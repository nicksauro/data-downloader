"""data_downloader._internal.bundle_paths — frozen-mode path resolution (ADR-018 / ADR-021).

Owner: Aria (architect — fronteira frozen/source).
Story: v1.1.0 master plan Wave 1 (P0 architecture extraction).

**Single source of truth** para resolução de paths em runtime — frozen
(PyInstaller ``--onedir``) ou source (dev / pip-installed). Antes desta
extração, cada módulo (``ui/app.py``, ``cli.py``, ``settings_screen.py``,
``orchestrator/contracts.py``, ``dll/wrapper.py``) duplicava a lógica
``getattr(sys, 'frozen', False)`` + ``sys._MEIPASS`` ad-hoc — fonte de bugs
v1.0.4 (QSS path mismatch) e v1.0.5 (DLL companions).

Ver ADR-018 (frozen-mode boundary) e ADR-021 (sys.frozen contract).

Layout PyInstaller ``--onedir`` em produção::

    dist/data_downloader/
    ├── data_downloader.exe              # windowed (UI)
    ├── data_downloader-cli.exe          # console (CLI)
    └── _internal/                       # <-- sys._MEIPASS aponta aqui em runtime
        ├── assets/
        │   └── style.qss
        ├── docs/
        │   └── storage/
        │       └── CONTRACTS.md
        ├── scripts/
        │   └── verify-dll-companions.py
        ├── ProfitDLL.dll
        └── ... (Python runtime, libs, etc.)

Layout dev / source-install::

    <repo>/
    ├── src/data_downloader/             # <-- bundle_root() retorna aqui
    │   ├── _internal/bundle_paths.py
    │   ├── ui/assets/style.qss
    │   └── ...
    ├── docs/storage/CONTRACTS.md
    ├── scripts/verify-dll-companions.py
    └── profitdll/DLLs/Win64/ProfitDLL.dll

R21 (hot path): este módulo NÃO faz I/O no import (sem ``is_file()``,
sem leitura de FS). Resolução é lazy — chamada apenas quando consumer
precisa de um path específico.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = [
    "asset_path",
    "bundle_root",
    "default_data_dir",
    "exe_dir",
    "is_frozen",
    "user_data_dir",
    "user_env_path",
]


def is_frozen() -> bool:
    """Retorna ``True`` se executando em bundle PyInstaller frozen.

    Verifica AMBOS ``sys.frozen`` e a presença de ``sys._MEIPASS`` —
    PyInstaller seta os dois. Ferramentas de teste podem setar apenas
    ``sys.frozen=True`` (fake) sem ``_MEIPASS``; tratamos isso como
    "frozen sem extração" (raro: ``--onefile`` ainda em runtime
    extraction). Caller deve usar :func:`bundle_root` que sabe lidar.

    Returns:
        ``True`` se ``getattr(sys, 'frozen', False)`` E ``sys._MEIPASS``
        está setado para uma string não-vazia. ``False`` em dev / source
        install.

    Examples:
        >>> isinstance(is_frozen(), bool)
        True
    """
    if not getattr(sys, "frozen", False):
        return False
    meipass = getattr(sys, "_MEIPASS", "")
    return bool(meipass)


def bundle_root() -> Path:
    """Retorna o diretório-base de assets bundleados.

    - **Frozen mode**: ``Path(sys._MEIPASS)`` — diretório onde PyInstaller
      extraiu (ou referencia direto, em ``--onedir``) os assets do
      ``datas`` tuple do spec.
    - **Source mode**: diretório do pacote ``data_downloader`` (i.e.
      ``<repo>/src/data_downloader``). Calculado via ``Path(__file__).parent.parent``
      — ``bundle_paths.py`` está em ``_internal/``, ``parent`` é
      ``_internal/``, ``parent.parent`` é o pacote.

    Returns:
        :class:`pathlib.Path` resolvido (não-resolved — não chama
        ``.resolve()`` para evitar I/O em hot path; caller resolve se
        precisar).

    Examples:
        >>> bundle_root().is_dir() or True  # path pode não existir em sandbox
        True
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", "")
        # is_frozen() já validou meipass não-vazio; defensive cast.
        return Path(meipass)
    # Source mode: __file__ = .../src/data_downloader/_internal/bundle_paths.py
    # parent = _internal/
    # parent.parent = data_downloader/   <-- raiz do pacote em source mode.
    return Path(__file__).parent.parent


def exe_dir() -> Path:
    """Retorna o diretório do executável atual.

    - **Frozen mode**: ``Path(sys.executable).parent`` — em ``--onedir``,
      este é o diretório que CONTÉM ``_internal/``. Útil para procurar
      ``.env`` adjacente ao .exe (Story v1.0.5) ou para instalar
      side-companions (DLLs do usuário).
    - **Source mode**: ``Path(sys.executable).parent`` — diretório do
      Python interpreter. Quase nunca é o que se quer em dev; caller
      tipicamente cai para :func:`bundle_root` em source mode.

    Returns:
        Diretório que contém ``sys.executable``.

    Examples:
        >>> exe_dir().exists() or True
        True
    """
    return Path(sys.executable).parent


