# BASELINES.md — Performance Baselines Canônicos

**Owner:** Pyro (perf-engineer) — autoridade exclusiva para criar/atualizar baseline.
**Status:**
- v1.0.0-synthetic registrado em **Story 1.4.5**.
- v1.1.0-mock registrado em Story 1.8 (mock pipeline E2E — Orchestrator + ParquetWriter + Catalog reais, mock DLL inline).
- **v2.0.0-vectorized registrado em Story 2.2** (ParquetWriter vectorizado via pa.compute + DuckDB ROW_NUMBER; refactor interno; comportamento INTACTO; **target V1 100k trades/s ATINGIDO** — 121_565 trades/s p50, +21.6% acima do target, speedup 4.40x vs v1.1.0-mock).
**Próximo:** v1.0.0-real será registrado em **Story 1.7b-followup** (humano roda smoke com `PROFITDLL_KEY`).
**Política:** baselines reais aguardam Story 1.7b-followup (humano roda smoke). Quando smoke real verde, baselines `v1.0.0-real` substituem `v1.1.0-mock` como referência canônica de pipeline E2E. v2.0.0-vectorized continua como referência canônica do **standalone ParquetWriter** (independente de pipeline).

---

## Princípio

Cada baseline é um **número canônico** contra o qual regressões são medidas. Sem baseline em BASELINES.md → regression-check é palpite. Com baseline → bloqueio determinístico de PR que regredir > budget (default 10%, ver `REGRESSION_BUDGETS.md`).

---

## Hardware de referência (host de execução Story 1.4.5)

| Campo | Valor |
|-------|-------|
| **CPU** | Intel64 Family 6 Model 58 Stepping 9 (i7-3770 ~ 4 cores físicos / 8 lógicos) |
| **RAM** | 16 GB |
| **Disco** | NVMe SSD (host laptop) |
| **OS** | Windows 10 build 19045 |
| **Machine** | AMD64 |

**NOTA SOBRE HARDWARE:** Este é hardware **modesto** (~2012 CPU). Baselines em hardware moderno (8+ cores físicos, 32GB+ RAM, NVMe Gen4) tendem a ser 2-4x melhores. Targets V1 foram definidos pensando em hardware moderno; ver `TARGETS_V1.md` para revisão pós-medição.

| Versões | |
|---------|--|
| Python | 3.14.3 (CPython) |
| pyarrow | 23.0.1 |
| duckdb | 1.5.2 |
| psutil | 7.2.2 |
| git_sha | `d1fb2e0` (workdir dirty — branch Story 1.4.5) |
| date | 2026-05-04 |

---

## Estrutura de um baseline

Cada entrada DEVE conter:

| Campo | Obrigatório | Exemplo |
|-------|-------------|---------|
| `benchmark` | sim | `bench_parquet_write` |
| `baseline_version` | sim | `1.0.0-synthetic` (Story 1.4.5) ou `1.0.0-real` (Story 1.8) |
| `git_sha` | sim | `d1fb2e0` |
| `dll_version` | sim | `4.0.0.30` (ou `mock-1.0` para sintético) |
| `hardware` | sim | CPU model, cores, RAM, disk type, OS |
| `python_version` | sim | `3.14.3` |
| `config` | sim | parâmetros do benchmark (row_group, compression, etc.) |
| `n_runs` | sim | 5+ runs (warmup descartado quando aplicável) |
| `metric_p50` | sim | mediana |
| `metric_p95` | sim | percentil 95 |
| `metric_p99` | sim | percentil 99 |
| `metric_stddev` | sim | desvio padrão |
| `date_iso` | sim | `2026-05-04T04:08:20Z` |
| `result_json` | sim | path para JSON em `benchmarks/results/baselines/` |
| `notes` | opcional | observações relevantes |

JSONs canônicos completos em `benchmarks/results/baselines/`.

---

## Baselines

### `bench_parquet_write` — v1.0.0-synthetic

**Workload:** 1M trades sintéticos (WDOJ26), 5 runs/config.
**Resultado JSON:** `benchmarks/results/baselines/bench_parquet_write-1.0.0-synthetic.json`.

**Matriz raw (`pq.write_table` direto):**

