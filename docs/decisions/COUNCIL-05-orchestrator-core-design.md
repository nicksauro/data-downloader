# COUNCIL-05 — Orchestrator core design (Story 1.7a)

**Data:** 2026-05-04
**Convocação:** Dex (dev) — modo autônomo Story 1.7a
**Participantes mentais:** Dex (impl authority), Aria (state machine — já amendou ADR-005), Pyro (queue defaults — COUNCIL-02), Sol (catalog handoff)
**Contexto:** Story 1.7a integra `download_chunk` (Story 1.3) + `Catalog` (Story 1.5)
+ `ParquetWriter` (Story 1.4) em loop multi-chunk com retry, recovery e state
machine de shutdown (ADR-005 amendment).

---

## Decisões upfront

### D1 — State machine: ADR-005 amendment (Idle → Running → DrainingDLL → DrainingWrite → Committed → Idle)

**Decisão:** Implementar exatamente conforme amendment de ADR-005 (2026-05-03,
Aria). 6 estados (incluindo `FAILED` como terminal alternativo). Transições
válidas explícitas em `JobStateMachine.transition()`. `threading.Lock` interno
para thread-safety. Logger event para cada transição via structlog (cool path —
1 evento por transição, R21 OK).

**Sign-off:** Aria — implícito (já amendou ADR). Quinn — aplicará INV-11/INV-12
durante QA.

**Estados extra além do amendment:**
- `FAILED` — terminal alternativo a `COMMITTED` quando run abortado por erro
  fatal antes de COMMITTED. Permitido apenas a partir de `RUNNING` ou
  `DRAINING_*`. Documentado em docstring.

### D2 — Queue size default: dll_queue=100_000 (Pyro)

**Decisão:** A constante `TRADE_QUEUE_MAXSIZE` já está em
`download_primitive.py` (Story 1.3) com valor 100_000 (atendendo recomendação
Pyro 1.4.5 / COUNCIL-02). Story 1.7a NÃO altera — `download_chunk` cria sua
própria fila per-chunk. Orchestrator não cria fila própria de trades; ele
consome `ChunkResult` (lista materializada) do `download_chunk`.

**Configurável:** `DATA_DOWNLOADER_DLL_QUEUE_SIZE` env var é responsabilidade
de `download_primitive`; orchestrator apenas honra o tamanho default.

### D3 — Métricas (V1: structlog events, V2: Prometheus em ADR-013)

**Decisão V1 (Story 1.7a):** Métricas expostas via structlog events (cool path
— per-chunk):

| Métrica            | Tipo      | Onde emitida                        |
|--------------------|-----------|-------------------------------------|
| `dll_drops_total`  | counter   | Não emitida em V1 (download_chunk não dropa — block back-pressure). Reservada para Story 2.X (drop policy se mudar). |
| `chunk_duration`   | histogram | `orchestrator.chunk_complete` (ms) |
| `chunks_completed` | counter   | `orchestrator.complete` (final)    |
| `chunks_failed`    | counter   | `orchestrator.complete` (final)    |
| `trades_persisted` | counter   | `orchestrator.complete` (final)    |
| `state_transition` | event     | `orchestrator.state_transition`    |

V2 (ADR-013, deferred): Prometheus exporter — sem mudança de API.

### D4 — Chunking strategy: lookup por prefixo + business-days B3

**Decisão:**

| Prefixo  | dias úteis B3/chunk | Justificativa                              |
|----------|---------------------|--------------------------------------------|
| `WDO*`   | 5                   | Manual §3.1 Q12-E — alta vazão futuros mini |
| `WIN*`   | 5                   | Idem                                       |
| `IND*`   | 5                   | Idem (índice cheio)                        |
| `DOL*`   | 5                   | Idem (dólar cheio)                         |
| (outros) | 1                   | Equities — vazão menor, granularidade fina |

Implementado em `chunker.py::CHUNK_DAYS` (mapa) + função pura
`chunk_date_range(symbol, start, end, *, calendar)`. Consome
`b3_business_days_range` de `validation.calendar_b3` — pula feriados e fins de
semana automaticamente. Configurável via parâmetro `chunk_days_map` (sobrescreve
default por símbolo).

### D5 — Retry policy: exponencial 3 tentativas (1s, 4s, 16s) com jitter

**Decisão:**

- `max_attempts = 3`
- `base_delay = 1.0s`, `factor = 4` (delays: 1s, 4s, 16s)
- Jitter: `±20%` uniforme (evita thundering herd em multi-chunk falha)
- **Erros transientes (retry):** `OSError` (rede), `TimeoutError`,
  `ChunkResult.status == "timeout"`. Códigos NL_* específicos (futuro: NL_CONN_LOST,
  NL_TIMEOUT) — V1 trata `status == "timeout"` como retryable.
