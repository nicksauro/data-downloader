"""Unit tests — Story 4.26 / ADR-028 rollover safety (AC7).

Cobertura:

- ``_validate_no_rollover_in_window`` com 1 / 2 / 0 contratos no range
  (no raise / raise / no raise — fail-late via vigent_contract).
- ``AmbiguousRolloverError.__str__`` contem os 3 remedies prescritivos.
- ``Catalog.list_contracts_in_range`` ordem ASC + overlap edge no instante
  de rollover (toca exatamente vigent_until de A e vigent_from de B).
- ``Catalog.completed_days`` roots kwarg filtra por contract_codes
  heterogeneos (AC6 cache-hit per-chunk).
- ``JobConfig.resolve_contract_per_chunk`` default False + frozen.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from data_downloader.orchestrator.orchestrator import JobConfig, Orchestrator
from data_downloader.public_api.exceptions import AmbiguousRolloverError
from data_downloader.storage.catalog import Catalog

if TYPE_CHECKING:
    pass


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def catalog_with_wdo_seed(tmp_path: Path) -> Catalog:
    """Catalogo com 3 contratos WDO (H/J/K 26) + 1 WDOFUT continuous.

    Vigencias mensais consecutivas com instante de rollover compartilhado
    (vigent_until[A] == vigent_from[B] no nivel data) — testa overlap
    edge.
    """
    db_path = tmp_path / "data" / "history" / "catalog.db"
    cat = Catalog(db_path=db_path, auto_reconcile=False)
    conn = cat._conn_or_raise()
    with cat._transaction():
        rows = [
            # Continuous future cobre todo o tempo (overlap com qualquer range)
            ("WDOFUT", "WDOFUT", "1900-01-01 00:00:00", "9999-12-31 23:59:59"),
            # Contratos mensais consecutivos
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
    yield cat
    cat.close()


def _orchestrator_with_catalog(cat: Catalog) -> Orchestrator:
    """Cria um Orchestrator com dll/writer dummies — apenas validation usado."""

    class _DummyDLL:
        def get_dll_version(self) -> str:
            return "test"

    class _DummyWriter:
        pass

    return Orchestrator(_DummyDLL(), cat, _DummyWriter())  # type: ignore[arg-type]


def _cfg(symbol: str, start: date, end: date, **kwargs: object) -> JobConfig:
    """Helper para construir JobConfig com defaults seguros."""
    return JobConfig(
        symbol=symbol,
        exchange="F",
        start=datetime(start.year, start.month, start.day, 9, 0, 0),
        end=datetime(end.year, end.month, end.day, 17, 0, 0),
        **kwargs,  # type: ignore[arg-type]
    )


# =====================================================================
# AC7.1 — _validate_no_rollover_in_window: 1 contrato no range -> no raise
# =====================================================================


@pytest.mark.unit
def test_validate_no_rollover_single_contract_in_range(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """Range cabe inteiro em 1 contrato (WDOJ26) -> passa sem raise."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    config = _cfg("WDO", date(2026, 3, 1), date(2026, 3, 15))
    # Nao raise — validation passa.
    orch._validate_no_rollover_in_window(config)


# =====================================================================
# AC7.2 — _validate_no_rollover_in_window: 2+ contratos -> AmbiguousRolloverError
# =====================================================================


