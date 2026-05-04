"""data_downloader.observability.prometheus_exporter — Prometheus HTTP exporter (Story 2.4).

Owner: Dex (impl) | Audit: Aria (Protocol fronteira), Pyro (overhead/cardinality).
Story 2.4 — V2 deferred de ADR-013 (Opção A escolhida).

Implementa:

1. :class:`PrometheusExporter` — registra métricas canônicas (Counters,
   Gauges, Histograms — ADR-013 §Métricas V1) num
   ``CollectorRegistry`` próprio (isolado do REGISTRY global — facilita
   testes sem fixture global de reset). Implementa
   :class:`~data_downloader.contracts.MetricsEmitter` Protocol.
2. :class:`MultiTargetEmitter` — fan-out para múltiplos backends
   simultaneamente (e.g. Prometheus + log JSON sample).

LEIS RESPEITADAS:
- R21 (hot path): apenas per-chunk increment (orchestrator decide).
- ADR-013 (Opção A): prometheus_client lock-free, O(1) increment.
- Cardinality control: símbolo é label de cardinalidade média (~50 ativos);
  V2 LRU (top-50 + ``other``) é responsabilidade do caller — este exporter
  apenas exposes counters; orchestrator passa o símbolo já normalizado.

Métricas canônicas (ADR-013 §Métricas V1 + COUNCIL-05 §D3):

**Counters** (8):
- ``trades_received_total{symbol}``
- ``parquet_writes_total{symbol}``
- ``dll_reconnects_total``
- ``dll_drops_total{symbol}``
- ``chunks_completed_total{symbol,status}``
- ``download_jobs_total{status}``
- ``parquet_bytes_written_total{symbol}``
- ``dedup_dropped_total{symbol}``

**Gauges** (5):
- ``dll_queue_depth``
- ``write_queue_depth``
- ``ui_progress_queue_depth``
- ``active_downloads``
- ``last_chunk_duration_seconds``

**Histograms** (5):
- ``chunk_duration_seconds{symbol}`` — buckets 1, 5, 10, 30, 60, 300, 900
- ``callback_to_disk_seconds_p99{symbol}`` — buckets 0.001, 0.01, 0.1, 1, 10
- ``parquet_write_duration_seconds`` — buckets 0.001, 0.01, 0.1, 1, 10
- ``dedup_duration_seconds`` — buckets 0.0001, 0.001, 0.01, 0.1, 1
- ``migration_duration_seconds`` — buckets 0.001, 0.01, 0.1, 1, 10
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final
from wsgiref.simple_server import WSGIServer

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    make_wsgi_app,
    start_http_server,
)

from data_downloader.contracts.observability import MetricsEmitter

__all__ = [
    "CANONICAL_COUNTERS",
    "CANONICAL_GAUGES",
    "CANONICAL_HISTOGRAMS",
    "DEFAULT_METRICS_PORT",
    "METRIC_PREFIX",
    "MultiTargetEmitter",
    "PrometheusExporter",
]


log = logging.getLogger("data_downloader.observability.prometheus_exporter")


METRIC_PREFIX: Final[str] = "data_downloader_"
"""Prefixo canônico de todas as métricas (ADR-013 §Métricas V1)."""

DEFAULT_METRICS_PORT: Final[int] = 9090
"""Porta default do exporter HTTP (AC4 — overridable via CLI/env)."""


# =====================================================================
# Especificações canônicas (declarativas — fonte de verdade dos testes)
# =====================================================================


@dataclass(frozen=True)
class _CounterSpec:
    """Spec declarativa de um Counter canônico."""

    name: str
    description: str
    labelnames: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _GaugeSpec:
    """Spec declarativa de um Gauge canônico."""

    name: str
    description: str
    labelnames: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _HistogramSpec:
    """Spec declarativa de um Histogram canônico."""

    name: str
    description: str
    buckets: tuple[float, ...]
    labelnames: tuple[str, ...] = field(default_factory=tuple)


# Counters canônicos — 8 totais (ADR-013 §Métricas V1 + COUNCIL-05 §D3
# adiciona dll_drops_total).
CANONICAL_COUNTERS: Final[tuple[_CounterSpec, ...]] = (
    _CounterSpec(
        name="trades_received_total",
        description="Total de trades recebidos do callback DLL.",
        labelnames=("symbol",),
    ),
    _CounterSpec(
        name="parquet_writes_total",
        description="Total de operações append a Parquet bem-sucedidas.",
        labelnames=("symbol",),
    ),
    _CounterSpec(
        name="parquet_bytes_written_total",
        description="Total de bytes escritos em Parquet.",
        labelnames=("symbol",),
    ),
    _CounterSpec(
        name="dll_reconnects_total",
        description="Total de reconexões DLL (esperado raro — Q11-99 quirk).",
    ),
    _CounterSpec(
        name="dll_drops_total",
        description="Total de drops na fila DLL por back-pressure (V2 — reservado).",
        labelnames=("symbol",),
    ),
    _CounterSpec(
        name="chunks_completed_total",
        description="Total de chunks processados (status: success/failed/cancelled).",
        labelnames=("symbol", "status"),
    ),
    _CounterSpec(
        name="download_jobs_total",
        description=(
            "Total de jobs de download finalizados " "(status: completed/partial/failed/cache_hit)."
        ),
        labelnames=("status",),
    ),
    _CounterSpec(
        name="dedup_dropped_total",
        description="Total de duplicatas detectadas e descartadas pelo writer.",
        labelnames=("symbol",),
    ),
)


# Gauges canônicos — 5 totais.
CANONICAL_GAUGES: Final[tuple[_GaugeSpec, ...]] = (
    _GaugeSpec(
        name="dll_queue_depth",
        description="Tamanho atual da fila DLL (0..100_000 — COUNCIL-02).",
    ),
    _GaugeSpec(
        name="write_queue_depth",
        description="Tamanho atual da fila de write (0..5_000).",
    ),
    _GaugeSpec(
        name="ui_progress_queue_depth",
        description="Tamanho atual da fila de progress UI (0..100).",
    ),
    _GaugeSpec(
        name="active_downloads",
        description="Número de jobs de download ativos no momento.",
    ),
    _GaugeSpec(
        name="last_chunk_duration_seconds",
        description="Duração do último chunk processado (segundos).",
    ),
)


# Histograms canônicos — 5 totais.
CANONICAL_HISTOGRAMS: Final[tuple[_HistogramSpec, ...]] = (
    _HistogramSpec(
        name="chunk_duration_seconds",
        description="Tempo de processamento de um chunk completo.",
        buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 900.0),
        labelnames=("symbol",),
    ),
    _HistogramSpec(
        name="callback_to_disk_seconds_p99",
        description="Latência callback DLL → flush em disco (p99 target).",
        buckets=(0.001, 0.01, 0.1, 1.0, 10.0),
        labelnames=("symbol",),
    ),
    _HistogramSpec(
        name="parquet_write_duration_seconds",
        description="Tempo de uma operação de write batch Parquet.",
        buckets=(0.001, 0.01, 0.1, 1.0, 10.0),
    ),
    _HistogramSpec(
        name="dedup_duration_seconds",
        description="Tempo da operação de deduplicação por batch.",
        buckets=(0.0001, 0.001, 0.01, 0.1, 1.0),
    ),
    _HistogramSpec(
        name="migration_duration_seconds",
        description="Tempo de execução de uma migração schema.",
        buckets=(0.001, 0.01, 0.1, 1.0, 10.0),
    ),
)


# =====================================================================
# PrometheusExporter — implementação principal
# =====================================================================


class PrometheusExporter:
    """Exporter Prometheus — registra métricas canônicas + serve HTTP ``/metrics``.

    Implementa :class:`~data_downloader.contracts.MetricsEmitter` Protocol,
    portanto pode ser injetado diretamente no orchestrator sem
    acoplamento estrutural.

    Args:
        port: Porta HTTP do endpoint ``/metrics`` (default 9090).
        registry: ``CollectorRegistry`` opcional. Default = registry novo
            isolado (recomendado — evita estado global REGISTRY do
            prometheus_client, simplifica testes).

    Example::

        exporter = PrometheusExporter(port=9090)
        exporter.start()
        try:
            exporter.incr_counter("trades_received_total", labels={"symbol": "WDOJ26"})
            exporter.set_gauge("active_downloads", 1)
            exporter.observe_histogram("chunk_duration_seconds", 12.3, labels={"symbol": "WDOJ26"})
        finally:
            exporter.stop()

    Thread-safety: prometheus_client garante operações thread-safe
    (lock-free em CPython com GIL, com locks finos em métricas labeled).
    """

    def __init__(
        self,
        port: int = DEFAULT_METRICS_PORT,
        *,
        registry: CollectorRegistry | None = None,
    ) -> None:
        self._port = port
        self._registry = registry if registry is not None else CollectorRegistry()
        self._server: WSGIServer | None = None
        self._server_thread: threading.Thread | None = None

        # Pre-criação dos coletores — single allocation, single registry.
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

        self._build_metrics()

    # ------------------------------------------------------------------
    # Construção / introspecção
    # ------------------------------------------------------------------

    def _build_metrics(self) -> None:
        """Cria todos os Counters/Gauges/Histograms canônicos no registry.

        Chamado uma vez no ``__init__``. Idempotente apenas se ``registry``
        for novo (default) — registries reutilizados levantarão duplicate
        registration.
        """
        for spec in CANONICAL_COUNTERS:
            self._counters[spec.name] = Counter(
                name=METRIC_PREFIX + spec.name,
                documentation=spec.description,
                labelnames=spec.labelnames,
                registry=self._registry,
            )
        for gspec in CANONICAL_GAUGES:
            self._gauges[gspec.name] = Gauge(
                name=METRIC_PREFIX + gspec.name,
                documentation=gspec.description,
                labelnames=gspec.labelnames,
                registry=self._registry,
            )
        for hspec in CANONICAL_HISTOGRAMS:
            self._histograms[hspec.name] = Histogram(
                name=METRIC_PREFIX + hspec.name,
                documentation=hspec.description,
                labelnames=hspec.labelnames,
                buckets=hspec.buckets,
                registry=self._registry,
            )

    @property
    def registry(self) -> CollectorRegistry:
        """Acesso ao registry interno (útil para tests / introspecção)."""
        return self._registry

    @property
    def port(self) -> int:
        """Porta configurada do exporter."""
        return self._port

    @property
    def is_running(self) -> bool:
        """``True`` se o servidor HTTP foi iniciado e ainda está vivo."""
        return self._server is not None

    # ------------------------------------------------------------------
    # Lifecycle HTTP server
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia o servidor HTTP em ``self._port`` (background daemon thread).

        ``prometheus_client.start_http_server`` cria internamente uma
        ``ThreadingWSGIServer`` daemon — não bloqueia o processo principal.

        Idempotente: chamadas subsequentes são no-op.

        Raises:
            OSError: porta já em uso (caller decide se tenta próxima — AC4).
        """
        if self._server is not None:
            log.debug("PrometheusExporter.start called twice — no-op")
            return

        # ``start_http_server`` retorna ``(server, thread)`` desde
        # prometheus_client 0.20+. Aceita ``registry`` para isolar do global.
        # Bind localhost por default — exporter é local desktop, não-público
        # (segurança: não expor métricas em 0.0.0.0 sem opt-in explícito).
        server, thread = start_http_server(self._port, addr="127.0.0.1", registry=self._registry)
        self._server = server
        self._server_thread = thread

    def stop(self) -> None:
        """Para o servidor HTTP (best-effort).

        Idempotente: se já parado, no-op.
        """
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception as exc:  # pragma: no cover defensive
            log.warning("PrometheusExporter.stop: %s", exc)
        finally:
            self._server = None
            self._server_thread = None

    def __enter__(self) -> PrometheusExporter:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # MetricsEmitter Protocol implementation
    # ------------------------------------------------------------------

    def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        """Incrementa Counter ``name`` em 1.

        Métricas desconhecidas são silenciosamente ignoradas (com log
        warning) — facilita evolução incremental sem quebrar produção.
        """
        counter = self._counters.get(name)
        if counter is None:
            log.warning("PrometheusExporter.incr_counter: unknown counter %r", name)
            return
        if labels:
            counter.labels(**labels).inc()
        else:
            counter.inc()

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        """Seta Gauge ``name`` para ``value``."""
        gauge = self._gauges.get(name)
        if gauge is None:
            log.warning("PrometheusExporter.set_gauge: unknown gauge %r", name)
            return
        if labels:
            gauge.labels(**labels).set(value)
        else:
            gauge.set(value)

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        """Registra observação ``value`` no Histogram ``name``."""
        histogram = self._histograms.get(name)
        if histogram is None:
            log.warning("PrometheusExporter.observe_histogram: unknown histogram %r", name)
            return
        if labels:
            histogram.labels(**labels).observe(value)
        else:
            histogram.observe(value)

    # ------------------------------------------------------------------
    # Introspection helpers (úteis em testes)
    # ------------------------------------------------------------------

    def render_text(self) -> str:
        """Renderiza o snapshot atual em formato Prometheus text exposition.

        Equivalente a um GET ``/metrics`` em-memory — útil para tests sem
        precisar levantar o HTTP server.
        """
        # ``generate_latest`` aceita registry opcional.
        from prometheus_client import generate_latest

        text: str = generate_latest(self._registry).decode("utf-8")
        return text

    def make_wsgi_app(self) -> object:
        """Retorna app WSGI standalone (útil para embedar em outro server)."""
        return make_wsgi_app(self._registry)


