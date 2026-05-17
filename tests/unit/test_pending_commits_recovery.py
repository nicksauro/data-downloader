"""Unit tests — storage.catalog recovery on boot (Story 4.22 / ADR-026 §2.2).

Cobertura:

- Test 1: ``_pid_alive`` com psutil mockado (pid_exists=True + create<started) -> True.
- Test 2: ``_pid_alive`` com pid_exists=False -> False.
- Test 3: ``_pid_alive`` PID reciclado (create_time>started_at) -> False.
- Test 4: ``_pid_alive`` fallback timestamp (ImportError) + started_at recente -> True.
- Test 5: ``_pid_alive`` pid=None -> False.
- Test 6: ``recover_pending_commits`` row com pid morto + arquivo ausente -> ``cleaned``.
- Test 7: ``recover_pending_commits`` row com pid morto + sha match -> ``recovered``.
- Test 8: ``recover_pending_commits`` row com sha mismatch -> ``quarantined`` +
  arquivo movido para data/_quarantine/.
- Test 9: ``recover_pending_commits`` row com pid vivo -> ``skipped``.
- Test 10: ``recover_pending_commits`` em DB sem rows pendentes -> report limpo.
"""

from __future__ import annotations

import sqlite3
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from data_downloader.storage.catalog import (
    Catalog,
    PendingRecoveryReport,
    _pid_alive,
)
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


def _make_trades(n: int = 5) -> list[TradeRecord]:
    base = 1_700_000_000_000_000_000
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base + i * 1_000_000,
            timestamp_str="01/03/2024 00:00:00.000",
            price=5_300.0 + i,
            quantity=10,
            trade_id=i,
            trade_type=2,
            buy_agent_id=None,
            sell_agent_id=None,
            flags=0,
            source_callback="history_v2",
            side=None,
            ingestion_ts_ns=base + i * 1_000_000 + 1,
            chunk_id=None,
            dll_version="0.0.0+stub",
            sequence_within_ns=0,
        )
        for i in range(n)
    ]


def _insert_pending(
    cat: Catalog,
    *,
    rel_path: str,
    started_at: datetime,
    expected_sha256: str,
    expected_size: int,
    pid: int,
    job_id: str | None = None,
) -> None:
    """Helper: insere uma row em _pending_commits diretamente."""
    conn = cat._conn_or_raise()
    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S.%f")
    with cat._transaction():
        conn.execute(
            "INSERT INTO _pending_commits"
            "(partition_path, started_at, expected_sha256, expected_size, job_id, pid)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rel_path, started_str, expected_sha256, expected_size, job_id, pid),
        )


def _count_pending(cat: Catalog) -> int:
    conn = cat._conn_or_raise()
    return int(conn.execute("SELECT COUNT(*) FROM _pending_commits").fetchone()[0])


# =====================================================================
# AC2 — _pid_alive tests
# =====================================================================


class _FakeProcess:
    """Stub minimo para psutil.Process — retorna create_time controlado."""

    def __init__(self, create_time_epoch: float) -> None:
        self._ct = create_time_epoch

    def create_time(self) -> float:
        return self._ct


def _install_fake_psutil(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exists: bool,
    create_time_epoch: float,
) -> None:
    """Substitui psutil em sys.modules por um stub controlado.

    As classes _NoSuchProcess/_AccessDenied imitam o naming do psutil
    real (sem suffix Error) — noqa local justifica a divergencia.
    """
    fake = types.ModuleType("psutil")

    class _NoSuchProcess(Exception):  # noqa: N818  — espelha API psutil
        pass

    class _AccessDenied(Exception):  # noqa: N818  — espelha API psutil
        pass

    fake.pid_exists = lambda _pid: exists  # type: ignore[attr-defined]
    fake.NoSuchProcess = _NoSuchProcess  # type: ignore[attr-defined]
    fake.AccessDenied = _AccessDenied  # type: ignore[attr-defined]
    fake.Process = lambda _pid: _FakeProcess(create_time_epoch)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psutil", fake)


def _block_psutil_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ImportError quando _pid_alive tentar importar psutil."""

    real_import = (
        __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
    )

    def _import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "psutil":
            raise ImportError("psutil blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _import)
    # Garante que cache de modulo nao curto-circuite o import.
    monkeypatch.delitem(sys.modules, "psutil", raising=False)


@pytest.mark.unit
def test_pid_alive_returns_true_when_process_exists_and_created_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9-1: pid_exists=True + create_time<started_at -> True."""
    started_at = datetime.now(UTC) - timedelta(minutes=5)
    # create_time epoch ANTES de started_at (processo legitimamente vivo).
    create_time = (started_at - timedelta(seconds=10)).timestamp()
    _install_fake_psutil(monkeypatch, exists=True, create_time_epoch=create_time)
    assert _pid_alive(12345, started_at) is True


