"""Unit tests — storage.schema (Story 1.4).

Cobertura:

- pyarrow schema tem 17 campos exatamente (SCHEMA.md §1.1).
- ``validate_record`` aceita registro válido.
- ``validate_record`` rejeita price <= 0, quantity <= 0, exchange
  inválido, timestamp_ns <= 0 com ``IntegrityError``.
"""

from __future__ import annotations

import pytest

from data_downloader.public_api.exceptions import IntegrityError
from data_downloader.storage.schema import (
    SCHEMA_VERSION,
    TradeRecord,
    pyarrow_schema,
    validate_record,
)


@pytest.mark.unit
def test_schema_version_constant() -> None:
    """``SCHEMA_VERSION`` é a v1.1.0 documentada (SCHEMA.md §1; Story 1.7g
    Nelo Council 32 release blocker P0).
    """
    assert SCHEMA_VERSION == "1.1.0"


@pytest.mark.unit
def test_pyarrow_schema_has_20_fields() -> None:
    """SCHEMA.md §1.1 v1.1.0 declara 20 campos (17 v1.0.0 + 3 aditivos)."""
    schema = pyarrow_schema()
    assert len(schema) == 20


@pytest.mark.unit
def test_pyarrow_schema_field_names() -> None:
    """Nomes batem 1:1 com SCHEMA.md §1.2 v1.1.0 (ordem importa)."""
    expected = [
        "symbol",
        "exchange",
        "timestamp_ns",
        "timestamp_str",
        "price",
        "quantity",
        "trade_id",
        "trade_type",
        "buy_agent_id",
        "sell_agent_id",
        "flags",
        "source_callback",
        "side",
        "ingestion_ts_ns",
        "chunk_id",
        "dll_version",
        "sequence_within_ns",
        # v1.1.0 — Nelo Council 32 release blocker P0:
        "buy_agent_name",
        "sell_agent_name",
        "trade_type_name",
    ]
    assert pyarrow_schema().names == expected


@pytest.mark.unit
def test_pyarrow_schema_nullability() -> None:
    """Campos NOT NULL conforme SCHEMA.md §1.1."""
    schema = pyarrow_schema()
    not_null_fields = {
        "symbol",
        "exchange",
        "timestamp_ns",
        "timestamp_str",
        "price",
        "quantity",
        "trade_type",
        "flags",
        "source_callback",
        "ingestion_ts_ns",
        "dll_version",
        "sequence_within_ns",
    }
    for name in not_null_fields:
        assert not schema.field(name).nullable, f"{name} should be NOT NULL"

    nullable_fields = {
        "trade_id",
        "buy_agent_id",
        "sell_agent_id",
        "side",
        "chunk_id",
        # v1.1.0 — Nelo Council 32 release blocker P0:
        "buy_agent_name",
        "sell_agent_name",
        "trade_type_name",
    }
    for name in nullable_fields:
        assert schema.field(name).nullable, f"{name} should be nullable"


def _valid_record() -> TradeRecord:
    """Helper: registro mínimo válido (todos os campos NOT NULL preenchidos)."""
    return TradeRecord(
        symbol="WDOJ26",
        exchange="F",
        timestamp_ns=1_709_251_200_000_000_000,
        timestamp_str="01/03/2024 00:00:00.000",
        price=5_300.5,
        quantity=10,
        trade_id=42,
        trade_type=2,
        buy_agent_id=None,
        sell_agent_id=None,
        flags=0,
        source_callback="history_v2",
        side=None,
        ingestion_ts_ns=1_709_251_200_000_000_001,
        chunk_id=None,
        dll_version="4.0.0.34",
        sequence_within_ns=0,
    )


@pytest.mark.unit
def test_validate_record_accepts_valid() -> None:
    """Registro válido não levanta."""
    validate_record(_valid_record())


@pytest.mark.unit
def test_validate_record_rejects_zero_price() -> None:
    rec = _valid_record()
    rec["price"] = 0.0
    with pytest.raises(IntegrityError) as ei:
        validate_record(rec)
    assert ei.value.details["field"] == "price"


@pytest.mark.unit
def test_validate_record_rejects_negative_price() -> None:
    rec = _valid_record()
    rec["price"] = -1.0
    with pytest.raises(IntegrityError):
        validate_record(rec)


