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

---

## Amendment 2026-05-04 (c) — Init/Wait separation + subscribe-handshake

**Autor:** 🏛️ Aria (review-design autônomo, mini-council Aria)
**Origem:** Smoke real persistente: MARKET_DATA fica em `result=1`
(CONNECTING/MARKET_WAITING_TICKETS) e nunca alcança `result=4`
(MARKET_CONNECTED) mesmo após o amendment (b) recomendar
`SetXxxCallback` extras. Usuário (autoridade ProfitDLL real)
reafirmou: **"MARKET_DATA não conecta = bug na nossa função de
inicialização, não é DLL nem horário"**. Diagnóstico arquitetural
da fronteira `init / wait / subscribe`.
**Related:** Amendment 2026-05-04 (b) (callback pre-registration),
ADR-005 thread model, Story 1.2 AC2, Story 1.7b-followup.

### Problema endereçado

Apesar dos esforços anteriores (callbacks Noop nos 7 slots,
critério estrito `result=4`, retry policy 2.12), o handshake de
MARKET_DATA permanece travado em `result=1`. O wrapper atual
acopla **em uma única chamada** três responsabilidades distintas:

```
initialize_market_only()  →  internamente chama:
  1. WinDLL load
  2. SetEnabledLogToDebug(0)
  3. DLLInitializeMarketLogin(...)
  4. (NÃO chama wait — está separado)
```

E o caller faz, em sequência:

```
dll.initialize_market_only(...)   # passos 1-3
dll.wait_market_connected(300)    # bloqueia 300s, devolve False
download_chunk(...)               # subscribe_ticker DENTRO do chunk
```

