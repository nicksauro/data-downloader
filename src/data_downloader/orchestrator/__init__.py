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

__all__: list[str] = []
