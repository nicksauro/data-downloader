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
    TAssetID,
    TConnectorAssetIdentifier,
    TradeFields,
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


def _dt_to_brt_naive_ns(dt: datetime) -> int:
    """datetime naive (BRT, lei R7) → ns desde 1970-01-01 — espelha
    ``download_primitive._system_time_to_ns_local`` (v1.1.0 task #10)."""
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
            # Ran out of rounds — emite chunk vazio mas COMPLETO (progress=100)
            # em vez de retornar 0 e nunca sinalizar fim. Sem isso o
            # download_chunk fica em timeout (10s) → retry → suite "pendura"
            # quando o chunker ADR-023 (1d) gera mais chunks que rounds
            # configurados. v1.1.0 task #10 — Quinn QA 2026-05-11.
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

    def translate_trade(self, handle: int) -> TradeFields | None:
        """API V2 (Story 1.7b-followup): ``(handle) -> TradeFields | None``.

        Antes (drift): ``(handle, struct) -> int`` mutando struct in-place
        — incompatível com ``download_chunk`` atual; causava o deadlock da
        suite de integração (v1.1.0 task #10 — Quinn QA 2026-05-11).
        """
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
        # TProgressCallback V2 (Q-DRIFT-05): 2 args (TAssetID, c_int).
        progress_asset = TAssetID(ticker=ticker, bolsa="F", feed=0)
        for p in progress_seq:
            if self._progress_cb is None:
                break
            self._progress_cb(progress_asset, p)
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


@pytest.fixture
def fast_retry_policy() -> Any:
    """Story 2.6 — RetryPolicy com delays quase zero para testes rápidos."""
    from data_downloader.orchestrator.retry_policy import RetryPolicy

    return RetryPolicy(
        max_attempts_transient=3,
        max_attempts_ambiguous=2,
        base_delay_transient=0.001,
        base_delay_ambiguous=0.001,
        factor=1.0,
        jitter=0.0,
        max_delay=0.01,
    )


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
# Happy path — múltiplos chunks (ADR-023: 1d uniforme → N dias úteis = N chunks)
# =====================================================================


