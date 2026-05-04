# ADR-010 — Logging strategy: structlog + contextvars + redaction + hot-path rules

**Status:** accepted (implemented in Story 2.9)
**Aceito em:** 2026-05-03 — Aria
**Implementado em:** 2026-05-04 — Story 2.9 (Dex+Aria+Pyro — COUNCIL-19)
**Data:** 2026-05-03
**Última emenda:** 2026-05-04 — implementação V1 + COUNCIL-19 sign-off
**Autor:** 🏛️ Aria
**Consultados:** ⚡ Pyro, 🧪 Quinn, 🎨 Uma
**Related:** ADR-005 (thread model), ADR-013 (observability), MANIFEST §R21 (nova lei), PLAN_REVIEW H22, L2

---

## Implementation Status (Amendment 2026-05-04)

V1 implementado em `src/data_downloader/observability/logging_config.py`
(Story 2.9 / COUNCIL-19). Componentes entregues:

- `configure_logging(level, json_output, redact)` + alias `setup_logging(level, format, redact_secrets)`.
- `bind_context()` / `clear_context()` / `unbind_context()` / `bound_context()` CM.
- `redact_secrets()` recursivo (substring match case-insensitive + allow-list).
- `copy_context_to_thread()` para propagation cross-thread (ADR-005).
- CLI flag `--log-level` / `--log-format` global (`@app.callback`) + env vars
  `DATA_DOWNLOADER_LOG_LEVEL` / `DATA_DOWNLOADER_LOG_FORMAT`.
- Heurística TTY default (console se interactive, json se pipe).
- Integrado em: `orchestrator.run` (job_id/correlation_id/symbol/exchange),
  `_process_chunk` (chunk_id placeholder), `download_chunk` (chunk_id real
  uuid), `IngestorThread`/`ProgressMonitor` (cross-thread propagation),
  `public_api/download.py` worker thread.

Testes: 21 setup unit + 53 redaction unit (incl. 100-example Hypothesis
property) + 4 cross-thread integration = 78 testes PASS.

**Item deferred V2:** `redact_userprofile` processor (mascara
`%USERPROFILE%` em tracebacks) — não-crítico V1; Quinn escala se aparecer
em audit forense.

---

## Contexto

Squad precisa de logging estruturado para:
- **Debug** — reproduzir bug a partir de log de campo.
- **Auditoria** — INV-12 (fim de chunk = filas vazias + commit) auditável.
- **Telemetria** — Pyro extrai métricas de log (latências, throughput).
- **UI** — log view (Felix/Uma) consome eventos.
- **Forense** — "o que aconteceu antes do crash?" (release V1).

Restrições:
- **Hot path proibido** (lei R21 nova) — `Trade*Callback` recebe centenas a milhares de trades/segundo. Logging síncrono síncrono no callback: 50-150% de 1 core gasto só formatando JSON (medido por Pyro em projetos similares).
- **Credenciais (NL_USERNAME, NL_PASSWORD, NL_KEY)** não podem aparecer em log.
- **Filesystem paths** podem expor PII (nome de usuário Windows).
- **Multi-thread** (ADR-005) — IDs precisam estar em contexto, não em string format.
- **PySide6** — UI consome events via signal; backend gera structured records.

---

## Opções Consideradas

### Opção A — `structlog` + JSON renderer + contextvars + hot-path rules

```python
import structlog
from contextvars import ContextVar

# Bound em entry point de cada thread/job
job_id_var: ContextVar[str] = ContextVar('job_id', default='-')
chunk_id_var: ContextVar[str] = ContextVar('chunk_id', default='-')
symbol_var: ContextVar[str] = ContextVar('symbol', default='-')

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        add_thread_name,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt='iso', utc=True),
        redact_credentials,            # custom processor
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(),  # production
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    cache_logger_on_first_use=True,
)
```

### Opção B — `loguru`

- API mais simples, mas menos contextvars-aware.
- Mais difícil customizar processors.
- Comunidade menor; menos integração com OTEL.

### Opção C — stdlib `logging` + `JSONFormatter` custom

- Familiar; sem dep nova.
- Sem contextvars nativo (precisa middleware).
- Performance pior em hot path (formatação eager).

### Opção D — Sem logging estruturado (printf-style)

- Trivial.
- Inviável para auditoria, forense, telemetria.

---

## Análise

