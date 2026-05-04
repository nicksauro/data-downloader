"""Unit tests — storage.catalog initialization (Story 1.5 AC2/AC3/AC7).

Cobertura:

- Test 1: re-init em DB existente é no-op (idempotência — AC2).
- Test 2: PRAGMAs configurados conforme SCHEMA.md §5 (M6 reduzido).
- Test 3: Tabelas criadas conforme DDL (downloads, partitions, gaps,
  contracts, _checksum_cache, _pending_commits, _schema_meta).
- Test 4: Indexes criados (idx_partitions_symbol_ym, idx_gaps_symbol_unresolved).
- Test 5: cleanup_orphans é chamado em ``__init__`` (AC7).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from data_downloader.storage.catalog import CATALOG_VERSION, Catalog


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "history" / "catalog.db"


@pytest.mark.unit
def test_init_creates_db_and_dir(db_path: Path) -> None:
    """``__init__`` cria diretório pai + arquivo DB."""
    assert not db_path.exists()
    cat = Catalog(db_path=db_path)
    cat.close()
    assert db_path.exists()
    assert db_path.parent.exists()


@pytest.mark.unit
def test_init_is_idempotent_no_duplicate_schema(db_path: Path) -> None:
    """Re-init em DB existente não duplica tabelas nem _schema_meta (AC2)."""
    cat1 = Catalog(db_path=db_path)
    # Versão registrada após primeira init.
    conn = sqlite3.connect(str(db_path))
    rows1 = conn.execute("SELECT key, value FROM _schema_meta ORDER BY key").fetchall()
    conn.close()
    cat1.close()

    # Re-init — não deve mudar nada.
    cat2 = Catalog(db_path=db_path)
    conn = sqlite3.connect(str(db_path))
    rows2 = conn.execute("SELECT key, value FROM _schema_meta ORDER BY key").fetchall()
    conn.close()
    cat2.close()

    # catalog_version igual; não foram criadas linhas extras (key é PK).
    assert dict(rows1)["catalog_version"] == CATALOG_VERSION
    assert dict(rows1) == dict(rows2)


@pytest.mark.unit
def test_init_pragmas_configured(db_path: Path) -> None:
    """PRAGMAs canônicos (SCHEMA.md §5 + finding M6 reduzido)."""
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    cache_size = conn.execute("PRAGMA cache_size").fetchone()[0]
    mmap_size = conn.execute("PRAGMA mmap_size").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    temp_store = conn.execute("PRAGMA temp_store").fetchone()[0]
    cat.close()

    assert journal_mode.lower() == "wal"
    assert int(synchronous) == 1  # NORMAL
    assert int(cache_size) == -50000  # 50 MB (M6)
    assert int(mmap_size) == 67108864  # 64 MB (M6)
    assert int(foreign_keys) == 1
    assert int(temp_store) == 2  # MEMORY


@pytest.mark.unit
def test_init_creates_all_tables(db_path: Path) -> None:
    """Todas as tabelas do DDL existem após init."""
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r["name"] for r in rows}
    cat.close()

    expected = {
        "_schema_meta",
        "downloads",
        "partitions",
        "gaps",
        "contracts",
        "_checksum_cache",
        "_pending_commits",
    }
    missing = expected - table_names
    assert not missing, f"missing tables: {missing}"


@pytest.mark.unit
def test_init_creates_indexes(db_path: Path) -> None:
    """Indexes canônicos criados (SCHEMA.md §5.3..§5.4)."""
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    index_names = {r["name"] for r in rows}
    cat.close()

    expected = {
        "idx_downloads_symbol_status",
        "idx_partitions_symbol_ym",
        "idx_partitions_exchange",
        "idx_gaps_symbol_unresolved",
        "idx_contracts_root_vigency",
    }
    missing = expected - index_names
    assert not missing, f"missing indexes: {missing}"


@pytest.mark.unit
def test_init_runs_cleanup_orphans(tmp_path: Path) -> None:
    """``__init__`` chama ``cleanup_orphans`` automaticamente (AC7)."""
    data_dir = tmp_path / "data"
    history = data_dir / "history" / "F" / "WDOJ26" / "2026"
    history.mkdir(parents=True)

    # Arquivo .tmp.* antigo (>5min) — deve ser limpo.
    orphan = history / "03.parquet.tmp.abc123"
    orphan.write_bytes(b"junk")
    old = time.time() - 600  # 10 min atrás
    import os

    os.utime(orphan, (old, old))

    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, data_dir=data_dir)
    cat.close()

    assert not orphan.exists(), "orphan tmp file should be removed by init cleanup"


@pytest.mark.unit
def test_close_is_idempotent(db_path: Path) -> None:
    """``close()`` chamado múltiplas vezes não levanta."""
    cat = Catalog(db_path=db_path)
    cat.close()
    cat.close()
    cat.close()


@pytest.mark.unit
def test_context_manager(db_path: Path) -> None:
    """``with Catalog(...) as cat:`` fecha automaticamente."""
    with Catalog(db_path=db_path) as cat:
        assert cat._conn is not None
    assert cat._conn is None
