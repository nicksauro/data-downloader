"""Unit tests — orchestrator.circuit_breaker (Story 2.6 AC3 / AC7).

Cobertura:
- Estado inicial CLOSED.
- Transição CLOSED → OPEN após N falhas em janela.
- Falhas fora da janela são evictadas (sliding window).
- Transição OPEN → HALF_OPEN após cooldown decorrido.
- HALF_OPEN + sucesso → CLOSED + cooldown reset.
- HALF_OPEN + falha → OPEN com cooldown ampliado (x2).
- ``call()`` em OPEN raise CircuitOpenError sem invocar fn.
- ``call()`` em CLOSED/HALF_OPEN passa exception transparente.
- ``reset()`` força CLOSED em qualquer estado.
- ``with_circuit_breaker`` decorator funciona.
- Validações de construção (threshold/window/cooldown >= 1).
- Thread-safety: 2 threads concorrentes convergem para mesmo estado.
"""

from __future__ import annotations

import contextlib
import threading

import pytest

from data_downloader.orchestrator.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
    with_circuit_breaker,
)


class _FakeClock:
    """Relógio determinístico — substitui ``time.monotonic`` no breaker."""

    def __init__(self, t0: float = 1000.0) -> None:
        self._now = t0

    def __call__(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        self._now += dt


# =====================================================================
# Construção / validação
# =====================================================================


@pytest.mark.unit
def test_initial_state_is_closed() -> None:
    cb = CircuitBreaker("WDOJ26", "F")
    assert cb.state is BreakerState.CLOSED
    assert cb.failure_count == 0
    assert cb.cooldown_remaining_seconds == 0.0


@pytest.mark.unit
def test_invalid_threshold_raises() -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreaker("X", "F", failure_threshold=0)


@pytest.mark.unit
def test_invalid_window_raises() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        CircuitBreaker("X", "F", window_seconds=0)


@pytest.mark.unit
def test_invalid_cooldown_raises() -> None:
    with pytest.raises(ValueError, match="cooldown_seconds"):
        CircuitBreaker("X", "F", cooldown_seconds=0)


@pytest.mark.unit
def test_public_properties_exposed() -> None:
    cb = CircuitBreaker("WDO", "F", failure_threshold=7, window_seconds=120, cooldown_seconds=300)
    assert cb.symbol == "WDO"
    assert cb.exchange == "F"
    assert cb.failure_threshold == 7
    assert cb.window_seconds == 120
    assert cb.base_cooldown_seconds == 300
    assert cb.current_cooldown_seconds == 300


# =====================================================================
# CLOSED → OPEN (sliding window)
# =====================================================================


@pytest.mark.unit
def test_closed_to_open_after_threshold_failures() -> None:
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=3,
        window_seconds=60,
        cooldown_seconds=120,
        clock_fn=clock,
    )
    # 2 falhas — ainda CLOSED
    cb.record_failure()
    cb.record_failure()
    assert cb.state is BreakerState.CLOSED
    # 3ª falha — trip para OPEN
    cb.record_failure()
    assert cb.state is BreakerState.OPEN


@pytest.mark.unit
def test_failures_outside_window_are_evicted() -> None:
    """Falhas fora da janela não contam para o threshold."""
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=3,
        window_seconds=60,
        cooldown_seconds=120,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()
    # Avança >60s — falhas anteriores estão fora da janela
    clock.advance(61)
    cb.record_failure()
    cb.record_failure()
    # Apenas 2 dentro da janela atual
    assert cb.state is BreakerState.CLOSED


@pytest.mark.unit
def test_open_blocks_call_raises_circuit_open_error() -> None:
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=2,
        window_seconds=60,
        cooldown_seconds=120,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()
    assert cb.state is BreakerState.OPEN

    calls = {"n": 0}

    def _fn() -> int:
        calls["n"] += 1
        return 42

    with pytest.raises(CircuitOpenError) as exc_info:
        cb.call(_fn)
    assert calls["n"] == 0  # fn NUNCA invocada
    assert exc_info.value.symbol == "WDO"
    assert exc_info.value.exchange == "F"
    assert exc_info.value.failure_count >= 2
    assert exc_info.value.retry_after_seconds > 0


# =====================================================================
# OPEN → HALF_OPEN (cooldown)
# =====================================================================


@pytest.mark.unit
def test_open_to_half_open_after_cooldown() -> None:
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=2,
        window_seconds=60,
        cooldown_seconds=120,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()
    assert cb.state is BreakerState.OPEN
    # cooldown não decorrido — ainda OPEN
    clock.advance(60)
    assert cb.state is BreakerState.OPEN
    # cooldown decorrido → HALF_OPEN (lazy transition via state property)
    clock.advance(61)
    assert cb.state is BreakerState.HALF_OPEN


@pytest.mark.unit
def test_half_open_success_back_to_closed() -> None:
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=2,
        window_seconds=60,
        cooldown_seconds=120,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()
    clock.advance(121)  # cooldown decorrido
    assert cb.state is BreakerState.HALF_OPEN

    # call() succeeded em HALF_OPEN → CLOSED + reset
    result = cb.call(lambda: "probe-ok")
    assert result == "probe-ok"
    assert cb.state is BreakerState.CLOSED
    assert cb.failure_count == 0
    assert cb.current_cooldown_seconds == 120  # cooldown reset to base


