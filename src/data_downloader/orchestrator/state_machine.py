"""data_downloader.orchestrator.state_machine — Job state machine (ADR-005 amendment).

Owner: Dex (impl) | Audit: Aria (state model — ADR-005 amendment).
Story 1.7a — AC3.

State machine canônica de um download job, derivada do amendment de ADR-005
(2026-05-03 — race no shutdown, INV-11/INV-12). Estados explícitos
permitem que o orchestrator declare "fim de chunk" só quando ``dll_queue``
e ``write_queue`` estão drenadas E o último commit SQLite foi feito.

Estados e transições válidas::

       IDLE ──run()──> RUNNING ──draining──> DRAINING_DLL
                          │                       │
                          │                       ▼
                          │                  DRAINING_WRITE
                          │                       │
                          │                       ▼
                          ├──fatal──> FAILED  COMMITTED
                          │                       │
                          ▼                       ▼
                       FAILED                   IDLE

Transições válidas:

- IDLE → RUNNING               (orchestrator.run() iniciou)
- RUNNING → DRAINING_DLL       (último chunk OK ou cancel solicitado)
- RUNNING → FAILED             (erro fatal antes do drain)
- DRAINING_DLL → DRAINING_WRITE (dll_queue vazia, ingestor idle)
- DRAINING_DLL → FAILED        (timeout no drain)
- DRAINING_WRITE → COMMITTED   (write_queue vazia + commit SQLite OK)
- DRAINING_WRITE → FAILED      (timeout ou erro de commit)
- COMMITTED → IDLE             (cleanup feito; pronto para próximo run)
- FAILED → IDLE                (cleanup feito; estado terminal de erro)

Qualquer transição não listada levanta ``InvalidStateTransition``.

Lei R3 / INV-11 (separação física): este módulo NÃO referencia threads
diretamente — é puro state machine + lock. O orchestrator decide QUANDO
transitar; este módulo apenas valida que A → B é legal.

LEIS RESPEITADAS:
- R21 (hot-path): logger é cool-path (1 evento por transição, < 1/s típico).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum, auto
from typing import Final

import structlog

__all__ = [
    "VALID_TRANSITIONS",
    "InvalidStateTransition",
    "JobState",
    "JobStateMachine",
]


log: structlog.stdlib.BoundLogger = structlog.get_logger(
    "data_downloader.orchestrator.state_machine"
)


class JobState(Enum):
    """Estados possíveis de um download job (ADR-005 amendment).

    Ordem é semanticamente significativa (forward-only no happy path):
    ``IDLE → RUNNING → DRAINING_DLL → DRAINING_WRITE → COMMITTED → IDLE``.

    ``FAILED`` é terminal alternativo a ``COMMITTED`` quando o run aborta
    por erro fatal antes do commit final.
    """

    IDLE = auto()
    RUNNING = auto()
    DRAINING_DLL = auto()
    DRAINING_WRITE = auto()
    COMMITTED = auto()
    FAILED = auto()


# Mapeamento explícito de transições válidas (Aria — ADR-005 amendment).
VALID_TRANSITIONS: Final[dict[JobState, frozenset[JobState]]] = {
    JobState.IDLE: frozenset({JobState.RUNNING}),
    JobState.RUNNING: frozenset({JobState.DRAINING_DLL, JobState.FAILED}),
    JobState.DRAINING_DLL: frozenset({JobState.DRAINING_WRITE, JobState.FAILED}),
    JobState.DRAINING_WRITE: frozenset({JobState.COMMITTED, JobState.FAILED}),
    JobState.COMMITTED: frozenset({JobState.IDLE}),
    JobState.FAILED: frozenset({JobState.IDLE}),
}


class InvalidStateTransition(RuntimeError):  # noqa: N818  alinhado com InvalidContract (public_api)
    """Transição de estado inválida tentada.

    Levantada por :meth:`JobStateMachine.transition` quando o destino não
    está em :data:`VALID_TRANSITIONS` para o estado corrente.

    Attributes:
        from_state: Estado corrente no momento da chamada.
        to_state: Estado pedido (rejeitado).
    """

    def __init__(self, from_state: JobState, to_state: JobState) -> None:
        super().__init__(
            f"Invalid transition: {from_state.name} → {to_state.name} "
            f"(allowed: {sorted(s.name for s in VALID_TRANSITIONS.get(from_state, set()))})"
        )
        self.from_state = from_state
        self.to_state = to_state


class JobStateMachine:
    """State machine thread-safe de um job de download.

    Cada instância representa o ciclo de vida de UM job (1 chamada a
    ``Orchestrator.run``). O orchestrator é dono da instância; outras
    threads (ingestor, writer) consultam ``state`` mas não devem
    transitar.

    Args:
        job_id: UUID do job (correlation_id em logs — finding L2).
        on_change: Callback opcional ``(from, to) -> None`` invocado APÓS
            cada transição válida (com lock liberado). Útil para
            observabilidade externa (ex.: gauge de estado).

    Thread-safety:
        ``transition()`` adquire um ``threading.Lock`` interno; concorrentes
        são serializados. ``state`` (property) lê snapshot sem lock — leitura
        atômica de uma referência Python.
    """

    def __init__(
        self,
        job_id: str,
        *,
        on_change: Callable[[JobState, JobState], None] | None = None,
    ) -> None:
        self.job_id = job_id
        self._state: JobState = JobState.IDLE
        self._lock = threading.Lock()
        self._on_change = on_change

    @property
    def state(self) -> JobState:
        """Snapshot do estado atual (leitura sem lock)."""
        return self._state

    def transition(self, to: JobState) -> None:
        """Transita para ``to`` se transição é válida.

        Atomic via ``threading.Lock``; emite event structlog
        ``orchestrator.state_transition`` (cool path — 1 evento por
        transição, R21 OK).

        Args:
            to: Estado destino.

        Raises:
            InvalidStateTransition: Transição não permitida em
                :data:`VALID_TRANSITIONS`.
        """
        with self._lock:
            current = self._state
            allowed = VALID_TRANSITIONS.get(current, frozenset())
            if to not in allowed:
                raise InvalidStateTransition(current, to)
            self._state = to

        # Logger e callback fora do lock — evita reentrância e mantém lock curto.
        log.info(
            "orchestrator.state_transition",
            job_id=self.job_id,
            from_state=current.name,
            to_state=to.name,
        )
        if self._on_change is not None:
            self._on_change(current, to)

    def is_terminal(self) -> bool:
        """``True`` se o estado atual é terminal (``IDLE`` pós-completed/failed).

        Note: ``COMMITTED`` e ``FAILED`` NÃO são terminais — devem
        transitar para ``IDLE`` após cleanup. Apenas ``IDLE`` (após o
        ciclo completo) é terminal sem trabalho pendente.
        """
        return self._state == JobState.IDLE

    def force_idle(self) -> None:
        """Força transição para ``IDLE`` a partir de ``COMMITTED`` ou ``FAILED``.

        Helper para o orchestrator ao final do ``run()``: permite reaproveitar
        a instância em runs subsequentes (não usado em V1 mas útil para
        testes que validam ciclo completo).

        Raises:
            InvalidStateTransition: Se estado atual não é ``COMMITTED`` nem
                ``FAILED``.
        """
        if self._state not in (JobState.COMMITTED, JobState.FAILED):
            raise InvalidStateTransition(self._state, JobState.IDLE)
        self.transition(JobState.IDLE)
