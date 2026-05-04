"""Unit tests — orchestrator.retry_policy (Story 2.6 AC2 / AC7).

Cobertura:
- TRANSIENT retry respeita ``max_attempts_transient`` + backoff exponencial.
- PERMANENT/UNKNOWN: fail-fast (re-raise sem retry).
- AMBIGUOUS retry com cap menor.
- ``classify_exception`` lê ``nl_code`` attr quando presente.
- ``next_delay`` aplica jitter dentro dos limites e respeita ``max_delay``.
- ``policy_from_env`` lê env vars + fallback silencioso em valores inválidos.
- KeyboardInterrupt / SystemExit nunca retried.
- backwards compat: ``with_retry`` aceita ``policy=`` e delega.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from data_downloader.dll.error_taxonomy import ErrorCategory
from data_downloader.orchestrator.retry import with_retry
from data_downloader.orchestrator.retry_policy import (
    DEFAULT_AMBIGUOUS_MAX_ATTEMPTS,
    DEFAULT_FACTOR,
    DEFAULT_JITTER,
    DEFAULT_MAX_DELAY,
    DEFAULT_TRANSIENT_BASE_DELAY,
    DEFAULT_TRANSIENT_MAX_ATTEMPTS,
    RetryPolicy,
    default_retry_policy,
    policy_from_env,
)


def _make_nl_exc(code: int, msg: str = "nl error") -> OSError:
    """Helper — cria OSError com ``nl_code`` (mimica orchestrator)."""
    exc = OSError(msg)
    exc.nl_code = code  # type: ignore[attr-defined]
    return exc


# =====================================================================
# Defaults sanity
# =====================================================================


@pytest.mark.unit
def test_default_retry_policy_attributes() -> None:
    policy = default_retry_policy()
    assert policy.max_attempts_transient == DEFAULT_TRANSIENT_MAX_ATTEMPTS == 5
    assert policy.max_attempts_ambiguous == DEFAULT_AMBIGUOUS_MAX_ATTEMPTS == 3
    assert policy.base_delay_transient == DEFAULT_TRANSIENT_BASE_DELAY == 30.0
    assert policy.factor == DEFAULT_FACTOR == 2.0
    assert policy.max_delay == DEFAULT_MAX_DELAY == 600.0
    assert policy.jitter == DEFAULT_JITTER == 0.2


@pytest.mark.unit
def test_default_retryable_categories_contains_transient_and_ambiguous() -> None:
    policy = default_retry_policy()
    assert ErrorCategory.TRANSIENT in policy.retryable_categories
    assert ErrorCategory.AMBIGUOUS in policy.retryable_categories
    assert ErrorCategory.PERMANENT not in policy.retryable_categories
    assert ErrorCategory.UNKNOWN not in policy.retryable_categories


# =====================================================================
# classify_exception
# =====================================================================


@pytest.mark.unit
def test_classify_exception_uses_nl_code_when_present() -> None:
    policy = default_retry_policy()
    transient = _make_nl_exc(-2147483647)  # NL_INTERNAL_ERROR
    permanent = _make_nl_exc(-2147483617)  # NL_INVALID_TICKER
    ambiguous = _make_nl_exc(-2147483636)  # NL_NOT_FOUND

    assert policy.classify_exception(transient) is ErrorCategory.TRANSIENT
    assert policy.classify_exception(permanent) is ErrorCategory.PERMANENT
    assert policy.classify_exception(ambiguous) is ErrorCategory.AMBIGUOUS


@pytest.mark.unit
def test_classify_exception_oserror_without_nl_code_is_transient() -> None:
    """Backwards compat Story 1.7a — OSError sem nl_code é transient."""
    policy = default_retry_policy()
    assert policy.classify_exception(OSError("net")) is ErrorCategory.TRANSIENT
    assert policy.classify_exception(TimeoutError()) is ErrorCategory.TRANSIENT


@pytest.mark.unit
def test_classify_exception_value_error_is_permanent() -> None:
    """ValueError não está em retryable_exception_types → PERMANENT (fail fast)."""
    policy = default_retry_policy()
    assert policy.classify_exception(ValueError("bad")) is ErrorCategory.PERMANENT
    assert policy.classify_exception(KeyError("missing")) is ErrorCategory.PERMANENT


# =====================================================================
# should_retry
# =====================================================================


@pytest.mark.unit
def test_should_retry_transient_within_max() -> None:
    policy = default_retry_policy()
    exc = _make_nl_exc(-2147483647)
    # attempt 1..(max-1): True; attempt == max: False
    for attempt in range(1, policy.max_attempts_transient):
        assert policy.should_retry(exc, attempt) is True
    assert policy.should_retry(exc, policy.max_attempts_transient) is False


@pytest.mark.unit
def test_should_retry_permanent_never() -> None:
    policy = default_retry_policy()
    exc = _make_nl_exc(-2147483617)  # NL_INVALID_TICKER
    assert policy.should_retry(exc, 1) is False
    assert policy.should_retry(exc, 0) is False


@pytest.mark.unit
def test_should_retry_keyboard_interrupt_never() -> None:
    policy = default_retry_policy()
    assert policy.should_retry(KeyboardInterrupt(), 1) is False
    assert policy.should_retry(SystemExit(), 1) is False


# =====================================================================
# next_delay (backoff + jitter + max_delay)
# =====================================================================


@pytest.mark.unit
def test_next_delay_exponential_no_jitter() -> None:
    """jitter=0 → delay exato base * factor^(attempt-1)."""
    policy = RetryPolicy(
        base_delay_transient=10.0,
        factor=2.0,
        max_delay=10_000.0,
        jitter=0.0,
    )
    # attempt 1 → 10 * 2^0 = 10
    assert policy.next_delay(1, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 10.0
    # attempt 2 → 10 * 2^1 = 20
    assert policy.next_delay(2, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 20.0
    # attempt 3 → 10 * 2^2 = 40
    assert policy.next_delay(3, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 40.0


@pytest.mark.unit
def test_next_delay_capped_by_max_delay() -> None:
    policy = RetryPolicy(
        base_delay_transient=100.0,
        factor=10.0,
        max_delay=300.0,
        jitter=0.0,
    )
    # attempt 1 → 100 (≤ cap), attempt 2 → 1000 → capped at 300
    assert policy.next_delay(1, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 100.0
    assert policy.next_delay(2, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 300.0
    assert policy.next_delay(5, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 300.0


@pytest.mark.unit
def test_next_delay_with_jitter_in_bounds() -> None:
    policy = RetryPolicy(
        base_delay_transient=10.0,
        factor=2.0,
        max_delay=10_000.0,
        jitter=0.2,
    )
    # random=0.0 → jitter_signed = -0.2 → delay = 10 * 0.8 = 8.0
    assert policy.next_delay(1, ErrorCategory.TRANSIENT, random_fn=lambda: 0.0) == pytest.approx(
        8.0
    )
    # random=1.0 → jitter_signed = +0.2 → delay = 10 * 1.2 = 12.0
    assert policy.next_delay(1, ErrorCategory.TRANSIENT, random_fn=lambda: 1.0) == pytest.approx(
        12.0
    )


@pytest.mark.unit
def test_next_delay_attempt_zero_raises() -> None:
    policy = default_retry_policy()
    with pytest.raises(ValueError, match="attempt"):
        policy.next_delay(0, ErrorCategory.TRANSIENT)


@pytest.mark.unit
def test_next_delay_uses_correct_base_per_category() -> None:
    policy = RetryPolicy(
        base_delay_transient=10.0,
        base_delay_ambiguous=100.0,
        factor=1.0,
        max_delay=10_000.0,
        jitter=0.0,
    )
    assert policy.next_delay(1, ErrorCategory.TRANSIENT, random_fn=lambda: 0.5) == 10.0
    assert policy.next_delay(1, ErrorCategory.AMBIGUOUS, random_fn=lambda: 0.5) == 100.0
    # PERMANENT/UNKNOWN: base=0 (fail fast) — não deveria ser chamado mas defensivo
    assert policy.next_delay(1, ErrorCategory.PERMANENT, random_fn=lambda: 0.5) == 0.0


# =====================================================================
# __call__ — execução end-to-end
# =====================================================================


@pytest.mark.unit
def test_call_success_first_attempt() -> None:
    policy = default_retry_policy()
    sleeps: list[float] = []
    result = policy(lambda: 42, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    assert result == 42
    assert sleeps == []


@pytest.mark.unit
def test_call_transient_retry_then_success() -> None:
    """TRANSIENT falha 1x, depois sucesso → 1 sleep, retorna."""
    policy = RetryPolicy(
        max_attempts_transient=3,
        base_delay_transient=1.0,
        factor=1.0,
        jitter=0.0,
    )
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _make_nl_exc(-2147483647)  # NL_INTERNAL_ERROR
        return "ok"

    result = policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    assert result == "ok"
    assert calls["n"] == 2
    assert sleeps == [1.0]


@pytest.mark.unit
def test_call_transient_exhausted_reraises_last() -> None:
    """TRANSIENT falha em todas as max → re-raise última exception (NÃO RetryError)."""
    policy = RetryPolicy(
        max_attempts_transient=3,
        base_delay_transient=1.0,
        factor=1.0,
        jitter=0.0,
    )
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(-2147483647, f"attempt-{calls['n']}")

    with pytest.raises(OSError, match="attempt-3"):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    assert calls["n"] == 3
    # 2 sleeps entre as 3 tentativas
    assert len(sleeps) == 2


@pytest.mark.unit
def test_call_permanent_fails_fast() -> None:
    """PERMANENT (NL_INVALID_TICKER) → 0 retries, re-raise direto (R7)."""
    policy = default_retry_policy()
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(-2147483617)  # NL_INVALID_TICKER

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    assert calls["n"] == 1
    assert sleeps == []


@pytest.mark.unit
def test_call_unknown_fails_fast() -> None:
    """UNKNOWN code → 0 retries (R7 conservadora)."""
    policy = default_retry_policy()
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(99999)  # UNKNOWN

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append)
    assert calls["n"] == 1
    assert sleeps == []


@pytest.mark.unit
def test_call_ambiguous_uses_ambiguous_max() -> None:
    """AMBIGUOUS retry mas com cap menor que TRANSIENT."""
    policy = RetryPolicy(
        max_attempts_transient=10,
        max_attempts_ambiguous=2,
        base_delay_ambiguous=1.0,
        factor=1.0,
        jitter=0.0,
    )
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> None:
        calls["n"] += 1
        raise _make_nl_exc(-2147483636)  # NL_NOT_FOUND (AMBIGUOUS)

    with pytest.raises(OSError):
        policy(_fn, sleep_fn=sleeps.append, random_fn=lambda: 0.5)
    # max_attempts_ambiguous=2: 2 tentativas, 1 sleep
    assert calls["n"] == 2
    assert len(sleeps) == 1


@pytest.mark.unit
def test_call_keyboard_interrupt_propagates_immediately() -> None:
    policy = default_retry_policy()
    sleeps: list[float] = []
    with pytest.raises(KeyboardInterrupt):
        policy(
            lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
            sleep_fn=sleeps.append,
        )
    assert sleeps == []


@pytest.mark.unit
def test_call_value_error_propagates_immediately() -> None:
    """ValueError → PERMANENT → fail-fast (não em retryable_exception_types)."""
    policy = default_retry_policy()
    sleeps: list[float] = []
    with pytest.raises(ValueError):
        policy(
            lambda: (_ for _ in ()).throw(ValueError("bug")),
            sleep_fn=sleeps.append,
        )
    assert sleeps == []


@pytest.mark.unit
def test_with_retry_delegates_to_policy_when_passed() -> None:
    """``with_retry(fn, policy=...)`` delega tudo para a policy (Story 2.6)."""
    policy = RetryPolicy(
        max_attempts_transient=2,
        base_delay_transient=1.0,
        factor=1.0,
        jitter=0.0,
    )
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _make_nl_exc(-2147483647)
        return "ok"

    result = with_retry(
        _fn,
        policy=policy,
        sleep_fn=sleeps.append,
        random_fn=lambda: 0.5,
    )
    assert result == "ok"
    assert calls["n"] == 2
    assert len(sleeps) == 1


# =====================================================================
# policy_from_env
# =====================================================================


@pytest.mark.unit
def test_policy_from_env_no_overrides_returns_defaults() -> None:
    """Sem env vars → policy == default_retry_policy."""
    with patch.dict(os.environ, {}, clear=False):
        # Limpa qualquer env relacionada
        for k in list(os.environ.keys()):
            if k.startswith("DATA_DOWNLOADER_RETRY_"):
                del os.environ[k]
        policy = policy_from_env()
        assert policy == default_retry_policy()


@pytest.mark.unit
def test_policy_from_env_overrides_max_attempts() -> None:
    with patch.dict(
        os.environ,
        {
            "DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT": "10",
            "DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_AMBIGUOUS": "2",
            "DATA_DOWNLOADER_RETRY_FACTOR": "3.0",
            "DATA_DOWNLOADER_RETRY_JITTER": "0.0",
        },
    ):
        policy = policy_from_env()
        assert policy.max_attempts_transient == 10
        assert policy.max_attempts_ambiguous == 2
        assert policy.factor == 3.0
        assert policy.jitter == 0.0


@pytest.mark.unit
def test_policy_from_env_invalid_value_falls_back_to_default() -> None:
    """Env vars malformadas → fallback silencioso (best-effort)."""
    with patch.dict(
        os.environ,
        {
            "DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT": "not-an-int",
            "DATA_DOWNLOADER_RETRY_FACTOR": "abc",
            "DATA_DOWNLOADER_RETRY_JITTER": "0.5",  # válido
        },
    ):
        policy = policy_from_env()
        assert policy.max_attempts_transient == DEFAULT_TRANSIENT_MAX_ATTEMPTS
        assert policy.factor == DEFAULT_FACTOR
        assert policy.jitter == 0.5


@pytest.mark.unit
def test_policy_from_env_negative_value_falls_back() -> None:
    """Valores negativos / zero (onde proibido) caem no default."""
    with patch.dict(
        os.environ,
        {
            "DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT": "-1",
            "DATA_DOWNLOADER_RETRY_BASE_DELAY_SECONDS": "0",
        },
    ):
        policy = policy_from_env()
        assert policy.max_attempts_transient == DEFAULT_TRANSIENT_MAX_ATTEMPTS
        assert policy.base_delay_transient == DEFAULT_TRANSIENT_BASE_DELAY
