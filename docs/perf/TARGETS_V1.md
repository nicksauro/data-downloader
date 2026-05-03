# TARGETS_V1.md — Targets de performance V1

**Status:** todos os targets V1 são **ASPIRACIONAIS** até bench correspondente rodar.
**Validação:** Story 1.4.5 (sintéticos) e Story 1.8 (reais).
**Owner:** Pyro (perf-engineer) — autoridade para ajustar targets pós-medição.

---

## Convenção de status

| Status | Significado |
|--------|-------------|
| `aspiracional` | Target derivado de heurística / experiência prévia; **NÃO medido neste sistema** |
| `measured-synthetic` | Validado via mock DLL + fixtures sintéticos (Story 1.4.5) |
| `measured-real` | Validado via DLL real + dados reais (Story 1.8+) |
| `revised` | Target ajustado após medição revelar realidade diferente |

**Por que "aspiracional" é importante:**
O plan review (finding H3) detectou que targets V1 atuais são palpites. Marcar status explicitamente evita que squad trate aspiração como compromisso.

---

## Targets V1 — Download

| Métrica | Target | Status | Story que valida |
|---------|--------|--------|------------------|
| Latência callback DLL → trade gravado em Parquet (p99) | < 100ms | aspiracional | 1.4.5 (synthetic) → 1.8 (real) |
| Throughput escrita Parquet sustentado | >= 100k trades/s | aspiracional | 1.4.5 → 1.8 |
| Tempo total para baixar 1 mês WDOJ26 (rede boa) | < 5 min | aspiracional | 1.8 (real) |
| Speedup multi-symbol N=4 processos | >= 3.2x (80% efficiency) | aspiracional | 1.4.5 (synthetic) — pode ser revised se H20 confirmar Windows spawn overhead anula |
| Drops de trades em condições normais | 0 | aspiracional | 1.4.5 (synthetic) — depende de resposta de Nelo (finding H4) |
| Drops em pico (writer pausa 500ms via AV scan) | < 0.1% | aspiracional | 1.4.5 — depende de queue + back-pressure |

---

## Targets V1 — Leitura

| Métrica | Target | Status | Story que valida |
|---------|--------|--------|------------------|
| DuckDB full scan (single thread) | >= 1M trades/s | aspiracional | 1.4.5 (synthetic) |
| DuckDB filtrado WHERE timestamp_ns BETWEEN (selectivity 1%) | >= 5M trades/s | aspiracional | 1.4.5 — depende de row_group + statistics |
| Catalog query (SQLite, partição por symbol+date) p99 | < 5ms | aspiracional | Epic 2 |

---

## Targets V1 — Recursos

| Métrica | Target | Status | Story que valida |
|---------|--------|--------|------------------|
| RSS steady state (1 worker download ativo) | < 500MB | aspiracional | 1.4.5 → 1.8 |
| CPU avg durante download (1 symbol) | < 50% (de 1 core) | aspiracional | 1.4.5 → 1.8 |
| Disk size por 1M trades (Snappy) | <= 30MB | aspiracional | 1.4.5 — pode ser revised se ZSTD-1 ganhar (finding H5) |
| Disk size por 1M trades (ZSTD-1) | <= 18MB | aspiracional | 1.4.5 |

---

## Targets V1 — Boot / lifecycle

| Métrica | Target | Status | Story que valida |
|---------|--------|--------|------------------|
| Cleanup orphan tmp 10k partições | < 1s | aspiracional | 1.4.5 (bench_boot_cleanup) |
| Cold start subprocess Windows (worker DLL) | informativo (sem target) | aspiracional | 1.4.5 (bench_subprocess_spawn) |
| Boot time UI até "Ready" (sem download ativo) | < 2s | aspiracional | Epic 3 (Felix) |

---

## Targets V1 — Logging / Observabilidade (R21)

| Métrica | Target | Status | Story que valida |
|---------|--------|--------|------------------|
| CPU% gasto APENAS logando, hot path INFO + sampled_1_1000 + 100k/s | < 5% (de 1 core) | aspiracional | 1.4.5 (bench_log_overhead) |
| CPU% hot path DEBUG per-trade @ 100k/s | informativo (espera-se 50-150%) | aspiracional | 1.4.5 — confirma necessidade de R21 |

---

## Re-avaliação pós-medição

Cada target marcado `aspiracional` será revisitado após bench correspondente rodar:

1. Se bench confirma target → status `measured-synthetic` ou `measured-real`.
2. Se bench mostra que target é **inatingível** com arquitetura atual:
   - Pyro propõe `revised` target + justificativa.
   - Aria revisa (pode exigir ADR amendment se mudança arquitetural for indicada).
   - Morgan aprova (decisão de produto).
3. Se bench mostra que target é **conservador demais** (sistema ganha muito mais):
   - Pyro propõe `revised` target mais agressivo.
   - Atualiza budget de regressão proporcionalmente.

---

## Targets V2 (futuro — não V1)

Aspirações para versões posteriores, registradas aqui para evitar perda de contexto:

| Métrica | Target V2 aspiracional | Notas |
|---------|------------------------|-------|
| Multi-symbol N=8 speedup | >= 6x | requer broker SQLite maduro (ADR-013) |
| Streaming live (não histórico) com latência sub-segundo | p99 < 500ms | Epic 4+ |
| Compressão adaptativa por chunk (Snappy → ZSTD baseado em freq de leitura) | -30% disk avg | Epic 4+ |
| Catalog query distribuída (DuckDB sobre Parquet só) sem SQLite | p99 < 50ms para 1M chunks | Epic 5+ |

---

## Notas

- **Hardware de referência:** ver `BASELINES.md`. Targets em hardware modesto (laptop dev) são piso, não teto.
- **DLL version:** targets assumem `4.0.0.30` (versão atual). Mudança de versão DLL exige re-baseline.
- **Rede:** "rede boa" = > 50 Mbps download estável, latência < 30ms RTT até endpoint Nelogica. Rede pior degrada `bench_chunking` proporcionalmente; outros benchmarks não são afetados (são local).

— Pyro ⚡
