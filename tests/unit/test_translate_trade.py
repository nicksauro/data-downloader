"""tests/unit/test_translate_trade.py — Story 1.7b-followup.

Cobertura da nova API ``ProfitDLL.translate_trade(handle) -> TradeFields | None``:

- Aloca struct interno + chama TranslateTrade com handle correto.
- Extrai 9 campos do struct para TradeFields imutável.
- TradeDate (SystemTime) → timestamp_ns BRT naive (lei R7).
- TradeType / flags variados.
- NL_* < 0 → retorna None (caller agrega via counter).
- DLL não-inicializada → DLLInitError(NL_NOT_INITIALIZED).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import SystemTime, TConnectorTrade, TradeFields
from data_downloader.dll.wrapper import ProfitDLL, _system_time_to_ns_local
from data_downloader.public_api.exceptions import DLLInitError


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


def _make_st(
    *,
    year: int = 2026,
    month: int = 4,
    day: int = 15,
    hour: int = 9,
    minute: int = 0,
    second: int = 0,
    millis: int = 0,
) -> SystemTime:
    """Helper: cria SystemTime preenchido."""
    st = SystemTime()
    st.wYear = year
    st.wMonth = month
    st.wDayOfWeek = 0
    st.wDay = day
    st.wHour = hour
    st.wMinute = minute
    st.wSecond = second
    st.wMilliseconds = millis
    return st


def _patch_translate_trade(
    mock_dll: MagicMock,
    *,
    rc: int = 0,
    fields: dict[str, object] | None = None,
) -> None:
    """Configura mock_dll.TranslateTrade(handle, byref(struct)) → preenche struct.

    ``fields`` é dict ``{TradeDate: SystemTime, TradeNumber: int, Price: float, ...}``.
    """

    fields = fields or {}

    def _side_effect(_handle: int, struct_ref: object) -> int:
        # struct_ref é byref(struct) — ._obj é o struct subjacente.
        struct = struct_ref._obj  # type: ignore[attr-defined]
        for k, v in fields.items():
            setattr(struct, k, v)
        return rc

    mock_dll.TranslateTrade = MagicMock(side_effect=_side_effect)


@pytest.mark.unit
def test_translate_trade_returns_tradefields_with_extracted_fields(tmp_path: Path) -> None:
    """Sucesso → retorna TradeFields com os 9 campos do struct."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    _patch_translate_trade(
        mock_dll,
        rc=0,
        fields={
            "Version": 0,
            "TradeDate": _make_st(
                year=2026, month=4, day=15, hour=10, minute=30, second=45, millis=123
            ),
            "TradeNumber": 42,
            "Price": 5025.5,
            "Quantity": 7,
            "Volume": 5025.5 * 7,
            "BuyAgent": 308,
            "SellAgent": 110,
            "TradeType": 3,
        },
    )
    dll._dll = mock_dll

    result = dll.translate_trade(0xCAFEBABE)
    assert result is not None
    assert isinstance(result, TradeFields)
    assert result.version == 0
    assert result.trade_number == 42
    assert result.price == pytest.approx(5025.5)
    assert result.quantity == 7
    assert result.volume == pytest.approx(5025.5 * 7)
    assert result.buy_agent_id == 308
    assert result.sell_agent_id == 110
    assert result.trade_type == 3


@pytest.mark.unit
def test_translate_trade_called_with_handle(tmp_path: Path) -> None:
    """TranslateTrade recebe handle exato no 1º arg."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    _patch_translate_trade(mock_dll, rc=0, fields={"TradeDate": _make_st()})
    dll._dll = mock_dll

    dll.translate_trade(0xDEADBEEF)
    args = mock_dll.TranslateTrade.call_args.args
    assert args[0] == 0xDEADBEEF
    assert args[1] is not None  # byref pointer-like


@pytest.mark.unit
def test_translate_trade_returns_none_on_nl_error(tmp_path: Path) -> None:
    """rc < 0 (NL_*) → retorna None (caller agrega via counter)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    _patch_translate_trade(mock_dll, rc=-2147483645)  # alguma NL_ERR
    dll._dll = mock_dll

    result = dll.translate_trade(0x1234)
    assert result is None


@pytest.mark.unit
def test_translate_trade_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    """DLL ainda não inicializada → DLLInitError(NL_NOT_INITIALIZED)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll._dll is None
    with pytest.raises(DLLInitError) as exc:
        dll.translate_trade(0x99)
    assert exc.value.name == "NL_NOT_INITIALIZED"


@pytest.mark.unit
def test_translate_trade_parses_systemtime_to_brt_naive_ns(tmp_path: Path) -> None:
    """TradeDate (SystemTime) → timestamp_ns BRT naive (lei R7)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    st = _make_st(year=2026, month=4, day=15, hour=14, minute=30, second=45, millis=500)
    _patch_translate_trade(mock_dll, rc=0, fields={"TradeDate": st})
    dll._dll = mock_dll

    result = dll.translate_trade(1)
    assert result is not None
    expected_ns = _system_time_to_ns_local(st)
    assert result.timestamp_ns == expected_ns


@pytest.mark.unit
@pytest.mark.parametrize(
    "trade_type",
    [0, 1, 2, 3, 5, 200],  # auction, regular, cross, ...
)
def test_translate_trade_propagates_trade_type(tmp_path: Path, trade_type: int) -> None:
    """Vários TradeType propagam corretamente (uint8 → int)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    _patch_translate_trade(
        mock_dll,
        rc=0,
        fields={"TradeDate": _make_st(), "TradeType": trade_type},
    )
    dll._dll = mock_dll

    result = dll.translate_trade(1)
    assert result is not None
    assert result.trade_type == trade_type


@pytest.mark.unit
def test_translate_trade_raw_low_level_api(tmp_path: Path) -> None:
    """Helper privado ``_translate_trade_raw(handle, struct) -> int`` ainda funciona."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.TranslateTrade = MagicMock(return_value=0)
    dll._dll = mock_dll

    struct = TConnectorTrade(Version=0)
    rc = dll._translate_trade_raw(0x55, struct)
    assert rc == 0
    mock_dll.TranslateTrade.assert_called_once()


@pytest.mark.unit
def test_translate_trade_does_not_leak_struct_state(tmp_path: Path) -> None:
    """Múltiplas chamadas alocam structs independentes (não compartilham state)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()

    call_count = {"n": 0}

    def _side_effect(_handle: int, struct_ref: object) -> int:
        struct = struct_ref._obj  # type: ignore[attr-defined]
        call_count["n"] += 1
        struct.TradeDate = _make_st()
        struct.TradeNumber = call_count["n"] * 100
        struct.Price = 100.0 * call_count["n"]
        struct.Quantity = call_count["n"]
        return 0

    mock_dll.TranslateTrade = MagicMock(side_effect=_side_effect)
    dll._dll = mock_dll

    r1 = dll.translate_trade(1)
    r2 = dll.translate_trade(2)
    r3 = dll.translate_trade(3)

    assert r1 is not None and r1.trade_number == 100 and r1.quantity == 1
    assert r2 is not None and r2.trade_number == 200 and r2.quantity == 2
    assert r3 is not None and r3.trade_number == 300 and r3.quantity == 3
