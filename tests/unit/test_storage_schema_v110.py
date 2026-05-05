"""Unit tests — storage.schema v1.1.0 (Story 1.7g — Nelo Council 32 P0).

Cobertura:

- Schema v1.1.0 inclui ``buy_agent_name`` / ``sell_agent_name`` /
  ``trade_type_name`` (nullable strings).
- ``TRADE_TYPE_NAME`` mapping completo (14 valores 0..13 — fonte
  ``LegacyProfitDataTypesU.pas``).
- ``trade_type_name`` resolve corretamente ids conhecidos + None para
  ids fora do range.
- ``ParquetWriter.write`` levanta ``SchemaIntegrityError`` se receber
  um ``TradeRecord`` com chave que não está no schema (fail-loudly —
  NUNCA descartar campos silenciosamente).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import (
    SCHEMA_VERSION,
    TRADE_TYPE_NAME,
    SchemaIntegrityError,
    TradeRecord,
    pyarrow_schema,
    trade_type_name,
)

# =====================================================================
# AC1 — schema_v11_includes_agent_names
# =====================================================================


@pytest.mark.unit
def test_schema_version_bumped_to_v110() -> None:
    """v1.0.0 -> v1.1.0 (Nelo Council 32 release blocker P0)."""
    assert SCHEMA_VERSION == "1.1.0"


@pytest.mark.unit
def test_schema_v11_includes_agent_names() -> None:
    """Schema v1.1.0 inclui buy_agent_name + sell_agent_name (nullable)."""
    schema = pyarrow_schema()
    names = schema.names
    assert (
        "buy_agent_name" in names
    ), "Schema v1.1.0 deve incluir buy_agent_name (Nelo Council 32 P0)."
    assert (
        "sell_agent_name" in names
    ), "Schema v1.1.0 deve incluir sell_agent_name (Nelo Council 32 P0)."
    # Ambos nullable (algumas trades sem agent name).
    assert schema.field("buy_agent_name").nullable is True
    assert schema.field("sell_agent_name").nullable is True


@pytest.mark.unit
def test_schema_v11_includes_trade_type_name() -> None:
    """Schema v1.1.0 inclui trade_type_name (string nullable)."""
    schema = pyarrow_schema()
    assert "trade_type_name" in schema.names
    assert schema.field("trade_type_name").nullable is True


@pytest.mark.unit
def test_pyarrow_schema_has_20_fields() -> None:
    """v1.1.0 = 17 (v1.0.0) + 3 nullable aditivos = 20 campos."""
    assert len(pyarrow_schema()) == 20


# =====================================================================
# AC3 — trade_type_id_to_name_mapping_complete (14 valores)
# =====================================================================


@pytest.mark.unit
def test_trade_type_id_to_name_mapping_complete() -> None:
    """``TRADE_TYPE_NAME`` mapeia exatamente 14 valores 0..13.

    Fonte canônica: ``profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas``
    L33-46 (TTradeType enum). Nelo Council 32 §3.1.
    """
    expected = {
        0: "Zero",
        1: "CrossTrade",
        2: "AgressionBuy",  # NÃO "normal" (bug v1.0.0 SCHEMA.md L33)
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
    assert (
        expected == TRADE_TYPE_NAME
    ), "TRADE_TYPE_NAME deve ter 14 valores exatos do enum TTradeType."


@pytest.mark.unit
def test_trade_type_name_resolves_known_ids() -> None:
    """``trade_type_name(id)`` retorna nome humano para 0..13."""
    assert trade_type_name(2) == "AgressionBuy"
    assert trade_type_name(3) == "AgressionSell"
    assert trade_type_name(13) == "RLP"
    assert trade_type_name(0) == "Zero"


@pytest.mark.unit
def test_trade_type_name_returns_none_for_unknown() -> None:
    """ids fora 0..13 retornam None (writer persiste como NULL)."""
    assert trade_type_name(99) is None
    assert trade_type_name(-1) is None
    assert trade_type_name(None) is None


# =====================================================================
# AC2 — writer_raises_on_missing_schema_field (fail-loudly)
# =====================================================================


def _valid_v11_record() -> TradeRecord:
    """Helper: TradeRecord válido para v1.1.0."""
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
        # v1.1.0 fields:
        buy_agent_name=None,
        sell_agent_name=None,
        trade_type_name="AgressionBuy",
    )


@pytest.mark.unit
def test_writer_raises_on_missing_schema_field() -> None:
    """``ParquetWriter.write`` raises ``SchemaIntegrityError`` se record
    tem campo que schema não mapeia (fail-loudly — Nelo Council 32 P0).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = ParquetWriter(data_dir=Path(tmpdir))
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=5)
        bad_record = dict(_valid_v11_record())
        # Adiciona um campo que NÃO existe no schema — deve raise.
        bad_record["future_field_not_in_schema"] = "drift!"  # type: ignore[typeddict-unknown-key]

        with pytest.raises(SchemaIntegrityError) as exc_info:
            writer.write(
                [bad_record],  # type: ignore[list-item]
                partition,
                dll_version="4.0.0.34",
            )

        # Mensagem deve identificar o campo problemático.
        assert "future_field_not_in_schema" in str(exc_info.value)
        # ``details`` deve conter info útil pra debug.
        assert exc_info.value.details["schema_version"] == SCHEMA_VERSION
        assert "future_field_not_in_schema" in exc_info.value.details["missing_in_schema"]


@pytest.mark.unit
def test_writer_accepts_valid_v11_record() -> None:
    """Sanity: writer aceita TradeRecord v1.1.0 sem raise (regression guard)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = ParquetWriter(data_dir=Path(tmpdir))
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
        result = writer.write(
            [_valid_v11_record()],
            partition,
            dll_version="4.0.0.34",
        )
        assert result.row_count == 1
        assert result.path.exists()
