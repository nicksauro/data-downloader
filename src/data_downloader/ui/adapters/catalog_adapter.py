"""data_downloader.ui.adapters.catalog_adapter — Bridge para catálogo SQLite.

Owner: Felix (frontend-dev) | Story 3.2 (CatalogScreen + SettingsScreen).

QObject vivendo em ``QThread`` separada. Encapsula:

    - Listagem de partições do catálogo (consumido por CatalogScreen).
    - Operações destrutivas (delete partition) — chamadas com confirm prévio
      no UI layer (PRINCIPLES.md §H5).
    - Re-validação de checksum (drift C audit).
    - Reconciliação (drift A auto-correct).

Padrão (QT_PATTERNS §2.3):

    class CatalogAdapter(QObject):
        partitions_loaded = Signal(object)        # tuple[Partition, ...]
        deleted           = Signal(str)           # rel_path apagado
        validated         = Signal(str, bool)     # path, ok
        reconciled        = Signal(object)        # ReconcileReport
        error             = Signal(object)        # DataDownloaderError | Exception

        @Slot(object)
        def list_partitions(self, data_dir): ...

        @Slot(object, str)
        def delete_partition(self, data_dir, rel_path): ...

        @Slot(object, str)
        def revalidate_checksum(self, data_dir, rel_path): ...

        @Slot(object)
        def reconcile(self, data_dir): ...

Operações de listagem podem ser caras (> 1000 partições). Sempre rodam em
QThread separada (R11) e emitem signal só quando completa — UI mostra
loading skeleton enquanto.

Story 2.9 — context propagation: snapshot dos contextvars do MainThread é
copiado para o worker via :func:`copy_context_to_thread` (graceful fallback
se observability não inicializada).

Decisões D1-D4 herdadas de COUNCIL-23 (Story 3.1):
    - D1: signals para despachar slots cross-thread (não invokeMethod).
    - D2: adapter sem parent Qt (moveToThread requirement).
    - D3: caller (CatalogScreen) chama ``shutdown()`` no closeEvent.
    - D4: microcopy literal preservado (R17).

Referências:
    - docs/ux/QT_PATTERNS.md §2.3
    - docs/decisions/COUNCIL-23-epic3-first-screen.md
    - src/data_downloader/storage/catalog.py (Catalog API consumida)
"""

from __future__ import annotations

import contextlib
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

if TYPE_CHECKING:
    from data_downloader.storage.catalog_models import Partition, ReconcileReport


__all__ = ["CatalogAdapter"]


