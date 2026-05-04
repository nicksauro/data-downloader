"""data_downloader.storage.continuous_reader — Leitura contínua com rollover.

Owner: Dex (impl) + Sol (query canônica) | Consult: Aria (public_api).
Story 1.5b — read_continuous + queries DuckDB canônicas.
Refs:

- ``docs/storage/QUERIES.md`` §2 (read_continuous canônico)
- ``docs/storage/CONTRACTS.md`` §6.1 (rollover semantics)
- ``docs/adr/ADR-002-storage-stack.md`` (DuckDB engine)
- ``docs/adr/ADR-004-partition-layout.md`` (glob pattern)

Concatena Parquets de múltiplos contratos vigentes em um único
``pa.Table`` ordenado por ``timestamp_ns``, com coluna extra
``_contract_code`` (rastreabilidade) e flag ``_rollover_event``
(boolean) marcando primeira linha após troca de contrato.

Política de rollover (mini-council Dex+Sol — QUERIES.md §6):

- ``vigent_until`` (default): cut-off pelo ``vigent_until`` do contrato
  anterior; trades do contrato seguinte só entram a partir de
  ``vigent_until_anterior + 1ns``. Garante zero overlap.
- TODO Story 4.X — ``first_trade``: troca quando o novo contrato tem
  seu primeiro trade real. Útil para análises de liquidez.
- TODO Story 4.X — ``liquidity_crossover``: troca quando volume do novo
  excede o corrente. Mais alinhado a roll real de mercado.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa

from data_downloader.orchestrator.contracts import list_contracts
from data_downloader.storage.schema import pyarrow_schema

if TYPE_CHECKING:
    from data_downloader.storage.catalog import Catalog


# =====================================================================
# Modelo público — ContractTransition
# =====================================================================


@dataclass(frozen=True)
class ContractTransition:
    """Marcador de transição entre contratos em ``read_continuous``.

    Para uma série com N contratos contíguos, há N-1 transições.

    Atributos:
        from_contract: Código do contrato anterior (ex.: ``"WDOH26"``).
        to_contract: Código do contrato seguinte (ex.: ``"WDOJ26"``).
        boundary_ts_ns: ``timestamp_ns`` da PRIMEIRA linha do contrato
            seguinte (i.e. o ponto de costura). ``None`` se o contrato
            seguinte não tem trades dentro do range pedido (transição
            puramente declarativa via vigência).
    """

    from_contract: str
    to_contract: str
    boundary_ts_ns: int | None


# =====================================================================
# Helpers internos
# =====================================================================


def _to_ns(dt: datetime) -> int:
    """Converte ``datetime`` naive para nanos epoch (sem TZ)."""
    epoch = datetime(1970, 1, 1)
    delta = dt - epoch
    # total_seconds() inclui microseconds em parte fracionária.
    # Convertemos diretamente: seg * 1e9 + micros * 1e3.
    seconds = int(delta.total_seconds())
    extra_us = delta.microseconds
    return seconds * 1_000_000_000 + extra_us * 1_000


def _glob_pattern(data_dir: Path, exchange: str, contract_code: str) -> str:
    """Constrói glob ADR-004 para um contrato (todos year/month)."""
    return str(data_dir / "history" / exchange / contract_code / "**" / "*.parquet")


def _resolved_paths(data_dir: Path, exchange: str, contract_code: str) -> list[str]:
    """Resolve glob para paths concretos existentes (vazio se nada)."""
    return sorted(glob.glob(_glob_pattern(data_dir, exchange, contract_code), recursive=True))


def _empty_table_with_contract_columns() -> pa.Table:
    """Schema canônico + colunas ``_contract_code`` e ``_rollover_event``."""
    base = pyarrow_schema()
    extended = base.append(pa.field("_contract_code", pa.string(), nullable=False)).append(
        pa.field("_rollover_event", pa.bool_(), nullable=False)
    )
    return extended.empty_table()


# =====================================================================
# read_continuous — função canônica
# =====================================================================


def read_continuous(
    symbol_root: str,
    start: datetime,
    end: datetime,
    *,
    exchange: str = "F",
    catalog: Catalog,
    data_dir: Path | None = None,
) -> pa.Table:
    """Lê série contínua para ``symbol_root`` concatenando contratos vigentes.

    Resolve via ``catalog.contracts`` quais contratos cobrem o range
    ``[start, end]``, lê os Parquets de cada um (DuckDB UNION ALL com
    pushdown predicate em ``timestamp_ns``), concatena ordenado e adiciona
    coluna ``_contract_code`` para rastreabilidade.

    Política de rollover (QUERIES.md §6, mini-council Dex+Sol):
    cut-off pelo ``vigent_until`` do contrato anterior — trades do
    contrato seguinte entram apenas a partir de
    ``vigent_until + 1 nanosegundo``. Garante zero overlap nem duplicata
    em fronteira (INV-7 + property test Story 1.5b).

    Args:
        symbol_root: Raiz do contrato (ex.: ``"WDO"``, ``"WIN"``,
            ``"PETR4"``). Para equities (root == ticker) há tipicamente
            um único contrato cobrindo todo o histórico.
        start: Inclusivo. Datetime BRT naive (R7).
        end: Inclusivo. Datetime BRT naive (R7).
        exchange: ``"F"`` (BMF, default) ou ``"B"`` (Bovespa).
        catalog: Instância já inicializada de ``Catalog`` (fonte da
            tabela ``contracts``).
        data_dir: Raiz dos dados. Default: ``catalog.data_dir`` (layout
            convencional ``data/history/...``).

    Returns:
        ``pa.Table`` com schema canônico (17 campos — SCHEMA.md §1.2)
        ESTENDIDO com:

        - ``_contract_code`` (string, NOT NULL) — código do contrato que
          originou cada trade.
        - ``_rollover_event`` (bool, NOT NULL) — ``True`` na primeira
          linha após cada rollover (N-1 ``True`` para N contratos com
          dados; ``False`` em todas as outras linhas).

        Garantias (Sol — QUERIES.md §0):

        - Ordenado por ``timestamp_ns`` ascendente (cross-contract).
        - Sem duplicatas em fronteira de rollover.
        - Vazio se nenhum contrato vigente OU nenhum tem dados no range.

    Raises:
        ValueError: ``exchange`` fora de ``{"F", "B"}`` ou ``start > end``.
    """
    if exchange not in ("F", "B"):
        raise ValueError(f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}")
    if start > end:
        raise ValueError(
            f"start must be <= end; got start={start.isoformat()}, end={end.isoformat()}"
        )

    table, _ = read_continuous_with_rollover_metadata(
        symbol_root,
        start,
        end,
        exchange=exchange,
        catalog=catalog,
        data_dir=data_dir,
    )
    return table


def read_continuous_with_rollover_metadata(
    symbol_root: str,
    start: datetime,
    end: datetime,
    *,
    exchange: str = "F",
    catalog: Catalog,
    data_dir: Path | None = None,
) -> tuple[pa.Table, list[ContractTransition]]:
    """Versão de :func:`read_continuous` que retorna também transições.

    Útil para downstream debug / observabilidade — mostra exatamente
    onde cada rollover aconteceu e qual ``timestamp_ns`` foi a fronteira.

    Args:
        symbol_root: Raiz do contrato.
        start: Inclusivo. Datetime BRT naive.
        end: Inclusivo. Datetime BRT naive.
        exchange: ``"F"`` (default) ou ``"B"``.
        catalog: Catálogo SQLite.
        data_dir: Raiz dos dados. Default: ``catalog.data_dir``.

    Returns:
        ``(table, transitions)``:

        - ``table`` — idêntica a :func:`read_continuous`.
        - ``transitions`` — lista de :class:`ContractTransition` com N-1
          entries para N contratos contíguos com dados; vazia se 0 ou 1
          contratos. ``boundary_ts_ns`` é o ``timestamp_ns`` da PRIMEIRA
          linha do contrato seguinte (i.e. onde a costura é visível).

    Raises:
        ValueError: ``exchange`` fora de ``{"F", "B"}`` ou ``start > end``.
    """
    if exchange not in ("F", "B"):
        raise ValueError(f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}")
    if start > end:
        raise ValueError(
            f"start must be <= end; got start={start.isoformat()}, end={end.isoformat()}"
        )

    if data_dir is None:
        if catalog.data_dir is None:  # pragma: no cover defensive
            raise ValueError("data_dir not provided and catalog.data_dir is None")
        data_dir = catalog.data_dir
    data_dir = Path(data_dir)

    contracts = [
        c
        for c in list_contracts(catalog, root=symbol_root, exchange=exchange)
        if c.vigent_until >= start and c.vigent_from <= end
    ]
    # Ordenar por vigent_from (list_contracts já ordena, mas defensive).
    contracts.sort(key=lambda c: c.vigent_from)

    if not contracts:
        return _empty_table_with_contract_columns(), []

    start_ns = _to_ns(start)
    end_ns = _to_ns(end)

    # Para cada contrato, calcula a janela efetiva [slice_start_ns, slice_end_ns]
    # aplicando cut-off por vigent_until do contrato anterior (rollover policy).
    chunks: list[pa.Table] = []
    used_contracts: list[str] = []  # contratos que retornaram >= 0 linhas
    contract_with_data: list[tuple[str, int | None]] = []  # (code, first_ts_ns)

    prev_vigent_until_ns: int | None = None

    for contract in contracts:
        contract_code = contract.contract_code

        # Aplica policy ``vigent_until``: cut-off do contrato anterior.
        slice_start = max(start, contract.vigent_from)
        if prev_vigent_until_ns is not None:
            # +1ns para exclusive cut-off (zero overlap garantido).
            policy_floor = prev_vigent_until_ns + 1
            slice_start_ns_candidate = max(_to_ns(slice_start), policy_floor)
        else:
            slice_start_ns_candidate = max(_to_ns(slice_start), start_ns)

        slice_end_ns_candidate = min(_to_ns(min(end, contract.vigent_until)), end_ns)
        # vigent_until é o último dia inclusivo (datetime à meia-noite no seed).
        # Para abranger o dia inteiro do vigent_until, somamos 24h-1ns.
        # Isso casa com a semântica "vigente DURANTE o dia vigent_until".
        # Story 4.2 — equities têm vigent_until=9999-12-31; +1d overflowa.
        # Defensivo: clamp a datetime.max sem perder semântica (equity é
        # sempre vigente até o fim do tempo expressável).
        try:
            vigent_until_eod_ns = _to_ns(contract.vigent_until + timedelta(days=1)) - 1
        except OverflowError:
            # Equity / vigência infinita — usa um upper-bound seguro.
            vigent_until_eod_ns = _to_ns(datetime(9999, 12, 31, 23, 59, 59, 999_999))
        slice_end_ns_candidate = min(slice_end_ns_candidate, vigent_until_eod_ns)
        slice_end_ns_candidate = min(slice_end_ns_candidate, end_ns)

        if slice_start_ns_candidate > slice_end_ns_candidate:
            # Janela vazia para este contrato após cut-off — pula.
            prev_vigent_until_ns = vigent_until_eod_ns
            continue

        chunk_table = _read_one_contract(
            data_dir=data_dir,
            exchange=exchange,
            contract_code=contract_code,
            start_ns=slice_start_ns_candidate,
            end_ns=slice_end_ns_candidate,
        )
        used_contracts.append(contract_code)

        if chunk_table.num_rows == 0:
            contract_with_data.append((contract_code, None))
            prev_vigent_until_ns = vigent_until_eod_ns
            continue

        # Anexa coluna _contract_code (rastreabilidade — AC3).
        contract_col = pa.array(
            [contract_code] * chunk_table.num_rows,
            type=pa.string(),
        )
        chunk_table = chunk_table.append_column("_contract_code", contract_col)

        first_ts_ns = int(chunk_table.column("timestamp_ns")[0].as_py())
        contract_with_data.append((contract_code, first_ts_ns))
        chunks.append(chunk_table)

        prev_vigent_until_ns = vigent_until_eod_ns

    # Constrói transições (N-1 para N contratos com dados).
    transitions: list[ContractTransition] = []
    contracts_with_actual_data = [(c, ts) for c, ts in contract_with_data if ts is not None]
    for i in range(1, len(contracts_with_actual_data)):
        prev_code, _prev_ts = contracts_with_actual_data[i - 1]
        next_code, next_ts = contracts_with_actual_data[i]
        transitions.append(
            ContractTransition(
                from_contract=prev_code,
                to_contract=next_code,
                boundary_ts_ns=next_ts,
            )
        )

    if not chunks:
        return _empty_table_with_contract_columns(), transitions

    # Concatena e ordena globalmente por timestamp_ns (defensive — ordem
    # já é monotônica cross-contract dado o cut-off, mas garantimos).
    combined = pa.concat_tables(chunks, promote_options="default")
    combined = combined.sort_by([("timestamp_ns", "ascending")])

    # Computa _rollover_event: True na primeira linha após mudança de
    # _contract_code (i.e. boundary). Implementação: detecta posições
    # onde contract_code[i] != contract_code[i-1].
    rollover_flags = [False] * combined.num_rows
    if combined.num_rows > 0:
        codes = combined.column("_contract_code").to_pylist()
        for i in range(1, len(codes)):
            if codes[i] != codes[i - 1]:
                rollover_flags[i] = True
    combined = combined.append_column(
        "_rollover_event",
        pa.array(rollover_flags, type=pa.bool_()),
    )

    return combined, transitions


def _read_one_contract(
    *,
    data_dir: Path,
    exchange: str,
    contract_code: str,
    start_ns: int,
    end_ns: int,
) -> pa.Table:
    """Lê trades de um único contrato no range ``[start_ns, end_ns]``.

    Usa DuckDB com pushdown predicate em ``timestamp_ns`` (QUERIES.md
    §5.1). Retorna ``pa.Table`` ordenado por ``timestamp_ns``. Vazio se
    nenhum arquivo Parquet existe para o contrato (não levanta).

    Args:
        data_dir: Raiz dos dados.
        exchange: ``"F"`` ou ``"B"``.
        contract_code: Código exato do contrato (ex.: ``"WDOJ26"``).
        start_ns: Lower bound inclusivo (epoch ns).
        end_ns: Upper bound inclusivo (epoch ns).

    Returns:
        ``pa.Table`` ordenado por ``timestamp_ns``. Schema canônico (17
        campos). NÃO inclui ``_contract_code`` (caller adiciona).
    """
    paths = _resolved_paths(data_dir, exchange, contract_code)
    if not paths:
        return pyarrow_schema().empty_table()

    conn = duckdb.connect(":memory:")
    try:
        sql = (
            "SELECT * FROM read_parquet(?) "
            "WHERE timestamp_ns BETWEEN ? AND ? "
            "ORDER BY timestamp_ns ASC"
        )
        arrow_obj = conn.execute(sql, [paths, start_ns, end_ns]).arrow()
    finally:
        conn.close()

    if isinstance(arrow_obj, pa.Table):
        return arrow_obj
    return arrow_obj.read_all()


__all__ = [
    "ContractTransition",
    "read_continuous",
    "read_continuous_with_rollover_metadata",
]
