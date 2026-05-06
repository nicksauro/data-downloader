"""Integration tests — Orchestrator emits ChunkCompletedEvent (Story 4.16).

Owner: Dex (impl) | Pichau directive 2026-05-06.

Cobertura:
    - Listener recebe 1 ChunkCompletedEvent por chunk processado.
    - chunk_index é 0-based e cresce monotonicamente.
    - total_chunks reflete o plano (len(chunks)).
    - progress_pct cobre 0..100 (último chunk = 100%).
    - chunk_strategy aplicado: WDOFUT → 5d/chunk, WINFUT → 1d/chunk.
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
    """2 semanas WDO → 2 chunks → listener recebe 2 events com indices 0,1."""
    # 2026-03-02 (seg) a 2026-03-13 (sex) = 10 dias úteis = 2 chunks de 5d.
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
    assert len(events) == 2, f"expected 2 chunk events, got {len(events)}"
    assert events[0].chunk_index == 0
    assert events[1].chunk_index == 1
    assert events[0].total_chunks == 2
    assert events[1].total_chunks == 2
    assert events[0].status == "success"
    assert events[1].status == "success"
    assert events[0].progress_pct == pytest.approx(50.0)
    assert events[1].progress_pct == pytest.approx(100.0)


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
def test_chunk_listener_wdofut_uses_5d_chunk(
    catalog: Catalog,
    writer: ParquetWriter,
) -> None:
    """Story 4.16: WDOFUT (chunk_days=5) → 1 evento para 5 dias úteis."""
    # 5 dias úteis (1 semana cheia) = 1 chunk WDO.
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

    # 5 dias / 5d-chunk = 1 chunk.
    assert len(events) == 1
    assert events[0].chunk_index == 0
    assert events[0].total_chunks == 1
    assert events[0].progress_pct == pytest.approx(100.0)
    assert events[0].trades_count == 3  # patch retorna 3 em "success"


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
    result = orch.run(config, chunk_listener=_broken_listener)
    assert result.status == "completed"
    assert result.chunks_completed == 1
