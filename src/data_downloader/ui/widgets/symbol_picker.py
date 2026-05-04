"""data_downloader.ui.widgets.symbol_picker — Picker de símbolo com autocomplete.

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Widget composto para selecionar contrato/símbolo. Combina ``QComboBox``
editável com autocomplete consumindo ``vigent_contract()`` via
``CatalogAdapter`` (não chama ``public_api`` diretamente — passa pelo
adapter em QThread, conforme R11).

Comportamento (Felix Story 3.2):

    - **Default value** — última usada (cache ``~/.data-downloader/last_symbol``)
      ou contrato vigente do WDO.
    - **Autocomplete** — mostra contrato vigente em destaque + alternativas.
      Format: "WDOJ26 (vigente até 28/03/2026)" usando ``LBL_CONTRACT_VALID_UNTIL``.
    - **Validação inline** — se símbolo digitado não é contrato vigente,
      mostra erro inline ``ERR_DLL_INVALID_TICKER`` ao lado do campo.
    - **Botão "Listar Vigentes"** — abre modal com tabela de contratos
      vigentes filtráveis por asset (WDO, WIN, etc.).
    - **Tooltip** — ``TIP_SYMBOL`` (THEME — context).

Microcopy referenced:
    - ``LBL_SYMBOL`` — label do campo
    - ``PLH_SYMBOL`` — placeholder "ex: WDOJ26"
    - ``LBL_CONTRACT_VALID_UNTIL`` — sufixo "vigente até {date}"
    - ``BTN_LIST_CONTRACTS`` — "Listar Vigentes"
    - ``ERR_DLL_INVALID_TICKER`` — erro inline
    - ``PLH_SYMBOL_SUGGESTED_HINT`` — hint quando sugerido
    - ``TIP_SYMBOL`` — tooltip

Referências:
    - docs/ux/WIREFRAMES.md (DownloadScreen)
    - docs/ux/MICROCOPY_CATALOG.md
    - docs/ux/QT_PATTERNS.md §2 (signal/slot via adapter)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["SymbolPicker"]


class SymbolPicker:
    """Placeholder — Epic 3 Story 3.2 implementa ``QWidget`` real.

    Autocomplete de contratos vigentes com validação inline. Consome
    ``vigent_contract()`` via CatalogAdapter (R11 — não bloqueia MainThread).
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.2 implementa SymbolPicker. "
            "Veja docs/ux/WIREFRAMES.md (DownloadScreen) + COUNCIL-12."
        )