| row_group | compression | trades/s p50 | size MB | p99 ms |
|-----------|-------------|--------------|---------|--------|
| 10k | snappy | 759_939 | 37.4 | 1343 |
| 50k | snappy | 685_307 | 37.2 | 1674 |
| 100k | snappy | 802_229 | 36.5 | 1406 |
| 250k | snappy | 954_423 | 33.4 | 1100 |
| **1M** | snappy (winner raw) | **1_185_599** | 30.6 | 859 |
| 100k | zstd-1 | 820_451 | 26.7 | 1226 |
| 100k | zstd-3 | 713_887 | 24.2 | 1405 |
| 100k | none | 985_190 | 57.6 | 1070 |

**Production writer (`ParquetWriter` canônico — snappy + row_group=100k + validate + dedup + fsync + sha256):**

| Métrica | Valor |
|---------|-------|
| trades/s p50 | **27_638** |
| trades/s min | 27_420 |
| trades/s stddev | 117 (estável) |
| disk size MB | 36.3 |
| p50 ms (1M trades) | 35_857 (~36s para 1M) |
| p99 ms | 36_134 |
| peak RSS delta MB | 227 |

**Target V1:** >= 100_000 trades/s sustained → **gap (-72%)** vs production writer.

**Status:** ❌ não atinge (production writer); ✅ atinge (raw write_table). Ver `docs/decisions/COUNCIL-02-parquet-writer-streaming-overhead.md` para análise de causa raiz e roadmap de otimização (Story 2.X).

---

### `bench_parquet_write` — v2.0.0-vectorized (Story 2.2)

**Workload:** 1M trades sintéticos (WDOJ26), 5 runs, ParquetWriter vectorizado.
**git_sha:** `36709de-dirty` (Story 2.2 implementação 2026-05-04).
**Resultado JSON:** `benchmarks/results/baselines_v2_vectorized/bench_parquet_write-2.0.0-vectorized.json`.

**Production writer (v2 vectorizado — pa.compute validate + DuckDB dedup + sha256 streaming + fsync):**

| Métrica | Valor v2.0.0-vectorized | Valor v1.1.0-mock | Delta |
|---------|-------------------------|--------------------|-------|
| trades/s p50 | **121_565** | 27_638 | **+339.8%** (4.40x speedup) |
| trades/s min | 118_443 | 27_420 | +332.0% |
| trades/s stddev | 1_516 | 117 | +12.97x (mais variável — DuckDB session lifecycle) |
| disk size MB (1M trades) | 36.3 | 36.3 | +0% (schema preserved — INV) |
| p50 ms (1M trades) | **8_152** (~8.2s) | 35_857 (~36s) | **-77.3%** (4.40x faster) |
| p99 ms | 8_359 | 36_134 | -76.9% |
| peak RSS delta MB | 132 | 227 | -41.8% (sha256 streaming + DuckDB lazy init) |

**Target V1:** >= 100_000 trades/s sustained → ✅ **PASS** (+21.6% acima, gap fechado).

**Status:** ✅ **TARGET ATINGIDO**. Story 2.2 fechou gap de -72% via vectorização interna (sem mudança de schema, sem mudança de fronteira). Referência canônica do **standalone ParquetWriter** v2.

**Vectorizações aplicadas (COUNCIL-10 §2):**

1. **`_trades_to_table` → `trades_to_table_vectorized`** — single-pass column accumulation; eliminado loop coluna-a-coluna por trade.
2. **`validate_record` → `validate_records_vectorized`** — `pa.compute.greater` / `pa.compute.is_in` boolean masks sobre coluna inteira (vs N chamadas de função Python por trade).
3. **`assign_sequence_within_ns` → `assign_sequence_within_ns_vectorized`** — DuckDB `ROW_NUMBER() OVER (PARTITION BY symbol, timestamp_ns ORDER BY orig_idx)` (vs defaultdict per-trade).
4. **`dedup` → `dedup_table_vectorized`** — DuckDB `ROW_NUMBER() OVER (PARTITION BY chave_canonica)` com UNION ALL para variantes V1/V2 (vs dict.setdefault per-trade).
5. **`_sha256_file` → `compute_sha256_streaming`** — streaming chunks (1MB default; já era streaming, agora explicitamente exportado em `_vectorized` para substituibilidade).
6. **`_read_existing` → `_read_existing_table`** — retorna `pa.Table` direto (evita 2x conversão list↔table no merge path).

**Property tests (Hypothesis — Aria recomendação 7 COUNCIL-02 §sign-off):**

