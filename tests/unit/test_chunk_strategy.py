"""Unit tests — orchestrator.chunk_strategy (Story 4.16, Pichau 2026-05-06).

Cobertura:

- WINFUT → 1 (override).
- WDOFUT, INDFUT, DOLFUT → 5 (default).
- Equity ticker (PETR4) → 5 (default — directive Pichau).
- Lowercase normalization (case-insensitive).
- Symbol desconhecido → 5 (default).
"""

from __future__ import annotations

import pytest

from data_downloader.orchestrator.chunk_strategy import (
    DEFAULT_CHUNK_DAYS,
    get_chunk_days,
)


@pytest.mark.unit
def test_chunk_days_winfut_returns_1() -> None:
    """WINFUT → 1 (override Q-DRIFT-37 / COUNCIL-37 Pyro)."""
    assert get_chunk_days("WINFUT") == 1


@pytest.mark.unit
def test_chunk_days_wdofut_returns_5() -> None:
    """WDOFUT → 5 (default — Pichau directive 2026-05-06)."""
    assert get_chunk_days("WDOFUT") == 5


@pytest.mark.unit
def test_chunk_days_petr4_returns_5() -> None:
    """Equity Ibovespa (PETR4) → 5 (Pichau directive sobrescreve 1d
    histórico)."""
    assert get_chunk_days("PETR4") == 5


@pytest.mark.unit
def test_chunk_days_indfut_returns_5() -> None:
    """INDFUT → 5 (default)."""
    assert get_chunk_days("INDFUT") == 5


@pytest.mark.unit
def test_chunk_days_lowercase_normalizes() -> None:
    """Case-insensitive: 'winfut' resolve igual a 'WINFUT'."""
    assert get_chunk_days("winfut") == 1
    assert get_chunk_days("WinFut") == 1
    assert get_chunk_days("wdofut") == 5


@pytest.mark.unit
def test_chunk_days_unknown_symbol_returns_default_5() -> None:
    """Símbolo desconhecido → DEFAULT_CHUNK_DAYS (5)."""
    assert get_chunk_days("XPTO99") == DEFAULT_CHUNK_DAYS
    assert get_chunk_days("XPTO99") == 5


# =====================================================================
# Sanidade — invariantes da política
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "symbol",
    ["WINFUT", "WDOFUT", "INDFUT", "DOLFUT", "PETR4", "VALE3", "ITUB4", "FOO", ""],
)
def test_chunk_days_always_positive(symbol: str) -> None:
    """Garantia: get_chunk_days NUNCA retorna 0 ou negativo (bloquearia
    download_chunk em loop infinito)."""
    assert get_chunk_days(symbol) >= 1


@pytest.mark.unit
def test_default_chunk_days_is_5() -> None:
    """Sentinela: DEFAULT_CHUNK_DAYS canonical = 5 (Pichau 2026-05-06)."""
    assert DEFAULT_CHUNK_DAYS == 5
