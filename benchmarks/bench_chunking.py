"""bench_chunking.py — Pipeline end-to-end (mock DLL + orchestrator + writer + catalog).

Objetivo:
    Mede tempo total + throughput chunk-completo do pipeline real
    (`Orchestrator` + `ParquetWriter` + `Catalog`) usando mock DLL injetado
    diretamente no padrão de `tests/integration/test_orchestrator.py`. NAO
    depende de mock_dll.py (esqueleto incompleto) — usa fake `_FakeProfitDLL`
    inline, idêntico ao usado pela suite de integração.

Target V1:
    - Tempo total < 5min em rede boa (mock = 0 latencia → mede só pipeline).
    - Throughput chunk-completo trades/s (cumulativo: dll mock + ingest +
      write + commit catalog).

Hipoteses (mock-based v1):
    H1: Tempo dominante é IO de Parquet write (ParquetWriter overhead
        confirmado em COUNCIL-02 / 1.4.5).
    H2: Chunking de 5 dias úteis (WDO* via chunker.CHUNK_DAYS) é Pareto-otimo.
    H3: Reconnect ratio nao afeta tempo (mock = 0 reconnects).

Output:
    benchmarks/results/baselines_v1_mock/bench_chunking-{date}-{git_sha}.json

NOTA Pyro+Sol+Aria (COUNCIL-10):
    Este bench substitui v1.0.0-synthetic placeholder. Baseline registrado
    como `1.1.0-mock` aguardando smoke real (Story 1.7b-followup).
"""

from __future__ import annotations

import shutil
import statistics
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmarks._common import (
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from data_downloader.dll.types import (
    TC_LAST_PACKET,
    SystemTime,
    TConnectorAssetIdentifier,
    TConnectorTrade,
)
from data_downloader.orchestrator.orchestrator import JobConfig, Orchestrator
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter

TARGET_TOTAL_MIN = 5.0
SYMBOL = "WDOJ26"
TRADES_PER_CHUNK = 50_000  # reduzido vs 500k/dia para manter bench sob alguns min em mock
N_CHUNKS = 4  # 4 chunks de 5d uteis = ~20 dias = ~1 mes WDO
RUNS_PER_CONFIG = 3


# =====================================================================
# Mock DLL (mesmo padrão de tests/integration/test_orchestrator.py)
# =====================================================================


class _FakeProfitDLL:
    """Mock DLL inline — replica padrão do test suite."""

    def __init__(self, *, rounds: list[dict[str, Any]], dll_version: str = "4.0.0.30-mock"):
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
        self, ticker: str, exchange: str, dt_start_str: str, dt_end_str: str
    ) -> int:
        self.get_history_calls += 1
        if self._round_idx >= len(self.rounds):
            return 0
        round_cfg = self.rounds[self._round_idx]
        self._round_idx += 1
        self._current_specs = round_cfg.get("trade_specs", [])
        progress_seq = round_cfg.get("progress_sequence", [25, 50, 75, 100])
        emit_delay = round_cfg.get("emit_delay", 0.0)

        thread = threading.Thread(
            target=self._emit_loop,
            args=(ticker, list(self._current_specs), progress_seq, emit_delay),
            daemon=True,
        )
        thread.start()
        return 0

    def translate_trade(self, handle: int, struct: TConnectorTrade) -> int:
        self.translate_trade_calls += 1
        if handle >= len(self._current_specs):
            return -1
        spec = self._current_specs[handle]
        st = SystemTime()
        ts: datetime = spec["timestamp"]
        st.wYear = ts.year
        st.wMonth = ts.month
        st.wDay = ts.day
        st.wDayOfWeek = 0
        st.wHour = ts.hour
        st.wMinute = ts.minute
        st.wSecond = ts.second
        st.wMilliseconds = ts.microsecond // 1000
        struct.TradeDate = st
        struct.TradeNumber = spec.get("trade_number", handle + 1)
        struct.Price = spec["price"]
        struct.Quantity = spec["quantity"]
        struct.Volume = spec["price"] * spec["quantity"]
        struct.BuyAgent = spec.get("buy_agent", 0)
        struct.SellAgent = spec.get("sell_agent", 0)
        struct.TradeType = spec.get("trade_type", 1)
        return 0

    def _emit_loop(
        self,
        ticker: str,
        specs: list[dict[str, Any]],
        progress_seq: list[int],
        emit_delay: float,
    ) -> None:
        time.sleep(0.001)
        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        n = len(specs)
        for i, spec in enumerate(specs):
            if self._history_cb is None:
                break
            flags = spec.get("flags", 0)
            if i == n - 1 and spec.get("last_packet", True):
                flags |= TC_LAST_PACKET
            self._history_cb(asset, i, flags)
            if emit_delay > 0:
                time.sleep(emit_delay)
        for p in progress_seq:
            if self._progress_cb is None:
                break
            self._progress_cb(ticker, "F", 0, p)


