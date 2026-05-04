"""Property tests — RetryPolicy + CircuitBreaker invariantes (Story 2.6 AC7).

Hypothesis-based testing — gera sequências aleatórias de eventos
(success/failure/category) para validar invariantes do retry+breaker que
seriam impossíveis de cobrir exaustivamente com unit tests.

Invariantes verificados:

1. **Retry NUNCA excede max_attempts x max_delay total**:
   - Para qualquer policy + sequência arbitrária, número total de attempts
     ≤ max(max_attempts_transient, max_attempts_ambiguous).
   - Soma total dos sleeps ≤ max_attempts x max_delay (cap superior).

2. **CircuitBreaker abre se e somente se TRANSIENT count ≥ threshold em janela**:
   - Sequência aleatória de record_failure → state OPEN se número de
     falhas em janela W ≥ threshold; nunca OPEN de outra forma.

3. **fail-fast em PERMANENT**:
   - Para qualquer NL_PERMANENT, attempts == 1 (sem retry).

4. **Determinismo de delay**:
   - Mesma policy + mesmo random_fn → mesmo delay calculado.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.dll.error_taxonomy import ErrorCategory
from data_downloader.orchestrator.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
)
from data_downloader.orchestrator.retry_policy import RetryPolicy

# =====================================================================
# Strategies
# =====================================================================


@st.composite
def _retry_policies(draw: st.DrawFn) -> RetryPolicy:
    """Gera RetryPolicy com defaults razoáveis."""
    return RetryPolicy(
        max_attempts_transient=draw(st.integers(min_value=1, max_value=10)),
        max_attempts_ambiguous=draw(st.integers(min_value=1, max_value=5)),
        base_delay_transient=draw(st.floats(min_value=0.0, max_value=10.0)),
        base_delay_ambiguous=draw(st.floats(min_value=0.0, max_value=10.0)),
        factor=draw(st.floats(min_value=1.0, max_value=5.0)),
        max_delay=draw(st.floats(min_value=10.0, max_value=1000.0)),
        jitter=draw(st.floats(min_value=0.0, max_value=0.5)),
    )


@st.composite
def _failure_sequences(draw: st.DrawFn) -> tuple[int, int, list[float]]:
    """Gera (threshold, window, failures_timestamps_in_seconds)."""
    threshold = draw(st.integers(min_value=2, max_value=20))
    window = draw(st.integers(min_value=10, max_value=300))
    n_failures = draw(st.integers(min_value=0, max_value=threshold * 3))
    # timestamps monotônicos crescentes
    timestamps = sorted(
        draw(
            st.lists(
                st.floats(min_value=0.0, max_value=window * 5.0),
                min_size=n_failures,
                max_size=n_failures,
            )
        )
    )
    return threshold, window, timestamps


def _make_nl_exc(code: int) -> OSError:
    exc = OSError("nl error")
    exc.nl_code = code  # type: ignore[attr-defined]
    return exc


# =====================================================================
# Property 1 — Retry NUNCA excede max_attempts
# =====================================================================


@pytest.mark.property
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(policy=_retry_policies())
def test_retry_never_exceeds_max_attempts_transient(policy: RetryPolicy) -> None:
    """Para qualquer policy + erro TRANSIENT contínuo, attempts <= max_transient."""
    sleeps: list[float] = []
    calls = {"n": 0}
    nl_code = -2147483647  # NL_INTERNAL_ERROR (TRANSIENT)

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(nl_code)

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    # Invariante: número de attempts <= max_attempts_transient
    assert calls["n"] <= policy.max_attempts_transient
    # Sleeps são (attempts - 1)
    assert len(sleeps) == calls["n"] - 1


@pytest.mark.property
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(policy=_retry_policies())
def test_retry_never_exceeds_max_attempts_ambiguous(policy: RetryPolicy) -> None:
    """AMBIGUOUS contínuo: attempts <= max_attempts_ambiguous."""
    sleeps: list[float] = []
    calls = {"n": 0}
    nl_code = -2147483636  # NL_NOT_FOUND (AMBIGUOUS)

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(nl_code)

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    assert calls["n"] <= policy.max_attempts_ambiguous


@pytest.mark.property
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(policy=_retry_policies())
def test_retry_total_sleep_bounded_by_max_attempts_times_max_delay(
    policy: RetryPolicy,
) -> None:
    """Soma total de sleeps <= max_attempts * max_delay (cap superior)."""
    sleeps: list[float] = []
    nl_code = -2147483647  # TRANSIENT

    def _fn() -> None:
        raise _make_nl_exc(nl_code)

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)

    total_sleep = sum(sleeps)
    upper_bound = policy.max_attempts_transient * policy.max_delay
    assert total_sleep <= upper_bound


# =====================================================================
# Property 2 — fail-fast em PERMANENT/UNKNOWN
# =====================================================================


@pytest.mark.property
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    policy=_retry_policies(),
    nl_code=st.sampled_from(
        [
            -2147483646,  # NL_NOT_INITIALIZED
            -2147483645,  # NL_INVALID_ARGS
            -2147483617,  # NL_INVALID_TICKER
            -2147483643,  # NL_NO_LOGIN
            -2147483642,  # NL_NO_LICENSE
            99999,  # UNKNOWN
        ]
    ),
)
def test_permanent_or_unknown_fails_fast(policy: RetryPolicy, nl_code: int) -> None:
    """PERMANENT/UNKNOWN → exatamente 1 attempt, 0 sleeps (R7 fail fast)."""
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(nl_code)

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    assert calls["n"] == 1
    assert sleeps == []


# =====================================================================
# Property 3 — Determinismo de next_delay
# =====================================================================


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    policy=_retry_policies(),
    attempt=st.integers(min_value=1, max_value=10),
    rand=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
def test_next_delay_is_deterministic_with_fixed_random(
    policy: RetryPolicy,
    attempt: int,
    rand: float,
) -> None:
    """Mesma policy + mesmo random_fn → mesmo delay (idempotência)."""
    d1 = policy.next_delay(attempt, ErrorCategory.TRANSIENT, random_fn=lambda: rand)
    d2 = policy.next_delay(attempt, ErrorCategory.TRANSIENT, random_fn=lambda: rand)
    assert d1 == d2
    # E sempre <= max_delay * (1 + jitter)
    assert d1 <= policy.max_delay * (1.0 + policy.jitter)
    assert d1 >= 0.0


# =====================================================================
# Property 4 — CircuitBreaker abre se e somente se threshold atingido
# =====================================================================


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.mark.property
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    failure_data=_failure_sequences(),
)
def test_breaker_opens_iff_threshold_reached_in_window(
    failure_data: tuple[int, int, list[float]],
) -> None:
    """Invariante: state == OPEN sse falhas em janela ≥ threshold.

    Rigorosamente: simula cada falha em sequência. Após cada uma, verifica
    se já era esperado abrir (count em janela ≥ threshold). Se sim e o
    breaker NÃO abriu até esse ponto, falha. Se não e o breaker abriu, falha.
    """
    threshold, window, timestamps = failure_data
    clock = _FakeClock()
    cb = CircuitBreaker(
        symbol="X",
        exchange="F",
        failure_threshold=threshold,
        window_seconds=float(window),
        cooldown_seconds=10_000.0,  # cooldown enorme — não testamos transição OPEN→HALF_OPEN aqui
        clock_fn=clock,
    )

    for i, ts in enumerate(timestamps):
        clock.t = ts
        cb.record_failure()

        # Calcula falhas dentro da janela [ts - window, ts] — usando APENAS
        # timestamps já registrados (até e incluindo o atual)
        cutoff = ts - window
        recorded_so_far = timestamps[: i + 1]
        in_window = sum(1 for t in recorded_so_far if cutoff <= t <= ts)
        # Se acumulou >= threshold em janela, deve estar OPEN
        if in_window >= threshold:
            assert cb.state is BreakerState.OPEN, (
                f"Expected OPEN at step {i} (in_window={in_window} >= threshold={threshold}); "
                f"got {cb.state}"
            )
            return  # invariante satisfeito; não precisamos continuar
    # Se chegamos aqui, nenhuma janela atingiu threshold → breaker NÃO deve estar OPEN
    assert cb.state is BreakerState.CLOSED


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    threshold=st.integers(min_value=2, max_value=10),
)
def test_breaker_zero_failures_always_closed(threshold: int) -> None:
    """Invariante trivial: 0 falhas → CLOSED."""
    cb = CircuitBreaker(
        symbol="X",
        exchange="F",
        failure_threshold=threshold,
        window_seconds=60.0,
        cooldown_seconds=120.0,
    )
    assert cb.state is BreakerState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    threshold=st.integers(min_value=1, max_value=20),
    n_calls=st.integers(min_value=1, max_value=50),
)
def test_breaker_record_success_keeps_closed_in_clean_path(
    threshold: int,
    n_calls: int,
) -> None:
    """Sucessos contínuos NUNCA abrem o breaker."""
    cb = CircuitBreaker(
        symbol="X",
        exchange="F",
        failure_threshold=threshold,
        window_seconds=60.0,
        cooldown_seconds=120.0,
    )
    for _ in range(n_calls):
        cb.record_success()
    assert cb.state is BreakerState.CLOSED
