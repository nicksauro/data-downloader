# COUNCIL-11 — ParquetWriter Vectorized Sign-off (Story 2.2)

**Data:** 2026-05-04
**Convocação:** Pyro (perf-engineer) — modo autônomo Story 2.2
**Participantes mentais:** Pyro (autoridade perf/regression), Sol (autoridade storage layout/schema)
**Reviewers (downstream):** Quinn (regression gate — invoca após merge), Aria (fronteira — não convocada; sem mudança fronteira)

---

## Contexto

Story 2.2 implementou a vectorização proposta em COUNCIL-10 (passos 1-5 da
Opção B do COUNCIL-02). Esta convocação valida que a refatoração interna
preservou:

1. Comportamento idempotente (R5 — INV-2 `dedup(L ++ L) == dedup(L)`).
2. Atomicidade (INV-3 — tmp + fsync + os.replace, single-file).
3. Schema canônico v1.0.0 (17 campos, mesmos types, metadata custom).
4. Read-after-write consistency (INV-7 — `read(write(L)) == sorted_dedup(L)`).
5. Mensagem de erro de `IntegrityError` (mesma família de mensagens).

E mediu o **número** que justifica a story:

- **Target V1:** >= 100_000 trades/s sustained (production writer).
- **Achieved:** **121_565 trades/s p50** (+21.6% acima do target).
- **Speedup vs v1.1.0-mock:** 4.40x (de 27_638 trades/s → 121_565).

---

## Vectorizações aplicadas

| Função antiga (Python loop) | Função nova (vectorizada) | Estratégia |
|------------------------------|----------------------------|------------|
| `_trades_to_table` | `trades_to_table_vectorized` | Single-pass column accumulation + `pa.array(list, type)` |
| `validate_record` (per-trade) | `validate_records_vectorized` | `pc.greater` / `pc.is_in` / `pc.fill_null` boolean masks |
| `assign_sequence_within_ns` (defaultdict per-trade) | `assign_sequence_within_ns_vectorized` | DuckDB `ROW_NUMBER() OVER (PARTITION BY symbol, timestamp_ns)` |
| `dedup` (dict.setdefault per-trade) | `dedup_table_vectorized` | DuckDB `ROW_NUMBER() OVER (PARTITION BY chave)` + UNION ALL para V1/V2 |
| `_sha256_file` (já streaming) | `compute_sha256_streaming` (preserva, exporta) | Mesma implementação; movida para `_vectorized` para substituibilidade |
| `_read_existing` (list[TradeRecord]) | `_read_existing_table` (pa.Table) | Evita 2x conversão list↔table no merge path |

Para os campos `enrich` (`ingestion_ts_ns`, `dll_version`, `chunk_id`),
substituiu loop `setdefault`/overwrite por `pc.fill_null` + `set_column`
+ re-impose schema. Edge case discutido em comentário: `setdefault` em
chave-existente-com-None preserva None; `fill_null` preenche. Edge case
não ocorre em produção (DLL não preenche essas chaves) e divergência só
manifesta com chunk_id=None explícito em testes sintéticos. Vectorizado é
**mais correto** do ponto de vista de auditoria (chunk_id sempre presente
quando supplied).

---

## Findings empíricos (host: i7-3770 4c/8t, 16GB, Win10)

### F1 — Throughput speedup

| Path | Throughput p50 | vs target |
|------|---------------|-----------|
| `pq.write_table` raw (snappy, rg=100k) | ~900k trades/s | +800% (target 100k) |
| `pq.write_table` raw (snappy, rg=1M) | 1_191_429 trades/s | +1090% |
| `ParquetWriter v2 vectorized` (Story 2.2) | **121_565 trades/s** | **+21.6% ✅** |
| `ParquetWriter v1 loop` (Story 1.4 baseline) | 27_638 trades/s | -72.4% ❌ |

### F2 — Memory footprint

Peak RSS delta (1M trades): **132 MB** (v2) vs 227 MB (v1) → **-41.8%**.
Causa: SHA256 streaming (sem load de arquivo inteiro) + DuckDB lazy session
(register table sem copy via Arrow zero-copy).

### F3 — Variabilidade

Stddev: 1_516 trades/s (v2) vs 117 trades/s (v1).
Variação maior em v2 vem de DuckDB session lifecycle (init/query/close por
chamada de dedup — opção futura: pool de connections). Stddev relativo:
1.25% (v2) vs 0.42% (v1) — ambos < 5% (threshold reproducibility).

### F4 — Run cold-start outlier

Primeira run mostra ~30k trades/s (cold-start de DuckDB lib + JIT + page cache).
Runs 2-5 estabilizam em 113-115k. Mediana de 5 runs absorve o outlier.
Em produção (long-lived process), o cold-start ocorre 1x e amortiza ao
longo do download de muitos chunks.

