"""data_downloader.public_api.history — Leitura de histórico (fronteira pública).

Owner: Aria (design) + Dex (impl) + Sol (consult queries).
Story 1.5b — public_api expor read_continuous + read + vigent_contract.

Wrappers ESTÁVEIS sobre primitivas internas. Garantias contratuais
(QUERIES.md §0 + §7):

1. **Estável** — assinatura não muda em minor versions (SemVer ADR-007a).
2. **BRT naive (R7)** — ``datetime`` aceitos são naive (sem TZ).
3. **Sem duplicatas** — dedup é responsabilidade do writer (Story 1.4
   AC8); reader não duplica trades em rollover (Story 1.5b property).
4. **Ordenado** — ``timestamp_ns`` ascendente, cross-contract em
   :func:`read_continuous`.
5. **schema_version** — exposto via metadata Parquet (SCHEMA.md §4).

Exceções públicas — somente subclasses de ``DataDownloaderError``
(``InvalidContract``, etc.). Erros internos (DuckDB, sqlite3, OSError)
podem propagar em cenários degenerados (disco corrompido) — caller
trata com try/except amplo.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    from datetime import date

    from data_downloader.storage.catalog import Catalog


__all__ = [
    "read",
    "read_continuous",
    "vigent_contract",
]


def read(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    exchange: str = "F",
    data_dir: Path | None = None,
    columns: list[str] | None = None,
) -> pa.Table:
    """Lê todos os trades de UM contrato no intervalo ``[start, end]``.

    Wrapper estável sobre :class:`DuckDBReader.read`. Para séries
    multi-contrato (com rollover), use :func:`read_continuous`.

    Garantias (QUERIES.md §1):

    - Datetime BRT naive (R7) — ``start`` e ``end`` SEM timezone.
    - Ordenado por ``timestamp_ns`` ascendente.
    - ``pa.Table`` vazia se nenhuma partição existe (não levanta).
    - schema_version disponível via metadata Parquet.

    Args:
        symbol: Código exato do contrato (ex.: ``"WDOJ26"``, ``"PETR4"``).
            NÃO aceita root (use :func:`read_continuous`).
        start: Inclusivo. Datetime BRT naive.
        end: Inclusivo. Datetime BRT naive.
        exchange: ``"F"`` (BMF, default) ou ``"B"`` (Bovespa).
        data_dir: Raiz dos dados. Default: ``Path("data")`` no cwd.
        columns: Subset de colunas (otimização I/O). Default: todas
            (17 campos canônicos — SCHEMA.md §1.2). NB: na implementação
            atual ``columns`` é apenas declarativo (DuckDBReader já
            retorna as 17 colunas) — projeção será reativada em Story
            futura quando o reader expor ``columns=``.

    Returns:
        ``pa.Table`` com schema canônico (17 campos, SCHEMA.md §1.2).
        Vazia se nenhum trade no intervalo OU partição inexistente.

    Raises:
        ValueError: ``exchange`` fora de ``{"F", "B"}`` ou ``start > end``.
    """
    if exchange not in ("F", "B"):
        raise ValueError(f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}")
    if start > end:
        raise ValueError(
            f"start must be <= end; got start={start.isoformat()}, end={end.isoformat()}"
        )

    # Deferred import — evita circular import via public_api.__init__.
    from data_downloader.storage.duckdb_reader import DuckDBReader

    resolved_data_dir = Path(data_dir) if data_dir is not None else Path("data")

    start_ns = _datetime_to_ns(start)
    end_ns = _datetime_to_ns(end)

    with DuckDBReader(data_dir=resolved_data_dir) as reader:
        table = reader.read(
            symbol,
            start_ts_ns=start_ns,
            end_ts_ns=end_ns,
            exchange=exchange,
        )

    # ``columns`` aceito mas ainda não pushed-down — projetar aqui
    # mantém a fronteira estável (QUERIES.md §7 — aditivo).
    if columns is not None:
        # Filtra colunas que existem no schema (defensive — caller pode
        # passar campos legacy).
        existing = [c for c in columns if c in table.schema.names]
        if existing:
            table = table.select(existing)
    return table


def read_continuous(
    symbol_root: str,
    start: datetime,
    end: datetime,
    *,
    exchange: str = "F",
    data_dir: Path | None = None,
    catalog: Catalog,
) -> pa.Table:
    """Lê série contínua para ``symbol_root`` concatenando contratos vigentes.

    Wrapper estável sobre
    :func:`data_downloader.storage.continuous_reader.read_continuous`.
    Resolve via ``catalog.contracts`` quais contratos cobrem o range,
    aplica policy ``vigent_until`` (cut-off pelo fim do contrato anterior
    + 1ns) e concatena ordenado.

    Garantias (QUERIES.md §0 + §2):

    - **Estável** — assinatura SemVer-tracked (ADR-007a).
    - **BRT naive (R7)** — datetime sem timezone.
    - **Ordenado** — ``timestamp_ns`` ascendente cross-contract.
    - **Sem duplicatas** — cut-off ``+1ns`` garante zero overlap em
      rollover (Story 1.5b property test).
    - **schema_version** — exposto via metadata dos Parquets de origem.
    - **Rastreabilidade** — coluna ``_contract_code`` indica origem por
      trade; ``_rollover_event`` flag boundary de troca.

    Args:
        symbol_root: Raiz do contrato (ex.: ``"WDO"``, ``"WIN"``).
            Para equities, usar o ticker (geralmente single-contract).
        start: Inclusivo. Datetime BRT naive.
        end: Inclusivo. Datetime BRT naive.
        exchange: ``"F"`` (default) ou ``"B"``.
        data_dir: Raiz dos dados. Default: ``catalog.data_dir``.
        catalog: Catálogo SQLite (kw-only — sempre obrigatório). Fonte
            da tabela ``contracts``. Não há default porque o catálogo
            é stateful e o caller deve gerenciar lifecycle.

    Returns:
        ``pa.Table`` com schema canônico (17 campos) + duas colunas
        extras: ``_contract_code`` (string) e ``_rollover_event`` (bool).

    Raises:
        ValueError: ``exchange`` fora de ``{"F", "B"}`` ou ``start > end``.
    """
    # Deferred import — evita circular import via public_api.__init__.
    from data_downloader.storage.continuous_reader import (
        read_continuous as _read_continuous_impl,
    )

    return _read_continuous_impl(
        symbol_root,
        start,
        end,
        exchange=exchange,
        catalog=catalog,
        data_dir=data_dir,
    )


def vigent_contract(
    symbol_root: str,
    on_date: date | datetime,
    *,
    exchange: str = "F",
    catalog: Catalog,
) -> str:
    """Resolve ``(symbol_root, on_date)`` para ``contract_code``.

    Wrapper estável sobre
    :func:`data_downloader.orchestrator.contracts.vigent_contract`.

    Args:
        symbol_root: Raiz (ex.: ``"WDO"``, ``"WIN"``, ``"PETR4"``).
        on_date: Data de referência. ``date`` ou ``datetime`` (datetime
            herda de date no Python).
        exchange: ``"F"`` (default) ou ``"B"``.
        catalog: Catálogo SQLite (kw-only).

    Returns:
        ``contract_code`` — ex.: ``"WDOJ26"``.

    Raises:
        InvalidContract: Nenhum contrato vigente em ``on_date``.
        ValueError: ``exchange`` fora de ``{"F", "B"}``.
    """
    # Deferred import — evita circular import via public_api.__init__.
    from data_downloader.orchestrator.contracts import (
        vigent_contract as _vigent_contract_impl,
    )

    return _vigent_contract_impl(catalog, symbol_root, on_date, exchange=exchange)


def _datetime_to_ns(dt: datetime) -> int:
    """Converte datetime naive para nanos epoch (helper local)."""
    epoch = datetime(1970, 1, 1)
    delta = dt - epoch
    seconds = int(delta.total_seconds())
    extra_us = delta.microseconds
    return seconds * 1_000_000_000 + extra_us * 1_000
