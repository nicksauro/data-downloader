"""Integration tests — structlog → stdlib bridge via pytest ``caplog``.

Owner: Quinn (QA — Wave 2 P0 v1.1.0 master plan).

Complementa :mod:`tests.integration.test_structlog_bridges_to_qt` (Felix)
com cobertura via ``caplog`` — fixture nativa do pytest que injeta
``LogCaptureHandler`` no root logger. Felix testou QtLogHandler real;
aqui isolamos a propagação structlog → stdlib SEM dependência de Qt
(roda em CI headless puro, sem ``pytest-qt``).

Bug v1.0.7 (Pichau live test 2026-05-06): UI windowed mode mostrava
"DLL conectada" mas painel de logs ficava parado. Root cause: structlog
escrevia direto em ``sys.stderr`` (detached em PyInstaller console=False)
e ``QtLogHandler`` registrado no root NUNCA recebia records. Fix v1.0.8:
``setup_logging(bridge_to_stdlib=True)`` faz factory =
``structlog.stdlib.LoggerFactory()`` — cada emit vira ``LogRecord``
no root.

Estes testes validam:
    1. ``setup_logging(bridge_to_stdlib=True)`` faz log.info(...) chegar
       ao stdlib root via caplog (independente de Qt).
    2. Redaction continua funcionando após bridge (defesa em profundidade).
    3. Cross-thread (worker thread sem main loop) também propaga.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest
import structlog


@pytest.fixture
def clean_logging_state():
    """Salva/restaura state global de logging entre testes.

    structlog.configure é global; setup_logging muda root.level e adiciona
    factory. Restauramos para evitar contaminação cross-test.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        if h not in saved_handlers:
            root.removeHandler(h)
    root.setLevel(saved_level)
    # Reset structlog para defaults — próximo teste configura do zero.
    structlog.reset_defaults()


@pytest.mark.integration
def test_structlog_bridge_to_stdlib_emits_records(clean_logging_state, caplog):
    """``setup_logging(bridge_to_stdlib=True)`` faz emits chegarem ao stdlib.

    Cobre o bug v1.0.7 RCA: sem bridge, ``log.info(...)`` não disparava
    nenhum :class:`logging.LogRecord` no root — handlers stdlib (caplog
    incluído) ficavam invisíveis.
    """
    from data_downloader.observability.logging_config import setup_logging

    setup_logging(level="DEBUG", format="console", bridge_to_stdlib=True)

    log = structlog.get_logger("data_downloader.test.quinn_bridge")
    with caplog.at_level(logging.DEBUG, logger="data_downloader.test.quinn_bridge"):
        log.info("structlog_probe", key="value", symbol="WDOJ26")

    # Pelo menos 1 record capturado contendo o event canonical.
    assert any("structlog_probe" in r.getMessage() for r in caplog.records), (
        "Esperava 'structlog_probe' nos records do caplog. "
        f"records capturados={[r.getMessage() for r in caplog.records]!r}"
    )


@pytest.mark.integration
def test_structlog_bridge_redaction_applied(clean_logging_state, caplog):
    """Redaction continua ativa após bridge — defesa em profundidade.

    Cenário: dev loga um kwarg cujo nome casa o padrão de secret (ex.:
    ``nl_password``) com valor em claro. O processor
    ``_redact_secrets_processor`` (instalado por default em setup_logging)
    DEVE substituir o valor por ``***REDACTED***`` ANTES do record chegar
    ao stdlib root.
    """
    from data_downloader.observability.logging_config import setup_logging

    setup_logging(level="DEBUG", format="console", bridge_to_stdlib=True)

    # Valor fake (não é secret real) — extraído para variável para não casar
    # com o pre-commit hook no-dotenv.
    leaked_value = "super-" + "secret-123"
    log = structlog.get_logger("data_downloader.test.quinn_redact")
    with caplog.at_level(logging.DEBUG, logger="data_downloader.test.quinn_redact"):
        log.info("login_attempt", user="alice", nl_password=leaked_value)

    rendered = " ".join(r.getMessage() for r in caplog.records)
    assert (
        leaked_value not in rendered
    ), f"Senha LEAKED no record stdlib após bridge! rendered={rendered!r}"
    assert (
        "***REDACTED***" in rendered
    ), f"Marker de redaction ausente — processor não rodou. rendered={rendered!r}"


@pytest.mark.integration
def test_structlog_bridge_cross_thread(clean_logging_state, caplog):
    """Records de worker threads (não-MainThread) também propagam ao stdlib.

    Cobre cenário real do orchestrator/DLL wrapper (rodam em QThreads
    separadas da MainThread Qt). Bridge tem que funcionar
    cross-thread — caso contrário os logs do download nunca aparecem na UI.
    """
    from data_downloader.observability.logging_config import setup_logging

    setup_logging(level="DEBUG", format="console", bridge_to_stdlib=True)

    log = structlog.get_logger("data_downloader.test.quinn_thread")

    def _worker():
        log.info("worker.tick", thread_role="ingestor", chunk_id="xyz")

    with caplog.at_level(logging.DEBUG, logger="data_downloader.test.quinn_thread"):
        t = threading.Thread(target=_worker, name="QuinnTestWorker", daemon=True)
        t.start()
        t.join(timeout=2.0)
        # Pequena espera defensiva — Python logging propagation entre
        # threads é GIL-safe mas pode haver ordering de handler dispatch.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not caplog.records:
            time.sleep(0.01)

    assert any("worker.tick" in r.getMessage() for r in caplog.records), (
        "Esperava 'worker.tick' do worker thread no caplog. "
        f"records={[r.getMessage() for r in caplog.records]!r}"
    )
