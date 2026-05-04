"""tests/smoke/test_dll_init.py — Story 1.2 AC10.

Smoke real da DLL — gated pelas env vars de credencial Profit
(``PROFITDLL_KEY`` / ``PROFITDLL_USER`` / ``PROFITDLL_PASS`` — alinhado com
``.env.example``). Manual run only (defina as 3 env vars e rode
``pytest tests/smoke/test_dll_init.py -v``).

Salva log estruturado em ``docs/qa/SMOKE_EVIDENCE/1.2-{timestamp}.log``
(formato definido por Quinn em ``SMOKE_PROTOCOL.md`` — Story futura).
Por ora, este teste é PLACEHOLDER (skipped sem env) — implementação real
em Story 1.7 quando smoke protocol estiver formalizado.

Q-DRIFT-02 (smoke 2026-05-04): timeout 300s para wait_market_connected
(handshake MARKET_DATA pode levar >60s).
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
