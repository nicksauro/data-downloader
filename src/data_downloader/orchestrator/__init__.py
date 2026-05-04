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
from data_downloader.orchestrator.timestamp import (
    format_brt_timestamp,
    parse_brt_timestamp,
)

__all__ = [
    "ChunkResult",
    "Contract",
    "ProbeResult",
    "TradeRecord",
    "download_chunk",
    "format_brt_timestamp",
    "list_contracts",
    "month_from_letter",
    "month_letter",
    "parse_brt_timestamp",
    "populate_contracts_from_seed",
    "probe_contract",
    "vigent_contract",
]
