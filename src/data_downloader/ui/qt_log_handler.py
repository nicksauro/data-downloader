"""data_downloader.ui.qt_log_handler — Qt-aware logging handler (Story v1.0.7).

Owner: Felix (frontend-dev) | Pichau directive 2026-05-06.

Pichau live test v1.0.6 reportou: **"nem aparece que começou a baixar nos
logs do aplicativo"**. Root cause: ``data_downloader.exe`` é um build
PyInstaller windowed (``console=False`` em ``data_downloader.spec``) — o
``sys.stderr`` nesse modo é detached/None, então os eventos structlog
(que vão para stderr via ``DynamicStreamLogger``) caem no void. Usuário
abre o app, clica BAIXAR e não vê nenhum sinal de atividade até o
download terminar (ou até a barra de progresso atualizar — quando ela
funciona).

Este módulo provê um :class:`QtLogHandler` que:

1. É um :class:`logging.Handler` registrado no logger root via
   :func:`install_qt_log_handler`.
2. Captura registros via :meth:`logging.Handler.emit`.
3. Emite um sinal Qt :attr:`QtLogBridge.message_logged(str)` carregando
   uma linha formatada (``[HH:MM:SS] LEVEL event=...``) que widgets UI
   (e.g. :class:`ProgressCard._log_view`) podem consumir via
   ``Qt.QueuedConnection`` (cross-thread safe — emit pode vir de qualquer
   worker thread).

LEIS RESPEITADAS:

- **R21** (hot path): handler é registrado UMA vez no boot do app
  (``ui/app.py::main``). Cada emit faz format + signal emit (cool path —
  loggers structlog em data_downloader são chamados per-chunk / per-job,
  NUNCA per-trade).
- **Cross-thread safe**: handler instances live no MainThread mas
  ``logging.Handler.emit`` pode ser chamado de qualquer worker. O
  ``Signal`` emit é thread-safe (Qt marshalling). Consumer connect com
  ``Qt.QueuedConnection`` para drop em MainThread event loop.
- **Defesa em profundidade**: caso uma exception ocorra no formatter, o
  handler captura silenciosamente (``handleError`` default). Logging
  NUNCA pode derrubar o app.

Exemplo de uso (em ``ui/app.py``)::

    from data_downloader.ui.qt_log_handler import install_qt_log_handler

    bridge = install_qt_log_handler(level="INFO")
    # Mais tarde, quando ProgressCard for criada:
    bridge.message_logged.connect(progress_card.append_log_line, Qt.QueuedConnection)
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    pass

__all__ = [
    "QtLogBridge",
    "QtLogHandler",
    "install_qt_log_handler",
]


class QtLogBridge(QObject):
    """QObject que carrega o sinal :attr:`message_logged`.

    Necessário separar o ``QObject`` (que detém o sinal) do
    ``logging.Handler`` porque ``logging.Handler.__init__`` faz coisas
    incompatíveis com herança múltipla a partir de ``QObject`` (em
    PySide6 algumas plataformas — defensive: keep separate).
    """

    #: Emitido a cada record formatado. Payload é a linha humana pronta.
    message_logged = Signal(str)


class QtLogHandler(logging.Handler):
    """Handler stdlib que emite cada record via :class:`QtLogBridge`.

    Format adotado: ``[HH:MM:SS] LEVEL event_name key=value key=value``.
    Para records vindos do structlog (que injeta ``event`` e
    contextvars), o ``event`` é extraído via ``record.msg`` que já
    contém a linha JSON renderizada — para evitar parsing JSON pesado
    aqui, usamos o ``record.getMessage()`` direto.
    """

    def __init__(self, bridge: QtLogBridge, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            level = record.levelname
            msg = record.getMessage()
            # Trunca mensagens muito longas (structlog JSON pode ser grande)
            # — UI não precisa de payload completo, só sinal de atividade.
            if len(msg) > 200:
                msg = msg[:200] + "..."
            line = f"[{ts}] {level} {msg}"
            self._bridge.message_logged.emit(line)
        except Exception:
            # ``handleError`` default: reraise apenas se ``logging.raiseExceptions``
            # estiver True E o stream ainda estiver disponível. Best-effort.
            with contextlib.suppress(Exception):
                self.handleError(record)


def install_qt_log_handler(level: str = "INFO") -> QtLogBridge:
    """Registra o :class:`QtLogHandler` no logger root.

    Idempotente — múltiplas chamadas reusam a bridge global (evita
    duplicação de logs caso ``main()`` seja chamada mais de uma vez em
    tests ou re-launch).

    Args:
        level: Nível mínimo (case-insensitive). ``"DEBUG"`` mostra TUDO.

    Returns:
        :class:`QtLogBridge` — caller conecta widgets ao
        ``message_logged`` via ``Qt.QueuedConnection`` (cross-thread).
    """
    root = logging.getLogger()
    level_int = getattr(logging, level.upper(), logging.INFO)
    if not isinstance(level_int, int):
        level_int = logging.INFO

    # Reuse bridge se já instalada (idempotente).
    for existing in root.handlers:
        if isinstance(existing, QtLogHandler):
            return existing._bridge

    bridge = QtLogBridge()
    handler = QtLogHandler(bridge, level=level_int)
    # Garante que o root logger não filtra: stdlib root default = WARNING.
    if root.level > level_int or root.level == 0:
        root.setLevel(level_int)
    root.addHandler(handler)
    return bridge
