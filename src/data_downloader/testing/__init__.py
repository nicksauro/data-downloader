"""Test utilities exposed for downstream consumers.

Story 2.10 — implementação de **ADR-014 (Test Strategy)**.

Este sub-pacote consolida fixtures, mocks e helpers usados originalmente
em ``tests/`` e ``benchmarks/fixtures/`` em uma API pública opt-in que
pode ser consumida por:

- testes do próprio repositório (``tests/`` — via ``conftest.py``);
- benchmarks (``benchmarks/`` — via re-export legado em
  ``benchmarks/fixtures/mock_dll.py`` que apenas redireciona para
  :mod:`data_downloader.testing.mock_dll` — backwards compat);
- consumidores externos (Epic 4 multi-asset, projetos downstream que
  reutilizam o ``ProfitDLL`` wrapper) que querem rodar suas próprias
  suites contra a mesma fixture canônica.

Princípios (Quinn / ADR-014):

- **Fidelidade ao contrato real:** :class:`~data_downloader.testing.mock_dll.MockProfitDLL`
  expõe a mesma superfície de :class:`data_downloader.dll.wrapper.ProfitDLL`.
- **Determinismo:** mesmo seed → mesmo output (validação via meta-tests).
- **Sem invenção:** apenas comportamento documentado em manual da DLL +
  PROFITDLL_KNOWLEDGE.md + INVARIANTS_TESTS.md (R3 / Quinn / Nelo).
- **Opt-in:** importar este módulo NÃO instala mocks globalmente — caller
  controla via fixture pytest dedicada.

API pública (re-exports — estável):

- :class:`MockProfitDLL` — substituto in-process da ``ProfitDLL.dll``.
- :class:`FakeClock` — relógio controlável (substitui ``time.perf_counter`` /
  ``datetime.now`` em testes time-dependent).
- ``fixtures`` (módulo) — fixtures pytest reutilizáveis. Consumidores
  ativam com ``from data_downloader.testing.fixtures import *``.

Compatibility note:
    Esta API é **stable** dentro do major V1. Mudanças breaking exigem
    bump major + ADR. Mudanças aditivas (campo novo opcional, fixture
    nova) bumpam minor.
"""

from __future__ import annotations

from data_downloader.testing.fake_clock import FakeClock
from data_downloader.testing.mock_dll import MockCall, MockProfitDLL, TradeRecordSpec

__all__ = [
    "FakeClock",
    "MockCall",
    "MockProfitDLL",
    "TradeRecordSpec",
]
