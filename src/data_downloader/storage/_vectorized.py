"""data_downloader.storage._vectorized — Vectorizações internas Story 2.2.

Owner: Pyro (perf-engineer) — autoridade perf.
Endossado por: Sol (storage), Aria (fronteira) via COUNCIL-10.
Refs:

- ``docs/decisions/COUNCIL-02-parquet-writer-streaming-overhead.md`` (causa raiz)
- ``docs/decisions/COUNCIL-10-perf-optimization-roadmap.md`` (decisão)
- ``docs/stories/2.2.story.md`` (8 ACs)

Substitui loops Python puros do hot path do :mod:`parquet_writer` por
operações ``pa.compute`` / DuckDB SQL sobre ``pa.Table`` inteiras. Cada
função aqui é uma **otimização interna** — não cruza fronteira de
camada; preserva comportamento e schema canônico v1.0.0
(SCHEMA.md §1.2 — 17 campos imutáveis).

Garantias funcionais (validadas por property tests Hypothesis em
``tests/property/test_vectorized_equivalence.py``):

- ``validate_records_vectorized`` raises sse versão loop puro raise.
- ``enrich_records_vectorized`` produz ``pa.Table`` byte-equivalente ao
  loop puro (mesmas colunas, mesmos valores).
- ``dedup_table_vectorized`` resultado equivalente como conjunto às
  chamadas equivalentes de :func:`dedup` (mesma chave canônica
  preservada — primeira ocorrência vence; INV-2 mantida).
- ``compute_sha256_streaming`` produz hash idêntico a
  ``hashlib.sha256(path.read_bytes()).hexdigest()``.

Pyro princípio: "Vectorizar é refactor — número manda, mas
correctness é gate. Hypothesis garante que o número não veio de bug."
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc

from data_downloader.public_api.exceptions import IntegrityError
from data_downloader.storage.schema import TradeRecord, pyarrow_schema

_VALID_EXCHANGES_LIST: list[str] = ["F", "B"]


def trades_to_table_vectorized(trades: list[TradeRecord]) -> pa.Table:
    """Converte ``list[TradeRecord]`` em ``pa.Table`` vectorizadamente.

    Equivalente a ``_trades_to_table`` do path antigo, mas pré-acumula
    cada coluna em uma única ``list`` Python (1 traversal) e constrói
    ``pa.array`` por coluna direto. PyArrow internamente faz o type
    coercion em C — evita o overhead de N chamadas a ``trade.get(name)``
    x M campos no path antigo.

    Para 1M trades * 17 campos:
    - Path antigo: 17M get-calls + 17 ``pa.array`` calls.
    - Path novo: 17 list-appends por trade + 17 ``pa.array`` calls.

    Ganho real vem de:

    1. Cache locality — cada coluna processada de uma vez.
    2. ``pa.array(list, type=t)`` é internamente vectorizado em C.
    """
    schema = pyarrow_schema()
    field_names = [f.name for f in schema]
    columns: dict[str, list[object]] = {name: [] for name in field_names}
    # Single pass: cada trade alimenta todas as colunas.
    for trade in trades:
        for name in field_names:
            columns[name].append(trade.get(name))
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def validate_records_vectorized(table: pa.Table) -> None:
    """Valida invariantes em ``pa.Table`` inteira via ``pa.compute``.

    Cobre as MESMAS regras de :func:`data_downloader.storage.schema.validate_record`:

    - INT-4: ``price > 0`` e ``quantity > 0``.
    - INT-5: ``exchange in {'F', 'B'}``.
    - INT-3 (parcial): ``timestamp_ns > 0``.

    Estratégia: para cada regra, computa boolean mask via ``pc.greater``
    / ``pc.is_in``. Identifica primeiro registro inválido (se houver) e
    raise ``IntegrityError`` com ``details`` no MESMO formato do path
    antigo (``field`` + ``value`` do ofensor).

    Args:
        table: ``pa.Table`` aderente ao schema canônico v1.0.0.

    Raises:
        IntegrityError: alguma invariante violada (mesma mensagem que
            :func:`validate_record`).
    """
    if table.num_rows == 0:
        return

    # price > 0 (NOT NULL no schema; NULL impossível, mas defensive)
    price = table.column("price")
    # pc.greater retorna NA para NULLs; coerce_null_to_false trata edge case
    price_ok = pc.greater(price, pa.scalar(0.0, type=pa.float64()))
    price_ok_filled = pc.fill_null(price_ok, False)
    if not bool(pc.all(price_ok_filled).as_py()):
        idx = _find_first_false(price_ok_filled)
        bad_value = price[idx].as_py() if idx is not None else None
        raise IntegrityError(
            "price must be > 0",
            details={"field": "price", "value": bad_value},
        )

    # quantity > 0
    quantity = table.column("quantity")
    qty_ok = pc.greater(quantity, pa.scalar(0, type=pa.int64()))
    qty_ok_filled = pc.fill_null(qty_ok, False)
    if not bool(pc.all(qty_ok_filled).as_py()):
        idx = _find_first_false(qty_ok_filled)
        bad_value = quantity[idx].as_py() if idx is not None else None
        raise IntegrityError(
            "quantity must be > 0",
            details={"field": "quantity", "value": bad_value},
        )

    # exchange in {'F', 'B'}
    exchange = table.column("exchange")
    exch_ok = pc.is_in(exchange, value_set=pa.array(_VALID_EXCHANGES_LIST, type=pa.string()))
    exch_ok_filled = pc.fill_null(exch_ok, False)
    if not bool(pc.all(exch_ok_filled).as_py()):
        idx = _find_first_false(exch_ok_filled)
        bad_value = exchange[idx].as_py() if idx is not None else None
        raise IntegrityError(
            "exchange must be one of {'F', 'B'}",
            details={"field": "exchange", "value": bad_value},
        )

    # timestamp_ns > 0
    ts = table.column("timestamp_ns")
    ts_ok = pc.greater(ts, pa.scalar(0, type=pa.int64()))
    ts_ok_filled = pc.fill_null(ts_ok, False)
    if not bool(pc.all(ts_ok_filled).as_py()):
        idx = _find_first_false(ts_ok_filled)
        bad_value = ts[idx].as_py() if idx is not None else None
        raise IntegrityError(
            "timestamp_ns must be > 0",
            details={"field": "timestamp_ns", "value": bad_value},
        )


def _find_first_false(mask: pa.ChunkedArray | pa.Array) -> int | None:
    """Retorna índice do primeiro ``False`` em uma boolean mask."""
    py_list = mask.to_pylist()
    for i, v in enumerate(py_list):
        if not v:
            return i
    return None


def enrich_table_vectorized(
    table: pa.Table,
    *,
    ingestion_ts_ns: int,
    dll_version: str,
    chunk_id: str | None,
) -> pa.Table:
    """Enriquece ``pa.Table`` com campos por trade via ``pa.array`` constante.

    Substitui o ``setdefault`` per-trade do path antigo:

    - ``ingestion_ts_ns``: já preenchido, faz ``coalesce`` (preserva valor
      existente; preenche o ``ingestion_ts_ns`` argumento onde NULL/ausente).
    - ``dll_version``: SOBRESCREVE com argumento (path antigo:
      ``trade["dll_version"] = dll_version`` — overwrite).
    - ``chunk_id``: usa ``setdefault`` semantics — preserva existente,
      preenche argumento (ou NULL) onde ausente.

    Equivalência: produz ``pa.Table`` com **mesmos valores** que
    ``trades_to_table_vectorized`` chamada após o loop antigo de enrich.

    Args:
        table: Tabela com 17 campos canônicos.
        ingestion_ts_ns: Timestamp ns para preencher onde ausente.
        dll_version: String NOT NULL — sobrescreve.
        chunk_id: Opcional. Preserva existente; preenche onde ausente.

    Returns:
        Nova ``pa.Table`` com mesmas colunas + enriquecimento aplicado.
        Schema preservado (mesma ordem de fields, mesmos types).
    """
    n = table.num_rows
    if n == 0:
        return table

    # ingestion_ts_ns — coalesce (preserve existing, fill NULL with arg).
    ing_existing = table.column("ingestion_ts_ns")
    ing_filled = pc.fill_null(ing_existing, pa.scalar(ingestion_ts_ns, type=pa.int64()))
    table = table.set_column(
        table.schema.get_field_index("ingestion_ts_ns"),
        "ingestion_ts_ns",
        ing_filled,
    )

    # dll_version — overwrite (path antigo sobrescreve sem condicional).
    dll_array = pa.array([dll_version] * n, type=pa.string())
    table = table.set_column(
        table.schema.get_field_index("dll_version"),
        "dll_version",
        dll_array,
    )

    # chunk_id — setdefault (preserve existing; fill NULL with arg or None).
    chunk_existing = table.column("chunk_id")
    if chunk_id is not None:
        chunk_filled = pc.fill_null(chunk_existing, pa.scalar(chunk_id, type=pa.string()))
    else:
        # Path antigo: ``trade.setdefault("chunk_id", None)`` — no-op em
        # campos NULL; deixa como está.
        chunk_filled = chunk_existing
    table = table.set_column(
        table.schema.get_field_index("chunk_id"),
        "chunk_id",
        chunk_filled,
    )
    # Re-impõe schema canônico: set_column muda nullability dos arrays
    # após fill_null, mas o schema canônico (NOT NULL para
    # ingestion_ts_ns/dll_version) deve ser preservado. Cast garante.
    schema = pyarrow_schema()
    arrays = [table.column(f.name).cast(f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def assign_sequence_within_ns_vectorized(table: pa.Table) -> pa.Table:
    """Atribui ``sequence_within_ns`` 0..N por bucket ``(symbol, timestamp_ns)``.

    Equivalente a :func:`data_downloader.storage.dedup.assign_sequence_within_ns`
    mas via DuckDB ``ROW_NUMBER() OVER (PARTITION BY symbol, timestamp_ns
    ORDER BY (linha original))``. Preserva a ordem original
    (essencial — INV: sequence atribuído na ORDEM em que trades chegam,
    não em ordem ordenada).

    Estratégia: adiciona coluna `_orig_idx`, faz ROW_NUMBER particionado,
    re-ordena por `_orig_idx`, drop `_orig_idx`.

    Args:
        table: ``pa.Table`` com colunas ``symbol``, ``timestamp_ns``.

    Returns:
        Nova ``pa.Table`` com ``sequence_within_ns`` recomputado.
        Ordem original preservada.
    """
    n = table.num_rows
    if n == 0:
        return table

    # Adiciona índice original.
    idx_col = pa.array(range(n), type=pa.int64())
    table_with_idx = table.append_column("_orig_idx", idx_col)

    con = duckdb.connect(":memory:")
    try:
        con.register("t", table_with_idx)
        # ROW_NUMBER 0-based: usa ROW_NUMBER() - 1.
        # Necessário ORDER BY _orig_idx para garantir a ordem de chegada.
        result = con.execute(
            """
            SELECT
                * EXCLUDE (sequence_within_ns, _orig_idx),
                CAST(
                    ROW_NUMBER() OVER (
                        PARTITION BY symbol, timestamp_ns
                        ORDER BY _orig_idx
                    ) - 1 AS USMALLINT
                ) AS sequence_within_ns,
                _orig_idx
            FROM t
            ORDER BY _orig_idx
            """
        ).to_arrow_table()
    finally:
        con.close()

    # Drop _orig_idx e re-impõe schema canônico (mesma ordem dos 17
    # campos). DuckDB pode re-ordenar; aplicamos schema explícito.
    schema = pyarrow_schema()
    arrays = [result.column(f.name).cast(f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def dedup_table_vectorized(table: pa.Table) -> pa.Table:
    """Dedup vectorizado preservando primeira ocorrência (INV-2).

    Equivalente a :func:`data_downloader.storage.dedup.dedup`:

    - Variante curta (V2 — ``trade_id`` not null):
      chave ``(symbol, timestamp_ns, trade_id)``.
    - Variante longa (V1 — ``trade_id`` null):
      chave ``(symbol, timestamp_ns, price, quantity, buy_agent_id,
      sell_agent_id, sequence_within_ns)``.

    Usa DuckDB com ``ROW_NUMBER() OVER (PARTITION BY chave ORDER BY
    _orig_idx)``: primeira ocorrência da chave (menor ``_orig_idx``)
    vence — equivalente a ``dict.setdefault``.

    O discriminador V1/V2 é embutido no GROUP BY: NULL ``trade_id``
    nunca colide com não-NULL pois a tupla canônica V1 vs V2 difere
    no campo ``trade_id`` (NULL) já. A pré-condição é que V1 tenha
    ``sequence_within_ns`` atribuído (caller garante via writer).

    Args:
        table: ``pa.Table`` com 17 campos canônicos. Trades V1 (sem
            trade_id) DEVEM ter ``sequence_within_ns`` populado.

    Returns:
        Nova ``pa.Table`` sem duplicatas (primeira ocorrência vence).
        Ordem de inserção preservada (igual ao :func:`dedup` antigo).
    """
    n = table.num_rows
    if n == 0:
        return table

    idx_col = pa.array(range(n), type=pa.int64())
    table_with_idx = table.append_column("_orig_idx", idx_col)

    con = duckdb.connect(":memory:")
    try:
        con.register("t", table_with_idx)
        # ROW_NUMBER particionado pelas chaves canônicas. CASE distingue
        # V2 (trade_id NOT NULL) de V1 (trade_id NULL):
        # - V2: chave (symbol, ts, trade_id)
        # - V1: chave (symbol, ts, price, qty, buy_agent_id,
        #             sell_agent_id, sequence_within_ns)
        # Em SQL fazemos via ROW_NUMBER particionado por TODAS as colunas
        # da chave longa, com NULL-safe distinção via discriminator
        # implícito: se trade_id NOT NULL, particiona só por
        # (symbol, ts, trade_id); se NULL, particiona pela chave longa.
        # Solução: union de duas projeções ou usar COALESCE +
        # discriminator. Mais simples: dois caminhos via UNION ALL.
        result = con.execute(
            """
            WITH
            v2 AS (
                SELECT *, 'V2' AS _disc
                FROM t WHERE trade_id IS NOT NULL
            ),
            v1 AS (
                SELECT *, 'V1' AS _disc
                FROM t WHERE trade_id IS NULL
            ),
            ranked_v2 AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY symbol, timestamp_ns, trade_id
                        ORDER BY _orig_idx
                    ) AS _rn
                FROM v2
            ),
            ranked_v1 AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY symbol, timestamp_ns, price,
                                     quantity, buy_agent_id, sell_agent_id,
                                     sequence_within_ns
                        ORDER BY _orig_idx
                    ) AS _rn
                FROM v1
            ),
            unioned AS (
                SELECT * FROM ranked_v2 WHERE _rn = 1
                UNION ALL
                SELECT * FROM ranked_v1 WHERE _rn = 1
            )
            SELECT * EXCLUDE (_orig_idx, _disc, _rn)
            FROM unioned
            ORDER BY _orig_idx
            """
        ).to_arrow_table()
    finally:
        con.close()

    # Re-impõe schema canônico (DuckDB pode trocar ordem de fields).
    schema = pyarrow_schema()
    arrays = [result.column(f.name).cast(f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def compute_sha256_streaming(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA256 hex via streaming chunks (1MB default).

    Equivalente byte-a-byte a ``hashlib.sha256(path.read_bytes()).hexdigest()``
    mas evita carregar arquivo inteiro em RAM. Para arquivos > 100MB,
    reduz peak RSS significativamente.

    Implementação: ``iter(lambda: f.read(chunk_size), b"")`` + ``h.update``.
    Pyro nota: o path antigo (``_sha256_file``) já fazia streaming com
    chunk=1MB — esta função preserva esse comportamento e é
    explicitamente exportada para ser substituível por implementações
    alternativas (ex.: hash hardware-accelerated em V2).

    Args:
        path: Path do arquivo.
        chunk_size: Bytes por chunk (default 1MB).

    Returns:
        SHA256 hex string (64 chars lowercase).
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "assign_sequence_within_ns_vectorized",
    "compute_sha256_streaming",
    "dedup_table_vectorized",
    "enrich_table_vectorized",
    "trades_to_table_vectorized",
    "validate_records_vectorized",
]
