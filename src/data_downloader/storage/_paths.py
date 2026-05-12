"""data_downloader.storage._paths — helpers de filesystem para storage layer.

Owner: Aria (architect) + Sol (storage).
Origem: ADR-024 (catalog em ``data/_internal/``) — directive Pichau live smoke
v1.1.0 (2026-05-07): usuário abria Explorer em ``data/`` e via ``catalog.db``
junto com os parquets, gerando confusão UX.

Funções aqui são best-effort, não-bloqueantes: aplicar Windows
``FILE_ATTRIBUTE_HIDDEN`` em diretório falha silenciosamente em outros OS,
em path inexistente, ou sem permissão. Path operations Python (``Path``,
``os``) ignoram o attribute Hidden — só o Windows Explorer respeita o
default de "ocultar arquivos ocultos".
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["hide_directory_windows"]


# Windows GetFileAttributes/SetFileAttributes constant.
# Ref: https://learn.microsoft.com/en-us/windows/win32/fileio/file-attribute-constants
_FILE_ATTRIBUTE_HIDDEN = 0x02


def hide_directory_windows(path: Path) -> None:
    """Aplica ``FILE_ATTRIBUTE_HIDDEN`` (Windows) em ``path``.

    Best-effort: silenciosamente no-op em:

    - Plataformas não-Windows (``sys.platform != "win32"``);
    - ``path`` inexistente;
    - Falha de permissão (``ctypes.WinError`` ou exceção genérica);
    - ``ctypes`` indisponível (improvável mas defensivo).

    O atributo Hidden em Windows faz com que Explorer **default** oculte o
    diretório, mas Python (``Path.exists``, ``open``, etc.) continua
    enxergando normalmente — i.e. não interfere com runtime do app.

    Args:
        path: Diretório (ou arquivo) a marcar como Hidden.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as t:
        ...     hide_directory_windows(pathlib.Path(t))  # no-op em CI Linux
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # local import — evita custo em platforms não-Windows
    except ImportError:
        return
    try:
        # ``windll`` só existe em Windows; ``ctypes`` em Linux não tem o
        # attribute. Em sys.platform=="win32" o type checker enxerga normal.
        ctypes.windll.kernel32.SetFileAttributesW(
            str(path),
            _FILE_ATTRIBUTE_HIDDEN,
        )
    except Exception:
        # Best-effort — falha não bloqueia operação de Catalog.__init__.
        return
