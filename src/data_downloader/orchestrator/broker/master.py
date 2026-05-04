"""data_downloader.orchestrator.broker.master — High-level coordinator (Story 4.1 AC6).

Owner: Aria (orchestration design) | Impl: Dex.
Refs:

- ``docs/adr/ADR-015-multiprocess-catalog.md`` §"Arquitetura"
- ``docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md`` D1

:class:`MultiSymbolMaster` é o **high-level coordinator** que junta:

- :class:`Catalog` (Story 1.5) — fonte única SQLite no master.
- :class:`CatalogBroker` — drena mutation_queue serializa SQLite writes.
- :class:`WorkerPool` — pool persistente N workers (cada um = 1 processo + 1 DLL).
- :class:`MultiSymbolMaster.download_multi(jobs)` — distribui jobs e
  retorna outcomes.

Lifecycle (context manager):

```python
with MultiSymbolMaster(catalog, pool_config) as master:
    outcomes = master.download_multi(jobs)
```

Ordem de criação garantida:

1. Catalog já criado (caller).
2. mutation_queue criada (mp.Queue).
3. CatalogBroker criado e iniciado (registra response_queues lazy).
4. WorkerPool criado e startado (registra response_queues no broker).
5. Workers carregam factory + DLL.

Ordem de teardown:

1. ``WorkerPool.stop_pool`` (envia sentinels + join workers).
2. ``CatalogBroker.stop`` (drena fila pendente + join thread).
3. Catalog é responsabilidade do caller (não fechamos aqui).
"""

from __future__ import annotations

import logging
import multiprocessing as mp
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any

from data_downloader.orchestrator.broker.catalog_broker import CatalogBroker
from data_downloader.orchestrator.broker.pool import (
    JobOutcome,
    JobSpec,
    PoolConfig,
    WorkerPool,
)

if TYPE_CHECKING:
    from data_downloader.storage.catalog import Catalog

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MultiSymbolJobConfig:
    """Spec leve de 1 job multi-symbol (envelope para CLI ou caller).

    Diferente de :class:`JobConfig` (orchestrator.py) — esta dataclass é
    pickle-safe (datetime serializado pelo pool antes de submeter).
    """

    symbol: str
    exchange: str
    start: datetime
    end: datetime
    chunk_timeout_seconds: int = 1800
    max_retry_attempts: int = 3
    resolve_contract: bool = True


class MultiSymbolMaster:
    """Coordinator: catalog + broker + pool.

    Args:
        catalog: :class:`Catalog` já inicializado (master process).
        pool_config: :class:`PoolConfig` para o WorkerPool.

    Attributes:
        catalog: Referência ao Catalog injetado.
        broker: :class:`CatalogBroker` criado em ``__enter__``.
        pool: :class:`WorkerPool` criado em ``__enter__``.

    Notes:
        Use como context manager para garantir cleanup:

        ```python
        with MultiSymbolMaster(catalog, config) as master:
            outcomes = master.download_multi(jobs)
        # broker e pool stopados automaticamente
        ```
    """

    def __init__(
        self,
        catalog: Catalog,
        pool_config: PoolConfig,
    ) -> None:
        self._catalog = catalog
        self._pool_config = pool_config
        self._mutation_queue: mp.Queue[Any] | None = None
        self._broker: CatalogBroker | None = None
        self._pool: WorkerPool | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> MultiSymbolMaster:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia broker thread + worker pool. Idempotente."""
        if self._broker is not None and self._pool is not None and self._pool.started:
            return

        ctx = mp.get_context("spawn")
        self._mutation_queue = ctx.Queue()

        self._broker = CatalogBroker(
            catalog=self._catalog,
            mutation_queue=self._mutation_queue,
        )
        self._broker.start()

        self._pool = WorkerPool(
            config=self._pool_config,
            mutation_queue=self._mutation_queue,
            broker=self._broker,
        )
        self._pool.start_pool()

        _LOG.info(
            "multi_symbol_master.started",
            extra={"n_workers": self._pool_config.n_workers},
        )

    def stop(self) -> None:
        """Graceful shutdown: pool first, depois broker. Idempotente."""
        if self._pool is not None and self._pool.started:
            try:
                self._pool.stop_pool()
            except Exception as exc:
                _LOG.warning(
                    "multi_symbol_master.pool_stop_failed",
                    extra={"error": str(exc)},
                )
        if self._broker is not None:
            try:
                self._broker.stop()
            except Exception as exc:
                _LOG.warning(
                    "multi_symbol_master.broker_stop_failed",
                    extra={"error": str(exc)},
                )
        self._pool = None
        self._broker = None
        self._mutation_queue = None

    # ------------------------------------------------------------------
    # Public API — download_multi
    # ------------------------------------------------------------------

    def download_multi(self, jobs: list[MultiSymbolJobConfig]) -> list[JobOutcome]:
        """Distribui ``jobs`` entre workers do pool e retorna outcomes em ordem.

        Args:
            jobs: Lista de :class:`MultiSymbolJobConfig` a executar em paralelo.

        Returns:
            Lista de :class:`JobOutcome` na MESMA ordem de ``jobs``.

        Raises:
            RuntimeError: Master não startado.
        """
        if self._pool is None or self._broker is None:
            raise RuntimeError(
                "MultiSymbolMaster.download_multi called before start(). "
                "Use as context manager or call start() explicitly."
            )

        specs = [
            JobSpec(
                job_index=i,
                symbol=j.symbol,
                exchange=j.exchange,
                start_iso=j.start.isoformat(),
                end_iso=j.end.isoformat(),
                chunk_timeout_seconds=j.chunk_timeout_seconds,
                max_retry_attempts=j.max_retry_attempts,
                resolve_contract=j.resolve_contract,
            )
            for i, j in enumerate(jobs)
        ]

        return self._pool.submit_jobs(specs)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def broker_stats(self) -> dict[str, int]:
        """Snapshot dos contadores do broker (mutations applied/rejected/errored)."""
        if self._broker is None:
            return {"mutations_applied": 0, "mutations_rejected": 0, "mutations_errored": 0}
        return self._broker.stats


__all__ = [
    "JobOutcome",
    "MultiSymbolJobConfig",
    "MultiSymbolMaster",
]
