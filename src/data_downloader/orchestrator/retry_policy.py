"""data_downloader.orchestrator.retry_policy — RetryPolicy dataclass + factories.

Owner: Dex (impl) | Audit: Aria (fronteira retry/breaker — COUNCIL-20).
Story 2.6 (Retry inteligente + circuit breaker) — AC2 + AC8.

Encapsula a política de retry em um único objeto imutável que é passado
para :func:`with_retry` (ou usado por :class:`RetryPolicy.__call__` como
decorator). Substitui o conjunto de kwargs ad-hoc do :func:`with_retry`
de Story 1.7a.

Default policy (Story 2.6 AC2):

    TRANSIENT (NL_INTERNAL_ERROR, NL_WAITING_SERVER, OSError, TimeoutError):
        max=5, base=30s, factor exp até cap 600s, jitter ±20%
    AMBIGUOUS (NL_NOT_FOUND, NL_ASSET_NO_DATA):
        max=3, base=60s, jitter ±20%
    PERMANENT/UNKNOWN: NO RETRY (raise imediato — R7 fail fast)

Override via env var (AC8):

    DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT=int  (default 5)
    DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_AMBIGUOUS=int  (default 3)
    DATA_DOWNLOADER_RETRY_BASE_DELAY_SECONDS=float    (default 30.0)
    DATA_DOWNLOADER_RETRY_MAX_DELAY_SECONDS=float     (default 600.0)
    DATA_DOWNLOADER_RETRY_JITTER=float                (default 0.2)

LEIS RESPEITADAS:
- R7 (fail fast): PERMANENT/UNKNOWN NÃO retry (default policy explicita).
- R10 (minimal deps): apenas stdlib + structlog.
- R21 (cool path): logger emite em cada attempt (per-call, não per-trade).
"""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

import structlog

from data_downloader.dll.error_taxonomy import ErrorCategory, categorize_nl

__all__ = [
    "DEFAULT_AMBIGUOUS_BASE_DELAY",
    "DEFAULT_AMBIGUOUS_MAX_ATTEMPTS",
    "DEFAULT_FACTOR",
    "DEFAULT_JITTER",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_TRANSIENT_BASE_DELAY",
    "DEFAULT_TRANSIENT_MAX_ATTEMPTS",
    "RetryPolicy",
    "default_retry_policy",
    "policy_from_env",
]

T = TypeVar("T")

log: structlog.stdlib.BoundLogger = structlog.get_logger(
    "data_downloader.orchestrator.retry_policy"
)


# =====================================================================
# Defaults (Story 2.6 AC2)
# =====================================================================

DEFAULT_TRANSIENT_MAX_ATTEMPTS: int = 5
"""Tentativas para TRANSIENT — generoso (rede pode demorar minutos)."""

DEFAULT_AMBIGUOUS_MAX_ATTEMPTS: int = 3
"""Tentativas para AMBIGUOUS — conservador (pode ser permanent disfarçado)."""

DEFAULT_TRANSIENT_BASE_DELAY: float = 30.0
"""Base delay TRANSIENT (30s) — alinhado a Q02-E (99% reconnect leva ~minutos)."""

DEFAULT_AMBIGUOUS_BASE_DELAY: float = 60.0
"""Base delay AMBIGUOUS (60s) — backoff mais lento dá tempo ao servidor."""

DEFAULT_FACTOR: float = 2.0
"""Multiplicador exponencial (delay = base * factor^(attempt-1)).
Story 2.6 AC2: factor=2 → 30, 60, 120, 240, 480 (capped @ 600)."""

DEFAULT_MAX_DELAY: float = 600.0
"""Cap absoluto de delay por attempt — 10 min."""

DEFAULT_JITTER: float = 0.2
"""Jitter ±20% — anti thundering-herd."""


# =====================================================================
# RetryPolicy dataclass
# =====================================================================


