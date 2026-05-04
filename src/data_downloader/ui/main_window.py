"""data_downloader.ui.main_window — QMainWindow shell (Story 3.1).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

``MainWindow`` é o frame geral do app desktop:

    - **Sidebar** (esquerda) — nav: Download / Catálogo / Settings.
    - **Main area** (central) — ``QStackedWidget`` com a tela ativa.
    - **Status bar** (inferior) — DLL status, pasta atual, versão app.

Atalhos globais (registrados via ``QShortcut`` ``Qt.ApplicationShortcut``):

    - ``Ctrl+D`` — DownloadScreen
    - ``Ctrl+B`` — CatalogScreen
    - ``Ctrl+,`` — SettingsScreen
    - ``Ctrl+Q`` — Sair (com confirm se download em progresso)

``Esc`` é context-aware via ``eventFilter`` despachando para handler do
contexto ativo (ver THEME.md §6 — ordem de prioridade): primeiro fecha modal
aberto, senão delega para a tela ativa.

Referências:
    - docs/ux/WIREFRAMES.md (MainWindow frame geral)
    - docs/ux/THEME.md §6 (atalhos teclado)
    - docs/ux/QT_PATTERNS.md §6 (atalhos Qt)
    - docs/ux/MICROCOPY_CATALOG.md §17b.4 (LBL_NAV_*, LBL_STATUSBAR_*)
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from data_downloader.ui.microcopy_loader import format_msg

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

__all__ = ["MainWindow"]


# Identificadores estáveis das telas no QStackedWidget.
SCREEN_DOWNLOAD = "download"
SCREEN_CATALOG = "catalog"
SCREEN_SETTINGS = "settings"


class MainWindow(QMainWindow):
    """Frame geral do app — sidebar + stacked area + status bar.

    Public API consumida apenas internamente (telas filhas), conforme
    convenção QT_PATTERNS §2 (UI nunca cruza fronteira backend direto).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle("data-downloader")
        self.resize(1024, 700)
        self.setMinimumSize(960, 640)

        # Layout: sidebar (esq) + stack central + status bar (inferior).
        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self._sidebar = self._build_sidebar()
        central_layout.addWidget(self._sidebar)

        self._stack = QStackedWidget(self)
        central_layout.addWidget(self._stack, stretch=1)

        self.setCentralWidget(central)

        # Telas — instanciadas aqui (uma por tipo). Story 3.1 fornece
        # apenas DownloadScreen funcional; demais ficam como placeholder
        # textual visível para preservar nav.
        self._screens: dict[str, QWidget] = {}
        self._screen_indices: dict[str, int] = {}
        self._build_screens()

        # Status bar.
        self._build_status_bar()

        # Atalhos globais.
        self._register_global_shortcuts()

        # Default = DownloadScreen.
        self.set_active_screen(SCREEN_DOWNLOAD)

    # ------------------------------------------------------------------
    # Construção de UI
    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        """Constrói a sidebar esquerda com 3 botões de nav."""
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 16, 0, 16)
        layout.setSpacing(0)

        self._nav_buttons: dict[str, QPushButton] = {}
        for screen_id, label_id, shortcut_text in (
            (SCREEN_DOWNLOAD, "LBL_NAV_DOWNLOAD", "Ctrl+D"),
            (SCREEN_CATALOG, "LBL_NAV_CATALOG", "Ctrl+B"),
            (SCREEN_SETTINGS, "LBL_NAV_SETTINGS", "Ctrl+,"),
        ):
            label = format_msg(label_id)
            btn = QPushButton(f"  {label}\n  {shortcut_text}", sidebar)
            btn.setProperty("role", "nav-item")
            btn.setProperty("active", False)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, sid=screen_id: self.set_active_screen(sid))
            layout.addWidget(btn)
            self._nav_buttons[screen_id] = btn

        layout.addStretch(1)
        return sidebar

    def _build_screens(self) -> None:
        """Instancia as telas e popula o ``QStackedWidget``."""
        # Story 3.1 — DownloadScreen funcional.
        from data_downloader.ui.screens.download_screen import DownloadScreen

        download_screen = DownloadScreen(self)
        self._add_screen(SCREEN_DOWNLOAD, download_screen)

        # Catálogo / Settings — placeholders mínimos com label central. Não
        # bloqueiam nav; serão substituídos em Stories 3.3 e 3.4.
        for screen_id, label_id in (
            (SCREEN_CATALOG, "LBL_CATALOG_SCREEN_TITLE"),
            (SCREEN_SETTINGS, "LBL_SETTINGS_SCREEN_TITLE"),
        ):
            placeholder = QWidget(self)
            ph_layout = QVBoxLayout(placeholder)
            title = QLabel(format_msg(label_id), placeholder)
            title.setProperty("role", "title")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph_layout.addStretch(1)
            ph_layout.addWidget(title)
            hint = QLabel("(em construção — Story 3.x)", placeholder)
            hint.setProperty("role", "muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph_layout.addWidget(hint)
            ph_layout.addStretch(1)
            self._add_screen(screen_id, placeholder)

    def _add_screen(self, screen_id: str, widget: QWidget) -> None:
        idx = self._stack.addWidget(widget)
        self._screens[screen_id] = widget
        self._screen_indices[screen_id] = idx

    def _build_status_bar(self) -> None:
        """StatusBar com DLL status (esquerda), pasta (centro), versão (direita)."""
        bar = QStatusBar(self)
        self.setStatusBar(bar)

        # DLL status placeholder (Story 3.1 não conecta DLL; setado por
        # Story 3.4 / SettingsScreen quando disponível).
        self._dll_status_label = QLabel(format_msg("LBL_STATUSBAR_DLL_DISCONNECTED"), self)
        self._dll_status_label.setProperty("status", "disconnected")
        bar.addWidget(self._dll_status_label)

        bar.addWidget(QLabel("  •  ", self))

        # Versão app (direita) — usa __api_version__ do public_api como
        # proxy enquanto não há __version__ exposto pela UI.
        try:
            from data_downloader.public_api import __api_version__ as app_version
        except ImportError:
            app_version = "0.1.0"
        version_label = QLabel(
            format_msg("LBL_STATUSBAR_APP_VERSION", version=app_version),
            self,
        )
        version_label.setProperty("role", "muted")
        bar.addPermanentWidget(version_label)

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------

    def set_active_screen(self, screen_id: str) -> None:
        """Troca a tela ativa no stack + atualiza visual da sidebar."""
        if screen_id not in self._screen_indices:
            return
        self._stack.setCurrentIndex(self._screen_indices[screen_id])
        for sid, btn in self._nav_buttons.items():
            active = sid == screen_id
            btn.setChecked(active)
            btn.setProperty("active", active)
            # Forçar re-aplicar QSS após property change.
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def active_screen_id(self) -> str:
        """Retorna o ID da tela ativa atualmente."""
        idx = self._stack.currentIndex()
        for sid, sidx in self._screen_indices.items():
            if sidx == idx:
                return sid
        return SCREEN_DOWNLOAD

    # ------------------------------------------------------------------
    # Atalhos globais
    # ------------------------------------------------------------------

    def _register_global_shortcuts(self) -> None:
        """Registra atalhos globais THEME.md §6 com escopo Application."""
        self._shortcuts: list[QShortcut] = []
        for keyseq, screen_id in (
            ("Ctrl+D", SCREEN_DOWNLOAD),
            ("Ctrl+B", SCREEN_CATALOG),
            ("Ctrl+,", SCREEN_SETTINGS),
        ):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(lambda sid=screen_id: self.set_active_screen(sid))
            self._shortcuts.append(sc)

        # Ctrl+Q — sair (com confirm se download em progresso).
        quit_sc = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_sc.activated.connect(self._on_quit_requested)
        self._shortcuts.append(quit_sc)

        # File-level menu actions também — facilita tooltip via QAction (V2).
        # Não criamos QMenuBar nesta story para manter footprint pequeno.
        _ = QAction  # explicit import retained for possible future menubar

    def _on_quit_requested(self) -> None:
        """Confirma com usuário se download em progresso, senão fecha."""
        download_active = False
        download_screen = self._screens.get(SCREEN_DOWNLOAD)
        if download_screen is not None and hasattr(download_screen, "is_download_active"):
            try:
                download_active = bool(download_screen.is_download_active())
            except Exception:
                download_active = False

        if not download_active:
            self.close()
            return

        # Microcopy via catalog (R17).
        title = format_msg("MOD_QUIT_DURING_DOWNLOAD_TITLE")
        body = format_msg("MOD_QUIT_DURING_DOWNLOAD_BODY")
        confirm = format_msg("BTN_QUIT_AND_CANCEL")
        keep = format_msg("BTN_KEEP_DOWNLOADING")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title or "Sair")
        box.setText(title or "Sair?")
        box.setInformativeText(body or "")
        yes_btn = box.addButton(confirm or "Sim", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(keep or "Continuar", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        if box.clickedButton() is yes_btn:
            # Pede cancel à tela e fecha mesmo assim — drain acontece em
            # background (worker thread daemon).
            if hasattr(download_screen, "request_cancel"):
                with contextlib.suppress(Exception):
                    download_screen.request_cancel()  # type: ignore[attr-defined]
            self.close()

    # ------------------------------------------------------------------
    # Esc context-aware (THEME §6 — ordem de prioridade)
    # ------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Despacha Esc para handler do contexto ativo.

        Ordem de prioridade (THEME §6):

        1. Modal aberto → fecha modal (default Qt — não interceptamos).
        2. Tela ativa = DownloadScreen e download ativo → cancel.
        3. Outra tela → no-op.
        """
        if event.type() == QEvent.Type.KeyPress:
            key_event = event  # type: QKeyEvent  # noqa: F841 (typing aid)
            if hasattr(event, "key") and event.key() == Qt.Key.Key_Escape:  # type: ignore[attr-defined]
                screen = self._screens.get(self.active_screen_id())
                if screen is not None and hasattr(screen, "handle_escape"):
                    handled = bool(screen.handle_escape())  # type: ignore[attr-defined]
                    if handled:
                        return True
        return super().eventFilter(watched, event)
