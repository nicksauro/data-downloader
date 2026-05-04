"""Unit tests — Story 2.9 / ADR-010 logging pipeline (configure_logging).

Owner: Dex (impl) | Authority: Aria (ADR-010 strategy).

Cobre AC1 (pipeline), AC2 (contextvars), AC3 (redaction básico — completo em
``test_logging_redaction.py``), AC4 (JSON canonical fields).
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest
import structlog

from data_downloader.observability.logging_config import (
    REDACTED_VALUE,
    bind_context,
    bound_context,
    clear_context,
    configure_logging,
    get_logger,
    redact_secrets,
    resolve_format_from_env,
    resolve_level_from_env,
    setup_logging,
    unbind_context,
)

# =====================================================================
# Helpers
# =====================================================================


def _capture_stderr(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """Substitui ``sys.stderr`` por um buffer in-memory e retorna-o.

    Necessário porque structlog usa ``PrintLoggerFactory(file=sys.stderr)``;
    re-configure de logging precisa apontar para o novo stderr.
    """
    buf = io.StringIO()
    monkeypatch.setattr("sys.stderr", buf)
    # Re-configure após patch — o factory captura sys.stderr no configure.
    return buf


# =====================================================================
# AC1 — Pipeline structlog formal
# =====================================================================


@pytest.mark.unit
def test_configure_logging_json_output_emits_parseable_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON output: cada log line é um objeto JSON parseable."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    log = get_logger("test_json")
    log.info("test.event", foo="bar", count=42)

    out = buf.getvalue().strip()
    assert out, "expected at least one log line"
    payload = json.loads(out.splitlines()[-1])
    assert payload["event"] == "test.event"
    assert payload["foo"] == "bar"
    assert payload["count"] == 42
    assert payload["level"] == "info"
    assert "timestamp" in payload
    assert "thread" in payload  # _add_thread_name processor


@pytest.mark.unit
def test_configure_logging_console_output_uses_console_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Console output: human-readable (não-JSON, com nome do evento)."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=False)
    log = get_logger("test_console")
    log.info("console.event", item="abc")

    out = buf.getvalue()
    assert "console.event" in out
    # Console renderer NÃO é JSON-parseável.
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.splitlines()[-1])


@pytest.mark.unit
def test_configure_logging_invalid_level_raises() -> None:
    """level inválido → ValueError."""
    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging(level="NOSUCHLEVEL", json_output=True)


@pytest.mark.unit
def test_configure_logging_filters_below_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Log abaixo do nível configurado é filtrado (não emitido)."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="WARNING", json_output=True)
    log = get_logger("test_filter")
    log.debug("filtered.debug")
    log.info("filtered.info")
    log.warning("emitted.warning")
    log.error("emitted.error")

    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    events = [json.loads(line)["event"] for line in lines]
    assert "filtered.debug" not in events
    assert "filtered.info" not in events
    assert "emitted.warning" in events
    assert "emitted.error" in events


@pytest.mark.unit
def test_configure_logging_includes_iso_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """timestamp é ISO 8601 UTC (com 'Z' suffix)."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    log = get_logger("test_ts")
    log.info("ts.event")

    payload = json.loads(buf.getvalue().splitlines()[-1])
    ts = payload["timestamp"]
    # ISO 8601 UTC: "2026-05-04T..." e termina em Z.
    assert ts.endswith("Z"), f"expected UTC timestamp ending in Z; got {ts}"
    assert "T" in ts


# =====================================================================
# AC1 — setup_logging alias
# =====================================================================


@pytest.mark.unit
def test_setup_logging_alias_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """setup_logging(format='json') === configure_logging(json_output=True)."""
    buf = _capture_stderr(monkeypatch)
    setup_logging("INFO", format="json")
    log = get_logger("test_alias")
    log.info("alias.event")
    payload = json.loads(buf.getvalue().splitlines()[-1])
    assert payload["event"] == "alias.event"


@pytest.mark.unit
def test_setup_logging_alias_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """setup_logging(format='console') === configure_logging(json_output=False)."""
    buf = _capture_stderr(monkeypatch)
    setup_logging("INFO", format="console")
    log = get_logger("test_alias_console")
    log.info("alias.console.event")
    out = buf.getvalue()
    assert "alias.console.event" in out


# =====================================================================
# AC2 — contextvars
# =====================================================================


@pytest.mark.unit
def test_bind_context_appears_in_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """contextvars bound via bind_context aparecem em todo log subsequente."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    clear_context()  # garante estado limpo
    bind_context(job_id="job-123", symbol="WDOJ26")
    try:
        log = get_logger("test_ctx")
        log.info("ctx.event", extra="value")

        payload = json.loads(buf.getvalue().splitlines()[-1])
        assert payload["job_id"] == "job-123"
        assert payload["symbol"] == "WDOJ26"
        assert payload["extra"] == "value"
    finally:
        clear_context()


@pytest.mark.unit
def test_clear_context_removes_contextvars(monkeypatch: pytest.MonkeyPatch) -> None:
    """clear_context remove TODOS os contextvars bound."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    bind_context(job_id="abc")
    clear_context()
    log = get_logger("test_clear")
    log.info("after.clear")

    payload = json.loads(buf.getvalue().splitlines()[-1])
    assert "job_id" not in payload


