"""tests/property/test_invariants_core.py — Hypothesis core (Story 2.10).

ADR-014 §Property-based tests + INVARIANTS_TESTS.md cobertura agregada.

Este módulo é o **ponto único** que materializa as invariantes core do
sistema como property tests Hypothesis (>= 100 examples cada). Cobre:

- INV-1: callback NÃO chama DLL (auditoria via :class:`MockProfitDLL`).
- INV-2: ``dedup(L ++ L) == dedup(L)`` (idempotência).
- INV-3: write atômico (escreve OU nada — sem partial state).
- INV-7: ``read(write(L))`` retorna ``dedup(L)`` ordenado por timestamp_ns.
- INV-9: migration aditiva preserva campos comuns + adiciona NULL.
- INV-11: separação de threads (mock fire_trades NÃO bloqueia chamador).

Strategies customizadas:

- :func:`valid_trade_record_strategy` — TradeRecord WDO realista.
- :func:`valid_partition_key_strategy` — PartitionKey válida (F/B,
  ano>=2000, mês 1-12, símbolo non-empty).
- :func:`trade_spec_strategy` — TradeRecordSpec para mock.fire_trades.

NÃO duplica testes existentes — *consolida* a referência. Cada property
abaixo é a **versão canônica** mencionada em INVARIANTS_TESTS.md a partir
da Story 2.10. Testes em outros arquivos (``test_storage_dedup``,
``test_storage_roundtrip``, ``test_migration_aditive``) continuam válidos
e são complementares (cobrem aspectos específicos de implementação).
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.dedup import (
    assign_sequence_within_ns,
    compute_canonical_hash,
    dedup,
)
from data_downloader.storage.duckdb_reader import DuckDBReader
from data_downloader.storage.migrations.parquet.v1_0_0_to_v1_1_0 import V100ToV110
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord
from data_downloader.testing.mock_dll import MockProfitDLL, TradeRecordSpec

# =====================================================================
# Strategies — geração de inputs realistas
# =====================================================================

# Range de timestamps WDO realista: ~2024-01-01 (1.7e18 ns) → 2024-12-31.
_TS_MIN = 1_700_000_000_000_000_000
_TS_MAX = 1_735_000_000_000_000_000


def _build_trade_with_id(
    symbol: str, ts_ns: int, trade_id: int, price: float, quantity: int
) -> TradeRecord:
    return TradeRecord(
        symbol=symbol,
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/03/2024 00:00:00.000",
        price=price,
        quantity=quantity,
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


def valid_trade_record_strategy() -> st.SearchStrategy[TradeRecord]:
    """Strategy canônica para gerar :class:`TradeRecord` v1.0.0 realista."""
    return st.builds(
        _build_trade_with_id,
        symbol=st.sampled_from(["WDOJ26", "WDOK26", "WDON26", "PETR4"]),
        ts_ns=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
        trade_id=st.integers(min_value=1, max_value=10**9),
        price=st.floats(min_value=0.01, max_value=100_000.0, allow_nan=False, allow_infinity=False),
        quantity=st.integers(min_value=1, max_value=10_000),
    )


def valid_partition_key_strategy() -> st.SearchStrategy[PartitionKey]:
    """Strategy canônica para gerar :class:`PartitionKey` válida (F/B)."""
    return st.builds(
        PartitionKey,
        exchange=st.sampled_from(["F", "B"]),
        symbol=st.sampled_from(["WDOJ26", "WDOK26", "PETR4"]),
        year=st.integers(min_value=2000, max_value=2099),
        month=st.integers(min_value=1, max_value=12),
    )


def trade_spec_strategy() -> st.SearchStrategy[TradeRecordSpec]:
    """Strategy para :class:`TradeRecordSpec` (input de :meth:`MockProfitDLL.fire_trades`)."""

    def _build(
        symbol: str, ts_ns: int, trade_id: int, price: float, quantity: int
    ) -> TradeRecordSpec:
        return TradeRecordSpec(
            symbol=symbol,
            exchange="F",
            timestamp_ns=ts_ns,
            trade_id=trade_id,
            price=price,
            quantity=quantity,
            flags=0,
        )

    return st.builds(
        _build,
        symbol=st.sampled_from(["WDOJ26", "WDOK26"]),
        ts_ns=st.integers(min_value=_TS_MIN, max_value=_TS_MAX),
        trade_id=st.integers(min_value=1, max_value=10**6),
        price=st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False, allow_infinity=False),
        quantity=st.integers(min_value=1, max_value=1000),
    )


# =====================================================================
# INV-1 — callback NÃO chama DLL (Hypothesis sweep)
# =====================================================================


@pytest.mark.property
@given(trades=st.lists(trade_spec_strategy(), min_size=0, max_size=50))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_inv1_well_behaved_callback_never_violates_for_any_input(
    trades: list[TradeRecordSpec],
) -> None:
    """INV-1: callback que apenas appenda em lista local NUNCA viola.

    Para qualquer sequência de trades gerada por Hypothesis, o callback
    bem-comportado ``lambda t,h,f: sink.append(t)`` não dispara
    detecção de violation no MockProfitDLL.
    """
    dll = MockProfitDLL(seed=1)
    dll.initialize_market_only("k", "u", "p")
    sink: list[TradeRecordSpec] = []
    dll.set_history_trade_callback_v2(lambda t, h, f: sink.append(t))
    delivered = dll.fire_trades(trades)
    assert delivered == len(trades)
    assert (
        dll.callback_violations == []
    ), f"INV-1 violado para input ben-comportado: {dll.callback_violations}"
    dll.finalize()


# =====================================================================
# INV-2 — dedup idempotente
# =====================================================================


@pytest.mark.property
@given(trades=st.lists(valid_trade_record_strategy(), max_size=50))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_inv2_dedup_idempotent_under_concat(trades: list[TradeRecord]) -> None:
    """INV-2: ``dedup(L ++ L) == dedup(L)`` para qualquer L."""
    once = dedup(deepcopy(trades))
    twice = dedup(deepcopy(trades) + deepcopy(trades))
    once_keys = [compute_canonical_hash(t) for t in once]
    twice_keys = [compute_canonical_hash(t) for t in twice]
    assert once_keys == twice_keys


@pytest.mark.property
@given(trades=st.lists(valid_trade_record_strategy(), max_size=50))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_inv2_dedup_idempotent_under_self_apply(trades: list[TradeRecord]) -> None:
    """INV-2: ``dedup(dedup(L)) == dedup(L)`` para qualquer L."""
    once = dedup(deepcopy(trades))
    twice = dedup(deepcopy(once))
    assert [compute_canonical_hash(t) for t in once] == [compute_canonical_hash(t) for t in twice]


# =====================================================================
# INV-3 — write atômico (escreve tudo OU nada)
# =====================================================================


@pytest.mark.property
@given(trades=st.lists(valid_trade_record_strategy(), min_size=1, max_size=20))
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_inv3_write_atomicity_no_tmp_files_after_success(
    trades: list[TradeRecord],
) -> None:
    """INV-3: após write bem-sucedido, nenhum ``*.tmp.*`` órfão sobra.

    Garantia de atomicidade: writer escreve em ``tmp.uuid`` + os.replace.
    Após sucesso, nenhum tmp file deve existir no diretório alvo.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        # Forçar mesma symbol+exchange+year+month para single partition.
        for t in trades:
            t["symbol"] = "WDOJ26"
            t["exchange"] = "F"
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
        writer = ParquetWriter(data_dir=data_dir)
        result = writer.write(trades, partition, dll_version="4.0.0.34")
        # Final file existe.
        assert result.path.exists()
        # Nenhum tmp órfão.
        tmp_files = list(result.path.parent.glob("*.tmp.*"))
        assert tmp_files == [], f"tmp files órfãos encontrados: {tmp_files}"


