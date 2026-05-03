# INVARIANTS → TESTS — Mapa Explícito

> Mapa **invariante → teste planejado**. Toda invariante listada em
> `docs/ARCHITECTURE.md#invariants` (incluindo INV-11 e INV-12 que Aria adiciona
> via amendment) tem entrada aqui com o teste responsável por verificá-la.
>
> Responsável: Quinn 🧪 (autoria de testes); Aria 🏛️ (autoria de invariantes).
>
> Regra: nenhuma invariante sem teste planejado. Nenhum teste planejado sem invariante associada.

---

## 1. Tabela mestre

| ID    | Invariante (resumo)                                                | Teste planejado                                                               | Tipo        | Status   |
|-------|---------------------------------------------------------------------|-------------------------------------------------------------------------------|-------------|----------|
| INV-1 | Nenhuma chamada à DLL ocorre dentro de callback                     | `tests/unit/test_callbacks.py::test_callback_does_not_call_dll`               | unit + property | planned |
| INV-2 | `dedup(L ++ L) == dedup(L)` — idempotência                          | `tests/property/test_dedup.py::test_dedup_idempotent`                         | property    | planned  |
| INV-3 | `download(s, [a, b])` é idempotente (re-rodar não duplica/corrompe) | `tests/property/test_download.py::test_download_idempotent_replay`            | property    | planned  |
| INV-4 | Todo Parquet escrito tem `schema_version` no metadata               | `tests/integration/test_writer.py::test_parquet_has_schema_version`           | integration | planned  |
| INV-5 | Toda escrita reflete no catálogo SQLite (write atômico)             | `tests/integration/test_atomic_write.py::test_catalog_matches_files`          | integration | planned  |
| INV-6 | `read_history(s, [a, b])` ordena por `timestamp_ns` ascendente      | `tests/property/test_read.py::test_read_returns_monotonic_timestamps`         | property    | planned  |
| INV-7 | `migrate_v1_to_v2(read_v1(p))` preserva campos comuns               | `tests/property/test_schema_migration.py::test_migration_preserves_common_fields` | property | planned  |
| INV-8 | `chunking([a, b])` cobre `[a, b]` sem overlap nem gap               | `tests/property/test_chunking.py::test_chunks_cover_range_no_overlap`         | property    | planned  |
| INV-9 | `parse_brt_timestamp(s)` é canônico (entradas com "." e ":" antes ms produzem mesmo `ts_ns`) | `tests/property/test_timestamp.py::test_brt_parse_canonical_form` | property | planned |
| INV-10| Catálogo SQLite reconciliado com filesystem após cada `register_partition` | `tests/integration/test_catalog.py::test_catalog_filesystem_reconciliation` | integration | planned |
| **INV-11** | OrchestratorThread ≠ IngestorThread ≠ ConnectorThread (separação física obrigatória) | `tests/unit/test_thread_model.py::test_thread_separation_enforced`     | unit        | planned (depende ADR-005 amendment) |
| **INV-12** | "Fim de chunk" só declarado quando `dll_queue` vazia AND `write_queue` vazia AND último write commitou no SQLite | `tests/integration/test_shutdown.py::test_chunk_end_requires_full_drain` | integration | planned (depende ADR-005 amendment) |

> **INV-11 e INV-12** são adicionadas por Aria em `ARCHITECTURE.md` como parte do
> amendment ADR-005 (PLAN_REVIEW finding H11 + design observation). Quinn registra
> os testes planejados aqui para que assim que Aria fechar o amendment, Dex saiba
> exatamente quais arquivos criar.

---

## 2. Detalhes por invariante

### INV-1 — Callback não chama DLL

**Statement formal:**
> ∀ callback `cb` registrado, ∀ chamada `cb(...)`: durante a execução de `cb`,
> nenhuma função da `ProfitDLL` é invocada pelo mesmo thread.

**Teste:**
```python
# tests/unit/test_callbacks.py
def test_callback_does_not_call_dll():
    mock_dll = MockProfitDLL(scenario=Scenario.HappyPath)
    ingestor = Ingestor(dll=mock_dll, ...)
    ingestor.start()
    mock_dll.fire_history_callback(sample_trades(1000))
    ingestor.join_drain()
    # Mock detecta violações automaticamente
    assert mock_dll.callback_violations == [], (
        f"INV-1 violado: {mock_dll.callback_violations}"
    )
```

