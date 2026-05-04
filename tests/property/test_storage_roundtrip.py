"""Property tests — storage round-trip (Story 1.4 / INV-7).

Hypothesis property:

    read(write(L)).to_pylist() == sorted(dedup(L), by=timestamp_ns)

Garante que:

- write -> read preserva conteúdo (modulo dedup).
- Ordem na leitura é por ``timestamp_ns ASC``.
- Schema preservado em round-trip.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.dedup import compute_canonical_hash, dedup
from data_downloader.storage.duckdb_reader import DuckDBReader
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord


def _make_trade(ts_ns: int, trade_id: int, price: float) -> TradeRecord:
    return TradeRecord(
        symbol="WDOJ26",
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/03/2024 00:00:00.000",
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


_trade_strategy = st.builds(
    _make_trade,
    ts_ns=st.integers(
        min_value=1_700_000_000_000_000_000,
        max_value=1_710_000_000_000_000_000,
    ),
    trade_id=st.integers(min_value=0, max_value=10_000),
    price=st.floats(
        min_value=0.01,
        max_value=10_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)


@given(trades=st.lists(_trade_strategy, min_size=1, max_size=30))
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_write_read_roundtrip_inv7(tmp_path_factory: object, trades: list[TradeRecord]) -> None:
    """``read(write(L))`` retorna ``dedup(L)`` ordenado por ``timestamp_ns``."""
    # tmp_path_factory é fixture pytest, mas Hypothesis não passa fixtures
    # automaticamente — usar tmp_path interno via pathlib.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)

        writer = ParquetWriter(data_dir=data_dir)
        # Cópia defensiva — writer enriquece os trades.
        result = writer.write(deepcopy(trades), partition, dll_version="4.0.0.34")

        with DuckDBReader(data_dir=data_dir) as reader:
            table = reader.read(
                "WDOJ26",
                start_ts_ns=0,
                end_ts_ns=2_000_000_000_000_000_000,
            )

        # Esperado: dedup(trades) ordenado por timestamp_ns.
        deduped = dedup(deepcopy(trades))
        expected_keys = sorted(
            (compute_canonical_hash(t) for t in deduped),
            key=lambda k: k[2],  # timestamp_ns é o 3º elemento da chave V2/V1
        )

        # Lido: mesma cardinalidade.
        assert table.num_rows == len(deduped) == result.row_count

        # Ordenação por timestamp_ns ASC.
        ts_read = table.column("timestamp_ns").to_pylist()
        assert ts_read == sorted(ts_read)

        # Conjunto de chaves bate (modulo ordem).
        from typing import cast

        read_records = [cast(TradeRecord, r) for r in table.to_pylist()]
        read_keys = sorted(
            (compute_canonical_hash(t) for t in read_records),
            key=lambda k: k[2],
        )
        assert read_keys == expected_keys