@pytest.mark.unit
def test_unbind_context_preserves_other_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """unbind_context remove apenas keys especificadas."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    clear_context()
    bind_context(job_id="J1", chunk_id="C1", symbol="S1")
    unbind_context("chunk_id")
    log = get_logger("test_unbind")
    log.info("partial.unbind")

    payload = json.loads(buf.getvalue().splitlines()[-1])
    assert payload["job_id"] == "J1"
    assert payload["symbol"] == "S1"
    assert "chunk_id" not in payload
    clear_context()


@pytest.mark.unit
def test_bound_context_manager_auto_unbind(monkeypatch: pytest.MonkeyPatch) -> None:
    """bound_context (CM) faz bind no enter e unbind no exit."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    clear_context()
    with bound_context(job_id="cm-job"):
        log = get_logger("test_cm")
        log.info("inside.cm")

    log.info("outside.cm")
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    inside = next(p for p in lines if p["event"] == "inside.cm")
    outside = next(p for p in lines if p["event"] == "outside.cm")
    assert inside["job_id"] == "cm-job"
    assert "job_id" not in outside


# =====================================================================
# AC3 — redaction (smoke; full coverage em test_logging_redaction.py)
# =====================================================================


@pytest.mark.unit
def test_redact_secrets_known_keys() -> None:
    """Keys conhecidas são redactadas (smoke)."""
    payload: dict[str, Any] = {"user": "demo", "nl_password": "x", "api_key": "y", "token": "z"}
    result = redact_secrets(payload)
    assert result["user"] == "demo"
    assert result["nl_password"] == REDACTED_VALUE
    assert result["api_key"] == REDACTED_VALUE
    assert result["token"] == REDACTED_VALUE


@pytest.mark.unit
def test_redact_secrets_via_logger_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redaction processor integrado: log com secret é mascarado em JSON output."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True, redact=True)
    log = get_logger("test_redact_pipeline")
    fake_pwd = "leaked!"  # pragma: allowlist secret
    fake_keyval = "sk_live_xyz"  # pragma: allowlist secret
    fake_apikey = fake_keyval
    log.info("auth.event", user="demo", password=fake_pwd, api_key=fake_apikey)

    payload = json.loads(buf.getvalue().splitlines()[-1])
    assert payload["user"] == "demo"
    assert payload["password"] == REDACTED_VALUE
    assert payload["api_key"] == REDACTED_VALUE


@pytest.mark.unit
def test_redact_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``redact=False`` desabilita o processor (raro; útil em testes)."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True, redact=False)
    log = get_logger("test_no_redact")
    plain_value = "visible"  # pragma: allowlist secret
    log.info("plain.event", password=plain_value)

    payload = json.loads(buf.getvalue().splitlines()[-1])
    assert payload["password"] == "visible"  # pragma: allowlist secret


# =====================================================================
# AC4 — JSON canonical fields
# =====================================================================


@pytest.mark.unit
def test_json_canonical_fields_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON entry contém campos canônicos: timestamp, level, event, thread."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    bind_context(job_id="JOB-A", chunk_id="CHK-A", symbol="WDOJ26", exchange="F")
    log = get_logger("test_canonical")
    log.info("canonical.event", trades_count=1234)

    payload = json.loads(buf.getvalue().splitlines()[-1])
    expected_keys = {
        "timestamp",
        "level",
        "event",
        "thread",
        "job_id",
        "chunk_id",
        "symbol",
        "exchange",
        "trades_count",
    }
    missing = expected_keys - set(payload.keys())
    assert not missing, f"missing canonical keys: {missing}"
    clear_context()


@pytest.mark.unit
def test_json_handles_exception_with_dict_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    """exc_info=True produz ``exception`` field estruturado (dict_tracebacks)."""
    buf = _capture_stderr(monkeypatch)
    configure_logging(level="INFO", json_output=True)
    log = get_logger("test_exc")
    try:
        raise ValueError("boom")
    except ValueError:
        log.error("crash.event", exc_info=True)

    payload = json.loads(buf.getvalue().splitlines()[-1])
    assert payload["event"] == "crash.event"
    assert payload["level"] == "error"
    # dict_tracebacks renderiza ``exception`` como lista de dicts (frames).
    # Aceita ``exception`` ou ``exc_info`` (ambos são estruturados).
    assert "exception" in payload or "exc_info" in payload


# =====================================================================
# Env var helpers
# =====================================================================


@pytest.mark.unit
def test_resolve_level_from_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_DOWNLOADER_LOG_LEVEL", raising=False)
    assert resolve_level_from_env("INFO") == "INFO"


@pytest.mark.unit
def test_resolve_level_from_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DOWNLOADER_LOG_LEVEL", "debug")
    assert resolve_level_from_env("INFO") == "DEBUG"


@pytest.mark.unit
def test_resolve_format_from_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_DOWNLOADER_LOG_FORMAT", raising=False)
    assert resolve_format_from_env("json") == "json"
    assert resolve_format_from_env("console") == "console"


@pytest.mark.unit
def test_resolve_format_from_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DOWNLOADER_LOG_FORMAT", "console")
    assert resolve_format_from_env("json") == "console"


@pytest.mark.unit
def test_resolve_format_from_env_invalid_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var inválida → fallback ao default (best-effort)."""
    monkeypatch.setenv("DATA_DOWNLOADER_LOG_FORMAT", "garbage")
    assert resolve_format_from_env("json") == "json"


# =====================================================================
# Cleanup — reset structlog config no teardown global
# =====================================================================


@pytest.fixture(autouse=True)
def _reset_structlog_after_test() -> Any:
    """Reseta structlog para evitar leak entre testes."""
    yield
    structlog.reset_defaults()
    # Re-aplica config conservadora — outros tests não dependem do output.
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )
    # Limpa contextvars (defensivo).
    import contextlib as _contextlib

    with _contextlib.suppress(Exception):  # pragma: no cover defensive
        clear_context()
