"""Integration tests — CLI ``migrate`` subcommands (Story 2.3 AC3)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_downloader.cli import app
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord


def _make_trades(n: int) -> list[TradeRecord]:
    base = 1_700_000_000_000_000_000
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base + i * 1_000_000,
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
            ingestion_ts_ns=base + i * 1_000_000 + 1,
            chunk_id=None,
            dll_version="0.0.0+stub",
            sequence_within_ns=0,
        )
        for i in range(n)
    ]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def populated_data_dir(tmp_path: Path) -> Path:
    """Cria data_dir com 1 partição v1.0.0 + catálogo registrado.

    ADR-024 (v1.1.0): o catálogo canônico é ``data/_internal/catalog.db``
    (antes ``data/history/catalog.db``). A CLI ``migrate`` abre o catálogo
    via ``_open_migration_components`` que usa ``_internal/``; o fixture e
    as asserções precisam usar o mesmo path (v1.1.0 task #10 — Quinn QA).
    """
    data_dir = tmp_path / "data"
    catalog = Catalog(
        db_path=data_dir / "_internal" / "catalog.db",
        data_dir=data_dir,
        auto_reconcile=False,
    )
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
    write_result = writer.write(_make_trades(20), partition, dll_version="4.0.0.34")

    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2024, 3, 1),
        requested_end=datetime(2024, 3, 31),
    )
    catalog.register_partition(write_result, partition, job_id=job_id)
    # Força schema_version=1.0.0 para o plan() achar.
    conn = catalog._conn_or_raise()
    conn.execute(
        "UPDATE partitions SET schema_version = '1.0.0' WHERE partition_path = ?",
        ("F/WDOJ26/2024/03.parquet",),
    )
    catalog.close()
    return data_dir


# =====================================================================
# plan
# =====================================================================


@pytest.mark.integration
def test_cli_migrate_plan_lists_partitions(runner: CliRunner, populated_data_dir: Path) -> None:
    """plan exibe partições afetadas + steps."""
    result = runner.invoke(
        app,
        [
            "migrate",
            "plan",
            "--from",
            "1.0.0",
            "--to",
            "1.1.0",
            "--data-dir",
            str(populated_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "1.0.0" in result.output
    assert "1.1.0" in result.output
    assert "F/WDOJ26/2024/03.parquet" in result.output
    assert "DRY-RUN" in result.output


@pytest.mark.integration
def test_cli_migrate_plan_no_path_exits_2(runner: CliRunner, populated_data_dir: Path) -> None:
    """plan retorna exit 2 se não há path."""
    result = runner.invoke(
        app,
        [
            "migrate",
            "plan",
            "--from",
            "1.0.0",
            "--to",
            "9.9.9",
            "--data-dir",
            str(populated_data_dir),
        ],
    )
    assert result.exit_code == 2


# =====================================================================
# execute (com --yes para skip prompt)
# =====================================================================


@pytest.mark.integration
def test_cli_migrate_execute_success(runner: CliRunner, populated_data_dir: Path) -> None:
    """execute --yes migra com sucesso e atualiza catalog."""
    result = runner.invoke(
        app,
        [
            "migrate",
            "execute",
            "--from",
            "1.0.0",
            "--to",
            "1.1.0",
            "--data-dir",
            str(populated_data_dir),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Migração concluída" in result.output
    # Verifica catalog.
    catalog = Catalog(
        db_path=populated_data_dir / "_internal" / "catalog.db",
        data_dir=populated_data_dir,
        auto_reconcile=False,
    )
    try:
        conn = catalog._conn_or_raise()
        row = conn.execute(
            "SELECT schema_version FROM partitions WHERE partition_path = ?",
            ("F/WDOJ26/2024/03.parquet",),
        ).fetchone()
        assert row["schema_version"] == "1.1.0"
    finally:
        catalog.close()


# =====================================================================
# rollback
# =====================================================================


@pytest.mark.integration
def test_cli_migrate_rollback(runner: CliRunner, populated_data_dir: Path) -> None:
    """execute -> rollback restaura catálogo + arquivo."""
    # 1. Execute com run_id fixo.
    result_exec = runner.invoke(
        app,
        [
            "migrate",
            "execute",
            "--from",
            "1.0.0",
            "--to",
            "1.1.0",
            "--data-dir",
            str(populated_data_dir),
            "--yes",
            "--run-id",
            "cli-rb-test",
        ],
    )
    assert result_exec.exit_code == 0, result_exec.output

    # 2. Rollback.
    result_rb = runner.invoke(
        app,
        [
            "migrate",
            "rollback",
            "--run-id",
            "cli-rb-test",
            "--data-dir",
            str(populated_data_dir),
        ],
    )
    assert result_rb.exit_code == 0, result_rb.output
    assert "Rollback concluído" in result_rb.output

    catalog = Catalog(
        db_path=populated_data_dir / "_internal" / "catalog.db",
        data_dir=populated_data_dir,
        auto_reconcile=False,
    )
    try:
        conn = catalog._conn_or_raise()
        row = conn.execute(
            "SELECT schema_version FROM partitions WHERE partition_path = ?",
            ("F/WDOJ26/2024/03.parquet",),
        ).fetchone()
        assert row["schema_version"] == "1.0.0"
    finally:
        catalog.close()


# =====================================================================
# cleanup
# =====================================================================


@pytest.mark.integration
def test_cli_migrate_cleanup_no_backups(runner: CliRunner, populated_data_dir: Path) -> None:
    """cleanup sem .bak retorna 0 removidos."""
    result = runner.invoke(
        app,
        [
            "migrate",
            "cleanup",
            "--older-than",
            "30",
            "--data-dir",
            str(populated_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Cleanup" in result.output
