"""data_downloader.dll.callbacks — Factories de callbacks da ProfitDLL.

Owner: Dex (impl) | Audit: Nelo. Story 1.2.

LEIS INVIOLÁVEIS (manual ProfitDLL §4 L4382 + ADR-005 INV-1 + R3 MANIFEST):

1. **Callback APENAS enfileira.** Body do callback chama EXCLUSIVAMENTE
   ``queue.put_nowait(...)``. Sem logs, sem prints, sem ``self.dll.*``,
   sem I/O. Todo processamento real ocorre em outra thread (ingestor).
   Violação = exceções inesperadas / corrupção da fila interna da DLL.

2. **``_cb_refs`` previne GC.** Lista global retém TODOS os
   ``WINFUNCTYPE``-wrapped objects. Sem isso, GC do Python coleta o
   trampoline e a DLL crasha (Q07-V).

3. **NUNCA limpar ``_cb_refs``.** Mesmo em ``finalize()``. ConnectorThread
   interna da DLL pode ainda referenciar callbacks pendentes; limpar = crash
   (Story 1.2 AC4).

Story 1.2 escopo:

- ``make_state_callback(queue)`` — callback ativo (state changes).
- ``make_noop_callback(funtype)`` — factory para slots não usados (Q11-E
  / AC2 — JAMAIS passar ``None`` no init).
- ``cleanup_cb_refs()`` — APENAS para test cleanup (NUNCA chamar em prod).
"""

from __future__ import annotations

import contextlib
from queue import Full, Queue
from typing import Any

from data_downloader.dll.types import (
    THistoryTradeCallbackV2,
    TProgressCallback,
    TStateCallback,
)

__all__ = [
    "_cb_refs",
    "cleanup_cb_refs",
    "make_history_trade_callback_v2",
    "make_noop_callback",
    "make_progress_callback",
    "make_state_callback",
]


# =====================================================================
# _cb_refs — Lista global anti-GC (Q07-V / AC4)
# =====================================================================
# Lista de TODOS os ``WINFUNCTYPE``-wrapped objects criados pelo wrapper.
# A DLL guarda o ponteiro nativo; se o objeto Python for coletado pelo
# GC, o trampoline desaparece e a DLL crasha na próxima invocação.
#
# REGRAS:
# - Append IMEDIATAMENTE após criar o WINFUNCTYPE wrapper.
# - NUNCA chamar ``.clear()`` durante a vida do processo (mesmo em
#   ``finalize()``). ConnectorThread interna pode ainda referenciar.
# - ``cleanup_cb_refs()`` é EXCLUSIVAMENTE para teardown de testes que
#   verificam isolamento entre runs (NÃO usar em código de produção).
# =====================================================================
_cb_refs: list[Any] = []


def make_state_callback(state_queue: Queue[tuple[int, int]]) -> Any:
    """Cria o callback ativo de state changes da DLL.

    O callback construído faz EXCLUSIVAMENTE ``state_queue.put_nowait(...)``
    com a tupla ``(conn_type, result)``. Lei R3 / ADR-005 INV-1 / manual
    §4 L4382: NÃO chamar funções da DLL, NÃO logar, NÃO acessar arquivos,
    NÃO acessar ``self``. Drenagem da fila (incluindo logging dos
    eventos) ocorre em ``ProfitDLL.wait_market_connected`` em thread
    separada (NUNCA dentro do callback).

    Política de overflow (AC16): ``put_nowait`` raises ``queue.Full`` em
    overflow teórico. State changes são raras (ordem de unidades por
    sessão), então ``Queue(maxsize=1000)`` no wrapper é >>> qualquer
    cenário realista. Se ``Full`` acontecer, é bug — o callback engole
    silenciosamente (NÃO pode logar / lançar; bloquearia a
    ConnectorThread). Detecção do bug ocorre via observabilidade
    externa (counter ``dll_state_queue_full_total`` em ADR-013).

    Args:
        state_queue: ``Queue[tuple[int, int]]`` consumida por
            ``wrapper.wait_market_connected`` em thread Python separada.

    Returns:
        Objeto ``WINFUNCTYPE``-wrapped pronto para passar como 4º arg a
        ``DLLInitializeMarketLogin``. JÁ está em ``_cb_refs`` (anti-GC,
        Q07-V) — caller NÃO precisa appendar.

    Examples:
        >>> from queue import Queue
        >>> q = Queue(maxsize=1000)
        >>> cb = make_state_callback(q)
        >>> # cb pronto para passar à DLL; NÃO chamar manualmente em prod.
    """

    def _state_cb(conn_type: int, result: int) -> None:
        # CRITICAL — apenas put_nowait. Não adicionar NADA aqui.
        # AC15 / INV-1: teste verifica via mock que mock_calls == [].
        # contextlib.suppress(Full): bug-only path (state changes <<<
        # maxsize=1000). NÃO logar daqui (R3) — counter externo detecta.
        # Engolir é a única opção segura: lançar bloquearia
        # ConnectorThread.
        with contextlib.suppress(Full):
            state_queue.put_nowait((conn_type, result))

    # Aplica WINFUNCTYPE como call em vez de @decorator para evitar
    # ``untyped-decorator`` no mypy --strict (TStateCallback é ctypes
    # ``_FuncPtr`` factory, sem type hints).
    wrapped: Any = TStateCallback(_state_cb)
    _cb_refs.append(wrapped)
    return wrapped


