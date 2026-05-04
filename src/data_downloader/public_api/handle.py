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
    """Evento de progresso emitido pelo worker (M16 — telemetria UI).

    Atributos:
        total: Total de chunks planejados (``-1`` se ainda desconhecido).
        done: Chunks concluídos até este evento.
        message: Mensagem humana (microcopy ID resolvido por chamador).
        trades_received: Soma acumulada de trades recebidos.
        current_contract: Contrato sendo baixado (resolvido) — útil quando
            ``download(symbol_root)`` resolve automaticamente.
        is_99_reconnect: ``True`` quando estamos no quirk Q11-99 (download
            travado em ~99% reconectando). UI deve renderizar amarelo
            com microcopy ``WAR_99_RECONNECT``.
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

    Espelha o :class:`JobResult` interno do orchestrator + campos de UI
    (duration_seconds em segundos float, status estendido com ``cancelled``).
    Bumpa ``__api_version__`` 0.2.0 → 0.3.0 (minor aditivo) — ADR-007a §3.

    Atributos:
        job_id: UUID do job no catalog (correlation_id em logs).
        symbol: Contrato resolvido (ex. ``"WDOJ26"``).
        exchange: Bolsa (``"F"`` ou ``"B"``).
        actual_start: Início real do range coberto.
        actual_end: Fim real do range coberto.
        trades_count: Total de trades persistidos.
        partitions: Tuple imutável de paths Parquet escritos (vazia se
            cache_hit ou cancelled antes do 1º write).
        duration_seconds: Tempo total do worker (float, segundos).
        status: ``DownloadStatus``.
        error_message: Mensagem humana se ``status == "failed"``; ``None``
            caso contrário. Vem do humanize_nl_error quando aplicável.
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
    # Public API (ADR-007a)
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Sinaliza cancelamento ao worker.

        Idempotente — múltiplas chamadas só seteam o flag uma vez.
        NÃO bloqueia: worker termina graceful e produz
        ``DownloadResult(status="cancelled")``. Use ``result()`` para
        aguardar.
        """
        self._cancel_event.set()

    def is_cancelling(self) -> bool:
        """Retorna ``True`` se :meth:`cancel` já foi chamado."""
        return self._cancel_event.is_set()

    def result(self, timeout: float | None = None) -> DownloadResult:
        """Bloqueia até o worker terminar e retorna :class:`DownloadResult`.

        Args:
            timeout: Timeout em segundos. ``None`` (default) bloqueia
                para sempre.

        Returns:
            :class:`DownloadResult` com status final.

        Raises:
            TimeoutError: ``timeout`` esgotou antes do worker terminar.
            RuntimeError: Worker terminou sem produzir resultado (bug).
        """
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
            return self._result

    def events(self) -> Iterator[DownloadProgress]:
        """Iterador sobre eventos de progresso emitidos pelo worker.

        Termina (StopIteration) quando o worker conclui (ou é cancelado).
        Bloqueante por design — caller controla cadência.

        Yields:
            :class:`DownloadProgress` por evento.
        """
        while True:
            item = self._events_queue.get()
            if item is _EVENTS_DONE:
                return
            # mypy: garantimos via produtor (worker) que item é DownloadProgress.
            yield item  # type: ignore[misc]

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
