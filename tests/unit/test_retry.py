"""Unit tests — orchestrator.retry (Story 1.7a AC2).

Cobertura:

- Sucesso na 1ª tentativa: ``fn`` chamado uma vez, sem sleep.
- Sucesso na 2ª tentativa: 1 sleep, depois retorna.
- Exhaustion: ``RetryError`` com ``attempts == max_attempts``.
- Erros fatais (não em retryable_errors) propagam imediatamente.
- Backoff exponencial: 1s, 4s, 16s para defaults.
- Jitter: delays variam dentro de ±20% do raw.
- max_attempts < 1 levanta ValueError.
"""

from __future__ import annotations

import pytest

from data_downloader.orchestrator.retry import (
    DEFAULT_BASE_DELAY,
    DEFAULT_FACTOR,
    RetryError,
    with_retry,
)


@pytest.mark.unit
def test_success_first_attempt_no_sleep() -> None:
    """fn retorna na 1ª tentativa → 0 sleeps, 0 retries."""
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> int:
        calls["n"] += 1
        return 42

    result = with_retry(_fn, sleep_fn=sleeps.append)
    assert result == 42
    assert calls["n"] == 1
    assert sleeps == []


@pytest.mark.unit
def test_success_second_attempt_one_sleep() -> None:
    """fn falha na 1ª, retorna na 2ª → 1 sleep."""
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return "ok"

    result = with_retry(
        _fn,
        sleep_fn=sleeps.append,
        random_fn=lambda: 0.5,  # determinístico — jitter zerado
    )
    assert result == "ok"
    assert calls["n"] == 2
    assert len(sleeps) == 1


@pytest.mark.unit
def test_retry_exhausted_raises_retry_error() -> None:
    """Todas as tentativas falham → RetryError com last_exception preservado."""
    sleeps: list[float] = []

    def _fn() -> None:
        raise OSError("always-fail")

    with pytest.raises(RetryError) as exc_info:
        with_retry(
            _fn,
            max_attempts=3,
            sleep_fn=sleeps.append,
            random_fn=lambda: 0.5,
        )
    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.last_exception, OSError)
    assert "always-fail" in str(exc_info.value.last_exception)
    # 2 sleeps entre as 3 tentativas.
    assert len(sleeps) == 2


@pytest.mark.unit
def test_fatal_exception_propagates_immediately() -> None:
    """ValueError não está em retryable → re-raise direto, 0 sleeps."""
    sleeps: list[float] = []
    calls = {"n": 0}

    def _fn() -> None:
        calls["n"] += 1
        raise ValueError("fatal")

    with pytest.raises(ValueError, match="fatal"):
        with_retry(_fn, sleep_fn=sleeps.append)
    assert calls["n"] == 1
    assert sleeps == []


@pytest.mark.unit
def test_keyboard_interrupt_propagates_immediately() -> None:
    """KeyboardInterrupt nunca é retried (não em DEFAULT_RETRYABLE)."""
    sleeps: list[float] = []
    with pytest.raises(KeyboardInterrupt):
        with_retry(
            lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
            sleep_fn=sleeps.append,
        )
    assert sleeps == []


@pytest.mark.unit
def test_backoff_exponential_delays_no_jitter() -> None:
    """jitter=0 → delays exatos: 1s, 4s, 16s para defaults."""
    sleeps: list[float] = []

    def _fn() -> None:
        raise OSError("retry me")

    with pytest.raises(RetryError):
        with_retry(
            _fn,
            max_attempts=4,
            base_delay=DEFAULT_BASE_DELAY,
            factor=DEFAULT_FACTOR,
            jitter=0.0,
            sleep_fn=sleeps.append,
            random_fn=lambda: 0.5,  # jitter=0 zera mesmo
        )
    # Delays para attempts 1, 2, 3 (sleep ANTES do attempt 2, 3, 4).
    assert sleeps == [1.0, 4.0, 16.0]


@pytest.mark.unit
def test_backoff_with_jitter_in_bounds() -> None:
    """jitter=0.2 → cada delay ∈ [raw * 0.8, raw * 1.2)."""
    sleeps: list[float] = []

    def _fn() -> None:
        raise OSError("x")

    # random_fn determinístico:
    # attempt 1 → random=0.0 → jitter_signed = -0.2 → delay = 1.0 * 0.8 = 0.8
    # attempt 2 → random=1.0 → jitter_signed = +0.2 → delay = 4.0 * 1.2 = 4.8
    randoms = iter([0.0, 1.0])
    with pytest.raises(RetryError):
        with_retry(
            _fn,
            max_attempts=3,
            base_delay=1.0,
            factor=4.0,
            jitter=0.2,
            sleep_fn=sleeps.append,
            random_fn=lambda: next(randoms),
        )
    assert sleeps[0] == pytest.approx(0.8, rel=1e-9)
    assert sleeps[1] == pytest.approx(4.8, rel=1e-9)


@pytest.mark.unit
def test_max_attempts_one_no_sleep() -> None:
    """max_attempts=1: 1 tentativa, 0 sleeps, RetryError ou success."""
    sleeps: list[float] = []
    with pytest.raises(RetryError):
        with_retry(
            lambda: (_ for _ in ()).throw(OSError("x")),
            max_attempts=1,
            sleep_fn=sleeps.append,
        )
    assert sleeps == []


@pytest.mark.unit
def test_max_attempts_zero_raises_value_error() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        with_retry(lambda: 1, max_attempts=0)


@pytest.mark.unit
def test_custom_retryable_errors() -> None:
    """Caller pode estender retryable — KeyError vira retryable."""
    calls = {"n": 0}

    def _fn() -> int:
        calls["n"] += 1
        if calls["n"] < 2:
            raise KeyError("missing")
        return 7

    result = with_retry(
        _fn,
        retryable_errors=(KeyError,),
        sleep_fn=lambda _: None,
        random_fn=lambda: 0.5,
    )
    assert result == 7
    assert calls["n"] == 2


@pytest.mark.unit
def test_timeout_error_is_retryable_default() -> None:
    """TimeoutError ∈ DEFAULT_RETRYABLE."""
    calls = {"n": 0}

    def _fn() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError()
        return "ok"

    result = with_retry(
        _fn,
        sleep_fn=lambda _: None,
        random_fn=lambda: 0.5,
    )
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.unit
def test_op_name_in_logs_does_not_affect_behavior() -> None:
    """op_name é só rotulagem — não muda fluxo."""
    result = with_retry(lambda: "x", op_name="my_op")
    assert result == "x"
