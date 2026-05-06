"""tests/integration/test_ui_settings_doctor_button.py — Story 4.9.

Integration test do botão "Diagnóstico Completo" (``BTN_DOCTOR_FULL``)
em :class:`SettingsScreen`. Verifica:

    - O botão tem ``clicked.connect`` (cabeado, não orphan).
    - Click invoca ``run_doctor_checks`` e mostra modal com resultado.
    - Modal contém sumário (PASS/FAIL/WARN counts) e texto bruto.

Headless via ``QT_QPA_PLATFORM=offscreen`` (alinhado com test_ui_*).

Owner: Dex (dev). Story 4.9 (v1.0.3 hotfix — Owners Council B5).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


def _seed_catalog(db_path: Path, version: str = "1.1.0") -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO _schema_meta(key, value) VALUES('catalog_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (version,),
        )
        conn.commit()


@pytest.fixture
def settings_screen(qtbot, monkeypatch, tmp_path):
    """SettingsScreen com home temporário + env vars configuradas."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Env vars set so doctor não FAIL no check Credenciais.
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    # Patch checks externos (companions / connectivity) para não depender
    # da máquina real. Os testes de unit já cobrem cada check.
    from data_downloader import cli as cli_module

    monkeypatch.setattr(cli_module, "_check_dll_companions", lambda: ("PASS", "mocked"))
    monkeypatch.setattr(cli_module, "_check_connectivity", lambda: ("PASS", "mocked"))

    _seed_catalog(tmp_path / "data" / "history" / "catalog.db", version="1.1.0")

    from data_downloader.ui.screens.settings_screen import SettingsScreen

    screen = SettingsScreen()
    qtbot.addWidget(screen)
    # Aponta data_dir para tmp_path/data — onde o catalog está seedado.
    screen._data_dir_edit.setText(str(tmp_path / "data"))
    screen.show()
    yield screen


# =====================================================================
# Tests
# =====================================================================


def test_doctor_button_exists_and_is_connected(settings_screen):
    """O botão ``_doctor_btn`` existe + clicked tem 1+ conexões.

    PySide6 ``QObject.receivers`` aceita string signature SIGNAL("clicked()").
    """
    assert settings_screen._doctor_btn is not None
    # PySide6 8.x: receivers aceita signal name string ``"2clicked()"`` (formato
    # SIGNAL macro do Qt). Fallback: smoke via emissão direta.
    n = settings_screen._doctor_btn.receivers("2clicked()")
    assert n >= 1, f"Expected >=1 slot connected to clicked, got {n}"


def test_doctor_button_microcopy_resolves(settings_screen):
    """Texto do botão não é placeholder ``<microcopy id not found>``."""
    text = settings_screen._doctor_btn.text()
    assert "<microcopy id not found" not in text
    assert "Diagn" in text  # Diagnóstico — match acentuado e plain.


def test_doctor_button_invokes_diagnosis_and_shows_modal(settings_screen, qtbot, monkeypatch):
    """Click no botão → invoca ``run_doctor_checks`` + abre QDialog modal."""
    captured: dict[str, object] = {}

    # Patch ``run_doctor_checks`` para evitar custos reais (sockets etc).
    from data_downloader import cli as cli_module

    def _fake_run_doctor_checks(*, data_dir, with_handshake=False, console=None, verbose=False):
        captured["called"] = True
        captured["data_dir"] = data_dir
        captured["with_handshake"] = with_handshake
        if console is not None:
            console.print("Doctor mock output\n")
        return 0, [
            ("DLL companions", "PASS", "mocked"),
            ("Credenciais", "PASS", "mocked"),
            ("Disk", "PASS", "mocked"),
            ("Schema", "PASS", "mocked"),
            ("Connectivity", "PASS", "mocked"),
        ]

    monkeypatch.setattr(cli_module, "run_doctor_checks", _fake_run_doctor_checks)

    # Patch QDialog.exec para não bloquear o teste com modal.
    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: 0)

    settings_screen._on_doctor_clicked()
    qtbot.wait(50)

    assert captured.get("called") is True
    # default with_handshake=False (UI usuário não espera 10s).
    assert captured.get("with_handshake") is False
    # Modal foi criado.
    assert hasattr(settings_screen, "_last_doctor_dialog")
    dialog = settings_screen._last_doctor_dialog
    assert dialog is not None
    # Properties expostos para testabilidade.
    assert dialog.property("doctorExitCode") == 0
    assert dialog.property("doctorPassCount") == 5
    assert dialog.property("doctorFailCount") == 0


def test_doctor_button_fail_path_shows_error_summary(settings_screen, qtbot, monkeypatch):
    """Quando doctor retorna exit 1, modal mostra sumário FAIL."""
    from data_downloader import cli as cli_module

    def _fake_run_doctor_checks(*, data_dir, with_handshake=False, console=None, verbose=False):
        if console is not None:
            console.print("Doctor FAIL mock\n")
        return 1, [
            ("DLL companions", "FAIL", "missing X"),
            ("Credenciais", "PASS", "ok"),
            ("Disk", "PASS", "ok"),
            ("Schema", "PASS", "ok"),
            ("Connectivity", "PASS", "ok"),
        ]

    monkeypatch.setattr(cli_module, "run_doctor_checks", _fake_run_doctor_checks)

    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: 0)

    settings_screen._on_doctor_clicked()
    qtbot.wait(50)

    dialog = settings_screen._last_doctor_dialog
    assert dialog is not None
    assert dialog.property("doctorExitCode") == 1
    assert dialog.property("doctorFailCount") == 1
    assert dialog.property("doctorPassCount") == 4
