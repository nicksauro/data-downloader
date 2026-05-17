"""Integration tests — compact single-flight via threading (Story 4.24 / ADR-026 sect 2.4).

Cobertura (AC12 — minimo 2 tests):

- Test 1: 2 threads chamando ``maybe_compact_month`` para mesmo
  ``(symbol, year, month)`` simultaneamente. Validamos que apenas 1
  thread retorna ``True`` (compactou) e outra retorna ``False`` (claim
  perdido). Apenas 1 ``os.replace`` ocorre no ``MM.parquet`` (assert via
  spy patch). Estado final: ``MM.parquet`` existe, diarios deletados,
  ``partitions`` tem 1 row mensal.
- Test 2 (sugestao opcional do squad): teste E2E via ``maybe_compact_
  month`` em concorrencia exercitando o pipeline COMPLETO (writer +
  compact). Confirma que o claim atomico cobre o caminho ponta-a-ponta.

Race control: ``threading.Barrier(2)`` para sincronizar starts; cada
thread tem seu proprio ``Catalog`` (SQLite Connections sao thread-
affined). Timeout 10-15s em joins/events para evitar flakes em CI
Windows.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

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


def _make_trades(n: int, base_ts: int) -> list[TradeRecord]:
    return [
        TradeRecord(
            symbol="WDOJ26",
            exchange="F",
            timestamp_ns=base_ts + i * 1_000_000,
            timestamp_str="01/03/2024 00:00:00.000",
            price=5_300.0 + (i % 100) * 0.1,
            quantity=10 + (i % 50),
            trade_id=i,
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


def _seed_dailies(
    catalog: Catalog, writer: ParquetWriter, *, year: int, month: int, days: list[int]
) -> None:
    base_day_ns = 1_700_000_000_000_000_000
    for day in days:
        pk = PartitionKey(exchange="F", symbol="WDOJ26", year=year, month=month, day=day)
        writer.write(
            _make_trades(5, base_ts=base_day_ns + day * 86_400_000_000_000),
            pk,
            dll_version="4.0.0.34",
            catalog=catalog,
        )


# =====================================================================
# AC12 tests
# =====================================================================


@pytest.mark.integration
def test_two_threads_same_month_one_compacts_one_noops(
    catalog: Catalog, db_path: Path, data_dir: Path
) -> None:
    """AC12-1: 2 threads em maybe_compact_month -> 1 True, 1 False, 1 compact mensal.

    Setup: 2 diarios em WDOJ26/2026/03/ + is_month_complete mockado True
    (per-thread, pois cada thread abre seu proprio Catalog).

    Validamos:
    - Exatamente 1 thread retorna ``True`` (compactou), 1 retorna
      ``False`` (claim perdido).
    - ``compact_month`` foi chamada exatamente 1 vez (single-flight).
    - Apos: ``MM.parquet`` existe; diarios deletados do FS; catalog tem
      1 row mensal (day=None) e 0 diarias.

    Sincronizacao do race: o ``compact_month`` da thread vencedora eh
    patcheado para aguardar ``loser_done_event`` antes de retornar.
    Isso garante que a perdedora teve oportunidade de tentar o claim
    (e perder) ANTES que a vencedora finalize ``completed_at``.
    """
    from data_downloader.storage import parquet_writer as pw_module

    writer = ParquetWriter(data_dir=data_dir)
    _seed_dailies(catalog, writer, year=2026, month=3, days=[15, 16])
    catalog.close()  # Libera lock antes do race (per-thread catalogs assumem WAL).

    monthly_rel = "F/WDOJ26/2026/03.parquet"
    monthly_path = data_dir / "history" / monthly_rel

    # Patch compact_month para (a) sustentar o claim ate a perdedora
    # terminar (race deterministico) e (b) contar invocations.
    real_compact_month = pw_module.compact_month
    loser_done_event = threading.Event()
    compact_invocations: list[str] = []
    compact_lock = threading.Lock()

    def _patched_compact_month(*args: object, **kwargs: object) -> object:
        with compact_lock:
            compact_invocations.append("called")
        # Executa o real, depois aguarda o sinal (timeout 5s).
        result = real_compact_month(*args, **kwargs)
        loser_done_event.wait(timeout=5)
        return result

    barrier = threading.Barrier(2, timeout=10)
    results: list[BaseException | bool | None] = [None, None]

    def _worker(idx: int) -> None:
        thread_cat = Catalog(
            db_path=db_path,
            data_dir=data_dir,
            auto_reconcile=False,
            auto_cleanup_orphans=False,
        )
        try:
            with (
                patch.object(thread_cat, "is_month_complete", return_value=True),
                patch(
                    "data_downloader.storage.parquet_writer.compact_month",
                    side_effect=_patched_compact_month,
                ),
            ):
                barrier.wait(timeout=5)
                results[idx] = thread_cat.maybe_compact_month(
                    "WDOJ26", "F", 2026, 3, dll_version="4.0.0.34"
                )
        except BaseException as exc:
            results[idx] = exc
        finally:
            # Sinaliza para a vencedora poder finalizar.
            loser_done_event.set()
            thread_cat.close()

    t1 = threading.Thread(target=_worker, args=(0,))
    t2 = threading.Thread(target=_worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)
    assert not t1.is_alive() and not t2.is_alive()

    # Sem excecoes.
    for r in results:
        assert not isinstance(r, BaseException), f"thread raised: {r!r}"

    # 1 True, 1 False (single-flight).
    bool_results = [r for r in results if isinstance(r, bool)]
    assert sorted(bool_results) == [False, True], f"results={results}"

    # Apenas 1 compact_month executou (single-flight).
    assert len(compact_invocations) == 1, (
        f"esperado 1 compact_month invocation (single-flight); "
        f"got {len(compact_invocations)}: {compact_invocations}"
    )

    # Mensal existe, diarios deletados.
    assert monthly_path.exists(), "MM.parquet deve existir pos-compact"
    month_dir = monthly_path.with_suffix("")
    if month_dir.is_dir():
        remaining_dailies = list(month_dir.glob("*.parquet"))
        assert remaining_dailies == [], (
            f"diarios deveriam ter sido deletados; got {remaining_dailies}"
        )

    # Catalog: 1 row mensal (day=None), 0 diarios.
    cat_final = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    try:
        parts = cat_final.get_completed_partitions("WDOJ26", "F")
        monthly_parts = [p for p in parts if p.day is None]
        daily_parts = [p for p in parts if p.day is not None]
        assert len(monthly_parts) == 1, (
            f"esperado 1 row mensal; got {[p.partition_path for p in monthly_parts]}"
        )
        assert daily_parts == [], (
            f"diarios deveriam ter sido removidos do catalog; "
            f"got {[p.partition_path for p in daily_parts]}"
        )
    finally:
        cat_final.close()


@pytest.mark.integration
def test_two_threads_end_to_end_maybe_compact_month_safe(
    catalog: Catalog, db_path: Path, data_dir: Path
) -> None:
    """AC12-2: E2E maybe_compact_month sob concorrencia preserva integridade.

    Variante do test 1 com setup ligeiramente diferente (mes 4, 3
    diarios) — exercita o pipeline completo (claim + compact_month +
    UPSERT mensal + DELETE diarios + UPDATE completed_at) sob race.
    """
    from data_downloader.storage import parquet_writer as pw_module

    writer = ParquetWriter(data_dir=data_dir)
    _seed_dailies(catalog, writer, year=2026, month=4, days=[10, 11, 12])
    catalog.close()

    monthly_rel = "F/WDOJ26/2026/04.parquet"
    monthly_path = data_dir / "history" / monthly_rel

    # Sustenta o claim ate a perdedora terminar (single-flight test).
    real_compact_month = pw_module.compact_month
    loser_done_event = threading.Event()

    def _patched_compact_month(*args: object, **kwargs: object) -> object:
        result = real_compact_month(*args, **kwargs)
        loser_done_event.wait(timeout=5)
        return result

    barrier = threading.Barrier(2, timeout=10)
    results: list[BaseException | bool | None] = [None, None]

    def _worker(idx: int) -> None:
        thread_cat = Catalog(
            db_path=db_path,
            data_dir=data_dir,
            auto_reconcile=False,
            auto_cleanup_orphans=False,
        )
        try:
            with (
                patch.object(thread_cat, "is_month_complete", return_value=True),
                patch(
                    "data_downloader.storage.parquet_writer.compact_month",
                    side_effect=_patched_compact_month,
                ),
            ):
                barrier.wait(timeout=5)
                results[idx] = thread_cat.maybe_compact_month(
                    "WDOJ26", "F", 2026, 4, dll_version="4.0.0.34"
                )
        except BaseException as exc:
            results[idx] = exc
        finally:
            loser_done_event.set()
            thread_cat.close()

    t1 = threading.Thread(target=_worker, args=(0,))
    t2 = threading.Thread(target=_worker, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)
    assert not t1.is_alive() and not t2.is_alive()

    bool_results = [r for r in results if isinstance(r, bool)]
    assert sorted(bool_results) == [False, True], f"results={results}"

    assert monthly_path.exists()

    cat_final = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    try:
        parts = cat_final.get_completed_partitions("WDOJ26", "F")
        monthly_parts = [p for p in parts if p.day is None]
        assert len(monthly_parts) == 1
    finally:
        cat_final.close()

    # Diarios deletados do FS.
    month_dir = monthly_path.with_suffix("")
    if month_dir.is_dir():
        assert list(month_dir.glob("*.parquet")) == []
