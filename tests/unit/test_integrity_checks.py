"""Unit tests — validation.integrity (Story 2.1).

Cobre os 6 checks principais de :class:`IntegrityChecker` usando
fixtures Parquet reais escritos via :class:`ParquetWriter` (path
canônico Story 1.4).

- check_no_duplicates — clean dataset PASS; com duplicatas FAIL.
- check_monotonic_timestamps — clean PASS; com regression FAIL.
- check_schema_version_present — Parquet do writer real PASS; Parquet
  sem metadata FAIL.
- check_valid_price_quantity — clean PASS; preço/qty inválido FAIL.
- check_exchange_code_valid — clean PASS; exchange inválida FAIL.
- check_catalog_disk_sync — clean PASS; com drift FAIL.
- run_all — overall_passed correto.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord, pyarrow_schema
from data_downloader.validation.integrity import IntegrityChecker


def _make_trades(n: int = 5, *, base_ts: int = 1_700_000_000_000_000_000) -> list[TradeRecord]:
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base_ts + i * 1_000_000,
            timestamp_str="01/03/2024 00:00:00.000",
            price=5_300.0 + i,
            quantity=10 + i,
            trade_id=i + 1,
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
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def partition() -> PartitionKey:
    return PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)


@pytest.fixture
def clean_dataset(data_dir: Path, db_path: Path, partition: PartitionKey) -> tuple[Catalog, Path]:
    """Dataset limpo: 1 partição com 10 trades, registrada no catálogo."""
    writer = ParquetWriter(data_dir=data_dir)
    result = writer.write(_make_trades(10), partition, dll_version="4.0.0.34")
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    cat.register_partition(result, partition)
    return cat, result.path


@pytest.fixture
def checker(clean_dataset: tuple[Catalog, Path], data_dir: Path) -> IntegrityChecker:
    cat, _ = clean_dataset
    return IntegrityChecker(data_dir=data_dir, catalog=cat)


# ---------------------------------------------------------------------
# Clean dataset: all checks PASS
# ---------------------------------------------------------------------


@pytest.mark.unit
def test_check_no_duplicates_clean_passes(checker: IntegrityChecker) -> None:
    result = checker.check_no_duplicates(symbol="WDOJ26")
    assert result.passed
    assert result.name == "INT-2.no_duplicates"


@pytest.mark.unit
def test_check_monotonic_timestamps_clean_passes(checker: IntegrityChecker) -> None:
    result = checker.check_monotonic_timestamps(symbol="WDOJ26")
    assert result.passed


@pytest.mark.unit
def test_check_schema_version_present_clean_passes(checker: IntegrityChecker) -> None:
    result = checker.check_schema_version_present(symbol="WDOJ26")
    assert result.passed


@pytest.mark.unit
def test_check_valid_price_quantity_clean_passes(checker: IntegrityChecker) -> None:
    result = checker.check_valid_price_quantity(symbol="WDOJ26")
    assert result.passed


@pytest.mark.unit
def test_check_exchange_code_valid_clean_passes(checker: IntegrityChecker) -> None:
    result = checker.check_exchange_code_valid(symbol="WDOJ26")
    assert result.passed


@pytest.mark.unit
def test_check_catalog_disk_sync_clean_passes(checker: IntegrityChecker) -> None:
    result = checker.check_catalog_disk_sync()
    assert result.passed


@pytest.mark.unit
def test_run_all_clean_overall_passed(checker: IntegrityChecker) -> None:
    """Dataset limpo: overall_passed=True; 6 checks executados."""
    report = checker.run_all(symbol="WDOJ26")
    assert report.overall_passed
    assert len(report.checks) == 6
    assert report.hash_canonical  # hash não-vazio
    # Serialização funciona.
    d = report.to_dict()
    assert d["overall_passed"] is True
    assert len(d["checks"]) == 6


# ---------------------------------------------------------------------
# Vacuous PASS: nenhum Parquet
# ---------------------------------------------------------------------


@pytest.mark.unit
def test_check_no_duplicates_no_partitions_returns_vacuous_pass(
    data_dir: Path, db_path: Path
) -> None:
    """Sem nenhuma partição, retorna PASS info-only."""
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    chk = IntegrityChecker(data_dir=data_dir, catalog=cat)
    try:
        result = chk.check_no_duplicates(symbol="NOEXIST")
        assert result.passed
        assert result.severity == "info"
    finally:
        chk.close()
        cat.close()


# ---------------------------------------------------------------------
# Falhas — montadas escrevendo Parquet "corrompido" diretamente.
# ---------------------------------------------------------------------


def _write_raw_parquet(
    path: Path, trades: list[dict[str, object]], *, with_schema_metadata: bool = True
) -> None:
    """Escreve Parquet bypass do ParquetWriter (sem dedup, opcionalmente sem metadata)."""
    schema = pyarrow_schema()
    columns: dict[str, list[object]] = {f.name: [] for f in schema}
    for t in trades:
        for f in schema:
            columns[f.name].append(t.get(f.name))
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    table = pa.Table.from_arrays(arrays, schema=schema)
    if with_schema_metadata:
        table = table.replace_schema_metadata({b"schema_version": b"1.0.0"})
    else:
        table = table.replace_schema_metadata({})  # remove metadata
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


@pytest.mark.unit
def test_check_no_duplicates_with_dups_fails(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Parquet com chave duplicada: FAIL."""
    # Constrói duas linhas IDÊNTICAS em (symbol, ts_ns, trade_id).
    base_ts = 1_700_000_000_000_000_000
    trade = {
        "symbol": "WDOJ26",
        "exchange": "F",
        "timestamp_ns": base_ts,
        "timestamp_str": "01/03/2024 00:00:00.000",
        "price": 5300.0,
        "quantity": 10,
        "trade_id": 42,  # mesma trade_id em ambas
        "trade_type": 2,
        "buy_agent_id": None,
        "sell_agent_id": None,
        "flags": 0,
        "source_callback": "history_v2",
        "side": None,
        "ingestion_ts_ns": base_ts + 1,
        "chunk_id": None,
        "dll_version": "0.0.0+stub",
        "sequence_within_ns": 0,
    }
    parquet_path = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    _write_raw_parquet(parquet_path, [trade, dict(trade)])

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    chk = IntegrityChecker(data_dir=data_dir, catalog=cat)
    try:
        result = chk.check_no_duplicates(symbol="WDOJ26")
        assert not result.passed
        assert result.severity == "critical"
        assert result.evidence is not None
        assert result.evidence["paths_scanned"] == 1
    finally:
        chk.close()
        cat.close()


