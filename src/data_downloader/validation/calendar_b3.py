"""data_downloader.validation.calendar_b3 — Calendário B3.

Owner: 💾 Sol (custodian de calendar policy) +
🧪 Quinn (consumidor primário em gap detection).

Story 2.5 — Calendário B3 agora prioriza ``holidays.dat`` distribuído pela
Nelogica em ``profitdll/DLLs/Win64/holidays.dat`` (parsed via
:mod:`data_downloader.validation.holidays_dat_parser`). Tabela hardcoded
2020-2030 permanece como **fallback** para ambientes sem ProfitDLL (CI,
contributors externos) e como **complemento** quando a DAT omite feriados
que caem em fim de semana (Nelogica intencionalmente não lista feriados em
sábado/domingo, pois já não há pregão).

**Fonte ativa em runtime (estratégia COUNCIL-16 mini-council Sol+Nelo+Dex):**

1. Tenta carregar ``holidays.dat`` no path ``HOLIDAYS_DAT_PATH``
   (parametrizável via env ``DATA_DOWNLOADER_HOLIDAYS_DAT_PATH``).
2. Se carregou: feriados do ano = união(parser, hardcoded). Captura tanto
   pontos facultativos (24/12, 31/12) quanto feriados em fim de semana.
3. Se não carregou (arquivo ausente, parse falha): fallback hardcoded puro.
4. Para anos fora do range hardcoded (< 2020 ou > 2030), **só** o parser
   responde. Se parser também não cobre → ``is_holiday`` retorna ``False``
   (caller deve assumir dia útil — pode ser falso positivo de gap).

Política Sol (INTEGRITY.md §6 / finding M17):

- B3 não observa DST desde 2019-01-01.
- Para histórico < 2020, ``timestamp_ns`` BRT NAIVE pode mapear ambiguamente
  a 2 instantes UTC. **Smoke tests + gap detection limitados a
  ``>= 2020-01-01``** salvo flag ``--allow-dst-ambiguity``.

Funções:

- :func:`is_b3_business_day` — ``True`` se ``date`` é dia útil B3.
- :func:`b3_business_days_range` — lista todos os dias úteis B3 em
  ``[start, end]`` (inclusivo nas duas pontas).
- :func:`is_holiday` — ``True`` se ``date`` é feriado B3 conhecido.
- :func:`b3_holidays` — conjunto de feriados B3 para um ano (ou todos os
  anos cobertos se ``year=None``).
"""

from __future__ import annotations

import os
import threading
from datetime import date, timedelta
from pathlib import Path

import structlog

from data_downloader.validation.holidays_dat_parser import (
    HolidaysDatError,
    parse_holidays_dat,
)

logger = structlog.get_logger(__name__)

# Path default do holidays.dat distribuído pela Nelogica. Pode ser
# sobrescrito via env var (útil em CI ou para apontar para fixture de teste).
_DEFAULT_HOLIDAYS_DAT_PATH = Path("profitdll/DLLs/Win64/holidays.dat")

# Env var name para override (usado em testes e CI).
HOLIDAYS_DAT_ENV_VAR = "DATA_DOWNLOADER_HOLIDAYS_DAT_PATH"


def _resolve_holidays_dat_path() -> Path:
    """Resolve path do ``holidays.dat`` (env var ou default).

    Returns:
        Path absoluto. NÃO verifica existência aqui — caller (parse_holidays_dat)
        levanta :class:`HolidaysDatNotFoundError` se faltar.
    """
    env_path = os.environ.get(HOLIDAYS_DAT_ENV_VAR)
    if env_path:
        return Path(env_path).resolve()
    return _DEFAULT_HOLIDAYS_DAT_PATH.resolve()


