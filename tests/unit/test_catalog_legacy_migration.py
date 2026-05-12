"""Unit tests — migração silenciosa ADR-024 (catalog.db legacy → _internal/).

Background: Story v1.1.0 hotfix Pichau live smoke 2026-05-07. Catalog SQLite
foi movido de ``data/history/catalog.db`` para ``data/_internal/catalog.db``
para evitar UX confusa (usuário viu o ``.db`` ao lado dos parquets no
Explorer).

Cobertura:

- Test 1: migração ocorre quando só legacy existe (rename atômico).
- Test 2: no-op quando só new path existe (já migrado).
- Test 3: keep new + log warning quando ambos existem (ADR-024 regra de
  segurança — preserva o que parece mais novo).
- Test 4: no-op quando nenhum existe (Catalog cria limpo no novo path).
- Test 5: WAL/SHM auxiliares são migrados junto com o ``.db`` principal.
- Test 6: caller passando explicitamente o path legado não dispara
  migração (idempotência defensiva).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from data_downloader.storage.catalog import (
    CATALOG_VERSION,
    Catalog,
    _migrate_legacy_catalog_path,
)


def _seed_legacy_db(legacy_path: Path) -> None:
    """Cria um SQLite minimal no path legado simulando v1.0.x catalog.

    Conteúdo é só uma tabela ``_legacy_marker`` para verificarmos depois
    que o arquivo MOVIDO é o mesmo (não foi recriado vazio).
    """
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(legacy_path))
    try:
        conn.execute("CREATE TABLE _legacy_marker (val TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO _legacy_marker(val) VALUES ('v1_0_x_data')")
        conn.commit()
    finally:
        conn.close()


def _has_legacy_marker(db_path: Path) -> bool:
    """Verifica se o DB em ``db_path`` contém a tabela ``_legacy_marker``."""
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master " "WHERE type='table' AND name='_legacy_marker' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return row is not None


@pytest.mark.unit
def test_migrate_old_to_new_when_only_old_exists(tmp_path: Path) -> None:
    """Legacy existe + new ausente → rename atômico, marker preservado."""
    data_dir = tmp_path / "data"
    legacy = data_dir / "history" / "catalog.db"
    new = data_dir / "_internal" / "catalog.db"
    _seed_legacy_db(legacy)
    assert legacy.exists()
    assert not new.exists()

    # Instancia Catalog no NEW path → migration deve disparar via __post_init__.
    cat = Catalog(db_path=new, data_dir=data_dir, auto_reconcile=False)
    cat.close()

    assert new.exists(), "novo catalog.db deveria existir após migração"
    assert not legacy.exists(), "legacy deveria ter sido movido (não copiado)"
    assert _has_legacy_marker(new), (
        "novo path deve conter o marker do legado — "
        "garantia que rename moveu o arquivo (não criou vazio)"
    )

    # Schema novo também foi aplicado em cima do legado migrado.
    conn = sqlite3.connect(str(new))
    try:
        version_row = conn.execute(
            "SELECT value FROM _schema_meta WHERE key='catalog_version'"
        ).fetchone()
    finally:
        conn.close()
    assert version_row is not None
    assert version_row[0] == CATALOG_VERSION


@pytest.mark.unit
def test_no_migrate_when_only_new_exists(tmp_path: Path) -> None:
    """Apenas new existe → no-op (Catalog usa o existente normalmente)."""
    data_dir = tmp_path / "data"
    new = data_dir / "_internal" / "catalog.db"
    legacy = data_dir / "history" / "catalog.db"
    # First boot: cria new diretamente (ADR-024 path).
    cat1 = Catalog(db_path=new, data_dir=data_dir, auto_reconcile=False)
    cat1.close()
    assert new.exists()
    assert not legacy.exists()

    # Re-boot: migration helper deve ser no-op (nenhum legacy a migrar).
    cat2 = Catalog(db_path=new, data_dir=data_dir, auto_reconcile=False)
    cat2.close()
    assert new.exists()
    assert not legacy.exists()


@pytest.mark.unit
def test_kept_new_when_both_exist(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Ambos existem → preserva NEW + emite log warning (regra ADR-024)."""
    data_dir = tmp_path / "data"
    legacy = data_dir / "history" / "catalog.db"
    new = data_dir / "_internal" / "catalog.db"

    # Seed: legacy com marker; new com marker DIFERENTE (vazio mas válido).
    _seed_legacy_db(legacy)
    new.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(new))
    try:
        conn.execute("CREATE TABLE _new_marker (val TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO _new_marker VALUES ('post_migration')")
        conn.commit()
    finally:
        conn.close()

    new_size_before = new.stat().st_size
    legacy_size_before = legacy.stat().st_size

    with caplog.at_level(logging.WARNING, logger="data_downloader.storage.catalog"):
        _migrate_legacy_catalog_path(data_dir, new)

    # NEW preservado (não foi sobrescrito); LEGACY também preservado para
    # que admin possa investigar/excluir manualmente.
    assert new.exists()
    assert legacy.exists()
    assert new.stat().st_size == new_size_before
    assert legacy.stat().st_size == legacy_size_before

    # Log warning emitido com event apropriado.
    legacy_kept_logs = [r for r in caplog.records if "catalog_legacy_path_kept" in r.getMessage()]
    assert legacy_kept_logs, "esperado log 'catalog_legacy_path_kept' quando ambos paths existem"


