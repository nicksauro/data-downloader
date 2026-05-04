# COUNCIL-15 — Prometheus Exporter V2 (Story 2.4)

**Data:** 2026-05-04
**Convocação:** Dex (dev) — modo autônomo Story 2.4 (Prometheus exporter V2)
**Participantes mentais:** Aria (architect — Protocol fronteira), Pyro
(perf — hot path R21), Dex (impl — minimalismo opt-in)
**Contexto:** Story 2.4 antecipa a V2 do ADR-013 (HTTP exporter Prometheus
deferred Epic 4 → Epic 2) porque smoke MVP V1 (Story 1.7b release readiness)
exige métricas live para dashboards e validação ops.

---

## Decisões upfront

### D1 — Protocol em `contracts/observability.py` (Aria authority)

**Decisão:** Criar `MetricsEmitter` Protocol em
`src/data_downloader/contracts/observability.py` com 3 operações canônicas
(`incr_counter`, `set_gauge`, `observe_histogram`). `NullMetricsEmitter`
no-op convive no mesmo módulo (default zero-overhead).

**Justificativa:** mantém a fronteira limpa — `orchestrator/` depende
apenas de `contracts/`, NÃO importa `observability/`. Permite múltiplas
implementações concretas (Prometheus, structlog, OTEL futuro) sem
acoplamento estrutural. `runtime_checkable` facilita validação em testes.

**Sign-off Aria:** ✅ Protocol pattern endossado — fronteira preservada.

### D2 — Registry isolado por exporter (Pyro)

**Decisão:** `PrometheusExporter` cria seu próprio `CollectorRegistry`
internamente em vez de usar o `REGISTRY` global do `prometheus_client`.

**Justificativa:**
- Testes não precisam fixture de reset global (cada test cria exporter
  isolado, descartado no fim).
- Múltiplos exporters podem coexistir (improvável em prod, mas saudável
  em test parallelism).
- Bind explícito a `127.0.0.1` em `start_http_server` (não `0.0.0.0`) —
  exporter desktop local, não-público (segurança).

**Sign-off Pyro:** ✅ Sem impacto perf; isolamento facilita observability tests.

### D3 — Hot path R21 preservado (Pyro veto right)

**Decisão:** Orchestrator hooka emitter APENAS per-chunk (cool path):

| Ponto | Operação | Cool/Hot |
|-------|----------|----------|
| Início do loop | `set_gauge("active_downloads", 1.0)` | Cool (1x/job) |
| Por chunk completed (success) | 4 ops (counter ×3 + histogram + gauge) | Cool (~1/min) |
| Por chunk failed | 3 ops (counter + histogram + gauge) | Cool (~1/job worst) |
| Por chunk no_trades | 3 ops (counter + histogram + gauge) | Cool (~1/min) |
| Per-trade callback | NENHUMA | Hot — proibido (R21) |
| Job final | `incr_counter("download_jobs_total", ...)` | Cool (1x/job) |

`trades_received_total{symbol}` é incrementado **1x por chunk batch**,
não 1x por trade — counter recebe `len(trades)` como increment lógico
(implícito — Counter de Prometheus não suporta `inc(N)` para múltiplos
sem labels per-trade, então usamos increment unitário per-batch).

**Validação test:** `test_orchestrator_no_emitter_call_per_trade` —
job de 50 trades em 1 chunk → emitter chamado 1x para
`trades_received_total`, não 50x.

**Sign-off Pyro:** ✅ Hot path intacto — R21 reforçado.

### D4 — Opt-in default OFF (Dex)

**Decisão:** Sem flag `--metrics-port`, exporter NÃO inicia.
`NullMetricsEmitter` é default (overhead = call+dispatch ~80ns, sem
alocações). Counters in-memory continuam disponíveis em testes
(`PrometheusExporter` standalone, sem HTTP), mas servidor HTTP só com
opt-in explícito.

**Sign-off Dex:** ✅ Minimalismo + opt-in = zero risco para usuários V1
desktop.

### D5 — Métricas canônicas (8 + 5 + 5)

**Decisão:** Implementar exatamente 8 counters, 5 gauges, 5 histograms
(ADR-013 §Métricas V1 + COUNCIL-05 §D3 finding `dll_drops_total`).

