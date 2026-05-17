"""data_downloader.contracts — Protocols compartilhados entre camadas.

Owner: Aria (architect).

Espaço para ``typing.Protocol`` que definem interfaces entre ``dll/``,
``orchestrator/``, ``storage/``, ``ui/`` e ``public_api/`` sem criar
acoplamento estrutural.

Story 1.1 criou apenas o esqueleto; Story 2.4 introduziu o primeiro
Protocol concreto (:class:`MetricsEmitter`); Story 4.28 adicionou os 5
Protocols restantes prometidos em ``ARCHITECTURE.md §6`` (v1.1.0 H21) e
formalizados em ADR-030 — Protocol-First Boundary Policy.

Exports:

- :class:`CatalogProtocol` — fronteira catalog (Story 4.28 / ADR-030).
- :class:`DLLClientProtocol` — fronteira DLL wrapper (Story 4.28 / ADR-030).
- :class:`DownloadHandle` — fronteira public_api handle (Story 4.28 / ADR-030 / ADR-007a).
- :class:`MetricsEmitter` — observability backend (Story 2.4 / ADR-013).
- :class:`NullMetricsEmitter` — no-op metrics impl (Story 2.4).
- :class:`ProgressEmitter` — orchestrator → UI/CLI (Story 4.28 / ADR-030).
- :class:`WriterProtocol` — storage interna (Story 4.28 / ADR-030).

Política de migração (ADR-030 §2.2): callers existentes mantêm imports
concretos; código novo cruzando fronteira de camada DEVE depender via
Protocol. Implementações concretas NÃO herdam (structural subtyping).
"""

from __future__ import annotations

from data_downloader.contracts._protocols import (
    CatalogProtocol,
    DLLClientProtocol,
    DownloadHandle,
    ProgressEmitter,
    WriterProtocol,
)
from data_downloader.contracts.observability import MetricsEmitter, NullMetricsEmitter

__all__: list[str] = [
    "CatalogProtocol",
    "DLLClientProtocol",
    "DownloadHandle",
    "MetricsEmitter",
    "NullMetricsEmitter",
    "ProgressEmitter",
    "WriterProtocol",
]