**Hipótese arquitetural reforçada pelo usuário:** a DLL pode
condicionar o handshake `MARKET_DATA → result=4` à presença de
**uma intenção de consumo declarada** (subscribe de ticker) ANTES
do wait. Sem subscribe, a DLL "não sabe" qual feed o cliente
quer, fica em `MARKET_WAITING_TICKETS` (literal: "aguardando
inscrição em ticker"), e nunca progride.

Hoje a sequência é:
```
init → wait (timeout 300s) → subscribe → get_history → unsubscribe
        ↑ stuck aqui em result=1
```

A sequência hipotética correta seria:
```
init → subscribe → wait → get_history → unsubscribe
                  ↑ subscribe DESBLOQUEIA o handshake
```

### Hipóteses arquiteturais avaliadas

| ID  | Hipótese                                                                 | Suporte                                                                 | Avaliação |
|-----|--------------------------------------------------------------------------|-------------------------------------------------------------------------|-----------|
| H-1 | `wait_market_connected` está acoplado dentro do `initialize_market_only` (impede injeção de subscribe entre os dois) | Falso na implementação atual: já estão SEPARADOS (`wrapper.py:472-667` é só init; `wrapper.py:754-857` é só wait). Mas no **fluxo do caller**, init é imediatamente seguido de wait, sem janela para subscribe. | **PARCIAL** — fronteira está separada no wrapper, mas o caller (`download_chunk`) chama subscribe DEPOIS do wait |
| H-2 | `SubscribeTicker` faltando ENTRE init e wait bloqueia o handshake porque a DLL não tem ticket para popular | Coerente com state literal `MARKET_WAITING_TICKETS` (result=1) — nome semântico aponta para "aguardando ticker". Coerente com regra documentada (Story 1.7b-followup): "ProfitDLL não popula trades sem subscribe explícito". | **FORTE** — recomendar mudança |
| H-3 | NoopCallback nos 7 slots faz a DLL recusar handshake porque "callback não responde" | Refutada por amendment (b): exemplo Nelogica passa `None` (mais agressivo) e funciona; Noop é estritamente mais defensivo. | **FRACA** — não-causa |
| H-4 | `SetEnabledLogToDebug(0)` silencia warnings críticos da DLL que indicariam o motivo do não-handshake | Plausível mas não-causa — se warnings da DLL fossem visíveis, daríamos pista; mas habilitar logging é **diagnóstico**, não correção. | **DIAGNÓSTICA** — útil para investigação, não causa-raiz |

**Conclusão arquitetural:** **H-2 é a hipótese mais forte.** O nome
literal do estado (`MARKET_WAITING_TICKETS`) e o requisito documentado
de subscribe-antes-de-history convergem. O subscribe atual em
`download_chunk` chega TARDE — depois do wait que já fracassou.

### Decisão arquitetural

Refatoração em **3 partes** propostas a Dex (implementador, paralelo):

#### 1. Manter separação init/wait (já existente)

`initialize_market_only(key, user, password)` continua fazendo
APENAS: WinDLL + SetEnabledLogToDebug + DLLInitializeMarketLogin.
**NÃO** chamar `wait_market_connected` interno (já é assim — manter).

#### 2. Adicionar método `subscribe_for_handshake(ticker, exchange)`

Novo método público no wrapper, semanticamente distinto de
`subscribe_ticker` (que é chamado dentro de `download_chunk`):

```python
def subscribe_for_handshake(self, ticker: str, exchange: str) -> int:
    """Inscreve ticker ANTES de wait_market_connected.

    Hipótese arquitetural (Amendment 2026-05-04 c): DLL pode
    condicionar handshake MARKET_DATA → result=4 à presença de
    intenção de consumo declarada. Sem subscribe pré-wait, MARKET_DATA
    fica em result=1 (MARKET_WAITING_TICKETS — literal: "aguardando
    ticker"). Este método deve ser chamado entre initialize_market_only
    e wait_market_connected.

    Internamente é a mesma chamada SubscribeTicker; o nome distinto
    documenta a intenção arquitetural. Caller deve fazer
    unsubscribe correspondente quando finalizar (ou reutilizar para
    download_chunk).
    """
```

Implementação trivial: idêntica a `subscribe_ticker`, apenas com
docstring documentando o papel arquitetural.

#### 3. Reordenar fluxo no caller (download_chunk OU camada superior)

**Opção 3a (preferida — caller faz subscribe-handshake):**

Caller (CLI ou Story 1.4 orchestrator) faz:

```python
dll.initialize_market_only(key, user, password)
dll.subscribe_for_handshake(symbol, exchange)   # NOVO
connected = dll.wait_market_connected(timeout=300)
if not connected:
    raise DLLConnectError(...)

# download_chunk pode então pular subscribe interno (já feito) ou
# chamar idempotente (DLL aceita subscribe duplo retornando código
# não-fatal — testar)
result = download_chunk(dll, symbol, exchange, ...)
```

**Opção 3b (fallback — wrapper faz tudo):**

Adicionar parâmetro opcional a `initialize_market_only`:

```python
dll.initialize_market_only(
    key, user, password,
    handshake_ticker=("WDOJ26", "F"),  # NOVO
)
# Internamente: init → subscribe(handshake_ticker) → (caller chama wait)
```

**Recomendação Aria:** **Opção 3a** — preserva separação de
responsabilidades (wrapper expõe primitivas; caller orquestra
sequência). Opção 3b acopla wrapper a "saber o ticker" antes do
download — viola coesão da fronteira `dll/`.

### Conexão com download_chunk

`download_chunk` mantém o `subscribe_ticker → get_history →
unsubscribe` interno **inalterado** — é correto para o caso de
chunks subsequentes (mesmo símbolo, intervalos diferentes; ou
símbolo distinto). A mudança é APENAS adicionar o
**subscribe-handshake inicial** entre init e wait.

Em re-uso (segundo chunk do mesmo símbolo na mesma sessão):
- subscribe-handshake ainda válido na DLL.
- `download_chunk` chama subscribe novamente — DLL retorna código
  não-fatal (já-subscrito) e segue. Comportamento atual já tolera
  isso (`download_chunk` linhas 619-638 trata como WARNING).

### Risco arquitetural

| Risco | Severidade | Mitigação |
|-------|-----------|-----------|
| Subscribe pré-wait pode também travar se DLL ainda não está em estado para aceitar subscribe | MÉDIA | DLL deveria aceitar SubscribeTicker imediatamente após DLLInitializeMarketLogin (não requer MARKET_CONNECTED para enfileirar). Validar no smoke. |
| Caller precisa "saber o ticker" antes do init — quebra fluxo "1 sessão DLL, N símbolos" | BAIXA | OK para MVP (1 símbolo por sessão); para multi-symbol futuro, fazer subscribe de TODOS os símbolos ANTES do wait. |
| Hipótese H-2 errada: subscribe não desbloqueia, apenas adia o problema | MÉDIA | Smoke real é o teste decisivo. Se falhar, próxima hipótese é H-4 (habilitar SetEnabledLogToDebug(1) para ver warnings DLL). |

### Validação requerida (smoke real)

1. Aplicar refatoração (Opção 3a).
2. Smoke 1: `init → subscribe_for_handshake("WDOJ26", "F") → wait_market_connected(timeout=120)`.
   - **Sucesso esperado:** MARKET_DATA progride de `result=1` → `result=4` em <60s.
   - **Falha:** próxima hipótese é H-4 (habilitar log nativo).
3. Smoke 2 (se 1 OK): `download_chunk` completo retorna trades.

### Fallback se hipótese refutada

Se o smoke da Opção 3a falhar, próximos passos arquiteturais:

1. **H-4 ativo:** `SetEnabledLogToDebug(1)` ou remover a chamada —
   capturar warnings nativos da DLL no console.
2. **Audit signature:** verificar que `SubscribeTicker` argtypes/restype
   estão configurados em `_configure_dll_signatures` (CRIT-2).
3. **Consultar Nelo:** signature ou semântica de `result=1` na versão
   da DLL embarcada (`profitdll/`).

### Sign-off

- **Aria (architect):** APPROVED — refatoração proposta para Dex.
  H-2 é a hipótese arquitetural mais forte; teste empírico via
  smoke real é decisivo. Mudança é minor (1 método novo, 1 linha
  no caller), reversível, sem regressão de invariantes.

### Auditor

Dex (próximo agente, paralelo) implementa Opção 3a +
`subscribe_for_handshake` no wrapper. Smoke real é o gate. Quinn
adiciona property test: `subscribe_for_handshake` retorna >=0 antes
de `wait_market_connected` ser chamado em testes de integração.

---

## Amendment 2026-05-04 (d) — NoopCallback × ConnectorThread interaction

**Autor:** 🏛️ Aria (mini-council Aria pós-mortem attempt 7)
**Origem:** Smoke real attempt 7 (`docs/qa/SMOKE_EVIDENCE/1.7b-20260504T220650Z-attempt7-flakey.md`)
falhou com MARKET_DATA travado em `result=1` (MARKET_WAITING_TICKETS) por
600s+, **mesmo após** os fixes de `os.chdir` (Q-DRIFT-10) e
`subscribe_for_handshake` (amendment c). Probe discriminante
(`scripts/probe_init.py`) rodado 28 min após o attempt falhar conectou em
**2.43s** no MESMO horário noturno, mesmo `.env`, mesma DLL, mesmo cwd.
Prova empírica: **bug está no nosso wrapper, não é ambiental**.
**Related:** Amendment (b) (slots Noop vs `None`), Amendment (c)
(subscribe-handshake), Story 1.2 AC2, Q11-E (Sentinel §12 — folclore
"JAMAIS None"), Q-DRIFT-11 (a ser criado por Sol em paralelo).

### Contexto

A análise pós-mortem do attempt 7 (Quinn + Nelo + Aria, 22:10–22:13 BRT)
estabeleceu que a **única variável** entre o caminho que falha (wrapper
completo) e o caminho que conecta (probe minimalista) é o conteúdo dos
slots não-state do `DLLInitializeMarketLogin`:

| Slot | Função     | Wrapper attempt 7 | Probe (sucesso) | Exemplo Nelogica |
|------|------------|-------------------|-----------------|------------------|
| 4    | newTrade   | NoopCallback      | **None**        | **None**         |
| 5    | newDaily   | NoopCallback      | REAL            | REAL             |
| 6    | newHistory | NoopCallback      | **None**        | **None**         |
| 7    | priceBook  | NoopCallback      | **None**        | **None**         |
| 8    | offerBook  | NoopCallback      | **None**        | **None**         |
| 9    | progress   | NoopCallback      | REAL            | REAL             |
| 10   | tinyBook   | NoopCallback      | REAL            | REAL             |

Probe e exemplo oficial Nelogica passam **`None`** em 4 slots não
utilizados. Wrapper passa NoopCallback em todos os 7 — exatamente o que
Q11-E (folclore Sentinel §12) prescrevia como obrigatório.

### Decisão técnica original (Q11-E / ADR-005 baseline)

> "JAMAIS passar `None` nos slots não-state de `DLLInitializeMarketLogin`
> — usar NoopCallback para preservar binding interno da DLL. `None`
> corrompe o registro e faz `Set*Callback` posteriores nunca dispararem,
> sem erro reportado." (`callbacks.py:119-156`, docstring `make_noop_callback`)

Esta diretriz vinha de Sentinel §12, sem evidência empírica direta — era
**folclore** transmitido entre revisões do wrapper.

### Por que estava errada

1. **Sem evidência empírica direta:** Sentinel §12 é narrativa de "semanas
   debugando", não bug-report reproduzível. Nenhum teste registra
   `Set*Callback posterior não disparou após init com None`.
2. **Refutada pelo exemplo oficial:** `profitdll/Exemplo Python/main.py`
   L742-743 passa `None` em 4 slots e funciona em produção há anos.
3. **Refutada empiricamente:** probe `scripts/probe_init.py` conecta em
   1.82–2.43s passando `None` (3 corridas independentes: lab, attempt 7
   pós-mortem, e replay).
4. **NoopCallback NÃO é "estritamente mais defensivo":** ao contrário do
   que o amendment (b) §C concluía, `None` instrui a DLL a NÃO invocar
   nada naquele slot — `funtype(_noop)` instrui a DLL a invocar uma função
   válida (que ignora args). A diferença é load-bearing.

### Hipótese refinada (mecanismo arquitetural)

A `ConnectorThread` interna da ProfitDLL é **single-threaded** (Q07-V,
ADR-005 baseline §"Threads do processo"). Durante o handshake de
`DLLInitializeMarketLogin → MARKET_CONNECTED`, a DLL emite eventos
sequencialmente para múltiplos slots (não apenas state):

- `progress` callback dispara para cada ticker da watchlist inicial
  (cold-start ServerAddr/exchangeinfo2),
- `tinyBook` snapshot inicial,
- `daily` snapshot do dia anterior por ativo,
- ... e SÓ ENTÃO emite `(conn_type=2, result=4)` no slot state.

**Quando o slot é `None`:** a DLL pula a invocação imediatamente
(branch nativo `if (cb_ptr != NULL) cb_ptr(...)`) — `ConnectorThread`
fica livre, próximo evento (incluindo o crítico `MARKET_CONNECTED`) é
despachado em milissegundos.

**Quando o slot é NoopCallback:** a DLL invoca o trampoline ctypes →
ctypes desempacota a struct (`TAssetID` por valor, `TDailyCallback` com
19 args mistos `c_double`/`c_int`/`c_wchar_p`) → adquire GIL → chama o
Python `_noop(*args)` → libera GIL → empacota retorno → continua.
**Cada invocação custa centenas de microssegundos a milissegundos.**
Multiplicado por N tickers da watchlist × M tipos de evento, a
`ConnectorThread` fica saturada por **segundos** drenando trampolines
no-op antes de poder despachar o `result=4`. Nosso `wait_market_connected`
timeout (300s) eventualmente vence — mas o handshake real nunca falha:
está apenas **bufferizado atrás de uma fila de no-ops**.

Isso explica o "flakey" histórico (Q-DRIFT-02): se a watchlist do
servidor tiver poucos tickers naquele momento (final de pregão, dia
sem movimento), o gargalo passa em <60s e parece OK; em horário mais
ativo (cold-start completo), trava. Mesmo `.env`, mesma DLL, mesmo
binário — comportamento depende de **carga de eventos do servidor**,
não de "instabilidade ambiental".

### Implicações para o thread model (ADR-005)

1. **Callback no wrapper já é mínimo absoluto** (`make_state_callback`
   linha 101-109: apenas `state_queue.put_nowait(...)` em
   `contextlib.suppress(Full)`). MANTER. INV-1 / R3 cumprida.
2. **Slots não usados devem ser `None`**, NÃO NoopCallback. Isto
   **inverte** Q11-E.
3. **`_cb_refs` deve reter SOMENTE callbacks reais** — todo callback que
   está em `_cb_refs` é um trampoline ctypes vivo, candidato a ser
   invocado pela `ConnectorThread`. Inflação de `_cb_refs` com no-ops é
   pegada arquitetural (não anti-GC saudável: anti-throughput).
4. **Documentação formal:** `ConnectorThread` é recurso crítico
   single-threaded. Tratá-la como tal — TODA carga colocada em qualquer
   trampoline registrado é serializada e atrasa state events.

### Diretriz arquitetural (NOVA)

> **Nenhum callback ctypes deve ser registrado se não tem trabalho útil
> a fazer.** Slots não consumidos em `DLLInitializeMarketLogin` (e em
> qualquer `Set*Callback` futuro) devem permanecer `None`. NoopCallback
> é anti-padrão: cada invocação serializa a `ConnectorThread` interna
> da DLL, atrasando state events críticos (notadamente
> `MARKET_CONNECTED`).

Esta diretriz vai DIRETO contra Q11-E (Sentinel §12). Q11-E deve ser
**rebaixada** ("REVISAR — provavelmente errada, refutada por probe
2026-05-04") ou **invertida** ("Slots não usados DEVEM ser `None`")
— decisão de @sol (curador de QUIRKS, em paralelo).

### Trade-offs considerados

| Opção                                                             | Vantagem                                                  | Desvantagem                                                                                | Veredicto |
|-------------------------------------------------------------------|-----------------------------------------------------------|--------------------------------------------------------------------------------------------|-----------|
| (A) Manter NoopCallback (status quo Q11-E)                        | Zero mudança, "defesa em profundidade" teórica            | **Reproduz o bug do attempt 7 — falha real em produção**                                   | REJEITADA |
| (B) Trocar NoopCallback por `None` nos 4 slots não usados         | Alinhado com probe + exemplo oficial; ConnectorThread livre | Inverte folclore Q11-E (mas Q11-E refutada empiricamente)                                | **ESCOLHIDA** |
| (C) Manter NoopCallback mas com bodies vazios em C (sem trampoline) | Throughput máximo                                         | Requer DLL helper externa; viola ADR-001 (pure Python no wrapper); over-engineering        | REJEITADA |
| (D) Inverter Q11-E para "JAMAIS NoopCallback"                     | Diretriz forte e clara                                    | Pode haver casos legítimos de Noop futuros (ex.: state callback dummy em testes mockados)  | PARCIAL   |

**Decisão final:** (B) para os 4 slots não usados em
`DLLInitializeMarketLogin` (trade/history/priceBook/offerBook); diretriz
geral (D-suavizada): "Nenhum callback ctypes registrado sem trabalho
útil — Noop apenas em mocks de teste, nunca em path de produção".

### Validação pendente

- **Story 1.7c (owner @dev / Dex, em paralelo):** implementar variante
  bisseccional `minimal_handshake=True` no `initialize_market_only` que
  passa `None` nos 4 slots (4, 6, 7, 8) e mantém NoopCallback nos demais
  (5, 9, 10) — **igualando exatamente** a configuração do probe. Smoke
  real deve confirmar handshake em <60s. Sucesso ⇒ esta hipótese
  ratificada; falha ⇒ próxima hipótese (Nelo: signature drift em
  `DLLInitializeMarketLogin`, ou Sol: `SetEnabledLogToDebug(0)` mascarando
  warnings nativos).
- **Story 1.7c bisseção secundária:** se `minimal_handshake=True` passa,
  testar `None` em TODOS os 7 slots não-state (igualar Probe completo).
  Diferença esperada: 0 (já estava isolado em 4 slots).
- **Quinn:** property-test que enumera `_cb_refs` durante init e
  confirma que SOMENTE callbacks reais (state + os 3 com trabalho útil)
  estão presentes — nunca NoopCallback em path produção.

### Riscos residuais

| Risco | Severidade | Mitigação |
|-------|-----------|-----------|
| State callback (real) também tiver corpo pesado | BAIXA | Já é `put_nowait` em fila bounded — INV-1 cumprida; teste `test_state_callback_only_put_nowait` confirma `mock_calls == []` no body. |
| Daily/progress/tinyBook callbacks "reais" também serializam ConnectorThread | MÉDIA | Eles SÃO úteis (consumidores existem). Aplicar mesma disciplina: corpo APENAS `put_nowait`; consumidor em thread Python. Mitigação preventiva, não nova arquitetura. |
| `Set*Callback` posterior (e.g. `SetHistoryTradeCallbackV2`) NÃO funcionar após init com `None` no slot 8 (folclore Q11-E real) | BAIXA | Probe não testou isso, mas exemplo Nelogica L745-761 faz exatamente esse padrão (init com `None` no slot 8 → `SetTradeCallbackV2` posterior). Se acontecer no smoke 1.7c, fallback é re-introduzir NoopCallback APENAS no slot 8 (history) e manter `None` nos outros 3 — bisseção fina. |
| Inversão de Q11-E confunde futuros agentes que leem Sentinel §12 sem ler ADR-005 | BAIXA | Sol cria Q-DRIFT-11 referenciando este amendment; QUIRKS.md vira fonte de verdade primária; Sentinel §12 é arquivo histórico. |

### Constitucionalidade

- **Article IV (No Invention):** este amendment NÃO inventa
  funcionalidade — refuta uma diretriz prévia (Q11-E) com evidência
  empírica direta (probe, attempt 7, exemplo oficial). Toda afirmação
  rastreia para arquivo citado (`probe_init.py`, attempt 7 evidence,
  `main.py:742-743`).
- **Article V (Quality First):** sign-off requer Story 1.7c smoke
  validation; sem smoke, este amendment é **HIPÓTESE
  ARQUITETURAL**, não decisão ratificada.

### Sign-off

- **Aria (architect):** APPROVED como **hipótese arquitetural** com
  validação requerida pela Story 1.7c. Refutação de Q11-E é
  empiricamente sólida (3 corridas de probe + exemplo oficial); o
  mecanismo proposto (ConnectorThread saturada por trampolines no-op)
  é coerente com state literal `MARKET_WAITING_TICKETS` e com o "flakey"
  histórico (carga variável da watchlist do servidor).

### Auditor

- **@dev / Dex (Story 1.7c, paralelo):** implementa
  `minimal_handshake=True` e roda smoke. Resultado vira ratificação ou
  refutação deste amendment.
- **@sol (Q-DRIFT-11, paralelo):** documenta a interação
  NoopCallback × ConnectorThread como quirk formal e rebaixa Q11-E.
- **@qa / Quinn:** property-test sobre `_cb_refs` (apenas reais em
  produção); smoke real ratifica.

### Cross-links

- Evidência primária: `docs/qa/SMOKE_EVIDENCE/1.7b-20260504T220650Z-attempt7-flakey.md`
  (seção "Análise Pós-Mortem", 22:10–22:13 BRT).
- Probe canônico: `scripts/probe_init.py` (commit `3ef7699`).
- Quirk derivado: `docs/dll/QUIRKS.md` Q-DRIFT-11 (a ser criado por
  @sol em paralelo).
- Story de validação: `docs/stories/1.7c.story.md` (a ser criada por
  @dev em paralelo).
- Folclore refutado: `docs/dll/QUIRKS.md` Q11-E (Sentinel §12).
- Amendment relacionado: este ADR-005 amendment (b) §C
  ("Slots de callback no init") — esta sessão **inverte** a conclusão
  daquela seção.

---

## Amendment 2026-05-12 — R3 amended para o callback V2 de trade histórico (Q-DRIFT-40)

**Status:** ACCEPTED — mini-council Nelo + Aria (COUNCIL-38 decisão 2), modo autônomo v1.2.0.

**Origem:** RCA `translate_failures` (~0.01% de trades históricos perdidos —
ex.: 261 / 2.86M). Causa raiz: o callback V2 (`make_history_trade_callback_v2`)
fazia `put_nowait((handle, flags))` e o `TranslateTrade(handle)` era feito
DEPOIS no `_IngestorThread`. Mas o `handle` (`a_pTrade` de
`TConnectorTradeCallback`) só é válido **dentro do escopo do callback** — a DLL
recicla/libera o buffer interno do pacote ao retornar. Com ~2.86M trades
enfileirados, ~0.01% dos handles ficavam stale → `PopulateTradeV0` lia freed
memory → access violation interna SILENT MODE → `TranslateTrade` rc!=0 →
`translate_trade()` → `None` → trade perdido. O exemplo oficial Nelogica
(`profitdll/Exemplo Python/main.py` L325-333, `CallbackHandlerU.pas`
L473-497) chama `TranslateTrade` **síncrono dentro do callback** — esse é o
contrato. Ver `docs/dll/QUIRKS.md` Q-DRIFT-40.

**Decisão:** R3 ("nenhuma chamada à DLL dentro de callback; callback faz apenas
`queue.put_nowait()`") é **amended** para o callback V2 de trade histórico
(`SetHistoryTradeCallbackV2`):

> **R3 (amended v1.2.0):** o callback V2 de trade histórico chama
> `TranslateTrade(handle, byref(struct))` DENTRO do callback (obrigatório pela
> semântica transiente do `handle`) e enfileira o `TradeFields` JÁ COPIADO —
> nunca o handle. `TranslateTrade` é ~µs (a DLL só copia campos do buffer
> interno para o struct out); não bloqueia a ConnectorThread perceptivelmente.
> `AgentResolver` / format de timestamp / construção de `TradeRecord`
> continuam no `_IngestorThread` (cool path). O callback continua **sem
> logs / I/O / acesso a `self`**.

**Escopo da amendment:** ESTRITAMENTE o callback V2 de trade histórico (e, por
simetria, o trade live V2 — `SetTradeCallbackV2` — se vier a ser consumido).
Todos os demais callbacks (state, progress, daily, tinyBook, offerBook, ...)
permanecem sob R3 original — `put_nowait` only. INV-1 ("nenhuma chamada à DLL
dentro de callback") é especializada do mesmo jeito: o callback V2 de trade
pode chamar `TranslateTrade` (e somente `TranslateTrade`); nada mais.

**Consequências:**
- `translate_failures` / `nl_errors` de trade histórico esperados → ~0 (sem
  handle stale → sem AV → `TranslateTrade` não retorna mais lixo).
- Métrica `completeness_pct` por chunk (= trades / (trades + nl_errors) * 100)
  logada em `download.complete` / `orchestrator.chunk_complete` + gauge
  Prometheus `download_chunk_completeness_pct`. < 99.99% dispara retry do
  chunk no orchestrator (max 2 retries — classificado AMBIGUOUS, não falha).
- Os counters `translate_nl_errors` / `translate_invalid_price_skips` /
  `queue_dropped` agora são incrementados IN-CALLBACK (dict mutável,
  incrementos GIL-atômicos — single bytecode, não bloqueia ConnectorThread).
  O `_IngestorThread` mantém só os counters residuais de defense-in-depth.

**Cross-links:**
- Quirk: `docs/dll/QUIRKS.md` Q-DRIFT-40.
- Impl: `src/data_downloader/dll/callbacks.py::make_history_trade_callback_v2`,
  `src/data_downloader/orchestrator/download_primitive.py` (`_IngestorThread`,
  `ChunkResult`, `download_chunk`), `src/data_downloader/orchestrator/orchestrator.py`
  (hook retry-on-completeness + gauge).
- Evidência: `Erro.log` Pichau 2026-05-12 (COUNCIL-38 H-B); exemplo Nelogica.
- Plano: `docs/qa/V1.2.0-PLAN.md` (Wave 1 → Nelo-C + decisão 2).
