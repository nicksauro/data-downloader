"""data_downloader.orchestrator.orchestrator — Multi-chunk download loop (Story 1.7a).

Owner: Dex (impl) | Audit: Aria (state machine + integração — ADR-005 amendment),
Sol (storage handoff), Nelo (DLL handoff via download_chunk).
COUNCIL-05.

Coração do MVP. Compõe três camadas em um loop multi-chunk:

1. **DLL** (Story 1.3) — :func:`download_chunk` baixa 1 sub-intervalo.
2. **Writer** (Story 1.4) — :class:`ParquetWriter` escreve o Parquet.
3. **Catalog** (Story 1.5) — :class:`Catalog` faz two-phase commit + resume.

Pipeline canônico de :meth:`Orchestrator.run`:

    1. State: IDLE → RUNNING.
    2. Catalog.register_job(symbol, exchange, [start, end]) → job_id
       (ou retoma job_id se ``resume_job_id`` passado).
    3. Resolve contrato vigente via Story 1.6.
    4. Cache hit check (range coverage REAL — finding H8): se range
       solicitado já está coberto pelas partições registradas, retorna
       sem chamar DLL.
    5. Calcula chunks via :func:`chunk_date_range` (Story 1.7a chunker).
    6. Para cada chunk:
       a. download_chunk(...) com retry (3 tentativas — COUNCIL-05 §D5).
       b. Se status == "completed": writer.write(...) → catalog.register_partition(...).
       c. Se status fail definitivo: catalog.register_gap(reason="failed_chunk")
          e segue próximo chunk (não aborta job).
    7. State: RUNNING → DRAINING_DLL → DRAINING_WRITE → COMMITTED → IDLE.
    8. catalog.update_job_progress(status="completed"|"partial"|"failed").

Retorna :class:`JobResult` com métricas + paths das partições escritas.

LEIS RESPEITADAS:
- INV-1 / R3: orchestrator NUNCA está em contexto de callback DLL — chama
  ``GetHistoryTrades`` em OrchestratorThread (esta thread); callbacks vivem
  em ConnectorThread/IngestorThread separadas (download_chunk gerencia).
- INV-11: orchestrator é thread distinta de Ingestor/Connector (download_chunk
  cria threads próprias internamente).
- INV-12: declara "fim de chunk" só após writer.write retornar OK E
  catalog.register_partition fazer commit com WAL checkpoint (Story 1.5 AC12).
- R5 (idempotência): re-rodar com mesmo (symbol, range) = cache hit ou
  re-escrita idempotente (writer faz dedup; catalog faz UPSERT).
- R21: logger 1 evento por chunk (cool path) — nunca per-trade.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal

import structlog

from data_downloader.contracts.observability import MetricsEmitter, NullMetricsEmitter
from data_downloader.observability.logging_config import (
    bind_context,
    clear_context,
    unbind_context,
)
from data_downloader.orchestrator.chunk_strategy import get_chunk_days
from data_downloader.orchestrator.chunker import ChunkRange, chunk_date_range
from data_downloader.orchestrator.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
)
from data_downloader.orchestrator.contracts import vigent_contract
from data_downloader.orchestrator.download_primitive import (
    DEFAULT_TIMEOUT_SECONDS,
    ChunkResult,
    download_chunk,
)
from data_downloader.orchestrator.retry import (
    DEFAULT_BASE_DELAY,
    DEFAULT_FACTOR,
    DEFAULT_JITTER,
    DEFAULT_MAX_ATTEMPTS,
    RetryError,
    with_retry,
)
from data_downloader.orchestrator.retry_policy import RetryPolicy, default_retry_policy
from data_downloader.orchestrator.state_machine import JobState, JobStateMachine
from data_downloader.storage.catalog_models import Partition
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord as SchemaTradeRecord

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.orchestrator.download_primitive import (
        TradeRecord as PrimitiveTradeRecord,
    )
    from data_downloader.storage.catalog import Catalog
    from data_downloader.storage.parquet_writer import ParquetWriter, WriteResult

__all__ = [
    "ChunkCompletedEvent",
    "ChunkListener",
    "JobConfig",
    "JobResult",
    "Orchestrator",
    "OrchestratorMetrics",
]


log: structlog.stdlib.BoundLogger = structlog.get_logger(
    "data_downloader.orchestrator.orchestrator"
)


JobStatus = Literal["completed", "partial", "failed", "cache_hit"]
"""Status final de um job (refletido em ``downloads.status`` no catalog)."""


_DEFAULT_RETRYABLE_DOWNLOAD_ERRORS: Final[tuple[type[BaseException], ...]] = (
    OSError,
    TimeoutError,
)


# =====================================================================
# Dataclasses (entrada / saída / métricas)
# =====================================================================


@dataclass(frozen=True)
class JobConfig:
    """Configuração imutável de um job de download.

    Atributos:
        symbol: Contrato vigente OU raiz (e.g. ``"WDOJ26"`` ou ``"WDO"``).
            Se for raiz, orchestrator resolve via :func:`vigent_contract`
            usando ``start.date()`` como ``on_date``.
        exchange: ``"F"`` (BMF) ou ``"B"`` (Bovespa).
        start: Início (datetime BRT naive) — inclusivo.
        end: Fim (datetime BRT naive) — inclusivo.
        chunk_timeout_seconds: Timeout por chunk (default 1800s — Q02-E
            quirk margin).
        chunk_days_map: Override para chunker — mapa prefixo → dias úteis/chunk.
            Default ``None`` (usa :data:`chunker.CHUNK_DAYS`).
        max_retry_attempts: Tentativas por chunk (default 3 — COUNCIL-05).
        retry_base_delay: Delay base do retry (default 1s).
        retry_factor: Fator multiplicativo (default 4 → 1s, 4s, 16s).
        retry_jitter: Jitter ±frac (default 0.2).
        resolve_contract: Se ``True`` (default), trata ``symbol`` como raiz
            e resolve via catalog. Se ``False``, usa ``symbol`` como já
            contrato vigente (skip lookup).
    """

    symbol: str
    exchange: str
    start: datetime
    end: datetime
    chunk_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    chunk_days_map: Mapping[str, int] | None = None
    max_retry_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_base_delay: float = DEFAULT_BASE_DELAY
    retry_factor: float = DEFAULT_FACTOR
    retry_jitter: float = DEFAULT_JITTER
    resolve_contract: bool = True


@dataclass
class OrchestratorMetrics:
    """Métricas mutáveis acumuladas durante um run.

    Note: mutável intencionalmente (acumulador). Snapshot imutável é
    embutido em :class:`JobResult` ao final.
    """

    callbacks_received: int = 0
    """Soma de ``len(ChunkResult.trades)`` em todos os chunks (inclui falhados)."""

    trades_persisted: int = 0
    """Soma de ``WriteResult.row_count`` (trades de fato escritos em Parquet)."""

    chunks_completed: int = 0
    """Chunks com status ``"completed"`` em ``ChunkResult`` (após retry)."""

    chunks_failed: int = 0
    """Chunks que falharam após esgotar todas as tentativas."""

    dll_drops_total: int = 0
    """Reservado V2 (drop policy). V1 = 0 (block back-pressure — ADR-005)."""

    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Duração total se ``started_at`` e ``completed_at`` setados."""
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class ChunkCompletedEvent:
    """Evento imutável emitido após cada chunk processado (Story 4.16).

    Owner: Dex (impl) | Pichau directive 2026-05-06.

    Produzido pelo orchestrator após cada chunk (independente de status —
    sucesso, no_trades ou falha definitiva) e entregue ao ``chunk_listener``
    injetado em :meth:`Orchestrator.run`. UI consome para atualizar a barra
    de progresso (chunks_completed / total_chunks * 100).

    Frozen por design (R6 — thread-safety por imutabilidade). Cool path
    cool-rate (1 evento por chunk — R21 OK).

    Attributes:
        chunk_index: Índice 0-based do chunk no plano de execução. Em jobs
            resume, conta a partir de 0 do plano de chunks faltantes.
        total_chunks: Total de chunks planejados para este run. Em jobs
            resume, reflete apenas os chunks faltantes (não inclui os
            já-completos da run anterior).
        chunk_start: Início do chunk (apenas a parte ``date`` — convenção
            stable da DownloadProgress; UI agrega range, não timestamp
            preciso).
        chunk_end: Fim do chunk (apenas a parte ``date``).
        trades_count: Trades baixados+persistidos neste chunk. ``0`` se
            o chunk não retornou trades (gap registrado) ou falhou.
        duration_seconds: Tempo total do chunk (download + write +
            register), em segundos com precisão de microssegundos.
        status: ``"success"`` (trades persistidos), ``"no_trades"`` (chunk
            válido mas vazio — gap registrado), ``"failed"`` (falha
            definitiva pós-retry; gap registrado), ``"circuit_open"``
            (rejeitado pelo breaker).

    Examples:
        Wiring orchestrator → UI Qt::

            def emit_to_ui(event: ChunkCompletedEvent) -> None:
                progress_bar.setValue(int(event.progress_pct))
                label.setText(
                    f"{event.chunk_index + 1}/{event.total_chunks} "
                    f"chunks ({event.trades_count:,} trades) — "
                    f"{event.progress_pct:.1f}%"
                )

            orchestrator.run(config, chunk_listener=emit_to_ui)
    """

    chunk_index: int
    total_chunks: int
    chunk_start: date
    chunk_end: date
    trades_count: int
    duration_seconds: float
    status: Literal["success", "no_trades", "failed", "circuit_open"] = "success"

    @property
    def progress_pct(self) -> float:
        """Percentual de progresso (0.0 .. 100.0) após este chunk.

        ``(chunk_index + 1) / total_chunks * 100`` — assume ``chunk_index``
        é 0-based. Defesa: se ``total_chunks <= 0``, retorna 0.0
        (evita ZeroDivisionError em jobs degenerados).
        """
        if self.total_chunks <= 0:
            return 0.0
        return 100.0 * (self.chunk_index + 1) / self.total_chunks


