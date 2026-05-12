"""Unit tests — CheatSheetDialog (Wave 3 v1.1.0 — Uma).

Cobertura mínima:
    - Dialog instancia sem crash em headless (offscreen).
    - Tabela tem N linhas == ``len(SHORTCUTS)``.
    - ``accept()`` fecha o dialog (close button wired).
    - SHORTCUTS lista contém atalhos críticos (Ctrl+/, Ctrl+,, Ctrl+S, Esc).

Headless: pytest-qt usa ``QT_QPA_PLATFORM=offscreen`` setado antes do
import PySide6 (mesmo padrão de ``tests/integration/test_ui_main_window.py``).
"""

from __future__ import annotations

import os

import pytest

# Forçar offscreen ANTES de qualquer import PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def cheat_sheet_dialog(qtbot):
    """Instancia ``CheatSheetDialog`` com cleanup automático via qtbot."""
    from data_downloader.ui.widgets.cheat_sheet_dialog import CheatSheetDialog

    dlg = CheatSheetDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_dialog_instantiates_without_error(cheat_sheet_dialog):
    """Smoke — dialog constrói sem exception."""
    assert cheat_sheet_dialog is not None
    assert cheat_sheet_dialog.windowTitle() == "Atalhos de Teclado"
    assert cheat_sheet_dialog.objectName() == "cheatSheetDialog"


def test_dialog_is_modal(cheat_sheet_dialog):
    """Modal — bloqueia interação com parent até fechar (UX padrão help)."""
    assert cheat_sheet_dialog.isModal()


def test_dialog_table_has_all_shortcuts(cheat_sheet_dialog):
    """Tabela renderiza N linhas == len(SHORTCUTS)."""
    from data_downloader.ui.widgets.cheat_sheet_dialog import SHORTCUTS

    table = cheat_sheet_dialog.findChild(type(cheat_sheet_dialog._table), "cheatSheetTable")
    assert table is not None
    assert table.rowCount() == len(SHORTCUTS)
    assert table.columnCount() == 2


def test_dialog_table_cells_match_shortcuts(cheat_sheet_dialog):
    """Cada célula (atalho, ação) corresponde à entry em SHORTCUTS."""
    from data_downloader.ui.widgets.cheat_sheet_dialog import SHORTCUTS

    table = cheat_sheet_dialog._table
    for row, (key, desc) in enumerate(SHORTCUTS):
        item_key = table.item(row, 0)
        item_desc = table.item(row, 1)
        assert item_key is not None, f"Linha {row} sem item de atalho"
        assert item_desc is not None, f"Linha {row} sem item de descrição"
        assert item_key.text() == key
        assert item_desc.text() == desc


def test_close_button_accepts_dialog(cheat_sheet_dialog, qtbot):
    """Click em ``Fechar`` chama ``accept()`` e fecha o dialog."""
    from PySide6.QtCore import Qt

    cheat_sheet_dialog.show()
    qtbot.waitExposed(cheat_sheet_dialog)
    assert cheat_sheet_dialog.isVisible()

    qtbot.mouseClick(cheat_sheet_dialog._close_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert not cheat_sheet_dialog.isVisible()


def test_shortcuts_list_includes_critical_bindings():
    """SHORTCUTS canônica deve conter atalhos essenciais (regressão)."""
    from data_downloader.ui.widgets.cheat_sheet_dialog import SHORTCUTS

    keys = {key for key, _desc in SHORTCUTS}
    # Atalhos não-negociáveis para v1.1.0 (THEME.md §6).
    for required in ("Ctrl+/", "Ctrl+,", "Ctrl+D", "Ctrl+B", "Ctrl+S", "Ctrl+Q", "Esc"):
        assert required in keys, f"Atalho crítico faltando em SHORTCUTS: {required}"


def test_table_is_read_only(cheat_sheet_dialog):
    """Tabela é não-editável (R17 — atalhos não customizáveis em V1)."""
    from PySide6.QtWidgets import QTableWidget

    table = cheat_sheet_dialog._table
    assert table.editTriggers() == QTableWidget.EditTrigger.NoEditTriggers
