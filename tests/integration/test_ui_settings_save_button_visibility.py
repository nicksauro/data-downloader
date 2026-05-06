"""Integration tests — Save button visibility (Story 4.15 P0 release-blocker).

Owner: Felix (frontend-dev) | Reporter: Pichau (live test v1.0.3 2026-05-06).

Pichau testou v1.0.3 ao vivo e relatou:

    "n tem nhnum lugar para apertar save, só testar conexao,
     quando clico em testar conexao da errado"

Causa raiz identificada:

    1. **PRIMARY** — ``app.py`` lookup de QSS usava ``Path(__file__).parent /
       "assets"`` (== ``<bundle>/data_downloader/ui/assets/``), mas o spec
       PyInstaller bundla os assets em ``<bundle>/assets/`` (raiz). Em
       frozen build, ``setStyleSheet`` nunca era invocado → ``QPushButton[
       variant="primary"]`` perdia background azul + padding 10/20 →
       botão Save virava um QPushButton default Qt (cinza, ~20px alt) que
       Pichau não distinguia visualmente do botão Doctor.

    2. **SECONDARY (defense-in-depth)** — mesmo com QSS, o botão Save
       herdava ``min-height: 20px`` global. ``setMinimumSize(140, 36)``
       garante área clicável mínima independente de QSS.

Cobertura desta suíte:

    - Save button existe + tem objectName ``saveBtn``.
    - Texto não-vazio (microcopy resolve).
    - Visível após show().
    - Altura >= 30px (proxy para "não-colapsado").
    - Width >= 100px (proxy para "área clicável Fitts").
    - É QPushButton com variant=primary (regression de styling).
    - É default button (Enter ativa).
    - Botão Doctor NÃO esconde Save (ambos visíveis no bottom bar).
    - Funciona SEM QSS aplicado (defense-in-depth).

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def settings_screen(qtbot, monkeypatch, tmp_path):
    """SettingsScreen com home temporário + env vars limpas."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        monkeypatch.delenv(var, raising=False)

    from data_downloader.ui.screens.settings_screen import SettingsScreen

    screen = SettingsScreen()
    qtbot.addWidget(screen)
    screen.resize(1024, 700)
    screen.show()
    qtbot.waitExposed(screen)
    yield screen


# =====================================================================
# Story 4.15 P0 — Save button visibility regression
# =====================================================================


def test_save_button_exists_and_has_object_name(settings_screen):
    """Save button existe e é localizável via findChild('saveBtn')."""
    from PySide6.QtWidgets import QPushButton

    btn = settings_screen.findChild(QPushButton, "saveBtn")
    assert btn is not None, (
        "Save button missing — Story 4.15 regression. "
        "QPushButton com objectName='saveBtn' deve existir em SettingsScreen."
    )


def test_save_button_has_non_empty_text(settings_screen):
    """Microcopy BTN_SAVE_SETTINGS resolve para texto não-vazio."""
    from PySide6.QtWidgets import QPushButton

    btn = settings_screen.findChild(QPushButton, "saveBtn")
    assert btn is not None
    text = btn.text()
    assert text, f"Save button without text! got={text!r}"
    assert (
        "<microcopy id not found" not in text
    ), f"Microcopy BTN_SAVE_SETTINGS não resolveu: {text!r}"
    # Story 4.15 — texto em CAIXA ALTA garante visibilidade sem depender
    # de QSS font-weight (que pode falhar a carregar em frozen build).
    assert text == text.upper(), (
        f"Save button text deve estar em UPPERCASE para visibilidade "
        f"defense-in-depth (sem QSS). got={text!r}"
    )


def test_save_button_is_visible_after_show(settings_screen):
    """Botão visível ao usuário após screen.show()."""
    from PySide6.QtWidgets import QPushButton

    btn = settings_screen.findChild(QPushButton, "saveBtn")
    assert btn is not None
    assert btn.isVisible(), (
        f"Save button hidden! geometry={btn.geometry()}, "
        f"isVisibleTo(parent)={btn.isVisibleTo(settings_screen)}"
    )


