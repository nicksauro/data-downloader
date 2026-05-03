"""bench_callback_to_disk.py — Latência callback DLL → trade visível em Parquet.

Objetivo:
    Medir latência ponta-a-ponta: mock DLL injeta callback → ConnectorThread
    → IngestorThread → WriterThread → fsync → trade visível em Parquet.
    p50, p95, p99 sobre 1M callbacks. CRÍTICO: incluir cenário de pausa
    simulada do writer para validar back-pressure.

Target V1:
    p99 < 100ms (cenário 0ms pausa).

Hipóteses a testar:
    H1: Pipeline default (queue 10000, writer 1 thread) atinge p99 < 100ms
        em condições normais (writer NÃO pausado).
    H2: Quando writer pausa 100ms (GC pause), back-pressure se propaga sem
        drop — queue absorve.
    H3: Quando writer pausa 500ms (Windows Defender scan), queue=10000 enche;
        comportamento depende de ProfitDLL ser block-on-full ou drop-on-full
        (CRITICAL: pergunta aberta para Nelo — finding H4).
    H4: Quando writer pausa 2000ms, drops são INEVITÁVEIS sem queue gigante;
        precisamos métrica `dll_drops_total` exposta + alarme.

Cenários (matriz):
    writer_pause_ms: [0, 100, 500, 2000]
    queue_size: [1000, 10000, 100000]
    callbacks_per_sec_injected: [10_000, 100_000, 1_000_000]

Output:
    benchmarks/results/bench_callback_to_disk-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_callback_to_disk",
        "scenarios": [
            {"writer_pause_ms": 0, "queue_size": 10000, "rate_per_sec": 100000,
             "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0,
             "n_callbacks": 0, "n_drops": 0, "n_visible": 0,
             "queue_max_depth": 0}
        ],
        "verdict_baseline": "PASS|FAIL",  # cenário 0ms pause
        "back_pressure_behavior": "block|drop|unknown"
    }
"""

from __future__ import annotations

import json  # noqa: F401  # used by commented-out skeleton body
import statistics  # noqa: F401  # used by commented-out skeleton body
import time  # noqa: F401  # used by commented-out skeleton body
from pathlib import Path
from typing import Any

# TODO: imports
# import threading
# import queue
# from benchmarks.fixtures.mock_dll import MockProfitDLL
# from data_downloader.ingest import IngestorThread
# from data_downloader.writer import WriterThread

RESULTS_DIR = Path(__file__).parent / "results"
N_CALLBACKS = 1_000_000
TARGET_P99_MS = 100.0

SCENARIOS = [
    # baseline cenário target
    {"writer_pause_ms": 0, "queue_size": 10_000, "rate_per_sec": 100_000},
    # GC pause realista
    {"writer_pause_ms": 100, "queue_size": 10_000, "rate_per_sec": 100_000},
    # Windows Defender scan
    {"writer_pause_ms": 500, "queue_size": 10_000, "rate_per_sec": 100_000},
    # worst case: DLL load spike
    {"writer_pause_ms": 2_000, "queue_size": 10_000, "rate_per_sec": 100_000},
    # queue grande absorve mais
    {"writer_pause_ms": 500, "queue_size": 100_000, "rate_per_sec": 100_000},
    # rate alto stress
    {"writer_pause_ms": 0, "queue_size": 10_000, "rate_per_sec": 1_000_000},
]


def setup_pipeline(scenario: dict[str, Any], tmp_dir: Path) -> Any:
    """Constrói pipeline: MockDLL → ConnectorThread → IngestorThread → WriterThread."""
    # TODO:
    # mock_dll = MockProfitDLL()
    # ingestor = IngestorThread(queue_size=scenario["queue_size"])
    # writer = WriterThread(
    #     output_dir=tmp_dir,
    #     pause_ms_per_batch=scenario["writer_pause_ms"],  # injetar pausa simulada
    # )
    # mock_dll.bind_callback(ingestor.on_trade)
    # ingestor.bind_writer(writer)
    # return mock_dll, ingestor, writer
    raise NotImplementedError("Aguarda mock_dll + IngestorThread + WriterThread")


def measure_scenario(scenario: dict[str, Any], tmp_dir: Path) -> dict[str, Any]:
    """Roda 1M callbacks; mede latência callback → visible em Parquet por amostragem."""
    # TODO:
    # mock_dll, ingestor, writer = setup_pipeline(scenario, tmp_dir)
    #
    # latencies_ns: list[int] = []
    # n_drops = 0
    # queue_max_depth = 0
    #
    # # Marcar 1% dos callbacks com timestamp_inject_ns; após writer commit,
    # # ler Parquet e medir delta para esses marcados.
    # SAMPLE_RATE = 0.01
    # n_sampled = int(N_CALLBACKS * SAMPLE_RATE)
    #
    # writer.start()
    # ingestor.start()
    #
    # interval_ns = int(1e9 / scenario["rate_per_sec"])
    # for i in range(N_CALLBACKS):
    #     inject_ns = time.perf_counter_ns()
    #     dropped = not mock_dll.fire_trade(
    #         trade_id=i, inject_marker=(i % int(1/SAMPLE_RATE) == 0),
    #         inject_ts_ns=inject_ns,
    #     )
    #     if dropped:
    #         n_drops += 1
    #     queue_max_depth = max(queue_max_depth, ingestor.queue.qsize())
    #     # rate limit
    #     while time.perf_counter_ns() < inject_ns + interval_ns:
    #         pass
    #
    # ingestor.shutdown()
    # writer.shutdown()
    #
    # # Ler Parquet, comparar timestamps marcados
    # # latencies_ns = ...
    #
    # n_visible = ...
    # latencies_ms = [ns / 1e6 for ns in latencies_ns]
    # return {
    #     **scenario,
    #     "p50_ms": statistics.median(latencies_ms),
    #     "p95_ms": sorted(latencies_ms)[int(0.95 * len(latencies_ms))],
    #     "p99_ms": sorted(latencies_ms)[int(0.99 * len(latencies_ms))],
    #     "max_ms": max(latencies_ms),
    #     "n_callbacks": N_CALLBACKS,
    #     "n_drops": n_drops,
    #     "n_visible": n_visible,
    #     "queue_max_depth": queue_max_depth,
    # }
    raise NotImplementedError("Aguarda pipeline real (Stories 1.2, 1.3, 1.4)")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO: rodar todos cenários, decidir baseline=cenário[0]
    # back_pressure = "block" if max(s["n_drops"] == 0 for s in scenarios) else "drop"
    raise NotImplementedError(
        "bench_callback_to_disk é CRÍTICO (Story 1.4.5). "
        "Cenário writer_pause_ms=500ms valida finding H4 (back-pressure)."
    )


if __name__ == "__main__":
    main()
