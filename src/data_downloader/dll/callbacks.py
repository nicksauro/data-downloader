"""data_downloader.dll.callbacks — Factories de callbacks da ProfitDLL.

Owner: Dex (impl) | Audit: Nelo. Story 1.2.

LEIS INVIOLÁVEIS (manual ProfitDLL §4 L4382 + ADR-005 INV-1 + R3 MANIFEST):

1. **Callback faz apenas trabalho de copiar/enfileirar — sem I/O, sem logs.**
   Body do callback NÃO chama logs, prints, arquivos ou ``self``. O state
   callback faz EXCLUSIVAMENTE ``queue.put_nowait(...)``.

   **R3 amended v1.2.0 (mini-council Nelo + Aria, COUNCIL-38 decisão 2):** o
   callback V2 de trade histórico (``make_history_trade_callback_v2``) AGORA
   chama ``dll.translate_trade(handle)`` DENTRO do callback e enfileira o
   ``TradeFields`` JÁ COPIADO — não o handle. Motivo: ``a_pTrade``
   (``TConnectorTradeCallback.a_pTrade``) só é válido **dentro do escopo do
   callback** — a DLL recicla/libera o buffer interno do pacote assim que o
   callback retorna. Enfileirar o handle e traduzir depois (no IngestorThread)
   gerava ~0.01% de handles stale → ``PopulateTradeV0`` lia freed memory →
   access violation interna SILENT MODE → ``TranslateTrade`` rc!=0 → trade
   perdido (Q-DRIFT-40 / Erro.log Pichau 2026-05-12). ``TranslateTrade`` é
   ~µs (a DLL só copia campos do buffer interno para o struct out), não
   bloqueia a ConnectorThread perceptivelmente. ``AgentResolver`` / format /
   ``TradeRecord`` continuam no IngestorThread (cool path). O exemplo oficial
   Nelogica (``profitdll/Exemplo Python/main.py`` L325-333,
   ``CallbackHandlerU.pas`` L473-497) chama ``TranslateTrade`` síncrono dentro
   do callback — esse é o contrato.

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
from typing import TYPE_CHECKING, Any

from data_downloader.dll.types import (
    THistoryTradeCallbackV2,
    TProgressCallback,
    TradeFields,
    TStateCallback,
)

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL

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
# Story 1.3 — History download callbacks (V2) + v1.2.0 translate-in-callback
# =====================================================================
# Decisão COUNCIL-03 (mini-council Dex+Nelo+Sol): usar V2
# (``SetHistoryTradeCallbackV2`` + ``TranslateTrade``).
#
# v1.2.0 (COUNCIL-38 decisão 2 — Nelo + Aria): a tradução é feita DENTRO do
# callback. O handle ``a_pTrade`` só é válido no escopo do callback (a DLL
# recicla o buffer interno do pacote ao retornar) — enfileirar o handle e
# traduzir depois (no IngestorThread) gerava ~0.01% de handles stale →
# ``PopulateTradeV0`` AV silenciosa → trade perdido (Q-DRIFT-40). Agora:
#
# - History callback V2 entrega ``(asset, pTrade_handle, flags)`` na
#   ConnectorThread.
# - Callback chama ``dll.translate_trade(handle)`` (TranslateTrade ~µs — só
#   copia campos do buffer interno para o struct) e enfileira o ``TradeFields``
#   JÁ COPIADO: ``trade_queue.put_nowait((fields, flags))``.
# - Se ``translate_trade`` falhar (rc!=0 ou struct sentinela zerado) retorna
#   ``None`` → callback incrementa ``stats["translate_nl_errors"]`` e descarta
#   (contamos o nl_error sem enfileirar handle stale). Se ``price <= 0``
#   (Q-DRIFT-38, sentinela/leilão/corruption ABI) → incrementa
#   ``stats["translate_invalid_price_skips"]`` e descarta.
# - ``AgentResolver`` / format de timestamp / ``TradeRecord`` continuam no
#   IngestorThread (cool path — dict-hit O(1) por broker).
# - Política put-with-timeout aplicada na thread CONSUMIDORA (IngestorThread
#   .get(timeout=...)), NÃO aqui — o callback usa ``put_nowait`` por
#   necessidade (não pode bloquear ConnectorThread).
# =====================================================================


def make_history_trade_callback_v2(
    trade_queue: Queue[tuple[TradeFields, int]],
    dll: ProfitDLL,
    stats: dict[str, int] | None = None,
) -> Any:
    """Cria o callback V2 de trades históricos (translate-in-callback v1.2.0).

    O callback chama ``dll.translate_trade(int(handle))`` DENTRO do callback
    (semântica transiente do handle — Q-DRIFT-40 / R3 amended v1.2.0) e
    enfileira o ``TradeFields`` COPIADO via ``trade_queue.put_nowait((fields,
    flags))``. NUNCA enfileira o handle (stale após retorno do callback).

    Counters em ``stats`` (dict mutável, incrementos GIL-atômicos — single
    bytecode, não bloqueia ConnectorThread):

    - ``translate_nl_errors``: ``translate_trade`` retornou ``None`` (rc!=0 da
      DLL — NL_*; inclui o struct sentinela zerado Q-DRIFT-34 que ``translate_
      trade`` filtra retornando ``None``). Trade perdido — registrado, não
      enfileirado.
    - ``translate_invalid_price_skips``: ``price <= 0`` (Q-DRIFT-38 —
      sentinela / leilão / corruption ABI esporádica). Descartado antes do
      ``validate_record`` do schema. Categoria separada de
      ``translate_failures`` (preserva semântica histórica do agregado).
    - ``queue_dropped``: ``put_nowait`` levantou ``queue.Full`` (saturação).
      Callback engole (não pode logar/lançar — bloquearia a ConnectorThread,
      lei R3). ADR-020 Nível 4 detection.

    Caller deve inicializar essas chaves com 0. ``stats=None`` = sem métrica
    (back-compat — drops/errors engolidos sem rastro).

    Args:
        trade_queue: ``Queue[tuple[TradeFields, int]]`` consumida por
            ``download_chunk`` IngestorThread. Tuple = ``(fields, flags)``.
        dll: Instância de ``ProfitDLL`` (precisa expor ``translate_trade``).
            A ``TranslateTrade`` da DLL DEVE estar registrada/configurada
            (``_configure_dll_signatures`` ou path minimal preserva
            ``TranslateTrade.argtypes/restype``) ANTES de ``GetHistoryTrades``
            disparar o callback — garantido por ``download_chunk`` que registra
            o callback antes de ``get_history_trades``.
        stats: dict mutável opcional para os 3 counters acima.

    Returns:
        Objeto ``WINFUNCTYPE``-wrapped pronto para passar a
        ``ProfitDLL.set_history_trade_callback_v2``. JÁ está em
        ``_cb_refs`` (anti-GC, Q07-V) — caller NÃO precisa appendar.

    Examples:
        >>> from queue import Queue
        >>> from data_downloader.dll.types import TradeFields
        >>> q: Queue[tuple[TradeFields, int]] = Queue(maxsize=2_000_000)
        >>> stats = {
        ...     "translate_nl_errors": 0,
        ...     "translate_invalid_price_skips": 0,
        ...     "queue_dropped": 0,
        ... }
        >>> # cb = make_history_trade_callback_v2(q, dll, stats=stats)
        >>> # Pass cb to dll.set_history_trade_callback_v2(cb).
    """
    # Bind local — micro-opt + evita lookup de atributo no hot path da
    # ConnectorThread (mesma técnica do ingestor).
    translate = dll.translate_trade

    def _history_cb(_asset: object, p_trade: int, flags: int) -> None:
        # CRITICAL — caminho R3 amended v1.2.0 (Q-DRIFT-40). ``_asset`` é
        # descartado (IngestorThread já conhece symbol via contexto do chunk).
        # ``p_trade`` é handle opaco (``c_size_t``) válido APENAS aqui — por
        # isso traduzimos AGORA, dentro do escopo do callback.
        fields = translate(int(p_trade))
        if fields is None:
            # rc!=0 da DLL (NL_*) ou struct sentinela zerado (Q-DRIFT-34) —
            # ``translate_trade`` já filtra ambos retornando None. Contamos o
            # nl_error mas NÃO enfileiramos (não há trade válido).
            if stats is not None:
                stats["translate_nl_errors"] += 1
            return
        if fields.price <= 0:
            # Q-DRIFT-38 — sentinela / leilão / corruption ABI. Schema v1.1.0
            # ``validate_record`` exige price > 0; descartar aqui evita abortar
            # o JOB inteiro por 1 trade ruim. Categoria separada (não soma em
            # translate_failures).
            if stats is not None:
                stats["translate_invalid_price_skips"] += 1
            return
        try:
            trade_queue.put_nowait((fields, int(flags)))
        except Full:
            # Q-DRIFT-37 — drop silencioso. Increment de int em dict é
            # single-bytecode GIL-atômico — não bloqueia ConnectorThread.
            if stats is not None:
                stats["queue_dropped"] += 1

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

    Signature (Q-DRIFT-05 — Story 1.7b-followup): ``TProgressCallback`` agora
    usa ``(TAssetID, c_int)`` — TAssetID por valor, alinhado ao exemplo
    oficial Nelogica (main.py L243). Anteriormente expandia em
    ``(c_wchar_p, c_wchar_p, c_int, c_int)`` o que desalinhava o stack
    frame stdcall.

    Args:
        progress_queue: ``Queue[int]`` consumida por ``download_chunk``
            ProgressMonitor thread. Cada item = inteiro 1..100.

    Returns:
        Objeto ``WINFUNCTYPE``-wrapped (signature
        ``TProgressCallback`` da DLL — ``(TAssetID, c_int)``). JÁ está em
        ``_cb_refs``.

    Examples:
        >>> from queue import Queue
        >>> q: Queue[int] = Queue(maxsize=1000)
        >>> cb = make_progress_callback(q)
        >>> # Pass cb to dll.set_progress_callback(cb).
    """

    def _progress_cb(
        _asset_id: object,
        progress: int,
    ) -> None:
        # CRITICAL — apenas put_nowait. Não adicionar NADA aqui (R3/INV-1).
        # ``_asset_id`` é TAssetID struct passado por valor — descartado
        # (IngestorThread já conhece o ticker via contexto do chunk).
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
