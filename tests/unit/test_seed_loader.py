"""Unit tests — orchestrator.contracts.populate_contracts_from_seed (Story 1.6 AC5 / Subtask 6.3).

Cobertura:

- Default seed (``docs/storage/CONTRACTS.md``) carrega N contratos sem erro.
- Idempotência: rodar 2x não duplica linhas (UPSERT por chave primária).
- Seed customizado (tmp file) com formato YAML embutido.
- Erros: arquivo ausente, YAML sem chave ``contracts:``, entrada sem
  campos obrigatórios.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_downloader.orchestrator.contracts import (
    DEFAULT_SEED_PATH,
    list_contracts,
    populate_contracts_from_seed,
)
from data_downloader.storage.catalog import Catalog


@pytest.fixture
def empty_catalog(tmp_path: Path) -> Catalog:
    return Catalog(db_path=tmp_path / "data" / "history" / "catalog.db")


@pytest.mark.unit
def test_seed_loader_default_path_exists() -> None:
    """``DEFAULT_SEED_PATH`` aponta para CONTRACTS.md de fato no repo."""
    assert (
        DEFAULT_SEED_PATH.exists()
    ), f"Esperado encontrar {DEFAULT_SEED_PATH} — Sol garantiu via Story 0.0/1.6."


@pytest.mark.unit
def test_seed_loader_loads_default(empty_catalog: Catalog) -> None:
    """Carrega seed default — N >= 3 contratos (WDOH26/WDOJ26/WDOK26 + WIN/equities)."""
    count = populate_contracts_from_seed(empty_catalog)
    assert count >= 3
    rows = list_contracts(empty_catalog, root="WDO")
    codes = {r.contract_code for r in rows}
    assert {"WDOH26", "WDOJ26", "WDOK26"} <= codes
    empty_catalog.close()


@pytest.mark.unit
def test_seed_loader_is_idempotent(empty_catalog: Catalog) -> None:
    """Rodar 2x não duplica linhas (UPSERT por (symbol_root, contract_code))."""
    n1 = populate_contracts_from_seed(empty_catalog)
    rows1 = list_contracts(empty_catalog)
    n2 = populate_contracts_from_seed(empty_catalog)
    rows2 = list_contracts(empty_catalog)
    assert n1 == n2
    assert len(rows1) == len(rows2)
    empty_catalog.close()


@pytest.mark.unit
def test_seed_loader_custom_file(empty_catalog: Catalog, tmp_path: Path) -> None:
    """Aceita seed_path explícito; YAML mínimo deve funcionar."""
    seed = tmp_path / "custom.md"
    seed.write_text(
        "# custom seed\n\n"
        "```yaml\n"
        "contracts:\n"
        "  - symbol_root: WDO\n"
        "    contract_code: WDOM27\n"
        "    vigent_from: 2027-04-29\n"
        "    vigent_until: 2027-05-29\n"
        "    validation_source: hypothesized\n"
        '    notes: "Custom test entry"\n'
        "```\n",
        encoding="utf-8",
    )
    n = populate_contracts_from_seed(empty_catalog, seed_path=seed)
    assert n == 1
    rows = list_contracts(empty_catalog, root="WDO")
    assert len(rows) == 1
    assert rows[0].contract_code == "WDOM27"
    assert rows[0].notes == "Custom test entry"
    empty_catalog.close()


@pytest.mark.unit
def test_seed_loader_missing_file_raises(empty_catalog: Catalog, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        populate_contracts_from_seed(empty_catalog, seed_path=tmp_path / "nope.md")
    empty_catalog.close()


@pytest.mark.unit
def test_seed_loader_no_yaml_block_raises(empty_catalog: Catalog, tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("# no yaml here\nplain text\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No YAML block"):
        populate_contracts_from_seed(empty_catalog, seed_path=bad)
    empty_catalog.close()


@pytest.mark.unit
def test_seed_loader_missing_required_keys_raises(empty_catalog: Catalog, tmp_path: Path) -> None:
    bad = tmp_path / "incomplete.md"
    bad.write_text(
        "```yaml\n" "contracts:\n" "  - symbol_root: WDO\n" "    contract_code: WDOJ26\n" "```\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required keys"):
        populate_contracts_from_seed(empty_catalog, seed_path=bad)
    empty_catalog.close()
