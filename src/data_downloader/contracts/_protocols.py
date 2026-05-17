"""data_downloader.contracts._protocols — Protocols por fronteira (ADR-030).

Owner: Aria (architect) | Impl: Sol (Story 4.28 P0-A2).

Define os 5 Protocols ``runtime_checkable`` prometidos em ``ARCHITECTURE.md
§6`` (v1.1.0 H21) e formalizados em ADR-030 — Protocol-First Boundary Policy.
Convenção:

- ``runtime_checkable`` em TODOS para suportar ``isinstance(obj, Protocol)``
  (asserts defensivos em testes + adapter dispatchers em runtime).
- **Forma mínima reconhecível** — Protocols capturam SOMENTE a superfície
  pública usada nas fronteiras reais; métodos privados (``_conn_or_raise``,
  ``_transaction``, ``_translate_trade_raw``) NÃO entram (são detalhes de
  impl).
- **NÃO duplicar assinatura de impl** — usar ``*args: object,
  **kwargs: object`` quando a assinatura concreta tem keyword args
  específicos da implementação (caller cruzando fronteira não deve
  acoplar-se a kwargs default).
- Implementações concretas (``ParquetWriter``, ``Catalog``, ``ProfitDLL``)
  NÃO herdam destes Protocols — conformidade é structural (duck typing).
  Ver INV-PROTO-1 em ADR-030 §5.

Convenção de migração (opt-in — ADR-030 §2.2):

| Quem                            | Obrigação                                       |
|---------------------------------|-------------------------------------------------|
| Código existente (v1.3.0)       | Mantém imports concretos. Nenhuma mudança.      |
| Código novo (>= v1.4.0)         | DEVE usar Protocols ao cruzar fronteira de camada. |
| Testes novos                    | DEVEM type-hint via Protocols (mocks duck-typed).|
| Implementações concretas        | NÃO herdam (structural subtyping).              |

Re-exportado via ``data_downloader.contracts.__init__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator

    from data_downloader.public_api.handle import DownloadProgress, DownloadResult


__all__ = [
    "CatalogProtocol",
    "DLLClientProtocol",
    "DownloadHandle",
    "ProgressEmitter",
    "WriterProtocol",
]


# ---------------------------------------------------------------------------
# WriterProtocol — fronteira storage interna (ADR-030 §2.1)
# ---------------------------------------------------------------------------


@runtime_checkable
class WriterProtocol(Protocol):
    """Fronteira ``orchestrator → storage`` (writes atômicos por partição).

    Captura a superfície mínima usada pelo orchestrator ao persistir um
    lote de trades. ``compact_month`` NÃO entra no Protocol porque hoje é
    um **function** module-level em ``storage.parquet_writer`` (não um
    método de instância) — ADR-030 §8 Q1 deixou a porta aberta; a forma
    real é "function callable, não method", logo permanece fora.
    A compactação é orquestrada via ``Catalog.maybe_compact_month``
    (que delega a function), preservando a fronteira sem inflar o Protocol.

    Implementação concreta: :class:`data_downloader.storage.parquet_writer.ParquetWriter`.
    Implementações alternativas futuras (ex.: ``ArcticWriter``) só
    precisam expor ``write`` com a mesma forma mínima.
    """

    def write(
        self,
        trades: object,
        partition: object,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        """Persiste um lote de trades numa partição.

        Forma mínima reconhecível — assinatura detalhada vive em
        ``ParquetWriter.write`` (dll_version, chunk_id kwargs específicos
        de impl). Caller cruzando fronteira NÃO depende dos kwargs concretos.

        Returns:
            ``WriteResult`` (path, row_count, bounds, sha256, file_size).
            Typed como ``object`` para evitar import circular contracts→storage.
        """
        ...


# ---------------------------------------------------------------------------
# CatalogProtocol — fronteira catalog (ADR-030 §2.1)
# ---------------------------------------------------------------------------


@runtime_checkable
class CatalogProtocol(Protocol):
    """Fronteira ``orchestrator/cli/ui → catalog`` (SQLite single-process).

    Captura métodos críticos do catálogo usados em mais de uma camada;
    NÃO replica os 50+ métodos públicos (a maioria é interno do
    orchestrator). Métodos privados (``_conn_or_raise``, ``_transaction``)
    NÃO entram — fronteira é a interface PÚBLICA.

    Pré-Story 4.22, ``recover_pending_commits`` e ``pending_commit`` ainda
    não existem em ``Catalog``. ADR-030 §2.1 os menciona porque Aria
    desenhou a fronteira "completa". Para esta story (4.28) precisamos
    que ``isinstance(Catalog(...), CatalogProtocol)`` retorne True; logo
    o Protocol inclui SOMENTE métodos que existem hoje. Métodos futuros
    (Story 4.22) podem ser adicionados quando ``Catalog`` ganhar a
    superfície correspondente — Protocol adicional é breaking change na
    fronteira (Aria approval), mas adicionar método NOVO é aditivo (callers
    pré-existentes mantêm conformidade structural).

    Implementação concreta: :class:`data_downloader.storage.catalog.Catalog`.
    """

    def register_partition(self, /, *args: object, **kwargs: object) -> None:
        """UPSERT (write_result, partition) no catalog (two-phase commit emulado).

        Forma mínima — assinatura concreta tem ``write_result``,
        ``partition`` e kwargs (``job_id``, ``day``). Caller usa kwargs
        nomeados, Protocol não impõe forma estrita (kwargs varying entre
        callers cruzando fronteira é OK).
        """
        ...

    def completed_days(
        self,
        symbol: str,
        exchange: str,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        """Conjunto de ``date`` já baixados em [start, end] — chunk_ledger.

        Forma mínima — Catalog tem ``(symbol, exchange, start, end)``;
        Protocol aceita kwargs extras (resilience a evolução).

        Returns:
            ``set[date]`` (typed como ``object`` para evitar import datetime
            no Protocol layer).
        """
        ...

    def maybe_compact_month(self, /, *args: object, **kwargs: object) -> object:
        """Compacta mês se completo (ADR-025 — auto-compactação).

        Delega para ``compact_month`` module-level no writer. Retorna
        ``bool`` (compactou ou não). Typed como ``object`` na fronteira.
        """
        ...

    def close(self) -> None:
        """Fecha conexão SQLite. Idempotente."""
        ...


# ---------------------------------------------------------------------------
# DLLClientProtocol — fronteira DLL (ADR-030 §2.1)
# ---------------------------------------------------------------------------


@runtime_checkable
class DLLClientProtocol(Protocol):
    """Fronteira ``orchestrator → DLL`` (ADR-014 mockable wrapper).

    Captura a superfície usada pelo orchestrator para inicializar a DLL,
    aguardar handshake MARKET_CONNECTED, requisitar history, gerenciar
    subscriptions e finalizar. Implementação concreta:
    :class:`data_downloader.dll.wrapper.ProfitDLL`.

    Implementações mock (testes — ADR-014) precisam apenas expor estes
    métodos com forma minimamente compatível para satisfazer
    ``isinstance(mock, DLLClientProtocol)``.
    """

    def initialize_market_only(
        self,
        key: str,
        user: str,
        password: str,
        /,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Inicializa a DLL em modo market-only (sem trading).

        Forma mínima — concreto tem kwargs ``register_extra_callbacks``
        e ``minimal_handshake`` (defaults False).
        """
        ...

    def wait_market_connected(self, /, *args: object, **kwargs: object) -> bool:
        """Aguarda MARKET_CONNECTED (retry policy). Forma mínima — kwargs varia."""
        ...

    def get_history_trades(self, /, *args: object, **kwargs: object) -> int:
        """Solicita download de trades históricos.

        Concreto: ``(ticker, exchange, dt_start, dt_end)`` posicional.
        Retorna código DLL (0=ok, NL_* negativo em erro).
        """
        ...

    def subscribe_ticker(self, ticker: str, exchange: str, /) -> int:
        """Subscribe ticker (market-data). Retorna código DLL."""
        ...

    def unsubscribe_ticker(self, ticker: str, exchange: str, /) -> int:
        """Unsubscribe ticker. Retorna código DLL."""
        ...

    def finalize(self) -> None:
        """Finaliza DLL (restaura cwd, libera handles). Idempotente."""
        ...


