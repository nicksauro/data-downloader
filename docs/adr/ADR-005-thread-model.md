# ADR-005 — Thread model com bounded queues e block back-pressure

**Status:** accepted
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🗝️ Nelo (lei DLL), ⚡ Pyro
**Supersedes:** —
**Related:** ADR-001 (Python), ADR-003 (PySide6), ARCHITECTURE.md §2

---

## Contexto

O sistema combina três fontes de concorrência:
1. **ProfitDLL** — cria sua própria `ConnectorThread` que dispara callbacks.
2. **Backend Python** — precisa drenar callbacks, validar, persistir, sem chamar a DLL de volta (lei R3 / manual §4).
3. **UI PySide6** — MainThread Qt nunca pode bloquear (lei R11).

Restrições inegociáveis:
- **R3:** Nenhuma chamada à DLL dentro de callback. Callback faz apenas `queue.put_nowait()`.
- **R11:** Slots no MainThread Qt < 16ms.
- **Idempotência (R5):** writer não pode escrever Parquet incompleto se processo morre.

---

## Opções Consideradas

### Opção A — Single-writer, bounded queues, block back-pressure
- 1 IngestorThread + 1 WriterThread + 1 OrchestratorThread + Qt MainThread.
- Filas bounded (`Queue(maxsize=N)`).
- Política overflow: **block** (callback espera se fila cheia).

### Opção B — Multi-writer com lock
- N WriterThreads escrevendo em arquivos diferentes em paralelo.
- Lock de catálogo SQLite.

### Opção C — asyncio
- Loop asyncio drenando filas.

### Opção D — Drop-on-overflow
- Filas bounded; callback descarta se fila cheia (não bloqueia).

---

## Análise

| Critério | A (block) | B (multi-writer) | C (asyncio) | D (drop) |
|----------|-----------|------------------|-------------|----------|
| Respeita R3 (callback rápido) | ✅ block é micro-pausa | ✅ | ✅ | ✅ (literal não bloqueia) |
| Respeita R11 (UI não bloqueia) | ✅ (Qt MainThread isolada) | ✅ | depende | ✅ |
| Perda de dado | nenhuma | nenhuma | nenhuma | **sim** ❌ |
| Complexidade | baixa | alta (sincronização) | média (asyncio + ctypes interop) | trivial |
| Throughput single-writer | OK (>100k trades/s) | maior (mas multi-symbol é melhor via processo) | similar | maior |
| Debugging | fácil | difícil (race conditions) | médio | médio |

**Pontos críticos:**

- **Opção D (drop)** viola a essência: queremos baixar TODOS os trades; perder porque a fila encheu = inaceitável. **Rejeitada.**

- **Opção B (multi-writer)** complica sincronização de catálogo SQLite. Ganho de throughput é marginal porque escrita Parquet single-thread já entrega 100k+ trades/s (alvo Pyro). Para multi-symbol real, é melhor usar **multiprocessing** (1 processo por DLL, vide ARCHITECTURE.md §2.4) — sem race conditions intra-processo. **Rejeitada.**

- **Opção C (asyncio)** seria elegante, mas asyncio + ctypes + threading da DLL = friction grande. ConnectorThread da DLL não é asyncio-aware; teríamos pontes thread→loop. Complexidade não compensa. **Rejeitada para V1.**

- **Opção A (single-writer + block)** é a mais simples, suficientemente performática (Pyro valida >100k trades/s em bench), zero perda de dado, debugging trivial. **Escolhida.**

---

## Decisão

**Opção A — Single-writer com bounded queues e block back-pressure.**

### Threads do processo (5)

| # | Thread | Owner | Função | Restrição |
|---|--------|-------|--------|-----------|
| 1 | MainThread (Qt) | PySide6 | Eventos UI, slots Qt | < 16ms; nunca chama DLL |
| 2 | ConnectorThread | ProfitDLL | Dispara callbacks | Não controlada por nós |
| 3 | IngestorThread | orchestrator | Drena `dll_queue` → valida → enqueue `write_queue` | Nunca chama DLL |
| 4 | WriterThread | storage | Drena `write_queue` → batch → Parquet append → catálogo | Nunca chama DLL |
| 5 | OrchestratorThread | orchestrator | Loop chunking, dispara `GetHistoryTrades`, retry | Pode chamar DLL (não está em callback) |

### Filas (3, todas bounded)

| Fila | Capacidade | Política overflow | Produtor → Consumidor |
|------|-----------|-------------------|------------------------|
| `dll_queue` | 10_000 | **block** | ConnectorThread → IngestorThread |
| `write_queue` | 5_000 | **block** | IngestorThread → WriterThread |
| `ui_progress_queue` | 100 | **drop-oldest** | OrchestratorThread → MainThread (via Qt signal) |

**Por que `block` no caminho de dado:** se a fila enche, a `ConnectorThread` da DLL fica brevemente parada na chamada `put_nowait()` que bloqueia. Isso aplica back-pressure naturalmente — a DLL para de gerar callbacks até o ingestor drenar. Resultado: nada perdido, throughput regulado pelo gargalo (geralmente disco).