# Type alias — listener callback para chunk events.
# Usado em :meth:`Orchestrator.run` para wiring opcional com UI / events_queue.
# Definido como type-comment em runtime (não vira tipo callable) — uso só
# para documentação. Caller passa ``Callable[[ChunkCompletedEvent], None]``
# em ``chunk_listener=``.
if TYPE_CHECKING:
    ChunkListener = Callable[[ChunkCompletedEvent], None]
else:
    ChunkListener = object  # placeholder — runtime usa duck-typing


@dataclass(frozen=True)
class JobResult:
    """Resultado imutável de :meth:`Orchestrator.run`.

    Atributos:
        job_id: UUID do job (correlation_id em logs).
        status: ``"completed"`` (todos chunks OK), ``"partial"`` (alguns
            falharam), ``"failed"`` (todos falharam ou erro fatal),
            ``"cache_hit"`` (range já coberto, nada baixado).
        contract_code: Contrato vigente resolvido (e.g. ``"WDOJ26"``).
        chunks_completed: Quantos chunks foram baixados+persistidos com sucesso.
        chunks_failed: Quantos chunks falharam definitivamente.
        partitions_written: Lista de paths absolutos das partições
            escritas (vazia em ``cache_hit``).
        metrics: Snapshot final de :class:`OrchestratorMetrics`.
    """

    job_id: str
    status: JobStatus
    contract_code: str
    chunks_completed: int
    chunks_failed: int
    partitions_written: tuple[Path, ...] = field(default_factory=tuple)
    metrics: OrchestratorMetrics = field(default_factory=OrchestratorMetrics)


# =====================================================================
# Orchestrator
# =====================================================================


