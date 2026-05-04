"""data_downloader.storage.partition — Layout de partição (ADR-004).

Owner: Sol (layout) | Impl: Dex.
Ref: ``docs/adr/ADR-004-partition-layout.md``,
``docs/storage/SCHEMA.md`` §3.

Layout canônico:

    data/history/{exchange}/{symbol}/{year:04d}/{month:02d}.parquet

Ex.: ``data/history/F/WDOJ26/2026/03.parquet``.

**Particionamento é IMUTÁVEL em prod** (SCHEMA.md §3) — mudar layout
exige migração explícita de TODOS os arquivos. Esta camada apenas
encapsula a tradução ``PartitionKey <-> Path`` para que outras camadas
não codifiquem o layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Constantes de validação (refletem regras de SCHEMA.md §1.1 + ADR-004).
_VALID_EXCHANGES: frozenset[str] = frozenset({"F", "B"})
_MIN_YEAR: int = 2000  # B3 + ProfitDLL não cobrem antes disso
_MAX_MONTH: int = 12
_MIN_MONTH: int = 1


@dataclass(frozen=True)
class PartitionKey:
    """Chave imutável que identifica unicamente uma partição mensal.

    Atributos:
        exchange: ``"F"`` (BMF) ou ``"B"`` (Bovespa). 1 char.
        symbol: Código do contrato (ex. ``"WDOJ26"``, ``"PETR4"``).
        year: 4 dígitos, >= 2000 (limite ProfitDLL/B3).
        month: 1..12.

    Validação ocorre em ``__post_init__`` — instância inválida nunca é
    construída. ``frozen=True`` permite uso direto como chave de dict.
    """

    exchange: str
    symbol: str
    year: int
    month: int

    def __post_init__(self) -> None:
        if self.exchange not in _VALID_EXCHANGES:
            raise ValueError(
                f"exchange must be one of {sorted(_VALID_EXCHANGES)}, " f"got {self.exchange!r}"
            )
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.year < _MIN_YEAR:
            raise ValueError(f"year must be >= {_MIN_YEAR}, got {self.year}")
        if not (_MIN_MONTH <= self.month <= _MAX_MONTH):
            raise ValueError(f"month must be in [{_MIN_MONTH}, {_MAX_MONTH}], got {self.month}")


def resolve_partition_path(key: PartitionKey, data_dir: Path) -> Path:
    """Resolve o path absoluto de uma partição.

    Encapsula o layout ADR-004:
    ``{data_dir}/history/{exchange}/{symbol}/{year:04d}/{month:02d}.parquet``.

    Args:
        key: Chave da partição.
        data_dir: Raiz dos dados (tipicamente ``./data``).

    Returns:
        Path absoluto do arquivo Parquet (não cria diretórios).
    """
    return (
        data_dir
        / "history"
        / key.exchange
        / key.symbol
        / f"{key.year:04d}"
        / f"{key.month:02d}.parquet"
    )


def parse_partition_path(path: Path) -> PartitionKey | None:
    """Inverso de :func:`resolve_partition_path`.

    Extrai a ``PartitionKey`` de um path conhecido. Útil para
    reconciliação (Story 1.5 — drift report INTEGRITY.md §5).

    Args:
        path: Path candidato (relativo ou absoluto).

    Returns:
        ``PartitionKey`` se o path bate com o layout canônico, senão
        ``None``. Falhas de validação (exchange inválido, ano fora de
        range, etc.) também retornam ``None`` — esta função NÃO levanta.
    """
    parts = path.parts
    # Esperado (tail): ..., 'history', exchange, symbol, year, 'MM.parquet'
    if len(parts) < 5:
        return None

    # Procura "history" como âncora e descasca a partir dali.
    try:
        history_idx = next(i for i, p in enumerate(parts) if p == "history")
    except StopIteration:
        return None

    tail = parts[history_idx + 1 :]
    if len(tail) != 4:
        return None

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
        # Validação de PartitionKey rejeitou — path mal-formado.
        return None


__all__ = [
    "PartitionKey",
    "parse_partition_path",
    "resolve_partition_path",
]
