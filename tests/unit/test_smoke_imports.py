"""Smoke imports — valida que o scaffolding (Story 1.1) é importável.

Satisfaz:
    - AC5  : ``pytest`` roda sem erro mesmo sem testes reais.
    - AC11 : ``pytest --collect-only`` retorna 0 erros (todos os módulos do
             scaffolding precisam ser importáveis sem side-effects).

Estes testes são intencionalmente triviais — a intenção é PEGAR sintaxe
quebrada / circular import / dependência faltando NO CI antes que Stories
seguintes acumulem dívida.
"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
def test_root_package_exposes_version() -> None:
    """``data_downloader.__version__`` existe e bate com a source-of-truth.

    Não enrijece um literal — deriva da constante canônica
    ``_PACKAGE_VERSION`` (que por sua vez é mantida em sync com
    ``pyproject.toml::project.version``). Isso evita a regressão recorrente
    de o teste travar numa versão antiga após cada bump.
    """
    from data_downloader import _PACKAGE_VERSION, __version__

    assert isinstance(__version__, str)
    assert __version__ == _PACKAGE_VERSION


@pytest.mark.smoke
def test_public_api_exposes_api_version() -> None:
    """``public_api.__api_version__`` existe (ADR-007a — SemVer da API pública)."""
    from data_downloader.public_api import __api_version__

    assert isinstance(__api_version__, str)
    # Story 1.5b — bumpado para 0.2.0 ao adicionar read/read_continuous/vigent_contract.
    # Story 1.7b — bumpado para 0.3.0 ao adicionar download/DownloadHandle (minor aditivo).
    # Story 2.11 — bumpado para 0.4.0.
    # Story 4.3 — bumpado para 1.0.0 (V1.0 stable release).
    assert __api_version__ == "1.0.0"


@pytest.mark.smoke
def test_subpackages_importable() -> None:
    """Cada subpacote do scaffolding é importável sem side-effects."""
    import data_downloader.contracts
    import data_downloader.dll
    import data_downloader.orchestrator
    import data_downloader.public_api
    import data_downloader.storage
    import data_downloader.ui

    # Touch para silenciar linter "imported but unused".
    for mod in (
        data_downloader.contracts,
        data_downloader.dll,
        data_downloader.orchestrator,
        data_downloader.public_api,
        data_downloader.storage,
        data_downloader.ui,
    ):
        assert mod.__doc__, f"{mod.__name__} sem docstring de propósito (AC3)"


@pytest.mark.smoke
def test_dll_get_dll_version_stub() -> None:
    """``dll.get_dll_version`` retorna sentinela enquanto Story 1.2 não chega.

    AC12 — campo ``dll_version`` do schema Sol (SCHEMA.md §1, NOT NULL) tem um
    valor estável em builds sem DLL real.
    """
    from data_downloader.dll import get_dll_version

    version = get_dll_version()
    assert isinstance(version, str)
    assert version == "0.0.0+stub"


@pytest.mark.smoke
def test_cli_app_importable() -> None:
    """O entry point Typer ``data_downloader.cli:app`` carrega."""
    from data_downloader.cli import app

    assert app.info.name == "data-downloader"
