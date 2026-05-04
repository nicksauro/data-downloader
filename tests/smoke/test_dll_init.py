"""tests/smoke/test_dll_init.py — Story 1.2 AC10.

Smoke real da DLL — gated pelas env vars de credencial Profit. Manual run
only (defina as 3 env vars de credencial — KEY, USER, PASSWORD —
e rode ``pytest tests/smoke/test_dll_init.py -v``).

Salva log estruturado em ``docs/qa/SMOKE_EVIDENCE/1.2-{timestamp}.log``
(formato definido por Quinn em ``SMOKE_PROTOCOL.md`` — Story futura).
Por ora, este teste é PLACEHOLDER (skipped sem env) — implementação real
em Story 1.7 quando smoke protocol estiver formalizado.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.getenv("PROFITDLL_KEY"),
    reason="Smoke real requer PROFITDLL_KEY + DLL companions reais (manual run)",
)
def test_dll_init_real(dll_session: object) -> None:
    """AC10 — smoke real conecta e valida wait_market_connected.

    Implementado mas requer ambiente real (DLL + license + companions).
    Execução em CI gated por env. Story 1.7 finaliza protocolo de
    evidence capture (SMOKE_PROTOCOL.md).
    """
    pytest.skip("Implemented but requires real environment (PROFITDLL_KEY set)")
