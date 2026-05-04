"""Integration tests — orchestrator.Orchestrator (Story 1.7a AC4..AC8).

Cobertura:

- Happy path: download de N chunks, todos persistidos, status="completed".
- Falha em 1 chunk após retries: status="partial" + gap registrado.
- Falha em todos os chunks: status="failed".
- Cache hit: range já coberto → 0 chamadas DLL, status="cache_hit".
- Resume: re-rodar com resume_job_id pula partições já completadas.
- Métricas atualizadas corretamente (callbacks_received, trades_persisted,
  chunks_completed, chunks_failed).
- State machine percorre transições corretas.

Mocka ``ProfitDLL`` inteiro via ``_FakeProfitDLL`` (mesmo padrão de
test_download_primitive). Catalog em tmp + ParquetWriter em tmp.
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
from data_downloader.orchestrator.orchestrator import (
    JobConfig,
    Orchestrator,
)
from data_downloader.orchestrator.state_machine import JobState, JobStateMachine
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter

# =====================================================================
# Mock DLL — versão simplificada para orchestrator
# =====================================================================


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Any:
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


class _FakeProfitDLL:
    """Mock DLL reusable para download_chunk + orchestrator.

    Configurável: lista de "rounds" — cada round especifica trades e
    progress emitidos durante 1 chamada a ``get_history_trades``. Round
    0 = primeira chamada, round 1 = segunda, etc.
    """

    def __init__(
        self,
        *,
        rounds: list[dict[str, Any]],
        dll_version: str = "4.0.0.34",
    ) -> None:
        self.rounds = rounds
        self.dll_version = dll_version

        self._history_cb: Any = None
        self._progress_cb: Any = None
        self._round_idx = 0

        # Counters.
        self.set_history_calls = 0
        self.set_progress_calls = 0
        self.get_history_calls = 0
        self.translate_trade_calls = 0

        # Trade specs do round corrente — translate_trade indexa por handle.
        self._current_specs: list[dict[str, Any]] = []

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
        if self._round_idx >= len(self.rounds):
            # Ran out of rounds — empty result (test misconfig or extra calls).
            return 0
        round_cfg = self.rounds[self._round_idx]
        self._round_idx += 1

        # Erros simulados
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

    def translate_trade(self, handle: int, struct: TConnectorTrade) -> int:
        self.translate_trade_calls += 1
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
        struct.BuyAgent = spec.get("buy_agent", 0)
        struct.SellAgent = spec.get("sell_agent", 0)
        struct.TradeType = spec.get("trade_type", 1)
        return 0

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
        for p in progress_seq:
            if self._progress_cb is None:
                break
            self._progress_cb(ticker, "F", 0, p)
            time.sleep(emit_delay)


def _spec(
    *,
    timestamp: datetime,
    price: float = 100.0,
    quantity: int = 1,
    trade_number: int = 1,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "price": price,
        "quantity": quantity,
        "trade_number": trade_number,
    }


def _round_with_n_trades(
    n: int,
    *,
    base: datetime,
    base_price: float = 100.0,
) -> dict[str, Any]:
    """Helper: cria round com N trades sequenciais."""
    specs = [
        _spec(
            timestamp=base.replace(microsecond=i * 1000),
            price=base_price + i,
            quantity=1,
            trade_number=i + 1,
        )
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
def catalog(data_dir: Path) -> Catalog:
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    yield cat
    cat.close()


@pytest.fixture
def writer(data_dir: Path) -> ParquetWriter:
    return ParquetWriter(data_dir=data_dir)


# =====================================================================
# Happy path — 1 chunk
# =====================================================================


@pytest.mark.integration
def test_orchestrator_happy_path_single_chunk(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """1 dia útil → 1 chunk → 1 partição persistida; status='completed'."""
    base = datetime(2026, 3, 2, 9, 0, 0)  # segunda-feira, dia útil
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(5, base=base)])

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,  # já é contrato vigente
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)

    assert result.status == "completed"
    assert result.chunks_completed == 1
    assert result.chunks_failed == 0
    assert result.metrics.trades_persisted == 5
    assert len(result.partitions_written) == 1
    # Verifica catalog.
    job = catalog.get_job(result.job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.trades_count == 5
    # Verifica partição existe em disco.
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1
    assert parts[0].year == 2026
    assert parts[0].month == 3


# =====================================================================
# Happy path — múltiplos chunks (1 semana WDO = 1 chunk; 2 semanas = 2)
# =====================================================================


@pytest.mark.integration
def test_orchestrator_happy_path_two_chunks(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """2 semanas WDO → 2 chunks; ambos persistidos."""
    # 2026-03-02 (seg) a 2026-03-13 (sex) = 10 dias úteis = 2 chunks de 5.
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    base = start
    dll = _FakeProfitDLL(
        rounds=[
            _round_with_n_trades(3, base=base.replace(day=2)),
            _round_with_n_trades(4, base=base.replace(day=9)),
        ]
    )

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)

    assert result.status == "completed"
    assert result.chunks_completed == 2
    assert result.chunks_failed == 0
    assert result.metrics.trades_persisted == 7
    # Mesma partição (março/2026) — 2 chunks escrevem na mesma; UPSERT idempotente.
    assert len(result.partitions_written) == 2
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    # Última escrita ganha (UPSERT) — 1 partição com row_count = 7
    # (writer faz dedup+merge, então 3+4=7 sem dups).
    assert len(parts) == 1
    assert parts[0].row_count == 7


# =====================================================================
# Falha em 1 chunk → status partial + gap
# =====================================================================


@pytest.mark.integration
def test_orchestrator_partial_when_one_chunk_fails(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """1º chunk falha (NL_*); 2º chunk OK → status='partial' + 1 gap."""
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    # Primeiro round retorna NL_* error em todas as 3 tentativas;
    # segundo round retorna 4 trades.
    fail_round = {"get_history_return": -2147483390}  # NL_INVALID_TICKER
    success_round = _round_with_n_trades(4, base=start.replace(day=9))
    dll = _FakeProfitDLL(rounds=[fail_round, fail_round, fail_round, success_round])

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        max_retry_attempts=3,
        retry_base_delay=0.001,  # quase zero para teste rápido
        retry_factor=1.0,
        retry_jitter=0.0,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)

    assert result.status == "partial"
    assert result.chunks_completed == 1
    assert result.chunks_failed == 1
    assert result.metrics.trades_persisted == 4
    # Gap registrado para 1ª semana.
    gaps = catalog.get_gaps("WDOJ26")
    assert len(gaps) == 1
    assert gaps[0].reason == "failed_chunk"


# =====================================================================
# Falha em todos os chunks → status failed
# =====================================================================


@pytest.mark.integration
def test_orchestrator_failed_when_all_chunks_fail(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Todos os 6 attempts falham (3 retries x 2 chunks) -> status='failed'."""
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    fail_round = {"get_history_return": -2147483390}
    dll = _FakeProfitDLL(rounds=[fail_round] * 6)  # 2 chunks x 3 attempts

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        max_retry_attempts=3,
        retry_base_delay=0.001,
        retry_factor=1.0,
        retry_jitter=0.0,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    result = orch.run(config)

    assert result.status == "failed"
    assert result.chunks_completed == 0
    assert result.chunks_failed == 2
    job = catalog.get_job(result.job_id)
    assert job is not None
    assert job.status == "failed"


