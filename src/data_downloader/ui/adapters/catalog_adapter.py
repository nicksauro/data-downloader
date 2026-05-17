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

Fix B-4 (Wave A 2026-05-11) — ``_propagate_context`` previously called
``copy_context_to_thread()`` (no target) inside the slot body. Because
``@Slot`` em ``Qt.QueuedConnection`` já roda DENTRO da QThread do adapter,
``contextvars.copy_context()`` capturava o contexto vazio do worker, nunca
o do MainThread. Resultado: contextvars (job_id, symbol, ...) jamais chegavam
ao worker — bug silencioso. O caller passa parâmetros explicitamente via
signal payload (data_dir, rel_path); para logs estruturados, o adapter agora
faz bind explícito de ``adapter_thread`` no boot da slot, e operações que
precisam de job_id devem recebê-lo via signal arg (não via contextvar
herdado). Propagação real cross-thread requer mudança nas signaturas dos
sinais (defer para story futura) ou que o caller chame
``copy_context_to_thread(target).run(...)`` ANTES de emitir o signal.

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

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot

if TYPE_CHECKING:
    from data_downloader.storage.catalog_models import Partition, ReconcileReport


# v1.3.0 Wave 2B — debounce intervals.
# 500ms coalesce chunks rápidos (1 partition/dia em downloads longos pode
# disparar dezenas de eventos/segundo) num único reload — Aria directive.
_DEBOUNCE_MS: int = 500


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
    # v1.3.0 Wave 2B — observer pattern bridge.
    # Catalog (backend, puro Python) chama ``register_partition_observer``
    # com callback; aqui agendamos via ``QTimer.singleShot`` (afinidade
    # MainThread — singleShot agenda no event loop da thread em que o
    # adapter vive, que é o adapter QThread; mas re-emit do signal usa
    # Qt.QueuedConnection do conector externo). Debounce de 500ms coalesce
    # múltiplos eventos em runtime (download que registra 1 partition/chunk
    # a alta frequência não thrash a UI).
    partition_registered = Signal(str, int, int)
    # Story 4.27 AC1+AC4 (Sol) — emit após ``check_interrupted_jobs`` consultar
    # ``Catalog.list_jobs(statuses=("in_progress","partial"))``. Payload é um
    # dict ``{"job_id", "symbol", "done_chunks", "total_chunks",
    # "data_dir"}`` em caso de hit, ou ``None`` se nada a retomar. Conexão
    # cross-thread DEVE ser ``Qt.QueuedConnection`` — slot é MainThread.
    # ADR-029: SQLite I/O → Worker, não Defer.
    interrupted_job_found = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        # D2 (COUNCIL-23): NÃO passar parent ao super — QObjects com parent
        # não podem ser movidos para outra thread. Caller mantém referência
        # via atributo + chama shutdown() no closeEvent.
        super().__init__(None)
        self._owner = parent
        self._thread = QThread()
        self._thread.setObjectName("catalog-adapter")

        # v1.3.0 Wave 2B — observer pattern. Last-write-wins coalescing:
        # mantemos APENAS o último (symbol, year, month) recebido durante
        # a janela de debounce; quando o timer dispara, emitimos o signal
        # Qt para o(s) listener(s) (CatalogScreen).
        #
        # IMPORTANTE: o ``QTimer`` é parented em ``self`` mas criado ANTES
        # de ``moveToThread`` — Qt move a árvore inteira (adapter + children)
        # para a thread correta numa única operação. Inverter a ordem (criar
        # o QTimer DEPOIS do moveToThread) deixaria o timer órfão na
        # MainThread, e ``QTimer.start()`` falharia com "Timers cannot be
        # started from another thread".
        self._pending_partition: tuple[str, int, int] | None = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(_DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._emit_pending_partition)

        # Move adapter + filhos (incluindo o QTimer) para a thread alocada.
        self.moveToThread(self._thread)
        self._thread.start()

        # Registra o callback puro-Python (catalog.py — module-state).
        # Marcamos o método bound para podermos chamar
        # ``unregister_partition_observer(self._on_partition_event)``
        # no shutdown (mesma identidade — re-register é no-op).
        with contextlib.suppress(Exception):
            from data_downloader.storage.catalog import register_partition_observer

            register_partition_observer(self._on_partition_event)

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

    @Slot(object)
    def check_interrupted_jobs(self, data_dir: object) -> None:
        """Story 4.27 AC1+AC4 — consulta jobs interrompidos em QThread.

        Substitui o ``Catalog(...) + list_jobs + resume_job`` síncrono que
        rodava em ``DownloadScreen.__init__`` (R11 P0-U2 violation: 5-200ms
        no MainThread em catalogs grandes).

        Emite :attr:`interrupted_job_found` com payload ``dict`` (caso de
        hit) ou ``None`` (catalog ausente / sem jobs interrompidos).

        Args:
            data_dir: Path raiz dos dados (str ou Path) — passado via signal
                payload (cross-thread). Catalog.db esperado em
                ``data_dir/_internal/catalog.db`` (ADR-024).

        ADR-029 (sign-off Aria): SQLite I/O → Worker, não Defer. Esta slot
        roda na thread do adapter (``catalog-adapter``), serializada com
        outras operações do catalog (list/delete/reconcile).
        """
        self._propagate_context()
        try:
            payload = self._compute_interrupted_payload(Path(str(data_dir)))
        except Exception as exc:
            # Story 4.27 — best-effort: erro silencioso, banner não aparece.
            # Não emitimos via ``error`` (não é falha do usuário: catalog
            # ausente / schema legado / etc. são casos esperados de no-op).
            with contextlib.suppress(Exception):
                from data_downloader.observability import bind_context

                bind_context(check_interrupted_jobs_error=str(exc))
            self.interrupted_job_found.emit(None)
            return
        self.interrupted_job_found.emit(payload)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Encerra a thread limpa. Chamar no fechamento da janela."""
        # v1.3.0 Wave 2B — desliga observer ANTES de quit da thread, evitando
        # callbacks chegando enquanto o timer/QObject destrói.
        with contextlib.suppress(Exception):
            from data_downloader.storage.catalog import unregister_partition_observer

            unregister_partition_observer(self._on_partition_event)
        with contextlib.suppress(Exception):
            # Para o timer (pode estar pendente); se já parou, no-op.
            self._debounce_timer.stop()
        try:
            self._thread.quit()
            self._thread.wait(2000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # v1.3.0 Wave 2B — observer bridge (debounce + last-write-wins)
    # ------------------------------------------------------------------

    def _on_partition_event(self, symbol: str, year: int, month: int) -> None:
        """Callback puro Python invocado pelo Catalog (qualquer thread).

        Reside na adapter QThread? NÃO — roda na thread que chamou
        ``register_partition`` (tipicamente a worker thread do orchestrator,
        que NÃO é Qt; nos testes, a MainThread). Por isso usamos
        ``QMetaObject.invokeMethod`` (Qt.QueuedConnection) para marshall a
        chamada para o event loop da thread do adapter. ``QMetaObject.invoke
        Method`` com ``QueuedConnection`` é o padrão canônico Qt para essa
        marshall cross-thread (mais robusto que ``QTimer.singleShot`` com
        receptor explícito, que em algumas versões PySide6 6.11+ ignora o
        receptor e dispara no event loop da thread chamadora — race
        observada em test offscreen).

        Last-write-wins: o último evento da janela vence. Para granularidade
        diária (chunk_ledger), múltiplos chunks do mesmo mês são coalescidos
        — UI re-popula a tabela uma vez só.
        """
        # Atualiza estado em uma operação atômica (Python GIL — set/get de
        # uma referência é thread-safe). Não usamos lock pois o pior caso
        # é perder 1 evento de coalescing, mas o timer dispara mesmo assim
        # e o reload re-consulta o catalog (sempre source-of-truth).
        self._pending_partition = (symbol, year, month)
        # Marshall para o event loop do adapter via QueuedConnection — único
        # mecanismo seguro quando este callback é invocado de uma thread
        # que NÃO é a do adapter (caso normal: worker thread do orchestrator).
        with contextlib.suppress(Exception):
            QMetaObject.invokeMethod(
                self, "_arm_debounce_timer", Qt.ConnectionType.QueuedConnection
            )

    @Slot()
    def _arm_debounce_timer(self) -> None:
        """Re-arma o debounce timer no event loop do adapter. Thread-affined.

        Importante: este slot é invocado via ``QMetaObject.invokeMethod``
        com ``QueuedConnection``, o que garante execução no event loop da
        thread do adapter (``self._thread``). Sem essa marshall,
        ``self._debounce_timer.start()`` falharia com "Timers cannot be
        started from another thread".
        """
        if self._debounce_timer.isActive():
            # Já armado — só atualiza o "pending" (já feito em
            # _on_partition_event). Reseta o timer para coalescer novos
            # eventos dentro da mesma janela de 500ms.
            self._debounce_timer.stop()
        self._debounce_timer.start()

    @Slot()
    def _emit_pending_partition(self) -> None:
        """Timer fired — emite o signal Qt com o último evento pendente."""
        pending = self._pending_partition
        self._pending_partition = None
        if pending is None:
            return
        symbol, year, month = pending
        # Emit Qt signal — listeners (CatalogScreen) recebem via Queued.
        self.partition_registered.emit(symbol, year, month)

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
        on_partition_registered: object | None = None,
        on_interrupted: object | None = None,
    ) -> None:
        """Conecta sinais usando ``Qt.QueuedConnection`` (R11).

        v1.3.0 Wave 2B — ``on_partition_registered(symbol, year, month)``
        recebe notificações debounced (500ms) quando o catálogo registra
        uma nova partition/chunk em runtime. CatalogScreen liga este sinal
        ao :meth:`refresh` para auto-atualização durante downloads.

        Story 4.27 AC1+AC4 — ``on_interrupted(payload)`` recebe o resultado
        de :meth:`check_interrupted_jobs`. ``payload`` é ``dict`` ou ``None``
        (ver docstring do signal :attr:`interrupted_job_found`).
        """
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
        if on_partition_registered is not None:
            self.partition_registered.connect(
                on_partition_registered, Qt.ConnectionType.QueuedConnection
            )
        if on_interrupted is not None:
            self.interrupted_job_found.connect(on_interrupted, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------
    # Internal — operações de catálogo (rodam dentro da thread do adapter).
    # ------------------------------------------------------------------

    def _propagate_context(self) -> None:
        """Bind adapter-thread identity context (Fix B-4 Wave A).

        Note (B-4): the previous implementation called
        ``copy_context_to_thread()`` (no target) which was a documented no-op
        — the slot body already runs on the worker QThread, so
        ``contextvars.copy_context()`` would only see the empty worker
        context. We now bind a minimal worker-side identity (adapter name +
        thread) so logs emitted from this adapter at least carry that
        breadcrumb. True MainThread → worker propagation requires the caller
        to ferry the snapshot via signal payload (deferred — out of Wave A
        scope). All operational arguments (data_dir, rel_path) are already
        passed explicitly via signal args, so no functional regression.
        """
        with contextlib.suppress(Exception):
            from data_downloader.observability import bind_context

            bind_context(
                adapter="catalog",
                adapter_thread=QThread.currentThread().objectName() or "catalog-adapter",
            )

    def _open_catalog(self, data_dir: Path):  # type: ignore[no-untyped-def]
        """Abre Catalog na convenção ``data_dir/_internal/catalog.db`` (ADR-024).

        Migration silenciosa em ``Catalog.__post_init__`` cuida de mover
        legacy ``data_dir/history/catalog.db`` se houver.
        """
        from data_downloader.storage.catalog import Catalog

        db_path = data_dir / "_internal" / "catalog.db"
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
        db_path = data_dir / "_internal" / "catalog.db"
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
        db_path = data_dir / "_internal" / "catalog.db"
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
        db_path = data_dir / "_internal" / "catalog.db"
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
        db_path = data_dir / "_internal" / "catalog.db"
        if not db_path.exists():
            from data_downloader.storage.catalog_models import ReconcileReport

            return ReconcileReport()

        with self._open_catalog(data_dir) as catalog:
            return catalog.reconcile(auto_correct=True)

    def _compute_interrupted_payload(self, data_dir: Path) -> dict | None:
        """Story 4.27 AC1 — helper síncrono (roda dentro da QThread).

        Replica a lógica que estava em ``DownloadScreen._check_for_interrupted_download``:
        abre Catalog (catalog.db), consulta jobs com status in_progress/partial
        (limit=1) e, se houver, computa resume_job para extrair done/total
        chunks. Retorna ``None`` se não há nada a retomar.

        Worker thread — R11 OK (ADR-029).
        """
        db_path = data_dir / "_internal" / "catalog.db"
        if not db_path.exists():
            return None
        from data_downloader.storage.catalog import Catalog

        job = None
        plan = None
        catalog = Catalog(db_path=db_path, data_dir=data_dir)
        try:
            jobs = catalog.list_jobs(statuses=("in_progress", "partial"), limit=1)
            if jobs:
                job = jobs[0]
                with contextlib.suppress(Exception):
                    plan = catalog.resume_job(job.job_id)
        finally:
            with contextlib.suppress(Exception):
                catalog.close()
        if job is None:
            return None
        symbol = getattr(job, "symbol", "?") or "?"
        if plan is not None:
            done = len(getattr(plan, "completed_partitions", ()) or ())
            pending = len(getattr(plan, "pending_chunks", ()) or ())
            total = done + pending
        else:
            done = 0
            total = 0
        return {
            "job_id": getattr(job, "job_id", None),
            "symbol": symbol,
            "done_chunks": done,
            "total_chunks": total,
            "data_dir": data_dir,
        }
