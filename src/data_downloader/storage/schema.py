"""data_downloader.storage.schema — Schema canônico Parquet v1.1.0.

Owner: Sol (schema/policy) | Impl: Dex (com audit Sol+Nelo).
Ref: ``docs/storage/SCHEMA.md`` v1.1.0 (20 campos).

Este módulo é a fonte de verdade Python do schema. Qualquer mudança AQUI
DEVE refletir mudança em ``SCHEMA.md`` (e vice-versa) — drift = bug.

Política de mudança (R4 — SCHEMA.md §6):

- aditiva (campo novo nullable, default seguro) -> bump minor (1.0.0 -> 1.1.0)
- quebradora (rename, type change, drop, NO->YES nullability) -> bump major

Constantes:
    SCHEMA_VERSION: Versão semver do schema atual (string).
    TRADE_TYPE_NAME: Mapping ``trade_type_id`` (uint8) -> nome legível
        (``TConnectorTradeType``, ``profitdll/Exemplo Delphi/Types/
        LegacyProfitDataTypesU.pas`` L33-L46, 14 valores 0..13).

Funções:
    pyarrow_schema(): retorna ``pa.Schema`` exato do SCHEMA.md §1.2.
    validate_record(record): valida invariantes simples (price > 0,
        quantity > 0, exchange in ('F', 'B'), timestamp_ns > 0).
        Levanta ``IntegrityError`` (público — ADR-011).
    trade_type_name(trade_type_id): resolve id -> nome legível
        (None se id desconhecido).

Tipos:
    TradeRecord: ``TypedDict`` para type-safety em consumidores.
    SchemaIntegrityError: levantada quando o schema descartaria campos
        de um ``TradeRecord`` — NUNCA descartar colunas silenciosamente.

Nelo Council 32 (2026-05-05): release blocker P0 — versão v1.0.0
silenciosamente descartava ``buy_agent_name``, ``sell_agent_name``,
``trade_type_name`` no writer. Schema v1.1.0 (aditivo, R4) inclui esses
3 campos como nullable + writer agora falha LOUDLY se algum campo do
``TradeRecord`` cair fora do schema (ver ``parquet_writer.py``).
"""

from __future__ import annotations

from typing import TypedDict

import pyarrow as pa

from data_downloader.public_api.exceptions import IntegrityError

# Single source-of-truth: ``storage/partition.py`` define o frozenset de
# exchanges válidas (Story 4.31 AC15 — dedup). Re-export local mantido
# para compat de callers internos que ainda importam de ``schema``.
from data_downloader.storage.partition import _VALID_EXCHANGES

SCHEMA_VERSION: str = "1.1.0"
"""Versão semver do schema Parquet atual (Sol — SCHEMA.md §1).

Bump v1.0.0 -> v1.1.0 (aditivo, R4 — SCHEMA.md §6) introduz 3 campos
nullable: ``buy_agent_name``, ``sell_agent_name``, ``trade_type_name``.
Nelo Council 32 release blocker.
"""


# =====================================================================
# TConnectorTradeType — 14 valores enum (LegacyProfitDataTypesU.pas L33-46)
# =====================================================================
# Source canônica: ``profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas``
# L33-46 — ``TTradeType`` enum:
#   ttZero            = 0  (placeholder; aparece em sentinel structs)
#   ttCrossTrade      = 1
#   ttAgressionBuy    = 2
#   ttAgressionSell   = 3
#   ttAuction         = 4
#   ttSurveillance    = 5
#   ttExpit           = 6
#   ttOptionsExercise = 7
#   ttOverTheCounter  = 8
#   ttDerivativeTerm  = 9
#   ttIndex           = 10
#   ttBTC             = 11
#   ttOnBehalf        = 12
#   ttRLP             = 13
# =====================================================================

TRADE_TYPE_NAME: dict[int, str] = {
    0: "Zero",
    1: "CrossTrade",
    2: "AgressionBuy",
    3: "AgressionSell",
    4: "Auction",
    5: "Surveillance",
    6: "Expit",
    7: "OptionsExercise",
    8: "OverTheCounter",
    9: "DerivativeTerm",
    10: "Index",
    11: "BTC",
    12: "OnBehalf",
    13: "RLP",
}
"""Mapping ``trade_type`` (uint8) -> nome legível.

Usado pelo writer (vectorized enrich) para popular a coluna nullable
``trade_type_name`` em v1.1.0. Nelo Council 32 §3.1: SCHEMA.md L33
documentava ``2=normal`` (errado); o valor real é ``ttAgressionBuy``.

Ver ``profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas`` L33-L46
para fonte canônica.
"""


def trade_type_name(trade_type_id: int | None) -> str | None:
    """Resolve ``trade_type_id`` (uint8) -> nome legível.

    Args:
        trade_type_id: Valor 0..13 do struct ``TConnectorTrade.TradeType``,
            ou ``None``.

    Returns:
        Nome humano (ex. ``"AgressionBuy"``) se id em 0..13; ``None`` caso
        contrário (id desconhecido / ``None``). Nunca raises — caller
        decide como lidar com ``None`` (writer persiste como NULL).
    """
    if trade_type_id is None:
        return None
    return TRADE_TYPE_NAME.get(int(trade_type_id))


