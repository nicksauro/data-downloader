"""Integration tests — multi-asset pipeline mock (Story 4.2 AC3 + AC5).

Cobertura end-to-end com mock DLL:

- WINH26 (futuro trimestral, BMF `F`) → download_chunk retorna trades.
- PETR4 (equity, Bovespa `B`) → download_chunk retorna trades.
- WDOJ26 (futuro mensal, BMF `F`) → regression — preserved.

Não chama ProfitDLL real — usa ``_FakeProfitDLL`` minimalista (mesma
fixture canônica de ``tests/integration/test_download_primitive.py``).
Smoke real está atrás de WAIVER 4.2 (humano roda).
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import (
    TC_LAST_PACKET,
    TAssetID,
    TConnectorAssetIdentifier,
    TradeFields,
)
from data_downloader.orchestrator.download_primitive import (
    ChunkResult,
    download_chunk,
)


def _dt_to_brt_naive_ns(dt: datetime) -> int:
    """datetime naive (BRT, lei R7) → ns desde 1970-01-01 — espelha
    ``download_primitive._system_time_to_ns_local``."""
    aware = dt.replace(tzinfo=UTC)
    delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
    total_seconds = delta.days * 86_400 + delta.seconds
    return total_seconds * 1_000_000_000 + delta.microseconds * 1_000


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    """Story 1.2 Q07-V — cada teste limpa o registry global de callbacks."""
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


# =====================================================================
# Mock DLL — multi-asset aware (subset de _FakeProfitDLL canônico)
# =====================================================================


class _MultiAssetFakeDLL:
    """DLL mock que valida exchange/ticker pair antes de aceitar request.

    Story 4.2 AC3 — comportamento esperado:
    - PETR4 + exchange='B' → OK, retorna trades.
    - WINH26 + exchange='F' → OK, retorna trades.
    - PETR4 + exchange='F' → simula NL_EXCHANGE_UNKNOWN (Q05-V).
    """

    def __init__(
        self,
        *,
        trade_specs: list[dict[str, Any]],
        progress_sequence: list[int] | None = None,
        emit_delay: float = 0.001,
        dll_version: str = "4.0.0.34-mock",
    ) -> None:
        self.trade_specs = trade_specs
        self.progress_sequence = progress_sequence or [25, 50, 75, 100]
        self.emit_delay = emit_delay
        self.dll_version = dll_version

        self._history_cb: Any = None
        self._progress_cb: Any = None
        self._emit_thread: threading.Thread | None = None

        # Audit
        self.calls: list[tuple[str, str]] = []  # (ticker, exchange)

    # ---- Surface compatible with ProfitDLL ----

    def set_history_trade_callback_v2(self, cb: Any) -> None:
        self._history_cb = cb

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_cb = cb

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start_str: str,
        dt_end_str: str,
    ) -> int:
        self.calls.append((ticker, exchange))
        # Q05-V — equity em BMF é NL_EXCHANGE_UNKNOWN.
        # Tickers equity B3 (4 letras + 1 dígito).
        from data_downloader.orchestrator.chunker import is_equity_ticker

        if is_equity_ticker(ticker) and exchange != "B":
            return -2147483600  # NL_EXCHANGE_UNKNOWN-like
        # Futuros (WDO/WIN) em Bovespa também não funcionam.
        if not is_equity_ticker(ticker) and exchange != "F":
            return -2147483600
        # Spawn thread emit.
        self._emit_thread = threading.Thread(
            target=self._emit_loop,
            args=(ticker, exchange),
            daemon=True,
        )
        self._emit_thread.start()
        return 0  # NL_OK

    def translate_trade(self, handle: int) -> TradeFields | None:
        """API V2 (Story 1.7b-followup): ``(handle) -> TradeFields | None``.

        Antes (drift): ``(handle, struct) -> int`` mutando struct in-place
        — incompatível com ``download_chunk`` atual (v1.1.0 task #10).
        """
        if handle >= len(self.trade_specs):
            return None
        spec = self.trade_specs[handle]
        ts: datetime = spec["timestamp"]
        return TradeFields(
            version=0,
            timestamp_ns=_dt_to_brt_naive_ns(ts),
            trade_number=spec.get("trade_number", handle + 1),
            price=spec["price"],
            quantity=spec["quantity"],
            volume=spec["price"] * spec["quantity"],
            buy_agent_id=0,
            sell_agent_id=0,
            trade_type=1,
        )

    def _emit_loop(self, ticker: str, exchange: str) -> None:
        time.sleep(0.01)
        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange=exchange, FeedType=0)
        n_trades = len(self.trade_specs)
        for i, spec in enumerate(self.trade_specs):
            if self._history_cb is None:
                break
            flags = spec.get("flags", 0)
            if i == n_trades - 1 and spec.get("last_packet", False):
                flags |= TC_LAST_PACKET
            self._history_cb(asset, i, flags)
            time.sleep(self.emit_delay)
        # TProgressCallback V2 (Q-DRIFT-05): 2 args (TAssetID, c_int) — note
        # que progress usa TAssetID (struct V1, 3 fields), distinto do
        # TConnectorAssetIdentifier do history callback.
        progress_asset = TAssetID(ticker=ticker, bolsa=exchange, feed=0)
        for p in self.progress_sequence:
            if self._progress_cb is None:
                break
            self._progress_cb(progress_asset, p)
            time.sleep(self.emit_delay)


def _spec(
    *,
    timestamp: datetime,
    price: float = 100.0,
    quantity: int = 1,
    trade_number: int = 0,
    last_packet: bool = False,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "price": price,
        "quantity": quantity,
        "trade_number": trade_number,
        "last_packet": last_packet,
    }


# =====================================================================
# Tests — multi-asset shapes
# =====================================================================


@pytest.mark.integration
def test_download_winh26_returns_trades() -> None:
    """Story 4.2 AC3 — WINH26 + exchange='F' → trades reais via mock."""
    base = datetime(2026, 2, 16, 9, 0, 0)
    specs = [
        _spec(
            timestamp=base.replace(second=i),
            price=130_000.0 + i,
            quantity=1,
            trade_number=i + 1,
        )
        for i in range(5)
    ]
    dll = _MultiAssetFakeDLL(trade_specs=specs, progress_sequence=[50, 100])

    result: ChunkResult = download_chunk(
        dll,  # type: ignore[arg-type]
        "WINH26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert isinstance(result, ChunkResult)
    assert result.status == "completed"
    assert len(result.trades) == 5
    assert result.symbol == "WINH26"
    assert result.exchange == "F"
    # Audita que mock recebeu (ticker, exchange) corretos.
    assert ("WINH26", "F") in dll.calls


@pytest.mark.integration
def test_download_petr4_with_bovespa_exchange_returns_trades() -> None:
    """Story 4.2 AC3 — PETR4 + exchange='B' → trades reais via mock (Q05-V)."""
    base = datetime(2026, 5, 4, 10, 30, 0)
    specs = [
        _spec(
            timestamp=base.replace(second=i),
            price=38.50 + i * 0.01,
            quantity=100,
            trade_number=i + 1,
        )
        for i in range(8)
    ]
    dll = _MultiAssetFakeDLL(trade_specs=specs, progress_sequence=[100])

    result: ChunkResult = download_chunk(
        dll,  # type: ignore[arg-type]
        "PETR4",
        "B",  # Bovespa — Q05-V
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 8
    assert result.symbol == "PETR4"
    assert result.exchange == "B"
    assert ("PETR4", "B") in dll.calls


@pytest.mark.integration
def test_download_petr4_with_bmf_exchange_returns_nl_error() -> None:
    """Story 4.2 / Q05-V — PETR4 + exchange='F' → NL_EXCHANGE_UNKNOWN.

    A primitiva ``download_chunk`` valida exchange ∈ ('F', 'B') antes
    de chamar a DLL. Aqui passamos 'B' válido, mas se mock detectar
    incompatibilidade ticker↔exchange, retorna NL erro pré-callback.
    Como ``download_chunk`` aceita 'F' como válido na fronteira,
    testamos cenário onde DLL rejeita → status='failed'.
    """
    base = datetime(2026, 5, 4, 10, 30, 0)
    specs = [_spec(timestamp=base, trade_number=1)]
    dll = _MultiAssetFakeDLL(trade_specs=specs)

    # Passamos 'F' para PETR4 → mock retorna NL_EXCHANGE_UNKNOWN-like.
    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "PETR4",
        "F",  # incorreto — equity não funciona em BMF (Q05-V).
        base,
        base.replace(hour=17),
        timeout=2,
    )

    assert result.status == "failed"
    assert result.nl_error_code is not None
    assert result.nl_error_code < 0


@pytest.mark.integration
def test_download_wdoj26_regression_preserved() -> None:
    """Regression — WDOJ26 (Story 1.3 baseline) ainda funciona inalterado."""
    base = datetime(2026, 4, 15, 9, 0, 0)
    specs = [
        _spec(
            timestamp=base.replace(second=i),
            price=5_400.0 + i * 0.5,
            quantity=1,
            trade_number=i + 1,
        )
        for i in range(3)
    ]
    dll = _MultiAssetFakeDLL(trade_specs=specs, progress_sequence=[100])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WDOJ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 3
    assert result.symbol == "WDOJ26"


@pytest.mark.integration
def test_download_winz26_quarterly_buffer() -> None:
    """Story 4.2 — WINZ26 (último trimestre 2026) também funciona."""
    base = datetime(2026, 11, 15, 10, 0, 0)
    specs = [_spec(timestamp=base, price=140_000.0, quantity=1, trade_number=1)]
    dll = _MultiAssetFakeDLL(trade_specs=specs, progress_sequence=[100])

    result = download_chunk(
        dll,  # type: ignore[arg-type]
        "WINZ26",
        "F",
        base,
        base.replace(hour=17),
        timeout=10,
    )

    assert result.status == "completed"
    assert len(result.trades) == 1


@pytest.mark.integration
def test_download_multiple_equities_sequential() -> None:
    """Story 4.2 — múltiplos equities em sequência (PETR4, VALE3, ITUB4)."""
    base = datetime(2026, 5, 4, 10, 0, 0)

    for ticker, price in (("PETR4", 38.50), ("VALE3", 65.20), ("ITUB4", 32.10)):
        specs = [
            _spec(
                timestamp=base.replace(second=i),
                price=price + i * 0.01,
                quantity=100,
                trade_number=i + 1,
            )
            for i in range(2)
        ]
        dll = _MultiAssetFakeDLL(trade_specs=specs, progress_sequence=[100])

        result = download_chunk(
            dll,  # type: ignore[arg-type]
            ticker,
            "B",
            base,
            base.replace(hour=17),
            timeout=10,
        )

        assert result.status == "completed", f"{ticker} failed: {result.status}"
        assert len(result.trades) == 2, f"{ticker} trades count {len(result.trades)}"
        assert result.symbol == ticker
        assert result.exchange == "B"
