"""data_downloader.storage.migrations._registry — descoberta + path planning.

Owner: Sol (policy) | Impl: Dex.
Refs:

- Story 2.3 — AC1 (regex de nome estrito + rejeição clara).
- ``docs/storage/MIGRATIONS.md`` §1 (estrutura de diretório).

Registry descobre migrations no diretório ``parquet/`` por convenção de
nome (regex ``v\\d+_\\d+_\\d+_to_v\\d+_\\d+_\\d+\\.py``), valida cada
módulo, e expõe ``find_path(from, to)`` para planejamento de migrações
multi-step (V1: linear path apenas — DAG com forks futuro).

Uso típico::

    from data_downloader.storage.migrations._registry import (
        MigrationRegistry,
    )
    reg = MigrationRegistry.discover()
    path = reg.find_path("1.0.0", "1.1.0")  # -> [V100ToV110()]
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path

from data_downloader.storage.migrations._base import Migration

# Regex AC1 — nome estrito v{from}_to_v{to}.py
_FILENAME_RE = re.compile(r"^v(\d+)_(\d+)_(\d+)_to_v(\d+)_(\d+)_(\d+)\.py$")
_SQL_FILENAME_RE = re.compile(r"^v(\d+)_(\d+)_(\d+)_to_v(\d+)_(\d+)_(\d+)\.sql$")


@dataclass(frozen=True)
class _MigrationKey:
    """Chave canônica (from, to) para indexação no registry."""

    from_version: str
    to_version: str


@dataclass
class MigrationRegistry:
    """Registry de migrations descobertas por convenção de nome.

    Não armazena estado mutável de runtime (resultados de execução vão
    para ``MigrationLog`` em ``_runner.py``). Apenas indexa migrations
    disponíveis no diretório ``parquet/``.

    Atributos:
        migrations: Mapa ``(from_version, to_version) -> Migration``.
        invalid_files: Lista de arquivos que NÃO seguiram a convenção
            (ignorados; expostos para diagnóstico/CLI).
    """

    migrations: dict[tuple[str, str], Migration] = field(default_factory=dict)
    invalid_files: list[str] = field(default_factory=list)

    @classmethod
    def discover(cls, parquet_dir: Path | None = None) -> MigrationRegistry:
        """Descobre migrations no diretório ``parquet/``.

        Args:
            parquet_dir: Override do path de descoberta (testes).
                Default: subdiretório ``parquet/`` do pacote ``migrations``.

        Returns:
            ``MigrationRegistry`` populado.
        """
        if parquet_dir is None:
            parquet_dir = Path(__file__).resolve().parent / "parquet"
        registry = cls()
        if not parquet_dir.exists() or not parquet_dir.is_dir():
            return registry

        for file in sorted(parquet_dir.iterdir()):
            if file.name.startswith("_") or not file.name.endswith(".py"):
                continue
            if not _FILENAME_RE.match(file.name):
                # AC1 — registry rejeita com mensagem clara.
                registry.invalid_files.append(file.name)
                continue
            mod = _import_module_from_file(file, parquet_dir)
            mod_name = getattr(mod, "__name__", "")
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, Migration)
                    and obj is not Migration
                    and not obj.__name__.startswith("_")
                    # Skip ParquetMigration mixin (vem de _base, não do módulo descoberto).
                    and obj.__module__ == mod_name
                ):
                    instance = obj()
                    registry.register(instance)
        return registry

    def register(self, migration: Migration) -> None:
        """Registra uma migration. Última registrada por (from,to) ganha."""
        if not migration.from_version or not migration.to_version:
            raise ValueError(
                f"Migration {type(migration).__name__} sem from_version/to_version definidos."
            )
        key = (migration.from_version, migration.to_version)
        self.migrations[key] = migration

    def get(self, from_version: str, to_version: str) -> Migration | None:
        """Lookup direto por par (from, to)."""
        return self.migrations.get((from_version, to_version))

    def find_path(self, from_version: str, to_version: str) -> list[Migration]:
        """Calcula path linear de migrations (BFS sobre DAG).

        V1: assume DAG sem ciclos e busca o caminho mais curto. Para
        evolução em chain (1.0.0 -> 1.1.0 -> 1.2.0), basta haver
        migrations registradas para cada hop.

        Args:
            from_version: Versão atual.
            to_version: Versão alvo.

        Returns:
            Lista ordenada de migrations a aplicar. Vazia se
            ``from_version == to_version`` (no-op).

        Raises:
            ValueError: Não há path entre as versões.
        """
        if from_version == to_version:
            return []

        # BFS — cada nó é uma versão.
        from collections import deque

        adj: dict[str, list[tuple[str, Migration]]] = {}
        for (frm, to), mig in self.migrations.items():
            adj.setdefault(frm, []).append((to, mig))

        # Detecção de ciclo simples (Story V1: linear; futuro DAG).
        # BFS já evita re-visitar, então ciclos não causam loop infinito.
        queue: deque[tuple[str, list[Migration]]] = deque([(from_version, [])])
        visited: set[str] = {from_version}
        while queue:
            current, chain = queue.popleft()
            for next_version, mig in adj.get(current, ()):
                new_chain = [*chain, mig]
                if next_version == to_version:
                    return new_chain
                if next_version not in visited:
                    visited.add(next_version)
                    queue.append((next_version, new_chain))

        raise ValueError(
            f"No migration path from {from_version} to {to_version}. "
            f"Migrations disponíveis: {sorted(self.migrations.keys())}"
        )

    def __len__(self) -> int:
        return len(self.migrations)


def _import_module_from_file(file: Path, base: Path) -> object:
    """Importa um arquivo .py como módulo Python.

    Usa ``importlib.import_module`` quando o pacote já está instalado
    (caso normal); fallback para ``importlib.util.spec_from_file_location``
    em testes que apontam para diretório fora do pacote.
    """
    # Tenta import via pacote canônico.
    pkg_root = "data_downloader.storage.migrations.parquet"
    expected_path = (Path(__file__).resolve().parent / "parquet" / file.name).resolve()
    if file.resolve() == expected_path:
        return importlib.import_module(f"{pkg_root}.{file.stem}")

    # Fallback: import por path absoluto (testes).
    spec = importlib.util.spec_from_file_location(f"_dyn_migration_{file.stem}", file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load spec for {file}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover_catalog_migrations(catalog_dir: Path | None = None) -> list[tuple[str, str, Path]]:
    """Descobre migrations SQL de catálogo em ``catalog/``.

    Returns:
        Lista de ``(from_version, to_version, sql_path)`` ordenada por
        ``from_version``.
    """
    if catalog_dir is None:
        catalog_dir = Path(__file__).resolve().parent / "catalog"
    out: list[tuple[str, str, Path]] = []
    if not catalog_dir.exists() or not catalog_dir.is_dir():
        return out
    for file in sorted(catalog_dir.iterdir()):
        if not file.is_file():
            continue
        m = _SQL_FILENAME_RE.match(file.name)
        if not m:
            continue
        from_v = ".".join(m.group(1, 2, 3))
        to_v = ".".join(m.group(4, 5, 6))
        out.append((from_v, to_v, file))
    return out


__all__ = [
    "MigrationRegistry",
    "discover_catalog_migrations",
]
