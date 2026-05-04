# COUNCIL-20 — Retry inteligente + Circuit breaker (Story 2.6)

**Data:** 2026-05-03
**Story:** [2.6](../stories/2.6.story.md) — Retry inteligente + circuit breaker
**Participantes:** Nelo (DLL semantics) + Dex (impl) + Aria (boundary)
**Status:** APROVADO

---

## Sumário

Story 2.6 finaliza o item "Retry inteligente" do EPIC-2 escopo IN. Constrói
sobre o `with_retry` mínimo de Story 1.7a (max_attempts=3 fixo, sem
categorização) e estende com:

1. **Taxonomia NL_*** (Nelo authority): cada código mapeado em
   `ErrorCategory{TRANSIENT, AMBIGUOUS, PERMANENT, UNKNOWN}` —
   39 codes catalogados (canônicos + legacy + sentinela).
2. **RetryPolicy dataclass + factories** (Dex impl + Aria boundary):
   imutável, decidida por categoria, suporta override via env var.
3. **CircuitBreaker stateful** (Dex impl + Aria state machine):
   3-state machine (CLOSED/HALF_OPEN/OPEN) com sliding-window deque,
   thread-safe via `threading.Lock`, dependency-free (R10).
4. **Q02-E (99% reconnect) policy formal**: hook progress-aware no
   orchestrator — quirk NÃO conta como falha no breaker porque
   download_primitive já trata via timeout duro (não retorna NL_* error
   code para 99% repeats).

---

## Decisões críticas

### D1 — Categorização NL_* por taxonomia (Nelo)

**Decisão:** Cada código `NL_*` é categorizado em `ErrorCategory` via
tabela imutável `NL_CATEGORY_MAP` em `src/data_downloader/dll/error_taxonomy.py`.

**Categorias canônicas:**

| Categoria | Semântica | Comportamento padrão |
|-----------|-----------|----------------------|
| `TRANSIENT` | Falhas auto-recuperáveis (timeout, queue full, race) | RETRY agressivo |
| `AMBIGUOUS` | Semantics depende do contexto (NL_NOT_FOUND, NL_ASSET_NO_DATA) | RETRY com cap menor |
| `PERMANENT` | Erros lógicos / configuração (license, ticker inválido, args) | NO RETRY (R7 fail fast) |
| `UNKNOWN` | Código novo / não-categorizado | NO RETRY (R7 conservadora) |

**Cobertura:** 39 codes mapeados (NL_OK + 33 canônicos do `profit.h` + 5
legacy do `dll/errors.py` Story 1.2). Cada entry tem justification em
prosa para audit.

**Justificativa Nelo:**
- `NL_INTERNAL_ERROR` (-2147483647): TRANSIENT — geralmente race interna,
  retry após ConnectorThread reciclar resolve.
- `NL_WAITING_SERVER` (-2147483644): TRANSIENT — semântica explícita.
- `NL_NOT_FOUND`, `NL_ASSET_NO_DATA`: AMBIGUOUS — pode ser warming
  (transient) OU pediu errado (permanent). Cap conservador (max=3).
- Auth codes (`NL_NO_LOGIN`, `NL_NO_LICENSE`): PERMANENT — re-login não
  é responsabilidade do retry; caller deve agir.
- `NL_INVALID_TICKER`, `NL_EXCHANGE_UNKNOWN`: PERMANENT — bug lógico;
  retry mascararia.
- `NL_NOT_INITIALIZED`: PERMANENT — bug do caller (initialize_market_only
  faltou).

**Trade-off:** UNKNOWN como NO-RETRY é decisão conservadora — alternativa
seria default TRANSIENT para "código novo da DLL pode ser flake transitório"
mas isso mascararia bugs de protocolo (release nova com semântica diferente).
R7 vence.

### D2 — RetryPolicy como dataclass imutável (Dex + Aria)

