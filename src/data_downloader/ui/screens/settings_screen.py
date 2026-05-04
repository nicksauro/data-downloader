"""data_downloader.ui.screens.settings_screen — Tela Configurações.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Tela de configurações do app. Quatro seções principais (cada uma em
``QGroupBox`` dentro de ``QScrollArea``).

Componentes (Felix Story 3.4):

    - **ProfitDLL** — status conexão, path DLL, .env vars não-vazias
      (mascaradas, com [Mostrar]/[Esconder]), botão TESTAR CONEXÃO.
    - **Storage** — pasta data atual, espaço disco, status catálogo,
      ações MUDAR PASTA / ABRIR EXPLORER / VERIFICAR INTEGRIDADE.
    - **Performance** (read-only) — display de defaults DLL queue size,
      storage queue size, chunk size, max retries. Sem edição inline
      (mudanças requerem advanced flags — consulte docs/perf/).
    - **About** — versão app, versão DLL, schema version, links docs/bugs.

5 estados (WIREFRAMES.md §"Tela 3 — SettingsScreen"):

    - **Normal** — todas as seções populadas com valores correntes.
    - **Loading** — durante TESTAR CONEXÃO (status DLL "↻ Testando...").
    - **Error** — teste DLL falhou; card vermelho com microcopy + RETRY.
    - **Empty** — primeira execução sem .env; passos educativos
      ``EMP_SETTINGS_DLL_FIRST_RUN_*``.
    - **Success** — toast verde 3s após salvar (``TST_SETTINGS_SAVED``).

Atalhos (THEME.md §6 — SettingsScreen):

    - ``Ctrl+S`` — Salvar (atalho convencional).
    - ``Esc``    — Sair sem salvar (com confirm se mudou algo).

QFileDialog para "MUDAR PASTA" usa ``DontUseNativeDialog`` (ADR-003 amendment,
finding M9, QT_PATTERNS §1) — wrapper centralizado em ``widgets/file_dialog.py``.

Adapter: para .env e teste DLL, usa adapter dedicado (Epic 3 Story 3.4 cria).
Para storage, reusa ``catalog_adapter`` para integrity check.

Referências:
    - docs/ux/WIREFRAMES.md (Tela 3)
    - docs/ux/MICROCOPY_CATALOG.md §17b.3 (IDs SettingsScreen)
    - docs/ux/QT_PATTERNS.md §1 (DontUseNativeDialog)
    - docs/adr/ADR-003-front-pyside6.md amendment 2 (DontUseNativeDialog)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["SettingsScreen"]


class SettingsScreen:
    """Placeholder — Epic 3 Story 3.4 implementa ``QWidget`` real.

    Configurações em 4 seções (DLL, Storage, Performance, About). Performance
    é read-only; mudanças requerem advanced flags (zero alucinação P9).
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.4 implementa SettingsScreen. "
            "Veja docs/ux/WIREFRAMES.md (Tela 3) + COUNCIL-12."
        )