# =====================================================================
# Tabela hardcoded — fallback + complemento (cobertura 2020-2030).
# =====================================================================
#
# Fonte: legislação federal brasileira + tabela B3 oficial. Carnaval e
# Corpus Christi calculados via Páscoa (algoritmo Gauss / Meeus):
#
# Páscoa 2020: 12/4 -> Carnaval = 24/2,25/2; Corpus = 11/6
# Páscoa 2021: 4/4  -> Carnaval = 15/2,16/2; Corpus = 3/6
# Páscoa 2022: 17/4 -> Carnaval = 28/2,1/3;  Corpus = 16/6
# Páscoa 2023: 9/4  -> Carnaval = 20/2,21/2; Corpus = 8/6
# Páscoa 2024: 31/3 -> Carnaval = 12/2,13/2; Corpus = 30/5
# Páscoa 2025: 20/4 -> Carnaval = 4/3,5/3*;  Corpus = 19/6
# Páscoa 2026: 5/4  -> Carnaval = 17/2,18/2*;Corpus = 4/6
# Páscoa 2027: 28/3 -> Carnaval = 9/2,10/2*; Corpus = 27/5
# Páscoa 2028: 16/4 -> Carnaval = 28/2,29/2*;Corpus = 15/6
# Páscoa 2029: 1/4  -> Carnaval = 13/2,14/2*;Corpus = 31/5
# Páscoa 2030: 21/4 -> Carnaval = 4/3,5/3*;  Corpus = 20/6
#
# *Convenção B3: Carnaval feriado = segunda + terça (não quarta-Cinzas).
#
# Consciência Negra (20/11) é feriado nacional desde 2024 (Lei 14.759/2023).
# Para 2020-2023 NÃO incluído (não era feriado nacional ainda).
_B3_HOLIDAYS_2020_2030: frozenset[date] = frozenset(
    {
        # 2020
        date(2020, 1, 1),  # Confraternização
        date(2020, 2, 24),  # Carnaval seg
        date(2020, 2, 25),  # Carnaval ter
        date(2020, 4, 10),  # Sexta-feira Santa
        date(2020, 4, 21),  # Tiradentes
        date(2020, 5, 1),  # Trabalho
        date(2020, 6, 11),  # Corpus Christi
        date(2020, 9, 7),  # Independência
        date(2020, 10, 12),  # Aparecida
        date(2020, 11, 2),  # Finados
        date(2020, 11, 15),  # Proclamação
        date(2020, 12, 25),  # Natal
        # 2021
        date(2021, 1, 1),
        date(2021, 2, 15),  # Carnaval seg
        date(2021, 2, 16),  # Carnaval ter
        date(2021, 4, 2),  # Sexta Santa
        date(2021, 4, 21),
        date(2021, 5, 1),
        date(2021, 6, 3),  # Corpus
        date(2021, 9, 7),
        date(2021, 10, 12),
        date(2021, 11, 2),
        date(2021, 11, 15),
        date(2021, 12, 25),
        # 2022
        date(2022, 1, 1),
        date(2022, 2, 28),  # Carnaval seg
        date(2022, 3, 1),  # Carnaval ter
        date(2022, 4, 15),  # Sexta Santa
        date(2022, 4, 21),
        date(2022, 5, 1),
        date(2022, 6, 16),
        date(2022, 9, 7),
        date(2022, 10, 12),
        date(2022, 11, 2),
        date(2022, 11, 15),
        date(2022, 12, 25),
        # 2023
        date(2023, 1, 1),
        date(2023, 2, 20),
        date(2023, 2, 21),
        date(2023, 4, 7),
        date(2023, 4, 21),
        date(2023, 5, 1),
        date(2023, 6, 8),
        date(2023, 9, 7),
        date(2023, 10, 12),
        date(2023, 11, 2),
        date(2023, 11, 15),
        date(2023, 12, 25),
        # 2024
        date(2024, 1, 1),
        date(2024, 2, 12),
        date(2024, 2, 13),
        date(2024, 3, 29),  # Sexta Santa
        date(2024, 4, 21),
        date(2024, 5, 1),
        date(2024, 5, 30),  # Corpus Christi
        date(2024, 9, 7),
        date(2024, 10, 12),
        date(2024, 11, 2),
        date(2024, 11, 15),
        date(2024, 11, 20),  # Consciência Negra (1º ano nacional)
        date(2024, 12, 25),
        # 2025
        date(2025, 1, 1),
        date(2025, 3, 3),
        date(2025, 3, 4),
        date(2025, 4, 18),
        date(2025, 4, 21),
        date(2025, 5, 1),
        date(2025, 6, 19),
        date(2025, 9, 7),
        date(2025, 10, 12),
        date(2025, 11, 2),
        date(2025, 11, 15),
        date(2025, 11, 20),
        date(2025, 12, 25),
        # 2026
        date(2026, 1, 1),
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 4, 3),
        date(2026, 4, 21),
        date(2026, 5, 1),
        date(2026, 6, 4),
        date(2026, 9, 7),
        date(2026, 10, 12),
        date(2026, 11, 2),
        date(2026, 11, 15),
        date(2026, 11, 20),
        date(2026, 12, 25),
        # 2027
        date(2027, 1, 1),
        date(2027, 2, 8),
        date(2027, 2, 9),
        date(2027, 3, 26),
        date(2027, 4, 21),
        date(2027, 5, 1),
        date(2027, 5, 27),
        date(2027, 9, 7),
        date(2027, 10, 12),
        date(2027, 11, 2),
        date(2027, 11, 15),
        date(2027, 11, 20),
        date(2027, 12, 25),
        # 2028
        date(2028, 1, 1),
        date(2028, 2, 28),
        date(2028, 2, 29),
        date(2028, 4, 14),
        date(2028, 4, 21),
        date(2028, 5, 1),
        date(2028, 6, 15),
        date(2028, 9, 7),
        date(2028, 10, 12),
        date(2028, 11, 2),
        date(2028, 11, 15),
        date(2028, 11, 20),
        date(2028, 12, 25),
        # 2029
        date(2029, 1, 1),
        date(2029, 2, 12),
        date(2029, 2, 13),
        date(2029, 3, 30),
        date(2029, 4, 21),
        date(2029, 5, 1),
        date(2029, 5, 31),
        date(2029, 9, 7),
        date(2029, 10, 12),
        date(2029, 11, 2),
        date(2029, 11, 15),
        date(2029, 11, 20),
        date(2029, 12, 25),
        # 2030
        date(2030, 1, 1),
        date(2030, 3, 4),
        date(2030, 3, 5),
        date(2030, 4, 19),
        date(2030, 4, 21),
        date(2030, 5, 1),
        date(2030, 6, 20),
        date(2030, 9, 7),
        date(2030, 10, 12),
        date(2030, 11, 2),
        date(2030, 11, 15),
        date(2030, 11, 20),
        date(2030, 12, 25),
    }
)


