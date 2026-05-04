"""Broker thread no master (Story 4.1 AC1 + AC3).

data_downloader.orchestrator.broker.catalog_broker
Owner: Aria (architectural design — ADR-015) | Impl: Dex.
Refs:

- ``docs/adr/ADR-015-multiprocess-catalog.md`` §"Master (Catalog Owner Thread)"
- ``docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md`` D1 + D2

:class:`CatalogBroker` roda como **thread no master process** (não subprocess).
Mantém a única conexão R/W SQLite (via ``Catalog`` existente — Story 1.5),
drena ``mutation_queue`` em loop contínuo, aplica cada mutação em transação
curta, e envia ACK via response_queues mapeadas por ``worker_id``.

Lifecycle:

1. ``CatalogBroker(catalog, mutation_queue)`` — cria instância (não inicia).
2. ``register_worker(worker_id, response_queue)`` — registra response queue
   antes do worker começar a enviar requests.
3. ``broker.start()`` — inicia thread daemon (drena queue).
4. ``broker.stop(timeout=5.0)`` — sinaliza graceful shutdown (drena pendentes
   + thread.join).

Invariantes (Aria):

- INV-6 preservada: 1 catálogo único, 1 conexão R/W SQLite.
- AC3: serializa todas as escritas SQLite — zero ``SQLITE_BUSY``.
- AC4: cada request recebe ACK (committed | rejected | error).
- Threading: broker drena queue serialmente; ``Catalog.register_partition``
  já é thread-safe via ``_transaction()`` BEGIN IMMEDIATE.

Não viola lei do Nelo (Q06-V): broker NÃO está em contexto de callback DLL.
DLL vive nos worker processes; broker no master só vê Queue messages.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from queue import Empty
from typing import TYPE_CHECKING, Any

from data_downloader.orchestrator.broker.protocol import (
    BrokerProtocol,
    BrokerRequest,
    BrokerResponse,
)
from data_downloader.public_api.exceptions import IntegrityError

if TYPE_CHECKING:
    from multiprocessing import Queue

    from data_downloader.storage.catalog import Catalog
    from data_downloader.storage.parquet_writer import WriteResult

_LOG = logging.getLogger(__name__)

# Timeout default (s) do drain loop — controla responsividade do shutdown.
_DRAIN_POLL_TIMEOUT_S: float = 0.25

# Timeout default (s) do graceful stop — broker.stop() aguarda thread.join.
_DEFAULT_STOP_TIMEOUT_S: float = 5.0


class CatalogBrokerError(Exception):
    """Erro estrutural do broker (ex.: catalog conn fechada antes do shutdown).

    NÃO usado para erros de mutação individual — esses viram
    :class:`BrokerResponse` com ``success=False`` (worker decide).
    """


class CatalogBroker:
    """Thread no master que serializa todas as escritas SQLite (Story 4.1 AC1).

    Args:
        catalog: Instância já inicializada de :class:`Catalog` (Story 1.5).
            **Importante:** broker NÃO usa esta conexão diretamente (SQLite
            connections são thread-bound; broker thread cria sua própria).
            Catalog passado serve apenas como referência para ``db_path``
            e ``data_dir`` — broker abre uma segunda conexão R/W na sua
            própria thread.

            Por que não compartilhar a mesma conexão? SQLite (em modo
            ``check_same_thread=True`` default) bloqueia uso cross-thread.
            Em modo WAL, múltiplas conexões R/W na mesma thread sequencial
            funcionam OK; broker abre a sua e usa serialmente.
        mutation_queue: ``multiprocessing.Queue`` para receber
            :class:`BrokerRequest` dos workers. Workers compartilham UMA
            única queue (broker é single-consumer).
        name: Nome opcional da thread (debug — default ``"CatalogBroker"``).

    Notes:
        ACK queues são registradas via :meth:`register_worker` antes de
        ``start()``. Default = dict vazio (broker rejeita requests cujo
        worker_id não foi registrado, com ``error="unknown_worker_id"``).

        ``register_worker`` pode ser chamado APÓS ``start()`` desde que o
        worker_id seja registrado antes do worker começar a enviar
        requests. Race window é mínima na prática (workers só conectam
        após ``WorkerPool.start_pool`` confirmar broker pronto).
    """

    def __init__(
        self,
        catalog: Catalog,
        mutation_queue: Queue[Any],
        *,
        name: str = "CatalogBroker",
    ) -> None:
        self._reference_catalog = catalog  # source of db_path/data_dir
        self._broker_catalog: Catalog | None = None  # criado na thread (lazy)
        self._mutation_queue = mutation_queue
        self._name = name
        self._response_queues: dict[str, Queue[Any]] = {}
        self._response_queues_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stats_lock = threading.Lock()
        self._mutations_applied = 0
        self._mutations_rejected = 0
        self._mutations_errored = 0

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def register_worker(self, worker_id: str, response_queue: Queue[Any]) -> None:
        """Registra response_queue para um worker_id (AC2).

        Deve ser chamado ANTES do worker começar a enviar requests (idealmente
        antes de ``start()``). Se broker já está rodando e worker envia request
        com ``worker_id`` desconhecido, broker responde
        ``error="unknown_worker_id"`` no log e descarta (sem ACK — worker
        bloqueia até timeout).

        Args:
            worker_id: Identificador estável do worker (ex.: ``"worker-0"``).
            response_queue: ``multiprocessing.Queue`` exclusiva deste worker.
        """
        with self._response_queues_lock:
            self._response_queues[worker_id] = response_queue

    def start(self) -> None:
        """Inicia thread daemon do broker.

        Idempotente — chamadas adicionais após start são no-op.

        Raises:
            CatalogBrokerError: Reference catalog connection já fechada.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        # Sanity check — reference catalog (master) ainda viva.
        try:
            self._reference_catalog._conn_or_raise()
        except RuntimeError as exc:
            raise CatalogBrokerError(f"Catalog connection closed: {exc}") from exc

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()
        _LOG.info("catalog_broker.started", extra={"name": self._name})

    def stop(self, *, timeout: float = _DEFAULT_STOP_TIMEOUT_S) -> None:
        """Sinaliza graceful shutdown e aguarda thread terminar (AC1).

        Drena queue completamente antes de sair (workers que enviaram
        request justo antes do stop ainda recebem ACK).

        Args:
            timeout: Tempo máximo (s) a aguardar thread.join. Default 5.0s.

        Notes:
            Se thread não terminar no timeout, broker é abandonado (daemon
            thread morre com processo). Log warning é emitido.
        """
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            _LOG.warning(
                "catalog_broker.stop_timeout",
                extra={"name": self._name, "timeout": timeout},
            )
        else:
            _LOG.info(
                "catalog_broker.stopped",
                extra={
                    "name": self._name,
                    "applied": self._mutations_applied,
                    "rejected": self._mutations_rejected,
                    "errored": self._mutations_errored,
                },
            )
        self._thread = None

    @property
    def stats(self) -> dict[str, int]:
        """Snapshot imutável de contadores (mutations_applied / rejected / errored)."""
        with self._stats_lock:
            return {
                "mutations_applied": self._mutations_applied,
                "mutations_rejected": self._mutations_rejected,
                "mutations_errored": self._mutations_errored,
            }

    # ------------------------------------------------------------------
    # Internal — drain loop + dispatch
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Loop principal — drena ``mutation_queue`` até ``stop_event`` setado.

        Cria a conexão broker SQLite **na própria thread** (SQLite é
        thread-bound). Continua drenando após stop_event setado se queue
        tem itens pendentes (graceful drain). Sai quando ambos: stop_event
        setado E queue vazia (após poll com timeout curto).
        """
        # Thread-local catalog (SQLite connection criada nesta thread).
        from data_downloader.storage.catalog import Catalog as _Catalog

        ref = self._reference_catalog
        try:
            self._broker_catalog = _Catalog(
                db_path=ref.db_path,
                data_dir=ref.data_dir,
                auto_reconcile=False,
                auto_cleanup_orphans=False,
                sqlite_profile=ref.sqlite_profile,
            )
        except Exception as exc:
            _LOG.error(
                "catalog_broker.thread_catalog_init_failed",
                extra={"error": str(exc)},
            )
            return

        try:
            while True:
                try:
                    request = self._mutation_queue.get(timeout=_DRAIN_POLL_TIMEOUT_S)
                except Empty:
                    if self._stop_event.is_set():
                        return
                    continue

                if request is None or (
                    isinstance(request, BrokerRequest) and request.op == BrokerProtocol.SHUTDOWN
                ):
                    # Sentinel — sai imediatamente sem drenar resto (caller
                    # usou ``stop()`` que set stop_event antes).
                    return

                if not isinstance(request, BrokerRequest):
                    _LOG.warning(
                        "catalog_broker.invalid_request_type",
                        extra={"type": type(request).__name__},
                    )
                    continue

                self._handle_request(request)
        finally:
            # Fecha catalog thread-local antes de sair.
            if self._broker_catalog is not None:
                try:
                    self._broker_catalog.close()
                except Exception as exc:
                    _LOG.warning(
                        "catalog_broker.close_failed",
                        extra={"error": str(exc)},
                    )
                self._broker_catalog = None

    def _handle_request(self, request: BrokerRequest) -> None:
        """Processa 1 request: dispatch + ACK.

        Captura exceptions e converte em ``BrokerResponse(success=False)``.
        NUNCA propaga exception — se response_queue do worker estiver
        cheia/quebrada, log warning e segue.
        """
        try:
            data = self._dispatch(request)
            response = BrokerResponse(
                request_id=request.request_id,
                success=True,
                data=data,
            )
            with self._stats_lock:
                self._mutations_applied += 1
        except IntegrityError as exc:
            # Regra de negócio violada — caller pode tratar.
            response = BrokerResponse(
                request_id=request.request_id,
                success=False,
                error=str(exc),
                error_type="IntegrityError",
            )
            with self._stats_lock:
                self._mutations_rejected += 1
        except Exception as exc:
            # Erro inesperado (ex.: SQLite corrompido, connection morreu).
            # Worker recebe ACK error e decide.
            response = BrokerResponse(
                request_id=request.request_id,
                success=False,
                error=str(exc)[:500],  # cap para não estourar pickle.
                error_type=type(exc).__name__,
            )
            with self._stats_lock:
                self._mutations_errored += 1
            _LOG.warning(
                "catalog_broker.dispatch_error",
                extra={
                    "request_id": request.request_id,
                    "op": request.op.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                },
            )

        self._send_ack(request.worker_id, response)

    def _catalog_or_raise(self) -> Catalog:
        """Retorna catalog thread-local; raise se broker não está rodando."""
        if self._broker_catalog is None:
            raise CatalogBrokerError(
                "broker thread-local catalog not initialized — broker not running"
            )
        return self._broker_catalog

    def _send_ack(self, worker_id: str, response: BrokerResponse) -> None:
        """Envia ACK na response_queue do worker. Best-effort."""
        with self._response_queues_lock:
            response_queue = self._response_queues.get(worker_id)
        if response_queue is None:
            _LOG.warning(
                "catalog_broker.unknown_worker",
                extra={"worker_id": worker_id, "request_id": response.request_id},
            )
            return
        try:
            response_queue.put(response, timeout=1.0)
        except Exception as exc:
            _LOG.warning(
                "catalog_broker.ack_send_failed",
                extra={
                    "worker_id": worker_id,
                    "request_id": response.request_id,
                    "error": str(exc),
                },
            )

    def _dispatch(self, request: BrokerRequest) -> Any:
        """Mapeia op → método do Catalog. Retorna data (None ou serializável).

        Schema do payload por op:

        - REGISTER_PARTITION: ``{write_result: dict, partition: dict, job_id: str | None}``
        - REGISTER_GAP: ``{symbol, exchange, gap_start_iso, gap_end_iso, reason}``
        - UPDATE_JOB_PROGRESS: ``{job_id, **kwargs}``  (kwargs com ts ISO)
        - REGISTER_JOB: ``{symbol, exchange, requested_start_iso, requested_end_iso}``
        - QUERY_COMPLETED_PARTITIONS: ``{symbol, exchange}`` → list[dict]
        """
        op = request.op
        payload = request.payload

        if op == BrokerProtocol.REGISTER_PARTITION:
            from data_downloader.storage.parquet_writer import WriteResult
            from data_downloader.storage.partition import PartitionKey

            wr_data = payload["write_result"]
            pk_data = payload["partition"]
            from pathlib import Path as _Path

            write_result = WriteResult(
                path=_Path(wr_data["path"]),
                row_count=int(wr_data["row_count"]),
                first_ts_ns=int(wr_data["first_ts_ns"]),
                last_ts_ns=int(wr_data["last_ts_ns"]),
                checksum_sha256=wr_data["checksum_sha256"],
                file_size_bytes=int(wr_data["file_size_bytes"]),
            )
            partition = PartitionKey(
                exchange=pk_data["exchange"],
                symbol=pk_data["symbol"],
                year=int(pk_data["year"]),
                month=int(pk_data["month"]),
            )
            self._catalog_or_raise().register_partition(
                write_result, partition, job_id=payload.get("job_id")
            )
            return None

        if op == BrokerProtocol.REGISTER_GAP:
            self._catalog_or_raise().register_gap(
                symbol=payload["symbol"],
                exchange=payload["exchange"],
                gap_start=datetime.fromisoformat(payload["gap_start_iso"]),
                gap_end=datetime.fromisoformat(payload["gap_end_iso"]),
                reason=payload["reason"],
            )
            return None

        if op == BrokerProtocol.UPDATE_JOB_PROGRESS:
            kwargs: dict[str, Any] = {}
            for key in (
                "status",
                "trades_count",
                "error",
                "dll_version",
            ):
                if key in payload:
                    kwargs[key] = payload[key]
            for ts_key in ("actual_start", "actual_end", "started_at", "completed_at"):
                ts_iso_key = f"{ts_key}_iso"
                if ts_iso_key in payload and payload[ts_iso_key] is not None:
                    kwargs[ts_key] = datetime.fromisoformat(payload[ts_iso_key])
            self._catalog_or_raise().update_job_progress(payload["job_id"], **kwargs)
            return None

        if op == BrokerProtocol.REGISTER_JOB:
            job_id = self._catalog_or_raise().register_job(
                symbol=payload["symbol"],
                exchange=payload["exchange"],
                requested_start=datetime.fromisoformat(payload["requested_start_iso"]),
                requested_end=datetime.fromisoformat(payload["requested_end_iso"]),
            )
            return {"job_id": job_id}

        if op == BrokerProtocol.QUERY_COMPLETED_PARTITIONS:
            partitions = self._catalog_or_raise().get_completed_partitions(
                symbol=payload["symbol"],
                exchange=payload["exchange"],
            )
            # Serializa Partition → dict para pickle (datetime → ISO).
            return [
                {
                    "partition_path": p.partition_path,
                    "symbol": p.symbol,
                    "exchange": p.exchange,
                    "year": p.year,
                    "month": p.month,
                    "row_count": p.row_count,
                    "first_ts_ns": p.first_ts_ns,
                    "last_ts_ns": p.last_ts_ns,
                    "schema_version": p.schema_version,
                    "checksum_sha256": p.checksum_sha256,
                    "file_size_bytes": p.file_size_bytes,
                    "written_at_iso": p.written_at.isoformat(),
                    "job_id": p.job_id,
                }
                for p in partitions
            ]

        if op == BrokerProtocol.SHUTDOWN:
            # Tratado em _run; aqui apenas no-op para completude.
            return None

        raise CatalogBrokerError(f"Unknown protocol op: {op!r}")


# Helper para serialização WriteResult → dict (usado pelo cliente; exposto aqui
# para evitar dependência circular).
def serialize_write_result(write_result: WriteResult) -> dict[str, Any]:
    """Converte :class:`WriteResult` em dict pickle-safe (Path → str)."""
    return {
        "path": str(write_result.path),
        "row_count": write_result.row_count,
        "first_ts_ns": write_result.first_ts_ns,
        "last_ts_ns": write_result.last_ts_ns,
        "checksum_sha256": write_result.checksum_sha256,
        "file_size_bytes": write_result.file_size_bytes,
    }


def deserialize_partition_dict(data: dict[str, Any]) -> Any:
    """Reconstrói :class:`Partition` a partir de dict (worker side)."""
    from data_downloader.storage.catalog_models import Partition

    return Partition(
        partition_path=data["partition_path"],
        symbol=data["symbol"],
        exchange=data["exchange"],
        year=int(data["year"]),
        month=int(data["month"]),
        row_count=int(data["row_count"]),
        first_ts_ns=int(data["first_ts_ns"]),
        last_ts_ns=int(data["last_ts_ns"]),
        schema_version=data["schema_version"],
        checksum_sha256=data["checksum_sha256"],
        file_size_bytes=int(data["file_size_bytes"]),
        written_at=datetime.fromisoformat(data["written_at_iso"]),
        job_id=data.get("job_id"),
    )


__all__ = [
    "CatalogBroker",
    "CatalogBrokerError",
    "deserialize_partition_dict",
    "serialize_write_result",
]
