"""tests/unit/test_mock_dll.py — Meta-test do :class:`MockProfitDLL`.

Story 2.10 / ADR-014. Garante que o mock:

- Reproduz lifecycle (init → wait_market_connected → finalize) idêntico
  ao :class:`data_downloader.dll.wrapper.ProfitDLL` real (Quinn).
- É determinístico (mesma seed → mesma sequência de quirks) — Quinn.
- Detecta violação INV-1 (callback chama DLL) automaticamente — Aria.
- Implementa proteção M15 (reinit pós-finalize → erro) — Nelo.
- Exporta superfície compatível com benchmarks legados (Q11-E callbacks
  contagem, NL_* errors injectáveis) — Nelo.
"""

from __future__ import annotations

import pytest

from data_downloader.testing.mock_dll import (
    NL_DISCONNECT,
    NL_OK,
    MockCall,
    MockProfitDLL,
)

# =====================================================================
# Lifecycle / surface — espelhar ProfitDLL.wrapper
# =====================================================================


@pytest.mark.unit
def test_mock_initialize_market_only_records_call_with_credentials_redacted() -> None:
    """``initialize_market_only`` registra call com key/password mascarados."""
    dll = MockProfitDLL(seed=1)
    dll.initialize_market_only("LICENSE-XYZ", "user@b3", "p@ssw0rd")
    assert dll.is_initialized
    init_calls = [c for c in dll.mock_calls if c.name == "initialize_market_only"]
    assert len(init_calls) == 1
    assert init_calls[0].kwargs == {
        "key_redacted": "***",
        "user": "user@b3",
        "password_redacted": "***",
    }
    dll.finalize()


@pytest.mark.unit
def test_mock_wait_market_connected_returns_true_within_timeout() -> None:
    """Connector loop emite (MARKET_DATA, MARKET_CONNECTED) — wait retorna True."""
    dll = MockProfitDLL(seed=1)
    dll.initialize_market_only("k", "u", "p")
    assert dll.wait_market_connected(timeout=5) is True
    dll.finalize()


@pytest.mark.unit
def test_mock_finalize_after_finalize_is_noop() -> None:
    """finalize() repetido não levanta — espelha defensividade do wrapper."""
    dll = MockProfitDLL(seed=1)
    dll.initialize_market_only("k", "u", "p")
    dll.finalize()
    # Segunda chamada não levanta.
    dll.finalize()


@pytest.mark.unit
def test_mock_reinit_after_finalize_raises_m15() -> None:
    """M15 / Q08-E: reinit pós-finalize é proibido."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    dll.finalize()
    with pytest.raises(RuntimeError, match=r"M15|Q08-E|não-idempotente"):
        dll.initialize_market_only("k", "u", "p")


@pytest.mark.unit
def test_mock_dll_version_property_returns_configured_value() -> None:
    """Property ``dll_version`` retorna valor configurado no construtor."""
    dll = MockProfitDLL(dll_version="4.0.0.34-mock")
    assert dll.dll_version == "4.0.0.34-mock"


@pytest.mark.unit
def test_mock_context_manager_finalizes_on_exit() -> None:
    """``with MockProfitDLL() as dll:`` finaliza automaticamente."""
    with MockProfitDLL() as dll:
        dll.initialize_market_only("k", "u", "p")
        assert dll.is_initialized
    # Após o with, finalize foi chamado.
    assert not dll.is_initialized


# =====================================================================
# Callback registration
# =====================================================================


@pytest.mark.unit
def test_mock_set_history_trade_callback_v2_requires_init() -> None:
    """Callback V2 sem init levanta NL_NOT_INITIALIZED-equivalente."""
    dll = MockProfitDLL()
    with pytest.raises(RuntimeError, match="NL_NOT_INITIALIZED"):
        dll.set_history_trade_callback_v2(lambda *a: None)


@pytest.mark.unit
def test_mock_set_progress_callback_requires_init() -> None:
    """Progress callback sem init levanta NL_NOT_INITIALIZED-equivalente."""
    dll = MockProfitDLL()
    with pytest.raises(RuntimeError, match="NL_NOT_INITIALIZED"):
        dll.set_progress_callback(lambda *a: None)


# =====================================================================
# get_history_trades — validação de args
# =====================================================================


@pytest.mark.unit
def test_mock_get_history_trades_rejects_invalid_exchange() -> None:
    """Bolsa != F/B → ValueError (R8/Q05-V replicado)."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    with pytest.raises(ValueError, match="exchange"):
        dll.get_history_trades("WDOJ26", "BMF", "01/03/2024 00:00:00", "01/03/2024 18:00:00")
    dll.finalize()


@pytest.mark.unit
def test_mock_get_history_trades_rejects_bad_date_format() -> None:
    """Formato data != 'DD/MM/YYYY HH:mm:SS' (19 chars) → ValueError."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    with pytest.raises(ValueError, match="DD/MM/YYYY"):
        dll.get_history_trades("WDOJ26", "F", "2024-03-01", "01/03/2024 18:00:00")
    dll.finalize()


@pytest.mark.unit
def test_mock_get_history_trades_returns_configured_nl_error() -> None:
    """``nl_error_on_history`` injecta erro retornado por get_history_trades."""
    dll = MockProfitDLL(nl_error_on_history=NL_DISCONNECT)
    dll.initialize_market_only("k", "u", "p")
    rc = dll.get_history_trades("WDOJ26", "F", "01/03/2024 00:00:00", "01/03/2024 18:00:00")
    assert rc == NL_DISCONNECT
    dll.finalize()


@pytest.mark.unit
def test_mock_get_history_trades_returns_nl_ok_by_default() -> None:
    """Default → NL_OK retornado mesmo sem callbacks registrados."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    rc = dll.get_history_trades("WDOJ26", "F", "01/03/2024 00:00:00", "01/03/2024 18:00:00")
    assert rc == NL_OK
    dll.finalize()


