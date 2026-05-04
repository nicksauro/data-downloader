"""data_downloader.ui.adapters.download_adapter — Bridge para ``download()``.

Owner: Felix (frontend-dev) | Story 3.2.

QObject vivendo em ``QThread`` separada. Encapsula chamadas a
:func:`data_downloader.public_api.download` + iteração sobre
:meth:`DownloadHandle.events` + cancelamento via :meth:`DownloadHandle.cancel`.

Padrão (QT_PATTERNS §2.3):
    - Sinais carregam objetos tipados (``Signal(object)`` carregando
      :class:`DownloadProgress` / :class:`DownloadResult`); NUNCA dict.
    - Conexões cross-thread sempre ``Qt.QueuedConnection`` explícito.
    - Worker thread roda ``download()`` (que já é async — retorna handle
      imediatamente). Adapter consome ``handle.events()`` em loop bloqueante
      dentro do próprio QThread, traduzindo cada evento em sinal Qt.

Story 2.9 — context propagation: snapshot dos contextvars do MainThread é
copiado para o worker via :func:`copy_context_to_thread` (graceful fallback
se observability não inicializada).

Métrica ``ui_progress_dropped_count`` (M11): adapter expõe getter
``dropped_count()``; ainda não emite drop (Story 3.8 conecta a Pyro). Por
ora acumula 0 — placeholder para a story futura.
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

if TYPE_CHECKING:
    from data_downloader.public_api import DownloadHandle


__all__ = ["DownloadAdapter"]


class DownloadAdapter(QObject):
    """Bridge thread-safe MainThread Qt → ``public_api.download()``.

    Sinais:
        progress(object): carrega :class:`DownloadProgress`. Emitido a cada
            evento recebido de :meth:`DownloadHandle.events`.
        error(object): carrega :class:`DataDownloaderError` ou ``Exception``
            quando o worker falha (ou ``download()`` levanta antes do handle).
        cancelled(object): carrega :class:`OperationCancelled` quando o
            usuário cancela e o worker drena com sucesso.
        finished(object): carrega :class:`DownloadResult` em sucesso normal.

    Lifecycle:
        adapter = DownloadAdapter()
        adapter.progress.connect(slot, Qt.QueuedConnection)
        adapter.start("WDOJ26", date(2026,3,1), date(2026,3,31))
        # ... eventually:
        adapter.cancel()  # graceful via handle.cancel()
        adapter.shutdown()  # finaliza a thread no destrutor da janela
    """

    progress = Signal(object)
    error = Signal(object)
    cancelled = Signal(object)
    finished = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        # IMPORTANTE: NÃO passar parent ao super — QObjects com parent não
        # podem ser movidos para outra thread. Caller (DownloadScreen)
        # mantém referência via atributo para evitar GC e chama
        # ``shutdown()`` no closeEvent.
        super().__init__(None)
        # ``_owner`` usado apenas para vincular lifetime — não é parent Qt.
        self._owner = parent
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.start()
        self._handle: DownloadHandle | None = None
        self._dropped = 0

    # ------------------------------------------------------------------
    # Public API (chamada do MainThread; @Slot garante marshalling Queued)
    # ------------------------------------------------------------------

    @Slot(str, str, object, object, object)
    def start(
        self,
        symbol: str,
        exchange: str,
        start: date | datetime,
        end: date | datetime,
        data_dir: Path | None,
    ) -> None:
        """Dispara download (executa na thread do adapter).

        Argumentos seguem :func:`data_downloader.public_api.download`.
        Captura erros sincronamente (validação) e levantamentos no worker
        — emite via signal ``error``.
        """
        # Story 2.9 — propaga contextvars do MainThread (caller pode ter
        # bind correlation_id antes de start()). Best-effort.
        try:
            from data_downloader.observability import copy_context_to_thread

            copy_context_to_thread()
        except Exception:
            pass

        try:
            from data_downloader.public_api import download

            self._handle = download(
                symbol,
                start,
                end,
                exchange=exchange,
                data_dir=data_dir,
            )
        except Exception as exc:
            self.error.emit(exc)
            return

        # Loop bloqueante de eventos — roda nesta QThread, não bloqueia
        # MainThread. Cada item é DownloadProgress.
        try:
            for event in self._handle.events():
                self.progress.emit(event)
        except Exception as exc:
            self.error.emit(exc)
            return

        # Após events() esgotar, busca resultado final. result() levanta
        # OperationCancelled em cancel cooperativo — traduzimos para sinal.
        try:
            from data_downloader.public_api import OperationCancelled

            result = self._handle.result()
        except OperationCancelled as exc:
            self.cancelled.emit(exc)
            return
        except Exception as exc:
            self.error.emit(exc)
            return

        self.finished.emit(result)

    @Slot()
    def cancel(self) -> None:
        """Sinaliza cancel ao handle (idempotente).

        Non-blocking probe — não esperar drain aqui (UI mostra estado
        "Cancelando..."; ``result()`` final dispara sinal ``cancelled``
        quando worker drena).
        """
        if self._handle is not None:
            with contextlib.suppress(Exception):
                self._handle.cancel(timeout=0.0)

    def is_cancelling(self) -> bool:
        """True se cancel foi solicitado mas worker ainda drena."""
        if self._handle is None:
            return False
        try:
            return bool(self._handle.is_cancelling())
        except Exception:
            return False

    def dropped_count(self) -> int:
        """Métrica ``ui_progress_dropped_count`` (M11 — Story 3.8 conecta).

        Por enquanto retorna sempre 0. Placeholder reservado.
        """
        return self._dropped

    def shutdown(self) -> None:
        """Encerra a thread limpa. Chamar no fechamento da janela."""
        try:
            self._thread.quit()
            self._thread.wait(2000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Conexão helper para reduzir boilerplate cross-thread no caller.
    # ------------------------------------------------------------------

    def connect_to(
        self,
        on_progress: object,
        on_error: object,
        on_cancelled: object,
        on_finished: object,
    ) -> None:
        """Conecta os 4 signals usando ``Qt.QueuedConnection`` (R11)."""
        self.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)  # type: ignore[arg-type]
        self.error.connect(on_error, Qt.ConnectionType.QueuedConnection)  # type: ignore[arg-type]
        self.cancelled.connect(on_cancelled, Qt.ConnectionType.QueuedConnection)  # type: ignore[arg-type]
        self.finished.connect(on_finished, Qt.ConnectionType.QueuedConnection)  # type: ignore[arg-type]