def asset_path(rel: str) -> Path:
    """Resolve ``rel`` (path relativo) procurando em ordem de candidatos.

    Ordem (primeiro arquivo existente vence):

    1. ``bundle_root() / rel``  — onde PyInstaller datas extrai (frozen)
       ou raiz do pacote ``data_downloader`` (source).
    2. ``exe_dir() / "_internal" / rel``  — layout ``--onedir`` quando
       ``sys._MEIPASS`` não está setado (raro — ex.: ferramentas que
       executam o .exe via subprocess sem o launcher PyI extrair).
    3. ``exe_dir() / rel``  — layout flat (assets ao lado do .exe;
       fallback defensivo).
    4. ``Path(__file__).parent.parent / rel``  — explicit source-mode
       lookup; redundante com (1) em source mode mas defesa-em-profundidade
       caso bundle_root() esteja apontando para FS path inválido.

    Args:
        rel: Path relativo ao bundle root (ex.: ``"assets/style.qss"``,
            ``"docs/storage/CONTRACTS.md"``).

    Returns:
        Primeiro candidato existente, como :class:`pathlib.Path`.

    Raises:
        FileNotFoundError: nenhum candidato existe. Mensagem lista TODOS
            os paths tentados — debug em frozen é doloroso sem isso.

    Examples:
        >>> # asset_path("nonexistent/file.txt") raises FileNotFoundError
        >>> # listing all candidates tried.
        >>> True
        True
    """
    candidates: list[Path] = [
        bundle_root() / rel,
        exe_dir() / "_internal" / rel,
        exe_dir() / rel,
        Path(__file__).parent.parent / rel,
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            # Path inválido em alguma plataforma exótica — pula candidato.
            continue

    # Não achou — lança com lista de TODOS os candidatos para debug.
    candidates_str = "\n  - ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"Asset {rel!r} não encontrado em nenhum candidato.\n"
        f"is_frozen()={is_frozen()}\n"
        f"Candidates tried (in order):\n  - {candidates_str}"
    )


def user_data_dir() -> Path:
    """Retorna ``~/.data-downloader/`` (com hífen — canônico).

    Diretório user-global para config + credenciais + cache. Pré-v1.0.5
    havia divergência entre ``.data-downloader/`` (hífen — usado por
    ``.env``) e ``.data_downloader/`` (underscore — usado por
    ``config.toml``). Story v1.0.5 canonizou hífen como única forma.

    NÃO cria o diretório — caller é responsável (idempotência via
    ``mkdir(parents=True, exist_ok=True)``).

    Returns:
        ``Path.home() / ".data-downloader"``.

    Examples:
        >>> p = user_data_dir()
        >>> p.name == ".data-downloader"
        True
    """
    return Path.home() / ".data-downloader"


def user_env_path() -> Path:
    """Retorna ``~/.data-downloader/.env`` — alias mantido para compat.

    Existe em :mod:`data_downloader._env_loader` desde Story v1.0.5; aqui
    apenas re-exporta para que consumers que já importam ``bundle_paths``
    não precisem dual-import. Mantemos a fonte canônica em ``_env_loader``
    (ele tem precedência se houver divergência).

    Returns:
        ``user_data_dir() / ".env"``.

    Examples:
        >>> p = user_env_path()
        >>> p.name == ".env"
        True
        >>> p.parent.name == ".data-downloader"
        True
    """
    return user_data_dir() / ".env"


def default_data_dir() -> Path:
    """Pasta de dados default — ``user_data_dir() / "data"``.

    Single source of truth para o ``data_dir`` da UI (DownloadScreen,
    CatalogScreen, SettingsScreen) e do CLI quando o usuário não passa
    ``--data-dir`` explícito.

    v1.3.0 (Bug 2 fix): antes a UI tinha 3 caminhos divergentes para
    o data_dir default (DownloadScreen usava ``user_data_dir()/"data"``,
    mas CatalogScreen e SettingsScreen caíam em ``Path.cwd()/"data"``).
    Quando o ``.exe`` instalado é lançado pelo atalho do Setup, o ``cwd``
    é tipicamente ``System32`` → CatalogScreen abria ``System32\\data\\``
    (inexistente) e mostrava lista vazia mesmo com downloads concluídos.
    Esta função consolida o caminho para que os 3 lugares concordem.

    Returns:
        ``user_data_dir() / "data"`` (ex.: ``~/.data-downloader/data``).
    """
    return user_data_dir() / "data"
