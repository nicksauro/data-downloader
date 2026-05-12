"""Integration tests — Orchestrator + MetricsEmitter (Story 2.4 AC5).

Cobertura:

- Orchestrator aceita ``metrics_emitter`` no ``__init__`` (default Null).
- Após mock job de N chunks, spy emitter recebeu eventos canônicos:
  - ``chunks_completed_total{symbol,status="success"}`` += N
  - ``parquet_writes_total{symbol}`` += N
  - ``trades_received_total{symbol}`` += N (1x por chunk com trades)
  - ``download_jobs_total{status}`` += 1
  - ``active_downloads`` set 1 → 0
  - ``chunk_duration_seconds`` observado N vezes
  - ``last_chunk_duration_seconds`` setado N vezes
- Cache hit emite ``download_jobs_total{status="cache_hit"}``.

NÃO testa per-trade events — R21: orchestrator NÃO chama emitter
per-trade (apenas per-chunk batch).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import (
    TC_LAST_PACKET,
    TAssetID,
    TConnectorAssetIdentifier,
    TradeFields,
)
from data_downloader.orchestrator.orchestrator import (
    JobConfig,
    Orchestrator,
)
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter


def _dt_to_brt_naive_ns(dt: datetime) -> int:
    """datetime naive (BRT, lei R7) → ns desde 1970-01-01 (v1.1.0 task #10)."""
    from datetime import UTC

    aware = dt.replace(tzinfo=UTC)
    delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


# =====================================================================
# Spy MetricsEmitter
# =====================================================================


class _SpyEmitter:
    """Captura todas chamadas para asserts em ordem cronológica."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str] | None]] = []
        self.gauges: list[tuple[str, float, dict[str, str] | None]] = []
        self.observations: list[tuple[str, float, dict[str, str] | None]] = []

    def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        self.counters.append((name, labels))

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self.gauges.append((name, value, labels))

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        self.observations.append((name, value, labels))


# =====================================================================
# Mock DLL — copia simplificada do test_orchestrator.py
# =====================================================================


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Any:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


class _FakeProfitDLL:
    def __init__(
        self,
        *,
        rounds: list[dict[str, Any]],
        dll_version: str = "4.0.0.34",
    ) -> None:
        self.rounds = rounds
        self.dll_version = dll_version
        self._history_cb: Any = None
        self._progress_cb: Any = None
        self._round_idx = 0
        self.set_history_calls = 0
        self.set_progress_calls = 0
        self.get_history_calls = 0
        self.translate_trade_calls = 0
        self._current_specs: list[dict[str, Any]] = []

    def set_history_trade_callback_v2(self, cb: Any) -> None:
        self._history_cb = cb
        self.set_history_calls += 1

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_cb = cb
        self.set_progress_calls += 1

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start_str: str,
        dt_end_str: str,
    ) -> int:
        self.get_history_calls += 1
        if self._round_idx >= len(self.rounds):
            # Out-of-rounds → chunk vazio mas COMPLETO (progress=100) — evita
            # timeout/retry/deadlock quando o chunker ADR-023 (1d) gera mais
            # chunks que rounds (v1.1.0 task #10 — Quinn QA).
            self._current_specs = []
            threading.Thread(
                target=self._emit_loop, args=(ticker, [], [50, 100], 0.001), daemon=True
            ).start()
            return 0
        round_cfg = self.rounds[self._round_idx]
        self._round_idx += 1
        if round_cfg.get("get_history_return", 0) < 0:
            return int(round_cfg["get_history_return"])
        self._current_specs = round_cfg.get("trade_specs", [])
        progress_seq = round_cfg.get("progress_sequence", [25, 50, 75, 100])
        emit_delay = round_cfg.get("emit_delay", 0.001)
        thread = threading.Thread(
            target=self._emit_loop,
            args=(ticker, list(self._current_specs), progress_seq, emit_delay),
            daemon=True,
        )
        thread.start()
        return 0

    def translate_trade(self, handle: int) -> TradeFields | None:
        """API V2 (Story 1.7b-followup) — ``(handle) -> TradeFields | None``."""
        self.translate_trade_calls += 1
        if handle >= len(self._current_specs):
            return None
        spec = self._current_specs[handle]
        ts: datetime = spec["timestamp"]
        return TradeFields(
            version=0,
            timestamp_ns=_dt_to_brt_naive_ns(ts),
            trade_number=spec.get("trade_number", handle + 1),
            price=spec["price"],
            quantity=spec["quantity"],
            volume=spec["price"] * spec["quantity"],
            buy_agent_id=spec.get("buy_agent", 0),
            sell_agent_id=spec.get("sell_agent", 0),
            trade_type=spec.get("trade_type", 1),
        )

    def _emit_loop(
        self,
        ticker: str,
        specs: list[dict[str, Any]],
        progress_seq: list[int],
        emit_delay: float,
    ) -> None:
        time.sleep(0.005)
        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        n = len(specs)
        for i, spec in enumerate(specs):
            if self._history_cb is None:
                break
            flags = spec.get("flags", 0)
            if i == n - 1 and spec.get("last_packet", True):
                flags |= TC_LAST_PACKET
            self._history_cb(asset, i, flags)
            time.sleep(emit_delay)
        # TProgressCallback V2 (Q-DRIFT-05): 2 args (TAssetID, c_int).
        progress_asset = TAssetID(ticker=ticker, bolsa="F", feed=0)
        for p in progress_seq:
            if self._progress_cb is None:
                break
            self._progress_cb(progress_asset, p)
            time.sleep(emit_delay)


def _spec(
    *,
    timestamp: datetime,
    price: float = 100.0,
    quantity: int = 1,
    trade_number: int = 1,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "price": price,
        "quantity": quantity,
        "trade_number": trade_number,
    }


def _round_with_n_trades(
    n: int,
    *,
    base: datetime,
    base_price: float = 100.0,
) -> dict[str, Any]:
    specs = [
        _spec(
            timestamp=base.replace(microsecond=i * 1000),
            price=base_price + i,
            quantity=1,
            trade_number=i + 1,
        )
        for i in range(n)
    ]
    return {"trade_specs": specs}


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def catalog(data_dir: Path) -> Catalog:
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    yield cat
    cat.close()


@pytest.fixture
def writer(data_dir: Path) -> ParquetWriter:
    return ParquetWriter(data_dir=data_dir)


# =====================================================================
# Tests — emitter receives expected events
# =====================================================================


@pytest.mark.integration
def test_orchestrator_default_emitter_is_null(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Sem ``metrics_emitter``, orchestrator usa NullMetricsEmitter (zero overhead)."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(3, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    # Não passa metrics_emitter — usa default.
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"


@pytest.mark.integration
def test_orchestrator_emits_metrics_for_successful_chunk(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Job de 1 chunk com 5 trades → métricas canônicas refletem operações."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(5, base=base)])
    spy = _SpyEmitter()
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer, metrics_emitter=spy)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"

    # active_downloads = 1 e depois 0.
    active_gauges = [g for g in spy.gauges if g[0] == "active_downloads"]
    assert active_gauges == [
        ("active_downloads", 1.0, None),
        ("active_downloads", 0.0, None),
    ]

    # last_chunk_duration_seconds setado pelo menos uma vez.
    assert any(g[0] == "last_chunk_duration_seconds" for g in spy.gauges)

    # Counters: 1 chunks_completed{success}, 1 trades_received, 1 parquet_writes,
    # 1 download_jobs{completed}.
    chunks_done = [c for c in spy.counters if c[0] == "chunks_completed_total"]
    assert chunks_done == [
        (
            "chunks_completed_total",
            {"symbol": "WDOJ26", "status": "success"},
        )
    ]
    trades_received = [c for c in spy.counters if c[0] == "trades_received_total"]
    assert trades_received == [("trades_received_total", {"symbol": "WDOJ26"})]
    parquet_writes = [c for c in spy.counters if c[0] == "parquet_writes_total"]
    assert parquet_writes == [("parquet_writes_total", {"symbol": "WDOJ26"})]
    jobs_total = [c for c in spy.counters if c[0] == "download_jobs_total"]
    assert jobs_total == [("download_jobs_total", {"status": "completed"})]

    # Histogram: chunk_duration_seconds observado 1 vez.
    chunk_durations = [o for o in spy.observations if o[0] == "chunk_duration_seconds"]
    assert len(chunk_durations) == 1
    assert chunk_durations[0][2] == {"symbol": "WDOJ26"}
    # Duração > 0.
    assert chunk_durations[0][1] >= 0.0


@pytest.mark.integration
def test_orchestrator_emits_metrics_for_two_chunks(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Janela de 10 dias úteis WDO → 10 chunks de 1d (ADR-023).

    2 chunks carregam trades → 2 ``chunks_completed_total{status=success}``;
    os 8 restantes ficam vazios (out-of-rounds → status=no_trades). O
    histograma ``chunk_duration_seconds`` é observado 1x por chunk
    (independente do status) → 10 observações.
    """
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    dll = _FakeProfitDLL(
        rounds=[
            _round_with_n_trades(3, base=start.replace(day=2)),
            _round_with_n_trades(4, base=start.replace(day=9)),
        ]
    )
    spy = _SpyEmitter()
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer, metrics_emitter=spy)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"

    chunks_done = [
        c
        for c in spy.counters
        if c[0] == "chunks_completed_total" and c[1] == {"symbol": "WDOJ26", "status": "success"}
    ]
    assert len(chunks_done) == 2  # apenas 2 chunks têm trades
    chunk_durations = [o for o in spy.observations if o[0] == "chunk_duration_seconds"]
    assert len(chunk_durations) == 10  # 10 dias úteis = 10 chunks (ADR-023)


