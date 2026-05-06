"""Unit tests — storage.migrations._base + _registry (Story 2.3 AC1/AC2)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_downloader.storage.migrations import (
    Migration,
    MigrationPlan,
    MigrationRegistry,
    MigrationResult,
    MigrationStep,
    ParquetMigration,
)
from data_downloader.storage.migrations.parquet.v1_0_0_to_v1_1_0 import V100ToV110

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def sample_table() -> pa.Table:
    """Tabela v1.0.0 sintética — schema completo de 17 campos.

    Schema v1.0.0 = pyarrow_schema() v1.1.0 SEM os 3 campos resolvidos.
    Necessário para o V100ToV110.transform alcançar o schema canônico
    v1.1.0 (cast preserva ordem/tipos).
    """
    from data_downloader.storage.schema import pyarrow_schema as _full_schema

    full = _full_schema()
    drop = {"buy_agent_name", "sell_agent_name", "trade_type_name"}
    schema_v100 = pa.schema([f for f in full if f.name not in drop])
    n = 3
    base_ts = 1_700_000_000_000_000_000
    cols: dict[str, list[object]] = {
        "symbol": ["WDOJ26"] * n,
        "exchange": ["F"] * n,
        "timestamp_ns": [base_ts + i for i in range(n)],
        "timestamp_str": ["01/03/2024 00:00:00.000"] * n,
        "price": [100.0, 200.0, 300.0],
        "quantity": [10, 20, 30],
        "trade_id": [1, 2, 3],
        "trade_type": [2, 2, 99],
        "buy_agent_id": [1, None, 5],
        "sell_agent_id": [2, 4, None],
        "flags": [0, 0, 0],
        "source_callback": ["history_v2"] * n,
        "side": [None, None, None],
        "ingestion_ts_ns": [base_ts + i + 1 for i in range(n)],
        "chunk_id": [None] * n,
        "dll_version": ["0.0.0+stub"] * n,
        "sequence_within_ns": [0, 0, 0],
    }
    arrays = [pa.array(cols[f.name], type=f.type) for f in schema_v100]
    return pa.Table.from_arrays(arrays, schema=schema_v100)


# =====================================================================
# ABC contract
# =====================================================================


@pytest.mark.unit
def test_migration_is_abstract() -> None:
    """Migration ABC não pode ser instanciada diretamente."""
    with pytest.raises(TypeError):
        Migration()  # type: ignore[abstract]


@pytest.mark.unit
def test_parquet_migration_subclass_must_implement_transform() -> None:
    """ParquetMigration ainda exige `transform` (abstract)."""

    class Bad(ParquetMigration):
        from_version: ClassVar[str] = "1.0.0"
        to_version: ClassVar[str] = "1.1.0"
        breaking: ClassVar[bool] = False
        description: ClassVar[str] = "bad"
        rollback_supported: ClassVar[bool] = True

    with pytest.raises(TypeError):
        Bad()  # type: ignore[abstract]


@pytest.mark.unit
def test_v100_to_v110_metadata() -> None:
    """V100ToV110 declara from/to/breaking corretos.

    Owners Council 2026-05-05 (B1 fix): description menciona os 3 campos
    aditivos reais (``buy_agent_name`` etc), NÃO ``liquidity_classification``.
    """
    m = V100ToV110()
    assert m.from_version == "1.0.0"
    assert m.to_version == "1.1.0"
    assert m.breaking is False
    assert m.rollback_supported is True
    assert "buy_agent_name" in m.description
    assert "sell_agent_name" in m.description
    assert "trade_type_name" in m.description


@pytest.mark.unit
def test_v100_to_v110_transform_adds_three_resolved_fields(sample_table: pa.Table) -> None:
    """transform adiciona ``buy_agent_name`` / ``sell_agent_name`` /
    ``trade_type_name`` (string nullable) com fallback determinístico."""
    m = V100ToV110()
    new_table = m.transform(sample_table)

    for name in m.NEW_FIELD_NAMES:
        assert name in new_table.schema.names
        f = new_table.schema.field(name)
        assert pa.types.is_string(f.type)
        assert f.nullable

    # Fallback: row 0 tem buy_agent_id=1, sell_agent_id=2, trade_type=2.
    assert new_table.column("buy_agent_name").to_pylist()[0] == "Agent#1"
    assert new_table.column("sell_agent_name").to_pylist()[0] == "Agent#2"
    assert new_table.column("trade_type_name").to_pylist()[0] == "AgressionBuy"
    # Row 2: trade_type=99 (fora do dict) → fallback.
    assert new_table.column("trade_type_name").to_pylist()[2] == "TradeType#99"
    # Row 1: buy_agent_id=None → buy_agent_name=None (não inventa).
    assert new_table.column("buy_agent_name").to_pylist()[1] is None


@pytest.mark.unit
def test_v100_to_v110_transform_idempotent(sample_table: pa.Table) -> None:
    """transform aplicado 2x produz schema + valores idênticos."""
    m = V100ToV110()
    once = m.transform(sample_table)
    twice = m.transform(once)
    assert once.schema.equals(twice.schema)
    assert once.num_rows == twice.num_rows
    for name in once.column_names:
        assert once.column(name).to_pylist() == twice.column(name).to_pylist()


@pytest.mark.unit
def test_v100_to_v110_preserves_existing_columns(sample_table: pa.Table) -> None:
    """Campos existentes preservados byte-a-byte (R4)."""
    m = V100ToV110()
    new_table = m.transform(sample_table)
    for col_name in sample_table.column_names:
        original = sample_table.column(col_name).to_pylist()
        migrated = new_table.column(col_name).to_pylist()
        assert original == migrated, f"column {col_name} changed"


@pytest.mark.unit
def test_write_new_dry_run_no_io(sample_table: pa.Table, tmp_path: Path) -> None:
    """AC4 — dry-run não escreve arquivo nem .tmp."""
    m = V100ToV110()
    transformed = m.transform(sample_table)

    dst = tmp_path / "out.parquet"
    result = m.write_new(transformed, dst, dry_run=True)

    assert isinstance(result, MigrationResult)
    assert result.status == "dry_run"
    assert result.bytes_actual == 0
    assert not dst.exists()
    # Sem .tmp.
    assert not list(tmp_path.glob("*.tmp.*"))


@pytest.mark.unit
def test_write_new_real_writes_metadata(sample_table: pa.Table, tmp_path: Path) -> None:
    """write_new real escreve arquivo + metadata schema_version."""
    m = V100ToV110()
    transformed = m.transform(sample_table)
    dst = tmp_path / "out.parquet"
    result = m.write_new(transformed, dst, dry_run=False)

    assert result.status == "migrated"
    assert dst.exists()
    md = pq.read_metadata(dst).metadata
    assert md is not None
    assert md.get(b"schema_version") == b"1.1.0"
    assert md.get(b"migrated_from") == b"1.0.0"


@pytest.mark.unit
def test_verify_after_write(sample_table: pa.Table, tmp_path: Path) -> None:
    """verify retorna True após write_new bem-sucedido."""
    m = V100ToV110()
    transformed = m.transform(sample_table)
    dst = tmp_path / "out.parquet"
    m.write_new(transformed, dst, dry_run=False)
    assert m.verify(dst, dst) is True


# =====================================================================
# Registry
# =====================================================================


@pytest.mark.unit
def test_registry_discover_finds_v100_to_v110() -> None:
    """Registry descobre o exemplo v1.0.0 → v1.1.0."""
    reg = MigrationRegistry.discover()
    assert len(reg) >= 1
    mig = reg.get("1.0.0", "1.1.0")
    assert mig is not None
    assert isinstance(mig, V100ToV110)


@pytest.mark.unit
def test_registry_find_path_same_version() -> None:
    """find_path(v, v) -> []."""
    reg = MigrationRegistry.discover()
    assert reg.find_path("1.0.0", "1.0.0") == []


@pytest.mark.unit
def test_registry_find_path_direct() -> None:
    """find_path direto entre versões registradas."""
    reg = MigrationRegistry.discover()
    chain = reg.find_path("1.0.0", "1.1.0")
    assert len(chain) == 1
    assert chain[0].from_version == "1.0.0"
    assert chain[0].to_version == "1.1.0"


@pytest.mark.unit
def test_registry_find_path_no_route_raises() -> None:
    """find_path levanta se não há path."""
    reg = MigrationRegistry.discover()
    with pytest.raises(ValueError, match="No migration path"):
        reg.find_path("1.0.0", "9.9.9")


@pytest.mark.unit
def test_registry_rejects_invalid_filename(tmp_path: Path) -> None:
    """AC1 — arquivos fora da convenção vão para `invalid_files`."""
    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    # Arquivo válido.
    (parquet_dir / "v1_0_0_to_v1_1_0.py").write_text(
        "from data_downloader.storage.migrations._base import ParquetMigration\n"
        "import pyarrow as pa\n"
        "from typing import ClassVar\n"
        "class Mig(ParquetMigration):\n"
        "    from_version: ClassVar[str] = '1.0.0'\n"
        "    to_version: ClassVar[str] = '1.1.0'\n"
        "    description: ClassVar[str] = 't'\n"
        "    breaking: ClassVar[bool] = False\n"
        "    rollback_supported: ClassVar[bool] = True\n"
        "    def transform(self, t):\n"
        "        return t\n"
    )
    # Arquivo inválido (nome não bate regex).
    (parquet_dir / "random_helper.py").write_text("# nothing")
    # Arquivo com prefix _ é ignorado silenciosamente.
    (parquet_dir / "_private.py").write_text("# private")

    reg = MigrationRegistry.discover(parquet_dir=parquet_dir)
    assert "random_helper.py" in reg.invalid_files
    assert "_private.py" not in reg.invalid_files


# =====================================================================
# Plan / Step dataclasses
# =====================================================================


@pytest.mark.unit
def test_migration_plan_is_noop_empty_partitions() -> None:
    """is_noop True quando affected_partitions está vazio."""
    step = MigrationStep("1.0.0", "1.1.0", "test", False, True)
    plan = MigrationPlan(steps=(step,), affected_partitions=())
    assert plan.is_noop is True


@pytest.mark.unit
def test_migration_plan_is_noop_empty_steps() -> None:
    """is_noop True quando steps vazio."""
    plan = MigrationPlan(steps=(), affected_partitions=("F/WDO/2026/03.parquet",))
    assert plan.is_noop is True
