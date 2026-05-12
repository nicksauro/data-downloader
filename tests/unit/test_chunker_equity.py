"""Unit tests — chunker equity detection (Story 4.2 AC1 + COUNCIL-29 D2).

V1.1.0 Pichau directive (2026-05-07, supersede 2026-05-06):
política unificada 1d/chunk para WDO/WIN/IND/DOL e equities.

Cobertura:

- ``is_equity_ticker`` regex ``^[A-Z]{4}\\d$`` casa tickers B3 canônicos.
- ``chunk_days_for_symbol`` retorna 1 para todos os ativos (V1.1.0+).
- Equity chunks têm 1 dia útil cada (regression vs `test_chunker.py`).
"""

from __future__ import annotations

from datetime import date

import pytest

from data_downloader.orchestrator.chunker import (
    CHUNK_DAYS,
    DEFAULT_EQUITY_CHUNK_DAYS,
    EQUITY_TICKER_RE,
    chunk_date_range,
    chunk_days_for_symbol,
    is_equity_ticker,
)

# =====================================================================
# is_equity_ticker — regex matching
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker",
    ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3", "MGLU3", "WEGE3"],
)
def test_is_equity_ticker_canonical_b3(ticker: str) -> None:
    """Tickers canônicos B3 (4 letras + 1 dígito) são equities."""
    assert is_equity_ticker(ticker)


@pytest.mark.unit
@pytest.mark.parametrize(
    "non_equity",
    [
        "WDOJ26",  # futuro — 6 chars
        "WDOFUT",  # alias live — 6 letras, sem dígito final
        "WINH26",  # futuro WIN
        "INDV26",  # futuro IND cheio
        "DOLF26",  # futuro DOL cheio
        "PETR",  # sem dígito
        "PETR44",  # 2 dígitos
        "petr4",  # lowercase (regra B3 é uppercase)
        "PET4",  # 3 letras + 1 dígito
        "PETR4A",  # 4 letras + 1 dígito + letra
        "",  # vazio
        "1234",  # só dígitos
    ],
)
def test_is_equity_ticker_rejects_non_canonical(non_equity: str) -> None:
    """Não-equities (ou patterns ambíguos) retornam False."""
    assert not is_equity_ticker(non_equity)


@pytest.mark.unit
def test_equity_ticker_regex_export() -> None:
    """:data:`EQUITY_TICKER_RE` é exportado para reuso por outros módulos."""
    assert EQUITY_TICKER_RE.fullmatch("PETR4")
    assert not EQUITY_TICKER_RE.fullmatch("WDOJ26")


# =====================================================================
# chunk_days_for_symbol — multi-asset matrix
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("symbol", "expected_days"),
    [
        # WDO (V1.1.0+ política unificada Pichau 2026-05-07)
        ("WDOJ26", 1),
        ("WDOK26", 1),
        ("WDOFUT", 1),
        # WIN (V1.1.0+ política unificada)
        ("WINH26", 1),
        ("WINM26", 1),
        ("WINU26", 1),
        ("WINZ26", 1),
        ("WINZ27", 1),
        # IND/DOL (V1.1.0+ política unificada)
        ("INDV26", 1),
        ("DOLF26", 1),
        # Equities (Story 4.2 — regex match → default_equity=1)
        ("PETR4", 1),
        ("VALE3", 1),
        ("ITUB4", 1),
        ("BBDC4", 1),
        ("BBAS3", 1),
        ("ABEV3", 1),
        # Unknown símbolo (fallback default_equity=1)
        ("XYZW1", 1),  # casa regex equity
        ("UNKNOWN", 1),  # nenhum prefix — fallback
    ],
)
def test_chunk_days_for_symbol_full_matrix(symbol: str, expected_days: int) -> None:
    """Matrix completa V1.1.0+: TODOS os ativos = 1d/chunk (Pichau 2026-05-07)."""
    assert chunk_days_for_symbol(symbol) == expected_days


@pytest.mark.unit
def test_chunk_days_default_equity_constant() -> None:
    """:data:`DEFAULT_EQUITY_CHUNK_DAYS` é 1 (Story 1.7a + 4.2 confirmation)."""
    assert DEFAULT_EQUITY_CHUNK_DAYS == 1


@pytest.mark.unit
def test_chunk_days_table_has_win_1() -> None:
    """V1.1.0+ Pichau 2026-05-07: CHUNK_DAYS["WIN"] == CHUNK_DAYS["WDO"] == 1."""
    assert CHUNK_DAYS["WIN"] == 1
    assert CHUNK_DAYS["WDO"] == 1


# =====================================================================
# chunk_date_range — equity 1 chunk per business day
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker",
    ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3"],
)
def test_chunk_date_range_equity_1_chunk_per_day(ticker: str) -> None:
    """Story 4.2 AC1 — equity em 1 semana = 5 chunks de 1 dia útil."""
    # Segunda 2026-03-02 a sexta 2026-03-06 (5 dias úteis).
    chunks = chunk_date_range(ticker, "B", date(2026, 3, 2), date(2026, 3, 6))
    assert len(chunks) == 5
    for c in chunks:
        assert c.start.date() == c.end.date()
        assert c.symbol == ticker
        assert c.exchange == "B"


@pytest.mark.unit
def test_chunk_date_range_winh26_5_business_days() -> None:
    """V1.1.0+ Pichau 2026-05-07: WIN em 1 semana = 5 chunks de 1 dia útil."""
    chunks = chunk_date_range("WINH26", "F", date(2026, 3, 2), date(2026, 3, 6))
    assert len(chunks) == 5
    assert chunks[0].start.date() == date(2026, 3, 2)
    assert chunks[-1].end.date() == date(2026, 3, 6)
    assert chunks[0].symbol == "WINH26"
    assert chunks[0].exchange == "F"
    for c in chunks:
        assert c.start.date() == c.end.date()


@pytest.mark.unit
def test_chunk_date_range_winz27_buffer_year() -> None:
    """Story 4.2 — buffer 2027 funciona (sanity sobre seed completa).

    V1.1.0+ política unificada: 5 dias úteis = 5 chunks de 1d.
    """
    # 2027-09-15 (quarta) a 2027-09-21 (terça) = 5 dias úteis.
    chunks = chunk_date_range("WINZ27", "F", date(2027, 9, 15), date(2027, 9, 21))
    assert len(chunks) == 5
    assert chunks[0].symbol == "WINZ27"
    for c in chunks:
        assert c.start.date() == c.end.date()


@pytest.mark.unit
def test_chunk_date_range_equity_skips_holiday() -> None:
    """Equity (PETR4) também respeita feriados B3 (Tiradentes 21/04/2026)."""
    chunks = chunk_date_range("PETR4", "B", date(2026, 4, 20), date(2026, 4, 22))
    # 20 (segunda) e 22 (quarta) são úteis; 21 (terça) é Tiradentes.
    assert len(chunks) == 2
    days = [c.start.date() for c in chunks]
    assert date(2026, 4, 21) not in days
