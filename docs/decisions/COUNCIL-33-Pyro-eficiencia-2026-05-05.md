# COUNCIL-33 — Pyro: Eficiência (consideração #4 do council pós-postfix35)

**Data:** 2026-05-05
**Convocador:** Usuário (council pós-smoke standalone WDOFUT verde)
**Author:** Pyro (perf/observability/baselines)
**Persona scope:** APENAS Pyro (não impersona Quinn/Nelo/Aria/Sol)
**Modo:** Análise estática + dado existente (zero re-bench, zero modificação de código)
**Input canônico:** `docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-postfix35-20260505T123005Z.log`

---

## 1. Métricas observadas (este run)

| Métrica | Valor | Fonte (line) |
|---------|-------|--------------|
| Símbolo | WDOFUT (F) | log L23 |
| Janela | 4 dias corridos (2026-05-01 12:20 → 2026-05-05 12:20) | log L23 |
| `trades_count` | **796_963** | log L175, L179 |
| `duration_seconds` (download_chunk) | **149.989s** | log L179 |
| Throughput sustentado | **~5_313 trades/s** (796_963 / 149.989) | derivado |
| Throughput end-to-end (`total`) | ~5_204 trades/s (incluindo init+connect 1.91s) | log L184 |
| `translate_failures` | **961** (~0.12% das 796_963) | log L179 |
| `trade_edits` | 0 | log L179 |
| `progress_99_reconnect` | False | log L179 |
| `last_packet_seen` | True (TC_LAST_PACKET autoritativo) | log L179 |
| `agent_resolver.unknown_id` debug events | 4 visíveis (não são erros — IDs raros caem em `Agent#{id}` fallback determinístico) | log L171-174 |
| `queue_full` events | **0** (zero) — nem `trade_queue` nem `progress_queue` saturaram | grep no log |
| Acessos violation no log | 5 (todos do harness PowerShell `Tee-Object 2>&1`, **não** do download — `[VERDICT] PASS` confirma) | log L32-170 |

**Pipeline analisado:** standalone DOWNLOAD-ONLY. Não há `ParquetWriter`, dedup, validation, ou disk write neste run — apenas DLL → callback V2 → trade_queue → IngestorThread (TranslateTrade + AgentResolver) → list de TradeRecord em memória. Conclusões abaixo refletem **só** o gargalo download+ingestor, **não** o pipeline E2E.

---

## 2. Comparação com baselines existentes

### 2.1 Pyro baseline canônico (Story 1.8 / COUNCIL-10 / `docs/perf/BASELINES.md`)

| Bench | Versão | Throughput p50 | Cenário |
|-------|--------|---------------|---------|
| `pq.write_table` raw (rg=1M, snappy) | v1.0.0-synthetic | 1_185_599 trades/s | write isolado |
| `pq.write_table` raw (rg=100k, snappy) | v1.0.0-synthetic | 802_229 trades/s | write isolado |
| `ParquetWriter` (production, 1.4.5) | v1.1.0-mock | 27_638 trades/s | write canônico (com validate+enrich+dedup+merge+sha256) |
| `ParquetWriter` (vectorized 2.2) | **v2.0.0-vectorized** | **121_565 trades/s** | write canônico vectorized — TARGET V1 ATINGIDO (+21.6%) |
| Pipeline E2E (mock orchestrator+writer+catalog) | v1.1.0-mock | 4_594 trades/s | full chunk |

### 2.2 Comparação real-DLL standalone vs baselines mock

| Eixo | Real DLL (este run) | Baseline mock relevante | Δ |
|------|---------------------|------------------------|---|
| download+ingestor (sem parquet) | **5_313 trades/s** | n/a — sem baseline isolado | — |
| Pipeline E2E mock (com ParquetWriter v1.1.0) | n/a aqui | 4_594 trades/s | real-DLL ingestor ~+15% acima do E2E mock — sugere DLL sustenta o pipeline |
| Pipeline E2E mock (com ParquetWriter v2.0.0 vectorized) | n/a aqui | extrapolação ~30k trades/s (cap teórico do orquestrador serial) | real-DLL ingestor seria gargalo abaixo do writer vectorizado por **5.6x** |

