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

Persistência: ``~/.data-downloader/config.toml`` (ADR-012 alinhamento;
canonizado em hífen na Story v1.0.5 — antes underscore).

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
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
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
#
# Story v1.0.5 fix (Pichau live test 2026-05-06): canoniza
# ``~/.data-downloader/`` (hífen) — antes da v1.0.5, ``config.toml`` ia para
# ``.data_downloader/`` (underscore) e ``.env`` para ``.data-downloader/``
# (hífen). Essa divergência era confusa para o usuário e fonte latente de
# bugs (e.g. cleanup ferramentas viam dois diretórios "diferentes"). Single
# source of truth via :func:`data_downloader._env_loader.user_env_path`.
#
# Migration nota: usuários pré-v1.0.5 com ``~/.data_downloader/config.toml``
# perdem a configuração (re-Save no novo path resolve). Migration
# automática postergada para v1.0.6 (caso de uso raro — Save é trivial).
def _config_path() -> Path:
    from data_downloader._env_loader import user_env_path

    # ``user_env_path()`` retorna ``~/.data-downloader/.env`` — pegamos o
    # parent para ter o diretório canônico e adicionamos ``config.toml``.
    return user_env_path().parent / "config.toml"


def _auto_detect_dll_path() -> Path | None:
    """Detecta automaticamente o ``ProfitDLL.dll`` em paths conhecidos.

    Story 4.14 (Pichau live test 2026-05-05): usuário do .exe não sabe
    o path completo da DLL; UX deve auto-popular Settings → DLL Path.

    Ordem de busca:

        1. **Frozen mode (PyInstaller)**: ``bundle_root() / ProfitDLL.dll``
           — DLL bundled com o .exe é o golden path para o usuário final.
        2. **Common Nelogica install paths** (Windows): Program Files
           (x64 e x86) + ``%PROGRAMFILES%`` env var.
        3. **Bundled dev path** (repo): ``profitdll/DLLs/Win64/ProfitDLL.dll``
           — útil em dev/CI quando rodando ``python -m data_downloader``.

    Wave 1 v1.1.0 (Aria — ADR-018): detecção frozen delegada a
    :func:`bundle_paths.is_frozen` + :func:`bundle_paths.bundle_root`.

    Returns:
        Primeiro path existente como :class:`pathlib.Path`, ou ``None`` se
        nenhum candidato existe (usuário precisa usar Browse... ou colar).
    """
    from data_downloader._internal.bundle_paths import bundle_root, is_frozen

    # 1. Frozen mode — bundled DLL é o golden path.
    if is_frozen():
        bundled = bundle_root() / "ProfitDLL.dll"
        if bundled.is_file():
            return bundled

    # 2. Common Nelogica install paths (Windows).
    candidates: list[Path] = [
        Path(r"C:\Program Files\Nelogica\ProfitChart\DLLs\Win64\ProfitDLL.dll"),
        Path(r"C:\Program Files (x86)\Nelogica\ProfitChart\DLLs\Win64\ProfitDLL.dll"),
    ]
    program_files = os.environ.get("PROGRAMFILES", "").strip()
    if program_files:
        candidates.append(
            Path(program_files) / "Nelogica" / "ProfitChart" / "DLLs" / "Win64" / "ProfitDLL.dll"
        )

    # 3. Bundled dev path (repo) — settings_screen.py está em
    # ``src/data_downloader/ui/screens/``; parents[3] é o repo root.
    try:
        repo_root = Path(__file__).resolve().parents[3]
        candidates.append(repo_root / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll")
    except (IndexError, OSError):
        pass

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


# Variáveis .env esperadas (mascaradas no display).
# Story v1.0.2 B2 (Nelo+Aria 2026-05-05): naming canônico é ``PROFITDLL_*``
# (alinhado com .env.example, public_api/download.py:514-515 e tests/smoke).
# Versões anteriores liam ``PROFIT_USER``/``PROFIT_PASS`` sem prefixo,
# causando smoke real a sempre falhar com NL_NO_LOGIN.
_ENV_VARS = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
_SECRET_VARS = ("PROFITDLL_KEY", "PROFITDLL_PASS")


# =====================================================================
# QThread workers (Story v1.1.0 Wave 3 P1 — Felix-UI BIG COUNCIL B3+B4)
# =====================================================================
#
# Antes da Wave 3, ``_do_test_connection``, ``_on_integrity_clicked`` e
# ``_on_reconcile_clicked`` rodavam SYNC no MainThread, freezando a UI
# por 1-30s (test_connection chamando ProfitDLL Init/Login + waitMarket;
# integrity iterando sha256 de N partições; reconcile abrindo SQLite +
# scan disco). Resultado: ao clicar "Testar Conexão" o usuário não conseguia
# nem mover a janela. Wave 3 P1 move tudo para QThread workers — UI fica
# fluida e workers comunicam via signals (Qt.QueuedConnection na conexão).


class _TestConnectionWorker(QObject):
    """Worker que executa teste de conexão DLL em QThread.

    Move a operação bloqueante (ProfitDLL Init + Login + wait) para fora
    do MainThread. Caller cria o worker, move para QThread, conecta
    ``finished`` ao slot UI (Qt.QueuedConnection) e dá ``thread.start()``.
    """

    finished = Signal(bool, str, str)  # ok, version, error_msg

    def __init__(self, key: str, user: str, password: str) -> None:
        super().__init__()
        self._key = key
        self._user = user
        self._password = password

    @Slot()
    def run(self) -> None:
        ok = False
        version = ""
        error_msg = ""
        try:
            if not all((self._key, self._user, self._password)):
                error_msg = "Credenciais ausentes (PROFITDLL_KEY/USER/PASS)"
            else:
                # Import lazy — evita custo se worker nunca rodar.
                # task #21 (Nelo Q08-E): a ProfitDLL Classic NÃO é
                # re-inicializável no mesmo processo (init→finalize→init
                # crasha em ``CreateDataLoader`` — ``Erro.log`` Pichau
                # 2026-05-12). Usamos o singleton process-global de
                # ``dll.session`` — SEM ``finalize()`` aqui. Se o usuário
                # clicar "Baixar" depois, ``_build_real_dll`` reusa esta
                # mesma instância já conectada. O finalize roda 1x no
                # encerramento (atexit + MainWindow.closeEvent).
                # fix #21b: o modo de init DEVE ser o mesmo do Download
                # (``resolve_dll_init_mode`` é a fonte única). A DLL Classic
                # não é re-inicializável (Q08-E) — se o usuário clicar
                # "Testar Conexão" e depois "Baixar", o singleton reusa esta
                # instância no modo em que foi criada. Antes (fix #21) este
                # call site forçava ``minimal_handshake=True`` enquanto o
                # download usava o default ``False`` (modo completo) →
                # download reusava a instância minimal → DLL crashava
                # internamente ao traduzir trades (PopulateTradeV0 AV,
                # status=failed trades=0). Test Connection só lê status/
                # versão — não baixa nada — então ter os callbacks de trade
                # registrados (modo completo) é inócuo aqui.
                from data_downloader.dll.session import get_dll, resolve_dll_init_mode

                dll = get_dll(
                    market_only=True,
                    key=self._key,
                    user=self._user,
                    password=self._password,
                    **resolve_dll_init_mode(),
                )
                connected = dll.wait_market_connected(timeout=30, retry_attempts=1)
                if connected:
                    version = str(getattr(dll, "dll_version", None) or "?")
                    ok = True
                else:
                    error_msg = "Timeout aguardando MARKET_CONNECTED"
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            ok = False
        self.finished.emit(ok, version, error_msg)


class _IntegrityWorker(QObject):
    """Worker que executa integrity check (revalidate sha256 de N partições).

    Itera sobre todas as partições do catálogo na thread separada — cada
    partição requer leitura do arquivo + cálculo sha256, custo O(arquivo).
    """

    finished = Signal(int, int, str)  # n_ok, n_total, error_msg
    progress = Signal(int, int)  # current, total (não usado por padrão; hook futuro)

    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self._data_dir = data_dir

    @Slot()
    def run(self) -> None:
        n_ok = 0
        n_total = 0
        error_msg = ""
        try:
            from data_downloader.ui.adapters.catalog_adapter import CatalogAdapter

            adapter = CatalogAdapter()
            try:
                partitions = adapter._load_all_partitions(self._data_dir)
                n_total = len(partitions)
                for idx, partition in enumerate(partitions, start=1):
                    rel_path = getattr(partition, "partition_path", "")
                    if not rel_path:
                        continue
                    try:
                        ok = adapter._revalidate_checksum(self._data_dir, rel_path)
                    except Exception:
                        ok = False
                    if ok:
                        n_ok += 1
                    self.progress.emit(idx, n_total)
            finally:
                adapter.shutdown()
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
        self.finished.emit(n_ok, n_total, error_msg)


class _ReconcileWorker(QObject):
    """Worker que executa reconcile (auto-correct=True) em QThread.

    Reconcile abre SQLite + scaneia disco — pode demorar segundos em
    catálogos grandes. Movido para fora do MainThread.
    """

    finished = Signal(int, int, str)  # n_added, n_removed, error_msg

    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self._data_dir = data_dir

    @Slot()
    def run(self) -> None:
        n_added = 0
        n_removed = 0
        error_msg = ""
        try:
            from data_downloader.ui.adapters.catalog_adapter import CatalogAdapter

            adapter = CatalogAdapter()
            try:
                report = adapter._reconcile(self._data_dir)
                n_added = len(getattr(report, "auto_corrected_paths", ()) or ())
                # reconcile não remove drift B (só reporta) — Story 4.10.
                n_removed = 0
            finally:
                adapter.shutdown()
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
        self.finished.emit(n_added, n_removed, error_msg)


class SettingsScreen(QWidget):
    """Tela Configurações — 4 seções em QScrollArea (5 estados).

    Sinais públicos:
        state_changed(str): emitido em troca de estado.
        dll_status_changed(str, str): emitido quando teste de conexão completa.
            Payload: (status, version) onde status é
            "connected" | "disconnected" | "testing" | "not_configured"
            e version é a string da versão (ou "—" quando indisponível).
        data_dir_changed(str): emitido quando usuário muda data_dir + salva.
            Payload: novo path.
    """

    state_changed = Signal(str)
    dll_status_changed = Signal(str, str)
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

        # Timer (parented em ``self``) usado para restaurar STATE_NORMAL após o
        # toast de Save. Antes era ``QTimer.singleShot(3000, lambda: ...)`` órfão
        # — o lambda capturava ``self`` e podia disparar após a screen ser
        # destruída, causando ``RuntimeError: Signal source has been deleted``
        # de forma não-determinística (poluindo testes seguintes). Com parent
        # ``self`` o timer é destruído junto com a screen → não vaza.
        self._state_restore_timer = QTimer(self)
        self._state_restore_timer.setSingleShot(True)
        self._state_restore_timer.timeout.connect(lambda: self._set_state(STATE_NORMAL))

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
        #
        # Story 4.15 P0 release-blocker (Pichau live test 2026-05-06):
        # botão Save desaparecia visualmente em frozen build porque QSS não
        # carregava (spec/app.py path mismatch — fix em app.py). Hardening
        # defense-in-depth aqui: mesmo SEM QSS, o botão deve ser visualmente
        # óbvio. ``setMinimumSize(140, 36)`` garante área clicável mínima
        # confortável (Fitts's law) e diferencia do doctor button. Texto em
        # CAIXA ALTA ("SALVAR") aumenta peso visual sem depender de
        # font-weight QSS. ``setDefault(True)`` faz o botão receber o realce
        # nativo de "default action" (Enter ativa).
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)
        bottom_bar.setContentsMargins(0, 8, 0, 0)
        self._doctor_btn = QPushButton(format_msg("BTN_DOCTOR_FULL"), self)
        self._doctor_btn.setObjectName("doctorBtn")
        # Story 4.31 AC10: nome acessível para Narrator/NVDA.
        self._doctor_btn.setAccessibleName("Executar diagnóstico (Doctor)")
        self._doctor_btn.setMinimumSize(180, 36)
        # Story 4.9 (v1.0.3 hotfix — Owners Council B5): cabeia o botão
        # ao slot ``_on_doctor_clicked`` que invoca ``run_doctor_checks``
        # via import direto + mostra resultado em modal.
        self._doctor_btn.clicked.connect(self._on_doctor_clicked)
        bottom_bar.addWidget(self._doctor_btn)
        bottom_bar.addStretch(1)
        # Story 4.15: caixa alta + minimum size + setDefault(True) garantem
        # visibilidade mesmo se QSS falhar a carregar (frozen build).
        save_label = format_msg("BTN_SAVE_SETTINGS")
        self._save_btn = QPushButton(save_label.upper() if save_label else "SALVAR", self)
        self._save_btn.setObjectName("saveBtn")
        self._save_btn.setProperty("variant", "primary")
        self._save_btn.setMinimumSize(140, 36)
        self._save_btn.setDefault(True)
        self._save_btn.setAutoDefault(True)
        self._save_btn.setToolTip(format_msg("BTN_SAVE_SETTINGS") or "Salvar")
        # Story 4.31 AC10: nome acessível.
        self._save_btn.setAccessibleName("Salvar configurações")
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
        # Timer (parented em self) que esconde o toast após ``duration_ms``.
        # Antes era ``QTimer.singleShot(duration_ms, self._toast.hide)`` órfão —
        # podia disparar após a screen ser destruída → RuntimeError flaky.
        self._toast_hide_timer = QTimer(self)
        self._toast_hide_timer.setSingleShot(True)
        self._toast_hide_timer.timeout.connect(self._toast.hide)

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

        # DLL path — edit + Browse button (Story 4.14, Pichau 2026-05-05).
        # Browse abre QFileDialog (DontUseNativeDialog, ADR-003 amendment M9)
        # para o usuário não precisar saber/colar o path manualmente.
        dll_path_row = QHBoxLayout()
        self._dll_path_edit = QLineEdit(section)
        self._dll_path_edit.setObjectName("dllPathEdit")
        self._dll_path_edit.textEdited.connect(self._mark_dirty)
        # textChanged dispara em qualquer mudança (programática ou usuário) —
        # garante que validação visual reage tanto a Browse quanto a digitação.
        self._dll_path_edit.textChanged.connect(self._update_dll_path_validation)
        dll_path_row.addWidget(self._dll_path_edit, stretch=1)

        self._dll_browse_btn = QPushButton(format_msg("BTN_DLL_BROWSE"), section)
        self._dll_browse_btn.setObjectName("dllBrowseBtn")
        self._dll_browse_btn.setToolTip(format_msg("TOOLTIP_DLL_BROWSE"))
        # Story 4.31 AC10: nome acessível para Narrator/NVDA — o texto
        # visível pode ser "...".
        self._dll_browse_btn.setAccessibleName("Procurar arquivo da ProfitDLL")
        self._dll_browse_btn.clicked.connect(self._on_dll_browse_clicked)
        dll_path_row.addWidget(self._dll_browse_btn)

        dll_path_widget = QWidget(section)
        dll_path_widget.setLayout(dll_path_row)
        form.addRow(QLabel(format_msg("LBL_DLL_PATH") + ":", section), dll_path_widget)

        # Status visual da DLL path (✓ encontrado / ⚠ nome errado / ✗ não existe).
        self._dll_path_status = QLabel("", section)
        self._dll_path_status.setObjectName("dllPathStatus")
        self._dll_path_status.setProperty("role", "muted")
        form.addRow(self._dll_path_status)

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
        # Story 4.31 AC10: nome acessível.
        self._test_conn_btn.setAccessibleName("Testar conexão com a ProfitDLL")
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

        # Story 4.10 v1.0.3 — botões antes ficavam dead (sem clicked.connect).
        # Cabeados a CatalogAdapter.revalidate_checksum / reconcile.
        self._integrity_btn = QPushButton(format_msg("BTN_INTEGRITY_CHECK"), section)
        self._integrity_btn.setObjectName("integrityBtn")
        self._integrity_btn.clicked.connect(self._on_integrity_clicked)
        actions.addWidget(self._integrity_btn)

        self._reconcile_btn = QPushButton(format_msg("BTN_RECONCILE"), section)
        self._reconcile_btn.setObjectName("reconcileSettingsBtn")
        self._reconcile_btn.clicked.connect(self._on_reconcile_clicked)
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
            ("LBL_PERF_CHUNK_SIZE", "1 dia útil (todos os ativos)"),
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
        # DLL path: env > auto-detect > vazio. Story 4.14 (Pichau 2026-05-05):
        # se ``PROFITDLL_PATH`` está vazio, tentamos auto-detect (frozen
        # bundled ou install paths comuns Nelogica) — usuário do .exe não
        # deveria precisar saber/colar o path manualmente.
        dll_path = os.environ.get("PROFITDLL_PATH", "")
        auto_detected = False
        if not dll_path:
            detected = _auto_detect_dll_path()
            if detected is not None:
                dll_path = str(detected)
                auto_detected = True
        self._dll_path_edit.setText(dll_path)
        if auto_detected:
            # Toast curto informando que populamos automaticamente —
            # ``_show_toast`` requer widget visível; defer para depois do
            # show() inicial via QTimer parented em self (não órfão — evita
            # disparo pós-destruição da screen → RuntimeError flaky).
            self._auto_detect_toast_timer = QTimer(self)
            self._auto_detect_toast_timer.setSingleShot(True)
            self._auto_detect_toast_timer.timeout.connect(
                lambda: self._show_toast(
                    format_msg("LBL_DLL_PATH_AUTO_DETECTED"),
                    variant="info",
                    duration_ms=3000,
                )
            )
            self._auto_detect_toast_timer.start(250)

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

        # Data dir: env or default. (Bug 2 fix v1.3.0: usar `default_data_dir()`
        # em vez de `Path.cwd()/data` — Settings/Catalog/Download agora concordam
        # no path canônico `user_data_dir()/data`. `Path.cwd()` é frágil em frozen
        # instalado via Setup — o cwd ao lançar via atalho pode ser System32.)
        from data_downloader._internal.bundle_paths import default_data_dir

        data_dir = os.environ.get("DATA_DOWNLOADER_DATA_DIR") or str(default_data_dir())
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
        db_path = data_dir / "_internal" / "catalog.db"
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
        """Testa conexão DLL — agora rodando em QThread (Wave 3 P1).

        Antes da Wave 3 v1.1.0, esta operação rodava SYNC no MainThread
        (com ``QTimer.singleShot(50, ...)`` apenas para repintar o status
        antes do bloqueio). Felix-UI BIG COUNCIL B3 identificou que
        ``ProfitDLL.initialize_market_only`` + ``wait_market_connected``
        bloqueavam a UI por 1-30s, impedindo o usuário até de mover a
        janela. Agora o trabalho real vai para :class:`_TestConnectionWorker`
        em QThread separada; a UI permanece fluida.
        """
        # Lê credenciais runtime — Save deve ter aplicado em os.environ.
        key = os.environ.get("PROFITDLL_KEY", "").strip()
        user = os.environ.get("PROFITDLL_USER", "").strip()
        pwd = os.environ.get("PROFITDLL_PASS", "").strip()

        self._set_dll_status("testing")
        self._test_conn_btn.setEnabled(False)

        self._dispatch_test_connection_worker(key, user, pwd)

    def _dispatch_test_connection_worker(self, key: str, user: str, password: str) -> None:
        """Cria QThread + worker e os conecta — chamado por
        :meth:`_on_test_connection_clicked`.

        Mantemos referências em ``self`` para evitar GC (regra padrão Qt:
        thread/worker precisam sobreviver até ``finished``). Cleanup é
        idempotente — ``deleteLater`` agendado nos signals.
        """
        self._test_thread = QThread(self)
        self._test_thread.setObjectName("settings-test-connection")
        self._test_worker = _TestConnectionWorker(key, user, password)
        self._test_worker.moveToThread(self._test_thread)

        self._test_thread.started.connect(self._test_worker.run)
        # Qt.QueuedConnection — ``finished`` cruza thread → MainThread.
        self._test_worker.finished.connect(
            self._on_test_connection_finished, Qt.ConnectionType.QueuedConnection
        )
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()

    @Slot(bool, str, str)
    def _on_test_connection_finished(self, ok: bool, version: str, error_msg: str) -> None:
        """Slot MainThread — recebe resultado do worker e atualiza UI."""
        self._test_conn_btn.setEnabled(True)
        if ok:
            self._set_dll_status("connected", version=version or "—")
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
            if error_msg:
                self._dll_empty_hint.setText(f"Erro técnico: {error_msg}")

    # Backward-compat alias — testes antigos podem chamar ``_do_test_connection``
    # diretamente esperando a versão sync. Novo código deve usar
    # ``_on_test_connection_clicked`` (assíncrono via QThread).
    def _do_test_connection(self) -> None:  # pragma: no cover compat
        self._on_test_connection_clicked()

    def _on_open_dll_folder_clicked(self) -> None:
        path_str = self._dll_path_edit.text().strip()
        if not path_str:
            return
        self._open_in_explorer(Path(path_str).parent)

    def _on_dll_browse_clicked(self) -> None:
        """Abre QFileDialog para usuário selecionar ``ProfitDLL.dll`` do disco.

        Story 4.14 (Pichau live test 2026-05-05): usuário pediu botão de
        "buscar" porque não sabia o path completo da DLL para colar.
        Atalho: começa em ``Path(current).parent`` se já há valor; caso
        contrário ``C:\\Program Files`` (Windows install típico Nelogica).

        Filtros do diálogo priorizam ``ProfitDLL (ProfitDLL.dll)`` para
        guiar — usuários avançados podem mudar para *.dll ou All Files.

        ADR-003 amendment M9: usa ``DontUseNativeDialog`` para evitar
        problemas de modal Win32 com PySide6 (mesma flag de ``Mudar Pasta``).
        """
        start_dir = ""
        current = self._dll_path_edit.text().strip()
        if current:
            try:
                parent = Path(current).parent
                if parent.is_dir():
                    start_dir = str(parent)
            except OSError:
                start_dir = ""
        if not start_dir and sys.platform == "win32":
            start_dir = r"C:\Program Files"

        # Story v1.0.5 fix (Pichau live test 2026-05-06): em frozen mode
        # (PyInstaller .exe) ``DontUseNativeDialog`` causa cores bugadas e
        # widget Qt-default sem integração com Windows shell. UX correta no
        # .exe é o diálogo nativo Win32. Em dev/tests mantemos
        # ``DontUseNativeDialog`` para que mocks de ``QFileDialog`` sigam
        # funcionando e para evitar dependência de Win32 shell em CI.
        options: QFileDialog.Option = (
            QFileDialog.Option(0)  # nativo Windows (frozen / .exe)
            if getattr(sys, "frozen", False)
            else QFileDialog.Option.DontUseNativeDialog  # dev / tests
        )
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Selecionar ProfitDLL.dll",
            start_dir,
            "ProfitDLL (ProfitDLL.dll);;DLL Files (*.dll);;All Files (*)",
            "",
            options,
        )
        if file_path:
            self._dll_path_edit.setText(file_path)
            self._mark_dirty()
            self._update_dll_path_validation()

    def _update_dll_path_validation(self) -> None:
        """Atualiza ``_dll_path_status`` com feedback visual do path digitado.

        Estados:
            - vazio → label vazio (neutral, sem ruído).
            - arquivo existe + nome ``profitdll.dll`` (case-insensitive)
              → ✓ verde (success).
            - arquivo existe mas nome diferente → ⚠ ambar (warn).
            - arquivo não existe → ✗ vermelho (error).

        Cores hex inline garantem consistência mesmo se theme não carregou.
        """
        path = self._dll_path_edit.text().strip()
        if not path:
            self._dll_path_status.setText("")
            self._dll_path_status.setStyleSheet("")
            return
        try:
            p = Path(path)
            is_file = p.is_file()
        except OSError:
            is_file = False
            p = Path(path)

        if is_file and p.name.lower() == "profitdll.dll":
            self._dll_path_status.setText("✓ " + format_msg("LBL_DLL_PATH_VALID"))
            self._dll_path_status.setStyleSheet("color: #3FCB6F;")  # success green
        elif is_file:
            self._dll_path_status.setText("⚠ " + format_msg("LBL_DLL_PATH_NOT_DLL"))
            self._dll_path_status.setStyleSheet("color: #F2C04B;")  # warn amber
        else:
            self._dll_path_status.setText("✗ " + format_msg("LBL_DLL_PATH_NOT_FOUND"))
            self._dll_path_status.setStyleSheet("color: #F25656;")  # error red

    def _on_change_data_dir_clicked(self) -> None:
        # Story v1.0.5 fix (Pichau live test 2026-05-06): nativo Win32 em
        # frozen, ``DontUseNativeDialog`` em dev/tests (vide
        # ``_on_dll_browse_clicked`` para racional completo).
        current = self._data_dir_edit.text().strip() or str(Path.cwd())
        options: QFileDialog.Option = (
            QFileDialog.Option(0)
            if getattr(sys, "frozen", False)
            else QFileDialog.Option.DontUseNativeDialog
        )
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de dados",
            current,
            options,
        )
        if folder:
            self._data_dir_edit.setText(folder)
            self._mark_dirty()
            self._refresh_storage_status(Path(folder))

    def _on_open_data_dir_clicked(self) -> None:
        path_str = self._data_dir_edit.text().strip()
        if path_str:
            self._open_in_explorer(Path(path_str))

    # ------------------------------------------------------------------
    # Story 4.10 v1.0.3 — Storage actions (integrity check + reconcile)
    # ------------------------------------------------------------------

    def _on_integrity_clicked(self) -> None:
        """Roda integrity check em QThread (Wave 3 P1 — Felix-UI BIG COUNCIL B4).

        Itera sobre TODAS as partições do catálogo e revalida sha256 de cada
        uma. Em catálogos grandes (>500 partições) o sync bloqueava MainThread
        por segundos — agora rodamos em :class:`_IntegrityWorker` em QThread
        separada e atualizamos UI via signal Queued.
        """
        data_dir_str = self._data_dir_edit.text().strip()
        if not data_dir_str:
            self._show_toast(
                format_msg("TST_SETTINGS_OPERATION_ERROR", error="data_dir vazio"),
                variant="error",
                duration_ms=4000,
            )
            return

        data_dir = Path(data_dir_str)
        self._integrity_btn.setEnabled(False)
        # Toast de progresso aparece imediatamente — UI fluida.
        self._show_toast(
            format_msg("TST_SETTINGS_INTEGRITY_RUNNING", n_partitions="?"),
            variant="info",
            duration_ms=2000,
        )

        self._integrity_thread = QThread(self)
        self._integrity_thread.setObjectName("settings-integrity")
        self._integrity_worker = _IntegrityWorker(data_dir)
        self._integrity_worker.moveToThread(self._integrity_thread)

        self._integrity_thread.started.connect(self._integrity_worker.run)
        self._integrity_worker.finished.connect(
            self._on_integrity_finished, Qt.ConnectionType.QueuedConnection
        )
        self._integrity_worker.finished.connect(self._integrity_thread.quit)
        self._integrity_worker.finished.connect(self._integrity_worker.deleteLater)
        self._integrity_thread.finished.connect(self._integrity_thread.deleteLater)
        self._integrity_thread.start()

    @Slot(int, int, str)
    def _on_integrity_finished(self, n_ok: int, n_total: int, error_msg: str) -> None:
        """Slot MainThread — recebe resultado do integrity worker."""
        self._integrity_btn.setEnabled(True)
        if error_msg:
            self._show_toast(
                format_msg("TST_SETTINGS_OPERATION_ERROR", error=error_msg),
                variant="error",
                duration_ms=5000,
            )
            return
        n_bad = n_total - n_ok
        if n_total == 0 or n_bad == 0:
            self._show_toast(
                format_msg("TST_SETTINGS_INTEGRITY_OK", n_ok=n_ok, n_total=n_total),
                variant="success",
                duration_ms=4000,
            )
        else:
            self._show_toast(
                format_msg(
                    "TST_SETTINGS_INTEGRITY_DRIFT",
                    n_bad=n_bad,
                    n_total=n_total,
                ),
                variant="warning",
                duration_ms=6000,
            )

    def _on_reconcile_clicked(self) -> None:
        """Roda reconcile em QThread (Wave 3 P1 — Felix-UI BIG COUNCIL B4).

        Reconcile abre SQLite + scan disco — pode demorar segundos.
        Movido para :class:`_ReconcileWorker` em QThread, UI fica fluida.
        Toast de progresso aparece imediatamente, toast de resultado vem
        do slot ``_on_reconcile_finished``.
        """
        data_dir_str = self._data_dir_edit.text().strip()
        if not data_dir_str:
            self._show_toast(
                format_msg("TST_SETTINGS_OPERATION_ERROR", error="data_dir vazio"),
                variant="error",
                duration_ms=4000,
            )
            return

        data_dir = Path(data_dir_str)
        self._reconcile_btn.setEnabled(False)
        self._show_toast(
            format_msg("TST_SETTINGS_RECONCILE_RUNNING"),
            variant="info",
            duration_ms=2000,
        )

        self._reconcile_thread = QThread(self)
        self._reconcile_thread.setObjectName("settings-reconcile")
        self._reconcile_worker = _ReconcileWorker(data_dir)
        self._reconcile_worker.moveToThread(self._reconcile_thread)

        self._reconcile_thread.started.connect(self._reconcile_worker.run)
        self._reconcile_worker.finished.connect(
            self._on_reconcile_finished, Qt.ConnectionType.QueuedConnection
        )
        self._reconcile_worker.finished.connect(self._reconcile_thread.quit)
        self._reconcile_worker.finished.connect(self._reconcile_worker.deleteLater)
        self._reconcile_thread.finished.connect(self._reconcile_thread.deleteLater)
        self._reconcile_thread.start()

    @Slot(int, int, str)
    def _on_reconcile_finished(self, n_added: int, n_removed: int, error_msg: str) -> None:
        """Slot MainThread — recebe resultado do reconcile worker."""
        self._reconcile_btn.setEnabled(True)
        if error_msg:
            self._show_toast(
                format_msg("TST_SETTINGS_OPERATION_ERROR", error=error_msg),
                variant="error",
                duration_ms=5000,
            )
            return
        self._show_toast(
            format_msg("TST_RECONCILE_DONE", n_added=n_added, n_removed=n_removed),
            variant="success",
            duration_ms=4000,
        )

    def _on_save_clicked(self) -> None:
        """Persiste config em ~/.data-downloader/config.toml (ADR-012,
        canônico hífen pós-v1.0.5) + credenciais em ~/.data-downloader/.env
        (Story v1.0.3 — Pichau
        2026-05-06: UI digita creds → clica Save → persiste, sem precisar
        criar .env manualmente).

        Credenciais (``PROFITDLL_KEY/USER/PASS/PATH``) vão para arquivo
        separado em user-home — ``_bootstrap_env`` em ``cli.py`` já lê
        ``~/.data-downloader/.env`` como fallback final, então a próxima
        execução do .exe carrega automaticamente. Para a sessão atual,
        também aplicamos via ``os.environ`` (sem reiniciar).
        """
        config_data = {
            "dll_path": self._dll_path_edit.text().strip(),
            "data_dir": self._data_dir_edit.text().strip(),
        }
        env_data: dict[str, str] = {}
        for var_name, (edit, _toggle) in self._env_widgets.items():
            value = edit.text().strip()
            if value:
                env_data[var_name] = value

        try:
            self._write_config(config_data)
            if env_data:
                self._write_env_credentials(env_data)
                # Aplica em runtime — DLL Status pode reconectar sem reinício.
                for k, v in env_data.items():
                    os.environ[k] = v
        except OSError:
            self._show_toast(
                format_msg("TST_TEST_CONNECTION_FAIL"),
                variant="error",
                duration_ms=4000,
            )
            return

        # Story 4.11 v1.0.3 — Após Save, atualizar DLL Status panel se as
        # credenciais ficaram completas (transição "not_configured" →
        # "disconnected"/"configurado, não testado"). Antes só atualizava
        # após click manual em Test Connection.
        self._update_dll_status_after_save()

        self._dirty = False
        self._show_toast(format_msg("TST_SETTINGS_SAVED"), variant="success", duration_ms=3000)
        self._set_state(STATE_SUCCESS)
        # Notifica MainWindow para CatalogScreen recarregar com novo data_dir.
        if config_data["data_dir"]:
            self.data_dir_changed.emit(config_data["data_dir"])
        # Restaura state normal após toast (timer parented em self — ver __init__).
        self._state_restore_timer.start(3000)

    def _write_env_credentials(self, env_data: dict[str, str]) -> None:
        """Escreve credenciais em ~/.data-downloader/.env (formato KEY=value).

        Path alinhado com ``_bootstrap_env`` em ``cli.py`` (3º candidato no
        load order: cwd > exe-dir > ~/.data-downloader). Idempotente —
        sobrescreve o arquivo a cada save (preserva apenas as credenciais
        editadas no UI; outros env vars manuais do usuário NÃO são
        preservados, then-design — Settings UI é fonte da verdade).
        """
        env_dir = Path.home() / ".data-downloader"
        env_dir.mkdir(parents=True, exist_ok=True)
        env_path = env_dir / ".env"
        lines = [
            "# data-downloader credentials (gerado por SettingsScreen)",
            "# Editado via UI Settings → Save. NÃO commitar este arquivo.",
            "",
        ]
        for key in sorted(env_data):  # ordem determinística
            lines.append(f"{key}={env_data[key]}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

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

    def _update_dll_status_after_save(self) -> None:
        """Story 4.11 v1.0.3 — atualiza DLL Status panel após save credenciais.

        Lógica de transição:

            - Se TODOS ``_ENV_VARS`` agora estão em ``os.environ`` (não-vazios)
              + ``dll_path`` existe: status "disconnected" (configurado, não
              testado — usuário ainda precisa clicar Test Connection para
              validar conexão real).
            - Caso contrário: status "not_configured" (faltam credenciais ou
              path inválido).

        Não dispara teste real de conexão (que pode demorar). Apenas reflete
        no UI que as credenciais estão presentes — feedback imediato após
        Save sem precisar clicar Test Connection.
        """
        all_env_present = all(os.environ.get(var, "").strip() for var in _ENV_VARS)
        dll_path_str = self._dll_path_edit.text().strip()
        # Path pode não existir ainda em ambiente de teste — basta string
        # não vazia. Em produção, validate file exists antes de "configurado".
        dll_path_set = bool(dll_path_str)
        if all_env_present and dll_path_set:
            self._set_dll_status("disconnected")
            self._dll_empty_hint.setText("")
        else:
            self._set_dll_status("not_configured")

    # ------------------------------------------------------------------
    # Doctor button (Story 4.9 — v1.0.3 hotfix)
    # ------------------------------------------------------------------

    def _on_doctor_clicked(self) -> None:
        """Invoca ``data-downloader doctor`` e mostra resultado em modal.

        Decisão arquitetural (Story 4.9 — Owners Council B5): em vez de
        usar ``subprocess.run([sys.executable, "-m", "data_downloader.cli",
        "doctor"])`` — que falha em modo frozen porque ``-m`` não funciona
        em PyInstaller bundle e ``sys.executable`` é o próprio .exe da UI
        windowed (sem stdout) — chamamos ``run_doctor_checks`` por import
        direto, capturando o output Rich em ``StringIO`` via Console.

        Vantagens:
            - Funciona idêntico em dev (Python) e frozen (PyInstaller).
            - Sem overhead de spawn de processo.
            - Output Rich preservado (cores via export_text fallback).

        O modal exibe:
            - Sumário com ✓/✗/? counts.
            - Texto bruto em ``QPlainTextEdit`` (read-only, monospace).
        """
        from io import StringIO

        from rich.console import Console as _Console

        # Captura output Rich em buffer.
        buf = StringIO()
        capture_console = _Console(file=buf, force_terminal=False, no_color=True, width=100)

        try:
            # Import lazy — evita custo em initial load (R17).
            from data_downloader.cli import run_doctor_checks

            data_dir = Path(self._data_dir_edit.text().strip() or "data")
            exit_code, results = run_doctor_checks(
                data_dir=data_dir,
                with_handshake=False,  # default — UI usuário não espera 10s.
                console=capture_console,
                verbose=False,
            )
        except Exception as exc:  # pragma: no cover defensive
            exit_code = 2
            results = [("doctor", "FAIL", f"Erro inesperado: {exc}")]
            buf.write(f"\nErro inesperado ao rodar doctor: {exc}\n")

        self._show_doctor_modal(exit_code, results, buf.getvalue())

    def _show_doctor_modal(
        self,
        exit_code: int,
        results: list[tuple[str, str, str]],
        full_output: str,
    ) -> None:
        """Modal não-modal-bloqueante com resultado do doctor.

        Layout:
            [Sumário N PASS / M FAIL / K WARN]
            [QPlainTextEdit read-only com output completo]
            [OK button]
        """
        n_pass = sum(1 for _, s, _ in results if s == "PASS")
        n_fail = sum(1 for _, s, _ in results if s == "FAIL")
        n_warn = sum(1 for _, s, _ in results if s == "WARN")

        dialog = QDialog(self)
        dialog.setWindowTitle(format_msg("BTN_DOCTOR_FULL"))
        dialog.setMinimumSize(720, 480)

        layout = QVBoxLayout(dialog)

        # Sumário (header).
        if exit_code == 0:
            header_text = f"✓ OK — {n_pass} PASS"
            if n_warn:
                header_text += f", {n_warn} WARN"
            header_text += " (sem fails)."
        else:
            header_text = f"✗ FAIL — {n_fail} fail(s), {n_warn} warn(s), {n_pass} pass."
        header = QLabel(header_text, dialog)
        header.setProperty("role", "title")
        layout.addWidget(header)

        # Texto bruto.
        text_view = QPlainTextEdit(dialog)
        text_view.setReadOnly(True)
        text_view.setObjectName("doctorOutputText")
        text_view.setPlainText(full_output)
        layout.addWidget(text_view, stretch=1)

        # Botão OK.
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, parent=dialog)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        # Marker p/ tests integration.
        dialog.setObjectName("doctorDialog")
        dialog.setProperty("doctorExitCode", exit_code)
        dialog.setProperty("doctorPassCount", n_pass)
        dialog.setProperty("doctorFailCount", n_fail)
        dialog.setProperty("doctorWarnCount", n_warn)
        # Guarda referência para tests (qtbot evita garbage collection).
        self._last_doctor_dialog = dialog

        dialog.exec()

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
        """status: connected | disconnected | testing | not_configured.

        Quando ``status != "connected"`` o label "Sobre / Versão DLL" é
        resetado para o placeholder (``—``) para evitar reter uma versão
        fantasma de uma sessão anterior — fix B-2 (Pichau-bug: statusbar
        + about-dll mostravam versão obsoleta em sessões sem credenciais
        válidas).
        """
        self._dll_status_label.setProperty("status", status)
        # Versão resolvida usada tanto no label de status quanto no signal.
        resolved_version = version or "—"
        if status == "connected":
            self._dll_status_label.setText(
                format_msg("LBL_DLL_STATUS_CONNECTED", version=resolved_version)
            )
            self._about_dll_label.setText(
                format_msg("LBL_ABOUT_DLL_VERSION", version=resolved_version)
            )
        elif status == "disconnected":
            self._dll_status_label.setText(format_msg("LBL_DLL_STATUS_DISCONNECTED"))
            # Fix B-2: reset about-dll label para não reter versão antiga.
            self._about_dll_label.setText(format_msg("LBL_ABOUT_DLL_VERSION", version="—"))
        elif status == "testing":
            self._dll_status_label.setText(format_msg("LBL_DLL_STATUS_TESTING"))
            # Fix B-2: reset about-dll durante teste — evita exibir versão
            # de tentativa anterior enquanto o worker ainda está rodando.
            self._about_dll_label.setText(format_msg("LBL_ABOUT_DLL_VERSION", version="—"))
            self._set_state(STATE_LOADING)
        elif status == "not_configured":
            self._dll_status_label.setText(format_msg("LBL_DLL_STATUS_NOT_CONFIGURED"))
            # Fix B-2: reset about-dll quando .env desaparece / nunca foi
            # configurado — caso clássico do Pichau-bug.
            self._about_dll_label.setText(format_msg("LBL_ABOUT_DLL_VERSION", version="—"))
            self._set_state(STATE_EMPTY)

        self._dll_status_label.style().unpolish(self._dll_status_label)
        self._dll_status_label.style().polish(self._dll_status_label)
        # Fix B-1: emitir versão real (resolvida) ao invés de só status —
        # MainWindow consome para popular statusbar sem hardcode "?".
        self.dll_status_changed.emit(status, resolved_version)

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
        self._toast_hide_timer.start(duration_ms)
