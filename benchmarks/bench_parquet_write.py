"""bench_parquet_write.py — Throughput de escrita Parquet (synthetic).

Objetivo:
    Medir trades/s sustained, MB/s e peak memory ao escrever N trades
    sintéticos via PyArrow para Parquet, varrendo matriz de
    row_group_size x compression. Adicionalmente, mede o throughput do
    ``ParquetWriter`` de produção (validações + dedup + fsync) na config
    canônica (ADR-002: snappy + row_group=100k).

Target V1:
    >= 100k trades/s sustained.

Hipóteses a testar:
    H1: row_group_size=100k é Pareto-ótimo entre throughput de write e
        seletividade de read (validar contra bench_parquet_read).
    H2: Snappy é faster que ZSTD-1 para write, mas ZSTD-1 é Pareto-dominante
        considerando tamanho on-disk.
    H3: PyArrow batch writer com chunks pequenos não satura disco NVMe
        — gargalo é serialização Python -> Arrow, não IO.

Notas de execução:
    - Default N_TRADES_TOTAL = 1_000_000 (host modesto). 10M opcional
      via ``--n-trades 10000000``. 1M é suficiente para baseline; 10M
      apenas para validar sustentabilidade de throughput em batch grande.
    - ParquetWriter overhead inclui dedup + fsync + SHA256 — esperado
      ser 2-3x mais lento que pq.write_table direto.

Output:
    benchmarks/results/bench_parquet_write-{date}-{git_sha}.json
"""

from __future__ import annotations

import argparse
import gc
import shutil
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

import psutil
import pyarrow as pa
import pyarrow.parquet as pq

