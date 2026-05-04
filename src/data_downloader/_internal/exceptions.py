"""data_downloader._internal.exceptions — Internal exception hierarchy.

Owner: Aria (design — ADR-011) + Dex (impl). Story 2.11.

Hierarchy (ADR-011 §"Hierarquia interna (privada)"):

.. code-block::

    _InternalError (base privada)
    ├── _DLLProbeFailed         # DLL probe/state inválido (não é init)
    ├── _DLLDisconnected        # estado MARKET_DISCONNECTED sem reconexão
    ├── _ChunkTimedOut          # 1800s sem progress (Q02-E hard timeout)
    ├── _ChunkRetryExhausted    # max_attempts atingido
    ├── _QueueOverflow          # IngestorThread fila cheia (block-back-pressure)
    ├── _FormatParseError       # row Parquet/SQLite mal-formado
    ├── _StateTransitionError   # transição inválida na state machine
    └── _OperationCancelled     # worker cooperativo viu cancel_event

Regras (ADR-011):

1. Internals NUNCA importam de ``public_api/`` (fronteira unidirecional).
2. ``public_api/`` captura toda subclasse e traduz via
   :func:`data_downloader._internal.exception_adapter.translate_to_public`.
3. ``raise X from y`` sempre — preserva chain para debug.
4. Cada subclasse documenta seu *trigger* + *equivalente público*
   esperado (para o adapter table).

Marker ``_internal: ClassVar[Literal[True]]`` permite que o property test
(``test_no_internal_leak.py``) detecte mecanicamente leaks via
``getattr(exc.__class__, "_internal", False)`` sem precisar importar
o módulo.
"""

from __future__ import annotations

from typing import ClassVar, Literal

__all__ = [
    "_ChunkRetryExhausted",
    "_ChunkTimedOut",
    "_DLLDisconnected",
    "_DLLProbeFailed",
    "_FormatParseError",
    "_InternalError",
    "_OperationCancelled",
    "_QueueOverflow",
    "_StateTransitionError",
]


class _InternalError(Exception):
    """Base privada das exceções internas. NUNCA propagar fora de ``public_api/``.

    Atributos:
        context: Dict opcional com info estruturada (chunk_id, attempts,
            last_cause, etc.). É consumido pelo adapter para popular
            ``DataDownloaderError.details``.

    Args:
        message: Mensagem técnica (forense) — não destinada ao usuário.
        context: Info estruturada opcional. Se ``None``, vira ``{}``.
    """

    # Marker: testes podem inspecionar via ``getattr(cls, "_internal", False)``.
    _internal: ClassVar[Literal[True]] = True

    def __init__(
        self,
        message: str = "",
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.context: dict[str, object] = context or {}


class _DLLProbeFailed(_InternalError):  # noqa: N818  ADR-011 canonical name
    """DLL probe (state callback / version check) inválido — antes do init real.

    Equivalente público: :class:`DLLInitError` (com ``code=-1``).

    Triggers típicos:

    - State callback chegou com ``result < 0`` em wait sequencial.
    - ``GetServerVersion`` não retornou string válida.
    - Companion missing detectado pós-load (race em verify).
    """


class _DLLDisconnected(_InternalError):  # noqa: N818  ADR-011 canonical name
    """DLL reportou ``MARKET_DISCONNECTED`` e não reconectou em janela esperada.

    Equivalente público: :class:`ConnectionLost`. Caller pode reagir
    (retry, mostrar microcopy ``error.connection_lost.*``).
    """


class _ChunkTimedOut(_InternalError):  # noqa: N818  ADR-011 canonical name
    """Chunk não emitiu progresso por mais que o hard-timeout (Q02-E: 1800s).

    Equivalente público: :class:`DownloadError` (com mensagem
    "timeout"-orientada — preserva ``cause`` para debug).

    Atributos esperados em ``context``:

    - ``chunk_id``: identificador do chunk
    - ``timeout_seconds``: limite excedido
    """


class _ChunkRetryExhausted(_InternalError):  # noqa: N818  ADR-011 canonical name
    """``max_attempts`` retries atingido para o mesmo chunk.

    Equivalente público: :class:`DownloadError` (com mensagem
    "retry exhausted").

    Atributos esperados em ``context``:

    - ``chunk_id``
    - ``attempts``
    - ``last_cause`` (repr de exception)
    """


class _QueueOverflow(_InternalError):  # noqa: N818  ADR-011 canonical name
    """IngestorThread fila atingiu maxsize com back-pressure ineficaz.

    Equivalente público: :class:`DownloadError`. INV-13 violada — investigação
    necessária. Hot path: NUNCA logar per-callback.
    """


class _FormatParseError(_InternalError):
    """Row de Parquet ou SQLite mal-formada (schema drift detectado).

    Equivalente público: :class:`IntegrityError`. CRÍTICO — caller deve
    parar e investigar; não corrigir silenciosamente.
    """


class _StateTransitionError(_InternalError):
    """Transição inválida na state machine (e.g. ``COMMITTED → RUNNING``).

    Equivalente público: :class:`DataDownloaderError` genérico — bug
    interno; reportar.
    """


class _OperationCancelled(_InternalError):  # noqa: N818  ADR-011 canonical name
    """Worker cooperativo viu ``cancel_event`` setado e abortou graciosamente.

    Equivalente público: :class:`OperationCancelled`. NÃO é erro — é sinal
    de que o usuário pediu cancel via :meth:`DownloadHandle.cancel`.

    Atributos esperados em ``context``:

    - ``trades_preserved``: int (chunks/trades já committados)
    - ``chunks_completed``: int
    """
