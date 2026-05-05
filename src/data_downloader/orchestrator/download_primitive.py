"""data_downloader.orchestrator.download_primitive — `download_chunk`.

Owner: Dex (impl) | Audit: Nelo (DLL semantics) + Sol (TradeRecord schema)
| Aria (threading/queues design).
Story 1.3 / COUNCIL-03.

Primitiva fundamental do pipeline de download:

    download_chunk(dll, symbol, exchange, dt_start, dt_end, *, timeout=1800)
        -> ChunkResult

Para 1 (símbolo, intervalo de tempo):

1. Registra HistoryTradeCallbackV2 + ProgressCallback.
2. Chama GetHistoryTrades.
3. Drena fila de trades em **IngestorThread** (chama ``TranslateTrade``
   FORA do callback — R3).
4. Drena fila de progresso em **ProgressMonitor thread** (detecta 99%
   reconnect — Q02-E — sem confundir com trava).
5. Aguarda (a) progresso=100, OU (b) ``TC_LAST_PACKET`` no último trade,
   OU (c) timeout (default 1800s).
6. Retorna ``ChunkResult`` com trades agregados + metadata.

Não objetivos (escopo de stories futuras):

- Story 1.4 — escrita Parquet (writer separado).
- Story 1.6 — resolução de contrato vigente.
- Story 1.7 — chunking adaptativo, retry, multi-symbol.

LEIS RESPEITADAS:
- R3 / manual §4 L4382: callback APENAS ``put_nowait``. ``TranslateTrade``
  em IngestorThread.
- R7 / Q04-E: timestamps BRT naive (parse_brt_timestamp NÃO converte UTC).
- R8 / Q05-V: exchange ∈ ('F', 'B'); validado em ``ProfitDLL.get_history_trades``.
- R10 / Q13-V: V2 callback (COUNCIL-03).
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Final, Literal

import structlog

from data_downloader.dll.agent_resolver import AgentResolver
from data_downloader.dll.callbacks import (
    make_history_trade_callback_v2,
    make_progress_callback,
)
from data_downloader.dll.types import (
    TC_IS_EDIT,
    TC_LAST_PACKET,
)
from data_downloader.orchestrator.timestamp import format_brt_timestamp

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "PROGRESS_QUEUE_MAXSIZE",
    "TRADE_QUEUE_MAXSIZE",
    "ChunkResult",
    "TradeRecord",
    "download_chunk",
]


log: structlog.stdlib.BoundLogger = structlog.get_logger(
    "data_downloader.orchestrator.download_primitive"
)


# =====================================================================
# Constantes (centralizadas — facilita override em testes)
# =====================================================================

DEFAULT_TIMEOUT_SECONDS: Final[int] = 1800
"""Timeout default — 1800s (30 min). Manual §3.1 + Q02-E (99% reconnect)."""

TRADE_QUEUE_MAXSIZE: Final[int] = 100_000
"""Maxsize da fila de trade handles. Finding Pyro 1.4.5: 10k não basta em
picos de download (~100k trades/s sustentado). 100k dá ~1s de buffer."""

PROGRESS_QUEUE_MAXSIZE: Final[int] = 1000
"""Maxsize da fila de progresso. Progresso é raro (1 evento por % aprox)."""

NL_OK: Final[int] = 0
"""Código de sucesso da DLL (não erro)."""

_INGESTOR_GET_TIMEOUT: Final[float] = 0.1
"""Timeout do .get() em IngestorThread — permite checagem periódica do
shutdown event sem busy-loop."""

_PROGRESS_GET_TIMEOUT: Final[float] = 0.5
"""Timeout do .get() em ProgressMonitor — progresso é menos frequente."""

_VALID_EXCHANGES: Final[frozenset[str]] = frozenset({"F", "B"})


# =====================================================================
# Dataclasses
# =====================================================================


@dataclass(frozen=True)
class TradeRecord:
    """Trade canônico v1.0.0 (17 campos — alinhado com SCHEMA.md §1.2 / Sol).

    Versão *frozen dataclass* compatível com o ``TypedDict`` de
    ``storage.schema``. Esta dataclass é usada DENTRO da orchestrator
    layer; a writer layer (Story 1.4) converte para arrays pyarrow.

    Campos NOT NULL no schema são posicionais; nullable são keyword com
    default ``None``. Defaults extras (``trade_type=0``, ``flags=0`` etc.)
    refletem casos de trade V1 onde não há dado real (preenchido pelo
    writer com valores defensivos).

    Atenção: ``timestamp_ns`` é BRT NAIVE (lei R7) — NÃO converter UTC.
    """

    # NOT NULL
    symbol: str
    exchange: str
    timestamp_ns: int
    timestamp_str: str
    price: float
    quantity: int
    trade_type: int
    flags: int
    source_callback: str
    ingestion_ts_ns: int
    dll_version: str
    sequence_within_ns: int

    # Nullable
    trade_id: int | None = None
    buy_agent_id: int | None = None
    sell_agent_id: int | None = None
    side: int | None = None
    chunk_id: str | None = None

    # Story 1.7b-followup — agent names resolvidos via AgentResolver
    # (GetAgentNameLength + GetAgentName, manual §3.1 L1707-1729). Nullable
    # quando ID == 0 ou ID desconhecido pela DLL (fallback ``Agent#{id}``
    # ainda é populado pelo resolver para non-zero IDs). Campos NÃO fazem
    # parte do schema Parquet v1.0.0 (Sol authority — adição requer bump
    # SCHEMA_VERSION); writer atual descarta se não encontrar coluna.
    buy_agent_name: str | None = None
    sell_agent_name: str | None = None


@dataclass(frozen=True)
class ChunkResult:
    """Resultado de um download de chunk (Story 1.3 AC3).

    Imutável — orchestrator (Story 1.7) compõe múltiplos ``ChunkResult``
    em um download de janela maior.

    Atributos:
        symbol: Ticker pedido (e.g. ``"WDOJ26"``).
        exchange: Bolsa pedida (``"F"`` ou ``"B"``).
        requested_start: Datetime de início pedido (BRT naive).
        requested_end: Datetime de fim pedido (BRT naive).
        actual_start: Timestamp do PRIMEIRO trade recebido (BRT naive),
            ou ``None`` se 0 trades.
        actual_end: Timestamp do ÚLTIMO trade recebido (BRT naive),
            ou ``None`` se 0 trades.
        trades: Lista de ``TradeRecord`` recebidos.
        progress_history: Sequência de % recebidos (1..100). Útil para
            debugar Q02-E (99% reconnect).
        duration_seconds: Tempo total do download (do registro de callbacks
            ao retorno).
        status: ``"completed"`` (progresso=100 ou TC_LAST_PACKET),
            ``"timeout"`` (deadline atingido sem fim), ``"failed"``
            (GetHistoryTrades retornou erro NL_*).
        chunk_id: UUID gerado por chunk (rastreabilidade — H10).
        last_packet_seen: ``True`` se algum trade veio com flag
            ``TC_LAST_PACKET`` setada (sinal autoritativo de fim).
    """

    symbol: str
    exchange: str
    requested_start: datetime
    requested_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    trades: list[TradeRecord]
    progress_history: list[int]
    duration_seconds: float
    status: Literal["completed", "timeout", "failed"]
    chunk_id: str
    last_packet_seen: bool = False
    nl_error_code: int = 0
    """Código NL_* retornado por ``GetHistoryTrades`` (0 = sucesso). Em
    status=='failed', valor < 0 indica o erro específico."""

    subscribed: bool = False
    """``True`` se ``SubscribeTicker`` retornou código de sucesso (>= 0)
    ANTES de ``GetHistoryTrades``. ``False`` se subscribe falhou ou foi
    pulado (DLL pode tolerar tickers já subscritos retornando código não-zero
    mas trades ainda chegam — caller usa este flag para forensics).
    Story 1.7b-followup: subscribe é pré-requisito (autoridade ProfitDLL)."""

    progress_history_summary: str = field(default="")


# =====================================================================
# Internal — IngestorThread (drena trade_queue, chama TranslateTrade)
# =====================================================================


class _IngestorThread(threading.Thread):
    """Thread que drena ``trade_queue`` e chama ``TranslateTrade`` + ``AgentResolver``.

    Lei R3: ``TranslateTrade`` e ``GetAgentName`` são chamados FORA do
    callback (callback faz APENAS ``put_nowait((handle, flags))`` — ver
    ``callbacks.make_history_trade_callback_v2``).

    Story 1.7b-followup (TranslateTrade complete): consome
    :class:`data_downloader.dll.types.TradeFields` retornado por
    :meth:`ProfitDLL.translate_trade` (nova API). Resolve nomes de
    corretora via :class:`AgentResolver` (cache local — manual §3.1
    L1707-1729).
    """

    def __init__(
        self,
        dll: ProfitDLL,
        trade_queue: Queue[tuple[int, int]],
        symbol: str,
        exchange: str,
        chunk_id: str,
        dll_version: str,
        stop_event: threading.Event,
        agent_resolver: AgentResolver | None = None,
    ) -> None:
        super().__init__(name=f"ingestor-{symbol}-{chunk_id[:8]}", daemon=True)
        self._dll = dll
        self._trade_queue = trade_queue
        self._symbol = symbol
        self._exchange = exchange
        self._chunk_id = chunk_id
        self._dll_version = dll_version
        self._stop_event = stop_event
        # Story 1.7b-followup: resolver injetado (testes mockam) ou criado
        # default a partir do dll passado. Cache local sobrevive durante
        # toda a vida da thread (lookup primeira vez por agent_id, depois
        # dict-hit em hot path).
        self._agent_resolver = agent_resolver if agent_resolver is not None else AgentResolver(dll)

        # Story 2.9 — captura snapshot de contextvars do thread chamador
        # (orchestrator) para propagar logs com job_id/correlation_id/symbol.
        # Aplica via ctx.run no início de run().
        self._parent_ctx = contextvars.copy_context()

        # Saídas (acessadas após join via .trades / .last_packet_seen):
        # R21.4 — counters atomic (int +=) substituem logs per-trade. Logs
        # agregados emitidos em ``_run_inner`` (cool path) após drain.
        self.trades: list[TradeRecord] = []
        self.last_packet_seen: bool = False
        self.translate_failures: int = 0
        self.trade_edits: int = 0
        # Nelo Council 32 telemetry split (Story 1.7g): contadores
        # separados por causa raiz. ``translate_failures`` acima continua
        # somando os 3 (back-compat) para diagnose use estes 3:
        # sentinel_skips: Q-DRIFT-34 (struct zerado, timestamp_ns < 0).
        # nl_errors: ``translate_trade`` retornou None (DLL rc < 0).
        # exceptions: exception Python inesperada em _process_trade.
        self.translate_sentinel_skips: int = 0
        self.translate_nl_errors: int = 0
        self.translate_exceptions: int = 0

        # Sequência por (timestamp_ns) para preencher
        # ``sequence_within_ns`` (Sol — SCHEMA.md §2.1).
        self._sequence_counter: dict[int, int] = defaultdict(int)

    def run(self) -> None:
        """Drena trades até stop_event setado.

        Story 2.9 — executa o loop dentro do snapshot de contextvars
        capturado no ``__init__`` (parent thread). Garante que logs aqui
        carreguem ``job_id``/``correlation_id``/``symbol`` do orchestrator.
        """
        self._parent_ctx.run(self._run_inner)

    def _run_inner(self) -> None:
        """Loop interno (com contextvars do parent já aplicados).

        R21 (HOT_PATH_RULES.md) — ``_process_trade`` é hot path
        (per-trade @ 100-4000/s). Counters atomic (``translate_failures``,
        ``trade_edits``, ``last_packet_seen``) são incrementados sem
        I/O e os logs agregados emitidos AQUI após o drain (cool path).
        """
        while not self._stop_event.is_set():
            try:
                handle, flags = self._trade_queue.get(timeout=_INGESTOR_GET_TIMEOUT)
            except Empty:
                continue
            # Q-DRIFT-34 (Story 1.7d, Quinn @qa 2026-05-05): defense-in-depth
            # — qualquer exception em ``_process_trade`` é contada como
            # ``translate_failures`` e a thread continua drenando. Sem isso
            # uma única invocação sentinela do callback V2 (struct zerado)
            # mata o IngestorThread, callback segue empilhando handles, e
            # o chunk termina com ``trades_count=0`` apesar do TranslateTrade
            # ter sucesso.
            try:
                self._process_trade(handle, flags)
            except Exception:
                # Nelo Council 32 telemetry split: subcounter específico
                # + manter ``translate_failures`` como soma (back-compat).
                self.translate_exceptions += 1
                self.translate_failures += 1

        # Drenagem final — qualquer trade na queue depois do stop_event.
        # Garante que TC_LAST_PACKET no último trade não é perdido.
        while True:
            try:
                handle, flags = self._trade_queue.get_nowait()
            except Empty:
                break
            try:
                self._process_trade(handle, flags)
            except Exception:
                # Nelo Council 32 telemetry split (drain final).
                self.translate_exceptions += 1
                self.translate_failures += 1

        # R21.2 — logs agregados pós-drain (cool path, 1 evento por chunk).
        if self.last_packet_seen:
            log.info(
                "download.last_packet",
                chunk_id=self._chunk_id,
                trades_count=len(self.trades),
            )
        if self.trade_edits:
            log.debug(
                "download.trade_edits_summary",
                chunk_id=self._chunk_id,
                edits_count=self.trade_edits,
            )

    def _process_trade(self, handle: int, flags: int) -> None:
        """Processa 1 trade: TranslateTrade → AgentResolver → TradeRecord → append.

        Story 1.7b-followup: usa nova API ``ProfitDLL.translate_trade(handle)``
        que retorna :class:`TradeFields` (ou ``None`` em erro NL_*).
        Resolve agent names via :class:`AgentResolver` (cache local — primeira
        vez por broker, depois dict-hit O(1)).

        @hot_path — per-trade @ 100-4000/s. R21: counters atomic only,
        SEM logging síncrono / json / strftime aqui. Logs agregados
        emitidos em ``_run_inner`` após drain (cool path).
        """
        fields = self._dll.translate_trade(handle)
        if fields is None:
            # R21.4 — counter atomic; agregado é exposto em
            # ``ChunkResult`` via ``ingestor.translate_failures`` e logado
            # 1x no ``download.complete`` (cool path).
            # Nelo Council 32 telemetry split: ``None`` significa rc<0 da
            # DLL (NL_NOT_FOUND, NL_INVALID_ARGS, etc.) — incrementa
            # ``translate_nl_errors`` em adição ao agregado.
            self.translate_nl_errors += 1
            self.translate_failures += 1
            return

        timestamp_ns = fields.timestamp_ns
        # Q-DRIFT-34 (Story 1.7d, Quinn @qa 2026-05-05): guard explícito —
        # ``translate_trade`` agora filtra structs sentinela (TradeDate
        # zerado), mas mantemos defense-in-depth: ``format_brt_timestamp``
        # levanta ValueError em ``ns < 0`` e mataria a thread. Caso o
        # wrapper deixe escapar (ex.: drift entre versões), descartamos
        # silenciosamente como falha de tradução.
        if timestamp_ns < 0:
            # Nelo Council 32 telemetry split: este caminho é a sentinela
            # Q-DRIFT-34 (struct zerado, FILETIME 1601-01-01 → ts < 0).
            self.translate_sentinel_skips += 1
            self.translate_failures += 1
            return
        timestamp_str = format_brt_timestamp(timestamp_ns)
        trade_number = fields.trade_number
        # trade_id=0 da DLL → tratar como ausente (cai em chave longa de
        # dedup, Sol SCHEMA.md §2.1).
        trade_id: int | None = trade_number if trade_number > 0 else None
        seq = self._sequence_counter[timestamp_ns]
        self._sequence_counter[timestamp_ns] = seq + 1

        # Agent IDs — 0 é convenção "desconhecido" pela DLL (Q14-E). Cai em
        # None tanto para id quanto para name (não chamamos resolver para
        # 0 — economiza 1 lookup/trade quando broker não populou os campos).
        buy_id_raw = fields.buy_agent_id
        sell_id_raw = fields.sell_agent_id
        buy_agent_id: int | None = buy_id_raw if buy_id_raw != 0 else None
        sell_agent_id: int | None = sell_id_raw if sell_id_raw != 0 else None

        # AgentResolver.resolve usa cache local — primeira chamada por broker
        # paga GetAgentNameLength + GetAgentName; subsequentes são dict-hit.
        # Lei R3 respeitada: AgentResolver chama DLL DIRETAMENTE em
        # IngestorThread (Python thread), NÃO em callback (ConnectorThread).
        buy_agent_name: str | None = (
            self._agent_resolver.resolve(buy_agent_id) if buy_agent_id is not None else None
        )
        sell_agent_name: str | None = (
            self._agent_resolver.resolve(sell_agent_id) if sell_agent_id is not None else None
        )

        record = TradeRecord(
            symbol=self._symbol,
            exchange=self._exchange,
            timestamp_ns=timestamp_ns,
            timestamp_str=timestamp_str,
            price=fields.price,
            quantity=fields.quantity,
            trade_type=fields.trade_type,
            flags=int(flags),
            source_callback="history_v2",
            ingestion_ts_ns=time.time_ns(),
            dll_version=self._dll_version,
            sequence_within_ns=seq,
            trade_id=trade_id,
            buy_agent_id=buy_agent_id,
            sell_agent_id=sell_agent_id,
            side=None,  # not in V2 trade struct (live-only)
            chunk_id=self._chunk_id,
            buy_agent_name=buy_agent_name,
            sell_agent_name=sell_agent_name,
        )
        self.trades.append(record)

        if flags & TC_LAST_PACKET:
            # R21 — apenas seta flag (atomic bool); log agregado em
            # ``_run_inner`` após drain final.
            self.last_packet_seen = True
        if flags & TC_IS_EDIT:
            # R21.4 — counter atomic substitui log per-trade. Trade V2 com
            # flag de edição (correção de trade prévio). Sol decide se
            # downstream filtra ou armazena ambos (não é responsabilidade
            # do download_chunk). Counter agregado emitido em
            # ``_run_inner`` (cool path).
            self.trade_edits += 1


# =====================================================================
# Internal — ProgressMonitor (drena progress_queue, detecta 99% Q02-E)
# =====================================================================


class _ProgressMonitor(threading.Thread):
    """Thread que drena ``progress_queue`` e mantém histórico.

    Detecta quirk Q02-E (99% reconectando) sem confundir com travamento.
    Não interrompe download — apenas registra eventos.
    """

    def __init__(
        self,
        progress_queue: Queue[int],
        chunk_id: str,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name=f"progress-{chunk_id[:8]}", daemon=True)
        self._progress_queue = progress_queue
        self._chunk_id = chunk_id
        self._stop_event = stop_event

        # Story 2.9 — captura snapshot de contextvars do parent thread
        # (orchestrator) p/ propagar logs com job_id/correlation_id/symbol.
        self._parent_ctx = contextvars.copy_context()

        # Saídas:
        self.progress_history: list[int] = []
        self.completed: bool = False  # True se progresso=100 chegou
        self.last_99_log_time: float = 0.0
        self.reconnect_99_detected: bool = False

    def run(self) -> None:
        """Drena progresso até stop_event setado.

        Story 2.9 — executa o loop dentro do snapshot de contextvars
        capturado no ``__init__`` (parent thread).
        """
        self._parent_ctx.run(self._run_inner)

    def _run_inner(self) -> None:
        """Loop interno (com contextvars do parent já aplicados)."""
        while not self._stop_event.is_set():
            try:
                p = self._progress_queue.get(timeout=_PROGRESS_GET_TIMEOUT)
            except Empty:
                continue
            self._process_progress(p)
            if self.completed:
                # Não retorna — continua drenando até stop_event para
                # registrar progresso pós-100 (não deveria acontecer mas
                # útil para debug de comportamento estranho da DLL).
                continue

        # Drenagem final.
        while True:
            try:
                p = self._progress_queue.get_nowait()
            except Empty:
                break
            self._process_progress(p)

    def _process_progress(self, p: int) -> None:
        self.progress_history.append(p)
        if p == 100 and not self.completed:
            self.completed = True
            log.info(
                "download.progress_complete",
                chunk_id=self._chunk_id,
                history_len=len(self.progress_history),
            )
        elif p == 99:
            now = time.monotonic()
            if now - self.last_99_log_time > 30:  # log dedup: a cada 30s
                self.last_99_log_time = now
                self.reconnect_99_detected = True
                log.info(
                    "download.99_reconnect_detected",
                    chunk_id=self._chunk_id,
                    history_len=len(self.progress_history),
                )


# =====================================================================
# Public API — download_chunk
# =====================================================================


def download_chunk(
    dll: ProfitDLL,
    symbol: str,
    exchange: str,
    dt_start: datetime,
    dt_end: datetime,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    dll_version: str | None = None,
) -> ChunkResult:
    """Baixa 1 chunk (1 símbolo, 1 intervalo) e retorna ``ChunkResult``.

    Sequência (Story 1.3 AC2/AC3/AC5/AC6/AC7/AC8/AC9 + 1.7b-followup):

    1. Valida exchange ∈ ('F', 'B') — R8/Q05-V.
    2. Cria filas bounded para trade handles (100k) + progresso (1k).
    3. Cria callbacks via factories (R3 — `put_nowait` only).
    4. Inicia IngestorThread + ProgressMonitor.
    5. **SubscribeTicker(symbol, exchange)** — pré-requisito ProfitDLL
       (Story 1.7b-followup); sem subscribe a DLL não entrega trades.
       Falha = WARNING (best-effort), não bloqueia download.
    6. Registra callbacks no DLL via `set_history_trade_callback_v2` +
       `set_progress_callback`.
    7. Formata datas para `"DD/MM/YYYY HH:mm:SS"` (manual §3.1 L1750).
    8. Chama ``GetHistoryTrades``.
    9. Loop principal aguarda: progresso=100 OU TC_LAST_PACKET OU timeout.
       Quirk Q02-E: 99% reconectando NÃO é erro — continua aguardando.
    10. **UnsubscribeTicker** (em ``finally`` — sempre executa).
    11. Sinaliza stop_event → joina threads → coleta resultados.
    12. Retorna ChunkResult (com ``subscribed`` flag).

    Args:
        dll: Instância já inicializada de ``ProfitDLL`` (Story 1.2).
        symbol: Contrato vigente (NÃO alias — Q01-V). Ex.: ``"WDOJ26"``.
        exchange: ``"F"`` ou ``"B"`` — R8/Q05-V.
        dt_start: Datetime de início (BRT naive).
        dt_end: Datetime de fim (BRT naive).
        timeout: Timeout em segundos (default 1800 — Q02-E quirk margin).
        dll_version: Override para metadata (default: ``dll.dll_version``).

    Returns:
        ``ChunkResult`` com trades coletados + metadata.

    Raises:
        ValueError: exchange inválido, datas em ordem inválida.
    """
    if exchange not in _VALID_EXCHANGES:
        raise ValueError(
            f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}. "
            "R8/Q05-V — manual §3.1 L1673."
        )
    if dt_end < dt_start:
        raise ValueError(f"dt_end ({dt_end}) must be >= dt_start ({dt_start}).")

    chunk_id = uuid.uuid4().hex
    resolved_dll_version = dll_version if dll_version is not None else dll.dll_version

    # Story 2.9 — bind chunk_id REAL (uuid) em contextvars (sobrescreve o
    # placeholder range-based bound pelo orchestrator). Logs do download +
    # ingestor + monitor + DLL agora carregam ``chunk_id`` automático.
    # Best-effort: se logging_config não foi inicializado, structlog ignora
    # bind silenciosamente (degradação benigna).
    from data_downloader.observability.logging_config import bind_context

    bind_context(chunk_id=chunk_id)

    trade_queue: Queue[tuple[int, int]] = Queue(maxsize=TRADE_QUEUE_MAXSIZE)
    progress_queue: Queue[int] = Queue(maxsize=PROGRESS_QUEUE_MAXSIZE)
    stop_event = threading.Event()

    log.info(
        "download.start",
        chunk_id=chunk_id,
        symbol=symbol,
        exchange=exchange,
        dt_start=dt_start.isoformat(),
        dt_end=dt_end.isoformat(),
        timeout=timeout,
        dll_version=resolved_dll_version,
    )

    # Iniciar threads ANTES de registrar callbacks — quando GetHistoryTrades
    # dispara, callback chama put_nowait imediatamente; threads precisam
    # estar drenando para evitar pausa transitória.
    ingestor = _IngestorThread(
        dll=dll,
        trade_queue=trade_queue,
        symbol=symbol,
        exchange=exchange,
        chunk_id=chunk_id,
        dll_version=resolved_dll_version,
        stop_event=stop_event,
    )
    monitor = _ProgressMonitor(
        progress_queue=progress_queue,
        chunk_id=chunk_id,
        stop_event=stop_event,
    )
    ingestor.start()
    monitor.start()

    # Factories já appendam em callbacks._cb_refs (anti-GC global). Wrapper
    # também guarda em self._cb_refs como cinto-e-suspensório.
    history_cb: Any = make_history_trade_callback_v2(trade_queue)
    progress_cb: Any = make_progress_callback(progress_queue)

    # Formato exato manual §3.1 L1750 — strftime determinístico.
    dt_start_str = dt_start.strftime("%d/%m/%Y %H:%M:%S")
    dt_end_str = dt_end.strftime("%d/%m/%Y %H:%M:%S")

    start_monotonic = time.monotonic()
    deadline = start_monotonic + timeout
    nl_code = 0
    status: Literal["completed", "timeout", "failed"]
    subscribed = False

    try:
        # Story 1.7b-followup — SubscribeTicker é PRÉ-REQUISITO de
        # GetHistoryTrades (autoridade ProfitDLL). Sem subscribe a DLL
        # aceita a chamada mas NÃO entrega trades. Falha aqui é WARNING
        # (DLL pode aceitar tickers já subscritos retornando código não-zero;
        # trades ainda podem chegar) — não bloqueia o download.
        try:
            sub_rc = dll.subscribe_ticker(symbol, exchange)
        except Exception as exc:  # defensivo; subscribe é melhor-esforço
            log.warning(
                "download.subscribe_failed",
                chunk_id=chunk_id,
                symbol=symbol,
                exchange=exchange,
                error=str(exc),
                error_type=type(exc).__name__,
            )
        else:
            subscribed = sub_rc >= 0
            if not subscribed:
                log.warning(
                    "download.subscribe_nonzero_code",
                    chunk_id=chunk_id,
                    symbol=symbol,
                    exchange=exchange,
                    code=sub_rc,
                )

        dll.set_history_trade_callback_v2(history_cb)
        dll.set_progress_callback(progress_cb)
        nl_code = dll.get_history_trades(symbol, exchange, dt_start_str, dt_end_str)
        if nl_code < 0:
            status = "failed"
            log.error(
                "download.get_history_trades_failed",
                code=nl_code,
                chunk_id=chunk_id,
            )
            # Threads serão paradas no finally.
        else:
            # Loop principal — aguarda fim:
            # - sucesso: progresso=100 OR last_packet visto.
            # - timeout: deadline atingido.
            # - 99% reconnect (Q02-E): NÃO interrompe — log via monitor.
            poll_interval = 0.2
            while True:
                if monitor.completed or ingestor.last_packet_seen:
                    status = "completed"
                    break
                if time.monotonic() >= deadline:
                    status = "timeout"
                    log.warning(
                        "download.timeout",
                        chunk_id=chunk_id,
                        timeout=timeout,
                        progress_history_len=len(monitor.progress_history),
                        trades_received=len(ingestor.trades),
                    )
                    break
                time.sleep(poll_interval)
    finally:
        # Sinalizar stop e joinar — threads drenam restos antes de sair.
        stop_event.set()
        # Pequena espera para drenagem final (trades pendentes na queue).
        # 5s é confortável: queue maxsize=100k * ~10us per translate ~= 1s.
        ingestor.join(timeout=10.0)
        monitor.join(timeout=5.0)

        # Story 1.7b-followup — UnsubscribeTicker SEMPRE (mesmo em erro)
        # para liberar slot interno da DLL. Falha aqui é WARNING (estado
        # já está sujo de qualquer forma; downstream cleanup é responsabilidade
        # do caller / orchestrator superior). Só desinscreve se subscribe
        # foi tentado — evita unsubscribe em ticker nunca registrado.
        try:
            unsub_rc = dll.unsubscribe_ticker(symbol, exchange)
            log.info(
                "download.unsubscribe",
                chunk_id=chunk_id,
                symbol=symbol,
                exchange=exchange,
                code=unsub_rc,
            )
        except Exception as exc:  # defensivo
            log.warning(
                "download.unsubscribe_failed",
                chunk_id=chunk_id,
                symbol=symbol,
                exchange=exchange,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    duration = time.monotonic() - start_monotonic
    trades = ingestor.trades

    actual_start: datetime | None = None
    actual_end: datetime | None = None
    if trades:
        # trades vêm em ordem cronológica do servidor (DLL agrega por
        # timestamp_ns). actual_start / actual_end via min/max defensivo
        # caso ordem chegue sutilmente fora.
        ns_min = min(t.timestamp_ns for t in trades)
        ns_max = max(t.timestamp_ns for t in trades)
        actual_start = _ns_to_datetime(ns_min)
        actual_end = _ns_to_datetime(ns_max)

    result = ChunkResult(
        symbol=symbol,
        exchange=exchange,
        requested_start=dt_start,
        requested_end=dt_end,
        actual_start=actual_start,
        actual_end=actual_end,
        trades=trades,
        progress_history=list(monitor.progress_history),
        duration_seconds=duration,
        status=status,
        chunk_id=chunk_id,
        last_packet_seen=ingestor.last_packet_seen,
        nl_error_code=nl_code,
        subscribed=subscribed,
    )

    log.info(
        "download.complete" if status == "completed" else f"download.{status}",
        chunk_id=chunk_id,
        symbol=symbol,
        status=status,
        trades_count=len(trades),
        duration_seconds=round(duration, 3),
        translate_failures=ingestor.translate_failures,
        # Nelo Council 32 telemetry split (Story 1.7g): subcontadores
        # específicos em adição ao agregado para diagnose root-cause.
        translate_sentinel_skips=ingestor.translate_sentinel_skips,
        translate_nl_errors=ingestor.translate_nl_errors,
        translate_exceptions=ingestor.translate_exceptions,
        trade_edits=ingestor.trade_edits,
        progress_99_reconnect=monitor.reconnect_99_detected,
        last_packet_seen=ingestor.last_packet_seen,
        subscribed=subscribed,
    )

    return result


# =====================================================================
# Helpers
# =====================================================================


def _system_time_to_ns(st: Any) -> int:
    """Converte ``SystemTime`` (struct ctypes) → timestamp_ns BRT naive.

    Lei R7 / Q04-E: NÃO converter para UTC. wall clock da DLL é BRT naive
    (sem DST desde 2019). Construir datetime naive com os campos do struct
    e depois converter para nanos via mesmo truque do timestamp parser.

    Args:
        st: ``data_downloader.dll.types.SystemTime`` (campos wYear, wMonth,
            wDay, wHour, wMinute, wSecond, wMilliseconds; ignoramos
            wDayOfWeek).

    Returns:
        Nanosegundos desde 1970-01-01 BRT naive.
    """
    # Construir datetime naive — interpretado como BRT.
    dt_naive = datetime(
        year=int(st.wYear),
        month=int(st.wMonth),
        day=int(st.wDay),
        hour=int(st.wHour),
        minute=int(st.wMinute),
        second=int(st.wSecond),
        microsecond=int(st.wMilliseconds) * 1000,
    )
    # Truque BRT-naive-para-ns: tratar wall clock como UTC apenas para
    # cálculo. Não converte fuso. Resultado representa BRT naive.

    aware = dt_naive.replace(tzinfo=UTC)
    delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
    total_seconds = delta.days * 86_400 + delta.seconds
    return total_seconds * 1_000_000_000 + delta.microseconds * 1_000


def _ns_to_datetime(ns: int) -> datetime:
    """Converte timestamp_ns BRT naive → datetime naive (BRT).

    Inverso de ``_system_time_to_ns``. Usado para preencher
    ``ChunkResult.actual_start/actual_end``.
    """
    seconds, sub_ns = divmod(ns, 1_000_000_000)
    micros = sub_ns // 1_000
    # fromtimestamp(s, tz=UTC) + drop tzinfo dá wall clock representando
    # BRT naive (interpretação fictícia, R7).
    dt_aware = datetime.fromtimestamp(seconds, tz=UTC)
    return dt_aware.replace(microsecond=micros, tzinfo=None)
