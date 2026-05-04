# COUNCIL-10 — Perf Optimization Roadmap (ParquetWriter vectorization)

**Data:** 2026-05-03
**Convocação:** Pyro (perf-engineer) — modo autônomo Story 1.8 (mock-based v1 baselines)
**Participantes mentais:** Pyro (autoridade perf/regression), Sol (autoridade storage layout), Aria (fronteira / ADR governance)
**Reviewers (downstream):** Quinn (regression gate), Morgan (priorização)

---

## Contexto

Story 1.8 registrou baselines `v1.1.0-mock` rodando os benchmarks contra o
pipeline real (Orchestrator + ParquetWriter + Catalog) com mock DLL inline
(padrão `_FakeProfitDLL` de `tests/integration/test_orchestrator.py`).
Smoke real (Story 1.7b) está em WAIVER → `Story 1.7b-followup` rodará
quando humano disponibilizar credenciais; nesse momento `v1.0.0-real`
substitui `v1.1.0-mock`.

Esta convocação consolida **finding crítico de performance** identificado
em COUNCIL-02 (Story 1.4.5) e formalmente confirmado em Story 1.8: o
`ParquetWriter` atual é **~28x mais lento que `pq.write_table` raw**, com
gap de **-72%** vs target V1 (>= 100k trades/s sustained).

---

## Finding consolidado (números canônicos pós Story 1.8)

| Path | Throughput p50 | vs target |
|------|---------------|-----------|
| `pq.write_table` raw (snappy, rg=100k) | 802_229 trades/s | +702% (target 100k) |
| `pq.write_table` raw (snappy, rg=1M) | 1_185_599 trades/s | +1086% (winner raw) |
| `ParquetWriter` (canônico — 1.4.5) | **27_638 trades/s** | **-72%** ❌ |
| Pipeline E2E mock (chunk completo, Story 1.8) | **4_594 trades/s** | -95% ❌ |

O pipeline E2E é ainda mais lento que o `ParquetWriter` standalone porque
inclui ingestor + queue + catalog two-phase commit + fsync por partição.
Mas o **gargalo dominante (~85%) é o write**, conforme decomposição do
benchmark `bench_chunking` (Story 1.8).

### Causa raiz (re-confirmada COUNCIL-02 §F1)

`ParquetWriter.write` faz, **per-trade no Python loop puro**:

1. `validate_record` (price>0, qty>0, exchange in {F,B}, ts_ns positive, etc.)
2. `enrich` (ingestion_ts_ns, dll_version, chunk_id stamping)
3. `assign_sequence_within_ns` (defaultdict counter)
4. `dedup` (dict construction + tuple hashing como chave)
5. `merge` (union com `pq.read_table` se partition existe)
6. `sort_by` em `pa.Table` sobre dataset todo
7. `_trades_to_table` constrói arrays coluna a coluna em Python loop
8. `fsync(file)` + `fsync(parent_dir)` (Windows IO sync overhead)
9. `_sha256_file` lê arquivo completo de novo

Vectorização (Opção B em COUNCIL-02) ataca passos 1, 2, 3, 4, 7, 9.
Estimativa: **5-10x speedup** → fecha gap para ~150-280k trades/s
(supera target V1 100k).

### Corolário em Story 1.8 — bench_callback_to_disk + bench_chunking

- `bench_callback_to_disk` chunk-mode p99 = **1_510ms** (target 100ms = gap +1410%).
  Com vectorização esperada (5x), p99 cai para ~300ms (ainda gap, mas dentro
  da nova decomposição de 3 sub-targets aprovada em COUNCIL-02 §6 Aria).

- `bench_chunking` E2E mock = **40_712ms para 200k trades** = ~204_000ms para
  1M (3.4 min) extrapolado linear. Para 1 mês real (11M trades) = ~37 min
  (vs target 5min). Vectorização → ~7 min (próximo do target).

- `bench_multi_symbol` N=4 speedup = **2.87x** (gap vs target 3.2x).
  Esperado pós-vectorização: speedup deve ficar igual ou melhor (paralelismo
  é independente do hot path por-processo, mas com overhead absoluto menor).

---

## Decisão tomada (Pyro autoridade perf, com mini-council Sol+Aria)

### 1. Criar Story 2.2 — Perf Write Optimization (Epic 2)

