"""tests/unit/test_dll_wrapper_history.py — Story 1.3.

Cobertura dos métodos novos do ``ProfitDLL`` (Story 1.3):

- ``set_history_trade_callback_v2`` — registra via ``SetHistoryTradeCallbackV2``.
- ``set_progress_callback`` — registra via ``SetProgressCallback``.
- ``get_history_trades`` — chama ``GetHistoryTrades`` com 4 args + valida
  exchange + valida formato de data.
- ``translate_trade`` — chama ``TranslateTrade(handle, byref(struct))``.
- Lei R3 / INV-1: ``TranslateTrade`` NÃO é chamado durante callback exec.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import TConnectorTrade
from data_downloader.dll.wrapper import ProfitDLL, _validate_history_date_format
from data_downloader.public_api.exceptions import DLLInitError


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


# =====================================================================
# set_history_trade_callback_v2
# =====================================================================


@pytest.mark.unit
def test_set_history_trade_callback_v2_calls_dll_method(tmp_path: Path) -> None:
    """SetHistoryTradeCallbackV2 é chamado UMA vez com o callback."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    dll._dll = mock_dll

    fake_cb = MagicMock(name="history_cb")
    dll.set_history_trade_callback_v2(fake_cb)

    mock_dll.SetHistoryTradeCallbackV2.assert_called_once_with(fake_cb)


@pytest.mark.unit
def test_set_history_trade_callback_v2_appends_to_instance_cb_refs(
    tmp_path: Path,
) -> None:
    """Wrapper guarda ref defensiva em self._cb_refs (Q07-V belt-and-braces)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    dll._dll = MagicMock()
    fake_cb = MagicMock(name="history_cb")

    initial = len(dll._cb_refs)
    dll.set_history_trade_callback_v2(fake_cb)
    assert len(dll._cb_refs) == initial + 1
    assert fake_cb in dll._cb_refs


@pytest.mark.unit
def test_set_history_trade_callback_v2_raises_when_dll_not_initialized(
    tmp_path: Path,
) -> None:
    """Sem init → DLLInitError(NL_NOT_INITIALIZED)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll._dll is None
    with pytest.raises(DLLInitError) as exc:
        dll.set_history_trade_callback_v2(MagicMock())
    assert exc.value.name == "NL_NOT_INITIALIZED"


# =====================================================================
# set_progress_callback
# =====================================================================


@pytest.mark.unit
def test_set_progress_callback_calls_dll_method(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    dll._dll = mock_dll

    fake_cb = MagicMock(name="progress_cb")
    dll.set_progress_callback(fake_cb)

    mock_dll.SetProgressCallback.assert_called_once_with(fake_cb)


@pytest.mark.unit
def test_set_progress_callback_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    with pytest.raises(DLLInitError) as exc:
        dll.set_progress_callback(MagicMock())
    assert exc.value.name == "NL_NOT_INITIALIZED"


# =====================================================================
# get_history_trades
# =====================================================================


@pytest.mark.unit
def test_get_history_trades_calls_dll_with_4_args_in_order(tmp_path: Path) -> None:
    """GetHistoryTrades chamado com (ticker, exchange, dt_start, dt_end) na ordem."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.GetHistoryTrades = MagicMock(return_value=0)
    dll._dll = mock_dll

    rc = dll.get_history_trades("WDOJ26", "F", "15/04/2026 09:00:00", "15/04/2026 17:00:00")

    assert rc == 0
    mock_dll.GetHistoryTrades.assert_called_once()
    args = mock_dll.GetHistoryTrades.call_args.args
    assert len(args) == 4
    # Args são c_wchar_p — verificamos via .value (ctypes wrapper).
    assert args[0].value == "WDOJ26"
    assert args[1].value == "F"
    assert args[2].value == "15/04/2026 09:00:00"
    assert args[3].value == "15/04/2026 17:00:00"


@pytest.mark.unit
@pytest.mark.parametrize("bad_exchange", ["BMF", "BOVESPA", "f", "b", "", "FF"])
def test_get_history_trades_rejects_invalid_exchange(tmp_path: Path, bad_exchange: str) -> None:
    """R8/Q05-V — bolsa DEVE ser 'F' ou 'B'. Strings tipo 'BMF' rejeitadas."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    dll._dll = MagicMock()
    with pytest.raises(ValueError) as exc:
        dll.get_history_trades("WDOJ26", bad_exchange, "15/04/2026 09:00:00", "15/04/2026 17:00:00")
    msg = str(exc.value)
    assert "exchange" in msg.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_date",
    [
        "2026-04-15 09:00:00",  # ISO, separadores errados
        "15-04-2026 09:00:00",  # hífen em vez de barra
        "15/04/2026",  # sem horário
        "15/4/2026 09:00:00",  # mês 1 dígito
        "15/04/2026 9:00:00",  # hora 1 dígito
        "",
    ],
)
def test_get_history_trades_rejects_invalid_date_format(tmp_path: Path, bad_date: str) -> None:
    """Formato exato manual §3.1 L1750: ``DD/MM/YYYY HH:mm:SS``."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    dll._dll = MagicMock()
    with pytest.raises(ValueError):
        dll.get_history_trades("WDOJ26", "F", bad_date, "15/04/2026 17:00:00")


@pytest.mark.unit
def test_get_history_trades_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    with pytest.raises(DLLInitError) as exc:
        dll.get_history_trades("WDOJ26", "F", "15/04/2026 09:00:00", "15/04/2026 17:00:00")
    assert exc.value.name == "NL_NOT_INITIALIZED"


# =====================================================================
# translate_trade
# =====================================================================


@pytest.mark.unit
def test_translate_trade_calls_dll_with_handle_and_struct_byref(tmp_path: Path) -> None:
    """TranslateTrade(handle, byref(struct)) — args devem chegar à DLL."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.TranslateTrade = MagicMock(return_value=0)
    dll._dll = mock_dll

    struct = TConnectorTrade(Version=0)
    rc = dll.translate_trade(0xDEADBEEF, struct)

    assert rc == 0
    mock_dll.TranslateTrade.assert_called_once()
    call_args = mock_dll.TranslateTrade.call_args.args
    assert call_args[0] == 0xDEADBEEF
    # 2º arg é byref(struct) — inspecionamos via .contents (ctypes byref).
    # Garantia mínima: arg[1] não é None e existe (byref retorna pointer-like).
    assert call_args[1] is not None