def test_save_button_has_minimum_clickable_size(settings_screen):
    """Botão tem dimensões mínimas para ser clicável (Fitts's law)."""
    from PySide6.QtWidgets import QPushButton

    btn = settings_screen.findChild(QPushButton, "saveBtn")
    assert btn is not None
    assert btn.minimumWidth() >= 100, (
        f"Save button minimumWidth too small: {btn.minimumWidth()}px "
        f"(target >= 100px para Fitts's law em CTAs primários)."
    )
    assert btn.minimumHeight() >= 30, (
        f"Save button minimumHeight too small: {btn.minimumHeight()}px "
        f"(target >= 30px — Story 4.15: botão colapsava a 20px sem QSS)."
    )


def test_save_button_has_primary_variant_styling(settings_screen):
    """Botão tem property variant='primary' para QSS theming (regression)."""
    from PySide6.QtWidgets import QPushButton

    btn = settings_screen.findChild(QPushButton, "saveBtn")
    assert btn is not None
    assert btn.property("variant") == "primary", (
        f"Save button deve ter property variant='primary' "
        f"(QPushButton[variant=\"primary\"] no style.qss). "
        f"Atual: {btn.property('variant')!r}"
    )


def test_save_button_is_default_action(settings_screen):
    """Botão é default action (Enter ativa) — UX padrão para CTA primário."""
    from PySide6.QtWidgets import QPushButton

    btn = settings_screen.findChild(QPushButton, "saveBtn")
    assert btn is not None
    assert btn.isDefault(), (
        "Save button deve ser default action — Enter no settings deve "
        "ativar Save por convenção (Pichau não sabia onde clicar; "
        "default+autoDefault=True dá affordance via teclado também)."
    )


def test_save_button_does_not_collapse_in_bottom_bar(settings_screen, qtbot):
    """Bottom bar com doctor+save não colapsa save button verticalmente."""
    from PySide6.QtWidgets import QPushButton

    qtbot.wait(50)  # Layout settle
    save_btn = settings_screen.findChild(QPushButton, "saveBtn")
    doctor_btn = settings_screen.findChild(QPushButton, "doctorBtn")
    assert save_btn is not None
    assert doctor_btn is not None
    # Ambos visíveis (Doctor não cobre Save).
    assert save_btn.isVisible()
    assert doctor_btn.isVisible()
    # Save não está atrás do Doctor — geometrias não-overlapping.
    save_geo = save_btn.geometry()
    doctor_geo = doctor_btn.geometry()
    assert not save_geo.intersects(doctor_geo), (
        f"Save button overlaps Doctor button! " f"save={save_geo}, doctor={doctor_geo}"
    )
    # Save está VISIVELMENTE à direita do Doctor (UX padrão: primary à direita).
    assert save_geo.left() > doctor_geo.right(), (
        f"Save button deve estar à direita do Doctor (UX convenção). "
        f"save.left={save_geo.left()}, doctor.right={doctor_geo.right()}"
    )


def test_save_button_visible_without_qss_loaded(qtbot, monkeypatch, tmp_path):
    """Defense-in-depth — botão funciona mesmo sem QSS (frozen build bug).

    Cenário Pichau v1.0.3: QSS path mismatch em frozen build → ``setStyleSheet``
    nunca chamado → todos os widgets caem em sizing default Qt. Este test
    valida que mesmo sem QSS, o save button mantém dimensões clicáveis +
    texto visível (porque setMinimumSize/uppercase são aplicados em código,
    não em QSS).
    """
    from PySide6.QtWidgets import QApplication, QPushButton

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        monkeypatch.delenv(var, raising=False)

    # Force-clear stylesheet (simula frozen build com QSS path mismatch).
    app = QApplication.instance()
    assert app is not None
    saved_sheet = app.styleSheet()
    app.setStyleSheet("")
    try:
        from data_downloader.ui.screens.settings_screen import SettingsScreen

        screen = SettingsScreen()
        qtbot.addWidget(screen)
        screen.resize(1024, 700)
        screen.show()
        qtbot.waitExposed(screen)
        qtbot.wait(50)

        btn = screen.findChild(QPushButton, "saveBtn")
        assert btn is not None
        assert btn.isVisible()
        assert btn.text(), "Save button text vazio sem QSS"
        # Sem QSS, sizeHint ainda deve respeitar setMinimumSize aplicado em código.
        assert btn.height() >= 30, (
            f"Save button colapsou sem QSS: height={btn.height()}px. "
            f"Story 4.15 requer setMinimumSize(140, 36) em código (não só QSS)."
        )
        assert btn.width() >= 100, f"Save button width insuficiente sem QSS: width={btn.width()}px"
    finally:
        app.setStyleSheet(saved_sheet)
