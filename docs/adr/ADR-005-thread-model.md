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

---

## Amendment 2026-05-04 — FAILED state (terminal alternativo)

**Autor:** 🏛️ Aria (mini-council Aria+Dex)
**Origem:** Story 1.7a implementação — Dex adicionou `FAILED` como
terminal alternativo a `COMMITTED`. Aria avaliou e ratificou via
audit `*review-design 1.7a` (`docs/qa/AUDIT_REPORTS/1.7a-design-2026-05-04.md`).
**Related:** ADR-005 amendment 2026-05-03 (state machine de shutdown).

### Problema endereçado

O amendment de 2026-05-03 desenhou o happy-path
`Idle → Running → DrainingDLL → DrainingWrite → Committed → Idle`
mas NÃO formalizou o caminho de erro. Em produção, um chunk pode
falhar definitivamente após esgotar retries, ou o catálogo SQLite
pode rejeitar um commit (disk full, schema mismatch). Sem estado
explícito de erro, o orchestrator ficava em estado ambíguo entre
`Running` e `Committed` quando algo falhava antes do drain final.

### Decisão

Adicionar **`FAILED`** como estado terminal alternativo a
`COMMITTED`, alcançável a partir de `RUNNING`, `DRAINING_DLL`, ou
`DRAINING_WRITE` (qualquer estado ativo). De `FAILED`, transição
única para `IDLE` (cleanup) — alinhado com a transição
`COMMITTED → IDLE` do amendment original.

### Diagrama atualizado

```
                     ┌──────────┐
                     │   IDLE   │
                     └────┬─────┘
                          │ run()
                          ▼
                     ┌──────────┐
                     │ RUNNING  │
                     └─┬──────┬─┘
              fatal err│      │ último chunk OK ou cancel
                       ▼      ▼
                ┌──────────┐ ┌────────────────┐
                │  FAILED  │ │ DRAINING_DLL   │
                └────┬─────┘ └─┬──────────┬───┘
                     │  fatal│           │ dll_queue empty
                     │       ▼           ▼
                     │ ┌──────────┐ ┌────────────────┐
                     │ │  FAILED  │ │ DRAINING_WRITE │
                     │ └────┬─────┘ └─┬──────────┬───┘
                     │      │  fatal │           │ write empty + commit
                     │      │        ▼           ▼
                     │      │ ┌──────────┐ ┌────────────┐
                     │      │ │  FAILED  │ │ COMMITTED  │
                     │      │ └────┬─────┘ └─────┬──────┘
                     │      │      │             │
                     ▼      ▼      ▼             ▼
                          ┌──────────┐
                          │   IDLE   │
                          └──────────┘
```

### Transições válidas atualizadas

| De              | Para            | Trigger                                         |
|-----------------|-----------------|-------------------------------------------------|
| IDLE            | RUNNING         | `run()` chamado                                 |
| RUNNING         | DRAINING_DLL    | Último chunk OK ou cancel                       |
| RUNNING         | **FAILED**      | Erro fatal antes do drain (NOVO)                |
| DRAINING_DLL    | DRAINING_WRITE  | dll_queue vazia + ingestor idle                 |
| DRAINING_DLL    | **FAILED**      | Timeout/erro no drain (NOVO — formaliza `DrainingDLL_TimedOut`) |
| DRAINING_WRITE  | COMMITTED       | write_queue vazia + commit SQLite OK            |
| DRAINING_WRITE  | **FAILED**      | Timeout/erro no commit (NOVO — formaliza `DrainingWrite_TimedOut`) |
| COMMITTED       | IDLE            | Cleanup feito                                   |
| **FAILED**      | **IDLE**        | Cleanup feito (NOVO — terminal alternativo)     |

### Justificativa

1. **Determinismo:** o estado `FAILED` formaliza o que o amendment
   original chamou de `DrainingDLL_TimedOut` / `DrainingWrite_TimedOut`
   sob um nome único e unificado — reduz cardinalidade de estados
   sem perder informação (a causa raiz vai em
   `catalog.downloads.error` e nos logs `orchestrator.fatal_error`).
