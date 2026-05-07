"""tests/unit/test_ingestor_thread_invalid_price.py — Q-DRIFT-38 (Story 4.18).

Cobertura específica do bug isolado por Pichau live test 2026-05-06:

Q-DRIFT-38: 1 trade em 519k com ``price=0.0`` (sentinela / leilão / corruption
ABI esporádica) abortava o JOB INTEIRO no orchestrator via
``IntegrityError("price must be > 0")`` em ``validate_record`` (schema v1.1.0).
Mesmo com 99.9999% dos trades válidos, ``run_validate_record`` fail-loudly
matava o write-out e nenhum Parquet era gravado.

Este arquivo testa:

1. ``_IngestorThread._process_trade`` — guard de ``price <= 0`` incrementa
   ``translate_invalid_price_skips`` e RETORNA (não enfileira em
   ``result.trades`` e NÃO incrementa ``translate_failures``).
2. ``_process_trade`` — caminho positivo: ``price > 0`` produz ``TradeRecord``
   normalmente (sanity de não-regressão).
3. ``download_chunk`` log ``download.complete`` — expõe contador
   ``translate_invalid_price_skips`` para diagnóstico/telemetria.
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
        chunk_id="chunk-q-drift-38",
        dll_version="4.0.0.38",
        stop_event=stop_event,
        agent_resolver=resolver,
    )


def _valid_fields(*, price: float, ts_ns: int = 1_700_000_000_000_000_000) -> TradeFields:
    """TradeFields com timestamp válido (>0) e price configurável."""
    return TradeFields(
        version=0,
        timestamp_ns=ts_ns,
        trade_number=42,
        price=price,
        quantity=1,
        volume=price * 1.0,
        buy_agent_id=0,
        sell_agent_id=0,
        trade_type=1,
    )


@pytest.mark.unit
def test_process_trade_skips_zero_price() -> None:
    """Q-DRIFT-38: trade com ``price=0.0`` → counter +=1, NOT em ``result.trades``.

    Sentinela / leilão / corruption ABI: schema v1.1.0 ``validate_record``
    levanta ``IntegrityError("price must be > 0")``. Sem este guard, 1 trade
    ruim em 519k abortava o JOB inteiro. Trade válido nunca tem ``price=0``.
    """
    queue: Queue = Queue()
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=_valid_fields(price=0.0))

    thread = _make_thread(dll, queue)
    thread._process_trade(handle=0xCAFE0000, flags=0)

    assert thread.translate_invalid_price_skips == 1, (
        f"Q-DRIFT-38: price=0 deve incrementar translate_invalid_price_skips; "
        f"recebido {thread.translate_invalid_price_skips}"
    )
    assert len(thread.trades) == 0, (
        f"Q-DRIFT-38: nenhum TradeRecord deve ser produzido para price=0; "
        f"recebido {len(thread.trades)}"
    )
    # NÃO deve poluir ``translate_failures`` (que é {sentinel + nl_errors +
    # exceptions}). ``invalid_price_skips`` é categoria separada.
    assert thread.translate_failures == 0, (
        f"Q-DRIFT-38: price=0 NÃO deve incrementar translate_failures "
        f"(categoria separada); recebido {thread.translate_failures}"
    )


@pytest.mark.unit
def test_process_trade_skips_negative_price() -> None:
    """Q-DRIFT-38: trade com ``price < 0`` (corruption ABI) também é descartado.

    Garante que o guard usa ``<= 0`` (não apenas ``== 0``) — defense-in-depth
    contra qualquer valor não-positivo que ``validate_record`` rejeitaria.
    """
    queue: Queue = Queue()
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=_valid_fields(price=-1.5))

    thread = _make_thread(dll, queue)
    thread._process_trade(handle=0xCAFE0001, flags=0)

    assert thread.translate_invalid_price_skips == 1
    assert len(thread.trades) == 0
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_process_trade_accepts_positive_price() -> None:
    """Sanity / não-regressão: ``price > 0`` produz ``TradeRecord`` normalmente.

    Garante que o novo guard de Q-DRIFT-38 não regrediu o caminho feliz —
    trades válidos WDOFUT (~5500.0) seguem para ``self.trades``.
    """
    queue: Queue = Queue()
    dll = MagicMock()
    dll.translate_trade = MagicMock(return_value=_valid_fields(price=5500.0))

    thread = _make_thread(dll, queue)
    thread._process_trade(handle=0xCAFE0002, flags=0)

    assert thread.translate_invalid_price_skips == 0
    assert len(thread.trades) == 1, (
        f"Q-DRIFT-38: price>0 deve produzir 1 TradeRecord; " f"recebido {len(thread.trades)}"
    )
    assert thread.trades[0].price == pytest.approx(5500.0)
    assert thread.trades[0].symbol == "WDOFUT"
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_invalid_price_counter_in_download_complete_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Q-DRIFT-38: ``download.complete`` log expõe ``translate_invalid_price_skips``.

    Diagnóstico/telemetria — operadores precisam ver quantos trades foram
    descartados por ``price<=0`` para detectar drift (esperado 1-5/dia; > 0.1%
    do volume = investigar ABI corruption ou regra de leilão nova).
    """
    # Caminho mais leve: testar a estrutura do log diretamente via
    # ChunkResult não é necessário — basta inspecionar o keyword passado.
    # Estratégia: monkey-patch o ``log.info`` em ``download_primitive`` e
    # verificar que ``translate_invalid_price_skips`` está nos kwargs.
    from data_downloader.orchestrator import download_primitive as dp

    captured_kwargs: dict[str, object] = {}

    original_info = dp.log.info

    def _capture_info(event: str, **kwargs: object) -> None:
        if event in ("download.complete", "download.timeout", "download.failed"):
            captured_kwargs.update(kwargs)
        original_info(event, **kwargs)

    monkeypatch.setattr(dp.log, "info", _capture_info)

    # Mock minimal de ProfitDLL para download_chunk.
    dll = MagicMock()
    dll.dll_version = "4.0.0.38"
    dll.subscribe_ticker = MagicMock(return_value=0)
    dll.unsubscribe_ticker = MagicMock(return_value=0)
    dll.set_history_trade_callback_v2 = MagicMock()
    dll.set_progress_callback = MagicMock()
    # get_history_trades ret 0; loop principal completa via TC_LAST_PACKET=False
    # mas progress_monitor recebe 100 — controlamos isso via callback registry.
    dll.get_history_trades = MagicMock(return_value=0)
    dll.translate_trade = MagicMock(return_value=None)  # nada a traduzir

    from datetime import datetime

    # Forçar timeout curto via monkeypatch para o teste rodar rápido — o
    # objetivo é apenas validar a estrutura do log final, não o pipeline real.
    monkeypatch.setattr(dp, "DEFAULT_TIMEOUT_SECONDS", 1)

    # Forçar set_progress_callback a empurrar 100 imediatamente para
    # encerrar o loop com status=completed sem precisar timeout.
    def _set_progress(cb: object) -> None:
        # progress_callback factory já roda inteira e o cb é uma WINFUNCTYPE;
        # fazemos ``put`` direto na queue via closure: mais simples é setar
        # o stop_event indireto via patch do loop poll. Aqui aceitamos que o
        # download_chunk vai bater timeout=1s (status="timeout") — o log
        # ainda é emitido com mesmo formato e o kwarg de interesse aparece.
        pass

    dll.set_progress_callback.side_effect = _set_progress

    result = dp.download_chunk(
        dll=dll,  # type: ignore[arg-type]
        symbol="WDOFUT",
        exchange="F",
        dt_start=datetime(2026, 5, 4, 9, 0, 0),
        dt_end=datetime(2026, 5, 4, 18, 0, 0),
        timeout=1,
    )

    assert "translate_invalid_price_skips" in captured_kwargs, (
        f"Q-DRIFT-38: ``download.{result.status}`` log deve incluir kwarg "
        f"``translate_invalid_price_skips``; kwargs vistos: "
        f"{sorted(captured_kwargs.keys())}"
    )
    # 0 hits porque mock retorna None — o que importa é a chave estar presente
    # com tipo numérico para integradores parsearem o log.
    assert captured_kwargs["translate_invalid_price_skips"] == 0
    assert isinstance(captured_kwargs["translate_invalid_price_skips"], int)