**Property complementar (Hypothesis):**
```python
@given(trades=st.lists(trade_strategy(), min_size=1, max_size=10000))
def test_callback_never_calls_dll_for_any_input(trades):
    mock_dll = MockProfitDLL(scenario=Scenario.HappyPath)
    ingestor = Ingestor(dll=mock_dll, ...)
    ingestor.start()
    mock_dll.fire_history_callback(trades)
    ingestor.join_drain()
    assert mock_dll.callback_violations == []
```

---

### INV-2 — `dedup` é idempotente

**Teste (property, Hypothesis):**
```python
# tests/property/test_dedup.py
@given(trades=trade_list_strategy(allow_dups=True))
def test_dedup_idempotent(trades):
    once = dedup(trades)
    twice = dedup(once)
    assert once == twice
```

---

### INV-3 — `download` idempotente

**Teste (property + integration):**
```python
# tests/property/test_download.py
@given(spec=download_spec_strategy())
def test_download_idempotent_replay(spec, tmp_path, mock_dll_factory):
    storage = make_storage(tmp_path)
    run1 = download(spec, dll=mock_dll_factory(seed=1), storage=storage)
    catalog_before = storage.catalog.snapshot()
    run2 = download(spec, dll=mock_dll_factory(seed=1), storage=storage)
    catalog_after = storage.catalog.snapshot()
    assert catalog_before == catalog_after
    assert run2.trades_written == 0
    assert run2.cache_hits == run1.partitions_written
```

---

### INV-4 — `schema_version` em todo Parquet

**Teste (integration):**
```python
# tests/integration/test_writer.py
def test_parquet_has_schema_version(tmp_path):
    writer = ParquetWriter(...)
    writer.write_chunk(sample_trades(1000), tmp_path / "part-0001.parquet")
    metadata = pq.read_metadata(tmp_path / "part-0001.parquet")
    assert b'schema_version' in metadata.metadata
    assert metadata.metadata[b'schema_version'] in ALLOWED_SCHEMA_VERSIONS
```

---

### INV-5 — Write atômico (catálogo == filesystem)

```python
# tests/integration/test_atomic_write.py
def test_catalog_matches_files(tmp_path, mock_dll):
    download(spec, dll=mock_dll, storage=make_storage(tmp_path))
    files = set(p.relative_to(tmp_path) for p in tmp_path.rglob("*.parquet"))
    catalog = set(make_storage(tmp_path).catalog.list_files())
    assert files == catalog
```

---

### INV-6 — Read ordena monotonicamente

```python
# tests/property/test_read.py
@given(spec=read_spec_strategy())
def test_read_returns_monotonic_timestamps(spec, populated_storage):
    rows = read_history(spec, storage=populated_storage)
    for i in range(1, len(rows)):
        assert rows[i].timestamp_ns >= rows[i-1].timestamp_ns
```

---

### INV-7 — Migration aditiva preserva campos comuns

```python
# tests/property/test_schema_migration.py
@given(rows=trade_list_v1_strategy())
def test_migration_preserves_common_fields(rows):
    parquet_v1 = write_v1(rows)
    parquet_v2 = migrate_v1_to_v2(parquet_v1)
    rows_v2 = read_v2(parquet_v2)
    for r1, r2 in zip(rows, rows_v2):
        for field in COMMON_FIELDS_V1_V2:
            assert getattr(r1, field) == getattr(r2, field)
```

---

### INV-8 — Chunking cobre range sem overlap

```python
# tests/property/test_chunking.py
@given(start=date_strategy(), end=date_strategy(), chunk_size=st.integers(1, 30))
def test_chunks_cover_range_no_overlap(start, end, chunk_size):
    assume(start <= end)
    chunks = chunker(start, end, chunk_size_days=chunk_size)
    # Sem gap
    for i in range(1, len(chunks)):
        assert chunks[i].start == chunks[i-1].end + timedelta(days=1)
    # Sem overlap
    assert chunks[0].start == start
    assert chunks[-1].end == end
```

