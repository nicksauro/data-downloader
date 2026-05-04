"""Unit tests — storage.sqlite_profiles (Story 2.8 / COUNCIL-21).

Cobertura:

- 3 perfis canônicos aplicam PRAGMAs corretos.
- Resolução por env var ``DATA_DOWNLOADER_SQLITE_PROFILE``.
- Precedência: explicit > env var > default.
- Nome inválido = ``ValueError`` com mensagem útil.
- ``apply_profile`` é idempotente.
- ``describe_profile`` retorna snapshot serializável.
"""

from __future__ import annotations

import sqlite3

import pytest

from data_downloader.storage.sqlite_profiles import (
    DEFAULT_PROFILE,
    ENV_PROFILE,
    SQLITE_PROFILES,
    SQLiteProfile,
    apply_profile,
    describe_profile,
    resolve_profile,
)


@pytest.fixture
def in_memory_conn() -> sqlite3.Connection:
    """Conexão SQLite em memória para inspeção de PRAGMAs."""
    return sqlite3.connect(":memory:")


# ---------------------------------------------------------------------------
# Profile registry — invariantes sobre os 3 perfis canônicos
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_three_canonical_profiles_exist() -> None:
    """Story 2.8 AC3 — 3 perfis canônicos: low_memory / default / aggressive."""
    expected = {"low_memory", "default", "aggressive"}
    assert set(SQLITE_PROFILES) == expected


@pytest.mark.unit
def test_default_profile_is_default_constant() -> None:
    """``DEFAULT_PROFILE`` é o ``default`` do registry (alias estável)."""
    assert DEFAULT_PROFILE is SQLITE_PROFILES["default"]
    assert DEFAULT_PROFILE.name == "default"


@pytest.mark.unit
def test_low_memory_profile_values() -> None:
    """``low_memory`` = 10 MB cache + 16 MB mmap (CI / containers)."""
    p = SQLITE_PROFILES["low_memory"]
    assert p.cache_size == -10_000  # 10 MB negative-KiB convention
    assert p.mmap_size == 16 * 1024 * 1024
    assert p.journal_mode == "WAL"
    assert p.synchronous == "NORMAL"


@pytest.mark.unit
def test_default_profile_values() -> None:
    """``default`` = 50 MB cache + 64 MB mmap (M6-reduzido baseline)."""
    p = SQLITE_PROFILES["default"]
    assert p.cache_size == -50_000  # 50 MB
    assert p.mmap_size == 64 * 1024 * 1024


@pytest.mark.unit
def test_aggressive_profile_values() -> None:
    """``aggressive`` = 200 MB cache + 256 MB mmap (workstation high-end)."""
    p = SQLITE_PROFILES["aggressive"]
    assert p.cache_size == -200_000  # 200 MB
    assert p.mmap_size == 256 * 1024 * 1024


@pytest.mark.unit
def test_profile_is_frozen_immutable() -> None:
    """``SQLiteProfile`` é ``frozen`` — protege constantes globais."""
    p = SQLITE_PROFILES["default"]
    with pytest.raises(AttributeError):
        p.cache_size = -1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# apply_profile — PRAGMAs aplicados correspondem ao perfil
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("profile_name", ["low_memory", "default", "aggressive"])
def test_apply_profile_sets_correct_pragmas(
    profile_name: str, in_memory_conn: sqlite3.Connection
) -> None:
    """Cada perfil aplica seus PRAGMAs literalmente (cache_size, mmap_size).

    NOTA: ``mmap_size`` em :memory: pode reportar 0 (kernel não permite mmap
    em memória). Validamos somente ``cache_size`` (per-connection) +
    invariantes não-numéricas. ``mmap_size`` é validado em
    ``test_catalog_with_profiles`` integration sobre arquivo real.
    """
    profile = SQLITE_PROFILES[profile_name]
    apply_profile(in_memory_conn, profile)

    cache_size = in_memory_conn.execute("PRAGMA cache_size").fetchone()[0]
    foreign_keys = in_memory_conn.execute("PRAGMA foreign_keys").fetchone()[0]
    temp_store = in_memory_conn.execute("PRAGMA temp_store").fetchone()[0]
    synchronous = in_memory_conn.execute("PRAGMA synchronous").fetchone()[0]

    assert int(cache_size) == profile.cache_size
    assert int(foreign_keys) == 1  # invariante — sempre ON
    assert int(temp_store) == 2  # MEMORY
    assert int(synchronous) == 1  # NORMAL


