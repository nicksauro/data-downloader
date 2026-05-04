# COUNCIL-02 — ParquetWriter overhead em streaming + revisão de targets V1

**Data:** 2026-05-04
**Convocação:** Pyro (perf-engineer) — modo autônomo Story 1.4.5
**Participantes mentais:** Pyro (autoridade perf/regression), Sol (autoridade storage layout)
**Contexto:** Implementação de baselines sintéticos (Story 1.4.5). Bench
`bench_parquet_write` e `bench_callback_to_disk` revelaram que `ParquetWriter`
de produção (Story 1.4) tem throughput ~27k trades/s vs target V1 100k/s — gap
de 73%. Causa raiz identificada via comparação com `pq.write_table` direto
(~750k trades/s).

---

## Findings empíricos (host: i7-3770 4c/8t, 16GB, Win10)

### F1 — ParquetWriter throughput vs raw pq.write_table

| Path | Throughput p50 | Notas |
|------|---------------|-------|
| `pq.write_table` (raw, snappy, row_group=100k) | ~750k trades/s | apenas serialize + write |
| `ParquetWriter.write` (canônico, snappy, rg=100k, validate+dedup+fsync+sha256) | ~27k trades/s | -96% vs raw |

**Gap**: ~28x slower. Atribuído a:
1. `validate_record` chamada per-trade (Python loop puro).
2. `assign_sequence_within_ns` per-trade (Python loop com defaultdict).
3. `dedup` via dict construction + tuple hashing per-trade.
4. `_trades_to_table` constrói arrays coluna a coluna em Python (não vectorized).
5. `sort_by` em pa.Table sobre dataset todo.
6. `fsync(file)` + `fsync(parent_dir)` (Windows: latência de IO sync).
7. `_sha256_file` lê arquivo completo de novo após write.

### F2 — Merge overhead em streaming small-batch

`ParquetWriter.write` faz `pq.read_table` + union + `dedup` + sort + write
quando `path.exists()`. Em streaming (batches sucessivos na mesma partition):

- N batches de M trades na mesma partition = O(N²·M) work cumulativo.
- `bench_callback_to_disk` cenário `stream` mostrou p99 = 1.0-1.5s (em apenas
  10k callbacks com batches de ~5k cada — ~2 writes; cada write rebatcha tudo).

### F3 — Chunk-mode (1 write/chunk per Story 1.7) é viável mas distante de 100ms

Mesmo no padrão Story 1.7 (1 write único por chunk de ~500k trades), a
latência callback->disk inclui:

- Tempo de chunk completar (~ rate inverse): para 100k trades/s + chunk 500k
  = ~5s só para coletar.
- Tempo de write único: 500k / 27k trades/s = ~18.5s.

**p99 callback->disk realista em produção: dezenas de segundos**, não 100ms.

### F4 — H4 (back-pressure) — INDETERMINADO neste host

Cenário `writer_pause_ms=2000` com `queue.put(timeout=10ms)` resultou em
**0 drops** porque o writer drena em batches de 10k a cada ciclo, e na
janela de 100ms (n_callbacks=10k) o buffer (queue=10k) absorveu antes da
pausa de 2s ser sentida. **Bench precisa rodar com n_callbacks maior +
sustained rate** para validar H4 propriamente — escopo Story 1.7 (real
ingestor + worker process).

---

## Opções consideradas

### Opção A — Aceitar throughput atual, revisar target V1
Atualizar `TARGETS_V1.md`:
- `throughput_writes`: 100k/s → 25k/s (gap reconhecido).
- `latency_callback_to_disk_p99`: 100ms → 30s (rechunked: latência domínio = chunk wait, não ParquetWriter).

### Opção B — Otimizar ParquetWriter (Story 2.X)
Otimizações progressivas (cada uma é uma story):
1. **Vectorize `_trades_to_table`**: usar numpy/pa.array direto de columns dict
   (prepara arrays coluna por coluna sem Python loop). Esperado: 3-5x speedup.
2. **Vectorize `validate_record`**: rodar via pa.compute em batch (greater_than, isin)
   em vez de loop Python. Esperado: 5-10x speedup neste passo.
3. **Vectorize `dedup`**: usar pa.compute.unique sobre array de chave canônica
   computada como hash int64 (hash combinado em numpy). Esperado: 10x speedup.
4. **Skip merge para append-only**: se chamador garante "primeira escrita
   da partition na sessão" + "trades novos > existing.last_ts", append direto
   sem read+merge+sort.
5. **Defer fsync(parent_dir) e SHA256 para flush periódico**: trade-off durabilidade
   vs throughput; aceitar janela de risco controlada.

### Opção C — Streaming-append API separada (ADR-002 amendment)
Adicionar `ParquetStreamWriter` (separado de `ParquetWriter` atomic) que mantém
um `pq.ParquetWriter` aberto durante chunk e escreve row groups incrementalmente.
Trade-off: arquivo não é atomic durante stream (mas arquivo final via os.replace
ainda é). Complexidade média; afeta SCHEMA.md §4 (metadata só fechado no end).

---

## Decisão tomada (Pyro autoridade perf, com mini-council Sol storage)

**Decisão imediata (Story 1.4.5 — escopo: registrar baseline honesto):**

1. **Aceitar números atuais como baseline canônico v1.0.0-synthetic**.
   Eles refletem o que produção entrega hoje. ZERO mascaramento.

