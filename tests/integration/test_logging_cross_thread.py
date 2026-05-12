"""Integration tests — Story 2.9 / ADR-010 cross-thread contextvar propagation.

Owner: Dex (impl) | Authority: Aria (ADR-010 + ADR-005 thread model).

Cobre AC2.3 — cross-thread contextvars propagation:

- ``copy_context_to_thread`` propaga contextvars do main → worker thread.
- 2 jobs concorrentes (orchestrator-style) → cada thread tem seu próprio
  ``job_id`` em logs (sem cross-contamination).

Cross-process não testado (defer para Story 4.1 broker).
"""

from __future__ import annotations

import json
import logging
import threading
import warnings
from typing import Any

import pytest
import structlog

from data_downloader.observability.logging_config import (
    bind_context,
    clear_context,
    copy_context_to_thread,
    get_logger,
)

# =====================================================================
# Helpers
# =====================================================================


class _ListSink:
    """File-like sink que acumula linhas em uma lista thread-safe.

    Substituto de ``sys.stderr`` para captura de logs estruturados.
    """

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._lock = threading.Lock()

    def write(self, msg: str) -> int:
        if msg:
            with self._lock:
                self.lines.append(msg)
        return len(msg)

    def flush(self) -> None:
        pass


def _configure_with_sink() -> _ListSink:
    """Configura structlog para capturar em sink in-memory thread-safe."""
    sink = _ListSink()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sink),  # type: ignore[arg-type]
        cache_logger_on_first_use=False,  # importante p/ testes
    )
    return sink


def _parse_lines(sink: _ListSink) -> list[dict[str, Any]]:
    """Parsea cada linha capturada como JSON dict."""
    out: list[dict[str, Any]] = []
    for raw in sink.lines:
        line = raw.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # Multiple writes podem fragmentar; junta com a linha anterior
            # se possível.
            continue
    return out


# =====================================================================
# AC2.3 — Cross-thread propagation
# =====================================================================


@pytest.mark.integration
def test_copy_context_to_thread_propagates_contextvars() -> None:
    """contextvars bound no main thread aparecem em logs do worker thread."""
    sink = _configure_with_sink()
    clear_context()
    bind_context(job_id="parent-job", correlation_id="parent-job", symbol="WDOJ26")

    def worker(payload: str) -> None:
        log = get_logger("worker")
        log.info("worker.event", payload=payload)

    wrapped = copy_context_to_thread(worker)
    t = threading.Thread(target=wrapped, args=("hello",))
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive()

    events = _parse_lines(sink)
    worker_events = [e for e in events if e.get("event") == "worker.event"]
    assert worker_events, f"no worker.event captured; got {events}"
    payload = worker_events[0]
    assert payload["job_id"] == "parent-job"
    assert payload["correlation_id"] == "parent-job"
    assert payload["symbol"] == "WDOJ26"
    assert payload["payload"] == "hello"

    clear_context()


@pytest.mark.integration
def test_thread_without_propagation_does_not_inherit_contextvars() -> None:
    """Sanity check — sem ``copy_context_to_thread``, contextvars NÃO propagam."""
    sink = _configure_with_sink()
    clear_context()
    bind_context(job_id="parent-only")

    def worker() -> None:
        log = get_logger("worker_naive")
        log.info("naive.event")

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5.0)

    events = _parse_lines(sink)
    naive_events = [e for e in events if e.get("event") == "naive.event"]
    assert naive_events, "expected at least one naive.event"
    # SEM propagação, job_id NÃO aparece (default = ausente).
    assert "job_id" not in naive_events[0], (
        "Without copy_context_to_thread, contextvars MUST NOT propagate. "
        "Found job_id in worker thread — propagation leak suspected."
    )

    clear_context()


