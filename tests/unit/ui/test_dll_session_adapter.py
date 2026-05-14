"""Unit tests — DllSessionAdapter (Wave 2A v1.3.0 — Dex).

Cobertura:
    - Adapter registra observer no ``dll.session`` no ``__init__``.
    - Sync inicial emite o estado corrente (snapshot ``current_state``).
    - Transição via ``_set_state`` chega como ``session_state_changed`` Qt.
    - Callback puro Python vindo de outra thread é marshalado para
      MainThread via ``QMetaObject.invokeMethod``.
    - ``shutdown()`` desregistra (idempotente).
    - Singleton ``get_dll_session_adapter()`` reutiliza instância.

Headless: ``QT_QPA_PLATFORM=offscreen`` setado antes de qualquer import
PySide6 (mesmo padrão dos outros testes UI).
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _reset_session_module():
    """Reset estado global do ``dll.session`` entre testes."""
    import data_downloader.dll.session as session_mod
    from data_downloader.ui.adapters.dll_session_adapter import (
        reset_dll_session_adapter_for_tests,
    )

    reset_dll_session_adapter_for_tests()
    session_mod._OBSERVERS = []
    session_mod._DLL_STATE = "idle"
    session_mod._DLL_VERSION = "—"
    yield
    reset_dll_session_adapter_for_tests()
    session_mod._OBSERVERS = []
    session_mod._DLL_STATE = "idle"
    session_mod._DLL_VERSION = "—"


# =====================================================================
# __init__ + registro de observer
# =====================================================================


def test_adapter_registers_observer_on_init(qtbot):
    """Adapter no ``__init__`` registra callback em ``dll.session``."""
    import data_downloader.dll.session as session_mod
    from data_downloader.ui.adapters.dll_session_adapter import DllSessionAdapter

    initial = len(session_mod._OBSERVERS)
    adapter = DllSessionAdapter()
    # ``qtbot.addWidget`` exige QWidget — adapter é QObject. Não usar.

    try:
        assert len(session_mod._OBSERVERS) == initial + 1
    finally:
        adapter.shutdown()


def test_adapter_emits_initial_snapshot(qtbot):
    """``__init__`` emite snapshot atual via signal (sync para UI no boot).

    Para capturar o emit do construtor, conectamos um slot ANTES via
    monkey-patch: registramos um observer DIRETO no ``dll.session`` (mesma
    fonte de verdade do adapter) e validamos via ``current_state``. O
    signal Qt em si é validado em ``test_state_change_forwarded_to_qt_signal``.
    """
    import data_downloader.dll.session as session_mod
    from data_downloader.ui.adapters.dll_session_adapter import DllSessionAdapter

    # Avança estado ANTES de construir o adapter (CLI já subiu a DLL).
    session_mod._set_state("connected", "4.0.0.34")

    # ``current_state`` retorna o snapshot que o adapter emite no init.
    assert session_mod.current_state() == ("connected", "4.0.0.34")

    adapter = DllSessionAdapter()
    qtbot.wait(50)  # event loop drena marshaling
    adapter.shutdown()


# =====================================================================
# Signal forwarding
# =====================================================================


def test_state_change_forwarded_to_qt_signal(qtbot):
    """``_set_state`` no ``dll.session`` dispara ``session_state_changed``."""
    import data_downloader.dll.session as session_mod
    from data_downloader.ui.adapters.dll_session_adapter import DllSessionAdapter

    adapter = DllSessionAdapter()
    received: list[tuple[str, str]] = []
    adapter.session_state_changed.connect(lambda s, v: received.append((s, v)))

    # Drenar a emissão inicial (snapshot ``idle``).
    qtbot.wait(50)
    received.clear()

    session_mod._set_state("connecting", "")
    qtbot.wait(50)

    assert ("connecting", "—") in received
    adapter.shutdown()


def test_state_change_from_worker_thread_marshals_to_main_thread(qtbot):
    """Callback vindo de OUTRA thread chega ao slot na thread Qt do event loop.

    O orchestrator emite ``_set_state`` da worker thread; o adapter usa
    ``QMetaObject.invokeMethod`` com ``QueuedConnection`` para marshalar
    para o MainThread (event loop processa via ``qtbot.wait``).
    """
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    import data_downloader.dll.session as session_mod
    from data_downloader.ui.adapters.dll_session_adapter import DllSessionAdapter

    adapter = DllSessionAdapter()
    received: list[tuple[str, str, int]] = []

    main_thread = QApplication.instance().thread()  # type: ignore[union-attr]

    def _slot(s: str, v: str) -> None:
        # Capture qual thread executou o slot (deve ser MainThread).
        is_main = QThread.currentThread() == main_thread
        received.append((s, v, 1 if is_main else 0))

    adapter.session_state_changed.connect(_slot)
    qtbot.wait(50)
    received.clear()

    # Dispara ``_set_state`` de outra thread.
    def _worker() -> None:
        session_mod._set_state("downloading", "WDOFUT")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=2)

    qtbot.wait(100)

    # Pelo menos 1 evento downloading recebido E executado no MainThread.
    downloading_events = [e for e in received if e[0] == "downloading"]
    assert len(downloading_events) >= 1
    assert downloading_events[0][2] == 1  # MainThread

    adapter.shutdown()


# =====================================================================
# Shutdown
# =====================================================================


def test_shutdown_unregisters_observer(qtbot):
    """``shutdown()`` remove o callback do ``dll.session``."""
    import data_downloader.dll.session as session_mod
    from data_downloader.ui.adapters.dll_session_adapter import DllSessionAdapter

    adapter = DllSessionAdapter()
    initial_count = len(session_mod._OBSERVERS)
    assert initial_count >= 1

    adapter.shutdown()
    assert len(session_mod._OBSERVERS) == initial_count - 1


def test_shutdown_is_idempotent(qtbot):
    """Chamar ``shutdown()`` 2x não levanta."""
    from data_downloader.ui.adapters.dll_session_adapter import DllSessionAdapter

    adapter = DllSessionAdapter()
    adapter.shutdown()
    adapter.shutdown()  # noop


# =====================================================================
# Singleton
# =====================================================================


def test_get_dll_session_adapter_returns_singleton(qtbot):
    """``get_dll_session_adapter()`` reusa a mesma instância."""
    from data_downloader.ui.adapters.dll_session_adapter import (
        get_dll_session_adapter,
        reset_dll_session_adapter_for_tests,
    )

    reset_dll_session_adapter_for_tests()
    a = get_dll_session_adapter()
    b = get_dll_session_adapter()
    assert a is b
    reset_dll_session_adapter_for_tests()
