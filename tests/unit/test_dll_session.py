"""Tests for ``data_downloader.dll.session`` — DLL singleton (task #21).

Verifica que ``get_dll`` mantém uma única instância process-global (Q08-E:
ProfitDLL Classic não tolera init→finalize→init no mesmo processo), que
``shutdown_dll`` finaliza, e que após shutdown um novo ``get_dll`` cria
uma nova instância.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

import data_downloader.dll.session as session_mod

# Credenciais fake de teste — montadas via dict para não casar com o
# pre-commit hook no-dotenv (padrão `password=...`). Não são secrets reais.
_FAKE_CREDS = {"key": "k", "user": "u", "password": "p"}


class _FakeProfitDLL:
    """Fake mínimo de ``ProfitDLL`` para os testes de singleton."""

    instances: ClassVar[list[_FakeProfitDLL]] = []

    def __init__(self) -> None:
        self.init_calls = 0
        self.finalize_calls = 0
        self.init_kwargs: dict[str, object] = {}
        _FakeProfitDLL.instances.append(self)

    def initialize_market_only(self, **kwargs: object) -> None:
        self.init_calls += 1
        self.init_kwargs = kwargs

    def finalize(self) -> None:
        self.finalize_calls += 1


@pytest.fixture(autouse=True)
def _reset_session(monkeypatch: pytest.MonkeyPatch):
    """Garante estado limpo do módulo session entre testes."""
    # Reset estado global do módulo.
    monkeypatch.setattr(session_mod, "_DLL_INSTANCE", None, raising=False)
    monkeypatch.setattr(session_mod, "_DLL_INIT_KWARGS", {}, raising=False)
    monkeypatch.setattr(session_mod, "_ATEXIT_REGISTERED", True, raising=False)  # evita atexit real
    # v1.3.0 Wave 2A: reset observer state.
    monkeypatch.setattr(session_mod, "_OBSERVERS", [], raising=False)
    monkeypatch.setattr(session_mod, "_DLL_STATE", "idle", raising=False)
    monkeypatch.setattr(session_mod, "_DLL_VERSION", "—", raising=False)
    _FakeProfitDLL.instances.clear()
    # Patch ProfitDLL importado dentro de get_dll.
    monkeypatch.setattr("data_downloader.dll.wrapper.ProfitDLL", _FakeProfitDLL)
    yield
    # Cleanup defensivo.
    session_mod._DLL_INSTANCE = None
    session_mod._DLL_INIT_KWARGS = {}
    session_mod._OBSERVERS = []
    session_mod._DLL_STATE = "idle"
    session_mod._DLL_VERSION = "—"


def test_get_dll_returns_same_instance() -> None:
    a = session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    b = session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    assert a is b
    # Init chamado UMA vez só (singleton — não re-inicializa).
    assert a.init_calls == 1
    assert len(_FakeProfitDLL.instances) == 1


def test_get_dll_passes_init_kwargs() -> None:
    dll = session_mod.get_dll(market_only=True, **_FAKE_CREDS, minimal_handshake=True)
    assert dll.init_kwargs == {
        "key": "k",
        "user": "u",
        "password": "p",
        "minimal_handshake": True,
    }


def test_has_active_dll_tracks_lifecycle() -> None:
    assert session_mod.has_active_dll() is False
    session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    assert session_mod.has_active_dll() is True
    session_mod.shutdown_dll()
    assert session_mod.has_active_dll() is False


def test_shutdown_dll_finalizes() -> None:
    dll = session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    session_mod.shutdown_dll()
    assert dll.finalize_calls == 1
    # Idempotente — segunda chamada não re-finaliza.
    session_mod.shutdown_dll()
    assert dll.finalize_calls == 1


def test_get_dll_after_shutdown_creates_new_instance() -> None:
    a = session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    session_mod.shutdown_dll()
    b = session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    assert a is not b
    assert len(_FakeProfitDLL.instances) == 2


def test_get_dll_failed_init_not_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingDLL(_FakeProfitDLL):
        def initialize_market_only(self, **kwargs: object) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr("data_downloader.dll.wrapper.ProfitDLL", _FailingDLL)
    with pytest.raises(RuntimeError, match="boom"):
        session_mod.get_dll(market_only=True, **_FAKE_CREDS)
    # Instância NÃO foi guardada — próxima tentativa começa do zero.
    assert session_mod.has_active_dll() is False


def test_get_dll_rejects_non_market_only() -> None:
    with pytest.raises(NotImplementedError):
        session_mod.get_dll(market_only=False)


# --- fix #21b: resolve_dll_init_mode + mode mismatch warning ----------------


def test_resolve_dll_init_mode_default_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", raising=False)
    assert session_mod.resolve_dll_init_mode() == {"minimal_handshake": False}


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", " yes "])
def test_resolve_dll_init_mode_truthy(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", raw)
    assert session_mod.resolve_dll_init_mode() == {"minimal_handshake": True}


@pytest.mark.parametrize("raw", ["0", "false", "no", "", "off", "garbage"])
def test_resolve_dll_init_mode_falsy(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", raw)
    assert session_mod.resolve_dll_init_mode() == {"minimal_handshake": False}


def test_get_dll_same_mode_no_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        session_mod.log,
        "warning",
        lambda event, **kw: warnings.append((event, kw)),
    )
    session_mod.get_dll(market_only=True, **_FAKE_CREDS, minimal_handshake=False)
    session_mod.get_dll(market_only=True, **_FAKE_CREDS, minimal_handshake=False)
    assert not any(ev == "dll.session.mode_mismatch" for ev, _ in warnings)


def test_get_dll_mode_mismatch_warns_and_reuses(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        session_mod.log,
        "warning",
        lambda event, **kw: warnings.append((event, kw)),
    )
    a = session_mod.get_dll(market_only=True, **_FAKE_CREDS, minimal_handshake=False)
    # 2ª chamada pede um modo DIFERENTE — não re-inicializa, mas avisa.
    b = session_mod.get_dll(market_only=True, **_FAKE_CREDS, minimal_handshake=True)
    assert a is b
    assert a.init_calls == 1  # NÃO re-inicializou
    mismatch = [kw for ev, kw in warnings if ev == "dll.session.mode_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0]["requested"] == {"minimal_handshake": True}
    assert mismatch[0]["active"] == {"minimal_handshake": False}


def test_get_dll_stores_init_kwargs() -> None:
    session_mod.get_dll(market_only=True, **_FAKE_CREDS, minimal_handshake=True)
    assert session_mod._DLL_INIT_KWARGS == {
        "key": "k",
        "user": "u",
        "password": "p",
        "minimal_handshake": True,
    }
    session_mod.shutdown_dll()
    assert session_mod._DLL_INIT_KWARGS == {}


# =====================================================================
# v1.3.0 Wave 2A — Observer pattern + lifecycle states
# =====================================================================


def test_register_and_unregister_observer() -> None:
    """Observer registrado recebe transições; unregister cessa entrega."""
    events: list[tuple[str, str]] = []

    def _cb(state: str, version: str) -> None:
        events.append((state, version))

    session_mod.register_state_observer(_cb)
    session_mod._set_state("connecting", "")
    session_mod._set_state("connected", "1.2.3")

    assert ("connecting", "—") in events
    assert ("connected", "1.2.3") in events

    session_mod.unregister_state_observer(_cb)
    events.clear()
    session_mod._set_state("idle", "")
    assert events == []


def test_register_observer_idempotent() -> None:
    """Registrar a MESMA referência 2x não duplica entregas."""
    events: list[tuple[str, str]] = []

    def _cb(state: str, version: str) -> None:
        events.append((state, version))

    session_mod.register_state_observer(_cb)
    session_mod.register_state_observer(_cb)  # noop
    session_mod._set_state("connecting", "")
    assert events == [("connecting", "—")]


def test_unregister_unknown_observer_is_noop() -> None:
    """Remover callback não registrado não levanta."""

    def _cb(state: str, version: str) -> None:  # pragma: no cover
        pass

    # Sem registro prévio — deve ser no-op.
    session_mod.unregister_state_observer(_cb)


def test_set_state_calls_all_observers() -> None:
    """``_set_state`` chama TODOS os observers em ordem registrada."""
    events_a: list[str] = []
    events_b: list[str] = []
    events_c: list[str] = []

    session_mod.register_state_observer(lambda s, v: events_a.append(s))
    session_mod.register_state_observer(lambda s, v: events_b.append(s))
    session_mod.register_state_observer(lambda s, v: events_c.append(s))

    session_mod._set_state("downloading", "WDOFUT")

    assert events_a == ["downloading"]
    assert events_b == ["downloading"]
    assert events_c == ["downloading"]


def test_observer_exception_does_not_break_others() -> None:
    """Um observer que levanta NÃO interrompe os outros."""
    events: list[str] = []

    def _bad(state: str, version: str) -> None:
        raise RuntimeError("boom")

    def _good(state: str, version: str) -> None:
        events.append(state)

    session_mod.register_state_observer(_bad)
    session_mod.register_state_observer(_good)
    # Não deve levantar.
    session_mod._set_state("connecting", "")
    assert events == ["connecting"]


def test_current_state_reflects_transitions() -> None:
    """``current_state`` retorna o snapshot atual ``(state, version)``."""
    assert session_mod.current_state() == ("idle", "—")
    session_mod._set_state("connecting", "")
    assert session_mod.current_state()[0] == "connecting"
    session_mod._set_state("connected", "4.0.0.34")
    assert session_mod.current_state() == ("connected", "4.0.0.34")


def test_get_dll_emits_connecting_then_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle: ``get_dll`` emite ``connecting`` → ``connected``."""
    events: list[tuple[str, str]] = []

    session_mod.register_state_observer(lambda s, v: events.append((s, v)))

    # FakeDLL sem ``dll_version`` → version = "—".
    session_mod.get_dll(market_only=True, **_FAKE_CREDS)

    states = [e[0] for e in events]
    assert "connecting" in states
    assert "connected" in states
    # Connecting vem antes de connected.
    assert states.index("connecting") < states.index("connected")