@pytest.mark.unit
def test_translate_trade_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    struct = TConnectorTrade(Version=0)
    with pytest.raises(DLLInitError) as exc:
        dll.translate_trade(123, struct)
    assert exc.value.name == "NL_NOT_INITIALIZED"


# =====================================================================
# Lei R3 / INV-1 — TranslateTrade NÃO chamado durante callback exec
# =====================================================================


@pytest.mark.unit
def test_history_callback_does_not_invoke_translate_trade_inv1(tmp_path: Path) -> None:
    """INV-1 — V2 history callback NÃO chama dll.TranslateTrade.

    Isto é a invariante CRÍTICA da Story 1.3: o callback faz apenas
    ``put_nowait((handle, flags))`` — ``TranslateTrade`` é responsabilidade
    do IngestorThread (FORA do callback / ConnectorThread).

    Verificação: substitui dll por MagicMock; cria callback via factory
    real; invoca callback; assert que mock_dll.TranslateTrade NUNCA foi
    chamado.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    dll._dll = mock_dll

    from queue import Queue

    from data_downloader.dll.callbacks import make_history_trade_callback_v2
    from data_downloader.dll.types import TConnectorAssetIdentifier

    trade_queue: Queue[tuple[int, int]] = Queue()
    cb = make_history_trade_callback_v2(trade_queue)
    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDO", Exchange="F", FeedType=0)

    # Invocar callback várias vezes (simulando ConnectorThread):
    for handle in range(100):
        cb(asset, handle, 0)

    # CORE INV-1: TranslateTrade NUNCA foi chamado:
    assert (
        not mock_dll.TranslateTrade.called
    ), "V2 history callback chamou TranslateTrade — viola INV-1/R3!"
    # Nem qualquer outro método da DLL:
    assert (
        mock_dll.mock_calls == []
    ), f"V2 history callback chamou métodos da DLL — viola R3. Calls: {mock_dll.mock_calls}"

    # Side-check: queue recebeu todos os 100 handles.
    assert trade_queue.qsize() == 100


# =====================================================================
# _validate_history_date_format (helper exposto para reuso em testes)
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "valid",
    [
        "01/01/2026 00:00:00",
        "31/12/2099 23:59:59",
        "15/04/2026 09:00:00",
    ],
)
def test_validate_history_date_format_accepts_valid(valid: str) -> None:
    # Não levanta — sucesso.
    _validate_history_date_format(valid, "field")


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "2026-04-15 09:00:00",
        "15.04.2026 09:00:00",
        "15/04/2026T09:00:00",
        "15/04/202609:00:00",
        "",
        "x" * 19,  # comprimento certo, separadores errados
    ],
)
def test_validate_history_date_format_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        _validate_history_date_format(bad, "field")
