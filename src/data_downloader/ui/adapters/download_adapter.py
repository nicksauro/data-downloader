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

Story 2.9 — context propagation: contextvars do MainThread NÃO propagam
automaticamente para o worker do adapter (Qt slot já roda dentro da
QThread). Fix B-4 (Wave A 2026-05-11): o uso prévio de
:func:`copy_context_to_thread` (no-arg) era um no-op silencioso — call site
removido. Para correlacionar logs do worker com o job, todos os parâmetros
operacionais (symbol, datas, data_dir) já vêm via signal args, e
``DownloadHandle`` propaga seu próprio ``job_id`` internamente. Propagação
real MainThread → worker via contextvars está deferida (out of Wave A
scope — requer alteração nas signal signatures).

Métrica ``ui_progress_dropped_count`` (M11): adapter expõe getter
``dropped_count()``; ainda não emite drop (Story 3.8 conecta a Pyro). Por
ora acumula 0 — placeholder para a story futura.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

if TYPE_CHECKING:
    from data_downloader.public_api import DownloadHandle


__all__ = ["DownloadAdapter"]

# Story v1.0.8 fix (Pichau live test 2026-05-06): instrumentação para
# diagnosticar bugs futuros tipo "DLL conectada mas nada acontece" — este
# logger usa stdlib logging direto (não structlog) para garantir que mesmo
# quando structlog está em modo CLI (sem bridge_to_stdlib) os eventos do
# worker chegam ao QtLogHandler instalado em UI mode (que escuta o root
# logger stdlib). Não substitui structlog em produção — apenas dois
# breadcrumbs no entry point do worker QThread.
_log = logging.getLogger("data_downloader.ui.adapters.download_adapter")


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
        self._thread.setObjectName("download-adapter")
        self.moveToThread(self._thread)
        self._thread.start()
        self._handle: DownloadHandle | None = None
        self._dropped = 0

    # ------------------------------------------------------------------
    # Public API (chamada do MainThread; @Slot garante marshalling Queued)
    # ------------------------------------------------------------------

    @Slot(str, str, object, object, object)
    @Slot(str, str, object, object, object, object)
    def start(
        self,
        symbol: str,
        exchange: str,
        start: date | datetime,
        end: date | datetime,
        data_dir: Path | None,
        resume_job_id: str | None = None,
    ) -> None:
        """Dispara download (executa na thread do adapter).

        Argumentos seguem :func:`data_downloader.public_api.download`.
        Captura erros sincronamente (validação) e levantamentos no worker
        — emite via signal ``error``.

        v1.2.0 Wave 1D: ``resume_job_id`` opcional — quando passado, o
        ``public_api.download`` retoma o job existente em vez de criar um
        novo (Wave 1B — Dex-B). Default ``None`` = comportamento clássico.
        """
        # Story v1.0.8 fix (Pichau live test 2026-05-06): breadcrumbs no
        # entry point do worker QThread. Sem isto, em windowed mode após
        # "Inicializando ProfitDLL..." o painel ficava silencioso por
        # minutos — usuário não tinha sinal de que o worker arrancou nem
        # de que ``public_api.download()`` foi invocado. Logs vão via
        # stdlib root logger → QtLogHandler → ProgressCard._log_view.
        _log.info(
            "ui.download_worker_started thread=%s symbol=%s",
            threading.current_thread().name,
            symbol,
        )

        # Fix B-4 (Wave A 2026-05-11): a tentativa anterior de propagação
        # via ``copy_context_to_thread()`` aqui era um no-op silencioso —
        # ``@Slot`` em ``Qt.QueuedConnection`` já roda DENTRO da QThread,
        # então ``contextvars.copy_context()`` capturaria o contexto vazio
        # do worker. Todos os args operacionais (symbol, datas, data_dir)
        # vêm via signal payload; ``DownloadHandle`` propaga ``job_id``
        # internamente. MainThread → worker contextvar propagation real
        # está deferida (refactor maior — out of Wave A).

        try:
            from data_downloader.public_api import download

            _log.info(
                "ui.invoking_api_download symbol=%s exchange=%s start=%s end=%s",
                symbol,
                exchange,
                start,
                end,
            )
            self._handle = download(
                symbol,
                start,
                end,
                exchange=exchange,
                data_dir=data_dir,
                resume_job_id=resume_job_id,
            )
            _log.info(
                "ui.api_download_returned_handle symbol=%s resume_job_id=%s",
                symbol,
                resume_job_id,
            )
        except Exception as exc:
            _log.exception("ui.api_download_raised symbol=%s", symbol)
            self.error.emit(exc)
            return

        # Loop bloqueante de eventos — roda nesta QThread, não bloqueia
        # MainThread. Cada item é DownloadProgress.
        try:
            for event in self._handle.events():
                self.progress.emit(event)
        except Exception as exc:
            _log.exception("ui.events_loop_raised symbol=%s", symbol)
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

        # Hotfix v1.1.0 2026-05-08 (Felix+Aria — Pichau smoke real):
        # Disambiguar success vs failure pelo ``DownloadResult.status``.
        # ``public_api.download`` NÃO leak exception em caminhos como
        # ``DLLInitError`` (NL_WAITING_SERVER) — captura e devolve
        # ``DownloadResult(status='failed', error_message=...)``. Adapter
        # ANTES emitia ``finished`` para QUALQUER result, levando a UI a
        # exibir success card persistente "Download concluído 0 trades"
        # mesmo após retry exhausted (3x 300s timeouts MARKET_DATA).
        # Routing canônico: ``failed`` → error signal; ``cache_hit`` /
        # ``completed`` / ``partial`` → finished (screen lida com 0
        # trades como ``no_trades`` defensivamente — ver
        # ``DownloadScreen._on_finished``).
        status = getattr(result, "status", "completed")
        if status == "failed":
            error_message = getattr(result, "error_message", None) or "Erro desconhecido"
            _log.error(
                "ui.download_failed_status symbol=%s error=%s",
                symbol,
                error_message,
            )
            # Wrap em DataDownloaderError para que ``_on_error`` no
            # screen possa fazer humanização via ``humanized_message``
            # quando o error_message contiver um microcopy ID
            # (formato canônico: "ERR_xxx: detail" ou "NL_xxx: detail").
            try:
                from data_downloader.public_api.exceptions import DataDownloaderError

                exc = DataDownloaderError(error_message)
            except Exception:
                exc = RuntimeError(error_message)  # type: ignore[assignment]
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
        """Encerra a thread limpa. Chamar no fechamento da janela.

        Se um download está em andamento, o slot ``start`` está ocupado num
        loop Python na worker thread e ``quit()`` não é processado a tempo —
        ``wait()`` estouraria o timeout e a ``QThread`` ficaria viva no
        teardown, disparando ``QThread: Destroyed while thread
        'download-adapter' is still running`` + abort exit-code no Windows
        (task #14 v1.1.0). Por isso pedimos ``cancel`` ao handle primeiro (o
        loop de progresso sai assim que o worker drena) e damos um wait
        generoso. ``terminate()`` NÃO é usado — abortar a thread no meio de
        uma chamada nativa corrompe o estado e gera ``access violation``.
        """
        with contextlib.suppress(Exception):
            handle = self._handle
            if handle is not None:
                handle.cancel(timeout=0.0)
        try:
            self._thread.quit()
            self._thread.wait(5000)
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
