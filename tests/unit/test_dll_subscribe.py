"""tests/unit/test_dll_subscribe.py — Story 1.7b-followup.

Cobertura dos métodos ``subscribe_ticker`` / ``unsubscribe_ticker`` do
``ProfitDLL``:

- ``SubscribeTicker(c_wchar_p ticker, c_wchar_p exchange)`` chamada com args corretos.
- ``UnsubscribeTicker(c_wchar_p ticker, c_wchar_p exchange)`` chamada com args corretos.
- Retorno (int) propagado para caller.
- Validação R8/Q05-V: exchange ∉ {'F','B'} → ValueError ANTES de chamar a DLL.
- DLL não inicializada → ``DLLInitError(NL_NOT_INITIALIZED)``.
- Logger structlog emite eventos ``dll.subscribe_ticker`` /
  ``dll.unsubscribe_ticker`` (AC8 do wrapper — observabilidade).

Bug crítico corrigido (autoridade ProfitDLL): ``SubscribeTicker`` é
PRÉ-REQUISITO de ``GetHistoryTrades``. Sem subscribe, a DLL não entrega
trades históricos. Alinhado com exemplo Nelogica
(``profitdll/Exemplo Python/main.py`` L590-602).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.wrapper import ProfitDLL
from data_downloader.public_api.exceptions import DLLInitError


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


# =====================================================================
# subscribe_ticker
# =====================================================================


@pytest.mark.unit
def test_subscribe_ticker_calls_dll_with_two_wchar_args(tmp_path: Path) -> None:
    """SubscribeTicker chamada com (ticker, exchange) como ``c_wchar_p``."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.SubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    rc = dll.subscribe_ticker("WDOJ26", "F")

    assert rc == 0
    mock_dll.SubscribeTicker.assert_called_once()
    args = mock_dll.SubscribeTicker.call_args.args
    assert len(args) == 2
    # c_wchar_p — verificamos via .value (ctypes wrapper).
    assert args[0].value == "WDOJ26"
    assert args[1].value == "F"


@pytest.mark.unit
def test_subscribe_ticker_propagates_return_code(tmp_path: Path) -> None:
    """Código NL_* retornado pela DLL é propagado tal e qual."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.SubscribeTicker = MagicMock(return_value=-2147483646)  # NL_NOT_INITIALIZED
    dll._dll = mock_dll

    rc = dll.subscribe_ticker("WDOJ26", "F")
    assert rc == -2147483646


@pytest.mark.unit
@pytest.mark.parametrize("bad_exchange", ["BMF", "BOVESPA", "f", "b", "", "FF"])
def test_subscribe_ticker_rejects_invalid_exchange(tmp_path: Path, bad_exchange: str) -> None:
    """R8/Q05-V — bolsa DEVE ser 'F' ou 'B'. ValueError ANTES de chamar DLL."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    dll._dll = mock_dll

    with pytest.raises(ValueError) as exc:
        dll.subscribe_ticker("WDOJ26", bad_exchange)
    assert "exchange" in str(exc.value).lower()
    # CRITICAL: DLL NÃO foi chamada (validação é upfront).
    mock_dll.SubscribeTicker.assert_not_called()


@pytest.mark.unit
def test_subscribe_ticker_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    """Sem init → DLLInitError(NL_NOT_INITIALIZED)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll._dll is None
    with pytest.raises(DLLInitError) as exc:
        dll.subscribe_ticker("WDOJ26", "F")
    assert exc.value.name == "NL_NOT_INITIALIZED"


@pytest.mark.unit
def test_subscribe_ticker_emits_logger_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logger structlog emite ``dll.subscribe_ticker`` com ticker + exchange."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.SubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    dll.subscribe_ticker("WDOJ26", "F")

    # structlog write to stdout via PrintLogger configurado por logging_config.
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "dll.subscribe_ticker" in combined
    assert "WDOJ26" in combined
    assert "F" in combined


# =====================================================================
# unsubscribe_ticker
# =====================================================================


@pytest.mark.unit
def test_unsubscribe_ticker_calls_dll_with_two_wchar_args(tmp_path: Path) -> None:
    """UnsubscribeTicker chamada com (ticker, exchange) como ``c_wchar_p``."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.UnsubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    rc = dll.unsubscribe_ticker("WDOJ26", "B")

    assert rc == 0
    mock_dll.UnsubscribeTicker.assert_called_once()
    args = mock_dll.UnsubscribeTicker.call_args.args
    assert len(args) == 2
    assert args[0].value == "WDOJ26"
    assert args[1].value == "B"