**Inferência crítica:** com vectorização v2.0.0 já em produção, o **gargalo dominante mudou** do writer (era 27k trades/s) para o **DLL/IngestorThread (5.3k trades/s)**. Isto é uma inversão que **invalida parcialmente** a estratégia de COUNCIL-10 (que assumia writer = bottleneck).

### 2.3 Comparação com pico real WDO B3

WDOFUT em pregão pleno tem pico instantâneo ~1k-3k trades/s; média 4 dias inclui after-hours/madrugada. **5.3k trades/s sustentado no replay histórico** indica que a DLL está entregando rajadas bem acima do real-time — provavelmente buffer de servidor Nelogica drenando comprimido. Implicação: o pipeline NÃO é gargalo para live (latência muito menor que ingestion rate); é gargalo apenas para backfill em massa.

---

## 3. Gargalo identificado: TranslateTrade serial @ IngestorThread

### 3.1 Decomposição do hot path (`_process_trade`, download_primitive.py:336-426)

Por trade, sequencialmente:

1. `dll.translate_trade(handle)` — ctypes call → `TranslateTrade` C, copia 9 fields (price, qty, ts, agents, etc.) — wrapper.py:1697-1736
2. `_system_time_to_ns_local(struct.TradeDate)` — datetime construct + nanos
3. `format_brt_timestamp(timestamp_ns)` — strftime
4. `defaultdict[timestamp_ns]` lookup + `seq + 1`
5. `AgentResolver.resolve(buy_agent_id)` — dict-hit em hot path (cache); cache miss = 2 ctypes calls (`GetAgentNameLength` + `GetAgentName` + alloc buffer wide-char). Log mostra ≥4 unknown_ids → ≥4 cache misses ao longo do run, irrelevante.
6. `AgentResolver.resolve(sell_agent_id)` — idem
7. `time.time_ns()` (ingestion stamp)
8. `TradeRecord(...)` — frozen dataclass alloc (17 fields)
9. `self.trades.append(record)` — list append amortized O(1)

**Custo estimado por trade @ 5.3k/s:** ~188 µs/trade. Subtraindo overhead típico de ctypes round-trip (~5-15 µs em Windows) e dataclass alloc Python 3.14 (~10-20 µs com 17 fields), **TranslateTrade nativo é ~50-100 µs**, restante é Python overhead.

### 3.2 Evidência empírica: `translate_failures = 961`

961 falhas em 796_963 = 0.121%. Custo estimado de retry/discard: cada falha custa o mesmo `translate_trade` call + early-return (sem dataclass alloc). Overhead total: ~961 × 60 µs = **~58 ms** ao longo de 150s — **negligenciável** (0.04% do runtime). NÃO é fonte de regressão.

### 3.3 Queue saturation: NÃO observada

Zero `queue_full` no log. `TRADE_QUEUE_MAXSIZE=100_000` (download_primitive.py:88) → buffer de ~19s no pace atual. Callback nunca esperou. Ingestor manteve drain. **Sizing correto** (Pyro 1.4.5 finding confirmado).

### 3.4 Memória estimada

- 796_963 `TradeRecord` frozen dataclass × ~400 bytes (17 campos, mix int/float/str/None) = **~320 MB peak** retidos em `ingestor.trades` list até o retorno do `download_chunk`.
- Ainda + handles na queue (transitório, max 100k × ~32 bytes = 3.2 MB).
- AgentResolver cache: ≤256 brokers × ~80 bytes = 20 KB negligível.
- **Total RSS estimado durante o run:** ~350-400 MB peak. Sem profiler real, mas dentro do orçamento de máquina dev (16 GB+).

---

## 4. Top 5 oportunidades de eficiência (ranqueadas por ROI)

### #1 — Batched IngestorThread (drain de N>1 por iteração)

