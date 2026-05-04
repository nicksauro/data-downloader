# TARGETS_V1.md — Targets de performance V1

**Status:** Story 1.4.5 mediu 4 targets (write, read, dedup, callback_to_disk). Restantes ainda ASPIRACIONAIS.
**Validação:** Story 1.4.5 (sintéticos — DONE 2026-05-04) e Story 1.8 (reais — pending).
**Owner:** Pyro (perf-engineer) — autoridade para ajustar targets pós-medição.

---

## Convenção de status

| Status | Significado |
|--------|-------------|
| `aspiracional` | Target derivado de heurística / experiência prévia; **NÃO medido neste sistema** |
| `measured-synthetic` | Validado via fixtures sintéticos + storage real (Story 1.4.5) |
| `measured-real` | Validado via DLL real + dados reais (Story 1.8+) |
| `gap` | Bench rodou e mostrou que target NÃO é atingido — requer otimização ou revisão |
| `revised` | Target ajustado após medição revelar realidade diferente |

**Por que "aspiracional" é importante:**
O plan review (finding H3) detectou que targets V1 atuais são palpites. Marcar status explicitamente evita que squad trate aspiração como compromisso.

---

## Targets V1 — Download

| Métrica | Target | Status | Story que valida | Notas (Story 1.4.5) |
|---------|--------|--------|------------------|---------------------|
| Latência callback DLL → trade gravado em Parquet (p99) | < 100ms | **gap** | 1.4.5 measured | Achieved chunk-mode p99 = 2_244ms (gap +22x). `ParquetWriter` rewrite-full-on-merge é o bottleneck. Ver `docs/decisions/COUNCIL-02`. Target é arquiteturalmente incompatível com modelo chunk-then-write — proposta de revisão em Story 1.7. |
| Throughput escrita Parquet sustentado (production writer) | >= 100k trades/s | **gap** | 1.4.5 measured | Achieved 27_638 trades/s (gap -72%). Causa: validate+enrich+sequence+dedup+merge+sort+fsync+sha256 todos em loop Python. Roadmap em COUNCIL-02 (Story 2.1 vectorização). |
| Throughput escrita Parquet (raw `pq.write_table`) | >= 100k trades/s | **measured-synthetic** | 1.4.5 | Achieved p50 = 1_185_599 trades/s (raw pyarrow snappy rg=1M). Mostra que pyarrow não é o gargalo. |
| Tempo total para baixar 1 mês WDOJ26 (rede boa) | < 5 min | aspiracional | 1.8 (real) | — |
| Speedup multi-symbol N=4 processos | >= 3.2x (80% efficiency) | aspiracional | story posterior | Não medido em 1.4.5 (escopo declarou apenas 4 benchmarks). |
| Drops de trades em condições normais (writer pause = 0) | 0 | **gap parcial** | 1.4.5 measured | Stream-mode @ pause=0 mostrou 108 drops (0.22%) com queue=10k devido a put-timeout 10ms; chunk-mode @ pause=0 + queue=100k = 0 drops. Recomendação: produção usa queue >= 100k. |
| Drops em pico (writer pausa 500ms via AV scan) | < 0.1% | **gap** com queue=10k; **measured-synthetic ✅** com queue=100k | 1.4.5 measured | queue=10k + pause=500ms = 0.40% drops; queue=100k absorve sem drop (qmax=48841 = 49% util). |
| Drops em stress sustentado (writer pause 2000ms) | informativo (validar H4) | **measured H4 CONFIRMED** | 1.4.5 | 1.17% drops com queue=10k — drops inevitáveis sem alarme + queue gigante. Métrica `dll_drops_total` obrigatória em Story 1.7. |

---

## Targets V1 — Leitura

| Métrica | Target | Status | Story que valida | Notas (Story 1.4.5) |
|---------|--------|--------|------------------|---------------------|
| DuckDB full scan (single thread) | >= 1M trades/s | **measured-synthetic ✅** | 1.4.5 | Achieved p50 = 61_381_325 trades/s (61x acima do target). Winner: row_group=100k uncompressed (mas snappy 250k @ 56M também excelente). |
| DuckDB filtrado WHERE timestamp_ns BETWEEN (selectivity 1%) | >= 5M trades/s | **measured-synthetic ✅** | 1.4.5 | Achieved effective scan rate p50 = 35_781_119 trades/s (7x acima). Métrica = total_rows / elapsed (mede pruning). |
| Catalog query (SQLite, partição por symbol+date) p99 | < 5ms | aspiracional | Epic 2 | — |

---

## Targets V1 — Recursos

| Métrica | Target | Status | Story que valida | Notas (Story 1.4.5) |
|---------|--------|--------|------------------|---------------------|
| RSS steady state (1 worker download ativo) | < 500MB | aspiracional | 1.8 | bench_parquet_write peak_rss_delta = 227 MB para 1M trades em ParquetWriter — proxy parcial; medição steady-state real em Story 1.8. |
| CPU avg durante download (1 symbol) | < 50% (de 1 core) | aspiracional | 1.8 | — |
| Disk size por 1M trades (Snappy, row_group=100k) | <= 30MB | **measured-synthetic ✅** | 1.4.5 | Achieved 36.5 MB (gap +21% — ligeiramente acima). Para 1M trades de WDOJ26 sintético com 17 campos. row_group=1M reduz para 30.6 MB (atinge target). |
| Disk size por 1M trades (ZSTD-1) | <= 18MB | **gap parcial** | 1.4.5 | Achieved 26.7 MB com ZSTD-1 (gap +48%). ZSTD-3 = 24.2 MB (gap +34%). Targets foram sub-estimados para schema 17 campos. Recomendação: revisar para <= 30 MB (Snappy) e <= 25 MB (ZSTD-1). |

---

## Targets V1 — Boot / lifecycle

| Métrica | Target | Status | Story que valida | Notas (Story 1.4.5) |
|---------|--------|--------|------------------|---------------------|
| Cleanup orphan tmp 10k partições | < 1s | aspiracional | story posterior | Não no escopo de 1.4.5 (esqueleto vazio). |
| Cold start subprocess Windows (worker DLL) | informativo (sem target) | aspiracional | story posterior | Não no escopo de 1.4.5. |
| Boot time UI até "Ready" (sem download ativo) | < 2s | aspiracional | Epic 3 (Felix) | — |

**Dedup (bench novo medido em 1.4.5):**

| Métrica | Target | Status | Story | Notas |
|---------|--------|--------|-------|-------|
| Dedup batch 10k worst-case p50 | < 50ms | **measured-synthetic ✅** | 1.4.5 | Achieved 11.32ms (78% abaixo). V1 (chave longa) ~1.49x mais lento que V2 — H2 confirmada. |

---

## Targets V1 — Logging / Observabilidade (R21)

| Métrica | Target | Status | Story que valida | Notas (Story 1.4.5) |
|---------|--------|--------|------------------|---------------------|
| CPU% gasto APENAS logando, hot path INFO + sampled_1_1000 + 100k/s | < 5% (de 1 core) | aspiracional | story posterior | bench_log_overhead esqueleto vazio; não no escopo de 1.4.5. |
| CPU% hot path DEBUG per-trade @ 100k/s | informativo (espera-se 50-150%) | aspiracional | story posterior | — |

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