`tests/property/test_vectorized_equivalence.py` — 7 properties, todas PASS, ≥100 examples cada:

- `test_validate_equivalence`: vectorized raise sse loop puro raise.
- `test_table_build_equivalence`: `Table.to_pydict()` idêntico.
- `test_dedup_equivalence`: mesmo conjunto de chaves canônicas (INV-2).
- `test_dedup_inv2_concat_idempotent`: `dedup(L ++ L) == dedup(L)` no path vectorizado.
- `test_enrich_equivalence`: enrich vectorized == loop setdefault para trades realistas.
- `test_sha256_streaming_equals_full_read`: hash byte-idêntico para arquivos até 10MB.
- `test_inv7_read_after_write_via_vectorized_path`: read-back sorted by (ts_ns, seq) — INV-7 preservada.

**Mini-council COUNCIL-11 (Pyro+Sol — sign-off):** schema canônico v1.0.0 preservado intact (mesmos 17 campos, mesmos types, mesmo metadata custom), idempotência R5 preservada (validada por testes 1.4 sem mudança), atomicidade INV-3 preservada (mesmo fluxo tmp + fsync + os.replace).

---

### `bench_parquet_read` — v1.0.0-synthetic

**Workload:** 1M trades em 10 arquivos (100k cada), single-thread DuckDB.
**Resultado JSON:** `benchmarks/results/baselines/bench_parquet_read-1.0.0-synthetic.json`.

**Full scan (winners por row_group/compression):**

| row_group | compression | trades/s p50 | p99 ms |
|-----------|-------------|--------------|--------|
| 100k | snappy | 50_887_307 | 22 |
| 250k | snappy | 56_117_847 | 19 |
| 100k | zstd-1 | 23_158_540 | 47 |
| **100k** | **none (winner)** | **61_381_325** | 16 |

**Filtered scan (effective scan rate = total_rows / elapsed):**

| Selectivity | row_group=100k snappy | 100k none (winner) |
|-------------|----------------------|--------------------|
| 1% | ~30M trades/s | 35_781_119 trades/s |
| 10% | ~50M trades/s | 59_374_666 trades/s |

**Targets V1:**
- Full scan single-thread >= 1_000_000 trades/s → ✅ **PASS** (61M, 61x acima do target)
- Filtered 1% w/ pruning >= 5_000_000 trades/s → ✅ **PASS** (35M, 7x acima)

**Status:** ✅ atinge (ambos targets, com folga substancial).

---

### `bench_dedup` — v1.0.0-synthetic

**Workload:** matriz batch_size × duplicate_pct × key_strategy. 10 runs/config + 1 warmup.
**Resultado JSON:** `benchmarks/results/baselines/bench_dedup-1.0.0-synthetic.json`.

**Batch 10k (target zone):**

| dup % | key | p50 ms | p99 ms | trades/s |
|-------|-----|--------|--------|----------|
| 0% | V2 (curta) | 7.61 | 8.93 | 1_313_765 |
| 0% | V1 (longa) | 11.32 | 12.31 | 883_457 |
| 1% | V2 | 7.36 | 9.22 | 1_358_117 |
| 1% | V1 | 11.05 | 11.84 | 905_093 |
| 10% | V2 | 7.39 | 12.53 | 1_353_309 |
| 10% | V1 | 10.93 | 11.85 | 914_612 |

**Batch 100k:**

| dup % | key | p50 ms | p99 ms | trades/s |
|-------|-----|--------|--------|----------|
| 0% | V2 | 116.40 | 119.98 | 859_087 |
| 0% | V1 | 161.41 | 171.71 | 619_560 |
| 1% | V2 | 113.40 | 119.50 | 881_810 |
| 1% | V1 | 159.15 | 172.44 | 628_360 |
| 10% | V2 | 116.88 | 123.13 | 855_574 |
| 10% | V1 | 161.87 | 175.41 | 617_770 |

**Target V1:** < 50ms para batch 10k (worst-case) → ✅ **PASS** (worst p50 = 11.32ms; 78% abaixo do target).