2. **Observabilidade:** `JobStateMachine.transition(FAILED)` emite
   event `orchestrator.state_transition` com `to_state="FAILED"` —
   gauges e dashboards (V2 ADR-013) podem alertar em `state == FAILED`
   sem precisar correlacionar timeouts.
3. **Cleanup uniforme:** `force_idle()` aceita ambos `COMMITTED` e
   `FAILED` (linha 204 `state_machine.py`) — mesma rota de saída,
   simplifica o caller.
4. **Sem violação INV-11/INV-12:** estado `FAILED` é declarado pelo
   orchestrator (OrchestratorThread) APÓS observar erro fatal — não
   muda o contrato "fim de chunk" (INV-12); apenas marca que o job
   NÃO completou os 4 critérios de COMMITTED.

### Implementação

`src/data_downloader/orchestrator/state_machine.py:68-94` — `JobState.FAILED`
+ entradas em `VALID_TRANSITIONS` para `RUNNING/DRAINING_DLL/DRAINING_WRITE → FAILED`
e `FAILED → IDLE`. `force_idle()` (linhas 193-206) aceita ambos
terminais. 16 testes unit em `tests/unit/test_state_machine.py`
cobrem: `test_failed_path_from_running`, `test_failed_path_from_draining_dll`,
`test_failed_path_from_draining_write`, `test_force_idle_from_failed`.

### Sign-off

- **Aria (architect):** APPROVED — extensão é minor, alinhada com
  espírito do amendment original (DrainingDLL_TimedOut →
  DrainingDLL → FAILED). Uniformiza terminal alternativo.
- **Dex (implementer):** APPROVED implícito — implementação já
  existente em `state_machine.py`, este amendment formaliza.

### Auditor

Quinn — testes unit `test_state_machine.py` validam todas as 4
transições para FAILED + 1 transição FAILED → IDLE. Audit Aria
`*review-design 1.7a` confirmou consistência (sem regressão de
INV-11/INV-12).

---

## Amendment 2026-05-04 (b) — DLL init sequence Nelogica example

**Autor:** 🏛️ Aria (review-design Story 1.7b-followup, autônomo)
**Origem:** Smoke real falhou com MARKET_DATA estancado em `result=1`
(MARKET_WAITING_TICKETS) sem progredir para `result=4`
(MARKET_CONNECTED). Usuário reorientou: "manual e exemplo não estão
errados, basta seguir". Comparação arquitetural exemplo Nelogica
(`profitdll/Exemplo Python/main.py:729-764`) vs nosso wrapper
(`src/data_downloader/dll/wrapper.py`).
**Related:** Story 1.2 AC2 (11 callback slots), Q-DRIFT-02 (handshake
lento), Q11-E (Sentinel — None nos slots), R3 (callback-only
put_nowait).

### Problema endereçado

Smoke 2026-05-04 mostrou que `wait_market_connected` recebia
sequência de states travando em MARKET_DATA `result=1`
(MARKET_WAITING_TICKETS) — nunca alcançando `result=4`. Hipóteses
em paralelo:

1. **Nelo** investiga semântica de state codes (paralelo).
2. **Aria (este amendment)** investiga divergência de SEQUÊNCIA DE
   INICIALIZAÇÃO entre nosso wrapper e o exemplo oficial Nelogica.

### Comparação estrutural exemplo vs wrapper

#### A. Sequência de inicialização