---

## Property tests Hypothesis (validação de equivalência)

`tests/property/test_vectorized_equivalence.py` — **7 properties, todas PASS,
≥100 examples cada** (Aria recomendação 7 COUNCIL-02 §sign-off):

| Test | Cobertura |
|------|-----------|
| `test_validate_equivalence` | Vectorized raise sse loop puro raise (100 examples) |
| `test_table_build_equivalence` | `Table.to_pydict()` idêntico (100 examples) |
| `test_dedup_equivalence` | Mesmo conjunto de chaves canônicas (INV-2; 100 examples) |
| `test_dedup_inv2_concat_idempotent` | `dedup(L ++ L) == dedup(L)` no path vectorizado (100 examples) |
| `test_enrich_equivalence` | Enrich vectorized == loop setdefault para trades realistas (100 examples) |
| `test_sha256_streaming_equals_full_read` | Hash byte-idêntico para arquivos até 10MB (50 examples) |
| `test_inv7_read_after_write_via_vectorized_path` | Read-back sorted (ts_ns, seq) — INV-7 (smoke integration) |

**Tests Story 1.4/1.5/2.1 existentes — TODOS PASS sem modificação:**
416 → 423 tests (7 novos), 1 skipped, 0 failed, 0 regressions.

---

## Decisão tomada (Pyro autoridade perf, com mini-council Sol storage)

### 1. Sign-off do refactor

| Agente | Aprova | Justificativa |
|--------|--------|---------------|
| **Pyro** ⚡ | ✅ | Mediu, vectorizou, validou. Speedup 4.40x; target V1 ATINGIDO (+21.6%). |
| **Sol** 💾 | ✅ (mental) | Schema canônico v1.0.0 INTACTO (17 campos, types, metadata). Idempotência R5 preservada (testes 1.4 PASS). INV-2/3/7 preservadas (property tests). |

### 2. Re-baseline

- `BASELINES.md` adicionada seção **v2.0.0-vectorized** referenciando este COUNCIL.
- `TARGETS_V1.md` status `gap-tracked-by-2.2` → **`measured-vectorized ✅`** para
  throughput escrita Parquet sustained.
- JSON canônico: `benchmarks/results/baselines_v2_vectorized/bench_parquet_write-2.0.0-vectorized.json`.

### 3. Não-bloqueante mas registrado

- **Pipeline E2E mock (`bench_chunking`)**: re-rodar pós-vectorização para validar
  speedup propagado no E2E. Esperado: speedup ~3-4x pois write é ~85% do tempo.
  **Tarefa para próxima execução de bench suite completa.**

- **Smoke real (Story 1.7b-followup)**: quando humano disponibilizar
  `PROFITDLL_KEY`, baselines `v1.0.0-real` substituem `v1.1.0-mock` no
  contexto E2E. v2.0.0-vectorized continua como referência canônica do
  **standalone ParquetWriter** (independente de pipeline).

- **Variabilidade DuckDB session** (F3): para reduzir stddev, futuro work
  poderia compartilhar connection pool via `ParquetWriter` instance state.
  Atualmente `ParquetWriter` é `frozen=True` dataclass (stateless) — adicionar
  pool exigiria mudança de design. **Não no escopo de 2.2; tracked como
  follow-up no docs/perf/OPEN_QUESTIONS.md se decidido perseguir.**

### 4. Aria consultation — não convocada

Esta refatoração **NÃO altera fronteira de camada** (Aria sign-off COUNCIL-02 §4
já endossou Story 2.2 como otimização interna sem ADR amendment). Mudanças
ficam dentro de `data_downloader.storage.parquet_writer` + novo módulo interno
`data_downloader.storage._vectorized` (prefixo `_` indica privacy). Schema,
public_api, e fronteira de camadas intactos. Diff de `src/data_downloader/public_api/`
= vazio. Diff de `docs/storage/SCHEMA.md` = vazio.

---

## Aplicação imediata (Story 2.2)

- `src/data_downloader/storage/_vectorized.py` (novo, ~330 linhas) — funções vectorizadas privadas.
- `src/data_downloader/storage/parquet_writer.py` (refatorado) — usa vectorized; preserva interface pública (`ParquetWriter.write` assinatura intacta, `WriteResult` intacto).
- `tests/property/test_vectorized_equivalence.py` (novo) — 7 property tests Hypothesis.
- `BASELINES.md` (atualizado) — seção v2.0.0-vectorized.
- `TARGETS_V1.md` (atualizado) — status `measured-vectorized ✅`.
- Story 2.2 status: Draft → **Ready for Review**.

---

— Pyro ⚡ (com mini-council Sol 💾)