@dataclass(frozen=True)
class RetryPolicy:
    """Política imutável de retry por categoria (Story 2.6 AC2).

    Use factories :func:`default_retry_policy` ou :func:`policy_from_env`
    em vez de construir diretamente — defaults documentados em
    ``docs/dev/RETRY_POLICY.md``.

    Attributes:
        max_attempts_transient: Tentativas para categoria TRANSIENT.
        max_attempts_ambiguous: Tentativas para categoria AMBIGUOUS.
        base_delay_transient: Delay base TRANSIENT (segundos).
        base_delay_ambiguous: Delay base AMBIGUOUS (segundos).
        factor: Multiplicador exponencial.
        max_delay: Cap absoluto por attempt (segundos).
        jitter: Jitter ±jitter (fração).
        retryable_exception_types: Exceptions Python (não-NL_*) consideradas
            retryable. Default ``(OSError, TimeoutError)`` (alinhado com
            Story 1.7a). NL_*-derived errors são categorizados via
            :func:`categorize_nl` ao classificá-los.
        retryable_categories: Set de :class:`ErrorCategory` que disparam
            retry. Default ``{TRANSIENT, AMBIGUOUS}``.
    """

    max_attempts_transient: int = DEFAULT_TRANSIENT_MAX_ATTEMPTS
    max_attempts_ambiguous: int = DEFAULT_AMBIGUOUS_MAX_ATTEMPTS
    base_delay_transient: float = DEFAULT_TRANSIENT_BASE_DELAY
    base_delay_ambiguous: float = DEFAULT_AMBIGUOUS_BASE_DELAY
    factor: float = DEFAULT_FACTOR
    max_delay: float = DEFAULT_MAX_DELAY
    jitter: float = DEFAULT_JITTER
    retryable_exception_types: tuple[type[BaseException], ...] = (OSError, TimeoutError)
    retryable_categories: frozenset[ErrorCategory] = field(
        default_factory=lambda: frozenset({ErrorCategory.TRANSIENT, ErrorCategory.AMBIGUOUS})
    )

    # ------------------------------------------------------------------
    # API pública — decisão por exception
    # ------------------------------------------------------------------

    def classify_exception(self, exc: BaseException) -> ErrorCategory:
        """Classifica uma exception em categoria.

        Heurísticas (em ordem):

        1. Se exc tem attr ``nl_code``: usa :func:`categorize_nl(nl_code)`.
        2. Se exc é instância de ``retryable_exception_types``: TRANSIENT
           (preserva contrato Story 1.7a — OSError/TimeoutError = transient).
        3. Caso contrário: PERMANENT (R7 fail fast).
        """
        # 1. Exception carrega NL_* code → consulta taxonomia.
        nl_code = getattr(exc, "nl_code", None)
        if isinstance(nl_code, int):
            return categorize_nl(nl_code).category

        # 2. Tipo Python "transient-by-convention" (rede / timeout).
        if isinstance(exc, self.retryable_exception_types):
            return ErrorCategory.TRANSIENT

        # 3. Default conservador.
        return ErrorCategory.PERMANENT

    def should_retry(self, exc: BaseException, attempt: int) -> bool:
        """Decide se deve retry após attempt N falhar com `exc`.

        Args:
            exc: Exception capturada.
            attempt: Número da tentativa que ACABOU de falhar (1-indexed).

        Returns:
            ``True`` se deve agendar attempt (N+1); ``False`` se
            re-raise imediato.
        """
        # KeyboardInterrupt / SystemExit NUNCA retry — short-circuit.
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            return False
        category = self.classify_exception(exc)
        if category not in self.retryable_categories:
            return False
        max_attempts = self.max_attempts_for(category)
        return attempt < max_attempts

    def max_attempts_for(self, category: ErrorCategory) -> int:
        """Retorna max_attempts para uma categoria."""
        if category is ErrorCategory.TRANSIENT:
            return self.max_attempts_transient
        if category is ErrorCategory.AMBIGUOUS:
            return self.max_attempts_ambiguous
        # PERMANENT / UNKNOWN — conceitualmente "1 attempt sem retry".
        return 1

    def base_delay_for(self, category: ErrorCategory) -> float:
        """Retorna base_delay para uma categoria."""
        if category is ErrorCategory.TRANSIENT:
            return self.base_delay_transient
        if category is ErrorCategory.AMBIGUOUS:
            return self.base_delay_ambiguous
        return 0.0

    def next_delay(
        self,
        attempt: int,
        category: ErrorCategory = ErrorCategory.TRANSIENT,
        *,
        random_fn: Callable[[], float] = random.random,
    ) -> float:
        """Calcula delay para a PRÓXIMA tentativa após attempt N falhar.

        Fórmula: ``base * factor^(attempt-1) * (1 + jitter_signed)``,
        capped por :attr:`max_delay`. Sempre >= 0.

        Args:
            attempt: Número do attempt que acabou de falhar (1-indexed).
            category: Categoria do erro (decide base_delay).
            random_fn: Injetável para testes determinísticos.

        Returns:
            Delay em segundos antes do próximo attempt.
        """
        if attempt < 1:
            raise ValueError(f"attempt must be >= 1; got {attempt}")
        base = self.base_delay_for(category)
        raw = base * (self.factor ** (attempt - 1))
        capped = min(raw, self.max_delay)
        jitter_signed = random_fn() * 2.0 * self.jitter - self.jitter
        return max(0.0, capped * (1.0 + jitter_signed))

    # ------------------------------------------------------------------
    # API decorator
    # ------------------------------------------------------------------

    def __call__(
        self,
        fn: Callable[[], T],
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
        op_name: str = "retry",
    ) -> T:
        """Executa ``fn()`` aplicando esta policy (decorator-friendly).

        Algoritmo (Story 2.6):

        1. Tenta ``fn()``. Sucesso → retorna.
        2. Falha capturada `exc` → classifica via :meth:`classify_exception`.
        3. Se categoria PERMANENT/UNKNOWN → re-raise imediato (R7 fail fast).
        4. Se categoria retryable + attempt < max → sleep next_delay → retry.
        5. Se attempt == max → re-raise (caller decide o que fazer).

        Args:
            fn: Callable sem argumentos.
            sleep_fn: Injetável para testes (default :func:`time.sleep`).
            random_fn: Injetável para testes (default :func:`random.random`).
            op_name: Rótulo simbólico para logging.

        Returns:
            Resultado de ``fn()``.

        Raises:
            BaseException: Re-raise da exception após exauster ou
                fail-fast em PERMANENT.
        """
        # Limite superior de attempts = max em qualquer categoria
        # (TRANSIENT na default; AMBIGUOUS pode ser menor).
        attempt = 0
        max_overall = max(self.max_attempts_transient, self.max_attempts_ambiguous, 1)
        last_exc: BaseException | None = None
        while attempt < max_overall:
            attempt += 1
            try:
                return fn()
            except BaseException as exc:
                last_exc = exc
                if not self.should_retry(exc, attempt):
                    if self.classify_exception(exc) in (
                        ErrorCategory.PERMANENT,
                        ErrorCategory.UNKNOWN,
                    ):
                        log.info(
                            "retry.skipped_permanent",
                            op=op_name,
                            attempt=attempt,
                            error=repr(exc),
                            category=self.classify_exception(exc).value,
                        )
                    raise
                category = self.classify_exception(exc)
                delay = self.next_delay(attempt, category, random_fn=random_fn)
                log.info(
                    "retry.attempt",
                    op=op_name,
                    attempt=attempt,
                    next_attempt_in_seconds=round(delay, 3),
                    category=category.value,
                    error=repr(exc),
                )
                sleep_fn(delay)

        # Todas as tentativas exauridas — re-raise última exception.
        log.warning(
            "retry.exhausted",
            op=op_name,
            attempts=attempt,
            error=repr(last_exc),
        )
        # last_exc é Não-None aqui (loop só sai por exhaustion após raise).
        # mypy não infere — narrowing explícito.
        if last_exc is None:  # pragma: no cover defensive
            raise RuntimeError(f"retry exhausted without captured exception (op={op_name})")
        raise last_exc


