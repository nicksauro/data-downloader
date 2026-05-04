# COUNCIL-19 — Logging Strategy Impl (Story 2.9 / ADR-010)

**Data:** 2026-05-04
**Convocação:** Dex (dev) — modo autônomo Story 2.9 (Logging strategy
ADR-010 implementada — contextvars, redaction, JSON formatter, cross-thread
propagation)
**Participantes mentais:** Aria (architect — ADR-010 authority), Pyro
(perf — R21 hot path discipline), Dex (impl — integração mínima)
**Contexto:** Story 2.9 fecha o gap entre ADR-010 (decision aceita
2026-05-03) e a implementação real. Estado anterior: `structlog.get_logger`
usado em vários módulos (orchestrator, dll/wrapper, download_primitive),
mas SEM contextvars sistemáticos, SEM redaction processor, SEM JSON
renderer fixo. Esta story instala o pipeline canônico + integra nos
entry points existentes.

---

## Decisões

### D1 — Módulo único `observability/logging_config.py` (Dex)

**Decisão:** Criar `src/data_downloader/observability/logging_config.py`
(~530 linhas) consolidando: pipeline structlog (`configure_logging`),
helpers de contextvars (`bind_context` / `clear_context` / `unbind_context`
/ `bound_context` CM), redaction processor (`redact_secrets` recursivo),
cross-thread propagation (`copy_context_to_thread`), e factory canônico
(`get_logger`). Re-exportado via `observability/__init__.py`.

**Justificativa:**

- Story AC1 nomeia `logging_config.py` (não `logging.py` — evita conflito
  com `import logging` builtin). API tem 2 entry points: `configure_logging`
  (kwargs canônicos do ADR-010) e `setup_logging` (alias com
  `format="json|console"` mais legível em CLI).
- Co-localizado com `prometheus_exporter.py` (já em `observability/`) —
  ambos são telemetry plane (logs + métricas), evita criar novo subpackage.
- Imports do orchestrator/download_primitive ficam claros:
  `from data_downloader.observability.logging_config import bind_context`.

**Sign-off Dex:** ✅ Module layout limpo, sem dependência transversal nova.

### D2 — Substring matching case-insensitive p/ redaction (Aria)

**Decisão:** `_is_sensitive_key` usa **substring match** case-insensitive
contra `SENSITIVE_KEY_SUBSTRINGS` (frozenset com `pass`, `password`,
`secret`, `token`, `key`, `auth`, `credential`, `api_key`, `apikey`,
`authorization`). Allow-list explícito (`key_redacted`,
`credential_redacted`, `password_redacted`) preserva strings já marcadas
como redacted pelo dev (DLL wrapper usa `key_redacted="***"`).

**Justificativa:**

- ADR-010 §SENSITIVE_KEYS lista exatamente 9 keys. Substring match cobre
  variantes (`PROFITDLL_KEY`, `nl_password`, `user_pass`, `PROFIT_PASS`)
  sem precisar enumerar cada combinação. Heurística falsa-positiva
  controlada via allow-list.
- `nl_username` é um caso interessante: a heurística ANTIGA (substring
  `user`) o pegaria, mas como `user` NÃO está em `SENSITIVE_KEY_SUBSTRINGS`,
  username **não é redactado** (correto — username não é secret per ADR-010
  §Contexto). Property test (Hypothesis 100 examples) valida que keys
  sensíveis são SEMPRE redactadas e keys safe SEMPRE preservadas.
- Defesa em profundidade: `bind_context(...)` também roda redaction nos
  kwargs antes do bind — mesmo que dev passe um campo sensível por
  engano (e.g. ``bind_context(password=<value>)``), o contextvar já
  entra redactado.

**Sign-off Aria:** ✅ Heurística + allow-list cobrem ADR-010 §SENSITIVE_KEYS
sem regressão; property test garante INV-credenciais.

### D3 — Cross-thread via `contextvars.copy_context()` (Aria + Pyro)

**Decisão:** Threads workers (IngestorThread, ProgressMonitor,
public_api download worker) capturam `contextvars.copy_context()` no
`__init__` (parent thread) e executam `run()` via `ctx.run(self._run_inner)`.
Helper público `copy_context_to_thread(target)` decora callables para uso
genérico (e.g. QThread em Story 3.x).

**Justificativa:**

- Python `threading.Thread` NÃO copia contextvars automaticamente
  (diferente de `asyncio.Task`). Sem propagação explícita,
  `bind_context(job_id=...)` no orchestrator NÃO aparece em logs do
  IngestorThread → quebra correlação cross-thread, quebra debug forense.
- `copy_context()` é zero-overhead se nenhum contextvar foi bound (snapshot
  vazio). Em produção, snapshot tem 4-5 vars (job_id, correlation_id,
  symbol, exchange, opcionalmente chunk_id) — overhead negligível.
- Pyro: copy_context() é chamado UMA VEZ no `__init__` (cool path —
  per-chunk). NÃO entra em hot path. R21 preservado.

**Sign-off Aria:** ✅ Padrão consistente com ADR-005 thread model.
**Sign-off Pyro:** ✅ Zero overhead em hot path; R21 preservado.

### D4 — Bind por escopo (job + chunk separados) (Dex)

**Decisão:** `Orchestrator.run()` bind `{job_id, correlation_id, symbol,
exchange}` no início + `clear_context()` no `finally` global.
`_process_chunk()` bind `chunk_id` (placeholder range-based) +
`unbind_context("chunk_id")` no `finally` (preserva job_id/symbol entre
chunks). `download_chunk()` re-bind `chunk_id` REAL (uuid hex) que
aparece em downstream logs do IngestorThread/ProgressMonitor (snapshot
do parent ctx capturado APÓS o re-bind).

