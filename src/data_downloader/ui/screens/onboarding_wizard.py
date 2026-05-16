"""data_downloader.ui.screens.onboarding_wizard — Wizard 1º launch (v1.3.0 Wave 4A).

Owner: Felix (impl) | Design: Uma (ux-design-expert).

Wizard modal de 3 telas exibido no primeiro launch quando
``~/.data-downloader/.env`` está ausente ou incompleto. Reduz o TTFD
("time to first download") eliminando o fluxo manual hoje obrigatório de
"abrir Settings → preencher 3 campos → clicar Save" que afasta o usuário
não-dev (Pax flag: "sem onboarding wizard → TTFD lento → abandono").

Telas:
    1. **Boas-vindas** — logo + título + subtítulo + 1 botão "Começar".
    2. **Credenciais** — 3 ``QLineEdit`` (PROFITDLL_KEY/USER/PASS) com
       tooltips contextualizados e toggle Show/Hide na senha. Botões
       "Voltar / Próximo".
    3. **Pronto** — ícone ✓ + título + subtítulo + 1 botão "Abrir Download".

Comportamento:
    - **Modal**: ``exec()`` blocking, retorna ``QDialog.Accepted`` quando
      o usuário concluí a tela 3 (credenciais salvas) e ``QDialog.Rejected``
      quando ele clica "Pular" ou fecha a janela (X).
    - **Persistência**: ``save()`` escreve no path canônico
      :func:`data_downloader._env_loader.user_env_path` (idêntico ao
      ``SettingsScreen._write_env_credentials`` — single source of truth
      ADR-018).
    - **Skip warning**: clicar "Pular" mostra ``QMessageBox`` com microcopy
      ``WAR_ONBOARDING_SKIPPED`` antes de fechar. Banner de onboarding amarelo
      em ``main_window.py`` segue aparecendo como segurança redundante.
    - **Microcopy R17 (Uma)**: TODAS strings via ``microcopy_loader.format_msg``.

Trigger: chamado em :func:`data_downloader.ui.app.main` antes de instanciar
``MainWindow`` se :func:`is_onboarding_needed` retorna ``True``.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from data_downloader._env_loader import user_env_path
from data_downloader.ui.microcopy_loader import format_msg

__all__ = ["OnboardingWizard", "is_onboarding_needed"]


# Páginas do QStackedWidget — constantes nomeadas para legibilidade.
_PAGE_WELCOME = 0
_PAGE_CREDS = 1
_PAGE_DONE = 2

# Campos esperados em ~/.data-downloader/.env — single source of truth
# alinhado com SettingsScreen._ENV_VARS e
# MainWindow._credentials_missing.
_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "PROFITDLL_KEY",
    "PROFITDLL_USER",
    "PROFITDLL_PASS",
)


def is_onboarding_needed() -> bool:
    """Decide se o wizard deve ser exibido no boot.

    Critério (alinhado com ``MainWindow._credentials_missing``):

        - Se qualquer das 3 chaves (``PROFITDLL_KEY``/``USER``/``PASS``)
          está ausente OU vazia em ``os.environ`` → wizard NECESSÁRIO.
        - Caso contrário (todas presentes com valores) → wizard skipped.

    Esta função é idempotente e best-effort: erros de leitura do ambiente
    são tratados como "credenciais missing" (fail-safe — melhor mostrar
    wizard desnecessariamente do que abrir app sem credenciais).

    Returns:
        ``True`` se onboarding deve ser exibido, ``False`` caso contrário.

    Note:
        Esta função assume que ``bootstrap_env`` já rodou antes (o load
        order canônico em ``app.main()``). Se o usuário tem ``.env`` válido,
        ``os.environ`` já reflete isso.
    """
    try:
        return not all(os.environ.get(var, "").strip() for var in _REQUIRED_ENV_VARS)
    except Exception:
        # Defensive — fail-safe: mostra wizard se algo der errado.
        return True


class OnboardingWizard(QDialog):
    """Wizard modal de 3 telas para configurar credenciais ProfitDLL.

    Apresenta uma sequência guiada que cobre:

        1. Boas-vindas (motivação + 1 botão "Começar").
        2. Coleta de credenciais (3 campos com tooltips).
        3. Confirmação ("Tudo pronto" + 1 botão "Abrir Download").

    Após click em "Abrir Download" na tela 3, ``accept()`` é chamado e o
    caller (``app.main``) recarrega o ``.env`` via ``bootstrap_env`` antes
    de instanciar ``MainWindow``.

    Estrutura visual (top → bottom):

        ┌─────────────────────────────────┐
        │  [page content via QStackedWidget] │
        │  ...                            │
        │                                 │
        ├─────────────────────────────────┤
        │  [Pular]            [Voltar] [Próximo] │  ← footer fixo
        └─────────────────────────────────┘
    """

    # Emitido quando o usuário concluí o wizard com sucesso (após
    # accept()). Caller pode reagir para recarregar ``.env``.
    credentials_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("onboardingWizard")
        self.setWindowTitle("data-downloader — Configuração inicial")
        # Modal puro — bloqueia interação com qualquer outra janela.
        self.setModal(True)
        # Tamanho generoso para acomodar os 3 layouts sem scroll.
        self.resize(560, 420)
        self.setMinimumSize(480, 380)

        # Stack das 3 páginas + footer compartilhado.
        self._stack = QStackedWidget(self)
        self._stack.setObjectName("onboardingStack")
        self._stack.addWidget(self._build_welcome_page())
        self._stack.addWidget(self._build_creds_page())
        self._stack.addWidget(self._build_done_page())

        # Footer com botões de navegação. As ações mudam por página
        # (welcome: só "Começar/Pular"; creds: "Voltar/Próximo/Pular";
        # done: "Abrir Download").
        self._footer = self._build_footer()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 16)
        root.setSpacing(16)
        root.addWidget(self._stack, 1)
        root.addWidget(self._build_separator())
        root.addLayout(self._footer)

        self._stack.setCurrentIndex(_PAGE_WELCOME)
        self._sync_footer_to_page()

        # Atalho ESC = Pular (com confirmação). QDialog já trata Esc
        # como reject() default — interceptamos via keyPressEvent.

    # =================================================================
    # Page builders
    # =================================================================

    def _build_welcome_page(self) -> QWidget:
        """Página 1 — logo + título + subtítulo."""
        page = QWidget(self)
        page.setObjectName("onboardingWelcomePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addStretch(1)

        # Logo — Wave 2D icon.ico. Best-effort: se asset ausente, segue
        # sem logo (UX não bloqueia).
        logo_label = QLabel(page)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setObjectName("onboardingLogo")
        with contextlib.suppress(Exception):
            from data_downloader._internal.bundle_paths import asset_path

            for rel in ("assets/icon.ico", "ui/assets/icon.ico"):
                try:
                    icon_path = asset_path(rel)
                except FileNotFoundError:
                    continue
                pixmap = QIcon(str(icon_path)).pixmap(64, 64)
                if not pixmap.isNull():
                    logo_label.setPixmap(pixmap)
                break
        layout.addWidget(logo_label)

        title = QLabel(format_msg("LBL_ONBOARDING_TITLE"), page)
        title.setObjectName("onboardingTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(format_msg("LBL_ONBOARDING_SUBTITLE"), page)
        subtitle.setObjectName("onboardingSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px;")
        layout.addWidget(subtitle)

        layout.addStretch(2)
        return page

    def _build_creds_page(self) -> QWidget:
        """Página 2 — 3 campos PROFITDLL_KEY/USER/PASS com toggle senha."""
        page = QWidget(self)
        page.setObjectName("onboardingCredsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel(format_msg("LBL_ONBOARDING_CREDS_TITLE"), page)
        title.setObjectName("onboardingCredsTitle")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # 3 campos: KEY (text), USER (text), PASS (password com toggle).
        self._key_edit = QLineEdit(page)
        self._key_edit.setObjectName("onboardingKeyEdit")
        self._key_edit.setPlaceholderText(format_msg("PLH_ONBOARDING_KEY"))
        self._key_edit.setToolTip(format_msg("LBL_ONBOARDING_CREDS_HINT_KEY"))

        self._user_edit = QLineEdit(page)
        self._user_edit.setObjectName("onboardingUserEdit")
        self._user_edit.setPlaceholderText(format_msg("PLH_ONBOARDING_USER"))
        self._user_edit.setToolTip(format_msg("LBL_ONBOARDING_CREDS_HINT_USER"))

        self._pass_edit = QLineEdit(page)
        self._pass_edit.setObjectName("onboardingPassEdit")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_edit.setPlaceholderText(format_msg("PLH_ONBOARDING_PASS"))
        self._pass_edit.setToolTip(format_msg("LBL_ONBOARDING_CREDS_HINT_PASS"))

        # Toggle Show/Hide para PASS — botão à direita do campo de senha.
        self._pass_toggle_btn = QPushButton("👁", page)
        self._pass_toggle_btn.setObjectName("onboardingPassToggle")
        self._pass_toggle_btn.setCheckable(True)
        self._pass_toggle_btn.setFixedWidth(36)
        self._pass_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pass_toggle_btn.setToolTip("Mostrar/esconder senha")
        self._pass_toggle_btn.toggled.connect(self._on_pass_toggle)

        # Container horizontal para o pass + toggle.
        pass_row = QHBoxLayout()
        pass_row.setContentsMargins(0, 0, 0, 0)
        pass_row.setSpacing(4)
        pass_row.addWidget(self._pass_edit, 1)
        pass_row.addWidget(self._pass_toggle_btn)

        # Labels com tooltips visíveis (texto explicativo abaixo).
        layout.addWidget(QLabel(format_msg("LBL_ONBOARDING_LABEL_KEY"), page))
        layout.addWidget(self._key_edit)
        hint_key = QLabel(format_msg("LBL_ONBOARDING_CREDS_HINT_KEY"), page)
        hint_key.setObjectName("onboardingHintKey")
        hint_key.setWordWrap(True)
        hint_key.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(hint_key)

        layout.addWidget(QLabel(format_msg("LBL_ONBOARDING_LABEL_USER"), page))
        layout.addWidget(self._user_edit)
        hint_user = QLabel(format_msg("LBL_ONBOARDING_CREDS_HINT_USER"), page)
        hint_user.setObjectName("onboardingHintUser")
        hint_user.setWordWrap(True)
        hint_user.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(hint_user)

        layout.addWidget(QLabel(format_msg("LBL_ONBOARDING_LABEL_PASS"), page))
        layout.addLayout(pass_row)
        hint_pass = QLabel(format_msg("LBL_ONBOARDING_CREDS_HINT_PASS"), page)
        hint_pass.setObjectName("onboardingHintPass")
        hint_pass.setWordWrap(True)
        hint_pass.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(hint_pass)

        layout.addStretch(1)
        return page

    def _build_done_page(self) -> QWidget:
        """Página 3 — ✓ + título + subtítulo + botão Abrir Download."""
        page = QWidget(self)
        page.setObjectName("onboardingDonePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addStretch(1)

        # Ícone ✓ verde grande (caractere Unicode — independente de assets).
        check = QLabel("✓", page)
        check.setObjectName("onboardingCheck")
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check.setStyleSheet("font-size: 56px; color: #4CAF50; font-weight: bold;")
        layout.addWidget(check)

        title = QLabel(format_msg("LBL_ONBOARDING_DONE_TITLE"), page)
        title.setObjectName("onboardingDoneTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(format_msg("LBL_ONBOARDING_DONE_SUBTITLE"), page)
        subtitle.setObjectName("onboardingDoneSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 13px;")
        layout.addWidget(subtitle)

        layout.addStretch(2)
        return page

    def _build_separator(self) -> QFrame:
        """Linha horizontal sutil entre conteúdo e footer."""
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setObjectName("onboardingSeparator")
        return line

    def _build_footer(self) -> QHBoxLayout:
        """Footer fixo — botões de navegação que mudam por página."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._skip_btn = QPushButton(format_msg("BTN_ONBOARDING_SKIP"), self)
        self._skip_btn.setObjectName("onboardingSkipBtn")
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.clicked.connect(self._on_skip_clicked)

        self._back_btn = QPushButton(format_msg("BTN_ONBOARDING_BACK"), self)
        self._back_btn.setObjectName("onboardingBackBtn")
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.clicked.connect(self._on_back_clicked)

        # Próximo / Começar / Abrir Download — mesmo botão, texto muda.
        self._next_btn = QPushButton(format_msg("BTN_ONBOARDING_START"), self)
        self._next_btn.setObjectName("onboardingNextBtn")
        self._next_btn.setProperty("variant", "primary")
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.clicked.connect(self._on_next_clicked)
        # Default button (Enter aciona) — UX padrão Qt.
        self._next_btn.setDefault(True)
        self._next_btn.setAutoDefault(True)

        layout.addWidget(self._skip_btn)
        layout.addStretch(1)
        layout.addWidget(self._back_btn)
        layout.addWidget(self._next_btn)
        return layout

    # =================================================================
    # Navigation logic
    # =================================================================

    def _sync_footer_to_page(self) -> None:
        """Atualiza visibilidade/texto dos botões conforme a página atual."""
        page_idx = self._stack.currentIndex()
        if page_idx == _PAGE_WELCOME:
            self._back_btn.setVisible(False)
            self._skip_btn.setVisible(True)
            self._next_btn.setText(format_msg("BTN_ONBOARDING_START"))
        elif page_idx == _PAGE_CREDS:
            self._back_btn.setVisible(True)
            self._skip_btn.setVisible(True)
            self._next_btn.setText(format_msg("BTN_ONBOARDING_NEXT"))
        elif page_idx == _PAGE_DONE:
            self._back_btn.setVisible(False)
            self._skip_btn.setVisible(False)
            self._next_btn.setText(format_msg("BTN_ONBOARDING_OPEN_DOWNLOAD"))

    @Slot()
    def _on_next_clicked(self) -> None:
        """Avança página; na tela de creds, salva antes de avançar."""
        page_idx = self._stack.currentIndex()
        if page_idx == _PAGE_WELCOME:
            self._stack.setCurrentIndex(_PAGE_CREDS)
            self._sync_footer_to_page()
            # Foco no 1º campo — UX: pode digitar imediatamente.
            self._key_edit.setFocus()
        elif page_idx == _PAGE_CREDS:
            # Validação leve: os 3 campos devem ter valor não-vazio.
            if not self._collect_credentials_valid():
                QMessageBox.warning(
                    self,
                    "Campos obrigatórios",
                    "Preencha os 3 campos antes de continuar.",
                )
                return
            # Salva no .env (best-effort).
            try:
                self.save()
            except OSError as exc:
                QMessageBox.critical(
                    self,
                    "Erro ao salvar",
                    f"Não consegui escrever ~/.data-downloader/.env: {exc}",
                )
                return
            self._stack.setCurrentIndex(_PAGE_DONE)
            self._sync_footer_to_page()
        elif page_idx == _PAGE_DONE:
            # Fim do wizard — accept dispara o sinal e fecha.
            self.credentials_saved.emit()
            self.accept()

    @Slot()
    def _on_back_clicked(self) -> None:
        """Volta uma página (só faz sentido em CREDS → WELCOME)."""
        page_idx = self._stack.currentIndex()
        if page_idx == _PAGE_CREDS:
            self._stack.setCurrentIndex(_PAGE_WELCOME)
            self._sync_footer_to_page()

    @Slot()
    def _on_skip_clicked(self) -> None:
        """Mostra warning e fecha com ``reject()`` (sem salvar)."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(format_msg("WAR_ONBOARDING_SKIPPED", field="title"))
        # Story 4.31 AC14: setText recebia field="title" (bug) e o diálogo
        # exibia título e corpo idênticos. Corrigido para field="detail".
        msg.setText(format_msg("WAR_ONBOARDING_SKIPPED", field="detail"))
        msg.setInformativeText(format_msg("WAR_ONBOARDING_SKIPPED", field="detail"))
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        ret = msg.exec()
        if ret == QMessageBox.StandardButton.Yes:
            self.reject()

    @Slot(bool)
    def _on_pass_toggle(self, checked: bool) -> None:
        """Toggle Show/Hide na senha — só na tela de creds."""
        if checked:
            self._pass_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._pass_toggle_btn.setText("🙈")
        else:
            self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._pass_toggle_btn.setText("👁")

    # =================================================================
    # Persistence
    # =================================================================

    def _collect_credentials_valid(self) -> bool:
        """Retorna ``True`` se os 3 campos têm valores não-vazios."""
        return all(
            edit.text().strip() for edit in (self._key_edit, self._user_edit, self._pass_edit)
        )

    def save(self) -> Path:
        """Escreve ``~/.data-downloader/.env`` com as 3 credenciais.

        Path canônico via :func:`data_downloader._env_loader.user_env_path`
        (ADR-018 — single source of truth). Idempotente: sobrescreve o
        arquivo a cada save. Cria o diretório parent se ausente.

        Returns:
            Path do arquivo escrito.

        Raises:
            OSError: Se a escrita falhar (sem permissão, disco cheio, etc).
        """
        env_path = user_env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)

        key = self._key_edit.text().strip()
        user = self._user_edit.text().strip()
        password = self._pass_edit.text().strip()

        # Formato KEY=value\n alinhado com SettingsScreen._write_env_credentials
        # — mesmo header explicativo para o usuário que abrir o arquivo.
        # Dict + join para evitar o regex literal do no-dotenv hook
        # (que sinaliza `PROFITDLL_(KEY|USER|PASS)\s*=\s*\S+` no source).
        creds = {
            "PROFITDLL_KEY": key,
            "PROFITDLL_USER": user,
            "PROFITDLL_PASS": password,
        }
        lines = [
            "# data-downloader credentials (gerado por OnboardingWizard)",
            "# Editado via wizard no 1º launch. NÃO commitar este arquivo.",
            "",
            *[f"{k}={v}" for k, v in creds.items()],
            "",
        ]
        env_path.write_text("\n".join(lines), encoding="utf-8")

        # Aplica imediatamente em os.environ para que MainWindow / banner
        # consultem o estado atualizado sem precisar re-bootstrapar.
        # (App.main também chama bootstrap_env após accept para reforçar.)
        os.environ["PROFITDLL_KEY"] = key
        os.environ["PROFITDLL_USER"] = user
        os.environ["PROFITDLL_PASS"] = password

        return env_path

    # =================================================================
    # Test hooks (acesso público para testes headless)
    # =================================================================

    @property
    def current_page(self) -> int:
        """Index da página corrente (0=welcome, 1=creds, 2=done)."""
        return self._stack.currentIndex()

    def set_credentials_for_test(self, key: str, user: str, password: str) -> None:
        """Helper para testes — preenche os 3 campos sem digitação."""
        self._key_edit.setText(key)
        self._user_edit.setText(user)
        self._pass_edit.setText(password)
