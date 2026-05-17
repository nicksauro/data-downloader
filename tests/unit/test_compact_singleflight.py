"""Unit tests — compact single-flight via claim atomico (Story 4.24 / ADR-026 sect 2.4).

Cobertura (AC10 — minimo 4 tests):

- Test 1: ``maybe_compact_month`` com claim limpo (sem row previa em
  ``compactions``): sucesso, ``True``, ``completed_at`` populado.
- Test 2: ``maybe_compact_month`` com claim de outro processo RECENTE
  (mock SELECT pos-INSERT retornando ``started_at`` diferente do nosso
  ``now``): no-op, ``False``, log ``claim_lost``, ``compact_month`` NAO
  eh chamado.
- Test 3: ``maybe_compact_month`` com claim STALE (>1h, ``completed_at
  IS NULL``): claim sobrescreve (WHERE-guard libera) -> sucesso ``True``.
- Test 4: ``maybe_compact_month`` com claim previamente COMPLETED
  (``completed_at IS NOT NULL``): claim sobrescreve (WHERE-guard libera)
  -> sucesso ``True``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
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


def _seed_two_dailies(catalog: Catalog, writer: ParquetWriter, *, year: int, month: int) -> None:
    """Escreve 2 diarios via two-phase commit (writer com catalog)."""
    base_day_ns = 1_700_000_000_000_000_000
    for day in (15, 16):
        pk = PartitionKey(exchange="F", symbol="WDOJ26", year=year, month=month, day=day)
        writer.write(
            _make_trades(5, base_ts=base_day_ns + day * 86_400_000_000_000),
            pk,
            dll_version="4.0.0.34",
            catalog=catalog,
        )


def _insert_compaction_raw(
    cat: Catalog,
    *,
    symbol: str,
    exchange: str,
    year: int,
    month: int,
    started_at: datetime,
    completed_at: datetime | None = None,
    error: str | None = None,
) -> None:
    """Insere row em ``compactions`` direto (bypass claim)."""
    conn = cat._conn_or_raise()
    started_str = started_at.strftime("%Y-%m-%d %H:%M:%S")
    completed_str = completed_at.strftime("%Y-%m-%d %H:%M:%S") if completed_at else None
    with cat._transaction():
        conn.execute(
            "INSERT OR REPLACE INTO compactions(symbol, exchange, year, month, "
            "started_at, completed_at, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, exchange, year, month, started_str, completed_str, error),
        )


def _fetch_compaction(
    cat: Catalog, *, symbol: str, exchange: str, year: int, month: int
) -> dict[str, object] | None:
    conn = cat._conn_or_raise()
    row = conn.execute(
        "SELECT started_at, completed_at, error FROM compactions "
        "WHERE symbol = ? AND exchange = ? AND year = ? AND month = ?",
        (symbol, exchange, year, month),
    ).fetchone()
    if row is None:
        return None
    return {
        "started_at": str(row["started_at"]),
        "completed_at": str(row["completed_at"]) if row["completed_at"] is not None else None,
        "error": str(row["error"]) if row["error"] is not None else None,
    }


# =====================================================================
# AC10 tests
# =====================================================================


@pytest.mark.unit
def test_maybe_compact_month_succeeds_with_clean_claim(catalog: Catalog, data_dir: Path) -> None:
    """AC10-1: claim limpo (sem row previa) -> sucesso, True, completed_at populado."""
    writer = ParquetWriter(data_dir=data_dir)
    _seed_two_dailies(catalog, writer, year=2026, month=3)

    # is_month_complete normalmente exige todos os dias uteis B3 do mes.
    # Para teste unit, forcamos True via mock.
    with patch.object(catalog, "is_month_complete", return_value=True):
        result = catalog.maybe_compact_month("WDOJ26", "F", 2026, 3)

    assert result is True
    compact_row = _fetch_compaction(catalog, symbol="WDOJ26", exchange="F", year=2026, month=3)
    assert compact_row is not None
    assert compact_row["completed_at"] is not None
    assert compact_row["error"] is None
    catalog.close()


@pytest.mark.unit
def test_maybe_compact_month_noop_when_claim_lost(
    catalog: Catalog,
    data_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC10-2: claim de outro processo recente -> no-op, False, log claim_lost.

    Mockamos o SELECT pos-INSERT (atraves de patch em ``Connection.execute``)
    para retornar ``started_at`` diferente do ``now`` que passamos.
    Verificamos que ``compact_month`` NAO foi chamado.
    """
    writer = ParquetWriter(data_dir=data_dir)
    _seed_two_dailies(catalog, writer, year=2026, month=4)

    # Simula "outro processo claim'd primeiro" injetando manualmente uma row
    # ANTES de chamar maybe_compact_month. O INSERT WHERE-guarded vai
    # bloquear pelo started_at recente (< now-1h), preservando other_started_at.
    other_started_at = datetime.now(UTC) - timedelta(minutes=10)
    _insert_compaction_raw(
        catalog,
        symbol="WDOJ26",
        exchange="F",
        year=2026,
        month=4,
        started_at=other_started_at,
        completed_at=None,
    )

    # Patch compact_month para detectar invocacao (NAO deve ser chamado).
    compact_calls: list[tuple[str, object, object]] = []

    def _mock_compact_month(*args: object, **kwargs: object) -> None:
        compact_calls.append(("called", kwargs.get("year"), kwargs.get("month")))
        return None

    with (
        patch.object(catalog, "is_month_complete", return_value=True),
        patch(
            "data_downloader.storage.parquet_writer.compact_month",
            side_effect=_mock_compact_month,
        ),
        caplog.at_level(logging.INFO, logger="data_downloader.storage.catalog"),
    ):
        result = catalog.maybe_compact_month("WDOJ26", "F", 2026, 4)

    assert result is False, "claim lost should return False"
    assert compact_calls == [], (
        f"compact_month should NOT be called when claim lost; got {compact_calls}"
    )
    # Log claim_lost emitido.
    assert any(
        "catalog.maybe_compact_month.claim_lost" in record.message for record in caplog.records
    )
    # Row antiga preservada.
    row = _fetch_compaction(catalog, symbol="WDOJ26", exchange="F", year=2026, month=4)
    assert row is not None
    assert row["completed_at"] is None  # antiga estava in-flight; permanece in-flight
    catalog.close()


