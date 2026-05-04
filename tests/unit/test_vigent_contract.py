"""Unit tests — orchestrator.contracts.vigent_contract (Story 1.6 AC2-AC4 / Subtask 6.2).

Cobertura:

- Lookup correto retorna ``contract_code`` esperado dentro da janela.
- :class:`InvalidContract` quando data está fora de qualquer janela.
- ``exchange`` inválido → ``ValueError`` (R8/Q05-V).
- Boundary days (``vigent_from`` exato, ``vigent_until`` exato) são
  considerados vigentes (inclusivo).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from data_downloader.orchestrator.contracts import vigent_contract
from data_downloader.public_api.exceptions import InvalidContract
from data_downloader.storage.catalog import Catalog


@pytest.fixture
def catalog_with_seed(tmp_path: Path) -> Catalog:
    """Catálogo com 3 contratos WDO inseridos diretamente via INSERT."""
    db_path = tmp_path / "data" / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            ("WDO", "WDOH26", "2026-01-29 00:00:00", "2026-02-26 00:00:00"),
            ("WDO", "WDOJ26", "2026-02-26 00:00:01", "2026-03-30 00:00:00"),
            ("WDO", "WDOK26", "2026-03-30 00:00:01", "2026-04-29 00:00:00"),
        ]
        for root, code, vf, vu in rows:
            conn.execute(
                "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
                "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'hypothesized')",
                (root, code, vf, vu),
            )
    return cat


@pytest.mark.unit
def test_vigent_contract_returns_in_window(catalog_with_seed: Catalog) -> None:
    """Data no meio da janela → contract correto."""
    assert vigent_contract(catalog_with_seed, "WDO", date(2026, 3, 15)) == "WDOJ26"
    assert vigent_contract(catalog_with_seed, "WDO", date(2026, 4, 10)) == "WDOK26"
    assert vigent_contract(catalog_with_seed, "WDO", date(2026, 2, 10)) == "WDOH26"
    catalog_with_seed.close()


@pytest.mark.unit
def test_vigent_contract_boundary_inclusive(catalog_with_seed: Catalog) -> None:
    """vigent_from e vigent_until são inclusivos (lookup BETWEEN)."""
    # vigent_from exato de WDOH26 (2026-01-29)
    assert vigent_contract(catalog_with_seed, "WDO", date(2026, 1, 29)) == "WDOH26"
    # vigent_until exato de WDOK26 (2026-04-29)
    assert vigent_contract(catalog_with_seed, "WDO", date(2026, 4, 29)) == "WDOK26"
    catalog_with_seed.close()


@pytest.mark.unit
def test_vigent_contract_raises_invalid_contract(catalog_with_seed: Catalog) -> None:
    """Data fora de qualquer janela → InvalidContract com campos preenchidos."""
    with pytest.raises(InvalidContract) as exc_info:
        vigent_contract(catalog_with_seed, "WDO", date(2027, 1, 1))
    err = exc_info.value
    assert err.symbol_root == "WDO"
    assert err.exchange == "F"
    assert err.details["symbol_root"] == "WDO"
    catalog_with_seed.close()


@pytest.mark.unit
def test_vigent_contract_unknown_root_raises(catalog_with_seed: Catalog) -> None:
    """Raiz inexistente no catálogo → InvalidContract."""
    with pytest.raises(InvalidContract):
        vigent_contract(catalog_with_seed, "UNKNOWN", date(2026, 3, 15))
    catalog_with_seed.close()


@pytest.mark.unit
def test_vigent_contract_invalid_exchange_raises(catalog_with_seed: Catalog) -> None:
    with pytest.raises(ValueError, match="exchange must be"):
        vigent_contract(catalog_with_seed, "WDO", date(2026, 3, 15), exchange="BMF")
    catalog_with_seed.close()


@pytest.mark.unit
def test_vigent_contract_accepts_datetime(catalog_with_seed: Catalog) -> None:
    """``date`` ou ``datetime`` são aceitos (datetime herda de date)."""
    dt = datetime(2026, 3, 15, 14, 30, 0)
    assert vigent_contract(catalog_with_seed, "WDO", dt) == "WDOJ26"
    catalog_with_seed.close()
