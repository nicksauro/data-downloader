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
3. Callback V2 traduz cada trade DENTRO do escopo do handle (TranslateTrade ~µs
   — handle transiente, Q-DRIFT-40) e enfileira ``TradeFields``; o
   **IngestorThread** drena a fila e faz o pós-trabalho (AgentResolver / format
   / ``TradeRecord``).
4. Drena fila de progresso em **ProgressMonitor thread** (detecta 99%
   reconnect — Q02-E — sem confundir com trava).
5. Aguarda (a) progresso=100, OU (b) ``TC_LAST_PACKET`` no último trade,
   OU (c) timeout (default 1800s).
6. Retorna ``ChunkResult`` com trades agregados + metadata (inclui
   ``completeness_pct`` = trades / (trades + nl_errors) * 100).

Não objetivos (escopo de stories futuras):

- Story 1.4 — escrita Parquet (writer separado).
- Story 1.6 — resolução de contrato vigente.
- Story 1.7 — chunking adaptativo, retry, multi-symbol.

LEIS RESPEITADAS:
- R3 (amended v1.2.0 / COUNCIL-38): callback faz ``TranslateTrade`` (µs,
  obrigatório pela semântica transiente do handle — Q-DRIFT-40) +
  ``put_nowait`` do ``TradeFields`` copiado; AgentResolver/format ficam no
  IngestorThread. Callback NÃO faz logs/I/O.
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
    TradeFields,
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

TRADE_QUEUE_MAXSIZE: Final[int] = 2_000_000
"""Maxsize da fila de trade handles.

Histórico:
- Story 1.3: 10_000 (insuficiente — Pyro 1.4.5)
- Story 1.3 final: 100_000 (~1s de buffer @ 100k trades/s)
- Story 1.7g (COUNCIL-37 Quinn / H-E): 2_000_000.

Razão do bump: smoke histórico 4-day mostrou perda silenciosa de ~71% (218k
trades) porque DLL despeja burst histórico em ~10 min antes do
``IngestorThread`` drenar. Com 100k items, ``put_nowait`` saturava em ~10s
e ``Full`` era engolido em ``callbacks.py::_history_cb`` (R3 — callback NÃO
BLOQUEIA). 2M items ≈ 32 MB RAM (par de int64) é margem de segurança
ampla — pós-ADR-023 chunks são 1 dia útil (TODOS os ativos), e WDOFUT a
7-10k trades/s sustentado por 1d gera ~250-400k trades, bem abaixo do cap.

ADR-020 (Volume Completeness): bump é Nível 1 (capacity); contador
``queue_dropped`` em ``callback_stats`` é Nível 4 (detecção). Se
``queue_dropped > 0`` em smoke pós-fix, escalar para 1.7h
(chunking automático — Nível 3 replay)."""

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

    queue_dropped: int = 0
    """# de eventos descartados por ``queue.Full`` no ``_history_cb`` da
    ``trade_queue``. Story 1.7g / COUNCIL-37 (Quinn / H-E): callback engole
    drops para respeitar R3 (não bloquear ConnectorThread); este contador é
    incrementado in-callback (GIL-atômico). ``0`` = nenhum drop = volume
    completo entregue do callback ao IngestorThread. ``> 0`` viola ADR-020
    invariant (volume completeness) — escala para 1.7h (chunking)."""

    translate_nl_errors: int = 0
    """# de trades para os quais ``TranslateTrade`` retornou rc!=0 (NL_*) ou
    struct sentinela zerado (Q-DRIFT-34, ``translate_trade`` filtra → None).
    v1.2.0 (COUNCIL-38 / Q-DRIFT-40): contado AGORA no callback V2 (translate-
    in-callback), pois traduzir dentro do escopo do callback (handle válido)
    derruba este número de ~0.01% para ~0 — sem handle stale → sem AV →
    ``TranslateTrade`` não retorna mais lixo. ``completeness_pct`` =
    ``trades_count / (trades_count + translate_nl_errors) * 100``."""

    translate_invalid_price_skips: int = 0
    """# de trades descartados por ``price <= 0`` (Q-DRIFT-38 — sentinela /
    leilão / corruption ABI). v1.2.0: checado no callback V2 (antes de
    enfileirar) + defense-in-depth no IngestorThread. Categoria separada de
    ``translate_failures`` (preserva semântica histórica do agregado)."""

    translate_failures: int = 0
    """Agregado de falhas pós-tradução residuais no IngestorThread
    (``translate_exceptions`` + ``translate_sentinel_skips`` defense-in-depth).
    Com translate-in-callback (v1.2.0) o grosso das falhas (nl_errors) é
    contado in-callback (ver ``translate_nl_errors``); este agregado cobre só
    o caminho residual de defesa do ingestor (deveria ser 0 na prática)."""

    completeness_pct: float = 100.0
    """``trades_count / (trades_count + translate_nl_errors) * 100`` —
    completude do chunk (% dos trades que a DLL anunciou e que conseguimos
    traduzir). Logado em ``download.complete`` / ``orchestrator.chunk_complete``
    + gauge Prometheus ``download_chunk_completeness_pct``. < 99.99% dispara
    retry do chunk (orchestrator, max 2 retries — COUNCIL-38 decisão 2).
    ``100.0`` quando ``trades_count + translate_nl_errors == 0`` (sem dados)."""

    progress_history_summary: str = field(default="")


