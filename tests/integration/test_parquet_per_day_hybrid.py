"""Integration tests — ADR-025 parquet-per-day híbrido + auto-compactação.

Owner: Aria (@architect) | Wave 3 v1.3.0.
Pichau directive (2026-05-13): "rigidamente implementar e testar".

Cobertura T1-T9 (T10 é smoke real pós-build):

- **T1** — Download mensal completo: 22 diários → auto-compact → 1 mensal,
  0 diários remanescentes, ``partitions.day=NULL``.
- **T2** — Download parcial (10 dias): 10 diários, NÃO compacta.
- **T3** — Misto: jan inteiro + 10 dias fev → jan mensal, fev 10 diários,
  glob DuckDB retorna ambos.
- **T4** — Mês com feriado (dez/2024 com Natal, ~21 dias úteis): compact
  dispara ao fechar 21 dias (ignora feriados).
- **T5** — Re-baixar mês já compactado: idempotente, sem duplicação.
- **T6** — Crash entre write mensal e DELETE diários: reconcile detecta
  e completa o cleanup.
- **T7** — Resume após crash parcial: ledger granular preservado;
  re-run baixa só os dias faltantes; compacta no final.
- **T8** — Migração v1.2→v1.3: parquets mensais v1.2.0 intactos,
  ``partitions.day=NULL``, ``catalog_version=1.3.0``.
- **T9** — Throughput: row_group=1M validado em bench (smoke teste rápido).

Estes testes usam ``pa.Table`` aleatórios (sem DLL real) — simulam o
output do orchestrator escrevendo via ``ParquetWriter.write`` e o
gatilho ``Catalog.maybe_compact_month``.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import ParquetWriter
from data_downloader.storage.partition import PartitionKey, resolve_partition_path
from data_downloader.storage.schema import TradeRecord
from data_downloader.validation.calendar_b3 import b3_business_days_range

# =====================================================================
# Helpers
# =====================================================================


def _make_trades(
    n: int,
    *,
    base_ts: int,
    symbol: str = "WDOJ26",
    exchange: str = "F",
) -> list[TradeRecord]:
    """Gera N trades sintéticos com timestamps crescentes."""
    return [
        TradeRecord(
            symbol=symbol,
            exchange=exchange,
            timestamp_ns=base_ts + i * 1_000_000,
            timestamp_str="01/01/2018 00:00:00.000",
            price=5_300.0 + i * 0.5,
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
            dll_version="0.0.0+test",
            sequence_within_ns=0,
        )
        for i in range(n)
    ]


def _write_daily(
    writer: ParquetWriter,
    catalog: Catalog,
    *,
    symbol: str,
    exchange: str,
    d: date,
    n_trades: int = 100,
) -> None:
    """Helper: escreve 1 partição diária + registra em catalog + ledger."""
    base_ts = int(datetime(d.year, d.month, d.day, 9, 0, 0).timestamp()) * 1_000_000_000
    trades = _make_trades(n_trades, base_ts=base_ts, symbol=symbol, exchange=exchange)
    partition = PartitionKey(
        exchange=exchange, symbol=symbol, year=d.year, month=d.month, day=d.day
    )
    write_result = writer.write(trades, partition, dll_version="0.0.0+test")
    catalog.register_partition(write_result, partition)
    catalog.record_chunk(
        symbol=symbol,
        exchange=exchange,
        chunk_date=d,
        job_id=None,
        status="completed",
        trades_count=n_trades,
    )


def _count_files(data_dir: Path, symbol: str, exchange: str, year: int, month: int):
    """Conta (mensais, diários) para o (symbol, year, month)."""
    base = data_dir / "history" / exchange / symbol / f"{year:04d}"
    monthly = base / f"{month:02d}.parquet"
    monthly_count = 1 if monthly.is_file() else 0
    month_dir = base / f"{month:02d}"
    daily_count = 0
    if month_dir.is_dir():
        daily_count = sum(1 for p in month_dir.glob("*.parquet") if ".tmp." not in p.name)
    return monthly_count, daily_count


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def catalog(data_dir: Path) -> Catalog:
    db_path = data_dir / "_internal" / "catalog.db"
    c = Catalog(
        db_path=db_path, data_dir=data_dir, auto_reconcile=False, auto_cleanup_orphans=False
    )
    yield c
    c.close()


@pytest.fixture
def writer(data_dir: Path) -> ParquetWriter:
    return ParquetWriter(data_dir=data_dir)


# =====================================================================
# T1 — Download mensal completo → auto-compact
# =====================================================================


@pytest.mark.integration
def test_t1_full_month_auto_compacts(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T1: download de jan/2018 inteiro → 22 diários durante; após o 22º,
    auto-compact dispara, gera 01.parquet mensal, deleta os 22 diários,
    partitions tem 1 row com day=NULL e chunk_ledger mantém 22 rows.
    """
    symbol = "WDOJ26"
    exchange = "F"
    year, month = 2018, 1
    business_days = b3_business_days_range(date(year, month, 1), date(year, month, 31))
    assert len(business_days) >= 20, "sanity check: jan/2018 tem ~22 dias úteis"

    for d in business_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=100)
        # Cada chunk dispara maybe_compact_month no orchestrator real.
        catalog.maybe_compact_month(symbol, exchange, year, month)

    # Após o último dia útil, deve estar compactado.
    monthly_count, daily_count = _count_files(data_dir, symbol, exchange, year, month)
    assert monthly_count == 1, "mensal deve existir após compact"
    assert daily_count == 0, "diários devem ter sido deletados"

    # `partitions` deve ter 1 row mensal (day=NULL) e zero diárias.
    parts = catalog.get_completed_partitions(symbol, exchange)
    assert len(parts) == 1
    assert parts[0].day is None
    assert parts[0].row_count == 100 * len(business_days)

    # `chunk_ledger` deve preservar 22 rows.
    done = catalog.completed_days(symbol, exchange, date(year, month, 1), date(year, month, 31))
    assert len(done) == len(business_days)


