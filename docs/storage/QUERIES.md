# QUERIES.md — Queries DuckDB Canônicas para Projetos Downstream

**Owner:** 💾 Sol (Storage Engineer)
**Versão:** v1.0.0
**Audiência:** projetos downstream (backtest engine, live signal generator, risk monitor, qualquer consumidor do data-downloader).

---

## 0. Filosofia

O data-downloader é a **fundação** de TODOS os projetos quant futuros do usuário. Para que isso funcione, a interface de leitura deve ser:

1. **Estável** — assinatura não muda entre minor versions.
2. **Honesta** — `read_continuous` declara explicitamente o ponto de rollover (não esconde).
3. **Rápida** — pruning agressivo via row group + filter pushdown.
4. **Cólica zero** — não exige que consumidor entenda layout de partição, dedup, ou catálogo.

Os consumidores chegam via **DuckDB** (recomendado) ou **PyArrow direto** (avançado). Esta página documenta as queries canônicas que Sol mantém.

---

## 1. `read_history(symbol, start, end)` — single contract

### 1.1 Assinatura

```python
def read_history(
    symbol: str,
    start: datetime | str,
    end: datetime | str,
    *,
    columns: list[str] | None = None,
    catalog_path: Path | None = None,
) -> pa.Table:
    """
    Lê todos os trades de UM contrato específico no intervalo [start, end].

    Args:
        symbol: Código exato do contrato (ex: 'WDOJ26', 'PETR4').
                Não aceita root (use read_continuous para isso).
        start, end: Inclusivos. Datetime BRT NAIVE ou string ISO8601 sem timezone.
        columns: Subset de colunas (otimização de I/O). Default: todas.
        catalog_path: override do catálogo (testes). Default (ADR-024): data/_internal/catalog.db.

    Returns:
        pa.Table ordenada por (timestamp_ns, sequence_within_ns).

    Raises:
        SymbolNotFoundError: nenhum dado para o símbolo.
        EmptyRangeError: símbolo existe mas nenhum trade no intervalo.
    """
```

### 1.2 Implementação canônica (DuckDB)

```python
def read_history(symbol, start, end, columns=None, catalog_path=None):
    cat = _open_catalog(catalog_path)
    rows = cat.execute(
        """
        SELECT partition_path
        FROM partitions
        WHERE symbol = ?
          AND first_ts_ns <= ?
          AND last_ts_ns  >= ?
        ORDER BY year, month
        """,
        (symbol, _to_ns(end), _to_ns(start)),
    ).fetchall()
    if not rows:
        raise SymbolNotFoundError(symbol)

    paths = [str(_root() / r[0]) for r in rows]
    cols = "*" if columns is None else ", ".join(columns)
    sql = f"""
        SELECT {cols}
        FROM read_parquet({paths!r}, hive_partitioning=False)
        WHERE timestamp_ns BETWEEN ? AND ?
        ORDER BY timestamp_ns, sequence_within_ns
    """
    con = duckdb.connect(":memory:")
    return con.execute(sql, (_to_ns(start), _to_ns(end))).arrow()
```

### 1.3 Uso típico

```python
import pyarrow as pa
from data_downloader.queries import read_history

trades = read_history("WDOJ26", "2026-04-01", "2026-04-30")
df = trades.to_pandas()
print(f"{len(df):,} trades em abril/26")
```

---

## 2. `read_continuous(symbol_root, start, end)` — concatena com rollover

### 2.1 Assinatura

```python
def read_continuous(
    symbol_root: str,
    start: datetime | str,
    end: datetime | str,
    *,
    rollover_policy: str = "vigent_until",
    columns: list[str] | None = None,
    catalog_path: Path | None = None,
) -> pa.Table:
    """
    Lê uma série contínua para `symbol_root`, concatenando contratos vigentes
    com rollover entre eles. Ideal para backtests de longo prazo.

    Args:
        symbol_root: Ex: 'WDO', 'WIN'. Para equities, use read_history (root == ticker).
        rollover_policy:
            'vigent_until' (default): troca contrato no `vigent_until` do
                contrato corrente.
            'first_trade': troca quando o novo contrato tem seu primeiro trade
                (deteta na prática) — futuro, ainda não implementado.
        columns: subset.

    Returns:
        pa.Table com colunas originais + duas extras:
            - `_source_symbol` (string): qual contrato originou cada trade.
            - `_rollover_event` (bool): True na primeira linha após cada rollover.
        Garantia: `_source_symbol` é monotônico (nunca volta a contrato anterior).

    Raises:
        NoVigentContractError: nenhum contrato vigente em parte do range.
        AmbiguousContractError: overlap não resolvido por rollover_policy.
    """
```

