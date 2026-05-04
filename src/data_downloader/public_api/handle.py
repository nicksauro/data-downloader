"""data_downloader.public_api.handle — DownloadHandle (ADR-007a).

Owner: Aria (design — ADR-007a, finding H9/H10) + Dex (impl).
Story 1.7b — AC7.

Handle assíncrono retornado por :func:`data_downloader.public_api.download`.
Contrato (ADR-007a):

- ``cancel()`` — sinaliza cancelamento via ``threading.Event``; thread
  worker drena fila + commita parcial e marca o job como ``cancelled``
  no catalog. Idempotente.
- ``result(timeout)`` — bloqueia até o worker terminar (success | partial
  | failed | cancelled) e retorna :class:`DownloadResult`. Levanta
  ``TimeoutError`` se ``timeout`` esgotar.
- ``events()`` — iterador sobre :class:`DownloadProgress` emitidos pelo
  worker (callback do orchestrator). Bloqueante por design (consumidor
  controla cadência); termina via sentinela quando worker completa.

Garantias (ADR-007a + Aria mini-council):

1. Estável (SemVer-tracked) — assinaturas não mudam em minor versions.
2. Thread-safe — ``cancel()`` e ``result()`` podem ser chamados de
   threads distintas da que recebe ``events()``.
3. Sem leak de exception — exceções do worker são capturadas e expostas
   via ``DownloadResult.status == 'failed'`` + ``error_message``.
4. Cancelamento graceful — ``cancel()`` NÃO mata thread; apenas seta
   sinal. Worker checa entre chunks e drena antes de terminar.

Microcopy IDs relacionados (R17):
    - ``SUC_DOWNLOAD_DONE`` (status=completed)
    - ``SUC_CACHE_HIT`` (status=cache_hit)
    - ``SUC_CANCEL_DONE`` (status=cancelled)
    - ``ERR_*`` (status=failed → error_code mapeado por humanize_nl_error)
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path


__all__ = [
    "DownloadHandle",
    "DownloadProgress",
    "DownloadResult",
    "DownloadStatus",
]


DownloadStatus = Literal[
    "completed",
    "partial",
    "failed",
    "cache_hit",
    "cancelled",
]
"""Status final do download (espelha JobStatus + 'cancelled')."""


# Sentinela usada para encerrar a fila de eventos quando o worker termina.
_EVENTS_DONE: Final[object] = object()


@dataclass(frozen=True)
class DownloadProgress:
    """Evento imutável de progresso emitido pelo worker (M16 — telemetria UI).

    Produzido pelo worker thread em :func:`download` e disponível via
    iteração sobre :meth:`DownloadHandle.events`. Cada evento captura um
    snapshot do estado: chunks concluídos, trades acumulados, contrato
    sendo baixado e flag de reconexão. Frozen por design — eventos nunca
    são mutados após emissão (R6 — thread-safety por imutabilidade).

    Attributes:
        total: Total de chunks planejados para o job. ``-1`` quando ainda
            desconhecido (eventos de "starting" antes do plano consolidar).
        done: Chunks concluídos até este evento. Estritamente monotônico
            crescente entre eventos do mesmo job.
        message: Mensagem humana ou microcopy ID (UPPER_SNAKE_CASE prefixado
            ``INF_*``/``WAR_*``/``ERR_*``/``SUC_*``). Caller (CLI/Qt UI)
            resolve via ``data_downloader.ui.microcopy_loader.format_msg``.
            Esta camada não materializa texto.
        trades_received: Soma acumulada de trades recebidos da DLL desde
            o início do job. Inclui trades ainda não persistidos.
        current_contract: Contrato sendo baixado neste momento (resolvido
            via catalog). Útil em rollover quando ``download_continuous``
            (V1.x futura) muda o ``symbol`` no meio. ``None`` em jobs
            single-contract antes da resolução.
        is_99_reconnect: ``True`` quando o quirk Q11-99 (download travado em
            ~99% por DLL reconectando) está ativo. UI deve renderizar
            amarelo com microcopy ``WAR_99_RECONNECT`` em vez de "stuck".

    Examples:
        Update de UI a cada evento::

            for event in handle.events():
                if event.is_99_reconnect:
                    show_warning("Reconectando à corretora...")
                else:
                    pct = (event.done / event.total) if event.total > 0 else 0.0
                    progress_bar.set(pct)

    Notes:
        - Events ordering: emitidos em ordem chronological pelo worker.
          Drenados via fila bloqueante (FIFO).
        - Telemetria é best-effort: queue full = evento descartado
          silenciosamente (R21 — observability não bloqueia hot path).
    """

    total: int
    done: int
    message: str
    trades_received: int = 0
    current_contract: str | None = None
    is_99_reconnect: bool = False


@dataclass(frozen=True)
class DownloadResult:
    """Resultado final imutável de um download.

    Produzido pelo worker quando o job termina (qualquer status). Retornado
    por :meth:`DownloadHandle.result` (exceto quando status=cancelled, que
    levanta :class:`OperationCancelled` — use :meth:`DownloadHandle.peek_result`
    para inspecionar sem raise). Espelha :class:`JobResult` interno do
    orchestrator + campos de UI.

    Frozen por design (R6 — thread-safety por imutabilidade).

    Attributes:
        job_id: UUID do job no catalog. Usado como ``correlation_id`` em
            logs estruturados (structlog) e como chave de inspeção via
            ``catalog.get_job(job_id)``. Vazio (``""``) se job não chegou
            a iniciar (e.g. cancelled antes de start).
        symbol: Contrato resolvido (ex. ``"WDOJ26"``). Diferente do
            ``symbol`` passado a :func:`download` se este foi raiz
            (``"WDO"``) e foi resolvido via catalog.
        exchange: Bolsa onde o contrato foi baixado: ``"F"`` (BMF) ou
            ``"B"`` (Bovespa).
        actual_start: Início REAL do range coberto (primeiro trade
            efetivamente baixado). ``None`` se cache_hit ou cancelled
            antes do 1º trade. Pode ser > ``start`` passado a
            :func:`download` quando há gap inicial sem trades.
        actual_end: Fim REAL do range coberto. ``None`` em mesmas condições
            que ``actual_start``.
        trades_count: Total de trades persistidos no Parquet (após dedup).
            Pode ser ``0`` se cache_hit (range já presente) ou cancelled
            antes do 1º write.
        partitions: Tuple imutável (frozen) de :class:`Path` Parquet
            escritos durante este job. Vazia se cache_hit ou cancelled
            antes do 1º commit. Caller pode usar para read-back imediato.
        duration_seconds: Tempo total do worker em segundos (float, com
            precisão de microsegundos). Inclui startup DLL + chunking +
            writes. Útil para telemetria e dashboards.
        status: :data:`DownloadStatus` final. Veja semântica de cada valor
            no type alias.
        error_message: Mensagem humana se ``status == "failed"``; ``None``
            caso contrário. Para erros DLL, formato é
            ``"NL_<NAME>: <message>"`` (Uma microcopy ID + raw NL message).

    Examples:
        Tratamento idiomático pós-download::

            result = handle.result()
            match result.status:
                case "completed":
                    logger.info("ok", trades=result.trades_count, duration=result.duration_seconds)
                case "partial":
                    logger.warning("partial", trades=result.trades_count)
                case "cache_hit":
                    logger.info("cache_hit_skipped")
                case "failed":
                    logger.error("failed", message=result.error_message)
                case "cancelled":
                    # nota: result() levanta OperationCancelled neste caso —
                    # use peek_result() se quiser inspecionar sem raise
                    pass
    """

    job_id: str
    symbol: str
    exchange: str
    actual_start: datetime | None
    actual_end: datetime | None
    trades_count: int
    partitions: tuple[Path, ...] = field(default_factory=tuple)
    duration_seconds: float = 0.0
    status: DownloadStatus = "completed"
    error_message: str | None = None


class DownloadHandle:
    """Handle assíncrono de um download em andamento (ADR-007a).

    Construtor é interno — instâncias são produzidas por
    :func:`data_downloader.public_api.download.download`. Caller usa:

        >>> handle = download(symbol="WDOJ26", start=..., end=...)
        >>> for event in handle.events():
        ...     update_ui(event)
        >>> result = handle.result()  # bloqueia até completar
        >>> if result.status == "completed":
        ...     log.info("ok")

    Cancelamento:

        >>> handle.cancel()  # graceful — drena, commita, marca cancelled
        >>> result = handle.result()  # status == 'cancelled'

    Lifecycle:
        ``CREATED → RUNNING → (DRAINING → CANCELLED) | (COMPLETED|FAILED)``

    Thread-safety: TODOS os métodos públicos são safe de chamar de
    qualquer thread. Eventos via ``events()`` devem ser drenados por
    UMA SÓ thread (queue semantics).
    """

    def __init__(
        self,
        *,
        worker_target: object,
        cancel_event: threading.Event | None = None,
        events_queue: queue.Queue[object] | None = None,
    ) -> None:
        """Construtor interno — não chamar diretamente.

        Args:
            worker_target: Callable executada na worker thread. Recebe
                ``cancel_event`` e ``events_queue`` como kwargs.
            cancel_event: Event compartilhado (caller ou autocriado).
            events_queue: Queue thread-safe para progress events.
        """
        self._cancel_event = cancel_event or threading.Event()
        self._events_queue: queue.Queue[object] = events_queue or queue.Queue(maxsize=512)
        self._result: DownloadResult | None = None
        self._result_lock = threading.Lock()
        self._completed_event = threading.Event()

        # Worker recebe sinais via kwargs.
        # ``worker_target`` precisa ter assinatura
        # ``(cancel_event, events_queue, set_result) -> None``.
        def _runner() -> None:
            try:
                worker_target(  # type: ignore[operator]
                    cancel_event=self._cancel_event,
                    events_queue=self._events_queue,
                    set_result=self._set_result,
                )
            finally:
                # Garante que events() não bloqueia para sempre se worker
                # falhar antes de emitir resultado.
                self._events_queue.put(_EVENTS_DONE)
                self._completed_event.set()

        self._thread = threading.Thread(
            target=_runner,
            name="download-worker",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API (ADR-007a + Story 2.11 H10 closure)
    # ------------------------------------------------------------------

    def cancel(self, *, timeout: float = 30.0) -> bool:
        """Sinaliza cancelamento ao worker e aguarda graceful drain.

        Story 2.11 — fechamento de H10 (ADR-007a §"Cancel atômico").

        Comportamento:

        1. Seta o ``threading.Event`` interno (idempotente — múltiplas
           chamadas reusam o mesmo flag).
        2. Aguarda ``timeout`` segundos pela completion do worker.
           Worker checa ``cancel_event.is_set()`` ENTRE chunks (graceful
           — não interrompe chunk em andamento; preserva idempotência R5).
        3. Retorna ``True`` se worker terminou dentro de ``timeout``;
           ``False`` se ainda rodando após timeout (caller pode esperar
           mais via :meth:`result` ou logar para investigação).

        Idempotente: múltiplas chamadas com ``timeout=0.0`` são equivalentes
        a ``cancelled()`` (non-blocking probe).

        Args:
            timeout: Segundos a aguardar pelo drain (default 30.0 — alinhado
                com ADR-007a §Garantias). ``0.0`` = non-blocking probe.

        Returns:
            ``True`` se worker terminou dentro do timeout; ``False`` caso
            contrário.

        Notes:
            Após retorno ``True``, :meth:`result` levanta
            :class:`OperationCancelled` (status final ``"cancelled"``).
            Trades já committados são preservados (catalog atomic).
        """
        self._cancel_event.set()
        return self._completed_event.wait(timeout=timeout)

    def is_cancelling(self) -> bool:
        """Retorna ``True`` se :meth:`cancel` já foi chamado.

        Equivalente semântico de "cancel pedido, ainda pode estar drenando".
        Para "cancel concluído", use :meth:`cancelled` ou :attr:`is_cancelled`.
        """
        return self._cancel_event.is_set()

    def cancelled(self) -> bool:
        """Retorna ``True`` se cancel foi pedido E worker já terminou em
        status cancelled.

        Non-blocking — apenas inspeciona estado interno. Útil para UI que
        precisa decidir microcopy entre "Cancelando..." e "Cancelado".

        Story 2.11 — H10 closure.
        """
        if not self._cancel_event.is_set():
            return False
        if not self._completed_event.is_set():
            # Cancel pedido mas worker ainda drenando.
            return False
        with self._result_lock:
            return self._result is not None and self._result.status == "cancelled"

    @property
    def is_cancelled(self) -> bool:
        """Alias de :meth:`cancelled` para uso em property style.

        Story 2.11 — H10 closure.
        """
        return self.cancelled()

    def result(self, timeout: float | None = None) -> DownloadResult:
        """Bloqueia até o worker terminar e retorna :class:`DownloadResult`.

        Story 2.11 — passa a levantar :class:`OperationCancelled` quando
        o status final é ``"cancelled"`` (H10 contract).

        Args:
            timeout: Timeout em segundos. ``None`` (default) bloqueia
                para sempre.

        Returns:
            :class:`DownloadResult` com status final ``completed`` |
            ``partial`` | ``failed`` | ``cache_hit``.

        Raises:
            TimeoutError: ``timeout`` esgotou antes do worker terminar.
            RuntimeError: Worker terminou sem produzir resultado (bug).
            OperationCancelled: Worker terminou com status ``"cancelled"``
                (caller pediu :meth:`cancel` antes ou durante o run).
                ``details`` contém ``trades_preserved`` (chunks committados)
                e ``job_id`` para correlação em logs.
        """
        from data_downloader.public_api.exceptions import OperationCancelled

        finished = self._completed_event.wait(timeout=timeout)
        if not finished:
            raise TimeoutError(
                f"Download did not complete within {timeout}s " "(call .cancel() if needed)"
            )
        with self._result_lock:
            if self._result is None:
                raise RuntimeError(
                    "Worker terminated without producing a DownloadResult — "
                    "internal error; inspect logs."
                )
            if self._result.status == "cancelled":
                # H10: cancel cooperativo terminou; sinaliza via exception
                # pública. Trades já committados estão preservados em catalog.
                raise OperationCancelled(
                    f"Download cancelled by user (job_id={self._result.job_id!r})",
                    details={
                        "trades_preserved": self._result.trades_count,
                        "job_id": self._result.job_id,
                        "symbol": self._result.symbol,
                        "partitions": list(self._result.partitions),
                    },
                )
            return self._result

    def events(self) -> Iterator[DownloadProgress]:
        """Iterador sobre eventos :class:`DownloadProgress` emitidos pelo worker.

        Termina (``StopIteration``) quando o worker conclui (qualquer
        status final, incluindo ``cancelled`` e ``failed``). **Bloqueante
        por design** — caller controla cadência via velocidade de drain.

        Yields:
            :class:`DownloadProgress` por evento. Ordem cronológica.

        Examples:
            UI Qt update via signal::

                for event in handle.events():
                    self.progress_changed.emit(event)
                # eventos terminaram → worker pronto:
                result = handle.result()

        Notes:
            - Deve ser drenado por UMA SÓ thread (queue semantics — a
              fila interna é :class:`queue.Queue` que perde ordem se
              consumido por múltiplos consumers).
            - Ignorar este iterator é OK: worker continua emitindo (até
              fila encher → eventos descartados silenciosamente, mas
              :meth:`result` ainda funciona).
            - Não levanta exceções: erros do worker viram
              ``DownloadResult.status='failed'``.
        """
        while True:
            item = self._events_queue.get()
            if item is _EVENTS_DONE:
                return
            # mypy: garantimos via produtor (worker) que item é DownloadProgress.
            yield item  # type: ignore[misc]

    def peek_result(self) -> DownloadResult | None:
        """Retorna o :class:`DownloadResult` se já produzido (non-blocking, no-raise).

        Story 2.11 — utilitário para inspeção pós-cancel sem disparar
        :class:`OperationCancelled` (que :meth:`result` levanta para
        ``status == "cancelled"``).

        Returns:
            :class:`DownloadResult` ou ``None`` se worker ainda não emitiu.
        """
        with self._result_lock:
            return self._result

    def join(self, timeout: float | None = None) -> None:
        """Aguarda a thread worker terminar (sem retornar resultado).

        Útil para cleanup determinístico em testes — caller que precisa
        do resultado deve usar :meth:`result`.
        """
        self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Internal — chamados pelo worker
    # ------------------------------------------------------------------

    def _set_result(self, result: DownloadResult) -> None:
        """Worker chama isto quando produz o resultado final (success | error)."""
        with self._result_lock:
            self._result = result
