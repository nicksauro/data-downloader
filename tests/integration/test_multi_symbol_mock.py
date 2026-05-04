"""Integration tests — broker.master end-to-end com mock DLL (Story 4.1 AC5..AC7).

Cobertura:

- Pool de 2 workers + 2 jobs distintos: ambos completam, catálogo único contém
  partições de ambos sem race.
- Property test: para N workers concorrentes registrando partições de mesma
  estrutura, register_partition é serializado via broker (sem duplicate keys
  no SQLite).
- Cleanup: master.stop() encerra workers + broker graciosamente.

Notes:
    Usa multiprocessing real (Windows spawn) — testes podem ser lentos
    (5-15s cada por causa do spawn cost). Marcar como ``slow`` se necessário.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.orchestrator.broker.master import (
    MultiSymbolJobConfig,
    MultiSymbolMaster,
)
from data_downloader.orchestrator.broker.pool import PoolConfig
from data_downloader.storage.catalog import Catalog


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configura mock factory para gerar pequenos jobs rápidos."""
    monkeypatch.setenv("MOCK_TRADES_PER_CHUNK", "200")
    monkeypatch.setenv("MOCK_N_CHUNKS_PER_JOB", "1")
    monkeypatch.setenv("MOCK_DELAY_MS_PER_CHUNK", "0")


def _build_master(catalog: Catalog, data_dir: Path, n_workers: int) -> MultiSymbolMaster:
    config = PoolConfig(
        n_workers=n_workers,
        data_dir=data_dir,
        worker_factory_module="data_downloader.orchestrator.broker._mock_worker_factory",
        worker_factory_callable="create_orchestrator",
        broker_timeout_s=15.0,
    )
    return MultiSymbolMaster(catalog=catalog, pool_config=config)


def test_two_workers_two_symbols_both_complete(tmp_path: Path, mock_env: None) -> None:
    """2 workers x 2 símbolos: ambos completam + catalog único + sem duplicates."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)

    try:
        with _build_master(catalog, data_dir, n_workers=2) as master:
            jobs = [
                MultiSymbolJobConfig(
                    symbol="WDOJ26",
                    exchange="F",
                    start=datetime(2026, 3, 2, 9, 0),
                    end=datetime(2026, 3, 2, 17, 0),
                    resolve_contract=False,
                ),
                MultiSymbolJobConfig(
                    symbol="WDOK26",
                    exchange="F",
                    start=datetime(2026, 3, 2, 9, 0),
                    end=datetime(2026, 3, 2, 17, 0),
                    resolve_contract=False,
                ),
            ]
            outcomes = master.download_multi(jobs)

        assert len(outcomes) == 2
        statuses = {o.status for o in outcomes}
        # Ambos completos (no_trades é "completed" no orchestrator se chunk OK
        # mas com 0 trades — usamos trades_per_chunk=200 para ter dados).
        assert statuses.issubset(
            {"completed", "partial"}
        ), f"Unexpected statuses: {[(o.symbol, o.status, o.error) for o in outcomes]}"
        # Símbolos preservados em ordem.
        assert outcomes[0].symbol == "WDOJ26"
        assert outcomes[1].symbol == "WDOK26"

        # Catálogo único contém partições de ambos os símbolos.
        wdoj_parts = catalog.get_completed_partitions("WDOJ26", "F")
        wdok_parts = catalog.get_completed_partitions("WDOK26", "F")
        assert len(wdoj_parts) >= 1, "WDOJ26 deve ter ao menos 1 partição"
        assert len(wdok_parts) >= 1, "WDOK26 deve ter ao menos 1 partição"

        # Sem duplicate keys (UPSERT do broker preservou idempotência).
        all_paths = [p.partition_path for p in wdoj_parts + wdok_parts]
        assert len(all_paths) == len(set(all_paths))

    finally:
        catalog.close()


def test_broker_serializes_writes_no_sqlite_busy(tmp_path: Path, mock_env: None) -> None:
    """Property test variant: 4 workers concorrentes nunca disparam SQLITE_BUSY.

    Verifica AC3 (broker mantém SQLite write lock; serializa writes) — N
    workers escrevendo concorrentemente NÃO geram exceptions de lock no
    catálogo, e todas as partições são persistidas.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)

    try:
        stats_snapshot: dict[str, int] = {}
        with _build_master(catalog, data_dir, n_workers=4) as master:
            jobs = [
                MultiSymbolJobConfig(
                    symbol=f"WDO{letter}26",
                    exchange="F",
                    start=datetime(2026, 3, 2, 9, 0),
                    end=datetime(2026, 3, 2, 17, 0),
                    resolve_contract=False,
                )
                for letter in ("J", "K", "M", "N")
            ]
            outcomes = master.download_multi(jobs)
            # Snapshot stats antes do exit (master.stop limpa _broker).
            stats_snapshot = master.broker_stats

        # Todos completaram (nenhum exception por SQLITE_BUSY ou similar).
        for o in outcomes:
            assert o.status not in ("exception",), f"Worker exception on {o.symbol}: {o.error}"

        # Broker stats: mutations_applied > 0, errored == 0.
        assert (
            stats_snapshot["mutations_errored"] == 0
        ), f"Broker had errored mutations: {stats_snapshot}"
        assert stats_snapshot["mutations_applied"] >= 4  # at least 1 register_partition per job

        # Catálogo consistente — 4 símbolos distintos, todos com partição.
        for letter in ("J", "K", "M", "N"):
            sym = f"WDO{letter}26"
            parts = catalog.get_completed_partitions(sym, "F")
            assert len(parts) >= 1, f"{sym} sem partição"

    finally:
        catalog.close()


def test_master_idempotent_start_stop(tmp_path: Path, mock_env: None) -> None:
    """master.start() chamado 2x é no-op; master.stop() idempotente."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)

    try:
        master = _build_master(catalog, data_dir, n_workers=1)
        master.start()
        master.start()  # idempotente
        master.stop()
        master.stop()  # idempotente
    finally:
        catalog.close()
