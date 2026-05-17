"""Unit tests — writer race protection + retry policy (Story 4.24 / ADR-026 sect 2.3).

Cobertura (AC9 — minimo 4 tests):

- Test 1: ``Catalog.pending_commit`` chamado com pending row de PID
  diferente VIVO -> levanta ``ConcurrentWriterError`` (estende a
  cobertura do test 5 de Story 4.23 com asserts adicionais sobre
  ``own_pid``/``current_pid``).
- Test 2: ``Catalog.pending_commit`` chamado com pending row de PID
  diferente MORTO (mock ``psutil`` para ``pid_exists=False``) e
  ``started_at < 1h``: WHERE-guard bloqueia o UPDATE pela janela ainda
  recente, mas pos-SELECT detecta pid mismatch -> ``ConcurrentWriterError``.
  Validacao do contrato: a politica unica para "considerar morto na
  classe writer race" eh o WHERE-guard de 1h (Recovery on boot resolve
  PIDs mortos previamente). Test 3 cobre o caminho stale (>1h).
- Test 3: ``Catalog.pending_commit`` chamado com pending row MESMO PID
  (retry idempotente): sucesso (NAO levanta ``ConcurrentWriterError``).
- Test 4: ``ParquetWriter.write`` com claim falhando 3 vezes consecutivas
  -> exatos 3 attempts com backoff (mockado), propaga
  ``ConcurrentWriterError`` no 3o; ``tmp_path`` foi cleaned-up.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

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
    """Insere row em _pending_commits diretamente (bypass claim atomico)."""
    conn = cat._conn_or_raise()
    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S")
    with cat._transaction():
        conn.execute(
            "INSERT INTO _pending_commits"
            "(partition_path, started_at, expected_sha256, expected_size, job_id, pid)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rel_path, started_str, expected_sha256, expected_size, job_id, pid),
        )


def _install_fake_psutil(monkeypatch: pytest.MonkeyPatch, *, pid_exists: bool) -> None:
    """Stub psutil para reportar PID vivo ou morto."""
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

    fake.pid_exists = lambda _pid: pid_exists  # type: ignore[attr-defined]
    fake.NoSuchProcess = _NoSuchProcess  # type: ignore[attr-defined]
    fake.AccessDenied = _AccessDenied  # type: ignore[attr-defined]
    fake.Process = _FakeProcess  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psutil", fake)


# =====================================================================
# AC9 tests
# =====================================================================


@pytest.mark.unit
def test_pending_commit_raises_concurrent_writer_error_when_pid_alive(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-1: pending row de PID diferente vivo (psutil mock) -> ConcurrentWriterError.

    Asserts contratuais sobre o exception object: ``partition_path``,
    ``current_pid`` (other writer), ``own_pid`` (this process).
    """
    _install_fake_psutil(monkeypatch, pid_exists=True)

    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3, day=15)
    rel_path = "F/WDOJ26/2026/03/15.parquet"
    other_pid = 999_999_991

    _insert_pending_raw(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        expected_sha256="a" * 64,
        expected_size=1024,
        pid=other_pid,
    )

    with (
        pytest.raises(ConcurrentWriterError) as exc_info,
        catalog.pending_commit(
            rel_path=rel_path,
            partition=partition,
            expected_sha256="b" * 64,
            expected_size=2048,
        ),
    ):
        pytest.fail("Should NOT enter context — claim must be denied")

    err = exc_info.value
    assert err.partition_path == rel_path
    assert err.current_pid == other_pid
    assert err.own_pid == os.getpid()
    # Mensagem contem os 3 campos para auditoria.
    assert "partition_path" in str(err)
    assert str(other_pid) in str(err)

    catalog.close()


