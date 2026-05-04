# COUNCIL-17 — Exception Hierarchy ADR-011 Implementada + H10 Cancel Closure

**Data:** 2026-05-03
**Convocação:** Mini-council Aria + Dex + Uma — Story 2.11 (autônoma)
**Participantes mentais:**
- 🏛️ Aria (Architect — autoridade ADR-011 + fronteira public_api)
- 💻 Dex (Builder — implementação 3 camadas + cancel())
- 🎨 Uma (UX/UI Designer — autoridade microcopy R17)

**Reviewers (downstream):**
- 🖼️ Felix (Frontend — desbloqueado para Epic 3 via cancel API real)
- 🧪 Quinn (QA — gate de Story 2.11)

---

## Contexto

Story 2.11 implementou a hierarquia de exceptions ADR-011 (3 camadas) +
fechou o finding **H10** (`DownloadHandle.cancel()` agora é real, não
fingido). Esta entrega é **fronteira pura** — não muda algoritmo, não
muda performance, não muda dado. Muda **tipos** + adiciona método
cancelamento real. É contrato.

H10 era CRÍTICO porque desbloqueia Felix para Epic 3 (UI precisa de
cancel API real, não placeholder). Sem cancel real, o botão "Cancelar"
da UI mente para o usuário (UX desonesta).

---

## Decisões

### D1 — 3 camadas isoladas (Aria authority — ADR-011 §"Decisão")

**Escolha:** Opção A do ADR-011 — Hierarquia pública estável + base
interna privada + tradução na fronteira.

**Implementação:**

| Camada | Path | Conteúdo |
|--------|------|----------|
| **L1 — Internals** | `src/data_downloader/_internal/exceptions.py` | `_InternalError` base + 8 subclasses (`_DLLProbeFailed`, `_DLLDisconnected`, `_ChunkTimedOut`, `_ChunkRetryExhausted`, `_QueueOverflow`, `_FormatParseError`, `_StateTransitionError`, `_OperationCancelled`) |
| **L2 — Adapter** | `src/data_downloader/_internal/exception_adapter.py` | `translate_to_public()` lookup table + `@translate_internal` decorator |
| **L3 — Public API** | `src/data_downloader/public_api/exceptions.py` | `DataDownloaderError` family — adicionados `OperationCancelled` (H10) + `ConnectionLost` (Q02-E exposto). `humanized_message` property → microcopy ID via Uma |

**Fronteira unidirecional:** internals NUNCA importam public_api;
adapter faz late-import para evitar ciclos. Verificação mecânica via
`test_internals_do_not_import_public_api`.

**Marker `_internal: ClassVar[Literal[True]]`:** permite property test
de "no leak" detectar mecanicamente subclasses internas sem precisar
importar cada nome.

**Defesa em profundidade:** subclasses não-mapeadas no adapter caem em
`DataDownloaderError` genérico (fallback seguro). Property test
Hypothesis garante invariante mesmo com adições futuras de
`_InternalError` sem update simultâneo do adapter.

### D2 — H10 closure: `DownloadHandle.cancel(*, timeout=30.0) -> bool` (Dex impl, Aria audit)

**Escolha:** Cooperative cancellation — graceful drain entre chunks; NÃO
interrompe chunk em andamento (preserva idempotência R5 + INV-12).

**API surface (handle.py):**

| Método | Comportamento |
|--------|---------------|
| `cancel(*, timeout=30.0) -> bool` | Seta `threading.Event`; aguarda completion até timeout. `True` se worker terminou; `False` se ainda rodando. |
| `cancelled() -> bool` | Non-blocking probe — `True` apenas se cancel pedido E worker terminou em status `"cancelled"`. |
| `is_cancelled` (property) | Alias de `cancelled()`. |
| `is_cancelling()` | Continua existindo — "cancel pedido, ainda pode estar drenando". |
| `result()` | **Mudança breaking-soft:** levanta `OperationCancelled` quando status final é `"cancelled"` (em vez de retornar `DownloadResult` com status="cancelled"). |
| `peek_result()` | NEW — non-blocking, no-raise alternative para inspeção pós-cancel. |

**Orchestrator integration (orchestrator.py):**

- `Orchestrator.run(config, *, cancel_event=None)` — novo kwarg opcional.
- Loop chunks checa `cancel_event.is_set()` ENTRE chunks (boundary
  graceful — INV-12 preservada).
- Worker em `download.py` propaga `cancel_event` ao orchestrator e mapeia
  `JobResult` → `DownloadResult(status="cancelled")` quando cancel set.

### D3 — Uma microcopy IDs novos (Uma authority R17)

Adições em `docs/ux/MICROCOPY_CATALOG.md` §6 + replicadas em
`src/data_downloader/ui/microcopy_loader.py`:

| ID | Tipo | Texto pt-BR (resumo) |
|----|------|---------------------|
| `error.cancelled.title` | error | "Download cancelado" |
| `error.cancelled.description` | error | "Você cancelou o download. {trades_preserved} trades já baixados foram preservados." |
| `error.connection_lost.title` | error | "Conexão perdida" |
| `error.connection_lost.description` | error | "Conexão com a corretora caiu. Tentando reconectar... (até 30 minutos é normal — Q02-E)" |
| `ERR_CONNECTION_LOST` | error | Alias UPPER_SNAKE para compat com `humanized_message` |
| `ERR_CHUNK_FAILED`, `ERR_CATALOG_DRIFT` | error | Replicados (já existiam no .md, faltavam no loader) |