class SchemaIntegrityError(IntegrityError):
    """Levantada quando o schema descartaria campos de um ``TradeRecord``.

    Nelo Council 32 P0 fix: writer NUNCA pode descartar colunas
    silenciosamente. Se ``TradeRecord`` (orquestrador) tem campos que o
    schema atual não mapeia, ``parquet_writer.py`` levanta esta exception
    (em vez de simplesmente ignorar).

    Distinção semântica de ``IntegrityError``: este é um drift de SCHEMA
    (versão precisa bump), não um trade malformado. Ainda herda de
    ``IntegrityError`` para preservar back-compat de callers que catam
    esta família.
    """


class TradeRecord(TypedDict, total=False):
    """Trade canônico v1.1.0 (20 campos — SCHEMA.md §1.1).

    Type-safe representation para consumidores Python (orchestrator,
    writer, dedup). Reflete 1:1 o ``pa.Schema`` retornado por
    :func:`pyarrow_schema`.

    Campos NOT NULL devem estar presentes; ``total=False`` é só por
    flexibilidade em construções incrementais (writer enriquece o
    registro com ``ingestion_ts_ns``, ``chunk_id``, ``dll_version``,
    ``sequence_within_ns`` antes do flush).

    v1.1.0 (aditivo, Nelo Council 32): adiciona 3 campos nullable
    (resolved names) — ``buy_agent_name``, ``sell_agent_name``,
    ``trade_type_name``. Schema v1.0.0 silenciosamente descartava esses
    campos no writer; v1.1.0 mapeia explicitamente e o writer falha
    LOUDLY se algum outro campo do TradeRecord ficar fora do schema.

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
    # v1.1.0 — agent name resolution (nullable; algumas trades sem agent name).
    buy_agent_name: str | None
    sell_agent_name: str | None
    # v1.1.0 — trade type humano (nullable; id desconhecido -> None).
    trade_type_name: str | None


def pyarrow_schema() -> pa.Schema:
    """Retorna o schema pyarrow canônico v1.1.0.

    20 campos exatamente conforme ``docs/storage/SCHEMA.md`` §1.2 (v1.1.0).
    Esta função é determinística — chamadas repetidas retornam schemas
    estruturalmente idênticos (igualdade via ``pa.Schema.equals``).

    Returns:
        ``pa.Schema`` com os 20 campos canônicos do schema v1.1.0
        (17 v1.0.0 + 3 nullable adicionados em v1.1.0).
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
            # v1.1.0 — agent name resolution (nullable).
            pa.field("buy_agent_name", pa.string(), nullable=True),
            pa.field("sell_agent_name", pa.string(), nullable=True),
            # v1.1.0 — trade type humano (nullable).
            pa.field("trade_type_name", pa.string(), nullable=True),
        ]
    )


def validate_record(record: TradeRecord) -> None:
    """Valida invariantes simples de um trade antes de persistir.

    Cobre IN-PYTHON (defesa em profundidade — primeira linha):

    - INT-4: ``price > 0`` e ``quantity > 0``.
      Q-DRIFT-38 já filtra ``price <= 0`` upstream em ``IngestorThread``;
      manter o check aqui é redundância barata + defesa contra rotas que
      contornam a thread de ingestão.
    - INT-5: ``exchange in {'F', 'B'}``.
    - INT-3 (parcial): ``timestamp_ns > 0``.

    Invariantes DELEGADOS ao schema SQLite + writer Parquet (intencionalmente
    NÃO duplicados aqui — single source of truth):

    - **I1 (Schema-as-Contract — INVARIANTS.md):** writer Parquet falha
      LOUDLY com ``SchemaIntegrityError`` se ``TradeRecord`` traz chaves
      fora do schema declarado. Implementado em ``parquet_writer.py``;
      duplicar aqui exigiria conhecer o schema runtime e abriria drift.
    - **UNIQUE / CHECK constraints do catálogo SQLite:** as tabelas
      ``downloads`` (CHECK em ``status``), ``partitions`` (CHECK em
      ``row_count >= 0`` e ``file_size_bytes > 0``), ``gaps`` (CHECK em
      ``reason`` + PRIMARY KEY ``(symbol, gap_start, gap_end)``) e
      ``contracts`` (CHECK em ``validation_source``) levantam
      ``sqlite3.IntegrityError`` no commit. Validar essas regras em
      Python (a) duplicaria o schema, (b) exigiria SELECT por record
      para checagem de unicidade — caro e fonte de drift.
    - **INT-1 / INT-2 (dedup, monotonicidade cross-partition):** ficam
      em ``INTEGRITY.md`` §2 (queries DuckDB pos-write) e Story 2.1
      (validators executáveis). Não são checados aqui porque exigem
      visão multi-record / multi-partition.

    Aqui é o filtro de "registro obviamente quebrado" antes do writer —
    rejeita o que o schema/writer rejeitariam adiante de qualquer forma,
    mas o faz cedo + com mensagem rica em ``IntegrityError.details``.

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
    "TRADE_TYPE_NAME",
    "SchemaIntegrityError",
    "TradeRecord",
    "pyarrow_schema",
    "trade_type_name",
    "validate_record",
]