@pytest.mark.unit
def test_apply_profile_is_idempotent(in_memory_conn: sqlite3.Connection) -> None:
    """Aplicar o mesmo perfil duas vezes não muda estado nem levanta."""
    p = SQLITE_PROFILES["default"]
    apply_profile(in_memory_conn, p)
    cache_first = in_memory_conn.execute("PRAGMA cache_size").fetchone()[0]
    apply_profile(in_memory_conn, p)
    cache_second = in_memory_conn.execute("PRAGMA cache_size").fetchone()[0]
    assert cache_first == cache_second == p.cache_size


# ---------------------------------------------------------------------------
# resolve_profile — precedência explicit > env > default
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_profile_default_when_nothing_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem argumento e sem env var = ``DEFAULT_PROFILE``."""
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    assert resolve_profile() is DEFAULT_PROFILE


@pytest.mark.unit
@pytest.mark.parametrize("name", ["low_memory", "default", "aggressive"])
def test_resolve_profile_via_env_var(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var ``DATA_DOWNLOADER_SQLITE_PROFILE`` resolve corretamente."""
    monkeypatch.setenv(ENV_PROFILE, name)
    resolved = resolve_profile()
    assert resolved.name == name
    assert resolved is SQLITE_PROFILES[name]


@pytest.mark.unit
def test_resolve_profile_env_var_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var é case-insensitive (UX — usuário não precisa lembrar caps)."""
    monkeypatch.setenv(ENV_PROFILE, "AGGRESSIVE")
    assert resolve_profile().name == "aggressive"


@pytest.mark.unit
def test_resolve_profile_env_var_strips_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tolera espaços acidentais na env var."""
    monkeypatch.setenv(ENV_PROFILE, "  low_memory  ")
    assert resolve_profile().name == "low_memory"


@pytest.mark.unit
def test_resolve_profile_explicit_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Argumento explícito vence a env var (precedência)."""
    monkeypatch.setenv(ENV_PROFILE, "low_memory")
    assert resolve_profile("aggressive").name == "aggressive"


@pytest.mark.unit
def test_resolve_profile_explicit_instance_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instância explícita é retornada inalterada (sem lookup)."""
    monkeypatch.setenv(ENV_PROFILE, "low_memory")
    custom = SQLiteProfile(name="custom", cache_size=-1234, mmap_size=42)
    assert resolve_profile(custom) is custom


@pytest.mark.unit
def test_resolve_profile_unknown_name_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nome inválido = ``ValueError`` com lista de opções válidas."""
    monkeypatch.delenv(ENV_PROFILE, raising=False)
    with pytest.raises(ValueError, match="unknown SQLite profile"):
        resolve_profile("turbo_max")


@pytest.mark.unit
def test_resolve_profile_unknown_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var com valor inválido = ``ValueError`` com source identificado."""
    monkeypatch.setenv(ENV_PROFILE, "hyperdrive")
    with pytest.raises(ValueError, match=ENV_PROFILE):
        resolve_profile()


# ---------------------------------------------------------------------------
# describe_profile — snapshot serializável
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_describe_profile_returns_serializable_dict() -> None:
    """``describe_profile`` retorna ``dict`` com chaves canônicas para audit/log."""
    snap = describe_profile(SQLITE_PROFILES["default"])
    assert snap["name"] == "default"
    # 50_000 KiB / 1024 = 48 MiB (integer division). SQLite convention é KiB exato;
    # rótulo "50 MB" é shorthand. describe_profile retorna MiB true.
    assert snap["cache_size_mb"] == 48
    assert snap["mmap_size_mb"] == 64
    assert snap["journal_mode"] == "WAL"


@pytest.mark.unit
def test_describe_profile_handles_positive_cache_size() -> None:
    """``cache_size > 0`` (páginas, não KiB) → ``cache_size_mb`` é ``None``."""
    pages_profile = SQLiteProfile(name="pages", cache_size=10_000, mmap_size=0)
    snap = describe_profile(pages_profile)
    assert snap["cache_size_mb"] is None
    assert snap["cache_size_raw"] == 10_000
