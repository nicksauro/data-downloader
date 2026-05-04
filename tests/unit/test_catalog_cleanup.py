"""Unit tests — storage.catalog cleanup_orphans (Story 1.5 AC7).

Cobertura:

- Test 1: cria tmp file > 5min atrás -> cleanup remove.
- Test 2: tmp file recém-criado -> preservado (write em curso).
- Test 3: arquivo não-tmp -> preservado.
- Test 4: cleanup em data_dir inexistente é no-op (não levanta).
- Test 5: cleanup retorna lista de paths removidos.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def catalog(data_dir: Path) -> Catalog:
    db_path = data_dir / "history" / "catalog.db"
    # Desliga init-side cleanup pra teste controlar manualmente.
    return Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )


def _make_tmp_file(path: Path, *, age_seconds: int) -> Path:
    """Cria arquivo .tmp.* com idade controlada (mtime no passado)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"junk")
    if age_seconds > 0:
        old = time.time() - age_seconds
        os.utime(path, (old, old))
    return path


@pytest.mark.unit
def test_cleanup_removes_old_tmp(catalog: Catalog, data_dir: Path) -> None:
    """Test 1: arquivo .tmp.* >5min é removido."""
    target = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet.tmp.deadbeef"
    _make_tmp_file(target, age_seconds=600)  # 10 min

    removed = catalog.cleanup_orphans()
    assert target in removed
    assert not target.exists()
    catalog.close()


@pytest.mark.unit
def test_cleanup_preserves_recent_tmp(catalog: Catalog, data_dir: Path) -> None:
    """Test 2: tmp recém-criado (<5min) é preservado (write em curso)."""
    target = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet.tmp.cafef00d"
    _make_tmp_file(target, age_seconds=10)  # 10s — fresco

    removed = catalog.cleanup_orphans()
    assert target not in removed
    assert target.exists()
    catalog.close()


@pytest.mark.unit
def test_cleanup_preserves_non_tmp_files(catalog: Catalog, data_dir: Path) -> None:
    """Test 3: arquivo não-.tmp.* nunca é removido."""
    parquet = data_dir / "history" / "F" / "WDOJ26" / "2026" / "03.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_bytes(b"PAR1real")
    # Mesmo sendo antigo.
    old = time.time() - 600
    os.utime(parquet, (old, old))

    removed = catalog.cleanup_orphans()
    assert parquet not in removed
    assert parquet.exists()
    catalog.close()


@pytest.mark.unit
def test_cleanup_in_missing_history_dir_is_noop(tmp_path: Path) -> None:
    """Test 4: data_dir/history vazio -> cleanup retorna [] sem levantar."""
    data_dir = tmp_path / "no_data_yet"
    db_path = data_dir / "history" / "catalog.db"
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        auto_reconcile=False,
        auto_cleanup_orphans=False,
    )
    # data_dir/history existe (foi criado para o catalog.db) mas está vazio
    # de partições / tmp files. Cleanup deve simplesmente retornar [].
    removed = cat.cleanup_orphans()
    assert removed == []
    cat.close()


@pytest.mark.unit
def test_cleanup_returns_list_of_removed(catalog: Catalog, data_dir: Path) -> None:
    """Test 5: retorno é list[Path] de arquivos removidos."""
    base = data_dir / "history" / "F" / "WDOJ26" / "2026"
    t1 = _make_tmp_file(base / "03.parquet.tmp.aaa", age_seconds=600)
    t2 = _make_tmp_file(base / "04.parquet.tmp.bbb", age_seconds=600)
    fresh = _make_tmp_file(base / "05.parquet.tmp.ccc", age_seconds=10)

    removed = catalog.cleanup_orphans()
    assert isinstance(removed, list)
    assert set(removed) == {t1, t2}
    assert fresh.exists()
    catalog.close()
