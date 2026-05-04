"""data_downloader.ui.main_window — QMainWindow shell.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

``MainWindow`` é o frame geral do app desktop:

    - **Sidebar** (esquerda) — nav: Download / Catálogo / Settings.
    - **Main area** (central) — ``QStackedWidget`` com a tela ativa.
    - **Status bar** (inferior) — DLL status, pasta atual, versão app.

Implementação real será feita na Story 3.1 (PySide6 shell + nav).

Atalhos globais (registrados aqui via QShortcut com ``Qt.ApplicationShortcut``):

    - ``Ctrl+D`` — DownloadScreen
    - ``Ctrl+B`` — CatalogScreen
    - ``Ctrl+,`` — SettingsScreen
    - ``Ctrl+R`` — Refresh contextual (delegado para tela ativa)
    - ``Ctrl+Q`` — Sair (com confirm se download em progresso)
    - ``Ctrl+/`` — Cheat sheet modal

``Esc`` é context-aware via ``eventFilter`` no MainWindow despachando para
handler do contexto ativo (ver THEME.md §6 — ordem de prioridade).

Referências:
    - docs/ux/WIREFRAMES.md (MainWindow frame geral)
    - docs/ux/THEME.md §6 (atalhos teclado)
    - docs/ux/QT_PATTERNS.md §6 (atalhos Qt)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["MainWindow"]


class MainWindow:
    """Placeholder — Epic 3 Story 3.1 implementa ``QMainWindow`` real.

    Este placeholder existe apenas para reservar o nome do módulo e
    documentar o contrato esperado. NÃO importe nem use em produção até
    Story 3.1.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.1 implementa QMainWindow shell + nav. "
            "Veja docs/decisions/COUNCIL-12-epic3-prep.md."
        )
