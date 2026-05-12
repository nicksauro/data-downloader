"""Unit tests — orchestrator.chunker (Story 1.7a AC1).

V1.1.0 Pichau directive (2026-05-07, supersede 2026-05-06):
"SEMPRE 1 dia útil/chunk, qualquer ativo." → CHUNK_DAYS WDO/WIN/IND/DOL = 1.

Cobertura:

- ``chunk_days_for_symbol``: prefix lookup (WDO=1, WIN=1, equity default=1).
- ``chunk_date_range``: cobertura completa, sem overlap, sem gap.
- Skip de fins de semana e feriados B3.
- Edge cases: range vazio, range sem dias úteis, 1 dia útil.
- Property test (Hypothesis): união de chunks == business_days(start, end).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from data_downloader.orchestrator.chunker import (
    CHUNK_DAYS,
    DEFAULT_EQUITY_CHUNK_DAYS,
    chunk_date_range,
    chunk_days_for_symbol,
)
from data_downloader.validation.calendar_b3 import b3_business_days_range

# =====================================================================
# chunk_days_for_symbol
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("WDOJ26", 1),
        ("WDOFUT", 1),
        ("WINJ26", 1),
        ("INDV26", 1),
        ("DOLF26", 1),
        ("PETR4", DEFAULT_EQUITY_CHUNK_DAYS),
        ("VALE3", DEFAULT_EQUITY_CHUNK_DAYS),
        ("ITUB4", DEFAULT_EQUITY_CHUNK_DAYS),
    ],
)
def test_chunk_days_for_symbol_default_map(symbol: str, expected: int) -> None:
    assert chunk_days_for_symbol(symbol) == expected


@pytest.mark.unit
def test_chunk_days_for_symbol_custom_map() -> None:
    """Custom map override default."""
    assert chunk_days_for_symbol("CUST123", chunk_days_map={"CUST": 10}) == 10
    assert chunk_days_for_symbol("OTHER", chunk_days_map={"CUST": 10}) == 1


@pytest.mark.unit
def test_chunk_days_for_symbol_longest_prefix_wins() -> None:
    """Se múltiplos prefixos batem, o mais longo vence (defensivo)."""
    table = {"W": 99, "WDO": 5}
    assert chunk_days_for_symbol("WDOJ26", chunk_days_map=table) == 5
    assert chunk_days_for_symbol("WX", chunk_days_map=table) == 99


@pytest.mark.unit
def test_chunk_days_for_symbol_default_equity_override() -> None:
    """default_equity arg respeitado quando nenhum prefixo bate."""
    assert chunk_days_for_symbol("XYZ", default_equity=7) == 7


# =====================================================================
# chunk_date_range — happy paths
# =====================================================================


@pytest.mark.unit
def test_chunk_date_range_wdo_5_business_days() -> None:
    """WDO em uma semana B3 sem feriado: 5 chunks de 1 dia útil cada
    (V1.1.0+ política unificada Pichau 2026-05-07)."""
    # Segunda 2026-03-02 a sexta 2026-03-06 (5 dias úteis, sem feriado).
    chunks = chunk_date_range("WDOJ26", "F", date(2026, 3, 2), date(2026, 3, 6))
    assert len(chunks) == 5
    assert chunks[0].start == datetime(2026, 3, 2, 0, 0, 0)
    assert chunks[0].end.year == 2026
    assert chunks[0].end.month == 3
    assert chunks[0].end.day == 2
    assert chunks[-1].end.day == 6
    assert chunks[0].symbol == "WDOJ26"
    assert chunks[0].exchange == "F"
    for c in chunks:
        # cada chunk = 1 dia útil (start.date() == end.date()).
        assert c.start.date() == c.end.date()


@pytest.mark.unit
def test_chunk_date_range_wdo_two_weeks() -> None:
    """WDO em 10 dias úteis: 10 chunks de 1 dia (V1.1.0+ Pichau 2026-05-07)."""
    # 2026-03-02..03-13 = 10 dias úteis (sem feriado).
    chunks = chunk_date_range("WDOJ26", "F", date(2026, 3, 2), date(2026, 3, 13))
    assert len(chunks) == 10
    assert chunks[0].start.day == 2
    assert chunks[0].end.day == 2
    assert chunks[-1].start.day == 13
    assert chunks[-1].end.day == 13
    for c in chunks:
        assert c.start.date() == c.end.date()


@pytest.mark.unit
def test_chunk_date_range_equity_per_day() -> None:
    """PETR4: 5 dias úteis = 5 chunks de 1 dia."""
    chunks = chunk_date_range("PETR4", "B", date(2026, 3, 2), date(2026, 3, 6))
    assert len(chunks) == 5
    for c in chunks:
        # start.date() == end.date() (mesmo dia útil).
        assert c.start.date() == c.end.date()


@pytest.mark.unit
def test_chunk_date_range_skips_weekend() -> None:
    """Range sábado-domingo retorna lista vazia."""
    chunks = chunk_date_range("WDOJ26", "F", date(2026, 3, 7), date(2026, 3, 8))
    assert chunks == []


@pytest.mark.unit
def test_chunk_date_range_skips_holiday() -> None:
    """Tiradentes 2026 (21/4 terça) é pulado."""
    # 2026-04-20 (segunda) a 2026-04-22 (quarta) — sem o feriado seria 3 dias.
    # Tiradentes 2026 = 21/4 (terça) é feriado → 2 dias úteis (20 e 22).
    chunks = chunk_date_range("PETR4", "B", date(2026, 4, 20), date(2026, 4, 22))
    assert len(chunks) == 2
    days = [c.start.date() for c in chunks]
    assert date(2026, 4, 21) not in days
    assert date(2026, 4, 20) in days
    assert date(2026, 4, 22) in days


@pytest.mark.unit
def test_chunk_date_range_inverted_returns_empty() -> None:
    """end < start → lista vazia."""
    chunks = chunk_date_range("WDOJ26", "F", date(2026, 3, 10), date(2026, 3, 1))
    assert chunks == []


@pytest.mark.unit
def test_chunk_date_range_single_business_day() -> None:
    """1 dia útil → 1 chunk start=end."""
    chunks = chunk_date_range("WDOJ26", "F", date(2026, 3, 2), date(2026, 3, 2))
    assert len(chunks) == 1
    assert chunks[0].start.date() == chunks[0].end.date() == date(2026, 3, 2)


@pytest.mark.unit
def test_chunk_date_range_accepts_datetime_input() -> None:
    """datetime de entrada é coerced para date — comportamento idêntico."""
    chunks_d = chunk_date_range("PETR4", "B", date(2026, 3, 2), date(2026, 3, 6))
    chunks_dt = chunk_date_range(
        "PETR4",
        "B",
        datetime(2026, 3, 2, 9, 30),
        datetime(2026, 3, 6, 17, 0),
    )
    assert [c.start.date() for c in chunks_d] == [c.start.date() for c in chunks_dt]


@pytest.mark.unit
def test_chunk_date_range_chunks_have_no_overlap() -> None:
    """Para WDO em 3 semanas, chunks não se sobrepõem."""
    chunks = chunk_date_range("WDOJ26", "F", date(2026, 3, 2), date(2026, 3, 20))
    for i in range(len(chunks) - 1):
        # Final do chunk i é estritamente menor que start do chunk i+1.
        assert chunks[i].end.date() < chunks[i + 1].start.date()


@pytest.mark.unit
def test_chunk_date_range_emits_end_of_day_microseconds() -> None:
    """``end`` do chunk inclui microssegundos finais (23:59:59.999999)."""
    chunks = chunk_date_range("PETR4", "B", date(2026, 3, 2), date(2026, 3, 2))
    assert chunks[0].end.hour == 23
    assert chunks[0].end.minute == 59
    assert chunks[0].end.second == 59
    assert chunks[0].end.microsecond == 999_999


# =====================================================================
# Property test (Hypothesis) — invariantes principais.
# =====================================================================


# Estratégia: par de datas em 2026-03..2026-05 (alguns feriados conhecidos).
_RANGE_START = date(2026, 3, 1)
_RANGE_END = date(2026, 5, 31)
_DAYS_IN_RANGE = (_RANGE_END - _RANGE_START).days + 1


@st.composite
def _date_range(draw: st.DrawFn) -> tuple[date, date]:
    a = draw(st.integers(min_value=0, max_value=_DAYS_IN_RANGE - 1))
    b = draw(st.integers(min_value=0, max_value=_DAYS_IN_RANGE - 1))
    if a > b:
        a, b = b, a
    return _RANGE_START + timedelta(days=a), _RANGE_START + timedelta(days=b)


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(rng=_date_range())
def test_chunks_cover_all_business_days_no_gap_no_overlap(rng: tuple[date, date]) -> None:
    """União dos chunks == business_days(start, end), sem gap nem overlap."""
    start, end = rng
    expected = b3_business_days_range(start, end)

    chunks = chunk_date_range("WDOJ26", "F", start, end)

    if not expected:
        assert chunks == []
        return

    # Reconstrói a sequência de dias úteis cobertos pelos chunks.
    covered: list[date] = []
    for c in chunks:
        c_start = c.start.date()
        c_end = c.end.date()
        # Cada chunk só contém dias úteis B3 — ignora não-úteis dentro do
        # intervalo (que poderiam aparecer caso start/end caíssem em
        # weekend, mas chunker garante que start/end são dias úteis).
        for d in b3_business_days_range(c_start, c_end):
            covered.append(d)

    # Cobertura completa.
    assert covered == expected, f"covered={covered}, expected={expected}, chunks={chunks}"

    # No-overlap: sequência de dias úteis sem repetição.
    assert len(covered) == len(set(covered)), f"overlap detected: {covered}"


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(rng=_date_range())
def test_each_chunk_size_le_n_business_days(rng: tuple[date, date]) -> None:
    """Para WDO (V1.1.0+ CHUNK_DAYS=1), nenhum chunk tem > 1 dia útil."""
    start, end = rng
    chunks = chunk_date_range("WDOJ26", "F", start, end)
    n_max = CHUNK_DAYS["WDO"]
    for c in chunks:
        days_in_chunk = b3_business_days_range(c.start.date(), c.end.date())
        assert len(days_in_chunk) <= n_max
        assert len(days_in_chunk) >= 1  # nunca 0 — chunker não emite chunks vazios


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(rng=_date_range())
def test_equity_chunks_are_one_business_day_each(rng: tuple[date, date]) -> None:
    """Para PETR4 (equity, default 1), cada chunk tem exatamente 1 dia útil."""
    start, end = rng
    chunks = chunk_date_range("PETR4", "B", start, end)
    for c in chunks:
        days = b3_business_days_range(c.start.date(), c.end.date())
        assert len(days) == 1
