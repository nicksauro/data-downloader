"""data_downloader.ui.screens — Telas principais da UI Qt (Epic 3).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholders skeleton, COUNCIL-12 prep).

Cada tela é um ``QWidget`` (ou ``QMainWindow`` filho) com 5 estados internos
(normal / loading / error / empty / success). Felix implementa cada uma na
Story correspondente:

    - ``download_screen.py`` — Story 3.2 (golden path 1 botão)
    - ``catalog_screen.py``  — Story 3.3 (browse + filter + delete + revalidate)
    - ``settings_screen.py`` — Story 3.4 (DLL status, storage, performance, about)

Padrão de 5 estados: ``QStackedWidget`` interno com índices nomeados
(ENUM ``ScreenState.NORMAL/LOADING/ERROR/EMPTY/SUCCESS``). Transições fade
200ms via ``QPropertyAnimation`` (THEME.md §9).

Referências:
    - docs/ux/WIREFRAMES.md (5 estados ASCII por tela)
    - docs/ux/PRINCIPLES.md §3 P1 (5 estados é lei)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__: list[str] = []
