"""Unit tests — translate failure telemetry split (Story 1.7g) +
translate-in-callback (v1.2.0 / COUNCIL-38 / Q-DRIFT-40).

Com translate-in-callback o grosso das falhas é contado IN-CALLBACK
(``callbacks.make_history_trade_callback_v2`` → ``stats``):

- ``translate_nl_errors``: ``translate_trade`` retornou ``None`` (rc!=0 da
  DLL ou struct sentinela zerado Q-DRIFT-34 que o wrapper filtra → None).
- ``translate_invalid_price_skips``: ``price <= 0`` (Q-DRIFT-38).
- ``queue_dropped``: ``put_nowait`` levantou ``queue.Full``.

O ``_IngestorThread`` mantém apenas counters RESIDUAIS de defense-in-depth:
- ``translate_sentinel_skips``: TradeFields com ``timestamp_ns < 0`` escapou.
- ``translate_exceptions``: exception Python inesperada em ``_process_trade``.
- ``translate_invalid_price_skips``: ``price <= 0`` escapou do callback.
- ``translate_failures`` = ``sentinel_skips + exceptions`` (back-compat).
"""

from __future__ import annotations

import threading
from queue import Queue
from unittest.mock import MagicMock

import pytest

from data_downloader.dll.callbacks import cleanup_cb_refs, make_history_trade_callback_v2
from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields
from data_downloader.orchestrator.download_primitive import _IngestorThread


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    cleanup_cb_refs()
    yield
    cleanup_cb_refs()


def _tf(*, ts_ns: int = 1_700_000_000_000_000_000, price: float = 100.0, n: int = 1) -> TradeFields:
    return TradeFields(
        version=0,
        timestamp_ns=ts_ns,
        trade_number=n,
        price=price,
        quantity=1,
        volume=price,
        buy_agent_id=0,
        sell_agent_id=0,
        trade_type=1,
    )


def _asset() -> TConnectorAssetIdentifier:
    return TConnectorAssetIdentifier(Version=0, Ticker="WDOFUT", Exchange="F", FeedType=0)


def _stats() -> dict[str, int]:
    return {"translate_nl_errors": 0, "translate_invalid_price_skips": 0, "queue_dropped": 0}


# =====================================================================
# Callback-side counters (primary)
# =====================================================================


@pytest.mark.unit
def test_callback_counts_nl_error() -> None:
    """translate_trade -> None → stats["translate_nl_errors"] += 1."""
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=None)
    q: Queue = Queue()
    stats = _stats()
    cb = make_history_trade_callback_v2(q, dll, stats=stats)

    cb(_asset(), 0xCAFE, 0)

    assert stats["translate_nl_errors"] == 1
    assert stats["translate_invalid_price_skips"] == 0
    assert q.qsize() == 0


@pytest.mark.unit
def test_callback_counts_invalid_price() -> None:
    """price <= 0 → stats["translate_invalid_price_skips"] += 1."""
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=_tf(price=0.0))
    q: Queue = Queue()
    stats = _stats()
    cb = make_history_trade_callback_v2(q, dll, stats=stats)

    cb(_asset(), 0x1, 0)

    assert stats["translate_invalid_price_skips"] == 1
    assert stats["translate_nl_errors"] == 0
    assert q.qsize() == 0


@pytest.mark.unit
def test_callback_enqueues_valid_tradefields() -> None:
    """price > 0 + ts >= 0 → (TradeFields, flags) na fila, sem counters."""
    dll = MagicMock()
    tf = _tf(price=5500.0, n=42)
    dll.translate_trade = MagicMock(return_value=tf)
    q: Queue = Queue()
    stats = _stats()
    cb = make_history_trade_callback_v2(q, dll, stats=stats)

    cb(_asset(), 0x1, 0)

    assert stats == {
        "translate_nl_errors": 0,
        "translate_invalid_price_skips": 0,
        "queue_dropped": 0,
    }
    assert q.get_nowait() == (tf, 0)


@pytest.mark.unit
def test_callback_counters_mixed() -> None:
    """Mix de falhas distintas: cada subcontador conta separadamente."""
    dll = MagicMock()
    dll.translate_trade = MagicMock(side_effect=[None, _tf(price=-1.0), _tf(price=5500.0, n=7)])
    q: Queue = Queue()
    stats = _stats()
    cb = make_history_trade_callback_v2(q, dll, stats=stats)

    cb(_asset(), 0x1, 0)  # nl_error
    cb(_asset(), 0x2, 0)  # invalid_price
    cb(_asset(), 0x3, 0)  # ok

    assert stats["translate_nl_errors"] == 1
    assert stats["translate_invalid_price_skips"] == 1
    assert q.qsize() == 1


# =====================================================================
# Ingestor-side residual counters (defense-in-depth)
# =====================================================================


def _make_thread(queue: Queue) -> _IngestorThread:
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=None)
    return _IngestorThread(
        dll=MagicMock(),  # type: ignore[arg-type]
        trade_queue=queue,
        symbol="WDOFUT",
        exchange="F",
        chunk_id="chunk-telemetry-split",
        dll_version="4.0.0.34",
        stop_event=threading.Event(),
        agent_resolver=resolver,
    )


@pytest.mark.unit
def test_ingestor_residual_counters_initialize_to_zero() -> None:
    thread = _make_thread(Queue())
    assert thread.translate_sentinel_skips == 0
    assert thread.translate_exceptions == 0
    assert thread.translate_invalid_price_skips == 0
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_ingestor_residual_sentinel_guard() -> None:
    """TradeFields com ts < 0 escapou do filtro → sentinel_skips + failures."""
    thread = _make_thread(Queue())
    thread._process_trade(_tf(ts_ns=-1), flags=0)

    assert thread.translate_sentinel_skips == 1
    assert thread.translate_failures == 1
    assert len(thread.trades) == 0


@pytest.mark.unit
def test_ingestor_residual_exception_counter() -> None:
    """Exception em _process_trade → translate_exceptions + failures (thread sobrevive)."""
    queue: Queue = Queue()
    thread = _make_thread(queue)
    original = thread._process_trade
    calls = {"n": 0}

    def _wrapped(fields: TradeFields, flags: int) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        original(fields, flags)

    thread._process_trade = _wrapped  # type: ignore[method-assign]
    queue.put((_tf(n=1), 0))
    queue.put((_tf(n=2), 0))
    thread._stop_event.set()
    thread._run_inner()

    assert thread.translate_exceptions == 1
    assert thread.translate_failures == 1
    assert len(thread.trades) == 1