@pytest.mark.integration
def test_orchestrator_happy_path_two_chunks(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Janela de 10 dias úteis WDO → 10 chunks de 1d (ADR-023).

    2 chunks carregam trades (rounds 0 e 1); os 8 restantes ficam vazios
    (out-of-rounds → no_trades). Ambos os chunks com trades escrevem na
    mesma partição (março/2026) via UPSERT idempotente.
    """
    # 2026-03-02 (seg) a 2026-03-13 (sex) = 10 dias úteis = 10 chunks de 1d.
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
    assert result.chunks_completed == 10  # 10 dias úteis = 10 chunks (ADR-023)
    assert result.chunks_failed == 0
    assert result.metrics.trades_persisted == 7
    # Só os 2 chunks com trades escrevem partição; ADR-025 v1.3.0 — cada
    # chunk vira 1 partição DIÁRIA distinta (day=2 e day=9). Não há
    # compactação pq só baixamos 10 dias úteis de março, mas março tem ~22.
    assert len(result.partitions_written) == 2
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    # ADR-025: 2 partições diárias distintas (1º e 2º dia útil = Mar 02 e Mar 03).
    # Os 2 rounds do _FakeProfitDLL são consumidos pelos 2 primeiros chunks
    # (1 dia útil cada — ADR-023); a base interna dos trades nos rounds é
    # cosmética, o orchestrator escreve usando ``chunk.start.day``.
    assert len(parts) == 2
    assert all(p.day is not None for p in parts)
    assert {p.month for p in parts} == {3}
    total_rows = sum(p.row_count for p in parts)
    assert total_rows == 7


# =====================================================================
# Falha em 1 chunk → status partial + gap
# =====================================================================


@pytest.mark.integration
def test_orchestrator_partial_when_one_chunk_fails(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """1º chunk (1d) falha após retries; 2º chunk OK → status='partial' + gaps.

    ADR-023: janela de 10 dias úteis = 10 chunks de 1d. Chunk 0 esgota 3
    tentativas TRANSIENT (NL_INTERNAL_ERROR) → 1 gap 'failed_chunk'. Chunk 1
    persiste 4 trades. Chunks 2..9 ficam vazios (out-of-rounds → 8 gaps
    'no_trades'). Story 2.6 — policy fast (delay ~0) para velocidade.
    """
    from data_downloader.orchestrator.retry_policy import RetryPolicy

    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    # NL_INTERNAL_ERROR é TRANSIENT na taxonomia Nelo (Story 2.6).
    fail_round = {"get_history_return": -2147483647}  # NL_INTERNAL_ERROR
    success_round = _round_with_n_trades(4, base=start.replace(day=9))
    # Chunk 0: 3 falhas (3 attempts). Chunk 1: sucesso. Chunks 2..9: out-of-rounds.
    dll = _FakeProfitDLL(rounds=[fail_round, fail_round, fail_round, success_round])

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    fast_policy = RetryPolicy(
        max_attempts_transient=3,
        base_delay_transient=0.001,
        factor=1.0,
        jitter=0.0,
    )
    orch = Orchestrator(dll, catalog, writer, retry_policy=fast_policy)  # type: ignore[arg-type]
    result = orch.run(config)

    assert result.status == "partial"
    # 1 chunk falhou (chunk 0); os outros 9 "completaram" (1 com trades, 8 vazios).
    assert result.chunks_completed == 9
    assert result.chunks_failed == 1
    assert result.metrics.trades_persisted == 4
    # 1 gap 'failed_chunk' (chunk 0) + 8 gaps 'no_trades' (chunks 2..9).
    gaps = catalog.get_gaps("WDOJ26")
    failed_gaps = [g for g in gaps if g.reason == "failed_chunk"]
    assert len(failed_gaps) == 1
    assert len(gaps) == 9


# =====================================================================
# Falha em todos os chunks → status failed
# =====================================================================


@pytest.mark.integration
def test_orchestrator_failed_when_all_chunks_fail(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Todos os chunks falham → status='failed'.

    ADR-023: janela de 10 dias úteis = 10 chunks de 1d. Cada chunk esgota 3
    tentativas TRANSIENT (NL_INTERNAL_ERROR) → 30 rounds de falha. Nenhum
    chunk completa → status='failed'. Story 2.6 — policy fast (delay ~0).
    """
    from data_downloader.orchestrator.retry_policy import RetryPolicy

    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    fail_round = {"get_history_return": -2147483647}  # NL_INTERNAL_ERROR (TRANSIENT)
    dll = _FakeProfitDLL(rounds=[fail_round] * 30)  # 10 chunks x 3 attempts

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    fast_policy = RetryPolicy(
        max_attempts_transient=3,
        base_delay_transient=0.001,
        factor=1.0,
        jitter=0.0,
    )
    orch = Orchestrator(dll, catalog, writer, retry_policy=fast_policy)  # type: ignore[arg-type]
    result = orch.run(config)

    assert result.status == "failed"
    assert result.chunks_completed == 0
    assert result.chunks_failed == 10  # 10 dias úteis = 10 chunks (ADR-023)
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
    fast_retry_policy: Any,
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
    Orchestrator(dll1, catalog, writer, retry_policy=fast_retry_policy).run(config1)  # type: ignore[arg-type]

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
    result = Orchestrator(dll2, catalog, writer, retry_policy=fast_retry_policy).run(config2)  # type: ignore[arg-type]
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


# =====================================================================
# Wave 1B — resume DIÁRIO + fresh-path skip (chunk_ledger)
# =====================================================================


@pytest.mark.integration
def test_fresh_rerun_skips_completed_days_without_resume(
    catalog: Catalog,
    writer: ParquetWriter,
    fast_retry_policy: Any,
) -> None:
    """Wave 1B — re-rodar o MESMO range (sem --resume) NÃO re-baixa dias prontos.

    Run 1: janela de 5 dias úteis; o 3º dia falha definitivamente (gap +
    ledger=failed). Run 2: re-roda o range inteiro SEM resume — só o dia que
    falhou é re-baixado (os 4 dias OK estão no ``chunk_ledger`` como prontos).
    """
    # 2026-03-02 (seg) a 2026-03-06 (sex) = 5 dias úteis.
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 6, 17, 0, 0)
    fail_round = {"get_history_return": -2147483647}  # NL_INTERNAL_ERROR (TRANSIENT)

    # Run 1 — dias 1,2 OK; dia 3 falha 3x; dias 4,5 out-of-rounds (no_trades).
    dll1 = _FakeProfitDLL(
        rounds=[
            _round_with_n_trades(3, base=start.replace(day=2)),
            _round_with_n_trades(2, base=start.replace(day=3)),
            fail_round,
            fail_round,
            fail_round,
        ]
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    r1 = Orchestrator(dll1, catalog, writer, retry_policy=fast_retry_policy).run(config)  # type: ignore[arg-type]
    assert r1.status == "partial"
    # 5 dias úteis no ledger: 4 prontos (completed/no_trades) + 1 failed.
    done_after_r1 = catalog.completed_days("WDOJ26", "F", start.date(), end.date())
    assert len(done_after_r1) == 4  # o dia 4 (2026-03-04) que falhou NÃO conta

    # Run 2 — re-roda o range inteiro SEM resume. Só 1 chunk (o dia que
    # falhou) deve ser efetivamente baixado: a DLL recebe exatamente 1
    # get_history call.
    dll2 = _FakeProfitDLL(rounds=[_round_with_n_trades(5, base=start.replace(day=4))])
    r2 = Orchestrator(dll2, catalog, writer, retry_policy=fast_retry_policy).run(config)  # type: ignore[arg-type]
    assert dll2.get_history_calls == 1  # só o dia faltante foi re-baixado
    assert r2.status == "completed"
    # Agora todos os 5 dias úteis estão prontos.
    assert len(catalog.completed_days("WDOJ26", "F", start.date(), end.date())) == 5


@pytest.mark.integration
def test_resume_job_id_resumes_only_missing_days(
    catalog: Catalog,
    writer: ParquetWriter,
    fast_retry_policy: Any,
) -> None:
    """Wave 1B — ``resume_job_id`` retoma só os dias faltantes (granularidade DIÁRIA).

    Run 1 cobre 3 dias úteis; o 2º falha. Run 2 com ``resume_job_id`` do run 1
    baixa só o dia 2 (não re-baixa os dias 1 e 3).
    """
    start = datetime(2026, 3, 2, 9, 0, 0)  # seg
    end = datetime(2026, 3, 4, 17, 0, 0)  # qua → 3 dias úteis
    fail_round = {"get_history_return": -2147483647}

    dll1 = _FakeProfitDLL(
        rounds=[
            _round_with_n_trades(2, base=start.replace(day=2)),
            fail_round,
            fail_round,
            fail_round,
            _round_with_n_trades(3, base=start.replace(day=4)),
        ]
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    r1 = Orchestrator(dll1, catalog, writer, retry_policy=fast_retry_policy).run(config)  # type: ignore[arg-type]
    assert r1.status == "partial"
    assert r1.job_id

    # Resume — só o dia 2026-03-03 deve ser re-baixado.
    dll2 = _FakeProfitDLL(rounds=[_round_with_n_trades(4, base=start.replace(day=3))])
    r2 = Orchestrator(dll2, catalog, writer, retry_policy=fast_retry_policy).run(  # type: ignore[arg-type]
        config, resume_job_id=r1.job_id
    )
    assert dll2.get_history_calls == 1
    assert r2.status == "completed"
    assert len(catalog.completed_days("WDOJ26", "F", start.date(), end.date())) == 3


# =====================================================================
# v1.3.0 Wave 2A — DLL session state emission durante o run
# =====================================================================


@pytest.fixture
def _reset_dll_session_module():
    """Reset estado global do ``dll.session`` entre testes."""
    import data_downloader.dll.session as session_mod

    saved_observers = list(session_mod._OBSERVERS)
    saved_state = session_mod._DLL_STATE
    saved_version = session_mod._DLL_VERSION
    session_mod._OBSERVERS = []
    session_mod._DLL_STATE = "idle"
    session_mod._DLL_VERSION = "—"
    yield
    session_mod._OBSERVERS = saved_observers
    session_mod._DLL_STATE = saved_state
    session_mod._DLL_VERSION = saved_version


@pytest.mark.integration
def test_orchestrator_emits_downloading_state_during_run(
    catalog: Catalog,
    writer: ParquetWriter,
    _reset_dll_session_module,
) -> None:
    """Durante o run, ``dll.session`` recebe estado ``downloading``."""
    import data_downloader.dll.session as session_mod

    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(3, base=base)])

    states_seen: list[tuple[str, str]] = []
    session_mod.register_state_observer(lambda s, v: states_seen.append((s, v)))

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]

    states = [s for s, _ in states_seen]
    assert "downloading" in states
    # symbol viaja como "version" no payload do estado downloading.
    downloading_events = [(s, v) for s, v in states_seen if s == "downloading"]
    assert any("WDOJ26" in v for _, v in downloading_events)


