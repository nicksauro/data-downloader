"""Unit tests — orchestrator.state_machine (Story 1.7a AC3).

Cobertura:

- Transições válidas conforme :data:`VALID_TRANSITIONS` (ADR-005 amendment).
- Transições inválidas levantam :class:`InvalidStateTransition`.
- Callback ``on_change`` invocado com ``(from, to)``.
- Concorrência: lock serializa transitions concorrentes.
- ``force_idle`` aceita apenas ``COMMITTED``/``FAILED``.
"""

from __future__ import annotations

import threading

import pytest

from data_downloader.orchestrator.state_machine import (
    VALID_TRANSITIONS,
    InvalidStateTransition,
    JobState,
    JobStateMachine,
)


@pytest.mark.unit
def test_initial_state_is_idle() -> None:
    """Estado inicial = IDLE."""
    sm = JobStateMachine(job_id="job-1")
    assert sm.state == JobState.IDLE
    assert sm.is_terminal()


@pytest.mark.unit
def test_happy_path_full_cycle() -> None:
    """IDLE → RUNNING → DRAINING_DLL → DRAINING_WRITE → COMMITTED → IDLE."""
    sm = JobStateMachine(job_id="job-2")
    sm.transition(JobState.RUNNING)
    assert sm.state == JobState.RUNNING
    sm.transition(JobState.DRAINING_DLL)
    sm.transition(JobState.DRAINING_WRITE)
    sm.transition(JobState.COMMITTED)
    sm.transition(JobState.IDLE)
    assert sm.state == JobState.IDLE
    assert sm.is_terminal()


@pytest.mark.unit
def test_failed_path_from_running() -> None:
    """RUNNING → FAILED → IDLE válido."""
    sm = JobStateMachine(job_id="job-3")
    sm.transition(JobState.RUNNING)
    sm.transition(JobState.FAILED)
    assert sm.state == JobState.FAILED
    sm.transition(JobState.IDLE)
    assert sm.state == JobState.IDLE


@pytest.mark.unit
def test_failed_path_from_draining_dll() -> None:
    """DRAINING_DLL → FAILED válido (timeout)."""
    sm = JobStateMachine(job_id="job-4")
    sm.transition(JobState.RUNNING)
    sm.transition(JobState.DRAINING_DLL)
    sm.transition(JobState.FAILED)
    assert sm.state == JobState.FAILED


@pytest.mark.unit
def test_failed_path_from_draining_write() -> None:
    """DRAINING_WRITE → FAILED válido (commit error)."""
    sm = JobStateMachine(job_id="job-5")
    sm.transition(JobState.RUNNING)
    sm.transition(JobState.DRAINING_DLL)
    sm.transition(JobState.DRAINING_WRITE)
    sm.transition(JobState.FAILED)
    assert sm.state == JobState.FAILED


@pytest.mark.unit
def test_invalid_transition_raises() -> None:
    """IDLE → COMMITTED é inválido (skip RUNNING)."""
    sm = JobStateMachine(job_id="job-6")
    with pytest.raises(InvalidStateTransition) as exc:
        sm.transition(JobState.COMMITTED)
    assert exc.value.from_state == JobState.IDLE
    assert exc.value.to_state == JobState.COMMITTED


@pytest.mark.unit
def test_invalid_backward_transition_raises() -> None:
    """RUNNING → IDLE direto é inválido — deve passar por DRAINING+COMMITTED."""
    sm = JobStateMachine(job_id="job-7")
    sm.transition(JobState.RUNNING)
    with pytest.raises(InvalidStateTransition):
        sm.transition(JobState.IDLE)


@pytest.mark.unit
def test_self_transition_is_invalid() -> None:
    """A → A não é listado em VALID_TRANSITIONS — invalida (defensivo)."""
    sm = JobStateMachine(job_id="job-8")
    with pytest.raises(InvalidStateTransition):
        sm.transition(JobState.IDLE)


@pytest.mark.unit
def test_on_change_callback_invoked() -> None:
    """Callback recebe ``(from_state, to_state)`` após transição."""
    events: list[tuple[JobState, JobState]] = []

    def _on_change(from_s: JobState, to_s: JobState) -> None:
        events.append((from_s, to_s))

    sm = JobStateMachine(job_id="job-9", on_change=_on_change)
    sm.transition(JobState.RUNNING)
    sm.transition(JobState.DRAINING_DLL)
    assert events == [
        (JobState.IDLE, JobState.RUNNING),
        (JobState.RUNNING, JobState.DRAINING_DLL),
    ]


@pytest.mark.unit
def test_on_change_not_invoked_on_invalid_transition() -> None:
    """Callback não chamado quando transição é rejeitada."""
    events: list[tuple[JobState, JobState]] = []
    sm = JobStateMachine(
        job_id="job-10",
        on_change=lambda f, t: events.append((f, t)),
    )
    with pytest.raises(InvalidStateTransition):
        sm.transition(JobState.COMMITTED)
    assert events == []


@pytest.mark.unit
def test_force_idle_from_committed() -> None:
    sm = JobStateMachine(job_id="job-11")
    sm.transition(JobState.RUNNING)
    sm.transition(JobState.DRAINING_DLL)
    sm.transition(JobState.DRAINING_WRITE)
    sm.transition(JobState.COMMITTED)
    sm.force_idle()
    assert sm.state == JobState.IDLE


@pytest.mark.unit
def test_force_idle_from_failed() -> None:
    sm = JobStateMachine(job_id="job-12")
    sm.transition(JobState.RUNNING)
    sm.transition(JobState.FAILED)
    sm.force_idle()
    assert sm.state == JobState.IDLE


@pytest.mark.unit
def test_force_idle_invalid_from_running() -> None:
    sm = JobStateMachine(job_id="job-13")
    sm.transition(JobState.RUNNING)
    with pytest.raises(InvalidStateTransition):
        sm.force_idle()


@pytest.mark.unit
def test_concurrent_transitions_serialized() -> None:
    """Lock garante que apenas 1 thread vence transição concorrente.

    Cenário: 10 threads tentam transitar de IDLE para RUNNING. Apenas
    a primeira deve ter sucesso; as demais levantam InvalidStateTransition
    (já em RUNNING quando tentam).
    """
    sm = JobStateMachine(job_id="job-14")
    successes = 0
    failures = 0
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def _worker() -> None:
        nonlocal successes, failures
        barrier.wait()  # Sincroniza todas as 10 antes de tentar.
        try:
            sm.transition(JobState.RUNNING)
            with lock:
                successes += 1
        except InvalidStateTransition:
            with lock:
                failures += 1

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert successes == 1
    assert failures == 9
    assert sm.state == JobState.RUNNING


@pytest.mark.unit
def test_valid_transitions_table_is_consistent() -> None:
    """Todo target em VALID_TRANSITIONS é um JobState válido."""
    for source, targets in VALID_TRANSITIONS.items():
        assert isinstance(source, JobState)
        for t in targets:
            assert isinstance(t, JobState)


@pytest.mark.unit
def test_invalid_state_transition_repr_helpful() -> None:
    """Mensagem de erro inclui from/to + lista de allowed."""
    sm = JobStateMachine(job_id="job-15")
    try:
        sm.transition(JobState.COMMITTED)
    except InvalidStateTransition as exc:
        msg = str(exc)
        assert "IDLE" in msg
        assert "COMMITTED" in msg
        assert "RUNNING" in msg  # listed as allowed from IDLE
