"""bench_multi_symbol.py — N processos em paralelo (multi-symbol download).

Objetivo:
    Medir speedup, contention de disco, CPU/mem total ao baixar N símbolos
    em paralelo via multiprocessing (cada processo com sua própria DLL).
    CRÍTICO: medir crossover Windows spawn overhead (finding H20) — para
    downloads curtos, spawn (~3s/processo) pode anular ganho.

Target V1:
    Speedup >= 3.2x para N=4 (80% efficiency) OU aceitar limitação documentada
    com WAIVER + recomendação de "para downloads < X minutos, usar sequencial".

Hipóteses a testar:
    H1: Para downloads >= 10min, multi-process N=4 atinge 3.2x speedup.
    H2: Para downloads < 1min (1 dia ~1min), spawn overhead 4×3s = 12s
        anula ganho — sequencial vence (finding H20).
    H3: Crossover está entre 2-5 minutos por job — bench acha valor exato.
    H4: Contention de SQLite catalog (multi-writer) é resolvida por ADR-013
        (broker pattern) — sem broker, N=4 gera SQLITE_BUSY frequente.
    H5: N=8 saturação de CPU + IO; speedup cai a ~5x (não 8x).

Cenários (matriz):
    n_processes: [1, 2, 4, 8]
    job_duration_target_min: [0.5, 2, 10, 30]  # seu downloads de 30s, 2min, 10min, 30min
    catalog_strategy: ["broker", "shared_sqlite_busy_retry"]

Output:
    benchmarks/results/bench_multi_symbol-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_multi_symbol",
        "scenarios": [
            {"n_processes": 4, "job_duration_min": 10, "catalog_strategy": "broker",
             "total_wall_time_s": 0, "speedup_vs_sequential": 0,
             "efficiency_pct": 0, "spawn_overhead_total_s": 0,
             "cpu_peak_pct": 0, "rss_peak_mb": 0, "sqlite_busy_count": 0}
        ],
        "crossover_analysis": {
            "crossover_min_per_job": "TBD"  # job menor que isso = sequencial vence
        }
    }
"""

from __future__ import annotations

import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

# TODO: imports
# import multiprocessing
# import psutil
# from benchmarks.fixtures.mock_dll import MockProfitDLL

RESULTS_DIR = Path(__file__).parent / "results"
TARGET_SPEEDUP_N4 = 3.2

SCENARIOS = [
    {"n_processes": n, "job_duration_min": d, "catalog_strategy": s}
    for n in [1, 2, 4, 8]
    for d in [0.5, 2, 10, 30]
    for s in ["broker", "shared_sqlite_busy_retry"]
]


def measure_spawn_overhead() -> float:
    """Mede tempo médio de spawn de 1 worker no Windows."""
    # TODO:
    # times = []
    # for _ in range(5):
    #     t0 = time.perf_counter_ns()
    #     p = multiprocessing.Process(target=_noop_worker)
    #     p.start()
    #     p.join()
    #     times.append((time.perf_counter_ns() - t0) / 1e9)
    # return statistics.median(times)
    raise NotImplementedError("Aguarda implementação")


def measure_scenario(scenario: dict[str, Any], tmp_dir: Path) -> dict[str, Any]:
    """N processos baixam N símbolos em paralelo; mede wall time."""
    # TODO:
    # n_proc = scenario["n_processes"]
    # symbols = [f"WDOJ26", f"WDOK26", f"WDON26", f"WDOQ26"][:n_proc]
    #
    # process = psutil.Process()
    # cpu_samples: list[float] = []
    # rss_samples: list[float] = []
    #
    # t0 = time.perf_counter_ns()
    # workers = [
    #     multiprocessing.Process(
    #         target=_worker_download,
    #         args=(sym, scenario["job_duration_min"], tmp_dir,
    #               scenario["catalog_strategy"]),
    #     )
    #     for sym in symbols
    # ]
    # for w in workers:
    #     w.start()
    # # sample CPU/RSS during run
    # while any(w.is_alive() for w in workers):
    #     cpu_samples.append(psutil.cpu_percent(interval=0.5))
    #     rss_samples.append(_total_rss_mb([w.pid for w in workers]))
    # for w in workers:
    #     w.join()
    # wall_time_s = (time.perf_counter_ns() - t0) / 1e9
    #
    # # Comparar contra baseline n=1 (mesma duration)
    # baseline_s = scenario["job_duration_min"] * 60 * n_proc  # tempo se sequencial
    # speedup = baseline_s / wall_time_s
    # efficiency = speedup / n_proc * 100
    #
    # return {
    #     **scenario,
    #     "total_wall_time_s": wall_time_s,
    #     "speedup_vs_sequential": speedup,
    #     "efficiency_pct": efficiency,
    #     "cpu_peak_pct": max(cpu_samples),
    #     "rss_peak_mb": max(rss_samples),
    #     "sqlite_busy_count": _read_metric("sqlite_busy_total"),
    # }
    raise NotImplementedError("Aguarda Orchestrator + ADR-013 broker")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO:
    # spawn_overhead = measure_spawn_overhead()
    # results = [measure_scenario(s, tmp_dir) for s in SCENARIOS]
    # # Crossover: menor job_duration onde N=4 ainda vence sequencial
    # crossover = _compute_crossover(results, spawn_overhead)
    # output = {
    #     "benchmark": "bench_multi_symbol",
    #     "spawn_overhead_per_process_s": spawn_overhead,
    #     "scenarios": results,
    #     "crossover_analysis": {"crossover_min_per_job": crossover},
    # }
    raise NotImplementedError(
        "bench_multi_symbol é CRÍTICO (Story 1.4.5). "
        "Cenário N=4 + crossover validam findings H20 + ADR-013."
    )


if __name__ == "__main__":
    main()
