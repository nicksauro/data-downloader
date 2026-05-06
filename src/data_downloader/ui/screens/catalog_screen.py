"""data_downloader.ui.screens.catalog_screen — Tela Catálogo (Story 3.2).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Tela de listagem e gerenciamento de partições já baixadas. Permite filtrar,
selecionar, validar checksum, abrir pasta e apagar (com confirmação destrutiva).

Componentes:

    - **QTableView + QSortFilterProxyModel** — tabela com colunas: contract,
      year, month, row_count, size_mb, last_modified, schema_version.
    - **Search box + Filtros (combo)** — filtro por símbolo (Ctrl+F) +
      combo por exchange.
    - **Detail panel** — pasta, schema, DLL, checksum, ações (RE-VALIDAR,
      ABRIR PASTA, APAGAR).
    - **Footer summary** — "{N} partições, {total_mb} MB total" + drift
      indicator se aplicável.

5 estados (WIREFRAMES.md §"Tela 2 — CatalogScreen"):

    - **Normal** — tabela populada; detail panel se row selected.
    - **Loading** — texto "Carregando catálogo...".
    - **Error** — banner com microcopy + CTA reconciliar / retry.
    - **Empty** (primeira vez) — ícone xl + ``EMP_CATALOG_FIRST_RUN_*`` +
      CTA primário ``BTN_DOWNLOAD``.
    - **Empty filtrado** — ``EMP_CATALOG_FILTER_NO_MATCH_*`` + ``BTN_CLEAR_FILTERS``.
    - **Success** — toast verde após reconcile/delete/validate.

Confirmação destrutiva (apagar): modal exige usuário digitar "APAGAR" para
habilitar botão (PRINCIPLES.md §H5 / MICROCOPY §17b.5 — MOD_DELETE_PERMANENT_*).

Atalhos (THEME.md §6 — CatalogScreen):

    - ``Ctrl+R`` — Refresh (NÃO F5 — finding M10).
    - ``Ctrl+F`` — Foca campo de busca.
    - ``Esc``    — Limpa filtros (se algum); senão no-op.
    - ``Delete`` — Apagar row selecionada (confirmação destrutiva).

Adapter: ``ui/adapters/catalog_adapter.py`` — list_partitions /
delete_partition / revalidate_checksum / reconcile.

Microcopy (R17 — Uma): TODAS as strings vêm de ``microcopy_loader``.

Referências:
    - docs/ux/WIREFRAMES.md (Tela 2)
    - docs/ux/MICROCOPY_CATALOG.md §17b.2
    - docs/decisions/COUNCIL-23-epic3-first-screen.md (D1-D4)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from data_downloader.ui.adapters.catalog_adapter import CatalogAdapter
from data_downloader.ui.microcopy_loader import format_msg

if TYPE_CHECKING:
    from data_downloader.storage.catalog_models import Partition


__all__ = ["CatalogScreen", "PartitionTableModel"]


# Estados nominais (consumidos por testes via ``current_state()``).
STATE_NORMAL = "normal"
STATE_LOADING = "loading"
STATE_ERROR = "error"
STATE_EMPTY = "empty"
STATE_EMPTY_FILTERED = "empty_filtered"
STATE_SUCCESS = "success"


# Stack indices.
_IDX_LOADING = 0
_IDX_NORMAL = 1
_IDX_EMPTY = 2
_IDX_EMPTY_FILTERED = 3
_IDX_ERROR = 4


class PartitionTableModel(QAbstractTableModel):
    """Modelo Qt sobre lista de ``Partition`` para QTableView.

    Colunas (ordem):
        0 — Símbolo
        1 — Bolsa
        2 — Período (YYYY-MM)
        3 — Trades (row_count)
        4 — Tamanho (MB)
        5 — Atualizado (written_at)
        6 — Schema
    """

    COLUMNS = (
        "LBL_COL_SYMBOL",
        "LBL_COL_EXCHANGE",
        "LBL_COL_PERIOD",
        "LBL_COL_TRADES",
        "LBL_COL_SIZE_MB",
        "LBL_COL_LAST_UPDATE",
        "LBL_COL_SCHEMA",
    )

    def __init__(self, partitions: tuple[Partition, ...] | list[Partition] | None = None) -> None:
        super().__init__()
        self._partitions: list[Partition] = list(partitions or [])

    def set_partitions(self, partitions: tuple[Partition, ...] | list[Partition]) -> None:
        self.beginResetModel()
        self._partitions = list(partitions)
        self.endResetModel()

    def partitions(self) -> list[Partition]:
        return list(self._partitions)

    def partition_at(self, row: int) -> Partition | None:
        if 0 <= row < len(self._partitions):
            return self._partitions[row]
        return None

    # ------------------------------------------------------------------
    # QAbstractTableModel API
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._partitions)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self.COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return format_msg(self.COLUMNS[section])
            return None
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        partition = self.partition_at(index.row())
        if partition is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            col = index.column()
            if col == 0:
                return partition.symbol
            if col == 1:
                return partition.exchange
            if col == 2:
                return f"{partition.year:04d}-{partition.month:02d}"
            if col == 3:
                return f"{partition.row_count:,}".replace(",", ".")
            if col == 4:
                mb = partition.file_size_bytes / (1024 * 1024)
                return f"{mb:.2f}"
            if col == 5:
                if isinstance(partition.written_at, datetime):
                    return partition.written_at.strftime("%Y-%m-%d %H:%M")
                return str(partition.written_at)
            if col == 6:
                return partition.schema_version
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (3, 4):
            # Numéricos alinhados à direita.
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class CatalogScreen(QWidget):
    """Tela Catálogo — browse de partições baixadas (5 estados).

    Sinais públicos (úteis para testes / MainWindow):
        state_changed(str): emitido quando ``_set_state`` muda o estado.

    Signals internos para despacho cross-thread (D1 COUNCIL-23):
        _request_list(object): data_dir
        _request_delete(object, str): data_dir, rel_path
        _request_validate(object, str): data_dir, rel_path
        _request_reconcile(object): data_dir
    """

    state_changed = Signal(str)
    # Story 4.6 (UX polish, Pichau directive 2026-05-05) — empty state CTA
    # solicita navegação para DownloadScreen. MainWindow conecta este sinal
    # ao ``set_active_screen(SCREEN_DOWNLOAD)``. Quando não conectado, atalho
    # global Ctrl+D continua funcionando como fallback.
    request_navigate_to_download = Signal()

    _request_list = Signal(object)
    _request_delete = Signal(object, str)
    _request_validate = Signal(object, str)
    _request_reconcile = Signal(object)

    def __init__(
        self,
        data_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._data_dir = Path(data_dir) if data_dir is not None else Path.cwd() / "data"

        # Adapter (QThread bridge).
        self._adapter = CatalogAdapter(self)
        self._adapter.connect_to(
            on_partitions=self._on_partitions_loaded,
            on_deleted=self._on_deleted,
            on_validated=self._on_validated,
            on_reconciled=self._on_reconciled,
            on_error=self._on_error,
        )
        # Conexões cross-thread (D1).
        self._request_list.connect(
            self._adapter.list_partitions, Qt.ConnectionType.QueuedConnection
        )
        self._request_delete.connect(
            self._adapter.delete_partition, Qt.ConnectionType.QueuedConnection
        )
        self._request_validate.connect(
            self._adapter.revalidate_checksum, Qt.ConnectionType.QueuedConnection
        )
        self._request_reconcile.connect(self._adapter.reconcile, Qt.ConnectionType.QueuedConnection)

        # Header com título + atualizar.
        self._title = QLabel(format_msg("LBL_CATALOG_SCREEN_TITLE"), self)
        self._title.setProperty("role", "title")

        self._refresh_btn = QPushButton(format_msg("BTN_REFRESH_CATALOG"), self)
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.clicked.connect(self.refresh)

        # Search + Filtros.
        self._search_edit = QLineEdit(self)
        self._search_edit.setPlaceholderText(format_msg("PLH_SEARCH_CATALOG"))
        self._search_edit.setObjectName("searchEdit")
        self._search_edit.textChanged.connect(self._on_filter_changed)

        self._exchange_filter = QComboBox(self)
        self._exchange_filter.addItem("Todas", "")
        self._exchange_filter.addItem("F (BMF)", "F")
        self._exchange_filter.addItem("B (Bovespa)", "B")
        self._exchange_filter.currentIndexChanged.connect(self._on_filter_changed)
        self._exchange_filter.setObjectName("exchangeFilter")

        # Modelo + proxy de filtro.
        self._model = PartitionTableModel()
        self._proxy = _PartitionFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        # Tabela.
        self._table = QTableView(self)
        self._table.setModel(self._proxy)
        self._table.setObjectName("partitionsTable")
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.selectionModel().selectionChanged.connect(self._on_row_selected)

        # Detail panel.
        self._detail_panel = self._build_detail_panel()
        self._detail_panel.setVisible(False)

        # Footer summary.
        self._footer = QLabel("", self)
        self._footer.setProperty("role", "muted")

        # Empty state widgets (filtrado e first-run).
        self._empty_card = self._build_empty_card()
        self._empty_filtered_card = self._build_empty_filtered_card()

        # Loading widget.
        self._loading_card = self._build_loading_card()

        # Error widget.
        self._error_card = self._build_error_card()

        # Stack interno para 5 estados.
        # idx: 0=loading, 1=normal(table+detail), 2=empty, 3=empty_filtered, 4=error
        self._state_stack = QStackedWidget(self)

        normal_container = QWidget(self)
        normal_layout = QVBoxLayout(normal_container)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.addWidget(self._table, stretch=3)
        normal_layout.addWidget(self._detail_panel, stretch=1)

        # IMPORTANT: ordem deve bater com _IDX_*.
        self._state_stack.addWidget(self._loading_card)  # 0
        self._state_stack.addWidget(normal_container)  # 1
        self._state_stack.addWidget(self._empty_card)  # 2
        self._state_stack.addWidget(self._empty_filtered_card)  # 3
        self._state_stack.addWidget(self._error_card)  # 4

        # Top bar (search + filtros + refresh).
        top_bar = QHBoxLayout()
        top_bar.addWidget(self._search_edit, stretch=2)
        top_bar.addWidget(QLabel(format_msg("LBL_FILTERS_DROPDOWN") + ":", self))
        top_bar.addWidget(self._exchange_filter, stretch=1)
        top_bar.addStretch(1)
        top_bar.addWidget(self._refresh_btn)

        # Header bar (title + spacer).
        title_bar = QHBoxLayout()
        title_bar.addWidget(self._title)
        title_bar.addStretch(1)

        # Outer layout.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(12)
        outer.addLayout(title_bar)
        outer.addLayout(top_bar)
        outer.addWidget(self._state_stack, stretch=1)
        outer.addWidget(self._footer)

        # Toast.
        self._toast = self._build_toast()
        self._toast.setParent(self)
        self._toast.hide()

        # Atalhos.
        self._register_shortcuts()

        self._current_state = STATE_LOADING
        self._set_state(STATE_LOADING)

        # Carga inicial (deferred para não bloquear __init__).
        QTimer.singleShot(0, self.refresh)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_state(self) -> str:
        return self._current_state

    def refresh(self) -> None:
        """Re-query catálogo (atalho Ctrl+R)."""
        self._set_state(STATE_LOADING)
        self._request_list.emit(self._data_dir)

    def set_data_dir(self, data_dir: Path) -> None:
        """Atualiza data_dir (chamado por SettingsScreen ao mudar pasta)."""
        self._data_dir = Path(data_dir)
        self.refresh()

    def handle_escape(self) -> bool:
        """Esc — limpa filtros se algum ativo, senão no-op."""
        if self._search_edit.text() or self._exchange_filter.currentIndex() > 0:
            self._search_edit.clear()
            self._exchange_filter.setCurrentIndex(0)
            return True
        return False

    # ------------------------------------------------------------------
    # Construção UI
    # ------------------------------------------------------------------

    def _build_detail_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setProperty("elevated", "true")
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(panel)
        layout.setSpacing(6)

        self._detail_title = QLabel("", panel)
        self._detail_title.setProperty("role", "subtitle")
        layout.addWidget(self._detail_title)

        self._detail_folder = QLabel("", panel)
        self._detail_folder.setProperty("role", "code")
        self._detail_folder.setWordWrap(True)
        layout.addWidget(self._detail_folder)

        self._detail_schema = QLabel("", panel)
        self._detail_schema.setProperty("role", "muted")
        layout.addWidget(self._detail_schema)

        self._detail_checksum = QLabel("", panel)
        self._detail_checksum.setProperty("role", "muted")
        self._detail_checksum.setWordWrap(True)
        layout.addWidget(self._detail_checksum)

        self._detail_rowcount = QLabel("", panel)
        self._detail_rowcount.setProperty("role", "muted")
        layout.addWidget(self._detail_rowcount)

        # Botões de ação.
        actions = QHBoxLayout()
        self._validate_btn = QPushButton(format_msg("BTN_REVALIDATE_CHECKSUM"), panel)
        self._validate_btn.setObjectName("validateBtn")
        self._validate_btn.clicked.connect(self._on_validate_clicked)
        actions.addWidget(self._validate_btn)

        self._open_folder_btn = QPushButton(format_msg("BTN_OPEN_FOLDER"), panel)
        self._open_folder_btn.setObjectName("openFolderBtn")
        self._open_folder_btn.clicked.connect(self._on_open_folder_clicked)
        actions.addWidget(self._open_folder_btn)

        self._delete_btn = QPushButton(format_msg("BTN_DELETE"), panel)
        self._delete_btn.setProperty("variant", "destructive")
        self._delete_btn.setObjectName("deleteBtn")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        actions.addWidget(self._delete_btn)

        actions.addStretch(1)
        layout.addLayout(actions)

        return panel

    def _build_empty_card(self) -> QWidget:
        # Story 4.6 (UX polish HIGH, Pichau directive 2026-05-05):
        # Empty state agora inclui CTA "Baixar primeiro símbolo" (Ctrl+D)
        # — antes era só ícone + texto sem ação visível.
        card = QWidget(self)
        layout = QVBoxLayout(card)
        layout.addStretch(1)

        icon = QLabel("📊", card)
        icon.setObjectName("emptyStateIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 56px;")
        layout.addWidget(icon)

        title = QLabel(format_msg("EMP_CATALOG_FIRST_RUN_TITLE"), card)
        title.setObjectName("emptyStateTitle")
        title.setProperty("role", "subtitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel(format_msg("EMP_CATALOG_FIRST_RUN_SUBTITLE"), card)
        sub.setProperty("role", "muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        # CTA primário — emite sinal para MainWindow trocar para DownloadScreen.
        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        self._empty_cta_btn = QPushButton(format_msg("BTN_DOWNLOAD_FIRST_SYMBOL"), card)
        self._empty_cta_btn.setObjectName("emptyStateCta")
        self._empty_cta_btn.setProperty("variant", "primary")
        self._empty_cta_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._empty_cta_btn.clicked.connect(self.request_navigate_to_download.emit)
        cta_row.addWidget(self._empty_cta_btn)
        cta_row.addStretch(1)
        layout.addLayout(cta_row)

        layout.addStretch(1)
        return card

    def _build_empty_filtered_card(self) -> QWidget:
        card = QWidget(self)
        layout = QVBoxLayout(card)
        layout.addStretch(1)

        self._empty_filter_title = QLabel(
            format_msg("EMP_CATALOG_FILTER_NO_MATCH_TITLE", filter=""), card
        )
        self._empty_filter_title.setProperty("role", "subtitle")
        self._empty_filter_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_filter_title)

        sub = QLabel(format_msg("EMP_CATALOG_FILTER_NO_MATCH_SUBTITLE"), card)
        sub.setProperty("role", "muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        clear_btn_row = QHBoxLayout()
        clear_btn_row.addStretch(1)
        clear_btn = QPushButton(format_msg("BTN_CLEAR_FILTERS"), card)
        clear_btn.setObjectName("clearFiltersBtn")
        clear_btn.clicked.connect(self._on_clear_filters_clicked)
        clear_btn_row.addWidget(clear_btn)
        clear_btn_row.addStretch(1)
        layout.addLayout(clear_btn_row)

        layout.addStretch(1)
        return card

    def _build_loading_card(self) -> QWidget:
        card = QWidget(self)
        layout = QVBoxLayout(card)
        layout.addStretch(1)
        label = QLabel(format_msg("LBL_CATALOG_LOADING"), card)
        label.setProperty("role", "muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        layout.addStretch(1)
        return card

    def _build_error_card(self) -> QFrame:
        card = QFrame(self)
        card.setProperty("role", "error-card")

        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        self._error_title = QLabel("", card)
        self._error_title.setProperty("role", "title")
        self._error_title.setStyleSheet("color: #F25656;")
        self._error_title.setWordWrap(True)
        layout.addWidget(self._error_title)

        self._error_detail = QLabel("", card)
        self._error_detail.setWordWrap(True)
        layout.addWidget(self._error_detail)

        self._error_action = QLabel("", card)
        self._error_action.setProperty("role", "muted")
        self._error_action.setWordWrap(True)
        layout.addWidget(self._error_action)

        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        retry_btn = QPushButton(format_msg("BTN_RETRY"), card)
        retry_btn.clicked.connect(self.refresh)
        button_row.addWidget(retry_btn)

        reconcile_btn = QPushButton(format_msg("BTN_RECONCILE"), card)
        reconcile_btn.setObjectName("reconcileBtn")
        reconcile_btn.clicked.connect(self._on_reconcile_clicked)
        button_row.addWidget(reconcile_btn)
        layout.addLayout(button_row)

        return card

    def _build_toast(self) -> QFrame:
        toast = QFrame()
        toast.setProperty("role", "toast")
        toast.setProperty("variant", "success")
        toast.setObjectName("catalogToast")
        toast.setFixedWidth(320)

        layout = QVBoxLayout(toast)
        self._toast_text = QLabel("", toast)
        self._toast_text.setWordWrap(True)
        layout.addWidget(self._toast_text)
        return toast

    # ------------------------------------------------------------------
    # Atalhos
    # ------------------------------------------------------------------

    def _register_shortcuts(self) -> None:
        for keyseq, handler in (
            ("Ctrl+R", self.refresh),
            ("Ctrl+F", self._focus_search),
            ("Delete", self._on_delete_clicked),
        ):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    def _focus_search(self) -> None:
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # ------------------------------------------------------------------
    # Slots — botões / filtros
    # ------------------------------------------------------------------

    def _on_filter_changed(self, *_args: object) -> None:
        text = self._search_edit.text().strip()
        exchange = self._exchange_filter.currentData() or ""
        self._proxy.set_filter(text, str(exchange))
        # Recalcula estado: se há rows (model) mas proxy vazio = empty_filtered.
        self._update_post_filter_state()

    def _on_clear_filters_clicked(self) -> None:
        self._search_edit.clear()
        self._exchange_filter.setCurrentIndex(0)

    def _on_row_selected(self, *_args: object) -> None:
        partition = self._selected_partition()
        if partition is None:
            self._detail_panel.setVisible(False)
            return
        self._detail_panel.setVisible(True)
        self._detail_title.setText(format_msg("LBL_DETAIL_PANEL_HEADER", symbol=partition.symbol))
        self._detail_folder.setText(
            f"{format_msg('LBL_DETAIL_FOLDER')}: {partition.partition_path}"
        )
        self._detail_schema.setText(
            f"{format_msg('LBL_DETAIL_SCHEMA')}: {partition.schema_version}"
        )
        prefix = partition.checksum_sha256[:8]
        self._detail_checksum.setText(
            f"{format_msg('LBL_DETAIL_CHECKSUM')}: "
            + format_msg("LBL_DETAIL_CHECKSUM_VALID", prefix=prefix)
        )
        self._detail_rowcount.setText(
            f"{format_msg('LBL_DETAIL_ROW_COUNT')}: " f"{partition.row_count:,}".replace(",", ".")
        )

    def _on_validate_clicked(self) -> None:
        partition = self._selected_partition()
        if partition is None:
            return
        self._request_validate.emit(self._data_dir, partition.partition_path)

    def _on_open_folder_clicked(self) -> None:
        partition = self._selected_partition()
        if partition is None:
            return
        # Abre pasta (via webbrowser/open-equivalent).
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            path = self._data_dir / "history" / partition.partition_path
            folder = path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception:
            pass

    def _on_delete_clicked(self) -> None:
        partition = self._selected_partition()
        if partition is None:
            return
        # Modal de confirmação destrutiva (R17 — MOD_DELETE_PERMANENT_*).
        body = format_msg("MOD_DELETE_PERMANENT_BODY", symbol=partition.symbol)
        hint = format_msg("MOD_DELETE_PERMANENT_HINT")

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle(format_msg("BTN_DELETE"))
        dialog.setText(body)
        dialog.setInformativeText(hint)
        confirm_btn = dialog.addButton(
            format_msg("BTN_DELETE_CONFIRM"), QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton(format_msg("BTN_CONTINUE"), QMessageBox.ButtonRole.RejectRole)
        dialog.exec()

        if dialog.clickedButton() is not confirm_btn:
            return
        # Despacha delete cross-thread.
        self._request_delete.emit(self._data_dir, partition.partition_path)

    def _on_reconcile_clicked(self) -> None:
        self._request_reconcile.emit(self._data_dir)

    # ------------------------------------------------------------------
    # Slots — sinais do adapter (Qt.QueuedConnection — MainThread)
    # ------------------------------------------------------------------

    def _on_partitions_loaded(self, partitions: object) -> None:
        partitions_list = list(partitions or ())  # type: ignore[arg-type]
        self._model.set_partitions(partitions_list)
        # Atualiza footer.
        n = len(partitions_list)
        total_bytes = sum(getattr(p, "file_size_bytes", 0) for p in partitions_list)
        total_mb = total_bytes / (1024 * 1024)
        self._footer.setText(
            format_msg(
                "LBL_CATALOG_FOOTER_SUMMARY",
                n_partitions=n,
                total_mb=f"{total_mb:.2f}",
            )
        )
        # Decide estado.
        if n == 0:
            self._set_state(STATE_EMPTY)
        else:
            self._set_state(STATE_NORMAL)
            self._update_post_filter_state()

    def _on_deleted(self, rel_path: str) -> None:
        # Encontra symbol pelo path para microcopy do toast.
        symbol = ""
        try:
            parts = Path(rel_path).parts
            if len(parts) >= 2:
                symbol = parts[1]
        except Exception:
            symbol = rel_path
        self._show_toast(
            format_msg("TST_DELETE_DONE_TOAST", symbol=symbol),
            variant="info",
            duration_ms=3000,
        )
        self.refresh()

    def _on_validated(self, rel_path: str, ok: bool) -> None:
        if ok:
            self._show_toast(
                format_msg("TST_VALIDATION_PASSED"),
                variant="success",
                duration_ms=4000,
            )
        else:
            self._show_toast(
                format_msg("TST_VALIDATION_FAILED", n_issues=1),
                variant="error",
                duration_ms=6000,
            )

    def _on_reconciled(self, report: object) -> None:
        n_added = len(getattr(report, "auto_corrected_paths", ()) or ())
        n_removed = 0  # reconcile não remove (drift B só reporta).
        self._show_toast(
            format_msg("TST_RECONCILE_DONE", n_added=n_added, n_removed=n_removed),
            variant="success",
            duration_ms=4000,
        )
        self.refresh()

    def _on_error(self, exc: object) -> None:
        title = ""
        detail = str(exc)
        action = ""
        try:
            from data_downloader.public_api.exceptions import DataDownloaderError
            from data_downloader.ui.microcopy_loader import MSG

            if isinstance(exc, DataDownloaderError):
                msg_id = exc.humanized_message
                entry = MSG.get(msg_id)
                if entry is not None:
                    title = entry.title or ""
                    detail = entry.detail or detail
                    action = entry.action or ""
        except Exception:
            pass

        if not title:
            title = "Erro"
        self._error_title.setText(title)
        self._error_detail.setText(detail)
        self._error_action.setText(action)
        self._set_state(STATE_ERROR)

    # ------------------------------------------------------------------
    # State machine + helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._current_state = state
        if state == STATE_LOADING:
            self._state_stack.setCurrentIndex(_IDX_LOADING)
        elif state == STATE_NORMAL:
            self._state_stack.setCurrentIndex(_IDX_NORMAL)
        elif state == STATE_EMPTY:
            self._state_stack.setCurrentIndex(_IDX_EMPTY)
        elif state == STATE_EMPTY_FILTERED:
            self._state_stack.setCurrentIndex(_IDX_EMPTY_FILTERED)
        elif state == STATE_ERROR:
            self._state_stack.setCurrentIndex(_IDX_ERROR)
        self.state_changed.emit(state)

    def _update_post_filter_state(self) -> None:
        """Após filtro: se modelo tem rows mas proxy vazio = empty_filtered."""
        if self._model.rowCount() == 0:
            return  # já em STATE_EMPTY (first-run)
        if self._proxy.rowCount() == 0:
            filter_text = self._search_edit.text().strip()
            self._empty_filter_title.setText(
                format_msg("EMP_CATALOG_FILTER_NO_MATCH_TITLE", filter=filter_text)
            )
            self._set_state(STATE_EMPTY_FILTERED)
        else:
            if self._current_state in (STATE_EMPTY_FILTERED,):
                self._set_state(STATE_NORMAL)

    def _selected_partition(self) -> Partition | None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            return None
        source_row = self._proxy.mapToSource(idx).row()
        return self._model.partition_at(source_row)

    def _show_toast(self, text: str, *, variant: str, duration_ms: int) -> None:
        self._toast.setProperty("variant", variant)
        self._toast.style().unpolish(self._toast)
        self._toast.style().polish(self._toast)
        self._toast_text.setText(text)
        self._toast.adjustSize()
        margin = 24
        x = self.width() - self._toast.width() - margin
        y = margin
        self._toast.move(max(margin, x), y)
        self._toast.show()
        self._toast.raise_()
        QTimer.singleShot(duration_ms, self._toast.hide)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event: object) -> None:  # noqa: N802
        try:
            self._adapter.shutdown()
        finally:
            super().closeEvent(event)  # type: ignore[arg-type]


class _PartitionFilterProxy(QSortFilterProxyModel):
    """Proxy de filtro client-side: por símbolo (substring) + exchange (==)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._symbol_filter = ""
        self._exchange_filter = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_filter(self, symbol: str, exchange: str) -> None:
        self._symbol_filter = symbol.strip().upper()
        self._exchange_filter = exchange.strip().upper()
        # ``invalidate()`` é a API canônica em PySide6 6.11+
        # (invalidateFilter/invalidateRowsFilter foram marcadas deprecated).
        self.invalidate()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        # Symbol = col 0, Exchange = col 1.
        sym_idx = model.index(source_row, 0, source_parent)
        exc_idx = model.index(source_row, 1, source_parent)
        symbol = str(model.data(sym_idx, Qt.ItemDataRole.DisplayRole) or "").upper()
        exchange = str(model.data(exc_idx, Qt.ItemDataRole.DisplayRole) or "").upper()
        if self._symbol_filter and self._symbol_filter not in symbol:
            return False
        return not (self._exchange_filter and exchange != self._exchange_filter)
