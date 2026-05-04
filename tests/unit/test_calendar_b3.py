"""Unit tests — validation.calendar_b3 (Story 2.1).

Cobre:

- ``is_b3_business_day`` distingue dia útil, sábado, domingo, feriado.
- ``is_holiday`` reconhece feriados conhecidos (Tiradentes 2026,
  Carnaval 2026, etc.).
- ``b3_business_days_range`` retorna lista correta para um mês.
"""

from __future__ import annotations

from datetime import date

import pytest

from data_downloader.validation.calendar_b3 import (
    b3_business_days_range,
    is_b3_business_day,
    is_holiday,
)


@pytest.mark.unit
def test_is_holiday_2026_known_dates() -> None:
    """Tiradentes (21/4/2026), Dia do Trabalho (1/5/2026), Natal (25/12/2026)."""
    assert is_holiday(date(2026, 4, 21))  # Tiradentes
    assert is_holiday(date(2026, 5, 1))  # Dia do Trabalho
    assert is_holiday(date(2026, 12, 25))  # Natal
    # Carnaval 2026 (segunda+terça)
    assert is_holiday(date(2026, 2, 16))
    assert is_holiday(date(2026, 2, 17))
    # Corpus Christi 2026
    assert is_holiday(date(2026, 6, 4))


@pytest.mark.unit
def test_is_holiday_2025_known_dates() -> None:
    """Tiradentes 2025, Carnaval 2025."""
    assert is_holiday(date(2025, 4, 21))  # Tiradentes
    assert is_holiday(date(2025, 3, 3))  # Carnaval segunda
    assert is_holiday(date(2025, 3, 4))  # Carnaval terça
    assert is_holiday(date(2025, 6, 19))  # Corpus Christi 2025


@pytest.mark.unit
def test_is_holiday_returns_false_for_normal_day() -> None:
    """Quarta-feira aleatória de março/2026 não é feriado."""
    assert not is_holiday(date(2026, 3, 11))  # Quarta normal
    assert not is_holiday(date(2026, 3, 12))


@pytest.mark.unit
def test_is_b3_business_day_skips_weekends() -> None:
    """Sábados e domingos não são dias úteis B3."""
    # 2026-03-07 = sábado; 2026-03-08 = domingo
    assert not is_b3_business_day(date(2026, 3, 7))
    assert not is_b3_business_day(date(2026, 3, 8))
    # 2026-03-09 = segunda → dia útil
    assert is_b3_business_day(date(2026, 3, 9))


@pytest.mark.unit
def test_is_b3_business_day_skips_holidays() -> None:
    """Feriados B3 não são dias úteis."""
    # 2026-04-21 = Tiradentes (terça)
    assert not is_b3_business_day(date(2026, 4, 21))
    # Próximo dia útil: 2026-04-22 (quarta)
    assert is_b3_business_day(date(2026, 4, 22))


@pytest.mark.unit
def test_b3_business_days_range_full_week() -> None:
    """Semana de 2026-03-09 (seg) a 2026-03-13 (sex) = 5 dias úteis."""
    days = b3_business_days_range(date(2026, 3, 9), date(2026, 3, 13))
    assert days == [
        date(2026, 3, 9),
        date(2026, 3, 10),
        date(2026, 3, 11),
        date(2026, 3, 12),
        date(2026, 3, 13),
    ]


@pytest.mark.unit
def test_b3_business_days_range_with_holiday() -> None:
    """Semana de Tiradentes 2026: 20-24/4. Tiradentes (21/4) excluído."""
    days = b3_business_days_range(date(2026, 4, 20), date(2026, 4, 24))
    assert date(2026, 4, 21) not in days
    assert date(2026, 4, 20) in days  # segunda
    assert date(2026, 4, 22) in days  # quarta
    assert date(2026, 4, 24) in days  # sexta
    assert len(days) == 4


@pytest.mark.unit
def test_b3_business_days_range_inverted_returns_empty() -> None:
    """``start > end`` retorna lista vazia."""
    assert b3_business_days_range(date(2026, 3, 10), date(2026, 3, 9)) == []


@pytest.mark.unit
def test_b3_business_days_range_single_day_holiday_returns_empty() -> None:
    """Range de 1 dia que é feriado retorna lista vazia."""
    days = b3_business_days_range(date(2026, 4, 21), date(2026, 4, 21))
    assert days == []


@pytest.mark.unit
def test_b3_business_days_range_single_day_business_returns_one() -> None:
    """Range de 1 dia útil retorna lista com 1 elemento."""
    days = b3_business_days_range(date(2026, 3, 9), date(2026, 3, 9))
    assert days == [date(2026, 3, 9)]