@pytest.mark.unit
def test_maybe_compact_month_reclaims_stale_inflight(catalog: Catalog, data_dir: Path) -> None:
    """AC10-3: claim stale (>1h, completed_at IS NULL) -> sobrescreve, sucesso True."""
    writer = ParquetWriter(data_dir=data_dir)
    _seed_two_dailies(catalog, writer, year=2026, month=5)

    # Injeta row stale (2h atras, in-flight): WHERE-guard libera sobrescrita.
    _insert_compaction_raw(
        catalog,
        symbol="WDOJ26",
        exchange="F",
        year=2026,
        month=5,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        completed_at=None,
    )

    with patch.object(catalog, "is_month_complete", return_value=True):
        result = catalog.maybe_compact_month("WDOJ26", "F", 2026, 5)

    assert result is True
    row = _fetch_compaction(catalog, symbol="WDOJ26", exchange="F", year=2026, month=5)
    assert row is not None
    assert row["completed_at"] is not None
    catalog.close()


@pytest.mark.unit
def test_maybe_compact_month_reclaims_previously_completed(
    catalog: Catalog, data_dir: Path
) -> None:
    """AC10-4: claim previamente completed -> sobrescreve, sucesso True.

    Cenario: mes ja foi compactado uma vez (row tem completed_at != NULL),
    mas novos diarios chegaram e foram re-compactados. WHERE-guard
    permite (completed_at IS NOT NULL).
    """
    writer = ParquetWriter(data_dir=data_dir)
    _seed_two_dailies(catalog, writer, year=2026, month=6)

    # Injeta row previamente completed (8h atras).
    _insert_compaction_raw(
        catalog,
        symbol="WDOJ26",
        exchange="F",
        year=2026,
        month=6,
        started_at=datetime.now(UTC) - timedelta(hours=8),
        completed_at=datetime.now(UTC) - timedelta(hours=8) + timedelta(seconds=30),
    )

    with patch.object(catalog, "is_month_complete", return_value=True):
        result = catalog.maybe_compact_month("WDOJ26", "F", 2026, 6)

    assert result is True
    row = _fetch_compaction(catalog, symbol="WDOJ26", exchange="F", year=2026, month=6)
    assert row is not None
    # completed_at foi atualizado para o novo run.
    assert row["completed_at"] is not None
    assert row["error"] is None
    catalog.close()