# =====================================================================
# T2 — Download parcial (10 dias) NÃO compacta
# =====================================================================


@pytest.mark.integration
def test_t2_partial_month_does_not_compact(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T2: download de 10 dias de jan/2018 (mês incompleto) → 10 diários,
    auto-compact NÃO dispara, partições no catalog com day=N.
    """
    symbol = "WDOJ26"
    exchange = "F"
    year, month = 2018, 1
    business_days = b3_business_days_range(date(year, month, 1), date(year, month, 31))
    partial_days = business_days[:10]

    for d in partial_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=100)
        catalog.maybe_compact_month(symbol, exchange, year, month)

    monthly_count, daily_count = _count_files(data_dir, symbol, exchange, year, month)
    assert monthly_count == 0, "mensal NÃO deve existir (mês incompleto)"
    assert daily_count == 10

    parts = catalog.get_completed_partitions(symbol, exchange)
    assert len(parts) == 10
    assert all(p.day is not None for p in parts), "todos devem ser diários"


# =====================================================================
# T3 — Misto: jan completo + 10 dias fev
# =====================================================================


@pytest.mark.integration
def test_t3_mixed_layout_read_combined(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T3: jan inteiro compactado + 10 dias de fev (parciais);
    read DuckDB retorna ambos.
    """
    symbol = "WDOJ26"
    exchange = "F"
    # Janeiro completo → compacta.
    jan_days = b3_business_days_range(date(2018, 1, 1), date(2018, 1, 31))
    for d in jan_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=50)
        catalog.maybe_compact_month(symbol, exchange, 2018, 1)

    # Fev parcial → não compacta.
    feb_days = b3_business_days_range(date(2018, 2, 1), date(2018, 2, 28))[:10]
    for d in feb_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=50)
        catalog.maybe_compact_month(symbol, exchange, 2018, 2)

    # Validar layout no disco.
    jan_monthly, jan_daily = _count_files(data_dir, symbol, exchange, 2018, 1)
    feb_monthly, feb_daily = _count_files(data_dir, symbol, exchange, 2018, 2)
    assert jan_monthly == 1 and jan_daily == 0
    assert feb_monthly == 0 and feb_daily == 10

    # DuckDB read glob '**/*.parquet' deve agregar ambos.
    glob = str(data_dir / "history" / "**" / "*.parquet")
    conn = duckdb.connect(":memory:")
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM parquet_scan('{glob}')").fetchone()[0]
        assert total == 50 * len(jan_days) + 50 * len(feb_days)
    finally:
        conn.close()


