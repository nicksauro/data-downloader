"""data_downloader.orchestrator.circuit_breaker — Stateful breaker per (symbol, exchange).

Owner: Dex (impl) | Audit: Aria (state machine + thread model — ADR-005).
Story 2.6 (Retry inteligente + circuit breaker) — AC3 + AC4.

Implementação **dependency-free** (R10 — sem `pybreaker` ou similares):
máquina de estados de 3 estados + sliding-window deque + lock interno
``threading.Lock``.

Estados (state machine):

    CLOSED ──(N falhas em janela W)──> OPEN
    OPEN ──(cooldown decorrido)─────> HALF_OPEN
    HALF_OPEN ──(sucesso na 1ª call)─> CLOSED
    HALF_OPEN ──(falha na 1ª call)──> OPEN (cooldown x 2 — backoff)

CLOSED:
    Operação normal — chamadas passam direto para a função wrapped. Falhas
    são contabilizadas em sliding-window; sucessos resetam contagem
    parcial (janela ainda corre).

OPEN:
    Bloqueia toda chamada — raise :class:`CircuitOpenError` SEM invocar
    a função wrapped. Evita storm de retries quando DLL caída.

HALF_OPEN:
    Probe state — primeira call é deixada passar. Se ela passar, volta a
    CLOSED (recovered). Se ela falhar, volta a OPEN com cooldown ampliado
    (2x — exponential backoff sobre o cooldown).

LEIS RESPEITADAS:
- R7 (fail fast): erro lógico (PERMANENT) NÃO conta como falha — apenas
  TRANSIENT/AMBIGUOUS contam (responsabilidade do caller via
  ``record_failure(category)`` ou via `Decision.skip_breaker()` quando
  q02e quirk).
- R10 (minimal deps): zero dependências externas, apenas stdlib.
- R21 (cool path): logs apenas em transições de estado (não per-call).
- ADR-005 (thread model): lock interno garante que múltiplos threads
  observando o mesmo breaker convergem para estado consistente.

Q02-E (progress=99% reconnect):
    Hook ``q02e_progress_aware`` no chamador (orchestrator) — NÃO conta
    o quirk como falha porque progress=99% NÃO é NL_* error code, é
    estado de fluxo. Apenas timeouts duros do download_primitive contam.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

import structlog

from data_downloader.public_api.exceptions import DataDownloaderError

__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_WINDOW_SECONDS",
    "BreakerState",
    "CircuitBreaker",
    "CircuitOpenError",
    "with_circuit_breaker",
]

T = TypeVar("T")

log: structlog.stdlib.BoundLogger = structlog.get_logger(
    "data_downloader.orchestrator.circuit_breaker"
)


# =====================================================================
# Defaults (Story 2.6 AC3 + AC8)
# =====================================================================

DEFAULT_FAILURE_THRESHOLD: int = 10
"""N falhas TRANSIENT em janela W → OPEN. Default 10 — alto o bastante para
absorver flaky de rede sem disparar; baixo o bastante para detectar
DLL caída (~3-5 chunks failures consecutivos = trip)."""

DEFAULT_WINDOW_SECONDS: float = 300.0
"""Janela W (5 min) — escala de tempo de blip de rede."""

DEFAULT_COOLDOWN_SECONDS: float = 600.0
"""Cooldown OPEN → HALF_OPEN (10 min). Suficiente para Q02-E reconnect
estabilizar sem ser hostil ao operador (download longo aceita 10min de
freeze entre tentativas)."""


# =====================================================================
# Tipos públicos
# =====================================================================


class BreakerState(StrEnum):
    """3 estados canônicos do circuit breaker (Story 2.6 AC3).

    Ordem por severidade crescente: CLOSED < HALF_OPEN < OPEN.
    """

    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


class CircuitOpenError(DataDownloaderError):
    """Circuit breaker está OPEN — chamada bloqueada (Story 2.6 AC5).

    Subclasse de :class:`DataDownloaderError` (ADR-011 — fronteira pública
    SemVer-tracked). Caller (orchestrator) traduz para job ``status='failed'``.

    Args:
        symbol: Símbolo do breaker (e.g. ``"WDOJ26"``).
        exchange: Bolsa (``"F"`` ou ``"B"``).
        retry_after_seconds: Tempo aprox. até HALF_OPEN (cooldown restante).
        failure_count: Quantas falhas dispararam o trip (≥ threshold).
        message: Mensagem opcional; se ausente, é construída.
        cause: Última exception capturada (forensics).
    """

    def __init__(
        self,
        symbol: str,
        exchange: str,
        *,
        retry_after_seconds: float,
        failure_count: int,
        message: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        msg = message or (
            f"Circuit breaker OPEN for {symbol}/{exchange}: "
            f"{failure_count} consecutive transient failures detected; "
            f"retry after ~{retry_after_seconds:.0f}s."
        )
        details: dict[str, object] = {
            "symbol": symbol,
            "exchange": exchange,
            "retry_after_seconds": retry_after_seconds,
            "failure_count": failure_count,
        }
        super().__init__(msg, cause=cause, details=details)
        self.symbol = symbol
        self.exchange = exchange
        self.retry_after_seconds = retry_after_seconds
        self.failure_count = failure_count


# =====================================================================
# CircuitBreaker — state machine com sliding window
# =====================================================================


class CircuitBreaker:
    """Stateful circuit breaker thread-safe (Story 2.6 AC3).

    Use via :meth:`call` (wrapper) OU via API explícita:

        breaker = CircuitBreaker(symbol="WDOJ26", exchange="F")
        if breaker.state is BreakerState.OPEN:
            raise CircuitOpenError(...)
        try:
            result = breaker.call(my_dll_op)
        except CircuitOpenError:
            ...

    OU usando :func:`with_circuit_breaker` decorator:

        @with_circuit_breaker(breaker)
        def download_chunk(...):
            ...

    Attributes:
        symbol: Identificador (audit + label de métricas).
        exchange: Bolsa (audit + label).
        failure_threshold: N falhas em janela → OPEN.
        window_seconds: Tamanho da janela sliding W.
        cooldown_seconds: Tempo em OPEN antes de tentar HALF_OPEN.

    Thread-safety:
        Lock interno (``threading.Lock``). Múltiplos chamadores podem
        invocar :meth:`call` concorrentemente; estado converge.
    """

    def __init__(
        self,
        symbol: str = "default",
        exchange: str = "F",
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold must be >= 1; got {failure_threshold}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0; got {window_seconds}")
        if cooldown_seconds <= 0:
            raise ValueError(f"cooldown_seconds must be > 0; got {cooldown_seconds}")

        self._symbol = symbol
        self._exchange = exchange
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._base_cooldown = cooldown_seconds
        self._current_cooldown = cooldown_seconds  # ampliável após HALF_OPEN→OPEN
        self._clock_fn = clock_fn

        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        # Sliding window — timestamps das falhas (monotônicos).
        self._failures: deque[float] = deque()
        # Marca do último trip (CLOSED → OPEN ou HALF_OPEN → OPEN).
        self._opened_at: float | None = None

    # ------------------------------------------------------------------
    # Estado público
    # ------------------------------------------------------------------

    @property
    def state(self) -> BreakerState:
        """Estado atual — re-avalia OPEN→HALF_OPEN se cooldown decorrido.

        Acesso ao estado é via lock + lazy transition: chamada repetida
        a `.state` quando OPEN expirado promove para HALF_OPEN sem
        precisar de uma chamada `.call()` explicita.
        """
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            return self._state

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def exchange(self) -> str:
        return self._exchange

    @property
    def failure_count(self) -> int:
        """Falhas atualmente na janela (não-thread-safe; debug only)."""
        return len(self._failures)

    @property
    def failure_threshold(self) -> int:
        """N falhas configurado como threshold para trip (read-only)."""
        return self._failure_threshold

    @property
    def window_seconds(self) -> float:
        """Janela sliding W em segundos (read-only)."""
        return self._window_seconds

    @property
    def base_cooldown_seconds(self) -> float:
        """Cooldown base configurado (sem amplificação por probe failure)."""
        return self._base_cooldown

    @property
    def current_cooldown_seconds(self) -> float:
        """Cooldown corrente (pode ser ampliado após HALF_OPEN→OPEN)."""
        return self._current_cooldown

    @property
    def cooldown_remaining_seconds(self) -> float:
        """Tempo restante em OPEN (0 se não-OPEN ou cooldown decorrido)."""
        with self._lock:
            if self._state is not BreakerState.OPEN or self._opened_at is None:
                return 0.0
            elapsed = self._clock_fn() - self._opened_at
            return max(0.0, self._current_cooldown - elapsed)

    # ------------------------------------------------------------------
    # API principal — call wrapper
    # ------------------------------------------------------------------

    def call(self, fn: Callable[[], T]) -> T:
        """Executa ``fn()`` sob a proteção do circuit breaker.

        Fluxo:

        1. Re-avalia estado (OPEN → HALF_OPEN se cooldown decorrido).
        2. Se OPEN: raise :class:`CircuitOpenError` SEM invocar ``fn``.
        3. Se HALF_OPEN: invoca ``fn``. Sucesso → CLOSED. Falha → OPEN.
        4. Se CLOSED: invoca ``fn``. Sucesso → :meth:`record_success`.
           Falha (qualquer exception) → :meth:`record_failure`, re-raise.

        Args:
            fn: Callable sem argumentos.

        Returns:
            Resultado de ``fn()``.

        Raises:
            CircuitOpenError: Estado OPEN e cooldown não decorrido.
            Exception: Re-raise transparente da exception de ``fn``.
        """
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            if self._state is BreakerState.OPEN:
                raise CircuitOpenError(
                    self._symbol,
                    self._exchange,
                    retry_after_seconds=self._cooldown_remaining_locked(),
                    failure_count=len(self._failures),
                )
            in_half_open = self._state is BreakerState.HALF_OPEN

        # fn() RODA FORA do lock — evita deadlock se fn re-entra no
        # breaker (ex.: wrap aninhado) e não bloqueia outros threads
        # observando state durante longo download_chunk.
        try:
            result = fn()
        except Exception as exc:
            self.record_failure(cause=exc)
            raise
        else:
            self.record_success(was_half_open=in_half_open)
            return result

    # ------------------------------------------------------------------
    # API explícita — record success/failure (orchestrator usa direto
    # para alimentar breaker com NL_* category sem precisar levantar
    # exception)
    # ------------------------------------------------------------------

    def record_success(self, *, was_half_open: bool = False) -> None:
        """Registra um sucesso.

        Em HALF_OPEN, transita para CLOSED + reseta cooldown ao base.
        Em CLOSED, evicta falhas fora da janela (cleanup oportunista).

        Args:
            was_half_open: Se ``True``, força transição HALF_OPEN → CLOSED
                (caller já leu o estado pre-call e sabe que probe passou).
        """
        with self._lock:
            if was_half_open or self._state is BreakerState.HALF_OPEN:
                if self._state is not BreakerState.CLOSED:
                    self._transition_locked(BreakerState.CLOSED, reason="probe_success")
                self._failures.clear()
                self._current_cooldown = self._base_cooldown
                self._opened_at = None
            else:
                # CLOSED success — apenas cleanup janela.
                self._evict_old_failures_locked()

    def record_failure(self, *, cause: Exception | None = None) -> None:
        """Registra uma falha (transient — caller já filtrou category).

        Em CLOSED: append em sliding window; se contagem ≥ threshold → OPEN.
        Em HALF_OPEN: transita para OPEN, dobra cooldown (max base x 8).
        Em OPEN: idempotente (não muda nada — já está bloqueando).
        """
        with self._lock:
            now = self._clock_fn()
            if self._state is BreakerState.OPEN:
                # Já bloqueando — append para audit mas não muda estado.
                self._failures.append(now)
                self._evict_old_failures_locked()
                return

            if self._state is BreakerState.HALF_OPEN:
                # Probe falhou — re-OPEN com cooldown ampliado (max 8x).
                self._current_cooldown = min(
                    self._current_cooldown * 2.0,
                    self._base_cooldown * 8.0,
                )
                self._opened_at = now
                self._failures.append(now)
                self._evict_old_failures_locked()
                self._transition_locked(
                    BreakerState.OPEN,
                    reason="probe_failure",
                    cause=repr(cause) if cause else None,
                )
                return

            # CLOSED — sliding window
            self._failures.append(now)
            self._evict_old_failures_locked()
            if len(self._failures) >= self._failure_threshold:
                self._opened_at = now
                self._current_cooldown = self._base_cooldown
                self._transition_locked(
                    BreakerState.OPEN,
                    reason="threshold_reached",
                    cause=repr(cause) if cause else None,
                )

    # ------------------------------------------------------------------
    # Reset manual (debug / ops)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Força CLOSED (uso ops — `data-downloader doctor --reset-breaker`)."""
        with self._lock:
            prev = self._state
            self._state = BreakerState.CLOSED
            self._failures.clear()
            self._current_cooldown = self._base_cooldown
            self._opened_at = None
            if prev is not BreakerState.CLOSED:
                log.info(
                    "circuit_breaker.transition",
                    symbol=self._symbol,
                    exchange=self._exchange,
                    **{"from": prev.value, "to": "closed"},
                    reason="manual_reset",
                )

    # ------------------------------------------------------------------
    # Internals (locked) — chamados apenas com self._lock held
    # ------------------------------------------------------------------

    def _maybe_transition_to_half_open_locked(self) -> None:
        """OPEN → HALF_OPEN se cooldown decorrido (lazy transition)."""
        if self._state is not BreakerState.OPEN or self._opened_at is None:
            return
        elapsed = self._clock_fn() - self._opened_at
        if elapsed >= self._current_cooldown:
            self._transition_locked(BreakerState.HALF_OPEN, reason="cooldown_elapsed")

    def _cooldown_remaining_locked(self) -> float:
        if self._state is not BreakerState.OPEN or self._opened_at is None:
            return 0.0
        elapsed = self._clock_fn() - self._opened_at
        return max(0.0, self._current_cooldown - elapsed)

    def _evict_old_failures_locked(self) -> None:
        """Remove falhas fora da janela sliding."""
        if not self._failures:
            return
        cutoff = self._clock_fn() - self._window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def _transition_locked(
        self,
        new_state: BreakerState,
        *,
        reason: str,
        cause: str | None = None,
    ) -> None:
        """Loga e aplica transição. Apenas chamado com lock held."""
        old_state = self._state
        if old_state is new_state:
            return
        self._state = new_state
        log.info(
            "circuit_breaker.transition",
            symbol=self._symbol,
            exchange=self._exchange,
            **{"from": old_state.value, "to": new_state.value},
            reason=reason,
            cause=cause,
            failure_count=len(self._failures),
            cooldown_seconds=self._current_cooldown,
        )


# =====================================================================
# Decorator helper
# =====================================================================


def with_circuit_breaker(
    breaker: CircuitBreaker,
) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Decorator factory — aplica :meth:`CircuitBreaker.call` a uma função.

    Uso::

        breaker = CircuitBreaker(symbol="WDOJ26", exchange="F")

        @with_circuit_breaker(breaker)
        def my_op():
            return dll.get_history_trades(...)

        result = my_op()  # protegido pelo breaker

    Args:
        breaker: Instância já criada de :class:`CircuitBreaker`.

    Returns:
        Decorator que envolve qualquer callable zero-arg.
    """

    def _decorator(fn: Callable[[], T]) -> Callable[[], T]:
        def _wrapped() -> T:
            return breaker.call(fn)

        return _wrapped

    return _decorator