**Por que `drop-oldest` em ui_progress_queue:** UI não precisa de cada update; um update de 60Hz é suficiente. Acumular 1000 progressos antigos não ajuda usuário.

### Comunicação UI ↔ Backend

```
OrchestratorThread.emit_progress(p)
  → ui_progress_queue.put_nowait(p)  # drop-oldest se cheia
  → adapter (QObject em QThread separada) drena fila
  → adapter.progress_signal.emit(p)
    → MainThread slot (QueuedConnection) atualiza widget
```

`QueuedConnection` faz marshalling automático de thread em PySide6.

### Sequência de start/stop

**Start (no início de download):**
1. Cria filas
2. Inicia WriterThread
3. Inicia IngestorThread
4. Cria callbacks (com `_cb_refs` global p/ não GC)
5. Registra callbacks na DLL (`SetHistoryTradeCallback*`)
6. Inicia OrchestratorThread
7. OrchestratorThread chama `GetHistoryTrades` (1ª vez)

**Stop (graceful):**
1. OrchestratorThread sinaliza fim
2. Aguarda último callback drenar `dll_queue` → `write_queue` → arquivo
3. Sentinel `None` em `dll_queue` → IngestorThread termina
4. Sentinel `None` em `write_queue` → WriterThread termina (commit final SQLite)
5. Unsubscribe DLL callbacks
6. Limpa `_cb_refs`

**Stop (crash recovery):**
- WriterThread escreve Parquet em `.tmp.{uuid}`; só faz `os.replace` após `fsync`.
- Crash no meio = `.tmp` órfão; cleanup ao iniciar próximo download.
- SQLite WAL garante consistência do catálogo.
- Story 1.5: implementa cleanup + checkpoint.

### Multi-symbol (Epic 4+)

1 processo por símbolo. Cada processo tem seu próprio thread model acima. Coordenação via filesystem (catálogo SQLite com WAL aceita múltiplos leitores e escritor único). Para evitar contention, cada processo escreve em sua sub-árvore (símbolos diferentes = paths diferentes). Catálogo: sub-process abre SQLite read-only; processo principal (UI/master) tem write lock.

---

## Consequências

### Positivas
- Zero perda de dado (block = back-pressure natural).
- Debugging trivial (5 threads nomeadas, filas inspecionáveis).
- Respeita lei R3 (callback faz apenas put_nowait) e R11 (MainThread isolada via QueuedConnection).
- WriterThread single garante atomicidade de catálogo (transação SQLite simples).
- Pyro valida throughput >100k trades/s em Story 2.2 (target alcançável com single writer).

### Negativas
- 5 threads é inerentemente mais complexo que single-thread + asyncio (mas asyncio + ctypes piora).
- Block em `dll_queue` significa que disco lento desacelera download — feature, não bug (alternative = perder dado).

### Neutras
- Multi-symbol via multiprocessing (ADR independente, futuro).

---

## Invariantes derivadas (vão para ARCHITECTURE.md)

- INV-1: Nenhuma chamada à DLL dentro de callback (R3).
- INV-4: Toda fila tem `maxsize > 0` e política de overflow declarada.
- INV-10: MainThread Qt nunca bloqueia >16ms.

---

## Validações requeridas

- [ ] Pyro `*bench_callback_to_disk` p99 < 100ms (Story 2.2)
- [ ] Pyro `*bench_parquet_write` >= 100k trades/s sustained (Story 2.2)
- [ ] Quinn property-test: nenhum trade perdido em sequência simulada de 1M callbacks (Story 2.1)
- [ ] Quinn smoke test: graceful shutdown sem `.tmp` órfão (Story 1.7)
- [ ] Felix `*responsiveness-audit`: todos slots MainThread < 16ms (Epic 3)

---

## Amendment 2026-05-03 — State machine de shutdown + INV-11/INV-12

**Autor:** 🏛️ Aria
**Consultados:** 🧪 Quinn, 💻 Dex, 🖼️ Felix
**Origem:** PLAN_REVIEW H11 (race no shutdown), H10 (cancel real), C6 (INV-1 testável)
**Related:** ADR-007a (DownloadHandle.cancel)

### Problema endereçado

H11: shutdown atual é "sentinel `None` em fila + thread.join". Race possível:
- OrchestratorThread declara "100% completo" e emite `finished`.
- Mas último `HistoryTradeCallback` ainda está sendo processado pelo IngestorThread.
- Ou último `WriteThread.flush()` ainda não commitou no SQLite.
- UI mostra "Done" mas catálogo está inconsistente até o flush real.

H10: `cancel()` do DownloadHandle (ADR-007a) precisa de protocolo determinístico — não pode ser "set flag e torce".

### State machine de shutdown

Estados explícitos por job (rastreados em catalog SQLite):