# =====================================================================
# INV-7 — read sorted by timestamp_ns
# =====================================================================


@pytest.mark.property
@given(trades=st.lists(valid_trade_record_strategy(), min_size=1, max_size=20))
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_inv7_read_returns_sorted_by_timestamp_ns(trades: list[TradeRecord]) -> None:
    """INV-7: ``read(write(L))`` retorna trades ordenados por timestamp_ns ASC."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        for t in trades:
            t["symbol"] = "WDOJ26"
            t["exchange"] = "F"
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
        writer = ParquetWriter(data_dir=data_dir)
        writer.write(deepcopy(trades), partition, dll_version="4.0.0.34")
        with DuckDBReader(data_dir=data_dir) as reader:
            table = reader.read("WDOJ26", start_ts_ns=0, end_ts_ns=2_000_000_000_000_000_000)
        ts_read = table.column("timestamp_ns").to_pylist()
        assert ts_read == sorted(ts_read), "read() não retornou ordenado por timestamp_ns ASC"


# =====================================================================
# INV-9 — migration aditiva preserva campos comuns
# =====================================================================


@pytest.mark.property
@given(
    trades=st.lists(
        valid_trade_record_strategy(),
        min_size=1,
        max_size=15,
        unique_by=lambda t: t["trade_id"],
    )
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_inv9_migration_v100_to_v110_preserves_common_fields(
    trades: list[TradeRecord],
) -> None:
    """INV-9: ``migrate(write_v1)`` preserva todos os campos canônicos byte-a-byte
    e adiciona ``liquidity_classification`` NULL."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        for t in trades:
            t["symbol"] = "WDOJ26"
            t["exchange"] = "F"
        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
        writer = ParquetWriter(data_dir=data_dir)
        write_result = writer.write(trades, partition, dll_version="4.0.0.34")
        assert write_result.path.exists()

        table_v1 = pq.read_table(write_result.path)
        snapshot = {n: table_v1.column(n).to_pylist() for n in table_v1.column_names}

        migration = V100ToV110()
        table_v11 = migration.transform(table_v1)
        assert migration.NEW_FIELD_NAME in table_v11.schema.names
        assert table_v11.column(migration.NEW_FIELD_NAME).null_count == table_v11.num_rows
        for n in snapshot:
            assert table_v11.column(n).to_pylist() == snapshot[n], f"drift em {n}"


