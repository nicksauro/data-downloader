# HOT_PATH_RULES.md — Política de logging e overhead em hot path

**Status:** R21 nova (proposta — finding H22 do plan review).
**Autoridade:** Pyro (perf) propõe; Aria (architect) ratifica via ADR-010.
**Validação:** `bench_log_overhead` mede CPU% e wall-time em hot path.

---

## Definição

**Hot path** no data-downloader é qualquer código executado **per-trade** ou **per-callback** quando a vazão estável é >= 10k eventos/segundo. Isso inclui:

| Path | Vazão típica | Hot? |
|------|-------------|------|
| `TradeCallback` (DLL → ConnectorThread) | 100-4000 trades/s | ✅ HOT |
| `IngestorThread.on_trade()` | 100-4000 trades/s | ✅ HOT |
| `WriterThread.append()` | per-batch (1-10/s) | ❌ COOL |
| `Orchestrator.on_chunk_done()` | per-chunk (~1/min) | ❌ COOL |
| `Catalog.register_partition()` | per-chunk | ❌ COOL |
| `StateCallback` | per-state (raro) | ❌ COOL |
| `ProgressCallback` | per-1% (~100/job) | ❌ COOL |

---

## Regras (R21)

### R21.1 — Hot path NÃO loga per-evento

**PROIBIDO** em hot path:
```python
# RUIM — log per-trade @ 100k/s = 50-150% CPU 1 core
def on_trade(trade):
    logger.debug("trade_received", trade_id=trade.id, price=trade.price)
    queue.put(trade)
```

**OBRIGATÓRIO** em hot path:
```python
# BOM — atomic counter + sampling opcional
trades_received_counter = Counter("trades_received_total")

def on_trade(trade):
    trades_received_counter.inc()
    if _debug_sample_hit(trade.id):  # only if env DATA_DOWNLOADER_DEBUG_SAMPLE > 0
        logger.debug("trade_sampled", trade_id=trade.id, price=trade.price)
    queue.put(trade)
```

### R21.2 — Per-chunk logging é OK (info level)

**PERMITIDO** logar 1 evento por chunk (~1/min):
```python
# OK — 1 log a cada ~500k trades
def on_chunk_done(chunk):
    logger.info("chunk_completed",
                chunk_id=chunk.id,
                n_trades=chunk.count,
                duration_ms=chunk.duration_ms,
                throughput_per_sec=chunk.count / chunk.duration_s)
```

### R21.3 — Per-callback BATCH com sampling 1:N

Para callbacks que são per-batch internamente (ex: `HistoryTradeCallback`
batch-size=1000), permitido logar 1:N onde N = `floor(rate / target_log_rate)`.

Default: `target_log_rate = 10/s` → para callback @ 4kHz, N=400.

```python
# OK — sampling 1:400 garante <= 10 logs/s
def on_history_trade_batch(batch):
    metrics.history_trades_received.inc(len(batch))
    if _sample_hit(_log_sample_state, n=400):
        logger.info("history_batch_received",
                    n_trades=len(batch),
                    first_ts_ns=batch[0].timestamp_ns,
                    last_ts_ns=batch[-1].timestamp_ns)
```

### R21.4 — Métricas agregadas substituem logs per-evento

Toda informação que tentaríamos extrair de logs per-trade DEVE ter contraparte
em métrica agregada (counter, gauge, histogram):

| Antes (log per-trade) | Depois (métrica) |
|----------------------|------------------|
| `logger.debug("trade", trade_id, price)` | `Counter("trades_total")` |
| `logger.warning("dup", trade_id)` | `Counter("trades_duplicate_total")` |
| `logger.error("invalid_price", price)` | `Counter("trades_invalid_total{reason=...}")` |
| `logger.info("queue_depth", n)` | `Gauge("queue_depth").set(n)` |
| `logger.info("write_latency_ms", ms)` | `Histogram("write_latency_ms").observe(ms)` |

Métricas expostas via transporte definido em ADR-013 (TBD: stdout JSON, Prometheus, OpenTelemetry — ver OPEN_QUESTIONS.md Q3).

### R21.5 — Modo debug por sampling (env var)

Para debug ad-hoc em produção sem regressão de perf, usar variável de ambiente:

```
DATA_DOWNLOADER_DEBUG_SAMPLE=0.001   # 0.1% dos trades logados
DATA_DOWNLOADER_DEBUG_SAMPLE=0       # default = OFF (zero overhead)
DATA_DOWNLOADER_DEBUG_SAMPLE=1.0     # 100% (somente em test/dev)
```

