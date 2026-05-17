"""data_downloader.ui.widgets.storage_indicator_worker — Worker R11 (Story 4.27 AC3).

Owner: Sol (data-engineer) | Design: Aria (architect — ADR-029).

QObject vivendo em ``QThread`` separada dedicada (`storage-indicator`).
Encapsula a computação de free/used/total GB para o
:class:`StorageIndicator`, removendo o I/O do MainThread.

Antes da Story 4.27, ``_update_for_data_dir`` rodava no MainThread:
``shutil.disk_usage`` (syscall barata, mas em path de rede pode passar
de 5ms) + ``data_dir.rglob("*.parquet")`` + ``Path.stat()`` em cada
arquivo (50k+ arquivos = 500ms-2s freeze). Esse loop é disparado a
cada 30s via ``QTimer`` + a cada ``partition_registered`` durante
download (rajada).

ADR-029 (sign-off Aria) regra: I/O de disco → Worker, não Defer.
Defer apenas adia 1 frame; o custo continua no MainThread e cresce
com data_dir.

Estratégia em duas camadas:
    1. **Catalog-first** (AC3 — otimização): tenta
       ``SELECT COALESCE(SUM(file_size_bytes), 0) FROM partitions`` em
       ``data_dir/_internal/catalog.db``. Custo O(N) sobre N=partitions
       (tipicamente <1000), ~5-10ms em vez de ~2s.
    2. **rglob fallback** (AC3 — defesa): se catalog ausente ou erro
       SQLite, usa ``_parquets_used_gb(data_dir)`` (rglob original).
       Ainda em worker thread — R11 OK.

Debounce de 250ms no `compute_usage` slot é DESCOMPLETADO aqui — o
caller (`StorageIndicator._update_for_data_dir`) coalesce via
``QTimer`` antes de emitir.

Worker thread — R11 OK.

Referências:
    - docs/adr/ADR-029-ui-defer-vs-worker.md (sign-off Aria, accepted)
    - src/data_downloader/ui/widgets/storage_indicator.py (caller)
    - src/data_downloader/storage/catalog.py (schema com file_size_bytes)
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

__all__ = ["StorageIndicatorWorker"]


class StorageIndicatorWorker(QObject):
    """Worker R11: computa free/used/total GB fora do MainThread.

    Vive em QThread dedicada (`storage-indicator`). Padrão idêntico ao
    CatalogAdapter — sem parent Qt no construtor (moveToThread requirement).

    Sinais:
        usage_computed(float, float, float):
            (free_gb, used_gb, total_gb). Emitido após cada `compute_usage`
            completa (sucesso ou fallback). Caller conecta com
            ``Qt.QueuedConnection`` para receber no MainThread.

    Slots públicos:
        compute_usage(data_dir: object):
            Dispara o cálculo. ``data_dir`` é Path ou str (cross-thread
            payload). Best-effort: erros graciosos retornam (0, 0, 0).

    Lifecycle:
        worker = StorageIndicatorWorker()
        worker.connect_to(on_usage_computed=...)
        worker.request_compute.emit(data_dir)
        # ...
        worker.shutdown()
    """

    usage_computed = Signal(float, float, float)

    def __init__(self) -> None:
        # ADR-029 INV-UI-2: moveToThread requirement — sem parent.
        super().__init__(None)
        self._thread = QThread()
        self._thread.setObjectName("storage-indicator")
        self.moveToThread(self._thread)
        self._thread.start()

    # ------------------------------------------------------------------
    # Public slot (cross-thread Queued)
    # ------------------------------------------------------------------

    @Slot(object)
    def compute_usage(self, data_dir: object) -> None:
        """Computa free/used/total GB para um data_dir. R11 OK (worker thread).

        Args:
            data_dir: ``Path`` ou ``str`` (vem via signal payload — auto
                marshalled cross-thread).
        """
        path: Path
        try:
            path = Path(str(data_dir))
        except (TypeError, ValueError):
            self.usage_computed.emit(0.0, 0.0, 0.0)
            return

        # Imports lazy — mantém o módulo barato para importar.
        # ADR-029: import dentro do slot do worker é OK (não bloqueia
        # MainThread).
        from data_downloader.ui.widgets.storage_indicator import (
            _disk_free_gb,
            _disk_total_gb,
            _parquets_used_gb,
        )

        try:
            free_gb = _disk_free_gb(path)
        except Exception:
            free_gb = 0.0
        try:
            total_gb = _disk_total_gb(path)
        except Exception:
            total_gb = 0.0

        # Catalog-first (AC3a — otimização). Worker thread — R11 OK.
        used_gb = self._used_gb_from_catalog(path)
        if used_gb is None:
            # Fallback (AC3a — rglob original). Worker thread — R11 OK.
            try:
                used_gb = _parquets_used_gb(path)
            except Exception:
                used_gb = 0.0

        self.usage_computed.emit(float(free_gb), float(used_gb), float(total_gb))

    # ------------------------------------------------------------------
    # Helpers (rodam dentro da thread do worker)
    # ------------------------------------------------------------------

    def _used_gb_from_catalog(self, data_dir: Path) -> float | None:
        """Story 4.27 AC3a — SUM(file_size_bytes) via SQLite.

        Tenta a query rápida. Retorna ``None`` se catalog ausente / erro —
        caller faz fallback para rglob.

        ADR-029: SQLite I/O → Worker, não Defer. Esta query roda na thread
        do worker.
        """
        db_path = data_dir / "_internal" / "catalog.db"
        if not db_path.exists():
            return None
        try:
            import sqlite3

            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.execute("SELECT COALESCE(SUM(file_size_bytes), 0) FROM partitions")
                row = cursor.fetchone()
                if row is None:
                    return None
                total_bytes = int(row[0] or 0)
                return total_bytes / (1024**3)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Connection helper (padrão CatalogAdapter / DownloadAdapter)
    # ------------------------------------------------------------------

    def connect_to(
        self,
        on_usage_computed: object | None = None,
    ) -> None:
        """Conecta os sinais usando ``Qt.QueuedConnection`` (R11)."""
        if on_usage_computed is not None:
            self.usage_computed.connect(on_usage_computed, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------
    # Lifecycle (AC6)
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Encerra a worker thread limpa. Chamar no closeEvent.

        AC6: ``StorageIndicator.shutdown()`` invoca este método. Best-effort
        + idempotente.
        """
        with contextlib.suppress(Exception):
            self._thread.quit()
            self._thread.wait(500)