class CatalogAdapter(QObject):
    """Bridge thread-safe MainThread Qt → ``storage.catalog.Catalog``.

    Sinais:
        partitions_loaded(object): tuple[Partition, ...] — emit após
            ``list_partitions`` completa.
        deleted(str): rel_path apagado — emit após delete bem-sucedido.
        validated(str, bool): (rel_path, checksum_ok) — emit após
            ``revalidate_checksum`` completa.
        reconciled(object): ReconcileReport — emit após reconcile.
        error(object): DataDownloaderError ou Exception — emit em qualquer
            falha de operação.

    Lifecycle:
        adapter = CatalogAdapter()
        adapter.connect_to(on_partitions=..., on_error=...)
        adapter.request_list.emit(data_dir)
        # ... eventually:
        adapter.shutdown()  # finaliza a thread no destrutor da janela
    """

    partitions_loaded = Signal(object)
    deleted = Signal(str)
    validated = Signal(str, bool)
    reconciled = Signal(object)
    error = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        # D2 (COUNCIL-23): NÃO passar parent ao super — QObjects com parent
        # não podem ser movidos para outra thread. Caller mantém referência
        # via atributo + chama shutdown() no closeEvent.
        super().__init__(None)
        self._owner = parent
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.start()

    # ------------------------------------------------------------------
    # Public slots — chamados via signal Queued do MainThread.
    # ------------------------------------------------------------------

    @Slot(object)
    def list_partitions(self, data_dir: object) -> None:
        """Lista TODAS as partições registradas no catálogo.

        Args:
            data_dir: Path raiz dos dados (deve conter ``history/catalog.db``).
        """
        self._propagate_context()
        try:
            partitions = self._load_all_partitions(Path(str(data_dir)))
        except Exception as exc:
            self.error.emit(exc)
            return
        self.partitions_loaded.emit(tuple(partitions))

    @Slot(object, str)
    def delete_partition(self, data_dir: object, rel_path: str) -> None:
        """Apaga uma partição do disco + remove entrada do catálogo.

        Args:
            data_dir: Path raiz dos dados.
            rel_path: Path relativo (ex.: ``F/WDOJ26/2026/03.parquet``).
        """
        self._propagate_context()
        try:
            self._delete_partition(Path(str(data_dir)), rel_path)
        except Exception as exc:
            self.error.emit(exc)
            return
        self.deleted.emit(rel_path)

    @Slot(object, str)
    def revalidate_checksum(self, data_dir: object, rel_path: str) -> None:
        """Recalcula sha256 do arquivo e compara com catálogo.

        Args:
            data_dir: Path raiz dos dados.
            rel_path: Path relativo.
        """
        self._propagate_context()
        try:
            ok = self._revalidate_checksum(Path(str(data_dir)), rel_path)
        except Exception as exc:
            self.error.emit(exc)
            return
        self.validated.emit(rel_path, ok)

    @Slot(object)
    def reconcile(self, data_dir: object) -> None:
        """Roda reconcile (auto-correct=True) e emite report."""
        self._propagate_context()
        try:
            report = self._reconcile(Path(str(data_dir)))
        except Exception as exc:
            self.error.emit(exc)
            return
        self.reconciled.emit(report)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Encerra a thread limpa. Chamar no fechamento da janela."""
        try:
            self._thread.quit()
            self._thread.wait(2000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helper para conexão de signals (idêntico ao DownloadAdapter).
    # ------------------------------------------------------------------

    def connect_to(
        self,
        on_partitions: object | None = None,
        on_deleted: object | None = None,
        on_validated: object | None = None,
        on_reconciled: object | None = None,
        on_error: object | None = None,
    ) -> None:
        """Conecta sinais usando ``Qt.QueuedConnection`` (R11)."""
        if on_partitions is not None:
            self.partitions_loaded.connect(on_partitions, Qt.ConnectionType.QueuedConnection)
        if on_deleted is not None:
            self.deleted.connect(on_deleted, Qt.ConnectionType.QueuedConnection)
        if on_validated is not None:
            self.validated.connect(on_validated, Qt.ConnectionType.QueuedConnection)
        if on_reconciled is not None:
            self.reconciled.connect(on_reconciled, Qt.ConnectionType.QueuedConnection)
        if on_error is not None:
            self.error.connect(on_error, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------
    # Internal — operações de catálogo (rodam dentro da thread do adapter).
    # ------------------------------------------------------------------

    def _propagate_context(self) -> None:
        """Story 2.9 — propaga contextvars do MainThread (best-effort)."""
        with contextlib.suppress(Exception):
            from data_downloader.observability import copy_context_to_thread

            copy_context_to_thread()

    def _open_catalog(self, data_dir: Path):  # type: ignore[no-untyped-def]
        """Abre Catalog na convenção ``data_dir/history/catalog.db``."""
        from data_downloader.storage.catalog import Catalog

        db_path = data_dir / "history" / "catalog.db"
        # auto_reconcile=False — UI controla reconcile explicitamente para
        # evitar surpresa em cada list_partitions.
        return Catalog(
            db_path=db_path,
            data_dir=data_dir,
            auto_reconcile=False,
            auto_cleanup_orphans=False,
        )

    def _load_all_partitions(self, data_dir: Path) -> list[Partition]:
        """Lista TODAS as partições (todos symbols/exchanges)."""
        # Caso o catálogo ainda não exista, retornar lista vazia silently.
        db_path = data_dir / "history" / "catalog.db"
        if not db_path.exists():
            return []

        from data_downloader.storage.catalog import _row_to_partition

        results: list[Partition] = []
        with self._open_catalog(data_dir) as catalog:
            conn = catalog._conn_or_raise()
            rows = conn.execute(
                "SELECT * FROM partitions ORDER BY symbol ASC, year ASC, month ASC"
            ).fetchall()
            results = [_row_to_partition(r) for r in rows]
        return results

    def _delete_partition(self, data_dir: Path, rel_path: str) -> None:
        """Apaga arquivo + remove entrada SQLite (transação)."""
        db_path = data_dir / "history" / "catalog.db"
        if not db_path.exists():
            raise FileNotFoundError(f"catalog db not found: {db_path}")

        # Validação anti path-traversal: rel_path deve ser relativo simples.
        normalized = Path(rel_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"invalid partition path: {rel_path}")

        absolute = data_dir / "history" / normalized
        with self._open_catalog(data_dir) as catalog:
            conn = catalog._conn_or_raise()
            # Remove do catálogo primeiro (rollback se file unlink falhar
            # depois NÃO é trivial — mas drift A auto-corrigirá em próxima
            # reconcile se file persistir).
            with catalog._transaction():
                conn.execute(
                    "DELETE FROM partitions WHERE partition_path = ?",
                    (rel_path,),
                )
            # Tenta apagar arquivo do disco.
            if absolute.exists():
                absolute.unlink()

    def _revalidate_checksum(self, data_dir: Path, rel_path: str) -> bool:
        """Recalcula sha256 + compara contra catálogo."""
        db_path = data_dir / "history" / "catalog.db"
        if not db_path.exists():
            raise FileNotFoundError(f"catalog db not found: {db_path}")

        absolute = data_dir / "history" / rel_path
        if not absolute.exists():
            return False

        # Recalcula sha256.
        digest = hashlib.sha256()
        with absolute.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        actual = digest.hexdigest()

        with self._open_catalog(data_dir) as catalog:
            conn = catalog._conn_or_raise()
            row = conn.execute(
                "SELECT checksum_sha256 FROM partitions WHERE partition_path = ?",
                (rel_path,),
            ).fetchone()
            if row is None:
                return False
            expected = str(row["checksum_sha256"])
        return actual == expected

    def _reconcile(self, data_dir: Path) -> ReconcileReport:
        """Roda reconcile com auto_correct=True."""
        db_path = data_dir / "history" / "catalog.db"
        if not db_path.exists():
            from data_downloader.storage.catalog_models import ReconcileReport

            return ReconcileReport()

        with self._open_catalog(data_dir) as catalog:
            return catalog.reconcile(auto_correct=True)