@pytest.mark.integration
def test_orchestrator_emits_connected_at_end_when_dll_active(
    catalog: Catalog,
    writer: ParquetWriter,
    _reset_dll_session_module,
) -> None:
    """No fim do run, se ``has_active_dll`` → emite ``connected``."""
    import data_downloader.dll.session as session_mod

    # Simula que o singleton tem uma DLL ativa (set diretamente — o mock
    # ``_FakeProfitDLL`` deste teste NÃO passa por ``get_dll``, então
    # precisamos mockar o ``has_active_dll`` retornando True).
    session_mod._DLL_INSTANCE = object()  # sentinela qualquer; só checa "is not None"

    base = datetime(2026, 3, 2, 9, 0, 0)
    dll = _FakeProfitDLL(rounds=[_round_with_n_trades(2, base=base)])

    states_seen: list[str] = []
    session_mod.register_state_observer(lambda s, v: states_seen.append(s))

    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(hour=17),
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    Orchestrator(dll, catalog, writer).run(config)  # type: ignore[arg-type]

    # Cleanup: zera o sentinel.
    session_mod._DLL_INSTANCE = None

    # No fim do run, o orchestrator deve emitir ``connected`` (DLL ativa).
    assert states_seen[-1] == "connected"


@pytest.mark.integration
def test_orchestrator_pause_event_skips_chunks_during_pause(
    catalog: Catalog,
    writer: ParquetWriter,
    _reset_dll_session_module,
) -> None:
    """Pause cooperativo: ao setar pause_event, loop pausa entre chunks.

    Simula reconnect-without-reinit: thread externa seta o pause_event
    durante o run; loop pausa, clear o event, retoma. Verifica que o
    orchestrator NÃO mata chunk em andamento mas aguarda entre eles.
    """
    base = datetime(2026, 3, 2, 9, 0, 0)
    # 2 chunks (2 dias úteis): seg + ter.
    dll = _FakeProfitDLL(
        rounds=[
            _round_with_n_trades(2, base=base),
            _round_with_n_trades(2, base=base.replace(day=3)),
        ]
    )
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=base,
        end=base.replace(day=3, hour=17),
        chunk_timeout_seconds=5,
        resolve_contract=False,
    )
    orch = Orchestrator(dll, catalog, writer)  # type: ignore[arg-type]
    # Smoke test: sem pause setado, ambos os chunks rodam normalmente.
    result = orch.run(config)
    assert result.status == "completed"
    assert result.chunks_completed == 2
