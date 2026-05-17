"""data_downloader — Downloader de histórico de ativos via ProfitDLL.

Pacote raiz. Exporta ``__version__`` (versão do PACOTE) e re-exporta APIs
públicas via :mod:`data_downloader.public_api` (SemVer rastreado por
``__api_version__``).

Resolução de versão (Story 4.31 AC4 — 2026-05-16):

A versão é resolvida via :mod:`importlib.metadata` lendo o
``pyproject.toml::project.version`` da distribuição instalada. Em
ambientes onde :mod:`importlib.metadata` não enxerga a distribuição (e.g.
frozen builds PyInstaller sem ``.dist-info`` bundled), fallback para um
literal mantido como **safety net** apenas (não mais como source-of-truth).

Bug-class eliminada (v1.0.7 RCA): o literal antigo ``_PACKAGE_VERSION``
podia dessincronizar de ``pyproject.toml`` em bumps de versão (drift
``__init__`` vs ``pyproject``). Com a leitura via ``importlib.metadata``
como caminho primário, a única forma de drift é o usuário rodar com
``pip install -e .`` stale — o literal de fallback minimiza o impacto
visual nesse caso (legado da v1.0.8).

Procedimento de bump (simplificado):
    1. Editar ``pyproject.toml::project.version``.
    2. (Opcional) ``pip install -e .`` para refrescar dist-info local.
    3. (Opcional, defensivo para frozen) Atualizar ``_PACKAGE_VERSION_FALLBACK``
       abaixo. Não é load-bearing em dev/install normais.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Fallback literal — usado APENAS quando importlib.metadata.version() não
# enxerga a distribuição (frozen builds sem .dist-info, ambientes
# corrompidos). Em dev/install normais não é load-bearing.
#
# Compat: alias ``_PACKAGE_VERSION`` mantido como export interno para
# callers existentes (tests, MainWindow status bar). Não remover sem
# auditoria de callers (grep _PACKAGE_VERSION).
_PACKAGE_VERSION_FALLBACK = "1.3.0"
_PACKAGE_VERSION = _PACKAGE_VERSION_FALLBACK  # backward-compat alias


def _resolve_version() -> str:
    """Resolve a versão do pacote.

    Caminho primário: :func:`importlib.metadata.version`. Fallback:
    literal ``_PACKAGE_VERSION_FALLBACK`` quando metadata não disponível
    (frozen build sem dist-info, ambientes corrompidos).
    """
    # Tenta ambos os nomes (PEP 503 normalization): underscore (canônico
    # em pyproject) e hyphen (PyPI-style). Ambos resolvem para a mesma
    # distribuição em práticas modernas, mas defendemos contra
    # ambientes onde apenas uma forma está registrada.
    for dist_name in ("data_downloader", "data-downloader"):
        try:
            return _pkg_version(dist_name)
        except PackageNotFoundError:
            continue
    return _PACKAGE_VERSION_FALLBACK


__version__ = _resolve_version()

__all__ = ["__version__"]