| Campo | Valor |
|-------|-------|
| **ID** | `2.2` |
| **Titulo** | "Perf Write Optimization (vectorize ParquetWriter)" |
| **Owner** | Pyro (perf-engineer) |
| **Reviewers** | Sol (storage authority), Aria (fronteira), Quinn (regression gate) |
| **Priority** | P1 |
| **Estimate** | 3d |
| **Depends on** | 1.4 (canonical ParquetWriter), 1.7a (orchestrator), 2.1 (validation primitives) |

### 2. Tasks principais (Story 2.2)

1. **Vectorize `_trades_to_table`** — usar `pa.array` direto a partir de
   columns dict pré-acumuladas (sem loop Python). Esperado: 3-5x speedup
   neste passo isolado.

2. **Vectorize `validate_record`** — substituir loop Python por
   `pa.compute.greater_than`/`less_than`/`is_in`/`and_kleene` em boolean masks.
   Esperado: 5-10x speedup.

3. **Vectorize `dedup`** — usar `pa.compute.unique` ou
   `duckdb.sql("SELECT DISTINCT ...")` sobre array de chave canônica
   computada como hash int64 combinado em numpy. Esperado: 10x speedup.

4. **Hash SHA256 streaming** — `hashlib.sha256` consumindo `read(8192)`
   chunks via `iter()` em vez de carregar arquivo inteiro. Esperado:
   redução de RSS peak + speedup IO em arquivos > 100MB.

5. **Property tests Hypothesis** (Aria recomendação 7 em COUNCIL-02 §sign-off):
   garantir que vectorização preserva invariantes:
   - INV-2: `dedup(L ++ L) == dedup(L)`.
   - INV-3: read-after-write consistency.
   - INV-7: `read(write(L)) == sorted_dedup(L)`.
   - Validate: trades inválidos rejeitados pelo path vectorizado correspondem 1:1 ao path Python loop.

### 3. Justificativa "não fazer agora" (Story 1.8)

Story 1.4 já teve gate **PASS** (Sol APPROVED, Quinn PASS, Aria APPROVED via
review-design). Refatorar `ParquetWriter` exige **nova story dedicada** para:

- Preservar trilha de auditoria (gate de Story 1.4 não é re-aberto).
- Permitir property tests Hypothesis dedicados (Aria recomendação 7).
- Manter regression budget de Story 1.4 fixo como baseline canônico
  (vectorização vira **melhora** com PR `perf-baseline-update`, não baseline shift).

### 4. Justificativa NÃO buscar Opção C (streaming-append)

Re-confirma COUNCIL-02 §sign-off Aria #5:
- Opção C (streaming-append separado) quebraria atomicidade single-file (INV-3).
- Exigiria ADR amendment a ADR-002 + revisão SCHEMA.md §4.
- Esperar Opção B esgotar primeiro; só escalar se gap residual > 30%.

### 5. Sign-off

| Agente | Aprova | Justificativa |
|--------|--------|---------------|
| **Pyro** ⚡ | ✅ | Mediu, identificou gargalo, propôs roadmap empírico. |
| **Sol** 💾 | ✅ (mental) | Schema preserved (sem mudança SCHEMA.md). Vectorização é interna. |
| **Aria** 🏛️ | ✅ (mental) | Sem mudança fronteira `public_api`. Otimização interna ao módulo `data_downloader.storage.parquet_writer`. ADR não necessário. |

### 6. Não-bloqueante mas registrado

- **Smoke real (Story 1.7b-followup)**: quando humano rodar com `PROFITDLL_KEY`,
  baselines `v1.0.0-real` substituem `v1.1.0-mock`. Story 2.2 deve ser
  re-baseline contra `v1.0.0-real` antes do merge final.

- **Quinn handoff**: regression budget de Story 2.2 deve ser **inverso**
  ao default — em vez de bloquear regressão > 10%, bloqueia se **NÃO**
  observar melhora >= +400% (trade/s) na métrica primária `bench_parquet_write` (production).

---

## Aplicação imediata (Story 1.8)

- `BASELINES.md` atualizado com seção **v1.1.0-mock** referenciando este COUNCIL.
- `TARGETS_V1.md` atualizado com status `gap-tracked-by-2.2` para targets
  afetados (write throughput, callback_to_disk p99, multi-symbol speedup).
- `REGRESSION_BUDGETS.md` atualizado com override `bench_chunking` = 30%
  (variabilidade alta por natureza do bench; mock pipeline tem stddev maior).
- Story 2.2 criada em `docs/stories/2.2.story.md` com 6 ACs e 5 tasks.

— Pyro ⚡ (com mini-council Sol 💾 + Aria 🏛️)
