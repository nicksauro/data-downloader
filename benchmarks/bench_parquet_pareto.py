"""bench_parquet_pareto.py — Matriz Pareto compression x row_group (Story 2.8).

Owner: Pyro (perf-engineer) + Sol (storage-engineer) — mini-council
COUNCIL-21.
Refs:

- ``docs/stories/2.8.story.md`` AC1 + AC2.
- ``docs/decisions/COUNCIL-02-parquet-writer-streaming-overhead.md``.
- ``docs/perf/BASELINES.md`` — `bench_parquet_write` v1.0.0-synthetic
  ja mediu raw matrix; esta bench amplia para matriz completa
  ``compression x row_group`` cobrindo write + read + filtered_read +
  file_size num unico envelope, com workload representativo (1M
  trades) reproduzivel.

Matriz:

- ``compression``: ``snappy``, ``zstd-1``, ``zstd-3``, ``none``
- ``row_group_size``: ``10_000``, ``50_000``, ``100_000``, ``250_000``,
  ``1_000_000``

= 4 x 5 = **20 cells**. Cada celula mede:

- ``write_throughput_tps`` (trades/s, p50 sobre ``n_runs``)
- ``read_full_scan_tps`` (DuckDB COUNT(*), p50)
- ``read_filtered_tps`` (DuckDB WHERE timestamp_ns BETWEEN ..., p50)
- ``file_size_mb`` (mediana — deterministic for same seed)
- ``peak_memory_write_mb`` (RSS delta peak, max sobre runs)
- ``peak_memory_read_mb`` (RSS delta peak, max sobre runs)

Output JSON canonico em
``benchmarks/results/baselines_v1_mock/bench_parquet_pareto-{date}-{git_sha}.json``.

Notas de execucao (host modesto i7-3770 16GB):

- ``--n-trades`` default 500_000.
- ``--n-runs`` default 2.

Decisao final de defaults registrada em COUNCIL-21 (Sol+Pyro sign-off).
"""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