**Decisão:** `RetryPolicy(frozen=True)` substitui o conjunto de kwargs
ad-hoc do `with_retry` de Story 1.7a. Defaults documentados:

| Categoria | max_attempts | base_delay | factor | max_delay | jitter |
|-----------|--------------|------------|--------|-----------|--------|
| TRANSIENT | 5 | 30s | 2.0 | 600s | ±20% |
| AMBIGUOUS | 3 | 60s | 2.0 | 600s | ±20% |
| PERMANENT/UNKNOWN | 1 | — | — | — | — |

**Backwards-compat:** `with_retry(fn)` sem `policy=` mantém comportamento
Story 1.7a (max_attempts=3, OSError/TimeoutError retryable). Quando
`policy=` é passado, delega tudo para a policy (raise última exception em
exhaustion, NÃO `RetryError`).

**Override via env var (AC8):**
- `DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_TRANSIENT` (default 5)
- `DATA_DOWNLOADER_RETRY_MAX_ATTEMPTS_AMBIGUOUS` (default 3)
- `DATA_DOWNLOADER_RETRY_BASE_DELAY_SECONDS` (default 30.0)
- `DATA_DOWNLOADER_RETRY_BASE_DELAY_AMBIGUOUS_SECONDS` (default 60.0)
- `DATA_DOWNLOADER_RETRY_FACTOR` (default 2.0)
- `DATA_DOWNLOADER_RETRY_MAX_DELAY_SECONDS` (default 600.0)
- `DATA_DOWNLOADER_RETRY_JITTER` (default 0.2)

Valores inválidos caem silentemente no default (best-effort) com
`structlog.warning("retry_policy.env_invalid", ...)` — operador vê.

### D3 — CircuitBreaker dependency-free (Aria + Dex)

**Decisão:** Implementação própria com `collections.deque` + `threading.Lock`.
**Razão:** R10 (minimal deps) — `pybreaker` adiciona ~3KB + dep transversal.
Nossa máquina de estados é simples (3 estados, ~150 linhas).

**State machine:**
```
CLOSED ──(N falhas em janela W)──> OPEN
OPEN ──(cooldown decorrido)─────> HALF_OPEN
HALF_OPEN ──(sucesso na 1ª call)─> CLOSED
HALF_OPEN ──(falha na 1ª call)──> OPEN (cooldown x 2 — backoff)
```

**Defaults:**
- `failure_threshold=10` em janela `300s` → trip
- `cooldown=600s` (10min) — Q02-E margem
- Cooldown amplificado capped em `base_cooldown x 8` (anti-DoS)

**Thread-safety:** lock garante que `record_failure` + state read não
race entre threads. `fn()` no `call()` roda FORA do lock para evitar
deadlock se `fn` re-entrar (download_chunk usa threads internas).

**Por (symbol, exchange):** Orchestrator instancia 1 breaker por par
(lazy-create em `_get_breaker`). Multi-symbol futuro (Epic 3) já preparado.

### D4 — Q02-E progress-aware policy (Nelo + Dex)

**Decisão:** Q02-E (progress=99% reconnect) é tratado em
`download_primitive` (já em Story 1.3) — orchestrator confia que
`download_chunk` retorna `status='completed'` mesmo após 100 callbacks
de progress=99% se o `TC_LAST_PACKET` chegou. Apenas timeout duro
(1800s sem progresso real) ou `NL_*` error code real promovem para
`status='failed'` ou `'timeout'`.

**Logo:** o breaker NÃO precisa de hook especial Q02-E porque ele
recebe apenas:
- Sucesso (status='completed') → `record_success`
- Timeout (status='timeout' → TimeoutError) → `record_failure` (TRANSIENT)
- NL_* error real (status='failed' → OSError com nl_code) → `record_failure`
  classificado pela taxonomia

Q02-E aparece como sucesso para o breaker (porque download completou),
exatamente como deveria — não conta como falha. Test sintético em
`test_orchestrator_with_retry::test_circuit_breaker_does_not_count_q02e_progress_99_as_failure`
valida: 1 chunk completed → breaker permanece CLOSED, 0 falhas.

