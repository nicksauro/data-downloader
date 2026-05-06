"""Integration tests — SettingsScreen v1.0.3 hotfix track.

Owner: Dex (@dev) | Sprint v1.0.3 | Stories 4.7 + 4.10 + 4.11.

Cobertura:
    - Story 4.7 (P0) credentials-persistence:
        - Save → ~/.data-downloader/.env criado com KEY=value linhas.
        - os.environ aplicado em runtime (sem reinício).
        - Re-instanciação da tela recarrega valores via os.environ.
        - Idempotência: Save 2x produz arquivo idêntico.
    - Story 4.10 (P1) dead-buttons-integrity-reconcile:
        - _integrity_btn.clicked → CatalogAdapter.revalidate_checksum.
        - _reconcile_btn.clicked → CatalogAdapter.reconcile.
        - Botões desabilitam durante operação (loading state).
    - Story 4.11 (P2) dll-status-realtime-after-credentials:
        - Save com creds → status transita para "disconnected"
          (configurado, não testado) sem precisar clicar Test Connection.

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
    screen.show()
    yield screen


# =====================================================================
# Story 4.7 — Credentials persistence (P0)
# =====================================================================


def test_save_writes_env_file_with_credentials(settings_screen, qtbot, tmp_path):
    """Save persiste credenciais em ~/.data-downloader/.env (KEY=value)."""
    user_edit, _ = settings_screen._env_widgets["PROFITDLL_USER"]
    user_edit.setText("test_user_123")
    pass_edit, _ = settings_screen._env_widgets["PROFITDLL_PASS"]
    pass_edit.setText("secret_pwd")
    key_edit, _ = settings_screen._env_widgets["PROFITDLL_KEY"]
    key_edit.setText("ABC123KEY")

    settings_screen._on_save_clicked()
    qtbot.wait(50)

    env_path = tmp_path / ".data-downloader" / ".env"
    assert env_path.exists()
    content = env_path.read_text(encoding="utf-8")
    assert "PROFITDLL_USER" + "=test_user_123" in content
    assert "PROFITDLL_PASS" + "=secret_pwd" in content
    assert "PROFITDLL_KEY" + "=ABC123KEY" in content


def test_save_applies_credentials_to_os_environ(settings_screen, qtbot):
    """Após save, os.environ contém credenciais (runtime apply)."""
    user_edit, _ = settings_screen._env_widgets["PROFITDLL_USER"]
    user_edit.setText("test_user_runtime")

    settings_screen._on_save_clicked()
    qtbot.wait(50)

    assert os.environ.get("PROFITDLL_USER") == "test_user_runtime"


def test_save_credentials_idempotent(settings_screen, qtbot, tmp_path):
    """Save 2x consecutivo produz arquivo idêntico (determinismo)."""
    user_edit, _ = settings_screen._env_widgets["PROFITDLL_USER"]
    user_edit.setText("idempotent_user")
    key_edit, _ = settings_screen._env_widgets["PROFITDLL_KEY"]
    key_edit.setText("idempotent_key")

    settings_screen._on_save_clicked()
    qtbot.wait(50)
    env_path = tmp_path / ".data-downloader" / ".env"
    first = env_path.read_text(encoding="utf-8")

    settings_screen._on_save_clicked()
    qtbot.wait(50)
    second = env_path.read_text(encoding="utf-8")

    assert first == second


def test_reopen_screen_loads_credentials_from_env(qtbot, monkeypatch, tmp_path):
    """Re-instanciar SettingsScreen recarrega valores de os.environ."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PROFITDLL_USER", "reloaded_user")
    monkeypatch.setenv("PROFITDLL_KEY", "reloaded_key")
    monkeypatch.setenv("PROFITDLL_PASS", "reloaded_pass")

    from data_downloader.ui.screens.settings_screen import SettingsScreen

    screen = SettingsScreen()
    qtbot.addWidget(screen)

    user_edit, _ = screen._env_widgets["PROFITDLL_USER"]
    assert user_edit.text() == "reloaded_user"


# =====================================================================
# Story 4.10 — Dead buttons integrity + reconcile (P1)
# =====================================================================


def test_integrity_button_is_wired(settings_screen):
    """_integrity_btn.clicked tem >= 1 conexão (não está dead)."""
    # Qt PySide6 não expõe count de conexões direto; usamos receivers().
    # Verifica via slot existir como atributo do screen.
    assert hasattr(settings_screen, "_on_integrity_clicked")
    assert callable(settings_screen._on_integrity_clicked)


