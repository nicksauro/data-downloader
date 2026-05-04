# ADR-013 — Runtime observability: counters, gauges, histograms

**Status:** accepted (V1 + V2 implemented)
**Aceito em:** 2026-05-03 — Aria
**V2 implementada:** 2026-05-04 — Story 2.4 (Dex + mini-council Aria/Pyro — COUNCIL-15)
**Data:** 2026-05-03 (criação) / 2026-05-04 (amendment V2)
**Autor:** 🏛️ Aria
**Consultados:** ⚡ Pyro, 🧪 Quinn, 💻 Dex (V2)
**Related:** ADR-005 (thread model), ADR-010 (logging — R21), MANIFEST §R21,
PLAN_REVIEW H22, COUNCIL-05 §D3, COUNCIL-15 (V2 design)

---

## Contexto

Sem métricas:
- "Está rodando ou travado?" — só dá pra saber por log de chunk a cada N segundos.
- "Qual é o gargalo?" — Pyro precisa instrumentar manualmente toda vez.
- "Reconnects acontecendo?" — só com grep no log.
- "Disco lento?" — só percebido quando fila enche.

ADR-010 estabelece R21: **NÃO logar per-trade**. Substituto: **counters** que incrementam em hot path com custo `O(1)` lock-free.

Restrições:
- **Hot path** (callback) precisa de `O(1)` increment sem lock pesado.
- **V1** não precisa exportar para Prometheus/Grafana — usuário desktop single-process.
- **V2 (multi-symbol Epic 4)** pode exigir Prometheus para agregação cross-process.
- **Memória** — counters não podem crescer ilimitadamente (cardinality control).

---

## Opções Consideradas

### Opção A — `prometheus_client` (lib oficial Prometheus) — counters in-process + opcional exporter HTTP

- Maturidade altíssima.
- Counter/Gauge/Histogram thread-safe.
- Increment ~250ns (lock-free).
- Exporter HTTP integra com Prometheus Server (V2).
- Cardinality control via labels.

### Opção B — `opentelemetry-sdk` (OTEL Metrics API)

- Padrão emergente.
- Mais flexível (push e pull).
- Mais complexo: requer setup de provider, reader, exporter.
- Overkill para V1.

### Opção C — Counter custom (`threading.Lock` + dict)

- Zero deps.
- Requer reimplementar histograms (não trivial — needs HDR, percentile estimation).
- Reinventar roda.

### Opção D — Sem métricas (só logs)

- R21 já decidiu não.

---

## Análise

| Critério | A (prometheus_client) | B (OTEL) | C (custom) | D (none) |
|---------|----------------------|----------|-----------|----------|
| Hot-path safe (O(1)) | ✅ | ✅ | depende | n/a |
| Histogram nativo | ✅ | ✅ | reimplementar | ❌ |
| Future export (V2) | trivial | trivial | difícil | n/a |
| Esforço inicial | baixo-médio | médio-alto | médio | n/a |
| Maturidade | alta | crescente | n/a | n/a |
| Dep transversal | sim | sim+ | não | não |

**Pontos críticos:**

- **Opção C** parece simples mas histograma percentile (p99 latência) é matemática não-trivial — usar lib provada.
- **Opção B** vai acabar na frente em 2-3 anos (OTEL é o futuro), mas para V1 desktop single-process é overkill. Migração A→B futura é trivial (mesmas primitives).
- **Opção A** é o padrão da indústria há anos, leve, integra com tudo. **Escolhida.**

---

## Decisão

**Opção A — `prometheus_client` para in-process metrics. V1: stdout JSON via structlog (sample). V2 (Epic 4): exporter HTTP opcional.**

### Métricas V1

#### Counters (monotônico, lock-free)

| Métrica | Labels | Significado |
|---------|--------|-------------|
| `trades_received_total` | `symbol`, `exchange` | Trades recebidos no callback |
| `parquet_writes_total` | `symbol` | Append a Parquet bem-sucedido |
| `parquet_bytes_written_total` | `symbol` | Bytes escritos em Parquet |
| `dll_reconnects_total` | `reason` | Reconexões DLL (esperado raro) |
| `chunks_completed_total` | `symbol`, `status` | Chunks (status: success/failed/cancelled) |
| `errors_total` | `type` | Erros por tipo público (ADR-011) |
| `dedup_dropped_total` | `symbol` | Duplicatas detectadas e descartadas |

#### Gauges (valor instantâneo)

| Métrica | Labels | Significado |
|---------|--------|-------------|
| `queue_depth_dll` | — | Tamanho atual de `dll_queue` (0..10_000) |
| `queue_depth_write` | — | Tamanho atual de `write_queue` (0..5_000) |
| `queue_depth_ui_progress` | — | Tamanho atual de `ui_progress_queue` (0..100) |
| `active_jobs` | — | Jobs em execução |
| `dll_state` | — | Estado DLL (numérico — mapping em log) |
| `partition_count` | `symbol` | Partições escritas para o símbolo |

