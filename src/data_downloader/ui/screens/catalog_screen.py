"""data_downloader.ui.screens.catalog_screen — Tela Catálogo (browse).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

Tela de listagem e gerenciamento de partições já baixadas. Permite filtrar,
selecionar, validar checksum, abrir pasta e apagar (com confirmação
destrutiva).

Componentes (Felix Story 3.3):

    - **QTableView + QSortFilterProxyModel** — tabela com colunas: contract,
      year, month, row_count, size_mb, last_modified, schema_version.
    - **Search box + Filtros drawer** — filtro por símbolo (Ctrl+F) +
      drawer com filtros avançados (exchange, date range).
    - **Detail panel** (``QSplitter`` bottom) — pasta, schema, DLL, checksum,
      ações (VALIDAR, ABRIR PASTA, REPETIR DOWNLOAD, APAGAR).
    - **Footer summary** — "{N} partições, {total_mb} MB total" + drift
      indicator se aplicável.

5 estados (WIREFRAMES.md §"Tela 2 — CatalogScreen"):

    - **Normal** — tabela populada; detail panel se row selected.
    - **Loading** — skeleton rows animados.
    - **Error** — ``ERR_CATALOG_DRIFT`` ou ``ERR_DISK_PERMISSION`` ou
      ``ERR_CATALOG_LOCKED``; CTA reconciliar/abrir pasta/retry.
    - **Empty** (primeira vez) — ícone xl + ``EMP_CATALOG_FIRST_RUN`` +
      CTA primário ``BTN_DOWNLOAD``.
    - **Empty filtrado** — ``EMP_CATALOG_FILTERED`` + ``BTN_CLEAR_FILTERS``.
    - **Success** — toast verde após reconcile/delete/validate.

Confirmação destrutiva (apagar): modal ``PMT_DELETE_CONFIRM`` exige usuário
digitar "APAGAR" para habilitar botão (PRINCIPLES.md §H5).

Atalhos (THEME.md §6 — CatalogScreen):

    - ``Ctrl+R`` — Refresh (NÃO F5 — finding M10).
    - ``Ctrl+F`` — Foca campo de busca.
    - ``Esc``    — Limpa filtros (se algum); senão no-op.
    - ``Enter``  — Abre detalhe da row selecionada.
    - ``Delete`` — Apagar row (com confirmação destrutiva).
    - ``Ctrl+O`` — Abrir pasta no Explorer.

Adapter: ``ui/adapters/catalog_adapter.py`` consome storage queries +
``public_api.read()``.

Referências:
    - docs/ux/WIREFRAMES.md (Tela 2)
    - docs/ux/FLOWS.md (Flow 2 — Browse Catálogo)
    - docs/ux/MICROCOPY_CATALOG.md §17b.2 (IDs CatalogScreen)
    - docs/ux/QT_PATTERNS.md §6 (atalhos — Ctrl+R não F5)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__ = ["CatalogScreen"]


class CatalogScreen:
    """Placeholder — Epic 3 Story 3.3 implementa ``QWidget`` real.

    Browse de partições baixadas. Filtros + ações destrutivas com confirm.
    Felix implementa fielmente ao wireframe Uma.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.3 implementa CatalogScreen. "
            "Veja docs/ux/WIREFRAMES.md (Tela 2) + COUNCIL-12."
        )
