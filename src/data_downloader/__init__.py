"""data_downloader — Downloader de histórico de ativos via ProfitDLL.

Pacote raiz. Exporta ``__version__`` (versão do PACOTE) e re-exporta APIs
públicas via :mod:`data_downloader.public_api` (SemVer rastreado por
``__api_version__``).

Resolução de versão (Story v1.0.8 fix — Pichau live test 2026-05-06):

A versão é resolvida primeiro a partir de uma constante literal mantida
em sync com ``pyproject.toml::project.version``. Se :mod:`importlib.metadata`
reportar uma versão MAIOR (caso comum quando o usuário rodou
``pip install -e .`` em um pacote já bumpado externamente), preferimos a
metadata como source-of-truth. Se reportar uma versão MENOR (caso comum em
dev: ``pip install -e .`` antigo ficou pinned em 0.1.0 enquanto
``pyproject.toml`` foi bumpado para 1.0.7), preservamos a literal — assim
o usuário NÃO vê "v0.1.0" stale na status bar.

Bug v1.0.7 raiz: ``__version__ = "0.1.0"`` literal estava dessincronizado
de ``pyproject.toml::project.version = "1.0.7"``. Quando ``MainWindow`` lia
o atributo via ``importlib.metadata.version("data_downloader")``, recebia
"0.1.0" da dist-info stale e mostrava "v0.1.0" na status bar — Pichau
reportou ver "v1.0.0" por confusão visual com o ``__api_version__``
(intencionalmente travado em "1.0.0" para ADR-007a).

Procedimento de bump:
    1. Editar ``pyproject.toml::project.version``.
    2. Atualizar ``_PACKAGE_VERSION`` abaixo (mesma string).
    3. (Opcional) ``pip install -e .`` para refrescar dist-info local.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Story v1.0.8: literal mantida em sync com pyproject.toml::project.version.
# É a source-of-truth canônica em dev mode (onde dist-info pode estar stale)
# e em frozen builds onde importlib.metadata pode não enxergar a distribuição
# (PyInstaller sem .dist-info bundled).
_PACKAGE_VERSION = "1.1.0"


def _resolve_version() -> str:
    try:
        installed = _pkg_version("data_downloader")
    except PackageNotFoundError:
        return _PACKAGE_VERSION
    # Se metadata reporta versão MAIOR que a literal (raro — sinal de que
    # alguém bumpou pyproject + pip install -e . sem atualizar a literal
    # aqui), confiamos na metadata. Se reporta MENOR (dist-info stale),
    # preferimos a literal canônica.
    try:
        # Comparação SemVer naive — split por pontos, parsing tolerante.
        installed_tuple = tuple(int(x) for x in installed.split(".")[:3])
        literal_tuple = tuple(int(x) for x in _PACKAGE_VERSION.split(".")[:3])
    except ValueError:
        # Versão pre-release ou non-numérica — confia na metadata.
        return installed
    if installed_tuple >= literal_tuple:
        return installed
    return _PACKAGE_VERSION


__version__ = _resolve_version()

__all__ = ["__version__"]
