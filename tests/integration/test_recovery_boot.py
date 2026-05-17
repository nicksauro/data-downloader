"""Integration tests — recovery on boot (Story 4.22 / ADR-026 §2.2).

Cobertura:

- Test 1: pending row + arquivo valido on-disk -> boot do Catalog
  registra partition + limpa pending.
- Test 2: pending row + arquivo corrompido (sha mismatch) -> boot
  cria quarantine + limpa pending.
- Test 3: smoke CLI — invoca ``data-downloader catalog recover-pending
  --dry-run`` via subprocess e valida exit code 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord


def _make_trades(n: int = 10) -> list[TradeRecord]:
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


def _insert_pending_raw(
    db_path: Path,
    *,
    rel_path: str,
    started_at: datetime,
    expected_sha256: str,
    expected_size: int,
    pid: int,
) -> None:
    """Insere uma row em _pending_commits via conexao SQLite direta.

    Util quando queremos preparar o estado ANTES de instanciar o Catalog
    que vai disparar recovery em __post_init__.
    """
    import sqlite3

    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S.%f")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO _pending_commits"
            "(partition_path, started_at, expected_sha256, expected_size, job_id, pid)"
            " VALUES (?, ?, ?, ?, NULL, ?)",
            (rel_path, started_str, expected_sha256, expected_size, pid),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "_internal" / "catalog.db"


@pytest.mark.integration
def test_recovery_on_boot_registers_partition_when_file_matches(
    data_dir: Path, db_path: Path
) -> None:
    """AC10-1: arquivo + pending preparados; novo Catalog (boot) recupera."""
    # 1. Bootstrap inicial — cria DB + schema.
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )

    # 2. Escreve um Parquet real via writer (sem registrar em partitions).
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    wr = writer.write(_make_trades(15), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/03.parquet"
    cat.close()

    # 3. Insere pending row com PID inexistente + sha/size validos.
    dead_pid = 999_999_999  # extremamente improvavel de existir
    _insert_pending_raw(
        db_path,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
        pid=dead_pid,
    )

    # 4. Boot novo Catalog -> __post_init__ chama recover_pending_commits.
    cat2 = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    completed = cat2.get_completed_partitions("WDOJ26", "F")
    assert len(completed) == 1, "partition deveria ter sido re-registrada no boot"
    assert completed[0].partition_path == rel_path
    assert completed[0].checksum_sha256 == wr.checksum_sha256

    # Pending row deve ter sido removida.
    conn = cat2._conn_or_raise()
    pending_count = conn.execute("SELECT COUNT(*) FROM _pending_commits").fetchone()[0]
    assert pending_count == 0
    cat2.close()


@pytest.mark.integration
def test_recovery_on_boot_quarantines_corrupted_file(data_dir: Path, db_path: Path) -> None:
    """AC10-2: arquivo corrompido (sha mismatch); boot move para _quarantine/."""
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )

    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3)
    wr = writer.write(_make_trades(12), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/03.parquet"
    cat.close()

    # SHA esperado deliberadamente errado -> recovery deve quarentenar.
    dead_pid = 999_999_999
    _insert_pending_raw(
        db_path,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        expected_sha256="0" * 64,
        expected_size=wr.file_size_bytes,
        pid=dead_pid,
    )

    cat2 = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    # Arquivo original removido.
    assert not wr.path.exists()
    # Arquivo movido para _quarantine/.
    quarantine_root = data_dir / "_quarantine"
    assert quarantine_root.is_dir()
    moved = list(quarantine_root.rglob("03.parquet"))
    assert len(moved) == 1
    # Pending limpo.
    conn = cat2._conn_or_raise()
    pending_count = conn.execute("SELECT COUNT(*) FROM _pending_commits").fetchone()[0]
    assert pending_count == 0
    cat2.close()


@pytest.mark.integration
def test_cli_recover_pending_dry_run_returns_zero(tmp_path: Path) -> None:
    """AC10-3: smoke CLI — exit code 0 em DB limpo via subprocess."""
    data_dir = tmp_path / "data"
    # Cria DB minimal (boot vazio) para o CLI ter algo para abrir.
    db_path = data_dir / "_internal" / "catalog.db"
    Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    ).close()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "data_downloader.cli",
            "catalog",
            "recover-pending",
            "--dry-run",
            "--data-dir",
            str(data_dir),
        ],
        check=False,
        capture_output=True,
        env=env,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, (
        f"recover-pending --dry-run deveria sair 0; "
        f"got {result.returncode}, stderr={result.stderr[-500:]}"
    )
    # Stdout deve conter algum sinal de execucao (tabela rich ou panel).
    combined = (result.stdout or "") + (result.stderr or "")
    assert "recover" in combined.lower() or "clean" in combined.lower()
