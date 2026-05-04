"""data_downloader.ui.adapters.catalog_adapter — Bridge para catálogo + vigent_contract.

Owner: Felix (frontend-dev).

**Status:** Epic 3 — TODO (placeholder skeleton, COUNCIL-12 prep).

QObject vivendo em QThread separada. Encapsula:

    - Listagem de partições do catálogo (consumido por CatalogScreen).
    - ``vigent_contract()`` (consumido por SymbolPicker para autocomplete).
    - ``read()`` para queries inline (V2 — não MVP Epic 3).
    - Operações destrutivas (delete partition) — chamadas com confirm prévio
      no UI layer (PRINCIPLES.md §H5).

Padrão (QT_PATTERNS §2.3):

    class CatalogAdapter(QObject):
        partitions_loaded = Signal(object)   # list[PartitionMetadata]
        vigent_loaded     = Signal(object)   # str (contrato vigente)
        delete_done       = Signal(str)      # symbol apagado
        error             = Signal(str)      # mensagem humanizada

        @Slot()
        def load_partitions(self) -> None: ...

        @Slot(str)
        def get_vigent(self, asset: str) -> None: ...

        @Slot(str, str, int, int)
        def delete_partition(self, symbol: str, exchange: str, year: int, month: int) -> None: ...

Operações de listagem podem ser caras (> 1000 partições). Sempre rodam em
QThread separada (R11) e emitem signal só quando completa — UI mostra
loading skeleton enquanto.

Reconciliação (drift detected): adapter chama ``doctor --reconcile``
equivalente via API interna; emite progress + final.

Referências:
    - docs/ux/QT_PATTERNS.md §2.3
    - docs/ux/FLOWS.md (Flow 2 — Browse Catálogo)
    - docs/decisions/COUNCIL-12-epic3-prep.md
    - src/data_downloader/public_api/__init__.py (vigent_contract, read)
"""

from __future__ import annotations

__all__ = ["CatalogAdapter"]


class CatalogAdapter:
    """Placeholder — Epic 3 Story 3.3 implementa ``QObject`` real em QThread.

    Bridge entre MainThread Qt e queries de catálogo + ``vigent_contract()``.
    UI nunca importa storage internals — passa por este adapter.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "Epic 3 — Story 3.3 implementa CatalogAdapter. "
            "Veja docs/ux/QT_PATTERNS.md §2.3 + COUNCIL-12."
        )
