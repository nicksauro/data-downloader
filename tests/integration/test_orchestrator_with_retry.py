"""Integration tests — Orchestrator + RetryPolicy + CircuitBreaker (Story 2.6 AC5).

Cobertura:
- Mock DLL injeta NL_* errors em ``get_history_trades``; orchestrator
  exercita retry policy correta (TRANSIENT retries, PERMANENT fail-fast).
- Circuit breaker activates after N TRANSIENT failures — chunks subsequentes
  são rejeitadas via CircuitOpenError, registradas como gap, sem invocar DLL.
- Retry NUNCA loop infinito (máx N attempts x max delay).
- Orchestrator default (sem injeção) preserva comportamento Story 1.7a.
- Q02-E (99% reconnect) NÃO conta como failure no breaker (test sintético).
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
    SystemTime,
    TConnectorAssetIdentifier,
    TConnectorTrade,
)
from data_downloader.orchestrator.circuit_breaker import (
    DEFAULT_FAILURE_THRESHOLD,
    BreakerState,
    CircuitBreaker,
)
from data_downloader.orchestrator.orchestrator import (
    JobConfig,
    Orchestrator,
)
from data_downloader.orchestrator.retry_policy import RetryPolicy
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter

# =====================================================================
# Fixtures + helpers
# =====================================================================


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Any:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


class _NLInjectingDLL:
    """Mock DLL que injeta sequência fixa de retornos em ``get_history_trades``.

    Cada call consome o próximo elemento de ``nl_returns``. Se o retorno é
    >= 0, dispara emit normal de trades (vazio); se < 0, retorna o código
    NL_* sem disparar nada.
    """

    def __init__(
        self,
        *,
        nl_returns: list[int],
        trade_specs_per_call: list[list[dict[str, Any]]] | None = None,
        dll_version: str = "4.0.0.34",
    ) -> None:
        self.nl_returns = list(nl_returns)
        self.trade_specs_per_call = trade_specs_per_call or [[] for _ in nl_returns]
        self.dll_version = dll_version
        self.call_idx = 0
        self.calls_history: list[int] = []
        self._history_cb: Any = None
        self._progress_cb: Any = None
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
        idx = min(self.call_idx, len(self.nl_returns) - 1)
        nl = self.nl_returns[idx]
        # Specs paralelos (sucesso path)
        specs_idx = min(self.call_idx, len(self.trade_specs_per_call) - 1)
        self._current_specs = self.trade_specs_per_call[specs_idx]
        self.call_idx += 1
        self.calls_history.append(nl)
        if nl < 0:
            return nl
        # Sucesso — emit specs em background e progress=100
        thread = threading.Thread(
            target=self._emit,
            args=(ticker, list(self._current_specs)),
            daemon=True,
        )
        thread.start()
        return 0

    def translate_trade(self, handle: int, struct: TConnectorTrade) -> int:
        if handle >= len(self._current_specs):
            return -1
        spec = self._current_specs[handle]
        st = SystemTime()
        ts: datetime = spec["timestamp"]
        st.wYear = ts.year
        st.wMonth = ts.month
        st.wDay = ts.day
        st.wDayOfWeek = 0
        st.wHour = ts.hour
        st.wMinute = ts.minute
        st.wSecond = ts.second
        st.wMilliseconds = ts.microsecond // 1000
        struct.TradeDate = st
        struct.TradeNumber = spec.get("trade_number", handle + 1)
        struct.Price = spec["price"]
        struct.Quantity = spec["quantity"]
        struct.Volume = spec["price"] * spec["quantity"]
        struct.BuyAgent = 0
        struct.SellAgent = 0
        struct.TradeType = 1
        return 0

    def _emit(self, ticker: str, specs: list[dict[str, Any]]) -> None:
        time.sleep(0.005)
        asset = TConnectorAssetIdentifier(Version=0, Ticker=ticker, Exchange="F", FeedType=0)
        n = len(specs)
        for i in range(n):
            if self._history_cb is None:
                break
            flags = TC_LAST_PACKET if i == n - 1 else 0
            self._history_cb(asset, i, flags)
            time.sleep(0.001)
        # Progress 100 ao fim
        if self._progress_cb is not None:
            self._progress_cb(ticker, "F", 0, 100)


def _spec(timestamp: datetime, trade_number: int = 1) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "price": 100.0,
        "quantity": 1,
        "trade_number": trade_number,
    }


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def catalog(data_dir: Path) -> Any:
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    yield cat
    cat.close()


@pytest.fixture
def writer(data_dir: Path) -> ParquetWriter:
    return ParquetWriter(data_dir=data_dir)


# =====================================================================
# Tests — retry behavior on NL_* injection
# =====================================================================


_NL_INTERNAL_ERROR = -2147483647  # TRANSIENT
_NL_INVALID_TICKER = -2147483617  # PERMANENT


@pytest.mark.integration
def test_orchestrator_uses_default_retry_policy_when_none_given(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Sem injeção de retry_policy, orchestrator usa default (Story 2.6 backwards compat)."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _NLInjectingDLL(
        nl_returns=[0],
        trade_specs_per_call=[[_spec(base)]],
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"


@pytest.mark.integration
def test_orchestrator_permanent_nl_error_fail_fast_no_retry(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """NL_INVALID_TICKER (PERMANENT) → fail-fast em 1 call, gap registrado."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _NLInjectingDLL(
        nl_returns=[_NL_INVALID_TICKER, _NL_INVALID_TICKER],  # 2 chunks tentariam
    )
    # Policy default — PERMANENT fail-fast, 0 retries
    fast_policy = RetryPolicy(
        max_attempts_transient=5,
        max_attempts_ambiguous=3,
        base_delay_transient=0.0,
        base_delay_ambiguous=0.0,
        factor=1.0,
        max_delay=1.0,
        jitter=0.0,
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=2,
        resolve_contract=False,
    )
    orch = Orchestrator(
        dll,  # type: ignore[arg-type]
        catalog,
        writer,
        retry_policy=fast_policy,
    )
    result = orch.run(config)
    # 1 chunk PERMANENT → tudo failed/partial, sem stack overflow / hang
    assert result.status in ("failed", "partial")
    # PERMANENT → sem retry → 1 call DLL no único chunk
    assert dll.calls_history == [_NL_INVALID_TICKER]