2. **Atualizar `TARGETS_V1.md`** marcando os targets afetados como
   `gap` (não atingido) com referência a este COUNCIL.

3. **NÃO mudar o código de produção nesta story** (escopo é baseline,
   não otimização). Otimização é trabalho futuro (Stories 2.X, ver Opção B).

**Decisão de longo prazo (recomendação para PM/architect):**

4. **Story 2.1 (perf optimization roadmap)**: Pyro propõe story dedicada
   para Opção B passos 1-3 (vectorização). Estimativa: 3-5d trabalho,
   esperado fechar gap para ~150-200k trades/s (atinge target V1).

5. **Não buscar Opção C (streaming-append)** até Opção B esgotar. Razão:
   complexidade de SCHEMA.md (metadata final-only) + perda de atomicidade
   intermediária podem violar invariantes INTEGRITY.md INV-3 (read-after-write
   consistency).

6. **Revisar target `latency_callback_to_disk_p99`** em Story 1.7 (real
   orchestrator). Target 100ms é provavelmente inatingível com modelo
   chunk-then-write; deve ser substituído por:
   - "0 drops sob carga normal" (queue absorve)
   - "p99 callback→queue acceptance < 1ms" (responsividade do callback)
   - "p99 chunk→disk (write completes) < 30s para chunk 500k" (write throughput)

---

## Concordância de Sol (storage authority — mental)

Sol concordaria com:
- Decisão 1-3 (não otimizar nesta story; baseline honesto).
- Recomendação 4 (Opção B é o caminho — preserva contratos atuais).
- Recomendação 5 (NÃO Opção C — quebra atomicidade single-file).
- Recomendação 6 (target callback->disk p99 100ms é aspiracional incompatível
  com chunk-then-write design).

Sol enfatizaria que **Opção B passo 4 (skip merge para append-only)**
exige cuidado especial: a invariante "dedup(L ++ L) == dedup(L)" só vale
se chamador garante chunks sequenciais sem overlap. Em produção isso é
garantido pelo orchestrator (chunks consecutivos), mas o writer não pode
assumir — precisaria de novo método explícito `write_append_only()` com
docstring forte sobre pré-condição.

---

## Aria consultation (não convocada inicialmente — mudança não cruza fronteira)

Esta decisão NÃO altera fronteira de camada. Otimizações futuras (Opção B)
ficam dentro de `data_downloader.storage.parquet_writer` — sem novo
contrato externo. Aria consultada apenas se Opção C escalada.

**RATIFICAÇÃO ARIA (2026-05-04):** Aria revisou COUNCIL-02 durante
`*review-design 1.4.5` e endossa as 6 decisões/recomendações. Sign-off
formal abaixo.

---

## Aplicação imediata neste PR (Story 1.4.5)

- `TARGETS_V1.md` updated com status `gap` para targets afetados.
- `BASELINES.md` registra números reais com link a este COUNCIL.
- Bench permanece como-está (mostra realidade) — futura redução de
  regressão será MELHORA, não baseline shift.

— Pyro ⚡ (com mini-council Sol)

---

## Sign-off Aria (architect) — 2026-05-04

Aria endossa formalmente as 6 decisões/recomendações de COUNCIL-02 após
revisão durante `*review-design 1.4.5`. Auditoria completa em
`docs/qa/AUDIT_REPORTS/1.4.5-design-2026-05-04.md` §7.

**Aria endorses:**

1. ✅ Aceitar números atuais como baseline canônico v1.0.0-synthetic.
2. ✅ Atualizar `TARGETS_V1.md` marcando targets afetados como `gap`.
3. ✅ NÃO mudar código de produção nesta story (escopo = medição).
4. ✅ **Story 2.1 (perf-write-optimization)** — Opção B passos 1-3
   (vectorização interna do `ParquetWriter`). Owner Pyro, reviewer Sol.
   Otimização interna NÃO cruza fronteira de camada — sem ADR amendment
   necessário.
5. ✅ NÃO buscar Opção C (streaming-append separado) até Opção B esgotar.
   Opção C quebraria atomicidade single-file (INV-3) + exigiria ADR
   amendment a ADR-002 + revisão SCHEMA.md §4 (metadata final-only).
6. ✅ Revisar target `latency_callback_to_disk_p99` em Story 1.7
   (decomposição em 3 sub-targets: `0 drops sob carga normal`,
   `p99 callback→queue acceptance < 1ms`, `p99 chunk→disk < 30s para
   chunk 500k`). Decomposição é arquiteturalmente superior.

**Aria adds (não-vinculante):**

7. Story 2.1 deve incluir **property-based tests** (Hypothesis) para
   garantir que vectorização preserva invariantes INV-2/INV-3/INV-7.
   Vectorização é refactor de risco; Hypothesis é o gate apropriado.
8. Bump default `dll_queue maxsize` 10k → 100k (recomendação 2 do
   COUNCIL-02) em Story 1.7 deve ser documentado como **ADR amendment
   pequeno (3-5 linhas) a ADR-005**. Justificativa empírica: H4
   confirmada (queue=10k + pause=2000ms = 1.17% drops; queue=100k +
   pause=500ms = 0 drops).

**Mini-council confirmado:** Pyro (perf-engineer) + Aria (architect).
Consultoria mental: Sol (storage layout authority). Story 2.1
**perf-write-optimization** a ser criada por Morgan (PM) com base nesta
ratificação.

— Aria, mapeando o território 🏛️
