"""Integration tests — MainWindow shell (Story 3.1).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Cobertura:
    - MainWindow inicia sem crash.
    - QStackedWidget tem 3 telas (download/catalog/settings).
    - Atalhos Ctrl+D / Ctrl+B / Ctrl+, trocam telas.
    - Esc context-aware (no-op em telas não-Download).
    - Status bar exibe DLL status placeholder + versão.

Headless: pytest-qt usa QT_QPA_PLATFORM=offscreen via fixture.
"""

from __future__ import annotations

import os

import pytest

# Forçar offscreen ANTES de qualquer import PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest


@pytest.fixture
def main_window(qtbot):
    """Instancia MainWindow + registra para cleanup automático."""
    from data_downloader.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    yield window

    # Shutdown adapters explícito antes do teardown do qtbot.
    for screen_id in ("download", "catalog", "settings"):
        try:
            screen = window._screens.get(screen_id)
            if screen is not None and hasattr(screen, "_adapter"):
                screen._adapter.shutdown()
        except Exception:
            pass


# =====================================================================
# Smoke tests
# =====================================================================


def test_main_window_starts(main_window):
    """MainWindow constrói sem crash."""
    assert main_window.isVisible()
    assert main_window.windowTitle() == "data-downloader"


def test_main_window_has_three_screens(main_window):
    """Stack contém Download / Catálogo / Settings."""
    from data_downloader.ui.main_window import (
        SCREEN_CATALOG,
        SCREEN_DOWNLOAD,
        SCREEN_SETTINGS,
    )

    assert SCREEN_DOWNLOAD in main_window._screens
    assert SCREEN_CATALOG in main_window._screens
    assert SCREEN_SETTINGS in main_window._screens


def test_default_screen_is_download(main_window):
    """Default ao abrir = DownloadScreen."""
    assert main_window.active_screen_id() == "download"


# =====================================================================
# Navegação programática
# =====================================================================


def test_set_active_screen_switches_stack(main_window):
    """``set_active_screen`` muda o stack."""
    from data_downloader.ui.main_window import (
        SCREEN_CATALOG,
        SCREEN_DOWNLOAD,
        SCREEN_SETTINGS,
    )

    main_window.set_active_screen(SCREEN_CATALOG)
    assert main_window.active_screen_id() == SCREEN_CATALOG

    main_window.set_active_screen(SCREEN_SETTINGS)
    assert main_window.active_screen_id() == SCREEN_SETTINGS

    main_window.set_active_screen(SCREEN_DOWNLOAD)
    assert main_window.active_screen_id() == SCREEN_DOWNLOAD


def test_set_active_screen_unknown_id_noop(main_window):
    """ID desconhecido = no-op (não levanta)."""
    main_window.set_active_screen("download")
    main_window.set_active_screen("nonexistent")
    assert main_window.active_screen_id() == "download"


# =====================================================================
# Atalhos globais
# =====================================================================


def test_ctrl_d_focuses_download(main_window, qtbot):
    """Ctrl+D ativa DownloadScreen mesmo se já em outra."""
    from data_downloader.ui.main_window import SCREEN_CATALOG

    main_window.set_active_screen(SCREEN_CATALOG)
    assert main_window.active_screen_id() == SCREEN_CATALOG

    QTest.keySequence(main_window, QKeySequence("Ctrl+D"))
    qtbot.wait(50)
    assert main_window.active_screen_id() == "download"


def test_ctrl_b_focuses_catalog(main_window, qtbot):
    """Ctrl+B ativa CatalogScreen."""
    QTest.keySequence(main_window, QKeySequence("Ctrl+B"))
    qtbot.wait(50)
    assert main_window.active_screen_id() == "catalog"


def test_ctrl_comma_focuses_settings(main_window, qtbot):
    """Ctrl+, ativa SettingsScreen."""
    QTest.keySequence(main_window, QKeySequence("Ctrl+,"))
    qtbot.wait(50)
    assert main_window.active_screen_id() == "settings"


# =====================================================================
# Esc context-aware
# =====================================================================


def test_escape_noop_when_no_download(main_window):
    """Esc na DownloadScreen sem download ativo é no-op."""
    download_screen = main_window._screens["download"]
    assert not download_screen.is_download_active()
    handled = download_screen.handle_escape()
    assert handled is False
