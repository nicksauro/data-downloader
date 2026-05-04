"""Pytest root conftest.

Story 1.2 — fixture session-scoped ``dll_session`` (AC14 / Q08-E).
Story 2.10 — re-exporta fixtures canônicas de
:mod:`data_downloader.testing.fixtures` (ADR-014 §6).

A DLL ProfitDLL **não é idempotente** em ``init → finalize → init`` na mesma
sessão Python (segundo init pode crashar / retornar estado corrompido).
Re-init em sessão única é PROIBIDO em testes — fixture session-scoped
garante init exatamente UMA vez por ``pytest`` invocation.

Em V1 (Story 1.2), esta fixture é apenas placeholder (yield None) porque
smoke real ainda não está habilitado (PROFITDLL_KEY env required).
Story 1.7 implementa o init real quando smoke protocol estiver formalizado.

Story 2.10: as fixtures :func:`fake_clock`, :func:`mock_dll_session`,
:func:`mock_dll_uninitialized`, :func:`tmp_catalog`, :func:`tmp_data_dir`
e :func:`synthetic_trades_factory` agora vivem em
:mod:`data_downloader.testing.fixtures` e são re-exportadas aqui para
ficar disponíveis a TODOS os testes (descoberta automática do pytest).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

# Re-export Story 2.10 — fixtures canônicas (ADR-014).
# Importação tem efeito colateral: pytest descobre via __all__ + nomes.
from data_downloader.testing.fixtures import (  # noqa: F401
    fake_clock,
    mock_dll_session,
    mock_dll_uninitialized,
    synthetic_trades_factory,
    tmp_catalog,
    tmp_data_dir,
)


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
