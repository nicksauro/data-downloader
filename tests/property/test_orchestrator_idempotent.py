"""Property tests — orchestrator idempotency E2E (Story 1.7a AC10).

Cobertura:

- Hypothesis: rodar orchestrator 2x com mesmo (symbol, range) ≡ rodar 1x
  (R5 — INV-2 + writer dedup + catalog UPSERT). Verifica:

  1. Mesma quantidade final de partições.
  2. Mesmas (year, month) de partições.
  3. Mesmo total de trades nas partições (idempotência forte).
  4. 2º run = cache_hit (zero chamadas DLL).

Aplica :class:`hypothesis.HealthCheck.function_scoped_fixture` para silenciar
warning sobre fixtures com tempo de vida menor que ``@given``.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import (
    TC_LAST_PACKET,
    TAssetID,
    TConnectorAssetIdentifier,
    TradeFields,
)
from data_downloader.orchestrator.orchestrator import (
    JobConfig,
    Orchestrator,
)
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Any:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


# =====================================================================
# Mock DLL — versão idempotente (mesma config = mesmos trades em qq run)
# =====================================================================


class _ReplayDLL:
    """Mock DLL determinístico: mesmas N chamadas → mesmos N trades.

    Cada chamada a ``get_history_trades`` consome 1 round das ``rounds``
    pré-configuradas (sem reset entre runs do orchestrator). Para garantir
    idempotência E2E, o orchestrator deve evitar segundo download
    (cache hit) — testaremos isso.
    """

    def __init__(self, rounds: list[list[dict[str, Any]]]) -> None:
        self.rounds = rounds
        self._round_idx = 0
        self._current: list[dict[str, Any]] = []
        self._history_cb: Any = None
        self._progress_cb: Any = None
        self.dll_version = "4.0.0.34"
        self.get_history_calls = 0

    def set_history_trade_callback_v2(self, cb: Any) -> None:
        self._history_cb = cb

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_cb = cb

    def get_history_trades(self, ticker: str, *_args: Any, **_kw: Any) -> int:
        self.get_history_calls += 1
        if self._round_idx >= len(self.rounds):
            # Out-of-rounds → chunk vazio mas COMPLETO — evita deadlock quando
            # chunker ADR-023 (1d) gera mais chunks que rounds (v1.1.0 task #10).
            self._current = []
            threading.Thread(target=self._emit_loop, args=(ticker, []), daemon=True).start()
            return 0
        self._current = self.rounds[self._round_idx]
        self._round_idx += 1
        thread = threading.Thread(
            target=self._emit_loop,
            args=(ticker, list(self._current)),
            daemon=True,
        )
        thread.start()
        return 0

    def translate_trade(self, handle: int) -> TradeFields | None:
        """API V2 (Story 1.7b-followup) — ``(handle) -> TradeFields | None``."""
        from datetime import UTC

        if handle >= len(self._current):
            return None
        spec = self._current[handle]
        ts: datetime = spec["timestamp"]
        aware = ts.replace(tzinfo=UTC)
        delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
        ns = (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000
        return TradeFields(
            version=0,
            timestamp_ns=ns,
            trade_number=spec["trade_number"],
            price=spec["price"],
            quantity=spec["quantity"],
            volume=spec["price"] * spec["quantity"],
            buy_agent_id=0,
            sell_agent_id=0,
            trade_type=1,
        )

    def _emit_loop(self, ticker: str, specs: list[dict[str, Any]]) -> None:
        time.sleep(0.005)
        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        n = len(specs)
        for i, _spec in enumerate(specs):
            if self._history_cb is None:
                break
            flags = TC_LAST_PACKET if i == n - 1 else 0
            self._history_cb(asset, i, flags)
            time.sleep(0.001)
        # TProgressCallback V2 (Q-DRIFT-05): 2 args (TAssetID, c_int).
        if self._progress_cb is not None:
            self._progress_cb(TAssetID(ticker=ticker, bolsa="F", feed=0), 100)


# =====================================================================
# Strategies
# =====================================================================


@st.composite
def _trades_per_chunk(draw: st.DrawFn) -> int:
    """Número de trades no chunk: small = mais explorações."""
    return draw(st.integers(min_value=1, max_value=8))


# =====================================================================
# Property: dois runs com mesma config produzem mesmo estado de catálogo
# =====================================================================


@pytest.mark.property
@settings(
    max_examples=15,  # E2E é caro — manter modesto
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n_trades=_trades_per_chunk())
def test_orchestrator_run_is_idempotent(n_trades: int, tmp_path: Path) -> None:
    """Rodar 2x mesmo (symbol, range) ≡ 1x (R5)."""
    # Hypothesis reusa tmp_path entre exemplos; gera sub-dir único por exemplo.
    data_dir = tmp_path / f"data_{uuid.uuid4().hex}"
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    writer = ParquetWriter(data_dir=data_dir)

    base = datetime(2026, 3, 2, 9, 0, 0)
    # 1 chunk de N trades.
    specs = [
        {
            "timestamp": base.replace(microsecond=i * 1000),
            "price": 100.0 + i,
            "quantity": 1,
            "trade_number": i + 1,
        }
        for i in range(n_trades)
    ]

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )

    # 1º run.
    dll1 = _ReplayDLL(rounds=[specs])
    orch1 = Orchestrator(dll1, catalog, writer)  # type: ignore[arg-type]
    result1 = orch1.run(config)
    assert result1.status == "completed"

    parts_after_first = catalog.get_completed_partitions("WDOJ26", "F")
    rows_after_first = sum(p.row_count for p in parts_after_first)
    keys_after_first = {(p.year, p.month) for p in parts_after_first}

    # 2º run com mesma config.
    dll2 = _ReplayDLL(rounds=[specs])
    orch2 = Orchestrator(dll2, catalog, writer)  # type: ignore[arg-type]
    result2 = orch2.run(config)

    parts_after_second = catalog.get_completed_partitions("WDOJ26", "F")
    rows_after_second = sum(p.row_count for p in parts_after_second)
    keys_after_second = {(p.year, p.month) for p in parts_after_second}

    # Estado idêntico após o 2º run.
    assert keys_after_first == keys_after_second
    assert rows_after_first == rows_after_second

    # 2º run foi cache_hit (zero chamadas DLL).
    assert result2.status == "cache_hit"
    assert dll2.get_history_calls == 0

    catalog.close()


@pytest.mark.property
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(n_trades=_trades_per_chunk())
def test_orchestrator_re_register_partition_keeps_row_count_stable(
    n_trades: int,
    tmp_path: Path,
) -> None:
    """Re-rodar não infla nem deduplica row_count abaixo do esperado.

    Verifica que o fluxo `download → write → register_partition` não
    apresenta drift no segundo run (UPSERT idempotente do Story 1.5).
    """
    data_dir = tmp_path / f"data_{uuid.uuid4().hex}"
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    writer = ParquetWriter(data_dir=data_dir)

    base = datetime(2026, 3, 2, 9, 0, 0)
    specs = [
        {
            "timestamp": base.replace(microsecond=i * 1000),
            "price": 100.0 + i,
            "quantity": 1,
            "trade_number": i + 1,
        }
        for i in range(n_trades)
    ]
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )

    dll = _ReplayDLL(rounds=[specs])
    Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]
    rows1 = catalog.get_completed_partitions("WDOJ26", "F")[0].row_count

    # 2º run: cache_hit → zero rewrite.
    dll2 = _ReplayDLL(rounds=[specs])
    Orchestrator(dll2, catalog, writer).run(config)  # type: ignore[arg-type]
    rows2 = catalog.get_completed_partitions("WDOJ26", "F")[0].row_count

    assert rows1 == rows2 == n_trades
    catalog.close()
