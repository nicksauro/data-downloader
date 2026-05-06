"""Integration tests — Migration v1.0.0 → v1.1.0 (Owners Council 2026-05-05 P0).

Cobertura (AC1-AC6 do bug B1):

- AC1: parquet sintético v1.0.0 (10 trades, ``buy_agent_id=1``,
       ``sell_agent_id=2``, ``trade_type=2``) → resultado tem
       ``buy_agent_name="Agent#1"``, ``sell_agent_name="Agent#2"``,
       ``trade_type_name="AgressionBuy"``.
- AC2: migration preserva todos os campos v1.0.0 (price, quantity,
       timestamp_ns etc) byte-a-byte.
- AC3: ``trade_type=99`` (fora de 0..13) → ``trade_type_name="TradeType#99"``.
- AC4: idempotência — rodar 2x produz tabela idêntica
       (schema + valores).
- AC5: schema do output bate exatamente com ``pyarrow_schema()`` v1.1.0.
- AC6: re-escrita pós-migration via ``parquet_writer`` não falha em
       ``_check_no_field_drop`` (smoke E2E migration → write).

Refs:
- Bug B1 (Owners Council 2026-05-05 — Sol+Pax veredito P0).
- Story 1.7g (schema integrity v1.1.0 release blocker).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_downloader.storage.migrations.parquet.v1_0_0_to_v1_1_0 import V100ToV110
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord, pyarrow_schema

# =====================================================================
# Helpers — construção de parquet sintético v1.0.0 (17 colunas)
# =====================================================================


def _v100_schema() -> pa.Schema:
    """Schema v1.0.0 = pyarrow_schema() v1.1.0 SEM os 3 campos resolvidos.

    Espelha exatamente os 17 campos do schema v1.0.0 antigo (SCHEMA.md
    v1.0.0). Ordem é a mesma do schema v1.1.0 atual, sem buy_agent_name /
    sell_agent_name / trade_type_name.
    """
    full = pyarrow_schema()
    drop = {"buy_agent_name", "sell_agent_name", "trade_type_name"}
    return pa.schema([f for f in full if f.name not in drop])


def _make_v100_table(
    n: int = 10,
    *,
    buy_agent_id: int | None = 1,
    sell_agent_id: int | None = 2,
    trade_type: int = 2,
) -> pa.Table:
    """Cria ``pa.Table`` v1.0.0 sintética (17 colunas) com valores
    determinísticos parametrizáveis.

    Fixtures padrões batem com AC1 (id=1, id=2, type=2 → AgressionBuy).
    """
    base = 1_700_000_000_000_000_000
    schema = _v100_schema()

    cols: dict[str, list[object]] = {
        "symbol": ["WDOJ26"] * n,
        "exchange": ["F"] * n,
        "timestamp_ns": [base + i * 1_000_000 for i in range(n)],
        "timestamp_str": ["01/03/2024 00:00:00.000"] * n,
        "price": [5_300.0 + i * 0.5 for i in range(n)],
        "quantity": [10 + i for i in range(n)],
        "trade_id": list(range(n)),
        "trade_type": [trade_type] * n,
        "buy_agent_id": [buy_agent_id] * n,
        "sell_agent_id": [sell_agent_id] * n,
        "flags": [0] * n,
        "source_callback": ["history_v2"] * n,
        "side": [None] * n,
        "ingestion_ts_ns": [base + i * 1_000_000 + 1 for i in range(n)],
        "chunk_id": [None] * n,
        "dll_version": ["0.0.0+stub"] * n,
        "sequence_within_ns": [0] * n,
    }
    arrays = [pa.array(cols[f.name], type=f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def _write_v100_parquet(table: pa.Table, dst: Path) -> None:
    """Escreve parquet v1.0.0 com metadata ``schema_version="1.0.0"``."""
    md = {
        b"schema_version": b"1.0.0",
        b"row_count": str(table.num_rows).encode("utf-8"),
    }
    table_md = table.replace_schema_metadata(md)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(dst, table_md.schema, compression="snappy") as w:
        w.write_table(table_md, row_group_size=100_000)


# =====================================================================
# AC1 — fallback determinístico mapeia ids → nomes corretos
# =====================================================================


@pytest.mark.integration
def test_ac1_migration_resolves_agent_and_trade_type_names() -> None:
    """AC1: parquet v1.0.0 (id=1, id=2, type=2) → Agent#1 / Agent#2 / AgressionBuy."""
    table_v100 = _make_v100_table(n=10, buy_agent_id=1, sell_agent_id=2, trade_type=2)
    migration = V100ToV110()
    result = migration.transform(table_v100)

    # buy_agent_name
    buy_names = result.column("buy_agent_name").to_pylist()
    assert all(n == "Agent#1" for n in buy_names), buy_names

    # sell_agent_name
    sell_names = result.column("sell_agent_name").to_pylist()
    assert all(n == "Agent#2" for n in sell_names), sell_names

    # trade_type_name — TRADE_TYPE_NAME[2] == "AgressionBuy"
    type_names = result.column("trade_type_name").to_pylist()
    assert all(n == "AgressionBuy" for n in type_names), type_names


