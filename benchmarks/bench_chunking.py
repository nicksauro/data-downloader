"""bench_chunking.py — Tempo total simulado para baixar 1 mês de WDOJ26.

Objetivo:
    Simular download completo de 1 mês de WDOJ26 (~22 dias úteis × ~500k
    trades/dia = ~11M trades). Mock DLL gera trades realistas com taxa
    realista (4kHz pico de trade rate em horário de abertura).

Target V1:
    < 5min em rede boa (assume mock DLL = 0 latência de rede; baseline real
    em Story 1.8 com DLL real).

Hipóteses a testar:
    H1: Chunking diário (1 partição/dia) é Pareto-ótimo entre overhead de
        coordenação e isolamento de falha.
    H2: Tempo dominante é IO de Parquet write (não DLL/rede em mock).
    H3: Reconnect ratio 99% (Quirk Q-RECON) NÃO afeta tempo total porque
        reconnect é < 200ms vs ~13s/dia de download.

Estágios medidos:
    - dll_init_ms
    - per_chunk_total_ms (mediana sobre 22 chunks)
    - per_chunk_dll_ms
    - per_chunk_ingest_ms
    - per_chunk_write_ms
    - per_chunk_commit_ms
    - dll_finalize_ms
    - total_ms

Output:
    benchmarks/results/bench_chunking-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_chunking",
        "symbol": "WDOJ26",
        "month": "2026-04",
        "n_chunks": 22,
        "n_trades_total": 11000000,
        "stages": {...},
        "total_ms": 0,
        "verdict": "PASS|FAIL vs 5min target"
    }
"""

from __future__ import annotations

import json  # noqa: F401  # used by commented-out skeleton body
import statistics  # noqa: F401  # used by commented-out skeleton body
import time  # noqa: F401  # used by commented-out skeleton body
from pathlib import Path
from typing import Any

# TODO: imports
# from benchmarks.fixtures.mock_dll import MockProfitDLL
# from benchmarks.fixtures.synthetic_trades import generate
# from data_downloader.orchestrator import Orchestrator

RESULTS_DIR = Path(__file__).parent / "results"
TARGET_TOTAL_MIN = 5.0
SYMBOL = "WDOJ26"
MONTH = "2026-04"
TRADES_PER_DAY = 500_000
N_BUSINESS_DAYS = 22


def setup_mock_dll_with_realistic_rate() -> Any:
    """Mock DLL que entrega trades a taxa realista (~4kHz pico, ~1kHz médio)."""
    # TODO:
    # mock = MockProfitDLL()
    # mock.set_trade_rate_profile("realistic_b3")  # rampup 9h-10h, plateau, queda 17h
    # return mock
    raise NotImplementedError("Aguarda fixtures.mock_dll")


def measure_full_month(tmp_dir: Path) -> dict[str, Any]:
    """Simula download de 22 chunks; mede tempo por estágio."""
    # TODO:
    # mock_dll = setup_mock_dll_with_realistic_rate()
    # orch = Orchestrator(dll=mock_dll, output_dir=tmp_dir)
    #
    # stages: dict[str, list[float]] = {
    #     "dll_init_ms": [], "per_chunk_dll_ms": [], "per_chunk_ingest_ms": [],
    #     "per_chunk_write_ms": [], "per_chunk_commit_ms": [],
    # }
    #
    # t_total_0 = time.perf_counter_ns()
    # t0 = time.perf_counter_ns()
    # orch.init()
    # stages["dll_init_ms"].append((time.perf_counter_ns() - t0) / 1e6)
    #
    # for day in range(1, N_BUSINESS_DAYS + 1):
    #     handle = orch.download(symbol=SYMBOL, date=f"2026-04-{day:02d}")
    #     handle.wait()  # bloqueia até chunk commitado
    #     # extrair stages timestamps via metrics handle
    #     for k, v in handle.metrics.stages.items():
    #         stages[k].append(v)
    #
    # t0 = time.perf_counter_ns()
    # orch.finalize()
    # finalize_ms = (time.perf_counter_ns() - t0) / 1e6
    #
    # total_ms = (time.perf_counter_ns() - t_total_0) / 1e6
    #
    # return {
    #     "symbol": SYMBOL, "month": MONTH,
    #     "n_chunks": N_BUSINESS_DAYS,
    #     "n_trades_total": TRADES_PER_DAY * N_BUSINESS_DAYS,
    #     "stages": {
    #         "dll_init_ms": stages["dll_init_ms"][0],
    #         "dll_finalize_ms": finalize_ms,
    #         "per_chunk_total_ms_p50": statistics.median(
    #             sum(stages[k][i] for k in ["per_chunk_dll_ms", "per_chunk_ingest_ms",
    #                                       "per_chunk_write_ms", "per_chunk_commit_ms"])
    #             for i in range(N_BUSINESS_DAYS)
    #         ),
    #         **{k: statistics.median(v) for k, v in stages.items() if v},
    #     },
    #     "total_ms": total_ms,
    # }
    raise NotImplementedError("Aguarda Orchestrator (Story 1.7a)")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO:
    # result = measure_full_month(tmp_dir)
    # result["verdict"] = "PASS" if result["total_ms"] < TARGET_TOTAL_MIN * 60_000 else "FAIL"
    # _save(result)
    raise NotImplementedError("bench_chunking é esqueleto sintético (Story 1.4.5).")


if __name__ == "__main__":
    main()