def _build_round_with_n_trades(n: int, base: datetime) -> dict[str, Any]:
    """Cria round mock com N trades sequenciais (ts + 1ms entre eles)."""
    specs = []
    base_us = base.replace(microsecond=0)
    for i in range(n):
        sec_off = i // 1000
        us_off = (i % 1000) * 1000
        ts = base_us.replace(
            hour=min(base_us.hour + sec_off // 3600, 17),
            minute=min((base_us.minute + (sec_off // 60) % 60), 59),
            second=sec_off % 60,
            microsecond=us_off,
        )
        specs.append(
            {
                "timestamp": ts,
                "price": 5000.0 + (i % 100) * 0.5,
                "quantity": (i % 5) + 1,
                "trade_number": i + 1,
            }
        )
    return {"trade_specs": specs, "progress_sequence": [50, 100], "emit_delay": 0.0}


# =====================================================================
# Benchmark
# =====================================================================


def measure_full_month(tmp_dir: Path, n_chunks: int, trades_per_chunk: int) -> dict[str, Any]:
    """Mede pipeline completo end-to-end via Orchestrator real + mock DLL.

    Cada round de mock = 1 chunk. Orchestrator chama download_chunk por chunk;
    cada call dispara emit_loop -> callback -> ingestor -> writer.write -> catalog.
    """
    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    writer = ParquetWriter(data_dir=data_dir)

    # Build rounds (1 round por chunk)
    base_dates = [
        datetime(2026, 3, 2, 9, 0, 0),  # week 1 (5 d uteis)
        datetime(2026, 3, 9, 9, 0, 0),  # week 2
        datetime(2026, 3, 16, 9, 0, 0),  # week 3
        datetime(2026, 3, 23, 9, 0, 0),  # week 4
    ][:n_chunks]
    rounds = [_build_round_with_n_trades(trades_per_chunk, base) for base in base_dates]
    dll = _FakeProfitDLL(rounds=rounds)

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base_dates[0],
        end=base_dates[-1].replace(hour=17),
        chunk_timeout_seconds=300,
        resolve_contract=False,
    )

    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]

    t0 = time.perf_counter_ns()
    result = orch.run(config)
    t1 = time.perf_counter_ns()
    total_ms = (t1 - t0) / 1e6

    catalog.close()

    n_trades_total = trades_per_chunk * n_chunks
    throughput = (n_trades_total / (total_ms / 1000.0)) if total_ms > 0 else 0.0

    return {
        "n_chunks_target": n_chunks,
        "n_chunks_completed": result.chunks_completed,
        "n_chunks_failed": result.chunks_failed,
        "trades_per_chunk": trades_per_chunk,
        "n_trades_total": n_trades_total,
        "trades_persisted": result.metrics.trades_persisted,
        "total_ms": total_ms,
        "throughput_trades_per_sec": throughput,
        "status": result.status,
    }


def main() -> None:
    tmp_root = Path(tempfile.mkdtemp(prefix="bench_chunking_"))
    print(
        f"[bench_chunking] mock pipeline: {N_CHUNKS} chunks x {TRADES_PER_CHUNK:_} trades, "
        f"{RUNS_PER_CONFIG} runs"
    )

    runs: list[dict[str, Any]] = []
    try:
        for run_idx in range(RUNS_PER_CONFIG):
            run_dir = tmp_root / f"run_{run_idx}"
            print(f"\n[run {run_idx}/{RUNS_PER_CONFIG}]")
            res = measure_full_month(run_dir, N_CHUNKS, TRADES_PER_CHUNK)
            print(
                f"  total_ms={res['total_ms']:.0f}  "
                f"trades/s={res['throughput_trades_per_sec']:_.0f}  "
                f"chunks={res['n_chunks_completed']}/{res['n_chunks_target']}  "
                f"persisted={res['trades_persisted']:_}  status={res['status']}"
            )
            runs.append(res)

        total_ms_list = [r["total_ms"] for r in runs]
        tps_list = [r["throughput_trades_per_sec"] for r in runs]
        n_trades_total_first = runs[0]["n_trades_total"]
        target_total_ms = TARGET_TOTAL_MIN * 60_000

        # Extrapolacao: bench usa 50k trades/chunk, producao real usa 500k
        # tempo escala ~linear em ParquetWriter; estimativa para 1 mes real
        scale = (500_000 * 22) / n_trades_total_first  # 1 mes real / bench atual
        extrapolated_ms_p50 = statistics.median(total_ms_list) * scale

        summary = {
            "trades_per_chunk_mock": TRADES_PER_CHUNK,
            "n_chunks": N_CHUNKS,
            "total_ms_p50": statistics.median(total_ms_list),
            "total_ms_p99": percentile(total_ms_list, 0.99),
            "total_ms_stddev": statistics.stdev(total_ms_list) if len(total_ms_list) > 1 else 0.0,
            "throughput_chunk_complete_p50": statistics.median(tps_list),
            "throughput_chunk_complete_p99": percentile(tps_list, 0.99),
            "extrapolated_to_1month_real_ms_p50": extrapolated_ms_p50,
            "extrapolated_minutes_p50": extrapolated_ms_p50 / 60_000,
            "verdict_extrapolation": ("PASS" if extrapolated_ms_p50 < target_total_ms else "FAIL"),
            "verdict_basis": (
                f"Linear extrapolation from {n_trades_total_first:_} trades to "
                f"11M trades (1 month real); ParquetWriter is dominant cost — "
                f"matches COUNCIL-02 finding."
            ),
        }

        envelope = build_result_envelope(
            "bench_chunking",
            config={
                "n_chunks": N_CHUNKS,
                "trades_per_chunk": TRADES_PER_CHUNK,
                "runs_per_config": RUNS_PER_CONFIG,
                "target_total_min": TARGET_TOTAL_MIN,
                "mock_dll": "inline _FakeProfitDLL (test_orchestrator pattern)",
            },
            scenarios=runs,
            summary=summary,
            notes=(
                "End-to-end mock pipeline (Orchestrator + ParquetWriter + Catalog). "
                "Mock DLL inline (sem latencia rede). Baseline v1.1.0-mock — aguarda "
                "smoke real (Story 1.7b-followup) para baselines reais."
            ),
            dll_version="4.0.0.30-mock",
        )
        # Salva no resultsl normal E em baselines_v1_mock/
        path = save_results(envelope)

        # Copy to baselines_v1_mock/
        baseline_dir = path.parent / "baselines_v1_mock"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = baseline_dir / "bench_chunking-1.1.0-mock.json"
        shutil.copy(path, baseline_path)

        print(f"\n[bench_chunking] resultados em: {path}")
        print(f"[bench_chunking] baseline copy:  {baseline_path}")
        print_summary(envelope)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
