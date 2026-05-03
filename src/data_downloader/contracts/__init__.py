"""data_downloader.contracts — Protocols compartilhados entre camadas.

Owner: Aria (architect).

Espaço para ``typing.Protocol`` e ``ABC``s que definem interfaces entre
``dll/``, ``orchestrator/``, ``storage/`` e ``public_api/`` sem criar
acoplamento estrutural. Story 1.1 cria apenas o esqueleto; Protocols entram
quando as Stories de implementação precisarem deles (1.3+).

Exemplo futuro::

    class TradeSink(Protocol):
        def write(self, trades: list[Trade]) -> None: ...
"""

from __future__ import annotations

__all__: list[str] = []