@pytest.mark.integration
def test_ac1_agent_name_null_when_id_null() -> None:
    """Fallback: ``buy_agent_id=None`` → ``buy_agent_name=None`` (v1.0.0
    permite agent_id NULL; não inventa)."""
    table_v100 = _make_v100_table(n=5, buy_agent_id=None, sell_agent_id=None, trade_type=2)
    result = V100ToV110().transform(table_v100)
    assert result.column("buy_agent_name").to_pylist() == [None] * 5
    assert result.column("sell_agent_name").to_pylist() == [None] * 5
    # trade_type_name continua resolvido (trade_type é NOT NULL).
    assert result.column("trade_type_name").to_pylist() == ["AgressionBuy"] * 5


# =====================================================================
# AC2 — preservação byte-a-byte dos 17 campos v1.0.0
# =====================================================================


@pytest.mark.integration
def test_ac2_migration_preserves_all_v100_fields() -> None:
    """AC2: campos v1.0.0 (price, quantity, timestamp_ns, etc) preservados."""
    table_v100 = _make_v100_table(n=10)
    snapshot = {name: table_v100.column(name).to_pylist() for name in table_v100.column_names}

    result = V100ToV110().transform(table_v100)

    for name, values in snapshot.items():
        migrated = result.column(name).to_pylist()
        assert migrated == values, f"campo {name} sofreu drift na migration"


# =====================================================================
# AC3 — fallback para trade_type fora de 0..13
# =====================================================================


@pytest.mark.integration
def test_ac3_unknown_trade_type_uses_fallback() -> None:
    """AC3: ``trade_type=99`` → ``trade_type_name="TradeType#99"``."""
    table_v100 = _make_v100_table(n=3, trade_type=99)
    result = V100ToV110().transform(table_v100)
    assert result.column("trade_type_name").to_pylist() == ["TradeType#99"] * 3


@pytest.mark.integration
def test_ac3_known_trade_type_zero_resolves_zero() -> None:
    """Edge case: ``trade_type=0`` (``ttZero``) é id válido em
    ``TRADE_TYPE_NAME`` → ``"Zero"``, NÃO ``"TradeType#0"``."""
    table_v100 = _make_v100_table(n=2, trade_type=0)
    result = V100ToV110().transform(table_v100)
    assert result.column("trade_type_name").to_pylist() == ["Zero"] * 2


# =====================================================================
# AC4 — idempotência
# =====================================================================


@pytest.mark.integration
def test_ac4_migration_is_idempotent() -> None:
    """AC4: ``transform(transform(t)) == transform(t)``."""
    table_v100 = _make_v100_table(n=10)
    once = V100ToV110().transform(table_v100)
    twice = V100ToV110().transform(once)

    # Schema idêntico.
    assert once.schema.equals(twice.schema)
    # Mesma quantidade de linhas.
    assert once.num_rows == twice.num_rows
    # Valores byte-a-byte (em todas as colunas).
    for name in once.column_names:
        assert (
            once.column(name).to_pylist() == twice.column(name).to_pylist()
        ), f"idempotência quebrada na coluna {name}"


# =====================================================================
# AC5 — schema bate com pyarrow_schema() v1.1.0
# =====================================================================


