"""data_downloader.ui.app — QApplication entry point.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Esta entrypoint inicializa o ``QApplication`` PySide6, configura HiDPI
awareness, carrega o tema QSS, instancia ``MainWindow`` e executa o event
loop. Implementação real será feita na Story 3.1 (PySide6 shell).

Fluxo previsto (Felix Story 3.1):

    1. Set HiDPI attributes ANTES de criar ``QApplication`` (QT_PATTERNS §3).
    2. Cria ``QApplication(sys.argv)``.
    3. Lê ``assets/style.qss`` e aplica via ``app.setStyleSheet(...)``.
    4. Instancia ``MainWindow`` e mostra.
    5. ``sys.exit(app.exec())``.

Referências:
    - docs/ux/WIREFRAMES.md (MainWindow frame geral)
    - docs/ux/QT_PATTERNS.md §3 (HiDPI), §5 (QSS)
    - docs/adr/ADR-003-front-pyside6.md + amendment (--onedir, DontUseNativeDialog)
    - docs/decisions/COUNCIL-12-epic3-prep.md (sign-off Uma+Felix+Aria)
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> int:
    """Entry point para ``python -m data_downloader.ui.app`` (Epic 3 — TODO).

    Implementação real na Story 3.1 inicializa QApplication, carrega tema,
    cria MainWindow e executa o event loop. Atualmente apenas placeholder.

    Returns:
        Exit code (0 = sucesso). Sempre retorna 1 enquanto não implementado.
    """
    raise NotImplementedError(
        "Epic 3 — Story 3.1 implementa QApplication + MainWindow. "
        "Veja docs/decisions/COUNCIL-12-epic3-prep.md."
    )