# =====================================================================
# Factories
# =====================================================================


def default_retry_policy() -> RetryPolicy:
    """Cria a policy default Story 2.6 (TRANSIENT + AMBIGUOUS retry).

    Equivalente a ``RetryPolicy()`` — explícito para uso pelos callers
    do orchestrator.
    """
    return RetryPolicy()


def policy_from_env() -> RetryPolicy:
    """Cria a policy a partir de env vars (Story 2.6 AC8).

    Override:
        DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT
        DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_AMBIGUOUS
        DATA_DOWNLOADER_RETRY_BASE_DELAY_SECONDS  (TRANSIENT)
        DATA_DOWNLOADER_RETRY_BASE_DELAY_AMBIGUOUS_SECONDS
        DATA_DOWNLOADER_RETRY_FACTOR
        DATA_DOWNLOADER_RETRY_MAX_DELAY_SECONDS
        DATA_DOWNLOADER_RETRY_JITTER

    Cada valor inválido é silenciosamente substituído pelo default
    (best-effort robustez — env malformada não para o sistema). Loga
    warning para o operador notar.
    """

    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = int(raw)
            if value < 1:
                raise ValueError("must be >= 1")
            return value
        except ValueError as exc:
            log.warning("retry_policy.env_invalid", env=name, value=raw, error=str(exc))
            return default

    def _float(name: str, default: float, *, allow_zero: bool = False) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
            if value < 0 or (not allow_zero and value == 0):
                raise ValueError("must be > 0")
            return value
        except ValueError as exc:
            log.warning("retry_policy.env_invalid", env=name, value=raw, error=str(exc))
            return default

    return RetryPolicy(
        max_attempts_transient=_int(
            "DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT",
            DEFAULT_TRANSIENT_MAX_ATTEMPTS,
        ),
        max_attempts_ambiguous=_int(
            "DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_AMBIGUOUS",
            DEFAULT_AMBIGUOUS_MAX_ATTEMPTS,
        ),
        base_delay_transient=_float(
            "DATA_DOWNLOADER_RETRY_BASE_DELAY_SECONDS",
            DEFAULT_TRANSIENT_BASE_DELAY,
        ),
        base_delay_ambiguous=_float(
            "DATA_DOWNLOADER_RETRY_BASE_DELAY_AMBIGUOUS_SECONDS",
            DEFAULT_AMBIGUOUS_BASE_DELAY,
        ),
        factor=_float("DATA_DOWNLOADER_RETRY_FACTOR", DEFAULT_FACTOR),
        max_delay=_float("DATA_DOWNLOADER_RETRY_MAX_DELAY_SECONDS", DEFAULT_MAX_DELAY),
        jitter=_float("DATA_DOWNLOADER_RETRY_JITTER", DEFAULT_JITTER, allow_zero=True),
    )
