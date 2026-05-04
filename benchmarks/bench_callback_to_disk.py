"""bench_callback_to_disk.py — Latência callback DLL -> trade visível em Parquet.

Objetivo:
    Medir latência ponta-a-ponta: callback DLL -> queue -> writer thread
    -> ParquetWriter -> trade visível em disk. p50/p95/p99 sobre N
    callbacks. CRÍTICO: cenários incluem pausas simuladas do writer
    (GC pause, AV scan) para validar back-pressure (finding H4).

Target V1:
    p99 < 100ms (cenário writer_pause_ms=0 — baseline).

NOTA SOBRE PRODUÇÃO vs BENCH:
    Em produção (Story 1.7) writes acontecem 1x por chunk (~500k trades),
    não a cada batch pequeno; portanto p99 callback->disk em produção
    é dominado pelo tempo de chunk completar. Esta bench mede o caso
    onde writer drena queue continuamente em batches grandes (10k);
    métrica relevante é (a) drops sob back-pressure (b) p99 latência
    quando writer não pausa. Para medir "trade gravado quando o batch
    do writer flush" — granular ao writer-cycle.

KNOWN ISSUE (mini-council Pyro+Sol — ver docs/decisions/COUNCIL-02):
    ParquetWriter.write faz merge completo (read+union+dedup+sort+write)
    quando partition existe. Isso significa que escrita repetida sobre
    mesma partition é O(N²) no número total de trades. Bench usa
    batch_max grande (10k) para minimizar esse overhead.


Hipóteses a testar (alinhamento com BASELINES.md + finding H4):
    H1: Pipeline default (queue=10k, writer 1 thread) atinge p99 < 100ms
        em condições normais (writer NÃO pausado).
    H2: Quando writer pausa 100ms (GC pause), back-pressure se propaga;
        DLL via mock bloqueia ou drop (queue.put_nowait com queue cheia).
    H3: Quando writer pausa 500ms (Windows Defender scan), queue=10k
        enche em 5s @ 100k/s rate; comportamento depende de mock_dll
        ser block-on-full (Q-FLOW resposta de Nelo: provavelmente
        bloqueia no envio do callback) ou drop-on-full.
    H4: Quando writer pausa 2000ms, drops são INEVITÁVEIS sem queue
        gigante; precisamos métrica `dll_drops_total` exposta + alarme
        — esta bench prova a hipótese H4.

Pipeline simulado (sem depender de Story 1.7 orchestrator):
    MockDLL injector --(callback fn)--> queue.Queue(maxsize=N)
                                    -> writer_thread:
                                       while not stop:
                                          batch = drain queue
                                          time.sleep(writer_pause_ms/1000)
                                          ParquetWriter.write(batch, partition)

Latência medida:
    inject_ts_ns capturado no momento do callback (synthetic);
    visible_ts_ns = time.perf_counter_ns() após ParquetWriter.write retornar
    para o batch que continha o trade marcado.

Output:
    benchmarks/results/bench_callback_to_disk-{date}-{git_sha}.json
"""

from __future__ import annotations

import argparse
import queue
import shutil
import statistics
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from benchmarks._common import (
    build_result_envelope,
    percentile,
    print_summary,
    save_results,
)
from benchmarks.fixtures.synthetic_trades import generate
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey

DEFAULT_N_CALLBACKS = 100_000
TARGET_P99_MS_BASELINE = 100.0

# Cenários reduzidos: rate alvo é fixado em 100k/s; varia writer_pause +
# queue_size para validar H2/H3/H4. Cenário rate=1M/s removido — irrealista
# para callback DLL real (~4kHz peak, manual ProfitDLL).
SCENARIOS_DEFAULT = [
    # baseline — sem pausa, streaming pequenos batches (revela merge overhead)
    {
        "writer_pause_ms": 0,
        "queue_size": 10_000,
        "rate_per_sec": 100_000,
        "drain_strategy": "stream",
    },
    # GC pause realista
    {
        "writer_pause_ms": 100,
        "queue_size": 10_000,
        "rate_per_sec": 100_000,
        "drain_strategy": "stream",
    },
    # Windows Defender scan
    {
        "writer_pause_ms": 500,
        "queue_size": 10_000,
        "rate_per_sec": 100_000,
        "drain_strategy": "stream",
    },
    # worst case — bloqueio de DLL load spike
    {
        "writer_pause_ms": 2_000,
        "queue_size": 10_000,
        "rate_per_sec": 100_000,
        "drain_strategy": "stream",
    },
    # queue grande absorve mais
    {
        "writer_pause_ms": 500,
        "queue_size": 100_000,
        "rate_per_sec": 100_000,
        "drain_strategy": "stream",
    },
    # CHUNK MODE: drain todo callback antes de write único (modelo Story 1.7)
    # — mostra lower bound de latência sem merge overhead.
    {
        "writer_pause_ms": 0,
        "queue_size": 100_000,
        "rate_per_sec": 100_000,
        "drain_strategy": "chunk",
    },
]


