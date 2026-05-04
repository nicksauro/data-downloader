"""Integration tests — CLI ``integrity`` group (Story 2.1).

Cobre:

- ``data-downloader integrity check`` em dataset clean: exit 0.
- ``data-downloader integrity check`` em dataset com violação: exit 2.
- ``data-downloader integrity validate-data`` em dataset sem gaps: exit 0.
- ``data-downloader integrity validate-data`` em dataset com gap missing_download: exit 2.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from data_downloader.cli import app
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord, pyarrow_schema


def _trades_for_day(d: date, *, symbol: str = "WDOJ26", n: int = 3) -> list[TradeRecord]:
    base_dt = datetime.combine(d, time(10, 0))
    base_ts = int(base_dt.timestamp() * 1_000_000_000)
    return [
        TradeRecord(
            symbol=symbol,
            exchange="F",
            timestamp_ns=base_ts + i * 1_000_000_000,
            timestamp_str=base_dt.strftime("%d/%m/%Y %H:%M:%S.000"),
            price=5_300.0 + i,
            quantity=10 + i,
            trade_id=int(d.toordinal()) * 1000 + i,
            trade_type=2,
            buy_agent_id=None,
            sell_agent_id=None,
            flags=0,
            source_callback="history_v2",
            side=None,
            ingestion_ts_ns=base_ts + i * 1_000_000_000 + 1,
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
    """data_dir com 1 partição limpa registrada no catálogo."""
    data_dir = tmp_path / "data"
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    all_trades: list[TradeRecord] = []
    for d in (
        date(2026, 3, 9),
        date(2026, 3, 10),
        date(2026, 3, 11),
        date(2026, 3, 12),
        date(2026, 3, 13),
    ):
        all_trades.extend(_trades_for_day(d))
    result = writer.write(all_trades, partition, dll_version="4.0.0.34")
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    cat.register_partition(result, partition)
    cat.close()
    return data_dir


@pytest.mark.integration
def test_cli_integrity_check_clean_exit_zero(runner: CliRunner, populated_data_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "integrity",
            "check",
            "--symbol",
            "WDOJ26",
            "--data-dir",
            str(populated_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output or "pass" in result.output.lower()


@pytest.mark.integration
def test_cli_integrity_check_with_violation_exit_two(runner: CliRunner, tmp_path: Path) -> None:
    """Dataset com price=0 deve fazer CLI sair com exit code 2."""
    data_dir = tmp_path / "data"
    parquet_path = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    schema = pyarrow_schema()
    base_ts = 1_700_000_000_000_000_000
    columns: dict[str, list[object]] = {f.name: [] for f in schema}
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
    for f in schema:
        columns[f.name].append(bad_trade.get(f.name))
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    table = pa.Table.from_arrays(arrays, schema=schema)
    table = table.replace_schema_metadata({b"schema_version": b"1.0.0"})
    pq.write_table(table, parquet_path)

    result = runner.invoke(
        app,
        [
            "integrity",
            "check",
            "--symbol",
            "WDOJ26",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 2, result.output
    assert "FAIL" in result.output


@pytest.mark.integration
def test_cli_integrity_validate_data_no_gaps_exit_zero(
    runner: CliRunner, populated_data_dir: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "integrity",
            "validate-data",
            "--symbol",
            "WDOJ26",
            "--start",
            "2026-03-09",
            "--end",
            "2026-03-13",
            "--data-dir",
            str(populated_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_cli_integrity_validate_data_with_gap_exit_two(runner: CliRunner, tmp_path: Path) -> None:
    """Dataset vazio: dia útil sem trades → exit 2."""
    data_dir = tmp_path / "data"
    # Cria pelo menos a estrutura para o catálogo init não quebrar.
    (data_dir / "history").mkdir(parents=True, exist_ok=True)
    result = runner.invoke(
        app,
        [
            "integrity",
            "validate-data",
            "--symbol",
            "WDOJ26",
            "--start",
            "2026-03-09",
            "--end",
            "2026-03-09",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 2, result.output


@pytest.mark.integration
def test_cli_integrity_validate_data_invalid_date_exit_one(
    runner: CliRunner, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "history").mkdir(parents=True, exist_ok=True)
    result = runner.invoke(
        app,
        [
            "integrity",
            "validate-data",
            "--symbol",
            "WDOJ26",
            "--start",
            "not-a-date",
            "--end",
            "2026-03-09",
            "--data-dir",
            str(data_dir),
        ],
    )
    assert result.exit_code == 1
