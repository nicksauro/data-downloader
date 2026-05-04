"""data_downloader.ui.screens.download_screen — Tela Baixar Histórico.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Tela primária da UI. Implementa o **golden path 1 clique** — promessa de
produto inegociável (PRINCIPLES.md §1, MANIFEST §1).

Componentes (Felix Story 3.2):

    - **SymbolPicker** (``widgets/symbol_picker.py``) — autocomplete consumindo
      ``vigent_contract()`` via CatalogAdapter.
    - **PeriodPicker** (``widgets/period_picker.py``) — dropdown com presets
      ``PLH_PERIOD_*`` + opção customizada (2 ``QDateEdit``).
    - **Drawer "Avançado"** (collapsible) — chunk size, retry, pasta destino.
    - **Botão primário grande** ``BTN_DOWNLOAD`` — cor ``primary`` #4F8CFF.
    - **ProgressCard** (``widgets/progress_card.py``) — visível em estado
      Loading; barra ciano/amarelo/verde (state property), subtitle, log
      expansível, botão CANCELAR.

5 estados (WIREFRAMES.md §"Tela 1 — DownloadScreen"):

    - **Normal** — form com defaults; botão BAIXAR ativo.
    - **Loading** — form readonly; ProgressCard visível; botão vira CANCELAR.
        - Sub-estado **Loading.reconnecting** (quirk 99%) — barra amarela +
          banner ``WAR_99_RECONNECT`` literal + spinner.
        - Sub-estado **Loading.cancelling** — botão "Cancelando..." disabled.
    - **Error** — card vermelho com microcopy ``ERR_*`` + botão RETRY.
    - **Empty** — primeira vez; placeholders + welcome subtitle.
    - **Success** — toast verde 5s + tela volta ao normal.

Atalhos (THEME.md §6 — DownloadScreen):

    - ``Ctrl+D`` — Iniciar download (se válido).
    - ``Ctrl+R`` — Repetir último download.
    - ``Esc``    — Cancela download ativo (context-aware).
    - ``Ctrl+L`` — Foca campo símbolo.
    - ``Ctrl+E`` — Edita período.

Adapter: ``ui/adapters/download_adapter.py`` consome ``public_api.download()``.

Referências:
    - docs/ux/WIREFRAMES.md (Tela 1)
    - docs/ux/FLOWS.md (Flow 1 — golden path; Flow 3 — cancel; Flow 4 — quirk 99%)
    - docs/ux/MICROCOPY_CATALOG.md §17b.1 (IDs DownloadScreen)
    - docs/ux/QT_PATTERNS.md §2 (signal/slot), §6 (atalhos)
    - docs/adr/ADR-003-front-pyside6.md
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["DownloadScreen"]


class DownloadScreen:
    """Placeholder — Epic 3 Story 3.2 implementa ``QWidget`` real.

    Promessa de produto: 1 clique no caso comum (defaults inteligentes
    preenchem tudo). Felix implementa fielmente ao wireframe Uma.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.2 implementa DownloadScreen. "
            "Veja docs/ux/WIREFRAMES.md (Tela 1) + COUNCIL-12."
        )
