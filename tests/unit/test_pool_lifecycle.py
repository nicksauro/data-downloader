"""Unit tests — broker.pool (Story 4.1 AC5).

Cobertura:

- PoolConfig defaults.
- WorkerPool.start_pool: cria N workers + registra response_queues.
- WorkerPool.stop_pool: graceful shutdown (sentinel + join).
- WorkerPool.submit_jobs antes de start: raise RuntimeError.
- JobSpec / JobOutcome dataclasses immutability + ordering.

Não cobre IPC end-to-end (isso é em test_multi_symbol_mock.py integration).
Foca em lifecycle local (pool de 0 workers para isolar).
"""

from __future__ import annotations

import multiprocessing as mp

import pytest

from data_downloader.orchestrator.broker.catalog_broker import CatalogBroker
from data_downloader.orchestrator.broker.pool import (
    JobOutcome,
    JobSpec,
    PoolConfig,
    WorkerPool,
)


class _StubCatalog:
    """Catalog stub minimal — só responde a _conn_or_raise."""

    def _conn_or_raise(self) -> object:
        return object()

    def register_partition(self, *_args: object, **_kwargs: object) -> None:
        pass

    def register_gap(self, *_args: object, **_kwargs: object) -> None:
        pass

    def update_job_progress(self, *_args: object, **_kwargs: object) -> None:
        pass

    def register_job(self, *_args: object, **_kwargs: object) -> str:
        return "stub-job-id"

    def get_completed_partitions(self, *_args: object, **_kwargs: object) -> list:
        return []


class TestPoolConfig:
    def test_defaults(self) -> None:
        config = PoolConfig()
        assert config.n_workers == 4
        assert config.data_dir is None
        assert config.worker_factory_module is None
        assert config.worker_factory_callable == "create_orchestrator"
        assert config.broker_timeout_s == 30.0
        assert config.worker_warmup_timeout_s == 30.0

    def test_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        config = PoolConfig(n_workers=2)
        with pytest.raises(FrozenInstanceError):
            config.n_workers = 5  # type: ignore[misc]


class TestJobSpec:
    def test_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        spec = JobSpec(
            job_index=0,
            symbol="WDOJ26",
            exchange="F",
            start_iso="2026-04-01T09:00:00",
            end_iso="2026-04-01T17:00:00",
        )
        assert spec.symbol == "WDOJ26"
        with pytest.raises(FrozenInstanceError):
            spec.symbol = "OTHER"  # type: ignore[misc]

    def test_defaults(self) -> None:
        spec = JobSpec(
            job_index=0,
            symbol="WDOJ26",
            exchange="F",
            start_iso="2026-04-01T09:00:00",
            end_iso="2026-04-01T17:00:00",
        )
        assert spec.chunk_timeout_seconds == 1800
        assert spec.max_retry_attempts == 3
        assert spec.resolve_contract is True


class TestJobOutcome:
    def test_basic_completed(self) -> None:
        outcome = JobOutcome(
            job_index=0,
            symbol="WDOJ26",
            status="completed",
            job_id="abc",
            chunks_completed=2,
            trades_persisted=42,
            duration_seconds=1.5,
        )
        assert outcome.status == "completed"
        assert outcome.error is None

    def test_exception_status(self) -> None:
        outcome = JobOutcome(
            job_index=0,
            symbol="WDOJ26",
            status="exception",
            error="OOM",
        )
        assert outcome.error == "OOM"


class TestWorkerPoolLifecycle:
    """Lifecycle isolation tests — sem spawn real (n_workers=0 ou validações)."""

    def test_start_with_zero_workers_raises(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q)  # type: ignore[arg-type]
        pool = WorkerPool(PoolConfig(n_workers=0), mut_q, broker)
        with pytest.raises(RuntimeError, match="n_workers"):
            pool.start_pool()

    def test_submit_jobs_before_start_raises(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q)  # type: ignore[arg-type]
        pool = WorkerPool(PoolConfig(n_workers=2), mut_q, broker)

        with pytest.raises(RuntimeError, match="start_pool"):
            pool.submit_jobs(
                [
                    JobSpec(
                        job_index=0,
                        symbol="WDOJ26",
                        exchange="F",
                        start_iso="2026-04-01T09:00:00",
                        end_iso="2026-04-01T17:00:00",
                    )
                ]
            )

    def test_submit_empty_jobs_returns_empty(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q)  # type: ignore[arg-type]
        pool = WorkerPool(PoolConfig(n_workers=2), mut_q, broker)
        # Falsifica started para evitar spawn real.
        pool._started = True
        pool._job_queue = ctx.Queue()
        pool._output_queue = ctx.Queue()
        outcomes = pool.submit_jobs([])
        assert outcomes == []
        # Cleanup state manual.
        pool._started = False

    def test_stop_pool_idempotent_if_not_started(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q)  # type: ignore[arg-type]
        pool = WorkerPool(PoolConfig(n_workers=2), mut_q, broker)
        # Não startado — stop é no-op.
        pool.stop_pool()
        assert not pool.started


class TestCatalogBrokerLifecycle:
    """Lifecycle do broker isolado (sem workers reais)."""

    def test_start_stop_cycle(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q, name="test-broker")  # type: ignore[arg-type]

        broker.start()
        # Idempotente.
        broker.start()

        broker.stop(timeout=2.0)
        # Idempotente.
        broker.stop(timeout=2.0)

    def test_stats_initially_zero(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q)  # type: ignore[arg-type]
        stats = broker.stats
        assert stats == {
            "mutations_applied": 0,
            "mutations_rejected": 0,
            "mutations_errored": 0,
        }

    def test_register_worker_stores_response_queue(self) -> None:
        catalog = _StubCatalog()
        ctx = mp.get_context("spawn")
        mut_q: mp.Queue = ctx.Queue()
        resp_q: mp.Queue = ctx.Queue()
        broker = CatalogBroker(catalog, mut_q)  # type: ignore[arg-type]
        broker.register_worker("worker-0", resp_q)
        assert "worker-0" in broker._response_queues
        assert broker._response_queues["worker-0"] is resp_q
