# BASELINES.md — Performance Baselines Canônicos

**Owner:** Pyro (perf-engineer) — autoridade exclusiva para criar/atualizar baseline.
**Status:** v1.0.0-synthetic registrado em **Story 1.4.5** (este documento).
**Próximo:** v1.0.0-real será registrado em **Story 1.8** (com DLL real + dados reais).

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

### `bench_chunking` — TBD (Story 1.8)

Não medido em Story 1.4.5 (depende de DLL real / orchestrator real). Esqueleto em `benchmarks/bench_chunking.py`.

---

### `bench_multi_symbol` — TBD (Story 1.4.5 não cobre)

Story 1.4.5 escopo declarou apenas 4 benchmarks (write, read, dedup, callback_to_disk). Multi-symbol fica para Story posterior (Epic 2). Esqueleto em `benchmarks/bench_multi_symbol.py`.

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
