"""Factory mock para tests/bench (Story 4.1).

data_downloader.orchestrator.broker._mock_worker_factory
Owner: Dex (impl) | Audit: Aria (factory pattern).

Top-level factory que cria :class:`Orchestrator` com :class:`_FakeProfitDLL`
+ :class:`ParquetWriter` real + :class:`BrokerCatalogClient` (worker side).
Usado em:

- :file:`tests/integration/test_multi_symbol_mock.py` — integração real do pool.
- :file:`benchmarks/bench_multi_symbol.py` — bench mock-baseline broker.

Pickle-safe: top-level (Windows spawn re-importa este módulo). Não pode
referenciar fixtures pytest nem closures locais.

Configuração via env vars (worker process não tem acesso a kwargs do master):

- ``MOCK_TRADES_PER_CHUNK`` — trades por chunk (default 1000).
- ``MOCK_N_CHUNKS_PER_JOB`` — chunks por job (default 2).
- ``MOCK_DELAY_MS_PER_CHUNK`` — sleep simulado por chunk (default 0).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _dt_to_brt_naive_ns(dt: datetime) -> int:
    """datetime naive (interpretado como BRT) → ns desde 1970-01-01 BRT naive.

    Mesma convenção (lei R7) de ``download_primitive._system_time_to_ns_local``:
    trata o wall clock como UTC apenas para o cálculo aritmético, sem
    conversão de fuso.
    """
    aware = dt.replace(tzinfo=UTC)
    delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
    total_seconds = delta.days * 86_400 + delta.seconds
    return total_seconds * 1_000_000_000 + delta.microseconds * 1_000


def create_orchestrator(
    data_dir: Path,
    broker_client: Any,  # BrokerCatalogClient
) -> Any:
    """Cria :class:`Orchestrator` com mock DLL para multi-symbol bench/tests.

    Args:
        data_dir: Raiz dos dados (workers escrevem Parquet local).
        broker_client: :class:`BrokerCatalogClient` já criado pelo
            worker_main.

    Returns:
        :class:`Orchestrator` pronto para ``.run(JobConfig)``.

    Notes:
        Worker carrega ParquetWriter real (Parquet write é local — sem
        broker contention). Catalog é o broker_client (todas mutações
        vão para master).
    """
    from data_downloader.orchestrator.orchestrator import Orchestrator
    from data_downloader.storage.parquet_writer import ParquetWriter

    trades_per_chunk = int(os.environ.get("MOCK_TRADES_PER_CHUNK", "1000"))
    n_chunks = int(os.environ.get("MOCK_N_CHUNKS_PER_JOB", "2"))
    delay_ms = int(os.environ.get("MOCK_DELAY_MS_PER_CHUNK", "0"))

    fake_dll = _FakeProfitDLL(
        trades_per_chunk=trades_per_chunk,
        n_chunks=n_chunks,
        delay_ms=delay_ms,
    )
    writer = ParquetWriter(data_dir=data_dir)
    # broker_client implementa subset de Catalog que Orchestrator usa.
    orch = Orchestrator(fake_dll, broker_client, writer)  # type: ignore[arg-type]
    return orch


class _FakeProfitDLL:
    """Mock DLL minimalista — gera N chunks x M trades sintéticos.

    Replica o padrão de :file:`tests/integration/test_orchestrator.py`
    (_FakeProfitDLL) mas sem dep de pytest fixtures.
    """

    def __init__(
        self,
        *,
        trades_per_chunk: int = 1000,
        n_chunks: int = 2,
        delay_ms: int = 0,
        dll_version: str = "4.0.0.30-mock",
    ) -> None:
        self._trades_per_chunk = trades_per_chunk
        self._n_chunks = n_chunks
        self._delay_s = delay_ms / 1000.0
        self.dll_version = dll_version

        self._history_cb: Any = None
        self._progress_cb: Any = None
        self._call_idx = 0
        self._current_specs: list[dict[str, Any]] = []

    def set_history_trade_callback_v2(self, cb: Any) -> None:
        self._history_cb = cb

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_cb = cb

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start_str: str,
        dt_end_str: str,
    ) -> int:
        self._call_idx += 1
        # Gera trades sintéticos para este "chunk".
        base = datetime(2026, 3, 2, 9, 0, 0)
        specs: list[dict[str, Any]] = []
        for i in range(self._trades_per_chunk):
            sec = i // 1000
            us = (i % 1000) * 1000
            ts = base.replace(
                hour=min(base.hour + sec // 3600, 17),
                minute=min((base.minute + (sec // 60) % 60), 59),
                second=sec % 60,
                microsecond=us,
            )
            specs.append(
                {
                    "timestamp": ts,
                    "price": 5000.0 + (i % 100) * 0.5,
                    "quantity": (i % 5) + 1,
                    "trade_number": i + 1,
                }
            )
        self._current_specs = specs

        # Emite em thread separada (callback semantics — não bloqueia).
        t = threading.Thread(target=self._emit, args=(ticker,), daemon=True)
        t.start()
        return 0

    def translate_trade(self, handle: int) -> Any:
        """API V2 (Story 1.7b-followup): retorna ``TradeFields | None``.

        Antes (drift): assinatura ``(handle, struct) -> int`` mutando o
        struct in-place. Produção migrou para ``(handle) -> TradeFields | None``;
        este mock acompanha (v1.1.0 task #10 — Quinn QA 2026-05-11).
        """
        from data_downloader.dll.types import TradeFields

        if handle >= len(self._current_specs):
            return None
        spec = self._current_specs[handle]
        ts = spec["timestamp"]
        return TradeFields(
            version=0,
            timestamp_ns=_dt_to_brt_naive_ns(ts),
            trade_number=spec.get("trade_number", handle + 1),
            price=spec["price"],
            quantity=spec["quantity"],
            volume=spec["price"] * spec["quantity"],
            buy_agent_id=0,
            sell_agent_id=0,
            trade_type=1,
        )

    def _emit(self, ticker: str) -> None:
        from data_downloader.dll.types import (
            TC_LAST_PACKET,
            TAssetID,
            TConnectorAssetIdentifier,
        )

        if self._delay_s > 0:
            time.sleep(self._delay_s)

        if self._history_cb is None:
            return

        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        n = len(self._current_specs)
        for i in range(n):
            flags = TC_LAST_PACKET if i == n - 1 else 0
            try:
                self._history_cb(asset, i, flags)
            except Exception:
                break

        # Progress sweeping (50 → 100). TProgressCallback V2 (Q-DRIFT-05):
        # assinatura ``(TAssetID, c_int)`` — 2 args. Antes (drift) este mock
        # chamava com 4 args (ticker, exchange, 0, p) → TypeError silencioso
        # → progresso nunca chegava ao monitor. Note: progress usa TAssetID
        # (struct V1), distinto do TConnectorAssetIdentifier do history cb.
        import contextlib as _contextlib

        progress_asset = TAssetID(ticker=ticker, bolsa="F", feed=0)
        for p in (50, 100):
            if self._progress_cb is None:
                break
            with _contextlib.suppress(Exception):
                self._progress_cb(progress_asset, p)


__all__ = [
    "create_orchestrator",
]