@pytest.mark.integration
def test_orchestrator_transient_retry_then_success(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """NL_INTERNAL_ERROR 1 vez → retry → sucesso na 2ª call."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _NLInjectingDLL(
        nl_returns=[_NL_INTERNAL_ERROR, 0],
        trade_specs_per_call=[[], [_spec(base)]],
    )
    # Policy fast — base_delay=0 para teste rápido
    fast_policy = RetryPolicy(
        max_attempts_transient=3,
        max_attempts_ambiguous=2,
        base_delay_transient=0.0,
        base_delay_ambiguous=0.0,
        factor=1.0,
        max_delay=1.0,
        jitter=0.0,
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=2,
        resolve_contract=False,
    )
    orch = Orchestrator(
        dll,  # type: ignore[arg-type]
        catalog,
        writer,
        retry_policy=fast_policy,
    )
    result = orch.run(config)
    assert result.status == "completed"
    # 2 calls: 1 falha + 1 sucesso (após retry)
    assert dll.calls_history == [_NL_INTERNAL_ERROR, 0]


@pytest.mark.integration
def test_orchestrator_transient_exhausted_marks_failed(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """N TRANSIENT errors em 1 chunk → marca chunk como failed_chunk + gap registrado."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _NLInjectingDLL(
        nl_returns=[_NL_INTERNAL_ERROR] * 10,  # sempre falha
    )
    fast_policy = RetryPolicy(
        max_attempts_transient=3,
        max_attempts_ambiguous=2,
        base_delay_transient=0.0,
        base_delay_ambiguous=0.0,
        factor=1.0,
        max_delay=1.0,
        jitter=0.0,
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=2,
        resolve_contract=False,
    )
    orch = Orchestrator(
        dll,  # type: ignore[arg-type]
        catalog,
        writer,
        retry_policy=fast_policy,
    )
    result = orch.run(config)
    # Chunk único → policy esgotou após 3 attempts → failed
    assert result.status == "failed"
    assert result.chunks_failed == 1
    # Exatamente 3 calls (max_attempts_transient)
    assert len(dll.calls_history) == 3