**Idéia:** trocar `queue.get(timeout=0.1)` 1-a-1 por `_drain_n(queue, max_batch=512)` que chama `get_nowait()` em loop até esvaziar ou hit max_batch, depois processa todos sob 1 contextvar `run`. Reduz overhead de wakeup do thread (atualmente ~10 wakeups/ms no pico).

**Ganho estimado:** **+15-25%** throughput ingestor → **~6.1k-6.6k trades/s**.
**Complexidade:** S (≤30 LOC, IngestorThread isolada).
**Risco:** S (não toca callback, não toca DLL — semântica preservada; testes existentes seguram regressão).

### #2 — Translate em batch via `_translate_trade_raw` reusando struct

**Idéia:** wrapper.py:1738-1774 já documenta `_translate_trade_raw` como micro-opt ("evita alocação por trade"). Adotar no IngestorThread: alocar 1 `TConnectorTrade(Version=0)` no `__init__` da thread, chamar `_translate_trade_raw(handle, struct)` direto, copiar campos para `TradeFields` local. Elimina `TConnectorTrade(Version=0)` alloc per-trade (~796k allocs evitados).

**Ganho estimado:** **+8-12%** ingestor (alloc ctypes structs Python 3.14 é mais caro que 3.11 — Pyro 1.4.5 finding extrapolado) → **~5.7k-5.9k trades/s**.
**Complexidade:** S (15 LOC).
**Risco:** M — wrapper.py:1751-1752 já alerta para "buffer pode ser reescrito na próxima chamada"; teste regressão obrigatório (Hypothesis preservation invariants).

### #3 — Substituir `TradeRecord` frozen dataclass por slot-based `__slots__` class ou tuple

**Idéia:** frozen dataclass com 17 fields aloca dict per-instance (Python 3.14 ainda paga overhead). Trocar por `__slots__` class (-30% RAM, -10% alloc time) ou — mais radical — acumular em arrays columnar (numpy / pa.array builders) direto no IngestorThread, eliminando objeto Python por trade.

**Ganho estimado:** **+10-30%** se columnar (depende de quanto downstream consome objetos vs arrays); **+5-8%** se só __slots__.
**Complexidade:** M (slots) / L (columnar — quebra ABI de `ChunkResult.trades: list[TradeRecord]` — story dedicada, ADR amendment ao SCHEMA.md).
**Risco:** S (slots) / L (columnar — Sol authority, COUNCIL dedicado, INV invariants Hypothesis).

### #4 — IngestorThread paralelo (N=2-4 workers consumindo a mesma queue)

**Idéia:** atualmente 1 IngestorThread serial. TranslateTrade é GIL-released (ctypes call C nativa libera GIL durante a chamada). Múltiplos ingestors em paralelo poderiam quase dobrar throughput.

**Ganho estimado:** **+50-80%** com N=2 (Amdahl conservador) → **~8-9.5k trades/s** com N=2.
**Complexidade:** M (precisa repensar `_sequence_counter` defaultdict — atualmente non-thread-safe; precisa Lock ou per-thread counter merged no fim).
**Risco:** **M-H** — `last_packet_seen` precisa ser flag atômica (já é bool, OK em CPython); `trades.append()` non-thread-safe (precisa thread-local lists merged); Sol pode ter objeção sobre `sequence_within_ns` determinismo. **Requer mini-council Pyro+Sol+Aria** antes de implementar.

### #5 — Pre-allocate `defaultdict` keys + skip `format_brt_timestamp` per-trade

**Idéia:** (a) `_sequence_counter` cresce sem bound; mover para `dict[int, int]` com sentinela `dict.get(k, 0)`. (b) `format_brt_timestamp` constrói string strftime per-trade — 796k × ~5µs = ~4s só pra strftime. Adiar para cool path: armazenar só `timestamp_ns` no TradeRecord, formatar no writer (já vectorizado v2.0.0).

