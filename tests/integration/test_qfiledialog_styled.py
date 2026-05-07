"""Integration tests — QFileDialog defense-in-depth styling (Story v1.0.5).

Owner: Felix (impl) | Design: Uma (theme authority).

Contexto:
    Em frozen builds (Fix 4 — Dex), QFileDialog usa o dialog nativo Windows,
    que ignora QSS e mantém aparência consistente do SO.

    Em dev mode / tests, porém, o app aciona `DontUseNativeDialog` para
    evitar deadlocks Qt em ambientes específicos. Sem regras dedicadas no
    QSS, os widgets nested (QListView/QHeaderView/QToolButton/...) herdam
    paleta light default do Fusion e quebram o tema dark do app.

    Estes testes garantem que `style.qss` contém regras defense-in-depth
    para QFileDialog e seus widgets nested. Visual snapshot ficou para v1.1.

Headless via QT_QPA_PLATFORM=offscreen (alinhado com test_ui_theming.py).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qss_text() -> str:
    """Carrega o arquivo QSS uma vez por módulo."""
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "data_downloader"
        / "ui"
        / "assets"
        / "style.qss"
    )
    assert path.exists(), f"QSS não encontrado em {path}"
    return path.read_text(encoding="utf-8")


# =====================================================================
# Defense-in-depth — QFileDialog nested widgets
# =====================================================================


def test_qss_includes_qfiledialog_rules(qss_text: str) -> None:
    """Regras dedicadas a QFileDialog devem existir no QSS.

    QFileDialog tem especificidade própria — sem seletor explícito,
    descendentes herdam estilos default do Fusion (claros) que quebram
    tema dark.
    """
    assert "QFileDialog" in qss_text, (
        "QSS não contém nenhuma regra para QFileDialog. "
        "Defense-in-depth da Story v1.0.5 exige seletor dedicado."
    )


def test_qss_styles_filedialog_listview_treeview(qss_text: str) -> None:
    """Lista de arquivos (QListView/QTreeView/QTableView) sob QFileDialog/QDialog."""
    assert re.search(
        r"QFileDialog\s+QListView", qss_text
    ), "Lista de arquivos do QFileDialog precisa de regra QSS."
    assert re.search(
        r"QFileDialog\s+QTreeView", qss_text
    ), "View hierárquica do QFileDialog precisa de regra QSS."
    # QDialog também deve aparecer (cobre QMessageBox e custom dialogs).
    assert re.search(r"QDialog\s+QListView", qss_text)


def test_qss_styles_filedialog_headerview(qss_text: str) -> None:
    """Header de colunas (Name/Size/Date Modified) precisa de regra dedicada."""
    assert re.search(r"QFileDialog\s+QHeaderView::section", qss_text), (
        "Header do QFileDialog precisa estilizar ::section para "
        "manter coerência com QTableView do CatalogScreen."
    )


def test_qss_styles_filedialog_toolbutton(qss_text: str) -> None:
    """Botões back/forward/parent-dir são QToolButton."""
    assert re.search(
        r"QFileDialog\s+QToolButton", qss_text
    ), "QToolButton (navegação back/forward) sob QFileDialog precisa de regra."
    # Estados visuais mínimos — pelo menos hover deve estar presente.
    assert re.search(
        r"QFileDialog\s+QToolButton:hover", qss_text
    ), "QToolButton:hover ausente — affordance interativa quebrada."


def test_qss_styles_filedialog_splitter(qss_text: str) -> None:
    """Splitter sidebar do QFileDialog (Quick Access ↔ files)."""
    assert re.search(
        r"QFileDialog\s+QSplitter::handle", qss_text
    ), "QSplitter::handle sob QFileDialog precisa de regra."


def test_qss_styles_filedialog_combobox_lineedit(qss_text: str) -> None:
    """File-type filter (QComboBox) e file name input (QLineEdit)."""
    assert re.search(
        r"QFileDialog\s+QComboBox", qss_text
    ), "QComboBox (file-type filter) sob QFileDialog precisa de regra."
    assert re.search(
        r"QFileDialog\s+QLineEdit", qss_text
    ), "QLineEdit (file name input) sob QFileDialog precisa de regra."


def test_qss_filedialog_uses_dark_palette(qss_text: str) -> None:
    """Cores aplicadas a QFileDialog devem ser do tema dark canônico."""
    # Capturar o bloco da seção 19 (defense-in-depth) ou todas regras que
    # mencionam QFileDialog.
    filedialog_rules = re.findall(
        r"(?:QFileDialog|QDialog\s+\w+)[^{]*\{[^}]*\}",
        qss_text,
        flags=re.DOTALL,
    )
    assert filedialog_rules, "Nenhum bloco de QFileDialog/QDialog encontrado."

    combined = "\n".join(filedialog_rules).upper()
    # Pelo menos um background dark canônico deve estar presente.
    dark_bg_tokens = {"#0E0E10", "#17171A", "#1F1F23", "#26262B"}
    assert any(token in combined for token in dark_bg_tokens), (
        "QFileDialog rules devem usar background da paleta dark " f"(um de {dark_bg_tokens})."
    )
    # Texto primário canônico.
    assert "#E8E8EA" in combined, "QFileDialog deve usar text.primary #E8E8EA."


def test_qss_filedialog_rules_dont_break_global_qss(qtbot):
    """QSS aplicado em QApplication.setStyleSheet sem crash + smoke QFileDialog.

    Garante que as novas regras da seção 19 não introduzem erro de parsing
    ou specificidade conflitante que derrube widgets nested.
    """
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
    )

    qss_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "data_downloader"
        / "ui"
        / "assets"
        / "style.qss"
    )
    qss = qss_path.read_text(encoding="utf-8")

    app = QApplication.instance()
    assert app is not None, "QApplication deve existir (qtbot fixture)."
    # Aplicar QSS — não deve levantar.
    app.setStyleSheet(qss)

    # Smoke: criar QFileDialog com DontUseNativeDialog (cenário dev mode).
    dlg = QFileDialog()
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    qtbot.addWidget(dlg)
    # Forçar aplicação do estilo.
    dlg.style().unpolish(dlg)
    dlg.style().polish(dlg)
    # Não show()/exec() — apenas instanciar/polish para validar parser.
    assert dlg is not None
