"""Unit tests — storage.migrations._runner (Story 2.3 AC4-AC9).

Cobertura:

- AC4: dry-run não escreve nem .bak.
- AC5: checkpoint resumível (run_id duplicado pula migrated).
- AC6: catalog.partitions.schema_version atualizado.
- AC7: rollback restaura .bak.
- AC9: round-trip + idempotent + rollback + dry-run.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.migrations import MigrationRunner
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def catalog(db_path: Path, data_dir: Path) -> Catalog:
    """Catalog instance — auto_reconcile desligado."""
    return Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


def _make_trades(n: int, *, base_ts: int = 1_700_000_000_000_000_000) -> list[TradeRecord]:
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base_ts + i * 1_000_000,
            timestamp_str="01/03/2024 00:00:00.000",
            price=5_300.0 + i * 0.5,
            quantity=10 + i,
            trade_id=i,
            trade_type=2,
            buy_agent_id=None,
            sell_agent_id=None,
            flags=0,
            source_callback="history_v2",
            side=None,
            ingestion_ts_ns=base_ts + i * 1_000_000 + 1,
            chunk_id=None,
            dll_version="0.0.0+stub",
            sequence_within_ns=0,
        )
        for i in range(n)
    ]


@pytest.fixture
def populated_partition(catalog: Catalog, data_dir: Path) -> tuple[Path, str]:
    """Cria partição v1.0.0 + registra no catálogo. Retorna (path, rel_path)."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
    trades = _make_trades(50)
    write_result = writer.write(trades, partition, dll_version="4.0.0.34")

    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2024, 3, 1),
        requested_end=datetime(2024, 3, 31),
    )
    catalog.register_partition(write_result, partition, job_id=job_id)

    # Força schema_version='1.0.0' (parquet_schema_min_supported é '1.0.0').
    conn = catalog._conn_or_raise()
    conn.execute(
        "UPDATE partitions SET schema_version = '1.0.0' WHERE partition_path = ?",
        ("F/WDOJ26/2024/03.parquet",),
    )
    return write_result.path, "F/WDOJ26/2024/03.parquet"


# =====================================================================
# plan()
# =====================================================================


@pytest.mark.unit
def test_plan_lists_affected_partitions(
    catalog: Catalog, data_dir: Path, populated_partition: tuple[Path, str]
) -> None:
    """plan retorna partições com schema_version=from_v."""
    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    plan = runner.plan("1.0.0", "1.1.0")
    assert len(plan.affected_partitions) == 1
    assert plan.affected_partitions[0] == "F/WDOJ26/2024/03.parquet"
    assert len(plan.steps) == 1
    assert plan.steps[0].from_version == "1.0.0"
    assert plan.steps[0].to_version == "1.1.0"


@pytest.mark.unit
def test_plan_empty_when_no_partitions(catalog: Catalog, data_dir: Path) -> None:
    """plan retorna is_noop=True quando não há partições afetadas."""
    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    plan = runner.plan("1.0.0", "1.1.0")
    assert plan.is_noop


@pytest.mark.unit
def test_plan_no_path_raises(catalog: Catalog, data_dir: Path) -> None:
    """plan levanta se from→to sem migration."""
    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    with pytest.raises(ValueError, match="No migration path"):
        runner.plan("1.0.0", "9.9.9")


# =====================================================================
# execute() — round-trip + idempotent + dry-run + rollback
# =====================================================================


@pytest.mark.unit
def test_execute_round_trip(
    catalog: Catalog,
    data_dir: Path,
    populated_partition: tuple[Path, str],
) -> None:
    """AC9 round_trip: migra partição, lê de volta, campo novo presente."""
    parquet_path, rel_path = populated_partition
    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)

    plan = runner.plan("1.0.0", "1.1.0")
    result = runner.execute(plan)

    assert result.partitions_migrated == 1
    assert result.partitions_failed == 0

    # Arquivo lido tem novo campo.
    table = pq.read_table(parquet_path)
    assert "liquidity_classification" in table.schema.names
    assert table.column("liquidity_classification").null_count == table.num_rows

    # Catalog atualizou schema_version (AC6).
    conn = catalog._conn_or_raise()
    row = conn.execute(
        "SELECT schema_version FROM partitions WHERE partition_path = ?",
        (rel_path,),
    ).fetchone()
    assert row["schema_version"] == "1.1.0"


