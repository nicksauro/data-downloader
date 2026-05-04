"""Unit tests — storage.dedup (Story 1.4, AC10 / INV-2).

Cobertura:

- Property (Hypothesis): ``dedup(L ++ L) == dedup(L)`` (INV-2).
- Property (Hypothesis): ``dedup(dedup(L)) == dedup(L)``.
- Variante curta: dedup com ``trade_id`` usa chave V2.
- Variante longa: dedup sem ``trade_id`` usa chave V1 + sequence.
- ``assign_sequence_within_ns`` atribui 0..N por bucket
  ``(symbol, timestamp_ns)``.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.storage.dedup import (
    assign_sequence_within_ns,
    compute_canonical_hash,
    dedup,
)
from data_downloader.storage.schema import TradeRecord


def _trade_with_id(symbol: str, ts_ns: int, trade_id: int) -> TradeRecord:
    """Helper: trade V2 mínimo (com trade_id)."""
    return TradeRecord(
        symbol=symbol,
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/03/2024 00:00:00.000",
        price=100.0,
        quantity=1,
        trade_id=trade_id,
        trade_type=2,
        buy_agent_id=None,
        sell_agent_id=None,
        flags=0,
        source_callback="history_v2",
        side=None,
        ingestion_ts_ns=1,
        chunk_id=None,
        dll_version="x",
        sequence_within_ns=0,
    )


def _trade_no_id(
    symbol: str,
    ts_ns: int,
    price: float,
    quantity: int,
    sequence: int,
    buy_agent: int | None = None,
    sell_agent: int | None = None,
) -> TradeRecord:
    """Helper: trade V1 mínimo (sem trade_id)."""
    return TradeRecord(
        symbol=symbol,
        exchange="F",
        timestamp_ns=ts_ns,
        timestamp_str="01/03/2024 00:00:00.000",
        price=price,
        quantity=quantity,
        trade_id=None,
        trade_type=2,
        buy_agent_id=buy_agent,
        sell_agent_id=sell_agent,
        flags=0,
        source_callback="history_v1",
        side=None,
        ingestion_ts_ns=1,
        chunk_id=None,
        dll_version="x",
        sequence_within_ns=sequence,
    )


# Estratégia Hypothesis: trades V2 (com trade_id) — chave curta.
_v2_trade = st.builds(
    _trade_with_id,
    symbol=st.sampled_from(["WDOJ26", "WDOH26", "PETR4"]),
    ts_ns=st.integers(min_value=1_700_000_000_000_000_000, max_value=1_800_000_000_000_000_000),
    trade_id=st.integers(min_value=0, max_value=1_000_000),
)


# =====================================================================
# Property tests — INV-2
# =====================================================================


@given(trades=st.lists(_v2_trade, max_size=50))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_dedup_idempotent_under_concat(trades: list[TradeRecord]) -> None:
    """``dedup(L ++ L) == dedup(L)`` (INV-2)."""
    once = dedup(deepcopy(trades))
    twice = dedup(deepcopy(trades) + deepcopy(trades))
    # Comparar como conjuntos de chaves canônicas (ordem pode variar mas
    # a primeira ocorrência sempre vence).
    once_keys = [compute_canonical_hash(t) for t in once]
    twice_keys = [compute_canonical_hash(t) for t in twice]
    assert once_keys == twice_keys


@given(trades=st.lists(_v2_trade, max_size=50))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_dedup_idempotent_under_self_apply(trades: list[TradeRecord]) -> None:
    """``dedup(dedup(L)) == dedup(L)``."""
    once = dedup(deepcopy(trades))
    twice = dedup(deepcopy(once))
    assert [compute_canonical_hash(t) for t in once] == [compute_canonical_hash(t) for t in twice]


# =====================================================================
# Variante curta — chave V2
# =====================================================================


@pytest.mark.unit
def test_dedup_v2_uses_short_key() -> None:
    """Trades com mesmo (symbol, ts, trade_id) são dedupados, mesmo com price diferente."""
    a = _trade_with_id("WDOJ26", 1_000_000, 42)
    b = _trade_with_id("WDOJ26", 1_000_000, 42)
    b["price"] = 999.0  # noise — chave curta ignora price
    result = dedup([a, b])
    assert len(result) == 1
    assert result[0]["price"] == 100.0  # primeira ocorrência vence


@pytest.mark.unit
def test_dedup_v2_distinct_trade_ids_kept() -> None:
    """Trade_ids distintos no mesmo (symbol, ts) são preservados."""
    a = _trade_with_id("WDOJ26", 1_000_000, 1)
    b = _trade_with_id("WDOJ26", 1_000_000, 2)
    result = dedup([a, b])
    assert len(result) == 2


# =====================================================================
# Variante longa — chave V1 + sequence
# =====================================================================


@pytest.mark.unit
def test_dedup_v1_uses_long_key() -> None:
    """Sem trade_id, mesma chave longa -> dedup."""
    a = _trade_no_id("WDOJ26", 1_000_000, 100.0, 1, 0)
    b = _trade_no_id("WDOJ26", 1_000_000, 100.0, 1, 0)
    result = dedup([a, b])
    assert len(result) == 1


@pytest.mark.unit
def test_dedup_v1_sequence_distinguishes() -> None:
    """Mesmo (symbol, ts, price, qty) mas sequence distinto -> ambos preservados."""
    a = _trade_no_id("WDOJ26", 1_000_000, 100.0, 1, 0)
    b = _trade_no_id("WDOJ26", 1_000_000, 100.0, 1, 1)
    result = dedup([a, b])
    assert len(result) == 2


@pytest.mark.unit
def test_dedup_v1_agents_distinguish() -> None:
    """Agents distintos -> ambos preservados (chave longa inclui agentes)."""
    a = _trade_no_id("WDOJ26", 1_000_000, 100.0, 1, 0, buy_agent=1, sell_agent=2)
    b = _trade_no_id("WDOJ26", 1_000_000, 100.0, 1, 0, buy_agent=3, sell_agent=4)
    result = dedup([a, b])
    assert len(result) == 2


# =====================================================================
# assign_sequence_within_ns
# =====================================================================


@pytest.mark.unit
def test_assign_sequence_groups_by_symbol_and_ts() -> None:
    """3 trades no mesmo (symbol, ts) recebem 0, 1, 2."""
    trades = [
        _trade_no_id("WDOJ26", 1_000, 100.0, 1, sequence=99),  # noise
        _trade_no_id("WDOJ26", 1_000, 101.0, 2, sequence=99),
        _trade_no_id("WDOJ26", 1_000, 102.0, 3, sequence=99),
    ]
    result = assign_sequence_within_ns(trades)
    assert [t["sequence_within_ns"] for t in result] == [0, 1, 2]


@pytest.mark.unit
def test_assign_sequence_resets_per_bucket() -> None:
    """Buckets diferentes têm contadores independentes."""
    trades = [
        _trade_no_id("WDOJ26", 1_000, 100.0, 1, sequence=0),
        _trade_no_id("WDOJ26", 2_000, 100.0, 1, sequence=0),  # bucket diff
        _trade_no_id("WDOJ26", 1_000, 101.0, 1, sequence=0),  # bucket 1k
        _trade_no_id("PETR4", 1_000, 100.0, 1, sequence=0),  # symbol diff
    ]
    result = assign_sequence_within_ns(trades)
    assert [t["sequence_within_ns"] for t in result] == [0, 0, 1, 0]


@pytest.mark.unit
def test_assign_sequence_returns_same_list() -> None:
    """Função retorna a MESMA lista (in-place)."""
    trades = [_trade_no_id("WDOJ26", 1_000, 100.0, 1, sequence=0)]
    result = assign_sequence_within_ns(trades)
    assert result is trades