- **Erros fatais (no retry):** `ValueError` (validação — exchange/dt order),
  `InvalidContract`, `IntegrityError` (storage), `KeyboardInterrupt`,
  `SystemExit`.
- Após 3 falhas: chunk marcado `failed`, `Catalog.register_gap(reason="failed_chunk")`,
  loop continua próximo chunk (NÃO aborta job).

**Justificativa:** Aria recomendação 1.4.5 — "0 drops sob carga normal" inclui
tolerância a falhas transientes. 3 retries cobre 99% de blips de rede sem
inflar latência (16s + 4s + 1s + 3 × chunk_duration ≈ 60s extra worst case).

### D6 — Recovery: usa Catalog.resume_job (Story 1.5)

**Decisão:** `Orchestrator.run(config, *, resume_job_id=None)`:

- Se `resume_job_id` é `None`: `register_job` → calcula chunks → loop.
- Se `resume_job_id` passado: `Catalog.resume_job(job_id)` retorna
  `ResumePlan(job, completed_partitions, pending_chunks)`. Orchestrator
  recalcula seus sub-chunks DENTRO de `pending_chunks` (que vem em
  granularidade mensal — Story 1.5 §AC8) e processa apenas os ranges
  realmente faltantes.

**Sign-off Sol:** implícito — Catalog API já estável (Story 1.5 PASS).

### D7 — Cache hit = range coverage REAL (finding H8)

**Decisão:** Antes de iniciar loop, calcular union dos ranges das partições
registradas para `(symbol, exchange)`. Se `[start, end] ⊆ union(partições)` →
`status="cache_hit"`, retornar sem chamar DLL. Implementação em
`Orchestrator._check_cache_hit(config, completed_partitions)`. Granularidade
mensal (alinhada a `compute_pending_chunks` da Story 1.5) — se TODOS os meses
em `[start, end]` têm partição registrada, é cache hit.

### D8 — correlation_id = job_id (finding L2)

**Decisão:** Toda mensagem structlog do orchestrator carrega `job_id=...`
(começando em `register_job`) — funciona como correlation_id agregando logs
do mesmo run. `chunk_id` (vindo de `download_chunk`) é sub-correlação
per-chunk.

### D9 — Logging eventos canônicos (R21 — per-chunk OK, per-trade NÃO)

**Eventos emitidos:**

- `orchestrator.start` — job_id, symbol, exchange, range, mode (fresh/resume)
- `orchestrator.contract_resolved` — symbol_root → contract_code
- `orchestrator.cache_hit` — partições já cobrem range
- `orchestrator.chunk_start` — job_id, chunk_id (gerado), sub-range
- `orchestrator.chunk_complete` — job_id, chunk_id, n_trades, duration_ms
- `orchestrator.chunk_failed` — job_id, chunk_id, attempts, last_error
- `orchestrator.state_transition` — job_id, from, to
- `orchestrator.complete` — job_id, status (completed/partial/failed),
  chunks_ok/failed, trades_persisted, duration_s

**Não emitido:** per-trade events (R21 violação).

---

## Concordância dos participantes

### Aria (architect — mental)

Endossa D1 (state machine = ADR-005 amendment), D7 (cache hit = range coverage
real fecha H8), D8 (correlation_id = job_id fecha L2). Recomenda que o
`FAILED` terminal extra seja documentado em ADR-005 amendment v2 (story 2.1
follow-up — não bloqueia 1.7a).

### Pyro (perf — mental)

Endossa D2 (queue 100k já em download_primitive), D3 (V1 structlog cool-path
OK), D4 (chunking 5 dias úteis WDO/WIN evita batches gigantes que estouram
write_queue). Recomenda monitorar `chunk_duration` para validar premissa de
chunk size — se p99 > 30s sustentado, reduzir CHUNK_DAYS para WDO/WIN
(deferred Story 2.X).

### Sol (storage — mental)

Endossa D6 (resume via Catalog.resume_job — Story 1.5 API estável). Confirma
que `register_partition` é idempotente (UPSERT por path) — re-registrar mesma
partição é safe. Pré-condição respeitada: orchestrator chama
`writer.write(...)` PRIMEIRO, depois `catalog.register_partition(write_result,
partition, job_id)` (two-phase commit emulado, Story 1.5 §AC13).

---

## Aplicação imediata neste PR (Story 1.7a)

- 4 novos módulos em `src/data_downloader/orchestrator/`:
  `state_machine.py`, `chunker.py`, `retry.py`, `orchestrator.py`.
- 6 novos arquivos de teste cobrindo unit + integration + property.
- Atualização de `orchestrator/__init__.py` com exports públicos.
- Sem mudança em `download_primitive.py`, `contracts.py`, `storage/*`,
  `dll/*`, `public_api/*` — orchestrator apenas COMPÕE essas camadas.

— Dex 💻 (com mini-council mental Aria + Pyro + Sol)
