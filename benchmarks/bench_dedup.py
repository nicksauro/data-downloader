"""bench_dedup.py — Throughput de dedup.

Objetivo:
    Medir tempo e throughput de dedup ao receber batches de trades com fração
    variável de duplicatas, varrendo matriz batch_size × duplicate_pct.

Target V1:
    < 50ms para batch de 10k trades (qualquer % de duplicatas).

Hipóteses a testar:
    H1: Dedup via set/dict de hash(trade_id) é O(n) e satura para 10k em < 50ms.
    H2: Quando trade_id é NULL (Quirk Q-DLL-X), fallback hash(price, qty,
        sequence_within_ns, timestamp_ns) é ~1.5x mais lento que trade_id puro
        (finding H2 do plan review).
    H3: Para batches grandes (>= 1M), bottleneck migra de dict construction
        para hash function — considerar hash batched (numpy).

Cenários (matriz):
    batch_size: [10_000, 100_000, 1_000_000]
    duplicate_pct: [0.0, 0.01, 0.10]
    dedup_key: ["trade_id", "fallback_composite"]  # 2 estratégias

Output:
    benchmarks/results/bench_dedup-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_dedup",
        "config_matrix": [
            {"batch_size": 10000, "duplicate_pct": 0.01, "dedup_key": "trade_id",
             "elapsed_ms_p50": 0, "throughput_trades_per_sec": 0,
             "n_unique_returned": 0}
        ]
    }
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

# TODO: imports
# from benchmarks.fixtures.synthetic_trades import generate
# from data_downloader.dedup import dedup_batch  # Sol Story 1.4

RESULTS_DIR = Path(__file__).parent / "results"
N_RUNS_PER_CONFIG = 10
TARGET_MS_BATCH_10K = 50.0

CONFIG_MATRIX: list[dict[str, Any]] = []
for batch_size in [10_000, 100_000, 1_000_000]:
    for dup_pct in [0.0, 0.01, 0.10]:
        for key in ["trade_id", "fallback_composite"]:
            CONFIG_MATRIX.append(
                {"batch_size": batch_size, "duplicate_pct": dup_pct, "dedup_key": key}
            )


def setup_batch(batch_size: int, duplicate_pct: float, dedup_key: str) -> list[dict[str, Any]]:
    """Gera batch sintético com `duplicate_pct` * batch_size duplicatas."""
    # TODO: gerar via fixtures.synthetic_trades + injetar duplicatas
    # n_unique = int(batch_size * (1 - duplicate_pct))
    # n_dup = batch_size - n_unique
    # uniques = list(generate(n_unique))
    # dups = random.choices(uniques, k=n_dup)
    # batch = uniques + dups
    # random.shuffle(batch)
    # if dedup_key == "trade_id":
    #     pass  # trade_id já é unique; fixtures gera incremental
    # else:  # fallback_composite — zera trade_id, usa hash composto
    #     for t in batch:
    #         t["trade_id"] = None
    # return batch
    raise NotImplementedError("Aguarda fixtures.synthetic_trades")


def measure_dedup(batch: list[dict[str, Any]], dedup_key: str) -> dict[str, Any]:
    """Roda dedup, mede tempo, valida n_unique correto."""
    # TODO:
    # t0 = time.perf_counter_ns()
    # unique = dedup_batch(batch, key_strategy=dedup_key)
    # elapsed_ns = time.perf_counter_ns() - t0
    # return {
    #     "elapsed_ns": elapsed_ns,
    #     "n_in": len(batch),
    #     "n_out": len(unique),
    # }
    raise NotImplementedError("Aguarda data_downloader.dedup (Story 1.4)")


def run_config(config: dict[str, Any]) -> dict[str, Any]:
    """N runs, descarta primeiro warmup."""
    runs: list[dict[str, Any]] = []
    for _ in range(N_RUNS_PER_CONFIG + 1):
        batch = setup_batch(**config)
        runs.append(measure_dedup(batch, config["dedup_key"]))
    runs = runs[1:]  # drop warmup

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    return {
        **config,
        "n_runs": N_RUNS_PER_CONFIG,
        "elapsed_ms_p50": statistics.median(elapsed_ms),
        "elapsed_ms_p95": sorted(elapsed_ms)[int(0.95 * len(elapsed_ms))],
        "elapsed_ms_p99": max(elapsed_ms),
        "throughput_trades_per_sec": config["batch_size"] / (statistics.median(elapsed_ms) / 1000),
        "n_unique_returned": runs[0]["n_out"],
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO: rodar matriz, salvar JSON, comparar vs TARGET
    raise NotImplementedError(
        "bench_dedup é esqueleto sintético (Story 1.4.5)."
    )


if __name__ == "__main__":
    main()