@pytest.mark.integration
def test_ac5_output_schema_equals_canonical_v110() -> None:
    """AC5: ``result.schema.equals(pyarrow_schema())`` — ordem + tipos +
    nullability exatos."""
    table_v100 = _make_v100_table(n=10)
    result = V100ToV110().transform(table_v100)

    expected = pyarrow_schema()
    assert result.schema.equals(
        expected, check_metadata=False
    ), f"schema drift: result={result.schema} vs expected={expected}"
    assert len(result.schema) == 20  # 17 v1.0.0 + 3 v1.1.0
    assert result.num_rows == 10


# =====================================================================
# AC6 — smoke E2E: migration → re-write via ParquetWriter
# =====================================================================


@pytest.mark.integration
def test_ac6_post_migration_rewrite_via_parquet_writer(tmp_path: Path) -> None:
    """AC6: após migration, re-escrever os trades via ``ParquetWriter`` não
    dispara ``SchemaIntegrityError`` em ``_check_no_field_drop``.

    Evidência de que migration produz dados compatíveis com pipeline
    v1.1.0 corrente (Story 1.7g fail-loudly).
    """
    table_v100 = _make_v100_table(n=10, buy_agent_id=1, sell_agent_id=2, trade_type=2)
    migrated = V100ToV110().transform(table_v100)

    # Converte cada linha de volta a TradeRecord para passar via writer.
    rows = migrated.to_pylist()
    trades: list[TradeRecord] = []
    for r in rows:
        trades.append(
            TradeRecord(  # type: ignore[typeddict-item]
                symbol=r["symbol"],
                exchange=r["exchange"],
                timestamp_ns=r["timestamp_ns"],
                timestamp_str=r["timestamp_str"],
                price=r["price"],
                quantity=r["quantity"],
                trade_id=r["trade_id"],
                trade_type=r["trade_type"],
                buy_agent_id=r["buy_agent_id"],
                sell_agent_id=r["sell_agent_id"],
                flags=r["flags"],
                source_callback=r["source_callback"],
                side=r["side"],
                ingestion_ts_ns=r["ingestion_ts_ns"],
                chunk_id=r["chunk_id"],
                dll_version=r["dll_version"],
                sequence_within_ns=r["sequence_within_ns"],
                buy_agent_name=r["buy_agent_name"],
                sell_agent_name=r["sell_agent_name"],
                trade_type_name=r["trade_type_name"],
            )
        )

    data_dir = tmp_path / "data"
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
    write_result = writer.write(trades, partition, dll_version="0.0.0+stub")
    assert write_result.path.exists()
    assert write_result.row_count == 10

    # Re-lê e valida que os 3 campos vieram resolvidos.
    rewritten = pq.read_table(write_result.path)
    assert rewritten.column("buy_agent_name").to_pylist() == ["Agent#1"] * 10
    assert rewritten.column("sell_agent_name").to_pylist() == ["Agent#2"] * 10
    assert rewritten.column("trade_type_name").to_pylist() == ["AgressionBuy"] * 10


# =====================================================================
# Smoke E2E disco — write parquet v1.0.0 real → read_old → transform → write_new
# =====================================================================


@pytest.mark.integration
def test_full_pipeline_from_disk_v100_to_v110(tmp_path: Path) -> None:
    """E2E: parquet v1.0.0 em disco → migration usa pipeline real
    (read_old + transform + write_new) → arquivo destino tem schema_version
    metadata = '1.1.0' + verify retorna True."""
    src = tmp_path / "v100.parquet"
    table_v100 = _make_v100_table(n=10, buy_agent_id=7, sell_agent_id=8, trade_type=3)
    _write_v100_parquet(table_v100, src)

    migration = V100ToV110()
    table_read = migration.read_old(src)
    transformed = migration.transform(table_read)
    result = migration.write_new(transformed, src, dry_run=False)

    assert result.status == "migrated"
    assert result.rows == 10

    # Metadata esperado.
    md = pq.read_metadata(src).metadata
    assert md is not None
    assert md.get(b"schema_version") == b"1.1.0"
    assert md.get(b"migrated_from") == b"1.0.0"

    # verify retorna True.
    assert migration.verify(src, src) is True

    # Conteúdo migrado.
    final = pq.read_table(src)
    assert final.column("buy_agent_name").to_pylist() == ["Agent#7"] * 10
    assert final.column("sell_agent_name").to_pylist() == ["Agent#8"] * 10
    assert final.column("trade_type_name").to_pylist() == ["AgressionSell"] * 10  # type 3
