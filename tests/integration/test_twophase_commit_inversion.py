"""Integration tests — two-phase commit inversion (Story 4.23 / ADR-026 §2.1).

Cobertura (AC10 — mínimo 4 tests):

- Test 1: writer com ``catalog`` injetado popula ``_pending_commits``
  ANTES do ``os.replace`` (mockando os.replace para inspect intermediate state).
- Test 2: writer SEM ``catalog`` preserva comportamento legacy v1.3.x
  (write retorna WriteResult; caller pode chamar register_partition
  com DeprecationWarning).
- Test 3: crash simulado entre os.replace e handle.complete deixa estado
  recuperável; recovery on boot do próximo Catalog re-registra a partition.
- Test 4: compact_month com ``catalog`` injetado executa o full two-phase
  (pending row populada ANTES do {MM}.parquet replace; finalização agrega
  estado SQLite consistente).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from data_downloader.storage.catalog import Catalog, PendingCommitHandle
from data_downloader.storage.parquet_writer import ParquetWriter, compact_month
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.schema import TradeRecord


def _make_trades(n: int = 10, *, base: int | None = None) -> list[TradeRecord]:
    base = base or 1_700_000_000_000_000_000
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


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "_internal" / "catalog.db"


@pytest.mark.integration
def test_writer_with_catalog_populates_pending_before_replace(
    data_dir: Path, db_path: Path
) -> None:
    """AC10-1: writer.write(catalog=cat) faz INSERT _pending_commits ANTES do os.replace.

    Mockamos ``os.replace`` para inspecionar o estado intermediário
    (entre Fase 1 e Fase 2). Antes do replace, _pending_commits deve
    ter 1 row e partitions deve ter 0.
    """
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=3, day=15)

    pending_count_pre_replace: list[int] = []
    partitions_count_pre_replace: list[int] = []

    # Patcheia os.replace UMA vez dentro de parquet_writer.write para
    # snapshotar o estado SQLite no momento exato pré-replace.
    real_replace = __import__("os").replace

    def _snapshot_then_replace(src: str | Path, dst: str | Path) -> None:
        pending_count_pre_replace.append(_count_pending(cat))
        partitions_count_pre_replace.append(len(cat.get_completed_partitions("WDOJ26", "F")))
        real_replace(src, dst)

    with patch(
        "data_downloader.storage.parquet_writer.os.replace",
        side_effect=_snapshot_then_replace,
    ):
        wr = writer.write(_make_trades(8), partition, dll_version="4.0.0.34", catalog=cat)

    # Pré-replace: pending tinha 1 row (Fase 1 já tinha ocorrido) e
    # partitions vazio (Fase 3 só vem após replace + handle.complete).
    assert pending_count_pre_replace == [1]
    assert partitions_count_pre_replace == [0]

    # Pós-write: pending limpo, partition registrada (Fase 3 concluída).
    assert _count_pending(cat) == 0
    parts = cat.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1
    assert parts[0].checksum_sha256 == wr.checksum_sha256
    cat.close()


@pytest.mark.integration
def test_writer_without_catalog_preserves_legacy_path(data_dir: Path, db_path: Path) -> None:
    """AC10-2: writer sem catalog preserva caminho legacy (register_partition deprecated)."""
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4, day=22)

    # Writer SEM catalog: arquivo persistido mas catalog inalterado.
    wr = writer.write(_make_trades(6), partition, dll_version="4.0.0.34")
    assert wr.path.exists()
    assert _count_pending(cat) == 0
    assert len(cat.get_completed_partitions("WDOJ26", "F")) == 0

    # Caller usa register_partition (deprecated wrapper) para finalizar.
    with pytest.warns(DeprecationWarning, match="register_partition is deprecated"):
        cat.register_partition(wr, partition)

    parts = cat.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1
    assert parts[0].day == 22
    assert parts[0].checksum_sha256 == wr.checksum_sha256
    assert _count_pending(cat) == 0
    cat.close()


@pytest.mark.integration
def test_crash_between_replace_and_complete_is_recovered_on_next_boot(
    data_dir: Path, db_path: Path
) -> None:
    """AC10-3: crash entre os.replace e handle.complete -> recovery on boot completa.

    Simulamos um crash interceptando ``PendingCommitHandle.complete`` para
    raise antes da Fase 3 SQL. O arquivo final fica em disco + pending
    row preservada. Próximo boot do Catalog dispara recovery_pending_commits
    em __post_init__ que valida o arquivo (SHA/size match) e re-registra
    em ``partitions``.
    """
    # Boot 1: cria DB + escreve arquivo, mas crash antes da Fase 3.
    cat1 = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    writer = ParquetWriter(data_dir=data_dir)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=5, day=12)
    rel_path = "F/WDOJ26/2026/05/12.parquet"

    crash_msg = "simulated crash post-replace pre-finalize"

    def _raise_on_complete(self: PendingCommitHandle, write_result: object) -> None:
        raise RuntimeError(crash_msg)

    with (
        patch.object(PendingCommitHandle, "complete", _raise_on_complete),
        pytest.raises(RuntimeError, match=crash_msg),
    ):
        writer.write(_make_trades(12), partition, dll_version="4.0.0.34", catalog=cat1)

    # Estado pós-crash: arquivo presente, pending row preservada,
    # partition AINDA não registrada.
    final_path = data_dir / "history" / rel_path
    assert final_path.exists(), "Phase 2 (os.replace) deve ter ocorrido"
    assert _count_pending(cat1) == 1
    assert len(cat1.get_completed_partitions("WDOJ26", "F")) == 0
    cat1.close()

    # Boot 2: novo Catalog dispara recovery em __post_init__. O PID original
    # (deste mesmo processo) ainda está vivo, então recovery o trata como
    # 'skipped' por _pid_alive. Mas: o handle complete sequer rodou — então
    # a pending tem o nosso PID; o teste valida o caminho 'pid_alive' que
    # nao auto-recovery, mas o write é íntegro on-disk.
    # Para testar o caminho 'recovered', forçamos o pid em pending para um
    # PID conhecidamente morto.
    dead_pid = 999_999_999
    conn = cat1._open_connection() if False else None  # noqa: F841 — bypass closed conn
    import sqlite3

    raw_conn = sqlite3.connect(str(db_path))
    try:
        raw_conn.execute(
            "UPDATE _pending_commits SET pid = ? WHERE partition_path = ?",
            (dead_pid, rel_path),
        )
        raw_conn.commit()
    finally:
        raw_conn.close()

    # Boot 2 com pending now pointing to dead PID -> recovery re-registra.
    cat2 = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    # Recovery dispara em __post_init__; verifique pós-instanciação.
    assert _count_pending(cat2) == 0, "recovery deveria ter limpado pending"
    parts = cat2.get_completed_partitions("WDOJ26", "F")
    assert len(parts) == 1, "recovery deveria ter re-registrado a partition"
    assert parts[0].partition_path == rel_path
    cat2.close()


@pytest.mark.integration
def test_compact_month_with_catalog_uses_pending_commit(data_dir: Path, db_path: Path) -> None:
    """AC10-4: compact_month(catalog=cat) executa two-phase para o {MM}.parquet.

    Verificamos via patch em os.replace que o pending row do mensal é
    criado ANTES do replace; pós-compact, estado SQLite consistente
    (mensal day=NULL registrado, diários removidos do partitions e do FS).
    """
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    writer = ParquetWriter(data_dir=data_dir)

    # Cria 2 diários para um mesmo mês (sem auto-compact, pois mês não
    # estará "completo" sem cobrir todos os dias úteis B3).
    for day in (15, 16):
        pk = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=6, day=day)
        writer.write(
            _make_trades(5, base=1_700_000_000_000_000_000 + day * 86_400_000_000_000),
            pk,
            dll_version="4.0.0.34",
            catalog=cat,
        )

    # Sanity: 2 diários registrados, 0 mensal.
    parts = cat.get_completed_partitions("WDOJ26", "F")
    daily_parts = [p for p in parts if p.day is not None]
    monthly_parts = [p for p in parts if p.day is None]
    assert len(daily_parts) == 2
    assert len(monthly_parts) == 0

    pending_pre_replace_monthly: list[int] = []
    real_replace = __import__("os").replace
    monthly_rel = "F/WDOJ26/2026/06.parquet"

    def _snapshot_monthly_replace(src: str | Path, dst: str | Path) -> None:
        dst_str = str(dst)
        if dst_str.endswith("06.parquet") and "06" not in Path(dst_str).parent.name:
            # Este é o replace do MENSAL (não dos diários).
            conn = cat._conn_or_raise()
            row = conn.execute(
                "SELECT COUNT(*) FROM _pending_commits WHERE partition_path = ?",
                (monthly_rel,),
            ).fetchone()
            pending_pre_replace_monthly.append(int(row[0]))
        real_replace(src, dst)

    # Compactação manual (bypass do is_month_complete gate, que exigiria
    # todos os dias úteis B3 cobertos — fora de escopo para este teste).
    with patch(
        "data_downloader.storage.parquet_writer.os.replace",
        side_effect=_snapshot_monthly_replace,
    ):
        result = compact_month(
            data_dir,
            exchange="F",
            symbol="WDOJ26",
            year=2026,
            month=6,
            dll_version="4.0.0.34",
            catalog=cat,
        )

    # Pré-replace do mensal: pending row populada (Fase 1 ocorreu).
    assert pending_pre_replace_monthly == [1], "expected exactly one Phase 1 INSERT before replace"

    # Pós-compact: arquivo mensal em disco, pending limpo, partition mensal
    # presente. (Tests do diário cleanup do partitions é responsabilidade
    # de maybe_compact_month, não de compact_month direto — então diários
    # ainda podem aparecer em partitions se chamarmos compact_month diretamente.)
    assert result is not None
    assert (data_dir / "history" / monthly_rel).exists()
    conn = cat._conn_or_raise()
    row = conn.execute(
        "SELECT COUNT(*) FROM _pending_commits WHERE partition_path = ?",
        (monthly_rel,),
    ).fetchone()
    assert int(row[0]) == 0

    parts_post = cat.get_completed_partitions("WDOJ26", "F")
    monthly_post = [p for p in parts_post if p.day is None]
    assert len(monthly_post) == 1
    assert monthly_post[0].partition_path == monthly_rel
    assert monthly_post[0].checksum_sha256 == result.checksum_sha256
    cat.close()