**Observações:**
- V1 (chave longa 8-tupla) é ~1.49x mais lento que V2 (chave curta 4-tupla) — confirma H2.
- Scaling sub-linear: 0.74 µs/trade @ 10k → 1.13 µs/trade @ 100k (overhead de dict cresce, mas não O(n²)).
- V1 com `null_trade_id_pct=1.0` retorna n_out == n_in (não dedupa as duplicates do gerador) porque `assign_sequence_within_ns` distingue todas as ocorrências por seq — bench mede penalty de chave longa, NÃO efetividade de dedup nesse modo. Para validar dedup V1 com duplicates reais, precisaria gerar batch onde mesma `(symbol, ts_ns, price, qty, agents, seq)` aparece 2x — escopo Story 2.1.

**Status:** ✅ atinge (target com folga; H2 confirmada).

---

### `bench_callback_to_disk` — v1.0.0-synthetic

**Workload:** 50_000 callbacks @ 100k/s rate, sample_rate=5%, ParquetWriter pipeline simulado.
**Resultado JSON:** `benchmarks/results/baselines/bench_callback_to_disk-1.0.0-synthetic.json`.

**Cenários:**

| drain | pause ms | queue | p50 ms | p99 ms | drops | qmax | actual rate | back-pressure |
|-------|----------|-------|--------|--------|-------|------|-------------|---------------|
| stream | 0 | 10_000 | 2_325 | 4_449 | 108 (0.22%) | 10_000 | 13_701/s | drop |
| stream | 100 | 10_000 | 2_581 | 4_750 | 87 (0.17%) | 10_000 | 15_075/s | drop |
| stream | 500 | 10_000 | 3_571 | 5_734 | 199 (0.40%) | 10_000 | 9_432/s | drop |
| stream | 2000 | 10_000 | 6_618 | 8_644 | **585 (1.17%)** | 10_000 | 4_401/s | drop |
| stream | 500 | 100_000 | 4_782 | 10_172 | 0 | 48_841 | 100_000/s | block_or_absorb |
| **chunk** | **0** | **100_000** | **2_000** | **2_244** | **0** | 3_205 | 98_907/s | block_or_absorb |

**Target V1:** p99 < 100ms (cenário writer_pause=0) → ❌ **FAIL** por **22x** (2_244ms vs 100ms).

**Status:** ❌ não atinge (target inatingível com arquitetura `ParquetWriter` atual — full rewrite per write).

**HIPÓTESE H4 — CONFIRMADA:**
- Cenário `writer_pause_2000ms` resultou em **585 drops (1.17%)** com queue=10_000.
- Confirma finding H4 do plan review: drops são inevitáveis sob writer pause sustentado sem queue gigante.
- Mitigação observada: queue=100_000 absorve `pause=500ms` sem drops (queue_max_depth=48_841 = 48% utilization).
- Recomendação: produção (Story 1.7) DEVE expor métrica `dll_drops_total` + alarme + queue >= 100_000 default.

**Análise drains:**
- `stream` mode (write per-batch) sofre overhead de merge cumulativo no `ParquetWriter` (cada write reescreve partition completa).
- `chunk` mode (1 write por chunk completo) é o modelo de Story 1.7 — mais barato mas latência domínio é tempo até chunk fechar.
- Mesmo `chunk` mode não atinge p99 < 100ms porque ParquetWriter throughput limita (50k callbacks levam ~36s para escrever na config canônica; latência marker→disk inclui ~500ms inject + ~36s write = ordem de segundos).

---

### `bench_chunking` — v1.1.0-mock (Story 1.8)

**Workload:** 4 chunks × 50_000 trades = 200_000 trades total via pipeline E2E mock (Orchestrator + ParquetWriter + Catalog), mock DLL inline (padrão `_FakeProfitDLL` de tests/integration). 3 runs.
**git_sha:** `50f3368-dirty` (Story 1.8 baselines run 2026-05-04).
**JSON:** `benchmarks/results/baselines_v1_mock/bench_chunking-1.1.0-mock.json`.

| Métrica | Valor |
|---------|-------|
| total_ms p50 (200k trades) | **43_532ms** (~43.5s) |
| total_ms p99 | 47_631ms |
| total_ms stddev | 3_523ms (variabilidade alta — bench mock multi-thread + AV) |
| throughput chunk-completo p50 | **4_594 trades/s** |
| throughput chunk-completo p99 | 4_906 trades/s |
| extrapolated 1 mês real (11M) p50 | ~2_394_297ms (~40 min) |

