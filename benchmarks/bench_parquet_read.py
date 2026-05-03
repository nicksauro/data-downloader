"""bench_parquet_read.py — Throughput de leitura full scan via DuckDB.

Objetivo:
    Medir trades/s ao fazer SELECT * FROM parquet_scan(...) sobre 10M trades
    distribuídos em N arquivos Parquet (matriz produzida por bench_parquet_write).

Target V1:
    >= 1M trades/s single thread.

Hipóteses a testar:
    H1: DuckDB single-thread satura memory bandwidth antes de saturar CPU.
    H2: row_group_size maior (500k) acelera full scan vs 100k (menos overhead
        de metadata) — mas piora bench_parquet_read_filtered.
    H3: Snappy decompression é faster que ZSTD para full scan
        (CPU > memory bandwidth).

Output:
    benchmarks/results/bench_parquet_read-{date}-{git_sha}.json

JSON schema (resumido):
    {
        "benchmark": "bench_parquet_read",
        "git_sha": "...",
        "hardware": {...},
        "n_trades_total": 10000000,
        "config_matrix": [
            {"row_group_size": 100000, "compression": "snappy",
             "n_files": 10, "trades_per_sec": 0,
             "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "n_runs": 5}
        ],
        "winner": {...},
        "verdict": "PASS|FAIL vs target"
    }
"""

from __future__ import annotations

import json  # noqa: F401  # used by commented-out skeleton body
import statistics
import time  # noqa: F401  # used by commented-out skeleton body
from pathlib import Path
from typing import Any

# TODO: imports reais
# import duckdb
# from benchmarks.fixtures.synthetic_trades import generate

RESULTS_DIR = Path(__file__).parent / "results"
N_TRADES_TOTAL = 10_000_000
N_RUNS_PER_CONFIG = 5
TARGET_TRADES_PER_SEC = 1_000_000

# Reusa configs winner de bench_parquet_write
CONFIG_MATRIX: list[dict[str, Any]] = [
    {"row_group_size": 100_000, "compression": "snappy"},
    {"row_group_size": 500_000, "compression": "snappy"},
    {"row_group_size": 100_000, "compression": "zstd", "compression_level": 1},
    {"row_group_size": 100_000, "compression": None},
]


def setup_parquet_files(config: dict[str, Any], tmp_dir: Path) -> list[Path]:
    """Gera 10M trades, particiona em arquivos Parquet conforme config."""
    # TODO: usar fixtures.synthetic_trades + pyarrow para particionar
    raise NotImplementedError("Aguarda fixtures.synthetic_trades")


def measure_full_scan(parquet_files: list[Path]) -> dict[str, Any]:
    """SELECT COUNT(*) + sum(qty) full scan via DuckDB single-thread."""
    # TODO:
    # con = duckdb.connect(":memory:", config={"threads": 1})
    # glob = str(parquet_files[0].parent / "*.parquet")
    # t0 = time.perf_counter_ns()
    # result = con.execute(f"SELECT COUNT(*) AS n, SUM(quantity) AS s "
    #                       f"FROM parquet_scan('{glob}')").fetchone()
    # elapsed_ns = time.perf_counter_ns() - t0
    # n_trades = result[0]
    # return {
    #     "elapsed_ns": elapsed_ns,
    #     "trades_per_sec": n_trades / (elapsed_ns / 1e9),
    #     "n_trades": n_trades,
    # }
    raise NotImplementedError("Aguarda código de produção (Story 1.5)")


def run_config(config: dict[str, Any], tmp_dir: Path) -> dict[str, Any]:
    """Roda N_RUNS por config; descarta primeiro (cold cache)."""
    parquet_files = setup_parquet_files(config, tmp_dir)
    runs: list[dict[str, Any]] = []
    # Warmup: 1 run descartada (page cache)
    measure_full_scan(parquet_files)
    for _ in range(N_RUNS_PER_CONFIG):
        runs.append(measure_full_scan(parquet_files))

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    return {
        **config,
        "n_files": len(parquet_files),
        "n_runs": N_RUNS_PER_CONFIG,
        "trades_per_sec": statistics.median(r["trades_per_sec"] for r in runs),
        "p50_ms": statistics.median(elapsed_ms),
        "p95_ms": sorted(elapsed_ms)[int(0.95 * len(elapsed_ms))],
        "p99_ms": max(elapsed_ms),
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO: rodar matriz, salvar JSON, comparar vs target
    raise NotImplementedError(
        "bench_parquet_read é esqueleto sintético (Story 1.4.5). "
        "Implementação completa em Story 1.8."
    )


if __name__ == "__main__":
    main()
