"""data_downloader.orchestrator.chunk_strategy — Per-symbol chunk size strategy.

Story 4.16 — Pichau directive (2026-05-06):

    "WDOFUT baixa sempre em chunks de 5, WINFUT baixa sempre em chunks de 1,
    qualquer ação ibovespa baixa em chunks de 5, o restante dos futuros podemos
    baixar em chunk de 5 tbm."

Owner: Dex (impl) | Consult: Pyro (queue saturation baseline — COUNCIL-37),
Aria (fronteira chunker x strategy — ADR-020 Q-DRIFT-37).

Política canônica V1.0.4 (override do default 1d/equity histórico):

================  ===================  ===================================
Símbolo           dias úteis B3/chunk  Justificativa
================  ===================  ===================================
``WINFUT``        1                    Volatilidade alta — Q-DRIFT-37 risco
                                        de queue overflow se baixar 5d
                                        (COUNCIL-37 Pyro queue baseline).
``WDOFUT``        5                    Throughput vs DLL stability OK em 5d.
``INDFUT``        5                    Idem WDOFUT (futuros com vazão média).
``DOLFUT``        5                    Idem.
Equities (PETR4   5                    Pichau directive: tickers Ibovespa
VALE3 ITUB4 ...)                        baixam em 5d para reduzir N de
                                        chamadas DLL (era 1d default).
Outros            5                    Fallback conservador: 5d cobre o
                                        bulk dos casos sem risco de overflow.
================  ===================  ===================================

Fronteira com :mod:`data_downloader.orchestrator.chunker`:

- Este módulo expõe SOMENTE :func:`get_chunk_days(symbol)` — wrapper estável
  consumido pelo orchestrator e pela UI (estimativa de progresso).
- ``chunker.chunk_days_for_symbol`` é o detalhe de implementação histórico
  (prefix-map ``CHUNK_DAYS``). Mantemos para compatibilidade de API + tests
  legados (Story 1.7a).
- ``get_chunk_days`` aplica o **override de Story 4.16** sobre o resultado
  base, garantindo política única em toda a stack (orchestrator + UI).

LEIS RESPEITADAS:
- Pure function — sem I/O, sem state, sem dependência de catalog ou DLL.
- Determinístico: mesma entrada = mesma saída (idempotência R5 amigável).
- Case-insensitive: caller pode passar ``"winfut"`` ou ``"WINFUT"``.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "DEFAULT_CHUNK_DAYS",
    "get_chunk_days",
]


# Override map — símbolos que escapam do default de 5 dias úteis.
# WINFUT é o único caso conhecido com risco de queue overflow em chunk=5d
# (Q-DRIFT-37 — COUNCIL-37 Pyro queue baseline). Outros futuros e equities
# rodam confortavelmente em 5d. Mantemos o map enxuto: cada entrada nova
# precisa de justificativa empírica (Pichau directive 2026-05-06).
_CHUNK_OVERRIDES: Final[dict[str, int]] = {
    "WINFUT": 1,  # alta volatilidade — evita Q-DRIFT-37 queue overflow
}


DEFAULT_CHUNK_DAYS: Final[int] = 5
"""Default global Story 4.16 — futuros + equities baixam em 5 dias úteis."""


def get_chunk_days(symbol: str) -> int:
    """Retorna n dias úteis B3 por chunk para um símbolo.

    Aplica a política canônica V1.0.4 (Pichau directive 2026-05-06):

    - ``WINFUT`` → 1 (override por queue saturation risk).
    - Demais (``WDOFUT``, ``INDFUT``, ``DOLFUT``, equities, raízes,
      contratos vigentes, símbolos desconhecidos) → :data:`DEFAULT_CHUNK_DAYS`
      (5 dias úteis).

    Case-insensitive: ``"winfut"``, ``"WinFut"``, ``"WINFUT"`` resolvem
    igual.

    Args:
        symbol: Código do símbolo (e.g. ``"WDOFUT"``, ``"PETR4"``,
            ``"WINFUT"``). Convenções B3 ou raiz.

    Returns:
        Inteiro positivo ``>= 1`` — dias úteis B3 por chunk.

    Examples:
        >>> get_chunk_days("WINFUT")
        1
        >>> get_chunk_days("WDOFUT")
        5
        >>> get_chunk_days("PETR4")
        5
        >>> get_chunk_days("indfut")  # case-insensitive
        5
        >>> get_chunk_days("XPTO99")  # desconhecido → default
        5
    """
    return _CHUNK_OVERRIDES.get(symbol.upper(), DEFAULT_CHUNK_DAYS)