**Target V1:** < 5min para 1 mês WDOJ26 → ❌ **gap +800%** (extrapolation).
**Status:** ❌ não atinge. Causa raiz = mesma de COUNCIL-02 (ParquetWriter overhead). **Tracked by Story 2.2** — pós-vectorização esperado ~7 min (próximo do target; ainda gap menor).

**Notas:**
- Mock DLL = 0 latência rede; tempo total é dominado por write (confirmado via `chunk_complete` events: writer = ~85% do tempo de chunk).
- Extrapolation linear (justificada empiricamente em COUNCIL-02 — write é O(N) por trade).
- Smoke real (Story 1.7b-followup) provavelmente mostrará tempo total **maior** (latência DLL + reconnect 99% + rede), mas writer continua sendo o gargalo dominante.

---

### `bench_multi_symbol` — v1.1.0-mock (Story 1.8)

**Workload:** N processos paralelo via `multiprocessing.Pool` (Windows spawn). N ∈ {1, 2, 4}; 2 runs/N. Cada worker roda pipeline mock completo (2 chunks × 25k trades = 50k trades/job). Símbolos distintos por worker (WDOJ26, WDOK26, WDON26, WDOQ26).
**git_sha:** `50f3368-dirty` (Story 1.8 baselines run 2026-05-04).
**JSON:** `benchmarks/results/baselines_v1_mock/bench_multi_symbol-1.1.0-mock.json`.

**Spawn overhead (medido separadamente):**

| Métrica | Valor |
|---------|-------|
| spawn_p50_s | **0.248s** |
| spawn_p99_s | 0.295s |

**Cenários:**

| N | wall_p50_s | speedup vs N=1 | efficiency_pct |
|---|-----------|----------------|----------------|
| 1 | 9.99 | 1.00x | 100% (baseline) |
| 2 | 10.38 | 1.92x | 96% |
| **4** | **13.90** | **2.88x** | **72%** |

**Target V1:** N=4 speedup >= 3.2x (80% efficiency) → ❌ **gap -10%**.

**Status:** ❌ não atinge. Causa: contention de IO em filesystem único (todos workers escrevem em mesmo SSD), AV scan compartilhado, e overhead de spawn Windows (~0.25s/worker × 4 = 1s). **Tracked by Story 2.2** indireto (vectorização reduz tempo absoluto por worker, deve melhorar efficiency).

**Notas:**
- N=2 atinge 96% efficiency (excelente) — confirma que para downloads de 2 símbolos, multi-process é Pareto-ótimo no Windows.
- N=8 omitido (8 cores logicos, hardware modesto = saturação esperada → speedup cai).
- Crossover analysis (jobs curtos vs longos) **NÃO MEDIDO** nesta story — tarefa para Story 2.X (quando smoke real disponível).

---

### `bench_callback_to_disk` — v1.1.0-mock (Story 1.8 re-run)

**Workload:** 30_000 callbacks @ 100k/s rate, sample_rate=5%, ParquetWriter pipeline simulado. 6 cenários (mesma matriz de 1.4.5).
**git_sha:** `50f3368-dirty` (Story 1.8 re-run 2026-05-04).
**JSON:** `benchmarks/results/baselines_v1_mock/bench_callback_to_disk-1.1.0-mock.json`.

| drain | pause ms | queue | p50 ms | p99 ms | drops | qmax | actual rate | back-pressure |
|-------|----------|-------|--------|--------|-------|------|-------------|---------------|
| stream | 0 | 10_000 | 1_415 | 2_472 | 55 (0.18%) | 10_000 | 22_197/s | drop |
| stream | 100 | 10_000 | 1_565 | 2_668 | 19 (0.06%) | 10_000 | 42_596/s | drop |
| stream | 500 | 10_000 | 2_388 | 3_471 | 71 (0.24%) | 10_000 | 19_763/s | drop |
| stream | 2000 | 10_000 | 5_438 | 6_502 | **264 (0.88%)** | 10_000 | 6_536/s | drop |
| stream | 500 | 100_000 | 2_740 | 4_790 | 0 | 29_999 | 99_999/s | block_or_absorb |
| **chunk** | **0** | **100_000** | **1_352** | **1_510** | **0** | 3_205 | 99_999/s | block_or_absorb |

**Target V1:** p99 < 100ms (cenário writer_pause=0 chunk-mode) → ❌ **gap +1410%** (1_510ms vs 100ms).

