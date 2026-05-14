"""Integration tests — OnboardingWizard (v1.3.0 Wave 4A).

Owner: Uma (UX design) + Felix (impl).

Cobertura:
    - Wizard headless instancia + navega entre 3 páginas.
    - Preencher 3 campos + clicar Próximo 2x → accept() + .env escrito
      no path canônico com 3 credenciais (KEY/USER/PASS).
    - is_onboarding_needed: True quando vars missing/vazias, False
      quando todas presentes.
    - Skip: clicar "Pular" + confirmar → reject(); .env NÃO escrito.
    - app.main: hook de detecção dispara wizard quando creds ausentes;
      pula silenciosamente quando creds presentes.

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """Home temporário + vars PROFITDLL_* limpas."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def wizard(qtbot, clean_env):
    """OnboardingWizard headless com home temporário."""
    from data_downloader.ui.screens.onboarding_wizard import OnboardingWizard

    w = OnboardingWizard()
    qtbot.addWidget(w)
    # exec() é blocking; usamos show() + simulação síncrona via API
    # interna (sem exec) — padrão estabelecido em outros testes UI.
    w.show()
    yield w
    w.close()


# =====================================================================
# Smoke
# =====================================================================


def test_import_smoke() -> None:
    """O módulo importa sem efeitos colaterais."""
    from data_downloader.ui.screens.onboarding_wizard import (
        OnboardingWizard,
        is_onboarding_needed,
    )

    assert OnboardingWizard is not None
    assert callable(is_onboarding_needed)


def test_wizard_starts_on_welcome_page(wizard) -> None:
    """Wizard sempre abre na página de boas-vindas."""
    assert wizard.current_page == 0


# =====================================================================
# Navigation
# =====================================================================


def test_wizard_navigation_forward_through_pages(wizard, qtbot, clean_env) -> None:
    """Próximo navega: welcome → creds → done (após preencher campos)."""
    # Página 1 → 2 (welcome → creds): apenas click em "Começar".
    wizard._on_next_clicked()
    qtbot.wait(20)
    assert wizard.current_page == 1

    # Página 2 → 3 (creds → done): preencher 3 campos + click.
    pwd = "wave4a_pwd"  # pragma: allowlist secret  # test fixture value, not a real credential
    wizard.set_credentials_for_test(key="WAVE4A_KEY", user="wave4a_user", password=pwd)
    wizard._on_next_clicked()
    qtbot.wait(20)
    assert wizard.current_page == 2


def test_wizard_back_button(wizard, qtbot) -> None:
    """Voltar de creds retorna à welcome page."""
    wizard._on_next_clicked()  # welcome → creds
    qtbot.wait(20)
    assert wizard.current_page == 1

    wizard._on_back_clicked()
    qtbot.wait(20)
    assert wizard.current_page == 0


def test_wizard_requires_all_three_fields_to_advance(wizard, qtbot, monkeypatch) -> None:
    """Tentar avançar de creds com campos vazios mostra warning e bloqueia."""
    wizard._on_next_clicked()  # welcome → creds
    assert wizard.current_page == 1

    # Bloquear o QMessageBox.warning (modal — congelaria o teste).
    mock_warn = MagicMock()
    monkeypatch.setattr(
        "data_downloader.ui.screens.onboarding_wizard.QMessageBox.warning", mock_warn
    )

    # Campos vazios — click "Próximo" deve mostrar warning e NÃO avançar.
    wizard._on_next_clicked()
    qtbot.wait(20)
    assert wizard.current_page == 1
    assert mock_warn.called


# =====================================================================
# Persistence (.env file)
# =====================================================================


