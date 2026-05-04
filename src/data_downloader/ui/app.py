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

__all__ = ["main"]


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
    qss_path = Path(__file__).parent / "assets" / "style.qss"
    if qss_path.exists():
        # Best-effort — QSS é cosmético; UI funciona sem.
        with contextlib.suppress(OSError):
            app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    # Import deferido para evitar custo se main() não for chamado (ex.:
    # ``import data_downloader.ui.app`` em REPL para inspeção).
    from data_downloader.ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
