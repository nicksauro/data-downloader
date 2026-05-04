"""Unit tests — multi-asset contract resolution (Story 4.2 AC2 + AC4).

Cobertura:

- Seed expandido carrega 8 WIN (H/M/U/Z 26+27) + 6 equity (PETR4..ABEV3).
- ``vigent_contract("WIN", date)`` retorna H/M/U/Z conforme janela trimestral.
- ``vigent_contract("PETR4", any_date)`` retorna ``"PETR4"`` (vigência infinita).
- Boundary days WIN são inclusivos.
- Equity rollover entre vencimentos é absurdo (não acontece) — degenerado.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from data_downloader.orchestrator.contracts import (
    list_contracts,
    populate_contracts_from_seed,
    vigent_contract,
)
from data_downloader.public_api.exceptions import InvalidContract
from data_downloader.storage.catalog import Catalog

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def catalog_with_real_seed(tmp_path: Path) -> Catalog:
    """Catálogo com o seed real CONTRACTS.md (Story 4.2 v1.1.0).

    Carrega tudo: WDO + WIN H/M/U/Z 26+27 + 6 equities.
    """
    db_path = tmp_path / "data" / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    n_loaded = populate_contracts_from_seed(cat)
    assert n_loaded > 0
    return cat


# =====================================================================
# Seed loading — count assertions
# =====================================================================


@pytest.mark.unit
def test_seed_includes_8_win_contracts(catalog_with_real_seed: Catalog) -> None:
    """Story 4.2 AC2 — WIN H/M/U/Z para 2026 + 2027 (8 contratos)."""
    win_contracts = list_contracts(catalog_with_real_seed, root="WIN")
    codes = {c.contract_code for c in win_contracts}
    expected = {
        "WINH26",
        "WINM26",
        "WINU26",
        "WINZ26",
        "WINH27",
        "WINM27",
        "WINU27",
        "WINZ27",
    }
    assert expected <= codes, f"missing WIN contracts: {expected - codes}"
    catalog_with_real_seed.close()


@pytest.mark.unit
def test_seed_includes_6_equities(catalog_with_real_seed: Catalog) -> None:
    """Story 4.2 AC2 — PETR4 + VALE3 + ITUB4 + BBDC4 + BBAS3 + ABEV3."""
    expected_tickers = {"PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3"}
    for ticker in expected_tickers:
        contracts = list_contracts(catalog_with_real_seed, root=ticker)
        assert len(contracts) >= 1, f"equity {ticker} missing from seed"
        c = contracts[0]
        assert c.contract_code == ticker
        assert c.symbol_root == ticker
        # Vigência infinita
        assert c.vigent_from.year == 1900
        assert c.vigent_until.year == 9999
        assert c.validation_source == "manual"
    catalog_with_real_seed.close()


@pytest.mark.unit
def test_seed_win_validation_source_hypothesized(catalog_with_real_seed: Catalog) -> None:
    """Story 4.2 / Q18-OPEN — todas WIN entries são `hypothesized` até probe."""
    win_contracts = list_contracts(catalog_with_real_seed, root="WIN")
    for c in win_contracts:
        assert (
            c.validation_source == "hypothesized"
        ), f"{c.contract_code} expected hypothesized, got {c.validation_source}"
    catalog_with_real_seed.close()


# =====================================================================
# vigent_contract — WIN trimestral
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("on_date", "expected"),
    [
        # Mid-window WINH26 (mar/26)
        (date(2026, 2, 15), "WINH26"),
        # Mid-window WINM26 (jun/26)
        (date(2026, 5, 1), "WINM26"),
        # Mid-window WINU26 (set/26)
        (date(2026, 8, 15), "WINU26"),
        # Mid-window WINZ26 (dez/26)
        (date(2026, 11, 1), "WINZ26"),
        # Mid-window WINH27 (mar/27 — buffer)
        (date(2027, 2, 1), "WINH27"),
    ],
)
def test_vigent_contract_win_mid_window(
    catalog_with_real_seed: Catalog,
    on_date: date,
    expected: str,
) -> None:
    """Story 4.2 AC4 — vigent_contract WIN retorna H/M/U/Z correto."""
    assert vigent_contract(catalog_with_real_seed, "WIN", on_date) == expected
    catalog_with_real_seed.close()


@pytest.mark.unit
def test_vigent_contract_win_boundary_h_to_m(catalog_with_real_seed: Catalog) -> None:
    """Boundary WINH26 ↔ WINM26 (2026-03-18) — inclusivo."""
    # WINH26: vigent_from 2026-01-08, vigent_until 2026-03-18
    # WINM26: vigent_from 2026-03-18, vigent_until 2026-06-17
    # Em 2026-03-18 exato, ambos overlapam — vigent_contract usa
    # ORDER BY vigent_from DESC LIMIT 1, então WINM26 ganha.
    result = vigent_contract(catalog_with_real_seed, "WIN", date(2026, 3, 18))
    assert result == "WINM26"  # mais recente (vigent_from mais alto)
    catalog_with_real_seed.close()


@pytest.mark.unit
def test_vigent_contract_win_outside_range_raises(catalog_with_real_seed: Catalog) -> None:
    """Data fora de qualquer janela WIN → InvalidContract."""
    # 2025-12-01 — antes de WINH26 vigent_from (2026-01-08).
    with pytest.raises(InvalidContract):
        vigent_contract(catalog_with_real_seed, "WIN", date(2025, 12, 1))
    # 2028-01-01 — depois de WINZ27 vigent_until (2027-12-15).
    with pytest.raises(InvalidContract):
        vigent_contract(catalog_with_real_seed, "WIN", date(2028, 1, 1))
    catalog_with_real_seed.close()


# =====================================================================
# vigent_contract — Equity (vigência infinita)
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker",
    ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3"],
)
def test_vigent_contract_equity_returns_self(
    catalog_with_real_seed: Catalog,
    ticker: str,
) -> None:
    """Story 4.2 AC4 — equity vigente sempre retorna o próprio ticker.

    Equity precisa de exchange='B' (Bovespa, R8/Q05-V).
    """
    # Datas variadas — equity é sempre vigente.
    for on_date in (
        date(2020, 1, 1),
        date(2026, 5, 4),
        date(2030, 12, 31),
    ):
        result = vigent_contract(catalog_with_real_seed, ticker, on_date, exchange="B")
        assert result == ticker
    catalog_with_real_seed.close()


@pytest.mark.unit
def test_vigent_contract_equity_with_bmf_exchange_still_works(
    catalog_with_real_seed: Catalog,
) -> None:
    """``vigent_contract`` aceita exchange='F' OR 'B' — semântica de
    bolsa é validada na fronteira pública (download/probe), não no
    catálogo. Mas equity é semanticamente Bovespa — caller deve usar 'B'.
    """
    # Tabela atual `contracts` não armazena exchange; resolução via root.
    # Aceitar 'F' aqui é um teste de robustez do lookup (não significa
    # que PETR4 funcionaria em BMF — DLL retornaria NL_EXCHANGE_UNKNOWN).
    result = vigent_contract(catalog_with_real_seed, "PETR4", date(2026, 5, 4), exchange="F")
    assert result == "PETR4"
    catalog_with_real_seed.close()


# =====================================================================
# Seed integrity — re-load is idempotent (R-INV)
# =====================================================================


@pytest.mark.unit
def test_seed_idempotent_double_load(tmp_path: Path) -> None:
    """``populate_contracts_from_seed`` re-rodado não duplica linhas (Story 0.0)."""
    db_path = tmp_path / "data" / "history" / "catalog.db"
    cat = Catalog(db_path=db_path)
    n1 = populate_contracts_from_seed(cat)
    contracts_first = list_contracts(cat)
    n2 = populate_contracts_from_seed(cat)
    contracts_second = list_contracts(cat)

    assert n1 == n2  # mesmo count entries no seed
    assert len(contracts_first) == len(contracts_second)
    cat.close()


@pytest.mark.unit
def test_seed_total_count_is_at_least_17(catalog_with_real_seed: Catalog) -> None:
    """Story 4.2 sanity — seed tem >= 3 WDO + 8 WIN + 6 equity = 17 minimum.

    Permite Sol adicionar contratos extras (4.3+ pode adicionar futures
    distantes ou outros equities) sem quebrar este teste.
    """
    all_contracts = list_contracts(catalog_with_real_seed)
    assert len(all_contracts) >= 17, f"seed count {len(all_contracts)} < 17 minimum"
    catalog_with_real_seed.close()


# =====================================================================
# Asset class boundary checks
# =====================================================================


@pytest.mark.unit
def test_win_and_petr4_dont_overlap_in_root(catalog_with_real_seed: Catalog) -> None:
    """WIN e PETR4 são roots disjuntos — nenhum contrato com root ambíguo."""
    win_contracts = list_contracts(catalog_with_real_seed, root="WIN")
    petr_contracts = list_contracts(catalog_with_real_seed, root="PETR4")

    win_codes = {c.contract_code for c in win_contracts}
    petr_codes = {c.contract_code for c in petr_contracts}
    assert win_codes.isdisjoint(petr_codes)
    catalog_with_real_seed.close()


@pytest.mark.unit
def test_equity_validation_source_is_manual(catalog_with_real_seed: Catalog) -> None:
    """Story 4.2 AC2 — equity entries são `manual`, não `hypothesized`."""
    for ticker in ("PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3"):
        contracts = list_contracts(catalog_with_real_seed, root=ticker)
        for c in contracts:
            assert (
                c.validation_source == "manual"
            ), f"{c.contract_code} expected manual, got {c.validation_source}"
    catalog_with_real_seed.close()
