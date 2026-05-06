"""data_downloader.ui.screens.settings_screen — Tela Configurações (Story 3.2 + 4.4).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Tela de configurações do app. Cinco seções principais (cada uma em
``QGroupBox`` dentro de ``QScrollArea``).

Componentes:

    - **ProfitDLL** — status conexão, path DLL, .env vars não-vazias
      (mascaradas, com [Mostrar]/[Esconder]), botão TESTAR CONEXÃO.
    - **Storage** — pasta data atual, espaço disco, status catálogo,
      ações MUDAR PASTA / ABRIR EXPLORER / VERIFICAR INTEGRIDADE / RECONCILIAR.
    - **Performance** (read-only) — display de defaults DLL queue size,
      storage queue size, chunk size, max retries, SQLite profile.
    - **Updates** (Story 4.4) — versão atual, botão verificar atualizações,
      status (up-to-date / outdated / error). V1.0: notify-only;
      auto-apply tufup full chega V1.1 (Story 4.4-followup).
    - **About** — versão app, versão DLL, schema version, links docs/bugs,
      lista de agentes (10 emojis).

5 estados (WIREFRAMES.md §"Tela 3 — SettingsScreen"):

    - **Normal** — todas as seções populadas com valores correntes.
    - **Loading** — durante TESTAR CONEXÃO (status DLL "↻ Testando...").
    - **Error** — teste DLL falhou; card vermelho com microcopy + RETRY.
    - **Empty** — primeira execução sem .env; passos educativos
      ``EMP_SETTINGS_DLL_FIRST_RUN_*``.
    - **Success** — toast verde 3s após salvar (``TST_SETTINGS_SAVED``).

Atalhos (THEME.md §6 — SettingsScreen):

    - ``Ctrl+S`` — Salvar (atalho convencional).
    - ``Esc``    — no-op (sem modal aberto).

QFileDialog para "MUDAR PASTA" usa ``DontUseNativeDialog`` (ADR-003 amendment,
finding M9, QT_PATTERNS §1).

Persistência: ``~/.data_downloader/config.toml`` (ADR-012 alinhamento).

Microcopy (R17 — Uma): TODAS as strings vêm de ``microcopy_loader``.

Referências:
    - docs/ux/WIREFRAMES.md (Tela 3)
    - docs/ux/MICROCOPY_CATALOG.md §17b.3
    - docs/ux/QT_PATTERNS.md §1 (DontUseNativeDialog)
    - docs/decisions/COUNCIL-23-epic3-first-screen.md (D1-D4)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from data_downloader.ui.microcopy_loader import format_msg

__all__ = ["SettingsScreen"]


# Estados nominais.
STATE_NORMAL = "normal"
STATE_LOADING = "loading"
STATE_ERROR = "error"
STATE_EMPTY = "empty"
STATE_SUCCESS = "success"


# Path para persistência (ADR-012).
def _config_path() -> Path:
    return Path.home() / ".data_downloader" / "config.toml"


# Variáveis .env esperadas (mascaradas no display).
# Story v1.0.2 B2 (Nelo+Aria 2026-05-05): naming canônico é ``PROFITDLL_*``
# (alinhado com .env.example, public_api/download.py:514-515 e tests/smoke).
# Versões anteriores liam ``PROFIT_USER``/``PROFIT_PASS`` sem prefixo,
# causando smoke real a sempre falhar com NL_NO_LOGIN.
_ENV_VARS = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
_SECRET_VARS = ("PROFITDLL_KEY", "PROFITDLL_PASS")


class SettingsScreen(QWidget):
    """Tela Configurações — 4 seções em QScrollArea (5 estados).

    Sinais públicos:
        state_changed(str): emitido em troca de estado.
        dll_status_changed(str): emitido quando teste de conexão completa.
            Payload: "connected" | "disconnected" | "testing" | "not_configured".
        data_dir_changed(str): emitido quando usuário muda data_dir + salva.
            Payload: novo path.
    """

    state_changed = Signal(str)
    dll_status_changed = Signal(str)
    data_dir_changed = Signal(str)
    # Story 4.4 — emitted após check_for_updates() completar.
    # Payload: status string (UpdateStatus value: "up_to_date" | "outdated"
    # | "error" | "unchecked").
    update_status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._current_state = STATE_NORMAL
        self._dirty = False  # marca quando usuário editou algo.
        self._secrets_visible: dict[str, bool] = dict.fromkeys(_SECRET_VARS, False)

        # Layout exterior — title + scroll com seções.
        self._title = QLabel(format_msg("LBL_SETTINGS_SCREEN_TITLE"), self)
        self._title.setProperty("role", "title")

        # Scroll area com seções.
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(16)

        # Seção DLL.
        self._dll_section = self._build_dll_section()
        scroll_layout.addWidget(self._dll_section)

        # Seção Storage.
        self._storage_section = self._build_storage_section()
        scroll_layout.addWidget(self._storage_section)

        # Seção Performance.
        self._perf_section = self._build_performance_section()
        scroll_layout.addWidget(self._perf_section)

        # Seção Updates (Story 4.4 — auto-updater stub V1.0).
        self._updates_section = self._build_updates_section()
        scroll_layout.addWidget(self._updates_section)

        # Seção About.
        self._about_section = self._build_about_section()
        scroll_layout.addWidget(self._about_section)

        scroll_layout.addStretch(1)
        self._scroll.setWidget(scroll_content)

        # Bottom action bar (doctor + save).
        bottom_bar = QHBoxLayout()
        self._doctor_btn = QPushButton(format_msg("BTN_DOCTOR_FULL"), self)
        self._doctor_btn.setObjectName("doctorBtn")
        bottom_bar.addWidget(self._doctor_btn)
        bottom_bar.addStretch(1)
        self._save_btn = QPushButton(format_msg("BTN_SAVE_SETTINGS"), self)
        self._save_btn.setObjectName("saveBtn")
        self._save_btn.setProperty("variant", "primary")
        self._save_btn.clicked.connect(self._on_save_clicked)
        bottom_bar.addWidget(self._save_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(12)
        outer.addWidget(self._title)
        outer.addWidget(self._scroll, stretch=1)
        outer.addLayout(bottom_bar)

        # Toast.
        self._toast = self._build_toast()
        self._toast.setParent(self)
        self._toast.hide()

        # Atalhos.
        self._register_shortcuts()

        # Carga inicial — popula campos com valores correntes.
        self._load_initial_values()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_state(self) -> str:
        return self._current_state

    def handle_escape(self) -> bool:
        # Esc não fecha settings (usuário usa nav Ctrl+D / Ctrl+B).
        return False

    def is_dirty(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------
    # Construção UI
    # ------------------------------------------------------------------

    def _build_dll_section(self) -> QGroupBox:
        section = QGroupBox(format_msg("LBL_SETTINGS_SECTION_DLL"), self)

        form = QFormLayout(section)
        form.setSpacing(8)

        # Status (label dinâmico).
        self._dll_status_label = QLabel(format_msg("LBL_DLL_STATUS_NOT_CONFIGURED"), section)
        self._dll_status_label.setProperty("status", "not_configured")
        form.addRow(QLabel("Status:", section), self._dll_status_label)

        # DLL path.
        self._dll_path_edit = QLineEdit(section)
        self._dll_path_edit.setObjectName("dllPathEdit")
        self._dll_path_edit.textEdited.connect(self._mark_dirty)
        form.addRow(QLabel(format_msg("LBL_DLL_PATH") + ":", section), self._dll_path_edit)

        # Env vars — mascarados.
        env_label = QLabel(format_msg("LBL_ENV_VARS") + ":", section)
        env_label.setProperty("role", "muted")
        form.addRow(env_label)

        self._env_widgets: dict[str, tuple[QLineEdit, QPushButton | None]] = {}
        for var_name in _ENV_VARS:
            row = QHBoxLayout()
            value_edit = QLineEdit(section)
            value_edit.setObjectName(f"envEdit_{var_name}")
            if var_name in _SECRET_VARS:
                value_edit.setEchoMode(QLineEdit.EchoMode.Password)
            value_edit.textEdited.connect(self._mark_dirty)
            row.addWidget(value_edit, stretch=1)

            toggle_btn: QPushButton | None = None
            if var_name in _SECRET_VARS:
                toggle_btn = QPushButton(format_msg("BTN_SHOW_SECRET"), section)
                toggle_btn.setObjectName(f"toggleSecret_{var_name}")
                toggle_btn.setMaximumWidth(96)
                toggle_btn.clicked.connect(
                    lambda _checked=False, name=var_name: self._toggle_secret(name)
                )
                row.addWidget(toggle_btn)

            row_widget = QWidget(section)
            row_widget.setLayout(row)
            form.addRow(QLabel(var_name + ":", section), row_widget)
            self._env_widgets[var_name] = (value_edit, toggle_btn)

        # Botões.
        actions = QHBoxLayout()
        self._test_conn_btn = QPushButton(format_msg("BTN_TEST_CONNECTION"), section)
        self._test_conn_btn.setObjectName("testConnBtn")
        self._test_conn_btn.clicked.connect(self._on_test_connection_clicked)
        actions.addWidget(self._test_conn_btn)

        self._open_dll_folder_btn = QPushButton(format_msg("BTN_OPEN_DLL_FOLDER"), section)
        self._open_dll_folder_btn.setObjectName("openDllFolderBtn")
        self._open_dll_folder_btn.clicked.connect(self._on_open_dll_folder_clicked)
        actions.addWidget(self._open_dll_folder_btn)

        actions.addStretch(1)
        actions_widget = QWidget(section)
        actions_widget.setLayout(actions)
        form.addRow(actions_widget)

        # Empty state hint (mostrado se .env não configurado).
        self._dll_empty_hint = QLabel("", section)
        self._dll_empty_hint.setProperty("role", "muted")
        self._dll_empty_hint.setWordWrap(True)
        form.addRow(self._dll_empty_hint)

        return section

    def _build_storage_section(self) -> QGroupBox:
        section = QGroupBox(format_msg("LBL_SETTINGS_SECTION_STORAGE"), self)

        form = QFormLayout(section)
        form.setSpacing(8)

        # Pasta data.
        path_row = QHBoxLayout()
        self._data_dir_edit = QLineEdit(section)
        self._data_dir_edit.setObjectName("dataDirEdit")
        self._data_dir_edit.textEdited.connect(self._mark_dirty)
        path_row.addWidget(self._data_dir_edit, stretch=1)

        self._change_dir_btn = QPushButton(format_msg("BTN_CHANGE_DATA_DIR"), section)
        self._change_dir_btn.setObjectName("changeDirBtn")
        self._change_dir_btn.clicked.connect(self._on_change_data_dir_clicked)
        path_row.addWidget(self._change_dir_btn)

        path_widget = QWidget(section)
        path_widget.setLayout(path_row)
        form.addRow(QLabel(format_msg("LBL_STORAGE_DATA_DIR") + ":", section), path_widget)

        # Free space (calculado).
        self._free_space_label = QLabel("", section)
        self._free_space_label.setProperty("role", "muted")
        form.addRow(self._free_space_label)

        # Catalog status.
        self._catalog_status_label = QLabel("", section)
        self._catalog_status_label.setProperty("role", "muted")
        form.addRow(self._catalog_status_label)

        # Actions.
        actions = QHBoxLayout()
        self._open_data_dir_btn = QPushButton(format_msg("BTN_OPEN_DATA_DIR"), section)
        self._open_data_dir_btn.setObjectName("openDataDirBtn")
        self._open_data_dir_btn.clicked.connect(self._on_open_data_dir_clicked)
        actions.addWidget(self._open_data_dir_btn)

        self._integrity_btn = QPushButton(format_msg("BTN_INTEGRITY_CHECK"), section)
        self._integrity_btn.setObjectName("integrityBtn")
        actions.addWidget(self._integrity_btn)

        self._reconcile_btn = QPushButton(format_msg("BTN_RECONCILE"), section)
        self._reconcile_btn.setObjectName("reconcileSettingsBtn")
        actions.addWidget(self._reconcile_btn)

        actions.addStretch(1)
        actions_widget = QWidget(section)
        actions_widget.setLayout(actions)
        form.addRow(actions_widget)

        return section

    def _build_performance_section(self) -> QGroupBox:
        section = QGroupBox(format_msg("LBL_SETTINGS_SECTION_PERFORMANCE"), self)
        form = QFormLayout(section)
        form.setSpacing(6)

        # Defaults read-only (referência ADR-002).
        defaults = (
            ("LBL_PERF_DLL_QUEUE_SIZE", "8192 (default)"),
            ("LBL_PERF_STORAGE_QUEUE_SIZE", "2048 (default)"),
            ("LBL_PERF_CHUNK_SIZE", "30 dias (default)"),
            ("LBL_PERF_MAX_RETRIES", "3 (default)"),
        )
        for label_id, value in defaults:
            label = QLabel(format_msg(label_id) + ":", section)
            value_label = QLabel(value, section)
            value_label.setProperty("role", "code")
            form.addRow(label, value_label)

        # SQLite profile (Story 2.8 — env DATA_DOWNLOADER_SQLITE_PROFILE).
        profile = os.environ.get("DATA_DOWNLOADER_SQLITE_PROFILE", "default")
        sqlite_label = QLabel(format_msg("LBL_PERF_SQLITE_PROFILE") + ":", section)
        sqlite_value = QLabel(f"{profile} (env DATA_DOWNLOADER_SQLITE_PROFILE)", section)
        sqlite_value.setProperty("role", "code")
        form.addRow(sqlite_label, sqlite_value)

        note = QLabel(format_msg("LBL_PERF_NOTE_ADVANCED"), section)
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        form.addRow(note)

        return section

    def _build_updates_section(self) -> QGroupBox:
        """Seção Updates — Story 4.4 (UpdaterStub notify-only V1.0).

        Layout vertical:

            [Versão atual: vX.Y.Z]
            [Status — clique para verificar / outdated vN.M.K / up-to-date]
            [Aviso V1.0 manual]
            [Verificar atualizações] [Baixar manualmente — visível só se outdated]
        """
        section = QGroupBox(format_msg("LBL_SETTINGS_SECTION_UPDATES"), self)

        layout = QVBoxLayout(section)
        layout.setSpacing(6)

        # Versão atual (resolvida em _load_initial_values via UpdaterStub).
        self._update_current_version_label = QLabel(
            format_msg("LBL_UPDATE_CURRENT_VERSION", version="—"), section
        )
        self._update_current_version_label.setObjectName("updateCurrentVersionLabel")
        layout.addWidget(self._update_current_version_label)

        # Status (dinâmico).
        self._update_status_label = QLabel(format_msg("LBL_UPDATE_STATUS_UNCHECKED"), section)
        self._update_status_label.setObjectName("updateStatusLabel")
        self._update_status_label.setProperty("status", "unchecked")
        layout.addWidget(self._update_status_label)

        # Aviso V1.0 manual + link para INSTALL.md.
        notice = QLabel(format_msg("LBL_UPDATE_NOTICE_MANUAL_V1"), section)
        notice.setProperty("role", "muted")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        # Botões.
        actions = QHBoxLayout()
        self._check_updates_btn = QPushButton(format_msg("BTN_CHECK_FOR_UPDATES"), section)
        self._check_updates_btn.setObjectName("checkUpdatesBtn")
        self._check_updates_btn.clicked.connect(self._on_check_updates_clicked)
        actions.addWidget(self._check_updates_btn)

        self._download_update_btn = QPushButton(format_msg("BTN_DOWNLOAD_UPDATE_MANUAL"), section)
        self._download_update_btn.setObjectName("downloadUpdateBtn")
        self._download_update_btn.clicked.connect(self._on_download_update_manual_clicked)
        self._download_update_btn.setVisible(False)  # só aparece se outdated
        actions.addWidget(self._download_update_btn)

        actions.addStretch(1)
        actions_widget = QWidget(section)
        actions_widget.setLayout(actions)
        layout.addWidget(actions_widget)

        # Cache do release_url para botão "Baixar manualmente".
        self._pending_release_url: str = ""

        return section

    def _build_about_section(self) -> QGroupBox:
        section = QGroupBox(format_msg("LBL_SETTINGS_SECTION_ABOUT"), self)
        layout = QVBoxLayout(section)

        # Versão app.
        try:
            from data_downloader.public_api import __api_version__ as app_version
        except ImportError:
            app_version = "0.1.0"
        version_label = QLabel(format_msg("LBL_ABOUT_APP_VERSION", version=app_version), section)
        layout.addWidget(version_label)

        # DLL version (placeholder — populado após test connection).
        self._about_dll_label = QLabel(format_msg("LBL_ABOUT_DLL_VERSION", version="—"), section)
        self._about_dll_label.setObjectName("aboutDllLabel")
        layout.addWidget(self._about_dll_label)

        # Schema version (do catalog).
        try:
            from data_downloader.storage.catalog import CATALOG_VERSION

            schema = CATALOG_VERSION
        except ImportError:
            schema = "1.1.0"
        schema_label = QLabel(format_msg("LBL_ABOUT_SCHEMA_VERSION", version=schema), section)
        layout.addWidget(schema_label)

        # Links.
        layout.addWidget(QLabel(format_msg("LBL_ABOUT_DOCS_LINK"), section))
        layout.addWidget(QLabel(format_msg("LBL_ABOUT_BUG_LINK"), section))

        # Lista de agentes (referência COUNCIL-12 / agents/ folder).
        agents_label = QLabel(
            "Squad: 🖼️ Felix • 🎨 Uma • 🏛️ Aria • 💻 Dex • 🧪 Quinn • "
            "📋 Morgan • 💾 Sol • ⚡ Pyro • ⚙️ Gage • 🔌 Nelo",
            section,
        )
        agents_label.setProperty("role", "muted")
        agents_label.setWordWrap(True)
        layout.addWidget(agents_label)

        return section

    def _build_toast(self) -> QFrame:
        toast = QFrame()
        toast.setProperty("role", "toast")
        toast.setProperty("variant", "success")
        toast.setObjectName("settingsToast")
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
        for keyseq, handler in (("Ctrl+S", self._on_save_clicked),):
            sc = QShortcut(QKeySequence(keyseq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    # ------------------------------------------------------------------
    # Initial state
    # ------------------------------------------------------------------

    def _load_initial_values(self) -> None:
        # DLL path: env or default.
        dll_path = os.environ.get("PROFITDLL_PATH", "")
        if not dll_path:
            # Heurística Windows.
            for candidate in (
                Path("C:/ProfitDLL/ProfitDLL.dll"),
                Path.cwd() / "ProfitDLL" / "ProfitDLL.dll",
            ):
                if candidate.exists():
                    dll_path = str(candidate)
                    break
        self._dll_path_edit.setText(dll_path)

        # Env vars from environment.
        for var_name, (edit, _toggle) in self._env_widgets.items():
            value = os.environ.get(var_name, "")
            edit.setText(value)

        # Decide if .env is configured.
        configured = all(os.environ.get(var) for var in _ENV_VARS)
        if configured:
            self._set_dll_status("disconnected")  # configurado mas não testado
            self._dll_empty_hint.setText("")
        else:
            self._set_dll_status("not_configured")
            steps = "  ".join(
                format_msg(step_id)
                for step_id in (
                    "EMP_SETTINGS_DLL_FIRST_RUN_TITLE",
                    "EMP_SETTINGS_DLL_FIRST_RUN_STEP1",
                    "EMP_SETTINGS_DLL_FIRST_RUN_STEP2",
                    "EMP_SETTINGS_DLL_FIRST_RUN_STEP3",
                )
            )
            self._dll_empty_hint.setText(steps)

        # Data dir: env or default.
        data_dir = os.environ.get("DATA_DOWNLOADER_DATA_DIR") or str(Path.cwd() / "data")
        self._data_dir_edit.setText(data_dir)
        self._refresh_storage_status(Path(data_dir))

        # Updates section — popula versão atual (sem checagem de rede).
        # Story 4.4: check só acontece em click explícito do usuário
        # para evitar I/O em initial load (R11 + privacidade).
        try:
            from data_downloader._updater import UpdaterStub

            current_version = UpdaterStub().current_version
        except ImportError:
            current_version = "—"
        self._update_current_version_label.setText(
            format_msg("LBL_UPDATE_CURRENT_VERSION", version=current_version)
        )

        self._dirty = False

    def _refresh_storage_status(self, data_dir: Path) -> None:
        # Espaço livre.
        try:
            usage = shutil.disk_usage(str(data_dir if data_dir.exists() else data_dir.parent))
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            self._free_space_label.setText(
                format_msg(
                    "LBL_STORAGE_FREE_SPACE",
                    free_gb=f"{free_gb:.1f}",
                    total_gb=f"{total_gb:.1f}",
                )
            )
        except Exception:
            self._free_space_label.setText("—")

        # Catalog status — count partitions sem auto-reconcile (rápido).
        db_path = data_dir / "history" / "catalog.db"
        n_partitions = 0
        if db_path.exists():
            try:
                import sqlite3

                with sqlite3.connect(str(db_path)) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM partitions")
                    n_partitions = int(cursor.fetchone()[0])
            except Exception:
                pass
            self._catalog_status_label.setText(
                format_msg("LBL_STORAGE_CATALOG_OK", n_partitions=n_partitions)
            )
        else:
            self._catalog_status_label.setText(format_msg("LBL_STORAGE_CATALOG_OK", n_partitions=0))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _mark_dirty(self, *_args: object) -> None:
        self._dirty = True

    def _toggle_secret(self, var_name: str) -> None:
        edit, toggle_btn = self._env_widgets[var_name]
        if toggle_btn is None:
            return
        currently_visible = self._secrets_visible.get(var_name, False)
        new_visible = not currently_visible
        self._secrets_visible[var_name] = new_visible
        edit.setEchoMode(QLineEdit.EchoMode.Normal if new_visible else QLineEdit.EchoMode.Password)
        toggle_btn.setText(format_msg("BTN_HIDE_SECRET" if new_visible else "BTN_SHOW_SECRET"))

    def _on_test_connection_clicked(self) -> None:
        """Testa conexão DLL.

        Esta é uma operação que tipicamente precisa de DLL — em ambiente
        sem DLL (testes/Linux), retorna falha rapidamente. Implementação
        síncrona com timeout curto; futuro: mover para adapter próprio
        em QThread se for muito lento (Story 3.x).
        """
        self._set_dll_status("testing")
        self._test_conn_btn.setEnabled(False)

        # Defer execução para próximo evento — UI atualiza primeiro.
        QTimer.singleShot(50, self._do_test_connection)

    def _do_test_connection(self) -> None:
        ok = False
        version: str | None = None
        error_msg = ""
        try:
            # Tenta importar e inicializar — encapsula tudo em try.
            from data_downloader.dll.session import open_session  # type: ignore[import-not-found]

            with open_session() as session:
                version = getattr(session, "version", None) or "?"
                ok = True
        except Exception as exc:
            error_msg = str(exc)
            ok = False

        self._test_conn_btn.setEnabled(True)
        if ok:
            self._set_dll_status("connected", version=version or "?")
            self._show_toast(
                format_msg("TST_TEST_CONNECTION_OK"), variant="success", duration_ms=3000
            )
        else:
            self._set_dll_status("disconnected")
            self._show_toast(
                format_msg("TST_TEST_CONNECTION_FAIL"),
                variant="error",
                duration_ms=5000,
            )
            self._set_state(STATE_ERROR)
            # Detalhe técnico no hint do empty (caso exista).
            if error_msg:
                self._dll_empty_hint.setText(f"Erro técnico: {error_msg}")

    def _on_open_dll_folder_clicked(self) -> None:
        path_str = self._dll_path_edit.text().strip()
        if not path_str:
            return
        self._open_in_explorer(Path(path_str).parent)

    def _on_change_data_dir_clicked(self) -> None:
        # QFileDialog DontUseNativeDialog (QT_PATTERNS §1, finding M9).
        current = self._data_dir_edit.text().strip() or str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de dados",
            current,
            QFileDialog.Option.DontUseNativeDialog,
        )
        if folder:
            self._data_dir_edit.setText(folder)
            self._mark_dirty()
            self._refresh_storage_status(Path(folder))

    def _on_open_data_dir_clicked(self) -> None:
        path_str = self._data_dir_edit.text().strip()
        if path_str:
            self._open_in_explorer(Path(path_str))

    def _on_save_clicked(self) -> None:
        """Persiste config em ~/.data_downloader/config.toml (ADR-012)."""
        config_data = {
            "dll_path": self._dll_path_edit.text().strip(),
            "data_dir": self._data_dir_edit.text().strip(),
        }
        # Env vars não são persistidos em config.toml — são lidos do ambiente.
        # Apenas alertamos se valores foram editados (vão para ~/.env via outro fluxo).

        try:
            self._write_config(config_data)
        except OSError:
            self._show_toast(
                format_msg("TST_TEST_CONNECTION_FAIL"),
                variant="error",
                duration_ms=4000,
            )
            return

        self._dirty = False
        self._show_toast(format_msg("TST_SETTINGS_SAVED"), variant="success", duration_ms=3000)
        self._set_state(STATE_SUCCESS)
        # Notifica MainWindow para CatalogScreen recarregar com novo data_dir.
        if config_data["data_dir"]:
            self.data_dir_changed.emit(config_data["data_dir"])
        # Restaura state normal após toast.
        QTimer.singleShot(3000, lambda: self._set_state(STATE_NORMAL))

    def _write_config(self, config: dict[str, str]) -> None:
        """Escreve config TOML simples (sem dependência adicional)."""
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Format TOML mínimo manual — evita dep extra.
        lines = ["# data-downloader settings (gerado por SettingsScreen)\n"]
        for key, value in config.items():
            # Escapa aspas simples.
            v = (value or "").replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{v}"\n')
        path.write_text("".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # State machine + helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._current_state = state
        self.state_changed.emit(state)

    # ------------------------------------------------------------------
    # Updates section handlers (Story 4.4 — UpdaterStub V1.0)
    # ------------------------------------------------------------------

    def _on_check_updates_clicked(self) -> None:
        """Verifica updates via UpdaterStub. Slot síncrono curto (HTTP timeout 5s).

        Para evitar bloqueio MainThread > 16ms (R11), defer para próximo
        evento via QTimer.singleShot — UI atualiza spinner antes de
        chamar I/O HTTP.
        """
        self._check_updates_btn.setEnabled(False)
        self._update_status_label.setText(format_msg("LBL_UPDATE_STATUS_UNCHECKED"))
        self._update_status_label.setProperty("status", "checking")
        self._update_status_label.style().unpolish(self._update_status_label)
        self._update_status_label.style().polish(self._update_status_label)
        QTimer.singleShot(50, self._do_check_updates)

    def _do_check_updates(self) -> None:
        """Executa check via UpdaterStub e atualiza UI."""
        try:
            from data_downloader._updater import UpdaterStub, UpdateStatus
        except ImportError:
            self._update_status_label.setText(format_msg("LBL_UPDATE_STATUS_ERROR"))
            self._update_status_label.setProperty("status", "error")
            self._check_updates_btn.setEnabled(True)
            self.update_status_changed.emit("error")
            return

        updater = UpdaterStub()
        # Atualiza label de versão atual (sempre).
        self._update_current_version_label.setText(
            format_msg("LBL_UPDATE_CURRENT_VERSION", version=updater.current_version)
        )

        info = updater.check_for_updates()
        status = updater.last_status

        if status == UpdateStatus.UP_TO_DATE:
            self._update_status_label.setText(format_msg("LBL_UPDATE_STATUS_UP_TO_DATE"))
            self._update_status_label.setProperty("status", "up_to_date")
            self._download_update_btn.setVisible(False)
            self._pending_release_url = ""
        elif status == UpdateStatus.OUTDATED and info is not None:
            self._update_status_label.setText(
                format_msg("LBL_UPDATE_STATUS_OUTDATED", version=info.latest_version)
            )
            self._update_status_label.setProperty("status", "outdated")
            self._download_update_btn.setVisible(True)
            self._pending_release_url = info.release_url
        else:
            # ERROR ou UNCHECKED inesperado.
            self._update_status_label.setText(format_msg("LBL_UPDATE_STATUS_ERROR"))
            self._update_status_label.setProperty("status", "error")
            self._download_update_btn.setVisible(False)
            self._pending_release_url = ""

        self._update_status_label.style().unpolish(self._update_status_label)
        self._update_status_label.style().polish(self._update_status_label)
        self._check_updates_btn.setEnabled(True)
        self.update_status_changed.emit(status.value)

    def _on_download_update_manual_clicked(self) -> None:
        """Abre URL da release page no browser do usuário.

        V1.0: notify-only — usuário baixa zip da página GitHub
        manualmente. V1.1+: tufup auto-download + apply via signed bundle.
        """
        if not self._pending_release_url:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(self._pending_release_url))
        except Exception:
            pass

    def _set_dll_status(self, status: str, version: str = "") -> None:
        """status: connected | disconnected | testing | not_configured."""
        self._dll_status_label.setProperty("status", status)
        if status == "connected":
            self._dll_status_label.setText(
                format_msg("LBL_DLL_STATUS_CONNECTED", version=version or "?")
            )
            self._about_dll_label.setText(
                format_msg("LBL_ABOUT_DLL_VERSION", version=version or "?")
            )
        elif status == "disconnected":
            self._dll_status_label.setText(format_msg("LBL_DLL_STATUS_DISCONNECTED"))
        elif status == "testing":
            self._dll_status_label.setText(format_msg("LBL_DLL_STATUS_TESTING"))
            self._set_state(STATE_LOADING)
        elif status == "not_configured":
            self._dll_status_label.setText(format_msg("LBL_DLL_STATUS_NOT_CONFIGURED"))
            self._set_state(STATE_EMPTY)

        self._dll_status_label.style().unpolish(self._dll_status_label)
        self._dll_status_label.style().polish(self._dll_status_label)
        self.dll_status_changed.emit(status)

    def _open_in_explorer(self, path: Path) -> None:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception:
            pass

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