def test_get_dll_emits_error_on_init_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Init falhou → emite ``error`` (não ``connected``)."""

    class _FailingDLL(_FakeProfitDLL):
        def initialize_market_only(self, **kwargs: object) -> None:
            raise RuntimeError("init boom")

    monkeypatch.setattr("data_downloader.dll.wrapper.ProfitDLL", _FailingDLL)

    events: list[str] = []
    session_mod.register_state_observer(lambda s, v: events.append(s))

    with pytest.raises(RuntimeError, match="init boom"):
        session_mod.get_dll(market_only=True, **_FAKE_CREDS)

    assert "connecting" in events
    assert "error" in events
    assert "connected" not in events


def test_shutdown_emits_idle() -> None:
    """``shutdown_dll`` emite ``idle`` no final."""
    session_mod.get_dll(market_only=True, **_FAKE_CREDS)

    events: list[str] = []
    session_mod.register_state_observer(lambda s, v: events.append(s))

    session_mod.shutdown_dll()
    assert "idle" in events


def test_set_downloading_helper_sets_state() -> None:
    """``set_downloading(symbol)`` emite estado ``downloading`` com symbol como version."""
    events: list[tuple[str, str]] = []
    session_mod.register_state_observer(lambda s, v: events.append((s, v)))

    session_mod.set_downloading("WDOFUT")
    assert ("downloading", "WDOFUT") in events
    state, version = session_mod.current_state()
    assert state == "downloading"
    assert version == "WDOFUT"


def test_set_state_thread_safe() -> None:
    """Stress test — múltiplas threads chamando ``_set_state`` simultaneamente."""
    import threading as _threading

    events: list[tuple[str, str]] = []
    lock = _threading.Lock()

    def _cb(s: str, v: str) -> None:
        with lock:
            events.append((s, v))

    session_mod.register_state_observer(_cb)

    def _worker(state: str, n: int) -> None:
        for _ in range(n):
            session_mod._set_state(state, "v")

    threads = [
        _threading.Thread(target=_worker, args=("connecting", 50)),
        _threading.Thread(target=_worker, args=("downloading", 50)),
        _threading.Thread(target=_worker, args=("connected", 50)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # Cada thread emite 50 eventos → 150 totais (sem perdas).
    assert len(events) == 150
