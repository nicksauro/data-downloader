"""bench_dedup.py — Throughput de dedup canônico (storage.dedup).

Objetivo:
    Medir tempo e throughput de :func:`data_downloader.storage.dedup.dedup`
    ao receber batches de trades com fração variável de duplicatas,
    varrendo matriz batch_size x duplicate_pct.

Target V1:
    < 50ms para batch de 10k trades (qualquer % de duplicatas).

Hipóteses a testar:
    H1: Dedup via dict de hash(trade_id) é O(n) e satura para 10k em < 50ms.
    H2: Quando trade_id é NULL (Quirk Q01-V), chave canônica longa
        (V1: 8-tuple) é mais cara — esperado 1.5-2x slower que V2 (4-tuple).
    H3: Para batches grandes (>= 1M), bottleneck migra de dict
        construction para chamada de tuple() / hash de tuple.

Cenários (matriz):
    batch_size: [10_000, 100_000, 1_000_000]
    duplicate_pct: [0.0, 0.01, 0.10]
    null_trade_id_pct: [0.0 (key=V2 short), 1.0 (key=V1 long)]

Output:
    benchmarks/results/bench_dedup-{date}-{git_sha}.json
"""

from __future__ import annotations

import argparse
import gc
import random
import statistics
import time
from typing import Any

