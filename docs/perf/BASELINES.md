# BASELINES.md — Performance Baselines Canônicos

**Owner:** Pyro (perf-engineer) — autoridade exclusiva para criar/atualizar baseline.
**Status:** estrutura pronta; baselines reais preenchidos em **Story 1.4.5** (sintéticos) e **Story 1.8** (reais com DLL).

---

## Princípio

Cada baseline é um **número canônico** contra o qual regressões são medidas. Sem baseline em BASELINES.md → regression-check é palpite. Com baseline → bloqueio determinístico de PR que regredir > budget (default 10%, ver `REGRESSION_BUDGETS.md`).

---

## Estrutura de um baseline

Cada entrada DEVE conter:

| Campo | Obrigatório | Exemplo |
|-------|-------------|---------|
| `benchmark` | ✅ | `bench_parquet_write` |
| `baseline_version` | ✅ | `1.0.0-synthetic` (Story 1.4.5) ou `1.0.0-real` (Story 1.8) |
| `git_sha` | ✅ | `a1b2c3d` |
| `dll_version` | ✅ | `4.0.0.30` (ou `mock-1.0` para sintético) |
| `hardware` | ✅ | CPU model, cores, RAM, disk type, OS |
| `python_version` | ✅ | `3.13.0` |
| `config` | ✅ | parâmetros do benchmark (row_group, compression, etc.) |
| `n_runs` | ✅ | 5+ runs (warmup descartado) |
| `metric_p50` | ✅ | mediana |
| `metric_p95` | ✅ | percentil 95 |
| `metric_p99` | ✅ | percentil 99 |
| `metric_stddev` | ✅ | desvio padrão |
| `date_iso` | ✅ | `2026-05-03T18:42:00-03:00` |
| `result_json` | ✅ | path para JSON em `benchmarks/results/baselines/` |
| `notes` | opcional | observações relevantes |

---

## Baselines

### bench_parquet_write — TBD (Story 1.4.5)

| Versão | Git SHA | DLL | Hardware | Config | trades/s p50 | p95 | p99 | Date | Notes |
|--------|---------|-----|----------|--------|--------------|-----|-----|------|-------|
| `1.0.0-synthetic` | `TBD` | `mock-1.0` | TBD | row_group=100k, snappy | TBD | TBD | TBD | TBD | sintético; Story 1.4.5 |
| `1.0.0-real` | `TBD` | `4.0.0.30` | TBD | row_group=100k, snappy | TBD | TBD | TBD | TBD | real; Story 1.8 |

**Target V1:** >= 100k trades/s (ver `TARGETS_V1.md`).

---

### bench_parquet_read — TBD (Story 1.4.5)

| Versão | Git SHA | DLL | Hardware | Config | trades/s p50 | p95 | p99 | Date | Notes |
|--------|---------|-----|----------|--------|--------------|-----|-----|------|-------|
| `1.0.0-synthetic` | TBD | n/a | TBD | row_group=100k, snappy, threads=1 | TBD | TBD | TBD | TBD | sintético |

**Target V1:** >= 1M trades/s single thread.

---

### bench_parquet_read_filtered — TBD (Story 1.4.5)

| Versão | Git SHA | DLL | Hardware | Config | filter_selectivity | trades/s p50 | Date |
|--------|---------|-----|----------|--------|--------------------|--------------|------|
| `1.0.0-synthetic` | TBD | n/a | TBD | row_group=100k | 1pct | TBD | TBD |
| `1.0.0-synthetic` | TBD | n/a | TBD | row_group=100k | 10pct | TBD | TBD |

**Target V1:** >= 5M trades/s (com pruning, selectivity 1%).

---

### bench_dedup — TBD (Story 1.4.5)

| Versão | Git SHA | DLL | Hardware | Batch | dup_pct | dedup_key | ms p50 | p99 | Date |
|--------|---------|-----|----------|-------|---------|-----------|--------|-----|------|
| `1.0.0-synthetic` | TBD | n/a | TBD | 10k | 1% | trade_id | TBD | TBD | TBD |
| `1.0.0-synthetic` | TBD | n/a | TBD | 10k | 1% | fallback_composite | TBD | TBD | TBD |

