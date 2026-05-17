"""Property-based — Story 4.26 / ADR-028 rollover safety invariants (AC9).

Invariantes Hypothesis-checked:

1. Para todo (root, start, end) com resolve_contract_per_chunk=True, se
   list_contracts_in_range retorna N contratos, entao para cada chunk
   resolvido vigent_contract(root, chunk_day) e um dos N codes — sem
   off-by-one ou skip de vigencia.

2. Default flag (resolve_contract_per_chunk=False) + range cruzando
   rollover SEMPRE levanta AmbiguousRolloverError — nunca silent loss.

3. Range que cai inteiro dentro de um contrato (1 contrato no range)
   passa a validation sem raise.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from data_downloader.orchestrator.contracts import vigent_contract
from data_downloader.orchestrator.orchestrator import JobConfig, Orchestrator
from data_downloader.public_api.exceptions import (
    AmbiguousRolloverError,
    InvalidContract,
)
from data_downloader.storage.catalog import Catalog

if TYPE_CHECKING:
    pass


@pytest.fixture(scope="module")
def seeded_catalog(tmp_path_factory: pytest.TempPathFactory) -> Catalog:
    """Catalog seeded com WDO mensal (6 contratos) e WDOFUT continuous."""
    tmp: Path = tmp_path_factory.mktemp("rollover_property")
    cat = Catalog(db_path=tmp / "data" / "history" / "catalog.db", auto_reconcile=False)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            ("WDOFUT", "WDOFUT", "1900-01-01 00:00:00", "9999-12-31 23:59:59"),
            ("WDO", "WDOG26", "2025-12-30 00:00:00", "2026-01-29 00:00:00"),
            ("WDO", "WDOH26", "2026-01-29 00:00:01", "2026-02-26 00:00:00"),
            ("WDO", "WDOJ26", "2026-02-26 00:00:01", "2026-03-30 00:00:00"),
            ("WDO", "WDOK26", "2026-03-30 00:00:01", "2026-04-29 00:00:00"),
            ("WDO", "WDOM26", "2026-04-29 00:00:01", "2026-05-28 00:00:00"),
            ("WDO", "WDON26", "2026-05-28 00:00:01", "2026-06-29 00:00:00"),
        ]
        for root, code, vf, vu in rows:
            conn.execute(
                "INSERT INTO contracts(symbol_root, contract_code, vigent_from, "
                "vigent_until, validation_source) VALUES (?, ?, ?, ?, 'hypothesized')",
                (root, code, vf, vu),
            )
    yield cat
    cat.close()


def _orchestrator(cat: Catalog) -> Orchestrator:
    class _DummyDLL:
        def get_dll_version(self) -> str:
            return "test"

    class _DummyWriter:
        pass

    return Orchestrator(_DummyDLL(), cat, _DummyWriter())  # type: ignore[arg-type]


_WDO_RANGE_START = date(2026, 1, 1)
_WDO_RANGE_END = date(2026, 6, 28)


@pytest.mark.property
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    start_offset=st.integers(min_value=0, max_value=170),
    end_offset=st.integers(min_value=1, max_value=170),
)
def test_default_cross_rollover_always_raises_or_passes_for_unique_contract(
    seeded_catalog: Catalog,
    start_offset: int,
    end_offset: int,
) -> None:
    """Invariante 2: default flag NUNCA silently passes cross-rollover.

    Se list_contracts_in_range >= 2 -> _validate_config DEVE raise
    AmbiguousRolloverError.
    Se list_contracts_in_range <= 1 -> _validate_config NAO raise (passa).
    """
    start = _WDO_RANGE_START + timedelta(days=start_offset)
    end = _WDO_RANGE_START + timedelta(days=end_offset)
    assume(start <= end)
    assume(end <= _WDO_RANGE_END)

    contracts = seeded_catalog.list_contracts_in_range(root="WDO", start=start, end=end)
    n = len(contracts)

    orch = _orchestrator(seeded_catalog)
    config = JobConfig(
        symbol="WDO",
        exchange="F",
        start=datetime(start.year, start.month, start.day, 9, 0, 0),
        end=datetime(end.year, end.month, end.day, 17, 0, 0),
    )

    if n >= 2:
        with pytest.raises(AmbiguousRolloverError):
            orch._validate_config(config)
    else:
        # n == 0 ou n == 1: nao raise (caso 0 e fail-late no vigent_contract).
        orch._validate_config(config)


@pytest.mark.property
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    start_offset=st.integers(min_value=0, max_value=170),
    end_offset=st.integers(min_value=0, max_value=170),
)
def test_per_chunk_resolves_to_member_of_in_range(
    seeded_catalog: Catalog,
    start_offset: int,
    end_offset: int,
) -> None:
    """Invariante 1: em modo per-chunk, cada vigent_contract(root, day)
    retorna um code que esta em list_contracts_in_range(root, start, end).

    Garantia: nenhum chunk resolve para um contract fora do conjunto
    detectado para o range (no off-by-one ou skip).
    """
    start = _WDO_RANGE_START + timedelta(days=start_offset)
    end = _WDO_RANGE_START + timedelta(days=end_offset)
    assume(start <= end)
    assume(end <= _WDO_RANGE_END)

    contracts = seeded_catalog.list_contracts_in_range(root="WDO", start=start, end=end)
    in_range_codes = {c.contract_code for c in contracts}
    if not in_range_codes:
        # Range sem vigencia — caller esperaria InvalidContract no primeiro
        # chunk. Skip property.
        return

    # Itera dia-a-dia, simulando o que o per-chunk loop faria.
    cur = start
    while cur <= end:
        try:
            code = vigent_contract(seeded_catalog, "WDO", cur)
        except InvalidContract:
            cur += timedelta(days=1)
            continue
        assert code in in_range_codes, (
            f"per-chunk resolveu {code!r} para {cur} mas list_contracts_in_range"
            f"({start}, {end}) retornou apenas {sorted(in_range_codes)}"
        )
        cur += timedelta(days=1)


@pytest.mark.property
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    start_offset=st.integers(min_value=0, max_value=170),
    span_days=st.integers(min_value=0, max_value=170),
)
def test_continuous_future_never_triggers_rollover(
    seeded_catalog: Catalog,
    start_offset: int,
    span_days: int,
) -> None:
    """Invariante 3 (golden path): WDOFUT nunca levanta AmbiguousRolloverError.

    list_contracts_in_range para WDOFUT em qualquer range sempre retorna
    exatamente 1 contrato (1900..9999). Default flag passa sem raise.
    """
    start = _WDO_RANGE_START + timedelta(days=start_offset)
    end = start + timedelta(days=span_days)
    assume(end <= date(2030, 12, 31))

    orch = _orchestrator(seeded_catalog)
    config = JobConfig(
        symbol="WDOFUT",
        exchange="F",
        start=datetime(start.year, start.month, start.day, 9, 0, 0),
        end=datetime(end.year, end.month, end.day, 17, 0, 0),
    )
    # Nao raise.
    orch._validate_config(config)
