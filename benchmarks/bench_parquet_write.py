"""bench_parquet_write.py — Throughput de escrita Parquet (synthetic).

Objetivo:
    Medir trades/s sustained, MB/s e peak memory ao escrever 10M trades
    sintéticos via PyArrow para Parquet, varrendo matriz de row_group_size
    × compression.

Target V1:
    >= 100k trades/s sustained.

Hipóteses a testar:
    H1: row_group_size=100k é Pareto-ótimo entre throughput de write e
        seletividade de read (validar contra bench_parquet_read_filtered).
    H2: Snappy é faster que ZSTD-1 para write, mas ZSTD-1 é Pareto-dominante
        considerando tamanho on-disk (finding H5 do plan review).
    H3: PyArrow batch writer com chunks pequenos não satura disco NVMe
        — gargalo é serialização Python -> Arrow, não IO.

Output:
    benchmarks/results/bench_parquet_write-{date}-{git_sha}.json

JSON schema (resumido):
    {
        "benchmark": "bench_parquet_write",
        "git_sha": "...",
        "hardware": {...},
        "config_matrix": [
            {"row_group_size": 100000, "compression": "snappy",
             "trades_per_sec": 0, "mb_per_sec": 0, "peak_rss_mb": 0,
             "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "n_runs": 5}
        ],
        "winner": {"row_group_size": ..., "compression": ...},
        "verdict": "PASS|FAIL vs target"
    }
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

# TODO: imports reais quando código de produção existir
# import pyarrow as pa
# import pyarrow.parquet as pq
# import psutil
# from benchmarks.fixtures.synthetic_trades import generate

RESULTS_DIR = Path(__file__).parent / "results"
N_TRADES_TOTAL = 10_000_000
N_RUNS_PER_CONFIG = 5

CONFIG_MATRIX: list[dict[str, Any]] = [
    {"row_group_size": 50_000, "compression": "snappy"},
    {"row_group_size": 100_000, "compression": "snappy"},
    {"row_group_size": 500_000, "compression": "snappy"},
    {"row_group_size": 100_000, "compression": "zstd", "compression_level": 1},
    {"row_group_size": 100_000, "compression": "zstd", "compression_level": 3},
    {"row_group_size": 100_000, "compression": None},  # uncompressed baseline
]


def setup() -> Any:
    """Gera 10M trades sintéticos em memória (pa.Table)."""
    # TODO: implementar quando fixtures/synthetic_trades.py estiver pronto
    # trades = list(generate(N_TRADES_TOTAL, symbol="WDOJ26"))
    # return pa.Table.from_pylist(trades)
    raise NotImplementedError("Aguarda implementação de fixtures.synthetic_trades")


def measure(table: Any, config: dict[str, Any], output_path: Path) -> dict[str, Any]:
    """Escreve `table` para Parquet usando `config`. Retorna métricas."""
    # TODO: implementar
    # process = psutil.Process()
    # rss_before = process.memory_info().rss
    # t0 = time.perf_counter_ns()
    # pq.write_table(
    #     table, output_path,
    #     row_group_size=config["row_group_size"],
    #     compression=config["compression"],
    #     compression_level=config.get("compression_level"),
    #     use_dictionary=True,
    #     write_statistics=True,
    # )
    # elapsed_ns = time.perf_counter_ns() - t0
    # rss_peak = process.memory_info().rss
    # disk_size = output_path.stat().st_size
    # return {
    #     "elapsed_ns": elapsed_ns,
    #     "trades_per_sec": N_TRADES_TOTAL / (elapsed_ns / 1e9),
    #     "mb_per_sec": (disk_size / 1e6) / (elapsed_ns / 1e9),
    #     "peak_rss_mb": (rss_peak - rss_before) / 1e6,
    #     "disk_size_mb": disk_size / 1e6,
    # }
    raise NotImplementedError("Aguarda implementação de produção (Story 1.4)")


def run_config(table: Any, config: dict[str, Any], tmp_dir: Path) -> dict[str, Any]:
    """Roda N_RUNS_PER_CONFIG e retorna estatísticas agregadas."""
    runs: list[dict[str, Any]] = []
    for i in range(N_RUNS_PER_CONFIG):
        out = tmp_dir / f"run_{i}.parquet"
        runs.append(measure(table, config, out))
        out.unlink(missing_ok=True)

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    return {
        **config,
        "n_runs": N_RUNS_PER_CONFIG,
        "trades_per_sec": statistics.median(r["trades_per_sec"] for r in runs),
        "mb_per_sec": statistics.median(r["mb_per_sec"] for r in runs),
        "peak_rss_mb": max(r["peak_rss_mb"] for r in runs),
        "disk_size_mb": statistics.median(r["disk_size_mb"] for r in runs),
        "p50_ms": statistics.median(elapsed_ms),
        "p95_ms": sorted(elapsed_ms)[int(0.95 * len(elapsed_ms))],
        "p99_ms": max(elapsed_ms),
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO: criar tmp_dir, capturar git_sha + hardware info
    # table = setup()
    # results = [run_config(table, cfg, tmp_dir) for cfg in CONFIG_MATRIX]
    # winner = max(results, key=lambda r: r["trades_per_sec"])
    # output = {
    #     "benchmark": "bench_parquet_write",
    #     "git_sha": _get_git_sha(),
    #     "hardware": _get_hardware_info(),
    #     "n_trades_total": N_TRADES_TOTAL,
    #     "config_matrix": results,
    #     "winner": {"row_group_size": winner["row_group_size"],
    #                "compression": winner["compression"]},
    #     "target_trades_per_sec": 100_000,
    #     "verdict": "PASS" if winner["trades_per_sec"] >= 100_000 else "FAIL",
    # }
    # _save_results(output)
    raise NotImplementedError(
        "bench_parquet_write é esqueleto sintético (Story 1.4.5). "
        "Implementação completa em Story 1.8 (após código de produção pronto)."
    )


if __name__ == "__main__":
    main()
