"""data_downloader.orchestrator.retry — Retry com exponential backoff (Story 1.7a AC2).

Owner: Dex (impl) | Consult: Aria (política — COUNCIL-05 §D5).

Decorator/wrapper :func:`with_retry` para operações idempotentes que podem
falhar por causa transiente (rede, timeout DLL). Política V1 (COUNCIL-05):

- ``max_attempts = 3``
- Backoff exponencial: ``base_delay * (factor ** (attempt - 1))``
  → defaults: 1s, 4s, 16s.
- Jitter uniforme ±20% (evita thundering herd em multi-chunk).
- Retryable: ``OSError``, ``TimeoutError`` (V1 — distinção por tipo de
  exception). Caller pode estender via ``retryable_errors``.
- Fatal (no retry): ``ValueError``, ``KeyboardInterrupt``, ``SystemExit``,
  e tudo fora de ``retryable_errors``.

LEIS RESPEITADAS:
- R21 (cool path): logger emite 1 evento por tentativa, < 1/s típico.
- Determinístico para testes: ``sleep_fn`` injetável (default
  :func:`time.sleep`); ``random_fn`` injetável (default
  :func:`random.random`).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

import structlog

__all__ = [
    "DEFAULT_BASE_DELAY",
    "DEFAULT_FACTOR",
    "DEFAULT_JITTER",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRYABLE",
    "RetryError",
    "with_retry",
]


T = TypeVar("T")

log: structlog.stdlib.BoundLogger = structlog.get_logger("data_downloader.orchestrator.retry")


DEFAULT_MAX_ATTEMPTS: int = 3
"""3 tentativas total (1 inicial + 2 retries) — COUNCIL-05 §D5."""

DEFAULT_BASE_DELAY: float = 1.0
"""Delay base em segundos (1s) — multiplicado por ``factor`` por tentativa."""

DEFAULT_FACTOR: float = 4.0
"""Fator multiplicativo: 1s, 4s, 16s — COUNCIL-05 §D5."""

DEFAULT_JITTER: float = 0.2
"""Jitter ±20% (uniforme) sobre o delay calculado."""

DEFAULT_RETRYABLE: tuple[type[BaseException], ...] = (OSError, TimeoutError)
"""Exceptions consideradas transientes (retry) por default. Caller pode
estender — ``KeyboardInterrupt``/``SystemExit`` NUNCA são retried."""


class RetryError(RuntimeError):
    """Todas as tentativas foram exauridas sem sucesso.

    Attributes:
        attempts: Número total de tentativas realizadas (== max_attempts).
        last_exception: A última exception capturada (para forensics).
    """

    def __init__(self, attempts: int, last_exception: BaseException) -> None:
        super().__init__(
            f"Retry exhausted after {attempts} attempts; last error: {last_exception!r}"
        )
        self.attempts = attempts
        self.last_exception = last_exception


def with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    factor: float = DEFAULT_FACTOR,
    jitter: float = DEFAULT_JITTER,
    retryable_errors: tuple[type[BaseException], ...] = DEFAULT_RETRYABLE,
    sleep_fn: Callable[[float], None] = time.sleep,
    random_fn: Callable[[], float] = random.random,
    op_name: str = "retry",
) -> T:
    """Executa ``fn()`` com retry exponencial em erros transientes.

    Algoritmo:

    1. Tenta ``fn()``. Se sucesso, retorna o resultado.
    2. Se exceção em ``retryable_errors`` E ``attempt < max_attempts``:
       calcula ``delay = base_delay * (factor ** (attempt - 1))`` com
       jitter ``±jitter``, dorme, re-tenta.
    3. Se exceção fora de ``retryable_errors``: re-raise imediatamente
       (fatal — não retryable).
    4. Se exceção retryable mas ``attempt == max_attempts``: levanta
       :class:`RetryError` envolvendo a última exception.

    Args:
        fn: Callable sem argumentos. Use ``functools.partial`` ou lambda
            para passar args ao callable real.
        max_attempts: Número máximo de tentativas (>= 1). Default 3.
        base_delay: Delay base em segundos antes do 2º attempt.
        factor: Multiplicador exponencial (delay = base * factor**(n-1)).
        jitter: Fração ±jitter aplicada uniformemente sobre o delay.
        retryable_errors: Tupla de classes de exception que disparam retry.
            Default: ``(OSError, TimeoutError)``.
        sleep_fn: Injetável para testes (default :func:`time.sleep`).
        random_fn: Injetável para testes (default :func:`random.random`,
            retorna ``[0.0, 1.0)``).
        op_name: Nome simbólico da operação (apenas para log).

    Returns:
        Resultado de ``fn()`` quando uma tentativa é bem-sucedida.

    Raises:
        RetryError: Todas as ``max_attempts`` falharam com erro retryable.
        Exception: Qualquer erro fatal (não em ``retryable_errors``) é
            re-raised imediatamente.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1; got {max_attempts}")

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retryable_errors as exc:
            last_exc = exc
            if attempt >= max_attempts:
                log.warning(
                    "retry.exhausted",
                    op=op_name,
                    attempts=attempt,
                    error=repr(exc),
                )
                raise RetryError(attempts=attempt, last_exception=exc) from exc

            delay = _compute_delay(
                attempt=attempt,
                base_delay=base_delay,
                factor=factor,
                jitter=jitter,
                random_fn=random_fn,
            )
            log.info(
                "retry.attempt",
                op=op_name,
                attempt=attempt,
                next_attempt_in_seconds=round(delay, 3),
                error=repr(exc),
            )
            sleep_fn(delay)
        # Erros fora de ``retryable_errors`` propagam direto (fatal).

    # Inalcançável — loop sempre retorna ou levanta. Apenas para mypy.
    raise RetryError(  # pragma: no cover
        attempts=max_attempts,
        last_exception=last_exc if last_exc is not None else RuntimeError("unknown"),
    )


def _compute_delay(
    *,
    attempt: int,
    base_delay: float,
    factor: float,
    jitter: float,
    random_fn: Callable[[], float],
) -> float:
    """Calcula delay com backoff exponencial + jitter uniforme.

    ``delay = base_delay * factor**(attempt - 1) * (1 + jitter_signed)``
    onde ``jitter_signed = random()*2*jitter - jitter`` (∈ ``[-jitter, +jitter)``).

    Sempre >= 0 (clamped).
    """
    raw = base_delay * (factor ** (attempt - 1))
    jitter_signed = random_fn() * 2.0 * jitter - jitter
    return max(0.0, raw * (1.0 + jitter_signed))
