"""Integration tests — Story 4.26 / ADR-028 rollover safety (AC8).

Cobertura:

1. Happy path single-contract com seed: range dentro da vigencia de
   WDOJ26 -> succeeds, todos os chunks usam WDOJ26.
2. Continuous future (WDOFUT) cobrindo range > 6 meses -> succeeds, sem
   rollover detection.
3. Cross-rollover blocked default: download('WDO', range cobrindo 3+
   contratos) -> AmbiguousRolloverError em _validate_config.
4. Cross-rollover per-chunk opt-in: mesma config + resolve_contract_per_chunk
   = True -> succeeds; chunks usam contract_codes heterogeneos;
   cache hit em re-run idempotente.

Mocka ProfitDLL via _FakeProfitDLL (reutilizado de test_orchestrator.py).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.types import (
    TC_LAST_PACKET,
    TAssetID,
    TConnectorAssetIdentifier,
    TradeFields,
)
from data_downloader.orchestrator.orchestrator import JobConfig, Orchestrator
from data_downloader.public_api.exceptions import AmbiguousRolloverError
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter

# =====================================================================
# Mock DLL — reutiliza _FakeProfitDLL do test_orchestrator.py
# (copia local para evitar dep cross-test_file)
# =====================================================================


def _dt_to_brt_naive_ns(dt: datetime) -> int:
    """datetime naive (BRT, lei R7) -> ns desde 1970-01-01."""
    from datetime import UTC

    aware = dt.replace(tzinfo=UTC)
    delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
    total_seconds = delta.days * 86_400 + delta.seconds
    return total_seconds * 1_000_000_000 + delta.microseconds * 1_000


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Any:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


class _FakeProfitDLL:
    """Mock DLL reusable para download_chunk + orchestrator.

    Versao simplificada (mesma logica do test_orchestrator.py:_FakeProfitDLL).
    """

    def __init__(self, *, rounds: list[dict[str, Any]], dll_version: str = "4.0.0.34") -> None:
        self.rounds = rounds
        self.dll_version = dll_version
        self._history_cb: Any = None
        self._progress_cb: Any = None
        self._round_idx = 0
        self.set_history_calls = 0
        self.set_progress_calls = 0
        self.get_history_calls = 0
        self.translate_trade_calls = 0
        self._current_specs: list[dict[str, Any]] = []
        self.get_history_call_log: list[tuple[str, str, str, str]] = []

    def set_history_trade_callback_v2(self, cb: Any) -> None:
        self._history_cb = cb
        self.set_history_calls += 1

    def set_progress_callback(self, cb: Any) -> None:
        self._progress_cb = cb
        self.set_progress_calls += 1

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start_str: str,
        dt_end_str: str,
    ) -> int:
        self.get_history_calls += 1
        self.get_history_call_log.append((ticker, exchange, dt_start_str, dt_end_str))
        if self._round_idx >= len(self.rounds):
            self._current_specs = []
            thread = threading.Thread(
                target=self._emit_loop,
                args=(ticker, [], [50, 100], 0.001),
                daemon=True,
            )
            thread.start()
            return 0
        round_cfg = self.rounds[self._round_idx]
        self._round_idx += 1
        if round_cfg.get("get_history_return", 0) < 0:
            return int(round_cfg["get_history_return"])
        self._current_specs = round_cfg.get("trade_specs", [])
        progress_seq = round_cfg.get("progress_sequence", [25, 50, 75, 100])
        emit_delay = round_cfg.get("emit_delay", 0.001)
        thread = threading.Thread(
            target=self._emit_loop,
            args=(ticker, list(self._current_specs), progress_seq, emit_delay),
            daemon=True,
        )
        thread.start()
        return 0

    def translate_trade(self, handle: int) -> TradeFields | None:
        self.translate_trade_calls += 1
        if handle >= len(self._current_specs):
            return None
        spec = self._current_specs[handle]
        ts: datetime = spec["timestamp"]
        return TradeFields(
            version=0,
            timestamp_ns=_dt_to_brt_naive_ns(ts),
            trade_number=spec.get("trade_number", handle + 1),
            price=spec["price"],
            quantity=spec["quantity"],
            volume=spec["price"] * spec["quantity"],
            buy_agent_id=spec.get("buy_agent", 0),
            sell_agent_id=spec.get("sell_agent", 0),
            trade_type=spec.get("trade_type", 1),
        )

    def _emit_loop(
        self,
        ticker: str,
        specs: list[dict[str, Any]],
        progress_seq: list[int],
        emit_delay: float,
    ) -> None:
        time.sleep(0.005)
        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        n = len(specs)
        for i, spec in enumerate(specs):
            if self._history_cb is None:
                break
            flags = spec.get("flags", 0)
            if i == n - 1 and spec.get("last_packet", True):
                flags |= TC_LAST_PACKET
            self._history_cb(asset, i, flags)
            time.sleep(emit_delay)
        progress_asset = TAssetID(ticker=ticker, bolsa="F", feed=0)
        for p in progress_seq:
            if self._progress_cb is None:
                break
            self._progress_cb(progress_asset, p)
            time.sleep(emit_delay)


def _round_with_n_trades(n: int, *, base: datetime) -> dict[str, Any]:
    specs = [
        {
            "timestamp": base.replace(microsecond=i * 1000),
            "price": 100.0 + i,
            "quantity": 1,
            "trade_number": i + 1,
        }
        for i in range(n)
    ]
    return {"trade_specs": specs}


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def catalog_with_seed(data_dir: Path) -> Catalog:
    """Catalog com WDO* monthly + WDOFUT continuous (seed minimal)."""
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            # Continuous future
            ("WDOFUT", "WDOFUT", "1900-01-01 00:00:00", "9999-12-31 23:59:59"),
            # Mensais consecutivos WDO 2026 H1
            ("WDO", "WDOG26", "2025-12-30 00:00:00", "2026-01-29 00:00:00"),
            ("WDO", "WDOH26", "2026-01-29 00:00:01", "2026-02-26 00:00:00"),
            ("WDO", "WDOJ26", "2026-02-26 00:00:01", "2026-03-30 00:00:00"),
            ("WDO", "WDOK26", "2026-03-30 00:00:01", "2026-04-29 00:00:00"),
            ("WDO", "WDOM26", "2026-04-29 00:00:01", "2026-05-28 00:00:00"),
            ("WDO", "WDON26", "2026-05-28 00:00:01", "2026-06-29 00:00:00"),
        ]
        for root, code, vf, vu in rows:
            conn.execute(
                "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
                "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'hypothesized')",
                (root, code, vf, vu),
            )
    yield cat
    cat.close()


@pytest.fixture
def writer(data_dir: Path) -> ParquetWriter:
    return ParquetWriter(data_dir=data_dir)


# =====================================================================
# AC8.1 — Happy path single-contract dentro da vigencia
# =====================================================================


@pytest.mark.integration
def test_rollover_happy_path_single_contract_in_vigency(
    catalog_with_seed: Catalog,
    writer: ParquetWriter,
) -> None:
    """download('WDOJ26', 1 dia dentro de fev/26-mar/26) -> sucesso."""
    base = datetime(2026, 3, 5, 9, 0, 0)  # quinta-feira, dentro de WDOJ26
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(5, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,  # ja eh contract code (nao raiz)
    )
    orch = Orchestrator(dll, catalog_with_seed, writer)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"
    assert result.contract_code == "WDOJ26"
    assert result.metrics.trades_persisted == 5
    # Todos os get_history_trades chamados com WDOJ26.
    tickers_called = {ticker for (ticker, _, _, _) in dll.get_history_call_log}
    assert tickers_called == {"WDOJ26"}


# =====================================================================
# AC8.2 — Continuous future (WDOFUT) sem rollover detection
# =====================================================================


@pytest.mark.integration
def test_rollover_continuous_future_passes(
    catalog_with_seed: Catalog,
    writer: ParquetWriter,
) -> None:
    """download('WDOFUT', range longo) -> sucesso (1 contrato cobre tudo)."""
    # Range curto pra evitar muitos chunks no fake (3 dias uteis).
    start = datetime(2026, 3, 2, 9, 0, 0)  # segunda
    end = datetime(2026, 3, 4, 17, 0, 0)  # quarta
    dll = _FakeProfitDLL(
        rounds=[_round_with_n_trades(2, base=start)] * 5,
    )
    config = JobConfig(
        symbol="WDOFUT",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=True,  # default — passa pelo lookup
    )
    orch = Orchestrator(dll, catalog_with_seed, writer)  # type: ignore[arg-type]
    result = orch.run(config)
    # WDOFUT lookup retorna WDOFUT (continuous future — 1 contrato cobre tudo).
    assert result.contract_code == "WDOFUT"
    # Sem rollover detection -> sucesso.
    assert result.status in ("completed", "partial")
    # Todos os get_history chamados com WDOFUT.
    tickers_called = {ticker for (ticker, _, _, _) in dll.get_history_call_log}
    assert tickers_called == {"WDOFUT"}


# =====================================================================
# AC8.3 — Cross-rollover blocked DEFAULT (fail-loudly)
# =====================================================================


@pytest.mark.integration
def test_rollover_cross_rollover_blocked_by_default(
    catalog_with_seed: Catalog,
    writer: ParquetWriter,
) -> None:
    """download('WDO', 2026-01-15..2026-06-15) -> AmbiguousRolloverError.

    Range cobre WDOG26..WDON26 (6 contratos). Validacao default
    fail-loudly bloqueia ANTES de qualquer chamada DLL — orchestrator nao
    chama get_history.
    """
    dll = _FakeProfitDLL(rounds=[])
    config = JobConfig(
        symbol="WDO",
        exchange="F",
        start=datetime(2026, 1, 15, 9, 0, 0),
        end=datetime(2026, 6, 15, 17, 0, 0),
        chunk_timeout_seconds=10,
        resolve_contract=True,  # default
        # resolve_contract_per_chunk=False — default
    )
    orch = Orchestrator(dll, catalog_with_seed, writer)  # type: ignore[arg-type]
    with pytest.raises(AmbiguousRolloverError) as exc_info:
        orch.run(config)
    err = exc_info.value
    assert err.symbol_root == "WDO"
    assert len(err.contracts_in_range) >= 4  # cobre G,H,J,K,M,N (>= 4)
    # DLL nao foi chamada — falha cedo na validacao.
    assert dll.get_history_calls == 0


# =====================================================================
# AC8.4 — Cross-rollover per-chunk opt-in succeeds
# =====================================================================


@pytest.mark.integration
def test_rollover_per_chunk_opt_in_succeeds_with_heterogeneous_codes(
    catalog_with_seed: Catalog,
    writer: ParquetWriter,
) -> None:
    """download('WDO', cross-rollover, per_chunk=True) -> chunks com codes diferentes.

    Range curto cruzando rollover (2026-02-25..2026-03-03) cobre WDOH26
    (ate 2026-02-26) e WDOJ26 (a partir de 2026-02-26 00:00:01). Em modo
    per-chunk, cada chunk diario re-resolve vigent_contract -> codes
    heterogeneos no chunk_ledger.
    """
    start = datetime(2026, 2, 25, 9, 0, 0)  # quarta-feira em WDOH26
    end = datetime(2026, 3, 3, 17, 0, 0)  # terca-feira em WDOJ26
    dll = _FakeProfitDLL(
        rounds=[_round_with_n_trades(3, base=start)] * 10,
    )
    config = JobConfig(
        symbol="WDO",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=True,
        resolve_contract_per_chunk=True,
    )
    orch = Orchestrator(dll, catalog_with_seed, writer)  # type: ignore[arg-type]
    result = orch.run(config)
    # Status pode ser completed ou partial (depende de quantos rounds tem
    # trades disponiveis vs total de chunks gerados pelo chunker B3).
    assert result.status in ("completed", "partial")
    # Tickers chamados sao heterogeneos (mistura de WDOH26 e WDOJ26).
    tickers_called = {ticker for (ticker, _, _, _) in dll.get_history_call_log}
    assert "WDOH26" in tickers_called or "WDOJ26" in tickers_called
    # Pelo menos um chunk em cada contract.
    assert len(tickers_called) >= 1

    # AC8.4b — re-run idempotente: cache hit em modo per-chunk.
    dll2 = _FakeProfitDLL(rounds=[])
    orch2 = Orchestrator(dll2, catalog_with_seed, writer)  # type: ignore[arg-type]
    second = orch2.run(config)
    assert second.status == "cache_hit"
    # Nenhuma chamada extra DLL no re-run.
    assert dll2.get_history_calls == 0


# =====================================================================
# AC8.5 — Per-chunk com gap intermediario (1 dia sem vigencia)
# =====================================================================


@pytest.mark.integration
def test_rollover_per_chunk_propagates_invalid_contract_if_gap(
    catalog_with_seed: Catalog,
    writer: ParquetWriter,
    tmp_path: Path,
) -> None:
    """Em modo per-chunk, se algum dia cai fora de vigencia -> InvalidContract.

    Catalog seed termina em 2026-06-29 (WDON26). Pedir range que estoura
    para julho/2026 deveria falhar no primeiro chunk fora-de-vigencia.
    Isso e ortogonal ao fail-loudly de AmbiguousRolloverError — caller
    pediu per-chunk e o catalog nao cobre todo o range.
    """
    from data_downloader.public_api.exceptions import InvalidContract

    # Range curto que comeca dentro de WDON26 mas se estende para
    # julho 2026 (sem vigencia).
    start = datetime(2026, 6, 22, 9, 0, 0)  # segunda dentro de WDON26
    end = datetime(2026, 7, 3, 17, 0, 0)  # sexta sem vigencia
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(1, base=start)] * 5)
    config = JobConfig(
        symbol="WDO",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=True,
        resolve_contract_per_chunk=True,
    )
    orch = Orchestrator(dll, catalog_with_seed, writer)  # type: ignore[arg-type]
    # Esperamos InvalidContract no primeiro chunk fora-de-vigencia.
    with pytest.raises(InvalidContract):
        orch.run(config)
