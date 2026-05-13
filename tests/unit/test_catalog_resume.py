"""Unit tests — storage.catalog resume/checkpoint (Story 1.5 AC8).

Cobertura:

- Test 1: resume_job de job interrompido retorna pending chunks corretos.
- Test 2: compute_pending_chunks: união requested - completed.
- Test 3: edge case range completamente coberto = empty pending.
- Test 4: get_pending_chunks usa partições associadas ao job.
- Test 5: resume_job em job inexistente levanta ValueError.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.catalog_models import Partition, compute_pending_chunks
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def catalog(data_dir: Path) -> Catalog:
    db_path = data_dir / "history" / "catalog.db"
    return Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


def _fake_file(data_dir: Path, partition: PartitionKey) -> Path:
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


def _wr(path: Path) -> WriteResult:
    return WriteResult(
        path=path,
        row_count=10,
        first_ts_ns=1,
        last_ts_ns=2,
        checksum_sha256="b" * 64,
        file_size_bytes=path.stat().st_size,
    )


@pytest.mark.unit
def test_resume_job_returns_correct_pending(catalog: Catalog, data_dir: Path) -> None:
    """Test 1: job 2026-01..03; meses 1 e 2 baixados; pending = só março."""
    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 1, 1),
        requested_end=datetime(2026, 3, 31, 23, 59, 59),
    )
    # Marca jan e fev como completos.
    for month in (1, 2):
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=month)
        path = _fake_file(data_dir, partition)
        catalog.register_partition(_wr(path), partition, job_id=job_id)

    plan = catalog.resume_job(job_id)
    assert plan.job.job_id == job_id
    assert len(plan.completed_partitions) == 2
    assert {(p.year, p.month) for p in plan.completed_partitions} == {(2026, 1), (2026, 2)}
    # Pending = só março.
    assert len(plan.pending_chunks) == 1
    assert plan.pending_chunks[0].start.month == 3
    assert plan.pending_chunks[0].start.year == 2026
    catalog.close()


@pytest.mark.unit
def test_compute_pending_chunks_union_diff() -> None:
    """Test 2: pending = requested - completed (granularidade mensal)."""
    completed = [
        Partition(
            partition_path="F/WDOJ26/2026/02.parquet",
            symbol="WDOJ26",
            exchange="F",
            year=2026,
            month=2,
            row_count=10,
            first_ts_ns=1,
            last_ts_ns=2,
            schema_version="1.0.0",
            checksum_sha256="x" * 64,
            file_size_bytes=100,
            written_at=datetime(2026, 5, 3),
        ),
    ]
    pending = compute_pending_chunks(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 1, 1),
        requested_end=datetime(2026, 4, 30),
        completed_partitions=completed,
    )
    months = {(c.start.year, c.start.month) for c in pending}
    assert months == {(2026, 1), (2026, 3), (2026, 4)}


@pytest.mark.unit
def test_compute_pending_chunks_fully_covered_returns_empty() -> None:
    """Test 3: range totalmente coberto = lista vazia."""
    completed = [
        Partition(
            partition_path=f"F/WDOJ26/2026/{m:02d}.parquet",
            symbol="WDOJ26",
            exchange="F",
            year=2026,
            month=m,
            row_count=10,
            first_ts_ns=1,
            last_ts_ns=2,
            schema_version="1.0.0",
            checksum_sha256="x" * 64,
            file_size_bytes=100,
            written_at=datetime(2026, 5, 3),
        )
        for m in (1, 2, 3)
    ]
    pending = compute_pending_chunks(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 1, 1),
        requested_end=datetime(2026, 3, 31),
        completed_partitions=completed,
    )
    assert pending == []


@pytest.mark.unit
def test_compute_pending_chunks_filters_by_symbol_exchange() -> None:
    """Partições de outro símbolo/exchange não contam."""
    completed = [
        Partition(
            partition_path="F/WIN26/2026/02.parquet",  # outro símbolo
            symbol="WIN26",
            exchange="F",
            year=2026,
            month=2,
            row_count=10,
            first_ts_ns=1,
            last_ts_ns=2,
            schema_version="1.0.0",
            checksum_sha256="x" * 64,
            file_size_bytes=100,
            written_at=datetime(2026, 5, 3),
        ),
    ]
    pending = compute_pending_chunks(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 1, 1),
        requested_end=datetime(2026, 2, 28),
        completed_partitions=completed,
    )
    # Nenhuma partição do nosso símbolo -> ambos os meses pendentes.
    months = {(c.start.year, c.start.month) for c in pending}
    assert months == {(2026, 1), (2026, 2)}


@pytest.mark.unit
def test_resume_job_invalid_id_raises(catalog: Catalog) -> None:
    """resume_job em job inexistente levanta ValueError."""
    with pytest.raises(ValueError, match="job_id not found"):
        catalog.resume_job("nonexistent")
    catalog.close()


@pytest.mark.unit
def test_compute_pending_chunks_inverted_range_returns_empty() -> None:
    """Edge case: requested_end < requested_start = empty pending."""
    pending = compute_pending_chunks(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 5, 1),
        requested_end=datetime(2026, 1, 1),
        completed_partitions=[],
    )
    assert pending == []


# =====================================================================
# Wave 1B — chunk_ledger (granularidade diária)
# =====================================================================


@pytest.mark.unit
def test_record_chunk_and_completed_days(catalog: Catalog) -> None:
    """record_chunk persiste 1 row/dia; completed_days lê só completed/no_trades."""
    from datetime import date

    catalog.record_chunk(
        symbol="WDOJ26",
        exchange="F",
        chunk_date=date(2018, 1, 2),
        job_id="j1",
        status="completed",
        trades_count=1234,
    )
    catalog.record_chunk(
        symbol="WDOJ26",
        exchange="F",
        chunk_date=date(2018, 1, 3),
        job_id="j1",
        status="no_trades",
        trades_count=0,
    )
    catalog.record_chunk(
        symbol="WDOJ26",
        exchange="F",
        chunk_date=date(2018, 1, 4),
        job_id="j1",
        status="failed",
        trades_count=0,
    )
    done = catalog.completed_days("WDOJ26", "F", date(2018, 1, 1), date(2018, 1, 31))
    assert done == {date(2018, 1, 2), date(2018, 1, 3)}  # failed NÃO conta
    # Range filter.
    assert catalog.completed_days("WDOJ26", "F", date(2018, 1, 3), date(2018, 1, 3)) == {
        date(2018, 1, 3)
    }
    # Outro símbolo não vaza.
    assert catalog.completed_days("WINJ26", "F", date(2018, 1, 1), date(2018, 1, 31)) == set()
    catalog.close()


@pytest.mark.unit
def test_record_chunk_upsert_idempotent(catalog: Catalog) -> None:
    """record_chunk no mesmo (symbol, exchange, date) faz UPSERT (não duplica)."""
    from datetime import date

    catalog.record_chunk(
        symbol="WDOJ26",
        exchange="F",
        chunk_date=date(2020, 5, 4),
        job_id="j1",
        status="failed",
        trades_count=0,
    )
    catalog.record_chunk(
        symbol="WDOJ26",
        exchange="F",
        chunk_date=date(2020, 5, 4),
        job_id="j2",
        status="completed",
        trades_count=999,
    )
    done = catalog.completed_days("WDOJ26", "F", date(2020, 5, 1), date(2020, 5, 31))
    assert done == {date(2020, 5, 4)}  # agora conta (status virou completed)
    catalog.close()
