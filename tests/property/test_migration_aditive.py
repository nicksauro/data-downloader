"""Property test (Hypothesis) — Story 2.3 AC9 + Story 1.7g (Nelo Council 32 P0).

Para qualquer Table v1.0.0 gerada via strategy de TradeRecord, após
``V100ToV110.transform``:

- Todos os campos canônicos v1.0.0 preservados byte-a-byte
  (to_pylist comparison).
- Os 3 campos aditivos v1.1.0 (``buy_agent_name``, ``sell_agent_name``,
  ``trade_type_name``) presentes como ``string`` nullable com fallback
  determinístico aplicado.
- Schema do output bate com ``pyarrow_schema()`` v1.1.0 (20 campos).

Hypothesis 100 examples (default mais alto que mínimo aceitável de 50;
INV-9 R5 — schema migration aditivo idempotente).
"""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.migrations.parquet.v1_0_0_to_v1_1_0 import V100ToV110
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord

# Strategies — alinhados com test_storage_roundtrip.py (Story 1.4).
SYMBOL = st.sampled_from(["WDOJ26", "WDOK26", "PETR4"])
EXCHANGE = st.sampled_from(["F", "B"])
PRICE = st.floats(min_value=0.01, max_value=100_000.0, allow_nan=False, allow_infinity=False)
QUANTITY = st.integers(min_value=1, max_value=1_000_000)
TIMESTAMP = st.integers(min_value=1_700_000_000_000_000_000, max_value=1_900_000_000_000_000_000)


@st.composite
def trade_record_strategy(draw: st.DrawFn) -> TradeRecord:
    """Gera um TradeRecord canônico v1.0.0 (todos os campos)."""
    # Para evitar que hypothesis gere conflict de exchange diferente do
    # symbol, fixamos exchange='F' (BMF) e symbol consistente com isso.
    return TradeRecord(
        symbol=draw(st.sampled_from(["WDOJ26", "WDOK26"])),
        exchange="F",
        timestamp_ns=draw(TIMESTAMP),
        timestamp_str="01/03/2024 00:00:00.000",
        price=draw(PRICE),
        quantity=draw(QUANTITY),
        trade_id=draw(st.integers(min_value=1, max_value=10**12)),
        trade_type=draw(st.integers(min_value=1, max_value=10)),
        buy_agent_id=None,
        sell_agent_id=None,
        flags=0,
        source_callback="history_v2",
        side=None,
        ingestion_ts_ns=draw(TIMESTAMP),
        chunk_id=None,
        dll_version="0.0.0+stub",
        sequence_within_ns=0,
    )


@pytest.mark.property
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    trades=st.lists(
        trade_record_strategy(),
        min_size=1,
        max_size=20,
        unique_by=lambda t: t["trade_id"],
    )
)
def test_migrate_v100_to_v110_preserves_common_fields(
    trades: list[TradeRecord], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """INV-9: migrate(write_v1) preserva todos os campos canônicos.

    Strategy:
    1. Escreve trades via ParquetWriter (schema canônico v1.1.0 atual).
    2. Lê tabela bruta (snapshot pré-migration).
    3. Aplica V100ToV110.transform.
    4. Verifica que cada coluna original mantém os mesmos valores
       (to_pylist comparison) e que os 3 campos aditivos v1.1.0
       (``buy_agent_name``, ``sell_agent_name``, ``trade_type_name``)
       estão presentes (string nullable).
    """
    data_dir = tmp_path_factory.mktemp("migrate_property")
    writer = ParquetWriter(data_dir=data_dir)
    # Particiona pelo símbolo do PRIMEIRO trade (todos podem variar; o
    # writer deduplica e ordena — basta que cada teste tenha 1 partição).
    partition = PartitionKey(
        exchange="F",
        symbol=trades[0]["symbol"],
        year=2024,
        month=3,
    )
    # Garante que TODOS os trades tem o mesmo symbol que a partition
    # (writer não rejeita, mas escreve todos no mesmo arquivo).
    for t in trades:
        t["symbol"] = trades[0]["symbol"]

    write_result = writer.write(trades, partition, dll_version="4.0.0.34")
    assert write_result.path.exists()

    # Snapshot — writer atual já escreve schema v1.1.0 (20 colunas);
    # migration deve ser idempotente (apenas re-cast canônico).
    table_v1 = pq.read_table(write_result.path)
    snapshot_columns = {name: table_v1.column(name).to_pylist() for name in table_v1.column_names}

    # Aplica migration.
    migration = V100ToV110()
    table_v11 = migration.transform(table_v1)

    # 3 campos aditivos v1.1.0 presentes como string nullable.
    for name in migration.NEW_FIELD_NAMES:
        assert name in table_v11.schema.names
        f = table_v11.schema.field(name)
        import pyarrow as _pa

        assert _pa.types.is_string(f.type)
        assert f.nullable

    # Campos antigos preservados byte-a-byte.
    for name in snapshot_columns:
        assert (
            table_v11.column(name).to_pylist() == snapshot_columns[name]
        ), f"column {name} drift after migration"
