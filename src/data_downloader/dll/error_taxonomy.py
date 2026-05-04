"""data_downloader.dll.error_taxonomy — Categorização semântica de NL_*.

Owner: Nelo (DLL authority — categorização) + Dex (impl) + Aria (fronteira).
Story 2.6 (Retry inteligente + circuit breaker) — AC1.

Cada código ``NL_*`` é categorizado em :class:`ErrorCategory` para que o
:class:`~data_downloader.orchestrator.retry_policy.RetryPolicy` possa decidir
**por categoria** (NÃO por código individual) se deve retry, fail-fast ou
disparar handling especial:

- ``TRANSIENT`` — falhas auto-recuperáveis (timeout, queue full, rede): RETRY.
- ``PERMANENT`` — erros lógicos / de configuração (license, ticker inválido,
  args malformados, plataforma não suportada): NO RETRY (R7 — fail fast).
- ``AMBIGUOUS`` — códigos onde semantics depende do contexto: RETRY com cap
  menor + jitter mais agressivo.
- ``UNKNOWN`` — código novo / não-categorizado: NO RETRY (lei R7 conservadora).

Categorias são imutáveis (tabela compile-time) — qualquer mudança requer
audit Nelo + bump de tabela.

Constraint Q02-E (quirk reconnect 99%):
    Esta tabela mapeia somente *códigos NL_* retornados pela DLL*. O
    quirk Q02-E (progress=99% repetindo durante reconexão) NÃO é um NL_*
    — é estado de fluxo. O hook progress-aware no breaker
    (orchestrator/circuit_breaker.py) é quem trata esse caso, NÃO esta
    tabela.

Referências:
    - ``profitdll/Exemplo Python/main.py`` L13-48 — códigos canônicos.
    - ``profitdll/Exemplo C++/profit.h`` L217-222 — fonte oficial Nelogica.
    - ``docs/dll/PROFITDLL_KNOWLEDGE.md`` §5 — categorias high-level Nelo.
    - ``docs/dll/QUIRKS.md`` Q02-E — workaround formalizado em Story 2.6.
    - ``agents/profitdll-specialist.md`` — Nelo authority sobre semantics.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, NamedTuple

__all__ = [
    "NL_CATEGORY_MAP",
    "ErrorCategory",
    "NLErrorCategory",
    "categorize_nl",
    "is_retryable",
]


class ErrorCategory(StrEnum):
    """Categoria semântica de um código NL_* (Story 2.6 AC1)."""

    TRANSIENT = "transient"
    AMBIGUOUS = "ambiguous"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class NLErrorCategory(NamedTuple):
    """Resultado de :func:`categorize_nl` — categoria + justificativa.

    Attributes:
        code: Código numérico original (negativo = erro, 0 = sucesso).
        name: Nome simbólico canônico ou ``"NL_UNKNOWN_<code>"``.
        category: :class:`ErrorCategory` decidida pela tabela Nelo.
        justification: String curta explicando POR QUE essa categoria.
    """

    code: int
    name: str
    category: ErrorCategory
    justification: str


# =====================================================================
# Códigos canônicos da DLL — fonte: profit.h L217-222 + main.py L13-48
# =====================================================================

_NL_OK: Final[int] = 0
_NL_INTERNAL_ERROR: Final[int] = -2147483647  # 0x80000001
_NL_NOT_INITIALIZED: Final[int] = -2147483646  # 0x80000002
_NL_INVALID_ARGS: Final[int] = -2147483645  # 0x80000003
_NL_WAITING_SERVER: Final[int] = -2147483644  # 0x80000004
_NL_NO_LOGIN: Final[int] = -2147483643  # 0x80000005
_NL_NO_LICENSE: Final[int] = -2147483642  # 0x80000006
_NL_PASSWORD_HASH_SHA1: Final[int] = -2147483641
_NL_PASSWORD_HASH_MD5: Final[int] = -2147483640
_NL_OUT_OF_RANGE: Final[int] = -2147483639
_NL_MARKET_ONLY: Final[int] = -2147483638
_NL_NO_POSITION: Final[int] = -2147483637
_NL_NOT_FOUND: Final[int] = -2147483636
_NL_VERSION_NOT_SUPPORTED: Final[int] = -2147483635
_NL_OCO_NO_RULES: Final[int] = -2147483634
_NL_EXCHANGE_UNKNOWN: Final[int] = -2147483633
_NL_NO_OCO_DEFINED: Final[int] = -2147483632
_NL_INVALID_SERIE: Final[int] = -2147483631
_NL_LICENSE_NOT_ALLOWED: Final[int] = -2147483630
_NL_NOT_HARD_LOGOUT: Final[int] = -2147483629
_NL_SERIE_NO_HISTORY: Final[int] = -2147483628
_NL_ASSET_NO_DATA: Final[int] = -2147483627
_NL_SERIE_NO_DATA: Final[int] = -2147483626
_NL_HAS_STRATEGY_RUNNING: Final[int] = -2147483625
_NL_SERIE_NO_MORE_HISTORY: Final[int] = -2147483624
_NL_SERIE_MAX_COUNT: Final[int] = -2147483623
_NL_DUPLICATE_RESOURCE: Final[int] = -2147483622
_NL_UNSIGNED_CONTRACT: Final[int] = -2147483621
_NL_NO_PASSWORD: Final[int] = -2147483620
_NL_NO_USER: Final[int] = -2147483619
_NL_FILE_ALREADY_EXISTS: Final[int] = -2147483618
_NL_INVALID_TICKER: Final[int] = -2147483617
_NL_NOT_MASTER_ACCOUNT: Final[int] = -2147483616

# Códigos LEGACY mantidos no `dll/errors.py` (Story 1.2). Story 2.6 honra
# para que decode_nl_error e categorize_nl reconheçam o mesmo conjunto.
_NL_INVALID_ARGS_LEGACY: Final[int] = -2147483393
_NL_NO_LICENSE_LEGACY: Final[int] = -2147483392
_NL_NO_LOGIN_LEGACY: Final[int] = -2147483391
_NL_INVALID_TICKER_LEGACY: Final[int] = -2147483390
_NL_EXCHANGE_UNKNOWN_LEGACY: Final[int] = -2147483389

# Sentinela interna do wrapper (NÃO vem da DLL).
_DLL_SENTINEL: Final[int] = -1


# =====================================================================
# Tabela canônica NL_* → categoria — auditoria Nelo Story 2.6
# =====================================================================

NL_CATEGORY_MAP: Final[dict[int, tuple[str, ErrorCategory, str]]] = {
    # Sucesso (não-erro; PERMANENT impede retry sobre code=0).
    _NL_OK: (
        "NL_OK",
        ErrorCategory.PERMANENT,
        "Sucesso (não-erro). Categoria PERMANENT impede retry sobre code=0.",
    ),
    # Internos
    _NL_INTERNAL_ERROR: (
        "NL_INTERNAL_ERROR",
        ErrorCategory.TRANSIENT,
        "Erro interno DLL — geralmente race/state inconsistente. Retry "
        "pode resolver após ConnectorThread reciclar.",
    ),
    _NL_NOT_INITIALIZED: (
        "NL_NOT_INITIALIZED",
        ErrorCategory.PERMANENT,
        "DLL não inicializada — bug lógico do caller. R7 fail fast.",
    ),
    _NL_INVALID_ARGS: (
        "NL_INVALID_ARGS",
        ErrorCategory.PERMANENT,
        "Argumentos inválidos — bug lógico do caller. R7 fail fast.",
    ),
    _NL_WAITING_SERVER: (
        "NL_WAITING_SERVER",
        ErrorCategory.TRANSIENT,
        "Aguardando dados do servidor — semântica explícita transient.",
    ),
    # Auth / licença
    _NL_NO_LOGIN: (
        "NL_NO_LOGIN",
        ErrorCategory.PERMANENT,
        "Login expirado/ausente — requer re-login pelo caller.",
    ),
    _NL_NO_LICENSE: (
        "NL_NO_LICENSE",
        ErrorCategory.PERMANENT,
        "Licença ausente/inválida — assinatura Nelogica.",
    ),
    _NL_LICENSE_NOT_ALLOWED: (
        "NL_LICENSE_NOT_ALLOWED",
        ErrorCategory.PERMANENT,
        "Recurso não liberado na licença.",
    ),
    _NL_PASSWORD_HASH_SHA1: (
        "NL_PASSWORD_HASH_SHA1",
        ErrorCategory.PERMANENT,
        "Senha não em SHA1 — bug de configuração.",
    ),
    _NL_PASSWORD_HASH_MD5: (
        "NL_PASSWORD_HASH_MD5",
        ErrorCategory.PERMANENT,
        "Senha não em MD5 — bug de configuração.",
    ),
    _NL_NO_PASSWORD: (
        "NL_NO_PASSWORD",
        ErrorCategory.PERMANENT,
        "Nenhuma senha — bug de configuração.",
    ),
    _NL_NO_USER: (
        "NL_NO_USER",
        ErrorCategory.PERMANENT,
        "Nenhum usuário — bug de configuração.",
    ),
    # Subscriptions / tickers
    _NL_INVALID_TICKER: (
        "NL_INVALID_TICKER",
        ErrorCategory.PERMANENT,
        "Ticker inválido — caller pediu símbolo errado (ou alias Q01-V).",
    ),
    _NL_EXCHANGE_UNKNOWN: (
        "NL_EXCHANGE_UNKNOWN",
        ErrorCategory.PERMANENT,
        "Bolsa desconhecida — Q05-V (use 'B' ou 'F').",
    ),
    # History
    _NL_SERIE_NO_HISTORY: (
        "NL_SERIE_NO_HISTORY",
        ErrorCategory.PERMANENT,
        "Série não tem histórico no servidor.",
    ),
    _NL_SERIE_NO_DATA: (
        "NL_SERIE_NO_DATA",
        ErrorCategory.PERMANENT,
        "Série sem dados (count=0) — não-erro funcional.",
    ),
    _NL_SERIE_NO_MORE_HISTORY: (
        "NL_SERIE_NO_MORE_HISTORY",
        ErrorCategory.PERMANENT,
        "Sem mais dados disponíveis — cap natural do histórico.",
    ),
    _NL_SERIE_MAX_COUNT: (
        "NL_SERIE_MAX_COUNT",
        ErrorCategory.PERMANENT,
        "Série no limite — chunker deve quebrar mais fino.",
    ),
    _NL_ASSET_NO_DATA: (
        "NL_ASSET_NO_DATA",
        ErrorCategory.AMBIGUOUS,
        "Asset sem dados — pode ser warming (transient) OU vazio (permanent).",
    ),
    # State / lifecycle
    _NL_MARKET_ONLY: (
        "NL_MARKET_ONLY",
        ErrorCategory.PERMANENT,
        "Sem roteamento — N/A para data-downloader (market-only).",
    ),
    _NL_NO_POSITION: (
        "NL_NO_POSITION",
        ErrorCategory.PERMANENT,
        "Sem posição — N/A para data-downloader.",
    ),
    _NL_NOT_HARD_LOGOUT: (
        "NL_NOT_HARD_LOGOUT",
        ErrorCategory.PERMANENT,
        "Não em HardLogout — N/A para data-downloader.",
    ),
    _NL_HAS_STRATEGY_RUNNING: (
        "NL_HAS_STRATEGY_RUNNING",
        ErrorCategory.PERMANENT,
        "Estratégia rodando — N/A para data-downloader.",
    ),
    # Resource / generic
    _NL_NOT_FOUND: (
        "NL_NOT_FOUND",
        ErrorCategory.AMBIGUOUS,
        "Recurso não encontrado — pode ser warming OU pediu errado.",
    ),
    _NL_OUT_OF_RANGE: (
        "NL_OUT_OF_RANGE",
        ErrorCategory.PERMANENT,
        "Count > tamanho do array — bug lógico.",
    ),
    _NL_VERSION_NOT_SUPPORTED: (
        "NL_VERSION_NOT_SUPPORTED",
        ErrorCategory.PERMANENT,
        "Versão do recurso não suportada — bug de struct version.",
    ),
    _NL_OCO_NO_RULES: (
        "NL_OCO_NO_RULES",
        ErrorCategory.PERMANENT,
        "OCO sem regras — N/A para data-downloader.",
    ),
    _NL_NO_OCO_DEFINED: (
        "NL_NO_OCO_DEFINED",
        ErrorCategory.PERMANENT,
        "Nenhuma OCO — N/A para data-downloader.",
    ),
    _NL_INVALID_SERIE: (
        "NL_INVALID_SERIE",
        ErrorCategory.PERMANENT,
        "(Level + Offset + Factor) inválido — bug lógico.",
    ),
    _NL_DUPLICATE_RESOURCE: (
        "NL_DUPLICATE_RESOURCE",
        ErrorCategory.PERMANENT,
        "Recurso duplicado — bug lógico (subscribe duplicado).",
    ),
    _NL_UNSIGNED_CONTRACT: (
        "NL_UNSIGNED_CONTRACT",
        ErrorCategory.PERMANENT,
        "Contrato não assinado — burocracia Nelogica.",
    ),
    _NL_FILE_ALREADY_EXISTS: (
        "NL_FILE_ALREADY_EXISTS",
        ErrorCategory.PERMANENT,
        "Arquivo já existe — bug lógico do caller.",
    ),
    _NL_NOT_MASTER_ACCOUNT: (
        "NL_NOT_MASTER_ACCOUNT",
        ErrorCategory.PERMANENT,
        "Conta não é master — N/A para data-downloader.",
    ),
    # Sentinela interna
    _DLL_SENTINEL: (
        "DLL_SENTINEL",
        ErrorCategory.PERMANENT,
        "Sentinela interna do wrapper (COMPANIONS_MISSING / "
        "UNSUPPORTED_PLATFORM) — bug de ambiente.",
    ),
    # Códigos LEGACY (Story 1.2 dll/errors.py) — same category as canônico.
    _NL_INVALID_ARGS_LEGACY: (
        "NL_INVALID_ARGS",
        ErrorCategory.PERMANENT,
        "Argumentos inválidos (legacy code dll/errors.py).",
    ),
    _NL_NO_LICENSE_LEGACY: (
        "NL_NO_LICENSE",
        ErrorCategory.PERMANENT,
        "Licença (legacy code dll/errors.py).",
    ),
    _NL_NO_LOGIN_LEGACY: (
        "NL_NO_LOGIN",
        ErrorCategory.PERMANENT,
        "Login (legacy code dll/errors.py).",
    ),
    _NL_INVALID_TICKER_LEGACY: (
        "NL_INVALID_TICKER",
        ErrorCategory.PERMANENT,
        "Ticker inválido (legacy code dll/errors.py).",
    ),
    _NL_EXCHANGE_UNKNOWN_LEGACY: (
        "NL_EXCHANGE_UNKNOWN",
        ErrorCategory.PERMANENT,
        "Bolsa desconhecida (legacy code dll/errors.py).",
    ),
}


def categorize_nl(code: int) -> NLErrorCategory:
    """Categoriza um código ``NL_*`` para decisão de retry/fail-fast.

    NUNCA raises — códigos não-mapeados retornam categoria
    :attr:`ErrorCategory.UNKNOWN` (defesa conservadora R7).

    Args:
        code: Código ``NL_*`` retornado por uma chamada ``ProfitDLL.*``.

    Returns:
        :class:`NLErrorCategory` com (code, name, category, justification).

    Examples:
        >>> info = categorize_nl(0)
        >>> info.category is ErrorCategory.PERMANENT
        True
        >>> info.name
        'NL_OK'

        >>> info = categorize_nl(-2147483647)
        >>> info.category is ErrorCategory.TRANSIENT
        True

        >>> info = categorize_nl(99999)
        >>> info.category is ErrorCategory.UNKNOWN
        True
    """
    if code in NL_CATEGORY_MAP:
        name, category, justification = NL_CATEGORY_MAP[code]
        return NLErrorCategory(code=code, name=name, category=category, justification=justification)
    return NLErrorCategory(
        code=code,
        name=f"NL_UNKNOWN_{code}",
        category=ErrorCategory.UNKNOWN,
        justification=(
            f"Código NL_* desconhecido ({code}). Possível mudança em release "
            "nova da ProfitDLL. R7 conservadora: NO retry até audit Nelo."
        ),
    )


def is_retryable(code: int) -> bool:
    """Conveniência: ``True`` se categoria == TRANSIENT (retry agressivo).

    AMBIGUOUS NÃO entra aqui — caller deve usar :func:`categorize_nl` e
    decidir baseado em política específica (cap diferente para AMBIGUOUS).

    Args:
        code: Código ``NL_*``.

    Returns:
        ``True`` apenas se TRANSIENT. ``False`` para PERMANENT, AMBIGUOUS,
        UNKNOWN — decisão conservadora R7.
    """
    return categorize_nl(code).category is ErrorCategory.TRANSIENT