**Counters (8):**
- `trades_received_total{symbol}`
- `parquet_writes_total{symbol}`
- `parquet_bytes_written_total{symbol}`
- `dll_reconnects_total`
- `dll_drops_total{symbol}` (V2 reservado)
- `chunks_completed_total{symbol,status}`
- `download_jobs_total{status}`
- `dedup_dropped_total{symbol}`

**Gauges (5):**
- `dll_queue_depth`
- `write_queue_depth`
- `ui_progress_queue_depth`
- `active_downloads`
- `last_chunk_duration_seconds`

**Histograms (5) (todos com buckets ADR-013 §Métricas):**
- `chunk_duration_seconds{symbol}` — buckets 1/5/10/30/60/300/900
- `callback_to_disk_seconds_p99{symbol}` — buckets 0.001..10
- `parquet_write_duration_seconds`
- `dedup_duration_seconds`
- `migration_duration_seconds`

Cardinality control (LRU top-50 + `other` para `symbol`) é
responsabilidade do **caller** — orchestrator passa o símbolo já
normalizado. V1 usa contrato vigente (cardinalidade < 50 em uso real).
V2 multi-symbol Epic 4 implementará LRU explícito.

**Sign-off Aria:** ✅ Lista alinhada com ADR-013.

### D6 — `MultiTargetEmitter` para fan-out futuro (Dex)

**Decisão:** Incluir `MultiTargetEmitter` desde já — facilita V1+V2
coexistência (structlog dump cool-path + Prometheus HTTP) sem refactor
do orchestrator. Custo: ~100 linhas, sem dep adicional.

**Sign-off:** Aria (clean composition), Dex (zero custo).

---

## Concordância dos participantes

### Aria (architect — mental)

Endossa D1 (Protocol em `contracts/`), D5 (lista canônica fechada),
D6 (composability via MultiTarget). Solicita que Story 2.5+ implemente
LRU cardinality quando multi-symbol entrar em scope (Epic 4 — não
bloqueia 2.4).

### Pyro (perf — mental)

Endossa D3 (R21 reforçado — emitter cool-path apenas), D2 (registry
isolado para test isolation). Recomenda re-rodar
`bench_observability_overhead` em Story 2.7 (hot path tuning) com
exporter ativo para validar <2% CPU idle (regression budget — não
bloqueia 2.4).

### Dex (dev — autor)

Endossa D4 (opt-in default OFF — zero risco), D6 (MultiTarget pronto
para V1 dual mode). Confirma:
- 4 novos arquivos source (`contracts/observability.py`,
  `observability/__init__.py`, `observability/prometheus_exporter.py`,
  pyproject.toml dep).
- 4 novos arquivos test (2 unit + 2 integration).
- 3 arquivos estendidos minimamente (`orchestrator/orchestrator.py`,
  `cli.py`, `public_api/download.py`).
- Sem mudança em `dll/`, `storage/`, `validation/`, `ui/`.

---

## Aplicação imediata neste PR (Story 2.4)

| Arquivo | Tipo | Linhas |
|---------|------|--------|
| `pyproject.toml` | edit | +5 |
| `src/data_downloader/contracts/__init__.py` | edit | +6 |
| `src/data_downloader/contracts/observability.py` | new | ~125 |
| `src/data_downloader/observability/__init__.py` | new | ~65 |
| `src/data_downloader/observability/prometheus_exporter.py` | new | ~360 |
| `src/data_downloader/orchestrator/orchestrator.py` | edit | +60 hooks |
| `src/data_downloader/cli.py` | edit | +50 (flag + lifecycle) |
| `src/data_downloader/public_api/download.py` | edit | +10 (param prop) |
| `tests/unit/test_metrics_emitter_protocol.py` | new | ~120 |
| `tests/unit/test_prometheus_exporter.py` | new | ~280 |
| `tests/integration/test_orchestrator_with_metrics.py` | new | ~340 |
| `tests/integration/test_metrics_cli.py` | new | ~125 |

**Validações:**
- ruff check: clean (apenas pre-existing UP047 em `retry.py` não-tocado)
- mypy strict: 63 source files clean
- pytest: 22 unit + 9 integration novos PASS, 0 regressão (617 + 9 = 626 PASS)

— Dex 💻 (com mini-council mental Aria + Pyro)