# =====================================================================
# Internal — IngestorThread (drena trade_queue, chama TranslateTrade)
# =====================================================================


class _IngestorThread(threading.Thread):
    """Thread que drena ``trade_queue`` (já com ``TradeFields``) + ``AgentResolver``.

    v1.2.0 (COUNCIL-38 / Q-DRIFT-40 — translate-in-callback): a fila agora
    carrega ``(TradeFields, flags)`` JÁ TRADUZIDO pelo callback V2 (que chamou
    ``TranslateTrade`` dentro do escopo do handle — válido só ali). O ingestor
    NÃO toca handle nem chama ``TranslateTrade``: faz apenas o trabalho
    pós-tradução — resolve nomes de corretora via :class:`AgentResolver`
    (cache local — manual §3.1 L1707-1729), formata timestamp, monta
    :class:`TradeRecord`, acumula em ``self.trades``.

    Counters residuais (defense-in-depth — o grosso das falhas é contado
    in-callback): ``translate_exceptions`` (exception inesperada em
    ``_process_trade``), ``translate_sentinel_skips`` (TradeFields com
    timestamp_ns < 0 escapou do filtro do wrapper), ``translate_invalid_price_
    skips`` (price <= 0 escapou do filtro do callback). ``translate_failures``
    = ``translate_exceptions + translate_sentinel_skips`` (back-compat).
    """

    def __init__(
        self,
        dll: ProfitDLL,
        trade_queue: Queue[tuple[TradeFields, int]],
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
        self.trade_edits: int = 0
        # v1.2.0 (COUNCIL-38 / Q-DRIFT-40): com translate-in-callback, o grosso
        # das falhas (NL_* / sentinela do struct) é contado IN-CALLBACK (ver
        # ``callbacks.make_history_trade_callback_v2`` → ``callback_stats``
        # ["translate_nl_errors"]). Estes counters do ingestor cobrem apenas o
        # caminho RESIDUAL de defense-in-depth (deveriam ficar em 0):
        # - translate_sentinel_skips: TradeFields com timestamp_ns < 0 escapou
        #   do filtro do wrapper (drift entre versões).
        # - translate_exceptions: exception Python inesperada em _process_trade.
        # - translate_invalid_price_skips: price <= 0 escapou do filtro do
        #   callback (Q-DRIFT-38). Categoria separada (não soma em failures).
        # ``translate_failures`` = sentinel + exceptions (back-compat agregado).
        self.translate_sentinel_skips: int = 0
        self.translate_exceptions: int = 0
        self.translate_invalid_price_skips: int = 0
        self.translate_failures: int = 0

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
        (per-trade @ 100-4000/s). Counters atomic (``trade_edits``,
        ``last_packet_seen``, residuais de defesa) são incrementados sem
        I/O e os logs agregados emitidos AQUI após o drain (cool path).
        """
        while not self._stop_event.is_set():
            try:
                fields, flags = self._trade_queue.get(timeout=_INGESTOR_GET_TIMEOUT)
            except Empty:
                continue
            # Defense-in-depth (Q-DRIFT-34): qualquer exception em
            # ``_process_trade`` é contada como falha residual e a thread
            # continua drenando — uma única entrada anômala não pode matar o
            # IngestorThread (callback seguiria enfileirando e o chunk
            # terminaria com trades_count baixo).
            try:
                self._process_trade(fields, flags)
            except Exception:
                self.translate_exceptions += 1
                self.translate_failures += 1

        # Drenagem final — qualquer trade na queue depois do stop_event.
        # Garante que TC_LAST_PACKET no último trade não é perdido.
        while True:
            try:
                fields, flags = self._trade_queue.get_nowait()
            except Empty:
                break
            try:
                self._process_trade(fields, flags)
            except Exception:
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

    def _process_trade(self, fields: TradeFields, flags: int) -> None:
        """Processa 1 trade JÁ TRADUZIDO: AgentResolver → TradeRecord → append.

        v1.2.0 (COUNCIL-38 / Q-DRIFT-40): a fila já carrega ``TradeFields``
        (o callback V2 chamou ``TranslateTrade`` dentro do escopo do handle —
        ver ``callbacks.make_history_trade_callback_v2``). Aqui só fazemos o
        pós-trabalho: resolve agent names via :class:`AgentResolver` (cache
        local — primeira vez por broker, depois dict-hit O(1)), formata
        timestamp, monta :class:`TradeRecord`.

        Guards residuais (defense-in-depth — o callback já filtra; estes
        deveriam ser no-op): ``timestamp_ns < 0`` (sentinela escapou) e
        ``price <= 0`` (Q-DRIFT-38 escapou).

        @hot_path — per-trade @ 100-4000/s. R21: counters atomic only,
        SEM logging síncrono / json / strftime aqui. Logs agregados
        emitidos em ``_run_inner`` após drain (cool path).
        """
        timestamp_ns = fields.timestamp_ns
        # Defense-in-depth (Q-DRIFT-34): ``format_brt_timestamp`` levanta
        # ValueError em ns < 0 e mataria a thread. O callback/wrapper já
        # filtra structs sentinela; se algo escapar, descartamos como falha
        # residual.
        if timestamp_ns < 0:
            self.translate_sentinel_skips += 1
            self.translate_failures += 1
            return
        # Defense-in-depth (Q-DRIFT-38): o callback já descarta price <= 0;
        # mantemos o guard aqui caso a fila receba algo anômalo.
        if fields.price <= 0:
            self.translate_invalid_price_skips += 1
            return  # skip — não enfileira em result.trades
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

    trade_queue: Queue[tuple[TradeFields, int]] = Queue(maxsize=TRADE_QUEUE_MAXSIZE)
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
    # v1.2.0 (COUNCIL-38 / Q-DRIFT-40): o callback V2 traduz dentro do escopo
    # do handle e incrementa estes counters in-callback (GIL-atômico):
    #   - translate_nl_errors: TranslateTrade rc!=0 ou struct sentinela → trade
    #     perdido (era ~0.01% com translate-no-ingestor por handle stale; agora
    #     ~0). Entra em ``completeness_pct``.
    #   - translate_invalid_price_skips: price <= 0 descartado (Q-DRIFT-38).
    #   - queue_dropped: ``put_nowait`` Full (Q-DRIFT-37, ADR-020 Nível 4).
    # Lemos após join() das threads (sem race — stop_event sinalizado).
    callback_stats: dict[str, int] = {
        "translate_nl_errors": 0,
        "translate_invalid_price_skips": 0,
        "queue_dropped": 0,
    }
    history_cb: Any = make_history_trade_callback_v2(trade_queue, dll, stats=callback_stats)
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

    # Counters agregados: nl_errors/invalid_price vêm do callback (translate-
    # in-callback); o ingestor só tem os residuais de defense-in-depth.
    trades_count = len(trades)
    nl_errors = callback_stats["translate_nl_errors"] + ingestor.translate_sentinel_skips
    invalid_price_skips = (
        callback_stats["translate_invalid_price_skips"] + ingestor.translate_invalid_price_skips
    )
    denom = trades_count + nl_errors
    completeness_pct = (trades_count / denom * 100.0) if denom > 0 else 100.0

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
        queue_dropped=callback_stats["queue_dropped"],
        translate_nl_errors=nl_errors,
        translate_invalid_price_skips=invalid_price_skips,
        translate_failures=ingestor.translate_failures,
        completeness_pct=completeness_pct,
    )

    log.info(
        "download.complete" if status == "completed" else f"download.{status}",
        chunk_id=chunk_id,
        symbol=symbol,
        status=status,
        trades_count=trades_count,
        duration_seconds=round(duration, 3),
        # v1.2.0 (COUNCIL-38 / Q-DRIFT-40): translate-in-callback. nl_errors
        # contado no callback (handle válido → ~0); residual = ingestor.
        translate_nl_errors=nl_errors,
        # completude do chunk — < 99.99% dispara retry no orchestrator.
        completeness_pct=round(completeness_pct, 6),
        translate_failures=ingestor.translate_failures,
        translate_sentinel_skips=ingestor.translate_sentinel_skips,
        translate_exceptions=ingestor.translate_exceptions,
        # Q-DRIFT-38: trades com price<=0 descartados antes do validate_record
        # (schema v1.1.0). 1-5 hits típicos por dia — > 0 é defesa, não erro.
        translate_invalid_price_skips=invalid_price_skips,
        trade_edits=ingestor.trade_edits,
        # Q-DRIFT-37 / ADR-020 Nível 4: drops silenciosos da trade_queue no
        # callback. > 0 = volume incompleto entregue ao IngestorThread.
        queue_dropped=callback_stats["queue_dropped"],
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
