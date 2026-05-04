"""data_downloader.ui.adapters.download_adapter — Bridge para ``download()``.

Owner: Felix (frontend-dev).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

QObject vivendo em QThread separada. Encapsula chamadas a
``data_downloader.public_api.download()`` + iteração sobre
``DownloadHandle.stream()`` + cancelamento via ``DownloadHandle.cancel()``.

Padrão (QT_PATTERNS §2.3):

    class DownloadAdapter(QObject):
        progress = Signal(object)   # carrega DownloadProgress (M16: current_contract)
        error    = Signal(str)      # mensagem humanizada (Uma microcopy)
        finished = Signal(object)   # carrega DownloadResult

        def __init__(self, parent=None):
            super().__init__(parent)
            self._thread = QThread()
            self.moveToThread(self._thread)
            self._thread.start()
            self._handle: DownloadHandle | None = None

        @Slot(str, str, str)
        def start(self, symbol: str, start: str, end: str) -> None:
            from data_downloader.public_api import download
            try:
                self._handle = download(symbol, start, end)
                for progress in self._handle.stream():
                    self.progress.emit(progress)
                self.finished.emit(self._handle.result())
            except Exception as e:
                self.error.emit(str(e))

        @Slot()
        def cancel(self) -> None:
            if self._handle is not None:
                self._handle.cancel()  # ADR-007a — drain + commit parcial

        def stop(self) -> None:
            self._thread.quit()
            self._thread.wait()

Sinais carregam objetos tipados (``Signal(object)``) carregando dataclasses
do public_api — NUNCA ``Signal(dict)`` (QT_PATTERNS §2.1, finding Felix §2).

Conexões cross-thread (DownloadScreen → adapter): SEMPRE
``Qt.QueuedConnection`` explícito.

Métrica ``ui_progress_dropped_count`` (M11 — finding Pyro): adapter
instrumenta dropped progress events; expõe via getter para Pyro coletar
e UI mostrar no log expansível se > 0.

Referências:
    - docs/ux/QT_PATTERNS.md §2.3, §2.4 (current_contract M16), §8 (cancel ADR-007a)
    - docs/adr/ADR-007a (DownloadHandle.cancel())
    - docs/decisions/COUNCIL-12-epic3-prep.md
    - src/data_downloader/public_api/__init__.py
      (download, DownloadHandle, DownloadProgress, DownloadResult)
"""

from __future__ import annotations

__all__ = ["DownloadAdapter"]


class DownloadAdapter:
    """Placeholder — Epic 3 Story 3.2 implementa ``QObject`` real em QThread.

    Bridge entre MainThread Qt e ``public_api.download()``. UI nunca
    importa orchestrator diretamente — passa por este adapter.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.2 implementa DownloadAdapter. "
            "Veja docs/ux/QT_PATTERNS.md §2.3 + COUNCIL-12."
        )