# =====================================================================
# MultiTargetEmitter — fan-out
# =====================================================================


class MultiTargetEmitter:
    """Fan-out para múltiplos :class:`MetricsEmitter` simultaneamente.

    Útil quando V1 (structlog dump cool-path) coexiste com V2 (Prometheus
    HTTP) — orchestrator vê uma única instância, mas eventos vão para
    ambos.

    Example::

        prom = PrometheusExporter(port=9090)
        log_emitter = StructlogEmitter()  # hipotético
        emitter = MultiTargetEmitter([prom, log_emitter])
        prom.start()
        Orchestrator(dll, catalog, writer, metrics_emitter=emitter).run(config)

    Implementa :class:`~data_downloader.contracts.MetricsEmitter` Protocol
    (delega cada chamada para todos os targets — sem retry, sem isolation
    entre targets).
    """

    def __init__(self, targets: Iterable[MetricsEmitter]) -> None:
        self._targets: tuple[MetricsEmitter, ...] = tuple(targets)

    @property
    def targets(self) -> tuple[MetricsEmitter, ...]:
        """Tupla imutável dos targets."""
        return self._targets

    def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        for t in self._targets:
            t.incr_counter(name, labels=labels)

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        for t in self._targets:
            t.set_gauge(name, value, labels=labels)

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        for t in self._targets:
            t.observe_histogram(name, value, labels=labels)
