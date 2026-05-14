"""data_downloader.ui.adapters.dll_session_adapter — Bridge Qt para dll.session.

Owner: Dex (impl Wave 2A v1.3.0) | Design: Aria (proposal #2 — single source
of truth) + Uma (5 estados visuais).

Wrappeia ``dll.session`` observer pattern (puro Python) em um ``QObject``
que emite ``Signal(str, str)`` (state, version). Permite que telas Qt
(MainWindow statusbar, DownloadScreen, etc.) reajam ao lifecycle real da
DLL sem importar ``dll.session`` diretamente nem fazer polling.

Thread-safety:
    ``register_state_observer`` aceita callable invocado SÍNCRONO na thread
    que provocou a transição — pode ser o orchestrator worker, atexit, ou
    o MainThread. Para emitir o ``Signal`` Qt na thread certa, o callback
    interno reposta via ``QMetaObject.invokeMethod`` com
    ``Qt.QueuedConnection`` (event loop do MainThread despacha) — mesma
    estratégia usada em ``downloader_adapter`` (Story 3.1 / B2 Wave 1).

5 estados (Uma — WIREFRAMES.md):
    - ``idle``         — pre-init / pós-shutdown
    - ``connecting``   — Initialize em curso
    - ``connected``    — DLL ativa
    - ``downloading``  — orchestrator rodando (set via ``set_downloading``)
    - ``reconnecting`` — state_monitor detectou MARKET_DATA != CONNECTED
    - ``error``        — init falhou / DLL caiu

Referências:
    - docs/qa/V1.3.0-PLAN.md (Wave 2A — Aria #2/#4)
    - src/data_downloader/dll/session.py (observer API)
    - docs/ux/QT_PATTERNS.md §2 (cross-thread signal pattern)
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, Signal, Slot

from data_downloader.dll.session import (
    current_state,
    register_state_observer,
    unregister_state_observer,
)

__all__ = ["DllSessionAdapter", "get_dll_session_adapter"]


class DllSessionAdapter(QObject):
    """Wrapper ``QObject`` que traduz ``dll.session`` observer → Qt signal.

    Vive no MainThread (parent default ``None``; pode ter parent Qt — não
    está em ``QThread`` separada porque o handler interno é leve e marshala
    o emit para o MainThread via ``QMetaObject.invokeMethod``).

    Lifecycle:
        - ``__init__`` registra ``_on_state_change`` no ``dll.session``.
        - ``shutdown()`` (explícito, via ``MainWindow.closeEvent`` ou
          quando o singleton é destruído) remove o callback. Sem o
          unregister, o observer continuaria no list após o ``QObject``
          ser destruído, e a 1ª transição pós-destruição tentaria invocar
          ``QMetaObject.invokeMethod`` sobre objeto deletado → segfault.

    Public signal:
        ``session_state_changed(state, version)`` — emitido no MainThread
        a cada transição. ``state`` ∈ {idle, connecting, connected,
        downloading, reconnecting, error}; ``version`` é string da versão
        DLL (ou ``"—"`` quando indisponível).
    """

    session_state_changed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registered = False
        register_state_observer(self._on_state_change)
        self._registered = True

        # Sync inicial: caso o estado já tenha avançado de ``idle`` antes
        # do adapter construir (ex.: CLI subiu o singleton antes do
        # MainWindow ser instanciado), emite o snapshot ATUAL agora.
        state, version = current_state()
        # ``self.session_state_changed.emit`` daqui roda no MainThread
        # (construtor é chamado no MainThread por convenção).
        self.session_state_changed.emit(state, version)

    # ------------------------------------------------------------------
    # Observer callback (pode rodar em qualquer thread)
    # ------------------------------------------------------------------

    def _on_state_change(self, state: str, version: str) -> None:
        """Callback registrado em ``dll.session``.

        Pode ser invocado em QUALQUER thread (orchestrator worker,
        Test Connection worker, atexit). Marshala para o MainThread via
        ``QMetaObject.invokeMethod`` em ``Qt.QueuedConnection`` — o slot
        ``_emit_qt`` então emite o ``Signal`` Qt no MainThread.
        """
        QMetaObject.invokeMethod(
            self,
            "_emit_qt",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, state),
            Q_ARG(str, version),
        )

    @Slot(str, str)
    def _emit_qt(self, state: str, version: str) -> None:
        """Slot invocado no MainThread pelo dispatcher Qt; emite o signal."""
        self.session_state_changed.emit(state, version)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Remove o callback do ``dll.session`` (idempotente).

        Chamado por ``MainWindow.closeEvent``. Sem isso, observer
        continuaria invocando ``QMetaObject.invokeMethod`` sobre objeto
        já destruído → segfault no atexit.
        """
        if self._registered:
            with contextlib.suppress(Exception):
                unregister_state_observer(self._on_state_change)
            self._registered = False

    def __del__(self) -> None:
        # Defensive: se ``shutdown`` não foi chamado, garante unregister.
        with contextlib.suppress(Exception):
            if getattr(self, "_registered", False):
                unregister_state_observer(self._on_state_change)


# =====================================================================
# Process-wide singleton
# =====================================================================
#
# Não há razão para 2 adapters competirem por observer slots — a UI inteira
# se conecta ao mesmo signal. Mantemos um singleton process-wide e o
# ``MainWindow`` cuida do shutdown no closeEvent.

_ADAPTER: DllSessionAdapter | None = None


def get_dll_session_adapter() -> DllSessionAdapter:
    """Retorna o singleton ``DllSessionAdapter`` (lazy-init).

    Cria na 1ª chamada (MainThread). Subsequentes devolvem a mesma
    instância — UI inteira conecta no mesmo ``session_state_changed``.
    """
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = DllSessionAdapter()
    return _ADAPTER


def reset_dll_session_adapter_for_tests() -> None:
    """Reset do singleton — APENAS para uso em tests (fixture cleanup).

    Pyobject ``_ADAPTER`` é destruído (``__del__`` chama unregister);
    próxima ``get_dll_session_adapter()`` cria novo.
    """
    global _ADAPTER
    if _ADAPTER is not None:
        _ADAPTER.shutdown()
        _ADAPTER = None
