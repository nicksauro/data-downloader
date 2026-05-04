"""Integration tests — SettingsScreen (Story 3.2).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Cobertura:
    - Smoke: tela inicia, mostra 4 seções (DLL, Storage, Performance, About).
    - Microcopy resolve sem <microcopy id not found>.
    - Toggle de secret muda echo mode.
    - Save → arquivo TOML criado em tmp.
    - data_dir_changed signal emitido após save.
    - Browse data_dir usa DontUseNativeDialog (verificado via patch QFileDialog).
    - Estado dirty marcado em edits.
    - Test connection com fail (sem DLL) → toast + status disconnected.

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
    """Cria SettingsScreen com home temporário (config.toml não polui home real)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Override env vars de DLL para garantir 'not_configured' state.
    for var in ("PROFITDLL_KEY", "PROFIT_USER", "PROFIT_PASS"):
        monkeypatch.delenv(var, raising=False)

    from data_downloader.ui.screens.settings_screen import SettingsScreen

    screen = SettingsScreen()
    qtbot.addWidget(screen)
    screen.show()
    yield screen


# =====================================================================
# Smoke
# =====================================================================


def test_settings_screen_starts(settings_screen):
    """Tela inicia sem crash + título correto."""
    assert settings_screen._title.text() == "Configurações"


def test_settings_screen_has_four_sections(settings_screen):
    """4 seções: DLL, Storage, Performance, About."""
    assert settings_screen._dll_section is not None
    assert settings_screen._storage_section is not None
    assert settings_screen._perf_section is not None
    assert settings_screen._about_section is not None


def test_settings_microcopy_resolves(settings_screen):
    """Nenhuma label visível mostra <microcopy id not found>."""
    title = settings_screen._title.text()
    assert "<microcopy id not found" not in title
    save_btn = settings_screen._save_btn.text()
    assert "<microcopy id not found" not in save_btn
    test_btn = settings_screen._test_conn_btn.text()
    assert "<microcopy id not found" not in test_btn


def test_settings_starts_in_empty_when_env_missing(settings_screen, qtbot):
    """Sem PROFITDLL_KEY/USER/PASS → state empty + status not_configured."""
    qtbot.wait(50)
    # Status label = not_configured.
    assert settings_screen._dll_status_label.property("status") == "not_configured"


# =====================================================================
# Toggle secrets
# =====================================================================


def test_toggle_secret_changes_echo_mode(settings_screen, qtbot):
    """Click em Mostrar → echo mode normal; click de novo → password."""
    from PySide6.QtWidgets import QLineEdit

    edit, btn = settings_screen._env_widgets["PROFITDLL_KEY"]
    assert btn is not None
    assert edit.echoMode() == QLineEdit.EchoMode.Password

    btn.click()
    qtbot.wait(50)
    assert edit.echoMode() == QLineEdit.EchoMode.Normal

    btn.click()
    qtbot.wait(50)
    assert edit.echoMode() == QLineEdit.EchoMode.Password


# =====================================================================
# Save flow
# =====================================================================


def test_save_writes_config_toml(settings_screen, qtbot, tmp_path):
    """Click salvar → arquivo TOML criado em ~/.data_downloader/config.toml."""
    settings_screen._dll_path_edit.setText("C:/test/ProfitDLL.dll")
    settings_screen._data_dir_edit.setText(str(tmp_path / "mydata"))

    settings_screen._on_save_clicked()
    qtbot.wait(100)

    config_path = tmp_path / ".data_downloader" / "config.toml"
    assert config_path.exists()
    content = config_path.read_text(encoding="utf-8")
    assert "dll_path" in content
    assert "data_dir" in content


def test_save_emits_data_dir_changed_signal(settings_screen, qtbot, tmp_path):
    """Save → data_dir_changed emit com novo path."""
    received: list[str] = []
    settings_screen.data_dir_changed.connect(received.append)

    new_dir = str(tmp_path / "newdata")
    settings_screen._data_dir_edit.setText(new_dir)
    settings_screen._on_save_clicked()
    qtbot.wait(100)

    assert new_dir in received


def test_save_shows_success_toast(settings_screen, qtbot):
    settings_screen._dll_path_edit.setText("C:/test/dll")
    settings_screen._on_save_clicked()
    qtbot.wait(50)
    assert settings_screen._toast.isVisible()


def test_dirty_flag_marked_on_edit(settings_screen):
    """textEdited handler marca _dirty=True."""
    assert settings_screen.is_dirty() is False
    settings_screen._mark_dirty()
    assert settings_screen.is_dirty() is True


# =====================================================================
# Browse / DontUseNativeDialog
# =====================================================================


def test_change_data_dir_uses_dont_use_native(settings_screen, qtbot, monkeypatch):
    """Browse data dir → QFileDialog.getExistingDirectory chamado com flag."""
    captured: dict[str, object] = {}

    def fake_get_existing(parent, caption, dir_, options):
        captured["caption"] = caption
        captured["dir"] = dir_
        captured["options"] = options
        return ""  # Cancelado.

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_get_existing)

    settings_screen._on_change_data_dir_clicked()
    qtbot.wait(20)

    # Garante que o flag DontUseNativeDialog foi passado (M9).
    assert captured.get("options") == QFileDialog.Option.DontUseNativeDialog


# =====================================================================
# Test connection
# =====================================================================


def test_test_connection_fail_shows_disconnected(settings_screen, qtbot):
    """Sem DLL real (ambiente teste) → status disconnected + toast erro."""
    settings_screen._on_test_connection_clicked()
    # Aguarda o singleShot interno (50ms).
    qtbot.wait(200)

    # Em ambiente sem DLL, status deve ser disconnected (ou continuar
    # not_configured; ambos são fail).
    status = settings_screen._dll_status_label.property("status")
    assert status in ("disconnected", "not_configured")
    assert settings_screen._toast.isVisible()


# =====================================================================
# State machine
# =====================================================================


def test_state_changed_signal_emitted(settings_screen, qtbot):
    states: list[str] = []
    settings_screen.state_changed.connect(states.append)

    settings_screen._set_state("normal")
    settings_screen._set_state("loading")
    settings_screen._set_state("error")

    assert states[-3:] == ["normal", "loading", "error"]


def test_handle_escape_returns_false(settings_screen):
    """Esc na settings é no-op (return False)."""
    assert settings_screen.handle_escape() is False