**Justificativa:**

- Lifecycle limpo: ao final do job, `clear_context` zera tudo (evita
  contaminação cross-job no mesmo thread).
- Per-chunk: `unbind_context("chunk_id")` evita que o chunk_id do
  chunk N apareça em logs de erro do chunk N+1 (caso de retry após
  falha intermediária).
- Defesa em profundidade: mesmo se logging_config NÃO foi inicializado
  (e.g. teste integração que esquece setup), `bind_context` é
  silencioso/no-op (`structlog.contextvars.bind_contextvars` aceita
  qualquer config).

**Sign-off Dex:** ✅ Integração mínima sem refactor de signature.

### D5 — CLI flag global + heurística TTY (Dex + Uma indireta)

**Decisão:** `cli.py` instala `@app.callback()` global com flags
`--log-level` e `--log-format`. Default format = heurística TTY
(`sys.stderr.isatty() → "console"` else `"json"`). Env vars
`DATA_DOWNLOADER_LOG_LEVEL` / `DATA_DOWNLOADER_LOG_FORMAT` overridable.
Precedência: CLI flag > env var > default.

**Justificativa:**

- AC5 da Story 2.9 exige CLI flags + env vars. `app.callback()` roda
  ANTES de qualquer subcomando — guarantee single configure_logging call.
- Heurística TTY: dev local (interactive shell) vê console renderer
  colorido; prod (pipe → systemd-journal, Docker logs) vê JSON
  parseável por Loki/ELK/CloudWatch. Zero config necessária.
- Uma microcopy review (AC7.3): help strings das flags são canônicas
  (não vão a microcopy_loader — flags CLI ficam estáveis em PT-BR
  inline; pequeno volume não justifica catálogo).

**Sign-off Dex:** ✅ Lifecycle correto; heurística cross-platform.

---

## R21 — Hot Path verificação (Pyro)

| Check | Status | Notas |
|-------|--------|-------|
| `configure_logging` chamado UMA vez por processo | ✅ | `cli.py @app.callback()` |
| Redaction processor não roda per-trade | ✅ | Roda apenas em log calls (cool path: per-chunk, per-job) |
| `bind_context` chamado per-job + per-chunk | ✅ | Não chamado em `TradeCallback`/`HistoryTradeCallback` |
| `copy_context()` snapshot capturado UMA vez por thread | ✅ | No `__init__` da thread, antes do `start()` |
| `redact_secrets` profundidade O(n) sobre event_dict | ✅ | event_dict tem ~6-12 keys; n trivial |

**Pyro sign-off:** ✅ Pipeline structlog + redaction processor permanecem
fora do hot path. R21 preservado integralmente.

---

## Aria — ADR-010 conformance check

| ADR-010 §Decisão item | Implementação | Conforme? |
|----------------------|---------------|-----------|
| structlog + JSON renderer | `configure_logging(json_output=True)` | ✅ |
| ConsoleRenderer dev mode | `configure_logging(json_output=False)` | ✅ |
| contextvars (job_id/chunk_id/symbol/correlation_id) | `bind_context()` helpers | ✅ (estendido c/ `exchange`) |
| Custom processor `redact_credentials` | `_redact_secrets_processor` | ✅ (recursivo + nested dicts) |
| `add_thread_name` processor | `_add_thread_name` | ✅ |
| Pipeline shared_processors + renderer | Conforme ADR-010 §Configuração | ✅ |
| `cache_logger_on_first_use=True` | Sim | ✅ |
| Logger factory `PrintLoggerFactory(file=sys.stderr)` | Sim | ✅ |
| Env vars `DATA_DOWNLOADER_LOG_*` | `--log-level`/`--log-format` + env helpers | ✅ |
| ADR-010 §`redact_userprofile` (PII home folder) | **Deferred V2** | ⏳ Documentar em `docs/dev/LOGGING.md` |

**Aria sign-off:** ✅ ADR-010 implementado em V1 conforme decisão. Item
opcional `redact_userprofile` (PII home folder em tracebacks) deferred
para V2 — documentar em `docs/dev/LOGGING.md` como TODO Quinn pode
escalar se aparecer em audit forense. Bump amendment 2026-05-04 no
ADR-010.

---

## Trade-offs aceitos

1. **`bound_context` CM faz unbind apenas das chaves bound nele** — não
   restaura valor anterior se a mesma chave estava bound em escopo
   externo. Workaround: usar nomes únicos por escopo (e.g.
   `chunk_id` é unbound após `_process_chunk`, e o orchestrator NÃO
   tem chunk_id bound no escopo externo). Em V2 podemos usar
   `unbind_contextvars` com tokens armazenados (mais complexo, deferido).
2. **`structlog` pipeline reset entre testes** — cada teste deve
   re-`configure_logging` (fixture autouse `_reset_structlog_after_test`
   nos test files). Sem isso, o `cache_logger_on_first_use=True` pode
   fazer testes anteriores afetarem next.
3. **No hot path enforcement automático** — Quinn audita via grep em
   `*qa-gate` (HOT_PATH_RULES.md §Auditoria). Linter custom seria ideal
   mas é Story futura.

---

## Sign-off final

- **Aria:** ✅ ADR-010 implementação completa em V1; deferred items
  documentados; bump amendment marcado.
- **Pyro:** ✅ R21 preservado; per-chunk only em cool path; zero
  per-trade impact.
- **Dex:** ✅ Integração mínima nos entry points existentes (orchestrator,
  download_primitive, public_api/download.py, cli.py); 78 testes pass
  (21 setup + 53 redaction + 4 cross-thread).