def make_noop_callback(funtype: type) -> Any:
    """Cria um callback no-op compatível com a signature dada.

    Usado para preencher os 7 slots NÃO-state de ``DLLInitializeMarketLogin``
    com callbacks no-op (Q11-E / AC2 — slots ``None`` corrompem o registro
    interno da DLL e fazem ``Set*Callback`` posteriores nunca dispararem,
    sem erro reportado). Sentinel §12 documenta semanas debugando "histórico
    não chega" causado por exatamente isso.

    O callback aceita qualquer signature (via ``*args``) porque o
    ``WINFUNCTYPE`` decorator garante a tradução ctypes corretamente —
    Python só vê os args desempacotados. Ignorar via ``del args`` evita
    "unused" warning sem alocar.

    Args:
        funtype: Uma das signatures de ``data_downloader.dll.types``
            (``TTradeCallback``, ``TDailyCallback``, etc.). Deve ser um
            ``WINFUNCTYPE`` decorator type.

    Returns:
        Objeto ``WINFUNCTYPE``-wrapped pronto para passar à DLL. JÁ está
        em ``_cb_refs`` (anti-GC, Q07-V).

    Examples:
        >>> from data_downloader.dll.types import TTradeCallback
        >>> noop = make_noop_callback(TTradeCallback)
        >>> # noop pode ser passado em qualquer slot de trade do init.
    """

    def _noop(*args: object) -> None:
        # No-op explícito. NÃO logar (R3), NÃO inspecionar args.
        # ``del args`` evita warning de variável não-usada e documenta
        # a intenção (drop sem inspecionar).
        del args

    wrapped: Any = funtype(_noop)
    _cb_refs.append(wrapped)
    return wrapped


# =====================================================================
# Story 1.3 — History download callbacks (V2)
# =====================================================================
# Decisão COUNCIL-03 (mini-council Dex+Nelo+Sol): usar V2
# (``SetHistoryTradeCallbackV2`` + ``TranslateTrade``).
#
# - History callback V2 entrega ``(asset, pTrade_handle, flags)`` na
#   ConnectorThread.
# - Callback faz APENAS ``queue.put_nowait((handle, flags))`` — lei R3 /
#   manual §4 L4382 / ADR-005 INV-1.
# - ``TranslateTrade(pTrade, byref(TConnectorTrade))`` é responsabilidade do
#   IngestorThread (FORA do callback) — chamá-lo no callback violaria R3.
# - Política put-with-timeout (resposta H4 Pyro em
#   ``OPEN_QUESTIONS_RESPONSES.md`` Q1) é aplicada na thread CONSUMIDORA
#   (IngestorThread .get(timeout=...)), NÃO aqui — o callback usa
#   ``put_nowait`` por necessidade (não pode bloquear ConnectorThread).
# =====================================================================


