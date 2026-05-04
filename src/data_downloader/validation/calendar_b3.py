"""data_downloader.validation.calendar_b3 — Calendário B3 (placeholder).

Owner: 💾 Sol (custodian de calendar policy) +
🧪 Quinn (consumidor primário em gap detection).

Lista hardcoded de feriados nacionais brasileiros 2025-2026 que afetam
B3 (BMF/Bovespa). B3 não opera em feriados nacionais nem fins de semana.

**TODO (story futura):** integrar com ``holidays.dat`` distribuído pela
Nelogica (PROFITDLL_KNOWLEDGE.md §X) — fonte autoritativa. Esta tabela
hardcoded é placeholder ate isso aterrissar.

Política Sol (INTEGRITY.md §6 / finding M17):

- B3 não observa DST desde 2019-01-01.
- Para histórico < 2020, ``timestamp_ns`` BRT NAIVE pode mapear
  ambiguamente a 2 instantes UTC. **Smoke tests + gap detection
  limitados a ``>= 2020-01-01``** salvo flag ``--allow-dst-ambiguity``.

Funções:

- :func:`is_b3_business_day` — ``True`` se ``date`` é dia útil B3.
- :func:`b3_business_days_range` — lista todos os dias úteis B3 em
  ``[start, end]`` (inclusivo nas duas pontas).
- :func:`is_holiday` — ``True`` se ``date`` é feriado B3 conhecido.
"""

from __future__ import annotations

from datetime import date, timedelta

# Feriados nacionais brasileiros 2025-2026 (afetam B3).
# Fonte: legislação federal + tabela B3 oficial; calculados manualmente
# para Carnaval (Páscoa - 47d) e Corpus Christi (Páscoa + 60d).
#
# Páscoa 2025: 20/4 -> Carnaval = 4/3, Corpus Christi = 19/6
# Páscoa 2026: 5/4  -> Carnaval = 17/2, Corpus Christi = 4/6
#
# B3 também adiciona como ponto facultativo: 24/12 e 31/12 (após meio-dia).
# Para o V1 do calendário consideramos APENAS feriados oficiais (não meio-pregão).
_B3_HOLIDAYS_2025_2026: frozenset[date] = frozenset(
    {
        # 2025
        date(2025, 1, 1),  # Confraternização Universal
        date(2025, 3, 3),  # Carnaval (segunda)
        date(2025, 3, 4),  # Carnaval (terça)
        date(2025, 4, 18),  # Sexta-feira Santa
        date(2025, 4, 21),  # Tiradentes
        date(2025, 5, 1),  # Dia do Trabalho
        date(2025, 6, 19),  # Corpus Christi
        date(2025, 9, 7),  # Independência
        date(2025, 10, 12),  # N. Sra. Aparecida
        date(2025, 11, 2),  # Finados
        date(2025, 11, 15),  # Proclamação da República
        date(2025, 11, 20),  # Consciência Negra (feriado nacional desde 2024)
        date(2025, 12, 25),  # Natal
        # 2026
        date(2026, 1, 1),  # Confraternização Universal
        date(2026, 2, 16),  # Carnaval (segunda)
        date(2026, 2, 17),  # Carnaval (terça)
        date(2026, 4, 3),  # Sexta-feira Santa
        date(2026, 4, 21),  # Tiradentes
        date(2026, 5, 1),  # Dia do Trabalho
        date(2026, 6, 4),  # Corpus Christi
        date(2026, 9, 7),  # Independência
        date(2026, 10, 12),  # N. Sra. Aparecida
        date(2026, 11, 2),  # Finados
        date(2026, 11, 15),  # Proclamação da República
        date(2026, 11, 20),  # Consciência Negra
        date(2026, 12, 25),  # Natal
    }
)


def is_holiday(d: date) -> bool:
    """``True`` se ``d`` consta da tabela hardcoded de feriados B3.

    Para datas fora do range coberto (2025-2026), retorna ``False``
    (assumir dia útil pode introduzir falso positivo de gap; ver TODO
    no docstring do módulo).

    Args:
        d: Data a verificar.

    Returns:
        ``True`` se ``d`` é feriado B3 conhecido.
    """
    return d in _B3_HOLIDAYS_2025_2026


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
    "b3_business_days_range",
    "is_b3_business_day",
    "is_holiday",
]
