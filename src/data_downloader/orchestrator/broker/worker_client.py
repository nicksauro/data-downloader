"""Cliente Catalog no worker (Story 4.1 AC2 + AC4).

data_downloader.orchestrator.broker.worker_client
Owner: Aria (protocol design — ADR-015) | Impl: Dex.
Refs:

- ``docs/adr/ADR-015-multiprocess-catalog.md`` §"Worker (subprocess)"
- ``docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md`` D1

:class:`BrokerCatalogClient` implementa o **mesmo contrato externo** de
:class:`Catalog` (subset usado pelo Orchestrator — Story 1.7a) mas em vez
de escrever SQLite local, envia mutações via ``multiprocessing.Queue`` ao
broker no master process e bloqueia em ACK.

Métodos cobertos (subset Catalog usado pelo Orchestrator):

- ``register_job(symbol, exchange, requested_start, requested_end)`` → job_id
- ``register_partition(write_result, partition, *, job_id=None)`` → None
- ``register_gap(symbol, exchange, gap_start, gap_end, reason)`` → None
- ``update_job_progress(job_id, status=None, **kwargs)`` → None
- ``get_completed_partitions(symbol, exchange)`` → list[Partition]

Métodos NÃO cobertos (worker não precisa — broker exclusivo):

- ``cleanup_orphans``, ``reconcile``, ``close``, ``__post_init__``,
  ``resume_job``, ``get_pending_chunks`` (lógica de orchestrator).

Idempotência preservada (R5): ``register_partition`` é UPSERT no broker;
re-enviar mesma payload = no-op idempotente.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from queue import Empty
from typing import TYPE_CHECKING, Any

from data_downloader.orchestrator.broker.catalog_broker import (
    deserialize_partition_dict,
    serialize_write_result,
)
from data_downloader.orchestrator.broker.protocol import (
    BrokerProtocol,
    BrokerRequest,
    BrokerResponse,
    BrokerTimeoutError,
)
from data_downloader.public_api.exceptions import IntegrityError

if TYPE_CHECKING:
    from multiprocessing import Queue

    from data_downloader.storage.catalog_models import Partition
    from data_downloader.storage.parquet_writer import WriteResult
    from data_downloader.storage.partition import PartitionKey

_LOG = logging.getLogger(__name__)

# Default timeout (s) por mutação. AC4 exige timeout configurável; default
# generoso (30s) para tolerar SQLite WAL checkpoint pesado.
DEFAULT_BROKER_TIMEOUT_S: float = 30.0


class BrokerCatalogClient:
    """Cliente Catalog no worker — envia mutações via Queue + bloqueia em ACK (AC2 + AC4).

    Args:
        mutation_queue: Queue para enviar requests ao broker.
        response_queue: Queue exclusiva deste worker para receber ACKs.
        worker_id: Identificador estável (deve estar registrado no broker
            via :meth:`CatalogBroker.register_worker`).
        timeout: Timeout (s) por mutação. Default 30s.

    Notes:
        Threading: cada worker usa instância dedicada (1 worker = 1 cliente).
        Não thread-safe entre threads do MESMO worker — workers são
        single-threaded por design (Q06-V + ADR-005).

        ACK out-of-order: se chegar ACK de outro request_id (improvável em
        worker single-threaded, mas defensive), :meth:`_wait_for_ack`
        re-enfileira na response_queue para próximo waiter.
    """

    def __init__(
        self,
        mutation_queue: Queue[Any],
        response_queue: Queue[Any],
        worker_id: str,
        *,
        timeout: float = DEFAULT_BROKER_TIMEOUT_S,
    ) -> None:
        self._mutation_queue = mutation_queue
        self._response_queue = response_queue
        self._worker_id = worker_id
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API — espelha Catalog (subset usado por Orchestrator)
    # ------------------------------------------------------------------

    def register_job(
        self,
        symbol: str,
        exchange: str,
        requested_start: datetime,
        requested_end: datetime,
    ) -> str:
        """Envia REGISTER_JOB ao broker. Retorna job_id (UUID hex)."""
        response = self._send(
            op=BrokerProtocol.REGISTER_JOB,
            payload={
                "symbol": symbol,
                "exchange": exchange,
                "requested_start_iso": requested_start.isoformat(),
                "requested_end_iso": requested_end.isoformat(),
            },
        )
        if not response.success:
            self._raise_from_response(response)
        if not isinstance(response.data, dict) or "job_id" not in response.data:
            raise IntegrityError(f"Broker REGISTER_JOB returned malformed data: {response.data!r}")
        return str(response.data["job_id"])

    def register_partition(
        self,
        write_result: WriteResult,
        partition: PartitionKey,
        *,
        job_id: str | None = None,
    ) -> None:
        """Envia REGISTER_PARTITION ao broker. Bloqueia em ACK (AC4)."""
        response = self._send(
            op=BrokerProtocol.REGISTER_PARTITION,
            payload={
                "write_result": serialize_write_result(write_result),
                "partition": {
                    "exchange": partition.exchange,
                    "symbol": partition.symbol,
                    "year": partition.year,
                    "month": partition.month,
                },
                "job_id": job_id,
            },
        )
        if not response.success:
            self._raise_from_response(response)

    def register_gap(
        self,
        symbol: str,
        exchange: str,
        gap_start: datetime,
        gap_end: datetime,
        reason: str,
    ) -> None:
        """Envia REGISTER_GAP ao broker."""
        response = self._send(
            op=BrokerProtocol.REGISTER_GAP,
            payload={
                "symbol": symbol,
                "exchange": exchange,
                "gap_start_iso": gap_start.isoformat(),
                "gap_end_iso": gap_end.isoformat(),
                "reason": reason,
            },
        )
        if not response.success:
            self._raise_from_response(response)

    def update_job_progress(
        self,
        job_id: str,
        status: str | None = None,
        *,
        actual_start: datetime | None = None,
        actual_end: datetime | None = None,
        trades_count: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
        dll_version: str | None = None,
    ) -> None:
        """Envia UPDATE_JOB_PROGRESS ao broker."""
        payload: dict[str, Any] = {"job_id": job_id}
        if status is not None:
            payload["status"] = status
        if trades_count is not None:
            payload["trades_count"] = trades_count
        if error is not None:
            payload["error"] = error
        if dll_version is not None:
            payload["dll_version"] = dll_version
        if actual_start is not None:
            payload["actual_start_iso"] = actual_start.isoformat()
        if actual_end is not None:
            payload["actual_end_iso"] = actual_end.isoformat()
        if started_at is not None:
            payload["started_at_iso"] = started_at.isoformat()
        if completed_at is not None:
            payload["completed_at_iso"] = completed_at.isoformat()

        response = self._send(
            op=BrokerProtocol.UPDATE_JOB_PROGRESS,
            payload=payload,
        )
        if not response.success:
            self._raise_from_response(response)

    def get_completed_partitions(self, symbol: str, exchange: str) -> list[Partition]:
        """Envia QUERY_COMPLETED_PARTITIONS ao broker. Retorna list[Partition]."""
        response = self._send(
            op=BrokerProtocol.QUERY_COMPLETED_PARTITIONS,
            payload={"symbol": symbol, "exchange": exchange},
        )
        if not response.success:
            self._raise_from_response(response)
        if not isinstance(response.data, list):
            raise IntegrityError(f"Broker QUERY returned non-list: {type(response.data).__name__}")
        return [deserialize_partition_dict(d) for d in response.data]

    # ------------------------------------------------------------------
    # Compat shims — métodos que Orchestrator chama mas que NÃO precisam
    # broker (eles são puramente locais ou são lidos via partições).
    # ------------------------------------------------------------------

    def get_pending_chunks(self, job_id: str) -> list[Any]:
        """Stub — Orchestrator multi-symbol NÃO usa resume; raise para evidência."""
        raise NotImplementedError(
            "BrokerCatalogClient.get_pending_chunks: resume não suportado em "
            "multi-symbol V1. Use Orchestrator single-process para resume."
        )

    def resume_job(self, job_id: str) -> Any:
        """Stub — multi-symbol não suporta resume V1 (mesma justificativa)."""
        raise NotImplementedError(
            "BrokerCatalogClient.resume_job: resume não suportado em " "multi-symbol V1."
        )

    # ------------------------------------------------------------------
    # Internal — IPC
    # ------------------------------------------------------------------

    def _send(self, op: BrokerProtocol, payload: dict[str, Any]) -> BrokerResponse:
        """Envia request + bloqueia em ACK até timeout."""
        request_id = uuid.uuid4().hex
        request = BrokerRequest(
            request_id=request_id,
            op=op,
            payload=payload,
            worker_id=self._worker_id,
        )
        self._mutation_queue.put(request)
        return self._wait_for_ack(request_id, op)

    def _wait_for_ack(self, request_id: str, op: BrokerProtocol) -> BrokerResponse:
        """Aguarda ACK correto, re-enfileira ACKs out-of-order, raise em timeout."""
        deadline = time.monotonic() + self._timeout
        # Buffer para ACKs out-of-order (defensive — improvável mas barato).
        buffered: list[BrokerResponse] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BrokerTimeoutError(
                        request_id=request_id, op=op.value, timeout=self._timeout
                    )
                try:
                    ack = self._response_queue.get(timeout=min(remaining, 1.0))
                except Empty:
                    continue

                if not isinstance(ack, BrokerResponse):
                    _LOG.warning(
                        "broker_client.invalid_ack_type",
                        extra={
                            "worker_id": self._worker_id,
                            "type": type(ack).__name__,
                        },
                    )
                    continue

                if ack.request_id == request_id:
                    return ack

                # ACK de outro request — buffer e continua aguardando.
                buffered.append(ack)
        finally:
            # Re-enfileira ACKs buffered para que próximos waiters os
            # encontrem (preserva semântica FIFO entre requests).
            for ack in buffered:
                try:
                    self._response_queue.put(ack, timeout=1.0)
                except Exception as exc:
                    _LOG.warning(
                        "broker_client.requeue_failed",
                        extra={
                            "worker_id": self._worker_id,
                            "error": str(exc),
                        },
                    )

    def _raise_from_response(self, response: BrokerResponse) -> None:
        """Mapeia BrokerResponse de erro → exception local."""
        msg = response.error or "unknown error"
        if response.error_type == "IntegrityError":
            raise IntegrityError(msg)
        # Outros tipos (ValueError, sqlite3.IntegrityError, RuntimeError, ...)
        # — propagar como IntegrityError para que callers tratem
        # uniformemente. Detalhe original fica no message.
        raise IntegrityError(f"{response.error_type or 'BrokerError'}: {msg}")


__all__ = [
    "DEFAULT_BROKER_TIMEOUT_S",
    "BrokerCatalogClient",
]