# =====================================================================
# Tabela hardcoded — extensão pré-2020 (Story 4.32 backfill 2013-2017).
# =====================================================================
#
# Nelogica's ``holidays.dat`` tem cobertura severamente esparsa para 2013
# (apenas 01-01) e gaps menores em outros anos pré-2020. Esta tabela
# preenche as lacunas, permitindo o backfill 2013-2017 rodar sem stalls
# em dias de não-pregão. Fonte: B3 official calendar + computus de
# Easter/Carnaval/Corpus (Meeus), filtrando feriados em fim de semana
# per Nelogica convention. Inclui feriados estaduais SP (Aniversário SP
# 25/01, Revolução Constitucionalista 09/07) e Consciência Negra (20/11,
# B3 SP pré-lei nacional 2024).
_B3_HOLIDAYS_2013_2017: frozenset[date] = frozenset(
    {
        # 2013 (Easter Mar 31; Carnaval Feb 11-12; Corpus May 30)
        date(2013, 1, 1),  # Confraternização (ter)
        date(2013, 1, 25),  # Aniversário SP (sex)
        date(2013, 2, 11),  # Carnaval seg
        date(2013, 2, 12),  # Carnaval ter
        date(2013, 3, 29),  # Sexta-feira Santa
        date(2013, 5, 1),  # Trabalho (qua)
        date(2013, 5, 30),  # Corpus Christi (qui)
        date(2013, 7, 9),  # Revolução Constitucionalista (ter)
        date(2013, 11, 15),  # Proclamação (sex)
        date(2013, 11, 20),  # Consciência Negra (qua, B3 SP)
        date(2013, 12, 24),  # Véspera Natal (ter)
        date(2013, 12, 25),  # Natal (qua)
        date(2013, 12, 31),  # Véspera Ano Novo (ter)
        # 2014 (Easter Apr 20; Carnaval Mar 3-4; Corpus Jun 19)
        date(2014, 1, 1),
        date(2014, 3, 3),
        date(2014, 3, 4),
        date(2014, 4, 18),
        date(2014, 4, 21),
        date(2014, 5, 1),
        date(2014, 6, 19),
        date(2014, 7, 9),
        date(2014, 11, 20),
        date(2014, 12, 24),
        date(2014, 12, 25),
        date(2014, 12, 31),
        # 2015 (Easter Apr 5; Carnaval Feb 16-17; Corpus Jun 4)
        date(2015, 1, 1),
        date(2015, 2, 16),
        date(2015, 2, 17),
        date(2015, 4, 3),
        date(2015, 4, 21),
        date(2015, 5, 1),
        date(2015, 6, 4),
        date(2015, 7, 9),
        date(2015, 9, 7),
        date(2015, 10, 12),
        date(2015, 11, 2),
        date(2015, 11, 20),
        date(2015, 12, 24),
        date(2015, 12, 25),
        date(2015, 12, 31),
        # 2016 (Easter Mar 27; Carnaval Feb 8-9; Corpus May 26)
        date(2016, 1, 1),
        date(2016, 1, 25),
        date(2016, 2, 8),
        date(2016, 2, 9),
        date(2016, 3, 25),
        date(2016, 4, 21),
        date(2016, 5, 26),
        date(2016, 9, 7),
        date(2016, 10, 12),
        date(2016, 11, 2),
        date(2016, 11, 15),
        date(2016, 12, 30),  # substitui 12-31 (sab)
        # 2017 (Easter Apr 16; Carnaval Feb 27-28; Corpus Jun 15)
        date(2017, 1, 25),
        date(2017, 2, 27),
        date(2017, 2, 28),
        date(2017, 4, 14),
        date(2017, 4, 21),
        date(2017, 5, 1),
        date(2017, 6, 15),
        date(2017, 9, 7),
        date(2017, 10, 12),
        date(2017, 11, 2),
        date(2017, 11, 15),
        date(2017, 11, 20),
        date(2017, 12, 25),
        date(2017, 12, 29),  # substitui 12-31 (dom)
    }
)


