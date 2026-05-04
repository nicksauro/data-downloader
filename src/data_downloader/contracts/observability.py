"""data_downloader.contracts.observability — MetricsEmitter Protocol (Story 2.4).

Owner: Aria (architect — fronteira de Protocols).
Story 2.4 — AC5 (hook orchestrator via Protocol pattern, sem refactor).

Define a interface mínima entre o **orchestrator** (produtor de eventos
canônicos cool-path) e o **observability backend** (consumidor — Prometheus
exporter, structlog dump, OTEL adapter futuro). Mantém fronteira limpa:

- ``orchestrator/`` NÃO importa ``observability/`` diretamente — depende
  apenas deste Protocol em ``contracts/``.
- ``observability/`` implementa o Protocol e é injetado no orchestrator.
- Default = :class:`NullMetricsEmitter` (zero overhead quando exporter
  desabilitado — opt-in via CLI flag ``--metrics-port``).

LEIS RESPEITADAS:
- R21 (hot-path): emitter NÃO é chamado per-trade — apenas per-chunk
  (responsabilidade do caller — orchestrator).
- ADR-013 §Decisão (Opção A): contadores in-process, lock-free.
- COUNCIL-15: Protocol pattern endossado por Aria (fronteira preservada),
  Pyro (hot path intacto) e Dex (implementação minimalista).

Exemplo de uso::

    class MyMetrics(MetricsEmitter):
        def incr_counter(self, name, *, labels=None):
            log.info(f"counter {name} +1")  # noqa: print (docstring example)
        def set_gauge(self, name, value, *, labels=None): ...
        def observe_histogram(self, name, value, *, labels=None): ...

    orchestrator = Orchestrator(dll, catalog, writer, metrics_emitter=MyMetrics())
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = [
    "MetricsEmitter",
    "NullMetricsEmitter",
]


@runtime_checkable
class MetricsEmitter(Protocol):
    """Interface mínima entre orchestrator (produtor) e backend de métricas.

    Três operações canônicas suficientes para cobrir Counter / Gauge /
    Histogram do Prometheus (e equivalentes em OTEL). Implementações
    concretas vivem em ``observability/`` (Aria fronteira).

    Convenções:
    - ``name`` é o nome lógico SEM prefixo (e.g. ``"chunks_completed_total"``).
      A implementação concreta adiciona o prefixo ``data_downloader_``
      (ADR-013 §Métricas V1).
    - ``labels`` é um mapping ``{label_name: label_value}``. ``None`` =
      sem labels (métrica não-rotulada). Cardinality control é
      responsabilidade da implementação concreta (Pyro — LRU símbolos).
    - Chamadas DEVEM ser thread-safe (Prometheus client garante; Null é
      no-op trivialmente safe).
    - Custo amortizado por chamada DEVE ser O(1) lock-free (<500ns target —
      Pyro `bench_observability_overhead`).
    """

    def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        """Incrementa um Counter monotônico em 1.

        Args:
            name: Nome lógico do counter (sem prefixo ``data_downloader_``).
            labels: Mapping opcional de labels. ``None`` = não-rotulada.
        """
        ...

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        """Seta um Gauge para um valor instantâneo.

        Args:
            name: Nome lógico do gauge (sem prefixo).
            value: Valor numérico instantâneo (e.g. queue depth).
            labels: Mapping opcional de labels.
        """
        ...

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        """Registra observação em um Histogram (e.g. duração em segundos).

        Args:
            name: Nome lógico do histogram (sem prefixo).
            value: Observação numérica (tipicamente segundos).
            labels: Mapping opcional de labels.
        """
        ...


class NullMetricsEmitter:
    """Implementação no-op — default quando exporter desabilitado.

    Garante que o orchestrator pode sempre chamar emitter.* sem
    branching (`if metrics is not None`) — overhead = call + dispatch
    (~80ns Python) sem alocações.

    Pyro: `bench_observability_overhead` valida que NullEmitter adiciona
    <100ns por chamada (zero overhead default — AC6 ADR-013).
    """

    __slots__ = ()

    def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        """No-op — descarta increment."""
        # Intencionalmente vazio. ``name`` e ``labels`` são ignorados
        # (não armazenados, não loggados — zero overhead).

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        """No-op — descarta gauge set."""

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        """No-op — descarta histogram observation."""
