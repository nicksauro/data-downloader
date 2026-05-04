"""bench_multi_symbol.py — N processos baixando N simbolos em paralelo (mock).

Objetivo:
    Mede speedup de N processos baixando N simbolos diferentes em paralelo
    via `multiprocessing` no Windows (spawn semantics). Cada processo roda
    pipeline mock completo (Orchestrator + ParquetWriter + Catalog) em
    diretorio isolado. Compara contra baseline sequencial 1-process.

Hipoteses (mock-based v1):
    H1: Speedup N=2 ~= 1.7-1.9x (overhead spawn ~3s no Windows + AV).
    H2: Speedup N=4 ~= 3.0-3.4x (gap vs target 3.2x = 80% efficiency).
    H3: Spawn overhead Windows e dominante em jobs curtos (< 30s) — bench
        usa job de 50k trades x 2 chunks = ~20s/job para validar crossover.

Output:
    benchmarks/results/baselines_v1_mock/bench_multi_symbol-{date}-{git_sha}.json

NOTA Pyro+Sol+Aria (COUNCIL-10):
    Usa multiprocessing.Pool (Windows spawn). Cada worker rebuild full
    Orchestrator + DLL mock — overhead de spawn medido separadamente.
"""

from __future__ import annotations

import multiprocessing as mp
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

TARGET_SPEEDUP_N4 = 3.2
TRADES_PER_CHUNK = 25_000  # menor para nao explodir tempo total
N_CHUNKS = 2
RUNS_PER_N = 2  # 2 runs por configuracao (estabilidade vs tempo)
N_PROCESSES_LIST = [1, 2, 4]  # 8 omitido (8 cores logicos = saturacao incerta)


# =====================================================================
# Worker (top-level: required by Windows spawn pickling)
# =====================================================================


