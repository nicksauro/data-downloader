"""Unit tests — calendar_b3 cobertura estendida 2020-2030 (Story 2.5).

Valida que `is_holiday` e `b3_holidays` cobrem feriados nacionais brasileiros
em todo o range 2020-2030 (vs original que cobria apenas 2025-2026).

Ground truth: tabela hardcoded interna ``_B3_HOLIDAYS_2020_2030`` —
feriados oficiais BR calculados via Páscoa + datas fixas (legislação federal).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from data_downloader.validation.calendar_b3 import (
    HOLIDAYS_DAT_ENV_VAR,
    _reset_calendar_cache,  # type: ignore[attr-defined]  # private cache reset (test-only)
    b3_business_days_range,
    b3_holidays,
    is_b3_business_day,
    is_holiday,
)


@pytest.fixture(autouse=True)
def _force_hardcoded_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aponta env var para path inexistente → força fallback hardcoded only.

    Garante isolamento: testes de cobertura hardcoded NÃO devem depender
    de holidays.dat real.
    """
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(tmp_path / "nonexistent.dat"))
    _reset_calendar_cache()
    yield
    _reset_calendar_cache()


# =====================================================================
# Datas fixas (não dependem de Páscoa) — válidas em todos os anos cobertos
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_confraternizacao_universal_jan1(year: int) -> None:
    """1 de janeiro é feriado em todo ano coberto."""
    assert is_holiday(date(year, 1, 1))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_tiradentes_abr21(year: int) -> None:
    """21 de abril (Tiradentes) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 4, 21))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_dia_trabalho_mai1(year: int) -> None:
    """1 de maio (Dia do Trabalho) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 5, 1))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_natal_dez25(year: int) -> None:
    """25 de dezembro (Natal) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 12, 25))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_independencia_set7(year: int) -> None:
    """7 de setembro (Independência) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 9, 7))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_aparecida_out12(year: int) -> None:
    """12 de outubro (N. Sra. Aparecida) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 10, 12))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_finados_nov2(year: int) -> None:
    """2 de novembro (Finados) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 11, 2))


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_proclamacao_nov15(year: int) -> None:
    """15 de novembro (Proclamação) é feriado em todo ano coberto."""
    assert is_holiday(date(year, 11, 15))


# =====================================================================
# Feriados móveis (Carnaval, Sexta Santa, Corpus Christi) — calculados
# via Páscoa.
# =====================================================================


@pytest.mark.unit
def test_carnaval_seg_ter_movel() -> None:
    """Carnaval (segunda + terça) cai em datas calculadas via Páscoa."""
    # Páscoa 2024 = 31/3 → Carnaval = 12/2,13/2
    assert is_holiday(date(2024, 2, 12))
    assert is_holiday(date(2024, 2, 13))
    # Páscoa 2025 = 20/4 → Carnaval = 4/3 (terça? na verdade seg=3/3 ter=4/3)
    assert is_holiday(date(2025, 3, 3))
    assert is_holiday(date(2025, 3, 4))
    # Páscoa 2030 = 21/4 → Carnaval = 4/3,5/3
    assert is_holiday(date(2030, 3, 4))
    assert is_holiday(date(2030, 3, 5))


@pytest.mark.unit
def test_sexta_feira_santa_movel() -> None:
    """Sexta-feira Santa = Páscoa - 2."""
    assert is_holiday(date(2024, 3, 29))  # Páscoa 31/3
    assert is_holiday(date(2025, 4, 18))  # Páscoa 20/4
    assert is_holiday(date(2026, 4, 3))  # Páscoa 5/4


@pytest.mark.unit
def test_corpus_christi_movel() -> None:
    """Corpus Christi = Páscoa + 60 dias."""
    assert is_holiday(date(2024, 5, 30))
    assert is_holiday(date(2025, 6, 19))
    assert is_holiday(date(2026, 6, 4))
    assert is_holiday(date(2027, 5, 27))


# =====================================================================
# Consciência Negra — feriado nacional desde 2024 (Lei 14.759/2023).
# =====================================================================


