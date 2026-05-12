"""Integration tests — CLI ``contracts`` subcommands (Story 1.6 Subtask 6.x).

Cobertura:

- ``contracts list`` — vazio, com filtro, com seed.
- ``contracts add`` — UPSERT funciona, code formado corretamente.
- ``contracts vigent`` — retorna code; ``InvalidContract`` → exit 1.

Smoke (``contracts validate``) é testado em ``tests/smoke/test_probe.py``
(gated pelo env PROFITDLL_KEY) — aqui usamos ``CliRunner`` apenas para
comandos puros (sem DLL).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from data_downloader.cli import app
from data_downloader.orchestrator.contracts import populate_contracts_from_seed
from data_downloader.storage.catalog import Catalog


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Roda cada teste num cwd limpo (defesa contra poluição cross-test).

    O CLI resolve ``_DEFAULT_CATALOG_PATH`` (e o seed bundled) relativo ao
    cwd em alguns fallbacks; rodar num ``tmp_path`` garante que nenhum
    artefato deixado por outro módulo (ex.: ``data/_internal/catalog.db``
    populado) vaze para estes testes. Ver V1.1.0-FIX-PLAN task #13.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_catalog_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aponta o CLI para um catálogo temporário isolado.

    ADR-024: o catálogo canônico vive em ``data/_internal/catalog.db``.
    Aqui usamos um path absoluto sob ``tmp_path`` (independente do cwd).
    """
    db_path = tmp_path / "data" / "_internal" / "catalog.db"
    # monkey-patcheamos _open_catalog para apontar ao tmp_path absoluto.
    from data_downloader import cli as cli_mod

    real_open = cli_mod._open_catalog

    def fake_open(db_path_arg: Path | None = None) -> Catalog:
        return real_open(db_path=db_path)

    monkeypatch.setattr(cli_mod, "_open_catalog", fake_open)
    return db_path


@pytest.mark.integration
def test_cli_contracts_list_empty(
    runner: CliRunner, isolated_catalog_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """List vazio → mensagem 'Nenhum contrato cadastrado'.

    ``_open_catalog`` faz auto-populate do seed bundled (CONTRACTS.md) em
    first-run, então um catálogo "vazio" nunca permanece vazio na prática.
    Para exercitar o branch da mensagem amigável, neutralizamos o
    auto-populate (no-op). Ver V1.1.0-FIX-PLAN task #13 — a hipótese
    original de "poluição cwd/contracts.json" era incorreta; a causa real
    é o seed embutido.
    """
    import data_downloader.orchestrator.contracts as contracts_mod

    monkeypatch.setattr(contracts_mod, "populate_contracts_from_seed", lambda *a, **k: None)
    result = runner.invoke(app, ["contracts", "list"])
    assert result.exit_code == 0, result.output
    assert "Nenhum contrato cadastrado" in result.output


@pytest.mark.integration
def test_cli_contracts_list_with_seed(runner: CliRunner, isolated_catalog_path: Path) -> None:
    """Após populate seed, list mostra >= 3 contratos WDO."""
    cat = Catalog(db_path=isolated_catalog_path)
    populate_contracts_from_seed(cat)
    cat.close()

    result = runner.invoke(app, ["contracts", "list", "--root", "WDO"])
    assert result.exit_code == 0, result.output
    # Ricos formatam como tabela; checamos por código presente.
    assert "WDOJ26" in result.output
    assert "WDOH26" in result.output


@pytest.mark.integration
def test_cli_contracts_add(runner: CliRunner, isolated_catalog_path: Path) -> None:
    """Add insere contrato com código formado corretamente."""
    result = runner.invoke(app, ["contracts", "add", "WDO", "N", "26"])
    assert result.exit_code == 0, result.output
    assert "WDON26" in result.output
    # Confere via list.
    list_result = runner.invoke(app, ["contracts", "list", "--root", "WDO"])
    assert list_result.exit_code == 0
    assert "WDON26" in list_result.output


@pytest.mark.integration
def test_cli_contracts_add_invalid_letter(runner: CliRunner, isolated_catalog_path: Path) -> None:
    """Letra inválida (I) → exit 2."""
    result = runner.invoke(app, ["contracts", "add", "WDO", "I", "26"])
    assert result.exit_code == 2, result.output


@pytest.mark.integration
def test_cli_contracts_vigent_returns_code(runner: CliRunner, isolated_catalog_path: Path) -> None:
    """Vigent retorna código quando contrato existe."""
    cat = Catalog(db_path=isolated_catalog_path)
    populate_contracts_from_seed(cat)
    cat.close()

    result = runner.invoke(app, ["contracts", "vigent", "WDO", "2026-03-15"])
    assert result.exit_code == 0, result.output
    # WDOJ26 cobre 2026-02-26 .. 2026-03-30 no seed.
    assert "WDOJ26" in result.output


@pytest.mark.integration
def test_cli_contracts_vigent_invalid_date(runner: CliRunner, isolated_catalog_path: Path) -> None:
    """Data sem contrato → exit 1 + mensagem amigável."""
    cat = Catalog(db_path=isolated_catalog_path)
    populate_contracts_from_seed(cat)
    cat.close()

    result = runner.invoke(app, ["contracts", "vigent", "WDO", "2030-01-01"])
    assert result.exit_code == 1, result.output
    assert "Contrato fora do calendário" in result.output


@pytest.mark.integration
def test_cli_contracts_vigent_bad_iso_date(runner: CliRunner, isolated_catalog_path: Path) -> None:
    result = runner.invoke(app, ["contracts", "vigent", "WDO", "not-a-date"])
    assert result.exit_code == 2, result.output


@pytest.mark.integration
def test_cli_contracts_validate_missing_creds(
    runner: CliRunner, isolated_catalog_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem credenciais env → exit 3 com mensagem clara."""
    # Story v1.0.2 B2 (2026-05-05): naming canônico ``PROFITDLL_*``.
    # Mantemos delenv dos legados também para evitar contamination via
    # backwards-compat fallback (que casaria PROFIT_USER → PROFITDLL_USER).
    monkeypatch.delenv("PROFITDLL_KEY", raising=False)
    monkeypatch.delenv("PROFITDLL_USER", raising=False)
    monkeypatch.delenv("PROFITDLL_PASS", raising=False)
    monkeypatch.delenv("PROFIT_USER", raising=False)
    monkeypatch.delenv("PROFIT_PASS", raising=False)
    result = runner.invoke(app, ["contracts", "validate", "WDO", "WDOJ26"])
    assert result.exit_code == 3, result.output
    assert "Credenciais ausentes" in result.output


@pytest.mark.integration
def test_cli_version_still_works(runner: CliRunner) -> None:
    """Sanity: comando ``version`` não foi quebrado pela introdução do grupo."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "data-downloader" in result.output
