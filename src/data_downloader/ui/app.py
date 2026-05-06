"""data_downloader.ui.app — QApplication entry point (Story 3.1).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Inicializa o ``QApplication`` PySide6, configura HiDPI awareness, carrega o
tema QSS e instancia ``MainWindow``. Implementação real Epic 3 — Story 3.1
(COUNCIL-23 sign-off Felix+Uma+Aria).

Fluxo:

    1. Set HiDPI attributes ANTES de criar ``QApplication`` (QT_PATTERNS §3).
    2. Cria ``QApplication(sys.argv)``.
    3. Configura logging (Story 2.9 — ``observability.setup_logging``).
    4. Lê ``assets/style.qss`` e aplica via ``app.setStyleSheet(...)``.
    5. Instancia ``MainWindow`` e mostra.
    6. ``sys.exit(app.exec())``.

Referências:
    - docs/ux/WIREFRAMES.md (MainWindow frame geral)
    - docs/ux/QT_PATTERNS.md §3 (HiDPI), §5 (QSS)
    - docs/decisions/COUNCIL-23 (Epic 3 first screen)
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

__all__ = ["main", "_cli_or_ui_dispatch", "_first_non_flag_token"]


def main() -> int:
    """Entry point para ``python -m data_downloader.ui.app`` (Story 3.1).

    Returns:
        Exit code (``0`` = sucesso). Repassa retorno de ``QApplication.exec()``.
    """
    # Configurar logging (Story 2.9). Best-effort — UI não falha se logging
    # config falhar (caller pode estar em ambiente sem stderr).
    try:
        from data_downloader.observability import setup_logging

        setup_logging()
    except Exception:
        pass

    # HiDPI: setAttribute ANTES de criar QApplication (QT_PATTERNS §3).
    # PySide6 6.0+ habilita por default mas mantemos o set explícito para
    # documentar intenção e proteger contra futuros downgrades.
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    # AA_EnableHighDpiScaling foi removido em Qt6 (sempre on) — definimos via
    # ``hasattr`` para tolerância a versões. Mantemos AA_UseHighDpiPixmaps.
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("data-downloader")
    app.setOrganizationName("data-downloader")

    # Tema QSS — fonte única em assets/style.qss (QT_PATTERNS §5).
    #
    # Story 4.15 P0 release-blocker (Pichau live test 2026-05-06): em frozen
    # mode (PyInstaller build) o spec ``data_downloader.spec`` bundla
    # ``../src/data_downloader/ui/assets`` no destino ``assets/`` — ou seja,
    # ``<bundle_root>/assets/style.qss``. Mas ``Path(__file__).parent`` em
    # frozen aponta para ``<bundle_root>/data_downloader/ui/`` → o lookup
    # original procurava em ``<bundle_root>/data_downloader/ui/assets/`` (que
    # NÃO EXISTE no bundle). Resultado: ``setStyleSheet`` nunca era chamado,
    # ``QPushButton[variant="primary"]`` perdia background azul + padding,
    # e o botão "Salvar" no Settings ficava com sizing default Qt (~20px,
    # cinza, mesma dimensão de outros botões secundários) — visualmente
    # passava despercebido. Pichau reportou: "n tem nhnum lugar para
    # apertar save".
    #
    # Fix: tenta múltiplos paths ordenados (dev > frozen-flat > frozen-MEIPASS),
    # primeiro existente vence. Determinístico, sem fallback silencioso.
    qss_candidates: list[Path] = [
        # 1. Dev mode / unfrozen install: relative to module file.
        Path(__file__).parent / "assets" / "style.qss",
        # 2. Frozen mode (PyInstaller --onedir): spec datas put assets/ at root.
        Path(sys.executable).parent / "_internal" / "assets" / "style.qss",
        Path(sys.executable).parent / "assets" / "style.qss",
    ]
    # 3. Frozen mode (sys._MEIPASS) — onefile or runtime-extracted.
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        qss_candidates.append(Path(meipass) / "assets" / "style.qss")

    for qss_path in qss_candidates:
        try:
            if qss_path.is_file():
                # Best-effort — QSS é cosmético; UI funciona sem.
                with contextlib.suppress(OSError):
                    app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
                break
        except OSError:
            continue

    # Import deferido para evitar custo se main() não for chamado (ex.:
    # ``import data_downloader.ui.app`` em REPL para inspeção).
    from data_downloader.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    return int(app.exec())


# =====================================================================
# CLI dispatch (Story 1.7b-followup release-blocker — v1.0.1 fix)
# =====================================================================
#
# PyInstaller bundle (Story 4.4) tem `app.py` como entry point único —
# mas o INSTALL.md publicado promete `data_downloader.exe download
# --symbol ...` (CLI). Sem dispatch, args extras eram passados a
# `QApplication(sys.argv)` que silenciosamente ignorava e abria UI.
#
# v1.0.0 → v1.0.1: dispatcher inicial só inspecionava `argv[1]`, mas
# Typer aceita flags globais ANTES do subcommand
# (e.g. `--log-level DEBUG download ...`), então `argv[1] == "--log-level"`
# caía no fallback UI → carregava Qt → crash 0xC0000409.
#
# Estratégia v1.0.1: percorrer argv pulando flags globais (com ou sem
# valor) até achar o primeiro token não-flag. Esse token decide o
# dispatch.

# Sub-comandos Typer conhecidos (mantém em sync com src/data_downloader/cli.py).
_CLI_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "download",
        "read",
        "contracts",
        "doctor",
        "migrate",
        "metrics",
        "integrity",
        "version",
    }
)

# Flags globais com valor — consomem o próximo token quando NÃO usadas
# em forma `--flag=valor`. Mantém em sync com `_global_callback` em cli.py
# e qualquer `typer.Option(..., "--name", ...)` adicionado no callback global.
_CLI_GLOBAL_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {
        "--log-level",
        "--log-format",
    }
)

# Flags globais sem valor — autocontidas. Help/version sozinhas devem
# ir para o CLI (Typer renderiza ajuda) em vez de abrir UI.
_CLI_GLOBAL_FLAGS_NO_VALUE: frozenset[str] = frozenset(
    {
        "--help",
        "-h",
        "--version",
        "-v",
    }
)


def _first_non_flag_token(args: list[str]) -> str | None:
    """Retorna o primeiro token de ``args`` que não é flag global.

    Pula flags conhecidas (com ou sem valor, incluindo forma ``--flag=val``).
    Retorna ``None`` se ``args`` só contém flags (ou está vazio).
    """
    i = 0
    while i < len(args):
        token = args[i]
        # Forma `--flag=valor` é autocontida — pula 1 token.
        if "=" in token and token.startswith("--"):
            flag_name = token.split("=", 1)[0]
            if flag_name in _CLI_GLOBAL_FLAGS_WITH_VALUE:
                i += 1
                continue
            # Flag desconhecida com `=` — também consideramos autocontida.
            if token.startswith("--"):
                i += 1
                continue
        if token in _CLI_GLOBAL_FLAGS_WITH_VALUE:
            # Pula flag + valor (próximo token).
            i += 2
            continue
        if token in _CLI_GLOBAL_FLAGS_NO_VALUE:
            i += 1
            continue
        if token.startswith("-"):
            # Flag desconhecida (sem `=`) — assumimos autocontida (sem valor)
            # para evitar consumir o subcommand. Typer reportará erro depois.
            i += 1
            continue
        return token
    return None


def _has_cli_only_flag(args: list[str]) -> bool:
    """True se ``args`` contém ``--help/-h/--version/-v`` em qualquer posição.

    Usado quando não há subcommand explícito mas o usuário pediu help/version
    via flag global — deve ir para CLI (Typer trata) ao invés de UI.
    """
    return any(token in _CLI_GLOBAL_FLAGS_NO_VALUE for token in args)


def _cli_or_ui_dispatch() -> int:
    """Roteia para CLI quando ``sys.argv`` contém subcommand; UI senão.

    Heurística (v1.0.1):

    1. ``sys.argv[1:]`` vazio → UI.
    2. Encontra primeiro token não-flag (pulando ``--log-level VAL``,
       ``--log-format=VAL``, ``--help``, etc).
    3. Token está em :data:`_CLI_SUBCOMMANDS` → dispatch CLI.
    4. Sem token não-flag, mas há ``--help/--version`` → dispatch CLI.
    5. Default → UI (preserva behaviour original; subcommand desconhecido
       cai no UI por segurança — usuário double-clicou .exe com lixo).

    **Importante:** este caminho NÃO importa PySide6 quando indo para CLI
    (imports Qt ficam confinados em :func:`main`). Garante que CLI rode
    em terminal sem GUI runtime.
    """
    args = sys.argv[1:]
    if not args:
        return main()

    first_positional = _first_non_flag_token(args)
    if first_positional is not None and first_positional in _CLI_SUBCOMMANDS:
        from data_downloader.cli import app as cli_app

        cli_app()
        return 0

    # Sem subcommand mas com --help/--version: deixa Typer responder.
    if first_positional is None and _has_cli_only_flag(args):
        from data_downloader.cli import app as cli_app

        cli_app()
        return 0

    return main()


if __name__ == "__main__":
    sys.exit(_cli_or_ui_dispatch())