class Orchestrator:
    """Coordena download multi-chunk: DLL → writer → catalog em loop.

    Args:
        dll: Instância já inicializada de ``ProfitDLL`` (Story 1.2).
        catalog: :class:`Catalog` SQLite (Story 1.5).
        writer: :class:`ParquetWriter` (Story 1.4).
        cleanup_orphans_on_start: Se ``True`` (default), Catalog já
            cleanup tmp órfãos no ``__init__`` — orchestrator não
            chama explicitamente (delegado a Catalog AC7). Mantido para
            sinalização explícita no log de start.
    """

    def __init__(
        self,
        dll: ProfitDLL,
        catalog: Catalog,
        writer: ParquetWriter,
        *,
        cleanup_orphans_on_start: bool = True,
        metrics_emitter: MetricsEmitter | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._dll = dll
        self._catalog = catalog
        self._writer = writer
        self._cleanup_orphans_on_start = cleanup_orphans_on_start
        # Story 2.4 — emitter de métricas via Protocol (Aria fronteira).
        # Default = NullMetricsEmitter (zero overhead opt-in default off).
        # Hot path R21: emitter chamado APENAS per-chunk (cool path).
        self._metrics: MetricsEmitter = (
            metrics_emitter if metrics_emitter is not None else NullMetricsEmitter()
        )
        # Story 2.6 — RetryPolicy + CircuitBreaker injetados (Aria fronteira).
        # Defaults garantem que callers existentes (Story 1.7a/1.7b) NÃO
        # quebram em comportamento (apenas ganham retry inteligente +
        # breaker ativo, documentado em CHANGELOG e docs/dev/RETRY_POLICY.md).
        self._retry_policy: RetryPolicy = retry_policy or default_retry_policy()
        # Breakers indexados por (symbol, exchange) — lazy-allocated em
        # _process_chunk para suportar multi-symbol futuro (Epic 3).
        # ``circuit_breaker`` injetado é usado como template
        # (compartilha threshold/window/cooldown); cada (symbol, exchange)
        # recebe seu próprio breaker stateful.
        self._cb_template: CircuitBreaker | None = circuit_breaker
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}
        self._breakers_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public — run
    # ------------------------------------------------------------------

    def run(
        self,
        config: JobConfig,
        *,
        resume_job_id: str | None = None,
        cancel_event: threading.Event | None = None,
        chunk_listener: Callable[[ChunkCompletedEvent], None] | None = None,
    ) -> JobResult:
        """Executa o job: chunking → loop download/write/register → finalize.

        Story 2.11 — H10 closure: aceita ``cancel_event`` cooperativo.
        Loop chunks checa ``cancel_event.is_set()`` ENTRE chunks (não
        interrompe chunk em andamento — graceful drain). Worker wrapper
        em :mod:`data_downloader.public_api.download` mapeia para
        ``DownloadResult(status='cancelled')``.

        Args:
            config: Imutável :class:`JobConfig`.
            resume_job_id: Se passado, retoma job existente (Story 1.5
                AC8). Se ``None``, registra novo job.
            cancel_event: Event cooperativo opcional. Se setado, loop de
                chunks aborta na próxima iteração (graceful drain).
            chunk_listener: Callback opcional invocado APÓS cada chunk
                processado (Story 4.16 — Pichau directive 2026-05-06).
                Recebe :class:`ChunkCompletedEvent` com índice / total /
                duration / status. Cool path (1 chamada por chunk —
                R21 OK). Falhas no listener são suprimidas (best-effort
                — UI não pode quebrar o orchestrator).

        Returns:
            :class:`JobResult` com status final + métricas.

        Raises:
            ValueError: ``config.exchange`` inválido OU ``config.end <
                config.start``.
            InvalidContract: ``config.symbol`` é raiz e não há contrato
                vigente para ``config.start.date()``.
            DownloadError: Erro fatal não-recuperável durante run (e.g.
                catalog corrompido).
        """
        self._validate_config(config)

        metrics = OrchestratorMetrics(started_at=datetime.now(UTC))

        # 1. Resolve job_id (novo ou resume).
        job_id, resume_pending_chunks = self._resolve_job(config, resume_job_id)
        sm = JobStateMachine(job_id=job_id)

        # Story 2.9 — Bind contextvars (job_id como correlation_id, symbol,
        # exchange) para que TODOS os logs daqui em diante (incluindo
        # download_primitive, dll wrapper, writer) carreguem identificadores
        # automáticos. ``correlation_id`` = ``job_id`` por convenção
        # (ADR-010 §Configuração + ADR-005 thread model).
        bind_context(
            job_id=job_id,
            correlation_id=job_id,
            symbol=config.symbol,
            exchange=config.exchange,
        )

        log.info(
            "orchestrator.start",
            job_id=job_id,
            symbol=config.symbol,
            exchange=config.exchange,
            start=config.start.isoformat(),
            end=config.end.isoformat(),
            mode="resume" if resume_job_id else "fresh",
            cleanup_orphans_on_start=self._cleanup_orphans_on_start,
        )

        # 2. Transition IDLE → RUNNING.
        sm.transition(JobState.RUNNING)

        try:
            # 3. Resolve contract vigente.
            contract_code = self._resolve_contract(config)
            log.info(
                "orchestrator.contract_resolved",
                job_id=job_id,
                symbol_root=config.symbol,
                contract_code=contract_code,
            )

            # 4. Cache hit check (range coverage REAL — finding H8).
            completed = self._catalog.get_completed_partitions(contract_code, config.exchange)
            if self._is_full_cache_hit(config, completed):
                log.info(
                    "orchestrator.cache_hit",
                    job_id=job_id,
                    contract_code=contract_code,
                    partitions=len(completed),
                )
                self._catalog.update_job_progress(
                    job_id,
                    status="completed",
                    completed_at=datetime.now(UTC),
                    trades_count=sum(p.row_count for p in completed),
                    dll_version=self._safe_dll_version(),
                )
                metrics.completed_at = datetime.now(UTC)
                # Story 2.4 — cache hit conta como job finalizado.
                self._metrics.incr_counter("download_jobs_total", labels={"status": "cache_hit"})
                # Cache hit pula DRAINING — direto para COMMITTED via FAILED-skip.
                # Por simplicidade, não usa state machine no cache hit (nada para
                # drenar); apenas marca run como concluído.
                return JobResult(
                    job_id=job_id,
                    status="cache_hit",
                    contract_code=contract_code,
                    chunks_completed=0,
                    chunks_failed=0,
                    partitions_written=(),
                    metrics=metrics,
                )

            # 5. Calcula chunks.
            chunks = self._compute_chunks(config, contract_code, resume_pending_chunks)

            # Marca job como in_progress.
            self._catalog.update_job_progress(
                job_id,
                status="in_progress",
                started_at=metrics.started_at,
                dll_version=self._safe_dll_version(),
            )

            # 6. Loop chunks.
            # Story 2.4: gauge active_downloads = 1 enquanto job ativo
            # (cool path — set 1x antes do loop, 0 ao final no finally).
            self._metrics.set_gauge("active_downloads", 1.0)
            partitions_written: list[Path] = []
            total_chunks = len(chunks)
            for chunk_index, chunk in enumerate(chunks):
                # Story 2.11 — H10 closure: cancel cooperativo entre chunks.
                # NÃO interrompe chunk em andamento (preserva idempotência R5
                # + INV-12: chunk começa com fila vazia, termina com partition
                # registrada). Verifica APENAS no boundary entre chunks.
                if cancel_event is not None and cancel_event.is_set():
                    log.info(
                        "orchestrator.cancel_detected",
                        job_id=job_id,
                        chunks_completed=metrics.chunks_completed,
                        chunks_failed=metrics.chunks_failed,
                        chunks_remaining=total_chunks
                        - (metrics.chunks_completed + metrics.chunks_failed),
                    )
                    break

                result, event_status, chunk_duration, chunk_trades = self._process_chunk(
                    job_id=job_id,
                    config=config,
                    contract_code=contract_code,
                    chunk=chunk,
                    metrics=metrics,
                )
                if result is not None:
                    partitions_written.append(result.path)

                # Story 4.16 — emite ChunkCompletedEvent (cool path, 1x por
                # chunk — R21 OK). Listener é best-effort: exceções suprimidas
                # para que UI não derrube orchestrator. Emitido APÓS gap/
                # partition register para que o estado já esteja persistido.
                if chunk_listener is not None:
                    # mypy: event_status é str genérico em runtime mas Literal
                    # no contrato do dataclass. cast para satisfazer.
                    from typing import Literal
                    from typing import cast as _cast

                    event = ChunkCompletedEvent(
                        chunk_index=chunk_index,
                        total_chunks=total_chunks,
                        chunk_start=chunk.start.date(),
                        chunk_end=chunk.end.date(),
                        trades_count=chunk_trades,
                        duration_seconds=chunk_duration,
                        status=_cast(
                            Literal["success", "no_trades", "failed", "circuit_open"],
                            event_status,
                        ),
                    )
                    try:
                        chunk_listener(event)
                    except Exception as listener_exc:
                        log.warning(
                            "orchestrator.chunk_listener_failed",
                            job_id=job_id,
                            chunk_index=chunk_index,
                            error=repr(listener_exc),
                        )

            # 7. State transitions: drain → commit.
            sm.transition(JobState.DRAINING_DLL)
            # Sem dll_queue separada no orchestrator — download_chunk já
            # drenou suas filas e retornou. Transição é simbólica
            # (rastreabilidade INV-12 — declara o ponto onde "DLL drain"
            # foi confirmado pela primitiva).
            sm.transition(JobState.DRAINING_WRITE)
            # Writer roda síncrono dentro de _process_chunk; nada
            # pendente. Catalog WAL checkpoint após cada register_partition
            # (Story 1.5 AC12) garante durabilidade.
            sm.transition(JobState.COMMITTED)

            # 8. Final status.
            metrics.completed_at = datetime.now(UTC)
            final_status: JobStatus
            if metrics.chunks_failed == 0 and metrics.chunks_completed == len(chunks):
                final_status = "completed"
            elif metrics.chunks_completed > 0:
                final_status = "partial"
            else:
                final_status = "failed"

            self._catalog.update_job_progress(
                job_id,
                status=final_status,
                completed_at=metrics.completed_at,
                trades_count=metrics.trades_persisted,
            )

            # Story 2.4 — métricas finais do job (cool path, 1x por job).
            self._metrics.incr_counter("download_jobs_total", labels={"status": final_status})
            self._metrics.set_gauge("active_downloads", 0.0)

            sm.force_idle()

            log.info(
                "orchestrator.complete",
                job_id=job_id,
                status=final_status,
                chunks_completed=metrics.chunks_completed,
                chunks_failed=metrics.chunks_failed,
                trades_persisted=metrics.trades_persisted,
                duration_seconds=round(metrics.duration_seconds or 0.0, 3),
            )

            return JobResult(
                job_id=job_id,
                status=final_status,
                contract_code=contract_code,
                chunks_completed=metrics.chunks_completed,
                chunks_failed=metrics.chunks_failed,
                partitions_written=tuple(partitions_written),
                metrics=metrics,
            )

        except Exception as exc:
            # Erro fatal — transita para FAILED via melhor caminho disponível
            # antes de re-raise.
            metrics.completed_at = datetime.now(UTC)
            # Story 2.4 — métrica de job failed + reset gauge.
            try:
                self._metrics.incr_counter("download_jobs_total", labels={"status": "failed"})
                self._metrics.set_gauge("active_downloads", 0.0)
            except Exception:  # pragma: no cover defensive
                pass
            self._handle_fatal_error(sm, job_id, exc)
            raise
        finally:
            # Story 2.9 — Limpa contextvars no fim do job (sucesso, cache_hit
            # ou erro). Evita contaminação cross-job se o mesmo thread roda
            # múltiplos jobs sequencialmente (ADR-010 AC2).
            clear_context()

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _validate_config(self, config: JobConfig) -> None:
        """Valida invariantes antes do run."""
        if config.exchange not in ("F", "B"):
            raise ValueError(
                f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {config.exchange!r}"
            )
        if config.end < config.start:
            raise ValueError(f"config.end ({config.end}) must be >= config.start ({config.start})")
        if config.max_retry_attempts < 1:
            raise ValueError(f"max_retry_attempts must be >= 1; got {config.max_retry_attempts}")

    def _resolve_job(
        self,
        config: JobConfig,
        resume_job_id: str | None,
    ) -> tuple[str, tuple[Partition, ...] | None]:
        """Registra novo job ou retoma existente.

        Returns:
            Tuple ``(job_id, resume_pending_chunks)`` onde
            ``resume_pending_chunks`` é ``None`` no caminho fresh e
            tupla das ``Partition`` já completas no caminho resume (para
            calcular sub-chunks faltantes).
        """
        if resume_job_id is None:
            job_id = self._catalog.register_job(
                symbol=config.symbol,
                exchange=config.exchange,
                requested_start=config.start,
                requested_end=config.end,
            )
            return job_id, None

        plan = self._catalog.resume_job(resume_job_id)
        return resume_job_id, plan.completed_partitions

    def _resolve_contract(self, config: JobConfig) -> str:
        """Resolve contrato vigente para ``config.symbol`` em ``config.start.date()``.

        Se ``config.resolve_contract == False``, retorna ``config.symbol``
        diretamente (assume já ser contrato vigente).
        """
        if not config.resolve_contract:
            return config.symbol
        # Resolve por raiz — propaga InvalidContract se não houver vigência.
        return vigent_contract(
            self._catalog,
            config.symbol,
            config.start.date(),
            exchange=config.exchange,
        )

    def _is_full_cache_hit(
        self,
        config: JobConfig,
        completed_partitions: list[Partition],
    ) -> bool:
        """Verifica se ``[start, end]`` é subset da união de partições completas.

        Granularidade mensal — alinhada a ``compute_pending_chunks`` da Story 1.5
        (ADR-004 partition layout). Cache hit REAL = todos os meses em
        ``[start.year/month .. end.year/month]`` têm partição registrada
        para ``(symbol, exchange)``.

        finding H8 — distingue "partição existe" de "range coberto":
        partições isoladas nas pontas NÃO contam como cache hit.
        """
        if not completed_partitions:
            return False
        completed_keys = {(p.year, p.month) for p in completed_partitions}
        year, month = config.start.year, config.start.month
        end_y, end_m = config.end.year, config.end.month
        while (year, month) <= (end_y, end_m):
            if (year, month) not in completed_keys:
                return False
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
        return True

    def _resolve_chunk_days_map(
        self,
        config: JobConfig,
        contract_code: str,
    ) -> Mapping[str, int] | None:
        """Resolve qual ``chunk_days_map`` passar ao chunker (Story 4.16).

        Ordem de precedência:

        1. ``config.chunk_days_map`` explícito → usado direto (testes/avançado).
        2. Caso contrário → constrói ``{contract_code: get_chunk_days(contract_code)}``,
           o que garante que o chunker use exatamente o N do strategy
           (Política unificada V1.1.0+ — ADR-023: TODOS=1).

        O map de 1 entrada funciona porque ``chunker.chunk_days_for_symbol``
        faz match por ``startswith`` — ``contract_code.startswith(contract_code)``
        é sempre verdadeiro (longest-prefix wins), então o lookup acerta.
        """
        if config.chunk_days_map is not None:
            return config.chunk_days_map
        return {contract_code: get_chunk_days(contract_code)}

    def _compute_chunks(
        self,
        config: JobConfig,
        contract_code: str,
        resume_pending_chunks: tuple[Partition, ...] | None,
    ) -> list[ChunkRange]:
        """Calcula sub-chunks (granularidade dias úteis) para o run.

        Caminho **fresh:** chunker quebra ``[config.start, config.end]`` em
        sub-intervalos. Story 4.16 + ADR-023 (V1.1.0+):
        ``chunk_days_map`` é derivado de :func:`get_chunk_days` — política
        unificada TODOS=1 dia útil. Se o caller passou
        ``config.chunk_days_map`` explicitamente, este override do caller
        prevalece (utilizado em testes que precisam isolar a estratégia).

        Caminho **resume:** subtrai partições já completas (granularidade
        mensal Story 1.5). Para cada mês ainda não-completo dentro do
        range, gera sub-chunks com chunker. Garante que re-rodar é safe
        (R5).
        """
        chunk_days_map = self._resolve_chunk_days_map(config, contract_code)

        if resume_pending_chunks is None:
            return chunk_date_range(
                contract_code,
                config.exchange,
                config.start,
                config.end,
                chunk_days_map=chunk_days_map,
            )

        # Caminho resume — meses já feitos viram set; expandimos os meses
        # faltantes em sub-chunks de dias úteis.
        completed_keys = {(p.year, p.month) for p in resume_pending_chunks}
        chunks: list[ChunkRange] = []

        year, month = config.start.year, config.start.month
        end_y, end_m = config.end.year, config.end.month
        while (year, month) <= (end_y, end_m):
            if (year, month) in completed_keys:
                # mês completo — pula.
                pass
            else:
                month_start = max(
                    datetime(year, month, 1),
                    config.start,
                )
                next_month = (year + 1, 1) if month == 12 else (year, month + 1)
                # Last instant do mês = next_month_start - 1us.
                next_dt = datetime(next_month[0], next_month[1], 1)
                # Subtrai 1 microssegundo para ficar dentro do mês.
                month_end_inclusive = (
                    next_dt.replace(microsecond=next_dt.microsecond) - _ONE_MICROSECOND
                )
                month_end = min(month_end_inclusive, config.end)
                chunks.extend(
                    chunk_date_range(
                        contract_code,
                        config.exchange,
                        month_start,
                        month_end,
                        chunk_days_map=chunk_days_map,
                    )
                )
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
        return chunks

    def _process_chunk(
        self,
        *,
        job_id: str,
        config: JobConfig,
        contract_code: str,
        chunk: ChunkRange,
        metrics: OrchestratorMetrics,
    ) -> tuple[WriteResult | None, str, float, int]:
        """Processa 1 chunk: download (com retry) → writer → register_partition.

        Retorna tupla ``(write_result, event_status, duration_seconds,
        trades_count)``:

        - ``write_result``: :class:`WriteResult` se chunk persistiu trades;
          ``None`` se falhou OU não havia trades.
        - ``event_status``: ``"success"``, ``"no_trades"``, ``"failed"`` ou
          ``"circuit_open"`` — alimenta :class:`ChunkCompletedEvent.status`
          consumido pela UI (Story 4.16).
        - ``duration_seconds``: tempo total deste chunk (download+write+
          register).
        - ``trades_count``: trades persistidos neste chunk (0 em failed/
          no_trades/circuit_open).

        Falhas são absorvidas (registra gap + segue) — não levanta para
        o caller (loop deve continuar próximo chunk).

        Story 2.9 — bind ``chunk_id`` (placeholder por chunk_start range) em
        contextvars antes do download para que logs do download_primitive +
        DLL sejam atribuíveis ao chunk corrente. ``chunk_id`` REAL é gerado
        por ``download_chunk`` (uuid hex) e re-bound assim que disponível
        (override) — ver ``_do_download``.
        """
        # Bind chunk identifier (range-based label até o uuid real estar
        # disponível). Não usamos bound_context porque o chunk_id "real"
        # vem de download_chunk e queremos override transparente; ao final
        # do chunk processamos try/finally para unbind (preserva job_id +
        # symbol bound em ``run``).
        chunk_label = f"{chunk.start.isoformat()}__{chunk.end.isoformat()}"
        bind_context(chunk_id=chunk_label, symbol=contract_code)

        try:
            return self._process_chunk_inner(
                job_id=job_id,
                config=config,
                contract_code=contract_code,
                chunk=chunk,
                metrics=metrics,
            )
        finally:
            unbind_context("chunk_id")

    def _process_chunk_inner(
        self,
        *,
        job_id: str,
        config: JobConfig,
        contract_code: str,
        chunk: ChunkRange,
        metrics: OrchestratorMetrics,
    ) -> tuple[WriteResult | None, str, float, int]:
        """Corpo de :meth:`_process_chunk` (ver docstring).

        Separado em método interno para permitir try/finally limpo no
        wrapper sem aninhamento adicional (ver acima).
        """
        log.info(
            "orchestrator.chunk_start",
            job_id=job_id,
            symbol=contract_code,
            exchange=config.exchange,
            chunk_start=chunk.start.isoformat(),
            chunk_end=chunk.end.isoformat(),
        )

        chunk_t0 = time.monotonic()
        # Story 2.6 — obtém breaker para (symbol, exchange). Em OPEN,
        # CircuitOpenError economiza retry inteiro + sleep.
        breaker = self._get_breaker(contract_code, config.exchange)

        def _do_download() -> ChunkResult:
            # Q02-E (Story 2.6 AC4): progress=99% reconnect NÃO levanta
            # exception em download_chunk — retorna status='completed' OU
            # status='timeout' (timeout duro). Apenas NL_* error codes
            # reais ou TimeoutError contam como falha (categoria via
            # taxonomy NL_*).
            result = download_chunk(
                self._dll,
                contract_code,
                config.exchange,
                chunk.start,
                chunk.end,
                timeout=config.chunk_timeout_seconds,
            )
            if result.status == "timeout":
                raise TimeoutError(
                    f"download_chunk timed out for {contract_code} " f"[{chunk.start}, {chunk.end}]"
                )
            if result.status == "failed":
                # OSError carrega ``nl_code`` para o RetryPolicy classificar
                # via taxonomia (TRANSIENT vs PERMANENT vs UNKNOWN).
                err = OSError(
                    f"download_chunk failed (NL_{result.nl_error_code}) for "
                    f"{contract_code} [{chunk.start}, {chunk.end}]"
                )
                err.nl_code = result.nl_error_code  # type: ignore[attr-defined]
                raise err
            return result

        def _do_download_with_breaker() -> ChunkResult:
            # breaker.call() aplica state machine: OPEN → CircuitOpenError
            # imediato; HALF_OPEN/CLOSED → executa fn, conta result.
            return breaker.call(_do_download)

        try:
            chunk_result = with_retry(
                _do_download_with_breaker,
                op_name=f"download_chunk[{contract_code}]",
                policy=self._retry_policy,
            )
        except CircuitOpenError as exc:
            # Story 2.6 AC5 — breaker bloqueou. Registra gap com reason
            # específico e segue (não aborta job; outros chunks podem
            # completar). Counter chunks_completed_total{status=circuit_open}.
            metrics.chunks_failed += 1
            chunk_duration = time.monotonic() - chunk_t0
            self._metrics.incr_counter(
                "chunks_completed_total",
                labels={"symbol": contract_code, "status": "circuit_open"},
            )
            self._metrics.observe_histogram(
                "chunk_duration_seconds",
                chunk_duration,
                labels={"symbol": contract_code},
            )
            self._catalog.register_gap(
                symbol=contract_code,
                exchange=config.exchange,
                gap_start=chunk.start,
                gap_end=chunk.end,
                reason="failed_chunk",
            )
            log.warning(
                "circuit_breaker.rejected",
                job_id=job_id,
                symbol=contract_code,
                chunk_start=chunk.start.isoformat(),
                chunk_end=chunk.end.isoformat(),
                retry_after_seconds=round(exc.retry_after_seconds, 1),
                failure_count=exc.failure_count,
            )
            return None, "circuit_open", chunk_duration, 0
        except RetryError as exc:
            # Falha definitiva após todas as tentativas (V1 path).
            metrics.chunks_failed += 1
            chunk_duration = time.monotonic() - chunk_t0
            self._metrics.incr_counter(
                "chunks_completed_total",
                labels={"symbol": contract_code, "status": "failed"},
            )
            self._metrics.observe_histogram(
                "chunk_duration_seconds",
                chunk_duration,
                labels={"symbol": contract_code},
            )
            self._metrics.set_gauge("last_chunk_duration_seconds", chunk_duration)
            self._catalog.register_gap(
                symbol=contract_code,
                exchange=config.exchange,
                gap_start=chunk.start,
                gap_end=chunk.end,
                reason="failed_chunk",
            )
            log.warning(
                "orchestrator.chunk_failed",
                job_id=job_id,
                symbol=contract_code,
                chunk_start=chunk.start.isoformat(),
                chunk_end=chunk.end.isoformat(),
                attempts=exc.attempts,
                last_error=repr(exc.last_exception),
            )
            return None, "failed", chunk_duration, 0
        except (OSError, TimeoutError) as exc:
            # Story 2.6 — quando RetryPolicy é usada (caminho default),
            # ela re-raise a última exception em vez de RetryError. Captura
            # aqui mantém isolamento por chunk (não aborta job inteiro).
            # PERMANENT/UNKNOWN também caem aqui (fail-fast pela policy).
            metrics.chunks_failed += 1
            chunk_duration = time.monotonic() - chunk_t0
            self._metrics.incr_counter(
                "chunks_completed_total",
                labels={"symbol": contract_code, "status": "failed"},
            )
            self._metrics.observe_histogram(
                "chunk_duration_seconds",
                chunk_duration,
                labels={"symbol": contract_code},
            )
            self._metrics.set_gauge("last_chunk_duration_seconds", chunk_duration)
            nl_code = getattr(exc, "nl_code", None)
            # NL_*-aware reason via taxonomy seria útil, mas o CHECK
            # constraint do catalog limita a um set fechado (Story 1.5).
            # Mantemos "failed_chunk" como bucket genérico — nl_code vai
            # para log estruturado para forensics.
            self._catalog.register_gap(
                symbol=contract_code,
                exchange=config.exchange,
                gap_start=chunk.start,
                gap_end=chunk.end,
                reason="failed_chunk",
            )
            log.warning(
                "orchestrator.chunk_failed",
                job_id=job_id,
                symbol=contract_code,
                chunk_start=chunk.start.isoformat(),
                chunk_end=chunk.end.isoformat(),
                last_error=repr(exc),
                nl_code=nl_code,
            )
            return None, "failed", chunk_duration, 0

        metrics.callbacks_received += len(chunk_result.trades)
        # Story 2.4 — counter trades recebidos (per-chunk batch — R21 OK).
        # Increment em batch (len(trades)) é cool path; NÃO chamamos
        # per-trade no callback DLL.
        if chunk_result.trades:
            self._metrics.incr_counter("trades_received_total", labels={"symbol": contract_code})

        # Caminho de sucesso — escreve Parquet + registra no catalog.
        if not chunk_result.trades:
            # Chunk válido sem trades (e.g. dia útil sem pregão real,
            # holiday não mapeado, etc.) — registra gap e continua.
            metrics.chunks_completed += 1
            chunk_duration = time.monotonic() - chunk_t0
            # Story 2.4 — métricas chunk completed sem trades.
            self._metrics.incr_counter(
                "chunks_completed_total",
                labels={"symbol": contract_code, "status": "no_trades"},
            )
            self._metrics.observe_histogram(
                "chunk_duration_seconds",
                chunk_duration,
                labels={"symbol": contract_code},
            )
            self._metrics.set_gauge("last_chunk_duration_seconds", chunk_duration)
            self._catalog.register_gap(
                symbol=contract_code,
                exchange=config.exchange,
                gap_start=chunk.start,
                gap_end=chunk.end,
                reason="no_trades",
            )
            log.info(
                "orchestrator.chunk_complete",
                job_id=job_id,
                symbol=contract_code,
                chunk_start=chunk.start.isoformat(),
                chunk_end=chunk.end.isoformat(),
                n_trades=0,
                duration_ms=int(chunk_duration * 1000),
                cache_hit=False,
            )
            return None, "no_trades", chunk_duration, 0

        # Converte TradeRecord (dataclass orchestrator) → TradeRecord
        # (TypedDict storage) e escreve.
        trade_records = [_to_schema_trade(t) for t in chunk_result.trades]
        partition = PartitionKey(
            exchange=config.exchange,
            symbol=contract_code,
            year=chunk.start.year,
            month=chunk.start.month,
        )
        write_result = self._writer.write(
            trade_records,
            partition,
            dll_version=self._safe_dll_version(),
            chunk_id=chunk_result.chunk_id,
        )
        # Register no catalog (two-phase commit emulado — Story 1.5 AC13).
        self._catalog.register_partition(
            write_result,
            partition,
            job_id=job_id,
        )

        metrics.chunks_completed += 1
        # ``trades_persisted`` conta trades NOVOS deste chunk (não o total
        # final da partição) para evitar double-counting quando múltiplos
        # chunks escrevem na mesma partição (mesmo mês). ``write_result.row_count``
        # reflete o total final pós-merge — útil para o catalog (UPSERT) mas
        # não como métrica de progresso de job.
        metrics.trades_persisted += len(chunk_result.trades)

        # Story 2.4 — métricas chunk success (cool path, 1x por chunk).
        chunk_duration = time.monotonic() - chunk_t0
        self._metrics.incr_counter(
            "chunks_completed_total",
            labels={"symbol": contract_code, "status": "success"},
        )
        self._metrics.incr_counter("parquet_writes_total", labels={"symbol": contract_code})
        self._metrics.observe_histogram(
            "chunk_duration_seconds", chunk_duration, labels={"symbol": contract_code}
        )
        self._metrics.set_gauge("last_chunk_duration_seconds", chunk_duration)

        log.info(
            "orchestrator.chunk_complete",
            job_id=job_id,
            symbol=contract_code,
            chunk_id=chunk_result.chunk_id,
            chunk_start=chunk.start.isoformat(),
            chunk_end=chunk.end.isoformat(),
            n_trades=len(chunk_result.trades),
            partition_total_rows=write_result.row_count,
            duration_ms=int(chunk_duration * 1000),
        )
        return write_result, "success", chunk_duration, len(chunk_result.trades)

    def _handle_fatal_error(
        self,
        sm: JobStateMachine,
        job_id: str,
        exc: BaseException,
    ) -> None:
        """Marca job como failed, transita state para FAILED, persiste error msg.

        Best-effort — toda falha aqui dentro é capturada e logada (não
        re-raised), porque o caller já está em ``except`` re-raise.
        """
        try:
            # Tenta transitar state para FAILED. Se já está em FAILED ou
            # IDLE, ignora.
            current = sm.state
            if current in (JobState.RUNNING, JobState.DRAINING_DLL, JobState.DRAINING_WRITE):
                sm.transition(JobState.FAILED)
                sm.force_idle()
            elif current == JobState.IDLE:
                # Erro antes mesmo de RUNNING — apenas registra.
                pass
        except Exception as inner:
            log.warning(
                "orchestrator.state_machine_cleanup_failed",
                job_id=job_id,
                error=repr(inner),
            )

        try:
            self._catalog.update_job_progress(
                job_id,
                status="failed",
                completed_at=datetime.now(UTC),
                error=repr(exc)[:500],  # cap em 500 chars para SQLite
            )
        except Exception as inner:
            log.warning(
                "orchestrator.catalog_update_failed",
                job_id=job_id,
                error=repr(inner),
            )

        # InvalidContract não é DownloadError — propaga direto (semantic).
        # Outras exceções viram DownloadError(cause=exc) somente no caller
        # se for o caso. Aqui apenas logamos.
        log.error(
            "orchestrator.fatal_error",
            job_id=job_id,
            error=repr(exc),
            error_type=type(exc).__name__,
        )

    def _get_breaker(self, symbol: str, exchange: str) -> CircuitBreaker:
        """Obtém (lazy-create) o circuit breaker para (symbol, exchange).

        Story 2.6 AC3 + AC5 — 1 breaker por par. Compartilha
        threshold/window/cooldown do template injetado em ``__init__``,
        ou usa defaults se nenhum template foi passado.
        """
        key = (symbol, exchange)
        with self._breakers_lock:
            existing = self._breakers.get(key)
            if existing is not None:
                return existing
            if self._cb_template is not None:
                breaker = CircuitBreaker(
                    symbol=symbol,
                    exchange=exchange,
                    failure_threshold=self._cb_template.failure_threshold,
                    window_seconds=self._cb_template.window_seconds,
                    cooldown_seconds=self._cb_template.base_cooldown_seconds,
                )
            else:
                breaker = CircuitBreaker(symbol=symbol, exchange=exchange)
            self._breakers[key] = breaker
            return breaker

    def _safe_dll_version(self) -> str:
        """Retorna ``dll.dll_version`` se atributo presente, senão ``"unknown"``.

        Tolerante a mocks de teste sem o attr.
        """
        try:
            return str(self._dll.dll_version)
        except (AttributeError, RuntimeError):
            return "unknown"