# =====================================================================
# T4 — Mês com feriado (dez/2024 com Natal)
# =====================================================================


@pytest.mark.integration
def test_t4_month_with_holiday_compacts(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T4: dez/2024 tem Natal (25/12); is_month_complete ignora feriados —
    só ~21 dias úteis baixados = mês completo, auto-compact dispara.
    """
    symbol = "WDOJ26"
    exchange = "F"
    year, month = 2024, 12
    business_days = b3_business_days_range(date(year, month, 1), date(year, month, 31))
    # Garante que Natal NÃO está na lista (sanity check do calendário B3).
    assert date(year, month, 25) not in business_days

    for d in business_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=100)
        catalog.maybe_compact_month(symbol, exchange, year, month)

    # is_month_complete deve retornar True mesmo sem o 25.
    assert catalog.is_month_complete(symbol, exchange, year, month)

    monthly_count, daily_count = _count_files(data_dir, symbol, exchange, year, month)
    assert monthly_count == 1
    assert daily_count == 0


# =====================================================================
# T5 — Re-baixar mês compactado é idempotente
# =====================================================================


@pytest.mark.integration
def test_t5_redownload_compacted_month_idempotent(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T5: após compactação, re-baixar dias do mês não duplica trades.

    Comportamento esperado: orchestrator real consulta ``completed_days``
    e pula dias já no ledger (fresh-skip). Mas se forçar re-execução com
    ``maybe_compact_month``, este é idempotente — mensal sobrescrito
    atomicamente (no-op se sem diários).
    """
    symbol = "WDOJ26"
    exchange = "F"
    year, month = 2018, 1
    business_days = b3_business_days_range(date(year, month, 1), date(year, month, 31))
    for d in business_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=100)
        catalog.maybe_compact_month(symbol, exchange, year, month)

    # Snapshot inicial.
    parts_before = catalog.get_completed_partitions(symbol, exchange)
    assert len(parts_before) == 1
    rows_before = parts_before[0].row_count

    # Re-disparar maybe_compact_month — deve ser no-op (sem diários).
    triggered = catalog.maybe_compact_month(symbol, exchange, year, month)
    assert triggered is False, "no-op: mensal existe sem diários"

    # Conta via DuckDB — não deve haver duplicação.
    glob = str(data_dir / "history" / exchange / symbol / "**" / "*.parquet")
    conn = duckdb.connect(":memory:")
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM parquet_scan('{glob}')").fetchone()[0]
        assert total == rows_before
    finally:
        conn.close()


# =====================================================================
# T6 — Crash simulado: reconcile completa cleanup
# =====================================================================