def make_history_trade_callback_v2(trade_queue: Queue[tuple[int, int]]) -> Any:
    """Cria o callback V2 de trades históricos (Story 1.3 / COUNCIL-03).

    O callback faz EXCLUSIVAMENTE ``trade_queue.put_nowait((handle, flags))``.
    O ``handle`` é opaco (``c_size_t`` truncado para ``int`` Python) e DEVE
    ser passado a ``ProfitDLL.translate_trade`` em **IngestorThread** —
    NUNCA dentro do callback (lei R3 / manual §4 L4382 / Q06-V).

    Política de overflow: ``put_nowait`` raises ``queue.Full`` em saturação.
    Callback engole silenciosamente (não pode logar/lançar — bloquearia a
    ConnectorThread). Detecção via metric externa em IngestorThread.
    O design real para back-pressure (resposta H4 Nelo em
    ``OPEN_QUESTIONS_RESPONSES.md`` Q1) é "fila grande + drain rápido em
    IngestorThread" — Story 1.3 usa ``maxsize=100_000`` (finding Pyro 1.4.5).

    Args:
        trade_queue: ``Queue[tuple[int, int]]`` consumida por
            ``download_chunk`` IngestorThread. Tuple = ``(handle, flags)``.

    Returns:
        Objeto ``WINFUNCTYPE``-wrapped pronto para passar a
        ``ProfitDLL.set_history_trade_callback_v2``. JÁ está em
        ``_cb_refs`` (anti-GC, Q07-V) — caller NÃO precisa appendar.

    Examples:
        >>> from queue import Queue
        >>> q: Queue[tuple[int, int]] = Queue(maxsize=100_000)
        >>> cb = make_history_trade_callback_v2(q)
        >>> # Pass cb to dll.set_history_trade_callback_v2(cb).
    """

    def _history_cb(_asset: object, p_trade: int, flags: int) -> None:
        # CRITICAL — apenas put_nowait. Não adicionar NADA aqui (R3/INV-1).
        # ``_asset`` é descartado — IngestorThread já conhece symbol via
        # contexto do download_chunk (ticker/exchange validados upfront).
        # ``p_trade`` é handle opaco (``c_size_t``); int(...) força python int
        # estável para uso na fila.
        with contextlib.suppress(Full):
            trade_queue.put_nowait((int(p_trade), int(flags)))

    wrapped: Any = THistoryTradeCallbackV2(_history_cb)
    _cb_refs.append(wrapped)
    return wrapped


def make_progress_callback(progress_queue: Queue[int]) -> Any:
    """Cria o callback de progresso de download histórico (Story 1.3).

    Callback faz EXCLUSIVAMENTE ``progress_queue.put_nowait(int(progress))``.
    Progresso é inteiro 1..100 (manual §3.1 L1750). Histórico chega na
    queue para que ProgressMonitor thread:

    - Detecte conclusão (progresso=100).
    - Detecte quirk Q02-E (99% reconectando) sem confundir com travamento.
    - Registre ``progress_history`` em ``ChunkResult``.

    Args:
        progress_queue: ``Queue[int]`` consumida por ``download_chunk``
            ProgressMonitor thread. Cada item = inteiro 1..100.

    Returns:
        Objeto ``WINFUNCTYPE``-wrapped (signature
        ``TProgressCallback`` da DLL — V1 signature: ``(ticker, bolsa,
        feed, progress)``). JÁ está em ``_cb_refs``.

    Examples:
        >>> from queue import Queue
        >>> q: Queue[int] = Queue(maxsize=1000)
        >>> cb = make_progress_callback(q)
        >>> # Pass cb to dll.set_progress_callback(cb).
    """

    def _progress_cb(
        _ticker: object,
        _bolsa: object,
        _feed: int,
        progress: int,
    ) -> None:
        # CRITICAL — apenas put_nowait. Não adicionar NADA aqui (R3/INV-1).
        with contextlib.suppress(Full):
            progress_queue.put_nowait(int(progress))

    wrapped: Any = TProgressCallback(_progress_cb)
    _cb_refs.append(wrapped)
    return wrapped


def cleanup_cb_refs() -> None:
    """Limpa ``_cb_refs`` — APENAS para teardown de testes.

    NUNCA chamar em código de produção (incluindo ``ProfitDLL.finalize``):
    ConnectorThread interna da DLL pode ainda referenciar callbacks
    pendentes, e remover a referência Python causa GC → crash (Q07-V +
    Story 1.2 AC4).

    Uso legítimo: testes unit que verificam isolamento entre setups (ex.
    confirmar que após teardown a próxima criação parte de lista vazia).
    """
    _cb_refs.clear()
