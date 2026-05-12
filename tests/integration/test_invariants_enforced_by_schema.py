"""tests/integration/test_invariants_enforced_by_schema.py — Sol Wave 2.

Owner: Sol (storage / schema integrity guardian).
Ref: ``docs/INVARIANTS.md`` + ``docs/storage/INTEGRITY.md`` §§3-5 +
v1.1.0 master plan Wave 2.

Purpose
-------
``schema.validate_record`` cobre INT-3/4/5 in-Python como defesa em
profundidade. Outras invariantes — UNIQUE/PK constraints, CHECK enums,
range constraints — são intencionalmente DELEGADAS ao schema SQLite
do catálogo (``catalog.py``). Estes tests validam que a delegação
funciona: o schema rejeita LOUDLY o que ``validate_record`` não checa.

Sem isso, a Council Sol Wave 2 ficou com gap aberto: "documentação diz
delegated, mas ninguém testa que o catálogo SQLite efetivamente rejeita".

Cobertura
---------

- Tabela ``downloads``: CHECK constraint em ``status``.
- Tabela ``partitions``: CHECK em ``row_count >= 0`` e
  ``file_size_bytes > 0``.
- Tabela ``gaps``: PRIMARY KEY ``(symbol, gap_start, gap_end)`` previne
  duplicatas (UPSERT no caminho público; INSERT direto rejeita).
- Tabela ``gaps``: CHECK em ``reason`` enum.
- Tabela ``contracts``: CHECK em ``validation_source`` enum.

Cada test abre o catálogo, tenta INSERT que viola constraint via
SQL direto, e confirma que ``sqlite3.IntegrityError`` é levantado.
INSERT direto é a forma de exercitar o constraint — APIs públicas
do ``Catalog`` aplicam ON CONFLICT que mascara violações de chave.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


@pytest.fixture
def catalog(db_path: Path, data_dir: Path) -> Catalog:
    """Catálogo SQLite — auto_reconcile off para isolar constraint tests."""
    return Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


# =====================================================================
# Tabela downloads — CHECK em status
# =====================================================================


@pytest.mark.integration
def test_downloads_status_check_rejects_invalid_value(catalog: Catalog) -> None:
    """``downloads.status`` CHECK rejeita valores fora do enum.

    Enum aceito (catalog.py L92-93): pending, in_progress, completed,
    failed, partial, cancelled. ``"invalid_status"`` deve quebrar.
    """
    job_id = catalog.register_job(
        symbol="WDOJ26",
        exchange="F",
        requested_start=datetime(2026, 3, 1),
        requested_end=datetime(2026, 3, 31),
    )
    conn = catalog._conn_or_raise()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE downloads SET status = ? WHERE job_id = ?",
            ("invalid_status", job_id),
        )
    catalog.close()


# =====================================================================
# Tabela partitions — CHECK em row_count >= 0 e file_size_bytes > 0
# =====================================================================


@pytest.mark.integration
def test_partitions_row_count_check_rejects_negative(catalog: Catalog) -> None:
    """``partitions.row_count`` CHECK rejeita valor negativo.

    Defesa contra bug de writer (catalog.py L114). Garante que o
    catálogo NUNCA aceita registro de partição com row_count < 0.
    """
    conn = catalog._conn_or_raise()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO partitions(
                partition_path, symbol, exchange, year, month,
                row_count, first_ts_ns, last_ts_ns, schema_version,
                checksum_sha256, file_size_bytes, written_at, job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                "F/WDOJ26/2026/03.parquet",
                "WDOJ26",
                "F",
                2026,
                3,
                -1,  # row_count < 0 → CHECK violado.
                1,
                2,
                "1.1.0",
                "a" * 64,
                1024,
                "2026-05-06 10:00:00",
            ),
        )
    catalog.close()


@pytest.mark.integration
def test_partitions_file_size_check_rejects_zero(catalog: Catalog) -> None:
    """``partitions.file_size_bytes`` CHECK rejeita 0.

    Constraint exige ``file_size_bytes > 0`` (catalog.py L114). Arquivo
    Parquet vazio = bug; catálogo bloqueia o registro.
    """
    conn = catalog._conn_or_raise()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO partitions(
                partition_path, symbol, exchange, year, month,
                row_count, first_ts_ns, last_ts_ns, schema_version,
                checksum_sha256, file_size_bytes, written_at, job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                "F/WDOJ26/2026/04.parquet",
                "WDOJ26",
                "F",
                2026,
                4,
                100,
                1,
                2,
                "1.1.0",
                "a" * 64,
                0,  # file_size_bytes == 0 → CHECK violado.
                "2026-05-06 10:00:00",
            ),
        )
    catalog.close()


# =====================================================================
# Tabela partitions — CHECK em month range
# =====================================================================


@pytest.mark.integration
def test_partitions_month_check_rejects_out_of_range(catalog: Catalog) -> None:
    """``partitions.month`` CHECK rejeita month fora de [1, 12]."""
    conn = catalog._conn_or_raise()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO partitions(
                partition_path, symbol, exchange, year, month,
                row_count, first_ts_ns, last_ts_ns, schema_version,
                checksum_sha256, file_size_bytes, written_at, job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                "F/WDOJ26/2026/13.parquet",
                "WDOJ26",
                "F",
                2026,
                13,  # month > 12 → CHECK violado.
                100,
                1,
                2,
                "1.1.0",
                "a" * 64,
                1024,
                "2026-05-06 10:00:00",
            ),
        )
    catalog.close()


# =====================================================================
# Tabela gaps — PRIMARY KEY (symbol, gap_start, gap_end) + CHECK reason
# =====================================================================


@pytest.mark.integration
def test_gaps_primary_key_rejects_duplicate_direct_insert(catalog: Catalog) -> None:
    """``gaps`` PK ``(symbol, gap_start, gap_end)`` rejeita duplicatas.

    A API pública ``register_gap`` usa ON CONFLICT (UPSERT). Aqui
    testamos o constraint subjacente via INSERT direto: segunda
    inserção com mesma chave tripla deve levantar IntegrityError.
    """
    conn = catalog._conn_or_raise()
    conn.execute(
        """
        INSERT INTO gaps(symbol, exchange, gap_start, gap_end, reason, detected_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "WDOJ26",
            "F",
            "2026-03-01 09:00:00",
            "2026-03-01 10:00:00",
            "no_trades",
            "2026-05-06 10:00:00",
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO gaps(symbol, exchange, gap_start, gap_end, reason, detected_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "WDOJ26",
                "F",
                "2026-03-01 09:00:00",  # mesma triple-key.
                "2026-03-01 10:00:00",
                "holiday",
                "2026-05-06 11:00:00",
            ),
        )
    catalog.close()


