"""Integration tests — structlog → stdlib bridge for UI windowed mode (v1.0.8).

Owner: Felix (frontend-dev) | Pichau live test bug 2026-05-06.

Pichau live test v1.0.7 reportou: status bar mostra "DLL: conectada (?)"
mas o painel de logs do app fica eternamente parado em apenas duas linhas:

    [22:54:56] Inicializando ProfitDLL...
    [22:54:56] INFO ui.progress msg=INF_STARTING_DLL done=0 total=-1 trades=0

Nenhum evento posterior (``download.start``, ``dll.subscribe_ticker``,
``orchestrator.chunk_start``, ``chunk_complete``, ``download.complete``)
chega à UI. Em CLI mode os mesmos eventos aparecem normalmente em stdout.

Root cause: em UI windowed mode (``console=False`` no PyInstaller spec),
``sys.stderr`` é detached. Antes da v1.0.8, o ``setup_logging`` configurava
structlog para escrever direto via ``DynamicStreamLoggerFactory`` em
``sys.stderr`` — ou seja, no void. O :class:`QtLogHandler` registrado no
``logging`` stdlib root nunca recebia esses records, porque structlog
NÃO propagava para stdlib.

Fix v1.0.8: ``setup_logging(bridge_to_stdlib=True)`` (chamado em
``ui/app.py::main``) faz ``logger_factory=structlog.stdlib.LoggerFactory()``
— cada evento structlog vira ``logging.LogRecord`` no logger stdlib
nomeado; propagação até o root entrega ao :class:`QtLogHandler`.

Estes testes validam:

1. Após ``setup_logging(bridge_to_stdlib=True)``, um ``structlog.get_logger``
   emite records que o root logger stdlib captura.
2. Records de worker threads (não-MainThread) também alcançam o
   :class:`QtLogHandler` — cobrindo o caso real do orchestrator/DLL
   wrapper que rodam em QThreads separadas.
3. O modo CLI (``bridge_to_stdlib=False``) NÃO regrede — ainda escreve
   via factory dinâmica, sem poluir o root logger com handlers extras.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import pytest
import structlog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def clean_root_logger():
    """Salva/restaura handlers e level do root logger entre testes.

    Previne contaminação cross-test quando ``setup_logging`` muda level
    do root ou ``install_qt_log_handler`` adiciona handlers.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    # Restore.
    for h in list(root.handlers):
        if h not in saved_handlers:
            root.removeHandler(h)
    root.setLevel(saved_level)


@pytest.mark.integration
def test_setup_logging_ui_mode_bridges_structlog_to_stdlib(clean_root_logger):
    """structlog.get_logger emits são capturados pelo logging stdlib root.

    Bug v1.0.7 root cause: sem bridge, ``log = structlog.get_logger(...)``
    seguido de ``log.info(...)`` não disparava nenhum
    :class:`logging.LogRecord` — handlers stdlib (ex.: QtLogHandler) ficavam
    invisíveis ao stream de eventos do orchestrator/DLL wrapper.
    """
    from data_downloader.observability.logging_config import setup_logging

    setup_logging(level="INFO", format="console", bridge_to_stdlib=True)

    captured: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _CaptureHandler(level=logging.INFO)
    clean_root_logger.addHandler(handler)

    log = structlog.get_logger("data_downloader.test.bridge")
    log.info("download.start", symbol="WDOJ26", exchange="F")

    # Sanity: pelo menos um record com a string renderizada.
    assert captured, (
        "Esperava pelo menos 1 LogRecord no root stdlib após log.info(...) — "
        "structlog → stdlib bridge não está ativo."
    )
    rendered = " ".join(record.getMessage() for record in captured)
    assert (
        "download.start" in rendered
    ), f"Esperava 'download.start' na mensagem renderizada; got={rendered!r}"
    assert "WDOJ26" in rendered, f"Esperava 'WDOJ26' na mensagem renderizada; got={rendered!r}"