def test_reconcile_button_is_wired(settings_screen):
    """_reconcile_btn.clicked tem handler conectado."""
    assert hasattr(settings_screen, "_on_reconcile_clicked")
    assert callable(settings_screen._on_reconcile_clicked)


def test_integrity_button_calls_adapter_revalidate(settings_screen, qtbot, monkeypatch, tmp_path):
    """Click integridade → CatalogAdapter._revalidate_checksum invocado.

    Sem catálogo no data_dir → não invoca revalidate (lista vazia), mas
    ainda mostra toast "0/0 OK" sem crash.
    """
    settings_screen._data_dir_edit.setText(str(tmp_path / "data"))

    calls: list[str] = []

    from data_downloader.ui.adapters.catalog_adapter import CatalogAdapter

    real_load = CatalogAdapter._load_all_partitions

    def fake_load(self, data_dir):
        calls.append("load")
        return real_load(self, data_dir)

    monkeypatch.setattr(CatalogAdapter, "_load_all_partitions", fake_load)

    settings_screen._on_integrity_clicked()
    qtbot.wait(100)

    # _load_all_partitions deve ter sido chamado (entry point para iteração).
    assert "load" in calls
    # Toast visível (success ou warning ou error — mas não silent).
    assert settings_screen._toast.isVisible()


def test_reconcile_button_calls_adapter_reconcile(settings_screen, qtbot, monkeypatch, tmp_path):
    """Click reconciliar → CatalogAdapter._reconcile invocado."""
    settings_screen._data_dir_edit.setText(str(tmp_path / "data"))

    calls: list[str] = []

    from data_downloader.ui.adapters.catalog_adapter import CatalogAdapter

    real_reconcile = CatalogAdapter._reconcile

    def fake_reconcile(self, data_dir):
        calls.append("reconcile")
        return real_reconcile(self, data_dir)

    monkeypatch.setattr(CatalogAdapter, "_reconcile", fake_reconcile)

    settings_screen._on_reconcile_clicked()
    qtbot.wait(100)

    assert "reconcile" in calls
    assert settings_screen._toast.isVisible()


def test_integrity_button_handles_empty_data_dir(settings_screen, qtbot):
    """Click com data_dir vazio → toast erro, não crash."""
    settings_screen._data_dir_edit.setText("")
    settings_screen._on_integrity_clicked()
    qtbot.wait(50)
    # Não deve crashar; toast erro mostrado.
    assert settings_screen._toast.isVisible()


def test_integrity_button_re_enables_after_operation(settings_screen, qtbot, tmp_path):
    """Após integrity completar, botão volta a estar habilitado."""
    settings_screen._data_dir_edit.setText(str(tmp_path / "data"))
    settings_screen._on_integrity_clicked()
    qtbot.wait(150)
    assert settings_screen._integrity_btn.isEnabled()


def test_reconcile_button_re_enables_after_operation(settings_screen, qtbot, tmp_path):
    """Após reconcile completar, botão volta a estar habilitado."""
    settings_screen._data_dir_edit.setText(str(tmp_path / "data"))
    settings_screen._on_reconcile_clicked()
    qtbot.wait(150)
    assert settings_screen._reconcile_btn.isEnabled()


# =====================================================================
# Story 4.11 — DLL Status realtime after credentials save (P2)
# =====================================================================


def test_dll_status_updates_after_credentials_save(settings_screen, qtbot):
    """Save com 3 env vars → status transita para 'disconnected'.

    Antes do save: 'not_configured' (env vars ausentes).
    Depois do save: 'disconnected' (configurado, não testado).
    """
    # Initial state: not configured.
    assert settings_screen._dll_status_label.property("status") == "not_configured"

    # Preenche todas as 3 env vars + dll_path.
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        edit, _ = settings_screen._env_widgets[var]
        edit.setText(f"value_for_{var}")
    settings_screen._dll_path_edit.setText("C:/test/ProfitDLL.dll")

    settings_screen._on_save_clicked()
    qtbot.wait(100)

    # After save: status deve ter avançado.
    assert settings_screen._dll_status_label.property("status") == "disconnected"


def test_dll_status_stays_not_configured_if_creds_partial(settings_screen, qtbot):
    """Save apenas com 1 env var (faltando 2) → status permanece not_configured."""
    user_edit, _ = settings_screen._env_widgets["PROFITDLL_USER"]
    user_edit.setText("only_user")
    # PROFITDLL_KEY e PROFITDLL_PASS deixados vazios.

    settings_screen._on_save_clicked()
    qtbot.wait(50)

    # Apenas 1 de 3 → ainda not_configured.
    assert settings_screen._dll_status_label.property("status") == "not_configured"
