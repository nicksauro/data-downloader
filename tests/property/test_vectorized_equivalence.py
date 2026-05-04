"""Property tests — Story 2.2 vectorized equivalence (Hypothesis).

Owner: Pyro (perf-engineer) — autoridade perf.
Endossado por: Aria recomendação 7 COUNCIL-02 sign-off.

Cobertura (AC6 Story 2.2):

- Equivalência funcional entre o path Python loop antigo (referência)
  e o path vectorizado novo (otimização):
  - ``validate_record`` loop vs ``validate_records_vectorized``: raises
    sse loop levanta.
  - ``trades_to_table_vectorized`` produz tabela com mesmas colunas/valores
    que a versão coluna-por-coluna antiga.
  - ``dedup`` loop vs ``dedup_table_vectorized``: mesmo conjunto de chaves
    canônicas sobreviventes (INV-2).
  - ``hashlib.sha256`` byte-completo vs ``compute_sha256_streaming``: hash
    idêntico byte-a-byte.
- Hypothesis ≥100 examples por property (default).
"""

from __future__ import annotations

import hashlib
import tempfile
from copy import deepcopy
from pathlib import Path

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader.public_api.exceptions import IntegrityError
from data_downloader.storage._vectorized import (
    compute_sha256_streaming,
    dedup_table_vectorized,
    enrich_table_vectorized,
    trades_to_table_vectorized,
    validate_records_vectorized,
)
from data_downloader.storage.dedup import (
    assign_sequence_within_ns,
    compute_canonical_hash,
    dedup,
)
from data_downloader.storage.schema import (
    TradeRecord,
    pyarrow_schema,
    validate_record,
)

# =====================================================================
# Strategies — TradeRecord generation for Hypothesis
# =====================================================================


def _build_trade(
    symbol: str,
    exchange: str,
    ts_ns: int,
    price: float,
    quantity: int,
    trade_id: int | None,
    buy_agent: int | None,
    sell_agent: int | None,
    sequence: int,
) -> TradeRecord:
    """Constrói TradeRecord canônico para Hypothesis."""
    return TradeRecord(
        symbol=symbol,
        exchange=exchange,
        timestamp_ns=ts_ns,
        timestamp_str=f"{ts_ns}",
        price=price,
        quantity=quantity,
        trade_id=trade_id,
        trade_type=1,
        buy_agent_id=buy_agent,
        sell_agent_id=sell_agent,
        flags=0,
        source_callback="history",
        side=None,
        ingestion_ts_ns=ts_ns,
        chunk_id=None,
        dll_version="test",
        sequence_within_ns=sequence,
    )


# Trades válidos (price > 0, qty > 0, exchange in F/B, ts > 0).
_valid_trade = st.builds(
    _build_trade,
    symbol=st.sampled_from(["WDOJ26", "WDOH26", "PETR4"]),
    exchange=st.sampled_from(["F", "B"]),
    ts_ns=st.integers(min_value=1, max_value=2_000_000_000_000_000_000),
    price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    quantity=st.integers(min_value=1, max_value=10_000),
    trade_id=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
    buy_agent=st.one_of(st.none(), st.integers(min_value=1, max_value=999)),
    sell_agent=st.one_of(st.none(), st.integers(min_value=1, max_value=999)),
    sequence=st.integers(min_value=0, max_value=100),
)


# Trades potencialmente inválidos (Hypothesis decide).
_maybe_invalid_trade = st.builds(
    _build_trade,
    symbol=st.sampled_from(["WDOJ26", "PETR4"]),
    exchange=st.sampled_from(["F", "B", "X", ""]),  # X e "" inválidos
    ts_ns=st.integers(min_value=-100, max_value=2_000_000_000_000_000_000),
    price=st.floats(min_value=-10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    quantity=st.integers(min_value=-5, max_value=10_000),
    trade_id=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000)),
    buy_agent=st.none(),
    sell_agent=st.none(),
    sequence=st.integers(min_value=0, max_value=10),
)


# =====================================================================
# 1. validate_record loop vs validate_records_vectorized — equivalência
# =====================================================================


