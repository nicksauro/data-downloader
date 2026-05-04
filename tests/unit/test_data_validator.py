"""Unit tests — validation.data_validator (Story 2.1).

Cenários:

- Todos os dias úteis B3 cobertos → 0 gaps.
- Um dia útil sem trades → 1 gap classificado ``missing_download``.
- Gap em dia que coincide com feriado B3 → ``holiday`` (acceptable).
- Range invertido → lista vazia.
- Símbolo sem nenhum Parquet → todos os dias úteis viram gaps.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord
from data_downloader.validation.data_validator import (
    DataValidator,
    GapReport,
    validate_dataset,
)


def _trades_for_day(d: date, *, symbol: str = "WDOJ26", n: int = 5) -> list[TradeRecord]:
    """Gera ``n`` trades sintéticos no dia ``d`` (BRT NAIVE)."""
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
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def catalog(db_path: Path, data_dir: Path) -> Catalog:
    return Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


@pytest.mark.unit
def test_no_partitions_returns_all_days_as_missing(catalog: Catalog, data_dir: Path) -> None:
    """Símbolo sem nenhum Parquet: todos os dias úteis viram gaps."""
    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    # Semana de 9-13/3/2026 (5 dias úteis sem feriado).
    gaps = validator.detect_gaps("WDOJ26", date(2026, 3, 9), date(2026, 3, 13))
    assert len(gaps) == 5
    for g in gaps:
        assert g.classification == "missing_download"


@pytest.mark.unit
def test_all_days_covered_returns_no_gaps(catalog: Catalog, data_dir: Path) -> None:
    """Todos os dias úteis com trades: 0 gaps."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    # Cria trades para 5 dias úteis (9-13/3/2026).
    all_trades: list[TradeRecord] = []
    for d in (
        date(2026, 3, 9),
        date(2026, 3, 10),
        date(2026, 3, 11),
        date(2026, 3, 12),
        date(2026, 3, 13),
    ):
        all_trades.extend(_trades_for_day(d))
    writer.write(all_trades, partition, dll_version="4.0.0.34")

    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    gaps = validator.detect_gaps("WDOJ26", date(2026, 3, 9), date(2026, 3, 13))
    assert gaps == []


@pytest.mark.unit
def test_one_missing_business_day_classified_as_missing_download(
    catalog: Catalog, data_dir: Path
) -> None:
    """4/5 dias úteis cobertos: 1 gap missing_download."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    # Cobre 9, 10, 12, 13. Falta 11/3/2026 (quarta — dia útil).
    all_trades: list[TradeRecord] = []
    for d in (date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 12), date(2026, 3, 13)):
        all_trades.extend(_trades_for_day(d))
    writer.write(all_trades, partition, dll_version="4.0.0.34")

    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    gaps = validator.detect_gaps("WDOJ26", date(2026, 3, 9), date(2026, 3, 13))
    assert len(gaps) == 1
    g = gaps[0]
    assert g.gap_start.date() == date(2026, 3, 11)
    assert g.classification == "missing_download"


@pytest.mark.unit
def test_holiday_day_with_no_trades_does_not_appear_as_gap(
    catalog: Catalog, data_dir: Path
) -> None:
    """Tiradentes (21/4/2026) sem trades NÃO é reportado (não é dia útil)."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)
    # Cobre 20/4 e 22-24/4 (sem 21/4 que é feriado).
    all_trades: list[TradeRecord] = []
    for d in (date(2026, 4, 20), date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24)):
        all_trades.extend(_trades_for_day(d))
    writer.write(all_trades, partition, dll_version="4.0.0.34")

    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    gaps = validator.detect_gaps("WDOJ26", date(2026, 4, 20), date(2026, 4, 24))
    # Tiradentes não é dia útil → não consta nos business_days esperados →
    # ausência de trades nesse dia NÃO é gap.
    assert gaps == []


@pytest.mark.unit
def test_inverted_range_returns_empty(catalog: Catalog, data_dir: Path) -> None:
    """``start > end`` retorna lista vazia sem erro."""
    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    gaps = validator.detect_gaps("WDOJ26", date(2026, 3, 13), date(2026, 3, 9))
    assert gaps == []


@pytest.mark.unit
def test_classify_gap_holiday_returns_holiday(catalog: Catalog, data_dir: Path) -> None:
    """``classify_gap`` em feriado conhecido retorna 'holiday'."""
    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    assert validator.classify_gap(date(2026, 4, 21)) == "holiday"
    assert validator.classify_gap(date(2026, 1, 1)) == "holiday"


@pytest.mark.unit
def test_classify_gap_weekday_returns_missing_download(catalog: Catalog, data_dir: Path) -> None:
    """``classify_gap`` em dia útil retorna 'missing_download' (V1)."""
    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    assert validator.classify_gap(date(2026, 3, 11)) == "missing_download"


@pytest.mark.unit
def test_validate_dataset_multi_symbol(catalog: Catalog, data_dir: Path) -> None:
    """``validate_dataset`` retorna dict por símbolo."""
    result = validate_dataset(
        data_dir=data_dir,
        catalog=catalog,
        symbols=["WDOJ26", "WINH26"],
        start=date(2026, 3, 9),
        end=date(2026, 3, 9),
    )
    assert set(result.keys()) == {"WDOJ26", "WINH26"}
    # Sem dados → 1 gap por símbolo.
    assert all(len(v) == 1 for v in result.values())


@pytest.mark.unit
def test_gap_report_is_frozen_dataclass() -> None:
    """:class:`GapReport` é frozen — não permite mutação."""
    from dataclasses import FrozenInstanceError

    g = GapReport(
        symbol="WDOJ26",
        gap_start=datetime(2026, 3, 11, 0, 0),
        gap_end=datetime(2026, 3, 11, 23, 59, 59),
        business_days_missing=1,
        classification="missing_download",
    )
    with pytest.raises(FrozenInstanceError):
        g.symbol = "OTHER"  # type: ignore[misc]