@pytest.mark.unit
def test_pid_alive_returns_false_when_process_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9-2: pid_exists=False -> False (PID nao existe)."""
    _install_fake_psutil(monkeypatch, exists=False, create_time_epoch=0.0)
    started_at = datetime.now(UTC) - timedelta(minutes=5)
    assert _pid_alive(99999, started_at) is False


@pytest.mark.unit
def test_pid_alive_detects_pid_recycling(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC9-3: create_time > started_at -> PID reciclado, retorna False."""
    started_at = datetime.now(UTC) - timedelta(minutes=10)
    # create_time DEPOIS de started_at — processo diferente herdou o PID.
    create_time = (started_at + timedelta(minutes=5)).timestamp()
    _install_fake_psutil(monkeypatch, exists=True, create_time_epoch=create_time)
    assert _pid_alive(12345, started_at) is False


@pytest.mark.unit
def test_pid_alive_fallback_uses_recent_started_at_when_psutil_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9-4: ImportError + started_at < 1h atras -> True (fallback timestamp)."""
    _block_psutil_import(monkeypatch)
    recent = datetime.now(UTC) - timedelta(minutes=10)
    assert _pid_alive(12345, recent) is True

    old = datetime.now(UTC) - timedelta(hours=2)
    assert _pid_alive(12345, old) is False


@pytest.mark.unit
def test_pid_alive_returns_false_for_none_pid() -> None:
    """AC9-5: pid=None -> False (defensivo, nao tem dono)."""
    assert _pid_alive(None, datetime.now(UTC)) is False


# =====================================================================
# AC3 — recover_pending_commits resolution table
# =====================================================================


@pytest.mark.unit
def test_recover_pending_with_missing_file_marks_cleaned(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-6: PID morto + arquivo ausente -> cleaned (no_file) + pending deletado."""
    _install_fake_psutil(monkeypatch, exists=False, create_time_epoch=0.0)
    rel_path = "F/WDOJ26/2026/03.parquet"
    _insert_pending(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256="a" * 64,
        expected_size=1024,
        pid=99999,
    )

    report = catalog.recover_pending_commits()

    assert isinstance(report, PendingRecoveryReport)
    assert (rel_path, "no_file") in report.cleaned
    assert report.recovered == ()
    assert report.quarantined == ()
    assert _count_pending(catalog) == 0
    catalog.close()


