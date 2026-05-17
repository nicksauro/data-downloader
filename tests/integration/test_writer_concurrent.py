"""Integration tests — writer race via threading (Story 4.24 / ADR-026 sect 2.3).

Cobertura (AC11 — minimo 2 tests):

- Test 1: 2 threads escrevendo a MESMA PartitionKey daily; exatamente
  1 sucede, 1 levanta ``ConcurrentWriterError`` apos retries esgotados.
  ``_pending_commits`` limpo no fim; apenas 1 row em ``partitions`` para
  o ``partition_path``.
- Test 2: 2 threads em PartitionKeys DIFERENTES (mesmo simbolo, dias
  diferentes): ambas sucedem; 2 rows em ``partitions``.

Race control: ``threading.Barrier(2)`` garante que ambas threads chegam
ao ponto critico simultaneamente. Timeout 10s em joins/events para
evitar flakes em CI Windows.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from data_downloader.public_api.exceptions import ConcurrentWriterError
from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "_internal" / "catalog.db"


@pytest.fixture
def catalog(db_path: Path, data_dir: Path) -> Catalog:
    return Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )


def _make_trades(n: int, base_ts: int, *, worker_id: int) -> list[TradeRecord]:
    """Trades sinteticos. ``worker_id`` diferencia conteudo entre threads."""
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base_ts + i * 1_000_000,
            timestamp_str="01/03/2024 00:00:00.000",
            price=5_300.0 + worker_id + i,
            quantity=10 + worker_id,
            trade_id=i + worker_id * 10_000,
            trade_type=2,
            buy_agent_id=None,
            sell_agent_id=None,
            flags=0,
            source_callback="history_v2",
            side=None,
            ingestion_ts_ns=base_ts + i * 1_000_000 + 1,
            chunk_id=None,
            dll_version="0.0.0+stub",
            sequence_within_ns=0,
        )
        for i in range(n)
    ]


def _count_pending(cat: Catalog) -> int:
    conn = cat._conn_or_raise()
    return int(conn.execute("SELECT COUNT(*) FROM _pending_commits").fetchone()[0])


# =====================================================================
# AC11 tests
# =====================================================================


@pytest.mark.integration
def test_two_threads_same_partition_one_succeeds_one_raises(
    db_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC11-1: 2 writers em mesma daily -> 1 sucede, 1 ConcurrentWriterError.

    SQLite Connections sao thread-affined; cada thread abre seu proprio
    ``Catalog`` apontando para o mesmo DB file (WAL mode). Isso reproduz
    o cenario real (UI + CLI em processos distintos) sem precisar de
    subprocess.

    **PID-per-thread:** threads do mesmo processo Python compartilham o
    PID, o que faria o WHERE-guard liberar o claim para ambas (caminho
    "same-PID retry idempotente"). Para simular o cenario cross-process
    real, monkeypatch ``os.getpid`` (no modulo catalog) para retornar
    PIDs distintos por thread (via ``threading.local``).

    **Sincronizacao do race:** o barrier sincroniza os starts; um patch
    em ``Catalog._finalize_pending_commit`` introduz uma janela curta
    (await na thread vencedora ate a outra completar seu pending_commit
    inicial). Isso garante que o teste sempre veja a colisao —
    determinismo > randomicidade para CI.
    """
    from data_downloader.storage import catalog as catalog_module

    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3, day=15)
    rel_path = "F/WDOJ26/2026/03/15.parquet"

    # Pre-cria o catalog principal para garantir DB inicializado.
    _bootstrap = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    _bootstrap.close()

    # Per-thread PID via threading.local.
    pid_state = threading.local()
    real_pid = os.getpid()

    def _fake_getpid() -> int:
        return int(getattr(pid_state, "pid", real_pid))

    monkeypatch.setattr(catalog_module.os, "getpid", _fake_getpid)

    # Sincronizacao do race: ambas as threads aguardam neste barrier
    # antes de chamar pending_commit. Apos o claim, a thread vencedora
    # espera por ``loser_done_event`` (no max 5s) antes de finalizar —
    # isso garante que a perdedora teve oportunidade de TENTAR o claim
    # e ver o conflito (Fase 1 INSERT WHERE-guard bloqueia).
    claim_start_barrier = threading.Barrier(2, timeout=10)
    loser_done_event = threading.Event()

    real_finalize = catalog_module.Catalog._finalize_pending_commit

    def _patched_finalize(self: Catalog, handle: object, write_result: object) -> None:
        # Antes de fechar (DELETE pending), aguardamos a perdedora.
        # Timeout 5s — se a perdedora ja propagou erro, evento setado
        # imediatamente; se nao, segue para evitar travar o teste.
        loser_done_event.wait(timeout=5)
        real_finalize(self, handle, write_result)

    monkeypatch.setattr(catalog_module.Catalog, "_finalize_pending_commit", _patched_finalize)

    results: list[BaseException | None] = [None, None]
    base_ts = 1_700_000_000_000_000_000

    def _worker(idx: int) -> None:
        pid_state.pid = 200_000 + idx
        thread_cat = Catalog(
            db_path=db_path,
            data_dir=data_dir,
            auto_reconcile=False,
            auto_cleanup_orphans=False,
        )
        try:
            claim_start_barrier.wait(timeout=5)
            writer.write(
                _make_trades(8, base_ts=base_ts, worker_id=idx),
                partition,
                dll_version="4.0.0.34",
                catalog=thread_cat,
            )
        except BaseException as exc:
            results[idx] = exc
        finally:
            # Sinaliza para a vencedora que pode finalizar.
            loser_done_event.set()
            thread_cat.close()

    t1 = threading.Thread(target=_worker, args=(0,))
    t2 = threading.Thread(target=_worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)
    assert not t1.is_alive(), "thread 0 nao terminou no timeout"
    assert not t2.is_alive(), "thread 1 nao terminou no timeout"

    successes = [r for r in results if r is None]
    errors = [r for r in results if isinstance(r, ConcurrentWriterError)]

    assert len(successes) == 1, f"esperado 1 sucesso e 1 ConcurrentWriterError; results={results}"
    assert len(errors) == 1, f"esperado 1 ConcurrentWriterError; results={results}"

    # Boot novo catalog para inspecionar estado final (sem race).
    cat_final = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    try:
        parts = cat_final.get_completed_partitions("WDOJ26", "F")
        matching = [p for p in parts if p.partition_path == rel_path]
        assert len(matching) == 1, (
            f"esperado 1 row em partitions para {rel_path}; got {[p.partition_path for p in parts]}"
        )

        assert _count_pending(cat_final) == 0

        final_path = data_dir / "history" / rel_path
        assert final_path.exists(), "arquivo final deve ter sido escrito pelo winner"
    finally:
        cat_final.close()


