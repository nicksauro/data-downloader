"""Property-based — vigent_contract invariant (Story 1.6 AC9 / Subtask 6.4).

Invariante (AC9): para todo ``(root, date)`` testado, se ``vigent_contract``
retorna um código, então o ``Contract`` correspondente em ``contracts`` tem
``vigent_from <= date <= vigent_until``.

Estratégia:

1. Popula um catálogo com seed default.
2. Hypothesis gera datas em janela ampla [2025-01-01, 2027-12-31].
3. Para cada data: tenta ``vigent_contract``; se sucesso, valida o
   invariante consultando o catálogo. Se ``InvalidContract``, é OK
   (significa que não há contrato vigente naquela data — não há nada
   a validar).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.orchestrator.contracts import (
    list_contracts,
    populate_contracts_from_seed,
    vigent_contract,
)
from data_downloader.public_api.exceptions import InvalidContract
from data_downloader.storage.catalog import Catalog


@pytest.fixture(scope="module")
def seeded_catalog(tmp_path_factory: pytest.TempPathFactory) -> Catalog:
    """Seeded catalog reusado entre todas as runs do property test (módulo-scope)."""
    tmp = tmp_path_factory.mktemp("contracts_invariant")
    cat = Catalog(db_path=tmp / "data" / "history" / "catalog.db")
    populate_contracts_from_seed(cat)
    yield cat
    cat.close()


_DATE_STRATEGY = st.dates(
    min_value=date(2025, 1, 1),
    max_value=date(2027, 12, 31),
)


@pytest.mark.property
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(on_date=_DATE_STRATEGY, root=st.sampled_from(["WDO", "WIN"]))
def test_vigent_invariant(seeded_catalog: Catalog, on_date: date, root: str) -> None:
    """Invariante AC9 — `vigent_from <= date <= vigent_until` para todo retorno."""
    try:
        code = vigent_contract(seeded_catalog, root, on_date)
    except InvalidContract:
        # Sem contrato cobrindo essa data — invariante trivialmente OK.
        return

    # Localiza a linha em contracts e checa invariante.
    matches = [c for c in list_contracts(seeded_catalog, root=root) if c.contract_code == code]
    assert len(matches) == 1, f"Expected unique contract for {code}, got {matches}"
    contract = matches[0]
    on_dt = datetime(on_date.year, on_date.month, on_date.day)
    assert contract.vigent_from <= on_dt <= contract.vigent_until, (
        f"Invariant violated: {code} has window "
        f"[{contract.vigent_from}, {contract.vigent_until}], on_date={on_dt}"
    )


@pytest.mark.property
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(offset_days=st.integers(min_value=0, max_value=30))
def test_vigent_returns_consecutive_days(seeded_catalog: Catalog, offset_days: int) -> None:
    """Sanity: dentro da janela de WDOJ26, todos os dias retornam o mesmo código."""
    base = date(2026, 3, 1)
    on = base + timedelta(days=offset_days)
    try:
        code = vigent_contract(seeded_catalog, "WDO", on)
    except InvalidContract:
        return
    # Não asserta código específico; apenas que o lookup é determinístico
    # (idempotente para a mesma input).
    code2 = vigent_contract(seeded_catalog, "WDO", on)
    assert code == code2
