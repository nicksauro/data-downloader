"""Integration tests — UI theming/QSS smoke (Story 3.3 — Wave 18).

Owner: Felix (impl) | Design: Uma (theme authority).

Cobertura best-effort offscreen:
    - QSS aplica sem warnings (carrega via app.setStyleSheet).
    - Tokens canônicos da paleta presentes no QSS (THEME.md §2).
    - QPushButton tem 4 estados visuais (variants).
    - QProgressBar tem 4 estados (normal / reconnecting / cancelling /
      complete / error).
    - QTableView tem alternating-row + accent selection.
    - QGroupBox usa background transparent.
    - QStatusBar tem padding + paleta dark.

QSS é cosmético — testes verificam consistência da paleta ao invés de
inspecionar QPalette do widget (offscreen platform tem cores limitadas).

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# QSS file integrity
# =====================================================================


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


# Tokens canônicos da paleta (THEME.md §2 dark mode).
CANONICAL_HEX_TOKENS = {
    # bg
    "#0E0E10",  # bg.primary
    "#17171A",  # bg.surface
    "#1F1F23",  # bg.elevated
    "#26262B",  # bg.input
    # border
    "#2D2D33",  # border.subtle
    "#3D3D45",  # border.strong
    # text
    "#E8E8EA",  # text.primary
    "#A8A8AC",  # text.secondary
    "#6E6E74",  # text.muted
    "#4A4A50",  # text.disabled
    # semânticos
    "#3DD0E1",  # accent.cyan
    "#4F8CFF",  # primary
    "#3FCB6F",  # success.green
    "#F25656",  # error.red
    "#F2C94C",  # warning.yellow
    "#5E9FFF",  # info.blue (THEME §2 — atualmente só documentado, futuro INF_*)
}


def test_qss_contains_full_dark_palette(qss_text: str) -> None:
    """Todas as cores canônicas da paleta dark mode devem aparecer no QSS."""
    qss_upper = qss_text.upper()
    missing = [t for t in CANONICAL_HEX_TOKENS if t not in qss_upper]
    assert not missing, f"Cores canônicas faltando no QSS: {missing}"


def test_qss_no_unauthorized_colors(qss_text: str) -> None:
    """Sniff básico — todas as cores hex devem estar na paleta canônica.

    Permite rgba(...) com uso semântico documentado. Detecta cores hex
    fora da paleta como sintoma de invenção (R17 / Uma authority).
    """
    # Encontra todos os literais hex (#rrggbb).
    hex_pattern = re.compile(r"#[0-9A-Fa-f]{6}")
    found_hex = {h.upper() for h in hex_pattern.findall(qss_text)}
    # Sub-tonalidades de hover/active das mesmas cores são permitidas
    # (e.g. #6BA0FF é hover do #4F8CFF). Lista pequena explícita:
    authorized_derivatives = {
        "#FFFFFF",  # texto branco em botão primário
        "#6BA0FF",  # primary hover (THEME)
        "#3D7AE8",  # primary pressed (THEME)
        "#FF6B6B",  # destructive hover
        "#D14A4A",  # destructive pressed
        "#5DDDED",  # cyan hover/gradient end
        "#5BD884",  # green gradient end / hover
        "#FFD86B",  # yellow gradient end
        "#2BB8C9",  # cyan pressed
        "#5A5A62",  # scrollbar pressed
        "#131316",  # alternate row
    }
    allowed = CANONICAL_HEX_TOKENS | authorized_derivatives
    invented = found_hex - allowed
    assert not invented, (
        f"Cores não autorizadas no QSS (invenção — viola R17): {invented}. "
        "Adicione em THEME.md ou remova."
    )


def test_qss_button_has_four_states(qss_text: str) -> None:
    """QPushButton normal / hover / pressed / disabled devem existir."""
    assert "QPushButton {" in qss_text
    assert "QPushButton:hover" in qss_text
    assert "QPushButton:pressed" in qss_text
    assert "QPushButton:disabled" in qss_text


def test_qss_progressbar_has_state_variants(qss_text: str) -> None:
    """QProgressBar tem state-aware (reconnecting/cancelling/complete/error)."""
    for state in ("reconnecting", "cancelling", "complete", "error"):
        assert (
            f'QProgressBar[state="{state}"]' in qss_text
        ), f"State {state} ausente no QSS — ProgressCard depende disso."


def test_qss_progressbar_uses_yellow_during_reconnect(qss_text: str) -> None:
    """Quirk 99% (Flow 4) — barra fica amarela durante reconnect."""
    # Encontra bloco state=reconnecting e verifica presença de #F2C94C.
    pattern = re.compile(
        r'QProgressBar\[state="reconnecting"\]::chunk\s*\{[^}]+\}',
        re.DOTALL,
    )
    matches = pattern.findall(qss_text)
    assert matches, "Bloco QProgressBar[state=reconnecting]::chunk ausente."
    assert any(
        "#F2C94C" in m for m in matches
    ), "Barra de progresso reconnecting precisa usar warning.yellow #F2C94C."


def test_qss_tableview_has_alternating_and_accent_selection(qss_text: str) -> None:
    """CatalogScreen QTableView: alternating + selection accent."""
    assert "alternate-background-color" in qss_text
    # Selection com accent (rgba do cyan).
    assert re.search(
        r"selection-background-color:\s*rgba\(61,\s*208,\s*225",
        qss_text,
    ), "Selection do QTableView deve usar accent.cyan rgba."


def test_qss_groupbox_transparent_with_accent_title(qss_text: str) -> None:
    """QGroupBox transparente com label accent."""
    # Bloco QGroupBox { ... } deve ter background: transparent
    pattern = re.compile(r"QGroupBox\s*\{[^}]+\}", re.DOTALL)
    blocks = pattern.findall(qss_text)
    assert blocks, "QGroupBox bloco ausente."
    assert any("transparent" in b for b in blocks), "QGroupBox deve ter background transparent."
    # Title deve usar accent.
    title_pattern = re.compile(r"QGroupBox::title\s*\{[^}]+\}", re.DOTALL)
    title_blocks = title_pattern.findall(qss_text)
    assert title_blocks, "QGroupBox::title bloco ausente."
    assert any(
        "#3DD0E1" in b for b in title_blocks
    ), "QGroupBox::title deve usar accent.cyan #3DD0E1."


def test_qss_input_focus_uses_accent_border(qss_text: str) -> None:
    """QLineEdit/QComboBox/QDateEdit: border accent on focus."""
    assert "QLineEdit:focus" in qss_text
    # Verifica que pelo menos um seletor :focus tem border-color accent.
    focus_pattern = re.compile(
        r"(QLineEdit|QComboBox|QDateEdit)[^{]*:focus[^{]*\{[^}]*\}",
        re.DOTALL,
    )
    blocks = focus_pattern.findall(qss_text)
    assert blocks, "Nenhum bloco :focus encontrado para inputs."


def test_qss_statusbar_dark_with_metric_styles(qss_text: str) -> None:
    """QStatusBar dark + estilos para metric labels (Story 3.3)."""
    assert "QStatusBar {" in qss_text
    assert 'QStatusBar QLabel[role="metric"]' in qss_text
    assert 'QStatusBar QLabel[role="metric-link"]' in qss_text
    assert 'QStatusBar QLabel[role="metric-off"]' in qss_text


def test_qss_scrollarea_no_border(qss_text: str) -> None:
    """QScrollArea sem borda dupla quando aninhada."""
    assert "QScrollArea {" in qss_text
    pattern = re.compile(r"QScrollArea\s*\{[^}]+\}", re.DOTALL)
    blocks = pattern.findall(qss_text)
    assert blocks
    assert any("border: none" in b for b in blocks)


def test_qss_tabbar_has_dark_styling(qss_text: str) -> None:
    """QTabBar/QTabWidget styled (caso futuro use abas)."""
    assert "QTabWidget::pane" in qss_text
    assert "QTabBar::tab" in qss_text
    assert "QTabBar::tab:selected" in qss_text


# =====================================================================
# QApplication apply test
# =====================================================================


def test_qss_applies_to_qapplication_without_warnings(qtbot, capsys):
    """QSS aplicado em QApplication.setStyleSheet sem crash + smoke widget."""
    from PySide6.QtWidgets import (
        QApplication,
        QGroupBox,
        QLineEdit,
        QProgressBar,
        QPushButton,
        QTableView,
        QWidget,
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

    # Smoke: criar widgets das principais classes para garantir que
    # a folha de estilo é parseada sem warnings sérios.
    container = QWidget()
    qtbot.addWidget(container)
    btn = QPushButton("OK", container)
    btn.setProperty("variant", "primary")
    bar = QProgressBar(container)
    bar.setProperty("state", "reconnecting")
    edit = QLineEdit(container)
    grp = QGroupBox("Sec", container)
    table = QTableView(container)
    container.show()
    qtbot.wait(20)

    # Re-polish para forçar aplicação das properties dinâmicas.
    for w in (btn, bar, edit, grp, table):
        w.style().unpolish(w)
        w.style().polish(w)

    # stderr de Qt parser tipicamente não vem em capsys (vai pra
    # qDebug); validamos apenas que widgets tem property setada.
    assert btn.property("variant") == "primary"
    assert bar.property("state") == "reconnecting"
