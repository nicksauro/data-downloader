"""data_downloader.dll.errors — Decode de códigos NL_* da ProfitDLL.

Owner: Dex (impl) | Audit: Nelo. Story 1.2.

Mapa simbólico ``NL_* code → name`` (base de ``profitTypes.py`` + manual §5
+ Sentinel §12). Função pública ``decode_nl_error(code)`` retorna
``NLErrorInfo`` (NamedTuple) com mensagem humanizada (refs Uma's
``MICROCOPY_CATALOG.md`` quando aplicável).

A classe pública de exceção ``DLLInitError`` mora em
``data_downloader.public_api.exceptions`` (ADR-011 — fronteira pública é
SemVer-tracked). Este módulo re-exporta para ergonomia (consumidores do
wrapper podem ``from data_downloader.dll.errors import DLLInitError``).

Códigos cobertos (mínimo Story 1.2 — expandir conforme story precisar):

- ``NL_OK = 0`` — sucesso (não é erro, mas listado para compleitude)
- ``NL_INTERNAL_ERROR``, ``NL_NOT_INITIALIZED``, ``NL_INVALID_ARGS``
- ``NL_NO_LICENSE``, ``NL_NO_LOGIN`` — autenticação
- ``NL_INVALID_TICKER``, ``NL_EXCHANGE_UNKNOWN`` (Q05-V)
- Sentinelas internas Story 1.2:
  - ``COMPANIONS_MISSING`` (code=-1, AC12)
  - ``UNSUPPORTED_PLATFORM`` (code=-1, raised em Linux/Mac)

Códigos desconhecidos retornam ``NL_UNKNOWN_<code>`` em vez de levantar —
isto evita que um código novo da DLL (em release futura) trave o wrapper.
"""

from __future__ import annotations

from typing import Final, NamedTuple

from data_downloader.public_api.exceptions import DLLInitError

__all__ = ["DLLInitError", "NLErrorInfo", "decode_nl_error"]


# =====================================================================
# NL_* code → (name, humanized_message) map
# =====================================================================
# Mensagens humanizadas referenciam IDs de Uma's MICROCOPY_CATALOG.md
# (Story 0.3) quando aplicável. Em V1 (Story 1.2), MICROCOPY_CATALOG.md
# ainda não é canônico — mensagens aqui são placeholders informativas.
# Stories 1.7+ devem reconciliar com microcopy aprovado.
#
# Códigos fonte: profitTypes.py (Nelogica) + manual ProfitDLL §5 +
# Sentinel §12 + agents/profitdll-specialist.md expertise.
# =====================================================================

_NL_CODE_MAP: Final[dict[int, tuple[str, str]]] = {
    # --- Sucesso ---
    0: ("NL_OK", "Operação concluída com sucesso."),
    # --- Internos / argumentos ---
    -2147483647: (
        "NL_INTERNAL_ERROR",
        "Erro interno da ProfitDLL. Tente reiniciar o data-downloader; "
        "se persistir, contate o suporte (microcopy: error.dll.internal).",
    ),
    -2147483646: (
        "NL_NOT_INITIALIZED",
        "ProfitDLL não foi inicializada. Chame initialize_market_only antes "
        "de qualquer operação (microcopy: error.dll.not_initialized).",
    ),
    -2147483393: (
        "NL_INVALID_ARGS",
        "Argumentos inválidos passados à ProfitDLL. Verifique chave/usuário/"
        "senha (microcopy: error.dll.invalid_args).",
    ),
    -2147483645: (
        "NL_INVALID_HANDLE",
        "Handle inválido. Estado da DLL pode estar corrompido — "
        "reinicialização necessária (microcopy: error.dll.invalid_handle).",
    ),
    # --- Licença / autenticação ---
    -2147483392: (
        "NL_NO_LICENSE",
        "Licença ProfitDLL não encontrada ou expirada. Verifique sua "
        "assinatura Nelogica (microcopy: error.dll.no_license).",
    ),
    -2147483391: (
        "NL_NO_LOGIN",
        "Falha no login: credenciais inválidas ou usuário sem permissão "
        "(microcopy: error.dll.no_login).",
    ),
    # --- Subscriptions / tickers ---
    -2147483390: (
        "NL_INVALID_TICKER",
        "Ticker inválido. Verifique o símbolo solicitado (microcopy: error.dll.invalid_ticker).",
    ),
    -2147483389: (
        "NL_EXCHANGE_UNKNOWN",
        "Bolsa desconhecida. Use 'B' para Bovespa ou 'F' para BMF (Q05-V); "
        "strings como 'BMF' ou 'BOVESPA' são rejeitadas (microcopy: "
        "error.dll.exchange_unknown).",
    ),
    # --- Sentinelas internas Story 1.2 (NÃO vêm da DLL) ---
    -1: (
        "DLL_SENTINEL",
        "Erro interno do wrapper data-downloader (não da DLL). Verifique "
        "logs estruturados para detalhe.",
    ),
}


class NLErrorInfo(NamedTuple):
    """Resultado de ``decode_nl_error``.

    Attributes:
        code: Código numérico original (negativo = erro, 0 = sucesso).
        name: Nome simbólico (ex. ``"NL_INVALID_ARGS"``).
        message: Mensagem humanizada (refs ``MICROCOPY_CATALOG.md``).
    """

    code: int
    name: str
    message: str


def decode_nl_error(code: int) -> NLErrorInfo:
    """Decode um código retornado por ``ProfitDLL.*`` em info estruturada.

    Esta função NUNCA raises — códigos desconhecidos retornam um nome
    sintético ``NL_UNKNOWN_<code>`` para evitar que código novo da DLL
    (release futura) trave o wrapper. O caller decide se levanta
    ``DLLInitError`` baseado no contexto (init vs runtime).

    Args:
        code: Valor inteiro retornado pela função da DLL (negativo = erro).

    Returns:
        ``NLErrorInfo(code, name, message)``. Mensagem é humanizada e
        sempre não-vazia.

    Examples:
        >>> info = decode_nl_error(0)
        >>> info.name
        'NL_OK'
        >>> info = decode_nl_error(-2147483393)
        >>> info.name
        'NL_INVALID_ARGS'
        >>> info = decode_nl_error(99999)
        >>> info.name
        'NL_UNKNOWN_99999'
    """
    if code in _NL_CODE_MAP:
        name, message = _NL_CODE_MAP[code]
        return NLErrorInfo(code=code, name=name, message=message)
    return NLErrorInfo(
        code=code,
        name=f"NL_UNKNOWN_{code}",
        message=(
            f"Código NL_* desconhecido ({code}). Possível mudança em release "
            "nova da ProfitDLL — atualize data_downloader/dll/errors.py."
        ),
    )