@pytest.mark.unit
def test_execute_dry_run_no_io(
    catalog: Catalog,
    data_dir: Path,
    populated_partition: tuple[Path, str],
) -> None:
    """AC4: dry-run não toca arquivo, .bak, nem .tmp."""
    parquet_path, _rel_path = populated_partition

    # Snapshot pre-state.
    sha_before = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    mtime_before = parquet_path.stat().st_mtime_ns

    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    plan = runner.plan("1.0.0", "1.1.0")
    result = runner.execute(plan, dry_run=True)

    # Em dry-run, runner ainda registra outcome.
    assert result.partitions_migrated == 1
    # Arquivo não tocado.
    assert hashlib.sha256(parquet_path.read_bytes()).hexdigest() == sha_before
    assert parquet_path.stat().st_mtime_ns == mtime_before
    # Sem .bak.
    assert not parquet_path.with_suffix(".parquet.bak").exists()


@pytest.mark.unit
def test_execute_idempotent_resume(
    catalog: Catalog,
    data_dir: Path,
    populated_partition: tuple[Path, str],
) -> None:
    """AC5: re-executar com mesmo run_id é no-op (skipped)."""
    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)

    plan = runner.plan("1.0.0", "1.1.0")
    r1 = runner.execute(plan, run_id="test-run-001")
    assert r1.partitions_migrated == 1

    # Forçar UPDATE schema_version de volta a 1.0.0 SOMENTE no catalog
    # para o plan() achar a partição de novo. Mas o checkpoint do
    # _migration_log impede re-migração.
    conn = catalog._conn_or_raise()
    conn.execute(
        "UPDATE partitions SET schema_version = '1.0.0' WHERE partition_path = ?",
        ("F/WDOJ26/2024/03.parquet",),
    )
    plan2 = runner.plan("1.0.0", "1.1.0")
    r2 = runner.execute(plan2, run_id="test-run-001")
    # 0 migradas — todas skipped por estar em status='migrated' no log.
    assert r2.partitions_migrated == 0
    assert r2.partitions_skipped == 1


@pytest.mark.unit
def test_execute_rollback_restores_bak(
    catalog: Catalog,
    data_dir: Path,
    populated_partition: tuple[Path, str],
) -> None:
    """AC7: rollback restaura .bak; sha256 do arquivo == sha original."""
    parquet_path, rel_path = populated_partition

    sha_pre = hashlib.sha256(parquet_path.read_bytes()).hexdigest()

    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    plan = runner.plan("1.0.0", "1.1.0")
    result = runner.execute(plan, run_id="rb-test")
    assert result.partitions_migrated == 1

    # Pós-migração: sha mudou.
    sha_post = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    assert sha_post != sha_pre
    # Backup existe.
    backup = parquet_path.with_suffix(".parquet.bak")
    assert backup.exists()

    # Rollback.
    rb = runner.rollback(run_id="rb-test")
    assert rb.partitions_migrated == 1

    # Sha restaurado.
    sha_after_rb = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    assert sha_after_rb == sha_pre

    # Catalog schema_version revertida.
    conn = catalog._conn_or_raise()
    row = conn.execute(
        "SELECT schema_version FROM partitions WHERE partition_path = ?",
        (rel_path,),
    ).fetchone()
    assert row["schema_version"] == "1.0.0"


# =====================================================================
# cleanup_backups
# =====================================================================


@pytest.mark.unit
def test_cleanup_backups_removes_old(catalog: Catalog, data_dir: Path) -> None:
    """cleanup_backups deleta .bak antigos."""
    history = data_dir / "history" / "F" / "WDOJ26" / "2024"
    history.mkdir(parents=True)
    bak = history / "03.parquet.bak"
    bak.write_bytes(b"x" * 100)

    # Força mtime antigo (40 dias).
    import os

    old = bak.stat().st_atime - (40 * 24 * 3600)
    os.utime(bak, (old, old))

    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    removed = runner.cleanup_backups(older_than_days=30)
    assert len(removed) == 1
    assert not bak.exists()


@pytest.mark.unit
def test_cleanup_backups_keeps_recent(catalog: Catalog, data_dir: Path) -> None:
    """cleanup_backups preserva .bak recentes."""
    history = data_dir / "history" / "F" / "WDOJ26" / "2024"
    history.mkdir(parents=True)
    bak = history / "03.parquet.bak"
    bak.write_bytes(b"x" * 100)

    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    removed = runner.cleanup_backups(older_than_days=30)
    assert removed == []
    assert bak.exists()