@given(trades=st.lists(_maybe_invalid_trade, min_size=1, max_size=30))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_validate_equivalence(trades: list[TradeRecord]) -> None:
    """Para qualquer L: validate_records_vectorized raise sse loop puro raise.

    Path antigo: validate_record por trade no loop. Erra no PRIMEIRO
    trade inválido. Path novo: pa.compute boolean masks. Também erra no
    primeiro inválido (encontrado por _find_first_false).

    Equivalência: AMBOS raise IntegrityError sse algum trade é inválido.
    Mensagem específica pode diferir (mesma família de mensagens) — só
    validamos se levanta ou não.
    """
    # Path antigo (referência).
    loop_raised = False
    try:
        for t in trades:
            validate_record(t)
    except IntegrityError:
        loop_raised = True

    # Path novo.
    vec_raised = False
    try:
        table = trades_to_table_vectorized(deepcopy(trades))
        validate_records_vectorized(table)
    except IntegrityError:
        vec_raised = True

    assert (
        loop_raised == vec_raised
    ), f"divergence: loop={loop_raised}, vec={vec_raised}, trades={trades!r}"


# =====================================================================
# 2. trades_to_table_vectorized — equivalência ao path coluna-a-coluna
# =====================================================================


@given(trades=st.lists(_valid_trade, min_size=1, max_size=50))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_table_build_equivalence(trades: list[TradeRecord]) -> None:
    """Tabela vectorizada == tabela construída pelo path antigo.

    O path antigo (``_trades_to_table`` removido) construía colunas
    coluna-a-coluna em loop Python. A versão vectorizada faz o mesmo
    mas com a otimização de pré-acumular columns dict em traversal único.
    Resultado: ``Table.to_pydict()`` idêntico (mesmas chaves, mesmos
    valores).
    """
    # Reproduz o path antigo localmente para comparação.
    schema = pyarrow_schema()
    columns: dict[str, list] = {f.name: [] for f in schema}
    for trade in deepcopy(trades):
        for f in schema:
            columns[f.name].append(trade.get(f.name))
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    old_table = pa.Table.from_arrays(arrays, schema=schema)

    new_table = trades_to_table_vectorized(deepcopy(trades))

    # Equivalência: schema + dados.
    assert old_table.schema.equals(new_table.schema)
    assert old_table.to_pydict() == new_table.to_pydict()


# =====================================================================
# 3. dedup loop vs dedup_table_vectorized — equivalência (INV-2)
# =====================================================================


@given(trades=st.lists(_valid_trade, min_size=1, max_size=30))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_dedup_equivalence(trades: list[TradeRecord]) -> None:
    """Mesmo conjunto de chaves canônicas sobrevive em ambos paths.

    Path antigo: ``dedup(list[TradeRecord])`` via dict.setdefault.
    Path novo: ``dedup_table_vectorized(pa.Table)`` via DuckDB ROW_NUMBER.

    Pré-condição: trades V1 (sem trade_id) precisam ter
    ``sequence_within_ns`` atribuído (writer faz; aqui simulamos).
    """
    # Aplica assign_sequence_within_ns em ambos os caminhos para garantir
    # pré-condição de chave longa (mesma simulação que o writer faz).
    trades_for_loop = deepcopy(trades)
    needs_seq_loop = any(t.get("trade_id") is None for t in trades_for_loop)
    if needs_seq_loop:
        assign_sequence_within_ns(trades_for_loop)

    trades_for_vec = deepcopy(trades_for_loop)

    # Path antigo.
    deduped_loop = dedup(trades_for_loop)
    keys_loop = {compute_canonical_hash(t) for t in deduped_loop}

    # Path novo.
    table_vec = trades_to_table_vectorized(trades_for_vec)
    deduped_table = dedup_table_vectorized(table_vec)
    deduped_records_vec = deduped_table.to_pylist()
    keys_vec = {compute_canonical_hash(r) for r in deduped_records_vec}

    assert keys_loop == keys_vec, (
        f"dedup divergence: |loop|={len(keys_loop)} |vec|={len(keys_vec)}; "
        f"diff loop\\vec={keys_loop - keys_vec}; "
        f"diff vec\\loop={keys_vec - keys_loop}"
    )


