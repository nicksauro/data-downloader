"""Unit tests — DownloadHandle.cancel() H10 closure (Story 2.11).

Cobertura H10 (ADR-007a §"Cancel atômico"):

- ``cancel(*, timeout)`` retorna ``True`` quando worker termina dentro do
  timeout; ``False`` quando ainda rodando.
- ``handle.result()`` raise :class:`OperationCancelled` quando worker
  terminou em status ``"cancelled"``.
- ``cancelled()`` / ``is_cancelled`` non-blocking corretos.
- ``timeout=0.0`` → ``False`` imediato se worker ainda rodando.
- Cancel durante chunk em progresso é graceful (não interrompe chunk —
  worker decide quando checar e parar).
- Cancelamento idempotente — múltiplas chamadas seteam o flag uma vez.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.public_api.exceptions import OperationCancelled
from data_downloader.public_api.handle import (
    DownloadHandle,
    DownloadProgress,
    DownloadResult,
)


def _make_cancelled_result(trades: int = 0, partitions: tuple[Path, ...] = ()) -> DownloadResult:
    return DownloadResult(
        job_id="job-cancel",
        symbol="WDOJ26",
        exchange="F",
        actual_start=datetime(2026, 3, 1),
        actual_end=datetime(2026, 3, 5),
        trades_count=trades,
        partitions=partitions,
        duration_seconds=0.1,
        status="cancelled",
    )


def _make_completed_result(trades: int = 100) -> DownloadResult:
    return DownloadResult(
        job_id="job-ok",
        symbol="WDOJ26",
        exchange="F",
        actual_start=datetime(2026, 3, 1),
        actual_end=datetime(2026, 3, 5),
        trades_count=trades,
        partitions=(Path("/tmp/x.parquet"),),
        duration_seconds=0.1,
        status="completed",
    )


# =====================================================================
# cancel() return semantics
# =====================================================================


class TestCancelReturnValue:
    def test_cancel_returns_true_when_worker_terminates_within_timeout(self) -> None:
        """cancel(timeout=2.0) → True quando worker drena rápido."""

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            # Aguarda cancel; ao receber, encerra graceful em <50ms.
            cancel_event.wait(timeout=5.0)
            time.sleep(0.05)
            set_result(_make_cancelled_result(trades=42))

        handle = DownloadHandle(worker_target=_worker)
        # Pequeno sleep para garantir worker iniciou.
        time.sleep(0.02)
        result_bool = handle.cancel(timeout=2.0)
        assert result_bool is True

    def test_cancel_returns_false_when_timeout_expires(self) -> None:
        """cancel(timeout=0) imediato → False (worker ainda rodando)."""
        proceed = threading.Event()

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            proceed.wait(timeout=10.0)
            set_result(_make_cancelled_result())

        handle = DownloadHandle(worker_target=_worker)
        # Sem dar tempo do worker terminar, timeout zero retorna False.
        result_bool = handle.cancel(timeout=0.0)
        assert result_bool is False
        # Cleanup.
        proceed.set()
        handle.join(timeout=2.0)

    def test_cancel_idempotent(self) -> None:
        """Múltiplas chamadas a cancel apenas seteam o flag uma vez."""

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            cancel_event.wait(timeout=5.0)
            set_result(_make_cancelled_result())

        handle = DownloadHandle(worker_target=_worker)
        time.sleep(0.02)
        # Várias chamadas — todas válidas.
        r1 = handle.cancel(timeout=2.0)
        r2 = handle.cancel(timeout=2.0)
        r3 = handle.cancel(timeout=2.0)
        assert r1 is True
        assert r2 is True
        assert r3 is True
        assert handle.is_cancelling() is True


# =====================================================================
# result() raises OperationCancelled
# =====================================================================


class TestResultRaisesOperationCancelled:
    def test_result_raises_operation_cancelled_when_status_cancelled(self) -> None:
        """H10 closure: result() levanta OperationCancelled em cancel."""

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            cancel_event.wait(timeout=5.0)
            set_result(_make_cancelled_result(trades=42))

        handle = DownloadHandle(worker_target=_worker)
        time.sleep(0.02)
        handle.cancel(timeout=2.0)

        with pytest.raises(OperationCancelled) as exc_info:
            handle.result(timeout=2.0)
        # details contém info para microcopy.
        assert exc_info.value.details["trades_preserved"] == 42
        assert exc_info.value.details["job_id"] == "job-cancel"

    def test_result_returns_normally_when_status_completed(self) -> None:
        """Sem cancel, result() retorna DownloadResult normal."""

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            time.sleep(0.02)
            set_result(_make_completed_result(trades=100))

        handle = DownloadHandle(worker_target=_worker)
        result = handle.result(timeout=2.0)
        assert result.status == "completed"
        assert result.trades_count == 100

    def test_peek_result_returns_cancelled_without_raising(self) -> None:
        """peek_result() não raise — útil para inspeção pós-cancel."""

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            cancel_event.wait(timeout=5.0)
            set_result(_make_cancelled_result(trades=5))

        handle = DownloadHandle(worker_target=_worker)
        time.sleep(0.02)
        handle.cancel(timeout=2.0)

        # peek_result NÃO levanta.
        peeked = handle.peek_result()
        assert peeked is not None
        assert peeked.status == "cancelled"
        assert peeked.trades_count == 5


# =====================================================================
# cancelled() / is_cancelled — non-blocking probes
# =====================================================================


class TestCancelledProbe:
    def test_cancelled_false_before_cancel(self) -> None:
        proceed = threading.Event()

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            proceed.wait(timeout=10.0)
            set_result(_make_completed_result())

        handle = DownloadHandle(worker_target=_worker)
        assert handle.cancelled() is False
        assert handle.is_cancelled is False
        proceed.set()
        handle.join(timeout=2.0)

    def test_cancelled_false_when_cancel_pending_drain(self) -> None:
        """cancel pedido mas worker ainda drenando → cancelled() False."""
        proceed = threading.Event()

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            cancel_event.wait(timeout=5.0)
            # Simula drain longo.
            proceed.wait(timeout=5.0)
            set_result(_make_cancelled_result())

        handle = DownloadHandle(worker_target=_worker)
        time.sleep(0.02)
        # cancel set mas worker ainda drenando (proceed not set yet).
        handle.cancel(timeout=0.0)
        assert handle.is_cancelling() is True
        assert handle.cancelled() is False
        proceed.set()
        handle.join(timeout=2.0)

    def test_cancelled_true_after_worker_terminates_with_cancelled(self) -> None:
        def _worker(*, cancel_event, events_queue, set_result) -> None:
            cancel_event.wait(timeout=5.0)
            set_result(_make_cancelled_result())

        handle = DownloadHandle(worker_target=_worker)
        time.sleep(0.02)
        handle.cancel(timeout=2.0)
        assert handle.cancelled() is True
        assert handle.is_cancelled is True

    def test_cancelled_false_when_worker_completed_normally(self) -> None:
        """Worker terminou normalmente (sem cancel set) → cancelled() False."""

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            time.sleep(0.02)
            set_result(_make_completed_result())

        handle = DownloadHandle(worker_target=_worker)
        handle.result(timeout=2.0)
        assert handle.cancelled() is False
        assert handle.is_cancelled is False


# =====================================================================
# Graceful: cancel mid-chunk não interrompe
# =====================================================================


class TestGracefulCancel:
    def test_cancel_does_not_interrupt_chunk_in_progress(self) -> None:
        """Cancel é cooperativo: worker decide quando checar e parar.

        Simula worker que está "no meio" de um chunk (sleep) — cancel não
        deveria abortar o sleep; apenas o próximo chunk é skipped.
        """
        chunks_started: list[int] = []
        chunks_completed: list[int] = []

        def _worker(*, cancel_event, events_queue, set_result) -> None:
            for i in range(5):
                # Boundary check ENTRE chunks.
                if cancel_event.is_set():
                    break
                chunks_started.append(i)
                # Simula chunk em andamento — não checa cancel no meio.
                time.sleep(0.05)
                chunks_completed.append(i)
                events_queue.put(
                    DownloadProgress(
                        total=5,
                        done=i + 1,
                        message=f"chunk {i + 1}",
                        trades_received=(i + 1) * 10,
                    )
                )
            set_result(
                _make_cancelled_result(trades=len(chunks_completed) * 10)
                if cancel_event.is_set()
                else _make_completed_result(trades=50)
            )

        handle = DownloadHandle(worker_target=_worker)
        # Aguarda chunk 0 iniciar e parcialmente completar.
        time.sleep(0.07)
        handle.cancel(timeout=2.0)

        # Pelo menos 1 chunk foi iniciado E completado (graceful — não interrompido).
        assert len(chunks_started) >= 1
        assert len(chunks_completed) >= 1
        # E não todos os 5 (cancel teve efeito).
        assert len(chunks_started) < 5

        # result raises OperationCancelled.
        with pytest.raises(OperationCancelled):
            handle.result(timeout=2.0)