@pytest.mark.unit
def test_recover_pending_with_matching_file_marks_recovered(
    catalog: Catalog, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-7: PID morto + sha/size match -> recovered + UPSERT em partitions."""
    _install_fake_psutil(monkeypatch, exists=False, create_time_epoch=0.0)
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    wr = writer.write(_make_trades(10), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/03.parquet"

    _insert_pending(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
        pid=99999,
    )

    report = catalog.recover_pending_commits()
    assert rel_path in report.recovered
    assert report.cleaned == ()
    assert report.quarantined == ()
    assert _count_pending(catalog) == 0

    completed = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(completed) == 1
    assert completed[0].partition_path == rel_path
    assert completed[0].checksum_sha256 == wr.checksum_sha256
    catalog.close()


@pytest.mark.unit
def test_recover_pending_with_sha_mismatch_quarantines_file(
    catalog: Catalog, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-8: PID morto + sha mismatch -> quarantined + arquivo movido."""
    _install_fake_psutil(monkeypatch, exists=False, create_time_epoch=0.0)
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    wr = writer.write(_make_trades(8), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/03.parquet"

    # SHA esperado diferente do real -> mismatch.
    _insert_pending(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256="b" * 64,  # mismatch deliberado
        expected_size=wr.file_size_bytes,
        pid=99999,
    )

    report = catalog.recover_pending_commits()
    assert (rel_path, "sha_mismatch") in report.quarantined
    assert report.recovered == ()
    assert report.cleaned == ()
    assert _count_pending(catalog) == 0
    # Arquivo original removido.
    assert not wr.path.exists()
    # Arquivo movido para quarantine.
    quarantine_root = data_dir / "_quarantine"
    assert quarantine_root.is_dir()
    moved_files = list(quarantine_root.rglob("03.parquet"))
    assert len(moved_files) == 1
    catalog.close()


@pytest.mark.unit
def test_recover_pending_with_live_pid_skips_row(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-9: PID vivo -> skipped (nao toca a row)."""
    started_at = datetime.now(UTC) - timedelta(minutes=2)
    create_time = (started_at - timedelta(seconds=30)).timestamp()
    _install_fake_psutil(monkeypatch, exists=True, create_time_epoch=create_time)
    rel_path = "F/WDOJ26/2026/03.parquet"
    _insert_pending(
        catalog,
        rel_path=rel_path,
        started_at=started_at,
        expected_sha256="c" * 64,
        expected_size=2048,
        pid=12345,
    )

    report = catalog.recover_pending_commits()
    assert (rel_path, "pid_alive") in report.skipped
    assert report.recovered == ()
    assert report.cleaned == ()
    assert report.quarantined == ()
    # Pending row preservada (PID vivo).
    assert _count_pending(catalog) == 1
    catalog.close()


@pytest.mark.unit
def test_recover_pending_empty_table_returns_clean_report(
    catalog: Catalog,
) -> None:
    """AC9-10: tabela vazia -> report is_clean True, nada a fazer."""
    report = catalog.recover_pending_commits()
    assert report.is_clean is True
    assert report.recovered == ()
    assert report.cleaned == ()
    assert report.quarantined == ()
    assert report.skipped == ()
    catalog.close()


@pytest.mark.unit
def test_dry_run_recovery_does_not_mutate(
    catalog: Catalog, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bonus: dry_run_recovery_pending classifica mas NAO aplica mutacoes."""
    _install_fake_psutil(monkeypatch, exists=False, create_time_epoch=0.0)
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    wr = writer.write(_make_trades(5), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/03.parquet"

    _insert_pending(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
        pid=99999,
    )

    report = catalog.dry_run_recovery_pending()
    assert rel_path in report.recovered
    # Sem mutacoes: pending ainda existe, partitions sem entry.
    assert _count_pending(catalog) == 1
    assert list(catalog.get_completed_partitions("WDOJ26", "F")) == []
    catalog.close()


@pytest.mark.unit
def test_recover_handles_missing_pending_commits_table(tmp_path: Path) -> None:
    """Bonus: DB sem migrations aplicadas (sem _pending_commits) -> report vazio."""
    db_path = tmp_path / "raw.db"
    # Cria DB minimal sem schema.
    conn = sqlite3.connect(str(db_path))
    conn.close()

    catalog = Catalog(
        db_path=db_path,
        data_dir=tmp_path / "data",
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    # Drop a tabela manualmente para simular DB pre-migration.
    raw = catalog._conn_or_raise()
    raw.execute("DROP TABLE _pending_commits")
    report = catalog.recover_pending_commits()
    assert report.is_clean
    catalog.close()


@pytest.mark.unit
def test_quarantine_cross_fs_fallback_uses_shutil_move(
    catalog: Catalog, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC15 (Story 4.24, fecha 4.22 CONCERN 1): cross-FS quarantine usa shutil.move.

    Quando ``os.replace`` falha com ``OSError(EXDEV)`` (cross-volume no
    Windows), o fallback ``shutil.move`` eh acionado. O arquivo ainda
    eh quarentenado e a pending row deletada.
    """
    import errno
    import shutil

    from data_downloader.storage import catalog as catalog_module

    _install_fake_psutil(monkeypatch, exists=False, create_time_epoch=0.0)
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)
    wr = writer.write(_make_trades(6), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/04.parquet"

    # SHA mismatch -> branch de quarantine.
    _insert_pending(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256="z" * 64,
        expected_size=wr.file_size_bytes,
        pid=99999,
    )

    # Mock os.replace (apenas no modulo catalog) para raise EXDEV.
    real_replace = catalog_module.os.replace
    replace_calls: list[tuple[str, str]] = []
    move_calls: list[tuple[str, str]] = []

    def _failing_replace(src: str | Path, dst: str | Path) -> None:
        replace_calls.append((str(src), str(dst)))
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    real_move = shutil.move

    def _spy_move(src: str, dst: str) -> str:
        move_calls.append((src, dst))
        # Delegamos para o real, porque o teste eh integration-light: o
        # objetivo eh validar que shutil.move foi acionado, nao testar
        # implementacao do shutil.
        return real_move(src, dst)

    monkeypatch.setattr(catalog_module.os, "replace", _failing_replace)
    monkeypatch.setattr(catalog_module.shutil, "move", _spy_move)

    report = catalog.recover_pending_commits()

    # os.replace falhou (EXDEV), shutil.move foi acionado.
    assert len(replace_calls) >= 1, "os.replace deveria ter sido tentado primeiro"
    assert len(move_calls) >= 1, "shutil.move deveria ter sido chamado no fallback"

    # Quarantine reportado, pending limpa.
    assert (rel_path, "sha_mismatch") in report.quarantined
    assert _count_pending(catalog) == 0

    # Arquivo original removido + arquivo em quarantine.
    assert not wr.path.exists()
    quarantine_root = data_dir / "_quarantine"
    assert quarantine_root.is_dir()
    moved_files = list(quarantine_root.rglob("04.parquet"))
    assert len(moved_files) == 1

    # Limpar mock para nao vazar para outros tests.
    monkeypatch.setattr(catalog_module.os, "replace", real_replace)
    catalog.close()