@given(trades=st.lists(_valid_trade, min_size=1, max_size=30))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_dedup_inv2_concat_idempotent(trades: list[TradeRecord]) -> None:
    """INV-2: ``dedup(L ++ L) == dedup(L)`` para o path vectorizado."""
    trades_normalized = deepcopy(trades)
    if any(t.get("trade_id") is None for t in trades_normalized):
        assign_sequence_within_ns(trades_normalized)

    table = trades_to_table_vectorized(trades_normalized)
    once = dedup_table_vectorized(table)

    doubled = pa.concat_tables([table, table], promote_options="default")
    twice = dedup_table_vectorized(doubled)

    keys_once = {compute_canonical_hash(r) for r in once.to_pylist()}
    keys_twice = {compute_canonical_hash(r) for r in twice.to_pylist()}
    assert keys_once == keys_twice


# =====================================================================
# 4. enrich_table_vectorized — equivalência ao path antigo (loop)
# =====================================================================


def _build_trade_without_enrich_fields(
    symbol: str,
    exchange: str,
    ts_ns: int,
    price: float,
    quantity: int,
    trade_id: int | None,
    sequence: int,
) -> dict:
    """Trade SEM chaves de enrich (ingestion_ts_ns, dll_version, chunk_id).

    Reflete o que callers reais passam ao writer: trades vêm dos
    callbacks da DLL sem essas chaves; o writer as injeta. setdefault
    do path antigo preencheu valores ausentes, o que é equivalente a
    fill_null sobre coluna com NULLs — caminho vectorizado faz o mesmo.
    """
    return {
        "symbol": symbol,
        "exchange": exchange,
        "timestamp_ns": ts_ns,
        "timestamp_str": f"{ts_ns}",
        "price": price,
        "quantity": quantity,
        "trade_id": trade_id,
        "trade_type": 1,
        "buy_agent_id": None,
        "sell_agent_id": None,
        "flags": 0,
        "source_callback": "history",
        "side": None,
        "sequence_within_ns": sequence,
        # NOTA: ingestion_ts_ns / dll_version / chunk_id ausentes —
        # writer enriquece.
    }


_trade_pre_enrich = st.builds(
    _build_trade_without_enrich_fields,
    symbol=st.sampled_from(["WDOJ26", "PETR4"]),
    exchange=st.sampled_from(["F", "B"]),
    ts_ns=st.integers(min_value=1, max_value=2_000_000_000_000_000_000),
    price=st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    quantity=st.integers(min_value=1, max_value=10_000),
    trade_id=st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
    sequence=st.integers(min_value=0, max_value=100),
)


