"""Integration tests — MainWindow status bar shows dynamic package version.

Owner: Felix (frontend-dev) | Pichau live test bug 2026-05-06.

Pichau live test v1.0.7 (mesmo screenshot do bug structlog → Qt) reportou:
status bar mostra ``v1.0.0`` apesar de o usuário ter instalado o pacote
1.0.7. Root cause: ``MainWindow._build_status_bar`` lia
``data_downloader.public_api.__api_version__`` (que é a SemVer da API
PÚBLICA estável, ADR-007a — intencionalmente fixa em "1.0.0" e
desacoplada da versão do PACOTE).

Fix v1.0.8:

1. ``data_downloader.__init__`` resolve ``__version__`` via
   :func:`importlib.metadata.version` com fallback literal
   (mantido em sync com ``pyproject.toml``).
2. ``main_window.py`` passa a usar ``data_downloader.__version__``
   no label da status bar.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def main_window(qtbot):
    from data_downloader.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close()


@pytest.mark.integration
def test_package_exposes_version_attribute():
    """``data_downloader.__version__`` existe e é uma string semver-like."""
    import data_downloader

    assert hasattr(
        data_downloader, "__version__"
    ), "data_downloader deve expor __version__ no __init__"
    version = data_downloader.__version__
    assert isinstance(version, str), f"__version__ deve ser str; got {type(version)!r}"
    assert version, "__version__ não pode ser string vazia"
    # SemVer-ish — deve ter ao menos 1 ponto (e.g. "1.0.8").
    assert "." in version, f"__version__ deve ser SemVer-like (X.Y.Z); got {version!r}"


@pytest.mark.integration
def test_package_version_is_not_legacy_hardcoded():
    """``__version__`` NÃO pode estar parado em "0.1.0" ou "1.0.0" hardcoded.

    Story v1.0.8 fix: antes ``data_downloader/__init__.py`` tinha
    ``__version__ = "0.1.0"`` literal, dessincronizado de
    ``pyproject.toml::project.version``. Agora deve refletir a versão
    real do pacote (>= 1.0.7 quando rodando a partir do source corrente).
    """
    import data_downloader

    assert data_downloader.__version__ != "0.1.0", (
        "__version__ ainda está hardcoded em 0.1.0 — não puxa de "
        "pyproject.toml. Rodar `pip install -e .` ou bump fallback "
        "literal em data_downloader/__init__.py."
    )


@pytest.mark.integration
def test_status_bar_shows_dynamic_version_not_hardcoded(main_window):
    """Status bar exibe a versão real do pacote (não "v1.0.0" hardcoded).

    Cenário Pichau v1.0.7: status bar mostrava ``v1.0.0`` mesmo após
    bump para 1.0.7+. Esse teste falha se alguém regredir o lookup
    para ``__api_version__``.
    """
    from PySide6.QtWidgets import QLabel

    import data_downloader

    expected_version = data_downloader.__version__
    expected_label = f"v{expected_version}"

    # Procura o label de versão na status bar via objectName.
    status_bar = main_window.statusBar()
    version_label = status_bar.findChild(QLabel, "appVersionLabel")

    assert version_label is not None, (
        "Esperava QLabel com objectName='appVersionLabel' na status bar; "
        "MainWindow._build_status_bar não está marcando o label de versão."
    )
    assert version_label.text() == expected_label, (
        f"Status bar deve mostrar {expected_label!r} (do pacote); " f"got {version_label.text()!r}"
    )


@pytest.mark.integration
def test_status_bar_does_not_use_api_version_proxy(main_window):
    """Defesa contra regressão: o label NÃO deve refletir __api_version__.

    ``__api_version__`` é a SemVer da API pública estável (ADR-007a) e
    fica intencionalmente travada — não pode ser usada como proxy de
    versão do app na UI.
    """
    from PySide6.QtWidgets import QLabel

    import data_downloader
    from data_downloader.public_api import __api_version__

    if data_downloader.__version__ == __api_version__:
        # Coincidência ok (o package version pode estar igualada à API
        # version em algum momento) — neste caso não há como diferenciar.
        # Skip — o teste anterior já valida o lookup correto.
        pytest.skip("__version__ == __api_version__ — não há como distinguir o lookup.")

    status_bar = main_window.statusBar()
    version_label = status_bar.findChild(QLabel, "appVersionLabel")
    assert version_label is not None
    assert __api_version__ not in version_label.text(), (
        f"Status bar NÃO deve mostrar __api_version__ ({__api_version__!r}); "
        f"got {version_label.text()!r}. Use data_downloader.__version__."
    )