**Target V1:** < 50ms para batch 10k.

---

### bench_callback_to_disk — TBD (Story 1.4.5)

| Versão | Git SHA | DLL | Hardware | writer_pause_ms | queue_size | rate/s | p50 ms | p99 ms | drops | Date |
|--------|---------|-----|----------|----|------|------|--------|--------|-------|------|
| `1.0.0-synthetic` | TBD | mock | TBD | 0 | 10000 | 100k | TBD | TBD | 0 | TBD |
| `1.0.0-synthetic` | TBD | mock | TBD | 100 | 10000 | 100k | TBD | TBD | TBD | TBD |
| `1.0.0-synthetic` | TBD | mock | TBD | 500 | 10000 | 100k | TBD | TBD | TBD | TBD |
| `1.0.0-synthetic` | TBD | mock | TBD | 2000 | 10000 | 100k | TBD | TBD | TBD | TBD |

**Target V1:** p99 < 100ms (cenário 0ms pause).

---

### bench_chunking — TBD (Story 1.4.5 sintético; 1.8 real)

| Versão | Git SHA | DLL | Hardware | Symbol | Month | total_ms | n_chunks | n_trades | Date |
|--------|---------|-----|----------|--------|-------|----------|----------|----------|------|
| `1.0.0-synthetic` | TBD | mock | TBD | WDOJ26 | 2026-04 | TBD | 22 | ~11M | TBD |
| `1.0.0-real` | TBD | 4.0.0.30 | TBD | WDOJ26 | 2026-04 | TBD | 22 | TBD | TBD |

**Target V1:** < 5min em rede boa.

---

### bench_multi_symbol — TBD (Story 1.4.5)

| Versão | Git SHA | DLL | Hardware | n_proc | job_min | strategy | wall_s | speedup | efficiency_% | Date |
|--------|---------|-----|----------|--------|---------|----------|--------|---------|--------------|------|
| `1.0.0-synthetic` | TBD | mock | TBD | 4 | 10 | broker | TBD | TBD | TBD | TBD |
| `1.0.0-synthetic` | TBD | mock | TBD | 4 | 0.5 | broker | TBD | TBD | TBD | TBD |

**Target V1:** speedup >= 3.2x para N=4 (job >= 10min).

---

### bench_boot_cleanup — TBD (Story 1.4.5)

| Versão | Git SHA | Hardware | n_orphans | strategy | ms p50 | ms p99 | Date |
|--------|---------|----------|-----------|----------|--------|--------|------|
| `1.0.0` | TBD | TBD | 100 | scoped | TBD | TBD | TBD |
| `1.0.0` | TBD | TBD | 10000 | full_sweep | TBD | TBD | TBD |

**Target V1:** < 1s para 10k partições.

---

### bench_subprocess_spawn — TBD (Story 1.4.5)

| Versão | Git SHA | Hardware | Stage | p50 ms | p99 ms | Date |
|--------|---------|----------|-------|--------|--------|------|
| `1.0.0` | TBD | TBD | total_cold_start | TBD | TBD | TBD |

**Target V1:** informativo (decide arquitetura: worker pool vs spawn-per-job).

---

### bench_log_overhead — TBD (Story 1.4.5)

| Versão | Git SHA | Hardware | log_level | format | strategy | rate/s | cpu_%_1core | Date |
|--------|---------|----------|-----------|--------|----------|--------|-------------|------|
| `1.0.0` | TBD | TBD | DEBUG | json | per_trade | 100k | TBD | TBD |
| `1.0.0` | TBD | TBD | INFO | json | per_chunk | 100k | TBD | TBD |
| `1.0.0` | TBD | TBD | INFO | json | sampled_1_1000 | 100k | TBD | TBD |

**Target V1:** informativo (define HOT_PATH_RULES.md).

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