@pytest.mark.integration
def test_gaps_reason_check_rejects_invalid_value(catalog: Catalog) -> None:
    """``gaps.reason`` CHECK rejeita valor fora do enum.

    Enum aceito (catalog.py L126-127): no_trades, holiday, weekend,
    failed_chunk, unknown, outside_vigency.
    """
    with pytest.raises(sqlite3.IntegrityError):
        catalog.register_gap(
            symbol="WDOJ26",
            exchange="F",
            gap_start=datetime(2026, 3, 1, 9, 0),
            gap_end=datetime(2026, 3, 1, 10, 0),
            reason="invalid_reason_xyz",  # fora do enum.
        )
    catalog.close()


# =====================================================================
# Tabela contracts — CHECK em validation_source
# =====================================================================


@pytest.mark.integration
def test_contracts_validation_source_check_rejects_invalid(catalog: Catalog) -> None:
    """``contracts.validation_source`` CHECK rejeita valor fora do enum.

    Enum aceito (catalog.py L140-141): hypothesized, nelogica_official,
    dll_probe, b3_calendar, manual.
    """
    conn = catalog._conn_or_raise()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO contracts(
                symbol_root, contract_code, vigent_from, vigent_until,
                validation_source
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "WDO",
                "WDOJ26",
                "2026-01-01 00:00:00",
                "2026-04-30 00:00:00",
                "made_up_source",  # fora do enum.
            ),
        )
    catalog.close()


# =====================================================================
# Tabela _migration_log — CHECK em status
# =====================================================================


@pytest.mark.integration
def test_migration_log_status_check_rejects_invalid(catalog: Catalog) -> None:
    """``_migration_log.status`` CHECK rejeita valor fora do enum.

    Enum aceito (catalog.py L192-193): pending, migrated, rolled_back,
    failed. Garante que o framework de migrations não aceita estado
    arbitrário.
    """
    conn = catalog._conn_or_raise()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO _migration_log(
                run_id, partition_path, from_version, to_version, status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "run-2026-05-06",
                "F/WDOJ26/2026/03.parquet",
                "1.0.0",
                "1.1.0",
                "in_flight",  # fora do enum.
            ),
        )
    catalog.close()
