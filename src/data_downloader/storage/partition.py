"""data_downloader.storage.partition — Layout HÍBRIDO de partição (ADR-025).

Owner: Sol (layout) | Impl: Dex.
Refs:

- ``docs/adr/ADR-025-parquet-per-day-hybrid.md`` (v1.3.0+, atual)
- ``docs/adr/ADR-004-partition-layout.md`` (legacy mensal)
- ``docs/storage/SCHEMA.md`` §3

Layout canônico (v1.3.0 HÍBRIDO):

- **Partição diária** (``day is not None``):
  ``data/history/{exchange}/{symbol}/{year:04d}/{month:02d}/{day:02d}.parquet``
- **Partição mensal compactada** (``day is None``):
  ``data/history/{exchange}/{symbol}/{year:04d}/{month:02d}.parquet``

Ex.: ``data/history/F/WDOJ26/2026/03/15.parquet`` (diário) vs.
``data/history/F/WDOJ26/2026/03.parquet`` (mensal compactado).

Política Sol/Aria (ADR-025):

- Writer escreve sempre diário (write-once, sem read-merge-rewrite — fim do O(N²)).
- ``compact_month`` consolida diários → mensal quando todos os dias úteis B3
  daquele (symbol, year, month) foram baixados.
- Read via DuckDB ``parquet_scan('**/*.parquet')`` lê ambos os formatos juntos.

Esta camada apenas encapsula a tradução ``PartitionKey <-> Path`` para que
outras camadas não codifiquem o layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Constantes de validação (refletem regras de SCHEMA.md §1.1 + ADR-004/025).
_VALID_EXCHANGES: frozenset[str] = frozenset({"F", "B"})
_MIN_YEAR: int = 2000  # B3 + ProfitDLL não cobrem antes disso
_MAX_MONTH: int = 12
_MIN_MONTH: int = 1
_MIN_DAY: int = 1
_MAX_DAY: int = 31


@dataclass(frozen=True)
class PartitionKey:
    """Chave imutável que identifica unicamente uma partição.

    Atributos:
        exchange: ``"F"`` (BMF) ou ``"B"`` (Bovespa). 1 char.
        symbol: Código do contrato (ex. ``"WDOJ26"``, ``"PETR4"``).
        year: 4 dígitos, >= 2000 (limite ProfitDLL/B3).
        month: 1..12.
        day: 1..31 se partição diária; ``None`` se partição mensal
            compactada (ADR-025 v1.3.0). Default ``None`` preserva
            compatibilidade com callers v1.2.x.

    Validação ocorre em ``__post_init__`` — instância inválida nunca é
    construída. ``frozen=True`` permite uso direto como chave de dict.
    """

    exchange: str
    symbol: str
    year: int
    month: int
    day: int | None = None

    def __post_init__(self) -> None:
        if self.exchange not in _VALID_EXCHANGES:
            raise ValueError(
                f"exchange must be one of {sorted(_VALID_EXCHANGES)}, got {self.exchange!r}"
            )
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.year < _MIN_YEAR:
            raise ValueError(f"year must be >= {_MIN_YEAR}, got {self.year}")
        if not (_MIN_MONTH <= self.month <= _MAX_MONTH):
            raise ValueError(f"month must be in [{_MIN_MONTH}, {_MAX_MONTH}], got {self.month}")
        if self.day is not None and not (_MIN_DAY <= self.day <= _MAX_DAY):
            raise ValueError(f"day must be in [{_MIN_DAY}, {_MAX_DAY}] or None, got {self.day}")


def resolve_partition_path(key: PartitionKey, data_dir: Path) -> Path:
    """Resolve o path absoluto de uma partição.

    Encapsula o layout ADR-025 (HÍBRIDO):

    - Diário (``day is not None``):
      ``{data_dir}/history/{ex}/{sym}/{YYYY}/{MM}/{DD}.parquet``
    - Mensal compactado (``day is None``):
      ``{data_dir}/history/{ex}/{sym}/{YYYY}/{MM}.parquet``

    Args:
        key: Chave da partição.
        data_dir: Raiz dos dados (tipicamente ``./data``).

    Returns:
        Path absoluto do arquivo Parquet (não cria diretórios).
    """
    base = data_dir / "history" / key.exchange / key.symbol / f"{key.year:04d}"
    if key.day is None:
        return base / f"{key.month:02d}.parquet"
    return base / f"{key.month:02d}" / f"{key.day:02d}.parquet"


def parse_partition_path(path: Path) -> PartitionKey | None:
    """Inverso de :func:`resolve_partition_path`.

    Extrai a ``PartitionKey`` de um path conhecido. Útil para
    reconciliação (Story 1.5 — drift report INTEGRITY.md §5).

    Aceita ambos os layouts ADR-025:

    - 4 segmentos após ``history``: layout mensal (``ex/sym/YYYY/MM.parquet``).
    - 5 segmentos após ``history``: layout diário (``ex/sym/YYYY/MM/DD.parquet``).

    Args:
        path: Path candidato (relativo ou absoluto).

    Returns:
        ``PartitionKey`` se o path bate com um dos layouts; ``None`` caso
        contrário. Falhas de validação (exchange inválido, ano fora de
        range, etc.) também retornam ``None`` — esta função NÃO levanta.
    """
    parts = path.parts
    if len(parts) < 5:
        return None

    try:
        history_idx = next(i for i, p in enumerate(parts) if p == "history")
    except StopIteration:
        return None

    tail = parts[history_idx + 1 :]
    if len(tail) == 4:
        # Layout mensal: exchange/symbol/year/MM.parquet
        exchange, symbol, year_str, month_file = tail
        if not month_file.endswith(".parquet"):
            return None
        try:
            year = int(year_str)
            month = int(month_file.removesuffix(".parquet"))
        except ValueError:
            return None
        try:
            return PartitionKey(exchange=exchange, symbol=symbol, year=year, month=month)
        except ValueError:
            return None

    if len(tail) == 5:
        # Layout diário: exchange/symbol/year/MM/DD.parquet
        exchange, symbol, year_str, month_str, day_file = tail
        if not day_file.endswith(".parquet"):
            return None
        try:
            year = int(year_str)
            month = int(month_str)
            day = int(day_file.removesuffix(".parquet"))
        except ValueError:
            return None
        try:
            return PartitionKey(exchange=exchange, symbol=symbol, year=year, month=month, day=day)
        except ValueError:
            return None

    return None


__all__ = [
    "PartitionKey",
    "parse_partition_path",
    "resolve_partition_path",
]