### 2.2 Implementação canônica

```python
def read_continuous(symbol_root, start, end, rollover_policy="vigent_until",
                    columns=None, catalog_path=None):
    cat = _open_catalog(catalog_path)
    contracts = cat.execute(
        """
        SELECT contract_code, vigent_from, vigent_until
        FROM contracts
        WHERE symbol_root = ?
          AND vigent_until >= ?
          AND vigent_from  <= ?
        ORDER BY vigent_from
        """,
        (symbol_root, start, end),
    ).fetchall()
    if not contracts:
        raise NoVigentContractError(symbol_root, start, end)

    chunks = []
    prev_until = None
    for code, vfrom, vuntil in contracts:
        slice_start = max(start, vfrom)
        slice_end = min(end, vuntil)
        if rollover_policy == "vigent_until" and prev_until is not None:
            slice_start = max(slice_start, prev_until + timedelta(seconds=1))
        slice_table = read_history(
            code, slice_start, slice_end,
            columns=columns, catalog_path=catalog_path
        )
        slice_table = slice_table.append_column(
            "_source_symbol",
            pa.array([code] * slice_table.num_rows, type=pa.string()),
        )
        rollover_flags = [False] * slice_table.num_rows
        if chunks and rollover_flags:
            rollover_flags[0] = True
        slice_table = slice_table.append_column(
            "_rollover_event",
            pa.array(rollover_flags, type=pa.bool_()),
        )
        chunks.append(slice_table)
        prev_until = vuntil

    return pa.concat_tables(chunks)
```

### 2.3 Uso típico

```python
trades = read_continuous("WDO", "2025-01-01", "2026-12-31")
# trades.column("_source_symbol") => ['WDOG25', 'WDOG25', ..., 'WDOH25', 'WDOH25', ...]
# rollovers = trades.filter(pa.compute.field("_rollover_event"))
#   => 12 a ~24 linhas/ano (uma por mês ou trimestre).
```

### 2.4 Caveat — gap de dados em rollover

Se `WDOG25.vigent_until = 2025-01-30` e `WDOH25.vigent_from = 2025-01-30`, o policy `vigent_until` corta WDOH25 a partir de `2025-01-30 00:00:00.000000001`. Em horário comercial real, o usuário pode ver descontinuidade artificial nos primeiros minutos do contrato novo. Solução verdadeira: política `first_trade` (futura) ou usuário desliga rollover (`read_history` direto).

---

## 3. View `v_partitions_summary`

View materializável (ou não) que combina catálogo + estatísticas de arquivos para uma visão executiva:

```sql
CREATE OR REPLACE VIEW v_partitions_summary AS
SELECT
    p.exchange,
    p.symbol,
    p.year,
    p.month,
    p.row_count,
    p.first_ts_ns,
    p.last_ts_ns,
    p.schema_version,
    p.file_size_bytes,
    p.written_at,
    d.job_id,
    d.dll_version,
    d.status                         AS download_status,
    -- coverage flags
    (p.first_ts_ns IS NOT NULL
     AND p.last_ts_ns IS NOT NULL
     AND p.last_ts_ns > p.first_ts_ns) AS has_data,
    -- size in MB
    p.file_size_bytes / 1024.0 / 1024.0 AS file_size_mb,
    -- row density
    p.row_count / NULLIF((p.last_ts_ns - p.first_ts_ns) / 1e9 / 60, 0) AS rows_per_minute
FROM partitions p
LEFT JOIN downloads d ON p.job_id = d.job_id;
```

Uso:

```sql
-- Quanto temos de WDO em 2026?
SELECT symbol, SUM(row_count) AS trades, SUM(file_size_mb) AS mb
FROM v_partitions_summary
WHERE symbol LIKE 'WDO%' AND year = 2026
GROUP BY symbol
ORDER BY symbol;
```

---

## 4. Property test conceitual — continuidade no rollover

Test (a ser implementado em `tests/storage/test_read_continuous.py`):

