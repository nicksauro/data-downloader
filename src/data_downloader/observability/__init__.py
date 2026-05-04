"""data_downloader.observability — Métricas runtime via Prometheus (Story 2.4).

Owner: Dex (impl) | Audit: Aria (fronteira Protocol — contracts/observability.py),
Pyro (overhead budget — hot path R21).
Story 2.4 — V2 deferred de ADR-013 antecipada para Epic 2 (smoke MVP).

Subpacote responsável por:

1. **Definir métricas canônicas** (ADR-013 §Métricas V1) — counters, gauges,
   histograms com prefixo ``data_downloader_``.
2. **Servir endpoint HTTP** ``/metrics`` (formato Prometheus exposition)
   via :class:`PrometheusExporter` (opt-in via CLI flag ``--metrics-port``).
3. **Implementar** :class:`~data_downloader.contracts.MetricsEmitter`
   Protocol — orchestrator depende apenas do Protocol em ``contracts/``.
4. **Fan-out** opcional via :class:`MultiTargetEmitter` (Prometheus + log
   sample, etc.).

Default = :class:`~data_downloader.contracts.NullMetricsEmitter` (zero
overhead quando exporter desabilitado — opt-in).

Exemplo de uso::

    from data_downloader.observability import PrometheusExporter
    from data_downloader.orchestrator.orchestrator import Orchestrator

    exporter = PrometheusExporter(port=9090)
    exporter.start()
    try:
        orch = Orchestrator(dll, catalog, writer, metrics_emitter=exporter)
        orch.run(config)
    finally:
        exporter.stop()

LEIS RESPEITADAS:
- R21 (hot path): emitter chamado APENAS per-chunk (cool path) —
  orchestrator nunca chama per-trade.
- ADR-013 (Opção A): prometheus_client lock-free, hot-path safe.
- COUNCIL-15: Aria endossa Protocol; Pyro endossa hot path preservado;
  Dex endossa implementação minimalista opt-in.
"""

from __future__ import annotations

from data_downloader.contracts.observability import MetricsEmitter, NullMetricsEmitter
from data_downloader.observability.prometheus_exporter import (
    CANONICAL_COUNTERS,
    CANONICAL_GAUGES,
    CANONICAL_HISTOGRAMS,
    DEFAULT_METRICS_PORT,
    METRIC_PREFIX,
    MultiTargetEmitter,
    PrometheusExporter,
)

__all__ = [
    "CANONICAL_COUNTERS",
    "CANONICAL_GAUGES",
    "CANONICAL_HISTOGRAMS",
    "DEFAULT_METRICS_PORT",
    "METRIC_PREFIX",
    "MetricsEmitter",
    "MultiTargetEmitter",
    "NullMetricsEmitter",
    "PrometheusExporter",
]
