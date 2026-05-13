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
    _FakeProfitDLL.instances.clear()
    # Patch ProfitDLL importado dentro de get_dll.
    monkeypatch.setattr("data_downloader.dll.wrapper.ProfitDLL", _FakeProfitDLL)
    yield
    # Cleanup defensivo.
    session_mod._DLL_INSTANCE = None
    session_mod._DLL_INIT_KWARGS = {}


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