**Status:** ❌ não atinge. Tracked by Story 2.2 (vectorização) + decomposição target em Story 1.7 (3 sub-targets aprovados em COUNCIL-02 §6 Aria).

**H4 re-confirmada:** writer_pause=2000ms + queue=10k = 0.88% drops (vs 1.17% em 1.4.5; mesma ordem de magnitude — métrica `dll_drops_total` continua obrigatória).

---

## Resumo Story 1.8 — Status final por target

| Bench | Target V1 | Achieved (mock v1.1.0) | Status | Tracked by |
|-------|-----------|------------------------|--------|------------|
| bench_parquet_write (raw) | >= 100k trades/s | 1.19M | ✅ atinge | — |
| bench_parquet_write (production) | >= 100k trades/s | 27_638 | ❌ gap -72% | **Story 2.2** |
| bench_parquet_read (full scan) | >= 1M trades/s | 61.4M | ✅ atinge | — |
| bench_parquet_read (filtered 1pct) | >= 5M trades/s | 35.8M | ✅ atinge | — |
| bench_dedup (batch 10k worst) | < 50ms | 11.32ms | ✅ atinge | — |
| bench_callback_to_disk (chunk p99) | < 100ms | 1_510ms | ❌ gap +1410% | **Story 2.2** + decomposição (COUNCIL-02 §6) |
| bench_chunking (1 mês WDOJ26) | < 5 min | ~40 min (extrapolated) | ❌ gap +700% | **Story 2.2** |
| bench_multi_symbol (N=4 speedup) | >= 3.2x | 2.88x | ❌ gap -10% | **Story 2.2** (indireto) + Story 2.X (crossover real) |

**Aguardam smoke real (`v1.0.0-real`):**
- Tempo total real download 1 mês (rede + DLL real)
- RSS steady state real
- CPU avg real
- Comportamento de reconnect 99% (Q-RECON)

**Footnote:** baselines reais (`v1.0.0-real`) aguardam **Story 1.7b-followup** (humano roda smoke MVP com `PROFITDLL_KEY` set). Quando smoke verde, esta seção é re-registrada com números reais. Mock baselines `v1.1.0-mock` permanecem registrados como referência de pipeline-only (sem network/DLL real).

---

### `bench_boot_cleanup` — TBD

Não no escopo de Story 1.4.5. Esqueleto vazio.

---

### `bench_subprocess_spawn` — TBD

Não no escopo de Story 1.4.5. Esqueleto vazio.

---

### `bench_log_overhead` — TBD

Não no escopo de Story 1.4.5. Esqueleto vazio.

---

## Resumo executivo (Story 1.4.5)

| Bench | Métrica primária | Target V1 | Achieved p50 | Status |
|-------|------------------|-----------|--------------|--------|
| bench_parquet_write (raw) | trades/s | >= 100k | 1.19M | ✅ |
| bench_parquet_write (production) | trades/s | >= 100k | **27_638** | ❌ gap -72% |
| bench_parquet_read (full scan) | trades/s | >= 1M | 61.4M | ✅ +6038% |
| bench_parquet_read (filtered 1pct) | effective trades/s | >= 5M | 35.8M | ✅ +615% |
| bench_dedup (batch 10k worst) | ms p50 | < 50 | 11.32 | ✅ -77% |
| bench_callback_to_disk (chunk-mode p99) | ms | < 100 | 2_244 | ❌ gap +2144% |

**2 verdicts FAIL** — ambos correlacionados ao gargalo do `ParquetWriter` (validate+dedup+fsync per call). Roadmap de otimização documentado em `docs/decisions/COUNCIL-02`.

**Recomendações Pyro:**
1. **Story 2.1 (perf-write-optimization)** — vectorizar `_trades_to_table` + `validate_record` + `dedup` (esperado 5-10x speedup → fecha gap para ~150k trades/s).
2. **Story 1.7 (orchestrator)** — DEVE incluir métricas `dll_drops_total`, `ingest_queue_depth`, `write_queue_depth` + queue default 100k.
3. **Re-baseline** após Story 2.1 implementada (PR separado label `perf-baseline-update`).

---

## Processo de atualização de baseline

1. Rodar bench em condições controladas (sem outras cargas, sem AV scan ativo).
2. Capturar JSON em `benchmarks/results/`.
3. Validar reprodutibilidade: rodar 3x, verificar stddev < 5%.
4. Mover JSON para `benchmarks/results/baselines/{benchmark}-{version}.json`.
5. Atualizar tabela acima.
6. Commit + PR com label `perf-baseline-update`.
7. PR exige aprovação de **Pyro** + **1 outro agente** do squad (review independente).

