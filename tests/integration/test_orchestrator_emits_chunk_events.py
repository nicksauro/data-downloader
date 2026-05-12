"""Integration tests — Orchestrator emits ChunkCompletedEvent (Story 4.16).

Owner: Dex (impl) | Pichau directive 2026-05-07 (supersede 2026-05-06).

V1.1.0 política unificada: SEMPRE 1d/chunk para todos os ativos.

Cobertura:
    - Listener recebe 1 ChunkCompletedEvent por chunk processado.
    - chunk_index é 0-based e cresce monotonicamente.
    - total_chunks reflete o plano (len(chunks)).
    - progress_pct cobre 0..100 (último chunk = 100%).
    - chunk_strategy aplicado: TODOS os ativos → 1d/chunk (V1.1.0+).
    - Listener exception NÃO derruba orchestrator (best-effort).

Estratégia: monkey-patch ``Orchestrator._process_chunk`` para retornar
sucessos sintéticos, isolando do pipeline DLL/writer real (que é coberto
em test_orchestrator.py via ``_FakeProfitDLL``). Isto mantém o teste
focado APENAS na fronteira ``chunk_listener`` x ``ChunkCompletedEvent``,
fora do hot path stable da Story 1.7a.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from data_downloader.orchestrator.orchestrator import (
    ChunkCompletedEvent,
    JobConfig,
    Orchestrator,
)
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter

# =====================================================================
# Fixtures — catalog + writer reais; DLL e _process_chunk fakeados
# =====================================================================


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def catalog(data_dir: Path):
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    yield cat
    cat.close()


@pytest.fixture
def writer(data_dir: Path) -> ParquetWriter:
    return ParquetWriter(data_dir=data_dir)


class _NoopDLL:
    """Mock minimalista — orchestrator não chamará via _process_chunk patched."""

    dll_version = "4.0.0.34-test"


def _patch_process_chunk(orch: Orchestrator, *, status: str = "success") -> None:
    """Substitui ``_process_chunk`` por stub determinístico que registra
    métricas e retorna a tupla ``(None, status, duration, trades)``."""

    def _fake_process_chunk(
        *,
        job_id: str,
        config: JobConfig,
        contract_code: str,
        chunk: Any,
        metrics: Any,
    ) -> tuple[Any, str, float, int]:
        # Simula contadores que o real incrementaria.
        if status == "success":
            metrics.chunks_completed += 1
            metrics.trades_persisted += 3
            return None, "success", 0.01, 3
        if status == "no_trades":
            metrics.chunks_completed += 1
            return None, "no_trades", 0.01, 0
        # failed
        metrics.chunks_failed += 1
        return None, "failed", 0.01, 0

    orch._process_chunk = _fake_process_chunk  # type: ignore[method-assign]


# =====================================================================
# Tests
# =====================================================================


@pytest.mark.integration
def test_chunk_listener_receives_one_event_per_chunk(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """V1.1.0+: 2 semanas WDO → 10 chunks (1d cada) → 10 events 0..9."""
    # 2026-03-02 (seg) a 2026-03-13 (sex) = 10 dias úteis = 10 chunks de 1d
    # (Pichau directive 2026-05-07 — política unificada).
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 13, 17, 0, 0)
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(_NoopDLL(), catalog, writer)  # type: ignore[arg-type]
    _patch_process_chunk(orch, status="success")

    events: list[ChunkCompletedEvent] = []
    result = orch.run(config, chunk_listener=events.append)

    assert result.status == "completed"
    assert len(events) == 10, f"expected 10 chunk events, got {len(events)}"
    # chunk_index 0-based monotonic.
    for i, ev in enumerate(events):
        assert ev.chunk_index == i
        assert ev.total_chunks == 10
        assert ev.status == "success"
    assert events[0].progress_pct == pytest.approx(10.0)
    assert events[4].progress_pct == pytest.approx(50.0)
    assert events[-1].progress_pct == pytest.approx(100.0)


@pytest.mark.integration
def test_chunk_listener_winfut_emits_per_day_chunk(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Story 4.16: WINFUT (chunk_days=1) → 1 evento por dia útil.

    Confirma que o ``chunk_strategy.get_chunk_days`` está integrado no
    cálculo de chunks.
    """
    # 3 dias úteis (seg, ter, qua) → 3 chunks de 1d.
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 4, 17, 0, 0)
    config = JobConfig(
        symbol="WINFUT",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(_NoopDLL(), catalog, writer)  # type: ignore[arg-type]
    _patch_process_chunk(orch, status="success")

    events: list[ChunkCompletedEvent] = []
    orch.run(config, chunk_listener=events.append)

    # 3 dias / 1d-chunk = 3 chunks (chunk_strategy WINFUT=1).
    assert len(events) == 3
    assert events[0].total_chunks == 3
    assert events[2].chunk_index == 2
    assert events[2].progress_pct == pytest.approx(100.0)


@pytest.mark.integration
def test_chunk_listener_wdofut_uses_1d_chunk(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """V1.1.0+ Pichau 2026-05-07: WDOFUT (chunk_days=1) → 5 events para
    5 dias úteis (política unificada — supersede directive 2026-05-06)."""
    # 5 dias úteis (1 semana cheia) = 5 chunks WDO de 1d cada.
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 6, 17, 0, 0)
    config = JobConfig(
        symbol="WDOFUT",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(_NoopDLL(), catalog, writer)  # type: ignore[arg-type]
    _patch_process_chunk(orch, status="success")

    events: list[ChunkCompletedEvent] = []
    orch.run(config, chunk_listener=events.append)

    # 5 dias / 1d-chunk = 5 chunks (V1.1.0+ política unificada).
    assert len(events) == 5
    for i, ev in enumerate(events):
        assert ev.chunk_index == i
        assert ev.total_chunks == 5
        assert ev.trades_count == 3  # patch retorna 3 em "success"
    assert events[-1].progress_pct == pytest.approx(100.0)


@pytest.mark.integration
def test_chunk_listener_exception_does_not_break_orchestrator(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Listener que levanta exception NÃO impede orchestrator de completar.

    Garante R6 (UI não pode derrubar pipeline) — best-effort emission.
    """
    start = datetime(2026, 3, 2, 9, 0, 0)
    end = datetime(2026, 3, 6, 17, 0, 0)
    config = JobConfig(
        symbol="WDOJ26",
        exchange="F",
        start=start,
        end=end,
        chunk_timeout_seconds=10,
        resolve_contract=False,
    )
    orch = Orchestrator(_NoopDLL(), catalog, writer)  # type: ignore[arg-type]
    _patch_process_chunk(orch, status="success")

    def _broken_listener(_event: ChunkCompletedEvent) -> None:
        raise RuntimeError("listener boom")

    # Não deve levantar — orchestrator suprime exception do listener.
    # V1.1.0+ política unificada: 5 dias úteis = 5 chunks de 1d.
    result = orch.run(config, chunk_listener=_broken_listener)
    assert result.status == "completed"
    assert result.chunks_completed == 5
