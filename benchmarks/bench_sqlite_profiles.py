"""bench_sqlite_profiles.py — Latencia por SQLite PRAGMA profile (Story 2.8).

Owner: Pyro (perf-engineer) + Sol (storage-engineer) — mini-council
COUNCIL-21.
Refs:

- ``docs/stories/2.8.story.md`` AC3.
- ``docs/decisions/COUNCIL-21-storage-pareto-defaults.md``.
- ``src/data_downloader/storage/sqlite_profiles.py``.

Mede impacto dos 3 perfis canonicos (``low_memory``, ``default``,
``aggressive``) em workload representativo do Catalog:

1. ``register_partition`` x N
2. ``get_completed_partitions`` x M
3. ``reconcile`` x 1

Metricas: latencia p50/p95/p99 (ms) por operacao + throughput.

Output JSON em
``benchmarks/results/baselines_v1_mock/bench_sqlite_profiles-{date}-{git_sha}.json``.
"""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from benchmarks._common import (
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.sqlite_profiles import SQLITE_PROFILES, SQLiteProfile

DEFAULT_N_PARTITIONS = 1_000
DEFAULT_N_QUERIES = 200
DEFAULT_N_RUNS = 3


def _make_partition(idx: int, data_dir: Path) -> tuple[PartitionKey, WriteResult, Path]:
    """Constroi uma particao sintetica deterministica.

    Cria arquivo placeholder em disco para satisfazer
    ``relative_partition_path`` resolve.
    """
    month = (idx // 10 % 12) + 1
    year = 2026 + (idx // 120)
    symbol = f"WDO{chr(ord('A') + month - 1)}{year % 100:02d}"
    parquet_path = data_dir / "history" / "F" / symbol / str(year) / f"{month:02d}.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    if not parquet_path.exists():
        parquet_path.write_bytes(b"PAR1\x00\x00\x00\x00")
    key = PartitionKey(exchange="F", symbol=symbol, year=year, month=month)
    write_result = WriteResult(
        path=parquet_path,
        row_count=10_000 + idx,
        first_ts_ns=1_700_000_000_000_000_000 + idx * 1_000_000,
        last_ts_ns=1_700_000_000_000_000_000 + (idx + 1) * 1_000_000,
        checksum_sha256=f"{idx:064x}"[:64],
        file_size_bytes=parquet_path.stat().st_size,
    )
    return key, write_result, parquet_path


def measure_register(catalog: Catalog, n_partitions: int, data_dir: Path) -> dict[str, Any]:
    elapsed_ns: list[int] = []
    process = psutil.Process()
    rss_before = process.memory_info().rss
    rss_peak = rss_before

    for i in range(n_partitions):
        key, wr, _ = _make_partition(i, data_dir)
        t0 = time.perf_counter_ns()
        catalog.register_partition(wr, key)
        elapsed_ns.append(time.perf_counter_ns() - t0)
        if i % 100 == 0:
            rss_peak = max(rss_peak, process.memory_info().rss)

    rss_after = process.memory_info().rss
    rss_peak = max(rss_peak, rss_after)
    elapsed_ms = [e / 1e6 for e in elapsed_ns]
    total_s = sum(elapsed_ns) / 1e9
    return {
        "operation": "register_partition",
        "n_ops": n_partitions,
        "p50_ms": statistics.median(elapsed_ms),
        "p95_ms": percentile(elapsed_ms, 0.95),
        "p99_ms": percentile(elapsed_ms, 0.99),
        "throughput_ops_per_sec": n_partitions / total_s if total_s > 0 else 0.0,
        "total_elapsed_s": total_s,
        "peak_rss_delta_mb": max(0, (rss_peak - rss_before) / 1e6),
    }


def measure_query(catalog: Catalog, n_queries: int, n_partitions: int) -> dict[str, Any]:
    elapsed_ns: list[int] = []
    process = psutil.Process()
    rss_before = process.memory_info().rss

    for i in range(n_queries):
        symbol = f"WDO{chr(ord('A') + (i % 12))}{2026 % 100:02d}"
        t0 = time.perf_counter_ns()
        catalog.get_completed_partitions(symbol, "F")
        elapsed_ns.append(time.perf_counter_ns() - t0)

    rss_after = process.memory_info().rss
    elapsed_ms = [e / 1e6 for e in elapsed_ns]
    total_s = sum(elapsed_ns) / 1e9
    return {
        "operation": "get_completed_partitions",
        "n_ops": n_queries,
        "n_partitions_in_db": n_partitions,
        "p50_ms": statistics.median(elapsed_ms),
        "p95_ms": percentile(elapsed_ms, 0.95),
        "p99_ms": percentile(elapsed_ms, 0.99),
        "throughput_ops_per_sec": n_queries / total_s if total_s > 0 else 0.0,
        "total_elapsed_s": total_s,
        "peak_rss_delta_mb": max(0, (rss_after - rss_before) / 1e6),
    }


def measure_reconcile(catalog: Catalog) -> dict[str, Any]:
    process = psutil.Process()
    rss_before = process.memory_info().rss
    t0 = time.perf_counter_ns()
    report = catalog.reconcile(auto_correct=False)
    elapsed_ns = time.perf_counter_ns() - t0
    rss_after = process.memory_info().rss
    return {
        "operation": "reconcile",
        "elapsed_ms": elapsed_ns / 1e6,
        "drift_a": len(report.drift_a),
        "drift_b": len(report.drift_b),
        "drift_c": len(report.drift_c),
        "peak_rss_delta_mb": max(0, (rss_after - rss_before) / 1e6),
    }


def run_profile(
    profile: SQLiteProfile, n_partitions: int, n_queries: int, n_runs: int
) -> dict[str, Any]:
    register_runs: list[dict[str, Any]] = []
    query_runs: list[dict[str, Any]] = []
    reconcile_runs: list[dict[str, Any]] = []

    for _ in range(n_runs):
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"bench_sqlite_{profile.name}_"))
        try:
            data_dir = tmp_dir / "data"
            db_path = data_dir / "history" / "catalog.db"
            cat = Catalog(
                db_path=db_path,
                data_dir=data_dir,
                sqlite_profile=profile,
                auto_reconcile=False,
                auto_cleanup_orphans=False,
            )
            try:
                gc.collect()
                register_runs.append(measure_register(cat, n_partitions, data_dir))
                query_runs.append(measure_query(cat, n_queries, n_partitions))
                reconcile_runs.append(measure_reconcile(cat))
            finally:
                cat.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _agg_op(runs: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "operation": runs[0]["operation"],
            "n_runs": len(runs),
            "p50_ms_p50_across_runs": statistics.median(r["p50_ms"] for r in runs),
            "p99_ms_p50_across_runs": statistics.median(r["p99_ms"] for r in runs),
            "throughput_ops_per_sec_p50": statistics.median(
                r["throughput_ops_per_sec"] for r in runs
            ),
            "peak_rss_delta_mb_max": max(r["peak_rss_delta_mb"] for r in runs),
        }

    reconcile_aggregate = {
        "operation": "reconcile",
        "n_runs": len(reconcile_runs),
        "elapsed_ms_p50": statistics.median(r["elapsed_ms"] for r in reconcile_runs),
        "elapsed_ms_p99": percentile([r["elapsed_ms"] for r in reconcile_runs], 0.99),
        "peak_rss_delta_mb_max": max(r["peak_rss_delta_mb"] for r in reconcile_runs),
    }

    return {
        "profile": profile.name,
        "cache_size": profile.cache_size,
        "mmap_size_mb": profile.mmap_size // (1024 * 1024),
        "n_partitions": n_partitions,
        "n_queries": n_queries,
        "register_partition": _agg_op(register_runs),
        "get_completed_partitions": _agg_op(query_runs),
        "reconcile": reconcile_aggregate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-partitions", type=int, default=DEFAULT_N_PARTITIONS)
    parser.add_argument("--n-queries", type=int, default=DEFAULT_N_QUERIES)
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS)
    parser.add_argument("--profiles", type=str, default="all")
    args = parser.parse_args()

    n_partitions = args.n_partitions
    n_queries = args.n_queries
    n_runs = args.n_runs

    profile_names = (
        list(SQLITE_PROFILES)
        if args.profiles == "all"
        else [p.strip() for p in args.profiles.split(",")]
    )
    profiles = [SQLITE_PROFILES[name] for name in profile_names]

    print(
        f"[bench_sqlite_profiles] {len(profiles)} profiles x {n_runs} runs each | "
        f"workload: {n_partitions:_} register + {n_queries:_} query + 1 reconcile"
    )
    started_at = datetime.now(UTC)

    scenarios: list[dict[str, Any]] = []
    for profile in profiles:
        print(
            f"[bench_sqlite_profiles] profile={profile.name} | "
            f"cache={profile.cache_size} | mmap={profile.mmap_size // 1024 // 1024} MB"
        )
        result = run_profile(profile, n_partitions, n_queries, n_runs)
        scenarios.append(result)
        reg = result["register_partition"]
        qry = result["get_completed_partitions"]
        rec = result["reconcile"]
        print(
            f"  -> register p50: {reg['p50_ms_p50_across_runs']:.2f}ms | "
            f"query p50: {qry['p50_ms_p50_across_runs']:.3f}ms | "
            f"reconcile: {rec['elapsed_ms_p50']:.1f}ms"
        )

    def _score(s: dict[str, Any]) -> float:
        return (
            0.7 * s["register_partition"]["p50_ms_p50_across_runs"]
            + 0.3 * s["get_completed_partitions"]["p50_ms_p50_across_runs"] * 100
        )

    fastest = min(scenarios, key=_score)
    summary = {
        "n_profiles": len(profiles),
        "n_partitions_workload": n_partitions,
        "n_queries_workload": n_queries,
        "scoring": "0.7 * register_p50_ms + 0.3 * query_p50_ms*100 (lower=better)",
        "fastest_profile": fastest["profile"],
        "current_default": "default",
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "verdict": "MEASURED",
    }

    envelope = build_result_envelope(
        "bench_sqlite_profiles",
        config={
            "n_partitions": n_partitions,
            "n_queries": n_queries,
            "n_runs_per_profile": n_runs,
            "profiles_tested": profile_names,
        },
        scenarios=scenarios,
        summary=summary,
        notes=(
            "Story 2.8 AC3 — bench dos 3 perfis SQLite canonicos. "
            "Workload sintetico deterministico (sem dependencia de DLL). "
            "Decisao default em COUNCIL-21 — Sol+Pyro sign-off."
        ),
    )

    save_dir = Path(__file__).parent / "results" / "baselines_v1_mock"
    save_dir.mkdir(parents=True, exist_ok=True)
    sha = envelope["git_sha"]
    if envelope.get("git_dirty"):
        sha = f"{sha}-dirty"
    date = envelope["date"][:10]
    filename = f"bench_sqlite_profiles-{date}-{sha}.json"
    out = save_dir / filename
    out.write_text(json.dumps(envelope, indent=2, default=str), encoding="utf-8")
    save_results(envelope)
    print(f"\n[bench_sqlite_profiles] resultados salvos em: {out}")
    print_summary(envelope)


if __name__ == "__main__":
    main()