from benchmarks._common import (
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from benchmarks.fixtures.synthetic_trades import generate_batch_arrow

DEFAULT_N_TRADES = 500_000
DEFAULT_N_RUNS = 2

COMPRESSIONS: list[dict[str, Any]] = [
    {"compression": "snappy"},
    {"compression": "zstd", "compression_level": 1},
    {"compression": "zstd", "compression_level": 3},
    {"compression": None},
]
ROW_GROUP_SIZES: list[int] = [10_000, 50_000, 100_000, 250_000, 1_000_000]


def _label_compression(cfg: dict[str, Any]) -> str:
    comp = cfg["compression"]
    if comp is None:
        return "none"
    lvl = cfg.get("compression_level")
    return f"{comp}-{lvl}" if lvl else str(comp)


def _measure_write(
    table: pa.Table, cfg: dict[str, Any], row_group_size: int, out_path: Path
) -> dict[str, Any]:
    process = psutil.Process()
    gc.collect()
    rss_before = process.memory_info().rss
    rss_peak = rss_before

    t0 = time.perf_counter_ns()
    pq.write_table(
        table,
        out_path,
        row_group_size=row_group_size,
        compression=cfg["compression"],
        compression_level=cfg.get("compression_level"),
        use_dictionary=True,
        write_statistics=True,
    )
    elapsed_ns = time.perf_counter_ns() - t0

    rss_after = process.memory_info().rss
    rss_peak = max(rss_peak, rss_after)
    file_size = out_path.stat().st_size

    return {
        "elapsed_ns": elapsed_ns,
        "trades_per_sec": table.num_rows / (elapsed_ns / 1e9),
        "file_size_bytes": file_size,
        "peak_rss_delta_mb": max(0, (rss_peak - rss_before) / 1e6),
    }


def _measure_full_scan(parquet_path: Path) -> dict[str, Any]:
    process = psutil.Process()
    gc.collect()
    rss_before = process.memory_info().rss

    con = duckdb.connect(":memory:", config={"threads": "1"})
    t0 = time.perf_counter_ns()
    row = con.execute(
        "SELECT COUNT(*), SUM(quantity) FROM read_parquet(?)", [str(parquet_path)]
    ).fetchone()
    elapsed_ns = time.perf_counter_ns() - t0
    n_rows = int(row[0]) if row else 0
    con.close()

    rss_after = process.memory_info().rss
    return {
        "elapsed_ns": elapsed_ns,
        "n_trades": n_rows,
        "trades_per_sec": n_rows / (elapsed_ns / 1e9) if elapsed_ns > 0 else 0.0,
        "peak_rss_delta_mb": max(0, (rss_after - rss_before) / 1e6),
    }


def _measure_filtered_scan(
    parquet_path: Path, *, total_rows: int, ts_min: int, ts_max: int
) -> dict[str, Any]:
    span = ts_max - ts_min
    win = max(1, span // 100)
    center = ts_min + span // 2

    process = psutil.Process()
    gc.collect()
    rss_before = process.memory_info().rss

    con = duckdb.connect(":memory:", config={"threads": "1"})
    t0 = time.perf_counter_ns()
    row = con.execute(
        "SELECT COUNT(*), SUM(quantity) FROM read_parquet(?) " "WHERE timestamp_ns BETWEEN ? AND ?",
        [str(parquet_path), center, center + win],
    ).fetchone()
    elapsed_ns = time.perf_counter_ns() - t0
    n_returned = int(row[0]) if row else 0
    con.close()

    rss_after = process.memory_info().rss
    elapsed_s = elapsed_ns / 1e9
    return {
        "elapsed_ns": elapsed_ns,
        "n_returned": n_returned,
        "n_total_rows": total_rows,
        "selectivity_actual": n_returned / max(1, total_rows),
        "trades_per_sec": total_rows / elapsed_s if elapsed_s > 0 else 0.0,
        "peak_rss_delta_mb": max(0, (rss_after - rss_before) / 1e6),
    }


def _ts_bounds(parquet_path: Path) -> tuple[int, int]:
    con = duckdb.connect(":memory:")
    res = con.execute(
        "SELECT MIN(timestamp_ns), MAX(timestamp_ns) FROM read_parquet(?)",
        [str(parquet_path)],
    ).fetchone()
    con.close()
    return int(res[0]), int(res[1])


def run_cell(
    table: pa.Table,
    cfg: dict[str, Any],
    row_group_size: int,
    tmp_dir: Path,
    n_runs: int,
) -> dict[str, Any]:
    write_runs: list[dict[str, Any]] = []
    out_path = tmp_dir / f"cell_{_label_compression(cfg)}_rg{row_group_size}.parquet"

    for _ in range(n_runs):
        if out_path.exists():
            out_path.unlink()
        write_runs.append(_measure_write(table, cfg, row_group_size, out_path))

    ts_min, ts_max = _ts_bounds(out_path)
    _measure_full_scan(out_path)  # warmup

    full_runs = [_measure_full_scan(out_path) for _ in range(n_runs)]
    filt_runs = [
        _measure_filtered_scan(out_path, total_rows=table.num_rows, ts_min=ts_min, ts_max=ts_max)
        for _ in range(n_runs)
    ]

    out_path.unlink(missing_ok=True)

    write_tps = [r["trades_per_sec"] for r in write_runs]
    full_tps = [r["trades_per_sec"] for r in full_runs]
    filt_tps = [r["trades_per_sec"] for r in filt_runs]

    return {
        "compression": _label_compression(cfg),
        "row_group_size": row_group_size,
        "n_trades": table.num_rows,
        "n_runs": n_runs,
        "write_throughput_tps_p50": statistics.median(write_tps),
        "write_throughput_tps_min": min(write_tps),
        "write_throughput_tps_stddev": (statistics.stdev(write_tps) if len(write_tps) > 1 else 0.0),
        "write_p50_ms": statistics.median(r["elapsed_ns"] / 1e6 for r in write_runs),
        "write_p99_ms": percentile([r["elapsed_ns"] / 1e6 for r in write_runs], 0.99),
        "peak_memory_write_mb": max(r["peak_rss_delta_mb"] for r in write_runs),
        "read_full_scan_tps_p50": statistics.median(full_tps),
        "read_full_scan_tps_min": min(full_tps),
        "read_full_p50_ms": statistics.median(r["elapsed_ns"] / 1e6 for r in full_runs),
        "read_full_p99_ms": percentile([r["elapsed_ns"] / 1e6 for r in full_runs], 0.99),
        "peak_memory_read_mb": max(r["peak_rss_delta_mb"] for r in full_runs),
        "read_filtered_tps_p50": statistics.median(filt_tps),
        "read_filtered_tps_min": min(filt_tps),
        "read_filtered_p50_ms": statistics.median(r["elapsed_ns"] / 1e6 for r in filt_runs),
        "read_filtered_p99_ms": percentile([r["elapsed_ns"] / 1e6 for r in filt_runs], 0.99),
        "selectivity_actual": statistics.median(r["selectivity_actual"] for r in filt_runs),
        "file_size_mb": statistics.median(r["file_size_bytes"] for r in write_runs) / 1e6,
    }


def _is_pareto_dominated(cell: dict[str, Any], all_cells: list[dict[str, Any]]) -> bool:
    """Cell e Pareto-dominada se outra e >= em TODAS metricas e > em pelo menos uma."""
    for other in all_cells:
        if other is cell:
            continue
        dominates = (
            other["write_throughput_tps_p50"] >= cell["write_throughput_tps_p50"]
            and other["read_full_scan_tps_p50"] >= cell["read_full_scan_tps_p50"]
            and other["read_filtered_tps_p50"] >= cell["read_filtered_tps_p50"]
            and other["file_size_mb"] <= cell["file_size_mb"]
        )
        strict = (
            other["write_throughput_tps_p50"] > cell["write_throughput_tps_p50"]
            or other["read_full_scan_tps_p50"] > cell["read_full_scan_tps_p50"]
            or other["read_filtered_tps_p50"] > cell["read_filtered_tps_p50"]
            or other["file_size_mb"] < cell["file_size_mb"]
        )
        if dominates and strict:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-trades", type=int, default=DEFAULT_N_TRADES)
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS)
    parser.add_argument("--compressions", type=str, default="all")
    parser.add_argument("--row-groups", type=str, default="all")
    args = parser.parse_args()

    n_trades = args.n_trades
    n_runs = args.n_runs

    compressions = COMPRESSIONS
    if args.compressions != "all":
        wanted = {c.strip() for c in args.compressions.split(",")}
        compressions = [c for c in COMPRESSIONS if _label_compression(c) in wanted]

    row_groups = ROW_GROUP_SIZES
    if args.row_groups != "all":
        wanted_rg = {int(r.strip()) for r in args.row_groups.split(",")}
        row_groups = [r for r in ROW_GROUP_SIZES if r in wanted_rg]

    print(
        f"[bench_parquet_pareto] gerando {n_trades:_} trades sinteticos "
        f"({len(compressions)} compressions x {len(row_groups)} row_groups = "
        f"{len(compressions) * len(row_groups)} cells x {n_runs} runs)"
    )
    t0 = time.perf_counter()
    table = generate_batch_arrow(n_trades, symbol="WDOJ26")
    gen_elapsed = time.perf_counter() - t0
    print(
        f"[bench_parquet_pareto] gerados em {gen_elapsed:.1f}s "
        f"({n_trades / gen_elapsed:_.0f} trades/s); "
        f"in-mem: {table.nbytes / 1e6:.1f} MB"
    )

    tmp_root = Path(tempfile.mkdtemp(prefix="bench_pareto_"))
    cells: list[dict[str, Any]] = []
    try:
        for cfg in compressions:
            for rg in row_groups:
                comp_label = _label_compression(cfg)
                print(
                    f"[bench_parquet_pareto] cell: compression={comp_label}, " f"row_group={rg:_}"
                )
                cell = run_cell(table, cfg, rg, tmp_root, n_runs)
                cells.append(cell)
                print(
                    f"  -> write {cell['write_throughput_tps_p50']:_.0f} tps | "
                    f"read_full {cell['read_full_scan_tps_p50']:_.0f} tps | "
                    f"read_filt {cell['read_filtered_tps_p50']:_.0f} tps | "
                    f"size {cell['file_size_mb']:.1f} MB"
                )

        for cell in cells:
            cell["pareto_dominated"] = _is_pareto_dominated(cell, cells)

        pareto_frontier = [c for c in cells if not c["pareto_dominated"]]
        print(
            f"\n[bench_parquet_pareto] Pareto frontier: "
            f"{len(pareto_frontier)} cells de {len(cells)} (nao-dominadas)"
        )

        write_winner = max(cells, key=lambda c: c["write_throughput_tps_p50"])
        read_full_winner = max(cells, key=lambda c: c["read_full_scan_tps_p50"])
        read_filt_winner = max(cells, key=lambda c: c["read_filtered_tps_p50"])
        size_winner = min(cells, key=lambda c: c["file_size_mb"])

        summary = {
            "matrix_size": len(cells),
            "pareto_frontier_size": len(pareto_frontier),
            "winners": {
                "write": {
                    "compression": write_winner["compression"],
                    "row_group_size": write_winner["row_group_size"],
                    "value_tps": write_winner["write_throughput_tps_p50"],
                },
                "read_full_scan": {
                    "compression": read_full_winner["compression"],
                    "row_group_size": read_full_winner["row_group_size"],
                    "value_tps": read_full_winner["read_full_scan_tps_p50"],
                },
                "read_filtered_1pct": {
                    "compression": read_filt_winner["compression"],
                    "row_group_size": read_filt_winner["row_group_size"],
                    "value_tps": read_filt_winner["read_filtered_tps_p50"],
                },
                "smallest_file": {
                    "compression": size_winner["compression"],
                    "row_group_size": size_winner["row_group_size"],
                    "value_mb": size_winner["file_size_mb"],
                },
            },
            "current_default": {
                "compression": "snappy",
                "row_group_size": 100_000,
                "note": "ADR-002 — verificar Pareto-dominance abaixo",
            },
            "verdict": "MEASURED",
        }

        envelope = build_result_envelope(
            "bench_parquet_pareto",
            config={
                "n_trades_per_run": n_trades,
                "n_runs_per_cell": n_runs,
                "compressions": [_label_compression(c) for c in compressions],
                "row_group_sizes": list(row_groups),
            },
            scenarios=cells,
            summary=summary,
            notes=(
                "Story 2.8 — matriz Pareto (compression x row_group). "
                "Workload: synthetic trades WDOJ26 seed=42. "
                "Decisao default Pareto-otimo em COUNCIL-21."
            ),
        )

        save_dir = Path(__file__).parent / "results" / "baselines_v1_mock"
        save_dir.mkdir(parents=True, exist_ok=True)
        sha = envelope["git_sha"]
        if envelope.get("git_dirty"):
            sha = f"{sha}-dirty"
        date = envelope["date"][:10]
        filename = f"bench_parquet_pareto-{date}-{sha}.json"
        out = save_dir / filename
        out.write_text(json.dumps(envelope, indent=2, default=str), encoding="utf-8")
        save_results(envelope)
        print(f"\n[bench_parquet_pareto] resultados salvos em: {out}")
        print_summary(envelope)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