# União hardcoded total: 2013-2017 + 2020-2030. Anos 2018-2019 são cobertos
# adequadamente pelo ``holidays.dat`` (verificado 2026-05-25).
_B3_HOLIDAYS_HARDCODED: frozenset[date] = _B3_HOLIDAYS_2013_2017 | _B3_HOLIDAYS_2020_2030


# Cache do conjunto efetivo (parser + hardcoded). Lazy-loaded no primeiro
# uso de is_holiday / b3_holidays. Reset via :func:`_reset_calendar_cache`
# (testes) ou automaticamente quando mtime do holidays.dat mudar.
_effective_lock = threading.Lock()
_effective_cache: frozenset[date] | None = None
_effective_source: str | None = None  # "dat+hardcoded" | "hardcoded_only"
_effective_dat_mtime: int | None = None


def _load_effective_holidays() -> frozenset[date]:
    """Carrega conjunto efetivo de feriados (parser UNION hardcoded).

    Cache módulo com invalidação por mtime do ``holidays.dat``. Se arquivo
    não existe ou parse falha, retorna apenas hardcoded (com log INFO/WARN).

    Returns:
        ``frozenset`` de feriados B3 cobertos por parser e/ou hardcoded.
    """
    global _effective_cache, _effective_source, _effective_dat_mtime

    dat_path = _resolve_holidays_dat_path()
    current_mtime: int | None = None
    if dat_path.is_file():
        try:
            current_mtime = dat_path.stat().st_mtime_ns
        except OSError:  # pragma: no cover — defensivo
            current_mtime = None

    with _effective_lock:
        if _effective_cache is not None and _effective_dat_mtime == current_mtime:
            return _effective_cache

        if dat_path.is_file():
            try:
                from_dat = parse_holidays_dat(dat_path)
                merged = _B3_HOLIDAYS_HARDCODED | from_dat
                _effective_cache = merged
                _effective_source = "dat+hardcoded"
                _effective_dat_mtime = current_mtime
                logger.info(
                    "calendar_b3.source",
                    source="dat+hardcoded",
                    dat_path=str(dat_path),
                    dat_holidays=len(from_dat),
                    hardcoded_holidays=len(_B3_HOLIDAYS_HARDCODED),
                    total=len(merged),
                )
                return merged
            except HolidaysDatError as exc:
                logger.warning(
                    "calendar_b3.dat_parse_failed",
                    dat_path=str(dat_path),
                    error=str(exc),
                    fallback="hardcoded_only",
                )
        else:
            logger.info(
                "calendar_b3.source",
                source="hardcoded_only",
                reason="holidays.dat not found at default path; using hardcoded 2020-2030",
                dat_path=str(dat_path),
            )

        _effective_cache = _B3_HOLIDAYS_HARDCODED
        _effective_source = "hardcoded_only"
        _effective_dat_mtime = None
        return _effective_cache