#### Histograms

| Métrica | Buckets (s) | Significado |
|---------|-------------|-------------|
| `chunk_duration_seconds` | 0.1, 0.5, 1, 5, 10, 30, 60, 300, 1800 | Tempo de chunk completo |
| `callback_to_disk_seconds` | 0.001, 0.01, 0.05, 0.1, 0.5, 1, 5 | Latência callback → flush em disco |
| `parquet_write_seconds` | 0.001, 0.01, 0.1, 1, 10 | Tempo de write batch |
| `dll_request_seconds` | 0.1, 1, 10, 60, 600, 1800 | Tempo de `GetHistoryTrades` chamada |
| `sqlite_commit_seconds` | 0.0001, 0.001, 0.01, 0.1, 1 | Tempo de commit SQLite |

#### Cardinality control

- `symbol` é alta cardinalidade (~500 contratos vivos). Mitigação: rotacionar — limitar a 50 mais ativos via LRU; restantes vão para `symbol="other"`.
- Outros labels têm cardinalidade baixa (status, type, reason).

### Implementação

```python
# src/data_downloader/observability.py

from prometheus_client import Counter, Gauge, Histogram, REGISTRY


# === Counters ===

trades_received_total = Counter(
    'data_downloader_trades_received_total',
    'Total trades received from DLL callbacks',
    labelnames=['symbol', 'exchange'],
)

parquet_writes_total = Counter(
    'data_downloader_parquet_writes_total',
    'Total Parquet append operations',
    labelnames=['symbol'],
)

parquet_bytes_written_total = Counter(
    'data_downloader_parquet_bytes_written_total',
    'Total bytes written to Parquet',
    labelnames=['symbol'],
)

dll_reconnects_total = Counter(
    'data_downloader_dll_reconnects_total',
    'Total DLL reconnections',
    labelnames=['reason'],
)

chunks_completed_total = Counter(
    'data_downloader_chunks_completed_total',
    'Total chunks completed',
    labelnames=['symbol', 'status'],
)

errors_total = Counter(
    'data_downloader_errors_total',
    'Total errors by public type (ADR-011)',
    labelnames=['type'],
)

dedup_dropped_total = Counter(
    'data_downloader_dedup_dropped_total',
    'Total duplicate trades detected and dropped',
    labelnames=['symbol'],
)


# === Gauges ===

queue_depth_dll = Gauge(
    'data_downloader_queue_depth_dll',
    'Current depth of DLL queue (0..10_000)',
)

queue_depth_write = Gauge(
    'data_downloader_queue_depth_write',
    'Current depth of write queue (0..5_000)',
)

queue_depth_ui_progress = Gauge(
    'data_downloader_queue_depth_ui_progress',
    'Current depth of UI progress queue (0..100)',
)

active_jobs = Gauge(
    'data_downloader_active_jobs',
    'Number of jobs currently running',
)

dll_state = Gauge(
    'data_downloader_dll_state',
    'Current DLL state (numeric; see docs/dll/QUIRKS.md)',
)


# === Histograms ===

chunk_duration_seconds = Histogram(
    'data_downloader_chunk_duration_seconds',
    'Time to complete one chunk',
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300, 1800],
    labelnames=['symbol'],
)

callback_to_disk_seconds = Histogram(
    'data_downloader_callback_to_disk_seconds',
    'Latency from DLL callback to disk flush',
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1, 5],
    labelnames=['symbol'],
)

parquet_write_seconds = Histogram(
    'data_downloader_parquet_write_seconds',
    'Time to write a Parquet batch',
    buckets=[0.001, 0.01, 0.1, 1, 10],
    labelnames=['symbol'],
)

dll_request_seconds = Histogram(
    'data_downloader_dll_request_seconds',
    'Time for GetHistoryTrades request',
    buckets=[0.1, 1, 10, 60, 600, 1800],
)

sqlite_commit_seconds = Histogram(
    'data_downloader_sqlite_commit_seconds',
    'Time to commit SQLite transaction',
    buckets=[0.0001, 0.001, 0.01, 0.1, 1],
)
```

### Padrão de uso

#### Hot path (callback DLL)

```python
def history_trade_callback(...):
    # Increment counter — O(1), lock-free
    trades_received_total.labels(symbol=symbol, exchange=exchange).inc()
    # Put in queue
    dll_queue.put_nowait(payload)
    queue_depth_dll.set(dll_queue.qsize())
    # NUNCA log aqui (R21)
```

#### Per-chunk

```python
with chunk_duration_seconds.labels(symbol=symbol).time():
    download_chunk(...)
chunks_completed_total.labels(symbol=symbol, status='success').inc()
```

#### Per-error (ADR-011)

```python
try:
    ...
except DownloadError as e:
    errors_total.labels(type=type(e).__name__).inc()
    raise
```

### Export V1: stdout JSON via structlog (sample)

V1 não exporta HTTP. Em vez disso:

