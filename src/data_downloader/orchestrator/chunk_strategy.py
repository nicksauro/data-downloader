"""data_downloader.orchestrator.chunk_strategy — Per-symbol chunk size strategy.

Story 4.16 — Pichau directive (2026-05-07, supersede 2026-05-06):

    "SEMPRE 1 dia útil/chunk, qualquer ativo."

Owner: Dex (impl) | Consult: Pyro (queue saturation baseline — COUNCIL-37),
Aria (fronteira chunker x strategy — ADR-020 Q-DRIFT-37).

Política canônica V1.1.0 (override de TODAS as políticas anteriores —
unifica o granular 1d/chunk para futuros mini, índices cheios e equities):

================  ===================  ===================================
Símbolo           dias úteis B3/chunk  Justificativa
================  ===================  ===================================
``WINFUT``        1                    Volatilidade alta — Q-DRIFT-37
                                        risco de queue overflow.
``WDOFUT``        1                    Feedback per-day na UI.
``INDFUT``        1                    Idem.
``DOLFUT``        1                    Idem.
Equities (PETR4   1                    Política unificada — feedback granular,
VALE3 ITUB4 ...)                        progress per-day.
Outros            1                    Fallback default — política única.
================  ===================  ===================================

Justificativa V1.1.0+ (Pichau directive 2026-05-07):

- **Feedback per-day na UI**: cada chunk = 1 dia útil → barra de progresso
  avança 1/N dias úteis ao final de cada chunk, dando feedback granular.
- **Resilience por chunk granular**: falha em 1 dia útil isolada do
  restante; retry/recovery custa apenas 1 dia, não 5.
- **Q-DRIFT-37 fully mitigated**: queue NUNCA atinge 2M trades em 1 dia
  útil mesmo para WINFUT em pico (baseline Pyro COUNCIL-37: ~400k/dia
  pior caso). Margem de 5x sobre threshold.
- **Política única simplifica catalog/orchestrator**: nenhum override
  per-symbol, comportamento determinístico em toda a stack.

Fronteira com :mod:`data_downloader.orchestrator.chunker`:

- Este módulo expõe SOMENTE :func:`get_chunk_days(symbol)` — wrapper estável
  consumido pelo orchestrator e pela UI (estimativa de progresso).
- ``chunker.chunk_days_for_symbol`` é o detalhe de implementação histórico
  (prefix-map ``CHUNK_DAYS``). Mantemos para compatibilidade de API + tests
  legados (Story 1.7a).
- ``get_chunk_days`` aplica a política canônica V1.1.0 sobre o resultado
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


# Override map — vazio em V1.1.0+ (política unificada 1d/chunk para todos
# os ativos via Pichau directive 2026-05-07). Mantemos a estrutura para
# permitir granularidade futura per-symbol caso surja necessidade empírica.
_CHUNK_OVERRIDES: Final[dict[str, int]] = {}
"""Vazio em v1.1.0+ — política unificada 1d/chunk para todos os ativos.
Mantemos a estrutura para futura granularidade per-symbol se necessário."""


DEFAULT_CHUNK_DAYS: Final[int] = 1
"""Default global v1.1.0+ — TODOS os ativos baixam em 1 dia útil/chunk
(Pichau directive 2026-05-07, supersede 2026-05-06)."""


def get_chunk_days(symbol: str) -> int:
    """Retorna n dias úteis B3 por chunk para um símbolo.

    Aplica a política canônica V1.1.0 (Pichau directive 2026-05-07):

    - **TODOS os ativos** → :data:`DEFAULT_CHUNK_DAYS` (1 dia útil/chunk).
    - O override map (``_CHUNK_OVERRIDES``) é vazio em V1.1.0+ — está
      preservado apenas como hook para granularidade futura per-symbol.

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
        1
        >>> get_chunk_days("PETR4")
        1
        >>> get_chunk_days("indfut")  # case-insensitive
        1
        >>> get_chunk_days("XPTO99")  # desconhecido → default
        1
    """
    return _CHUNK_OVERRIDES.get(symbol.upper(), DEFAULT_CHUNK_DAYS)
