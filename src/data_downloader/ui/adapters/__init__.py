"""data_downloader.ui.adapters — Bridges QThread → public_api (Epic 3).

Owner: Felix (frontend-dev).

**Status:** Epic 3 — TODO (placeholders skeleton, COUNCIL-12 prep).

Adapters são QObjects vivendo em ``QThread`` separadas. Encapsulam toda
chamada a ``public_api`` para garantir que MainThread Qt nunca bloqueie
(R11 — UI não bloqueia).

Padrão canônico (QT_PATTERNS §2.3):

    - QObject + ``moveToThread(QThread)``.
    - Slots ``@Slot(...)`` recebem comandos da MainThread via
      ``QMetaObject.invokeMethod(adapter, 'method', Qt.QueuedConnection)``.
    - Signals carregam **objetos tipados** (``Signal(object)`` carregando
      dataclass do public_api — NÃO ``Signal(dict)``).
    - Conexões cross-thread DEVEM declarar ``Qt.QueuedConnection`` explícito.

Adapters previstos:

    - ``download_adapter.py``  — Story 3.2 — bridge para ``download()`` +
      ``DownloadHandle.stream()/cancel()``.
    - ``catalog_adapter.py``   — Story 3.3 — bridge para listagem de
      partições + ``vigent_contract()`` (consumido por SymbolPicker).

Adapters futuros (não criados ainda):

    - ``settings_adapter.py``  — Story 3.4 — bridge para .env load/save +
      teste DLL conexão.

**Fronteira firme (Aria):** UI nunca importa internals do backend
(orchestrator, dll, storage). Apenas ``public_api``. Adapters são a
única camada que faz essa ponte.

Referências:
    - docs/ux/QT_PATTERNS.md §2 (signal/slot canônico)
    - docs/adr/ADR-003-front-pyside6.md
    - docs/adr/ADR-007 (public_api fronteira)
    - docs/decisions/COUNCIL-12-epic3-prep.md
"""

from __future__ import annotations

__all__: list[str] = []
