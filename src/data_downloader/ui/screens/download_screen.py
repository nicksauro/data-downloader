"""data_downloader.ui.screens.download_screen — Tela Baixar Histórico (Story 3.2).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Tela primária da UI. Implementa o **golden path 1 clique** (PRINCIPLES.md §1).

Estados (5) implementados via ``QStackedWidget`` interno:

    - ``normal``   — form com defaults; botão BAIXAR ativo.
    - ``loading``  — ProgressCard visível; botão CANCELAR.
        - sub-state ``reconnecting`` (quirk 99% Q11-99 — Flow 4): cor amarela
          + banner WAR_99_RECONNECT literal. NÃO interrompe download.
        - sub-state ``cancelling`` — botão "Cancelando..." disabled.
    - ``error``    — card vermelho com microcopy ``ERR_*`` + botão RETRY.
    - ``empty``    — N/A para tela de input (defaults inteligentes).
    - ``success``  — toast verde 5s + tela volta ao normal.

Atalhos (THEME.md §6 — DownloadScreen):
    - ``Ctrl+D`` — Iniciar download (se válido).
    - ``Esc``    — Cancela download ativo (context-aware).
    - ``Ctrl+C`` — Cancelar download (sinônimo de Esc com download ativo).

Adapter: ``ui/adapters/download_adapter.py`` consome ``public_api.download()``.

Microcopy (R17 — Uma): TODAS as strings vêm de ``microcopy_loader``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from data_downloader.ui.adapters.download_adapter import DownloadAdapter
from data_downloader.ui.microcopy_loader import format_msg
from data_downloader.ui.widgets.period_picker import PeriodPicker
from data_downloader.ui.widgets.progress_card import ProgressCard
from data_downloader.ui.widgets.symbol_picker import SymbolPicker

if TYPE_CHECKING:
    pass


__all__ = ["DownloadScreen"]


# Estados nominais (consumidos por testes via ``current_state()``).
STATE_NORMAL = "normal"
STATE_LOADING = "loading"
STATE_ERROR = "error"
STATE_SUCCESS = "success"


class DownloadScreen(QWidget):
    """Tela de download — 5 estados via QStackedWidget interno.

    Sinais públicos (úteis para testes):
        state_changed(str): emitido quando ``_set_state`` muda o estado.
    """

    state_changed = Signal(str)

    # Signal interno para despachar start ao adapter cross-thread (auto
    # marshalling via QueuedConnection — mais robusto que invokeMethod
    # com tipos não-Qt).
    _request_start = Signal(str, str, object, object, object)
    _request_cancel = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Adapter (QThread bridge para public_api.download).
        self._adapter = DownloadAdapter(self)
        self._adapter.connect_to(
            on_progress=self._on_progress,
            on_error=self._on_error,
            on_cancelled=self._on_cancelled,
            on_finished=self._on_finished,
        )
        # Conexões internas: signals → slots do adapter (cross-thread Queued).
        self._request_start.connect(self._adapter.start, Qt.ConnectionType.QueuedConnection)
        self._request_cancel.connect(self._adapter.cancel, Qt.ConnectionType.QueuedConnection)

        self._download_active = False

        # Header.
        self._title = QLabel(format_msg("LBL_DOWNLOAD_SCREEN_TITLE"), self)
        self._title.setProperty("role", "title")

        self._subtitle = QLabel(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"), self)
        self._subtitle.setProperty("role", "subtitle")

        # Form (state=normal e state=success compartilham layout).
        self._form_card = self._build_form_card()

        # Card error.
        self._error_card = self._build_error_card()

        # ProgressCard (state=loading).
        self._progress_card = ProgressCard(self)
        self._progress_card.cancel_requested.connect(self._on_cancel_clicked)

        # Footer.
        self._footer = QLabel(format_msg("LBL_FOOTER_SHORTCUTS"), self)
        self._footer.setProperty("role", "muted")

        # Stack interno para os 3 estados visíveis (normal/loading/error).
        # Success é overlay (toast) sobre normal.
        self._state_stack = QStackedWidget(self)
        self._state_stack.addWidget(self._form_card)  # idx 0 — normal
        self._state_stack.addWidget(self._progress_card)  # idx 1 — loading
        self._state_stack.addWidget(self._error_card)  # idx 2 — error

        # Layout exterior.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(16)
        outer.addWidget(self._title)
        outer.addWidget(self._subtitle)
        outer.addWidget(self._state_stack, stretch=1)
        outer.addWidget(self._footer)

        # Toast (overlay invisível por default).
        self._toast = self._build_toast()
        self._toast.setParent(self)
        self._toast.hide()

        # Atalhos por tela (Ctrl+D, Ctrl+C, Esc).
        self._register_shortcuts()

        # Default: estado normal.
        self._current_state = STATE_NORMAL

    # ------------------------------------------------------------------
    # Public API consumida pelo MainWindow / testes
    # ------------------------------------------------------------------

    def is_download_active(self) -> bool:
        return self._download_active

    def request_cancel(self) -> None:
        """Pede cancelamento (chamado por MainWindow no quit)."""
        if self._download_active:
            self._on_cancel_clicked()

    def handle_escape(self) -> bool:
        """Esc context-aware (chamado pelo MainWindow eventFilter)."""
        if self._download_active:
            self._on_cancel_clicked()
            return True
        return False

    def current_state(self) -> str:
        """Útil para testes."""
        return self._current_state

    # ------------------------------------------------------------------
    # Construção UI
    # ------------------------------------------------------------------

    def _build_form_card(self) -> QFrame:
        card = QFrame(self)
        card.setProperty("elevated", "true")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(card)
        layout.setSpacing(16)

        # SymbolPicker.
        self._symbol_picker = SymbolPicker(card)
        layout.addWidget(self._symbol_picker)

        # PeriodPicker.
        self._period_picker = PeriodPicker(card)
        layout.addWidget(self._period_picker)

        # Pasta destino.
        folder_row = QHBoxLayout()
        folder_label = QLabel(format_msg("LBL_OUTPUT_FOLDER"), card)
        folder_label.setProperty("role", "subtitle")
        layout.addWidget(folder_label)

        self._folder_edit = QLineEdit(card)
        self._folder_edit.setText(str(Path.cwd() / "data"))
        self._folder_edit.setObjectName("dataDirEdit")
        folder_row.addWidget(self._folder_edit, stretch=1)

        browse_btn = QPushButton("...", card)
        browse_btn.setObjectName("browseBtn")
        browse_btn.setMaximumWidth(48)
        browse_btn.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(browse_btn)

        layout.addLayout(folder_row)

        # Hint sobre estimativa (LBL_ESTIMATE_UNAVAILABLE — P9 zero alucinação).
        self._estimate_label = QLabel(format_msg("LBL_ESTIMATE_UNAVAILABLE"), card)
        self._estimate_label.setProperty("role", "muted")
        layout.addWidget(self._estimate_label)

        layout.addStretch(1)

        # Botão primário grande.
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._download_btn = QPushButton(format_msg("BTN_DOWNLOAD_PRIMARY"), card)
        self._download_btn.setProperty("variant", "primary")
        self._download_btn.setObjectName("downloadBtn")
        self._download_btn.setToolTip(format_msg("TIP_BTN_DOWNLOAD"))
        self._download_btn.clicked.connect(self._on_download_clicked)
        self._download_btn.setMinimumWidth(240)
        self._download_btn.setMinimumHeight(44)
        button_row.addWidget(self._download_btn)
        layout.addLayout(button_row)

        # Hint de não-bloqueio (visível em loading mas neutro em normal).
        self._navigation_hint = QLabel(format_msg("LBL_NAVIGATION_HINT"), card)
        self._navigation_hint.setProperty("role", "muted")
        layout.addWidget(self._navigation_hint)

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
        retry_btn.setProperty("variant", "primary")
        retry_btn.setObjectName("retryBtn")
        retry_btn.clicked.connect(self._on_retry_clicked)
        button_row.addWidget(retry_btn)
        layout.addLayout(button_row)

        return card

    def _build_toast(self) -> QFrame:
        toast = QFrame()
        toast.setProperty("role", "toast")
        toast.setProperty("variant", "success")
        toast.setObjectName("successToast")
        toast.setFixedWidth(320)

        layout = QVBoxLayout(toast)
        self._toast_text = QLabel("", toast)
        self._toast_text.setWordWrap(True)
        layout.addWidget(self._toast_text)

        link_btn = QPushButton(format_msg("BTN_VIEW_CATALOG") + " →", toast)
        link_btn.setProperty("variant", "link")
        link_btn.setObjectName("viewCatalogBtn")
        layout.addWidget(link_btn)

        return toast

    # ------------------------------------------------------------------
    # Atalhos
    # ------------------------------------------------------------------

    def _register_shortcuts(self) -> None:
        """Atalhos com escopo Widget (não global)."""
        for keyseq, handler in (
            ("Ctrl+D", self._on_download_clicked),
            ("Ctrl+C", self._on_cancel_clicked),
            (Qt.Key.Key_Escape, self._on_escape),
        ):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    def _on_escape(self) -> None:
        # MainWindow.eventFilter precede; mas se Esc bater aqui (foco direto),
        # também tratamos.
        self.handle_escape()

    # ------------------------------------------------------------------
    # Slots — botões
    # ------------------------------------------------------------------

    def _on_download_clicked(self) -> None:
        if self._download_active:
            return

        # Validação inline.
        symbol = self._symbol_picker.value()
        if not symbol:
            self._show_inline_error(format_msg("ERR_INPUT_SYMBOL_REQUIRED", field="title"))
            return
        period_err = self._period_picker.validate()
        if period_err:
            self._show_inline_error(period_err)
            return

        start, end = self._period_picker.range()
        data_dir = Path(self._folder_edit.text().strip() or "data")

        # Persiste último símbolo no cache (pós-validação).
        self._symbol_picker.save_to_cache()

        # Transição → loading.
        self._download_active = True
        self._progress_card.reset()
        self._set_state(STATE_LOADING)

        # Subtitle muda para "Baixando {symbol}".
        self._subtitle.setText(
            format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE_DOWNLOADING", symbol=symbol)
        )

        # Despacha para adapter via signal cross-thread (auto QueuedConnection).
        self._request_start.emit(symbol, "F", start, end, data_dir)

    def _on_cancel_clicked(self) -> None:
        if not self._download_active:
            return

        # Confirmação destrutiva (R17).
        title = format_msg("PMT_CANCEL_CONFIRM")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Cancelar")
        box.setText(title or "Cancelar download?")
        yes_btn = box.addButton(
            format_msg("BTN_CANCEL_CONFIRM") or "Sim, cancelar",
            QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton(
            format_msg("BTN_CONTINUE") or "Continuar baixando",
            QMessageBox.ButtonRole.RejectRole,
        )
        box.exec()

        if box.clickedButton() is not yes_btn:
            return

        # Sub-estado cancelling.
        self._progress_card.set_state("cancelling")

        # Despacha cancel para adapter via signal Queued.
        self._request_cancel.emit()

    def _on_retry_clicked(self) -> None:
        # Volta para o form para reconfigurar / tentar de novo.
        self._set_state(STATE_NORMAL)

    def _on_browse_folder(self) -> None:
        # QFileDialog DontUseNativeDialog (QT_PATTERNS §1, finding M9).
        current = self._folder_edit.text().strip() or str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de destino",
            current,
            QFileDialog.Option.DontUseNativeDialog,
        )
        if folder:
            self._folder_edit.setText(folder)

    # ------------------------------------------------------------------
    # Slots — sinais do adapter (Qt.QueuedConnection — MainThread)
    # ------------------------------------------------------------------

    def _on_progress(self, progress: object) -> None:
        # Encaminha para ProgressCard.
        self._progress_card.set_progress(progress)

    def _on_error(self, exc: object) -> None:
        self._download_active = False
        # Mensagem humanizada via humanized_message se possível.
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
        self._subtitle.setText(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"))

    def _on_cancelled(self, exc: object) -> None:
        self._download_active = False
        # Toast info "Download cancelado".
        self._show_toast(format_msg("TST_CANCEL_DONE"), variant="info", duration_ms=3000)
        self._set_state(STATE_NORMAL)
        self._subtitle.setText(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"))

    def _on_finished(self, result: object) -> None:
        self._download_active = False
        # Extrai stats com duck-typing (DownloadResult).
        symbol = getattr(result, "symbol", "") or self._symbol_picker.value()
        n_trades = int(getattr(result, "trades_count", 0) or 0)
        n_files = len(getattr(result, "partitions", ()) or ())
        toast_text = format_msg(
            "TST_DOWNLOAD_DONE",
            symbol=symbol,
            n_trades=f"{n_trades:,}".replace(",", "."),
            n_files=n_files,
        )
        self._show_toast(toast_text, variant="success", duration_ms=5000)
        self._set_state(STATE_NORMAL)
        self._subtitle.setText(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"))

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._current_state = state
        if state == STATE_LOADING:
            self._state_stack.setCurrentIndex(1)
        elif state == STATE_ERROR:
            self._state_stack.setCurrentIndex(2)
        else:
            self._state_stack.setCurrentIndex(0)
        self.state_changed.emit(state)

    def _show_inline_error(self, msg: str) -> None:
        """Validação leve antes do start — mostra como mini-toast."""
        self._show_toast(msg, variant="error", duration_ms=4000)

    # ------------------------------------------------------------------
    # Toast
    # ------------------------------------------------------------------

    def _show_toast(self, text: str, *, variant: str, duration_ms: int) -> None:
        self._toast.setProperty("variant", variant)
        # Re-aplica QSS para refletir variant.
        self._toast.style().unpolish(self._toast)
        self._toast.style().polish(self._toast)

        self._toast_text.setText(text)
        # Posiciona top-right da própria tela.
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
