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
    """``SCHEMA_VERSION`` é a v1.0.0 documentada (SCHEMA.md §1)."""
    assert SCHEMA_VERSION == "1.0.0"


@pytest.mark.unit
def test_pyarrow_schema_has_17_fields() -> None:
    """SCHEMA.md §1.1 declara exatamente 17 campos."""
    schema = pyarrow_schema()
    assert len(schema) == 17


@pytest.mark.unit
def test_pyarrow_schema_field_names() -> None:
    """Nomes batem 1:1 com SCHEMA.md §1.2 (ordem importa para reprodutibilidade)."""
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

    nullable_fields = {"trade_id", "buy_agent_id", "sell_agent_id", "side", "chunk_id"}
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
