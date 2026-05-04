"""Guardrail anti-leak — tests consumer não importam de internals.

Owner: Aria (architect — fronteira pública) + Dex (impl).
Story 4.3 — AC7 (parte regression SemVer).

AST-scan de todos os arquivos ``tests/integration/test_public_api_*.py``
garante que NENHUM teste consumer importa de namespaces privados:

- ``data_downloader.dll.*``
- ``data_downloader.storage.*`` (exceto ``storage.catalog`` — exposto
  intencionalmente por enquanto até refactor V1.x mover Catalog para
  ``public_api`` ou ``data_downloader.testing``)
- ``data_downloader.orchestrator.*``
- ``data_downloader._internal.*``

Razão: testes consumer servem como **referência canônica** de uso da
API pública. Se um test consumer importa internals, vira "exemplo" para
consumers reais — vaza fronteira por imitação. Falha aqui = bug
constitucional (Article IV — No Invention).

Exceção controlada (whitelist):

- ``data_downloader.storage.catalog.Catalog`` — necessário para
  ``read_continuous(catalog=...)`` enquanto não há factory pública.
- ``data_downloader.public_api.handle.DownloadResult`` — alias re-export
  (já em ``__all__`` da fronteira; OK importar via path direto também).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
CONSUMER_TEST_GLOB = "test_public_api_*.py"

# Prefixos de modules privados — proibidos em tests consumer.
FORBIDDEN_PREFIXES = (
    "data_downloader.dll",
    "data_downloader.orchestrator",
    "data_downloader._internal",
)

# Storage é semi-privado. Whitelist explícita para setup de fixtures
# legados que pré-datam Story 4.3 (test_public_api_history.py existente).
# Quando V1.x publicar fixtures canônicas em data_downloader.testing
# (ADR-014 §6 — `synthetic_trades_factory`, `tmp_catalog`), reduzir
# whitelist a apenas storage.catalog.
STORAGE_WHITELIST = {
    "data_downloader.storage.catalog",  # Catalog é arg de read_continuous/vigent_contract
    # Legacy fixture setup — TODO V1.x: migrar para data_downloader.testing.fixtures
    "data_downloader.storage.parquet_writer",
    "data_downloader.storage.partition",
    "data_downloader.storage.schema",
}


def _collect_consumer_test_files() -> list[Path]:
    """Encontra todos os tests consumer (path test_public_api_*)."""
    return sorted(TESTS_DIR.glob(CONSUMER_TEST_GLOB))


def _extract_imports(file_path: Path) -> list[tuple[str, int]]:
    """AST-parse + extrai todos os módulos importados (com line number).

    Retorna lista de (module_path, lineno).
    """
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                # relative import (from . import x) — skip
                continue
            imports.append((node.module, node.lineno))
    return imports


def _is_forbidden(module: str) -> bool:
    """True se ``module`` viola a fronteira."""
    # Storage tem whitelist
    if module in STORAGE_WHITELIST:
        return False
    if module.startswith("data_downloader.storage"):
        # qualquer outro storage.* é forbidden até V1.x mover Catalog
        return True
    return any(module.startswith(p) for p in FORBIDDEN_PREFIXES)


# =====================================================================
# Tests
# =====================================================================


def test_consumer_test_files_exist() -> None:
    """Sanity: pelo menos 1 arquivo test_public_api_* existe."""
    files = _collect_consumer_test_files()
    assert len(files) >= 1, (
        f"Expected at least 1 consumer test file matching {CONSUMER_TEST_GLOB!r} " f"in {TESTS_DIR}"
    )


@pytest.mark.parametrize(
    "test_file",
    _collect_consumer_test_files(),
    ids=lambda p: p.name,
)
def test_no_forbidden_imports_in_consumer_test(test_file: Path) -> None:
    """Cada test consumer NÃO importa de modules privados.

    Falha lista TODOS os imports proibidos com path + line para correção.
    """
    imports = _extract_imports(test_file)
    violations: list[str] = []
    for module, lineno in imports:
        if _is_forbidden(module):
            violations.append(f"  {test_file.name}:{lineno} → {module}")

    assert not violations, (
        f"Consumer test {test_file.name} imports forbidden internal modules:\n"
        + "\n".join(violations)
        + "\n\nFix: import only from data_downloader.public_api (whitelist: "
        + ", ".join(sorted(STORAGE_WHITELIST))
        + ")"
    )


def test_extract_imports_handles_simple_module() -> None:
    """Sanity check do AST scanner — funciona em este arquivo."""
    self_path = Path(__file__)
    imports = _extract_imports(self_path)
    modules = {m for m, _ in imports}
    assert "ast" in modules
    assert "pathlib" in modules


def test_is_forbidden_classifier() -> None:
    """Sanity check da classificação."""
    # Forbidden prefixes — sempre bloqueados
    assert _is_forbidden("data_downloader.dll.wrapper")
    assert _is_forbidden("data_downloader.orchestrator.orchestrator")
    assert _is_forbidden("data_downloader._internal.exceptions")
    # Storage não-whitelisted é forbidden
    assert _is_forbidden("data_downloader.storage.duckdb_reader")
    assert _is_forbidden("data_downloader.storage.continuous_reader")
    # Whitelist (storage helpers permitidos durante V1.0)
    assert not _is_forbidden("data_downloader.storage.catalog")
    assert not _is_forbidden("data_downloader.storage.parquet_writer")
    assert not _is_forbidden("data_downloader.storage.partition")
    assert not _is_forbidden("data_downloader.storage.schema")
    # Public API — sempre OK
    assert not _is_forbidden("data_downloader.public_api")
    assert not _is_forbidden("data_downloader.public_api.handle")
    # Unrelated
    assert not _is_forbidden("pyarrow")
    assert not _is_forbidden("pytest")
