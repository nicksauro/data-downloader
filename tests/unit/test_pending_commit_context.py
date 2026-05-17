"""Unit tests — Catalog.pending_commit() context manager (Story 4.23 / ADR-026 §2.1).

Cobertura (AC9 — mínimo 6 tests):

- Test 1 (happy path): pending_commit + handle.complete() -> UPSERT em
  partitions + DELETE em _pending_commits.
- Test 2 (exception in block): exception propaga, pending row preservada
  (recovery on boot resolverá).
- Test 3 (forget complete): exit normal sem chamar complete() ->
  warning logado + pending row preservada.
- Test 4 (idempotent retry): pending_commit chamado 2x para mesmo
  partition_path pelo mesmo PID -> claim atualiza (no ConcurrentWriterError).
- Test 5 (concurrent live writer): pending_commit chamado para
  partition_path com pending de PID diferente vivo -> raise
  ConcurrentWriterError.
- Test 6 (stale claim sobrescreve): pending_commit chamado para
  partition_path com pending stale (>1h, mesmo PID indiferente) ->
  claim sobrescreve com sucesso.
- Test 7 (double complete): handle.complete() chamado 2x raise
  RuntimeError.
- Test 8 (deprecated wrapper): register_partition emite
  DeprecationWarning + ainda funciona como esperado.
"""

from __future__ import annotations

import logging
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_downloader.public_api.exceptions import ConcurrentWriterError
from data_downloader.storage.catalog import (
    Catalog,
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


def _count_pending(cat: Catalog) -> int:
    conn = cat._conn_or_raise()
    return int(conn.execute("SELECT COUNT(*) FROM _pending_commits").fetchone()[0])


def _insert_pending_raw(
    cat: Catalog,
    *,
    rel_path: str,
    started_at: datetime,
    expected_sha256: str,
    expected_size: int,
    pid: int,
    job_id: str | None = None,
) -> None:
    """Insere row em _pending_commits diretamente (bypass claim atômico)."""
    conn = cat._conn_or_raise()
    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S")
    with cat._transaction():
        conn.execute(
            "INSERT INTO _pending_commits"
            "(partition_path, started_at, expected_sha256, expected_size, job_id, pid)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rel_path, started_str, expected_sha256, expected_size, job_id, pid),
        )


def _install_fake_psutil_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub psutil para reportar PID vivo (create_time bem antigo)."""
    fake = types.ModuleType("psutil")

    class _NoSuchProcess(Exception):  # noqa: N818
        pass

    class _AccessDenied(Exception):  # noqa: N818
        pass

    class _FakeProcess:
        def __init__(self, _pid: int) -> None:
            pass

        def create_time(self) -> float:
            return 0.0  # epoch — sempre ANTES de started_at

    fake.pid_exists = lambda _pid: True  # type: ignore[attr-defined]
    fake.NoSuchProcess = _NoSuchProcess  # type: ignore[attr-defined]
    fake.AccessDenied = _AccessDenied  # type: ignore[attr-defined]
    fake.Process = _FakeProcess  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psutil", fake)


# =====================================================================
# AC9 tests
# =====================================================================


@pytest.mark.unit
def test_pending_commit_happy_path_upserts_and_deletes_pending(
    catalog: Catalog, data_dir: Path
) -> None:
    """AC9-1: handle.complete() faz UPSERT em partitions + DELETE pending."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3, day=15)
    wr = writer.write(_make_trades(10), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/03/15.parquet"

    # Reset pending (writer sem catalog não cria, mas garante)
    assert _count_pending(catalog) == 0

    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
    ) as handle:
        # Fase 1 -> pending populado
        assert _count_pending(catalog) == 1
        assert handle._completed is False
        # Simula o caller fazendo os.replace + complete
        handle.complete(wr)
        assert handle._completed is True

    # Fase 3 finalizada -> pending limpo, partition registrada
    assert _count_pending(catalog) == 0
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1
    assert parts[0].partition_path == rel_path
    assert parts[0].day == 15
    assert parts[0].checksum_sha256 == wr.checksum_sha256
    catalog.close()


@pytest.mark.unit
def test_pending_commit_preserves_pending_when_block_raises(
    catalog: Catalog, data_dir: Path
) -> None:
    """AC9-2: exception no bloco -> pending preservada (recovery on boot trata)."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4, day=1)
    rel_path = "F/WDOJ26/2026/04/01.parquet"

    with (
        pytest.raises(RuntimeError, match="simulated"),
        catalog.pending_commit(
            rel_path=rel_path,
            partition=partition,
            expected_sha256="a" * 64,
            expected_size=1024,
        ),
    ):
        assert _count_pending(catalog) == 1
        raise RuntimeError("simulated crash mid-write")

    # Pending preservada — handle NÃO foi completado.
    assert _count_pending(catalog) == 1
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 0
    catalog.close()


@pytest.mark.unit
def test_pending_commit_warns_when_exit_without_complete(
    catalog: Catalog, caplog: pytest.LogCaptureFixture
) -> None:
    """AC9-3: exit normal sem complete() -> warning + pending preservada."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=5, day=10)
    rel_path = "F/WDOJ26/2026/05/10.parquet"

    with (
        caplog.at_level(logging.WARNING, logger="data_downloader.storage.catalog"),
        catalog.pending_commit(
            rel_path=rel_path,
            partition=partition,
            expected_sha256="b" * 64,
            expected_size=2048,
        ),
    ):
        pass  # caller esqueceu de chamar complete()

    # Warning emitido + pending preservada (recovery on boot resolve).
    assert any("pending_commit.not_completed" in record.message for record in caplog.records)
    assert _count_pending(catalog) == 1
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 0
    catalog.close()


@pytest.mark.unit
def test_pending_commit_idempotent_for_same_pid(catalog: Catalog) -> None:
    """AC9-4: 2 chamadas pendentes pelo mesmo PID -> claim atualiza (sem ConcurrentWriterError)."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=6, day=20)
    rel_path = "F/WDOJ26/2026/06/20.parquet"

    # 1ª chamada: instala claim
    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256="c" * 64,
        expected_size=3000,
    ) as _h1:
        # Saímos sem completar -> pending preservada
        pass

    assert _count_pending(catalog) == 1

    # 2ª chamada (mesmo PID): WHERE-guarded UPSERT permite sobrescrever
    # quando pid == excluded.pid (retry idempotente).
    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256="d" * 64,  # SHA novo
        expected_size=4000,
    ) as h2:
        # Claim sobrescrito; ainda 1 pending (mesmo path)
        assert _count_pending(catalog) == 1
        # Sanity: o SHA novo está em pending agora
        conn = catalog._conn_or_raise()
        row = conn.execute(
            "SELECT expected_sha256 FROM _pending_commits WHERE partition_path = ?",
            (rel_path,),
        ).fetchone()
        assert row["expected_sha256"] == "d" * 64
        # Não completa: deixamos pending para inspeção
        _ = h2

    assert _count_pending(catalog) == 1
    catalog.close()


@pytest.mark.unit
def test_pending_commit_raises_when_concurrent_writer_alive(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-5: PID diferente vivo + dentro da janela 1h -> ConcurrentWriterError."""
    _install_fake_psutil_alive(monkeypatch)

    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=7, day=5)
    rel_path = "F/WDOJ26/2026/07/05.parquet"

    # Injeta pending row com PID diferente do nosso, recente.
    other_pid = 999_999_991  # PID que não somos (mas fake_psutil diz vivo)
    _insert_pending_raw(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        expected_sha256="e" * 64,
        expected_size=5000,
        pid=other_pid,
    )

    # WHERE-guarded UPSERT bloqueia (started_at > now-1h E pid != excluded.pid):
    # row permanece com other_pid; post-SELECT detecta pid mismatch ->
    # ConcurrentWriterError.
    with (
        pytest.raises(ConcurrentWriterError) as exc_info,
        catalog.pending_commit(
            rel_path=rel_path,
            partition=partition,
            expected_sha256="f" * 64,
            expected_size=6000,
        ),
    ):
        pytest.fail("Should not enter the with block — claim must fail")

    assert exc_info.value.partition_path == rel_path
    assert exc_info.value.current_pid == other_pid
    # Pending original NÃO foi sobrescrita
    conn = catalog._conn_or_raise()
    row = conn.execute(
        "SELECT pid, expected_sha256 FROM _pending_commits WHERE partition_path = ?",
        (rel_path,),
    ).fetchone()
    assert int(row["pid"]) == other_pid
    assert row["expected_sha256"] == "e" * 64
    catalog.close()