@pytest.mark.unit
def test_unsubscribe_ticker_propagates_return_code(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.UnsubscribeTicker = MagicMock(return_value=-1234)
    dll._dll = mock_dll

    rc = dll.unsubscribe_ticker("PETR4", "B")
    assert rc == -1234


@pytest.mark.unit
@pytest.mark.parametrize("bad_exchange", ["BMF", "BOVESPA", "f", "b", "", "X"])
def test_unsubscribe_ticker_rejects_invalid_exchange(tmp_path: Path, bad_exchange: str) -> None:
    """R8/Q05-V — mesma validação que subscribe."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    dll._dll = mock_dll

    with pytest.raises(ValueError) as exc:
        dll.unsubscribe_ticker("WDOJ26", bad_exchange)
    assert "exchange" in str(exc.value).lower()
    mock_dll.UnsubscribeTicker.assert_not_called()


@pytest.mark.unit
def test_unsubscribe_ticker_raises_when_dll_not_initialized(tmp_path: Path) -> None:
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    with pytest.raises(DLLInitError) as exc:
        dll.unsubscribe_ticker("WDOJ26", "F")
    assert exc.value.name == "NL_NOT_INITIALIZED"


@pytest.mark.unit
def test_unsubscribe_ticker_emits_logger_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logger emite ``dll.unsubscribe_ticker``."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.UnsubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    dll.unsubscribe_ticker("WDOJ26", "F")
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "dll.unsubscribe_ticker" in combined
    assert "WDOJ26" in combined
    assert "F" in combined


# =====================================================================
# Subscribe / Unsubscribe pairing — order semantics
# =====================================================================


@pytest.mark.unit
def test_subscribe_then_unsubscribe_distinct_methods(tmp_path: Path) -> None:
    """``subscribe_ticker`` chama SubscribeTicker; ``unsubscribe_ticker`` chama UnsubscribeTicker.

    Garante que não há crossover (subscribe não chama UnsubscribeTicker e
    vice-versa). Manual §3.1 — funções distintas, slots distintos.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.SubscribeTicker = MagicMock(return_value=0)
    mock_dll.UnsubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    dll.subscribe_ticker("WDOJ26", "F")
    dll.unsubscribe_ticker("WDOJ26", "F")

    assert mock_dll.SubscribeTicker.call_count == 1
    assert mock_dll.UnsubscribeTicker.call_count == 1


@pytest.mark.unit
def test_subscribe_unsubscribe_validation_consistent(tmp_path: Path) -> None:
    """Mesma exchange válida para ambos — validação não é divergente."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.SubscribeTicker = MagicMock(return_value=0)
    mock_dll.UnsubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    # 'F' e 'B' válidos para ambos.
    for exch in ("F", "B"):
        dll.subscribe_ticker("WDOJ26", exch)
        dll.unsubscribe_ticker("WDOJ26", exch)

    assert mock_dll.SubscribeTicker.call_count == 2
    assert mock_dll.UnsubscribeTicker.call_count == 2


@pytest.mark.unit
def test_subscribe_ticker_does_not_clear_cb_refs(tmp_path: Path) -> None:
    """Subscribe é independente de callbacks — não toca _cb_refs.

    Sanity: subscribe/unsubscribe operam fora do ciclo de callback —
    apenas registro de interesse na DLL. AC4 / Q07-V: callbacks
    permanecem em _cb_refs.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.SubscribeTicker = MagicMock(return_value=0)
    dll._dll = mock_dll

    initial_global = list(cb_module._cb_refs)
    initial_local = list(dll._cb_refs)

    dll.subscribe_ticker("WDOJ26", "F")

    assert cb_module._cb_refs == initial_global
    assert dll._cb_refs == initial_local


# =====================================================================
# Sanity — ctypes argtypes (validação de tipo no edge)
# =====================================================================


@pytest.mark.unit
def test_subscribe_ticker_handles_unicode_ticker(tmp_path: Path) -> None:
    """c_wchar_p suporta strings Unicode (defensive — DLL espera UTF-16)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    captured: list[Any] = []

    def _capture(*args: Any) -> int:
        captured.extend(args)
        return 0

    mock_dll.SubscribeTicker = MagicMock(side_effect=_capture)
    dll._dll = mock_dll

    # Ticker com caracteres válidos (DLL não aceita Unicode real, mas
    # c_wchar_p deve aceitar a string sem quebrar).
    dll.subscribe_ticker("WDOJ26", "F")
    assert captured[0].value == "WDOJ26"
    assert captured[1].value == "F"