| Critério | A (structlog) | B (loguru) | C (stdlib) | D (printf) |
|---------|---------------|------------|-----------|-----------|
| Structured (JSON) nativo | ✅ | ✅ | médio | ❌ |
| contextvars suporte | ✅ nativo | parcial | manual | ❌ |
| Hot-path safe (lazy eval) | ✅ (processor-pipeline) | ❌ | ❌ | ✅ |
| Redaction custom | ✅ (processor) | médio | ✅ | ❌ |
| Console human-readable em dev | ✅ (ConsoleRenderer) | ✅ | médio | ✅ |
| Thread-safe | ✅ | ✅ | ✅ | depende |
| Maturidade | alta | alta | máxima | n/a |
| Community + docs | boa | boa | máxima | n/a |
| Integration OTEL futuro | ✅ | parcial | ✅ | ❌ |

**Pontos críticos:**

- **Opção D** falha objetivos básicos.
- **Opção C** funciona mas requer muito código boilerplate; sem perf-win em hot path.
- **Opção B** fica atrás de A em contextvars + processor pipeline customizável (que precisamos para redaction).
- **Opção A** é o estado da arte para Python structured logging com hot-path discipline. **Escolhida.**

---

## Decisão

**Opção A — `structlog` + JSON renderer (prod) / Console renderer (dev) + contextvars + hot-path rules.**

### Configuração

#### `src/data_downloader/logging.py`

```python
"""Logging configuration. Importar uma vez no entry point."""
import logging
import os
import sys
from contextvars import ContextVar
import structlog

# === ContextVars (thread-safe, async-safe) ===
job_id_var: ContextVar[str] = ContextVar('job_id', default='-')
chunk_id_var: ContextVar[str] = ContextVar('chunk_id', default='-')
symbol_var: ContextVar[str] = ContextVar('symbol', default='-')


# === Custom processor: redação de credenciais ===
SENSITIVE_KEYS = frozenset({
    'password', 'key', 'token', 'secret', 'api_key',
    'nl_password', 'nl_key', 'authorization',
})

def redact_credentials(_logger, _method_name, event_dict):
    """Substitui valores de chaves sensíveis por '***REDACTED***'."""
    for k in list(event_dict.keys()):
        if k.lower() in SENSITIVE_KEYS:
            event_dict[k] = '***REDACTED***'
    return event_dict


def add_thread_name(_logger, _method_name, event_dict):
    import threading
    event_dict['thread'] = threading.current_thread().name
    return event_dict


def configure_logging(*, level: str = 'INFO', console: bool = False) -> None:
    """
    Configura structlog. Chamar uma vez por processo.

    Args:
        level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
        console: True em dev (renderer humano colorido); False em prod (JSON).
    """
    timestamper = structlog.processors.TimeStamper(fmt='iso', utc=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        add_thread_name,
        structlog.processors.add_log_level,
        timestamper,
        redact_credentials,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.dict_tracebacks,
    ]

    if console:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """Helper canônico — todo módulo usa este."""
    return structlog.get_logger(name)
```

### Padrão de uso

#### Início de job (orchestrator)

```python
log = get_logger(__name__)

def execute_download(symbol: str, ...):
    job_id = uuid.uuid4().hex[:12]
    job_id_var.set(job_id)
    symbol_var.set(symbol)

    log.info('download.start', symbol=symbol, start=start.isoformat(), end=end.isoformat())
    try:
        ...
    finally:
        log.info('download.finish', trades_count=...)
```

#### Por chunk

```python
def execute_chunk(chunk_idx: int, ...):
    chunk_id_var.set(f'{chunk_idx:04d}')
    log.info('chunk.start', range_start=..., range_end=...)
    ...
    log.info('chunk.finish', trades_count=..., duration_ms=...)
```

Output JSON (prod):
```json
{
  "event": "chunk.finish",
  "level": "info",
  "timestamp": "2026-05-03T14:23:45.123Z",
  "thread": "OrchestratorThread",
  "job_id": "a3f7c2d1e8b4",
  "chunk_id": "0042",
  "symbol": "WDOJ26",
  "trades_count": 18234,
  "duration_ms": 312
}
```

### Hot-path rules (R21 — NOVA LEI proposta para MANIFEST)