**Atualização Q02-E em QUIRKS.md:** workaround formalizado como
"download_primitive usa timeout 1800s + breaker NUNCA conta progress=99%
porque progress não é error code."

### D5 — Boundary preservation (Aria)

**Decisão:** mudanças cirúrgicas em `orchestrator.py`:
- Aceita `retry_policy: RetryPolicy | None` e
  `circuit_breaker: CircuitBreaker | None` (defaults via factories).
- `_process_chunk` chama `breaker.call(_do_download)` dentro de
  `with_retry(..., policy=self._retry_policy)`.
- `CircuitOpenError` capturado separadamente — registra gap como
  `failed_chunk` + métrica `chunks_completed_total{status="circuit_open"}`,
  segue próximo chunk (NÃO aborta job).
- `RetryError` mantido para path V1 (sem policy) — backwards-compat.
- Novo `(OSError, TimeoutError)` capture para path policy (re-raise última
  exception).

**Sem mudança de fronteira `public_api/`:** `CircuitOpenError` já era tipo
público em ADR-011; semântica de `download(...)` continua "raise se
fatal" (para chamadores externos, breaker open vira `partial`/`failed` no
job result).

---

## Riscos & Mitigações

| Risco | Mitigação |
|-------|-----------|
| Loop infinito de retry em DLL caída | CircuitBreaker abre após N falhas → CircuitOpenError (R7) |
| Default policy quebra chamadores antigos | `with_retry(fn)` sem `policy=` mantém comportamento Story 1.7a |
| Bug em RetryPolicy mascara erro lógico | PERMANENT/UNKNOWN fail-fast (R7) + 47 unit tests + 8 property tests |
| Concurrency bug no breaker | `threading.Lock` interno + 2 thread-safety tests + property test |
| Cooldown ampliado vira ataque DoS | Capped em `base_cooldown x 8` |
| NL_* code novo da DLL não categorizado | Retorna `UNKNOWN` (NO retry, log warning) — defesa R7 |

---

## Sign-offs

- **Nelo (DLL):** Tabela `NL_CATEGORY_MAP` audited. 39 codes corretos por
  semântica (consultei `profit.h` L217-222 + main.py L13-48 + `PROFITDLL_KNOWLEDGE.md` §5).
- **Dex (impl):** RetryPolicy + CircuitBreaker implementados. 100 unit
  tests passam (47 nl_categorization + 26 retry_policy + 19 circuit_breaker
  + 8 property invariants). 7 integration tests verificam orchestrator
  integration sem regressão.
- **Aria (boundary):** Padrão circuit breaker correto (3-state machine
  canônica). Fronteira preservada (`public_api/exceptions.py` intacto;
  CircuitOpenError já era tipo público ADR-011). Thread-safety auditada
  (lock + fn FORA do lock). Mudanças em orchestrator.py mínimas e
  backwards-compatible.

---

## Referências

- `src/data_downloader/dll/error_taxonomy.py` — taxonomia NL_*.
- `src/data_downloader/orchestrator/retry_policy.py` — RetryPolicy + factories.
- `src/data_downloader/orchestrator/circuit_breaker.py` — state machine.
- `src/data_downloader/orchestrator/orchestrator.py` — integração.
- `tests/unit/test_nl_categorization.py` — 47 unit tests.
- `tests/unit/test_retry_policy.py` — 26 unit tests.
- `tests/unit/test_circuit_breaker.py` — 19 unit tests.
- `tests/integration/test_orchestrator_with_retry.py` — 7 integration tests.
- `tests/property/test_retry_invariants.py` — 8 hypothesis-based property tests.
- `docs/dll/QUIRKS.md` Q02-E — workaround formalizado.
- `docs/adr/ADR-011-exception-hierarchy.md` — `CircuitOpenError` herda
  `DataDownloaderError`.
