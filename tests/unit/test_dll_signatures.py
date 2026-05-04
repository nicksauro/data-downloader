"""tests/unit/test_dll_signatures.py — Story 1.7b-followup CRIT-2.

Cobertura de ``data_downloader.dll.wrapper.ProfitDLL._configure_dll_signatures``:

- Configura argtypes/restype para funções esperadas (TranslateTrade,
  SubscribeTicker, UnsubscribeTicker, GetAgentNameLength, GetAgentName,
  GetHistoryTrades, DLLInitializeMarketLogin, DLLFinalize, etc.).
- Tolera funções não exportadas (mock raising AttributeError em getattr) —
  pula com log warning, NÃO bloqueia init.
- Tolera erros ao setar argtypes/restype (TypeError ctypes) — pula.
- Chamado ANTES de SetEnabledLogToDebug em ``initialize_market_only`` —
  garantia de ordem (CRIT-2: argtypes ANTES de qualquer chamada à DLL).
- DLL não inicializada (``self._dll = None``) — early return sem raise.

Bug crítico corrigido (audit Nelo 2026-05-04 commit 29ad70d): sem argtypes,
ctypes assume c_int para todos args/return e desalinha stack stdcall em
x64 — TranslateTrade truncava handles c_size_t, SendOrder retornos c_int64
chegavam corrompidos, POINTER(struct) lia lixo. Pode ter sido causa raiz
da flakey de attempt 4 (smoke 2026-05-04).
"""

from __future__ import annotations

import sys
from ctypes import POINTER, c_int, c_int64, c_longlong, c_size_t, c_wchar_p
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import (
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    TConnectorTrade,
)
from data_downloader.dll.wrapper import ProfitDLL


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    """Isola ``_cb_refs`` entre testes (mesma pattern de test_dll_wrapper)."""
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


# =====================================================================
# Helpers
# =====================================================================


def _make_full_mock_dll() -> Any:
    """Mock DLL com TODAS as funções esperadas pelo configurador.

    MagicMock cria attributes automaticamente, então ``getattr`` nunca
    levanta AttributeError aqui. Para testar tolerância, ver
    ``_make_partial_mock_dll`` abaixo.
    """
    mock_dll = MagicMock(name="FullMockDLL")
    mock_dll.SetEnabledLogToDebug = MagicMock(return_value=0)
    mock_dll.DLLInitializeMarketLogin = MagicMock(return_value=0)
    mock_dll.DLLFinalize = MagicMock(return_value=0)
    mock_dll.GetDLLVersion = MagicMock(return_value="4.0.0.34")
    return mock_dll


# =====================================================================
# Direct test of _configure_dll_signatures
# =====================================================================


@pytest.mark.unit
def test_configure_signatures_early_return_when_dll_none(tmp_path: Path) -> None:
    """``self._dll is None`` → return sem raise (defensive guard)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll._dll is None
    # Não deve raise — apenas no-op.
    dll._configure_dll_signatures()


@pytest.mark.unit
def test_configure_signatures_sets_translate_trade_argtypes(tmp_path: Path) -> None:
    """``TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]``.

    CRÍTICO MED-4: sem isso handle c_size_t é truncado em x64.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    # MagicMock guarda atributos seteados — verificar que argtypes foi
    # atribuído ao TranslateTrade.
    assert mock_dll.TranslateTrade.argtypes == [c_size_t, POINTER(TConnectorTrade)]
    assert mock_dll.TranslateTrade.restype == c_int


@pytest.mark.unit
def test_configure_signatures_sets_subscribe_ticker(tmp_path: Path) -> None:
    """``SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; restype = c_int``."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    assert mock_dll.SubscribeTicker.argtypes == [c_wchar_p, c_wchar_p]
    assert mock_dll.SubscribeTicker.restype == c_int
    assert mock_dll.UnsubscribeTicker.argtypes == [c_wchar_p, c_wchar_p]
    assert mock_dll.UnsubscribeTicker.restype == c_int


@pytest.mark.unit
def test_configure_signatures_sets_get_agent_name(tmp_path: Path) -> None:
    """``GetAgentNameLength`` e ``GetAgentName`` configurados (CRIT-3 dependency)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    assert mock_dll.GetAgentNameLength.argtypes == [c_int, c_int]
    assert mock_dll.GetAgentNameLength.restype == c_int
    assert mock_dll.GetAgentName.argtypes == [c_int, c_int, c_wchar_p, c_int]
    assert mock_dll.GetAgentName.restype == c_int