Mapping `DataDownloaderError subclass → microcopy ID` via property
`humanized_message` (Story 2.11):

```python
{
    "DLLInitError": "ERR_DLL_NOT_INITIALIZED",
    "InvalidContract": "ERR_INVALID_CONTRACT",
    "DiskFull": "ERR_DISK_FULL",
    "DownloadError": "ERR_CHUNK_FAILED",
    "IntegrityError": "ERR_CATALOG_DRIFT",
    "OperationCancelled": "SUC_CANCEL_DONE",
    "ConnectionLost": "ERR_CONNECTION_LOST",
}
```

UI/CLI faz lookup via `microcopy_loader.format_msg(exc.humanized_message,
**exc.details)`. Texto continua sendo single-source no
`MICROCOPY_CATALOG.md` (R17 — Uma authority).

---

## Sign-off

### 🏛️ Aria (Architect)

**Verdict:** APPROVED.

ADR-011 fielmente implementada — 3 camadas isoladas, adapter pattern
em fronteira, marker para auditoria mecânica, fallback defensivo.
Hierarquia pública é **aditiva** (apenas novos tipos
`OperationCancelled` + `ConnectionLost`); **SemVer impact: MINOR**
(0.3.0 → 0.4.0 quando bumpar — recomendado mas opcional para Story 2.11
porque ambos tipos são novos sem renomear/remover existentes).

Property test "no internal leak" (Hypothesis 100 examples) garante a
invariante de fronteira mesmo com evolução futura. Test
`test_internals_do_not_import_public_api` reforça unidirecionalidade.

### 💻 Dex (Builder)

**Verdict:** APPROVED.

H10 fechado. `cancel(timeout)` retorna bool (True se drained, False se
timeout). `result()` raise `OperationCancelled` em vez de retornar
DownloadResult com status="cancelled" — caller força a tratar
cancelamento explicitamente (Pythonic). `peek_result()` adicionado para
casos onde caller quer inspecionar sem disparar.

Orchestrator agora aceita `cancel_event` opcional — backward-compatible
(default None preserva chamadores existentes; integration tests ainda
passam todos 12).

11 tests novos para cancel handle, 12 tests existentes do orchestrator
ainda PASS, tests existentes de `test_public_api_download.py` PASS sem
modificação.

### 🎨 Uma (UX/UI Designer)

**Verdict:** APPROVED.

Microcopy IDs novos seguem padrão dot-notation (`error.cancelled.*`,
`error.connection_lost.*`) E têm aliases UPPER_SNAKE
(`ERR_CONNECTION_LOST`) para compat com `humanized_message` que retorna
strings UPPER_SNAKE.

Texto pt-BR validado:
- "Download cancelado" — neutro, não-acusatório (P1 — humano-primeiro).
- "{trades_preserved} trades já baixados foram preservados" — sinaliza
  ao usuário que o cancelamento NÃO destruiu trabalho (P9 — recovery).
- "Conexão perdida... até 30 minutos é normal — Q02-E" — referência
  explícita ao quirk evita confusão com `WAR_99_RECONNECT` (que é
  reconexão NORMAL durante o quirk).

Microcopy registry consistente — cada exception type mapeia a 1 entry,
respeitando o catálogo Uma como single source.

---

## Validações

- [x] ruff check (src + tests novos): All checks passed
- [x] mypy (src/data_downloader/_internal/, public_api/, orchestrator.py): Success no issues
- [x] pytest (76 testes novos + 15 testes existentes): 91 passed
- [x] pytest tests/integration/test_orchestrator.py: 12 passed (sem regressão)
- [x] Property test Hypothesis: 100 examples no leak

---

## Felix unblocked notice

H10 fechada via Story 2.11. Felix pode iniciar Epic 3 com cancel API
real — `DownloadHandle.cancel(timeout=30.0) -> bool` + `cancelled()` /
`is_cancelled` property + `result()` raise `OperationCancelled` quando
cancelamento OK.

Note adicionada em `docs/decisions/COUNCIL-12-epic3-prep.md` §Pendências
(P1).

---

## Referências

- `docs/adr/ADR-011-exception-hierarchy.md` — fonte primária Aria
- `docs/adr/ADR-007a-public-api-redesign.md` — `DownloadHandle.cancel()` contract
- `docs/stories/2.11.story.md` — story
- `docs/ux/MICROCOPY_CATALOG.md` — Uma authority R17
- `src/data_downloader/_internal/exceptions.py` — Camada 1
- `src/data_downloader/_internal/exception_adapter.py` — Camada 2
- `src/data_downloader/public_api/exceptions.py` — Camada 3
- `src/data_downloader/public_api/handle.py` — H10 closure
- `src/data_downloader/orchestrator/orchestrator.py` — cancel_event integration

---

— Aria 🏛️, Dex 💻, Uma 🎨 — Story 2.11 complete; Felix unblocked for Epic 3.