---

### INV-9 — `parse_brt_timestamp` canônico

```python
# tests/property/test_timestamp.py
@given(ts_with_dot=brt_ts_dot_strategy())
def test_brt_parse_canonical_form(ts_with_dot):
    ts_with_colon = ts_with_dot.replace(".", ":", 1)  # 2026-05-03 10:30:45.123 → 10:30:45:123
    assert parse_brt_timestamp(ts_with_dot) == parse_brt_timestamp(ts_with_colon)
```

---

### INV-10 — Catálogo reconcilia com filesystem

```python
# tests/integration/test_catalog.py
def test_catalog_filesystem_reconciliation(tmp_path):
    catalog = SqliteCatalog(tmp_path / "catalog.db")
    writer = ParquetWriter(catalog=catalog, root=tmp_path)
    for spec in many_specs:
        writer.write_partition(spec, sample_trades(...))
    listed = set(catalog.list_files())
    physical = set(p.relative_to(tmp_path) for p in tmp_path.rglob("*.parquet"))
    assert listed == physical
```

---

### INV-11 — Separação física de threads (NEW — ADR-005 amendment)

**Statement formal:**
> ∀ thread `t`: `t.role ∈ {Connector, Ingestor, Orchestrator, Writer, UI}`,
> e `∄ t1, t2` distintos com `t1.role == t2.role` no mesmo orchestrator.
> ConnectorThread ≠ IngestorThread ≠ OrchestratorThread (separação obrigatória).

**Teste:**
```python
# tests/unit/test_thread_model.py
def test_thread_separation_enforced():
    orchestrator = Orchestrator(...)
    orchestrator.start()
    threads_by_role = orchestrator.get_threads_by_role()
    assert threads_by_role['connector'].ident != threads_by_role['ingestor'].ident
    assert threads_by_role['ingestor'].ident != threads_by_role['orchestrator'].ident
    assert threads_by_role['orchestrator'].ident != threads_by_role['connector'].ident
    orchestrator.stop()
```

**Status:** planejado — bloqueia em Aria fechar amendment ADR-005.

---

### INV-12 — Fim de chunk requer drain completo (NEW — ADR-005 amendment)

**Statement formal:**
> Estado `ChunkComplete` só pode ser emitido quando:
> `dll_queue.empty() AND write_queue.empty() AND last_write.committed_to_sqlite == True`.

**Teste:**
```python
# tests/integration/test_shutdown.py
def test_chunk_end_requires_full_drain(tmp_path, mock_dll):
    mock_dll = MockProfitDLL(scenario=Scenario.LateCallback)  # H11 race
    orch = Orchestrator(dll=mock_dll, storage=make_storage(tmp_path))
    chunk_complete_events = []
    orch.on('chunk_complete', chunk_complete_events.append)
    orch.run_chunk(spec)

    for event in chunk_complete_events:
        # No momento da emissão, queues devem estar vazias E último write comitado
        assert event.dll_queue_size == 0
        assert event.write_queue_size == 0
        assert event.last_write_sqlite_committed is True
```

**Status:** planejado — bloqueia em Aria fechar amendment ADR-005.

---

## 3. Cobertura

| Camada            | Invariantes cobertas | %      |
|-------------------|----------------------|--------|
| unit              | INV-1, INV-11        | 2/12   |
| integration       | INV-4, INV-5, INV-10, INV-12 | 4/12 |
| property          | INV-2, INV-3, INV-6, INV-7, INV-8, INV-9 | 6/12 |
| **Total planejado** | **12/12**          | **100%** |

> Toda invariante tem teste planejado. **Quinn não permite gate PASS na story
> que adicionar invariante nova sem entrada nesta tabela.**

---

## 4. Manutenção

- Toda nova invariante adicionada em `ARCHITECTURE.md#invariants` por Aria DEVE ter linha aqui no mesmo PR.
- Toda story que **viola** uma invariante tem `WAIVED` automático negado por Quinn (regra de §2 de `WAIVERS/README.md`).
- Quinn revisa este documento a cada release V*.

---

— Quinn, no portão 🧪 (autoria de testes; invariantes assinadas por Aria 🏛️)
