"""Smoke test — probe_contract real contra DLL (Story 1.6 AC10 / Subtask 6.5).

Gated por 3 env vars de credencial Profit (KEY/USER/PASS — ver
``.env.example``). Em CI sem credenciais reais, o teste é skipped
automaticamente — não quebra build.

Manual run (Linux/Mac):

    pytest tests/smoke/test_probe.py -v   # após exportar as 3 envs

Manual run (Windows PowerShell):

    pytest tests/smoke/test_probe.py -v   # após $env:* set

Cenário coberto:

1. Inicializa DLL (via fixture session-scoped ``dll_session`` ou direto
   se necessário).
2. Popula seed.
3. Roda ``probe_contract`` sobre ``WDOJ26``.
4. Esperado: ``ProbeResult.success == True`` ou skip se janela já fora
   de vigência (ex.: rodando teste muito tempo após Story 1.6).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_HAS_CREDS = all(os.getenv(k) for k in ("PROFITDLL_KEY", "PROFIT_USER", "PROFIT_PASS"))


@pytest.mark.smoke
@pytest.mark.skipif(
    not _HAS_CREDS,
    reason="Smoke real requer PROFITDLL_KEY + PROFIT_USER + PROFIT_PASS (manual run)",
)
def test_probe_wdoj26_real(tmp_path: Path) -> None:
    """AC10 — probe real WDOJ26 com DLL conectada."""
    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.orchestrator.contracts import populate_contracts_from_seed
    from data_downloader.orchestrator.contracts_probe import probe_contract
    from data_downloader.storage.catalog import Catalog

    catalog = Catalog(db_path=tmp_path / "data" / "history" / "catalog.db")
    populate_contracts_from_seed(catalog)

    try:
        with ProfitDLL() as dll:
            dll.initialize_market_only(
                key=os.environ["PROFITDLL_KEY"],
                user=os.environ["PROFIT_USER"],
                password=os.environ["PROFIT_PASS"],
            )
            assert dll.wait_market_connected(timeout=60), "DLL não conectou"
            result = probe_contract(
                dll=dll,
                catalog=catalog,
                symbol_root="WDO",
                contract_code="WDOJ26",
            )
    finally:
        catalog.close()

    assert result.success, (
        f"Probe falhou: reason={result.reason}, trades={result.trades_count}, "
        f"sample_date={result.sample_date}"
    )
    assert result.trades_count > 0