@pytest.mark.unit
def test_consciencia_negra_nacional_desde_2024() -> None:
    """20/11 é feriado nacional desde 2024 inclusive."""
    assert is_holiday(date(2024, 11, 20))
    assert is_holiday(date(2025, 11, 20))
    assert is_holiday(date(2026, 11, 20))


@pytest.mark.unit
def test_consciencia_negra_nao_era_nacional_pre_2024() -> None:
    """Pré-2024 NÃO está como feriado nacional no hardcoded."""
    # 2020-2023: era apenas feriado estadual (RJ, SP, etc.) — não nacional.
    assert not is_holiday(date(2020, 11, 20))
    assert not is_holiday(date(2023, 11, 20))


# =====================================================================
# Não-feriados (sanity check)
# =====================================================================


@pytest.mark.unit
def test_dias_uteis_nao_sao_feriado() -> None:
    """Quartas-feiras aleatórias não são feriado."""
    assert not is_holiday(date(2025, 1, 8))
    assert not is_holiday(date(2026, 7, 15))
    assert not is_holiday(date(2030, 8, 14))


# =====================================================================
# b3_holidays() filtragem por ano
# =====================================================================


@pytest.mark.unit
def test_b3_holidays_por_ano() -> None:
    """b3_holidays(year) retorna apenas feriados desse ano."""
    holidays_2025 = b3_holidays(2025)
    assert all(d.year == 2025 for d in holidays_2025)
    # Esperado: 13 feriados nacionais em 2025.
    assert len(holidays_2025) >= 13


@pytest.mark.unit
def test_b3_holidays_sem_year_retorna_tudo() -> None:
    """b3_holidays() sem args retorna todos os anos cobertos."""
    all_holidays = b3_holidays()
    assert len(all_holidays) >= 130  # 11 anos x 12-13/ano
    years = {d.year for d in all_holidays}
    assert 2020 in years
    assert 2030 in years


@pytest.mark.unit
def test_b3_holidays_ano_nao_coberto_retorna_vazio() -> None:
    """Ano fora do range hardcoded (e sem DAT) retorna vazio."""
    # 1990 não está em nenhuma fonte → vazio.
    holidays_1990 = b3_holidays(1990)
    assert holidays_1990 == frozenset()


# =====================================================================
# Cobertura mínima (AC4)
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize("year", list(range(2020, 2031)))
def test_cobertura_minima_por_ano(year: int) -> None:
    """Cada ano 2020-2030 tem >= 9 feriados (AC4 da story).

    Nota: anos antigos (2020-2023) não tinham Consciência Negra como
    feriado nacional, e alguns feriados podem cair em FDS (não contam para
    pregão). Mínimo realista: 9 feriados/ano.
    """
    holidays = b3_holidays(year)
    assert len(holidays) >= 9, f"year {year}: only {len(holidays)} holidays"


# =====================================================================
# is_b3_business_day integração
# =====================================================================


@pytest.mark.unit
def test_is_b3_business_day_2030_natal() -> None:
    """Natal 2030 (quarta) NÃO é dia útil B3."""
    assert not is_b3_business_day(date(2030, 12, 25))


@pytest.mark.unit
def test_is_b3_business_day_2020_jan1() -> None:
    """1/1/2020 (quarta) NÃO é dia útil B3 (era ano novo)."""
    assert not is_b3_business_day(date(2020, 1, 1))


@pytest.mark.unit
def test_b3_business_days_range_carnaval_2022() -> None:
    """Semana de Carnaval 2022 (28/2 + 1/3) — ambos excluídos."""
    days = b3_business_days_range(date(2022, 2, 28), date(2022, 3, 4))
    # 28/2 (seg) e 1/3 (ter) são feriados; 2/3 quarta-feira de cinzas em V1
    # NÃO é feriado (pregão parcial); 3-4/3 dias úteis.
    assert date(2022, 2, 28) not in days
    assert date(2022, 3, 1) not in days
    assert date(2022, 3, 2) in days  # Cinzas V1 = dia útil
    assert date(2022, 3, 3) in days
    assert date(2022, 3, 4) in days