**Ganho estimado:** **+3-5%** ingestor (~+200 trades/s).
**Complexidade:** S (mas exige mudança em `TradeRecord` schema interno — `timestamp_str` vira lazy property ou removido do hot path).
**Risco:** M — Sol authority sobre TradeRecord shape; Quinn precisa validar que `timestamp_str` ainda aparece nos parquets.

### Outras (rejeitadas / não top-5)

- **Aumentar `TRADE_QUEUE_MAXSIZE`:** sem evidência de saturação (zero queue_full). Não fazer.
- **Compression tuning:** fora do escopo (este run não escreve parquet). Já endereçado em `docs/perf/BASELINES.md` §dedup.
- **Memory pool de TConnectorTrade:** já coberto por #2 (struct reuse single-instance).
- **DuckDB para queries posteriores:** read path já está em 35-61M trades/s (BASELINES.md L171-176) — não é gargalo.

---

## 5. Recomendação para próximas fases

**Status atual:** com ParquetWriter v2.0.0 vectorizado (Story 2.2 Done), o **bottleneck migrou** do write (121k trades/s) para o **download+ingest (5.3k trades/s real, 4.6k trades/s mock E2E)**. Story 1.8-followup (Pending Human) deve **re-baseline** v1.0.0-real usando este log + 1 run com ParquetWriter encadeado para confirmar que pipeline E2E real ≈ ingestor real (ParquetWriter não saturará).

**Recomendações priorizadas:**

1. **Não otimizar agora.** Throughput real-DLL (5.3k/s) já é >2x o pico WDO B3 — para uso live e backfill curto, não há demanda por mais.

2. **Criar Story 2.3 — IngestorThread Throughput** (P2, estimate 2d) cobrindo Top-5 #1 + #2 + #5 (todas S/M, sem ABI break). Esperado: 5.3k → ~7k trades/s. Owner: Pyro. Reviewers: Nelo (DLL semantics), Sol (TradeRecord schema), Quinn (regression gate, Hypothesis preserve invariants).

3. **Diferir Top-5 #3 (columnar) e #4 (parallel ingestor)** para Epic 4 ou quando demanda real (multi-symbol massivo / backfill anual) aparecer. Ambas exigem council dedicado (Sol+Aria+Pyro) e ADR amendment.

4. **Re-baseline obrigatório:** Story 1.8-followup deve registrar `v2.1.0-real` com este log + run E2E real ParquetWriter v2.0.0. Sem isso, regressão futura não é detectável.

5. **Telemetria pendente (não bloqueante):** adicionar metric `ingestor_translate_failures_rate` (Story 1.8-followup ou em Story 2.3). 961/796_963 = 0.121% é OK hoje, mas sem alert se subir para >1% silenciosamente.

---

## 6. Sign-off

| Persona | Aprova | Justificativa |
|---------|--------|---------------|
| **Pyro** ⚡ (autor) | ✅ | Análise estática completa; recomendação conservadora "não otimizar agora" sustentada em dado (zero queue_full, throughput >2x B3 peak). |
| **Sol** 💾 | ⏳ (consult required Top-5 #3, #5) | Mudanças em TradeRecord shape (timestamp_str lazy / __slots__) precisam Sol authority. NÃO aprovado neste council. |
| **Aria** 🏛️ | ⏳ (consult required Top-5 #4) | Parallel IngestorThread quebra modelo single-thread atual; ADR-005 INV-1 segue intacto, mas ABI muda. NÃO aprovado neste council. |
| **Nelo** 🔌 | ⏳ (consult required Top-5 #2) | Reuse de struct ctypes `TConnectorTrade` — wrapper.py:1751 já alerta. Nelo precisa confirmar safety. NÃO aprovado neste council. |
| **Quinn** 🛡️ | ⏳ (regression gate p/ Story 2.3) | Hypothesis preserve invariants obrigatório se #1/#2/#5 forem implementadas. |

**Decisão deste council (escopo eficiência apenas):** "ship as-is; criar Story 2.3 backlog P2; re-baseline em Story 1.8-followup".

— Pyro ⚡ (squad data-downloader, council member: eficiência)
