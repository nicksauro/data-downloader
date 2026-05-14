"""Integration tests — storage.parquet_writer + storage.duckdb_reader (Story 1.4).

Cobertura (ACs 2-9):

- write 100 trades, read back via DuckDBReader -> 100 trades ordenados.
- write 100 trades duas vezes -> 100 trades únicos (idempotência R5).
- write com 10% duplicatas -> 90 únicos.
- schema_version está no metadata Parquet (AC6).
- SHA256 calculado e disponível em WriteResult (AC5).
- tmp file não existe após write success.
- read em diretório vazio retorna pa.Table vazio (não levanta).
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data_downloader.storage.duckdb_reader import DuckDBReader
from data_downloader.storage.parquet_writer import ParquetWriter, WriteResult
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import SCHEMA_VERSION, TradeRecord, pyarrow_schema


def _make_trades(n: int, *, base_ts: int = 1_700_000_000_000_000_000) -> list[TradeRecord]:
    """Gera n trades sintéticos (V2) sequenciais por timestamp."""
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
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def partition() -> PartitionKey:
    return PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)


@pytest.mark.integration
def test_write_then_read_roundtrip(data_dir: Path, partition: PartitionKey) -> None:
    """Test 1: write 100 -> read 100 ordenados."""
    writer = ParquetWriter(data_dir=data_dir)
    trades = _make_trades(100)
    result = writer.write(trades, partition, dll_version="4.0.0.34")

    assert isinstance(result, WriteResult)
    assert result.row_count == 100
    assert result.path.exists()

    with DuckDBReader(data_dir=data_dir) as reader:
        table = reader.read(
            "WDOJ26",
            start_ts_ns=0,
            end_ts_ns=2_000_000_000_000_000_000,
        )
    assert table.num_rows == 100
    # Ordenação asc.
    ts = table.column("timestamp_ns").to_pylist()
    assert ts == sorted(ts)


@pytest.mark.integration
def test_write_idempotent_same_batch(data_dir: Path, partition: PartitionKey) -> None:
    """Test 2: write 100 + write mesmos 100 -> arquivo final tem 100 (R5)."""
    writer = ParquetWriter(data_dir=data_dir)

    # 1ª escrita.
    trades_a = _make_trades(100)
    r1 = writer.write(trades_a, partition, dll_version="4.0.0.34")
    assert r1.row_count == 100

    # 2ª escrita com a mesma lista (deepcopy via re-construção).
    trades_b = _make_trades(100)
    r2 = writer.write(trades_b, partition, dll_version="4.0.0.34")
    assert r2.row_count == 100

    with DuckDBReader(data_dir=data_dir) as reader:
        assert reader.count("WDOJ26") == 100


@pytest.mark.integration
def test_write_dedups_within_batch(data_dir: Path, partition: PartitionKey) -> None:
    """Test 3: 100 sintéticos + 10 duplicatas -> 100 únicos."""
    writer = ParquetWriter(data_dir=data_dir)
    trades = _make_trades(100)
    # Adiciona 10 duplicatas (10 primeiros trades clonados).
    duplicates = _make_trades(10)
    payload = trades + duplicates
    assert len(payload) == 110

    result = writer.write(payload, partition, dll_version="4.0.0.34")
    assert result.row_count == 100

    with DuckDBReader(data_dir=data_dir) as reader:
        assert reader.count("WDOJ26") == 100


@pytest.mark.integration
def test_write_metadata_includes_schema_version(data_dir: Path, partition: PartitionKey) -> None:
    """Test 4: metadata Parquet contém ``schema_version`` (AC6)."""
    writer = ParquetWriter(data_dir=data_dir)
    trades = _make_trades(10)
    result = writer.write(trades, partition, dll_version="4.0.0.34", chunk_id="abc")

    md = pq.read_metadata(result.path).metadata
    assert md is not None
    assert md.get(b"schema_version") == SCHEMA_VERSION.encode("utf-8")
    assert md.get(b"row_count") == b"10"
    assert md.get(b"dll_version") == b"4.0.0.34"
    assert md.get(b"chunk_id") == b"abc"
    assert md.get(b"compression") == b"snappy"
    # ADR-025 v1.3.0 Wave 3 (Pyro): row_group 100k → 1M.
    assert md.get(b"row_group_size") == b"1000000"
    assert b"created_at" in md
    assert b"first_ts_ns" in md
    assert b"last_ts_ns" in md


@pytest.mark.integration
def test_write_result_has_sha256(data_dir: Path, partition: PartitionKey) -> None:
    """Test 5: SHA256 está em WriteResult (AC5) e tem 64 chars hex."""
    writer = ParquetWriter(data_dir=data_dir)
    trades = _make_trades(5)
    result = writer.write(trades, partition, dll_version="4.0.0.34")

    assert isinstance(result.checksum_sha256, str)
    assert len(result.checksum_sha256) == 64
    assert all(c in "0123456789abcdef" for c in result.checksum_sha256)
    assert result.file_size_bytes > 0


@pytest.mark.integration
def test_write_no_orphan_tmp_file(data_dir: Path, partition: PartitionKey) -> None:
    """Test 6: ``.tmp`` não existe após write success."""
    writer = ParquetWriter(data_dir=data_dir)
    trades = _make_trades(5)
    result = writer.write(trades, partition, dll_version="4.0.0.34")

    parent = result.path.parent
    tmp_files = list(parent.glob(f"{result.path.name}.tmp.*"))
    assert tmp_files == [], f"orphan tmp files: {tmp_files}"


@pytest.mark.integration
def test_read_empty_dir_returns_empty_table(data_dir: Path) -> None:
    """Test 7: read em diretório vazio retorna pa.Table vazio (não levanta)."""
    # data_dir não foi criado nem populado.
    with DuckDBReader(data_dir=data_dir) as reader:
        table = reader.read(
            "WDOJ26",
            start_ts_ns=0,
            end_ts_ns=2_000_000_000_000_000_000,
        )
        assert table.num_rows == 0
        # Schema deve corresponder ao canônico (v1.1.0 = 20 colunas, aditivo
        # +buy_agent_name/sell_agent_name/trade_type_name sobre as 17 de v1.0.0;
        # derivado de ``pyarrow_schema`` para não enrijecer o número — task #10).
        assert len(table.schema) == len(pyarrow_schema())

        # count também responde 0.
        assert reader.count("WDOJ26") == 0


@pytest.mark.integration
def test_read_filter_range(data_dir: Path, partition: PartitionKey) -> None:
    """Filtro timestamp_ns BETWEEN funciona (AC9)."""
    writer = ParquetWriter(data_dir=data_dir)
    base = 1_700_000_000_000_000_000
    trades = _make_trades(100, base_ts=base)
    writer.write(trades, partition, dll_version="4.0.0.34")

    # Janela: trades 10..19 (10 elementos).
    start = base + 10 * 1_000_000
    end = base + 19 * 1_000_000

    with DuckDBReader(data_dir=data_dir) as reader:
        table = reader.read("WDOJ26", start_ts_ns=start, end_ts_ns=end)
    assert table.num_rows == 10


@pytest.mark.integration
def test_write_empty_list_raises(data_dir: Path, partition: PartitionKey) -> None:
    """Lista vazia -> IntegrityError (não cria arquivo vazio)."""
    from data_downloader.public_api.exceptions import IntegrityError

    writer = ParquetWriter(data_dir=data_dir)
    with pytest.raises(IntegrityError):
        writer.write([], partition, dll_version="4.0.0.34")


@pytest.mark.integration
def test_write_v1_assigns_sequence(data_dir: Path, partition: PartitionKey) -> None:
    """Trades sem trade_id recebem ``sequence_within_ns`` automaticamente."""
    writer = ParquetWriter(data_dir=data_dir)
    base = 1_700_000_000_000_000_000
    # 3 trades V1 distintos no mesmo (symbol, ts) — devem ser preservados via sequence.
    trades = [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base,
            timestamp_str="01/03/2024 00:00:00.000",
            price=100.0 + i,
            quantity=1,
            trade_id=None,
            trade_type=2,
            buy_agent_id=None,
            sell_agent_id=None,
            flags=0,
            source_callback="history_v1",
            side=None,
            ingestion_ts_ns=base + 1,
            chunk_id=None,
            dll_version="0.0.0+stub",
            sequence_within_ns=999,  # noise — writer sobrescreve via assign
        )
        for i in range(3)
    ]
    result = writer.write(trades, partition, dll_version="4.0.0.34")
    assert result.row_count == 3
