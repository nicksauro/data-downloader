"""data_downloader.orchestrator.broker.pool — Pool persistente de workers (Story 4.1 AC5).

Owner: Pyro (perf decisão pool persistente — H20) | Impl: Dex.
Refs:

- ``docs/adr/ADR-015-multiprocess-catalog.md`` §"H20: subprocess overhead em Windows"
- ``docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md`` D2

:class:`WorkerPool` mantém **N processos workers persistentes** (aquecidos)
que ficam em loop aguardando :class:`JobSpec` na sua input_queue.
Reuso entre jobs evita o penalty de 2.7-10s spawn por download (finding H20
do Pyro).

Lifecycle:

1. ``WorkerPool(config, mutation_queue, broker)`` — cria mas NÃO spawn.
2. ``pool.start_pool()`` — spawn N workers, registra response_queues no broker.
3. ``pool.submit_jobs(jobs)`` → list[JobOutcome]:
   - distribui jobs via job_queue compartilhada;
   - aguarda outcomes via output_queue;
   - retorna outcomes na ordem submetida.
4. ``pool.stop_pool(timeout=10.0)`` — envia sentinel + join (graceful).

Workers:

- Cada worker é um processo independente (mp.Process).
- Função entry-point: :func:`_worker_main` — top-level (pickle-safe Windows).
- Worker loop: ``while True: job = job_queue.get(); if None: break;
  result = run(job); output_queue.put(result)``.
- Worker carrega ProfitDLL via factory (1 conexão por processo — R20).

V1 simplification: NÃO há monitor de health (AC5 menciona "restart se crash"
mas mock-first abordagem deixa isso para 4.1-followup quando smoke real
revelar comportamento de crash). Worker que crasha = mp.Process morre, joins
detectam via ``is_alive()`` no stop_pool e logam.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
from dataclasses import dataclass
from datetime import datetime
from queue import Empty
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from multiprocessing import Queue
    from pathlib import Path

    from data_downloader.orchestrator.broker.catalog_broker import CatalogBroker
    from data_downloader.orchestrator.orchestrator import JobConfig

_LOG = logging.getLogger(__name__)

# Sentinel — None enviado na job_queue sinaliza shutdown ao worker.
_WORKER_SHUTDOWN_SENTINEL: None = None

# Default timeout (s) para outcome polling no submit_jobs.
_OUTCOME_POLL_TIMEOUT_S: float = 0.5


@dataclass(frozen=True)
class PoolConfig:
    """Configuração imutável do :class:`WorkerPool`.

    Atributos:
        n_workers: Número de processos workers persistentes (default 4).
        worker_factory_module: Path do módulo Python que define a factory
            do Orchestrator dentro do worker (ex.:
            ``"data_downloader.orchestrator.broker._mock_worker_factory"``
            para tests). Default ``None`` = produção (carrega DLL real).
            Necessário ser top-level para pickle (Windows spawn).
        worker_factory_callable: Nome da factory dentro do módulo
            (default ``"create_orchestrator"``). Factory recebe (data_dir,
            broker_client) e retorna ``Orchestrator``.
        data_dir: Raiz dos dados (compartilhada entre workers — escrita
            via ``BrokerCatalogClient`` ao broker, leitura local Parquet).
        broker_timeout_s: Timeout default por mutação broker.
        worker_warmup_timeout_s: Tempo (s) máximo para worker reportar
            ready após spawn (default 30s).
    """

    n_workers: int = 4
    data_dir: Path | None = None
    worker_factory_module: str | None = None
    worker_factory_callable: str = "create_orchestrator"
    broker_timeout_s: float = 30.0
    worker_warmup_timeout_s: float = 30.0


@dataclass(frozen=True)
class JobSpec:
    """Spec de 1 job submetido ao pool (envelope para serialização pickle).

    Não usa :class:`JobConfig` direto porque ``Mapping[str, int]``
    (chunk_days_map) pode não serializar limpo. JobSpec carrega apenas
    campos pickle-safe.
    """

    job_index: int  # ordem de submissão — usado para preservar ordem em outcomes
    symbol: str
    exchange: str
    start_iso: str
    end_iso: str
    chunk_timeout_seconds: int = 1800
    max_retry_attempts: int = 3
    resolve_contract: bool = True


@dataclass(frozen=True)
class JobOutcome:
    """Resultado de 1 job (envelope serializável)."""

    job_index: int
    symbol: str
    status: str  # "completed" | "partial" | "failed" | "cache_hit" | "exception"
    job_id: str | None = None
    contract_code: str | None = None
    chunks_completed: int = 0
    chunks_failed: int = 0
    trades_persisted: int = 0
    duration_seconds: float = 0.0
    error: str | None = None  # apenas se status == "exception"


class WorkerFactoryProtocol(Protocol):
    """Protocol esperado da factory chamada pelo worker.

    Recebe (data_dir, broker_client) e retorna Orchestrator-like object com
    método ``run(JobConfig) -> JobResult``. Usado pelo worker para isolar
    construção de DLL/writer/orchestrator (produção vs mock para testes).
    """

    def __call__(
        self,
        data_dir: Path,
        broker_client: Any,  # BrokerCatalogClient
    ) -> Any:  # Orchestrator
        ...


class WorkerPool:
    """Pool persistente de N workers (AC5 — H20 mitigação).

    Args:
        config: :class:`PoolConfig` imutável.
        mutation_queue: Queue compartilhada que workers usam para enviar
            mutações ao broker. Já criada externamente (pelo
            :class:`MultiSymbolMaster`).
        broker: :class:`CatalogBroker` já iniciado — pool registra
            response_queues neste broker.

    Lifecycle:
        - ``start_pool()`` → spawn workers + warmup + registra acks.
        - ``submit_jobs(jobs)`` → list[JobOutcome] (ordem preservada).
        - ``stop_pool()`` → graceful shutdown.

    Notes:
        Re-uso entre múltiplas chamadas a ``submit_jobs`` é suportado
        (workers continuam vivos entre batches). Útil para CLI batch
        scenarios (futuro V1.x).
    """

    def __init__(
        self,
        config: PoolConfig,
        mutation_queue: Queue[Any],
        broker: CatalogBroker,
    ) -> None:
        self._config = config
        self._mutation_queue = mutation_queue
        self._broker = broker
        self._workers: list[Any] = []  # mp.Process or SpawnProcess (typing varies by ctx)
        self._worker_response_queues: dict[str, Queue[Any]] = {}
        self._job_queue: Queue[Any] | None = None
        self._output_queue: Queue[Any] | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start_pool(self) -> None:
        """Spawn N workers + registra response_queues no broker.

        Idempotente — se já startado, no-op.

        Raises:
            RuntimeError: Pool config inválida (n_workers < 1).
        """
        if self._started:
            return
        if self._config.n_workers < 1:
            raise RuntimeError(f"PoolConfig.n_workers must be >= 1; got {self._config.n_workers}")

        ctx = mp.get_context("spawn")  # explicit Windows-compatible
        self._job_queue = ctx.Queue()
        self._output_queue = ctx.Queue()

        for i in range(self._config.n_workers):
            worker_id = f"worker-{i}"
            response_queue: Queue[Any] = ctx.Queue()
            self._worker_response_queues[worker_id] = response_queue
            self._broker.register_worker(worker_id, response_queue)

            proc = ctx.Process(
                target=_worker_main,
                args=(
                    worker_id,
                    self._mutation_queue,
                    response_queue,
                    self._job_queue,
                    self._output_queue,
                    self._config,
                ),
                name=worker_id,
                daemon=False,  # non-daemon para join confiável
            )
            proc.start()
            self._workers.append(proc)

        self._started = True
        _LOG.info(
            "worker_pool.started",
            extra={"n_workers": self._config.n_workers},
        )

    def submit_jobs(self, jobs: list[JobSpec]) -> list[JobOutcome]:
        """Distribui jobs entre workers + coleta outcomes em ordem.

        Args:
            jobs: Lista de :class:`JobSpec` a executar. Cada um vira um
                item na ``job_queue`` compartilhada; workers consomem em
                FIFO (não round-robin estrito — workers idle pegam primeiro).

        Returns:
            Lista de :class:`JobOutcome` na MESMA ordem de ``jobs``
            (job_index preserva mapeamento).

        Raises:
            RuntimeError: Pool não startado.
        """
        if not self._started or self._job_queue is None or self._output_queue is None:
            raise RuntimeError("WorkerPool.submit_jobs called before start_pool()")
        if not jobs:
            return []

        for spec in jobs:
            self._job_queue.put(spec)

        outcomes: dict[int, JobOutcome] = {}
        n_expected = len(jobs)
        deadline = time.monotonic() + self._compute_collect_deadline(jobs)
        while len(outcomes) < n_expected:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOG.warning(
                    "worker_pool.collect_timeout",
                    extra={
                        "received": len(outcomes),
                        "expected": n_expected,
                    },
                )
                break
            try:
                outcome = self._output_queue.get(timeout=min(remaining, _OUTCOME_POLL_TIMEOUT_S))
            except Empty:
                continue
            if not isinstance(outcome, JobOutcome):
                _LOG.warning(
                    "worker_pool.invalid_outcome_type",
                    extra={"type": type(outcome).__name__},
                )
                continue
            outcomes[outcome.job_index] = outcome

        # Preenche outcomes ausentes (timeout/crash) com placeholders.
        ordered: list[JobOutcome] = []
        for spec in jobs:
            if spec.job_index in outcomes:
                ordered.append(outcomes[spec.job_index])
            else:
                ordered.append(
                    JobOutcome(
                        job_index=spec.job_index,
                        symbol=spec.symbol,
                        status="exception",
                        error="worker_did_not_return_outcome",
                    )
                )
        return ordered

    def stop_pool(self, *, timeout: float = 10.0) -> None:
        """Graceful shutdown: envia sentinel para cada worker + join.

        Args:
            timeout: Tempo (s) máximo aguardando cada worker terminar.

        Notes:
            Workers que não respondem ao sentinel no timeout são
            terminate()d (kill). Logs warning.
        """
        if not self._started:
            return
        if self._job_queue is None:
            return

        # Envia 1 sentinel por worker (cada worker consome exatamente 1
        # sentinel ao receber e sai do loop).
        for _ in self._workers:
            try:
                self._job_queue.put(_WORKER_SHUTDOWN_SENTINEL, timeout=2.0)
            except Exception as exc:
                _LOG.warning(
                    "worker_pool.sentinel_send_failed",
                    extra={"error": str(exc)},
                )

        deadline = time.monotonic() + timeout
        for proc in self._workers:
            remaining = max(0.1, deadline - time.monotonic())
            proc.join(timeout=remaining)
            if proc.is_alive():
                _LOG.warning(
                    "worker_pool.join_timeout_killing",
                    extra={"worker_name": proc.name},
                )
                proc.terminate()
                proc.join(timeout=2.0)
                if proc.is_alive():
                    _LOG.warning(
                        "worker_pool.terminate_failed_killing",
                        extra={"worker_name": proc.name},
                    )
                    # Última tentativa - kill (Python 3.7+).
                    if hasattr(proc, "kill"):
                        proc.kill()
                        proc.join(timeout=1.0)

        self._workers.clear()
        self._worker_response_queues.clear()
        self._started = False
        _LOG.info("worker_pool.stopped")

    @property
    def started(self) -> bool:
        """``True`` se :meth:`start_pool` foi chamado e nenhum stop ainda."""
        return self._started

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_collect_deadline(self, jobs: list[JobSpec]) -> float:
        """Estima deadline conservador: max(job.chunk_timeout x 2 x max_chunks_estimate).

        Heurística simples — real cap em 1h por job (suficiente para 1 mês
        WDO). Worker timeout interno é por chunk, não por job total.
        """
        # Cap conservador: número de jobs x 1h. Bench mock terminam em segundos.
        return float(len(jobs)) * 3600.0


# =====================================================================
# Worker entry-point — top-level para pickle (Windows spawn)
# =====================================================================


def _worker_main(
    worker_id: str,
    mutation_queue: Queue[Any],
    response_queue: Queue[Any],
    job_queue: Queue[Any],
    output_queue: Queue[Any],
    config: PoolConfig,
) -> None:
    """Entry-point do worker process. Top-level para pickle (Windows).

    Loop:

    1. Carrega factory via importlib (config.worker_factory_module +
       worker_factory_callable).
    2. Constrói BrokerCatalogClient (worker-side stub).
    3. Constrói Orchestrator via factory(data_dir, broker_client).
    4. Loop: ``while True: job = job_queue.get(); if None: break;
       result = orch.run(...); output_queue.put(JobOutcome)``.

    Raises (no worker process — propagado via JobOutcome.status="exception"):
        Qualquer exception em factory ou run vira JobOutcome com error.
    """
    # Imports DENTRO do worker — Windows spawn re-executa este módulo.
    import importlib
    import logging as _logging
    import traceback as _tb

    log = _logging.getLogger(f"worker.{worker_id}")
    log.info("worker.started worker_id=%s pid=%d", worker_id, _pid_safe())

    try:
        from data_downloader.orchestrator.broker.worker_client import (
            BrokerCatalogClient,
        )
        from data_downloader.orchestrator.orchestrator import JobConfig

        broker_client = BrokerCatalogClient(
            mutation_queue=mutation_queue,
            response_queue=response_queue,
            worker_id=worker_id,
            timeout=config.broker_timeout_s,
        )

        # Carrega factory.
        if config.worker_factory_module is None:
            raise RuntimeError(
                "PoolConfig.worker_factory_module is None — cannot spawn "
                "worker without factory. Production setup must specify "
                "factory module."
            )
        factory_mod = importlib.import_module(config.worker_factory_module)
        factory = getattr(factory_mod, config.worker_factory_callable)
        if not callable(factory):
            raise RuntimeError(
                f"Factory {config.worker_factory_module}."
                f"{config.worker_factory_callable} is not callable"
            )
        if config.data_dir is None:
            raise RuntimeError("PoolConfig.data_dir is None")
        orchestrator = factory(config.data_dir, broker_client)

        # Loop principal.
        while True:
            try:
                spec = job_queue.get(timeout=1.0)
            except Empty:
                continue
            if spec is _WORKER_SHUTDOWN_SENTINEL:
                log.info("worker.shutdown_sentinel worker_id=%s", worker_id)
                break
            if not isinstance(spec, JobSpec):
                log.warning(
                    "worker.invalid_spec_type worker_id=%s type=%s",
                    worker_id,
                    type(spec).__name__,
                )
                continue

            outcome = _execute_job(orchestrator, spec, log, JobConfig)
            try:
                output_queue.put(outcome, timeout=5.0)
            except Exception as put_exc:
                log.error(
                    "worker.outcome_put_failed worker_id=%s err=%s",
                    worker_id,
                    str(put_exc),
                )

    except Exception as outer_exc:
        log.error(
            "worker.fatal worker_id=%s err=%s tb=%s",
            worker_id,
            str(outer_exc),
            _tb.format_exc(),
        )
        # Tenta sinalizar falha para todos os jobs pending.
        import contextlib as _contextlib

        with _contextlib.suppress(Exception):
            output_queue.put(
                JobOutcome(
                    job_index=-1,
                    symbol="<worker-fatal>",
                    status="exception",
                    error=f"worker_fatal: {outer_exc}",
                )
            )

    log.info("worker.exiting worker_id=%s", worker_id)


def _execute_job(
    orchestrator: Any,
    spec: JobSpec,
    log: logging.Logger,
    job_config_cls: type[JobConfig],
) -> JobOutcome:
    """Executa 1 job e empacota resultado em :class:`JobOutcome`.

    Capture-all: qualquer exception vira ``status='exception'``.
    """
    t0 = time.monotonic()
    try:
        cfg = job_config_cls(
            symbol=spec.symbol,
            exchange=spec.exchange,
            start=datetime.fromisoformat(spec.start_iso),
            end=datetime.fromisoformat(spec.end_iso),
            chunk_timeout_seconds=spec.chunk_timeout_seconds,
            max_retry_attempts=spec.max_retry_attempts,
            resolve_contract=spec.resolve_contract,
        )
        result = orchestrator.run(cfg)
        dur = time.monotonic() - t0
        return JobOutcome(
            job_index=spec.job_index,
            symbol=spec.symbol,
            status=result.status,
            job_id=result.job_id,
            contract_code=result.contract_code,
            chunks_completed=result.chunks_completed,
            chunks_failed=result.chunks_failed,
            trades_persisted=result.metrics.trades_persisted,
            duration_seconds=dur,
        )
    except Exception as exc:
        dur = time.monotonic() - t0
        log.warning(
            "worker.job_exception job_index=%d symbol=%s err=%s",
            spec.job_index,
            spec.symbol,
            str(exc),
        )
        return JobOutcome(
            job_index=spec.job_index,
            symbol=spec.symbol,
            status="exception",
            duration_seconds=dur,
            error=str(exc)[:500],
        )


def _pid_safe() -> int:
    """Best-effort PID retrieval (defensive for tests)."""
    try:
        import os

        return os.getpid()
    except Exception:
        return -1


__all__ = [
    "JobOutcome",
    "JobSpec",
    "PoolConfig",
    "WorkerFactoryProtocol",
    "WorkerPool",
]