# =====================================================================
# Determinismo
# =====================================================================


@pytest.mark.unit
def test_mock_same_seed_yields_same_quirk_sequence() -> None:
    """Quirk Q02-E (reconnect 99%) é determinístico para mesma seed."""
    seq1: list[str] = []
    seq2: list[str] = []
    for seq in (seq1, seq2):
        dll = MockProfitDLL(seed=12345, reconnect_probability=0.5)
        dll.initialize_market_only("k", "u", "p")
        dll.wait_market_connected(timeout=2)
        dll.finalize()
        seq.append(",".join(c.name for c in dll.mock_calls))
    assert seq1 == seq2


# =====================================================================
# fire_trades — entrega determinística + INV-1
# =====================================================================


@pytest.mark.unit
def test_mock_fire_trades_delivers_in_order_to_history_callback() -> None:
    """``fire_trades`` chama callback uma vez por trade, em ordem."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    received: list[int] = []

    def cb(trade: dict, handle: int, flags: int) -> None:
        received.append(int(trade["trade_id"]))

    dll.set_history_trade_callback_v2(cb)
    trades = [{"symbol": "WDOJ26", "timestamp_ns": i, "trade_id": i} for i in range(5)]
    delivered = dll.fire_trades(trades)
    assert delivered == 5
    assert received == [0, 1, 2, 3, 4]
    dll.finalize()


@pytest.mark.unit
def test_mock_fire_trades_skips_when_no_callback_registered() -> None:
    """Sem callback registrado, fire_trades retorna 0 — não levanta."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    delivered = dll.fire_trades([{"symbol": "X", "timestamp_ns": 1, "trade_id": 1}])
    assert delivered == 0
    dll.finalize()


@pytest.mark.unit
def test_mock_inv1_violation_detected_when_callback_calls_dll() -> None:
    """Se callback chama dll.dll_version (qualquer método público), violation registrada."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")

    def evil_cb(trade: dict, handle: int, flags: int) -> None:
        # Callback hostil — chama de volta a superfície pública (viola INV-1).
        _ = dll.dll_version

    dll.set_history_trade_callback_v2(evil_cb)
    dll.fire_trades([{"symbol": "X", "timestamp_ns": 1, "trade_id": 1}])

    assert dll.callback_violations, "INV-1 violation deveria ter sido detectada"
    assert "dll_version" in dll.callback_violations[0]
    dll.finalize()


@pytest.mark.unit
def test_mock_no_inv1_violation_for_well_behaved_callback() -> None:
    """Callback bem-comportado (apenas append em lista local) → sem violation."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    sink: list[int] = []
    dll.set_history_trade_callback_v2(lambda t, h, f: sink.append(int(t["trade_id"])))
    dll.fire_trades([{"symbol": "X", "timestamp_ns": i, "trade_id": i} for i in range(3)])
    assert sink == [0, 1, 2]
    assert dll.callback_violations == []
    dll.finalize()


# =====================================================================
# Auditoria
# =====================================================================


@pytest.mark.unit
def test_mock_calls_records_surface_invocations_in_order() -> None:
    """mock_calls preserva ordem de invocações (FIFO)."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    dll.wait_market_connected(timeout=2)
    dll.set_history_trade_callback_v2(lambda *a: None)
    dll.set_progress_callback(lambda *a: None)
    dll.finalize()

    names = [c.name for c in dll.mock_calls]
    assert names[0] == "initialize_market_only"
    assert names[1] == "wait_market_connected"
    assert "set_history_trade_callback_v2" in names
    assert "set_progress_callback" in names
    assert names[-1] == "finalize"


@pytest.mark.unit
def test_mock_reset_audit_clears_only_audit_state() -> None:
    """reset_audit limpa mock_calls/violations sem desinicializar."""
    dll = MockProfitDLL()
    dll.initialize_market_only("k", "u", "p")
    assert dll.mock_calls
    dll.reset_audit()
    assert dll.mock_calls == []
    assert dll.is_initialized  # sem tocar lifecycle
    dll.finalize()


@pytest.mark.unit
def test_mock_call_dataclass_is_immutable() -> None:
    """:class:`MockCall` é frozen — não permite mutação acidental."""
    from dataclasses import FrozenInstanceError

    call = MockCall(name="x", args=(), kwargs={})
    with pytest.raises(FrozenInstanceError):
        call.name = "y"  # type: ignore[misc]


# =====================================================================
# Fidelidade ao contrato real (smoke check via attrs)
# =====================================================================


@pytest.mark.unit
def test_mock_surface_matches_real_wrapper() -> None:
    """Cada método público do mock existe e é callable.

    Auditoria de Nelo: drift entre mock e wrapper real é a forma mais
    insidiosa de bug — testes passam contra mock e quebram em smoke.
    Este teste impede que removamos um método sem refletir mudança no
    wrapper real (e vice-versa, via test simétrico em test_dll_wrapper).
    """
    expected_methods = {
        "initialize_market_only",
        "wait_market_connected",
        "set_history_trade_callback_v2",
        "set_progress_callback",
        "get_history_trades",
        "finalize",
    }
    expected_props = {"dll_version"}

    dll = MockProfitDLL()
    for m in expected_methods:
        attr = getattr(dll, m, None)
        assert callable(attr), f"método {m!r} ausente ou não-callable no MockProfitDLL"
    for p in expected_props:
        # property — apenas verificar que o acesso retorna algo (não levanta).
        getattr(MockProfitDLL, p)
