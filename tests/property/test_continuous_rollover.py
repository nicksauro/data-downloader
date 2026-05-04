"""Property tests — read_continuous rollover invariants (Story 1.5b AC6/AC7).

Hypothesis properties:

- **P1 (chunking não afeta resultado):** união de
  ``read_continuous(root, sub_range)`` por chunks ⊆ resultado direto
  ``read_continuous(root, full_range)`` (mesmas linhas, mesma ordem).
- **P2 (sem duplicatas em rollover):** trades fronteira aparecem
  exatamente UMA vez na concatenação multi-contrato.
- **P3 (ordering monotônica cross-contract):** ``timestamp_ns`` é
  sempre não-decrescente no resultado, mesmo cruzando rollover.

Setup: 3 contratos sintéticos contíguos (jan/fev/mar 2026), cada um com
N trades distribuídos uniformemente no seu range. Hypothesis varia (a)
quantos trades por contrato, (b) janelas de query, (c) chunking.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
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
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/01/2026 00:00:00.000",
        price=5_000.0 + (trade_id % 100) * 0.5,
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


def _setup_three_contracts(
    data_dir: Path,
    *,
    n_per_contract: int,
) -> Catalog:
    """Cria catalog com 3 contratos contíguos + escreve N trades em cada."""
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

    bases = [
        (
            PartitionKey(exchange="F", symbol="WDOG26", year=2026, month=1),
            "WDOG26",
            _to_ns(datetime(2026, 1, 15, 9, 0, 0)),
        ),
        (
            PartitionKey(exchange="F", symbol="WDOH26", year=2026, month=2),
            "WDOH26",
            _to_ns(datetime(2026, 2, 15, 9, 0, 0)),
        ),
        (
            PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3),
            "WDOJ26",
            _to_ns(datetime(2026, 3, 15, 9, 0, 0)),
        ),
    ]
    writer = ParquetWriter(data_dir=data_dir)
    trade_id_counter = 0
    for partition, code, base_ns in bases:
        trades = [
            _make_trade(
                symbol=code,
                ts_ns=base_ns + i * 1_000_000,
                trade_id=trade_id_counter + i,
            )
            for i in range(n_per_contract)
        ]
        trade_id_counter += n_per_contract
        writer.write(trades, partition, dll_version="4.0.0.34")
    return cat


# =====================================================================
# Property 1 — chunking does not affect result
# =====================================================================


@given(
    n_per_contract=st.integers(min_value=2, max_value=15),
    split_idx=st.integers(min_value=1, max_value=2),
)
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_chunking_invariance(n_per_contract: int, split_idx: int) -> None:
    """P1: ``read_continuous`` chunked == ``read_continuous`` direto.

    Quebra o range de 3 meses em 2 sub-ranges (split em fev ou mar)
    e verifica que a UNIÃO ordenada == leitura direta do range full.
    """
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_three_contracts(data_dir, n_per_contract=n_per_contract)
        try:
            full_start = datetime(2026, 1, 1)
            full_end = datetime(2026, 3, 31, 23, 59, 59)

            # Direct read (full range).
            direct = read_continuous(
                "WDO",
                full_start,
                full_end,
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )

            # Chunked read: split em [full_start, mid] + (mid, full_end].
            mid_month = 1 + split_idx  # 2 (fev) ou 3 (mar)
            mid_dt = datetime(2026, mid_month, 1)
            mid_ns_minus_1us = mid_dt - timedelta(microseconds=1)
            chunk1 = read_continuous(
                "WDO",
                full_start,
                mid_ns_minus_1us,
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )
            chunk2 = read_continuous(
                "WDO",
                mid_dt,
                full_end,
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )

            # Cardinalidade combinada == direct.
            assert chunk1.num_rows + chunk2.num_rows == direct.num_rows, (
                f"chunked sum {chunk1.num_rows + chunk2.num_rows} != " f"direct {direct.num_rows}"
            )

            # timestamps individualmente são subconjuntos disjuntos do direct.
            ts_direct = direct.column("timestamp_ns").to_pylist()
            ts_chunked = (
                chunk1.column("timestamp_ns").to_pylist()
                + chunk2.column("timestamp_ns").to_pylist()
            )
            assert sorted(ts_chunked) == ts_direct
        finally:
            cat.close()


# =====================================================================
# Property 2 — no duplicates in rollover boundary
# =====================================================================


@given(
    n_per_contract=st.integers(min_value=3, max_value=20),
)
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_no_duplicates_at_rollover(n_per_contract: int) -> None:
    """P2: trades não são duplicados em fronteira de rollover.

    Verifica que ``(timestamp_ns, _contract_code)`` é único — nunca o
    mesmo (ts, code) aparece 2x — e que o número total de linhas é
    EXATAMENTE ``3 * n_per_contract`` (nada perdido, nada duplicado).
    """
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_three_contracts(data_dir, n_per_contract=n_per_contract)
        try:
            table = read_continuous(
                "WDO",
                datetime(2026, 1, 1),
                datetime(2026, 3, 31, 23, 59, 59),
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )

            # Sem perdas: 3 contratos * n trades cada.
            assert table.num_rows == 3 * n_per_contract

            # Sem duplicatas em (ts_ns, contract_code).
            ts_list = table.column("timestamp_ns").to_pylist()
            codes_list = table.column("_contract_code").to_pylist()
            pairs = list(zip(ts_list, codes_list, strict=True))
            assert len(pairs) == len(set(pairs)), "duplicate (ts, code) pair detected"
        finally:
            cat.close()


# =====================================================================
# Property 3 — ordering preserved cross-contract
# =====================================================================


@given(
    n_per_contract=st.integers(min_value=2, max_value=20),
)
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_ordering_monotonic_cross_contract(n_per_contract: int) -> None:
    """P3: ``timestamp_ns`` é não-decrescente cross-contract."""
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_three_contracts(data_dir, n_per_contract=n_per_contract)
        try:
            table = read_continuous(
                "WDO",
                datetime(2026, 1, 1),
                datetime(2026, 3, 31, 23, 59, 59),
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )
            ts = table.column("timestamp_ns").to_pylist()
            for i in range(1, len(ts)):
                assert ts[i] >= ts[i - 1], f"non-monotonic at index {i}: {ts[i - 1]} > {ts[i]}"
        finally:
            cat.close()


# =====================================================================
# Property 4 — _contract_code never reverts (monotonic per Sol §2.1)
# =====================================================================


@pytest.mark.property
def test_contract_code_never_reverts() -> None:
    """Sol QUERIES.md §2.1: ``_contract_code`` é monotônico — uma vez
    trocado, não volta a um contrato anterior."""
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_three_contracts(data_dir, n_per_contract=5)
        try:
            table = read_continuous(
                "WDO",
                datetime(2026, 1, 1),
                datetime(2026, 3, 31, 23, 59, 59),
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )
            codes = table.column("_contract_code").to_pylist()
            seen: list[str] = []
            for c in codes:
                if not seen or c != seen[-1]:
                    if c in seen:
                        pytest.fail(f"contract {c} reappears after {seen[-1]}")
                    seen.append(c)
            # Ordem esperada: WDOG26 → WDOH26 → WDOJ26
            assert seen == ["WDOG26", "WDOH26", "WDOJ26"]
        finally:
            cat.close()


# =====================================================================
# Property 5 — WIN quarterly rollover H→M→U→Z (Story 4.2 AC4)
# =====================================================================


def _setup_four_win_contracts(
    data_dir: Path,
    *,
    n_per_contract: int,
) -> Catalog:
    """Cria catalog com 4 WIN trimestrais 2026 (H/M/U/Z) + escreve trades.

    Janelas trimestrais simplificadas (90 dias cada) para evitar
    dependência da regra B3 exata (Q18-OPEN). Property test exercita
    APENAS a integração `read_continuous` cross-trimestre — vigências
    reais do seed são validadas em ``test_contracts_multi_asset.py``.
    """
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            ("WIN", "WINH26", "2026-01-01 00:00:00", "2026-03-31 00:00:00"),
            ("WIN", "WINM26", "2026-04-01 00:00:00", "2026-06-30 00:00:00"),
            ("WIN", "WINU26", "2026-07-01 00:00:00", "2026-09-30 00:00:00"),
            ("WIN", "WINZ26", "2026-10-01 00:00:00", "2026-12-31 00:00:00"),
        ]
        for root, code, vf, vu in rows:
            conn.execute(
                "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
                "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'hypothesized')",
                (root, code, vf, vu),
            )

    bases = [
        (
            PartitionKey(exchange="F", symbol="WINH26", year=2026, month=2),
            "WINH26",
            _to_ns(datetime(2026, 2, 15, 9, 0, 0)),
        ),
        (
            PartitionKey(exchange="F", symbol="WINM26", year=2026, month=5),
            "WINM26",
            _to_ns(datetime(2026, 5, 15, 9, 0, 0)),
        ),
        (
            PartitionKey(exchange="F", symbol="WINU26", year=2026, month=8),
            "WINU26",
            _to_ns(datetime(2026, 8, 15, 9, 0, 0)),
        ),
        (
            PartitionKey(exchange="F", symbol="WINZ26", year=2026, month=11),
            "WINZ26",
            _to_ns(datetime(2026, 11, 15, 9, 0, 0)),
        ),
    ]
    writer = ParquetWriter(data_dir=data_dir)
    trade_id_counter = 0
    for partition, code, base_ns in bases:
        trades = [
            _make_trade(
                symbol=code,
                ts_ns=base_ns + i * 1_000_000,
                trade_id=trade_id_counter + i,
            )
            for i in range(n_per_contract)
        ]
        trade_id_counter += n_per_contract
        writer.write(trades, partition, dll_version="4.0.0.34")
    return cat


@given(
    n_per_contract=st.integers(min_value=2, max_value=10),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_win_quarterly_rollover_concatenates_4_contracts(n_per_contract: int) -> None:
    """Story 4.2 AC4 (P5) — WIN H/M/U/Z 26 concatenados sem dup nem perda.

    Verifica:
    - ``read_continuous("WIN", ano_inteiro)`` retorna ``4 * n`` trades.
    - Sequência de contratos é H → M → U → Z (sem reversão).
    - 3 rollover events (N-1 para N=4 contratos com dados).
    - Sem duplicatas (timestamp_ns, _contract_code).
    """
    with tempfile.TemporaryDirectory() as td:
        data_dir = Path(td) / "data"
        cat = _setup_four_win_contracts(data_dir, n_per_contract=n_per_contract)
        try:
            table = read_continuous(
                "WIN",
                datetime(2026, 1, 1),
                datetime(2026, 12, 31, 23, 59, 59),
                exchange="F",
                catalog=cat,
                data_dir=data_dir,
            )

            # Sem perdas: 4 contratos x n_per_contract.
            assert table.num_rows == 4 * n_per_contract

            # Ordem e monotonicidade dos contratos.
            codes = table.column("_contract_code").to_pylist()
            seen: list[str] = []
            for c in codes:
                if not seen or c != seen[-1]:
                    seen.append(c)
            assert seen == ["WINH26", "WINM26", "WINU26", "WINZ26"]

            # 3 rollover events.
            flags = table.column("_rollover_event").to_pylist()
            assert sum(flags) == 3

            # Sem duplicatas em (ts, code).
            ts_list = table.column("timestamp_ns").to_pylist()
            pairs = list(zip(ts_list, codes, strict=True))
            assert len(pairs) == len(set(pairs))
        finally:
            cat.close()
