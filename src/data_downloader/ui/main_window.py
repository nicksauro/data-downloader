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

from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
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
from data_downloader.ui.widgets.cheat_sheet_dialog import CheatSheetDialog

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

        # v1.3.0 Wave 2D (Uma): plugar o ícone do projeto na janela principal
        # (taskbar Windows + Alt-Tab + title bar). O .ico vive em
        # ``ui/assets/icon.ico`` (versionado) e é bundleado em ``_internal/
        # assets/icon.ico`` pelo PyInstaller spec (datas tuple). Resolução
        # cobre ambos os layouts via :func:`bundle_paths.asset_path`. Falha
        # silenciosa (cosmético): janela abre sem ícone custom se asset
        # ausente — mesmo padrão de ``app.py`` para o QSS.
        from data_downloader._internal.bundle_paths import asset_path

        for _rel in ("assets/icon.ico", "ui/assets/icon.ico"):
            try:
                _icon_path = asset_path(_rel)
            except FileNotFoundError:
                continue
            with contextlib.suppress(Exception):
                self.setWindowIcon(QIcon(str(_icon_path)))
            break

        # Layout: sidebar (esq) + (banner onboarding + stack) central + status
        # bar (inferior). Wave 3 v1.1.0 (Uma): banner é coluna direita acima
        # do stack — visible apenas quando credenciais ausentes (discoverability
        # gap detectado em BIG COUNCIL CONCERNS).
        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self._sidebar = self._build_sidebar()
        central_layout.addWidget(self._sidebar)

        # Coluna direita: banner (top) + stack (resto).
        right_col = QWidget(self)
        right_col_layout = QVBoxLayout(right_col)
        right_col_layout.setContentsMargins(0, 0, 0, 0)
        right_col_layout.setSpacing(0)

        self._onboarding_banner = self._build_onboarding_banner()
        right_col_layout.addWidget(self._onboarding_banner)

        self._stack = QStackedWidget(self)
        right_col_layout.addWidget(self._stack, stretch=1)

        central_layout.addWidget(right_col, stretch=1)

        self.setCentralWidget(central)

        # Telas — instanciadas aqui (uma por tipo). Story 3.1 fornece
        # apenas DownloadScreen funcional; demais ficam como placeholder
        # textual visível para preservar nav.
        self._screens: dict[str, QWidget] = {}
        self._screen_indices: dict[str, int] = {}
        self._build_screens()

        # Status bar.
        self._build_status_bar()

        # v1.3.0 Wave 4B (Uma+Felix) — storage indicator wiring. Precisa
        # rodar APÓS ``_build_status_bar`` (cria ``_storage_indicator``) E
        # APÓS ``_build_screens`` (cria settings_screen/catalog_adapter).
        self._wire_storage_indicator()

        # v1.3.0 Wave 2A (Dex) — DLL session adapter como single source of
        # truth. Antes da Wave 2A, ``settings_screen.dll_status_changed``
        # SÓ era emitido pelo ``_TestConnectionWorker`` no Test Connection
        # manual, e o download via ``get_dll()`` NÃO notificava — statusbar
        # ficava desincronizado durante o download (Bug 3 Pichau). Agora
        # o singleton ``dll.session`` emite estados para o adapter, que
        # roteia ao ``_on_dll_status_changed`` (mesmo handler usado pelo
        # Test Connection — coexistem sem conflito).
        with contextlib.suppress(Exception):
            from data_downloader.ui.adapters.dll_session_adapter import (
                get_dll_session_adapter,
            )

            self._dll_session_adapter = get_dll_session_adapter()
            self._dll_session_adapter.session_state_changed.connect(
                self._on_dll_status_changed,
                Qt.ConnectionType.QueuedConnection,
            )

        # Atalhos globais.
        self._register_global_shortcuts()

        # Story 4.31 AC3: ativa o event filter context-aware do Esc
        # (override de :meth:`eventFilter` mais abaixo). Sem este install,
        # o ``eventFilter`` nunca recebia eventos e o Esc só fechava
        # modais nativos (default Qt). Instalado na QApplication para
        # capturar key events de qualquer widget filho (sidebar, screens).
        from PySide6.QtWidgets import QApplication

        _app_instance = QApplication.instance()
        if _app_instance is not None:
            _app_instance.installEventFilter(self)

        # Default = DownloadScreen.
        self.set_active_screen(SCREEN_DOWNLOAD)

        # Wave 3 v1.1.0 (Uma): banner onboarding visível se credenciais missing.
        # Chamada explícita após screens prontas — evita janela de visibilidade
        # incorreta durante init (banner default hidden até esta linha decidir).
        self._refresh_onboarding_banner()

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

    def _build_onboarding_banner(self) -> QFrame:
        """Banner amarelo no topo — visível apenas se credenciais missing.

        Wave 3 v1.1.0 (Uma — diretiva Pichau): primeiro launch sem ``.env``
        deixava DownloadScreen utilizável mas Test Connection sempre falhava
        sem feedback óbvio do que faltava configurar. Banner deep-linka para
        Settings com microcopy direta + CTA grande.

        Visibility é checada em :meth:`_refresh_onboarding_banner` (chamado
        em init + após saves no SettingsScreen via signal handler).
        """
        banner = QFrame(self)
        banner.setObjectName("onboardingBanner")
        # v1.2.0 Wave 1D (Uma): migrado de cores fora da palette
        # (#FFF4CE/#DDB100/#6B4F00/#B07900) para o ``role="warning-card"``
        # canônico (rgba do warning.yellow #F2C94C — ver style.qss §11) +
        # text.primary nos labels. Defense-in-depth: estilo inline mínimo
        # usando apenas tokens autorizados, caso o QSS não carregue.
        banner.setProperty("role", "warning-card")
        banner.setStyleSheet(
            "QFrame#onboardingBanner {"
            "  background-color: rgba(242, 201, 76, 0.08);"
            "  border-bottom: 1px solid #F2C94C;"
            "  padding: 8px 12px;"
            "}"
            "QFrame#onboardingBanner QLabel { color: #E8E8EA; }"
        )

        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        icon_label = QLabel("⚠", banner)
        icon_label.setStyleSheet("font-size: 14pt; color: #F2C94C;")
        layout.addWidget(icon_label)

        msg_label = QLabel(
            "Configure suas credenciais ProfitDLL para começar a baixar dados.",
            banner,
        )
        msg_label.setObjectName("onboardingBannerLabel")
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label, stretch=1)

        configure_btn = QPushButton("Configurar Credenciais", banner)
        configure_btn.setObjectName("onboardingConfigureBtn")
        configure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        configure_btn.setMinimumSize(180, 32)
        configure_btn.clicked.connect(lambda: self.set_active_screen(SCREEN_SETTINGS))
        layout.addWidget(configure_btn)

        # Inicialmente oculto; ``_refresh_onboarding_banner`` decide.
        banner.setVisible(False)
        return banner

    def _credentials_missing(self) -> bool:
        """Retorna True se credenciais essenciais não estão configuradas.

        Critério: qualquer um de ``PROFITDLL_KEY``/``PROFITDLL_USER``/
        ``PROFITDLL_PASS`` ausente ou vazio em ``os.environ``.

        Não checa file ``~/.data-downloader/.env`` diretamente porque o
        bootstrap_env já o carregou para ``os.environ`` antes da MainWindow
        instanciar (cli.py / app.py — load order documentado).
        """
        import os

        required = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
        return not all(os.environ.get(var, "").strip() for var in required)

    def _refresh_onboarding_banner(self) -> None:
        """Sincroniza visibilidade do banner com estado das credenciais."""
        if hasattr(self, "_onboarding_banner"):
            self._onboarding_banner.setVisible(self._credentials_missing())

    @Slot()
    def _show_cheat_sheet(self) -> None:
        """Abre :class:`CheatSheetDialog` modal — trigger ``Ctrl+/``."""
        dlg = CheatSheetDialog(self)
        # Guarda referência para tests (qtbot evita garbage collection).
        self._last_cheat_sheet_dialog = dlg
        dlg.exec()

    def _build_screens(self) -> None:
        """Instancia as telas e popula o ``QStackedWidget``.

        Story 3.1 (Done) — DownloadScreen funcional.
        Story 3.2 (esta) — CatalogScreen + SettingsScreen funcionais.
        """
        from data_downloader.ui.screens.catalog_screen import CatalogScreen
        from data_downloader.ui.screens.download_screen import DownloadScreen
        from data_downloader.ui.screens.settings_screen import SettingsScreen

        download_screen = DownloadScreen(self)
        self._add_screen(SCREEN_DOWNLOAD, download_screen)

        # Bug 2 fix (v1.3.0): passar `data_dir` explícito alinhado com DownloadScreen
        # e SettingsScreen — antes CatalogScreen caía em `Path.cwd()/data` (ex.:
        # `System32\data` quando o .exe é lançado pelo atalho do Setup) e ficava
        # vazio mesmo com downloads concluídos. `default_data_dir()` é o single
        # source of truth em `bundle_paths`. `set_data_dir` (já wireado via
        # `settings.data_dir_changed`) continua atualizando em runtime se mudar.
        from data_downloader._internal.bundle_paths import default_data_dir

        catalog_screen = CatalogScreen(data_dir=default_data_dir(), parent=self)
        self._add_screen(SCREEN_CATALOG, catalog_screen)

        settings_screen = SettingsScreen(self)
        self._add_screen(SCREEN_SETTINGS, settings_screen)

        # Cross-screen wiring — quando Settings muda data_dir, Catalog re-carrega.
        with contextlib.suppress(Exception):
            settings_screen.data_dir_changed.connect(catalog_screen.set_data_dir)
        # StatusBar reflete DLL status quando Settings testa conexão.
        with contextlib.suppress(Exception):
            settings_screen.dll_status_changed.connect(self._on_dll_status_changed)
        # Wave 3 v1.1.0 (Uma): após Save em SettingsScreen (dll_status muda
        # de not_configured → disconnected), re-checa banner para esconder.
        with contextlib.suppress(Exception):
            settings_screen.dll_status_changed.connect(
                lambda _status, _version: self._refresh_onboarding_banner()
            )
        # Story 4.6 — empty state CTA do Catalog navega para Download.
        with contextlib.suppress(Exception):
            catalog_screen.request_navigate_to_download.connect(
                lambda: self.set_active_screen(SCREEN_DOWNLOAD)
            )
        # Wave 3 v1.1.0 (Uma): deep-link "Abrir Settings" do error card do
        # DownloadScreen quando falha for DLL/credentials.
        with contextlib.suppress(Exception):
            download_screen.open_settings_requested.connect(
                lambda: self.set_active_screen(SCREEN_SETTINGS)
            )
        # Hotfix v1.1.0 2026-05-07 (Felix+Uma — Pichau "não aparece quando
        # baixou, ta feio"): CTA "Ver no Catálogo" do success card do
        # DownloadScreen navega ao Catalog. v1.3.0 Wave 2B — agora
        # ``CatalogScreen.set_filter_symbol`` existe e é aplicado em
        # ``_on_open_catalog_for_symbol``, completando o flow proposto
        # por Uma ("Catálogo pós-download").
        with contextlib.suppress(Exception):
            download_screen.open_catalog_requested.connect(self._on_open_catalog_for_symbol)
        # v1.3.0 Wave 2B — também conecta o CTA do ProgressCard (success
        # sub-state). Por enquanto o success real vive no DownloadScreen
        # (``_success_card``); o ProgressCard ganhou o CTA como redundância
        # — Wave 2C decidirá unificação. Best-effort: se o widget não tem
        # o sinal (ex.: monkey-patch de testes), ignora silenciosamente.
        progress_card = getattr(download_screen, "_progress_card", None)
        if progress_card is not None and hasattr(progress_card, "view_catalog_requested"):
            with contextlib.suppress(Exception):
                progress_card.view_catalog_requested.connect(self._on_open_catalog_for_symbol)

    def _add_screen(self, screen_id: str, widget: QWidget) -> None:
        idx = self._stack.addWidget(widget)
        self._screens[screen_id] = widget
        self._screen_indices[screen_id] = idx

    def _build_status_bar(self) -> None:
        """StatusBar com DLL status (esquerda), métricas (centro), versão (direita).

        Story 3.3 (Wave 18) — agora consome ``MetricsAdapter`` polling
        :class:`PrometheusExporter` (opt-in via :meth:`set_metrics_exporter`).
        Quando exporter desabilitado: status bar mostra apenas DLL + versão
        (graceful degradation — Pyro audit).
        """
        from data_downloader.ui.widgets.metrics_panel import (
            MetricsAdapter,
            MetricsPanel,
        )

        bar = QStatusBar(self)
        self.setStatusBar(bar)

        # DLL status placeholder (Story 3.1 não conecta DLL; setado por
        # Story 3.4 / SettingsScreen quando disponível).
        self._dll_status_label = QLabel(format_msg("LBL_STATUSBAR_DLL_DISCONNECTED"), self)
        self._dll_status_label.setProperty("status", "disconnected")
        bar.addWidget(self._dll_status_label)

        bar.addWidget(QLabel("  •  ", self))

        # Metrics panel — compact, embed direto na status bar (Story 3.3).
        # Inicia em modo "off" — adapter só faz trabalho se exporter setado.
        self._metrics_panel = MetricsPanel(self, compact=True)
        bar.addWidget(self._metrics_panel)

        # Adapter em QThread separada — D2 COUNCIL-23 (sem parent Qt).
        # Story v1.1.0 Wave 1 (Felix-UI BIG COUNCIL B2): conexões cross-thread
        # DEVEM usar Qt.QueuedConnection explícito. Sem isso, em alguns hosts
        # PySide6 6.11+ o auto-detect falha e o slot roda na worker thread —
        # set_snapshot toca QSS/properties no MainThread e gera race silenciosa
        # (mesmo padrão do bug v1.0.7 em DownloadScreen).
        self._metrics_adapter = MetricsAdapter(owner=self)
        self._metrics_adapter.metrics_updated.connect(
            self._metrics_panel.set_snapshot,
            Qt.ConnectionType.QueuedConnection,
        )
        self._metrics_adapter.exporter_unavailable.connect(
            self._on_metrics_unavailable,
            Qt.ConnectionType.QueuedConnection,
        )
        self._metrics_adapter.start()

        # v1.3.0 Wave 4B (Uma+Felix) — Storage indicator (free/used GB).
        # Motivação Pax (BIG COUNCIL): usuário baixando 7 anos histórico
        # (~15-100 GB) hoje não tem visibilidade do consumo do SSD —
        # antes ``ERR_DISK_FULL`` aparecia no chunk N+1 sem aviso prévio.
        # Indicator vive na direita (permanent widget), antes da label
        # de versão. Atualiza a cada 30s + ao receber ``partition_registered``
        # (wired abaixo nos signals).
        from data_downloader._internal.bundle_paths import default_data_dir
        from data_downloader.ui.widgets.storage_indicator import StorageIndicator

        self._storage_indicator = StorageIndicator(self)
        bar.addPermanentWidget(self._storage_indicator)
        with contextlib.suppress(Exception):
            self._storage_indicator.set_data_dir(default_data_dir())

        # Versão app (direita).
        #
        # Story v1.0.8 fix (Pichau live test 2026-05-06): antes a status bar
        # mostrava "v1.0.0" hardcoded porque o code lia
        # ``public_api.__api_version__`` (SemVer da API pública, intencional-
        # mente fixa em "1.0.0" para ADR-007a — independente da versão do
        # pacote). O usuário esperava ver a versão do pacote (1.0.7+) que
        # ele instalou. Fix: lê ``data_downloader.__version__``, resolvido
        # via :func:`importlib.metadata.version` com fallback literal —
        # garantido estar em sync com ``pyproject.toml``.
        try:
            from data_downloader import __version__ as app_version
        except ImportError:
            app_version = "0.0.0"
        version_label = QLabel(
            format_msg("LBL_STATUSBAR_APP_VERSION", version=app_version),
            self,
        )
        version_label.setProperty("role", "muted")
        version_label.setObjectName("appVersionLabel")
        bar.addPermanentWidget(version_label)

    def _wire_storage_indicator(self) -> None:
        """v1.3.0 Wave 4B — conecta StorageIndicator aos signals de runtime.

        Triggers:
            - ``settings_screen.data_dir_changed`` → ``indicator.set_data_dir``
              (re-aponta + restart timer).
            - ``catalog_adapter.partition_registered`` → ``indicator.refresh``
              (re-poll imediato após download completar partition/chunk).

        Roda APÓS ``_build_screens`` + ``_build_status_bar`` — ambos os
        endpoints precisam existir. Idempotente em re-call (best-effort
        suppress de duplicate connect).
        """
        indicator = getattr(self, "_storage_indicator", None)
        if indicator is None:
            return
        settings_screen = self._screens.get(SCREEN_SETTINGS)
        if settings_screen is not None and hasattr(settings_screen, "data_dir_changed"):
            with contextlib.suppress(Exception):
                settings_screen.data_dir_changed.connect(indicator.set_data_dir)
        catalog_screen = self._screens.get(SCREEN_CATALOG)
        if catalog_screen is not None:
            catalog_adapter = getattr(catalog_screen, "_adapter", None)
            if catalog_adapter is not None and hasattr(catalog_adapter, "partition_registered"):
                with contextlib.suppress(Exception):
                    catalog_adapter.partition_registered.connect(
                        lambda *_args: indicator.refresh(),
                        Qt.ConnectionType.QueuedConnection,
                    )

    def set_metrics_exporter(self, exporter: object | None) -> None:
        """Liga (ou desliga) consumo de métricas do PrometheusExporter.

        Args:
            exporter: Instância de :class:`PrometheusExporter` (ou ``None``
                para desabilitar). Adapter em QThread já existente continua
                vivo — apenas troca o target.

        Graceful degradation: ``None`` faz status bar mostrar apenas DLL +
        versão (sem panel de métricas — Pyro audit).
        """
        if not hasattr(self, "_metrics_adapter"):
            return
        self._metrics_adapter.set_exporter(exporter)

    @Slot()
    def _on_metrics_unavailable(self) -> None:
        """Slot chamado quando exporter está indisponível (graceful)."""
        # Panel já renderiza 'off' state via snapshot vazio. Não precisamos
        # esconder; o usuário vê "Métricas: off" e sabe o estado.
        # Mantemos hook para futuras extensões (ex.: ocultar panel V2).

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

        # Ctrl+/ — abre cheat sheet modal (Wave 3 v1.1.0 — Uma).
        # Discoverability: Story 4.13 implementou shortcuts mas usuário não
        # tinha como descobri-los — resolve gap CONCERNS BIG COUNCIL.
        cheat_sc = QShortcut(QKeySequence("Ctrl+/"), self)
        cheat_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        cheat_sc.activated.connect(self._show_cheat_sheet)
        self._shortcuts.append(cheat_sc)

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

    @Slot(str)
    def _on_open_catalog_for_symbol(self, symbol: str) -> None:
        """Hotfix v1.1.0 — navega para CatalogScreen pós-download.

        Chamado pelo CTA "Ver no Catálogo" do success card do
        :class:`DownloadScreen`. Se ``CatalogScreen`` expor
        ``set_filter_symbol(symbol)`` no futuro, aplicamos o filtro
        automaticamente; senão apenas trocamos a tela ativa (graceful).
        """
        self.set_active_screen(SCREEN_CATALOG)
        catalog = self._screens.get(SCREEN_CATALOG)
        if catalog is not None and symbol and hasattr(catalog, "set_filter_symbol"):
            with contextlib.suppress(Exception):
                catalog.set_filter_symbol(symbol)  # type: ignore[attr-defined]

    @Slot(str, str)
    def _on_dll_status_changed(self, status: str, version: str = "—") -> None:
        """Atualiza statusbar com novo DLL status.

        Conectado a 2 fontes (ambas usam a MESMA assinatura ``(state,
        version)``):

        1. ``settings_screen.dll_status_changed`` — emitido pelo
           ``_TestConnectionWorker`` no Test Connection manual. Estados
           legados: ``"connected"`` / ``"testing"`` / ``"disconnected"`` /
           ``"not_configured"``.
        2. ``ui.adapters.dll_session_adapter.session_state_changed`` —
           Wave 2A v1.3.0 (Bug 3 fix): emitido pelo singleton
           ``dll.session`` a cada transição real (init, shutdown, run
           do orchestrator, reconnect). Estados novos:
           ``"idle"``/``"connecting"``/``"connected"``/``"downloading"``/
           ``"reconnecting"``/``"error"``.

        Os 2 sets coexistem (último a chamar ganha — Test Connection
        manual sobrepõe transitoriamente o estado da session, mas a
        session emite ``connected`` logo após e re-sincroniza).

        Args:
            status: estado da DLL (ver enums acima).
            version: string da versão DLL ou ``"—"``/symbol em
                ``downloading``. Default ``"—"`` para compat com chamadas
                legadas single-arg dos testes pré-Wave 2A.
        """
        # Wave 2A — mapeia estados novos + legados em (text, qss_status).
        # ``qss_status`` ∈ {connected, connecting, disconnected, downloading,
        # reconnecting, idle} — o style.qss define cores; estados novos não
        # mapeados caem em "disconnected" (cinza) por defesa.
        if status == "connected":
            text = format_msg("LBL_STATUSBAR_DLL_CONNECTED", version=version or "—")
            qss_status = "connected"
        elif status in ("connecting", "testing"):
            text = format_msg("LBL_STATUSBAR_DLL_CONNECTING")
            qss_status = "connecting"
        elif status == "downloading":
            # ``version`` aqui é o symbol (set_downloading passa symbol);
            # fallback ``"—"`` quando ausente.
            text = format_msg("LBL_STATUSBAR_DLL_DOWNLOADING", symbol=version or "—")
            qss_status = "downloading"
        elif status == "reconnecting":
            text = format_msg("LBL_STATUSBAR_DLL_RECONNECTING")
            qss_status = "reconnecting"
        elif status == "idle":
            text = format_msg("LBL_STATUSBAR_DLL_IDLE")
            qss_status = "idle"
        elif status == "error":
            text = format_msg("LBL_STATUSBAR_DLL_ERROR")
            qss_status = "disconnected"
        else:
            # ``disconnected`` / ``not_configured`` / desconhecido → estado
            # neutro "desconectada" (preserva compat com testes legados).
            text = format_msg("LBL_STATUSBAR_DLL_DISCONNECTED")
            qss_status = "disconnected"
        self._dll_status_label.setText(text)
        self._dll_status_label.setProperty("status", qss_status)
        self._dll_status_label.style().unpolish(self._dll_status_label)
        self._dll_status_label.style().polish(self._dll_status_label)

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

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: N802
        """Encerra worker threads (D3 COUNCIL-23) — metrics adapter + screens.

        Os screens (Download/Catalog) NÃO recebem ``closeEvent`` quando a janela
        principal fecha (widgets-filhos não-top-level não recebem o evento), então
        as ``QThread`` dos seus adapters precisam ser encerradas aqui. Sem isso,
        a thread fica viva no teardown e o Qt no Windows emite
        ``QThread: Destroyed while thread '' is still running`` + abort exit-code
        (task #14 v1.1.0).
        """
        # Shutdown metrics adapter primeiro (background polling).
        adapter = getattr(self, "_metrics_adapter", None)
        if adapter is not None:
            with contextlib.suppress(Exception):
                adapter.shutdown()
        # Shutdown dos adapters dos screens (DownloadAdapter / CatalogAdapter).
        for screen in getattr(self, "_screens", {}).values():
            screen_adapter = getattr(screen, "_adapter", None)
            if screen_adapter is not None and hasattr(screen_adapter, "shutdown"):
                with contextlib.suppress(Exception):
                    screen_adapter.shutdown()
        # v1.3.0 Wave 2A (Dex) — desliga observer do DllSessionAdapter
        # ANTES de ``shutdown_dll`` para evitar que o ``idle`` emitido no
        # finalize tente marshalar ``QMetaObject.invokeMethod`` sobre
        # ``self`` já em teardown.
        session_adapter = getattr(self, "_dll_session_adapter", None)
        if session_adapter is not None:
            with contextlib.suppress(Exception):
                session_adapter.shutdown()
        # task #21 (Q08-E): finaliza o singleton ProfitDLL process-global
        # UMA vez no encerramento da UI. ``shutdown_dll`` é idempotente e
        # best-effort (também registrado via ``atexit``). A ProfitDLL
        # Classic não tolera init→finalize→init, então o finalize só pode
        # rodar no teardown do processo.
        with contextlib.suppress(Exception):
            from data_downloader.dll.session import shutdown_dll

            shutdown_dll()
        super().closeEvent(event)
