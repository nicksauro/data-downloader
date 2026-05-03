"""bench_boot_cleanup.py — Cleanup de orphan tmp files no boot.

Objetivo:
    Medir tempo de scan + delete de partições .tmp órfãs (resíduos de crashes
    anteriores) durante boot do orchestrator. Cenários: 100, 1k, 10k partições
    simuladas.

Target V1:
    < 1s para 10k partições (boot não percebe lag visível).

Contexto (finding L3 do plan review):
    Cleanup escopado a `job ativo` no MVP — full sweep só na 1a vez ou
    quando explicitamente solicitado (`*cleanup-full`). Bench valida ambos:
    full sweep e scoped.

Hipóteses a testar:
    H1: Para 10k arquivos, `os.scandir` é ~5x mais rápido que `glob` recursivo.
    H2: Cleanup escopado a 1 job (~50 partições) é < 50ms — invisível.
    H3: Para 10k arquivos, bottleneck é IO de stat() — não a deleção.
    H4: Em SSD NVMe, target < 1s é atingível; em HDD, falha (warning).

Cenários:
    n_orphans: [100, 1_000, 10_000]
    strategy: ["scoped_to_active_job", "full_sweep"]
    storage: ["ssd_nvme", "ssd_sata", "hdd"]  # informational; user reporta

Output:
    benchmarks/results/bench_boot_cleanup-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_boot_cleanup",
        "scenarios": [
            {"n_orphans": 10000, "strategy": "full_sweep",
             "elapsed_ms_p50": 0, "elapsed_ms_p99": 0,
             "n_deleted": 10000, "n_errors": 0}
        ]
    }
"""

from __future__ import annotations

import os
import json
import statistics
import time
from pathlib import Path
from typing import Any

# TODO: imports
# from data_downloader.cleanup import cleanup_orphans, cleanup_scoped

RESULTS_DIR = Path(__file__).parent / "results"
TARGET_MS_10K = 1000.0
N_RUNS_PER_CONFIG = 5

SCENARIOS = [
    {"n_orphans": n, "strategy": s}
    for n in [100, 1_000, 10_000]
    for s in ["scoped_to_active_job", "full_sweep"]
]


def setup_orphan_files(n_orphans: int, tmp_dir: Path) -> None:
    """Cria N arquivos .tmp órfãos em estrutura realista de partições."""
    # TODO:
    # # Estrutura: data/WDOJ26/2026/04/2026-04-01/chunk_*.parquet.tmp
    # for i in range(n_orphans):
    #     symbol = f"WDO{['J','K','N','Q'][i % 4]}26"
    #     date = f"2026-04-{(i % 30) + 1:02d}"
    #     d = tmp_dir / "data" / symbol / "2026" / "04" / date
    #     d.mkdir(parents=True, exist_ok=True)
    #     (d / f"chunk_{i}.parquet.tmp").write_bytes(b"x" * 100)
    raise NotImplementedError("Aguarda layout definido por Sol (Story 0.0)")


def measure_cleanup(tmp_dir: Path, strategy: str) -> dict[str, Any]:
    """Roda cleanup, mede tempo + n_deleted."""
    # TODO:
    # t0 = time.perf_counter_ns()
    # if strategy == "scoped_to_active_job":
    #     n_deleted, n_errors = cleanup_scoped(tmp_dir, active_job_id="job_001")
    # else:
    #     n_deleted, n_errors = cleanup_orphans(tmp_dir)
    # elapsed_ns = time.perf_counter_ns() - t0
    # return {"elapsed_ns": elapsed_ns, "n_deleted": n_deleted, "n_errors": n_errors}
    raise NotImplementedError("Aguarda data_downloader.cleanup (Story 1.5)")


def run_scenario(scenario: dict[str, Any], tmp_dir: Path) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for _ in range(N_RUNS_PER_CONFIG):
        # cada run precisa recriar orphans (pois cleanup deletou)
        setup_orphan_files(scenario["n_orphans"], tmp_dir)
        runs.append(measure_cleanup(tmp_dir, scenario["strategy"]))

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    return {
        **scenario,
        "n_runs": N_RUNS_PER_CONFIG,
        "elapsed_ms_p50": statistics.median(elapsed_ms),
        "elapsed_ms_p95": sorted(elapsed_ms)[int(0.95 * len(elapsed_ms))],
        "elapsed_ms_p99": max(elapsed_ms),
        "n_deleted_p50": statistics.median(r["n_deleted"] for r in runs),
        "n_errors_total": sum(r["n_errors"] for r in runs),
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO:
    # results = [run_scenario(s, tmp_dir) for s in SCENARIOS]
    # verdict = "PASS" if max(r["elapsed_ms_p99"] for r in results
    #                          if r["n_orphans"] == 10000) < TARGET_MS_10K else "FAIL"
    raise NotImplementedError(
        "bench_boot_cleanup é esqueleto sintético (Story 1.4.5)."
    )


if __name__ == "__main__":
    main()
