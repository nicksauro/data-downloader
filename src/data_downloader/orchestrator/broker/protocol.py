"""data_downloader.orchestrator.broker.protocol — IPC protocol (Story 4.1 AC2 + AC4).

Owner: Aria (protocol design — ADR-015 §"Mutation protocol") | Impl: Dex.
Refs:

- ``docs/adr/ADR-015-multiprocess-catalog.md`` §"Mutation protocol"
- ``docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md`` D1

Protocolo de IPC entre master (broker) e workers via
``multiprocessing.Queue``. Cada mutação carrega ``request_id`` UUID para
correlacionar com ACK assíncrono. Mensagens são dataclasses ``frozen=True``
para compatibilidade com pickle (Windows spawn) e imutabilidade.

**Lei do protocolo (AC4):** Worker bloqueia em ACK até broker responder.
ACK ``committed`` = sucesso; ``rejected`` = regra de negócio violada
(AmbiguousContract etc); ``error`` = exception técnica; timeout sem ACK
levanta :class:`BrokerTimeoutError`.

Threading: dataclasses são read-only após criação. Não há race condition
em pickle/unpickle entre processos. ``multiprocessing.Queue`` faz a
serialização transparente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BrokerProtocol(StrEnum):
    """Tipos de mensagem do protocolo broker (AC2).

    Cada valor mapeia para uma operação do contrato Catalog (Story 1.5):

    - ``REGISTER_PARTITION`` → :meth:`Catalog.register_partition`
    - ``REGISTER_GAP`` → :meth:`Catalog.register_gap`
    - ``UPDATE_JOB_PROGRESS`` → :meth:`Catalog.update_job_progress`
    - ``REGISTER_JOB`` → :meth:`Catalog.register_job`
    - ``QUERY_COMPLETED_PARTITIONS`` → :meth:`Catalog.get_completed_partitions`
      (retorna lista serializada de Partition)
    - ``SHUTDOWN`` → sentinel para encerrar broker thread (graceful drain)

    Valores são strings (Enum subclass) para serializar transparente em
    pickle e debuggar fácil em logs.
    """

    REGISTER_PARTITION = "register_partition"
    REGISTER_GAP = "register_gap"
    UPDATE_JOB_PROGRESS = "update_job_progress"
    REGISTER_JOB = "register_job"
    QUERY_COMPLETED_PARTITIONS = "query_completed_partitions"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class BrokerRequest:
    """Request enviado pelo worker ao broker via mutation_queue.

    Atributos:
        request_id: UUID hex (32 chars) para correlacionar com ACK.
            Gerado pelo worker via :func:`uuid.uuid4().hex`.
        op: Tipo da operação (:class:`BrokerProtocol`).
        payload: Dict de argumentos serializáveis (pickle-safe). Cada op
            tem schema implícito documentado em
            :class:`CatalogBroker._dispatch`.
        worker_id: Identificador opcional do worker (debug + ACK routing).
            Usado pelo broker para retornar ACK na response_queue correta.

    Notes:
        ``payload`` deve conter APENAS tipos pickle-safe: str, int, float,
        bool, datetime, dict, list, tuple, dataclasses simples. NÃO passar
        Path (str), Connection (não serializável) ou referências a objetos
        do master.
    """

    request_id: str
    op: BrokerProtocol
    payload: dict[str, Any] = field(default_factory=dict)
    worker_id: str = ""


@dataclass(frozen=True)
class BrokerResponse:
    """Response do broker ao worker via response_queue.

    Atributos:
        request_id: Mesmo UUID do :class:`BrokerRequest` correspondente.
        success: ``True`` se mutação foi aplicada com sucesso.
        data: Payload de retorno (apenas para queries — ex.:
            ``QUERY_COMPLETED_PARTITIONS`` retorna list[dict]). ``None`` para
            mutações sem retorno.
        error: Mensagem de erro humana (apenas se ``success=False``).
        error_type: Nome da exception class (ex.: ``"IntegrityError"``).

    Notes:
        ``data`` para QUERY_COMPLETED_PARTITIONS é serializado como
        list[dict] (Partition.__dict__) — worker reconstrói Partition no
        client side. Path → str para compatibilidade com pickle.
    """

    request_id: str
    success: bool
    data: Any | None = None
    error: str | None = None
    error_type: str | None = None


class BrokerTimeoutError(TimeoutError):
    """Worker aguardou ACK além do timeout configurado (AC4).

    Default timeout no :class:`BrokerCatalogClient` = 30s (configurável).
    Causas comuns:

    - Broker travado (deadlock, exception não capturada no _apply).
    - Master process matou broker thread sem aviso.
    - Queue saturada (backpressure inverso — broker mais lento que workers).

    Recovery: caller (Orchestrator) propaga o erro; pool monitor pode
    decidir reiniciar broker ou marcar job como failed.
    """

    def __init__(self, request_id: str, op: str, timeout: float) -> None:
        self.request_id = request_id
        self.op = op
        self.timeout = timeout
        super().__init__(f"Broker did not ACK request {request_id} (op={op}) within {timeout}s")