@pytest.mark.unit
def test_validate_no_rollover_multiple_contracts_raises(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """Range cruza rollover -> AmbiguousRolloverError listando os codes."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    # Range cobre WDOH26 (jan-fev), WDOJ26 (fev-mar) e WDOK26 (mar-abr).
    config = _cfg("WDO", date(2026, 2, 1), date(2026, 4, 15))
    with pytest.raises(AmbiguousRolloverError) as exc_info:
        orch._validate_no_rollover_in_window(config)
    err = exc_info.value
    assert err.symbol_root == "WDO"
    assert err.start == date(2026, 2, 1)
    assert err.end == date(2026, 4, 15)
    assert "WDOH26" in err.contracts_in_range
    assert "WDOJ26" in err.contracts_in_range
    assert "WDOK26" in err.contracts_in_range
    # Ordenado lexicograficamente (sorted no helper) — match SCHEMA convention.
    assert err.contracts_in_range == sorted(err.contracts_in_range)


# =====================================================================
# AC7.3 — _validate_no_rollover_in_window: 0 contratos -> no raise (fail-late)
# =====================================================================


@pytest.mark.unit
def test_validate_no_rollover_zero_contracts_passes(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """Raiz sem vigencia no range -> passa (vigent_contract levanta depois)."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    # 'UNKNOWN' nao tem nenhuma linha no catalog -> 0 contratos no range.
    config = _cfg("UNKNOWN", date(2026, 1, 1), date(2026, 6, 30))
    # Nao raise — vigent_contract no orchestrator.run sera quem levanta.
    orch._validate_no_rollover_in_window(config)


# =====================================================================
# AC7.4 — AmbiguousRolloverError.__str__ contem 3 remedies
# =====================================================================


@pytest.mark.unit
def test_ambiguous_rollover_error_str_contains_three_remedies() -> None:
    """Mensagem multi-linha lista os 3 remedies prescritivos (ADR-028 §2.1)."""
    err = AmbiguousRolloverError(
        symbol_root="WDO",
        start=date(2026, 1, 15),
        end=date(2026, 6, 15),
        contracts_in_range=["WDOG26", "WDOH26", "WDOJ26", "WDOK26"],
    )
    msg = str(err)
    # Os contratos sao listados.
    assert "WDOG26" in msg
    assert "WDOH26" in msg
    assert "WDOJ26" in msg
    assert "WDOK26" in msg
    # Os 3 remedies sao mencionados.
    assert "continuous-future" in msg.lower() or "WDOFUT" in msg
    assert "contrato especifico" in msg.lower() or "specific" in msg.lower()
    assert "per_chunk" in msg or "per-chunk" in msg
    # Heuristica: 3 marcadores numerados ("1.", "2.", "3.") aparecem na msg.
    assert msg.count("1. ") >= 1
    assert msg.count("2. ") >= 1
    assert msg.count("3. ") >= 1


@pytest.mark.unit
def test_ambiguous_rollover_error_humanized_id() -> None:
    """humanized_message retorna o microcopy ID ERR_AMBIGUOUS_ROLLOVER (AC1)."""
    err = AmbiguousRolloverError(
        symbol_root="WDO",
        start=date(2026, 1, 15),
        end=date(2026, 6, 15),
        contracts_in_range=["WDOG26", "WDOH26"],
    )
    assert err.humanized_message == "ERR_AMBIGUOUS_ROLLOVER"
    # Subclasse de InvalidContract (compat com handlers existentes).
    from data_downloader.public_api.exceptions import InvalidContract

    assert isinstance(err, InvalidContract)


# =====================================================================
# AC7.5 — Catalog.list_contracts_in_range retorna ordem vigent_from ASC
# =====================================================================


@pytest.mark.unit
def test_list_contracts_in_range_orders_by_vigent_from_asc(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """Resultado sempre ordenado por vigent_from ASC."""
    contracts = catalog_with_wdo_seed.list_contracts_in_range(
        root="WDO",
        start=date(2026, 1, 1),
        end=date(2026, 6, 30),
    )
    assert len(contracts) == 3
    codes = [c.contract_code for c in contracts]
    # H26 (jan-fev) < J26 (fev-mar) < K26 (mar-abr) por vigent_from.
    assert codes == ["WDOH26", "WDOJ26", "WDOK26"]


# =====================================================================
# AC7.6 — Overlap edge: range toca vigent_until A e vigent_from B
# =====================================================================


@pytest.mark.unit
def test_list_contracts_in_range_overlap_edge_includes_both(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """Range que toca o instante de rollover deve incluir AMBOS contratos.

    WDOJ26.vigent_until = 2026-03-30 00:00:00
    WDOK26.vigent_from  = 2026-03-30 00:00:01
    Range [2026-03-30, 2026-03-30] cobre J e K (overlap inclusivo).
    """
    contracts = catalog_with_wdo_seed.list_contracts_in_range(
        root="WDO",
        start=date(2026, 3, 30),
        end=date(2026, 3, 30),
    )
    codes = sorted(c.contract_code for c in contracts)
    assert codes == ["WDOJ26", "WDOK26"]


# =====================================================================
# AC7.7 — Catalog.completed_days roots kwarg filtra por IN (AC6)
# =====================================================================


@pytest.mark.unit
def test_completed_days_with_roots_filters_in(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """Quando roots= passado, query usa symbol IN roots (per-chunk mode)."""
    cat = catalog_with_wdo_seed
    cat.record_chunk(
        symbol="WDOH26",
        exchange="F",
        chunk_date=date(2026, 2, 10),
        job_id=None,
        status="completed",
        trades_count=100,
    )
    cat.record_chunk(
        symbol="WDOJ26",
        exchange="F",
        chunk_date=date(2026, 3, 10),
        job_id=None,
        status="completed",
        trades_count=200,
    )
    cat.record_chunk(
        symbol="WDOK26",
        exchange="F",
        chunk_date=date(2026, 4, 10),
        job_id=None,
        status="completed",
        trades_count=300,
    )

    # Modo single-contract: so encontra os dias do contract_code passado.
    days_single = cat.completed_days("WDOJ26", "F", date(2026, 1, 1), date(2026, 6, 30))
    assert days_single == {date(2026, 3, 10)}

    # Modo per-chunk (roots={H,J,K}): encontra todos os dias.
    days_per_chunk = cat.completed_days(
        "WDO",  # symbol ignorado quando roots= passado
        "F",
        date(2026, 1, 1),
        date(2026, 6, 30),
        roots={"WDOH26", "WDOJ26", "WDOK26"},
    )
    assert days_per_chunk == {date(2026, 2, 10), date(2026, 3, 10), date(2026, 4, 10)}


# =====================================================================
# AC7.8 — JobConfig.resolve_contract_per_chunk default False + frozen
# =====================================================================


@pytest.mark.unit
def test_jobconfig_resolve_contract_per_chunk_default_false() -> None:
    """Campo novo tem default False (fail-loudly preservado)."""
    cfg = JobConfig(
        symbol="WDOFUT",
        exchange="F",
        start=datetime(2026, 3, 1, 9, 0, 0),
        end=datetime(2026, 3, 1, 17, 0, 0),
    )
    assert cfg.resolve_contract_per_chunk is False


@pytest.mark.unit
def test_jobconfig_resolve_contract_per_chunk_frozen() -> None:
    """JobConfig e frozen — nao deve aceitar mutacao do campo novo."""
    cfg = JobConfig(
        symbol="WDOFUT",
        exchange="F",
        start=datetime(2026, 3, 1, 9, 0, 0),
        end=datetime(2026, 3, 1, 17, 0, 0),
        resolve_contract_per_chunk=True,
    )
    assert cfg.resolve_contract_per_chunk is True
    with pytest.raises((AttributeError, Exception)):
        cfg.resolve_contract_per_chunk = False  # type: ignore[misc]


# =====================================================================
# AC7.9 — _validate_config integration (continuous future bypassa)
# =====================================================================


@pytest.mark.unit
def test_validate_config_continuous_future_passes(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """WDOFUT (1 contrato cobrindo qualquer range) nao deve raise."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    config = _cfg("WDOFUT", date(2020, 1, 1), date(2030, 12, 31))
    # _validate_config chama _validate_no_rollover_in_window quando
    # resolve_contract=True (default).
    orch._validate_config(config)


@pytest.mark.unit
def test_validate_config_root_cross_rollover_raises(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """download('WDO', cross-rollover) -> AmbiguousRolloverError no validate."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    config = _cfg("WDO", date(2026, 2, 1), date(2026, 4, 15))
    with pytest.raises(AmbiguousRolloverError):
        orch._validate_config(config)


@pytest.mark.unit
def test_validate_config_per_chunk_opt_in_bypasses_rollover_check(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """resolve_contract_per_chunk=True bypassa validation — caller responsavel."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    config = _cfg(
        "WDO",
        date(2026, 2, 1),
        date(2026, 4, 15),
        resolve_contract_per_chunk=True,
    )
    # Nao raise — opt-in passa a validation mesmo com rollover-spanning.
    orch._validate_config(config)


@pytest.mark.unit
def test_validate_config_resolve_false_bypasses(
    catalog_with_wdo_seed: Catalog,
) -> None:
    """resolve_contract=False -> caller passou contract code, nao raiz; skip."""
    orch = _orchestrator_with_catalog(catalog_with_wdo_seed)
    config = _cfg(
        "WDOJ26",
        date(2026, 2, 1),
        date(2026, 4, 15),
        resolve_contract=False,
    )
    orch._validate_config(config)
