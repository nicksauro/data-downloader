"""tests/unit/test_main_invokes_bootstrap_env.py — Story v1.0.5.

Pichau live test 2026-05-06: usuário salvou credenciais via SettingsScreen
→ fechou o ``data_downloader.exe`` → reabriu (double-click) → campos
vazios. Causa-raiz: UI mode entrava em ``ui/app.py::main()`` SEM importar
``cli.py``, então ``_bootstrap_env`` nunca era chamado e o ``.env`` em
``~/.data-downloader/.env`` ficava órfão.

Fix v1.0.5: ``main()`` chama ``data_downloader._env_loader.bootstrap_env()``
antes de qualquer outra inicialização (logging, QApplication, QSS, etc).

Este teste verifica que ``main()`` realmente chama ``bootstrap_env`` —
sentinel anti-regressão. Mocka ``QApplication`` / ``MainWindow`` para não
abrir janela e não bloquear o test runner.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_main_calls_bootstrap_env_before_qapplication(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()`` deve chamar ``bootstrap_env`` ANTES de criar ``QApplication``.

    Pichau bug v1.0.4: ``.env`` user-global era ignorado em UI mode.
    """
    call_order: list[str] = []

    # Spy em bootstrap_env (módulo standalone).
    import data_downloader._env_loader as env_loader

    def spy_bootstrap_env() -> bool:
        call_order.append("bootstrap_env")
        return True

    monkeypatch.setattr(env_loader, "bootstrap_env", spy_bootstrap_env)

    # Mock QApplication (impede abertura real de janela).
    fake_qapp_instance = MagicMock()
    fake_qapp_instance.exec.return_value = 0

    fake_qapp_class = MagicMock()
    fake_qapp_class.instance.return_value = None  # força construção nova
    fake_qapp_class.return_value = fake_qapp_instance

    def make_qapp(*_args: object, **_kwargs: object) -> MagicMock:
        call_order.append("QApplication")
        return fake_qapp_instance

    fake_qapp_class.side_effect = make_qapp

    # Patch os imports lazy dentro de main() — precisa interceptar no
    # módulo PySide6.QtWidgets (de onde ``main()`` faz o ``from ... import``).
    from PySide6 import QtWidgets

    monkeypatch.setattr(QtWidgets, "QApplication", fake_qapp_class)

    # Mock MainWindow para não criar widget real (que dispararia layouts).
    fake_window = MagicMock()
    import data_downloader.ui.main_window as mw_module

    monkeypatch.setattr(mw_module, "MainWindow", lambda *a, **kw: fake_window)

    # Importa e chama main().
    from data_downloader.ui.app import main

    rc = main()

    assert rc == 0
    # bootstrap_env deve ter sido chamado.
    assert (
        "bootstrap_env" in call_order
    ), f"main() não chamou bootstrap_env (call_order={call_order})"
    # E ANTES de QApplication (regression sentinel).
    assert call_order.index("bootstrap_env") < call_order.index(
        "QApplication"
    ), f"bootstrap_env deve ser chamado ANTES de QApplication; got order={call_order}"


def test_main_resilient_to_bootstrap_env_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se ``bootstrap_env`` levantar, ``main()`` ainda deve abrir a UI.

    Graceful degrade: usuário pode digitar valores manualmente; ``.env``
    corrompido não pode bloquear o app.
    """
    import data_downloader._env_loader as env_loader

    def boom() -> bool:
        raise RuntimeError("simulated .env corruption")

    monkeypatch.setattr(env_loader, "bootstrap_env", boom)

    fake_qapp_instance = MagicMock()
    fake_qapp_instance.exec.return_value = 0
    fake_qapp_class = MagicMock()
    fake_qapp_class.instance.return_value = None
    fake_qapp_class.return_value = fake_qapp_instance
    from PySide6 import QtWidgets

    monkeypatch.setattr(QtWidgets, "QApplication", fake_qapp_class)

    import data_downloader.ui.main_window as mw_module

    monkeypatch.setattr(mw_module, "MainWindow", lambda *a, **kw: MagicMock())

    from data_downloader.ui.app import main

    # Não deve levantar — main() deve absorver a exceção.
    rc = main()
    assert rc == 0