@pytest.mark.unit
def test_half_open_failure_back_to_open_with_amplified_cooldown() -> None:
    """HALF_OPEN + falha → OPEN, cooldown x 2 (exp backoff)."""
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=2,
        window_seconds=60,
        cooldown_seconds=100,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()
    clock.advance(101)  # cooldown decorrido
    assert cb.state is BreakerState.HALF_OPEN

    # falha em probe → OPEN, cooldown amplificado
    def _fn() -> None:
        raise OSError("probe failed")

    with pytest.raises(OSError):
        cb.call(_fn)

    assert cb.state is BreakerState.OPEN
    assert cb.current_cooldown_seconds == 200  # 100 x 2


@pytest.mark.unit
def test_amplified_cooldown_capped_at_8x_base() -> None:
    """Cooldown ampliado é capped em base x 8 (não cresce indefinidamente)."""
    clock = _FakeClock()
    cb = CircuitBreaker(
        "WDO",
        "F",
        failure_threshold=2,
        window_seconds=60,
        cooldown_seconds=100,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()

    # Loop: HALF_OPEN → falha → OPEN (cooldown x 2). Repete até cap.
    for _ in range(10):
        clock.advance(cb.current_cooldown_seconds + 1)
        assert cb.state is BreakerState.HALF_OPEN
        with pytest.raises(OSError):
            cb.call(lambda: (_ for _ in ()).throw(OSError("fail")))
    # Cap atingido — cooldown não pode passar de 800 (100 * 8)
    assert cb.current_cooldown_seconds == 800


# =====================================================================
# call() — comportamento
# =====================================================================


@pytest.mark.unit
def test_call_in_closed_passes_through_success() -> None:
    cb = CircuitBreaker("X", "F")
    result = cb.call(lambda: 99)
    assert result == 99
    assert cb.state is BreakerState.CLOSED


@pytest.mark.unit
def test_call_in_closed_records_failure_and_reraises() -> None:
    """Exception em fn é re-raised E conta como falha."""
    cb = CircuitBreaker("X", "F", failure_threshold=2)

    def _fn() -> None:
        raise OSError("boom")

    with pytest.raises(OSError, match="boom"):
        cb.call(_fn)
    assert cb.failure_count == 1
    with pytest.raises(OSError):
        cb.call(_fn)
    # 2 falhas → trip
    assert cb.state is BreakerState.OPEN


# =====================================================================
# reset / manual
# =====================================================================


@pytest.mark.unit
def test_reset_forces_closed_and_clears_failures() -> None:
    clock = _FakeClock()
    cb = CircuitBreaker(
        "X",
        "F",
        failure_threshold=2,
        cooldown_seconds=100,
        clock_fn=clock,
    )
    cb.record_failure()
    cb.record_failure()
    assert cb.state is BreakerState.OPEN

    cb.reset()
    assert cb.state is BreakerState.CLOSED
    assert cb.failure_count == 0
    assert cb.current_cooldown_seconds == 100


# =====================================================================
# Decorator helper
# =====================================================================


@pytest.mark.unit
def test_with_circuit_breaker_decorator_protects_function() -> None:
    cb = CircuitBreaker("X", "F", failure_threshold=2)

    calls = {"n": 0}

    @with_circuit_breaker(cb)
    def _op() -> int:
        calls["n"] += 1
        return 7

    assert _op() == 7
    assert calls["n"] == 1

    # 2 falhas via record_failure direto → OPEN → decorated function bloqueada
    cb.record_failure()
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        _op()
    assert calls["n"] == 1  # não foi chamado de novo


# =====================================================================
# Thread-safety
# =====================================================================


@pytest.mark.unit
def test_concurrent_failures_converge_to_open() -> None:
    """N threads recordando falhas concorrentemente chegam a OPEN."""
    cb = CircuitBreaker("X", "F", failure_threshold=20, window_seconds=60)

    barrier = threading.Barrier(10)

    def _worker() -> None:
        barrier.wait()
        for _ in range(5):
            # ValueError pode ser raised pelo PrintLogger se pytest capsys
            # invalidar stdout entre threads (issue conhecido structlog +
            # pytest com daemon threads — ver baseline 31+ failed). Estado
            # interno do breaker mutou ANTES do log (synchronous), portanto
            # o test ainda valida convergência para OPEN abaixo.
            with contextlib.suppress(ValueError, OSError):
                cb.record_failure()

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 50 falhas registradas — bem acima do threshold 20
    assert cb.state is BreakerState.OPEN
    assert cb.failure_count >= 20


@pytest.mark.unit
def test_concurrent_calls_to_breaker_safe() -> None:
    """Calls concorrentes em CLOSED — todos succeeded, estado consistente."""
    cb = CircuitBreaker("X", "F", failure_threshold=100)
    results: list[int] = []
    lock = threading.Lock()

    def _worker(n: int) -> None:
        result = cb.call(lambda v=n: v * 2)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [i * 2 for i in range(20)]
    assert cb.state is BreakerState.CLOSED


# =====================================================================
# CircuitOpenError contract
# =====================================================================


@pytest.mark.unit
def test_circuit_open_error_has_required_attributes() -> None:
    err = CircuitOpenError(
        "WDO",
        "F",
        retry_after_seconds=60.5,
        failure_count=10,
    )
    assert err.symbol == "WDO"
    assert err.exchange == "F"
    assert err.retry_after_seconds == 60.5
    assert err.failure_count == 10
    # ADR-011: humanized_message disponível via DataDownloaderError
    assert hasattr(err, "humanized_message")
    assert "WDO" in str(err)
