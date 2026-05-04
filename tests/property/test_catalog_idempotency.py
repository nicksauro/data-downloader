"""Property-based tests — storage.catalog idempotência (Story 1.5 AC10).

Hypothesis: para qualquer sequência de N ``register_partition`` chamadas
com os MESMOS argumentos, o estado final do catálogo é equivalente a
executar a operação UMA vez (R5 — idempotência).

Cobre:

- Idempotência por partition_path (UPSERT).
- Idempotência por job_id (re-register não duplica).
- Estado final = unique partitions, sem entradas em _pending_commits.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey


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


def _wr(path: Path, row_count: int) -> WriteResult:
    return WriteResult(
        path=path,
        row_count=row_count,
        first_ts_ns=1_700_000_000_000_000_000,
        last_ts_ns=1_700_000_001_000_000_000,
        checksum_sha256="c" * 64,
        file_size_bytes=path.stat().st_size,
    )


@pytest.mark.property
@given(
    n_repeats=st.integers(min_value=1, max_value=10),
    row_count=st.integers(min_value=0, max_value=1000),
)
@settings(
    deadline=None,
    max_examples=15,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_register_partition_n_times_equiv_one(
    tmp_path_factory: pytest.TempPathFactory, n_repeats: int, row_count: int
) -> None:
    """Property R5: register_partition N vezes (mesmos args) == 1 vez."""
    tmp_path = tmp_path_factory.mktemp("catalog_prop")
    data_dir = tmp_path / "data"
    db_path = data_dir / "history" / "catalog.db"

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    path = _fake_file(data_dir, partition)
    wr = _wr(path, row_count)

    for _ in range(n_repeats):
        cat.register_partition(wr, partition)

    completed = cat.get_completed_partitions("WDOJ26", "F")
    assert len(completed) == 1, (
        f"after {n_repeats} register_partition calls (same args), expected 1 row, "
        f"got {len(completed)}"
    )
    assert completed[0].row_count == row_count
    assert completed[0].partition_path == "F/WDOJ26/2026/03.parquet"

    # _pending_commits sempre vazio após register_partition success.
    conn = cat._conn_or_raise()
    pending = conn.execute("SELECT * FROM _pending_commits").fetchall()
    assert pending == []
    cat.close()


@pytest.mark.property
@given(
    months=st.lists(
        st.integers(min_value=1, max_value=12),
        min_size=1,
        max_size=12,
        unique=True,
    ),
)
@settings(
    deadline=None,
    max_examples=15,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_register_multiple_partitions_idempotent(
    tmp_path_factory: pytest.TempPathFactory, months: list[int]
) -> None:
    """Mesma sequência de register_partition produz estado final estável."""
    tmp_path = tmp_path_factory.mktemp("catalog_multi_prop")
    data_dir = tmp_path / "data"
    db_path = data_dir / "history" / "catalog.db"

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)

    # Round 1.
    for month in months:
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=month)
        path = _fake_file(data_dir, partition)
        cat.register_partition(_wr(path, row_count=10), partition)

    state_round1 = sorted(
        (p.partition_path, p.row_count) for p in cat.get_completed_partitions("WDOJ26", "F")
    )

    # Round 2 — exatamente os mesmos.
    for month in months:
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=month)
        path = _fake_file(data_dir, partition)
        cat.register_partition(_wr(path, row_count=10), partition)

    state_round2 = sorted(
        (p.partition_path, p.row_count) for p in cat.get_completed_partitions("WDOJ26", "F")
    )

    assert state_round1 == state_round2
    assert len(state_round1) == len(set(months))  # 1 row por mês único
    cat.close()