def _writer_thread_loop(
    q: queue.Queue,
    stop_event: threading.Event,
    *,
    writer: ParquetWriter,
    partition: PartitionKey,
    writer_pause_ms: float,
    batch_max: int,
    batch_max_wait_ms: float,
    metrics: dict[str, Any],
    drain_strategy: str = "stream",
) -> None:
    """Drain loop do writer: consome queue, em batches, grava com pausa simulada.

    Cada elemento da queue é (trade_dict, marker_inject_ns_or_none).
    Após write, registra (marker_inject_ns, write_done_ns) em
    ``metrics['latencies_ns']`` para markers != None.

    drain_strategy:
        "stream" — flush a cada batch_max OR batch_max_wait_ms (fluxo contínuo,
            mostra overhead de merge se partition existe).
        "chunk" — acumula TUDO até stop_event; faz 1 write final
            (modela Story 1.7 orchestrator: 1 write/chunk).
    """
    batch_id = 0
    accumulated: list[dict] = []
    accumulated_markers: list[int | None] = []

    while not stop_event.is_set() or not q.empty():
        batch: list[dict] = []
        markers: list[int | None] = []
        deadline = time.perf_counter() + (batch_max_wait_ms / 1000.0)

        try:
            item = q.get(timeout=0.05)
            batch.append(item[0])
            markers.append(item[1])
        except queue.Empty:
            continue

        # Drena até batch_max ou deadline.
        while len(batch) < batch_max and time.perf_counter() < deadline:
            try:
                item = q.get_nowait()
                batch.append(item[0])
                markers.append(item[1])
            except queue.Empty:
                break

        if not batch:
            continue

        if drain_strategy == "chunk":
            # Acumula sem flush.
            accumulated.extend(batch)
            accumulated_markers.extend(markers)
            continue

        # Pausa simulada (GC / AV scan) — só stream.
        if writer_pause_ms > 0:
            time.sleep(writer_pause_ms / 1000.0)

        # Write atômico via ParquetWriter.
        try:
            writer.write(
                batch,
                partition,
                dll_version="4.0.0.30-mock",
                chunk_id=f"bench-cb-batch-{batch_id}",
            )
            write_done_ns = time.perf_counter_ns()
            for marker in markers:
                if marker is not None:
                    metrics["latencies_ns"].append(write_done_ns - marker)
                    metrics["n_visible"] += 1
        except Exception as exc:
            metrics["write_errors"].append(str(exc))

        batch_id += 1

    # Strategy chunk: fim do loop = stop_event setado E queue vazia.
    # Faz 1 write único final.
    if drain_strategy == "chunk" and accumulated:
        if writer_pause_ms > 0:
            time.sleep(writer_pause_ms / 1000.0)
        try:
            writer.write(
                accumulated,
                partition,
                dll_version="4.0.0.30-mock",
                chunk_id="bench-cb-chunk-final",
            )
            write_done_ns = time.perf_counter_ns()
            for marker in accumulated_markers:
                if marker is not None:
                    metrics["latencies_ns"].append(write_done_ns - marker)
                    metrics["n_visible"] += 1
        except Exception as exc:
            metrics["write_errors"].append(str(exc))