@pytest.mark.unit
def test_no_op_when_neither_exists(tmp_path: Path) -> None:
    """Nenhum path existe → Catalog cria limpo no NEW (no migration)."""
    data_dir = tmp_path / "data"
    new = data_dir / "_internal" / "catalog.db"
    legacy = data_dir / "history" / "catalog.db"
    assert not new.exists()
    assert not legacy.exists()

    cat = Catalog(db_path=new, data_dir=data_dir, auto_reconcile=False)
    cat.close()

    assert new.exists()
    assert not legacy.exists()
    # Schema fresh (sem marker legado).
    assert not _has_legacy_marker(new)


@pytest.mark.unit
def test_wal_shm_aux_files_migrated(tmp_path: Path) -> None:
    """WAL/SHM auxiliares (.db-wal, .db-shm) também são movidos."""
    data_dir = tmp_path / "data"
    legacy = data_dir / "history" / "catalog.db"
    new = data_dir / "_internal" / "catalog.db"
    _seed_legacy_db(legacy)

    legacy_wal = legacy.with_suffix(".db-wal")
    legacy_shm = legacy.with_suffix(".db-shm")
    legacy_wal.write_bytes(b"WAL_STUB" + b"\x00" * 32)
    legacy_shm.write_bytes(b"SHM_STUB" + b"\x00" * 32)
    assert legacy_wal.exists() and legacy_shm.exists()

    _migrate_legacy_catalog_path(data_dir, new)

    new_wal = new.with_suffix(".db-wal")
    new_shm = new.with_suffix(".db-shm")
    assert new_wal.exists(), "WAL deveria ter sido movido"
    assert new_shm.exists(), "SHM deveria ter sido movido"
    assert not legacy_wal.exists(), "WAL legacy deveria ter sido removido (rename)"
    assert not legacy_shm.exists(), "SHM legacy deveria ter sido removido (rename)"
    # Conteúdo preservado (rename, não recriado).
    assert new_wal.read_bytes().startswith(b"WAL_STUB")
    assert new_shm.read_bytes().startswith(b"SHM_STUB")


@pytest.mark.unit
def test_caller_using_legacy_path_is_no_op(tmp_path: Path) -> None:
    """Caller passando ``data/history/catalog.db`` explicitamente não dispara
    migração (defensivo — preserva backward-compat se UI ainda usa legacy).

    Cenário: módulo legado ainda instancia ``Catalog(db_path=data/history/catalog.db)``.
    Migration helper detecta que old==new e sai. Catalog opera normalmente
    no path legado — sem auto-mover, sem perda de dados.
    """
    data_dir = tmp_path / "data"
    legacy = data_dir / "history" / "catalog.db"
    _seed_legacy_db(legacy)

    cat = Catalog(db_path=legacy, data_dir=data_dir, auto_reconcile=False)
    cat.close()

    # Legacy permanece; nada criado em _internal/.
    assert legacy.exists()
    new = data_dir / "_internal" / "catalog.db"
    assert not new.exists()
    assert _has_legacy_marker(legacy)
