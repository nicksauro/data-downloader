# REGRESSION_BUDGETS.md — Orçamentos de regressão por benchmark

**Owner:** Pyro (perf-engineer) — autoridade exclusiva para definir/alterar budget.
**Política base:** ver Constitution Article V (Quality First) + R21 (HOT_PATH_RULES).

---

## Default

**Budget default = 10%** por benchmark.
Diff > 10% (pior) vs baseline em `BASELINES.md` **bloqueia merge**.

Exemplo: baseline `bench_parquet_write` p50 = 145k trades/s → run atual com 130k trades/s = -10.3% → BLOCKED.

---

## Overrides

Cada benchmark pode ter budget customizado, justificado abaixo:

| Benchmark | Budget | Justificativa | Aprovado por |
|-----------|--------|---------------|--------------|
| `bench_parquet_write` | **10%** | default — write é hot path crítico | Pyro |
| `bench_parquet_read` | **10%** | default | Pyro |
| `bench_parquet_read_filtered` | **10%** | default | Pyro |
| `bench_dedup` | **10%** | default | Pyro |
| `bench_callback_to_disk` | **5%** ⚠️ | latência callback é mais sensível; 5% em p99 já é perceptível | Pyro |
| `bench_chunking` | **30%** ⚠️ | **OVERRIDE EXPLÍCITO Story 1.8** — mock E2E pipeline tem variabilidade alta por nature (multi-thread + writer + catalog + spawn de IngestorThread + AV scan compartilhado). Story 1.8 mediu stddev = 8% sobre 3 runs, mas budget conservador 30% para acomodar variação entre hosts e versões DLL diferentes (real pode ter swing maior). Reduzir para 15% só após smoke real estabilizar. | Pyro |
| `bench_multi_symbol` | **20%** | speedup depende de carga do sistema, AV, schedule do OS, IO contention | Pyro |
| `bench_boot_cleanup` | **30%** | < 1s já é alvo confortável; ruído do filesystem grande | Pyro |
| `bench_subprocess_spawn` | **30%** | Windows spawn varia muito por estado do sistema (page cache, AV, paths) | Pyro |
| `bench_log_overhead` | **15%** | CPU% medido tem ruído por scheduling | Pyro |

---

## Métrica primária por benchmark

Cada benchmark tem 1 métrica primária contra a qual budget é medido. Métricas secundárias são informativas.

| Benchmark | Métrica primária | Direção |
|-----------|------------------|---------|
| `bench_parquet_write` | `trades_per_sec` (p50) | maior = melhor |
| `bench_parquet_read` | `trades_per_sec` (p50) | maior = melhor |
| `bench_parquet_read_filtered` | `trades_per_sec` (p50) com selectivity=1pct | maior = melhor |
| `bench_dedup` | `elapsed_ms_p50` para batch 10k + dup 1% + key=trade_id | menor = melhor |
| `bench_callback_to_disk` | `p99_ms` no cenário writer_pause=0 | menor = melhor |
| `bench_chunking` | `total_ms` | menor = melhor |
| `bench_multi_symbol` | `speedup_vs_sequential` para N=4 + job=10min | maior = melhor |
| `bench_boot_cleanup` | `elapsed_ms_p99` para 10k orphans + full_sweep | menor = melhor |
| `bench_subprocess_spawn` | `total_cold_start_ms` (p50) | menor = melhor |
| `bench_log_overhead` | `cpu_percent_one_core` para cenário INFO + sampled_1_1000 + 100k/s | menor = melhor |

---

## Processo de override (regressão aceita)

1. Bench detecta regressão > budget.
2. Dev (ou agente responsável) abre PR com label `perf-regression`.
3. PR descrição inclui:
   - Diff numérico (baseline vs atual).
   - Causa raiz (com profile/flame graph se possível).
   - Justificativa (por que regressão é aceita?).
   - Plano de mitigação (ou declaração que não há plano).
4. **Aprovação obrigatória:**
   - Pyro (perf) **sempre**.
   - + Aria (architect) **se** mudança altera fronteira/contrato.
   - + Morgan (PM) **se** trade-off é decisão de produto.
   - + Sol (storage) **se** mudança altera layout Parquet.
5. Override é registrado em `docs/qa/WAIVERS/{story-id}-{date}.md`.
6. **Baseline NÃO é atualizado automaticamente** — fica como referência.
   Atualização do baseline = PR separado, depois que mudança estabiliza.

---

## Processo de melhora (improvement)

Run com diff > +5% (melhor) vs baseline:
1. Validar reprodutibilidade (rodar 3x, conferir stddev).
2. Investigar: melhora real ou ruído?
3. Se real: PR atualizando baseline (label `perf-baseline-update`).
4. Aprovação Pyro.

---

## Política de "first baseline" (Story 1.4.5)

Quando baseline NÃO existe ainda (Story 1.4.5 — sintéticos):
- Bench roda mas resultado é INFORMATIVO (não bloqueia merge).
- Após Story 1.4.5 mergear, baselines sintéticos viram canônicos.
- Em Story 1.8 (DLL real), baselines `*-real` substituem `*-synthetic`.
- Regression-check liga em ambiente CI a partir de Epic 2.

---

## CI integration (TBD)

Ver `OPEN_QUESTIONS.md` Q4: bench rodam em CI? GitHub Actions Windows runner? Ou apenas localmente?

Decisão impacta:
- **Local-only:** dev roda manualmente; pre-push hook valida.
- **CI:** PR checks bloqueiam automaticamente; runner precisa ser Windows hosted (lento) ou self-hosted.

— Pyro ⚡
