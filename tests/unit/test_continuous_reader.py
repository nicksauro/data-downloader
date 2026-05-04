"""Unit tests — storage.continuous_reader (Story 1.5b).

Cobertura:

- Cenário 1 contrato → equivalente a leitura normal de DuckDBReader.
- Cenário 2 contratos com transição limpa → trades concatenados em
  ordem temporal.
- Cenário 3 contratos sequenciais cobertos por um único range → todos
  juntos, ordenados.
- Range parcial dentro de 1 contrato → só os trades do range.
- Coluna ``_contract_code`` presente em todas as linhas.
- ``ContractTransition`` list tem N-1 entries para N contratos com dados.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.orchestrator.contracts import populate_contracts_from_seed
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.continuous_reader import (
    ContractTransition,
    _to_ns,
    read_continuous,
    read_continuous_with_rollover_metadata,
)
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord

# =====================================================================
# Helpers
# =====================================================================


def _make_trade(
    *,
    symbol: str,
    ts_ns: int,
    trade_id: int,
    price: float = 5_300.0,
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/03/2026 00:00:00.000",
        price=price,
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


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def catalog_with_wdo_contracts(data_dir: Path) -> Catalog:
    """Catalog com 3 contratos WDO sintéticos (jan/fev/mar 2026 — janelas
    sem overlap, contíguas)."""
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            ("WDO", "WDOG26", "2026-01-01 00:00:00", "2026-01-31 00:00:00"),
            ("WDO", "WDOH26", "2026-02-01 00:00:00", "2026-02-28 00:00:00"),
            ("WDO", "WDOJ26", "2026-03-01 00:00:00", "2026-03-31 00:00:00"),
        ]
        for root, code, vf, vu in rows:
            conn.execute(
                "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
                "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'hypothesized')",
                (root, code, vf, vu),
            )
    return cat


def _write_trades_for_contract(
    *,
    data_dir: Path,
    contract_code: str,
    year: int,
    month: int,
    base_ts_ns: int,
    n_trades: int,
) -> None:
    """Escreve ``n_trades`` para ``contract_code`` na partição ``year/month``."""
    trades = [
        _make_trade(
            symbol=contract_code,
            ts_ns=base_ts_ns + i * 1_000_000,
            trade_id=i,
            price=5_300.0 + i * 0.5,
        )
        for i in range(n_trades)
    ]
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol=contract_code, year=year, month=month)
    writer.write(trades, partition, dll_version="4.0.0.34")


# =====================================================================
# Tests
# =====================================================================


@pytest.mark.unit
def test_read_continuous_single_contract(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """Cenário 1 contrato apenas → equivalente a leitura normal."""
    base_ns = _to_ns(datetime(2026, 1, 15, 9, 0, 0))
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOG26",
        year=2026,
        month=1,
        base_ts_ns=base_ns,
        n_trades=10,
    )

    table = read_continuous(
        "WDO",
        datetime(2026, 1, 1),
        datetime(2026, 1, 31, 23, 59, 59),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )
    assert table.num_rows == 10
    codes = set(table.column("_contract_code").to_pylist())
    assert codes == {"WDOG26"}
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_two_contracts_clean_transition(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """2 contratos com transição limpa → trades concatenados em ordem."""
    base_jan = _to_ns(datetime(2026, 1, 15, 9, 0, 0))
    base_feb = _to_ns(datetime(2026, 2, 15, 9, 0, 0))

    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOG26",
        year=2026,
        month=1,
        base_ts_ns=base_jan,
        n_trades=5,
    )
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOH26",
        year=2026,
        month=2,
        base_ts_ns=base_feb,
        n_trades=5,
    )

    table = read_continuous(
        "WDO",
        datetime(2026, 1, 1),
        datetime(2026, 2, 28, 23, 59, 59),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )

    assert table.num_rows == 10
    # Ordering monotônica
    ts = table.column("timestamp_ns").to_pylist()
    assert ts == sorted(ts)
    # Primeiros 5 são WDOG26, últimos 5 são WDOH26.
    codes = table.column("_contract_code").to_pylist()
    assert codes[:5] == ["WDOG26"] * 5
    assert codes[5:] == ["WDOH26"] * 5
    # _rollover_event marcado na 6a linha (índice 5).
    flags = table.column("_rollover_event").to_pylist()
    assert flags[5] is True
    assert sum(flags) == 1
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_three_sequential_contracts(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """Range cobre 3 contratos sequenciais → todos juntos, ordenados."""
    base_jan = _to_ns(datetime(2026, 1, 15, 9, 0, 0))
    base_feb = _to_ns(datetime(2026, 2, 15, 9, 0, 0))
    base_mar = _to_ns(datetime(2026, 3, 15, 9, 0, 0))

    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOG26",
        year=2026,
        month=1,
        base_ts_ns=base_jan,
        n_trades=3,
    )
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOH26",
        year=2026,
        month=2,
        base_ts_ns=base_feb,
        n_trades=3,
    )
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOJ26",
        year=2026,
        month=3,
        base_ts_ns=base_mar,
        n_trades=3,
    )

    table = read_continuous(
        "WDO",
        datetime(2026, 1, 1),
        datetime(2026, 3, 31, 23, 59, 59),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )

    assert table.num_rows == 9
    # Ordering global monotônica
    ts = table.column("timestamp_ns").to_pylist()
    assert ts == sorted(ts)
    # Cada bloco tem 3 do mesmo código.
    codes = table.column("_contract_code").to_pylist()
    assert codes[:3] == ["WDOG26"] * 3
    assert codes[3:6] == ["WDOH26"] * 3
    assert codes[6:9] == ["WDOJ26"] * 3
    # 2 rollover events (3 contratos contíguos com dados → N-1 = 2).
    flags = table.column("_rollover_event").to_pylist()
    assert sum(flags) == 2
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_partial_range_within_one_contract(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """Range parcial dentro de 1 contrato → só os trades do range."""
    base_jan = _to_ns(datetime(2026, 1, 15, 9, 0, 0))
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOG26",
        year=2026,
        month=1,
        base_ts_ns=base_jan,
        n_trades=20,
    )

    # Range 09:00:05..09:00:09 (5 trades — índices 5..9).
    table = read_continuous(
        "WDO",
        datetime(2026, 1, 15, 9, 0, 0, 5_000),  # +5ms
        datetime(2026, 1, 15, 9, 0, 0, 9_000),  # +9ms
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )

    assert table.num_rows == 5
    codes = set(table.column("_contract_code").to_pylist())
    assert codes == {"WDOG26"}
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_contract_code_column_present(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """Coluna ``_contract_code`` está presente e tem o tipo correto."""
    base_jan = _to_ns(datetime(2026, 1, 15, 9, 0, 0))
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOG26",
        year=2026,
        month=1,
        base_ts_ns=base_jan,
        n_trades=3,
    )

    table = read_continuous(
        "WDO",
        datetime(2026, 1, 1),
        datetime(2026, 1, 31),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )

    assert "_contract_code" in table.schema.names
    assert "_rollover_event" in table.schema.names
    # _contract_code é string NOT NULL
    field = table.schema.field("_contract_code")
    import pyarrow as pa

    assert field.type == pa.string()
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_with_rollover_metadata_returns_n_minus_1_transitions(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """``ContractTransition`` list tem N-1 entries para N contratos com dados."""
    base_jan = _to_ns(datetime(2026, 1, 15, 9, 0, 0))
    base_feb = _to_ns(datetime(2026, 2, 15, 9, 0, 0))
    base_mar = _to_ns(datetime(2026, 3, 15, 9, 0, 0))

    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOG26",
        year=2026,
        month=1,
        base_ts_ns=base_jan,
        n_trades=2,
    )
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOH26",
        year=2026,
        month=2,
        base_ts_ns=base_feb,
        n_trades=2,
    )
    _write_trades_for_contract(
        data_dir=data_dir,
        contract_code="WDOJ26",
        year=2026,
        month=3,
        base_ts_ns=base_mar,
        n_trades=2,
    )

    table, transitions = read_continuous_with_rollover_metadata(
        "WDO",
        datetime(2026, 1, 1),
        datetime(2026, 3, 31, 23, 59, 59),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )

    assert table.num_rows == 6
    assert len(transitions) == 2
    assert transitions[0].from_contract == "WDOG26"
    assert transitions[0].to_contract == "WDOH26"
    assert transitions[0].boundary_ts_ns == base_feb
    assert transitions[1].from_contract == "WDOH26"
    assert transitions[1].to_contract == "WDOJ26"
    assert transitions[1].boundary_ts_ns == base_mar
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_no_contracts_returns_empty(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """Range fora de toda vigência → tabela vazia, sem levantar."""
    table = read_continuous(
        "WDO",
        datetime(2030, 1, 1),
        datetime(2030, 12, 31),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )
    assert table.num_rows == 0
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_unknown_root_returns_empty(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    """Raiz inexistente → tabela vazia."""
    table = read_continuous(
        "UNKNOWN",
        datetime(2026, 1, 1),
        datetime(2026, 12, 31),
        exchange="F",
        catalog=catalog_with_wdo_contracts,
        data_dir=data_dir,
    )
    assert table.num_rows == 0
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_invalid_exchange_raises(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    with pytest.raises(ValueError, match="exchange must be"):
        read_continuous(
            "WDO",
            datetime(2026, 1, 1),
            datetime(2026, 1, 31),
            exchange="BMF",
            catalog=catalog_with_wdo_contracts,
            data_dir=data_dir,
        )
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_start_after_end_raises(
    data_dir: Path,
    catalog_with_wdo_contracts: Catalog,
) -> None:
    with pytest.raises(ValueError, match="start must be"):
        read_continuous(
            "WDO",
            datetime(2026, 2, 1),
            datetime(2026, 1, 1),
            exchange="F",
            catalog=catalog_with_wdo_contracts,
            data_dir=data_dir,
        )
    catalog_with_wdo_contracts.close()


@pytest.mark.unit
def test_read_continuous_with_real_seed_no_data(
    data_dir: Path,
) -> None:
    """Smoke: carrega seed real (CONTRACTS.md) e verifica tabela vazia
    quando não há Parquets — confirma que a integração com ``list_contracts``
    e ``populate_contracts_from_seed`` funciona end-to-end."""
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    n_loaded = populate_contracts_from_seed(cat)
    assert n_loaded > 0  # seed tem pelo menos 1 entrada

    # Range coberto pelo seed (WDOH26 ~ jan-feb 2026) mas sem Parquets.
    table = read_continuous(
        "WDO",
        datetime(2026, 1, 29),
        datetime(2026, 2, 26),
        exchange="F",
        catalog=cat,
        data_dir=data_dir,
    )
    assert table.num_rows == 0
    cat.close()


@pytest.mark.unit
def test_contract_transition_dataclass_immutable() -> None:
    """``ContractTransition`` é frozen dataclass."""
    t = ContractTransition(from_contract="WDOH26", to_contract="WDOJ26", boundary_ts_ns=123)
    with pytest.raises((AttributeError, Exception)):
        t.from_contract = "WDOK26"  # type: ignore[misc]