| Passo | Exemplo Nelogica (`main.py:729-764`) | Nosso wrapper (`wrapper.py:240-375`) |
|-------|--------------------------------------|--------------------------------------|
| 1 | `DLLInitializeMarketLogin(key, user, pwd, stateCallback, None, newDailyCB, None, None, None, progressCB, tinyBookCB)` (11 args) | `DLLInitializeMarketLogin(key, user, pwd, stateCB, *7 NoopCB)` (11 args) |
| 2 | `SetAssetListCallback`, `SetAdjustHistoryCallbackV2`, `SetAssetListInfoCallback`, `SetAssetListInfoCallbackV2`, `SetOfferBookCallbackV2`, `SetOrderCallback`, `SetOrderHistoryCallback`, `SetInvalidTickerCallback`, `SetTradeCallbackV2`, `SetAssetPositionListCallback`, `SetBrokerAccountListChangedCallback`, `SetBrokerSubAccountListChangedCallback`, `SetPriceDepthCallback`, `SetTradingMessageResultCallback` (**14 calls**) | (NENHUM `SetXxxCallback` chamado entre init e wait) |
| 3 | `wait_login()` — busy-loop em flag `bMarketConnected` | `wait_market_connected()` — drain queue |

**Divergência arquitetural identificada:** o exemplo oficial registra
**14 callbacks adicionais via `SetXxxCallback` ANTES de aguardar a
conexão**. Nosso wrapper omite essa fase. **Hipótese:** a DLL pode
condicionar o handshake completo de MARKET_DATA (transição de
`result=1` para `result=4`) à presença de callbacks pré-registrados
para feed-types específicos (asset-list, adjust-history, trade-V2,
offer-book-V2). Ausência dos slots faz a DLL completar o login mas
nunca declarar MARKET_CONNECTED — porque, do ponto de vista da DLL,
não há "consumidor" para o feed.

#### B. Critério de "conectado"

| | Exemplo (`main.py:222-228, 568-579`) | Nosso wrapper (`wrapper.py:464-470`) |
|---|--------------------------------------|--------------------------------------|
| Aceita | `conn_type==2 AND result==4` (somente) | `conn_type==2 AND result ∈ {2, 4}` |

**Análise:** o exemplo é mais estrito (apenas `result=4`); o manual
canônico §3.2 L3317-3329 confirma `4 = MARKET_CONNECTED`. Nosso
wrapper introduziu `result=2` (MARKET_WAITING) como aceito sob
"flexibilidade defensiva" (Q-AMB-01) — mas isso é uma **inflação de
estados válidos**: `result=2` significa que a DLL está apenas
aguardando ticket-data, NÃO conectada. Aceitar `2` pode declarar
sucesso prematuro e mascarar bugs reais (como o smoke atual onde
`result=1` aparece e nunca avança — se aparecesse `2`, nosso wrapper
declararia "conectado" indevidamente). **Recomendação:** alinhar com
exemplo — aceitar SOMENTE `result=4` (consistente com manual canônico).

#### C. Slots de callback no init (None vs Noop)

| | Exemplo | Nosso wrapper |
|---|---------|---------------|
| Slots ativos | state, daily, progress, tinyBook (4) | state (1) |
| Slots `None` | 4 (trade, priceBook, offerBook, histTrade) | 0 |
| Slots Noop | 0 | 7 |

