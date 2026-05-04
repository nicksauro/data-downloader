"""data_downloader.ui.shortcuts — QShortcut registry centralizado.

Owner: Felix (frontend-dev) | Authority: Uma (THEME.md §6 — atalhos canônicos).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Registry centralizado de ``QShortcut`` para todos os atalhos da UI.

Felix mantém este módulo em sync com a tabela canônica em ``THEME.md §6``
(Uma é autoridade — qualquer mudança/adição passa por Uma + atualiza
THEME.md + atualiza help dialog cheat sheet F1/Ctrl+/).

Padrão (QT_PATTERNS §6):

    from PySide6.QtGui import QShortcut, QKeySequence
    from PySide6.QtCore import Qt

    # Atalhos globais — escopo ApplicationShortcut
    self._sc_download = QShortcut(QKeySequence("Ctrl+D"), main_window)
    self._sc_download.setContext(Qt.ApplicationShortcut)
    self._sc_download.activated.connect(lambda: nav.set_current("download"))

    # Atalhos por tela — escopo WidgetWithChildrenShortcut
    # Ex: Esc na DownloadScreen só dispara quando DownloadScreen tem foco.
    self._sc_cancel = QShortcut(QKeySequence(Qt.Key_Escape), download_screen)
    self._sc_cancel.setContext(Qt.WidgetWithChildrenShortcut)
    self._sc_cancel.activated.connect(download_screen.on_cancel_requested)

Atalhos canônicos (THEME.md §6 — referência completa lá):

GLOBAIS (Qt.ApplicationShortcut):
    - Ctrl+D — Foca/abre DownloadScreen
    - Ctrl+B — Foca/abre CatalogScreen
    - Ctrl+, — Foca/abre SettingsScreen
    - Ctrl+R — Refresh contextual (delegado para tela ativa)
    - Ctrl+Q — Sair (com confirm se download em progresso)
    - Ctrl+/ — Cheat sheet modal (todos atalhos da tela ativa + globais)
    - F1     — Ajuda contextual (V2)

DOWNLOADSCREEN (Qt.WidgetWithChildrenShortcut):
    - Ctrl+D — Iniciar download (se válido)
    - Ctrl+R — Repetir último download
    - Esc    — Cancela download ativo (context-aware — ver THEME §6 prioridade)
    - Ctrl+L — Foca campo símbolo
    - Ctrl+E — Edita período

CATALOGSCREEN (Qt.WidgetWithChildrenShortcut):
    - Ctrl+R — Refresh catálogo (NÃO F5 — finding M10)
    - Ctrl+F — Foca campo de busca
    - Esc    — Limpa filtros (se algum)
    - Enter  — Abre detalhe do row selecionado
    - Delete — Apagar row (com confirmação destrutiva)
    - Ctrl+O — Abrir pasta no Explorer

SETTINGSSCREEN (Qt.WidgetWithChildrenShortcut):
    - Ctrl+S — Salvar
    - Esc    — Sair sem salvar (com confirm se mudou algo)

Esc context-aware: implementação via ``eventFilter`` no MainWindow
despachando para handler do contexto ativo (THEME §6 — ordem de prioridade).

Cheat sheet modal (Ctrl+/): Felix implementa em Epic 3 Story 3.1; lista
todos atalhos da tela ativa + globais lendo este registry.

Referências:
    - docs/ux/THEME.md §6 (autoridade canônica de atalhos)
    - docs/ux/QT_PATTERNS.md §6 (implementação Qt)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["register_global_shortcuts", "register_screen_shortcuts"]


def register_global_shortcuts() -> None:
    """Placeholder — Epic 3 Story 3.1 implementa registry global.

    Registra QShortcut com Qt.ApplicationShortcut para Ctrl+D/B/,/R/Q//
    no MainWindow. Conecta cada um a seu handler.
    """
    raise NotImplementedError(
        "Epic 3 — Story 3.1 implementa register_global_shortcuts. "
        "Veja docs/ux/THEME.md §6 + COUNCIL-12."
    )


def register_screen_shortcuts() -> None:
    """Placeholder — Epic 3 Stories 3.2-3.4 implementam por tela.

    Cada screen registra seus QShortcut com Qt.WidgetWithChildrenShortcut
    no construtor da tela. Esc context-aware via eventFilter no MainWindow.
    """
    raise NotImplementedError(
        "Epic 3 — Stories 3.2-3.4 implementam register_screen_shortcuts. "
        "Veja docs/ux/THEME.md §6 + COUNCIL-12."
    )