@pytest.mark.unit
def test_configure_signatures_sets_get_history_trades(tmp_path: Path) -> None:
    """``GetHistoryTrades.argtypes = [4 x c_wchar_p]; restype = c_int``."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    assert mock_dll.GetHistoryTrades.argtypes == [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]
    assert mock_dll.GetHistoryTrades.restype == c_int


@pytest.mark.unit
def test_configure_signatures_sets_lifecycle_restypes(tmp_path: Path) -> None:
    """Lifecycle (DLLInitializeMarketLogin, DLLFinalize, Finalize, SetEnabledLogToDebug)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    # DLLInitializeMarketLogin: argtypes=None (não setamos — slots variam),
    # mas restype DEVE ser c_int (audit CRIT-2).
    assert mock_dll.DLLInitializeMarketLogin.restype == c_int
    # DLLFinalize / Finalize: argtypes=[] (sem args), restype=c_int.
    assert mock_dll.DLLFinalize.argtypes == []
    assert mock_dll.DLLFinalize.restype == c_int
    assert mock_dll.Finalize.argtypes == []
    assert mock_dll.Finalize.restype == c_int
    # SetEnabledLogToDebug: argtypes=[c_int], restype=c_int (HIGH-4 audit).
    assert mock_dll.SetEnabledLogToDebug.argtypes == [c_int]
    assert mock_dll.SetEnabledLogToDebug.restype == c_int


@pytest.mark.unit
def test_configure_signatures_sets_send_order_restypes(tmp_path: Path) -> None:
    """profit_dll.py:7-15 — SendBuyOrder / SendSellOrder restype c_longlong.

    CRÍTICO: ordem retorna c_longlong (8 bytes); sem restype, ctypes default
    é c_int (4 bytes) e o ID truncaria em 32 bits.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    assert mock_dll.SendBuyOrder.restype == c_longlong
    assert mock_dll.SendSellOrder.restype == c_longlong
    assert mock_dll.SendZeroPosition.restype == c_longlong
    # Market orders retornam c_int64 (mesma representação no Win64 — 8 bytes).
    assert mock_dll.SendMarketBuyOrder.restype == c_int64
    assert mock_dll.SendMarketSellOrder.restype == c_int64


@pytest.mark.unit
def test_configure_signatures_sets_price_depth_struct_pointers(tmp_path: Path) -> None:
    """SubscribePriceDepth + UnsubscribePriceDepth + GetPriceDepthSideCount.

    Validar que POINTER(TConnectorAssetIdentifier) é argtype canônico —
    sem isso a DLL recebe ponteiro desalinhado (corrupção de stack).
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    expected_arg = [POINTER(TConnectorAssetIdentifier)]
    assert mock_dll.SubscribePriceDepth.argtypes == expected_arg
    assert mock_dll.SubscribePriceDepth.restype == c_int
    assert mock_dll.UnsubscribePriceDepth.argtypes == expected_arg
    assert mock_dll.UnsubscribePriceDepth.restype == c_int
    # GetPriceDepthSideCount: POINTER(asset) + c_ubyte side.
    assert mock_dll.GetPriceDepthSideCount.argtypes[0] == POINTER(TConnectorAssetIdentifier)
    assert mock_dll.GetPriceDepthSideCount.restype == c_int


@pytest.mark.unit
def test_configure_signatures_sets_subaccount_count_struct_pointer(tmp_path: Path) -> None:
    """GetSubAccountCount usa POINTER(TConnectorAccountIdentifier)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = _make_full_mock_dll()
    dll._dll = mock_dll

    dll._configure_dll_signatures()

    assert mock_dll.GetSubAccountCount.argtypes == [POINTER(TConnectorAccountIdentifier)]
    assert mock_dll.GetSubAccountCount.restype == c_int


# =====================================================================
# Tolerância a funções não exportadas (Q-DRIFT)
# =====================================================================


class _PartialMockDLL:
    """DLL mock que levanta AttributeError em funções específicas.

    Usada para testar tolerância de ``_configure_dll_signatures`` quando
    a DLL real não exporta uma função (Q-DRIFT-09 confirma: GetDLLVersion
    pode estar ausente em versões reais).
    """

    def __init__(self, missing: set[str]) -> None:
        self._missing = missing
        # Cache de funções "exportadas" (MagicMock por nome — mesmo objeto
        # entre lookups para que setattr argtypes persista).
        self._funcs: dict[str, MagicMock] = {}

    def __getattr__(self, name: str) -> Any:
        # ``_missing`` e ``_funcs`` são acessados via __dict__ (não recursão).
        if name in self.__dict__.get("_missing", set()):
            raise AttributeError(f"function {name!r} not exported by mock DLL")
        funcs = self.__dict__.setdefault("_funcs", {})
        if name not in funcs:
            funcs[name] = MagicMock(name=f"DLLFunc<{name}>")
        return funcs[name]


@pytest.mark.unit
def test_configure_signatures_tolerates_missing_function(tmp_path: Path) -> None:
    """Função não exportada (AttributeError em getattr) → skip + log warning.

    Q-DRIFT-09: ``GetDLLVersion`` confirmado ausente em versões reais.
    Tolerância garante que init não bloqueia em DLLs antigas/drift.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    # Simula DLL sem GetDLLVersion (Q-DRIFT-09 confirmado smoke 2026-05-04).
    dll._dll = _PartialMockDLL(missing={"GetDLLVersion"})

    # NÃO deve raise — apenas log warning.
    dll._configure_dll_signatures()