**Análise:** o exemplo passa **`None` nos slots não-usados**, contrariando
o que documentamos em Q11-E / Sentinel §12 ("None corrompe registro
interno"). Esta evidência empírica do código oficial sugere que o
guard Q11-E pode ter sido **defesa em demasia**. Porém, NoopCallback
é estritamente mais defensivo (não há custo runtime) e mantém a regra
"nunca passar ponteiro nulo". **Decisão:** manter NoopCallback (custo
zero, robustez extra), mas reconhecer que a estrutura do exemplo é
válida.

Mais importante: **o exemplo deixa `histTrade` (slot 8) como `None`
no init** e depois registra `SetTradeCallbackV2` (note: TradeCallback
V2 ≠ HistoryTradeCallback V2). Isso confirma que `Set*Callback` pós-init
para handlers reais é o padrão canônico — exatamente o que Story 1.3
faz (`set_history_trade_callback_v2`).

#### D. Threading

| | Exemplo | Nosso wrapper |
|---|---------|---------------|
| State callback body | escreve em flag global (`bMarketConnected = True`) | `state_queue.put_nowait((conn_type, result))` |
| Wait loop | busy-loop sobre flag (sem sleep) | `queue.get(timeout=...)` com heartbeat 30s |

**Decisão arquitetural CONFIRMADA:** nosso modelo (queue + drain)
é **estritamente superior** ao exemplo:

- **R3 / INV-1 preservado:** callback faz APENAS put_nowait —
  exemplo escreve em flag (também simples, mas sem debugging útil).
- **Sem CPU-burn:** exemplo busy-loops sem sleep (consume 100% CPU
  até MARKET_CONNECTED chegar) — nosso `get(timeout=...)` cede CPU.
- **Heartbeat:** Q-DRIFT-02 emite log a cada 30s; exemplo é
  silencioso, operador não sabe se travou.
- **Inspecção externa:** counter `dll_state_queue_full_total`
  (ADR-013) detecta saturação; flag global é opaca.

**NÃO retroceder para flags globais.** Manter padrão queue (R3).

### Decisão arquitetural

1. **Manter** padrão queue + drain (R3 / INV-1) — modelo superior
   ao exemplo, sem regressão.
2. **Manter** NoopCallback nos 7 slots não-state do init — custo
   zero, defesa em profundidade, alinhado com Q11-E (mesmo que
   exemplo use `None`, NoopCallback é estritamente mais defensivo).
3. **Recomendação para Dex (próximo agente, paralelo):**
   pre-registrar callbacks adicionais via `SetXxxCallback` ENTRE
   init e `wait_market_connected`, replicando a sequência do
   exemplo. Hipótese: DLL pode requerer callbacks pré-registrados
   para feed-types específicos para completar handshake MARKET_DATA.
   Slots críticos a investigar (em ordem de probabilidade):
   - `SetTradeCallbackV2` (feed live trade — pode ser pré-requisito
     para MARKET_DATA `result=4`)
   - `SetOfferBookCallbackV2` (book live)
   - `SetAdjustHistoryCallbackV2` (adjust feed)
   - `SetAssetListCallback` + `SetAssetListInfoCallback{V2}`
     (registro de tickers ativos)
4. **Recomendação adicional:** alinhar critério de "conectado" com
   exemplo — aceitar SOMENTE `result=4` para `conn_type=2`. O
   `result=2` (MARKET_WAITING) é estado intermediário, não terminal.
   Atualizar `wait_market_connected` (`wrapper.py:464-470`) e doc
   AC5 / Q-AMB-01. Esta mudança restringe o critério, alinha com
   manual + exemplo, e elimina risco de "sucesso prematuro".

### Risco arquitetural

A hipótese (3) cria nova superfície de falha: cada `SetXxxCallback`
adicionado é um trampoline ctypes a mais para sustentar em
`_cb_refs` (anti-GC, Q07-V). Lista crescerá de 8 entries para
~22 entries — ainda trivial, mas formaliza que **factories
correspondentes** (`make_trade_callback_v2`, `make_offer_book_v2`,
etc.) precisam ser criadas em `callbacks.py` com mesma disciplina
(R3 — só put_nowait). Story dedicada (ex. 1.7c ou refactor
de 1.2) para Dex implementar com testes.

**Não há dependência circular.** Os novos callbacks viveriam em
`callbacks.py` (já existente), tipos em `types.py` (já estendido com
V2 em Story 1.3). Diff mecânico sobre wrapper.

### Sign-off

- **Aria (architect):** APPROVED — review-design conclusivo. A
  divergência (A) é a hipótese mais forte para o smoke real travado;
  (B) é fix seguro e baixo custo; (C/D) confirma decisões prévias.

### Auditor

Story 1.7c (futura, owner Dex) — implementação dos `SetXxxCallback`
pré-conexão + smoke real após mudança. Quinn validar via test
property: `wait_market_connected` retorna True SOMENTE em
`result=4`; smoke real demonstra MARKET_DATA progredindo de
`result=1` para `result=4`.