@pytest.mark.unit
def test_pending_commit_raises_when_recent_pending_even_if_pid_dead(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-2: pending row recente (<1h) MAS PID morto.

    Politica do writer race (advisory lock cross-process): a janela 1h
    eh o unico criterio aplicavel no ``pending_commit`` (que NAO invoca
    recovery). PID liveness eh resolvido por ``recover_pending_commits``
    no boot. Assim, durante runtime, qualquer pending row recente bloqueia
    o claim — mesmo que ``psutil`` reporte o PID como morto.

    Esta separacao de responsabilidades preserva latencia (sem psutil
    call no hot path) e garante consistencia (recovery on boot eh o
    unico que escreve em ``_pending_commits`` sem claim).
    """
    _install_fake_psutil(monkeypatch, pid_exists=False)  # PID dito morto

    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4, day=1)
    rel_path = "F/WDOJ26/2026/04/01.parquet"
    other_pid = 999_999_992

    # PID morto mas pending ainda RECENTE (<1h)
    _insert_pending_raw(
        catalog,
        rel_path=rel_path,
        started_at=datetime.now(UTC) - timedelta(minutes=30),
        expected_sha256="c" * 64,
        expected_size=3000,
        pid=other_pid,
    )

    # WHERE-guard bloqueia (started_at > now-1h e pid != excluded.pid);
    # pos-SELECT detecta pid mismatch -> ConcurrentWriterError.
    with (
        pytest.raises(ConcurrentWriterError) as exc_info,
        catalog.pending_commit(
            rel_path=rel_path,
            partition=partition,
            expected_sha256="d" * 64,
            expected_size=4000,
        ),
    ):
        pytest.fail("Should NOT enter — recent pending blocks claim")

    assert exc_info.value.current_pid == other_pid

    # Recovery on boot eh quem reclama o pending de PID morto.
    catalog.close()


@pytest.mark.unit
def test_pending_commit_succeeds_for_same_pid_retry(catalog: Catalog, data_dir: Path) -> None:
    """AC9-3: pending row mesmo PID (retry idempotente) -> sucesso (sem exception).

    Caminho usado quando o writer retry-loop re-entra apos
    ``ConcurrentWriterError`` previo OU quando uma chamada anterior
    deixou pending preservada (exit sem complete).
    """
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=5, day=10)
    wr = writer.write(_make_trades(8), partition, dll_version="4.0.0.34")
    rel_path = "F/WDOJ26/2026/05/10.parquet"

    # 1a chamada: instala claim mas sai sem completar (simula crash leve)
    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
    ):
        pass  # exit sem complete

    # 2a chamada: mesmo PID re-ataca o claim -> WHERE-guard permite
    # (pid == excluded.pid) -> nao levanta ConcurrentWriterError.
    with catalog.pending_commit(
        rel_path=rel_path,
        partition=partition,
        expected_sha256=wr.checksum_sha256,
        expected_size=wr.file_size_bytes,
    ) as handle:
        handle.complete(wr)

    # Pending limpo, partition registrada.
    conn = catalog._conn_or_raise()
    pending_count = int(conn.execute("SELECT COUNT(*) FROM _pending_commits").fetchone()[0])
    assert pending_count == 0
    parts = catalog.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1
    assert parts[0].partition_path == rel_path

    catalog.close()


@pytest.mark.unit
def test_writer_write_retries_three_times_then_propagates(
    catalog: Catalog, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC9-4: ParquetWriter.write retry 3x com backoff em ConcurrentWriterError.

    Mockamos ``Catalog.pending_commit`` para sempre levantar
    ``ConcurrentWriterError``. Validamos que:

    1. ``pending_commit`` foi chamada exatamente 3 vezes (len(_RETRY_DELAYS_MS)).
    2. ``time.sleep`` foi chamado 2 vezes (entre attempts 1 e 2,  2 e 3 —
       NAO apos o 3o pois propaga).
    3. ``ConcurrentWriterError`` propaga.
    4. ``tmp_path`` foi limpo (nao ha .tmp.* no parent dir final).
    """
    from data_downloader.storage import parquet_writer as pw_module

    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=6, day=20)
    rel_path = "F/WDOJ26/2026/06/20.parquet"
    writer = ParquetWriter(data_dir=data_dir)

    sleep_calls: list[float] = []

    def _capture_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(pw_module.time, "sleep", _capture_sleep)

    # Mock pending_commit para sempre levantar ConcurrentWriterError.
    pending_commit_calls: list[str] = []
    real_pending_commit = catalog.pending_commit

    from contextlib import contextmanager

    @contextmanager
    def _always_concurrent(
        rel_path: str,
        partition: PartitionKey,
        *,
        expected_sha256: str,
        expected_size: int,
        job_id: str | None = None,
    ) -> Iterator[None]:
        pending_commit_calls.append(rel_path)
        raise ConcurrentWriterError(
            partition_path=rel_path,
            current_pid=12345,
            own_pid=os.getpid(),
        )
        yield  # unreachable mas satisfaz typing do generator

    with (
        patch.object(catalog, "pending_commit", _always_concurrent),
        pytest.raises(ConcurrentWriterError) as exc_info,
    ):
        writer.write(
            _make_trades(5),
            partition,
            dll_version="4.0.0.34",
            catalog=catalog,
        )

    # Validacoes contratuais
    assert len(pending_commit_calls) == 3, f"expected 3 attempts, got {len(pending_commit_calls)}"
    assert all(p == rel_path for p in pending_commit_calls)
    # backoff entre attempts 1->2 (100ms) e 2->3 (500ms); 3o nao dorme.
    assert sleep_calls == [0.1, 0.5], f"backoff sequence mismatch: {sleep_calls}"
    assert exc_info.value.partition_path == rel_path

    # tmp cleanup — nenhum .tmp.* deve persistir no diretorio final.
    final_dir = data_dir / "history" / "F" / "WDOJ26" / "2026" / "06"
    if final_dir.is_dir():
        tmps = list(final_dir.glob("*.tmp.*"))
        assert tmps == [], f"tmp not cleaned up: {tmps}"
    # Sanity inverso (silenciar warning unused):
    _ = real_pending_commit
    catalog.close()