@pytest.mark.unit
def test_pending_commit_overrides_stale_claim(catalog: Catalog) -> None:
    """AC9-6: pending stale (>1h) -> claim sobrescreve com sucesso."""
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=8, day=2)
    rel_path = "F/WDOJ26/2026/08/02.parquet"

    # Injeta pending row stale (3h atrás) com PID diferente.
    other_pid = 999_999_992
    _insert_pending_raw(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(hours=3),
        expected_sha256="g" * 64,
        expected_size=7000,
        pid=other_pid,
    )

    # WHERE-guarded UPSERT autoriza (started_at < now-1h) -> sobrescreve.
    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256="h" * 64,
        expected_size=8000,
    ) as handle:
        # Claim sucedeu: nosso PID está na row.
        conn = catalog._conn_or_raise()
        row = conn.execute(
            "SELECT pid, expected_sha256 FROM _pending_commits WHERE partition_path = ?",
            (rel_path,),
        ).fetchone()
        import os

        assert int(row["pid"]) == os.getpid()
        assert row["expected_sha256"] == "h" * 64
        # Não completa: validamos só o claim
        _ = handle

    catalog.close()


@pytest.mark.unit
def test_handle_complete_blocks_second_invocation(catalog: Catalog, data_dir: Path) -> None:
    """AC9-7: handle.complete() chamado 2x -> RuntimeError."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=9, day=11)
    wr = writer.write(_make_trades(3), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/09/11.parquet"

    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
    ) as handle:
        handle.complete(wr)
        with pytest.raises(RuntimeError, match="already invoked"):
            handle.complete(wr)

    catalog.close()


@pytest.mark.unit
def test_register_partition_emits_deprecation_warning(catalog: Catalog, data_dir: Path) -> None:
    """AC9-8: register_partition emite DeprecationWarning mas ainda funciona."""
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=10, day=8)
    wr = writer.write(_make_trades(5), partition, dll_version="4.0.0.34")

    with pytest.warns(DeprecationWarning, match="register_partition is deprecated"):
        catalog.register_partition(wr, partition)

    # Comportamento preservado: partition registrada, pending limpo.
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1
    assert parts[0].day == 8
    assert _count_pending(catalog) == 0
    catalog.close()