```
                     ┌──────────┐
                     │   Idle   │
                     └────┬─────┘
                          │ download() chamado
                          ▼
                     ┌──────────┐
                     │ Running  │
                     └────┬─────┘
                          │ user clicked cancel() OR last chunk delivered
                          ▼
                  ┌───────────────┐
                  │ DrainingDLL   │   - Para de chamar GetHistoryTrades
                  │               │   - Aguarda dll_queue vazia (timeout 30s)
                  └───────┬───────┘
                          │ dll_queue.empty() == True
                          ▼
                  ┌───────────────┐
                  │ DrainingWrite │   - Aguarda write_queue vazia
                  │               │   - Aguarda último write commit em SQLite
                  └───────┬───────┘
                          │ write_queue.empty() AND último commit
                          ▼
                  ┌───────────────┐
                  │  Committed    │   - Catalog tem 'completed' status
                  │               │   - Emit finished signal para UI
                  └───────┬───────┘
                          │ cleanup
                          ▼
                     ┌──────────┐
                     │   Idle   │
                     └──────────┘
```

#### Transições

| De | Para | Trigger | Acción | Timeout |
|----|------|---------|--------|---------|
| Idle | Running | `download()` retorna handle | Cria threads, registra callbacks DLL | — |
| Running | DrainingDLL | `cancel()` ou último chunk OK | Sentinel em dll_queue: `STOP_REQUEST` | — |
| DrainingDLL | DrainingWrite | dll_queue.qsize()==0 + IngestorThread idle | Sentinel em write_queue | 30s (depois timeout error) |
| DrainingWrite | Committed | write_queue.qsize()==0 + WriterThread idle + last SQLite commit OK | Update catalog `status='completed'` | 30s |
| Committed | Idle | Cleanup feito (unsubscribe DLL callbacks, free `_cb_refs`) | Emit `finished` signal (UI) | — |

#### Emissão de `finished` ÚNICA

`finished` Qt signal é emitido **uma única vez**, no transition Committed → Idle, **após** SQLite commit confirmado. UI nunca vê "100%" antes de o catálogo refletir.

#### Cancel timeout

`DownloadHandle.cancel(timeout=30.0)` espera state machine atravessar até Idle. Se 30s expira em DrainingDLL ou DrainingWrite:
- Estado fica `DrainingDLL_TimedOut` ou `DrainingWrite_TimedOut`.
- Catalog marca chunks pending como `aborted`.
- Cleanup forçado de threads (com warnings em log).
- Levanta `DownloadError(cause=TimeoutError)` no caller.

### Novas invariantes

#### INV-11 — Separação física de threads

> **OrchestratorThread ≠ IngestorThread ≠ ConnectorThread.** Cada um é `threading.Thread` distinto, com nome distinto (`thread.name`), sem fusão (mesmo "para economia").

**Por que:** se Orchestrator e Ingestor compartilham thread, o orchestrator (que pode chamar DLL para `GetHistoryTrades`) acaba **dentro** do contexto do callback drain — viola INV-1 transitivamente. Confusão sutil; melhor enforçar fisicamente.

**Auditor:** Quinn — teste que enumera `threading.enumerate()` durante run e verifica nomes distintos.

#### INV-12 — Definição operacional de "fim de chunk"

> **"Fim de chunk" só pode ser declarado quando:**
> 1. `dll_queue.empty() == True` (nenhum trade pendente vindo da DLL)
> 2. `write_queue.empty() == True` (nenhum batch pendente para flush)
> 3. **AND** último write fez `commit()` em SQLite catalog (`PRAGMA synchronous=FULL` ou `wal_checkpoint(PASSIVE)`)

**Por que:** sem (3), pode haver buffers SQLite WAL não-checkpoint — se processo crashar nos próximos 100ms, catálogo perde a info de "chunk done" enquanto Parquet já foi `os.replace`-ed. Próximo run vê chunk como pending → dedup é necessário (lei R5).

**Auditor:** Quinn — property test que mata processo após `chunks_completed_total.inc()` e antes do próximo loop; verifica catálogo consistente em re-start.

### Implementação (Story 1.7a + 1.7b)

```python
# src/data_downloader/orchestrator/state_machine.py

from enum import Enum, auto

class JobState(Enum):
    IDLE = auto()
    RUNNING = auto()
    DRAINING_DLL = auto()
    DRAINING_WRITE = auto()
    COMMITTED = auto()


class JobStateMachine:
    def __init__(self, job_id: str, catalog: CatalogProtocol):
        self.job_id = job_id
        self.state = JobState.IDLE
        self.catalog = catalog
        self._lock = threading.Lock()

    def transition(self, to: JobState) -> None:
        with self._lock:
            valid_transitions = {
                JobState.IDLE: {JobState.RUNNING},
                JobState.RUNNING: {JobState.DRAINING_DLL},
                JobState.DRAINING_DLL: {JobState.DRAINING_WRITE},
                JobState.DRAINING_WRITE: {JobState.COMMITTED},
                JobState.COMMITTED: {JobState.IDLE},
            }
            if to not in valid_transitions.get(self.state, set()):
                raise ValueError(f'Invalid transition: {self.state} → {to}')
            self.state = to
            self.catalog.update_job_state(self.job_id, to.name)
```

### Atualização de invariantes globais

ARCHITECTURE.md §4 ganha INV-11 e INV-12 (este amendment). Aria editará separadamente.