@pytest.mark.integration
def test_qt_log_handler_receives_structlog_events_from_worker_thread(
    clean_root_logger,
    qtbot,
):
    """Records vindos de worker threads (download/orchestrator) chegam à UI.

    Reproduz o cenário Pichau: o worker QThread do DownloadAdapter emite
    ``log.info("download.start", ...)`` mas a UI não vê nada. Validamos
    que após o fix v1.0.8 (bridge_to_stdlib + QtLogHandler), o sinal
    ``message_logged`` é disparado para events vindos de qualquer thread.

    Nota: usa ``qtbot`` (de ``pytest-qt``) para garantir que existe uma
    ``QApplication`` ativa — necessário para que o ``Signal`` da
    :class:`QtLogBridge` entregue ao slot conectado em modo
    ``Qt.AutoConnection`` (que decide direct vs queued baseado em thread
    affinity dos QObjects). Sem ``QApplication`` o emit fica enfileirado
    sem dispatcher.
    """
    from PySide6.QtCore import Qt

    from data_downloader.observability.logging_config import setup_logging
    from data_downloader.ui.qt_log_handler import install_qt_log_handler

    setup_logging(level="INFO", format="console", bridge_to_stdlib=True)
    bridge = install_qt_log_handler(level="INFO")

    captured_lines: list[str] = []
    # DirectConnection: bridge.message_logged é emitido sincronamente do
    # QtLogHandler.emit (que roda na thread que originou o log record).
    # Para test synchronous, força DirectConnection — append em list é
    # GIL-safe.
    bridge.message_logged.connect(
        captured_lines.append,
        Qt.ConnectionType.DirectConnection,
    )

    log = structlog.get_logger("data_downloader.test.worker_bridge")

    def _worker_emits():
        log.info("dll.subscribe_ticker", symbol="WDOJ26", thread="WorkerThread")
        log.info("orchestrator.chunk_start", chunk_id="abc", total=10)

    worker = threading.Thread(target=_worker_emits, daemon=True, name="WorkerThread")
    worker.start()
    worker.join(timeout=2.0)

    # Racing entre worker emit + Python list append (GIL-safe). Pequena
    # espera defensiva.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and len(captured_lines) < 2:
        time.sleep(0.01)

    assert any("dll.subscribe_ticker" in line for line in captured_lines), (
        f"Esperava captura de 'dll.subscribe_ticker' do worker thread; " f"got={captured_lines!r}"
    )
    assert any("orchestrator.chunk_start" in line for line in captured_lines), (
        f"Esperava captura de 'orchestrator.chunk_start' do worker thread; "
        f"got={captured_lines!r}"
    )


@pytest.mark.integration
def test_setup_logging_cli_mode_does_not_install_stdlib_factory(clean_root_logger):
    """CLI mode (bridge_to_stdlib=False) NÃO regrede.

    Garante que o caminho CLI continua usando ``DynamicStreamLoggerFactory``
    (escreve direto em sys.stderr) e NÃO produz LogRecord no root — assim
    suítes pytest com captura de stdout (CliRunner) seguem funcionando.
    """
    from data_downloader.observability.logging_config import (
        DynamicStreamLoggerFactory,
        setup_logging,
    )

    setup_logging(level="INFO", format="console", bridge_to_stdlib=False)

    # Inspect structlog config — factory deve ser DynamicStreamLoggerFactory.
    config = structlog.get_config()
    factory = config.get("logger_factory")
    assert isinstance(
        factory, DynamicStreamLoggerFactory
    ), f"Esperava DynamicStreamLoggerFactory em CLI mode; got={type(factory)!r}"


@pytest.mark.integration
def test_bridge_mode_sets_root_logger_level(clean_root_logger):
    """bridge_to_stdlib=True garante root.level <= INFO.

    Defesa em profundidade: sem isso, root.level=WARNING (default stdlib)
    filtra INFO records antes de chegarem ao QtLogHandler.
    """
    from data_downloader.observability.logging_config import setup_logging

    # Reset root para WARNING (default stdlib).
    clean_root_logger.setLevel(logging.WARNING)

    setup_logging(level="INFO", format="console", bridge_to_stdlib=True)

    assert clean_root_logger.level <= logging.INFO, (
        f"Esperava root.level <= INFO após setup_logging(bridge_to_stdlib=True); "
        f"got level={clean_root_logger.level}"
    )
