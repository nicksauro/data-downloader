"""bench_parquet_read.py — Throughput de leitura via DuckDB (full scan + filtered).

Objetivo:
    Medir trades/s ao fazer:
    (a) full scan via DuckDB single-thread sobre N arquivos Parquet de
        100k linhas cada (target >= 1M trades/s).
    (b) range-filtered scan (``WHERE timestamp_ns BETWEEN ...``) com
        seletividade 1% e 10% — exercita pruning de row group
        (target >= 5M trades/s para selectivity 1%).

Pré-geração:
    1M trades sintéticos em N arquivos Parquet via pq.write_table direto
    (config canônica: snappy + row_group=100k). Não usa ParquetWriter
    pois ParquetWriter sobrescreve mesmo path quando merge — para read
    bench precisamos de N arquivos físicos distintos.

Hipóteses a testar:
    H1: DuckDB single-thread satura memory bandwidth antes de saturar CPU.
    H2: row_group_size maior (250k+) acelera full scan (menos overhead
        de metadata) — mas piora filtered (granularidade pruning).
    H3: Snappy decompression é faster que ZSTD para full scan
        (CPU > memory bandwidth).

Output:
    benchmarks/results/bench_parquet_read-{date}-{git_sha}.json
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq

from benchmarks._common import (
    DEFAULT_N_RUNS,
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from benchmarks.fixtures.synthetic_trades import generate_batch_arrow

DEFAULT_N_TRADES_TOTAL = 1_000_000
DEFAULT_N_FILES = 10  # 100k linhas/arquivo no setup default
TARGET_FULL_SCAN_TPS = 1_000_000
TARGET_FILTERED_TPS = 5_000_000

CONFIG_MATRIX: list[dict[str, Any]] = [
    {"row_group_size": 100_000, "compression": "snappy"},
    {"row_group_size": 250_000, "compression": "snappy"},
    {"row_group_size": 100_000, "compression": "zstd", "compression_level": 1},
    {"row_group_size": 100_000, "compression": None},
]


def setup_parquet_files(
    config: dict[str, Any], tmp_dir: Path, n_trades_total: int, n_files: int
) -> list[Path]:
    """Gera n_trades_total trades em n_files arquivos Parquet."""
    per_file = n_trades_total // n_files
    paths: list[Path] = []
    for i in range(n_files):
        # start_ts_ns crescente para cada arquivo (simula partições mensais).
        table = generate_batch_arrow(per_file, symbol="WDOJ26", seed=42 + i)
        out = tmp_dir / f"chunk_{i:03d}.parquet"
        pq.write_table(
            table,
            out,
            row_group_size=config["row_group_size"],
            compression=config["compression"],
            compression_level=config.get("compression_level"),
            use_dictionary=True,
            write_statistics=True,
        )
        paths.append(out)
    return paths


def measure_full_scan(parquet_files: list[Path]) -> dict[str, Any]:
    """SELECT COUNT(*) full scan via DuckDB single-thread."""
    con = duckdb.connect(":memory:", config={"threads": "1"})
    paths = [str(p) for p in parquet_files]
    # Warmup query handled by caller
    t0 = time.perf_counter_ns()
    result = con.execute(
        "SELECT COUNT(*) AS n, SUM(quantity) AS s FROM read_parquet(?)", [paths]
    ).fetchone()
    elapsed_ns = time.perf_counter_ns() - t0
    con.close()
    n_trades = int(result[0]) if result else 0
    return {
        "elapsed_ns": elapsed_ns,
        "n_trades": n_trades,
        "trades_per_sec": n_trades / (elapsed_ns / 1e9),
    }


def measure_filtered_scan(
    parquet_files: list[Path],
    *,
    start_ts_ns: int,
    end_ts_ns: int,
    selectivity: float,
) -> dict[str, Any]:
    """Range-filtered scan exercitando row group pruning.

    Métrica primária: ``effective_scan_rate`` = total_rows_in_dataset / elapsed
    (mede taxa de varredura "lógica" sobre input — pruning faz isso ser muito
    maior que rows-returned/elapsed). Target V1 5M trades/s refere-se a esta
    métrica (capacity de processar um dataset rapidamente quando filtro corta
    a maioria via metadata).
    """
    total_rows = _total_rows_cached(parquet_files)
    con = duckdb.connect(":memory:", config={"threads": "1"})
    paths = [str(p) for p in parquet_files]
    t0 = time.perf_counter_ns()
    result = con.execute(
        "SELECT COUNT(*) AS n, SUM(quantity) AS s FROM read_parquet(?) "
        "WHERE timestamp_ns BETWEEN ? AND ?",
        [paths, start_ts_ns, end_ts_ns],
    ).fetchone()
    elapsed_ns = time.perf_counter_ns() - t0
    con.close()
    n_returned = int(result[0]) if result else 0
    elapsed_s = elapsed_ns / 1e9
    return {
        "elapsed_ns": elapsed_ns,
        "n_returned": n_returned,
        "n_total_rows": total_rows,
        "selectivity_target": selectivity,
        "selectivity_actual": n_returned / max(1, total_rows),
        # Effective scan rate: total dataset rows / elapsed time (mede pruning).
        "trades_per_sec": total_rows / elapsed_s if elapsed_s > 0 else 0.0,
        # Returned-rows per sec (informativo).
        "returned_per_sec": n_returned / elapsed_s if elapsed_s > 0 and n_returned > 0 else 0.0,
    }


_TOTAL_ROWS_CACHE: dict[tuple[str, ...], int] = {}


def _total_rows_cached(paths: list[Path]) -> int:
    """Cacheia COUNT(*) total para selectivity_actual computation."""
    key = tuple(str(p) for p in paths)
    if key in _TOTAL_ROWS_CACHE:
        return _TOTAL_ROWS_CACHE[key]
    con = duckdb.connect(":memory:")
    res = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [list(key)]).fetchone()
    con.close()
    total = int(res[0]) if res else 0
    _TOTAL_ROWS_CACHE[key] = total
    return total


def _ts_bounds(parquet_files: list[Path]) -> tuple[int, int]:
    """min/max timestamp_ns dos arquivos (para definir filtros)."""
    con = duckdb.connect(":memory:")
    paths = [str(p) for p in parquet_files]
    res = con.execute(
        "SELECT MIN(timestamp_ns), MAX(timestamp_ns) FROM read_parquet(?)", [paths]
    ).fetchone()
    con.close()
    return int(res[0]), int(res[1])


def run_config(
    config: dict[str, Any],
    tmp_dir: Path,
    n_trades_total: int,
    n_files: int,
    n_runs: int,
) -> list[dict[str, Any]]:
    """Roda full scan + filtered scans (1% e 10%) para uma config; retorna rows agregadas."""
    parquet_files = setup_parquet_files(config, tmp_dir, n_trades_total, n_files)
    ts_min, ts_max = _ts_bounds(parquet_files)
    span = ts_max - ts_min

    # Warmup — discard.
    measure_full_scan(parquet_files)

    # Full scan runs.
    full_runs: list[dict[str, Any]] = []
    for _ in range(n_runs):
        full_runs.append(measure_full_scan(parquet_files))

    # Filtered 1%: pega janela central de 1% do span.
    filt_1pct = []
    win_1pct = int(span * 0.01)
    center = ts_min + span // 2
    measure_filtered_scan(
        parquet_files, start_ts_ns=center, end_ts_ns=center + win_1pct, selectivity=0.01
    )
    for _ in range(n_runs):
        filt_1pct.append(
            measure_filtered_scan(
                parquet_files,
                start_ts_ns=center,
                end_ts_ns=center + win_1pct,
                selectivity=0.01,
            )
        )

    # Filtered 10%.
    filt_10pct = []
    win_10pct = int(span * 0.10)
    measure_filtered_scan(
        parquet_files, start_ts_ns=ts_min, end_ts_ns=ts_min + win_10pct, selectivity=0.10
    )
    for _ in range(n_runs):
        filt_10pct.append(
            measure_filtered_scan(
                parquet_files,
                start_ts_ns=ts_min,
                end_ts_ns=ts_min + win_10pct,
                selectivity=0.10,
            )
        )

    # Cleanup.
    for p in parquet_files:
        p.unlink(missing_ok=True)

    def _agg(runs: list[dict[str, Any]], label: str) -> dict[str, Any]:
        elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
        throughputs = [r["trades_per_sec"] for r in runs]
        return {
            **dict(config),
            "compression": config["compression"] or "none",
            "scenario": label,
            "n_files": n_files,
            "n_trades_per_file": n_trades_total // n_files,
            "n_runs": n_runs,
            "trades_per_sec_p50": statistics.median(throughputs),
            "trades_per_sec_min": min(throughputs),
            "p50_ms": statistics.median(elapsed_ms),
            "p95_ms": percentile(elapsed_ms, 0.95),
            "p99_ms": percentile(elapsed_ms, 0.99),
            "n_returned_p50": int(
                statistics.median(r.get("n_returned", r.get("n_trades", 0)) for r in runs)
            ),
            "selectivity_actual_p50": statistics.median(
                r.get("selectivity_actual", 1.0) for r in runs
            ),
        }

    return [
        _agg(full_runs, "full_scan"),
        _agg(filt_1pct, "filtered_1pct"),
        _agg(filt_10pct, "filtered_10pct"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-trades", type=int, default=DEFAULT_N_TRADES_TOTAL)
    parser.add_argument("--n-files", type=int, default=DEFAULT_N_FILES)
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS)
    args = parser.parse_args()

    n_trades = args.n_trades
    n_files = args.n_files
    n_runs = args.n_runs

    print(
        f"[bench_parquet_read] {n_trades:_} trades em {n_files} arquivos "
        f"({n_trades // n_files:_} cada), {n_runs} runs/config"
    )

    tmp_root = Path(tempfile.mkdtemp(prefix="bench_pq_read_"))
    try:
        all_scenarios: list[dict[str, Any]] = []
        for cfg in CONFIG_MATRIX:
            comp_label = cfg["compression"] or "none"
            rg = cfg["row_group_size"]
            print(f"[bench_parquet_read] config: row_group={rg:_}, compression={comp_label}")
            scenarios = run_config(cfg, tmp_root, n_trades, n_files, n_runs)
            for sc in scenarios:
                all_scenarios.append(sc)
                print(
                    f"  {sc['scenario']:>16}: p50 {sc['trades_per_sec_p50']:_.0f} trades/s | "
                    f"p99 {sc['p99_ms']:.1f}ms | returned {sc['n_returned_p50']:_}"
                )

        # Winners.
        full_scans = [s for s in all_scenarios if s["scenario"] == "full_scan"]
        filt_1pct = [s for s in all_scenarios if s["scenario"] == "filtered_1pct"]

        full_winner = max(full_scans, key=lambda r: r["trades_per_sec_p50"])
        filt_winner = max(filt_1pct, key=lambda r: r["trades_per_sec_p50"])

        verdict_full = (
            "PASS" if full_winner["trades_per_sec_p50"] >= TARGET_FULL_SCAN_TPS else "FAIL"
        )
        verdict_filt = (
            "PASS" if filt_winner["trades_per_sec_p50"] >= TARGET_FILTERED_TPS else "FAIL"
        )

        summary = {
            "full_scan_winner": {
                "row_group_size": full_winner["row_group_size"],
                "compression": full_winner["compression"],
                "trades_per_sec_p50": full_winner["trades_per_sec_p50"],
            },
            "filtered_1pct_winner": {
                "row_group_size": filt_winner["row_group_size"],
                "compression": filt_winner["compression"],
                "trades_per_sec_p50": filt_winner["trades_per_sec_p50"],
                "selectivity_actual": filt_winner["selectivity_actual_p50"],
            },
            "vs_target_full_scan": {
                "target_value": TARGET_FULL_SCAN_TPS,
                "measured_value": full_winner["trades_per_sec_p50"],
                "delta_pct": (
                    (full_winner["trades_per_sec_p50"] - TARGET_FULL_SCAN_TPS)
                    / TARGET_FULL_SCAN_TPS
                )
                * 100,
                "verdict": verdict_full,
            },
            "vs_target_filtered_1pct": {
                "target_value": TARGET_FILTERED_TPS,
                "measured_value": filt_winner["trades_per_sec_p50"],
                "delta_pct": (
                    (filt_winner["trades_per_sec_p50"] - TARGET_FILTERED_TPS) / TARGET_FILTERED_TPS
                )
                * 100,
                "verdict": verdict_filt,
            },
            "verdict": "PASS" if verdict_full == "PASS" and verdict_filt == "PASS" else "FAIL",
        }

        envelope = build_result_envelope(
            "bench_parquet_read",
            config={
                "n_trades_total": n_trades,
                "n_files": n_files,
                "n_runs_per_scenario": n_runs,
                "duckdb_threads": 1,
            },
            scenarios=all_scenarios,
            summary=summary,
            notes="Single-thread DuckDB; 1 warmup query descartado por scenario.",
        )
        path = save_results(envelope)
        print(f"\n[bench_parquet_read] resultados salvos em: {path}")
        print_summary(envelope)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