@pytest.mark.integration
def test_two_concurrent_jobs_isolated_contextvars() -> None:
    """2 jobs concorrentes: cada thread tem job_id distinto, sem contamination.

    Simula 2 OrchestratorThread executando jobs paralelos. Validação:
    todos os logs do thread A têm job_id="JOB-A", todos do thread B têm
    "JOB-B" — nenhum cross-contamination.
    """
    sink = _configure_with_sink()
    clear_context()

    barrier = threading.Barrier(2)
    n_logs_per_job = 20

    def make_job_worker(job_id: str) -> threading.Thread:
        def _do_work() -> None:
            # Cada thread bind seu próprio job_id (simula
            # orchestrator.run() que faz bind_context(job_id=...)).
            bind_context(job_id=job_id, symbol=f"SYM-{job_id}")
            try:
                barrier.wait(timeout=5.0)  # sincroniza para maximizar concorrência
                log = get_logger(f"job_{job_id}")
                for i in range(n_logs_per_job):
                    log.info("job.tick", iteration=i)
            finally:
                clear_context()

        t = threading.Thread(target=_do_work, name=f"worker-{job_id}")
        return t

    t_a = make_job_worker("JOB-A")
    t_b = make_job_worker("JOB-B")
    t_a.start()
    t_b.start()
    t_a.join(timeout=10.0)
    t_b.join(timeout=10.0)
    assert not t_a.is_alive()
    assert not t_b.is_alive()

    events = _parse_lines(sink)
    job_a_events = [e for e in events if e.get("job_id") == "JOB-A"]
    job_b_events = [e for e in events if e.get("job_id") == "JOB-B"]

    assert (
        len(job_a_events) == n_logs_per_job
    ), f"expected {n_logs_per_job} events for JOB-A, got {len(job_a_events)}"
    assert (
        len(job_b_events) == n_logs_per_job
    ), f"expected {n_logs_per_job} events for JOB-B, got {len(job_b_events)}"

    # Cross-contamination check: cada evento JOB-A tem symbol SYM-JOB-A.
    for ev in job_a_events:
        assert (
            ev["symbol"] == "SYM-JOB-A"
        ), f"JOB-A log has wrong symbol: {ev['symbol']}; cross-contamination"
    for ev in job_b_events:
        assert (
            ev["symbol"] == "SYM-JOB-B"
        ), f"JOB-B log has wrong symbol: {ev['symbol']}; cross-contamination"

    clear_context()


@pytest.mark.integration
def test_cross_thread_propagation_preserves_secret_redaction() -> None:
    """Bind com secret no main → worker logs também redactam (mesma pipeline)."""
    # Configura com redaction enabled (configure_logging completo).
    # Acessa o processor private via módulo (intencional para testar
    # exatamente a função usada em produção, não duplicar implementação).
    from data_downloader.observability import logging_config as _lc

    sink = _ListSink()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _lc._redact_secrets_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sink),  # type: ignore[arg-type]
        cache_logger_on_first_use=False,
    )
    clear_context()
    # Bind com secret — redaction deve mascarar mesmo no bind.
    fake_kval = "should-be-redacted"  # pragma: allowlist secret
    fake_api_key = fake_kval
    bind_context(job_id="J1", api_key=fake_api_key)

    def worker() -> None:
        log = get_logger("redact_worker")
        secret_value = "also-redacted"  # pragma: allowlist secret
        log.info("worker.with.secret", password=secret_value)

    wrapped = copy_context_to_thread(worker)
    t = threading.Thread(target=wrapped)
    t.start()
    t.join(timeout=5.0)

    events = _parse_lines(sink)
    secret_events = [e for e in events if e.get("event") == "worker.with.secret"]
    assert secret_events
    payload = secret_events[0]
    assert payload["job_id"] == "J1"
    # api_key (do bind) e password (do log call) ambos redactados.
    assert payload["api_key"] == "***REDACTED***"
    assert payload["password"] == "***REDACTED***"

    clear_context()


# =====================================================================
# Fix B-4 (Wave A 2026-05-11) — null-call surfaces a RuntimeWarning
# =====================================================================


@pytest.mark.integration
def test_copy_context_to_thread_no_arg_emits_runtime_warning() -> None:
    """copy_context_to_thread() (no arg) is a no-op — must surface a warning.

    Fix B-4 (Wave A): previously the null call was silent — adapters relying
    on it for contextvar propagation lost job_id/symbol/etc. without any
    log signal. We now emit a one-shot ``RuntimeWarning`` so the call site
    is visible.
    """
    # Reset the module-level "warned once" flag so the test is independent of
    # any prior call in the same process (other tests / pytest collection).
    from data_downloader.observability import logging_config as _lc

    _lc._COPY_CONTEXT_NULL_WARNED = False

    with pytest.warns(RuntimeWarning, match="no-op for contextvar restoration"):
        result = copy_context_to_thread()  # null call
        # Returned value is callable (no-op); calling it returns None.
        assert callable(result)
        assert result() is None


@pytest.mark.integration
def test_copy_context_to_thread_no_arg_warning_is_one_shot() -> None:
    """The null-call warning fires at most once per process (no spam)."""
    from data_downloader.observability import logging_config as _lc

    # Force "already warned" state — subsequent null calls must NOT re-warn.
    _lc._COPY_CONTEXT_NULL_WARNED = True

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        # If a RuntimeWarning fired, it would convert to an exception. The
        # call must succeed silently.
        result = copy_context_to_thread()
        assert callable(result)


# =====================================================================
# Cleanup
# =====================================================================


@pytest.fixture(autouse=True)
def _reset_structlog_after_test() -> Any:
    """Reset structlog config + contextvars."""
    yield
    structlog.reset_defaults()
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )
    import contextlib as _contextlib

    with _contextlib.suppress(Exception):  # pragma: no cover defensive
        clear_context()
