"""Unit tests — storage.catalog CRUD (Story 1.5 AC4/AC5/AC6/AC13).

Cobertura:

- Test 1: ``register_job`` retorna UUID; status='pending'.
- Test 2: ``update_job_progress`` muda status (AC5).
- Test 3: ``register_partition`` + ``get_completed_partitions``.
- Test 4: ``register_gap`` + lookup por symbol.
- Test 5: ``register_partition`` é idempotente (UPSERT — AC6).
- Test 6: Two-phase commit — ``_pending_commits`` removido após confirm (AC13).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def catalog(db_path: Path, data_dir: Path) -> Catalog:
    """Catalog instance — auto_reconcile desligado para isolar CRUD."""
    return Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


def _fake_partition_file(data_dir: Path, partition: PartitionKey) -> Path:
    """Cria um arquivo Parquet stub no path canônico (sem conteúdo válido)."""
    p = (
        data_dir
        / "history"
        / partition.exchange
        / partition.symbol
        / f"{partition.year:04d}"
        / f"{partition.month:02d}.parquet"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PAR1stub" + b"\x00" * 100)
    return p


def _make_write_result(path: Path, *, row_count: int = 100) -> WriteResult:
    return WriteResult(
        path=path,
        row_count=row_count,
        first_ts_ns=1_700_000_000_000_000_000,
        last_ts_ns=1_700_000_001_000_000_000,
        checksum_sha256="a" * 64,
        file_size_bytes=path.stat().st_size,
    )


@pytest.mark.unit
def test_register_job_returns_uuid_pending(catalog: Catalog) -> None:
    """Test 1: register_job retorna UUID hex; status inicial = 'pending'."""
    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 3, 1),
        requested_end=datetime(2026, 3, 31),
    )
    catalog_close_helper = catalog
    assert isinstance(job_id, str)
    assert len(job_id) == 32  # UUID4 hex
    assert all(c in "0123456789abcdef" for c in job_id)

    job = catalog.get_job(job_id)
    assert job is not None
    assert job.symbol == "WDOJ26"
    assert job.exchange == "F"
    assert job.status == "pending"
    assert job.requested_start == datetime(2026, 3, 1)
    assert job.requested_end == datetime(2026, 3, 31)
    catalog_close_helper.close()


@pytest.mark.unit
def test_update_job_progress_transitions_status(catalog: Catalog) -> None:
    """Test 2: update_job_progress muda status conforme AC5."""
    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 3, 1),
        requested_end=datetime(2026, 3, 31),
    )

    catalog.update_job_progress(job_id, status="in_progress", started_at=datetime(2026, 5, 3, 10))
    j1 = catalog.get_job(job_id)
    assert j1 is not None
    assert j1.status == "in_progress"
    assert j1.started_at == datetime(2026, 5, 3, 10)

    catalog.update_job_progress(
        job_id,
        status="completed",
        completed_at=datetime(2026, 5, 3, 11),
        trades_count=12345,
    )
    j2 = catalog.get_job(job_id)
    assert j2 is not None
    assert j2.status == "completed"
    assert j2.trades_count == 12345
    catalog.close()


@pytest.mark.unit
def test_update_job_progress_invalid_id_raises(catalog: Catalog) -> None:
    """update_job_progress em job inexistente levanta ValueError."""
    with pytest.raises(ValueError, match="job_id not found"):
        catalog.update_job_progress("nonexistent", status="failed")
    catalog.close()


@pytest.mark.unit
def test_update_job_progress_invalid_status_raises(catalog: Catalog) -> None:
    """Status fora do CHECK constraint levanta IntegrityError SQLite."""
    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 3, 1),
        requested_end=datetime(2026, 3, 31),
    )
    with pytest.raises(sqlite3.IntegrityError):
        catalog.update_job_progress(job_id, status="bogus")
    catalog.close()


@pytest.mark.unit
def test_register_partition_then_get(catalog: Catalog, data_dir: Path) -> None:
    """Test 3: register_partition + get_completed_partitions roundtrip."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    path = _fake_partition_file(data_dir, partition)
    wr = _make_write_result(path, row_count=100)

    catalog.register_partition(wr, partition)

    got = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(got) == 1
    p = got[0]
    assert p.partition_path == "F/WDOJ26/2026/03.parquet"
    assert p.symbol == "WDOJ26"
    assert p.exchange == "F"
    assert p.year == 2026
    assert p.month == 3
    assert p.row_count == 100
    assert p.checksum_sha256 == "a" * 64
    catalog.close()


@pytest.mark.unit
def test_register_gap_lookup_by_symbol(catalog: Catalog) -> None:
    """Test 4: register_gap + get_gaps."""
    catalog.register_gap(
        symbol="WDOJ26",
        exchange="F",
        gap_start=datetime(2026, 3, 15, 9),
        gap_end=datetime(2026, 3, 15, 17),
        reason="no_trades",
    )
    gaps = catalog.get_gaps("WDOJ26")
    assert len(gaps) == 1
    g = gaps[0]
    assert g.symbol == "WDOJ26"
    assert g.exchange == "F"
    assert g.reason == "no_trades"
    assert g.gap_start == datetime(2026, 3, 15, 9)
    assert g.gap_end == datetime(2026, 3, 15, 17)
    catalog.close()


@pytest.mark.unit
def test_register_partition_is_idempotent_upsert(catalog: Catalog, data_dir: Path) -> None:
    """Test 5: re-registrar mesma partition_path = UPSERT (AC6)."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    path = _fake_partition_file(data_dir, partition)

    wr1 = _make_write_result(path, row_count=100)
    catalog.register_partition(wr1, partition)

    # Re-registra com row_count diferente — deve atualizar, não duplicar.
    wr2 = _make_write_result(path, row_count=150)
    catalog.register_partition(wr2, partition)

    got = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(got) == 1, "register_partition should UPSERT, not duplicate"
    assert got[0].row_count == 150
    catalog.close()


@pytest.mark.unit
def test_two_phase_commit_clears_pending(catalog: Catalog, data_dir: Path) -> None:
    """Test 6: após register_partition success, _pending_commits está vazio (AC13)."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    path = _fake_partition_file(data_dir, partition)
    wr = _make_write_result(path, row_count=42)

    catalog.register_partition(wr, partition)

    conn = catalog._conn_or_raise()
    rows = conn.execute("SELECT * FROM _pending_commits").fetchall()
    assert rows == [], (
        "_pending_commits should be empty after successful register_partition; "
        f"found {[dict(r) for r in rows]}"
    )

    # E partitions tem a entrada.
    p_rows = conn.execute("SELECT * FROM partitions").fetchall()
    assert len(p_rows) == 1
    catalog.close()


@pytest.mark.unit
def test_register_partition_with_job_id_links(catalog: Catalog, data_dir: Path) -> None:
    """Partition associada a job_id é recuperável via get_completed_partitions."""
    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 3, 1),
        requested_end=datetime(2026, 3, 31),
    )
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    path = _fake_partition_file(data_dir, partition)
    wr = _make_write_result(path)
    catalog.register_partition(wr, partition, job_id=job_id)

    got = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(got) == 1
    assert got[0].job_id == job_id
    catalog.close()