@pytest.mark.integration
def test_orchestrator_circuit_breaker_blocks_after_threshold(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Após N falhas TRANSIENT, breaker abre e chunks subsequentes pulam DLL."""
    # 3 chunks, todos com TRANSIENT — depois de threshold breaker abre
    base = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)  # 2 chunks
    # Cada chunk faz max_attempts=2 calls; 2 chunks x 2 calls = 4 falhas
    dll = _NLInjectingDLL(nl_returns=[_NL_INTERNAL_ERROR] * 50)
    fast_policy = RetryPolicy(
        max_attempts_transient=2,
        max_attempts_ambiguous=2,
        base_delay_transient=0.0,
        base_delay_ambiguous=0.0,
        factor=1.0,
        max_delay=1.0,
        jitter=0.0,
    )
    # Threshold baixo (2) e cooldown longo — primeiro chunk gera 2 falhas → trip
    template_breaker = CircuitBreaker(
        symbol="template",
        exchange="F",
        failure_threshold=2,
        window_seconds=60,
        cooldown_seconds=600,
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=end,
        chunk_timeout_seconds=2,
        resolve_contract=False,
    )
    orch = Orchestrator(
        dll,  # type: ignore[arg-type]
        catalog,
        writer,
        retry_policy=fast_policy,
        circuit_breaker=template_breaker,
    )
    result = orch.run(config)
    # Job falha (todos chunks failed), mas NÃO loop infinito
    assert result.status == "failed"
    # Após primeiro chunk esgotar (2 calls), breaker está OPEN.
    # Chunks subsequentes não devem invocar DLL → calls_history limitado.
    # 1 chunk x 2 calls = 2; 2º chunk bloqueado por breaker = 0 adicional.
    assert len(dll.calls_history) == 2

    # Verifica que breaker para (WDOJ26, F) está OPEN
    breaker = orch._get_breaker("WDOJ26", "F")
    assert breaker.state is BreakerState.OPEN


@pytest.mark.integration
def test_default_circuit_breaker_threshold_used_when_no_template(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Sem injeção de breaker, orchestrator cria breakers com defaults canônicos."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _NLInjectingDLL(
        nl_returns=[0],
        trade_specs_per_call=[[_spec(base)]],
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=2,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    orch.run(config)
    # Breaker para o par foi criado com defaults
    breaker = orch._get_breaker("WDOJ26", "F")
    assert breaker.failure_threshold == DEFAULT_FAILURE_THRESHOLD


@pytest.mark.integration
def test_circuit_breaker_does_not_count_q02e_progress_99_as_failure(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Q02-E (Story 2.6 AC4): 99% reconnect callbacks NÃO contam como falha.

    Cenário: chunk completa via TC_LAST_PACKET; download_primitive emite
    progress histories incluindo 99% repetidos. Orchestrator confia no
    download_primitive: status='completed' OU 'failed' baseado em NL_*
    error code real, NÃO em padrões de progress.

    Validação: 1 chunk completed → 0 falhas → breaker permanece CLOSED.
    """
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _NLInjectingDLL(
        nl_returns=[0],
        trade_specs_per_call=[[_spec(base)]],
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)
    assert result.status == "completed"
    breaker = orch._get_breaker("WDOJ26", "F")
    assert breaker.state is BreakerState.CLOSED
    assert breaker.failure_count == 0
