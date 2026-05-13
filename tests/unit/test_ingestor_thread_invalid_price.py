"""tests/unit/test_ingestor_thread_invalid_price.py — Q-DRIFT-38 (Story 4.18) +
Q-DRIFT-40 (v1.2.0 — translate-in-callback).

Q-DRIFT-38: 1 trade em 519k com ``price=0.0`` (sentinela / leilão / corruption
ABI esporádica) abortava o JOB INTEIRO no orchestrator via
``IntegrityError("price must be > 0")`` em ``validate_record`` (schema v1.1.0).

v1.2.0 (COUNCIL-38 / Q-DRIFT-40): a tradução é feita DENTRO do callback V2,
que checa ``price <= 0`` ANTES de enfileirar e conta em
``stats["translate_invalid_price_skips"]``. O ``_IngestorThread`` mantém o
guard como defense-in-depth (caso algo escape). ``download.complete`` continua
expondo ``translate_invalid_price_skips`` (agregado callback + ingestor).

Cobertura:

1. ``make_history_trade_callback_v2`` — ``price <= 0`` → counter +=1, nada
   na fila (cobertura primária — ``tests/unit/test_dll_callbacks.py``).
2. ``_IngestorThread._process_trade`` — guard residual de ``price <= 0``
   incrementa ``translate_invalid_price_skips`` e RETORNA (não enfileira,
   não soma em ``translate_failures``).
3. ``_process_trade`` — caminho positivo: ``price > 0`` produz ``TradeRecord``.
4. ``download_chunk`` log ``download.complete`` — expõe contador
   ``translate_invalid_price_skips``.
"""

from __future__ import annotations

import threading
from queue import Queue
from unittest.mock import MagicMock

import pytest

from data_downloader.dll.types import TradeFields
from data_downloader.orchestrator.download_primitive import _IngestorThread


def _make_thread(queue: Queue) -> _IngestorThread:
    stop_event = threading.Event()
    resolver = MagicMock()
    resolver.resolve = MagicMock(return_value=None)
    return _IngestorThread(
        dll=MagicMock(),  # type: ignore[arg-type]
        trade_queue=queue,
        symbol="WDOFUT",
        exchange="F",
        chunk_id="chunk-q-drift-38",
        dll_version="4.0.0.38",
        stop_event=stop_event,
        agent_resolver=resolver,
    )


def _tf(*, price: float, ts_ns: int = 1_700_000_000_000_000_000) -> TradeFields:
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
def test_process_trade_residual_guard_skips_zero_price() -> None:
    """Q-DRIFT-38 (guard residual): TradeFields com ``price=0.0`` → counter +=1, skip.

    Categoria separada de ``translate_failures`` (preserva semântica histórica
    do agregado). Trade válido WDOFUT/ações nunca tem ``price=0``.
    """
    queue: Queue = Queue()
    thread = _make_thread(queue)
    thread._process_trade(_tf(price=0.0), flags=0)

    assert thread.translate_invalid_price_skips == 1
    assert len(thread.trades) == 0
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_process_trade_residual_guard_skips_negative_price() -> None:
    """Q-DRIFT-38: guard usa ``<= 0`` (não apenas ``== 0``)."""
    queue: Queue = Queue()
    thread = _make_thread(queue)
    thread._process_trade(_tf(price=-1.5), flags=0)

    assert thread.translate_invalid_price_skips == 1
    assert len(thread.trades) == 0
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_process_trade_accepts_positive_price() -> None:
    """Sanity / não-regressão: ``price > 0`` produz ``TradeRecord``."""
    queue: Queue = Queue()
    thread = _make_thread(queue)
    thread._process_trade(_tf(price=5500.0), flags=0)

    assert thread.translate_invalid_price_skips == 0
    assert len(thread.trades) == 1
    assert thread.trades[0].price == pytest.approx(5500.0)
    assert thread.trades[0].symbol == "WDOFUT"
    assert thread.translate_failures == 0


@pytest.mark.unit
def test_invalid_price_counter_in_download_complete_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q-DRIFT-38: ``download.complete`` log expõe ``translate_invalid_price_skips``.

    Diagnóstico/telemetria — operadores precisam ver quantos trades foram
    descartados por ``price<=0`` para detectar drift.
    """
    from datetime import datetime

    from data_downloader.orchestrator import download_primitive as dp

    captured_kwargs: dict[str, object] = {}
    original_info = dp.log.info

    def _capture_info(event: str, **kwargs: object) -> None:
        if event in ("download.complete", "download.timeout", "download.failed"):
            captured_kwargs.update(kwargs)
        original_info(event, **kwargs)

    monkeypatch.setattr(dp.log, "info", _capture_info)

    dll = MagicMock()
    dll.dll_version = "4.0.0.38"
    dll.subscribe_ticker = MagicMock(return_value=0)
    dll.unsubscribe_ticker = MagicMock(return_value=0)
    dll.set_history_trade_callback_v2 = MagicMock()
    dll.set_progress_callback = MagicMock()
    dll.get_history_trades = MagicMock(return_value=0)
    dll.translate_trade = MagicMock(return_value=None)  # nada a traduzir

    monkeypatch.setattr(dp, "DEFAULT_TIMEOUT_SECONDS", 1)

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
    assert captured_kwargs["translate_invalid_price_skips"] == 0
    assert isinstance(captured_kwargs["translate_invalid_price_skips"], int)
    # v1.2.0 — completeness_pct também é exposto.
    assert "completeness_pct" in captured_kwargs
