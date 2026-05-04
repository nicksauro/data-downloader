"""Unit tests — MetricsEmitter Protocol + NullMetricsEmitter (Story 2.4 AC5).

Cobertura:

- :class:`NullMetricsEmitter` é instanciável e aceita todas as chamadas
  do Protocol sem efeito colateral observável (zero overhead default).
- :class:`NullMetricsEmitter` satisfaz ``isinstance`` check do
  ``runtime_checkable`` :class:`MetricsEmitter` Protocol.
- Implementações ad-hoc (spies para tests integration) também satisfazem
  o Protocol — confirma que a interface é minimal e estendível.
"""

from __future__ import annotations

import pytest

from data_downloader.contracts.observability import MetricsEmitter, NullMetricsEmitter


@pytest.mark.unit
def test_null_emitter_instantiable() -> None:
    """NullMetricsEmitter é instanciável sem args."""
    emitter = NullMetricsEmitter()
    assert emitter is not None


@pytest.mark.unit
def test_null_emitter_satisfies_protocol() -> None:
    """NullMetricsEmitter satisfaz runtime_checkable MetricsEmitter."""
    emitter = NullMetricsEmitter()
    assert isinstance(emitter, MetricsEmitter)


@pytest.mark.unit
def test_null_emitter_incr_counter_no_op() -> None:
    """incr_counter sem args adicionais não levanta nem retorna erro."""
    emitter = NullMetricsEmitter()
    # Sem labels.
    result = emitter.incr_counter("foo")
    assert result is None
    # Com labels.
    result = emitter.incr_counter("bar", labels={"symbol": "WDOJ26"})
    assert result is None


@pytest.mark.unit
def test_null_emitter_set_gauge_no_op() -> None:
    """set_gauge não levanta nem retorna valor."""
    emitter = NullMetricsEmitter()
    assert emitter.set_gauge("queue_depth", 42.0) is None
    assert emitter.set_gauge("queue_depth", 100.0, labels={"q": "dll"}) is None


@pytest.mark.unit
def test_null_emitter_observe_histogram_no_op() -> None:
    """observe_histogram não levanta nem retorna valor."""
    emitter = NullMetricsEmitter()
    assert emitter.observe_histogram("chunk_duration", 12.5) is None
    assert emitter.observe_histogram("chunk_duration", 1.0, labels={"symbol": "WDOJ26"}) is None


@pytest.mark.unit
def test_custom_emitter_satisfies_protocol() -> None:
    """Implementação ad-hoc com 3 métodos canônicos satisfaz Protocol."""

    class _SpyEmitter:
        def __init__(self) -> None:
            self.counters: list[tuple[str, dict[str, str] | None]] = []
            self.gauges: list[tuple[str, float, dict[str, str] | None]] = []
            self.observations: list[tuple[str, float, dict[str, str] | None]] = []

        def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
            self.counters.append((name, labels))

        def set_gauge(
            self, name: str, value: float, *, labels: dict[str, str] | None = None
        ) -> None:
            self.gauges.append((name, value, labels))

        def observe_histogram(
            self, name: str, value: float, *, labels: dict[str, str] | None = None
        ) -> None:
            self.observations.append((name, value, labels))

    spy = _SpyEmitter()
    assert isinstance(spy, MetricsEmitter)
    spy.incr_counter("a")
    spy.set_gauge("b", 1.0, labels={"x": "y"})
    spy.observe_histogram("c", 0.5)
    assert spy.counters == [("a", None)]
    assert spy.gauges == [("b", 1.0, {"x": "y"})]
    assert spy.observations == [("c", 0.5, None)]


@pytest.mark.unit
def test_partial_emitter_does_not_satisfy_protocol() -> None:
    """Implementação parcial (faltando observe_histogram) NÃO satisfaz."""

    class _PartialEmitter:
        def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
            pass

        def set_gauge(
            self, name: str, value: float, *, labels: dict[str, str] | None = None
        ) -> None:
            pass

        # observe_histogram FALTA propositalmente.

    partial = _PartialEmitter()
    assert not isinstance(partial, MetricsEmitter)
