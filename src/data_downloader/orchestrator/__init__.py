"""data_downloader.orchestrator — Coordenação de downloads históricos.

Owner: Dex (impl) | Consult: Nelo (DLL semantics) + Sol (storage handoff).

Responsabilidades:

- ``chunker.py``     — chunking adaptativo de janelas temporais.
- ``calendar.py``    — feriados B3 + dias úteis.
- ``contracts.py``   — resolver de contrato vigente (WDOJ26 etc.).
- ``retry.py``       — timeout + quirk de reconnect 99 % (Nelo).
- ``orchestrator.py``— main loop (consome queue da DLL, entrega ao storage).

Fronteiras (Aria, ARCHITECTURE.md §5):

- Orchestrator NUNCA chama DLL dentro de callback (lei do Nelo §4).
- Orchestrator NUNCA escreve Parquet diretamente — delega para storage.
"""

from __future__ import annotations

from data_downloader.orchestrator.chunker import (
    CHUNK_DAYS,
    ChunkRange,
    chunk_date_range,
    chunk_days_for_symbol,
)
from data_downloader.orchestrator.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
    with_circuit_breaker,
)
from data_downloader.orchestrator.contracts import (
    Contract,
    list_contracts,
    month_from_letter,
    month_letter,
    populate_contracts_from_seed,
    vigent_contract,
)
from data_downloader.orchestrator.contracts_probe import (
    ProbeResult,
    probe_contract,
)
from data_downloader.orchestrator.download_primitive import (
    ChunkResult,
    TradeRecord,
    download_chunk,
)
from data_downloader.orchestrator.orchestrator import (
    JobConfig,
    JobResult,
    Orchestrator,
    OrchestratorMetrics,
)
from data_downloader.orchestrator.retry import (
    RetryError,
    with_retry,
)
from data_downloader.orchestrator.retry_policy import (
    RetryPolicy,
    default_retry_policy,
    policy_from_env,
)
from data_downloader.orchestrator.state_machine import (
    InvalidStateTransition,
    JobState,
    JobStateMachine,
)
from data_downloader.orchestrator.timestamp import (
    format_brt_timestamp,
    parse_brt_timestamp,
)

__all__ = [
    "CHUNK_DAYS",
    "BreakerState",
    "ChunkRange",
    "ChunkResult",
    "CircuitBreaker",
    "CircuitOpenError",
    "Contract",
    "InvalidStateTransition",
    "JobConfig",
    "JobResult",
    "JobState",
    "JobStateMachine",
    "Orchestrator",
    "OrchestratorMetrics",
    "ProbeResult",
    "RetryError",
    "RetryPolicy",
    "TradeRecord",
    "chunk_date_range",
    "chunk_days_for_symbol",
    "default_retry_policy",
    "download_chunk",
    "format_brt_timestamp",
    "list_contracts",
    "month_from_letter",
    "month_letter",
    "parse_brt_timestamp",
    "policy_from_env",
    "populate_contracts_from_seed",
    "probe_contract",
    "vigent_contract",
    "with_circuit_breaker",
    "with_retry",
]