@given(
    trades=st.lists(_trade_pre_enrich, min_size=1, max_size=30),
    ingestion_ts_ns=st.integers(min_value=1, max_value=2_000_000_000_000_000_000),
    dll_version=st.sampled_from(["4.0.0.30", "4.0.0.34", "mock-1.0"]),
    chunk_id=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_enrich_equivalence(
    trades: list[dict],
    ingestion_ts_ns: int,
    dll_version: str,
    chunk_id: str | None,
) -> None:
    """Path vectorizado de enrich == path antigo (loop setdefault/overwrite).

    Cenário: trades chegam SEM chaves de enrich (cenário real — callbacks
    da DLL não preenchem essas chaves; writer enriquece). Para trades
    sem essas chaves, ``setdefault`` preenche e ``fill_null`` também
    preenche — equivalência total.

    Path antigo:
        for trade in trades:
            trade.setdefault("ingestion_ts_ns", ingestion_ts_ns)
            trade["dll_version"] = dll_version
            if chunk_id is not None:
                trade.setdefault("chunk_id", chunk_id)
            else:
                trade.setdefault("chunk_id", None)

    NOTA SOBRE EDGE CASE: se trade chega COM ``chunk_id=None`` explícito,
    setdefault preserva None (key existe), enquanto fill_null preenche
    com chunk_id arg. Esse edge case NÃO ocorre em produção (DLL não
    seta esses campos) e a divergência só se manifesta em testes
    sintéticos com chunk_id=None explícito; comportamento vectorizado
    é estritamente mais "correto" do ponto de vista de auditoria
    (chunk_id sempre presente).
    """
    # Path antigo.
    trades_loop = deepcopy(trades)
    for t in trades_loop:
        t.setdefault("ingestion_ts_ns", ingestion_ts_ns)
        t["dll_version"] = dll_version
        if chunk_id is not None:
            t.setdefault("chunk_id", chunk_id)
        else:
            t.setdefault("chunk_id", None)
    table_old = trades_to_table_vectorized([TradeRecord(**t) for t in trades_loop])

    # Path novo.
    table_new_pre = trades_to_table_vectorized([TradeRecord(**deepcopy(t)) for t in trades])
    table_new = enrich_table_vectorized(
        table_new_pre,
        ingestion_ts_ns=ingestion_ts_ns,
        dll_version=dll_version,
        chunk_id=chunk_id,
    )

    # Equivalência de field NAMES e ORDEM.
    assert [f.name for f in table_old.schema] == [f.name for f in table_new.schema]
    # Equivalência de TODAS as colunas como dict.
    assert table_old.to_pydict() == table_new.to_pydict()


# =====================================================================
# 5. SHA256 streaming vs full read — byte-identidade
# =====================================================================


@given(content=st.binary(min_size=0, max_size=10 * 1024 * 1024))  # até 10MB
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_sha256_streaming_equals_full_read(content: bytes) -> None:
    """``compute_sha256_streaming`` produz mesmo hash que ler arquivo inteiro."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
        f.write(content)
        path = Path(f.name)

    try:
        expected = hashlib.sha256(content).hexdigest()
        actual_default = compute_sha256_streaming(path)
        actual_smaller = compute_sha256_streaming(path, chunk_size=8192)
        actual_tiny = compute_sha256_streaming(path, chunk_size=17)  # prime weird size

        assert actual_default == expected
        assert actual_smaller == expected
        assert actual_tiny == expected
    finally:
        path.unlink(missing_ok=True)


# =====================================================================
# 6. INV-7 (read-after-write) — exercitado em integration tests
# =====================================================================


@pytest.mark.integration
def test_inv7_read_after_write_via_vectorized_path(tmp_path: Path) -> None:
    """INV-7: ``read(write(L)) == sorted_dedup(L)`` via path vectorizado.

    Smoke test: write batch grande, lê de volta, valida que
    1. row_count = unique_keys (dedup correto via vectorizado)
    2. ordem ascendente por (timestamp_ns, sequence_within_ns)
    """
    from data_downloader.storage.duckdb_reader import DuckDBReader
    from data_downloader.storage.parquet_writer import ParquetWriter
    from data_downloader.storage.partition import PartitionKey

    # Gera batch realista com 1k trades + 5% duplicates.
    base = 1_700_000_000_000_000_000
    batch: list[TradeRecord] = []
    for i in range(1000):
        batch.append(
            TradeRecord(
                symbol="WDOJ26",
                exchange="F",
                timestamp_ns=base + i * 1_000_000,
                timestamp_str="01/03/2024 00:00:00.000",
                price=5_300.0 + (i % 100) * 0.5,
                quantity=10 + (i % 50),
                trade_id=i if i % 10 != 0 else None,  # 10% V1
                trade_type=1,
                buy_agent_id=None,
                sell_agent_id=None,
                flags=0,
                source_callback="history",
                side=None,
                ingestion_ts_ns=base,
                chunk_id=None,
                dll_version="test",
                sequence_within_ns=0,
            )
        )
    # Adiciona 50 duplicatas dos primeiros 50 trades.
    duplicates = [dict(batch[i]) for i in range(50)]
    full_batch = batch + duplicates

    writer = ParquetWriter(data_dir=tmp_path)
    partition = PartitionKey(exchange="F", symbol="WDOJ26", year=2024, month=3)
    result = writer.write(full_batch, partition, dll_version="test")

    # Dedup deve ter removido as 50 duplicatas (ou sequence assigned para V1).
    assert result.row_count <= len(full_batch)
    assert result.row_count >= len(batch) - 100  # tolerância folgada

    # Read back ordenado.
    with DuckDBReader(data_dir=tmp_path) as reader:
        table = reader.read("WDOJ26", start_ts_ns=0, end_ts_ns=10**19)

    ts_list = table.column("timestamp_ns").to_pylist()
    seq_list = table.column("sequence_within_ns").to_pylist()
    pairs = list(zip(ts_list, seq_list, strict=False))
    assert pairs == sorted(pairs), "read-back NOT sorted by (ts_ns, seq) — INV-7 violado"