## Quem pode aprovar regressão (override de budget)

- **Mudança de fronteira / contrato:** Aria (architect).
- **Decisão de produto / trade-off de feature:** Morgan (PM).
- **Mudança de storage layout:** Sol + Pyro.
- Override **DEVE** ser registrado em `docs/qa/WAIVERS/{story}-{date}.md`.

— Pyro ⚡

---

## Storage Tuning Pareto Matrix (Story 2.8 — measured-pareto)

**Owner:** Sol + Pyro mini-council COUNCIL-21 (2026-05-04).
**Status:** measured-pareto.
**Refs:** `docs/decisions/COUNCIL-21-storage-pareto-defaults.md` —
sign-off completo + tabela cell-a-cell.

### `bench_parquet_pareto` — Story 2.8 v1

**Workload:** 500_000 trades sintéticos WDOJ26 seed=42; 4 compressions ×
5 row_groups = 20 cells; 2 runs/cell.
**git_sha:** `14ecdf3-dirty` (Story 2.8 measurement run).
**JSON:** `benchmarks/results/baselines_v1_mock/bench_parquet_pareto-2026-05-04-14ecdf3-dirty.json`.

**Pareto frontier (não-dominados):** 11 de 20 cells. Cell `snappy + 100k`
(default ADR-002) é PARETO-ÓTIMO — confirmado empiricamente.

**Resumo por compression@row_group=100k (cell de defaults):**

| compression | write_tps | read_full_tps | read_filt_tps | file_MB | Pareto? |
|-------------|----------:|--------------:|--------------:|--------:|---------|
| **snappy (default)** | 875_029 | 73_104_702 | 87_499_283 | 18.2 | **PARETO ✓** |
| zstd-1      | 648_433 | 51_716_696 | 64_206_893 | 13.3 | PARETO  |
| zstd-3      | 624_322 | 63_036_629 | 73_318_790 | 12.1 | PARETO  |
| none        | 898_933 | 79_949_438 | 104_593_030 | 28.8 | PARETO |

**Decisão Sol+Pyro (COUNCIL-21):** **MANTER snappy + 100k.** Substituir
por ZSTD-1 trocaria 27% de file_size por 26-30% de read throughput —
perda real para workload read-heavy do data-downloader. ZSTD-3 fica
disponível como ferramenta opcional para cold-storage (`*recompress`,
Story futura).

### `bench_sqlite_profiles` — Story 2.8 v1

**Workload:** 500 register_partition + 200 get_completed_partitions + 1
reconcile, 3 perfis × 2 runs.
**git_sha:** `efd8be4-dirty`.
**JSON:** `benchmarks/results/baselines_v1_mock/bench_sqlite_profiles-2026-05-04-efd8be4-dirty.json`.

| Profile      | cache_size  | mmap_size | register_p50_ms | query_p50_ms | reconcile_ms |
|--------------|------------:|----------:|----------------:|-------------:|-------------:|
| low_memory   | -10_000 (10MB) | 16 MB |          3.54   |       0.103  |       165.4  |
| **default**  | **-50_000 (50MB)** | **64 MB** | **3.39** |  **0.072** |    **161.5** |
| aggressive   | -200_000 (200MB) | 256 MB |          3.51   |       0.072  |       152.9  |

**Decisão Sol+Pyro (COUNCIL-21):** **MANTER default (50MB cache + 64MB
mmap).** Composite score (0.7 register + 0.3 query×100) coloca default
~2% à frente de aggressive (que custa 150MB extra de RAM) e ~19% à
frente de low_memory. Profiles `low_memory` e `aggressive` ficam opt-in
via env var `DATA_DOWNLOADER_SQLITE_PROFILE` ou arg
`Catalog(sqlite_profile=...)`. M6 (OOM em laptops 16GB) fechado: total
default = 114MB vs 456MB anteriores ao M6-fix de Story 1.5.

**Status Story 2.8:** ✅ Pareto matrix MEASURED; defaults VALIDATED
empiricamente; nenhuma mudança de default necessária; mudança aditiva
(profile registry permite override sem code change).

— Pyro + Sol, validando o Pareto ⚡💾
