"""Integration tests — Catalog x SQLite profiles (Story 2.8 / COUNCIL-21).

Cobertura:

- Catalog aceita ``sqlite_profile=...`` argumento.
- Env var ``DATA_DOWNLOADER_SQLITE_PROFILE`` é honrada.
- Argumento explícito vence env var.
- ``cache_size`` aplicado em conexão real é o do perfil.
- ``mmap_size`` aplicado em arquivo real (não :memory:).
- CRUD básico (register_partition + get_completed_partitions) funciona
  para todos os 3 perfis — preserva idempotência R5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.parquet_writer import WriteResult
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.sqlite_profiles import (
    ENV_PROFILE,
    SQLITE_PROFILES,
    SQLiteProfile,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    return data_dir / "history" / "catalog.db"


def _read_pragma(cat: Catalog, name: str) -> int:
    """Lê PRAGMA inteiro da conexão real do catálogo."""
    conn = cat._conn_or_raise()
    return int(conn.execute(f"PRAGMA {name}").fetchone()[0])


# ---------------------------------------------------------------------------
# Profile aplicado via argumento explícito
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("profile_name", ["low_memory", "default", "aggressive"])
def test_catalog_accepts_profile_by_name(
    profile_name: str,
    db_path: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog aceita nome string de perfil — aplica PRAGMAs correspondentes."""
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    expected = SQLITE_PROFILES[profile_name]
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        sqlite_profile=profile_name,
        auto_reconcile=False,
    )
    try:
        assert _read_pragma(cat, "cache_size") == expected.cache_size
    finally:
        cat.close()


@pytest.mark.integration
def test_catalog_accepts_profile_instance(
    db_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog aceita instância ``SQLiteProfile`` direta."""
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    custom = SQLiteProfile(name="custom_test", cache_size=-12_345, mmap_size=8 * 1024 * 1024)
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        sqlite_profile=custom,
        auto_reconcile=False,
    )
    try:
        assert _read_pragma(cat, "cache_size") == -12_345
    finally:
        cat.close()


# ---------------------------------------------------------------------------
# Profile via env var
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("profile_name", ["low_memory", "default", "aggressive"])
def test_catalog_honors_env_var(
    profile_name: str,
    db_path: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DATA_DOWNLOADER_SQLITE_PROFILE`` selecionado quando arg não fornecido."""
    monkeypatch.setenv(ENV_PROFILE, profile_name)
    expected = SQLITE_PROFILES[profile_name]
    cat = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    try:
        assert _read_pragma(cat, "cache_size") == expected.cache_size
    finally:
        cat.close()


@pytest.mark.integration
def test_catalog_explicit_arg_overrides_env(
    db_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Argumento explícito vence env var (precedência R12)."""
    monkeypatch.setenv(ENV_PROFILE, "low_memory")
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        sqlite_profile="aggressive",
        auto_reconcile=False,
    )
    try:
        assert _read_pragma(cat, "cache_size") == SQLITE_PROFILES["aggressive"].cache_size
    finally:
        cat.close()


# ---------------------------------------------------------------------------
# mmap_size aplicado em arquivo real (não :memory:)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("profile_name", ["low_memory", "default", "aggressive"])
def test_catalog_mmap_size_applied_on_file(
    profile_name: str,
    db_path: Path,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mmap_size`` é aplicado em DB-em-arquivo (Catalog real, não memória)."""
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    expected = SQLITE_PROFILES[profile_name]
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        sqlite_profile=profile_name,
        auto_reconcile=False,
    )
    try:
        actual = _read_pragma(cat, "mmap_size")
        assert actual == expected.mmap_size
    finally:
        cat.close()


# ---------------------------------------------------------------------------
# CRUD preservado por todos os perfis (R5 — idempotência intocada)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("profile_name", ["low_memory", "default", "aggressive"])
def test_register_partition_idempotent_across_profiles(
    profile_name: str,
    db_path: Path,
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``register_partition`` UPSERT continua idempotente em qualquer perfil.

    Property: re-registrar a mesma partição duas vezes deixa apenas 1
    linha em ``partitions``. Profile não pode quebrar essa invariante.
    """
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    cat = Catalog(
        db_path=db_path,
        data_dir=data_dir,
        sqlite_profile=profile_name,
        auto_reconcile=False,
    )
    try:
        # Cria arquivo dummy (writer real escreveria em data_dir/history/...).
        partition_dir = data_dir / "history" / "F" / "WDOJ26" / "2026"
        partition_dir.mkdir(parents=True, exist_ok=True)
        parquet_path = partition_dir / "04.parquet"
        parquet_path.write_bytes(b"PAR1\x00\x00\x00\x00")  # placeholder

        partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2026, month=4)
        write_result = WriteResult(
            path=parquet_path,
            row_count=1234,
            first_ts_ns=1_700_000_000_000_000_000,
            last_ts_ns=1_700_000_000_999_999_999,
            checksum_sha256="a" * 64,
            file_size_bytes=parquet_path.stat().st_size,
        )

        cat.register_partition(write_result, partition)
        cat.register_partition(write_result, partition)  # idempotência

        partitions = cat.get_completed_partitions("WDOJ26", "F")
        assert len(partitions) == 1, f"profile {profile_name}: idempotency broken"
        assert partitions[0].row_count == 1234
        assert partitions[0].checksum_sha256 == "a" * 64
    finally:
        cat.close()


# ---------------------------------------------------------------------------
# Schema imutável independente do perfil
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_schema_identical_across_profiles(
    db_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schema do catálogo é idêntico para os 3 perfis (PRAGMAs ≠ DDL)."""
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    schemas: list[set[str]] = []
    for profile_name in ("low_memory", "default", "aggressive"):
        path = db_path.parent / f"{profile_name}.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        cat = Catalog(
            db_path=path,
            data_dir=data_dir,
            sqlite_profile=profile_name,
            auto_reconcile=False,
        )
        try:
            conn = cat._conn_or_raise()
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            schemas.append(tables)
        finally:
            cat.close()
    assert schemas[0] == schemas[1] == schemas[2]


# ---------------------------------------------------------------------------
# Defesa: timestamp de teste estável (informativo)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
