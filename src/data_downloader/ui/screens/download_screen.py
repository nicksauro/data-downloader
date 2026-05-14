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

import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
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


def _default_data_dir() -> Path:
    """Pasta de dados default — delegada a ``bundle_paths.default_data_dir``.

    v1.3.0 Bug 2 fix: a fonte canônica está em ``bundle_paths.default_data_dir``
    (single source of truth para UI inteira — DownloadScreen, CatalogScreen,
    SettingsScreen). Esta função é mantida como wrapper local com fallback
    defensivo para preservar back-compat de testes que mockam este símbolo.
    """
    try:
        from data_downloader._internal.bundle_paths import default_data_dir

        return default_data_dir()
    except Exception:
        return Path.cwd() / "data"


class DownloadScreen(QWidget):
    """Tela de download — 5 estados via QStackedWidget interno.

    Sinais públicos (úteis para testes):
        state_changed(str): emitido quando ``_set_state`` muda o estado.
    """

    state_changed = Signal(str)
    # Wave 3 v1.1.0 (Uma): emitido quando usuário clica "Abrir Settings"
    # no error card de DLL/credentials. MainWindow conecta a
    # ``set_active_screen(SCREEN_SETTINGS)`` — discoverability fix.
    open_settings_requested = Signal()
    # Hotfix v1.1.0 2026-05-07 (Felix+Uma — Pichau directive "não aparece
    # quando baixou, ta feio"): STATE_SUCCESS card persistente com CTA
    # "Ver no Catálogo" emite este sinal carregando o symbol baixado para
    # MainWindow trocar a tela ativa (e opcionalmente filtrar pelo symbol).
    open_catalog_requested = Signal(str)

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

        # Hotfix v1.1.0 2026-05-07 (Felix+Uma): cache do último download
        # bem-sucedido para alimentar o STATE_SUCCESS card (path → "Abrir
        # Pasta", symbol → "Ver no Catálogo").
        self._last_success_path: Path | None = None
        self._last_success_symbol: str = ""

        # Header.
        self._title = QLabel(format_msg("LBL_DOWNLOAD_SCREEN_TITLE"), self)
        self._title.setProperty("role", "title")

        self._subtitle = QLabel(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"), self)
        self._subtitle.setProperty("role", "subtitle")

        # Form (state=normal e state=success compartilham layout).
        self._form_card = self._build_form_card()

        # Card error.
        self._error_card = self._build_error_card()

        # Hotfix v1.1.0 2026-05-07 (Felix+Uma): success card persistente
        # (substitui a antiga UX de toast 5s + tela vazia).
        self._success_card = self._build_success_card()

        # ProgressCard (state=loading).
        self._progress_card = ProgressCard(self)
        self._progress_card.cancel_requested.connect(self._on_cancel_clicked)

        # Story v1.0.7 fix (Pichau live test 2026-05-06): conecta o
        # :class:`QtLogBridge` global (instalado em ``ui/app.py::main``)
        # ao log view do ProgressCard. Cross-thread safe via
        # ``QueuedConnection`` — worker threads (download, orchestrator)
        # emitem records que aparecem no UI panel. Best-effort: se o
        # handler não foi instalado (e.g. testes sem app.main), fallback
        # silencioso preserva comportamento histórico.
        try:
            from data_downloader.ui.qt_log_handler import install_qt_log_handler

            bridge = install_qt_log_handler(level="INFO")
            bridge.message_logged.connect(
                self._progress_card.append_log_line,
                Qt.ConnectionType.QueuedConnection,
            )
        except Exception:
            pass

        # Footer.
        self._footer = QLabel(format_msg("LBL_FOOTER_SHORTCUTS"), self)
        self._footer.setProperty("role", "muted")

        # v1.2.0 Wave 1D (Uma) — banner não-modal "Retomar download interrompido".
        # Hidden até :meth:`_check_for_interrupted_download` decidir.
        self._resume_banner = self._build_resume_banner()
        self._resume_job_id: str | None = None
        self._resume_job_data_dir: Path | None = None

        # Stack interno para os 3 estados visíveis (normal/loading/error).
        # Success é overlay (toast) sobre normal.
        self._state_stack = QStackedWidget(self)
        self._state_stack.addWidget(self._form_card)  # idx 0 — normal
        self._state_stack.addWidget(self._progress_card)  # idx 1 — loading
        self._state_stack.addWidget(self._error_card)  # idx 2 — error
        self._state_stack.addWidget(self._success_card)  # idx 3 — success (hotfix v1.1.0)

        # Layout exterior.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(16)
        outer.addWidget(self._title)
        outer.addWidget(self._subtitle)
        outer.addWidget(self._resume_banner)
        outer.addWidget(self._state_stack, stretch=1)
        outer.addWidget(self._footer)

        # Toast (overlay invisível por default).
        self._toast = self._build_toast()
        self._toast.setParent(self)
        self._toast.hide()
        # Timer parented em self que esconde o toast (não órfão — evita
        # ``QTimer.singleShot`` disparando após destruição da screen).
        self._toast_hide_timer = QTimer(self)
        self._toast_hide_timer.setSingleShot(True)
        self._toast_hide_timer.timeout.connect(self._toast.hide)

        # Atalhos por tela (Ctrl+D, Ctrl+C, Esc).
        self._register_shortcuts()

        # Default: estado normal.
        self._current_state = STATE_NORMAL

        # v1.2.0 Wave 1D — ao abrir a tela, checa o catalog por jobs
        # interrompidos (status in_progress/partial) e oferece retomar.
        # Best-effort: qualquer falha (catalog ausente, schema antigo) é
        # silenciada — banner simplesmente não aparece.
        with contextlib.suppress(Exception):
            self._check_for_interrupted_download()

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
        # v1.2.0 Wave 1D (Uma): default não-relativo ao cwd de lançamento —
        # usa ``bundle_paths.user_data_dir()`` (mesma raiz do .env / cache),
        # garantindo que o .exe instalado grave num local estável.
        self._folder_edit.setText(str(_default_data_dir()))
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
        # Wave 3 v1.1.0 (Uma): deep-link "Abrir Settings" para erros de
        # DLL/credenciais — discoverability gap CONCERNS BIG COUNCIL. Hidden
        # por default; ``_on_error`` decide quando mostrar baseado em
        # humanized_message ID.
        self._open_settings_btn = QPushButton("Abrir Settings", card)
        self._open_settings_btn.setObjectName("openSettingsBtn")
        self._open_settings_btn.setProperty("variant", "secondary")
        self._open_settings_btn.setToolTip("Abre Configurações para revisar DLL path / credenciais")
        self._open_settings_btn.clicked.connect(self.open_settings_requested.emit)
        self._open_settings_btn.setVisible(False)
        button_row.addWidget(self._open_settings_btn)

        retry_btn = QPushButton(format_msg("BTN_RETRY"), card)
        retry_btn.setProperty("variant", "primary")
        retry_btn.setObjectName("retryBtn")
        retry_btn.clicked.connect(self._on_retry_clicked)
        button_row.addWidget(retry_btn)
        layout.addLayout(button_row)

        return card

    def _build_success_card(self) -> QFrame:
        """Card persistente após download — Hotfix v1.1.0 (Felix+Uma).

        Pichau live test 2026-05-07: a UX antiga (toast 5s → tela vazia
        sem feedback do que foi baixado nem CTA pra abrir) foi reportada
        como "não aparece quando baixou, ta feio". Este card substitui
        o estado pós-download: header verde + métricas (símbolo / trades /
        arquivos / pasta) + 3 CTAs (Abrir Pasta / Ver no Catálogo /
        Novo Download).
        """
        card = QFrame(self)
        card.setObjectName("downloadSuccessCard")
        card.setProperty("role", "success-card")

        layout = QVBoxLayout(card)
        layout.setSpacing(16)
        layout.setContentsMargins(40, 40, 40, 40)

        # Header: icon ✓ + título.
        header = QHBoxLayout()
        icon_label = QLabel("✓", card)
        icon_label.setObjectName("successIcon")
        icon_label.setStyleSheet(
            "color:#3FCB6F; font-size:48px; font-weight:700; background:transparent;"
        )
        title = QLabel("Download concluído", card)
        title.setObjectName("successTitle")
        title.setStyleSheet(
            "font-size:20px; font-weight:600; color:#E8E8EA; background:transparent;"
        )
        header.addWidget(icon_label)
        header.addSpacing(12)
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        # Métricas (grid label ↔ valor).
        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(6)

        self._success_symbol_lbl = QLabel("—", card)
        self._success_symbol_lbl.setObjectName("successSymbolValue")
        self._success_trades_lbl = QLabel("—", card)
        self._success_trades_lbl.setObjectName("successTradesValue")
        self._success_files_lbl = QLabel("—", card)
        self._success_files_lbl.setObjectName("successFilesValue")
        self._success_duration_lbl = QLabel("—", card)
        self._success_duration_lbl.setObjectName("successDurationValue")
        self._success_path_lbl = QLabel("—", card)
        self._success_path_lbl.setObjectName("successPathValue")
        self._success_path_lbl.setStyleSheet(
            "font-family:'Cascadia Code','Consolas',monospace; color:#A8A8AC;"
        )
        self._success_path_lbl.setWordWrap(True)
        self._success_path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        rows = (
            ("Símbolo:", self._success_symbol_lbl),
            ("Trades:", self._success_trades_lbl),
            ("Arquivos:", self._success_files_lbl),
            ("Duração:", self._success_duration_lbl),
            ("Pasta:", self._success_path_lbl),
        )
        for row_idx, (label_text, value_widget) in enumerate(rows):
            label = QLabel(label_text, card)
            label.setProperty("role", "muted")
            label.setStyleSheet("background:transparent;")
            metrics.addWidget(label, row_idx, 0, Qt.AlignmentFlag.AlignTop)
            metrics.addWidget(value_widget, row_idx, 1)
        metrics.setColumnStretch(1, 1)
        layout.addLayout(metrics)

        layout.addStretch(1)

        # Ações.
        actions = QHBoxLayout()
        self._success_open_folder_btn = QPushButton("Abrir Pasta", card)
        self._success_open_folder_btn.setObjectName("successOpenFolderBtn")
        self._success_open_folder_btn.setProperty("variant", "primary")
        self._success_open_folder_btn.setDefault(True)
        self._success_open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._success_open_folder_btn.clicked.connect(self._on_open_folder_clicked)

        self._success_view_catalog_btn = QPushButton(format_msg("BTN_VIEW_CATALOG"), card)
        self._success_view_catalog_btn.setObjectName("successViewCatalogBtn")
        self._success_view_catalog_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._success_view_catalog_btn.clicked.connect(self._on_view_catalog_clicked)

        self._success_new_download_btn = QPushButton("Novo Download", card)
        self._success_new_download_btn.setObjectName("successNewDownloadBtn")
        self._success_new_download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._success_new_download_btn.clicked.connect(self._on_new_download_clicked)

        actions.addWidget(self._success_open_folder_btn)
        actions.addWidget(self._success_view_catalog_btn)
        actions.addStretch(1)
        actions.addWidget(self._success_new_download_btn)
        layout.addLayout(actions)

        return card

    def _build_resume_banner(self) -> QFrame:
        """Banner não-modal "Retomar download interrompido?" (v1.2.0 Wave 1D).

        Aparece ao abrir a tela se houver job ``in_progress``/``partial`` no
        catalog. Três botões: [Retomar] / [Começar do zero] / [Descartar].
        Hidden por default; :meth:`_check_for_interrupted_download` decide.
        """
        banner = QFrame(self)
        banner.setObjectName("resumeBanner")
        banner.setProperty("role", "warning-card")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        icon = QLabel("↻", banner)
        icon.setStyleSheet("font-size: 14pt; color: #F2C94C;")
        layout.addWidget(icon)

        self._resume_banner_label = QLabel("", banner)
        self._resume_banner_label.setObjectName("resumeBannerLabel")
        self._resume_banner_label.setWordWrap(True)
        layout.addWidget(self._resume_banner_label, stretch=1)

        resume_btn = QPushButton("Retomar", banner)
        resume_btn.setObjectName("resumeBtn")
        resume_btn.setProperty("variant", "primary")
        resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        resume_btn.clicked.connect(self._on_resume_clicked)
        layout.addWidget(resume_btn)

        restart_btn = QPushButton("Começar do zero", banner)
        restart_btn.setObjectName("resumeRestartBtn")
        restart_btn.setProperty("variant", "secondary")
        restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restart_btn.clicked.connect(self._on_resume_restart_clicked)
        layout.addWidget(restart_btn)

        discard_btn = QPushButton("Descartar", banner)
        discard_btn.setObjectName("resumeDiscardBtn")
        discard_btn.setProperty("variant", "link")
        discard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discard_btn.clicked.connect(self._on_resume_discard_clicked)
        layout.addWidget(discard_btn)

        banner.setVisible(False)
        return banner

    def _check_for_interrupted_download(self) -> None:
        """Consulta o catalog por jobs interrompidos e mostra o banner.

        Usa ``Catalog.list_jobs(statuses=("in_progress","partial"))``. Se
        existir, popula o banner com o job mais recente. Best-effort.
        """
        data_dir = _default_data_dir()
        job = None
        plan = None
        try:
            from data_downloader.storage.catalog import Catalog

            db_path = data_dir / "_internal" / "catalog.db"
            if not db_path.exists():
                return
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
        except Exception:
            return
        if job is None:
            return
        self._resume_job_id = getattr(job, "job_id", None)
        self._resume_job_data_dir = data_dir
        symbol = getattr(job, "symbol", "?") or "?"
        # done/total em chunks — usa partições completas vs chunks pendentes.
        if plan is not None:
            done = len(getattr(plan, "completed_partitions", ()) or ())
            pending = len(getattr(plan, "pending_chunks", ()) or ())
            total = done + pending
            where = f"parou em {done}/{total} chunks" if total else "parcial em disco"
        else:
            where = "parcial em disco"
        self._resume_banner_label.setText(f"Retomar download de {symbol}? ({where})")
        self._resume_banner.setVisible(True)

    def _hide_resume_banner(self) -> None:
        self._resume_banner.setVisible(False)

    @Slot()
    def _on_resume_clicked(self) -> None:
        """Retoma o download interrompido via ``resume_job_id`` (Wave 1B — Dex-B)."""
        if self._download_active:
            return
        job_id = self._resume_job_id
        self._hide_resume_banner()
        if not job_id:
            return
        symbol = self._symbol_picker.value() or "?"
        start, end = self._period_picker.range()
        data_dir = self._resume_job_data_dir or _default_data_dir()
        self._download_active = True
        self._progress_card.reset()
        self._progress_card.set_data_dir(data_dir)
        self._set_state(STATE_LOADING)
        self._subtitle.setText(
            format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE_DOWNLOADING", symbol=symbol)
        )
        # Despacha start com resume_job_id (6º arg do signal/slot).
        self._request_start.emit(symbol, "F", start, end, data_dir, job_id)

    @Slot()
    def _on_resume_restart_clicked(self) -> None:
        """Esconde o banner — usuário prefere reconfigurar e começar do zero."""
        self._resume_job_id = None
        self._hide_resume_banner()
        self._set_state(STATE_NORMAL)

    @Slot()
    def _on_resume_discard_clicked(self) -> None:
        """Esconde o banner sem ação (descarta a sugestão)."""
        self._resume_job_id = None
        self._hide_resume_banner()

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
        self._hide_resume_banner()
        self._progress_card.reset()
        # v1.2.0 Wave 1D — passa data_dir ao card para o botão "Abrir Pasta"
        # ficar disponível durante o download.
        self._progress_card.set_data_dir(data_dir)
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

    # Hotfix v1.1.0 2026-05-07 (Felix+Uma) — handlers do success card.
    @Slot()
    def _on_open_folder_clicked(self) -> None:
        """Abre a pasta do download no explorer nativo (best-effort)."""
        if self._last_success_path is None:
            return
        # Defensive — UI nunca cai por falha de IO/shell (suppress).
        with contextlib.suppress(Exception):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_success_path)))

    @Slot()
    def _on_view_catalog_clicked(self) -> None:
        """Pede ao MainWindow para navegar ao CatalogScreen.

        Se algum dia ``CatalogScreen`` ganhar ``set_filter_symbol(symbol)``,
        o slot da MainWindow consome o symbol carregado pelo sinal.
        Por enquanto basta navegar (TODO follow-up: filtro automático).
        """
        self.open_catalog_requested.emit(self._last_success_symbol or "")

    @Slot()
    def _on_new_download_clicked(self) -> None:
        """Volta ao form para iniciar outro download."""
        self._set_state(STATE_NORMAL)
        self._subtitle.setText(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"))

    def _on_browse_folder(self) -> None:
        # Story v1.0.5 fix (Pichau live test 2026-05-06): nativo Win32 em
        # frozen (cores corretas, integração com shell), DontUseNativeDialog
        # em dev/tests (compatível com mocks ``QFileDialog`` e CI sem GUI).
        current = self._folder_edit.text().strip() or str(Path.cwd())
        options: QFileDialog.Option = (
            QFileDialog.Option(0)
            if getattr(sys, "frozen", False)
            else QFileDialog.Option.DontUseNativeDialog
        )
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de destino",
            current,
            options,
        )
        if folder:
            self._folder_edit.setText(folder)

    # ------------------------------------------------------------------
    # Slots — sinais do adapter (Qt.QueuedConnection — MainThread)
    # ------------------------------------------------------------------
    #
    # Story v1.0.7 fix (Pichau live test 2026-05-06): @Slot(object) é
    # OBRIGATÓRIO em PySide6 quando a conexão é cross-thread via
    # ``Qt.QueuedConnection`` carregando um payload Python (``object``).
    # Sem o decorator, o meta-call em frozen builds (PyInstaller windowed)
    # pode falhar silenciosamente — o test rodando em dev passa porque
    # introspect resolve o slot, mas o .exe não atualiza a UI.
    # Bugs Pichau v1.0.6: "barrinha nao anda, fica sempre em 0".

    @Slot(object)
    def _on_progress(self, progress: object) -> None:
        # Encaminha para ProgressCard. Story v1.0.7: também loga via
        # logging stdlib (que vai pro QtLogHandler → log panel) para
        # confirmar que o sinal está sendo recebido em MainThread —
        # diagnóstico de runtime + visibilidade ao usuário em windowed
        # mode (Pichau bug: "nem aparece que começou a baixar nos logs").
        import logging as _logging

        _ui_log = _logging.getLogger("data_downloader.ui.download_screen")
        try:
            done = int(getattr(progress, "done", 0) or 0)
            total = int(getattr(progress, "total", 0) or 0)
            msg = str(getattr(progress, "message", "") or "")
            trades = int(getattr(progress, "trades_received", 0) or 0)
            _ui_log.info(
                "ui.progress msg=%s done=%d total=%d trades=%d",
                msg,
                done,
                total,
                trades,
            )
        except Exception:
            # Defensive — log NUNCA derruba UI.
            pass
        self._progress_card.set_progress(progress)

    @Slot(object)
    def _on_error(self, exc: object) -> None:
        self._download_active = False
        # Mensagem humanizada via humanized_message se possível.
        title = ""
        detail = str(exc)
        action = ""
        msg_id = ""
        try:
            from data_downloader.public_api.exceptions import DataDownloaderError
            from data_downloader.ui.microcopy_loader import MSG, humanize_nl_error

            if isinstance(exc, DataDownloaderError):
                msg_id = exc.humanized_message
                entry = MSG.get(msg_id)
                if entry is not None:
                    title = entry.title or ""
                    detail = entry.detail or detail
                    action = entry.action or ""

            # Hotfix v1.1.0 2026-05-08 (Felix+Aria — Pichau smoke real):
            # adapter pode encaminhar strings como
            # "ERR_DLL_MARKET_TIMEOUT: detalhes…" ou "NL_WAITING_SERVER: …"
            # vindas de ``DownloadResult.error_message``. Tenta extrair o
            # ID e fazer lookup direto. Se ID começa com ``NL_``, usa
            # ``humanize_nl_error`` para resolver via tabela específica DLL.
            if not title:
                raw = detail or ""
                head, sep, tail = raw.partition(":")
                head_id = head.strip()
                if sep and head_id:
                    if head_id.startswith("NL_"):
                        nl_entry = humanize_nl_error(head_id)
                        if nl_entry.title:
                            title = nl_entry.title or ""
                            detail = nl_entry.detail or tail.strip() or detail
                            action = nl_entry.action or ""
                            msg_id = head_id
                    else:
                        entry = MSG.get(head_id)
                        if entry is not None:
                            title = entry.title or ""
                            detail = entry.detail or tail.strip() or detail
                            action = entry.action or ""
                            msg_id = head_id
        except Exception:
            pass

        if not title:
            title = "Erro"

        self._error_title.setText(title)
        self._error_detail.setText(detail)
        self._error_action.setText(action)

        # Wave 3 v1.1.0 (Uma) — deep-link "Abrir Settings" só faz sentido
        # quando erro é de DLL ou credenciais. Heurística: msg_id começa com
        # ``ERR_DLL_`` (todos os erros do wrapper DLL) — abrange:
        # ERR_DLL_NOT_INITIALIZED, ERR_DLL_NO_LICENSE, ERR_DLL_GENERIC, etc.
        # Fallback para detail string contém "DLL" ou "credenc"
        # (case-insensitive — robusto a variantes futuras).
        is_dll_error = bool(msg_id and msg_id.startswith("ERR_DLL_"))
        if not is_dll_error:
            haystack = (detail or "").lower()
            is_dll_error = "dll" in haystack or "credenc" in haystack
        self._open_settings_btn.setVisible(is_dll_error)

        self._set_state(STATE_ERROR)
        self._subtitle.setText(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"))

    @Slot(object)
    def _on_cancelled(self, exc: object) -> None:
        self._download_active = False
        # Toast info "Download cancelado".
        self._show_toast(format_msg("TST_CANCEL_DONE"), variant="info", duration_ms=3000)
        self._set_state(STATE_NORMAL)
        self._subtitle.setText(format_msg("LBL_DOWNLOAD_SCREEN_SUBTITLE"))

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        self._download_active = False

        # Hotfix v1.1.0 2026-05-08 (Felix+Aria — Pichau smoke real):
        # defesa em profundidade contra "success card pra falha". O adapter
        # já roteia ``status == 'failed'`` via signal ``error``; mesmo
        # assim, se algum caminho futuro emitir ``finished`` com result
        # vazio (0 trades + 0 partitions) sem indicar erro explícito,
        # tratamos como erro silenciado upstream. ``status`` "completed"
        # com 0 trades e 0 partitions é semanticamente "no_trades" — sem
        # estado dedicado por agora, encaminhamos para STATE_ERROR com
        # microcopy ``ERR_DOWNLOAD_EMPTY`` para que o usuário não veja
        # "Download concluído 0 trades" como vitória.
        status = str(getattr(result, "status", "completed") or "completed")
        n_trades_probe = int(getattr(result, "trades_count", 0) or 0)
        partitions_probe = tuple(getattr(result, "partitions", ()) or ())
        if status == "failed":
            error_message = (
                getattr(result, "error_message", None) or "ERR_GENERIC: erro desconhecido"
            )
            self._on_error(error_message)
            return
        if status not in ("cache_hit",) and n_trades_probe == 0 and not partitions_probe:
            import logging as _logging

            _logging.getLogger("data_downloader.ui.download_screen").warning(
                "on_finished_zero_state_treated_as_error status=%s result=%s",
                status,
                result,
            )
            self._on_error("ERR_DOWNLOAD_EMPTY: download retornou vazio sem erro")
            return

        # Extrai stats com duck-typing (DownloadResult — ver
        # ``public_api.handle.DownloadResult``: ``partitions`` é
        # ``tuple[Path, ...]`` de arquivos parquet escritos).
        symbol = getattr(result, "symbol", "") or self._symbol_picker.value()
        n_trades = n_trades_probe
        partitions = partitions_probe
        n_files = len(partitions)
        duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)

        # Resolve a pasta a abrir: pai do primeiro parquet (que é
        # ``data/history/{SYMBOL}/year=YYYY/month=MM/...parquet``).
        # Subir um nível (year=YYYY/month=MM) é o mais útil pro usuário —
        # mostra os arquivos do mês baixado direto.
        target_path: Path | None = None
        if partitions:
            try:
                first = partitions[0]
                target_path = Path(first).parent if first else None
            except Exception:
                target_path = None
        if target_path is None:
            # Fallback: pasta data_dir do form (pode existir mesmo sem
            # parquets — ex.: cache_hit sem partitions novas).
            try:
                target_path = Path(self._folder_edit.text().strip() or "data").resolve()
            except Exception:
                target_path = Path("data")

        self._last_success_symbol = symbol or ""
        self._last_success_path = target_path

        # Atualiza labels do card.
        self._success_symbol_lbl.setText(symbol or "—")
        # Formato pt-BR: "1.574.806 trades".
        self._success_trades_lbl.setText(f"{n_trades:,}".replace(",", ".") + " trades")
        files_label = (
            f"{n_files} arquivo parquet" if n_files == 1 else f"{n_files} arquivos parquet"
        )
        self._success_files_lbl.setText(files_label)
        # Duração formatada (ex.: "12.3s" ou "1m 24s").
        if duration >= 60.0:
            mins = int(duration // 60)
            secs = int(duration % 60)
            self._success_duration_lbl.setText(f"{mins}m {secs:02d}s")
        else:
            self._success_duration_lbl.setText(f"{duration:.1f}s")
        self._success_path_lbl.setText(str(target_path))

        # Toast curto (3s) — feedback rápido enquanto o card persiste.
        toast_text = format_msg(
            "TST_DOWNLOAD_DONE",
            symbol=symbol,
            n_trades=f"{n_trades:,}".replace(",", "."),
            n_files=n_files,
        )
        self._show_toast(toast_text, variant="success", duration_ms=3000)

        # Switch para success state — card persiste até ação do usuário.
        self._set_state(STATE_SUCCESS)
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
        elif state == STATE_SUCCESS:
            # Hotfix v1.1.0 2026-05-07 — success card persistente (idx 3).
            self._state_stack.setCurrentIndex(3)
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

        self._toast_hide_timer.start(duration_ms)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event: object) -> None:  # noqa: N802
        try:
            self._adapter.shutdown()
        finally:
            super().closeEvent(event)  # type: ignore[arg-type]