@pytest.mark.integration
def test_t6_crash_during_compact_recovers_via_reconcile(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T6: simula crash entre write {MM}.parquet e DELETE diários.
    Estado: {MM}.parquet existe, {DD}.parquet ainda existem, compactions
    tem row com started_at sem completed_at. reconcile detecta e completa
    o cleanup (ADR-025 §2.4 — política "completar").
    """
    symbol = "WDOJ26"
    exchange = "F"
    year, month = 2018, 1
    business_days = b3_business_days_range(date(year, month, 1), date(year, month, 31))
    # Escreve TODOS os diários (mas NÃO chama maybe_compact_month).
    for d in business_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=100)

    # Simula crash: cria {MM}.parquet manualmente (copia 1º diário —
    # row_count e SHA divergem do "ideal", mas para simular o crash o
    # importante é o file existir + compactions ter row in-flight).
    from data_downloader.storage.parquet_writer import compact_month as _compact

    # Executa compactação real para produzir um {MM}.parquet válido +
    # diários DELETADOS, depois REIMPORTA os diários para simular o estado
    # "intermediário do crash" (arquivo monthly + diários).
    _compact(data_dir, exchange=exchange, symbol=symbol, year=year, month=month, dll_version="test")
    monthly_path = resolve_partition_path(
        PartitionKey(exchange=exchange, symbol=symbol, year=year, month=month), data_dir
    )
    assert monthly_path.is_file()

    # Recria os diários (simula crash que não conseguiu deletar) E injeta
    # row in-flight em compactions (sem completed_at).
    for d in business_days:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=100)
    # Inject in-flight row.
    with sqlite3.connect(str(data_dir / "_internal" / "catalog.db")) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO compactions(symbol, exchange, year, month, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (symbol, exchange, year, month, "2026-05-13 12:00:00"),
        )
        conn.commit()

    # Agora roda reconcile com auto_correct=True → deve detectar in-flight
    # e completar (mensal existe e tem >= rows que diários).
    catalog.reconcile(auto_correct=True)

    monthly_count, daily_count = _count_files(data_dir, symbol, exchange, year, month)
    assert monthly_count == 1, "mensal preservado"
    assert daily_count == 0, "diários removidos pelo reconcile"
    # compactions atualizado: completed_at not null.
    with sqlite3.connect(str(data_dir / "_internal" / "catalog.db")) as conn:
        row = conn.execute(
            "SELECT completed_at FROM compactions WHERE symbol = ? AND year = ? AND month = ?",
            (symbol, year, month),
        ).fetchone()
        assert row is not None and row[0] is not None


# =====================================================================
# T7 — Resume após crash parcial
# =====================================================================


@pytest.mark.integration
def test_t7_resume_after_partial_crash(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T7: simula crash de download parcial — 15 de 22 dias completos no
    ledger. Re-run baixa os 7 faltantes e compacta no final.
    """
    symbol = "WDOJ26"
    exchange = "F"
    year, month = 2018, 1
    business_days = b3_business_days_range(date(year, month, 1), date(year, month, 31))
    # Etapa 1: baixa só 15.
    for d in business_days[:15]:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=80)
        catalog.maybe_compact_month(symbol, exchange, year, month)

    assert not catalog.is_month_complete(symbol, exchange, year, month)
    monthly_count, daily_count = _count_files(data_dir, symbol, exchange, year, month)
    assert monthly_count == 0
    assert daily_count == 15

    # Etapa 2: resume — baixa os 7 faltantes (consulta `completed_days`).
    already = catalog.completed_days(symbol, exchange, date(year, month, 1), date(year, month, 31))
    remaining = [d for d in business_days if d not in already]
    assert len(remaining) == len(business_days) - 15
    for d in remaining:
        _write_daily(writer, catalog, symbol=symbol, exchange=exchange, d=d, n_trades=80)
        catalog.maybe_compact_month(symbol, exchange, year, month)

    # Após o último, compactou.
    monthly_count, daily_count = _count_files(data_dir, symbol, exchange, year, month)
    assert monthly_count == 1
    assert daily_count == 0
    parts = catalog.get_completed_partitions(symbol, exchange)
    assert len(parts) == 1
    assert parts[0].row_count == 80 * len(business_days)


# =====================================================================
# T8 — Migração v1.2 → v1.3
# =====================================================================


