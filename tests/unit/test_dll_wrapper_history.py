"""tests/unit/test_dll_wrapper_history.py — Story 1.3.

Cobertura dos métodos novos do ``ProfitDLL`` (Story 1.3):

- ``set_history_trade_callback_v2`` — registra via ``SetHistoryTradeCallbackV2``.
- ``set_progress_callback`` — registra via ``SetProgressCallback``.
- ``get_history_trades`` — chama ``GetHistoryTrades`` com 4 args + valida
  exchange + valida formato de data.
- ``translate_trade`` — chama ``TranslateTrade(handle, byref(struct))``.
- v1.2.0 (COUNCIL-38 / Q-DRIFT-40): ``TranslateTrade`` É chamado DENTRO do
  callback V2 (handle transiente) — enfileira ``TradeFields`` copiado.
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
# translate_trade — Story 1.7b-followup (returns TradeFields | None)
# =====================================================================


@pytest.mark.unit
def test_translate_trade_calls_dll_with_handle_and_struct_byref(tmp_path: Path) -> None:
    """TranslateTrade(handle, byref(struct)) — args devem chegar à DLL.

    Story 1.7b-followup: nova API ``translate_trade(handle) -> TradeFields``
    aloca struct internamente. Verificamos que TranslateTrade foi chamada
    com o handle correto + um pointer-like (byref do struct interno).
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()

    def _fill(_handle: int, struct_ref: object) -> int:
        # struct_ref é byref(TConnectorTrade) — ._obj é o struct interno.
        # Populamos TradeDate com SystemTime válido para que o parse de ns
        # não levante (year>=1).
        struct = struct_ref._obj  # type: ignore[attr-defined]
        from data_downloader.dll.types import SystemTime

        st = SystemTime()
        st.wYear = 2026
        st.wMonth = 4
        st.wDay = 15
        st.wHour = 9
        st.wMinute = 0
        st.wSecond = 0
        st.wMilliseconds = 0
        struct.TradeDate = st
        return 0

    mock_dll.TranslateTrade = MagicMock(side_effect=_fill)
    dll._dll = mock_dll

    fields = dll.translate_trade(0xDEADBEEF)

    assert fields is not None
    mock_dll.TranslateTrade.assert_called_once()
    call_args = mock_dll.TranslateTrade.call_args.args
    assert call_args[0] == 0xDEADBEEF
    # 2º arg é byref(struct) — pointer-like, não None.
    assert call_args[1] is not None


@pytest.mark.unit
def test_translate_trade_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    with pytest.raises(DLLInitError) as exc:
        dll.translate_trade(123)
    assert exc.value.name == "NL_NOT_INITIALIZED"


@pytest.mark.unit
def test_translate_trade_returns_none_on_nl_error(tmp_path: Path) -> None:
    """translate_trade retorna None quando TranslateTrade retorna NL_* < 0."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.TranslateTrade = MagicMock(return_value=-1)  # NL_INTERNAL_ERROR
    dll._dll = mock_dll

    result = dll.translate_trade(0xCAFE)
    assert result is None


@pytest.mark.unit
def test_translate_trade_raw_low_level_still_works(tmp_path: Path) -> None:
    """Helper privado ``_translate_trade_raw(handle, struct)`` ainda preenche struct."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.TranslateTrade = MagicMock(return_value=0)
    dll._dll = mock_dll

    struct = TConnectorTrade(Version=0)
    rc = dll._translate_trade_raw(0x1234, struct)

    assert rc == 0
    mock_dll.TranslateTrade.assert_called_once()


# =====================================================================
# v1.2.0 (COUNCIL-38 / Q-DRIFT-40) — TranslateTrade DENTRO do callback
# (R3 amended: handle transiente exige tradução no escopo do callback;
# enfileira TradeFields copiado, nunca o handle stale)
# =====================================================================


@pytest.mark.unit
def test_history_callback_translates_in_callback_and_enqueues_tradefields(tmp_path: Path) -> None:
    """Q-DRIFT-40 — V2 history callback chama dll.translate_trade(handle) DENTRO do callback.

    Inversão da invariante antiga (era: "callback só put_nowait((handle,
    flags))"). O handle ``a_pTrade`` só é válido no escopo do callback (a DLL
    recicla o buffer ao retornar) — por isso traduzimos AGORA. A fila recebe
    ``(TradeFields, flags)``, NUNCA o handle (stale).
    """
    from queue import Queue

    from data_downloader.dll.callbacks import make_history_trade_callback_v2
    from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields

    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()

    def _fill(_handle: int, struct_ref: object) -> int:
        struct = struct_ref._obj  # type: ignore[attr-defined]
        struct.TradeDate.wYear = 2026
        struct.TradeDate.wMonth = 4
        struct.TradeDate.wDay = 15
        struct.TradeDate.wHour = 9
        struct.Price = 5500.0
        struct.Quantity = 1
        struct.TradeNumber = _handle + 1
        return 0

    mock_dll.TranslateTrade = MagicMock(side_effect=_fill)
    dll._dll = mock_dll

    trade_queue: Queue[tuple[TradeFields, int]] = Queue()
    cb = make_history_trade_callback_v2(trade_queue, dll)
    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDO", Exchange="F", FeedType=0)

    for handle in range(50):
        cb(asset, handle, 0)

    # CORE Q-DRIFT-40: TranslateTrade chamado dentro do callback, 1x por trade.
    assert mock_dll.TranslateTrade.call_count == 50
    # Fila tem 50 TradeFields (não handles).
    assert trade_queue.qsize() == 50
    fields, flags = trade_queue.get_nowait()
    assert isinstance(fields, TradeFields)
    assert fields.price == 5500.0
    assert flags == 0


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
