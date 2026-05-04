"""data_downloader.orchestrator.chunker — Date range chunking (Story 1.7a AC1).

Owner: Dex (impl) | Consult: Pyro (chunk size — COUNCIL-02 / COUNCIL-05),
Sol (calendar handoff via validation.calendar_b3).

Quebra um intervalo ``[start, end]`` em sub-intervalos consumíveis pelo
:func:`download_chunk` (Story 1.3). Granularidade lookup por prefixo de
contrato (decisão COUNCIL-05 §D4):

================  ===================  ===================================
Prefixo           dias úteis B3/chunk  Justificativa
================  ===================  ===================================
``WDO*``          5                    Manual §3.1 Q12-E — futuros mini
``WIN*``          5                    Idem
``IND*``          5                    Índice cheio (alta vazão)
``DOL*``          5                    Dólar cheio
(outros — equity) 1                    Vazão menor; granularidade fina
================  ===================  ===================================

Garantias:

- Chunks cobrem TODOS os dias úteis B3 em ``[start, end]`` (inclusive
  nas duas pontas).
- Sem overlap entre chunks consecutivos.
- Sem gap (dia útil não coberto).
- Fins de semana e feriados B3 são pulados (nunca aparecem em chunk
  ``start``/``end``).
- Resultado é determinístico (mesma entrada = mesma saída).

LEIS RESPEITADAS:
- Pure function — sem I/O, sem state. Trivial para Hypothesis testing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Final

from data_downloader.validation.calendar_b3 import b3_business_days_range

__all__ = [
    "CHUNK_DAYS",
    "DEFAULT_EQUITY_CHUNK_DAYS",
    "ChunkRange",
    "chunk_date_range",
    "chunk_days_for_symbol",
]


# Mapa default — prefixo de contrato → dias úteis B3 por chunk.
# COUNCIL-05 §D4 — Pyro recomenda 5 dias para futuros mini (alta vazão por
# segundo de pregão), 1 dia para equities.
CHUNK_DAYS: Final[Mapping[str, int]] = {
    "WDO": 5,
    "WIN": 5,
    "IND": 5,
    "DOL": 5,
}

DEFAULT_EQUITY_CHUNK_DAYS: Final[int] = 1
"""Default para símbolos sem prefixo conhecido — equities (1 dia útil/chunk)."""


@dataclass(frozen=True)
class ChunkRange:
    """Intervalo ``[start, end]`` (datetime BRT naive) de um chunk.

    Atributos:
        symbol: Contrato vigente (e.g. ``"WDOJ26"``).
        exchange: ``"F"`` ou ``"B"``.
        start: Início do chunk (datetime BRT naive — abertura do 1º dia
            útil; default ``00:00:00``).
        end: Fim do chunk (datetime BRT naive — final do último dia
            útil; default ``23:59:59.999999``).
    """

    symbol: str
    exchange: str
    start: datetime
    end: datetime


def chunk_days_for_symbol(
    symbol: str,
    *,
    chunk_days_map: Mapping[str, int] | None = None,
    default_equity: int = DEFAULT_EQUITY_CHUNK_DAYS,
) -> int:
    """Resolve dias úteis por chunk para um símbolo via prefixo.

    Procura o prefixo mais longo em ``chunk_days_map`` (ou :data:`CHUNK_DAYS`
    default) que corresponde ao início de ``symbol``. Se nenhum bate,
    retorna ``default_equity``.

    Args:
        symbol: Código do contrato (e.g. ``"WDOJ26"`` → prefixo ``"WDO"``).
        chunk_days_map: Override do mapa default. Se ``None``, usa
            :data:`CHUNK_DAYS`.
        default_equity: Fallback quando nenhum prefixo bate (default 1).

    Returns:
        Dias úteis B3 por chunk.
    """
    table = chunk_days_map if chunk_days_map is not None else CHUNK_DAYS
    # Match longest prefix first (defensivo se alguém usa "WDO" e "WDOFUT").
    for prefix in sorted(table, key=len, reverse=True):
        if symbol.startswith(prefix):
            return table[prefix]
    return default_equity


def chunk_date_range(
    symbol: str,
    exchange: str,
    start: date | datetime,
    end: date | datetime,
    *,
    chunk_days_map: Mapping[str, int] | None = None,
    default_equity: int = DEFAULT_EQUITY_CHUNK_DAYS,
) -> list[ChunkRange]:
    """Quebra ``[start, end]`` em :class:`ChunkRange` cobrindo dias úteis B3.

    Algoritmo:

    1. Lista todos os dias úteis B3 em ``[start.date(), end.date()]`` via
       :func:`b3_business_days_range`.
    2. Lookup de ``N = chunk_days_for_symbol(symbol)``.
    3. Particiona a lista em sub-listas de tamanho ``<= N`` (último pode ser menor).
    4. Para cada sub-lista, emite ``ChunkRange`` com:

       - ``start = datetime(primeiro_dia, 00:00:00)``
       - ``end = datetime(último_dia, 23:59:59.999999)``

    Edge cases:

    - ``start > end`` → retorna lista vazia.
    - Range sem nenhum dia útil (e.g. fim de semana puro) → retorna lista vazia.
    - 1 único dia útil → 1 ChunkRange com start=end (mesmo dia).

    Args:
        symbol: Contrato vigente (e.g. ``"WDOJ26"``).
        exchange: ``"F"`` (BMF) ou ``"B"`` (Bovespa).
        start: Data/datetime inicial (inclusive).
        end: Data/datetime final (inclusive).
        chunk_days_map: Override do mapa default. Se ``None``, usa
            :data:`CHUNK_DAYS`.
        default_equity: Fallback quando nenhum prefixo bate (default 1).

    Returns:
        Lista ordenada de :class:`ChunkRange`. Vazia se nenhum dia útil B3
        no range.
    """
    start_d = _to_date(start)
    end_d = _to_date(end)

    business_days = b3_business_days_range(start_d, end_d)
    if not business_days:
        return []

    n_per_chunk = chunk_days_for_symbol(
        symbol,
        chunk_days_map=chunk_days_map,
        default_equity=default_equity,
    )

    chunks: list[ChunkRange] = []
    for i in range(0, len(business_days), n_per_chunk):
        bucket = business_days[i : i + n_per_chunk]
        first = bucket[0]
        last = bucket[-1]
        chunks.append(
            ChunkRange(
                symbol=symbol,
                exchange=exchange,
                start=datetime.combine(first, time(0, 0, 0)),
                end=datetime.combine(last, time(23, 59, 59, 999_999)),
            )
        )
    return chunks


def _to_date(value: date | datetime) -> date:
    """Converte ``date | datetime`` → ``date`` (drop time)."""
    if isinstance(value, datetime):
        return value.date()
    return value