@pytest.mark.integration
def test_t8_migration_preserves_legacy_v1_2_0_parquets(tmp_path: Path) -> None:
    """T8: catálogo v1.2.0 + parquet mensal v1.2.0 existente; abre app
    v1.3.0 → migra schema, parquet mensal intacto, partitions.day=NULL.
    """
    data_dir = tmp_path / "data"
    db_path = data_dir / "_internal" / "catalog.db"
    db_path.parent.mkdir(parents=True)

    # Cria um catálogo v1.2.0 manual.
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE _schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """CREATE TABLE partitions (
            partition_path TEXT PRIMARY KEY, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
            year INTEGER NOT NULL, month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
            row_count INTEGER NOT NULL CHECK(row_count >= 0),
            first_ts_ns INTEGER NOT NULL, last_ts_ns INTEGER NOT NULL,
            schema_version TEXT NOT NULL, checksum_sha256 TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL CHECK(file_size_bytes > 0),
            written_at TIMESTAMP NOT NULL, job_id TEXT
        )"""
    )
    conn.execute("INSERT INTO _schema_meta(key, value) VALUES ('catalog_version', '1.2.0')")
    # Insere row mensal legacy.
    conn.execute(
        """INSERT INTO partitions(partition_path, symbol, exchange, year, month,
            row_count, first_ts_ns, last_ts_ns, schema_version, checksum_sha256,
            file_size_bytes, written_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "F/WDOJ26/2018/01.parquet",
            "WDOJ26",
            "F",
            2018,
            1,
            12345,
            1,
            2,
            "1.1.0",
            "a" * 64,
            10000,
            "2018-01-31 00:00:00",
        ),
    )
    conn.commit()
    conn.close()

    # Cria o parquet mensal "v1.2.0" no path legacy.
    legacy_monthly = data_dir / "history" / "F" / "WDOJ26" / "2018" / "01.parquet"
    legacy_monthly.parent.mkdir(parents=True, exist_ok=True)
    legacy_monthly.write_bytes(b"PAR1stub" + b"\x00" * 10000)
    legacy_monthly_mtime_before = legacy_monthly.stat().st_mtime_ns

    # Abre Catalog v1.3.0 → dispara migrations.
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    try:
        assert cat._get_meta("catalog_version") == "1.3.0"
        # Parquet mensal intacto.
        assert legacy_monthly.is_file()
        assert legacy_monthly.stat().st_mtime_ns == legacy_monthly_mtime_before
        # Row preservada, day = NULL.
        parts = cat.get_completed_partitions("WDOJ26", "F")
        assert len(parts) == 1
        assert parts[0].day is None
        assert parts[0].row_count == 12345
        # Coluna day existe.
        cols = [
            r[1] for r in cat._conn_or_raise().execute("PRAGMA table_info(partitions)").fetchall()
        ]
        assert "day" in cols
        # Compactions table existe.
        rows = cat._conn_or_raise().execute("PRAGMA table_info(compactions)").fetchall()
        assert len(rows) > 0
    finally:
        cat.close()


# =====================================================================
# T9 — Throughput sanity: row_group=1M efetivo no writer
# =====================================================================


@pytest.mark.integration
def test_t9_row_group_size_is_1_million(
    data_dir: Path, catalog: Catalog, writer: ParquetWriter
) -> None:
    """T9: row_group=1M (vs 100k baseline) — validado via metadata Parquet.

    Smoke teste — o bench dedicado (``bench_parquet_write``) faz medição
    real de throughput; aqui só assertamos que o setting prod está em 1M.
    """
    from data_downloader.storage.parquet_writer import _ROW_GROUP_SIZE

    assert _ROW_GROUP_SIZE == 1_000_000

    # Validate metadata.
    base_ts = int(datetime(2018, 1, 2, 9, 0).timestamp()) * 1_000_000_000
    trades = _make_trades(500, base_ts=base_ts)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2018, month=1, day=2)
    result = writer.write(trades, partition, dll_version="test")
    md = pq.read_metadata(result.path).metadata
    assert md is not None
    assert md.get(b"row_group_size") == b"1000000"


# =====================================================================
# T10 — Smoke real (TODO: pós-build, requer DLL real)
# =====================================================================


@pytest.mark.skip(
    reason="T10 = smoke real (DLL + B3 + ~30min) — deferido para validação manual pós-build"
)
def test_t10_real_smoke_download_one_month_via_ui() -> None:  # pragma: no cover
    """T10 placeholder: download de 1 mês WDOFUT (~21 dias) end-to-end via UI.

    Validar pós-build manualmente:
    - 1 parquet mensal ``{MM}.parquet`` resultante.
    - 0 diários remanescentes.
    - ``completeness_pct=100%``, ``translate_failures=0``.
    - CatalogScreen mostra a partition (debounced refresh 500ms).
    """
    raise AssertionError("T10 é smoke pós-build — não roda em CI")