def measure_scenario(
    scenario: dict[str, Any], tmp_dir: Path, n_callbacks: int, sample_rate: float
) -> dict[str, Any]:
    """Roda 1 scenario: inject n_callbacks via mock DLL, mede latency."""
    queue_size = scenario["queue_size"]
    rate_per_sec = scenario["rate_per_sec"]
    writer_pause_ms = scenario["writer_pause_ms"]
    drain_strategy = scenario.get("drain_strategy", "stream")

    # Diretório dedicado para este scenario (evita merge entre scenarios).
    scenario_dir = (
        tmp_dir / f"sc_{drain_strategy}_pause{writer_pause_ms}_q{queue_size}_r{rate_per_sec}"
    )
    scenario_dir.mkdir(parents=True, exist_ok=True)
    writer = ParquetWriter(data_dir=scenario_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)

    q: queue.Queue = queue.Queue(maxsize=queue_size)
    stop_event = threading.Event()
    metrics: dict[str, Any] = {
        "latencies_ns": [],
        "n_visible": 0,
        "write_errors": [],
    }

    # Heurística batch: writer drena até 10k trades por write OR 50ms.
    # Batch maior compensa overhead de merge no ParquetWriter (read+union+dedup+sort
    # +write toda vez que partition existe — O(N) por write).
    writer_thread = threading.Thread(
        target=_writer_thread_loop,
        args=(q, stop_event),
        kwargs={
            "writer": writer,
            "partition": partition,
            "writer_pause_ms": writer_pause_ms,
            "batch_max": 10_000,
            "batch_max_wait_ms": 50.0,
            "metrics": metrics,
            "drain_strategy": drain_strategy,
        },
        daemon=True,
        name=f"writer-{drain_strategy}-pause{writer_pause_ms}",
    )
    writer_thread.start()

    # Pré-gera trades (evita custo de geração no hot loop de inject).
    trades = list(generate(n_callbacks, symbol="WDOJ26", seed=42))

    interval_ns = int(1e9 / rate_per_sec)
    sample_period = max(1, int(1.0 / sample_rate))

    n_drops = 0
    queue_max_depth = 0
    inject_start = time.perf_counter_ns()

    for i, trade in enumerate(trades):
        # Marker timestamp (apenas para 1% — ou 100% se sample_rate=1.0).
        marker = time.perf_counter_ns() if (i % sample_period == 0) else None

        try:
            # Block-on-full simula DLL real (Q-FLOW: Nelo confirmou que ProfitDLL
            # bloqueia no thread DLL se callback não retorna — não dropa trades).
            # Para reproduzir drop-on-full, usar put_nowait (descomente abaixo).
            #
            # Default: put com timeout pequeno -> drop se não conseguir em 10ms
            # (simula DLL "perdendo" trade se aplicação não aceita rápido).
            q.put((trade, marker), timeout=0.01)
        except queue.Full:
            n_drops += 1

        depth = q.qsize()
        if depth > queue_max_depth:
            queue_max_depth = depth

        # Rate limit (busy wait fino para taxas altas).
        target_ns = inject_start + (i + 1) * interval_ns
        while time.perf_counter_ns() < target_ns:
            pass

    # Aguarda writer drenar.
    inject_end = time.perf_counter_ns()
    stop_event.set()
    writer_thread.join(timeout=30.0)
    if writer_thread.is_alive():
        # Ainda drenando; aguarda mais.
        writer_thread.join(timeout=30.0)

    inject_elapsed_s = (inject_end - inject_start) / 1e9
    actual_rate = n_callbacks / inject_elapsed_s if inject_elapsed_s > 0 else 0.0

    latencies_ms = sorted(ns / 1e6 for ns in metrics["latencies_ns"])

    if not latencies_ms:
        # Nenhum trade marker chegou ao disco — drop completo.
        return {
            **scenario,
            "n_callbacks": n_callbacks,
            "n_drops": n_drops,
            "n_visible": metrics["n_visible"],
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
            "queue_max_depth": queue_max_depth,
            "actual_rate_per_sec": actual_rate,
            "write_errors_count": len(metrics["write_errors"]),
            "back_pressure_observed": "drop_complete",
        }

    # Detecta back-pressure: drops > 0 = drop-on-full; senão block (writer foi
    # mais rápido que rate, ou put bloqueou e re-tentou — depende do timeout).
    bp_label = "drop" if n_drops > 0 else "block_or_absorb"

    return {
        **scenario,
        "n_callbacks": n_callbacks,
        "n_drops": n_drops,
        "drop_pct": (n_drops / n_callbacks) * 100,
        "n_visible": metrics["n_visible"],
        "p50_ms": statistics.median(latencies_ms),
        "p95_ms": percentile(latencies_ms, 0.95),
        "p99_ms": percentile(latencies_ms, 0.99),
        "max_ms": max(latencies_ms),
        "queue_max_depth": queue_max_depth,
        "actual_rate_per_sec": actual_rate,
        "write_errors_count": len(metrics["write_errors"]),
        "back_pressure_observed": bp_label,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-callbacks", type=int, default=DEFAULT_N_CALLBACKS, help="callbacks por scenario"
    )
    parser.add_argument(
        "--sample-rate", type=float, default=0.01, help="frac trades marcados para latency"
    )
    parser.add_argument(
        "--scenario-only", type=int, default=None, help="roda apenas scenario [idx]"
    )
    args = parser.parse_args()

    n_callbacks = args.n_callbacks
    sample_rate = args.sample_rate

    scenarios_to_run = (
        [SCENARIOS_DEFAULT[args.scenario_only]]
        if args.scenario_only is not None
        else SCENARIOS_DEFAULT
    )

    print(
        f"[bench_callback_to_disk] {len(scenarios_to_run)} scenarios, "
        f"{n_callbacks:_} callbacks/scenario, sample_rate={sample_rate}"
    )

    tmp_root = Path(tempfile.mkdtemp(prefix="bench_cb_to_disk_"))
    try:
        results: list[dict[str, Any]] = []
        for sc in scenarios_to_run:
            print(
                f"\n[bench_callback_to_disk] writer_pause={sc['writer_pause_ms']}ms, "
                f"queue={sc['queue_size']:_}, rate={sc['rate_per_sec']:_}/s"
            )
            res = measure_scenario(sc, tmp_root, n_callbacks, sample_rate)
            results.append(res)
            print(
                f"  -> p50 {res['p50_ms']:.1f}ms | p99 {res['p99_ms']:.1f}ms | "
                f"max {res['max_ms']:.1f}ms | drops {res['n_drops']} "
                f"({res.get('drop_pct', 0):.2f}%) | "
                f"queue_max_depth={res['queue_max_depth']} | "
                f"actual_rate {res['actual_rate_per_sec']:_.0f}/s | "
                f"BP={res['back_pressure_observed']}"
            )

        # Verdict baseado em chunk-mode (modela orchestrator real Story 1.7).
        # Stream-mode é informativo (mostra overhead de merge se write é per-batch).
        chunk_baseline = next(
            (
                r
                for r in results
                if r.get("drain_strategy") == "chunk" and r["writer_pause_ms"] == 0
            ),
            None,
        )
        stream_baseline = next(
            (
                r
                for r in results
                if r.get("drain_strategy", "stream") == "stream" and r["writer_pause_ms"] == 0
            ),
            results[0],
        )
        # Verdict primário: chunk-mode (production design). Stream é informativo.
        verdict_target_basis = chunk_baseline if chunk_baseline else stream_baseline
        verdict = "PASS" if verdict_target_basis["p99_ms"] <= TARGET_P99_MS_BASELINE else "FAIL"

        # H4 hypothesis: validation
        h4_writer_2000ms = next((r for r in results if r["writer_pause_ms"] == 2000), None)
        h4_observation: dict[str, Any] = {}
        if h4_writer_2000ms is not None:
            drops = h4_writer_2000ms["n_drops"]
            h4_observation = {
                "scenario": "writer_pause_2000ms",
                "drops": drops,
                "drops_pct": h4_writer_2000ms.get("drop_pct", 0),
                "verdict": (
                    "H4 CONFIRMED - drops inevitaveis sem queue gigante; alarme obrigatorio"
                    if drops > 0
                    else "H4 PARTIAL - queue absorveu; back-pressure tolerou"
                ),
                "back_pressure_behavior": h4_writer_2000ms["back_pressure_observed"],
            }

        summary = {
            "primary_baseline (chunk-mode)": {
                "drain_strategy": verdict_target_basis.get("drain_strategy", "stream"),
                "writer_pause_ms": verdict_target_basis["writer_pause_ms"],
                "queue_size": verdict_target_basis["queue_size"],
                "rate_per_sec": verdict_target_basis["rate_per_sec"],
                "p99_ms": verdict_target_basis["p99_ms"],
                "p50_ms": verdict_target_basis["p50_ms"],
                "drops": verdict_target_basis["n_drops"],
            },
            "stream_baseline (informational)": {
                "writer_pause_ms": stream_baseline["writer_pause_ms"],
                "queue_size": stream_baseline["queue_size"],
                "p99_ms": stream_baseline["p99_ms"],
                "p50_ms": stream_baseline["p50_ms"],
                "note": "stream-mode mostra overhead do merge per-batch (ParquetWriter rewrite)",
            },
            "vs_target_p99 (chunk-mode primary)": {
                "target_value_ms": TARGET_P99_MS_BASELINE,
                "measured_value_ms": verdict_target_basis["p99_ms"],
                "delta_pct": (
                    (
                        (verdict_target_basis["p99_ms"] - TARGET_P99_MS_BASELINE)
                        / TARGET_P99_MS_BASELINE
                    )
                    * 100
                    if TARGET_P99_MS_BASELINE > 0
                    else 0
                ),
            },
            "verdict": verdict,
            "h4_hypothesis": h4_observation,
        }

        envelope = build_result_envelope(
            "bench_callback_to_disk",
            config={
                "n_callbacks_per_scenario": n_callbacks,
                "sample_rate": sample_rate,
                "writer_batch_max": 10_000,
                "writer_batch_max_wait_ms": 50.0,
                "queue_put_timeout_s": 0.01,
            },
            scenarios=results,
            summary=summary,
            notes=(
                "Latency callback->disk via mock pipeline (queue + writer thread + "
                "ParquetWriter). queue.put timeout=10ms simula drop se DLL fosse "
                "non-blocking; produção (ProfitDLL) bloqueia no thread DLL "
                "(Q-FLOW Nelo). Scenario writer_pause_ms=2000 valida finding H4."
            ),
        )
        path = save_results(envelope)
        print(f"\n[bench_callback_to_disk] resultados salvos em: {path}")
        print_summary(envelope)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