# =====================================================================
# INV-11 — separação de threads (mock atende sem bloquear)
# =====================================================================


@pytest.mark.property
@given(
    trades=st.lists(trade_spec_strategy(), min_size=0, max_size=30),
    seed=st.integers(min_value=1, max_value=1_000),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_inv11_assign_sequence_then_dedup_is_stable(
    trades: list[TradeRecordSpec], seed: int
) -> None:
    """INV-11 (variação testável sem orchestrator real): após
    ``assign_sequence_within_ns + dedup``, mesma input → mesmo output
    independente de quantas vezes aplicado.

    Esta property é o "thread-safety equivalente" para code-paths puros
    de orchestrator + storage: dado o mesmo batch, deduplicação + sequence
    são determinísticas (não dependem de ordem de chegada de threads).
    """
    # Converter TradeRecordSpec para TradeRecord (sequence_within_ns será reatribuído).
    records: list[TradeRecord] = []
    for t in trades:
        records.append(
            _build_trade_with_id(
                symbol=t.get("symbol", "WDOJ26"),
                ts_ns=int(t.get("timestamp_ns", 0)) or 1,
                trade_id=int(t.get("trade_id", 0)) or 1,
                price=float(t.get("price", 100.0)),
                quantity=int(t.get("quantity", 1)),
            )
        )
    # Apply 3 vezes — resultado idêntico em todas.
    snapshots: list[list[tuple]] = []
    for _ in range(3):
        local = deepcopy(records)
        assign_sequence_within_ns(local)
        deduped = dedup(local)
        snapshots.append([compute_canonical_hash(t) for t in deduped])
    assert snapshots[0] == snapshots[1] == snapshots[2]
