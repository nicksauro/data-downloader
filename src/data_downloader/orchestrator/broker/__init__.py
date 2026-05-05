"""data_downloader.orchestrator.broker — Multi-symbol broker process (Story 4.1).

⚠️ DEAD-CODE — ADR-015 REVOKED em 2026-05-05 (Q17-CLOSED Hipótese B confirmada
por Pichau: licença Nelogica é single-session por chave, segundo init falha).
Substituido por **ADR-022 Single-Session Sequential Download Policy**.

Este sub-package permanece no repo como histórico mock-tested. **NÃO instanciar
em produção** — CLI guard (`src/data_downloader/cli.py` download command)
desabilita `--parallel N>1` e força path single-symbol. Remoção definitiva
agendada para Story 2.X-cleanup futura.

Owner histórico: Aria (architectural authority — ADR-015 REVOKED) | Impl: Dex.
Refs:

- ``docs/adr/ADR-015-multiprocess-catalog.md`` (REVOKED, supersede ADR-022)
- ``docs/adr/ADR-022-single-session-sequential-policy.md`` (substitui)
- ``docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md`` (impl decisions histórico)
- Story 4.1 — AC1..AC8 (Deprecated 2026-05-05)
- ``docs/dll/QUIRKS.md`` §Q17-CLOSED

Sub-package que implementa fielmente Opção A do ADR-015: master process
mantém a única conexão R/W SQLite (broker thread); workers (subprocess) enviam
mutações via ``multiprocessing.Queue`` com protocolo ACK.

Componentes:

- :class:`CatalogBroker` — thread no master que serializa SQLite writes (AC1).
- :class:`BrokerCatalogClient` — stub no worker que emula ``Catalog`` via Queue
  + ACK (AC2 + AC4).
- :class:`WorkerPool` — pool persistente N workers aquecidos (AC5 — H20 mitigação).
- :class:`MultiSymbolMaster` — high-level coordinator (AC6 CLI multi-symbol).
- :class:`BrokerRequest`/:class:`BrokerResponse` — protocolo IPC (request_id UUID).
- :class:`BrokerProtocol` — enum dos message types.

Fronteiras (Aria, ADR-015):

- Workers NÃO abrem conexão R/W SQLite — só broker abre (INV-6).
- Workers podem abrir SQLite R/O (idempotência check) — sem race com WAL.
- Toda mutação é síncrona do worker (envia + aguarda ACK) — preserva
  contrato R5 (idempotência).
- Pool persistente (não spawn-per-job) — H20 mitigação obrigatória.
"""

from __future__ import annotations

from data_downloader.orchestrator.broker.catalog_broker import (
    CatalogBroker,
    CatalogBrokerError,
)
from data_downloader.orchestrator.broker.master import (
    MultiSymbolJobConfig,
    MultiSymbolMaster,
)
from data_downloader.orchestrator.broker.pool import (
    JobOutcome,
    JobSpec,
    PoolConfig,
    WorkerPool,
)
from data_downloader.orchestrator.broker.protocol import (
    BrokerProtocol,
    BrokerRequest,
    BrokerResponse,
    BrokerTimeoutError,
)
from data_downloader.orchestrator.broker.worker_client import (
    BrokerCatalogClient,
)

__all__ = [
    "BrokerCatalogClient",
    "BrokerProtocol",
    "BrokerRequest",
    "BrokerResponse",
    "BrokerTimeoutError",
    "CatalogBroker",
    "CatalogBrokerError",
    "JobOutcome",
    "JobSpec",
    "MultiSymbolJobConfig",
    "MultiSymbolMaster",
    "PoolConfig",
    "WorkerPool",
]
