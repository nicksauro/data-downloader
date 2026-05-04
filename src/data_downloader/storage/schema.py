"""data_downloader.storage.schema — Schema canônico Parquet v1.0.0.

Owner: Sol (schema/policy) | Impl: Dex (com audit Sol).
Ref: ``docs/storage/SCHEMA.md`` v1.0.0 (17 campos).

Este módulo é a fonte de verdade Python do schema. Qualquer mudança AQUI
DEVE refletir mudança em ``SCHEMA.md`` (e vice-versa) — drift = bug.

Política de mudança (R4 — SCHEMA.md §6):

- aditiva (campo novo nullable, default seguro) -> bump minor (1.0.0 -> 1.1.0)
- quebradora (rename, type change, drop, NO->YES nullability) -> bump major

Constantes:
    SCHEMA_VERSION: Versão semver da v1.0.0 (string).

Funções:
    pyarrow_schema(): retorna ``pa.Schema`` exato do SCHEMA.md §1.2.
    validate_record(record): valida invariantes simples (price > 0,
        quantity > 0, exchange in ('F', 'B'), timestamp_ns > 0).
        Levanta ``IntegrityError`` (público — ADR-011).

Tipos:
    TradeRecord: ``TypedDict`` para type-safety em consumidores.
"""

from __future__ import annotations

from typing import TypedDict

import pyarrow as pa

from data_downloader.public_api.exceptions import IntegrityError

SCHEMA_VERSION: str = "1.0.0"
"""Versão semver do schema Parquet v1.0.0 (Sol — SCHEMA.md §1)."""


# Conjunto de exchanges válidas (SCHEMA.md §1.1 + INVARIANTE INT-5).
_VALID_EXCHANGES: frozenset[str] = frozenset({"F", "B"})


class TradeRecord(TypedDict, total=False):
    """Trade canônico v1.0.0 (17 campos — SCHEMA.md §1.1).

    Type-safe representation para consumidores Python (orchestrator,
    writer, dedup). Reflete 1:1 o ``pa.Schema`` retornado por
    :func:`pyarrow_schema`.

    Campos NOT NULL devem estar presentes; ``total=False`` é só por
    flexibilidade em construções incrementais (writer enriquece o
    registro com ``ingestion_ts_ns``, ``chunk_id``, ``dll_version``,
    ``sequence_within_ns`` antes do flush).

    Ver ``docs/storage/SCHEMA.md`` para semântica de cada campo.
    """

    symbol: str
    exchange: str
    timestamp_ns: int
    timestamp_str: str
    price: float
    quantity: int
    trade_id: int | None
    trade_type: int
    buy_agent_id: int | None
    sell_agent_id: int | None
    flags: int
    source_callback: str
    side: int | None
    ingestion_ts_ns: int
    chunk_id: str | None
    dll_version: str
    sequence_within_ns: int


def pyarrow_schema() -> pa.Schema:
    """Retorna o schema pyarrow canônico v1.0.0.

    17 campos exatamente conforme ``docs/storage/SCHEMA.md`` §1.2. Esta
    função é determinística — chamadas repetidas retornam schemas
    estruturalmente idênticos (igualdade via ``pa.Schema.equals``).

    Returns:
        ``pa.Schema`` com os 17 campos canônicos do schema v1.0.0.
    """
    return pa.schema(
        [
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("exchange", pa.string(), nullable=False),
            pa.field("timestamp_ns", pa.int64(), nullable=False),
            pa.field("timestamp_str", pa.string(), nullable=False),
            pa.field("price", pa.float64(), nullable=False),
            pa.field("quantity", pa.int64(), nullable=False),
            pa.field("trade_id", pa.int64(), nullable=True),
            pa.field("trade_type", pa.uint8(), nullable=False),
            pa.field("buy_agent_id", pa.int32(), nullable=True),
            pa.field("sell_agent_id", pa.int32(), nullable=True),
            pa.field("flags", pa.uint32(), nullable=False),
            pa.field("source_callback", pa.string(), nullable=False),
            pa.field("side", pa.uint8(), nullable=True),
            pa.field("ingestion_ts_ns", pa.int64(), nullable=False),
            pa.field("chunk_id", pa.string(), nullable=True),
            pa.field("dll_version", pa.string(), nullable=False),
            pa.field("sequence_within_ns", pa.uint16(), nullable=False),
        ]
    )


def validate_record(record: TradeRecord) -> None:
    """Valida invariantes simples de um trade antes de persistir.

    Cobre:

    - INT-4: ``price > 0`` e ``quantity > 0``.
    - INT-5: ``exchange in {'F', 'B'}``.
    - INT-3 (parcial): ``timestamp_ns > 0``.

    Validações estruturais mais ricas (dedup, monotonicidade,
    cross-partition) ficam em ``INTEGRITY.md`` §2 (queries DuckDB) e na
    Story 2.1 (validators executáveis). Aqui é o filtro de "registro
    obviamente quebrado" antes do writer.

    Args:
        record: Trade candidato (``TradeRecord``).

    Raises:
        IntegrityError: registro viola alguma invariante simples.
            ``.details`` contém o campo ofensor + valor recebido.
    """
    # price obrigatório e > 0 (INT-4)
    price = record.get("price")
    if price is None or price <= 0:
        raise IntegrityError(
            "price must be > 0",
            details={"field": "price", "value": price},
        )

    # quantity obrigatório e > 0 (INT-4)
    quantity = record.get("quantity")
    if quantity is None or quantity <= 0:
        raise IntegrityError(
            "quantity must be > 0",
            details={"field": "quantity", "value": quantity},
        )

    # exchange in {'F', 'B'} (INT-5)
    exchange = record.get("exchange")
    if exchange not in _VALID_EXCHANGES:
        raise IntegrityError(
            "exchange must be one of {'F', 'B'}",
            details={"field": "exchange", "value": exchange},
        )

    # timestamp_ns > 0 (INT-3 parcial)
    timestamp_ns = record.get("timestamp_ns")
    if timestamp_ns is None or timestamp_ns <= 0:
        raise IntegrityError(
            "timestamp_ns must be > 0",
            details={"field": "timestamp_ns", "value": timestamp_ns},
        )


__all__ = [
    "SCHEMA_VERSION",
    "TradeRecord",
    "pyarrow_schema",
    "validate_record",
]