def _worker_run_pipeline(args: tuple[str, str, int, int]) -> dict[str, Any]:
    """Top-level function: roda pipeline mock para 1 simbolo. Pickle-safe."""
    symbol, data_dir_str, n_chunks, trades_per_chunk = args
    data_dir = Path(data_dir_str)

    # Imports dentro do worker (Windows spawn re-executa o módulo)
    from data_downloader.dll.types import (
        TC_LAST_PACKET,
        SystemTime,
        TConnectorAssetIdentifier,
        TConnectorTrade,
    )
    from data_downloader.orchestrator.orchestrator import JobConfig, Orchestrator
    from data_downloader.storage.catalog import Catalog
    from data_downloader.storage.parquet_writer import ParquetWriter

    # Mock DLL inline (replica padrao do test suite)
    class _FakeProfitDLL:
        def __init__(self, rounds: list[dict[str, Any]]) -> None:
            self.rounds = rounds
            self.dll_version = "4.0.0.30-mock"
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
            cfg = self.rounds[self._round_idx]
            self._round_idx += 1
            self._current_specs = cfg.get("trade_specs", [])
            t = threading.Thread(
                target=self._emit, args=(ticker, list(self._current_specs)), daemon=True
            )
            t.start()
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
            struct.BuyAgent = 0
            struct.SellAgent = 0
            struct.TradeType = 1
            return 0

        def _emit(self, ticker: str, specs: list[dict[str, Any]]) -> None:
            time.sleep(0.001)
            asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
            n = len(specs)
            for i, _spec in enumerate(specs):
                if self._history_cb is None:
                    break
                flags = TC_LAST_PACKET if i == n - 1 else 0
                self._history_cb(asset, i, flags)
            for p in [50, 100]:
                if self._progress_cb is None:
                    break
                self._progress_cb(ticker, "F", 0, p)

    # Build rounds (1 round/chunk) — datas distintas por simbolo para evitar overlap
    base_dates = [
        datetime(2026, 3, 2, 9, 0, 0),
        datetime(2026, 3, 9, 9, 0, 0),
        datetime(2026, 3, 16, 9, 0, 0),
        datetime(2026, 3, 23, 9, 0, 0),
    ][:n_chunks]
    rounds = []
    for base in base_dates:
        specs = []
        for i in range(trades_per_chunk):
            sec_off = i // 1000
            us_off = (i % 1000) * 1000
            ts = base.replace(
                hour=min(base.hour + sec_off // 3600, 17),
                minute=min((base.minute + (sec_off // 60) % 60), 59),
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
        rounds.append({"trade_specs": specs})

    dll = _FakeProfitDLL(rounds=rounds)
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    writer = ParquetWriter(data_dir=data_dir)

    config = JobConfig(
        symbol=symbol,
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
    catalog.close()

    return {
        "symbol": symbol,
        "duration_ms": (t1 - t0) / 1e6,
        "status": result.status,
        "trades_persisted": result.metrics.trades_persisted,
    }


# =====================================================================
# Spawn overhead bench (separado)
# =====================================================================


def _noop_worker(_: int) -> int:
    return 1


def measure_spawn_overhead(n_samples: int = 5) -> dict[str, float]:
    """Mede overhead de spawn de 1 worker no Windows."""
    times: list[float] = []
    for _ in range(n_samples):
        t0 = time.perf_counter()
        with mp.Pool(processes=1) as pool:
            pool.map(_noop_worker, [0])
        times.append(time.perf_counter() - t0)
    return {
        "spawn_p50_s": statistics.median(times),
        "spawn_p99_s": percentile(times, 0.99),
        "spawn_n_samples": n_samples,
    }


# =====================================================================
# Main
# =====================================================================


# Symbols WDO consecutivos (cada processo escreve em PartitionKey distinto via symbol)
SYMBOLS = ["WDOJ26", "WDOK26", "WDON26", "WDOQ26", "WDOU26", "WDOV26", "WDOX26", "WDOZ26"]


def measure_n_processes(n: int, tmp_root: Path) -> dict[str, Any]:
    """Roda N workers em paralelo via Pool."""
    symbols = SYMBOLS[:n]
    args_list = [(sym, str(tmp_root / f"sym_{sym}"), N_CHUNKS, TRADES_PER_CHUNK) for sym in symbols]
    # Cria diretorios antes do spawn
    for _, d, _, _ in args_list:
        Path(d).mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    with mp.Pool(processes=n) as pool:
        results = pool.map(_worker_run_pipeline, args_list)
    wall_s = time.perf_counter() - t0

    total_trades = sum(r["trades_persisted"] for r in results)
    return {
        "n_processes": n,
        "wall_time_s": wall_s,
        "total_trades_persisted": total_trades,
        "agg_throughput_trades_per_sec": (total_trades / wall_s) if wall_s > 0 else 0.0,
        "per_worker_duration_ms_p50": statistics.median([r["duration_ms"] for r in results]),
        "all_status_completed": all(r["status"] == "completed" for r in results),
    }


def main() -> None:
    # Required for Windows spawn
    mp.freeze_support()

    print("[bench_multi_symbol] measuring spawn overhead...")
    spawn = measure_spawn_overhead(n_samples=5)
    print(f"  spawn p50={spawn['spawn_p50_s']:.3f}s  p99={spawn['spawn_p99_s']:.3f}s")

    tmp_root = Path(tempfile.mkdtemp(prefix="bench_msym_"))
    runs_by_n: dict[int, list[dict[str, Any]]] = {}

    try:
        for n in N_PROCESSES_LIST:
            runs_by_n[n] = []
            for run_idx in range(RUNS_PER_N):
                run_dir = tmp_root / f"n{n}_r{run_idx}"
                run_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n[N={n} run={run_idx}/{RUNS_PER_N}]")
                res = measure_n_processes(n, run_dir)
                print(
                    f"  wall={res['wall_time_s']:.2f}s  "
                    f"agg_tps={res['agg_throughput_trades_per_sec']:_.0f}/s  "
                    f"per_worker_ms_p50={res['per_worker_duration_ms_p50']:.0f}  "
                    f"all_ok={res['all_status_completed']}"
                )
                runs_by_n[n].append(res)

        # Compute speedups (vs N=1 baseline mediana)
        baseline_wall = statistics.median([r["wall_time_s"] for r in runs_by_n[1]])

        scenarios: list[dict[str, Any]] = []
        for n, runs in runs_by_n.items():
            walls = [r["wall_time_s"] for r in runs]
            agg_tps = [r["agg_throughput_trades_per_sec"] for r in runs]
            wall_p50 = statistics.median(walls)
            speedup = (baseline_wall * n) / wall_p50 if wall_p50 > 0 else 0.0
            efficiency_pct = (speedup / n) * 100 if n > 0 else 0.0
            scenarios.append(
                {
                    "n_processes": n,
                    "wall_time_s_p50": wall_p50,
                    "wall_time_s_p99": percentile(walls, 0.99),
                    "agg_throughput_p50": statistics.median(agg_tps),
                    "speedup_vs_n1": speedup,
                    "efficiency_pct": efficiency_pct,
                    "all_runs_completed": all(r["all_status_completed"] for r in runs),
                }
            )

        n4 = next((s for s in scenarios if s["n_processes"] == 4), None)
        n4_speedup = n4["speedup_vs_n1"] if n4 else 0.0

        summary = {
            "spawn_overhead_per_proc_p50_s": spawn["spawn_p50_s"],
            "scenarios_summary": [
                {
                    "n": s["n_processes"],
                    "wall_p50_s": round(s["wall_time_s_p50"], 2),
                    "speedup": round(s["speedup_vs_n1"], 2),
                    "efficiency_pct": round(s["efficiency_pct"], 1),
                }
                for s in scenarios
            ],
            "n4_speedup_vs_target": {
                "target": TARGET_SPEEDUP_N4,
                "measured": round(n4_speedup, 2),
                "verdict": ("PASS" if n4_speedup >= TARGET_SPEEDUP_N4 else "FAIL"),
            },
            "n4_speedup": n4_speedup,
            "trades_per_chunk_mock": TRADES_PER_CHUNK,
            "n_chunks_per_job": N_CHUNKS,
        }

        envelope = build_result_envelope(
            "bench_multi_symbol",
            config={
                "n_processes_list": N_PROCESSES_LIST,
                "runs_per_n": RUNS_PER_N,
                "trades_per_chunk": TRADES_PER_CHUNK,
                "n_chunks_per_job": N_CHUNKS,
                "spawn_strategy": "multiprocessing.Pool (Windows spawn)",
                "target_speedup_n4": TARGET_SPEEDUP_N4,
            },
            scenarios=scenarios,
            summary=summary,
            notes=(
                "Mock pipeline N processos paralelo (Windows spawn). Cada worker "
                "tem seu DLL mock + Catalog + Writer isolados. Speedup baseline = N=1. "
                "Baseline v1.1.0-mock — aguarda smoke real (Story 1.7b-followup)."
            ),
            dll_version="4.0.0.30-mock",
        )
        path = save_results(envelope)
        baseline_dir = path.parent / "baselines_v1_mock"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = baseline_dir / "bench_multi_symbol-1.1.0-mock.json"
        shutil.copy(path, baseline_path)

        print(f"\n[bench_multi_symbol] resultados: {path}")
        print(f"[bench_multi_symbol] baseline copy: {baseline_path}")
        print_summary(envelope)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