@pytest.mark.integration
def test_orchestrator_no_emitter_call_per_trade(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """R21 reforço: emitter NÃO é chamado per-trade (apenas per-chunk batch).

    Validação: 100 trades em 1 chunk → trades_received_total chamado APENAS 1x
    (não 100x). Hot path preservado.
    """
    base = datetime(2026, 3, 2, 9, 0, 0)
    # 50 trades em 1 chunk único.
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(50, base=base)])
    spy = _SpyEmitter()
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer, metrics_emitter=spy)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"
    assert result.metrics.trades_persisted == 50

    # CHAVE: trades_received_total chamado APENAS 1 vez (per-chunk),
    # NÃO 50 vezes (per-trade) — R21 garantido.
    trades_received = [c for c in spy.counters if c[0] == "trades_received_total"]
    assert len(trades_received) == 1


@pytest.mark.integration
def test_orchestrator_emits_cache_hit_status(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """2º run com mesmo range → cache_hit; emitter recebe download_jobs{cache_hit}."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll1 = _FakeProfitDLL(rounds=[_round_with_n_trades(3, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    # 1º run popula cache.
    orch1 = Orchestrator(dll1, catalog, writer)  # type: ignore[arg-type]
    res1 = orch1.run(config)
    assert res1.status == "completed"

    # 2º run com novo spy — deve dar cache_hit.
    spy = _SpyEmitter()
    dll2 = _FakeProfitDLL(rounds=[])  # sem rounds — não deve ser chamada.
    orch2 = Orchestrator(dll2, catalog, writer, metrics_emitter=spy)  # type: ignore[arg-type]
    res2 = orch2.run(config)
    assert res2.status == "cache_hit"

    # Apenas download_jobs_total{cache_hit} deve ter sido emitido.
    jobs_total = [c for c in spy.counters if c[0] == "download_jobs_total"]
    assert jobs_total == [("download_jobs_total", {"status": "cache_hit"})]
    # Nenhum chunk_completed (não passou pelo loop).
    assert not any(c[0] == "chunks_completed_total" for c in spy.counters)
