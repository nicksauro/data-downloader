"""Unit tests — translate_failures telemetry split (Story 1.7g).

Cobertura Nelo Council 32 telemetry split:

- ``_IngestorThread`` mantém ``translate_failures`` como soma agregada
  (back-compat) MAS expõe 3 subcontadores por causa raiz:
  - ``translate_sentinel_skips``: Q-DRIFT-34 (struct zerado, ts<0).
  - ``translate_nl_errors``: ``translate_trade`` retornou ``None``.
  - ``translate_exceptions``: exception Python inesperada.
"""

from __future__ import annotations

import threading
from queue import Queue
from unittest.mock import MagicMock

import pytest

from data_downloader.dll.types import TradeFields
from data_downloader.orchestrator.download_primitive import _IngestorThread


def _make_thread(dll: object, queue: Queue) -> _IngestorThread:
    """Helper: monta ``_IngestorThread`` com agent_resolver mockado."""
    stop_event = threading.Event()
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=None)
    return _IngestorThread(
        dll=dll,  # type: ignore[arg-type]
        trade_queue=queue,
        symbol="WDOFUT",
        exchange="F",
        chunk_id="chunk-telemetry-split",
        dll_version="4.0.0.34",
        stop_event=stop_event,
        agent_resolver=resolver,
    )


@pytest.mark.unit
def test_subcounters_initialize_to_zero() -> None:
    """3 subcontadores são inicializados a 0 + ``translate_failures`` legacy."""
    queue: Queue = Queue()
    dll = MagicMock()
    thread = _make_thread(dll, queue)

    assert thread.translate_sentinel_skips == 0
    assert thread.translate_nl_errors == 0
    assert thread.translate_exceptions == 0
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_translate_failures_split_into_3_counters_sentinel() -> None:
    """Sentinel (Q-DRIFT-34, ts<0) incrementa ``translate_sentinel_skips``."""
    queue: Queue = Queue()
    dll = MagicMock()
    dll.translate_trade = MagicMock(
        return_value=TradeFields(
            version=0,
            timestamp_ns=-2_209_161_600_000_000_000,
            trade_number=0,
            price=0.0,
            quantity=0,
            volume=0.0,
            buy_agent_id=0,
            sell_agent_id=0,
            trade_type=0,
        )
    )
    thread = _make_thread(dll, queue)
    thread._process_trade(handle=0xCAFEBABE, flags=0)

    assert thread.translate_sentinel_skips == 1
    assert thread.translate_nl_errors == 0
    assert thread.translate_exceptions == 0
    # Back-compat: agregado continua somando.
    assert thread.translate_failures == 1


@pytest.mark.unit
def test_translate_failures_split_into_3_counters_nl_error() -> None:
    """``translate_trade -> None`` incrementa ``translate_nl_errors``."""
    queue: Queue = Queue()
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=None)

    thread = _make_thread(dll, queue)
    thread._process_trade(handle=0x1234, flags=0)

    assert thread.translate_nl_errors == 1
    assert thread.translate_sentinel_skips == 0
    assert thread.translate_exceptions == 0
    assert thread.translate_failures == 1


@pytest.mark.unit
def test_translate_failures_split_into_3_counters_exception() -> None:
    """Exception em ``_process_trade`` incrementa ``translate_exceptions``."""
    queue: Queue = Queue()
    dll = MagicMock()
    valid_fields = TradeFields(
        version=0,
        timestamp_ns=1_700_000_000_000_000_000,
        trade_number=42,
        price=100.0,
        quantity=1,
        volume=100.0,
        buy_agent_id=0,
        sell_agent_id=0,
        trade_type=1,
    )
    dll.translate_trade = MagicMock(
        side_effect=[
            RuntimeError("boom"),  # 1ª: incrementa exceptions
            valid_fields,  # 2ª: trade válido
        ]
    )

    thread = _make_thread(dll, queue)
    queue.put((0x1, 0))
    queue.put((0x2, 0))
    thread._stop_event.set()
    thread._run_inner()

    assert thread.translate_exceptions == 1
    assert thread.translate_sentinel_skips == 0
    assert thread.translate_nl_errors == 0
    assert thread.translate_failures == 1
    assert len(thread.trades) == 1


@pytest.mark.unit
def test_translate_failures_split_into_3_counters_mixed() -> None:
    """Mix de 3 falhas distintas: cada subcontador conta separadamente."""
    queue: Queue = Queue()
    dll = MagicMock()
    sentinel_fields = TradeFields(
        version=0,
        timestamp_ns=-1,  # sentinel
        trade_number=0,
        price=0.0,
        quantity=0,
        volume=0.0,
        buy_agent_id=0,
        sell_agent_id=0,
        trade_type=0,
    )
    dll.translate_trade = MagicMock(
        side_effect=[
            None,  # nl_error
            sentinel_fields,  # sentinel skip
            RuntimeError("boom"),  # exception
        ]
    )

    thread = _make_thread(dll, queue)
    queue.put((0x1, 0))
    queue.put((0x2, 0))
    queue.put((0x3, 0))
    thread._stop_event.set()
    thread._run_inner()

    assert thread.translate_nl_errors == 1
    assert thread.translate_sentinel_skips == 1
    assert thread.translate_exceptions == 1
    # Agregado: 3.
    assert thread.translate_failures == 3