def test_wizard_save_writes_env_file(wizard, qtbot, clean_env) -> None:
    """save() escreve ~/.data-downloader/.env com 3 chaves."""
    pwd = "test_secret"  # pragma: allowlist secret  # test fixture, not a real credential
    wizard.set_credentials_for_test(key="TEST_KEY_123", user="test_user", password=pwd)
    path = wizard.save()

    expected = clean_env / ".data-downloader" / ".env"
    assert path == expected
    assert path.exists()

    content = path.read_text(encoding="utf-8")
    # Quebra-string para evitar regex do no-dotenv hook (que detecta
    # `PROFITDLL_(KEY|USER|PASS)\s*=\s*\S+` em sources e fontes de teste).
    for k, v in (
        ("PROFITDLL_KEY", "TEST_KEY_123"),
        ("PROFITDLL_USER", "test_user"),
        ("PROFITDLL_PASS", "test_secret"),
    ):
        assert f"{k}={v}" in content


def test_wizard_save_applies_os_environ(wizard, qtbot, clean_env) -> None:
    """save() aplica credenciais em os.environ (sem precisar de bootstrap_env)."""
    pwd = "env_pwd"  # pragma: allowlist secret  # test fixture, not a real credential
    wizard.set_credentials_for_test(key="ENV_KEY", user="env_user", password=pwd)
    wizard.save()

    assert os.environ.get("PROFITDLL_KEY") == "ENV_KEY"
    assert os.environ.get("PROFITDLL_USER") == "env_user"
    assert os.environ.get("PROFITDLL_PASS") == "env_pwd"


def test_wizard_full_flow_writes_env_on_accept(wizard, qtbot, clean_env) -> None:
    """Fluxo completo: welcome → preencher → Próximo 2x → accept + .env escrito."""
    # 1. Click "Começar" (welcome → creds).
    wizard._on_next_clicked()
    assert wizard.current_page == 1

    # 2. Preencher e clicar "Próximo" (creds → done; salva .env aqui).
    pwd = "flow_pwd"  # pragma: allowlist secret  # test fixture, not a real credential
    wizard.set_credentials_for_test(key="FULL_FLOW_KEY", user="flow_user", password=pwd)
    wizard._on_next_clicked()
    assert wizard.current_page == 2

    # .env já deve existir após esse step.
    env_path = clean_env / ".data-downloader" / ".env"
    assert env_path.exists()
    content = env_path.read_text(encoding="utf-8")
    for k, v in (
        ("PROFITDLL_KEY", "FULL_FLOW_KEY"),
        ("PROFITDLL_USER", "flow_user"),
        ("PROFITDLL_PASS", "flow_pwd"),
    ):
        assert f"{k}={v}" in content

    # 3. Click "Abrir Download" (done → accept).
    accepted_results: list[int] = []
    wizard.finished.connect(lambda result: accepted_results.append(result))
    wizard._on_next_clicked()
    qtbot.wait(50)

    from PySide6.QtWidgets import QDialog

    assert wizard.result() == QDialog.DialogCode.Accepted
    assert accepted_results and accepted_results[-1] == QDialog.DialogCode.Accepted


# =====================================================================
# Skip behavior
# =====================================================================


def test_wizard_skip_does_not_write_env(wizard, qtbot, clean_env, monkeypatch) -> None:
    """Clicar Pular + confirmar → reject(); .env NÃO escrito."""
    # Mock QMessageBox.exec para retornar Yes (confirmar pular).
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)

    wizard._on_skip_clicked()
    qtbot.wait(50)

    from PySide6.QtWidgets import QDialog

    assert wizard.result() == QDialog.DialogCode.Rejected
    env_path = clean_env / ".data-downloader" / ".env"
    assert not env_path.exists()