def _reset_calendar_cache() -> None:
    """Reseta cache do calendário (uso em testes — não API pública).

    Necessário quando teste muda env var ``DATA_DOWNLOADER_HOLIDAYS_DAT_PATH``
    ou quando outro teste alterou o filesystem.
    """
    global _effective_cache, _effective_source, _effective_dat_mtime
    with _effective_lock:
        _effective_cache = None
        _effective_source = None
        _effective_dat_mtime = None
    # Também limpa o cache do parser (mtime-based, mas safe limpar em testes).
    from data_downloader.validation.holidays_dat_parser import clear_cache

    clear_cache()


def b3_holidays(year: int | None = None) -> frozenset[date]:
    """Retorna feriados B3 conhecidos.

    Args:
        year: Se especificado, filtra apenas feriados desse ano. Se ``None``,
            retorna todos os feriados de todos os anos cobertos
            (parser + hardcoded).

    Returns:
        ``frozenset`` de :class:`datetime.date`. Vazio se ``year`` está fora
        de toda cobertura (parser + hardcoded).

    Example:
        >>> from datetime import date
        >>> holidays_2025 = b3_holidays(2025)
        >>> date(2025, 12, 25) in holidays_2025
        True
    """
    effective = _load_effective_holidays()
    if year is None:
        return effective
    return frozenset(d for d in effective if d.year == year)


def is_holiday(d: date) -> bool:
    """``True`` se ``d`` é feriado B3 conhecido (parser UNION hardcoded).

    Para datas fora da cobertura efetiva, retorna ``False`` (assumir dia
    útil pode introduzir falso positivo de gap; ver M17 DST policy).

    Args:
        d: Data a verificar.

    Returns:
        ``True`` se ``d`` é feriado B3 conhecido.
    """
    return d in _load_effective_holidays()


def is_b3_business_day(d: date) -> bool:
    """``True`` se ``d`` é dia útil B3 (não fim de semana, não feriado).

    Args:
        d: Data a verificar.

    Returns:
        ``False`` se sábado/domingo OU feriado conhecido; ``True`` caso
        contrário.
    """
    if d.weekday() >= 5:  # 5 = sábado, 6 = domingo
        return False
    return not is_holiday(d)


def b3_business_days_range(start: date, end: date) -> list[date]:
    """Lista de dias úteis B3 em ``[start, end]`` (inclusivo).

    Itera dia a dia (range típico de meses; performance acceptável para
    janelas até alguns anos). Para janelas multi-década, otimizar com
    ``pandas.bdate_range`` + filtro de feriados (deferred).

    Args:
        start: Início do range (inclusivo).
        end: Fim do range (inclusivo).

    Returns:
        Lista ordenada de ``date`` que são dias úteis B3. Vazia se
        ``start > end``.
    """
    if start > end:
        return []

    days: list[date] = []
    cur = start
    while cur <= end:
        if is_b3_business_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


__all__ = [
    "HOLIDAYS_DAT_ENV_VAR",
    "b3_business_days_range",
    "b3_holidays",
    "is_b3_business_day",
    "is_holiday",
]
