"""tests/unit/test_ingestor_thread_sentinel.py — Q-DRIFT-34 (Story 1.7d) +
Q-DRIFT-40 (v1.2.0 — translate-in-callback).

Q-DRIFT-34: callback V2 dispara primeiro com ``TConnectorTrade`` ZERADO
(struct sentinela). DLL retorna ``rc=0`` mas timestamp resolvido fica
negativo (FILETIME 1601-01-01). ``format_brt_timestamp(ns < 0)`` levanta
``ValueError`` → ``IngestorThread`` morre, drenagem para.

v1.2.0 (COUNCIL-38 / Q-DRIFT-40): a tradução é feita DENTRO do callback V2,
que filtra sentinela (``translate_trade`` retorna ``None``) e conta em
``stats["translate_nl_errors"]``. O ``_IngestorThread`` recebe a fila já com
``TradeFields`` — mantém apenas guards RESIDUAIS de defense-in-depth
(``timestamp_ns < 0`` escapou do filtro do wrapper → conta em
``translate_sentinel_skips`` / ``translate_failures`` e a thread sobrevive).

Cobertura:

1. ``_IngestorThread._process_trade(fields, flags)`` — guard residual de
   timestamp negativo incrementa ``translate_sentinel_skips`` /
   ``translate_failures`` e RETORNA (não levanta).
2. ``_IngestorThread._run_inner`` — defense-in-depth: qualquer exception
   dentro de ``_process_trade`` é capturada e contada como
   ``translate_exceptions`` / ``translate_failures`` (thread continua viva).
"""

from __future__ import annotations

import threading
from queue import Queue
from unittest.mock import MagicMock

import pytest

from data_downloader.dll.types import TradeFields
from data_downloader.orchestrator.download_primitive import _IngestorThread


def _make_thread(queue: Queue) -> _IngestorThread:
    """Helper: monta ``_IngestorThread`` com agent_resolver mockado."""
    stop_event = threading.Event()
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=None)
    return _IngestorThread(
        dll=MagicMock(),  # type: ignore[arg-type]
        trade_queue=queue,
        symbol="WDOFUT",
        exchange="F",
        chunk_id="chunk-q-drift-34",
        dll_version="4.0.0.34",
        stop_event=stop_event,
        agent_resolver=resolver,
    )


def _tf(*, ts_ns: int, price: float = 100.0, n: int = 1) -> TradeFields:
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


@pytest.mark.unit
def test_process_trade_residual_guard_skips_negative_timestamp() -> None:
    """Q-DRIFT-34 (guard residual): TradeFields com timestamp_ns < 0 → skip sem raise.

    O callback/wrapper já filtra structs sentinela; se algo escapar (drift
    entre versões) o ingestor descarta como falha residual — ``format_brt_
    timestamp`` NÃO deve ser chamado em ns < 0.
    """
    queue: Queue = Queue()
    thread = _make_thread(queue)

    thread._process_trade(_tf(ts_ns=-2_209_161_600_000_000_000), flags=0)

    assert thread.translate_sentinel_skips == 1
    assert thread.translate_failures == 1
    assert len(thread.trades) == 0


@pytest.mark.unit
def test_process_trade_accepts_valid_tradefields() -> None:
    """Sanity / não-regressão: TradeFields válido produz TradeRecord."""
    queue: Queue = Queue()
    thread = _make_thread(queue)

    thread._process_trade(_tf(ts_ns=1_700_000_000_000_000_000, n=42), flags=0)

    assert thread.translate_failures == 0
    assert len(thread.trades) == 1
    assert thread.trades[0].trade_id == 42


@pytest.mark.unit
def test_run_inner_survives_exception_in_process_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defense-in-depth: exception em ``_process_trade`` NÃO mata a thread.

    Qualquer exception inesperada no hot path é capturada em ``_run_inner`` e
    contada como ``translate_exceptions`` / ``translate_failures``. A thread
    continua viva e drena os próximos itens.
    """
    queue: Queue = Queue()
    valid = _tf(ts_ns=1_700_000_000_000_000_000, n=42)
    bad = _tf(ts_ns=1_700_000_000_000_000_000, n=7)

    thread = _make_thread(queue)
    # 1ª chamada de _process_trade levanta; 2ª segue normal.
    original = thread._process_trade
    calls = {"n": 0}

    def _wrapped(fields: TradeFields, flags: int) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom — falha inesperada")
        original(fields, flags)

    monkeypatch.setattr(thread, "_process_trade", _wrapped)

    queue.put((bad, 0))
    queue.put((valid, 0))
    thread._stop_event.set()
    thread._run_inner()

    assert thread.translate_exceptions == 1
    assert thread.translate_failures == 1
    assert len(thread.trades) == 1
    assert thread.trades[0].trade_id == 42
