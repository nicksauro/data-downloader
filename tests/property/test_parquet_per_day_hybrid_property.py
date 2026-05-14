"""Property tests — ADR-025 parquet-per-day híbrido + auto-compactação.

Owner: Aria (@architect) | v1.3.0 Wave 3.

Para uma sequência aleatória de N chunks diários (datas dentro de um
range plausível), aplicar ``register_partition`` + ``maybe_compact_month``
e verificar invariantes:

1. **Conservação de dados**: ``sum(chunk_ledger.trades_count) == DuckDB COUNT(*)``
   sobre ``parquet_scan('history/**/*.parquet')``.
2. **Mutualmente exclusivo**: para cada ``(symbol, year, month)``, ou existe
   ``{MM}.parquet`` + 0 diários, OU 0 mensal + >=1 diários — nunca ambos.
3. **Consistência catálogo**: rows em ``partitions`` table refletem os
   arquivos no disco.

Estratégia: Hypothesis gera datas em [2018, 2026] inclusive (com B3
calendar) e tamanhos de trades.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord
from data_downloader.validation.calendar_b3 import is_b3_business_day


def _make_trades(n: int, base_ts: int) -> list[TradeRecord]:
    """Gera N trades sintéticos com timestamps crescentes."""
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base_ts + i * 1_000_000,
            timestamp_str="01/01/2018 00:00:00.000",
            price=5_300.0 + (i % 100) * 0.1,
            quantity=10 + (i % 50),
            trade_id=i,
            trade_type=2,
            buy_agent_id=None,
            sell_agent_id=None,
            flags=0,
            source_callback="history_v2",
            side=None,
            ingestion_ts_ns=base_ts + i * 1_000_000 + 1,
            chunk_id=None,
            dll_version="0.0.0+test",
            sequence_within_ns=0,
        )
        for i in range(n)
    ]


# Range de datas: 2018-01-02 (1º dia útil) até 2020-12-31.
# Hypothesis usa esse intervalo + filtro para dia útil B3.
_DATE_STRATEGY = st.dates(min_value=date(2018, 1, 2), max_value=date(2020, 12, 31))


@st.composite
def _business_day(draw):
    """Gera 1 dia útil B3 (rejeita fins-de-semana e feriados)."""
    d = draw(_DATE_STRATEGY)
    # Hypothesis usa assume mas aqui filtramos manualmente para acelerar.
    while not is_b3_business_day(d):
        d = draw(_DATE_STRATEGY)
    return d


# 5..20 chunks por seed para manter tempo razoável; cada chunk = 1 dia
# útil + 50..200 trades.
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
        HealthCheck.data_too_large,
    ],
)
@given(
    chunks=st.lists(
        st.tuples(_business_day(), st.integers(min_value=50, max_value=200)),
        min_size=5,
        max_size=20,
        unique_by=lambda t: t[0],
    ),
)
@pytest.mark.property
def test_hybrid_layout_invariants(tmp_path_factory, chunks) -> None:
    """Para qualquer sequência de chunks, invariantes ADR-025 valem."""
    tmp_path: Path = tmp_path_factory.mktemp("hybrid")
    data_dir = tmp_path / "data"
    db_path = data_dir / "_internal" / "catalog.db"

    catalog = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    writer = ParquetWriter(data_dir=data_dir)
    symbol = "WDOJ26"
    exchange = "F"

    try:
        # Aplica cada chunk.
        total_trades = 0
        for d, n_trades in chunks:
            base_ts = int(datetime(d.year, d.month, d.day, 9, 0).timestamp()) * 1_000_000_000
            trades = _make_trades(n_trades, base_ts=base_ts)
            partition = PartitionKey(
                exchange=exchange,
                symbol=symbol,
                year=d.year,
                month=d.month,
                day=d.day,
            )
            wr = writer.write(trades, partition, dll_version="test")
            catalog.register_partition(wr, partition)
            catalog.record_chunk(
                symbol=symbol,
                exchange=exchange,
                chunk_date=d,
                job_id=None,
                status="completed",
                trades_count=n_trades,
            )
            catalog.maybe_compact_month(symbol, exchange, d.year, d.month)
            total_trades += n_trades

        # Invariante 1: conservação de dados.
        glob = str(data_dir / "history" / "**" / "*.parquet")
        conn = duckdb.connect(":memory:")
        try:
            disk_total = conn.execute(f"SELECT COUNT(*) FROM parquet_scan('{glob}')").fetchone()[0]
        finally:
            conn.close()
        assert disk_total == total_trades, (
            f"trade conservation: disk={disk_total} vs expected={total_trades}"
        )

        # Invariante 2: mutualmente exclusivo (mensal OR diário, nunca ambos).
        months_seen: set[tuple[int, int]] = set()
        for d, _ in chunks:
            months_seen.add((d.year, d.month))
        for year, month in months_seen:
            monthly_path = (
                data_dir / "history" / exchange / symbol / f"{year:04d}" / f"{month:02d}.parquet"
            )
            month_dir = monthly_path.with_suffix("")
            monthly_exists = monthly_path.is_file()
            daily_count = 0
            if month_dir.is_dir():
                daily_count = sum(1 for p in month_dir.glob("*.parquet") if ".tmp." not in p.name)
            # Mutualmente exclusivo: nunca ambos > 0.
            assert not (monthly_exists and daily_count > 0), (
                f"layout invariant violated: ({year:04d}-{month:02d}) has "
                f"monthly AND {daily_count} dailies"
            )
            # Pelo menos um existe (chunk foi escrito).
            assert monthly_exists or daily_count > 0

        # Invariante 3: catalog consistente com disco.
        parts = catalog.get_completed_partitions(symbol, exchange)
        # Cada partição registrada deve existir no disco.
        for part in parts:
            absolute = data_dir / "history" / part.partition_path
            assert absolute.is_file(), f"catalog has row for {part.partition_path} but file missing"
            # day=None ↔ mensal; day!=None ↔ diário.
            if part.day is None:
                assert "/" + f"{part.month:02d}.parquet" in "/" + part.partition_path
            else:
                assert f"/{part.month:02d}/{part.day:02d}.parquet" in part.partition_path
    finally:
        catalog.close()
