"""data_downloader.contracts — Protocols compartilhados entre camadas.

Owner: Aria (architect).

Espaço para ``typing.Protocol`` e ``ABC``s que definem interfaces entre
``dll/``, ``orchestrator/``, ``storage/`` e ``public_api/`` sem criar
acoplamento estrutural. Story 1.1 criou apenas o esqueleto; Story 2.4
introduz o primeiro Protocol concreto: :class:`MetricsEmitter`
(observability backend interface).

Exports atuais:

- :class:`MetricsEmitter` — Protocol para backends de métricas
  (Prometheus exporter, structlog dump, OTEL adapter).
- :class:`NullMetricsEmitter` — implementação no-op (default).
"""

from __future__ import annotations

from data_downloader.contracts.observability import MetricsEmitter, NullMetricsEmitter

__all__: list[str] = [
    "MetricsEmitter",
    "NullMetricsEmitter",
]