@pytest.mark.unit
def test_check_valid_price_quantity_with_zero_price_fails(data_dir: Path, db_path: Path) -> None:
    """Parquet com price <= 0 reportado como FAIL."""
    base_ts = 1_700_000_000_000_000_000
    bad_trade = {
        "symbol": "WDOJ26",
        "exchange": "F",
        "timestamp_ns": base_ts,
        "timestamp_str": "01/03/2024 00:00:00.000",
        "price": 0.0,  # inválido
        "quantity": 10,
        "trade_id": 1,
        "trade_type": 2,
        "buy_agent_id": None,
        "sell_agent_id": None,
        "flags": 0,
        "source_callback": "history_v2",
        "side": None,
        "ingestion_ts_ns": base_ts + 1,
        "chunk_id": None,
        "dll_version": "0.0.0+stub",
        "sequence_within_ns": 0,
    }
    parquet_path = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    _write_raw_parquet(parquet_path, [bad_trade])

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    chk = IntegrityChecker(data_dir=data_dir, catalog=cat)
    try:
        result = chk.check_valid_price_quantity(symbol="WDOJ26")
        assert not result.passed
        assert result.severity == "critical"
        assert result.evidence is not None
        assert result.evidence["bad_rows"] == 1
    finally:
        chk.close()
        cat.close()


@pytest.mark.unit
def test_check_schema_version_present_missing_fails(data_dir: Path, db_path: Path) -> None:
    """Parquet sem metadata schema_version: FAIL."""
    base_ts = 1_700_000_000_000_000_000
    trade = {
        "symbol": "WDOJ26",
        "exchange": "F",
        "timestamp_ns": base_ts,
        "timestamp_str": "01/03/2024 00:00:00.000",
        "price": 5300.0,
        "quantity": 10,
        "trade_id": 1,
        "trade_type": 2,
        "buy_agent_id": None,
        "sell_agent_id": None,
        "flags": 0,
        "source_callback": "history_v2",
        "side": None,
        "ingestion_ts_ns": base_ts + 1,
        "chunk_id": None,
        "dll_version": "0.0.0+stub",
        "sequence_within_ns": 0,
    }
    parquet_path = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    _write_raw_parquet(parquet_path, [trade], with_schema_metadata=False)

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    chk = IntegrityChecker(data_dir=data_dir, catalog=cat)
    try:
        result = chk.check_schema_version_present(symbol="WDOJ26")
        assert not result.passed
        assert result.severity == "critical"
    finally:
        chk.close()
        cat.close()


@pytest.mark.unit
def test_check_catalog_disk_sync_with_drift_fails(
    data_dir: Path, db_path: Path, partition: PartitionKey
) -> None:
    """Drift A: arquivo em disco sem entry no catálogo."""
    writer = ParquetWriter(data_dir=data_dir)
    writer.write(_make_trades(5), partition, dll_version="4.0.0.34")
    # Cria catálogo com auto_reconcile=False — drift A não é auto-corrigido.
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    chk = IntegrityChecker(data_dir=data_dir, catalog=cat)
    try:
        result = chk.check_catalog_disk_sync()
        assert not result.passed
        assert result.severity == "high"  # drift A apenas → high (não critical)
    finally:
        chk.close()
        cat.close()


@pytest.mark.unit
def test_run_all_with_partial_failure_overall_false(data_dir: Path, db_path: Path) -> None:
    """Dataset com 1 violação: overall_passed=False, mas alguns checks passam."""
    base_ts = 1_700_000_000_000_000_000
    bad_trade = {
        "symbol": "WDOJ26",
        "exchange": "F",
        "timestamp_ns": base_ts,
        "timestamp_str": "01/03/2024 00:00:00.000",
        "price": -1.0,  # inválido
        "quantity": 10,
        "trade_id": 1,
        "trade_type": 2,
        "buy_agent_id": None,
        "sell_agent_id": None,
        "flags": 0,
        "source_callback": "history_v2",
        "side": None,
        "ingestion_ts_ns": base_ts + 1,
        "chunk_id": None,
        "dll_version": "0.0.0+stub",
        "sequence_within_ns": 0,
    }
    parquet_path = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    _write_raw_parquet(parquet_path, [bad_trade])

    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    chk = IntegrityChecker(data_dir=data_dir, catalog=cat)
    try:
        report = chk.run_all(symbol="WDOJ26")
        assert not report.overall_passed
        # Identifica price/qty como FAIL.
        failed = [c for c in report.checks if not c.passed]
        assert any(c.name == "INT-4.valid_price_quantity" for c in failed)
    finally:
        chk.close()
        cat.close()
