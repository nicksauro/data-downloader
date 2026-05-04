"""data_downloader.storage.sqlite_profiles — SQLite PRAGMA profiles (M6).

Owner: Sol (storage authority) + Pyro (perf authority) — mini-council
COUNCIL-21 (Story 2.8).
Refs:

- ``docs/storage/SCHEMA.md`` §5 — finding M6 (PRAGMAs hardcoded
  estouravam RAM em laptops 16GB).
- ``docs/decisions/COUNCIL-21-storage-pareto-defaults.md`` — decisão
  empírica via mini-council Sol+Pyro.
- ``docs/stories/2.8.story.md`` AC3 — perfil-adaptativo selecionável
  via env var.

Substitui PRAGMAs hardcoded de :mod:`data_downloader.storage.catalog`
por **3 perfis canônicos** selecionáveis em runtime:

================  ===========  ===========  ====================================
Profile           cache_size   mmap_size    Use case
================  ===========  ===========  ====================================
``low_memory``    -10000 (10MB)  16 MB     CI, containers <4GB, laptops loaded
``default``       -50000 (50MB)  64 MB     Atual M6-reduzido (Story 1.5)
``aggressive``    -200000 (200MB) 256 MB    Workstations >=32GB, dev high-end
================  ===========  ===========  ====================================

Selection precedence (high to low):

1. Argumento explícito ``profile=...`` no construtor de :class:`Catalog`.
2. Env var ``DATA_DOWNLOADER_SQLITE_PROFILE`` em
   ``{low_memory, default, aggressive}``.
3. Default (``"default"``).

Princípio Sol: schema do catálogo é IMUTÁVEL. PRAGMAs são tuning de
runtime — mudam o trade-off RAM/throughput sem tocar dado on-disk.
Trocar de profile a qualquer momento é seguro (só afeta cache da
sessão atual).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Final

_LOG = logging.getLogger(__name__)

# Env var canônica (R12 — sempre prefixar com DATA_DOWNLOADER_).
ENV_PROFILE: Final[str] = "DATA_DOWNLOADER_SQLITE_PROFILE"


@dataclass(frozen=True, slots=True)
class SQLiteProfile:
    """Perfil imutável de PRAGMAs SQLite.

    Os valores aplicados via :func:`apply_profile` correspondem
    diretamente às convenções SQLite:

    - ``cache_size`` negativo = KiB (ex: ``-50000`` = 50 MiB).
      Positivo = páginas (page_size default = 4096B).
    - ``mmap_size`` em bytes (ex: ``67_108_864`` = 64 MiB).
    - ``journal_mode``, ``synchronous``, ``temp_store`` aplicados
      literalmente (case-insensitive no SQLite).

    Atributos invariantes para todos os perfis (não configuráveis):
    ``foreign_keys = ON`` (sempre).
    """

    name: str
    cache_size: int
    """SQLite cache_size — negativo = KiB; positivo = páginas (page_size)."""

    mmap_size: int
    """SQLite mmap_size em bytes."""

    journal_mode: str = "WAL"
    """Modo de journal — WAL para concorrência reader/writer."""

    synchronous: str = "NORMAL"
    """Modo sync — NORMAL é Pareto WAL+durability."""

    temp_store: str = "MEMORY"
    """Onde sort/index temp residem. MEMORY evita IO temporário."""


# Perfis canônicos — versionados aqui, referenciados em SCHEMA.md.
SQLITE_PROFILES: Final[dict[str, SQLiteProfile]] = {
    "low_memory": SQLiteProfile(
        name="low_memory",
        cache_size=-10_000,  # 10 MB
        mmap_size=16 * 1024 * 1024,  # 16 MB
    ),
    "default": SQLiteProfile(
        name="default",
        cache_size=-50_000,  # 50 MB (M6-reduzido — Story 1.5 default atual)
        mmap_size=64 * 1024 * 1024,  # 64 MB
    ),
    "aggressive": SQLiteProfile(
        name="aggressive",
        cache_size=-200_000,  # 200 MB
        mmap_size=256 * 1024 * 1024,  # 256 MB
    ),
}

# Default explícito — referenciado por Catalog.__init__.
DEFAULT_PROFILE: Final[SQLiteProfile] = SQLITE_PROFILES["default"]


def resolve_profile(explicit: SQLiteProfile | str | None = None) -> SQLiteProfile:
    """Resolve perfil ativo aplicando precedência canônica.

    Precedência (alta → baixa):

    1. ``explicit`` argumento (instância ou nome string).
    2. Env var ``DATA_DOWNLOADER_SQLITE_PROFILE``.
    3. ``DEFAULT_PROFILE`` (``"default"``).

    Args:
        explicit: Instância ``SQLiteProfile``, nome canônico
            (``"low_memory"``, ``"default"``, ``"aggressive"``) ou
            ``None`` (cai pra env/default).

    Returns:
        ``SQLiteProfile`` selecionado.

    Raises:
        ValueError: nome não-canônico em ``explicit`` ou env var.
    """
    if isinstance(explicit, SQLiteProfile):
        return explicit
    if isinstance(explicit, str):
        return _lookup_or_raise(explicit, source="explicit argument")

    env_value = os.environ.get(ENV_PROFILE)
    if env_value:
        return _lookup_or_raise(env_value.strip(), source=f"env var {ENV_PROFILE}")

    return DEFAULT_PROFILE


def _lookup_or_raise(name: str, *, source: str) -> SQLiteProfile:
    """Busca perfil por nome canônico — raise com mensagem amigável se não existe."""
    key = name.lower()
    if key not in SQLITE_PROFILES:
        valid = sorted(SQLITE_PROFILES)
        raise ValueError(
            f"unknown SQLite profile {name!r} from {source}; " f"valid options: {valid}"
        )
    return SQLITE_PROFILES[key]


def apply_profile(conn: sqlite3.Connection, profile: SQLiteProfile) -> None:
    """Aplica PRAGMAs de ``profile`` em ``conn`` (idempotente).

    Aplica também invariantes não-configuráveis:

    - ``foreign_keys = ON``
    - ``cache_size``, ``mmap_size``, ``journal_mode``, ``synchronous``,
      ``temp_store`` do perfil.

    Args:
        conn: Conexão SQLite aberta.
        profile: Perfil a aplicar.

    Notes:
        ``journal_mode`` é uma instrução stateful (per-database), mas
        re-aplicar o mesmo modo é no-op no SQLite. Os demais PRAGMAs são
        per-connection.
    """
    # Order matters slightly: journal_mode primeiro (mais barato se já
    # aplicado), depois caches.
    conn.execute(f"PRAGMA journal_mode = {profile.journal_mode}")
    conn.execute(f"PRAGMA synchronous = {profile.synchronous}")
    conn.execute(f"PRAGMA cache_size = {profile.cache_size}")
    conn.execute(f"PRAGMA mmap_size = {profile.mmap_size}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA temp_store = {profile.temp_store}")

    _LOG.debug(
        "sqlite_profiles.applied",
        extra={
            "profile": profile.name,
            "cache_size": profile.cache_size,
            "mmap_size_mb": profile.mmap_size // (1024 * 1024),
        },
    )


def describe_profile(profile: SQLiteProfile) -> dict[str, object]:
    """Retorna snapshot serializável do perfil (para logs/audit).

    Args:
        profile: Perfil a descrever.

    Returns:
        ``dict`` com nome + valores legíveis (RAM em MB onde aplicável).
    """
    return {
        "name": profile.name,
        "cache_size_raw": profile.cache_size,
        "cache_size_mb": abs(profile.cache_size) // 1024 if profile.cache_size < 0 else None,
        "mmap_size_mb": profile.mmap_size // (1024 * 1024),
        "journal_mode": profile.journal_mode,
        "synchronous": profile.synchronous,
        "temp_store": profile.temp_store,
    }


__all__ = [
    "DEFAULT_PROFILE",
    "ENV_PROFILE",
    "SQLITE_PROFILES",
    "SQLiteProfile",
    "apply_profile",
    "describe_profile",
    "resolve_profile",
]