```python
import pyarrow.compute as pc
from hypothesis import given, strategies as st

@given(
    start=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31)),
    span_days=st.integers(min_value=30, max_value=365),
)
def test_read_continuous_rollover_continuity(start, span_days):
    end = start + timedelta(days=span_days)
    trades = read_continuous("WDO", start, end)

    # Property 1: timestamps monotonic globalmente
    ts = trades.column("timestamp_ns").to_numpy()
    assert (ts[1:] >= ts[:-1]).all(), "timestamps regress at rollover"

    # Property 2: _source_symbol nunca volta a contrato anterior
    src = trades.column("_source_symbol").to_pylist()
    seen = []
    for s in src:
        if s not in seen:
            seen.append(s)
        else:
            assert s == seen[-1], f"contract {s} reappears after {seen[-1]}"

    # Property 3: _rollover_event flagged exatamente N-1 vezes para N contratos
    rollovers = pc.sum(trades.column("_rollover_event")).as_py()
    assert rollovers == max(0, len(seen) - 1)

    # Property 4: gap entre rollover_event e timestamp adjacente <= 1 dia útil
    # (sanidade — rollover não pode introduzir gap > 1 dia útil; se introduzir,
    # provavelmente o seed de contracts tem buraco)
    rollover_indices = [i for i, e in enumerate(trades.column("_rollover_event").to_pylist()) if e]
    for i in rollover_indices:
        if i > 0:
            delta_ns = ts[i] - ts[i-1]
            assert delta_ns < 4 * 24 * 3600 * 1e9, f"gap of {delta_ns/1e9/3600:.1f}h at rollover index {i}"
```

> Property 4 é heurística — gap de 4 dias cobre fim-de-semana longo + feriado. Se falhar regularmente, indica seed de contracts incompleto.

---

## 5. Otimizações recomendadas para projetos downstream

### 5.1 Filter pushdown — sempre passar timestamp_ns range

DuckDB faz row group pruning quando o filtro está em coluna ordenada. Como `timestamp_ns` é monotônico dentro de partição, sempre incluir:

```sql
WHERE timestamp_ns BETWEEN ? AND ?
```

### 5.2 Subset de colunas

Para análises que só precisam de `(timestamp_ns, price, quantity)`:

```python
trades = read_history("WDOJ26", start, end,
                     columns=["timestamp_ns", "price", "quantity"])
```

Reduz I/O em ~70% para esquema atual de 17 colunas.

### 5.3 Iteração por mês (memória limitada)

```python
for year, month in iter_months(start, end):
    table = read_history("WDOJ26", month_start(year, month),
                        month_end(year, month))
    process(table)
    del table  # libera explicitamente em workflows pesados
```

### 5.4 PyArrow direto (sem DuckDB)

Para máxima performance + zero deps:

```python
import pyarrow.parquet as pq
import pyarrow.dataset as ds

# Usa o catálogo só para descobrir paths
dataset = ds.dataset(
    paths_from_catalog,
    format='parquet',
    partitioning=None,  # particionamento é em diretórios, não Hive
)
table = dataset.to_table(
    columns=["timestamp_ns", "price", "quantity"],
    filter=ds.field("timestamp_ns") >= start_ns,
)
```

---

## 6. O que NÃO está em V1

Funções planejadas para versões futuras:

- `read_book_snapshot(symbol, ts)` — snapshot de livro (Epic futuro de book data).
- `read_continuous(rollover_policy="first_trade")` — rollover via primeiro trade do novo contrato.
- `read_continuous(rollover_policy="liquidity_crossover")` — rollover quando volume do novo > corrente.
- `read_aggregated(symbol, freq)` — OHLCV resampling (provavelmente fica em projeto downstream, não no data-downloader).

---

## 7. Estabilidade da API

| Item                     | Estabilidade                                                      |
|--------------------------|-------------------------------------------------------------------|
| Nome de função           | **Stable** — não muda em minor.                                   |
| Argumentos posicionais   | **Stable**.                                                        |
| Argumentos keyword       | **Aditivo OK** — novos KW podem aparecer; existentes não somem.    |
| Schema do retorno        | Reflete `SCHEMA.md`. Bump major do schema → bump major das queries.|
| Comportamento de rollover| Documentado e testado por property tests.                          |

Quebrar qualquer item acima = bump major do `data-downloader` + ADR.

---

## 8. Referências

- `SCHEMA.md` — schema dos retornos.
- `CONTRACTS.md` — como `read_continuous` resolve contratos.
- `INTEGRITY.md` — checks rodados antes de o leitor confiar nos dados.
- `MIGRATIONS.md` — quando schema muda, queries também versionam.
- Story 1.5b (`read_continuous` + property tests rollover).
- ADR-002 (DuckDB como interface de leitura).

— Sol, custodiando o histórico 💾
