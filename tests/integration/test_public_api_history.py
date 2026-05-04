"""Integration tests — public_api.history (Story 1.5b AC10).

Cobertura:

- Importação via fronteira pública: ``from data_downloader.public_api
  import read, read_continuous, vigent_contract`` funciona.
- ``read_continuous`` via fronteira pública com fixtures sintéticos de
  2 contratos.
- Garantias documentadas (sem duplicatas, ordenado, schema_version
  no metadata Parquet de origem).
- ``vigent_contract`` via fronteira pública.
- ``read`` (single contract) via fronteira pública.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import SCHEMA_VERSION, TradeRecord


def _to_ns(dt: datetime) -> int:
    epoch = datetime(1970, 1, 1)
    delta = dt - epoch
    seconds = int(delta.total_seconds())
    extra_us = delta.microseconds
    return seconds * 1_000_000_000 + extra_us * 1_000


def _make_trade(*, symbol: str, ts_ns: int, trade_id: int) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/01/2026 00:00:00.000",
        price=5_300.0 + trade_id * 0.5,
        quantity=1,
        trade_id=trade_id,
        trade_type=2,
        buy_agent_id=None,
        sell_agent_id=None,
        flags=0,
        source_callback="history_v2",
        side=None,
        ingestion_ts_ns=ts_ns + 1,
        chunk_id=None,
        dll_version="0.0.0+stub",
        sequence_within_ns=0,
    )


def _setup_two_contracts(data_dir: Path) -> tuple[Catalog, list[Path]]:
    """Catalog com 2 contratos WDO + 5 trades cada → retorna catálogo +
    lista de paths Parquet escritos."""
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            ("WDO", "WDOH26", "2026-01-29 00:00:00", "2026-02-26 00:00:00"),
            ("WDO", "WDOJ26", "2026-02-27 00:00:00", "2026-03-30 00:00:00"),
        ]
        for root, code, vf, vu in rows:
            conn.execute(
                "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
                "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'hypothesized')",
                (root, code, vf, vu),
            )

    writer = ParquetWriter(data_dir=data_dir)
    base_feb = _to_ns(datetime(2026, 2, 10, 9, 0, 0))
    base_mar = _to_ns(datetime(2026, 3, 10, 9, 0, 0))

    paths: list[Path] = []
    res1 = writer.write(
        [
            _make_trade(symbol="WDOH26", ts_ns=base_feb + i * 1_000_000, trade_id=i)
            for i in range(5)
        ],
        PartitionKey(exchange="F", symbol="WDOH26", year=2026, month=2),
        dll_version="4.0.0.34",
    )
    paths.append(res1.path)

    res2 = writer.write(
        [
            _make_trade(symbol="WDOJ26", ts_ns=base_mar + i * 1_000_000, trade_id=100 + i)
            for i in range(5)
        ],
        PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3),
        dll_version="4.0.0.34",
    )
    paths.append(res2.path)
    return cat, paths


@pytest.mark.integration
def test_public_api_imports_succeed() -> None:
    """``from data_downloader.public_api import read, read_continuous,
    vigent_contract`` funciona — fronteira está exposta."""
    from data_downloader.public_api import (
        read,
        read_continuous,
        vigent_contract,
    )

    assert callable(read)
    assert callable(read_continuous)
    assert callable(vigent_contract)


@pytest.mark.integration
def test_public_api_read_continuous_two_contracts(tmp_path: Path) -> None:
    """``read_continuous`` via fronteira pública concatena 2 contratos."""
    from data_downloader.public_api import read_continuous

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        table = read_continuous(
            "WDO",
            datetime(2026, 1, 29),
            datetime(2026, 3, 30, 23, 59, 59),
            exchange="F",
            catalog=cat,
            data_dir=data_dir,
        )
        assert table.num_rows == 10
        codes = table.column("_contract_code").to_pylist()
        assert codes[:5] == ["WDOH26"] * 5
        assert codes[5:] == ["WDOJ26"] * 5
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_read_continuous_no_duplicates(tmp_path: Path) -> None:
    """Garantia documentada — sem duplicatas em rollover."""
    from data_downloader.public_api import read_continuous

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        table = read_continuous(
            "WDO",
            datetime(2026, 1, 29),
            datetime(2026, 3, 30, 23, 59, 59),
            exchange="F",
            catalog=cat,
            data_dir=data_dir,
        )
        ts_codes = list(
            zip(
                table.column("timestamp_ns").to_pylist(),
                table.column("_contract_code").to_pylist(),
                strict=True,
            )
        )
        assert len(ts_codes) == len(set(ts_codes))
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_read_continuous_sorted(tmp_path: Path) -> None:
    """Garantia documentada — ordenado por ``timestamp_ns``."""
    from data_downloader.public_api import read_continuous

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        table = read_continuous(
            "WDO",
            datetime(2026, 1, 29),
            datetime(2026, 3, 30, 23, 59, 59),
            exchange="F",
            catalog=cat,
            data_dir=data_dir,
        )
        ts = table.column("timestamp_ns").to_pylist()
        assert ts == sorted(ts)
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_read_continuous_schema_version_in_metadata(
    tmp_path: Path,
) -> None:
    """Garantia documentada — schema_version disponível via metadata
    Parquet de origem (SCHEMA.md §4)."""
    from data_downloader.public_api import read_continuous  # noqa: F401

    data_dir = tmp_path / "data"
    cat, paths = _setup_two_contracts(data_dir)
    try:
        # schema_version é exposto pelos arquivos Parquet escritos pelo writer.
        for path in paths:
            md = pq.read_metadata(path).metadata
            assert md is not None
            assert md.get(b"schema_version") == SCHEMA_VERSION.encode("utf-8")
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_read_single_contract(tmp_path: Path) -> None:
    """``read`` (single contract) via fronteira pública."""
    from data_downloader.public_api import read

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        table = read(
            "WDOH26",
            datetime(2026, 2, 1),
            datetime(2026, 2, 28, 23, 59, 59),
            exchange="F",
            data_dir=data_dir,
        )
        assert table.num_rows == 5
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_read_with_columns_subset(tmp_path: Path) -> None:
    """``read(columns=...)`` filtra colunas do retorno."""
    from data_downloader.public_api import read

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        table = read(
            "WDOH26",
            datetime(2026, 2, 1),
            datetime(2026, 2, 28, 23, 59, 59),
            exchange="F",
            data_dir=data_dir,
            columns=["timestamp_ns", "price", "quantity"],
        )
        assert table.num_rows == 5
        assert table.schema.names == ["timestamp_ns", "price", "quantity"]
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_vigent_contract(tmp_path: Path) -> None:
    """``vigent_contract`` via fronteira pública."""
    from data_downloader.public_api import vigent_contract

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        # Date no meio da janela WDOH26 (jan-fev 2026).
        assert vigent_contract("WDO", date(2026, 2, 10), exchange="F", catalog=cat) == "WDOH26"
        # Date no meio da janela WDOJ26 (fev-mar 2026).
        assert vigent_contract("WDO", date(2026, 3, 10), exchange="F", catalog=cat) == "WDOJ26"
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_vigent_contract_invalid_raises(tmp_path: Path) -> None:
    """``vigent_contract`` propaga ``InvalidContract``."""
    from data_downloader.public_api import InvalidContract, vigent_contract

    data_dir = tmp_path / "data"
    cat, _ = _setup_two_contracts(data_dir)
    try:
        with pytest.raises(InvalidContract):
            vigent_contract("WDO", date(2030, 1, 1), exchange="F", catalog=cat)
    finally:
        cat.close()


@pytest.mark.integration
def test_public_api_read_invalid_exchange_raises(tmp_path: Path) -> None:
    """``read`` valida ``exchange`` na fronteira."""
    from data_downloader.public_api import read

    data_dir = tmp_path / "data"
    with pytest.raises(ValueError, match="exchange must be"):
        read(
            "WDOH26",
            datetime(2026, 2, 1),
            datetime(2026, 2, 28),
            exchange="BMF",
            data_dir=data_dir,
        )


@pytest.mark.integration
def test_public_api_api_version_exposed() -> None:
    """``__api_version__`` está exposto na fronteira.

    Story 1.7b → "0.3.0"; Story 2.11 → "0.4.0"; Story 4.3 → "1.0.0" (V1.0
    stable release). Versão exata é validada em
    ``test_public_api_semver_regression.py`` — aqui apenas verifica
    presença e formato SemVer.
    """
    from data_downloader.public_api import __api_version__

    assert isinstance(__api_version__, str)
    assert len(__api_version__.split(".")) == 3
    # V1.0+ a partir de Story 4.3
    assert int(__api_version__.split(".")[0]) >= 1
