"""data_downloader._env_loader — .env loader compartilhado CLI + UI.

Story v1.0.5 fix (Pichau live test 2026-05-06): em UI mode (data_downloader.exe
double-click), main() não importava cli.py, então _bootstrap_env nunca rodava
e ~/.data-downloader/.env (escrito por SettingsScreen Save) nunca era carregado
no boot. Resultado: user salva credenciais → fecha → reabre → campos vazios.

Fix: módulo standalone reutilizado por cli.py E ui/app.py.

Order de precedência (primeiro arquivo encontrado vence):
    1. ``cwd / .env``                              — projeto local (dev)
    2. ``<exe-dir> / .env``                        — distribuição PyInstaller
    3. ``~/.data-downloader/.env``                 — config user-global
       (escrito por SettingsScreen Save em runtime)

Graceful degrade: se ``python-dotenv`` não estiver instalado, retorna
silenciosamente ``False`` (variáveis precisam ser exportadas no shell —
rota antiga).
"""

from __future__ import annotations

from pathlib import Path

from data_downloader._internal.bundle_paths import (
    exe_dir,
    is_frozen,
)
from data_downloader._internal.bundle_paths import (
    user_env_path as _bp_user_env_path,
)

__all__ = ["bootstrap_env", "user_env_path"]


def user_env_path() -> Path:
    """Path canônico ``~/.data-downloader/.env`` (hífen, NÃO underscore).

    Single source of truth para o diretório user-global do data-downloader.
    Stories pré-v1.0.5 misturavam ``.data_downloader/`` (underscore, em
    ``settings_screen._config_path``) e ``.data-downloader/`` (hífen, em
    ``cli._bootstrap_env``) — essa divergência era um bug latente.

    Wave 1 v1.1.0 (Aria — ADR-018): delegado para
    :func:`data_downloader._internal.bundle_paths.user_env_path` —
    fonte canônica única.

    Returns:
        ``Path.home() / ".data-downloader" / ".env"`` resolvido.
    """
    return _bp_user_env_path()


def bootstrap_env() -> bool:
    """Carrega ``.env`` do primeiro candidato existente.

    Idempotent — chamada múltipla é segura (``load_dotenv`` não sobrescreve
    por default). Best-effort: qualquer erro de IO é silenciado (CLI/UI
    ainda funcionam sem ``.env`` quando vars já estão no ambiente).

    Order:
        1. ``cwd / .env``               (dev)
        2. ``<exe-dir> / .env``         (frozen, PyInstaller --onedir)
        3. ``~/.data-downloader/.env``  (user-global, written by Settings UI)

    Wave 1 v1.1.0 (Aria — ADR-018): detecção de frozen mode delegada a
    :func:`bundle_paths.is_frozen` — antes era ``getattr(sys, 'frozen', False)``
    duplicado.

    Returns:
        ``True`` se carregou um ``.env``; ``False`` caso contrário (sem
        ``python-dotenv`` instalado, ou nenhum candidato existe).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        # python-dotenv não instalado — graceful degrade. Usuário precisa
        # exportar PROFITDLL_* no shell ou via launcher dedicado.
        return False

    candidates: list[Path] = [Path.cwd() / ".env"]
    if is_frozen():
        # PyInstaller --onedir: .env junto do .exe é o caminho natural para
        # usuário final que não conhece cwd.
        candidates.append(exe_dir() / ".env")
    candidates.append(user_env_path())

    for candidate in candidates:
        try:
            if candidate.is_file():
                load_dotenv(candidate)
                return True
        except OSError:  # pragma: no cover defensive
            continue
    return False