```python
# src/data_downloader/observability_dump.py

import json
from prometheus_client import REGISTRY
from structlog import get_logger

log = get_logger(__name__)

def dump_metrics() -> None:
    """Sample current metrics to log. Chamar a cada ~5s ou em fim de chunk."""
    snapshot = {
        sample.name: sample.value
        for metric in REGISTRY.collect()
        for sample in metric.samples
        if sample.name.startswith('data_downloader_')
    }
    log.info('metrics.snapshot', metrics=snapshot)
```

Trigger:
- Por chunk: `dump_metrics()` no `chunks_completed_total.inc()`.
- Por timer: thread daemon a cada 5s.
- Por CLI: `data-downloader metrics` (consulta single-process via REGISTRY... ou via SQLite tmp file se multi-process — Epic 4).

### Export V2 (Epic 4 — multi-symbol): exporter HTTP

```python
from prometheus_client import start_http_server

start_http_server(port=9090)   # /metrics endpoint
```

Quando multi-symbol = N processos, cada processo expõe `/metrics`. Prometheus Server (opcional, dev avançado) faz scrape e agrega.

V1 desktop single-user **não precisa**. Documentar no ADR como "deferred to Epic 4".

#### Amendment 2026-05-04 — V2 antecipada para Epic 2 (Story 2.4)

**Decisão:** V2 implementada via `prometheus_client` na Story 2.4
(antecipada de Epic 4 para Epic 2). Motivação: Story 1.7b release
readiness exige métricas live para validar smoke MVP em produção.

**Arquitetura:**
- `MetricsEmitter` Protocol em `src/data_downloader/contracts/observability.py`
  (Aria fronteira) — interface mínima `incr_counter`/`set_gauge`/`observe_histogram`.
- `PrometheusExporter` em `src/data_downloader/observability/prometheus_exporter.py`
  implementa o Protocol + serve HTTP `/metrics`.
- Orchestrator aceita `metrics_emitter: MetricsEmitter | None` (default
  `NullMetricsEmitter` — zero overhead opt-in).
- CLI `download --metrics-port 9090` ativa exporter (lifecycle gerenciado
  por `cli.py` — start antes do download, stop em `finally`).

**Métricas implementadas (8 + 5 + 5):**
- Counters: `trades_received_total{symbol}`, `parquet_writes_total{symbol}`,
  `parquet_bytes_written_total{symbol}`, `dll_reconnects_total`,
  `dll_drops_total{symbol}`, `chunks_completed_total{symbol,status}`,
  `download_jobs_total{status}`, `dedup_dropped_total{symbol}`.
- Gauges: `dll_queue_depth`, `write_queue_depth`, `ui_progress_queue_depth`,
  `active_downloads`, `last_chunk_duration_seconds`.
- Histograms: `chunk_duration_seconds{symbol}`,
  `callback_to_disk_seconds_p99{symbol}`, `parquet_write_duration_seconds`,
  `dedup_duration_seconds`, `migration_duration_seconds`.

**R21 reforçado:** orchestrator hooka emitter APENAS per-chunk (cool path).
Test `test_orchestrator_no_emitter_call_per_trade` valida que job de N
trades em 1 chunk gera 1 chamada (não N).

**Cardinality control:** símbolo é label de cardinalidade média (~50
ativos vivos). LRU explícito (top-50 + `other`) deferred para Epic 4
(multi-symbol — cardinality real > 50).

**Decisões detalhadas:** `docs/decisions/COUNCIL-15-prometheus-exporter-v2.md`.

---

## Consequências

### Positivas
- **Hot-path safe** (O(1) increment, lock-free).
- **R21 cumprido** — counters substituem logs em callback.
- **Pyro instrumentado:** baseline e regression budgets têm dados objetivos.
- **Forense:** snapshot por chunk dá visão histórica.
- **Future-proof:** V2 vira HTTP exporter sem refator.
- **Cardinality controlada:** símbolos rotacionados por LRU.

### Negativas
- **Dep nova:** `prometheus_client`. Autorizada via este ADR.
- **Disciplina:** dev tem que lembrar de instrumentar (Quinn audita em `*qa-gate`).
- **REGISTRY global:** singleton — testes precisam reset (`REGISTRY.unregister`). Quinn provê fixture.

### Neutras
- Sem dashboard V1 — log basta.
- V2 abre porta para Grafana se usuário avançado quiser.

---

## Validações requeridas

- [ ] Pyro implementa `bench_observability_overhead` — verifica increment <500ns (Story 1.4.5)
- [ ] Quinn unit tests: cada counter/gauge/histogram tem teste de increment + snapshot (Story 1.7b)
- [ ] Quinn fixture: REGISTRY reset entre testes (Story 1.1 amendment)
- [ ] Aria valida lista de métricas (este ADR)
- [ ] Documentação em `docs/dev/OBSERVABILITY.md` (Pyro)
- [ ] Story 1.7b adiciona `data-downloader metrics` CLI command (Dex+Uma microcopy)