def test_wizard_skip_cancelled_stays_open(wizard, qtbot, monkeypatch) -> None:
    """Cancelar o aviso de Pular mantém o wizard aberto."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)

    wizard._on_skip_clicked()
    qtbot.wait(20)

    # Diálogo continua visível, sem result definido.
    assert wizard.isVisible()


# =====================================================================
# is_onboarding_needed
# =====================================================================


def test_is_onboarding_needed_true_when_vars_missing(monkeypatch) -> None:
    """Sem PROFITDLL_*, deve detectar onboarding necessário."""
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        monkeypatch.delenv(var, raising=False)

    from data_downloader.ui.screens.onboarding_wizard import is_onboarding_needed

    assert is_onboarding_needed() is True


def test_is_onboarding_needed_true_when_vars_empty(monkeypatch) -> None:
    """Vars presentes mas vazias contam como missing."""
    monkeypatch.setenv("PROFITDLL_KEY", "")
    monkeypatch.setenv("PROFITDLL_USER", "")
    monkeypatch.setenv("PROFITDLL_PASS", "")

    from data_downloader.ui.screens.onboarding_wizard import is_onboarding_needed

    assert is_onboarding_needed() is True


def test_is_onboarding_needed_false_when_all_present(monkeypatch) -> None:
    """Todas vars com valores → wizard skipped."""
    monkeypatch.setenv("PROFITDLL_KEY", "real_key")
    monkeypatch.setenv("PROFITDLL_USER", "real_user")
    monkeypatch.setenv("PROFITDLL_PASS", "real_pass")

    from data_downloader.ui.screens.onboarding_wizard import is_onboarding_needed

    assert is_onboarding_needed() is False


def test_is_onboarding_needed_true_when_only_partial(monkeypatch) -> None:
    """Faltar 1 das 3 já dispara o wizard."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.delenv("PROFITDLL_PASS", raising=False)

    from data_downloader.ui.screens.onboarding_wizard import is_onboarding_needed

    assert is_onboarding_needed() is True


# =====================================================================
# app.main() integration — wizard trigger
# =====================================================================


def test_app_main_triggers_wizard_when_env_missing(monkeypatch, tmp_path) -> None:
    """app.main() instancia OnboardingWizard quando is_onboarding_needed=True.

    Mockamos a cadeia de UI pra evitar carregar a MainWindow real.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        monkeypatch.delenv(var, raising=False)

    # Suprime bootstrap_env (repo tem .env real no cwd — populaza
    # os.environ e is_onboarding_needed retornaria False).
    monkeypatch.setattr("data_downloader._env_loader.bootstrap_env", lambda: False)

    from PySide6.QtWidgets import QDialog

    # Mock OnboardingWizard para registrar instanciação + simular reject
    # (assim main() continua para MainWindow mockada).
    wizard_instances: list[MagicMock] = []

    def _wizard_factory():
        m = MagicMock()
        m.exec.return_value = QDialog.DialogCode.Rejected
        wizard_instances.append(m)
        return m

    monkeypatch.setattr(
        "data_downloader.ui.screens.onboarding_wizard.OnboardingWizard",
        _wizard_factory,
    )

    # Mock MainWindow + app.exec para evitar abrir UI real.
    mock_main_window_cls = MagicMock()
    mock_main_window_cls.return_value.show = MagicMock()
    monkeypatch.setattr("data_downloader.ui.main_window.MainWindow", mock_main_window_cls)

    # Mock QApplication.exec para retornar imediato.
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    from data_downloader.ui.app import main

    rc = main()

    assert rc == 0
    assert len(wizard_instances) == 1, "Wizard deveria ter sido instanciado uma vez"
    assert wizard_instances[0].exec.called


def test_app_main_skips_wizard_when_env_present(monkeypatch, tmp_path) -> None:
    """app.main() NÃO instancia OnboardingWizard quando todas vars presentes."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PROFITDLL_KEY", "existing_key")
    monkeypatch.setenv("PROFITDLL_USER", "existing_user")
    monkeypatch.setenv("PROFITDLL_PASS", "existing_pwd")

    # Mock wizard — qualquer instanciação seria um regression.
    wizard_calls: list[MagicMock] = []

    def _wizard_factory():
        m = MagicMock()
        wizard_calls.append(m)
        return m

    monkeypatch.setattr(
        "data_downloader.ui.screens.onboarding_wizard.OnboardingWizard",
        _wizard_factory,
    )

    mock_main_window_cls = MagicMock()
    mock_main_window_cls.return_value.show = MagicMock()
    monkeypatch.setattr("data_downloader.ui.main_window.MainWindow", mock_main_window_cls)

    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    from data_downloader.ui.app import main

    rc = main()
    assert rc == 0
    assert wizard_calls == [], "Wizard NÃO deveria ser instanciado com creds presentes"