@pytest.mark.unit
def test_configure_signatures_tolerates_multiple_missing_functions(tmp_path: Path) -> None:
    """Múltiplas funções ausentes — todas puladas; restantes configuradas."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    missing = {
        "GetDLLVersion",
        "SendStopBuyOrder",
        "SendStopSellOrder",
        "GetAgentNameByID",
        "GetAgentShortNameByID",
    }
    partial_mock = _PartialMockDLL(missing=missing)
    dll._dll = partial_mock

    dll._configure_dll_signatures()

    # Funções críticas (não na lista missing) DEVEM ter sido configuradas.
    assert partial_mock.TranslateTrade.argtypes == [c_size_t, POINTER(TConnectorTrade)]
    assert partial_mock.SubscribeTicker.argtypes == [c_wchar_p, c_wchar_p]
    assert partial_mock.GetHistoryTrades.argtypes == [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]


@pytest.mark.unit
def test_configure_signatures_emits_logger_warning_on_skip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Função pulada emite ``dll.signature_skipped`` warning."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    dll._dll = _PartialMockDLL(missing={"GetDLLVersion"})

    dll._configure_dll_signatures()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "dll.signature_skipped" in combined
    assert "GetDLLVersion" in combined


@pytest.mark.unit
def test_configure_signatures_emits_summary_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Após configuração, emite ``dll.signatures_configured`` com counts."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    dll._dll = _make_full_mock_dll()

    dll._configure_dll_signatures()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "dll.signatures_configured" in combined


# =====================================================================
# Integration with initialize_market_only — ordem garantida
# =====================================================================


@pytest.mark.unit
def test_initialize_market_only_calls_configure_signatures_before_set_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CRIT-2: ``_configure_dll_signatures`` chamado ANTES de qualquer chamada DLL.

    Ordem esperada em ``initialize_market_only`` (CRÍTICO):

    1. WinDLL(path)
    2. _configure_dll_signatures()  ← argtypes ANTES de tudo
    3. SetEnabledLogToDebug(0)      ← AC11
    4. DLLInitializeMarketLogin(...)

    Sem (2) antes de (3)+(4), ctypes assume c_int em todos args e desalinha
    o stack stdcall em x64 (audit CRIT-2 commit 29ad70d).
    """
    monkeypatch.setattr(sys, "platform", "win32")

    # Mock da DLL com TODAS as funções esperadas (MagicMock auto-cria).
    dll_instance = MagicMock(name="DLLInstance")
    dll_instance.SetEnabledLogToDebug = MagicMock(return_value=0)
    dll_instance.DLLInitializeMarketLogin = MagicMock(return_value=0)
    dll_instance.DLLFinalize = MagicMock(return_value=0)
    windll_mock = MagicMock(return_value=dll_instance)

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    # Spy em _configure_dll_signatures (wrap real method para preservar efeitos).
    original_configure = dll._configure_dll_signatures
    configure_spy = MagicMock(side_effect=original_configure)
    dll._configure_dll_signatures = configure_spy  # type: ignore[method-assign]

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS")

    # _configure_dll_signatures DEVE ter sido chamado uma vez.
    configure_spy.assert_called_once()

    # E o efeito real (argtypes setados) DEVE estar presente — verifica que
    # foi chamado de verdade, não apenas spy interceptou.
    assert dll_instance.TranslateTrade.argtypes == [c_size_t, POINTER(TConnectorTrade)]
    assert dll_instance.SubscribeTicker.argtypes == [c_wchar_p, c_wchar_p]


@pytest.mark.unit
def test_initialize_market_only_configures_signatures_even_when_dll_init_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """argtypes são setados ANTES de DLLInitializeMarketLogin — mesmo se init falha.

    Garante que CRIT-2 fix não é bypassado por erro de credencial: ctypes
    coercion deve ocorrer NA chamada de DLLInitializeMarketLogin já com
    restype=c_int para que o código de erro retornado não seja corrompido.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    dll_instance = MagicMock(name="DLLInstance")
    dll_instance.SetEnabledLogToDebug = MagicMock(return_value=0)
    # Init falha com NL_INVALID_ARGS — restype=c_int garante leitura correta.
    dll_instance.DLLInitializeMarketLogin = MagicMock(return_value=-2147483393)
    windll_mock = MagicMock(return_value=dll_instance)

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    from data_downloader.dll.errors import DLLInitError

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
        pytest.raises(DLLInitError),
    ):
        dll.initialize_market_only("KEY", "BAD", "BAD")

    # Mesmo com erro, argtypes foram setados ANTES — verificação direta.
    assert dll_instance.TranslateTrade.argtypes == [c_size_t, POINTER(TConnectorTrade)]
    assert dll_instance.DLLInitializeMarketLogin.restype == c_int
