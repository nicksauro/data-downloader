"""data_downloader.ui.widgets.period_picker — Picker de período com presets.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Widget composto para selecionar período. Combina ``QComboBox`` de presets
com 2 ``QDateEdit`` que aparecem quando o preset "Customizado" é escolhido.

Comportamento (Felix Story 3.2):

    - **Default** — preset "Mês corrente" (``PLH_PERIOD_CURRENT_MONTH``).
    - **Presets disponíveis**:
        - ``PLH_PERIOD_TODAY`` — Hoje
        - ``PLH_PERIOD_YESTERDAY`` — Ontem
        - ``PLH_PERIOD_THIS_WEEK`` — Esta semana
        - ``PLH_PERIOD_CURRENT_MONTH`` — Mês corrente
        - ``PLH_PERIOD_LAST_MONTH`` — Mês anterior
        - ``PLH_PERIOD_CUSTOM`` — Customizado (expande 2 QDateEdit)
    - **Display formatado** — abaixo do dropdown, mostra range expandido:
      "01/03/2026 → 03/05/2026 (~2 meses)" usando ``LBL_PERIOD_RANGE_DISPLAY``.
    - **Validação inline**:
        - Start > End → ``ERR_INVALID_PERIOD``
        - End no futuro → ``ERR_PERIOD_FUTURE``
        - Start fora do range DLL → ``ERR_PERIOD_TOO_OLD``
    - **Warning inline** — período > 30 dias → ``WAR_LARGE_PERIOD`` (não
      bloqueia, informa). > 90 dias → ``PMT_LARGE_PERIOD_CONFIRM`` antes
      de permitir start.
    - **Estimativa** — abaixo, banda honesta consultando Pyro baseline:
      ``LBL_ESTIMATE_RANGE`` ("Estimativa: 3-7 minutos") OU
      ``LBL_ESTIMATE_UNAVAILABLE`` (P9 — zero alucinação).
    - **Tooltip** — ``TIP_PERIOD``.

Microcopy referenced:
    - ``LBL_PERIOD``, ``LBL_START_DATE``, ``LBL_END_DATE``
    - ``LBL_PERIOD_RANGE_DISPLAY``, ``LBL_ESTIMATE_RANGE``, ``LBL_ESTIMATE_UNAVAILABLE``
    - ``PLH_PERIOD_*`` (todos os presets)
    - ``PLH_START_DATE``, ``PLH_END_DATE``
    - ``WAR_LARGE_PERIOD``, ``PMT_LARGE_PERIOD_CONFIRM``
    - ``ERR_INVALID_PERIOD``, ``ERR_PERIOD_FUTURE``, ``ERR_PERIOD_TOO_OLD``
    - ``TIP_PERIOD``

Referências:
    - docs/ux/WIREFRAMES.md (DownloadScreen)
    - docs/ux/MICROCOPY_CATALOG.md
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["PeriodPicker"]


class PeriodPicker:
    """Placeholder — Epic 3 Story 3.2 implementa ``QWidget`` real.

    Dropdown presets + custom range com validação inline e warning para
    períodos grandes. Estimativa honesta via Pyro baseline.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.2 implementa PeriodPicker. "
            "Veja docs/ux/WIREFRAMES.md (DownloadScreen) + COUNCIL-12."
        )