@pytest.mark.integration
def test_two_threads_different_partitions_both_succeed(db_path: Path, data_dir: Path) -> None:
    """AC11-2: 2 writers em dailies diferentes (mesmo simbolo) -> ambos sucedem."""
    writer = ParquetWriter(data_dir=data_dir)
    p15 = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4, day=15)
    p16 = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4, day=16)
    partitions = (p15, p16)

    _bootstrap = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    _bootstrap.close()

    barrier = threading.Barrier(2, timeout=10)
    results: list[BaseException | None] = [None, None]
    base_ts = 1_700_000_000_000_000_000

    def _worker(idx: int) -> None:
        thread_cat = Catalog(
            db_path=db_path,
            data_dir=data_dir,
            auto_reconcile=False,
            auto_cleanup_orphans=False,
        )
        try:
            barrier.wait(timeout=5)
            writer.write(
                _make_trades(6, base_ts=base_ts + idx * 86_400_000_000_000, worker_id=idx),
                partitions[idx],
                dll_version="4.0.0.34",
                catalog=thread_cat,
            )
        except BaseException as exc:
            results[idx] = exc
        finally:
            thread_cat.close()

    t1 = threading.Thread(target=_worker, args=(0,))
    t2 = threading.Thread(target=_worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive(), "threads nao terminaram no timeout"

    assert all(r is None for r in results), f"esperado todos sucessos; results={results}"

    cat_final = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    try:
        parts = cat_final.get_completed_partitions("WDOJ26", "F")
        daily_paths = {p.partition_path for p in parts if p.day is not None}
        assert daily_paths == {
            "F/WDOJ26/2026/04/15.parquet",
            "F/WDOJ26/2026/04/16.parquet",
        }
        assert _count_pending(cat_final) == 0
    finally:
        cat_final.close()
