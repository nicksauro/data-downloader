"""Property-based tests — calendário B3 consistência (Story 2.5 AC6).

Hypothesis garante que:

1. Para qualquer data ``d``, ``is_b3_business_day(d)`` é equivalente a
   "weekday < 5 E NOT is_holiday(d)".
2. Idempotência: ``b3_holidays(year)`` chamada N vezes retorna mesmo set.
3. Ano fora de cobertura → ``b3_holidays(year)`` é vazio (e is_holiday
   sempre False para qualquer dia desse ano).
4. Estabilidade do source: enquanto holidays.dat não muda, todas chamadas
   produzem mesmo resultado.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from data_downloader.validation.calendar_b3 import (
    HOLIDAYS_DAT_ENV_VAR,
    _reset_calendar_cache,  # type: ignore[attr-defined]  # test-only
    b3_holidays,
    is_b3_business_day,
    is_holiday,
)


@pytest.fixture(autouse=True)
def _force_hardcoded(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aponta env var para path inexistente — usa hardcoded only.

    Garante reprodutibilidade do property test (não depende de holidays.dat real).
    """
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(tmp_path) + "/nonexistent.dat")  # type: ignore[operator]
    _reset_calendar_cache()
    yield
    _reset_calendar_cache()


# Datas no range 2020-2030 (cobertura hardcoded).
dates_2020_2030 = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)


@pytest.mark.property
@given(d=dates_2020_2030)
@settings(max_examples=200, deadline=None)
def test_business_day_equivale_weekday_e_nao_holiday(d: date) -> None:
    """``is_b3_business_day(d) == (weekday<5 AND NOT is_holiday(d))``."""
    expected = d.weekday() < 5 and not is_holiday(d)
    assert is_b3_business_day(d) == expected


@pytest.mark.property
@given(year=st.integers(min_value=2020, max_value=2030))
@settings(max_examples=11, deadline=None)
def test_b3_holidays_idempotente(year: int) -> None:
    """Chamadas repetidas de b3_holidays(year) retornam mesmo conjunto."""
    first = b3_holidays(year)
    second = b3_holidays(year)
    third = b3_holidays(year)
    assert first == second == third


@pytest.mark.property
@given(year=st.integers(min_value=1990, max_value=2010))
@settings(max_examples=20, deadline=None)
def test_anos_nao_cobertos_retornam_vazio(year: int) -> None:
    """Anos fora do hardcoded (e sem DAT) → b3_holidays vazio."""
    assert b3_holidays(year) == frozenset()


@pytest.mark.property
@given(year=st.integers(min_value=1990, max_value=2010))
@settings(max_examples=20, deadline=None)
def test_anos_nao_cobertos_is_holiday_sempre_false(year: int) -> None:
    """Para anos não cobertos, nenhum dia é feriado."""
    # Sample 5 datas dentro do ano para evitar varrer 365.
    samples = [
        date(year, 1, 1),
        date(year, 4, 15),
        date(year, 7, 1),
        date(year, 9, 30),
        date(year, 12, 31),
    ]
    for d in samples:
        assert not is_holiday(d)


@pytest.mark.property
@given(start=dates_2020_2030, days=st.integers(min_value=0, max_value=30))
@settings(max_examples=100, deadline=None)
def test_business_day_classificacao_estavel_em_chamadas_repetidas(start: date, days: int) -> None:
    """Resultado de is_b3_business_day é estável (cache não corrompe)."""
    target = start + timedelta(days=days)
    if target > date(2030, 12, 31):
        return  # skip out-of-range
    r1 = is_b3_business_day(target)
    r2 = is_b3_business_day(target)
    r3 = is_b3_business_day(target)
    assert r1 == r2 == r3