from benchmarks._common import (
    DEFAULT_N_RUNS,
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from benchmarks.fixtures.synthetic_trades import generate_batch_arrow
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey

DEFAULT_N_TRADES_TOTAL = 1_000_000
TARGET_TRADES_PER_SEC = 100_000

CONFIG_MATRIX: list[dict[str, Any]] = [
    # (row_group_size, compression[, compression_level])
    {"row_group_size": 10_000, "compression": "snappy"},
    {"row_group_size": 50_000, "compression": "snappy"},
    {"row_group_size": 100_000, "compression": "snappy"},
    {"row_group_size": 250_000, "compression": "snappy"},
    {"row_group_size": 1_000_000, "compression": "snappy"},
    {"row_group_size": 100_000, "compression": "zstd", "compression_level": 1},
    {"row_group_size": 100_000, "compression": "zstd", "compression_level": 3},
    {"row_group_size": 100_000, "compression": None},  # uncompressed
]


def setup_table(n_trades: int) -> pa.Table:
    """Gera N trades sintéticos como pa.Table."""
    return generate_batch_arrow(n_trades, symbol="WDOJ26")


def measure_pq_write(
    table: pa.Table,
    config: dict[str, Any],
    output_path: Path,
    n_trades: int,
) -> dict[str, Any]:
    """Escreve `table` para Parquet usando `config` raw (pq.write_table)."""
    process = psutil.Process()
    rss_before = process.memory_info().rss
    gc.collect()
    tracemalloc.start()
    t0 = time.perf_counter_ns()
    pq.write_table(
        table,
        output_path,
        row_group_size=config["row_group_size"],
        compression=config["compression"],
        compression_level=config.get("compression_level"),
        use_dictionary=True,
        write_statistics=True,
    )
    elapsed_ns = time.perf_counter_ns() - t0
    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = process.memory_info().rss
    disk_size = output_path.stat().st_size

    return {
        "elapsed_ns": elapsed_ns,
        "trades_per_sec": n_trades / (elapsed_ns / 1e9),
        "mb_per_sec": (disk_size / 1e6) / (elapsed_ns / 1e9),
        "peak_rss_delta_mb": max(0, (rss_after - rss_before) / 1e6),
        "peak_traced_mb": peak_traced / 1e6,
        "disk_size_mb": disk_size / 1e6,
    }


def run_config(
    table: pa.Table,
    config: dict[str, Any],
    tmp_dir: Path,
    n_trades: int,
    n_runs: int,
) -> dict[str, Any]:
    """Roda n_runs medições e retorna estatísticas agregadas."""
    runs: list[dict[str, Any]] = []
    for i in range(n_runs):
        out = tmp_dir / f"run_{i}.parquet"
        runs.append(measure_pq_write(table, config, out, n_trades))
        out.unlink(missing_ok=True)

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    throughputs = [r["trades_per_sec"] for r in runs]
    return {
        **dict(config),
        "compression": config["compression"] if config["compression"] is not None else "none",
        "n_runs": n_runs,
        "trades_per_sec_p50": statistics.median(throughputs),
        "trades_per_sec_p95": percentile(throughputs, 0.05),  # menor é pior aqui
        "trades_per_sec_min": min(throughputs),
        "trades_per_sec_stddev": statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0,
        "mb_per_sec_p50": statistics.median(r["mb_per_sec"] for r in runs),
        "peak_rss_delta_mb_max": max(r["peak_rss_delta_mb"] for r in runs),
        "peak_traced_mb_max": max(r["peak_traced_mb"] for r in runs),
        "disk_size_mb": statistics.median(r["disk_size_mb"] for r in runs),
        "p50_ms": statistics.median(elapsed_ms),
        "p95_ms": percentile(elapsed_ms, 0.95),
        "p99_ms": percentile(elapsed_ms, 0.99),
    }


def measure_production_writer(
    n_trades: int,
    tmp_dir: Path,
    n_runs: int,
) -> dict[str, Any]:
    """Mede throughput do ParquetWriter de produção (validate+dedup+fsync+sha256).

    Diferença vs raw pq.write_table:
    - validate_record por trade
    - assign_sequence_within_ns (quando trade_id NULL)
    - dedup do batch
    - fsync(file) + fsync(parent_dir)
    - SHA256 do arquivo final

    Esperado ser 2-3x mais lento que raw — mas é o que produção usa.
    """
    from benchmarks.fixtures.synthetic_trades import generate

    runs: list[dict[str, Any]] = []
    for i in range(n_runs):
        # ParquetWriter exige TradeRecord list (não pa.Table) — gera fresh.
        trades = list(generate(n_trades, symbol="WDOJ26"))
        # Cada run em data_dir limpo (writer faz merge se já existir).
        run_data_dir = tmp_dir / f"prod_run_{i}"
        run_data_dir.mkdir(parents=True, exist_ok=True)
        writer = ParquetWriter(data_dir=run_data_dir)
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)

        gc.collect()
        process = psutil.Process()
        rss_before = process.memory_info().rss
        t0 = time.perf_counter_ns()
        result = writer.write(trades, partition, dll_version="4.0.0.30-mock", chunk_id=f"bench-{i}")
        elapsed_ns = time.perf_counter_ns() - t0
        rss_after = process.memory_info().rss

        runs.append(
            {
                "elapsed_ns": elapsed_ns,
                "trades_per_sec": result.row_count / (elapsed_ns / 1e9),
                "row_count_after_dedup": result.row_count,
                "disk_size_mb": result.file_size_bytes / 1e6,
                "peak_rss_delta_mb": max(0, (rss_after - rss_before) / 1e6),
            }
        )
        # Cleanup run-specific data dir
        shutil.rmtree(run_data_dir, ignore_errors=True)

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    throughputs = [r["trades_per_sec"] for r in runs]
    return {
        "scenario": "production_writer_canonical",
        "config": "ParquetWriter (snappy + row_group=100k + validate + dedup + fsync + sha256)",
        "n_runs": n_runs,
        "n_trades_input": n_trades,
        "row_count_after_dedup_p50": statistics.median(r["row_count_after_dedup"] for r in runs),
        "trades_per_sec_p50": statistics.median(throughputs),
        "trades_per_sec_min": min(throughputs),
        "trades_per_sec_stddev": statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0,
        "disk_size_mb_p50": statistics.median(r["disk_size_mb"] for r in runs),
        "peak_rss_delta_mb_max": max(r["peak_rss_delta_mb"] for r in runs),
        "p50_ms": statistics.median(elapsed_ms),
        "p95_ms": percentile(elapsed_ms, 0.95),
        "p99_ms": percentile(elapsed_ms, 0.99),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-trades", type=int, default=DEFAULT_N_TRADES_TOTAL, help="trades por run"
    )
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS, help="runs por config")
    parser.add_argument("--skip-prod-writer", action="store_true", help="pula ParquetWriter prod")
    parser.add_argument("--matrix-only", action="store_true", help="só roda matriz (skip prod)")
    args = parser.parse_args()

    n_trades = args.n_trades
    n_runs = args.n_runs

    print(f"[bench_parquet_write] gerando {n_trades:_} trades sintéticos...")
    t0 = time.perf_counter()
    table = setup_table(n_trades)
    gen_elapsed = time.perf_counter() - t0
    gen_rate = n_trades / gen_elapsed
    print(f"[bench_parquet_write] gerados em {gen_elapsed:.1f}s ({gen_rate:_.0f} trades/s)")
    print(f"[bench_parquet_write] table size: {table.nbytes / 1e6:.1f} MB in-mem")

    tmp_root = Path(tempfile.mkdtemp(prefix="bench_pq_write_"))
    try:
        # Matriz raw pq.write_table.
        matrix_results: list[dict[str, Any]] = []
        for cfg in CONFIG_MATRIX:
            comp_label = cfg["compression"] or "none"
            cl = cfg.get("compression_level")
            cl_label = f"-{cl}" if cl else ""
            print(
                f"[bench_parquet_write] config: row_group={cfg['row_group_size']:_}, "
                f"compression={comp_label}{cl_label}"
            )
            res = run_config(table, cfg, tmp_root, n_trades, n_runs)
            matrix_results.append(res)
            print(
                f"  -> p50 throughput: {res['trades_per_sec_p50']:_.0f} trades/s | "
                f"size: {res['disk_size_mb']:.1f} MB | p99 elapsed: {res['p99_ms']:.0f}ms"
            )

        # Production writer.
        prod_result: dict[str, Any] | None = None
        if not args.matrix_only and not args.skip_prod_writer:
            print("[bench_parquet_write] medindo ParquetWriter de produção...")
            prod_result = measure_production_writer(n_trades, tmp_root, n_runs)
            print(
                f"  -> ParquetWriter p50 throughput: "
                f"{prod_result['trades_per_sec_p50']:_.0f} trades/s "
                f"(input {n_trades:_}, dedup -> {prod_result['row_count_after_dedup_p50']:_.0f})"
            )

        # Winner = maior throughput (raw matriz).
        winner = max(matrix_results, key=lambda r: r["trades_per_sec_p50"])
        # Pareto-snappy: melhor snappy (compressão default ADR-002).
        snappy_only = [r for r in matrix_results if r["compression"] == "snappy"]
        snappy_winner = max(snappy_only, key=lambda r: r["trades_per_sec_p50"])

        # Verdict baseado em production writer (já que é o que produção usa).
        prod_throughput = (
            prod_result["trades_per_sec_p50"]
            if prod_result is not None
            else winner["trades_per_sec_p50"]
        )
        verdict = "PASS" if prod_throughput >= TARGET_TRADES_PER_SEC else "FAIL"

        scenarios = matrix_results + ([prod_result] if prod_result else [])
        summary = {
            "winner_raw": {
                "row_group_size": winner["row_group_size"],
                "compression": winner["compression"],
                "trades_per_sec_p50": winner["trades_per_sec_p50"],
            },
            "snappy_winner": {
                "row_group_size": snappy_winner["row_group_size"],
                "trades_per_sec_p50": snappy_winner["trades_per_sec_p50"],
                "disk_size_mb": snappy_winner["disk_size_mb"],
            },
            "production_writer_p50_trades_per_sec": prod_throughput,
            "vs_target": {
                "target_metric": "trades_per_sec (production writer)",
                "target_value": TARGET_TRADES_PER_SEC,
                "measured_value": prod_throughput,
                "delta_pct": ((prod_throughput - TARGET_TRADES_PER_SEC) / TARGET_TRADES_PER_SEC)
                * 100,
            },
            "verdict": verdict,
        }

        envelope = build_result_envelope(
            "bench_parquet_write",
            config={
                "n_trades_per_run": n_trades,
                "n_runs_per_scenario": n_runs,
                "matrix_size": len(CONFIG_MATRIX),
            },
            scenarios=scenarios,
            summary=summary,
            notes=(
                "Synthetic write throughput. Matrix: raw pq.write_table; "
                "production scenario uses data_downloader.storage.ParquetWriter "
                "(validate + dedup + fsync + SHA256)."
            ),
        )
        path = save_results(envelope)
        print(f"\n[bench_parquet_write] resultados salvos em: {path}")
        print_summary(envelope)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