from benchmarks._common import (
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from benchmarks.fixtures.synthetic_trades import generate
from data_downloader.storage.dedup import assign_sequence_within_ns, dedup

DEFAULT_N_RUNS_PER_CONFIG = 10
TARGET_MS_BATCH_10K = 50.0


def setup_batch(
    batch_size: int, duplicate_pct: float, null_trade_id_pct: float, *, seed: int = 42
) -> list[dict[str, Any]]:
    """Gera batch sintético com `duplicate_pct` * batch_size duplicatas.

    Para chave V1 (null_trade_id_pct=1.0), aplica
    :func:`assign_sequence_within_ns` antes — o writer faz isso na produção;
    aqui simulamos a pré-condição da função :func:`dedup`.
    """
    n_unique = int(batch_size * (1 - duplicate_pct))
    n_dup = batch_size - n_unique

    # Geramos n_unique únicos via gerador (sem duplicatas internas para isolar
    # o impacto do duplicate_pct controlado).
    uniques = list(
        generate(
            n_unique,
            symbol="WDOJ26",
            seed=seed,
            null_trade_id_pct=null_trade_id_pct,
            duplicate_pct=0.0,
        )
    )

    rng = random.Random(seed)
    # Duplicatas: copia de elementos aleatórios da pool unique.
    dups = [dict(uniques[rng.randrange(len(uniques))]) for _ in range(n_dup)]
    batch = uniques + dups
    rng.shuffle(batch)

    # Pré-condição V1: sequence_within_ns atribuído.
    if null_trade_id_pct > 0:
        assign_sequence_within_ns(batch)

    return batch


def measure_dedup(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Roda dedup sobre `batch`, mede tempo e n_unique resultante."""
    gc.collect()
    t0 = time.perf_counter_ns()
    unique = dedup(batch)
    elapsed_ns = time.perf_counter_ns() - t0
    return {
        "elapsed_ns": elapsed_ns,
        "n_in": len(batch),
        "n_out": len(unique),
    }


def run_config(config: dict[str, Any], n_runs: int) -> dict[str, Any]:
    """N runs (warmup descartado), agregando estatísticas."""
    runs: list[dict[str, Any]] = []
    # Warmup
    setup_seed = 42
    warmup_batch = setup_batch(**config, seed=setup_seed)
    measure_dedup(warmup_batch)

    for i in range(n_runs):
        batch = setup_batch(**config, seed=setup_seed + i + 1)
        runs.append(measure_dedup(batch))

    elapsed_ms = [r["elapsed_ns"] / 1e6 for r in runs]
    throughputs = [r["n_in"] / (r["elapsed_ns"] / 1e9) for r in runs]
    return {
        **config,
        "n_runs": n_runs,
        "n_in": runs[0]["n_in"],
        "n_out_p50": int(statistics.median(r["n_out"] for r in runs)),
        "elapsed_ms_p50": statistics.median(elapsed_ms),
        "elapsed_ms_p95": percentile(elapsed_ms, 0.95),
        "elapsed_ms_p99": percentile(elapsed_ms, 0.99),
        "elapsed_ms_min": min(elapsed_ms),
        "elapsed_ms_stddev": statistics.stdev(elapsed_ms) if len(elapsed_ms) > 1 else 0.0,
        "throughput_trades_per_sec_p50": statistics.median(throughputs),
        "key_strategy": "V1_long" if config["null_trade_id_pct"] >= 1.0 else "V2_short",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-runs", type=int, default=DEFAULT_N_RUNS_PER_CONFIG)
    parser.add_argument("--skip-1m", action="store_true", help="pula batch_size=1M (lento)")
    args = parser.parse_args()

    n_runs = args.n_runs

    # Build matrix (com flag de skip-1m).
    batch_sizes = [10_000, 100_000]
    if not args.skip_1m:
        batch_sizes.append(1_000_000)

    matrix: list[dict[str, Any]] = []
    for bs in batch_sizes:
        for dp in [0.0, 0.01, 0.10]:
            for null_pct in [0.0, 1.0]:  # V2 short vs V1 long
                matrix.append(
                    {
                        "batch_size": bs,
                        "duplicate_pct": dp,
                        "null_trade_id_pct": null_pct,
                    }
                )

    print(f"[bench_dedup] {len(matrix)} configs, {n_runs} runs cada")

    scenarios: list[dict[str, Any]] = []
    for cfg in matrix:
        key_label = "V1_long" if cfg["null_trade_id_pct"] >= 1.0 else "V2_short"
        dp_pct = cfg["duplicate_pct"] * 100
        print(f"[bench_dedup] batch={cfg['batch_size']:_} | dup={dp_pct:.0f}% | key={key_label}")
        res = run_config(cfg, n_runs)
        scenarios.append(res)
        print(
            f"  -> p50 {res['elapsed_ms_p50']:.2f}ms | p99 {res['elapsed_ms_p99']:.2f}ms | "
            f"throughput {res['throughput_trades_per_sec_p50']:_.0f} trades/s"
        )

    # Verdict: target é < 50ms para batch 10k (qualquer config).
    batch_10k = [s for s in scenarios if s["batch_size"] == 10_000]
    worst_10k_p50 = max(s["elapsed_ms_p50"] for s in batch_10k)
    verdict = "PASS" if worst_10k_p50 <= TARGET_MS_BATCH_10K else "FAIL"

    summary = {
        "vs_target_batch_10k": {
            "target_metric": "elapsed_ms_p50 (worst case across configs)",
            "target_value": TARGET_MS_BATCH_10K,
            "measured_value": worst_10k_p50,
            "delta_pct": ((worst_10k_p50 - TARGET_MS_BATCH_10K) / TARGET_MS_BATCH_10K) * 100,
        },
        "verdict": verdict,
        "v1_v2_ratio_at_10k_dup0": _v1_v2_ratio(scenarios, batch_size=10_000, dup_pct=0.0),
        "scaling_complexity_check": _check_linear_scaling(scenarios),
    }

    envelope = build_result_envelope(
        "bench_dedup",
        config={"n_runs_per_config": n_runs, "matrix_size": len(matrix)},
        scenarios=scenarios,
        summary=summary,
        notes="Dedup canônico storage.dedup; V1 (chave longa 8-tupla) vs V2 (chave curta 4-tupla).",
    )
    path = save_results(envelope)
    print(f"\n[bench_dedup] resultados salvos em: {path}")
    print_summary(envelope)


def _v1_v2_ratio(scenarios: list[dict[str, Any]], *, batch_size: int, dup_pct: float) -> float:
    """Razão V1/V2 latência (mede penalidade de chave longa)."""
    v1 = next(
        (
            s
            for s in scenarios
            if s["batch_size"] == batch_size
            and s["duplicate_pct"] == dup_pct
            and s["key_strategy"] == "V1_long"
        ),
        None,
    )
    v2 = next(
        (
            s
            for s in scenarios
            if s["batch_size"] == batch_size
            and s["duplicate_pct"] == dup_pct
            and s["key_strategy"] == "V2_short"
        ),
        None,
    )
    if v1 and v2 and v2["elapsed_ms_p50"] > 0:
        return v1["elapsed_ms_p50"] / v2["elapsed_ms_p50"]
    return 0.0


def _check_linear_scaling(scenarios: list[dict[str, Any]]) -> dict[str, float]:
    """Checa se dedup é O(n) comparando ms/trade entre batch_size."""
    # Pega V2 + dup_pct=0.01 como referência.
    ref = [s for s in scenarios if s["key_strategy"] == "V2_short" and s["duplicate_pct"] == 0.01]
    if len(ref) < 2:
        return {}
    ms_per_trade = {s["batch_size"]: s["elapsed_ms_p50"] / s["batch_size"] for s in ref}
    return ms_per_trade


if __name__ == "__main__":
    main()
