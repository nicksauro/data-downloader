"""Integration tests — SettingsScreen DLL auto-detect + file picker (Story 4.14).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Story 4.14 (Pichau live test 2026-05-05): durante testes manuais do
.exe v1.0.3, usuário não sabia o path completo da DLL para colar em
Settings → DLL Path. Solicitação textual: "Tem como fazer o app puxar
o path da dll automaticamente? ou ter alguma coisa que facilite, tipo
um botão pra buscar o profitdll e selecionar o arquivo".

Cobertura:
    - ``_auto_detect_dll_path`` em frozen mode (sys._MEIPASS).
    - ``_auto_detect_dll_path`` em paths Nelogica comuns.
    - ``_auto_detect_dll_path`` retorna None quando nada encontrado.
    - Browse button abre QFileDialog (mocked).
    - Browse populates _dll_path_edit ao selecionar arquivo.
    - Validação visual (✓ verde / ⚠ ambar / ✗ vermelho).
    - Auto-populate em initial load quando env vazio.
    - Não sobrescreve valor explícito do usuário.

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Limpa env vars e força HOME tmp para isolar testes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in (
        "PROFITDLL_KEY",
        "PROFITDLL_USER",
        "PROFITDLL_PASS",
        "PROFITDLL_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def settings_screen_factory(qtbot, isolated_env):
    """Factory que retorna fresh SettingsScreen.

    Use ao invés de fixture pronta porque alguns testes mockam
    ``_auto_detect_dll_path`` ANTES de criar a tela.
    """
    created: list[object] = []

    def _make():
        from data_downloader.ui.screens.settings_screen import SettingsScreen

        screen = SettingsScreen()
        qtbot.addWidget(screen)
        screen.show()
        created.append(screen)
        return screen

    yield _make


# =====================================================================
# _auto_detect_dll_path — unit-style tests (não precisa qtbot)
# =====================================================================


def test_auto_detect_returns_bundled_in_frozen_mode(monkeypatch, tmp_path):
    """Frozen mode (PyInstaller) com _MEIPASS contendo ProfitDLL.dll
    → retorna esse path como golden path."""
    from data_downloader.ui.screens import settings_screen as ss

    # Cria fake _MEIPASS com ProfitDLL.dll real.
    fake_meipass = tmp_path / "_MEIPASS"
    fake_meipass.mkdir()
    bundled_dll = fake_meipass / "ProfitDLL.dll"
    bundled_dll.write_bytes(b"FAKE_DLL")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)

    result = ss._auto_detect_dll_path()
    assert result is not None
    assert result == bundled_dll


def test_auto_detect_returns_program_files_path_if_exists(monkeypatch, tmp_path):
    """Common Nelogica install path (via PROGRAMFILES) → retorna se existe.

    Mock via PROGRAMFILES env var apontando para tmp_path com estrutura
    Nelogica/ProfitChart/DLLs/Win64/ProfitDLL.dll.
    """
    from data_downloader.ui.screens import settings_screen as ss

    # Garante NÃO frozen (senão tenta _MEIPASS primeiro).
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    # Cria estrutura Nelogica em tmp_path.
    nelogica_root = tmp_path / "Nelogica" / "ProfitChart" / "DLLs" / "Win64"
    nelogica_root.mkdir(parents=True)
    dll_path = nelogica_root / "ProfitDLL.dll"
    dll_path.write_bytes(b"FAKE_DLL")

    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))

    result = ss._auto_detect_dll_path()
    assert result is not None
    assert result == dll_path


def test_auto_detect_returns_none_when_nothing_found(monkeypatch, tmp_path):
    """Frozen=False + PROGRAMFILES vazio + sem DLL no repo → None."""
    from data_downloader.ui.screens import settings_screen as ss

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "nonexistent"))

    # Mock __file__ → parents[3] inexistente para neutralizar dev path.
    fake_file = tmp_path / "fake_module.py"
    fake_file.write_text("")
    monkeypatch.setattr(ss, "__file__", str(fake_file))

    result = ss._auto_detect_dll_path()
    assert result is None


# =====================================================================
# Browse button
# =====================================================================


def test_browse_button_opens_qfiledialog(settings_screen_factory, monkeypatch, qtbot):
    """Click em Procurar... → QFileDialog.getOpenFileName chamado.

    Verifica também que ``DontUseNativeDialog`` foi passado (ADR-003 M9).
    """
    captured: dict[str, object] = {}

    def fake_get_open(parent, caption, dir_, filter_, selected_filter, options):
        captured["caption"] = caption
        captured["filter"] = filter_
        captured["options"] = options
        return ("", "")  # Cancelado.

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_get_open)

    screen = settings_screen_factory()
    screen._dll_browse_btn.click()
    qtbot.wait(20)

    assert captured.get("caption") == "Selecionar ProfitDLL.dll"
    assert "ProfitDLL.dll" in str(captured.get("filter", ""))
    assert captured.get("options") == QFileDialog.Option.DontUseNativeDialog


def test_browse_button_populates_edit_on_selection(
    settings_screen_factory, monkeypatch, qtbot, tmp_path
):
    """Quando QFileDialog retorna path → ``_dll_path_edit`` é populado +
    dirty=True + validação atualizada."""
    selected = tmp_path / "chosen" / "ProfitDLL.dll"
    selected.parent.mkdir()
    selected.write_bytes(b"FAKE")

    def fake_get_open(*_args, **_kwargs):
        return (str(selected), "ProfitDLL (ProfitDLL.dll)")

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_get_open)

    screen = settings_screen_factory()
    screen._dll_browse_btn.click()
    qtbot.wait(20)

    assert screen._dll_path_edit.text() == str(selected)
    assert screen.is_dirty() is True


# =====================================================================
# Validação visual (verde / ambar / vermelho)
# =====================================================================


def test_validation_green_check_for_valid_dll(settings_screen_factory, qtbot, tmp_path):
    """Path para ProfitDLL.dll existente → status verde (✓)."""
    valid = tmp_path / "ProfitDLL.dll"
    valid.write_bytes(b"FAKE")

    screen = settings_screen_factory()
    screen._dll_path_edit.setText(str(valid))
    qtbot.wait(20)

    text = screen._dll_path_status.text()
    style = screen._dll_path_status.styleSheet()
    assert "✓" in text
    assert "Arquivo encontrado" in text
    assert "#3FCB6F" in style.upper() or "#3fcb6f" in style.lower()


def test_validation_red_x_for_missing_file(settings_screen_factory, qtbot, tmp_path):
    """Path inexistente → status vermelho (✗)."""
    missing = tmp_path / "does" / "not" / "exist.dll"

    screen = settings_screen_factory()
    screen._dll_path_edit.setText(str(missing))
    qtbot.wait(20)

    text = screen._dll_path_status.text()
    style = screen._dll_path_status.styleSheet()
    assert "✗" in text
    assert "não encontrado" in text
    assert "#F25656" in style.upper() or "#f25656" in style.lower()


def test_validation_amber_warn_for_wrong_file_name(settings_screen_factory, qtbot, tmp_path):
    """Arquivo existe mas não se chama ProfitDLL.dll → status ambar (⚠)."""
    wrong = tmp_path / "OtherLibrary.dll"
    wrong.write_bytes(b"FAKE")

    screen = settings_screen_factory()
    screen._dll_path_edit.setText(str(wrong))
    qtbot.wait(20)

    text = screen._dll_path_status.text()
    style = screen._dll_path_status.styleSheet()
    assert "⚠" in text
    assert "não é ProfitDLL.dll" in text
    assert "#F2C04B" in style.upper() or "#f2c04b" in style.lower()


def test_validation_empty_when_path_blank(settings_screen_factory, qtbot):
    """Path vazio → status sem texto (neutral, sem ruído)."""
    screen = settings_screen_factory()
    screen._dll_path_edit.setText("")
    qtbot.wait(20)
    assert screen._dll_path_status.text() == ""


# =====================================================================
# Initial load — auto-populate
# =====================================================================


def test_initial_load_auto_populates_when_env_empty(qtbot, isolated_env, monkeypatch, tmp_path):
    """PROFITDLL_PATH vazio + auto-detect retorna path → edit populado."""
    detected = tmp_path / "auto_detected" / "ProfitDLL.dll"
    detected.parent.mkdir()
    detected.write_bytes(b"FAKE")

    from data_downloader.ui.screens import settings_screen as ss

    monkeypatch.setattr(ss, "_auto_detect_dll_path", lambda: detected)

    screen = ss.SettingsScreen()
    qtbot.addWidget(screen)
    screen.show()

    assert screen._dll_path_edit.text() == str(detected)


def test_initial_load_does_not_override_user_value(qtbot, isolated_env, monkeypatch, tmp_path):
    """Se PROFITDLL_PATH está setado → auto-detect não sobrescreve."""
    user_path = str(tmp_path / "user_explicit" / "MyProfit.dll")
    monkeypatch.setenv("PROFITDLL_PATH", user_path)

    from data_downloader.ui.screens import settings_screen as ss

    # Auto-detect retornaria outro valor — garantimos que NÃO foi chamado
    # porque a env já estava setada.
    monkeypatch.setattr(ss, "_auto_detect_dll_path", lambda: tmp_path / "should_not_be_used.dll")

    screen = ss.SettingsScreen()
    qtbot.addWidget(screen)
    screen.show()

    assert screen._dll_path_edit.text() == user_path


# =====================================================================
# Microcopy registration
# =====================================================================


def test_browse_microcopy_resolves(settings_screen_factory):
    """Botão Browse deve mostrar texto válido (não <microcopy id not found>)."""
    screen = settings_screen_factory()
    btn_text = screen._dll_browse_btn.text()
    assert "<microcopy id not found" not in btn_text
    assert btn_text == "Procurar..."

    tip_text = screen._dll_browse_btn.toolTip()
    assert "<microcopy id not found" not in tip_text
    assert "ProfitDLL" in tip_text
