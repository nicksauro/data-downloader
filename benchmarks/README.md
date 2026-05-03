# benchmarks/ — Performance Benchmark Suite

**Owner:** Pyro (perf-engineer)
**Política de baselines:** ver `docs/perf/BASELINES.md`
**Regression policy:** ver `docs/perf/REGRESSION_BUDGETS.md`
**Targets V1:** ver `docs/perf/TARGETS_V1.md`

---

## Princípio fundamental

> **MEDIR ANTES DE OTIMIZAR.** Sem baseline reproduzível, otimização é palpite.

Todos os benchmarks aqui são **esqueletos sintéticos** (Story 1.4.5) que rodam **sem o código de produção pronto** — usam fixtures (`fixtures/synthetic_trades.py`, `fixtures/mock_dll.py`) para validar arquitetura e estabelecer ordens de grandeza ANTES da implementação real (Story 1.8 substituirá fixtures pelo código real e re-rodará tudo).

---

## Suite de benchmarks

| Benchmark | O que mede | Target V1 | Status |
|-----------|-----------|-----------|--------|
| `bench_parquet_write` | trades/s sustained, MB/s, peak memory; matriz row_group × compression | >= 100k trades/s | TODO |
| `bench_parquet_read` | trades/s full scan via DuckDB | >= 1M trades/s single thread | TODO |
| `bench_parquet_read_filtered` | trades/s leitura com WHERE timestamp_ns BETWEEN | >= 5M trades/s (com pruning) | TODO |
| `bench_dedup` | throughput dedup; batches 10k/100k/1M × duplicates 0%/1%/10% | < 50ms para batch 10k | TODO |
| `bench_callback_to_disk` | latência callback DLL → trade visível em Parquet (p50/p95/p99); cenário de back-pressure (writer pausado 0/100/500/2000ms) | p99 < 100ms (cenário 0ms) | TODO |
| `bench_chunking` | tempo total simulado para baixar 1 mês de WDOJ26 | < 5min em rede boa | TODO |
| `bench_multi_symbol` | speedup N processos paralelos (1, 2, 4, 8); contention; CPU/mem total; crossover Windows spawn overhead | speedup >= 3.2x para N=4 | TODO |
| `bench_boot_cleanup` | cleanup de orphan tmp para 100/1k/10k partições | < 1s para 10k | TODO |
| `bench_subprocess_spawn` | cold start de 1 worker DLL no Windows (spawn) — Python init + import + DLL load + auth | informativo | TODO |
| `bench_log_overhead` | structlog throughput em hot path; CPU% gasto só logando | informativo (informa HOT_PATH_RULES.md) | TODO |

---

## Como rodar

### Rodar 1 benchmark
```powershell
python -m benchmarks.bench_parquet_write
```

### Rodar suite completa (TODO — quando script `run_all.py` existir)
```powershell
python -m benchmarks.run_all --output benchmarks/results/
```

### Rodar com pytest-benchmark (TODO)
```powershell
pytest benchmarks/ --benchmark-only --benchmark-json=benchmarks/results/pytest-{date}.json
```

### Rodar comparando contra baseline
```powershell
python -m benchmarks.bench_parquet_write --compare-baseline benchmarks/results/baseline.json
```

---

## Output

Cada benchmark gera um JSON em `benchmarks/results/`:

```
benchmarks/results/bench_parquet_write-2026-05-03-a1b2c3d.json
```

Schema do JSON está documentado em `benchmarks/results/README.md`.

---

## Política de baselines

1. **Cada benchmark tem 1 baseline canônico** registrado em `docs/perf/BASELINES.md`.
2. Baseline inclui: hardware, git_sha, dll_version, config, mediana N runs, p50/p95/p99, desvio, data, notas.
3. **Atualização de baseline exige aprovação de Pyro** (autoridade exclusiva).
4. **Override de regression budget** exige assinatura de Aria (mudança de fronteira) ou Morgan (decisão de produto), registrado em `docs/qa/WAIVERS/`.

---

## Interpretação de regressão

| Diff vs baseline | Severidade | Ação |
|------------------|-----------|------|
| Melhoria > 5% | INFO | Atualizar baseline (após confirmar reprodutibilidade) |
| -5% a +5% | OK | Ruído estatístico; nenhuma ação |
| -5% a -10% | WARN | Investigar causa, registrar em PR |
| -10% a -20% | REGRESSION | Bloqueia merge default; precisa justificativa em PR + override |
| < -20% | CRITICAL | Bloqueia merge sempre; investigação obrigatória |

Default `regression_budget = 10%` por benchmark. Overrides documentados em `docs/perf/REGRESSION_BUDGETS.md`.

---

## Dependências

- `pyarrow` — escrita Parquet
- `duckdb` — leitura Parquet
- `pytest-benchmark` — opcional, para integração com pytest
- `psutil` — medição de memória/CPU
- `numpy` — geração eficiente de fixtures sintéticos

Instalação: ver `requirements-dev.txt` (TODO — Gage Story 0.1).

---

## Hardware de referência

Baselines V1 serão estabelecidos em:
- **CPU:** TBD (preencher em Story 1.4.5)
- **RAM:** TBD
- **Disco:** TBD (NVMe SSD recomendado)
- **OS:** Windows 10 Pro 22H2 (build dev)

Resultados em hardware diferente são **comparativos**, não absolutos. Cada baseline em `BASELINES.md` carrega seu hardware.

---

## Perguntas abertas

Ver `docs/perf/OPEN_QUESTIONS.md`.

— Pyro, medindo o limite ⚡
