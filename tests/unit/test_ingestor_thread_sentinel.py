"""tests/unit/test_ingestor_thread_sentinel.py — Q-DRIFT-34 (Story 1.7d).

Cobertura específica do bug isolado por Quinn @qa em 2026-05-05:

Q-DRIFT-34: callback V2 dispara primeiro com ``TConnectorTrade`` ZERADO
(struct sentinela). DLL retorna ``rc=0`` mas timestamp resolvido fica
negativo (FILETIME 1601-01-01). ``format_brt_timestamp(ns < 0)`` levanta
``ValueError`` → ``IngestorThread`` morre, drenagem para mesmo com
callback V2 ainda enfileirando handles.

Este arquivo testa:

1. ``_IngestorThread._process_trade`` — guard de timestamp negativo
   incrementa ``translate_failures`` e RETORNA (não levanta).
2. ``_IngestorThread._run_inner`` — defense-in-depth: qualquer exception
   dentro de ``_process_trade`` é capturada e contada como failure
   (thread continua viva).
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
        chunk_id="chunk-q-drift-34",
        dll_version="4.0.0.34",
        stop_event=stop_event,
        agent_resolver=resolver,
    )


@pytest.mark.unit
def test_process_trade_skips_sentinel_with_negative_timestamp() -> None:
    """Q-DRIFT-34 (guard): timestamp_ns < 0 → translate_failures, sem raise.

    ``translate_trade`` agora filtra struct sentinela retornando ``None``,
    mas mantemos defense-in-depth: se o wrapper deixar passar (ex.: drift
    entre versões), o orchestrator descarta silenciosamente como falha
    de tradução. ``format_brt_timestamp`` NÃO deve ser chamado em ns < 0.
    """
    queue: Queue = Queue()
    dll = MagicMock()
    # Simula wrapper retornando TradeFields com ts negativo (FILETIME 1601).
    dll.translate_trade = MagicMock(
        return_value=TradeFields(
            version=0,
            timestamp_ns=-2_209_161_600_000_000_000,  # 1601-01-01 BRT em ns
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

    # _process_trade NÃO deve levantar — incrementa counter e retorna.
    thread._process_trade(handle=0xCAFEBABE, flags=0)

    assert thread.translate_failures == 1, (
        f"Q-DRIFT-34: timestamp_ns < 0 deve incrementar translate_failures; "
        f"recebido {thread.translate_failures}"
    )
    assert len(thread.trades) == 0, (
        f"Q-DRIFT-34: nenhum TradeRecord deve ser produzido para sentinela; "
        f"recebido {len(thread.trades)}"
    )


@pytest.mark.unit
def test_process_trade_skips_when_translate_returns_none() -> None:
    """Sanity: ``translate_trade -> None`` (NL_* error) já era contado.

    Garante que o novo guard de Q-DRIFT-34 não regrediu o caminho
    legacy de ``rc != 0`` (preservado pelo wrapper).
    """
    queue: Queue = Queue()
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=None)

    thread = _make_thread(dll, queue)
    thread._process_trade(handle=0x1234, flags=0)

    assert thread.translate_failures == 1
    assert len(thread.trades) == 0


@pytest.mark.unit
def test_run_inner_survives_exception_in_process_trade() -> None:
    """Q-DRIFT-34 (defense-in-depth): exception em ``_process_trade``
    NÃO mata a thread.

    Mesmo com guards explícitos, qualquer exception inesperada dentro
    do hot path é capturada em ``_run_inner`` e contada como failure.
    A thread continua viva e drena os próximos handles.
    """
    queue: Queue = Queue()
    dll = MagicMock()
    # 1ª chamada: raise (simula bug futuro qualquer)
    # 2ª chamada: TradeFields válido com ts > 0
    valid_fields = TradeFields(
        version=0,
        timestamp_ns=1_700_000_000_000_000_000,  # 2023-11-14 ish
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
            RuntimeError("boom — qualquer falha inesperada"),
            valid_fields,
        ]
    )

    thread = _make_thread(dll, queue)
    queue.put((0x1, 0))
    queue.put((0x2, 0))
    # Sinaliza stop ANTES de iniciar — assim _run_inner pula direto pro
    # drain final que processa as 2 entradas e termina.
    thread._stop_event.set()
    thread._run_inner()

    assert thread.translate_failures == 1, (
        f"Q-DRIFT-34: exception em _process_trade deve incrementar "
        f"translate_failures; recebido {thread.translate_failures}"
    )
    assert len(thread.trades) == 1, (
        f"Q-DRIFT-34: thread deve ter sobrevivido e processado 2º trade; "
        f"recebido {len(thread.trades)} trades"
    )
    assert thread.trades[0].trade_id == 42