# ---------------------------------------------------------------------------
# ProgressEmitter — fronteira orchestrator → UI/CLI (ADR-030 §2.1 / Q3)
# ---------------------------------------------------------------------------


@runtime_checkable
class ProgressEmitter(Protocol):
    """Fronteira ``orchestrator → UI/CLI`` para events de progresso.

    ADR-030 §8 Q3 resolveu: **um único método** ``emit(event)`` em vez
    dos 3 originais (``emit_progress``/``emit_finished``/``emit_failed``).
    Razão: o orchestrator hoje emite um único tipo de evento
    (``ProgressEvent``) na fila; UI/CLI consomem via ``handle.events()``
    iterator. Múltiplos métodos forçariam dispatch redundante.

    Implementações futuras:
    - ``QtProgressEmitter`` — re-emite em ``QtSignal`` (Epic 3 UI).
    - ``RichProgressEmitter`` — atualiza barra Rich (CLI download).
    - ``NullProgressEmitter`` — no-op (Jupyter / library mode).
    """

    def emit(self, event: object) -> None:
        """Emite um evento de progresso (typed como ``object`` na fronteira).

        Caller passa ``DownloadProgress`` (frozen dataclass do public_api).
        Implementação concreta DEVE ser tolerante a queue full (drop
        silencioso — R21, observability não bloqueia hot path).
        """
        ...


# ---------------------------------------------------------------------------
# DownloadHandle — fronteira public_api (ADR-030 §2.1 / Q2 — re-export)
# ---------------------------------------------------------------------------


@runtime_checkable
class DownloadHandle(Protocol):
    """Fronteira pública retornada por :func:`data_downloader.public_api.download`.

    ADR-030 §8 Q2 resolveu: este Protocol espelha a forma da classe
    concreta :class:`data_downloader.public_api.handle.DownloadHandle`
    (ADR-007a). Renomear ou re-exportar criava confusão de import path;
    definir Protocol homônimo deixa claro:

    - Caller de ``download()`` recebe sempre a **classe concreta**.
    - Code de adapter (tests / wrappers / proxy) tipa via este **Protocol**
      e recebe duck-typed conformance (incluindo mocks).

    Conformidade structural: ``isinstance(concrete_handle, DownloadHandle)``
    deve retornar True (validado em smoke test AC9).
    """

    job_id: str

    def cancel(self, /, *args: object, **kwargs: object) -> bool:
        """Cancela download (graceful drain). Idempotente."""
        ...

    def result(self, /, *args: object, **kwargs: object) -> DownloadResult:
        """Bloqueia até worker terminar; retorna DownloadResult.

        Raises ``OperationCancelled`` se status=cancelled (H10).
        """
        ...

    def events(self) -> Iterator[DownloadProgress]:
        """Itera sobre :class:`DownloadProgress` emitidos pelo worker."""
        ...
