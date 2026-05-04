"""Integration tests — storage.catalog reconcile (Story 1.5 AC9/AC11).

Cobertura:

- Test 1: drift A (Parquet existe, catálogo não tem) -> auto-corrige no startup.
- Test 2: drift B (catálogo tem, Parquet sumiu) -> reporta + warn.
- Test 3: drift C (checksum diverge) -> reporta + warn.
- Test 4: dataset clean -> reconcile retorna empty report (is_clean True).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord


def _make_trades(n: int = 5) -> list[TradeRecord]:
    base = 1_700_000_000_000_000_000
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base + i * 1_000_000,
            timestamp_str="01/03/2024 00:00:00.000",
            price=5_300.0 + i,
            quantity=10,
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
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def partition() -> PartitionKey:
    return PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)


@pytest.mark.integration
def test_reconcile_drift_a_auto_corrects_on_startup(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Test 1: arquivo Parquet existe sem entry em partitions; auto-corrige (AC11)."""
    # 1. Escreve Parquet sem usar catálogo.
    writer = ParquetWriter(data_dir=data_dir)
    writer.write(_make_trades(20), partition, dll_version="4.0.0.34")

    # 2. Inicia catálogo — deve detectar drift A e auto-corrigir.
    cat = Catalog(db_path=db_path, data_dir=data_dir)

    completed = cat.get_completed_partitions("WDOJ26", "F")
    assert len(completed) == 1, "drift A should be auto-corrected on startup"
    assert completed[0].partition_path == "F/WDOJ26/2026/03.parquet"
    assert completed[0].row_count == 20
    cat.close()


@pytest.mark.integration
def test_reconcile_drift_b_reports_only(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Test 2: catálogo lista, arquivo deletado -> drift B reportado, NUNCA fix."""
    # Escreve + registra.
    writer = ParquetWriter(data_dir=data_dir)
    wr = writer.write(_make_trades(10), partition, dll_version="4.0.0.34")

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    cat.register_partition(wr, partition)

    # Deleta o arquivo manualmente.
    wr.path.unlink()
    assert not wr.path.exists()

    # Reconcile (sem auto_correct mesmo, B nunca é corrigido).
    report = cat.reconcile(auto_correct=True)
    assert "F/WDOJ26/2026/03.parquet" in report.drift_b
    assert report.drift_a == ()
    assert report.drift_c == ()
    assert "F/WDOJ26/2026/03.parquet" not in report.auto_corrected_paths

    # Entrada em partitions ainda existe (B não é auto-fix).
    assert len(cat.get_completed_partitions("WDOJ26", "F")) == 1
    cat.close()


@pytest.mark.integration
def test_reconcile_drift_c_reports_only(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Test 3: arquivo modificado externamente -> drift C reportado, nunca fix."""
    writer = ParquetWriter(data_dir=data_dir)
    wr = writer.write(_make_trades(10), partition, dll_version="4.0.0.34")

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    cat.register_partition(wr, partition)
    cat.close()

    # Re-abre catalog (auto_reconcile default True) — mas primeiro corrompe o arquivo.
    # Modifica o arquivo: append bytes (preservando size != mas mtime muda também).
    # Para drift C precisamos: arquivo existe, size pode bater ou não, checksum diverge.
    # Truque: sobrescreve com mesmo tamanho mas conteúdo diferente.
    original_size = wr.path.stat().st_size
    wr.path.write_bytes(b"X" * original_size)

    cat2 = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    report = cat2.reconcile(auto_correct=True)
    assert "F/WDOJ26/2026/03.parquet" in report.drift_c
    assert "F/WDOJ26/2026/03.parquet" not in report.auto_corrected_paths
    cat2.close()


@pytest.mark.integration
def test_reconcile_clean_dataset_returns_empty(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Test 4: dataset consistente -> is_clean True."""
    writer = ParquetWriter(data_dir=data_dir)
    wr = writer.write(_make_trades(10), partition, dll_version="4.0.0.34")

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    cat.register_partition(wr, partition)

    report = cat.reconcile(auto_correct=False)
    assert report.is_clean
    assert report.drift_a == ()
    assert report.drift_b == ()
    assert report.drift_c == ()
    cat.close()


@pytest.mark.integration
def test_reconcile_ignores_tmp_files(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Reconcile ignora arquivos .tmp.* (não são partições válidas)."""
    writer = ParquetWriter(data_dir=data_dir)
    wr = writer.write(_make_trades(5), partition, dll_version="4.0.0.34")

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    cat.register_partition(wr, partition)

    # Cria arquivo .tmp.* irrelevante.
    tmp = wr.path.parent / "03.parquet.tmp.feedface"
    tmp.write_bytes(b"junk")

    report = cat.reconcile(auto_correct=False)
    assert report.is_clean, f"reconcile should ignore .tmp.* — got {report}"
    cat.close()
