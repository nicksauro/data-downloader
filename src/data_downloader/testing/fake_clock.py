"""data_downloader.testing.fake_clock — Relógio determinístico para testes.

Story 2.10 / ADR-014 — operacionaliza o requisito de **tempo controlável**
em testes para que retry/circuit_breaker/timeout-bound code-paths possam
ser exercitados sem ``time.sleep`` real (tempo de testes determinístico,
suite < 30s mesmo cobrindo 30s de "wallclock").

Substitui simultaneamente:

- :func:`time.perf_counter` (monotonic, usado por orchestrator/retry)
- :func:`time.time` (epoch UTC float)
- :meth:`datetime.datetime.now` / :meth:`datetime.datetime.utcnow` —
  obs.: naive vs aware é responsabilidade do caller.

Não substitui:

- :func:`time.sleep` — quem dorme em testes deve receber ``sleep_fn``
  injectado e usar :meth:`FakeClock.sleep`. Patch global de ``time.sleep``
  é hostil a libs internas (logging, structlog) que dependem dele para
  rate-limit. Use ``advance(n)`` explicitamente quando precisar avançar.

Uso típico (manual):

    >>> clock = FakeClock(start_seconds=1_700_000_000.0)
    >>> clock.now()
    1700000000.0
    >>> clock.advance(5.0)
    >>> clock.now()
    1700000005.0
    >>> clock.freeze()
    >>> clock.advance(1.0)  # no-op enquanto freezed
    >>> clock.now()
    1700000005.0

Uso como context manager (monkey-patch ``time.perf_counter`` /
``time.time`` / ``datetime.datetime`` apenas dentro do ``with``):

    >>> from datetime import datetime, timezone
    >>> with FakeClock.patched(start=datetime(2026, 1, 1, tzinfo=timezone.utc)) as clock:
    ...     import time as _t
    ...     t0 = _t.perf_counter()
    ...     clock.advance(2.5)
    ...     t1 = _t.perf_counter()
    ...     assert t1 - t0 == 2.5

INV preservadas:

- ``advance(s)`` é monotônica: ``now()`` jamais retrocede.
- ``advance(0)`` é idempotente.
- Após N invocações de ``advance(1.0)`` consecutivas, ``now()`` ==
  ``start + N`` exato (sem float drift, pois mantemos ns interno).
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from typing import Final
from unittest.mock import patch

# 1 segundo em nanosegundos — usado para conversão sem float drift.
_NS_PER_SEC: Final[int] = 1_000_000_000


class FakeClock:
    """Relógio controlável manualmente. Thread-safe.

    Mantém estado em **nanosegundos inteiros** internamente para evitar
    drift de ponto flutuante quando o teste avança em incrementos
    pequenos (ex.: ``advance(0.000001)`` 1M vezes deve dar 1.0s exato).

    Atributos públicos (read-only — use métodos para mutar):
        start_ns: Tempo inicial (ns desde epoch UTC).
    """

    __slots__ = ("_frozen", "_lock", "_now_ns", "start_ns")

    def __init__(
        self,
        start_seconds: float = 0.0,
        *,
        start_datetime: datetime | None = None,
    ) -> None:
        """Inicializa o relógio.

        Args:
            start_seconds: Tempo inicial em segundos desde epoch UTC.
                Default 0.0 — útil para testes onde só importa delta.
            start_datetime: Alternativa a ``start_seconds`` — caller passa
                ``datetime`` aware (timezone obrigatório). Se ambos forem
                passados, ``start_datetime`` vence.

        Raises:
            ValueError: Se ``start_datetime`` é naive (sem tzinfo).
        """
        if start_datetime is not None:
            if start_datetime.tzinfo is None:
                raise ValueError(
                    "start_datetime must be timezone-aware (use timezone.utc); "
                    f"got naive {start_datetime!r}"
                )
            start_seconds = start_datetime.timestamp()

        self.start_ns: int = int(start_seconds * _NS_PER_SEC)
        self._now_ns: int = self.start_ns
        self._frozen: bool = False
        self._lock = threading.Lock()

    # -----------------------------------------------------------------
    # Read API
    # -----------------------------------------------------------------

    def now(self) -> float:
        """Retorna o "agora" do relógio em segundos (epoch float).

        Equivalente a :func:`time.time` sob patch.
        """
        with self._lock:
            return self._now_ns / _NS_PER_SEC

    def perf_counter(self) -> float:
        """Equivalente a :func:`time.perf_counter` — segundos monotônicos.

        Para FakeClock, ``now()`` e ``perf_counter()`` retornam o mesmo
        valor. Em produção ``perf_counter`` é monotônico e ``time()`` é
        wall-clock; em testes determinísticos a distinção não importa.
        """
        with self._lock:
            return self._now_ns / _NS_PER_SEC

    def now_ns(self) -> int:
        """Retorna o "agora" em nanosegundos inteiros (zero drift)."""
        with self._lock:
            return self._now_ns

    def now_datetime(self, tz: timezone | None = UTC) -> datetime:
        """Retorna o "agora" como :class:`datetime` aware (default UTC)."""
        with self._lock:
            return datetime.fromtimestamp(self._now_ns / _NS_PER_SEC, tz=tz)

    # -----------------------------------------------------------------
    # Mutation API
    # -----------------------------------------------------------------

    def advance(self, seconds: float) -> None:
        """Avança o relógio em ``seconds`` (no-op se ``frozen``).

        Args:
            seconds: Delta em segundos. DEVE ser >= 0 (relógio é
                monotônico — passado é passado, INV-time-monotonic).

        Raises:
            ValueError: Se ``seconds`` < 0.
        """
        if seconds < 0:
            raise ValueError(f"FakeClock.advance requires seconds >= 0; got {seconds}")
        with self._lock:
            if self._frozen:
                return
            self._now_ns += int(seconds * _NS_PER_SEC)

    def advance_ns(self, nanoseconds: int) -> None:
        """Avança em nanosegundos exatos (sem conversão float)."""
        if nanoseconds < 0:
            raise ValueError(f"FakeClock.advance_ns requires nanoseconds >= 0; got {nanoseconds}")
        with self._lock:
            if self._frozen:
                return
            self._now_ns += nanoseconds

    def sleep(self, seconds: float) -> None:
        """Substituto in-process para :func:`time.sleep`.

        Avança o relógio instantaneamente — não bloqueia. Útil em código
        que recebe ``sleep_fn`` injectada (retry, circuit breaker).
        """
        self.advance(seconds)

    # -----------------------------------------------------------------
    # Freeze/thaw
    # -----------------------------------------------------------------

    def freeze(self) -> None:
        """Congela o relógio — ``advance`` vira no-op até :meth:`thaw`."""
        with self._lock:
            self._frozen = True

    def thaw(self) -> None:
        """Descongela o relógio — :meth:`advance` volta a funcionar."""
        with self._lock:
            self._frozen = False

    @property
    def frozen(self) -> bool:
        """True se :meth:`freeze` foi chamado e :meth:`thaw` ainda não."""
        with self._lock:
            return self._frozen

    # -----------------------------------------------------------------
    # Context manager — patch global de time/datetime
    # -----------------------------------------------------------------

    @contextmanager
    def patch_time(self) -> Generator[FakeClock, None, None]:
        """Monkey-patch ``time.time`` + ``time.perf_counter`` enquanto ativo.

        NÃO patcha ``time.sleep`` (ver docstring do módulo para o porquê).

        Yields:
            Self — para uso encadeado: ``with clock.patch_time() as c: ...``
        """
        with patch("time.time", self.now), patch("time.perf_counter", self.perf_counter):
            yield self

    @classmethod
    @contextmanager
    def patched(
        cls,
        *,
        start_seconds: float = 0.0,
        start: datetime | None = None,
    ) -> Generator[FakeClock, None, None]:
        """One-shot factory + patch — útil em testes pequenos.

        Cria um :class:`FakeClock` e já entra no :meth:`patch_time`.

        Args:
            start_seconds: Vide :class:`FakeClock`.
            start: Alias para ``start_datetime`` do construtor.

        Yields:
            Instância de :class:`FakeClock` com tempo já patcheado.
        """
        clock = cls(start_seconds=start_seconds, start_datetime=start)
        with clock.patch_time():
            yield clock


# -----------------------------------------------------------------
# Convenience helpers
# -----------------------------------------------------------------


def freeze_at(when: datetime) -> FakeClock:
    """Cria um :class:`FakeClock` parado em ``when`` (já frozen).

    Args:
        when: Datetime aware. Naive raises ``ValueError`` (mesma regra do
            construtor).

    Returns:
        :class:`FakeClock` com :meth:`freeze` aplicado.
    """
    clock = FakeClock(start_datetime=when)
    clock.freeze()
    return clock


def make_clock_at(year: int, month: int, day: int) -> FakeClock:
    """Helper: relógio em ``YYYY-MM-DD 00:00:00 UTC`` — açúcar para testes."""
    return FakeClock(start_datetime=datetime(year, month, day, tzinfo=UTC))


__all__ = [
    "FakeClock",
    "freeze_at",
    "make_clock_at",
]


# Re-export utilitário usado por testes que precisam construir delta sem
# importar ``timedelta`` separadamente.
seconds = timedelta
