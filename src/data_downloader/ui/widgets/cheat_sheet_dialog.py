"""data_downloader.ui.widgets.cheat_sheet_dialog — Modal de atalhos (Ctrl+/).

Owner: Uma (ux-design-expert) | Wave 3 v1.1.0 follow-up de Story 4.13.

Diretiva Pichau: discoverability gap. Story 4.13 implementou shortcuts em
todas as telas, mas nenhuma UI explorável existia para usuário descobrir os
atalhos. ``CheatSheetDialog`` resolve isso: ``Ctrl+/`` global em
:class:`MainWindow` abre este modal listando todos os atalhos canônicos.

Lista canônica vive em :data:`SHORTCUTS` — mantenha em sync com:

    - ``main_window.py::_register_global_shortcuts``
    - ``download_screen.py::_register_shortcuts``
    - ``settings_screen.py::_register_shortcuts``
    - ``catalog_screen.py::_register_shortcuts`` (Story 3.2 — Ctrl+R/F)
    - ``docs/ux/THEME.md §6``

Princípios (R17 — Uma):

    - **Microcopy clara em pt-BR** (sem jargão "shortcut").
    - **Não-editável** — usuário só lê (``EditTrigger.NoEditTriggers``).
    - **Hierarquia visual** — atalho em column 0 monospace-like, ação em col 1.
    - **Fechamento óbvio** — botão "Fechar" como default action (Enter aceita).

Footprint testes: ``tests/unit/ui/test_cheat_sheet_dialog.py``.

Referências:
    - docs/ux/THEME.md §6 (atalhos canônicos)
    - docs/ux/QT_PATTERNS.md §6 (atalhos Qt)
    - docs/stories/v1.1.0-master-plan.md (Wave 3 — Uma P1)
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

__all__ = ["SHORTCUTS", "CheatSheetDialog"]


# Lista canônica de shortcuts (atalho, descrição em pt-BR).
#
# Estrutura plana — agrupamento visual via headers seria cosmético em V2.
# Para v1.1.0 priorizamos discoverability simples: tabela 2 colunas, sem
# tabs ou sub-grupos (PRINCIPLES.md §1 — golden path 1 clique).
SHORTCUTS: tuple[tuple[str, str], ...] = (
    # Globais (Qt.ApplicationShortcut)
    ("Ctrl+/", "Abrir esta lista de atalhos"),
    ("Ctrl+,", "Abrir Configurações"),
    ("Ctrl+D", "Ir para tela Download"),
    ("Ctrl+B", "Ir para tela Catálogo"),
    ("Ctrl+Q", "Sair (com confirmação se download ativo)"),
    # DownloadScreen (Qt.WidgetWithChildrenShortcut)
    ("Ctrl+C", "Cancelar download em andamento"),
    ("Esc", "Cancelar download / fechar modal ativo"),
    # CatalogScreen (Qt.WidgetWithChildrenShortcut)
    ("Ctrl+R", "Atualizar lista do catálogo"),
    ("Ctrl+F", "Buscar/filtrar catálogo"),
    ("Delete", "Apagar entrada selecionada"),
    # SettingsScreen
    ("Ctrl+S", "Salvar configurações"),
)


class CheatSheetDialog(QDialog):
    """Modal não-bloqueante listando atalhos canônicos da UI.

    Trigger: ``Ctrl+/`` global em :class:`MainWindow`.

    Tamanho mínimo 420x360 garante leitura confortável; usuário pode
    redimensionar se quiser ver mais atalhos sem scroll (V2 expande).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("cheatSheetDialog")
        self.setWindowTitle("Atalhos de Teclado")
        self.setMinimumSize(420, 360)
        # Modal — bloqueia interação com MainWindow até fechar (UX padrão
        # de "ajuda contextual"). Não-modal seria confuso (usuário poderia
        # esquecer que abriu).
        self.setModal(True)

        layout = QVBoxLayout(self)

        # Título — auxilia screen-readers + reforça contexto visual.
        title = QLabel("Atalhos de Teclado", self)
        title.setObjectName("cheatSheetTitle")
        title.setStyleSheet("font-size: 14pt; font-weight: 600; padding: 4px;")
        layout.addWidget(title)

        # Subtítulo descritivo (microcopy R17).
        subtitle = QLabel(
            "Atalhos disponíveis em qualquer tela. Sequências globais "
            "funcionam mesmo sem foco específico.",
            self,
        )
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Tabela — duas colunas, sem grade pesada (visual leve).
        self._table = QTableWidget(len(SHORTCUTS), 2, self)
        self._table.setObjectName("cheatSheetTable")
        self._table.setHorizontalHeaderLabels(["Atalho", "Ação"])
        self._table.verticalHeader().setVisible(False)
        # Read-only — usuário não edita atalhos aqui (V2 talvez customizar).
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Visual cleaner — sem alternating rows (poucos itens).
        self._table.setShowGrid(False)

        for row, (key, desc) in enumerate(SHORTCUTS):
            item_key = QTableWidgetItem(key)
            item_key.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item_desc = QTableWidgetItem(desc)
            item_desc.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(row, 0, item_key)
            self._table.setItem(row, 1, item_desc)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._table)

        # Botão Fechar — default action, Enter aceita.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._close_btn = QPushButton("Fechar", self)
        self._close_btn.setObjectName("cheatSheetCloseBtn")
        self._close_btn.setDefault(True)
        self._close_btn.setAutoDefault(True)
        self._close_btn.setMinimumSize(120, 32)
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)