@pytest.mark.unit
def test_validate_record_rejects_zero_quantity() -> None:
    rec = _valid_record()
    rec["quantity"] = 0
    with pytest.raises(IntegrityError) as ei:
        validate_record(rec)
    assert ei.value.details["field"] == "quantity"


@pytest.mark.unit
def test_validate_record_rejects_negative_quantity() -> None:
    rec = _valid_record()
    rec["quantity"] = -1
    with pytest.raises(IntegrityError):
        validate_record(rec)


@pytest.mark.unit
def test_validate_record_rejects_invalid_exchange() -> None:
    rec = _valid_record()
    rec["exchange"] = "X"
    with pytest.raises(IntegrityError) as ei:
        validate_record(rec)
    assert ei.value.details["field"] == "exchange"


@pytest.mark.unit
def test_validate_record_rejects_zero_timestamp() -> None:
    rec = _valid_record()
    rec["timestamp_ns"] = 0
    with pytest.raises(IntegrityError) as ei:
        validate_record(rec)
    assert ei.value.details["field"] == "timestamp_ns"


# =====================================================================
# Sol Wave 2 — Delegation rationale (validate_record vs schema/writer)
# =====================================================================
#
# `validate_record` cobre INT-3/4/5 in-Python (defesa em profundidade).
# Outras invariantes ficam DELEGADAS ao schema SQLite (catalog) e ao
# writer Parquet (I1 — Schema-as-Contract). Estes tests documentam a
# fronteira para evitar drift entre validador e schema.


@pytest.mark.unit
def test_validate_record_does_not_check_uniqueness_delegates_to_schema() -> None:
    """Sol Wave 2: ``validate_record`` NÃO valida unicidade de records.

    Unicidade (PRIMARY KEY / UNIQUE INDEX) é responsabilidade do schema
    SQLite (catalog ``gaps`` PK, ``partitions`` PK por path). Chamar
    ``validate_record`` duas vezes com o mesmo registro NÃO levanta —
    o validador é stateless. Isso é intencional: duplicar checagem
    em Python exigiria SELECT por record (caro) + criaria drift entre
    validador e schema.
    """
    rec = _valid_record()
    # Duas chamadas consecutivas com o mesmo registro: ambas devem passar.
    validate_record(rec)
    validate_record(rec)  # não levanta — uniqueness não é escopo deste validador


@pytest.mark.unit
def test_validate_record_does_not_check_schema_contract_delegates_to_writer() -> None:
    """Sol Wave 2: ``validate_record`` NÃO valida I1 (Schema-as-Contract).

    Campos extras fora do schema NÃO levantam aqui — quem fail-loudly
    é o ``ParquetWriter`` (``SchemaIntegrityError`` quando o ``TradeRecord``
    traz chave não mapeada). Essa separação evita drift: o writer conhece
    o schema runtime; o validador não.
    """
    rec = _valid_record()
    # Adicionar chave fora do schema: validate_record não tem como saber
    # quais chaves são válidas; ele cobre INT-3/4/5 apenas.
    rec_with_extra = dict(rec)
    rec_with_extra["this_field_does_not_exist_in_schema"] = "spurious"
    # Type-checker não vê esta chave — é intencional para testar tolerância.
    validate_record(rec_with_extra)  # type: ignore[arg-type]
    # Confirmação positiva: writer faria fail-loudly downstream
    # (ver test_storage_schema_v110.py — SchemaIntegrityError suite).


@pytest.mark.unit
def test_validate_record_accepts_volume_zero_quantity_must_be_positive() -> None:
    """Sol Wave 2: documenta que volume == 0 é REJEITADO via INT-4.

    INT-4 (``quantity > 0``) é estrito; INVARIANTS.md não lista um
    invariante "volume_zero permitido" — Q-DRIFT-38 garante que trades
    com volume <= 0 são filtrados em ``IngestorThread``. Este test
    confirma que ``validate_record`` reforça a regra mesmo se algo
    contornar a thread de ingestão.
    """
    rec = _valid_record()
    rec["quantity"] = 0
    with pytest.raises(IntegrityError) as ei:
        validate_record(rec)
    assert ei.value.details["field"] == "quantity"