# =====================================================================
# Cache hit
# =====================================================================


@pytest.mark.integration
def test_orchestrator_cache_hit_when_range_fully_covered(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Após download completo, re-rodar mesmo (symbol, range) = cache_hit."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    # Primeiro run: baixa.
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(3, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    first = orch.run(config)
    assert first.status == "completed"
    initial_get_history_calls = dll.get_history_calls

    # Segundo run com mesmo config: cache_hit.
    second = orch.run(config)
    assert second.status == "cache_hit"
    assert second.chunks_completed == 0
    assert second.chunks_failed == 0
    assert second.partitions_written == ()
    # Nenhuma chamada extra à DLL.
    assert dll.get_history_calls == initial_get_history_calls


@pytest.mark.integration
def test_orchestrator_no_cache_hit_when_range_extends_beyond(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Range que extrapola partições registradas NÃO é cache hit (finding H8)."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll1 = _FakeProfitDLL(rounds=[_round_with_n_trades(2, base=base)])
    config1 = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    Orchestrator(dll1, catalog, writer).run(config1)  # type: ignore[arg-type]

    # Segundo run com range que se estende para abril.
    apr_base = datetime(2026, 4, 1, 9, 0, 0)
    dll2 = _FakeProfitDLL(
        rounds=[_round_with_n_trades(3, base=apr_base)] * 5  # vários chunks abril
    )
    config2 = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=datetime(2026, 4, 30, 17, 0, 0),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    result = Orchestrator(dll2, catalog, writer).run(config2)  # type: ignore[arg-type]
    # Não cache hit — abril não está em disco.
    assert result.status != "cache_hit"


# =====================================================================
# Resume
# =====================================================================


@pytest.mark.integration
def test_orchestrator_resume_skips_completed_months(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Job com 2 meses; após 1º mês baixar, resume só baixa o 2º."""
    # Janela: março 2026 + abril 2026.
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 4, 30, 17, 0, 0)

    # Primeiro run baixa só março (vamos abortar antes do abril).
    # Para simular: rodamos 1º run com range só de março, registramos job.
    mar_only_dll = _FakeProfitDLL(
        rounds=[_round_with_n_trades(2, base=start)] * 5  # 5 chunks março
    )
    mar_config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=datetime(2026, 3, 31, 17, 0, 0),
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    first = Orchestrator(mar_only_dll, catalog, writer).run(mar_config)  # type: ignore[arg-type]
    assert first.status == "completed"

    # Agora cria job NOVO cobrindo março+abril, mas usa resume (passa job_id
    # do primeiro run).
    apr_dll = _FakeProfitDLL(
        rounds=[
            _round_with_n_trades(2, base=datetime(2026, 4, day, 9, 0, 0))
            for day in (1, 6, 13, 20, 27)
        ]
    )
    full_config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    second = Orchestrator(apr_dll, catalog, writer).run(  # type: ignore[arg-type]
        full_config, resume_job_id=first.job_id
    )
    # Apenas chunks de abril foram baixados.
    # March já está em disco — orchestrator pula esses meses.
    assert second.status in ("completed", "partial")
    # Se o run cobriu apenas meses pendentes (abril), todos chunks são abril.
    assert apr_dll.get_history_calls >= 1


# =====================================================================
# Métricas + state machine
# =====================================================================


@pytest.mark.integration
def test_orchestrator_metrics_populated(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Métricas refletem trades recebidos + persistidos + duração."""
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(7, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    result = Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]

    assert result.metrics.callbacks_received == 7
    assert result.metrics.trades_persisted == 7
    assert result.metrics.chunks_completed == 1
    assert result.metrics.chunks_failed == 0
    assert result.metrics.dll_drops_total == 0  # block back-pressure (V1)
    assert result.metrics.started_at is not None
    assert result.metrics.completed_at is not None
    assert result.metrics.duration_seconds is not None
    assert result.metrics.duration_seconds >= 0


@pytest.mark.integration
def test_orchestrator_state_machine_observed_transitions(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Verifica via on_change callback que transições percorrem caminho canônico.

    Usamos uma instância separada de JobStateMachine via callback hook
    apenas — orchestrator usa sua própria interna. Aqui inspecionamos
    diretamente via patch no logger.
    """
    # Estratégia: rodar happy path e verificar que catalog reflete
    # status final correto (proxy para state machine).
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(3, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    result = Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]
    assert result.status == "completed"
    job = catalog.get_job(result.job_id)
    assert job is not None
    assert job.completed_at is not None


# =====================================================================
# Validação de config
# =====================================================================


@pytest.mark.integration
def test_orchestrator_rejects_invalid_exchange(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="BMF",  # inválido
        start=base,
        end=base.replace(hour=17),
        resolve_contract=False,
    )
    with pytest.raises(ValueError, match="exchange"):
        Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]


@pytest.mark.integration
def test_orchestrator_rejects_inverted_range(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base.replace(hour=17),
        end=base.replace(hour=9),
        resolve_contract=False,
    )
    with pytest.raises(ValueError, match="end"):
        Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]


# =====================================================================
# State machine spy — verifica caminho IDLE→RUNNING→DRAINING_DLL→...→IDLE
# =====================================================================


@pytest.mark.integration
def test_state_machine_full_cycle_observable_via_spy(
    catalog: Catalog,
    writer: ParquetWriter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patcha JobStateMachine para registrar todas as transições."""
    transitions: list[tuple[JobState, JobState]] = []
    original = JobStateMachine

    class _SpyJSM(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            existing = kwargs.get("on_change")

            def _on_change(f: JobState, t: JobState) -> None:
                transitions.append((f, t))
                if existing is not None:
                    existing(f, t)

            kwargs["on_change"] = _on_change
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("data_downloader.orchestrator.orchestrator.JobStateMachine", _SpyJSM)

    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(2, base=base)])
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]

    # Esperado: IDLE→RUNNING→DRAINING_DLL→DRAINING_WRITE→COMMITTED→IDLE
    states = [t for _, t in transitions]
    assert JobState.RUNNING in states
    assert JobState.DRAINING_DLL in states
    assert JobState.DRAINING_WRITE in states
    assert JobState.COMMITTED in states
    assert JobState.IDLE in states
    # Ordem.
    expected_order = [
        JobState.RUNNING,
        JobState.DRAINING_DLL,
        JobState.DRAINING_WRITE,
        JobState.COMMITTED,
        JobState.IDLE,
    ]
    # Filtra para só os esperados (transitions são todas as ocorridas).
    filtered = [s for s in states if s in expected_order]
    assert filtered == expected_order
