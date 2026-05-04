"""Property tests — read_continuous para equity (Story 4.2 AC4 / COUNCIL-29 D4).

Equity é caso degenerado: ``vigent_from=1900-01-01``,
``vigent_until=9999-12-31``, 1 contrato vigente cobrindo todo o range.
Logo ``read_continuous("PETR4", ...)`` é semanticamente equivalente a
ler 1 partição direto — sem rollover, sem `_rollover_event`, sem
concatenação cross-contract.

Properties:

- **P1 (idempotente):** chamar ``read_continuous`` 2x retorna mesmo resultado.
- **P2 (zero rollover):** equity tem 0 ``_rollover_event=True``.
- **P3 (single contract):** ``_contract_code`` é um único valor (o ticker).
- **P4 (chunking equivalência):** chunked == direct para equity.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.continuous_reader import (
    _to_ns,
    read_continuous,
)
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord


def _make_trade(*, symbol: str, ts_ns: int, trade_id: int) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        exchange="B",  # Bovespa (R8/Q05-V — equity)
        timestamp_ns=ts_ns,
        timestamp_str="04/05/2026 10:30:00.000",
        price=38.50 + (trade_id % 10) * 0.01,
        quantity=100,
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


def _setup_equity_catalog(
    data_dir: Path,
    *,
    ticker: str,
    n_trades: int,
    base_dt: datetime,
) -> Catalog:
    """Cria catalog com 1 equity (vigência infinita) + escreve N trades."""
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    with cat._transaction():
        # Equity: vigent_from=1900, vigent_until=9999.
        conn.execute(
            "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
            "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'manual')",
            (
                ticker,
                ticker,
                "1900-01-01 00:00:00",
                "9999-12-31 00:00:00",
            ),
        )

    base_ns = _to_ns(base_dt)
    trades = [
        _make_trade(
            symbol=ticker,
            ts_ns=base_ns + i * 1_000_000,
            trade_id=i,
        )
        for i in range(n_trades)
    ]
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(
        exchange="B",
        symbol=ticker,
        year=base_dt.year,
        month=base_dt.month,
    )
    writer.write(trades, partition, dll_version="4.0.0.34")
    return cat


# =====================================================================
# Property 1 — idempotência (read_continuous chamado 2x dá mesmo resultado)
# =====================================================================


@given(
    ticker=st.sampled_from(["PETR4", "VALE3", "ITUB4"]),
    n_trades=st.integers(min_value=1, max_value=20),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_equity_read_continuous_idempotent(ticker: str, n_trades: int) -> None:
    """P1: ``read_continuous`` chamado 2x retorna mesmas linhas."""
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_equity_catalog(
            data_dir,
            ticker=ticker,
            n_trades=n_trades,
            base_dt=datetime(2026, 5, 4, 10, 30, 0),
        )
        try:
            t1 = read_continuous(
                ticker,
                datetime(2026, 5, 1),
                datetime(2026, 5, 31, 23, 59, 59),
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )
            t2 = read_continuous(
                ticker,
                datetime(2026, 5, 1),
                datetime(2026, 5, 31, 23, 59, 59),
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )
            assert t1.num_rows == t2.num_rows == n_trades
            ts1 = t1.column("timestamp_ns").to_pylist()
            ts2 = t2.column("timestamp_ns").to_pylist()
            assert ts1 == ts2
        finally:
            cat.close()


# =====================================================================
# Property 2 — zero rollover events para equity
# =====================================================================


@given(
    ticker=st.sampled_from(["PETR4", "VALE3", "ITUB4", "BBDC4"]),
    n_trades=st.integers(min_value=2, max_value=20),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_equity_zero_rollover_events(ticker: str, n_trades: int) -> None:
    """P2: equity nunca dispara ``_rollover_event=True``.

    Equity tem 1 contrato vigente cobrindo o range — não há rollover.
    """
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_equity_catalog(
            data_dir,
            ticker=ticker,
            n_trades=n_trades,
            base_dt=datetime(2026, 5, 4, 10, 30, 0),
        )
        try:
            table = read_continuous(
                ticker,
                datetime(2026, 5, 1),
                datetime(2026, 5, 31, 23, 59, 59),
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )
            flags = table.column("_rollover_event").to_pylist()
            assert sum(flags) == 0, f"equity should have zero rollover events, got {sum(flags)}"
        finally:
            cat.close()


# =====================================================================
# Property 3 — single _contract_code value
# =====================================================================


@pytest.mark.property
@pytest.mark.parametrize("ticker", ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3"])
def test_equity_single_contract_code(ticker: str) -> None:
    """P3: ``_contract_code`` é um único valor (== ticker) para equity."""
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_equity_catalog(
            data_dir,
            ticker=ticker,
            n_trades=5,
            base_dt=datetime(2026, 5, 4, 10, 30, 0),
        )
        try:
            table = read_continuous(
                ticker,
                datetime(2026, 5, 1),
                datetime(2026, 5, 31, 23, 59, 59),
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )
            codes = set(table.column("_contract_code").to_pylist())
            assert codes == {ticker}
        finally:
            cat.close()


# =====================================================================
# Property 4 — chunking equivalence (mesma lógica WDO Story 1.5b)
# =====================================================================


@given(
    n_trades=st.integers(min_value=4, max_value=20),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_equity_chunking_invariance(n_trades: int) -> None:
    """P4: chunked read == direct read para equity (sem rollover envolvido)."""
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        base = datetime(2026, 5, 4, 10, 30, 0)
        cat = _setup_equity_catalog(
            data_dir,
            ticker="PETR4",
            n_trades=n_trades,
            base_dt=base,
        )
        try:
            full_start = datetime(2026, 5, 4, 0, 0, 0)
            full_end = datetime(2026, 5, 4, 23, 59, 59, 999_999)

            direct = read_continuous(
                "PETR4",
                full_start,
                full_end,
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )

            # Quebra em 2 sub-ranges (antes/depois do meio).
            from datetime import timedelta

            mid_index = n_trades // 2
            # mid_ns = _to_ns(base) + mid_index * 1_000_000  # ref doc apenas
            mid_dt = base + timedelta(microseconds=(mid_index * 1_000))
            chunk1 = read_continuous(
                "PETR4",
                full_start,
                mid_dt - timedelta(microseconds=1),
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )
            chunk2 = read_continuous(
                "PETR4",
                mid_dt,
                full_end,
                exchange="B",
                catalog=cat,
                data_dir=data_dir,
            )

            assert chunk1.num_rows + chunk2.num_rows == direct.num_rows
        finally:
            cat.close()