> **R21 — Hot-path logging:** Eventos per-trade NÃO são logados. Eventos per-chunk OK. Métricas (counters/histograms) substituem logs em hot path.

#### O que **NÃO** logar (hot path)

- Cada `TradeCallback` invocation (centenas-milhares/seg).
- Cada `put_nowait` em fila.
- Cada item processado por IngestorThread.
- Cada flush de batch parcial.

#### O que logar (eventos, não fluxo)

- Início/fim de chunk (1 evento por chunk).
- Reconexão DLL (esperado raro).
- Erro/warning (sempre).
- Estado de fila (sample a cada 5s, não por put).
- Início/fim de job.

#### Substituto em hot path: counters

```python
# src/data_downloader/observability.py (ADR-013)
trades_received_counter = Counter('trades_received', ['symbol'])

# No callback:
trades_received_counter.labels(symbol=symbol).inc()
# ZERO log call.
```

Counters são `O(1)` increment + lock-free; structlog é `O(n)` em context dict + serialize.

### Redação automática

Lista de chaves sensíveis em `SENSITIVE_KEYS`. Comparação case-insensitive. Aplicada via processor pipeline — desenvolvedor não precisa lembrar.

Exceção: paths de filesystem (`%USERPROFILE%`, `C:\Users\nicolas\...`) — Pyro detectou que `Path` aparece em `dict_tracebacks`. Mitigação adicional:

```python
def redact_userprofile(_logger, _method, event_dict):
    """Substitui home folder por ~/."""
    home = str(Path.home())
    for k, v in event_dict.items():
        if isinstance(v, str) and home in v:
            event_dict[k] = v.replace(home, '~')
    return event_dict
```

### Configuração runtime

| Env var | Default | Efeito |
|---------|---------|--------|
| `DATA_DOWNLOADER_LOG_LEVEL` | `INFO` | Nível mínimo |
| `DATA_DOWNLOADER_LOG_CONSOLE` | `0` | `1` = console renderer (dev) |
| `DATA_DOWNLOADER_LOG_FILE` | (empty) | Path opcional para tee em arquivo |

CLI flags:
- `--debug` → `LOG_LEVEL=DEBUG` + `LOG_CONSOLE=1`
- `--quiet` → `LOG_LEVEL=WARNING`

---

## Consequências

### Positivas
- **Hot-path safe:** R21 evita 50-150% CPU desperdiçado em log.
- **Auditável:** JSON estruturado parsa em jq, Splunk, ELK, Loki, Datadog.
- **Forense:** trace completo de job em arquivo — Quinn/Pyro reproduzem bug.
- **contextvars:** correlation_id (= job_id) propaga sem passar manual.
- **Redação automática:** secrets nunca vazam em log.
- **Dev UX:** console renderer colorido em dev; JSON em prod.
- **Future-proof:** structlog tem adaptador OTEL para o dia que precisarmos exportar traces.

### Negativas
- **Disciplina exigida:** dev tem que lembrar R21 (hot path). Quinn tem checklist em `*qa-gate`.
- **Dep transversal:** `structlog` adicionada (autorizada via este ADR).
- **Performance vs metric**: counters de ADR-013 substituem logs em hot path — se ADR-013 atrasar, hot-path fica sem visibilidade. Mitigação: ADR-013 inclui counters mínimos como pré-requisito de Story 1.2.

### Neutras
- ConsoleRenderer em dev é "bonito mas verboso" — Uma valida formato em Story 1.7.

---

## Validações requeridas

- [ ] Pyro bench: `bench_callback_to_disk` com R21 respeitado: <100ms p99 (Story 2.2)
- [ ] Pyro bench: comparar com R21 violado (logging per-trade) — esperado: 5-10x pior, prova R21
- [ ] Quinn checklist em `*qa-gate`: nenhum `log.*` em corpo de `Trade*Callback` (Story 1.2 + 1.3)
- [x] Quinn property test: redaction processor remove valores de chaves sensíveis (Story 2.9 / COUNCIL-19 — `tests/unit/test_logging_redaction.py::test_property_redaction_complete_for_sensitive_keys` 100 examples)
- [ ] Aria amenda MANIFEST.md adicionando R21 (após Morgan validar)
- [ ] Uma valida console renderer em dev (Story 1.7b)
- [ ] Documentação em `docs/dev/LOGGING.md` (Dex — Story 2.9 Task 7.1 deferred — TODO)
