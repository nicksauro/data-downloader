"""data_downloader.orchestrator.symbol_alias — Symbol alias resolver.

Story 4.6 / Pichau directive 2026-05-05 — UX simplification (Q-DRIFT-32).

**Q-DRIFT-32 (validated 2026-05-05):** SEMPRE usar o continuous future
``WDOFUT`` / ``WINFUT`` / ``INDFUT`` / ``DOLFUT`` para download histórico
— nunca o contrato com vencimento (ex.: ``WDOJ26``). A DLL retorna mais
dados (cobre a janela inteira, não só o vencimento) e o usuário não
precisa lembrar a letra-do-mês CME (F G H J K M N Q U V X Z).

Equities (PETR4, BBAS3, etc.) ficam diretos — symbology já é estável.
Quando o usuário ainda passa um contrato com vencimento (ex.: WDOJ26)
emitimos ``UserWarning`` recomendando o continuous future, mas
respeitamos o input (alguns flows downstream — backtests por vencimento
específico — ainda querem o ticker exato).

Uso típico::

    from data_downloader.orchestrator.symbol_alias import resolve_alias

    resolve_alias("WDO")     # -> "WDOFUT"
    resolve_alias("WDOFUT")  # -> "WDOFUT"   (passthrough)
    resolve_alias("PETR4")   # -> "PETR4"    (passthrough)
    resolve_alias("WDOJ26")  # -> "WDOJ26"   + UserWarning

Owner: Dex (impl) | Sign-off: Pichau (UX directive 2026-05-05).
"""

from __future__ import annotations

import re
import warnings

__all__ = ["resolve_alias"]


# Raízes de futuros B3 cobertas pelo alias → continuous future.
# Q-DRIFT-32: estes são os 4 contratos com volume relevante para
# data-downloader V1. Outras raízes (ISP, BGI, etc.) podem ser adicionadas
# em V1.x sem quebrar API (passthrough hoje).
_FUT_ROOTS: frozenset[str] = frozenset({"WDO", "WIN", "IND", "DOL"})

# Letra-do-mês CME/B3 (F=jan, G=fev, ... Z=dez; sem I e L).
# Pattern: <root 3 letras> + <letra-mês> + <ano 2 dígitos>.
# Ex: WDOJ26, WINH26, INDM25.
_VENCIMENTO_PATTERN = re.compile(r"^(WDO|WIN|IND|DOL)[FGHJKMNQUVXZ]\d{2}$")


def resolve_alias(symbol: str) -> str:
    """Resolve um símbolo user-friendly para o ticker canônico de download.

    Q-DRIFT-32 (2026-05-05) — recomendação de UX:

    - ``"WDO"`` / ``"WIN"`` / ``"IND"`` / ``"DOL"`` → ``"<ROOT>FUT"`` (continuous future).
    - ``"WDOFUT"`` etc. → passthrough (já é continuous).
    - ``"PETR4"`` / ``"BBAS3"`` etc. → passthrough (equity).
    - ``"WDOJ26"`` etc. (contrato com vencimento) → passthrough +
      ``UserWarning`` recomendando o continuous future.

    Args:
        symbol: Ticker como digitado pelo usuário. Espaços e case são
            normalizados (uppercase, strip).

    Returns:
        Ticker canônico para enviar à DLL / public_api.

    Notes:
        - Símbolo vazio retorna empty string (não levantamos — o caller
          (CLI) já valida no schema typer e emite microcopy específico).
        - O warning usa ``stacklevel=2`` para apontar para o caller.
    """
    s = symbol.upper().strip()

    if not s:
        return s

    if s in _FUT_ROOTS:
        return f"{s}FUT"

    if _VENCIMENTO_PATTERN.match(s):
        warnings.warn(
            (
                f"{s} é contrato com vencimento; recomendado usar "
                f"{s[:3]}FUT (continuous future) — Q-DRIFT-32"
            ),
            UserWarning,
            stacklevel=2,
        )
        return s

    # Passthrough — equities (PETR4, BBAS3, ABEV3) e contratos já em forma
    # canônica (WDOFUT, WINFUT) caem aqui sem warning.
    return s
