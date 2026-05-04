"""data_downloader._internal.exception_adapter — Internal → public translator.

Owner: Aria (design — ADR-011 §"Padrão de tradução") + Dex (impl). Story 2.11.

Fronteira ``_internal/`` → ``public_api/``. Fornece:

- :func:`translate_to_public` — função pura: ``_InternalError → DataDownloaderError``
  via lookup table indexada por tipo. Preserva ``__cause__`` chain.
- :func:`translate_internal` — decorator que wrappa funções públicas;
  captura ``_InternalError`` (ou subclasses) e re-raise como exceção
  pública traduzida (com ``raise public from internal``).

Garantia (testada por ``tests/property/test_no_internal_leak.py``):
nenhum ``_InternalError`` propaga fora de uma função decorada com
``@translate_internal``. Subclasses não-mapeadas viram
:class:`DataDownloaderError` genérico (fallback seguro).

Uso típico:

    @translate_internal
    def download(...) -> DownloadHandle:
        ...  # internals podem raise _ChunkRetryExhausted etc.

    # Caller só vê DataDownloaderError (ou subclasses).

Notes:
    - Importa ``public_api.exceptions`` LATE (dentro da função) para
      evitar ciclos — ``_internal/`` é layer abaixo, mas o adapter
      precisa referenciar tipos públicos. Late import resolve.
    - Performance: lookup table é dict O(1); decorator overhead é
      single try/except. Hot path: NÃO use em loops per-trade — apenas
      em entry points públicos (granularidade per-call).
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, TypeVar

from data_downloader._internal.exceptions import (
    _ChunkRetryExhausted,
    _ChunkTimedOut,
    _DLLDisconnected,
    _DLLProbeFailed,
    _FormatParseError,
    _InternalError,
    _OperationCancelled,
    _QueueOverflow,
    _StateTransitionError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from data_downloader.public_api.exceptions import DataDownloaderError

__all__ = [
    "translate_internal",
    "translate_to_public",
]


F = TypeVar("F", bound="Callable[..., Any]")


def translate_to_public(
    internal_exc: _InternalError,
    *,
    context: dict[str, object] | None = None,
) -> DataDownloaderError:
    """Mapeia uma exceção interna para a hierarquia pública correspondente.

    Faz lookup ``type(internal_exc) → public_factory`` e produz um
    :class:`DataDownloaderError` (ou subclasse) com:

    - ``message``: ``str(internal_exc)``.
    - ``cause``: o próprio ``internal_exc`` (preserva detalhes forenses
      via ``.cause`` field, NÃO via ``__cause__``).
    - ``details``: merge de ``internal_exc.context`` com ``context``.

    Args:
        internal_exc: A instância interna a traduzir.
        context: Contexto adicional opcional (caller-supplied). Sobrescreve
            chaves homônimas em ``internal_exc.context``.

    Returns:
        Instância de :class:`DataDownloaderError` (ou subclasse) — NUNCA
        propaga ``_InternalError``.

    Notes:
        - Subclasses não-mapeadas viram :class:`DataDownloaderError`
          genérico (fallback seguro — código defensivo + future-proof).
        - Para preservar ``__cause__`` chain, o caller deve usar
          ``raise translated from internal`` (o decorator
          :func:`translate_internal` já faz isso).
    """
    # Late import — evita ciclo com public_api → _internal.
    from data_downloader.public_api.exceptions import (
        ConnectionLost,
        DataDownloaderError,
        DLLInitError,
        DownloadError,
        IntegrityError,
        OperationCancelled,
    )

    # Merge context: internal first, caller overrides.
    merged: dict[str, object] = dict(internal_exc.context)
    if context:
        merged.update(context)

    msg = str(internal_exc) or type(internal_exc).__name__

    # Lookup table — type(exc) → factory(message, cause, details) → public exc.
    # Factories são closures para padronizar a assinatura.
    if isinstance(internal_exc, _OperationCancelled):
        return OperationCancelled(msg, cause=internal_exc, details=merged)

    if isinstance(internal_exc, _DLLDisconnected):
        return ConnectionLost(msg, cause=internal_exc, details=merged)

    if isinstance(internal_exc, _DLLProbeFailed):
        # DLL probe = init-time failure; código sintético -1.
        return DLLInitError(
            -1,
            "NL_PROBE_FAILED",
            msg,
            cause=internal_exc,
            details=merged,
        )

    if isinstance(internal_exc, _ChunkTimedOut | _ChunkRetryExhausted | _QueueOverflow):
        return DownloadError(msg, cause=internal_exc, details=merged)

    if isinstance(internal_exc, _FormatParseError):
        return IntegrityError(msg, cause=internal_exc, details=merged)

    if isinstance(internal_exc, _StateTransitionError):
        # Bug interno — DataDownloaderError genérico (caller pode logar/reportar).
        return DataDownloaderError(msg, cause=internal_exc, details=merged)

    # Fallback defensivo — subclasse não-mapeada (e.g. _InternalError direto
    # ou subclasse adicionada futuramente sem update do mapa). NUNCA leak;
    # vira genérico. Property test garante isso.
    return DataDownloaderError(msg, cause=internal_exc, details=merged)


def translate_internal(func: F) -> F:
    """Decorator: captura ``_InternalError`` em ``func`` e traduz para pública.

    Uso: aplicar em ENTRY POINTS de ``public_api/`` (download, validate, etc.)
    que chamam internals. Garante a invariante de fronteira (ADR-011 §Regras).

    .. code-block:: python

        @translate_internal
        def download(symbol, start, end) -> DownloadHandle:
            return _start_internal(...)

    Comportamento:

    - Sucesso normal → retorna o valor de ``func``.
    - ``_InternalError`` raised → captura, traduz, re-raise como público
      preservando ``__cause__`` (``raise public from internal``).
    - Outras exceções (``DataDownloaderError`` já público,
      :class:`ValueError`, etc.) → propaga sem alteração (não é nosso job).

    Args:
        func: Função a decorar.

    Returns:
        Wrapper preservando assinatura via :func:`functools.wraps`.

    Notes:
        - Não wrappa generators/iterators (decorator simples). Para
          iterators que cruzam fronteira, aplicar tradução manual no
          loop ou usar wrapper especializado.
        - Thread-safe: try/except é local ao frame; sem estado compartilhado.
    """

    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return func(*args, **kwargs)
        except _InternalError as exc:
            translated = translate_to_public(exc)
            raise translated from exc

    return wrapper  # type: ignore[return-value]