Implementação:
```python
import os, random
_DEBUG_SAMPLE = float(os.environ.get("DATA_DOWNLOADER_DEBUG_SAMPLE", "0"))

def _debug_sample_hit(trade_id: int) -> bool:
    if _DEBUG_SAMPLE <= 0:
        return False  # zero overhead branch
    if _DEBUG_SAMPLE >= 1:
        return True
    # Hash-based sampling (determinístico por trade_id, evita random.random() cost)
    return (trade_id * 2654435761) & 0xFFFFFFFF < _DEBUG_SAMPLE * 0xFFFFFFFF
```

`_DEBUG_SAMPLE <= 0` é avaliado primeiro → branch predito → ~1ns overhead em produção.

### R21.6 — Format/Renderer escolhido por perf

Decisão (sujeita a `bench_log_overhead`):
- **JSON renderer** quando log destino é arquivo / agregador (Loki, ELK).
- **TextRenderer** quando log destino é stdout em desenvolvimento.
- **NUNCA** ConsoleRenderer com cores em produção (5-10x slower).

### R21.7 — Lazy evaluation obrigatório

Todo log em hot path DEVE usar lazy/structured args, NUNCA f-string:

```python
# RUIM — f-string avalia mesmo se log filtered
logger.debug(f"trade {trade.id} price={trade.price}")

# BOM — structlog avalia args só se passa filter
logger.debug("trade", trade_id=trade.id, price=trade.price)
```

---

## Validação

`bench_log_overhead` mede:
- CPU% por log strategy × level × format × rate.
- Throughput máximo (eventos/s) que cada combinação suporta sem degradar.

Resultado vai para `BASELINES.md` e atualiza esta política se necessário.

---

## Auditoria

`@qa` valida em PR review:
- Buscar `logger\.(debug|info)` em arquivos hot path → PR rejeitado se per-trade.
- Hot path detectado por: `*Callback`, `IngestorThread`, qualquer função decorada `@hot_path`.

Sugestão Sol/Aria: marcar funções hot path com decorator `@hot_path` + linter custom em pre-commit.

---

## Auditoria mecânica (Story 2.7 / COUNCIL-22)

Implementada em `scripts/audit_hot_path.py` (Pyro). Faz AST scan dos
hot paths registrados e detecta violações vetadas.

### Como rodar

```bash
# CLI direto (relatório humano):
python scripts/audit_hot_path.py

# JSON output (CI / dashboards):
python scripts/audit_hot_path.py --json

# Auditar arquivos extras (pre-commit):
python scripts/audit_hot_path.py --paths src/data_downloader/dll/callbacks.py
```

### Pre-commit hook (opt-in)

Wrapper em `scripts/hooks/check_hot_path.py`. Para ativar:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: check-hot-path
      name: Audit R21 hot-path compliance
      entry: python scripts/hooks/check_hot_path.py
      language: system
      types: [python]
      files: ^src/data_downloader/.*\.py$
```

### Hot path registry autoritativo (Story 2.7)

| Arquivo | Função | Vazão típica | Tipo |
|---------|--------|-------------|------|
| `dll/callbacks.py` | `_history_cb` (closure de `make_history_trade_callback_v2`) | per-trade @ 100-4000/s | HOT |
| `dll/callbacks.py` | `_progress_cb` (closure de `make_progress_callback`) | per-1% @ 100/job | HOT (pequeno) |
| `orchestrator/download_primitive.py` | `_process_trade` (método de `_IngestorThread`) | per-trade @ 100-4000/s | HOT |

Funções **excluídas** (cool path):
- `_trades_to_table` (per-batch, ~1-10/s)
- `register_partition` (per-chunk, ~1/min)
- `_process_progress` (per-1%)

### Violações conhecidas (baseline 2026-05-04)

`scripts/audit_hot_path.py` detecta atualmente **3 violações** em
`download_primitive.py::_process_trade` (linhas 286, 328, 337). Estas
violações são herança da implementação inicial e devem ser endereçadas
em uma Story 2.X dedicada (Pyro+Dex):

1. `log.warning("download.translate_failed", ...)` — substituir por
   `Counter("trades_translate_failed_total")`.
2. `log.info("download.last_packet", ...)` — mover para `_run_inner`
   (cool path; emitido apenas no fim do drain).
3. `log.debug("download.trade_edit", ...)` — substituir por
   `Counter("trades_edit_total")` ou skip se `DEBUG_SAMPLE=0`.

O script reporta exit 1 (FAIL) enquanto essas violações existirem —
NÃO instalar o pre-commit hook como blocking até serem corrigidas.

— Pyro ⚡
