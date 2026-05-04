"""Pytest root conftest.

Story 1.2 — fixture session-scoped ``dll_session`` (AC14 / Q08-E).

A DLL ProfitDLL **não é idempotente** em ``init → finalize → init`` na mesma
sessão Python (segundo init pode crashar / retornar estado corrompido).
Re-init em sessão única é PROIBIDO em testes — fixture session-scoped
garante init exatamente UMA vez por ``pytest`` invocation.

Em V1 (Story 1.2), esta fixture é apenas placeholder (yield None) porque
smoke real ainda não está habilitado (PROFITDLL_KEY env required).
Story 1.7 implementa o init real quando smoke protocol estiver formalizado.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(scope="session")
def dll_session() -> Generator[None, None, None]:
    """Fixture session-scoped — DLL não-idempotente init→finalize→init (Q08-E).

    Story 1.2: placeholder (yield None) — smoke real em Story 1.7.
    Story 1.7: implementação real:

        dll = ProfitDLL()
        dll.initialize_market_only(env.key, env.user, env.password)
        assert dll.wait_market_connected(60)
        yield dll
        dll.finalize()
    """
    yield None