# =====================================================================
# Helpers
# =====================================================================


def _to_schema_trade(t: PrimitiveTradeRecord) -> SchemaTradeRecord:
    """Converte ``download_primitive.TradeRecord`` (dataclass) → schema.TradeRecord (TypedDict).

    Mapeia 20 campos canônicos (schema v1.1.0). ``ingestion_ts_ns`` e
    ``dll_version`` são re-enriquecidos pelo writer (Story 1.4) —
    preservamos os valores que o ingestor já preencheu.

    Nelo Council 32 (release blocker P0): v1.1.0 inclui ``buy_agent_name``,
    ``sell_agent_name`` e ``trade_type_name``. ``trade_type_name`` é
    resolvido aqui via :func:`schema.trade_type_name` (mapping
    ``TConnectorTradeType`` 0..13). v1.0.0 silenciosamente descartava
    esses 3 campos no writer.
    """
    from data_downloader.storage.schema import trade_type_name as _trade_type_name

    return SchemaTradeRecord(
        symbol=t.symbol,
        exchange=t.exchange,
        timestamp_ns=t.timestamp_ns,
        timestamp_str=t.timestamp_str,
        price=t.price,
        quantity=t.quantity,
        trade_id=t.trade_id,
        trade_type=t.trade_type,
        buy_agent_id=t.buy_agent_id,
        sell_agent_id=t.sell_agent_id,
        flags=t.flags,
        source_callback=t.source_callback,
        side=t.side,
        ingestion_ts_ns=t.ingestion_ts_ns,
        chunk_id=t.chunk_id,
        dll_version=t.dll_version,
        sequence_within_ns=t.sequence_within_ns,
        # v1.1.0 — agent name resolution (preservado do ingestor;
        # ``AgentResolver`` já populou via ``GetAgentName``).
        buy_agent_name=t.buy_agent_name,
        sell_agent_name=t.sell_agent_name,
        # v1.1.0 — trade type humano (resolvido via mapping enum
        # ``TConnectorTradeType`` — id desconhecido vira None).
        trade_type_name=_trade_type_name(t.trade_type),
    )


_ONE_MICROSECOND: Final[timedelta] = timedelta(microseconds=1)
