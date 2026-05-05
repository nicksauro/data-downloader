# ADR-015 — Multiprocess catalog coordination (broker process)

**Status:** REVOKED 2026-05-05
**Aceito em:** 2026-05-03 — Aria
**Revogado em:** 2026-05-05 — Aria (mini-council pós-confirmação Pichau)
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💾 Sol, ⚡ Pyro, 🗝️ Nelo
**Related:** ADR-002 (storage), ADR-005 (thread model), ARCHITECTURE.md §2.4, PLAN_REVIEW C9 + H20
**Superseded by:** ADR-022 (Single-Session Sequential Download Policy)

---

## Revogação (2026-05-05)

> **Status:** REVOKED. Mantido neste repositório como histórico arquitetural — não usar como fonte de verdade ativa. **Toda decisão de multi-symbol em V1.0.0+ é regida pelo ADR-022.**

### Motivo

A premissa fundacional deste ADR — **Hipótese A: "1 chave de licença Nelogica permite N conexões DLL simultâneas, uma por processo"** — foi **falsificada empiricamente em 2026-05-05** pelo dono do produto (Pichau, autoridade máxima):

> "A licença Nelogica é single-session — não permite 2 instâncias conectadas simultaneamente com a mesma chave."

Isso mata a Opção A (broker process + N workers DLL paralelos). Não é um detalhe ajustável: o vendor enforça single-session no servidor de licenciamento. A segunda conexão recebe `NL_LICENSE_BUSY` (ou equivalente) e é derrubada.

### Hipótese vencedora (Q17-OPEN → CLOSED)

A Hipótese B do COUNCIL-25 prep (1 processo + DLL única, multi-symbol via subscribe múltiplo) é a única factível dentro da licença atual. Ver ADR-022 para a política definitiva: **`for symbol in symbols: download_chunk(...)` SERIAL em 1 processo**, simplicidade preferida sobre IPC complexo (DLL é o gargalo de qualquer forma single-session — paralelismo entre símbolos não traz throughput adicional).

### Supersede

- **ADR-022** (Single-Session Sequential Download Policy) é a fonte de verdade para multi-symbol em V1.0.0+.
- Toda referência cruzada a "ADR-015" em docs/stories/qa/code-comments deve ser lida como "REVOKED — ver ADR-022".

### Impacto downstream

| Artefato | Impacto |
|----------|---------|
| Stories 4.1, 4.1-followup, 4.2-followup | Deprecated por @po (Pax) em paralelo a esta revogação |
| `src/data_downloader/orchestrator/broker/` (5 módulos: pool/catalog_broker/worker_client/master/protocol) | Código órfão — agendar remoção em Story 4.X-cleanup ou manter como dead-code documentado até decisão de @po + @dev |
| `docs/ARCHITECTURE.md` §2.4, §6, Change Log | Pede amendment 1.1.2 redirecionando broker → ADR-022 (será endereçado em handoff a Sol/Aria follow-up) |
| `docs/epics/EPIC-4-multi-asset-api.md` | Premissa "broker dedicado" cai; @pm reabre escopo Epic 4 — multi-symbol é commodity (loop), não feature arquitetural |
| `docs/qa/AUDIT_REPORTS/4.1-design-2026-05-04.md`, `WAIVERS/4.1-real-smoke-deferred-2026-05-04.md` | Tornam-se evidência histórica; auditoria 4.1 passa a ser N/A pelo cancelamento da story |
| `scripts/probe_multi_process_license.py` | Probe **confirmou** Hipótese B; preservar como evidência de Q17-OPEN→CLOSED |

### Observação para o histórico

A análise técnica deste ADR (broker process + mp.Queue + ACK + WAL coordination) **continua arquiteturalmente correta** para o problema teórico que ela resolve. O que mudou foi a **restrição de licenciamento** (não-arquitetural) que tornou o problema irrelevante. Se em futuro distante a Nelogica oferecer licenças multi-session, este ADR pode ser ressuscitado com supersede inverso. Não é um defeito de raciocínio — é um defeito de premissa de mercado.

---

## Contexto

A spec original de **multi-symbol** (Epic 4) é: **N processos**, cada um com 1 instância da ProfitDLL (limite Nelógica = 1 conexão DLL por processo). Cada processo escreve no mesmo filesystem (catálogo SQLite + Parquet).

Sol levantou **C9 (CRITICAL)**:
> **Multi-symbol viola SQLite WAL** — N processos = 1 writer ativo permitido + readers; spec atual gera `SQLITE_BUSY`.

SQLite WAL permite **N readers simultâneos + 1 writer**. Quando 2+ processos tentam escrever, o segundo recebe `SQLITE_BUSY` (timeout default 5s, depois exception). Em pior caso (escritas frequentes), todo um processo trava esperando lock.

Pyro adicionou **H20**: subprocess.spawn em Windows = 2.7-10s overhead. Multi-symbol pode não compensar para downloads curtos.

Restrições:
- **1 DLL = 1 processo** (Nelógica). Não negociável.
- **Catálogo é fonte única de verdade** (INV-6) — 1 banco SQLite, não N.
- **Parquet é fan-out** — diferentes símbolos vão para diretórios diferentes; sem contention.
- **Reader-friendly** — DuckDB queries devem funcionar sempre (UI lê catálogo enquanto download roda).

---

## Opções Consideradas

### Opção A — Broker process: 1 master mantém SQLite write lock; subprocessos enviam mutações via `multiprocessing.Queue`

```
┌──────────────────────────────────────┐
│ Master Process (UI + Coordinator)    │
│  - PySide6 MainWindow                │
│  - SQLite catalog WRITE owner (único)│
│  - multiprocessing.Queue receiver    │
└────┬─────────────────────────────────┘
     │
     │ stdin/Queue (catalog mutations)
     ▼
 ┌────────┐   ┌────────┐   ┌────────┐
 │Worker 1│   │Worker 2│   │Worker N│
 │WDOJ26  │   │WINH26  │   │PETR4   │
 │ DLL    │   │ DLL    │   │ DLL    │
 │ Parquet│   │ Parquet│   │ Parquet│
 │ (write)│   │ (write)│   │ (write)│
 │ catalog│   │ catalog│   │ catalog│
 │ (read- │   │ (read- │   │ (read- │
 │  only) │   │  only) │   │  only) │
 └────────┘   └────────┘   └────────┘
```

- Workers escrevem **Parquet diretamente** (paths não overlap — sem contention).
- Workers **leem** SQLite catalog (R/O) para verificar idempotência.
- Workers **enviam mutações** (`register_partition`, `mark_chunk_done`) ao master via `multiprocessing.Queue`.
- Master serializa todas as escritas SQLite — zero `SQLITE_BUSY`.
- Master emite ACKs via outra Queue para workers confirmarem persistência.

### Opção B — Sharded catalogs: 1 SQLite por símbolo

```
data/history/
├── F/WDOJ26/
│   ├── catalog.db        # só sobre WDOJ26
│   └── 2026/03.parquet
├── F/WDOH26/
│   ├── catalog.db        # só sobre WDOH26
```

- Cada processo dono do seu catálogo.
- Sem coordenação inter-processo.
- Master agrega via UNION em DuckDB ou via "meta-catalog" leve.

### Opção C — `SQLITE_BUSY` retry com exponential backoff

- Manter 1 catálogo único.
- Cada writer faz retry quando vê BUSY.
- WAL ajuda; commits curtos.

### Opção D — Postgres ou outro DB cliente-servidor

- Resolveria contention completamente.
- Adiciona dep externa (não-12-factor para desktop app).
- Overkill para caso V1 (single-user).

---

## Análise

| Critério | A (broker) | B (sharded) | C (retry) | D (Postgres) |
|---------|-----------|-------------|-----------|--------------|
| Resolve SQLITE_BUSY | ✅ | ✅ | parcial | ✅ |
| INV-6 mantida (catálogo única fonte) | ✅ | ❌ | ✅ | ✅ |
| DuckDB query simples cross-symbol | ✅ | UNION manual | ✅ | ✅ |
| Latência catalog write | +IPC (~100µs) | nativo | retry overhead | rede |
| Falha tolerância (worker crash) | ACK detecta | sharding salva | resilient | resilient |
| Esforço de implementação | médio-alto | médio | baixo | alto |
| Onboard / install | nenhum | nenhum | nenhum | servidor extra |

**Pontos críticos:**

- **Opção D** viola simplicidade para single-user desktop. Inviável V1.
- **Opção C** mascara o problema; sob carga real (N=10 símbolos com chunks paralelos), retries acumulam latência e podem timeout. Pyro vetou.
- **Opção B** quebra INV-6 (catalog é única fonte) — DuckDB queries cross-symbol viram problema. Reconciliação fica perigosa. **Rejeitada.**
- **Opção A** preserva INV-6, elimina contention, e adiciona overhead aceitável (~100µs IPC por mutation, vs ~10ms latência de Parquet write). **Escolhida.**

---

## Decisão

**Opção A — Broker process: master mantém write lock SQLite; workers enviam mutações via `multiprocessing.Queue` (com ACK).**

### Arquitetura

```
┌────────────────────────────────────────────────────┐
│ Master Process                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │ UI (PySide6)                                 │  │
│  │ Coordinator (subprocess pool manager)        │  │
│  │ Catalog Owner Thread                         │  │
│  │  ↳ Possui write conn SQLite                  │  │
│  │  ↳ Loop: drain mutation_queue → tx → ACK     │  │
│  └──────────────────────────────────────────────┘  │
└──────────┬─────────┬─────────┬─────────────────────┘
           │         │         │
   mp.Queue│ mp.Queue│ mp.Queue│
   (mut +  │ (mut +  │ (mut +  │
    ack)   │  ack)   │  ack)   │
           │         │         │
           ▼         ▼         ▼
       ┌────────┐┌────────┐┌────────┐
       │Worker 1││Worker 2││Worker N│
       │ DLL    ││ DLL    ││ DLL    │
       │ Parquet││ Parquet││ Parquet│
       │ writes ││ writes ││ writes │
       │ direto ││ direto ││ direto │
       │        ││        ││        │
       │ Catalog││ Catalog││ Catalog│
       │  R/O   ││  R/O   ││  R/O   │
       │ (idem- ││ (idem- ││ (idem- │
       │ check) ││ check) ││ check) │
       └────────┘└────────┘└────────┘
```

### Mutation protocol

```python
# src/data_downloader/orchestrator/catalog_broker.py

from dataclasses import dataclass
from multiprocessing import Queue
from typing import Literal


@dataclass(frozen=True)
class CatalogMutation:
    """Mutação atômica enviada do worker ao master."""
    op: Literal['register_partition', 'mark_chunk_done', 'mark_chunk_pending', 'reconcile']
    job_id: str
    payload: dict
    request_id: str   # uuid para correlacionar ACK


@dataclass(frozen=True)
class CatalogAck:
    """ACK do master após persistência."""
    request_id: str
    status: Literal['committed', 'rejected', 'error']
    error: str | None = None
```

### Master (Catalog Owner Thread)

```python
class CatalogOwner:
    """Thread no master process que serializa todas as escritas SQLite."""

    def __init__(self, db_path: Path, mutation_queue: Queue, ack_queues: dict[str, Queue]):
        self.conn = sqlite3.connect(str(db_path), isolation_level=None)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.mutation_queue = mutation_queue
        self.ack_queues = ack_queues
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                mut: CatalogMutation = self.mutation_queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self._apply(mut)
                ack = CatalogAck(request_id=mut.request_id, status='committed')
            except Exception as e:
                ack = CatalogAck(request_id=mut.request_id, status='error', error=str(e))
            self.ack_queues[mut.job_id].put(ack)

    def _apply(self, mut: CatalogMutation):
        if mut.op == 'register_partition':
            self.conn.execute('INSERT INTO partitions ...', mut.payload)
        elif mut.op == 'mark_chunk_done':
            self.conn.execute('UPDATE chunks SET status=? WHERE id=?', ('done', mut.payload['chunk_id']))
        ...
        self.conn.commit()
```

### Worker (subprocess)

```python
class CatalogClient:
    """Stub no worker — envia mutações + aguarda ACK."""

    def __init__(self, mutation_queue: Queue, ack_queue: Queue, job_id: str):
        self.mutation_queue = mutation_queue
        self.ack_queue = ack_queue
        self.job_id = job_id

    def register_partition(self, symbol: str, path: str, ...) -> None:
        request_id = uuid.uuid4().hex
        mut = CatalogMutation(
            op='register_partition',
            job_id=self.job_id,
            payload={'symbol': symbol, 'path': path, ...},
            request_id=request_id,
        )
        self.mutation_queue.put(mut)
        ack = self._wait_for_ack(request_id, timeout=10)
        if ack.status != 'committed':
            raise IntegrityError(f'Catalog rejected mutation: {ack.error}')

    def _wait_for_ack(self, request_id: str, timeout: float) -> CatalogAck:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ack = self.ack_queue.get(timeout=0.5)
            if ack.request_id == request_id:
                return ack
            else:
                # ACK fora de ordem — re-enfileira
                self.ack_queue.put(ack)
        raise TimeoutError(f'No ACK for request {request_id}')
```

### Worker leitura (R/O)

```python
# Workers podem abrir SQLite em modo read-only para checar idempotência
# (sem race com master — WAL permite múltiplos readers)

def is_chunk_already_done(chunk_id: str) -> bool:
    conn = sqlite3.connect(str(catalog_path) + '?mode=ro&immutable=0', uri=True)
    row = conn.execute('SELECT status FROM chunks WHERE id=?', (chunk_id,)).fetchone()
    conn.close()
    return row is not None and row[0] == 'done'
```

### Performance

- **Mutation latency:** ~100-500µs (mp.Queue IPC + SQLite commit). Aceitável: chunks duram segundos.
- **Throughput:** master commit ~5000 tx/s sustentado em SSD. Suficiente para N=20 workers escrevendo 1 chunk/min cada.
- **Backpressure:** se mutation_queue encher, worker bloqueia (RPC sync). Aceitável: master é prioridade.

### Crash recovery

- **Worker crash:** master detecta via subprocess monitor; partições parciais (`pending_commit`) são reconciliadas (script de cleanup).
- **Master crash:** UI fecha; em restart, lê SQLite WAL e reconciliação automática (Story 1.5).
- **Parquet `.tmp` órfão:** cleanup em startup.

### Multi-symbol single-process fallback (V1)

V1 (Epic 1-3) = single-process. Catalog é local; sem broker. CatalogClient e CatalogOwner são abstrações que coalescem para chamada direta SQLite no mesmo processo.

```python
class LocalCatalogClient(CatalogClient):
    """V1: chama SQLite direto, sem IPC."""
    def register_partition(self, ...):
        self.conn.execute(...)
        self.conn.commit()
```

V2 (Epic 4): substitui por `MultiprocessCatalogClient` (este ADR). Interface igual; Aria garante via Protocol.

### H20: subprocess overhead em Windows

H20 (Pyro): `multiprocessing.Process` em Windows = 2.7-10s spawn overhead. Para downloads curtos (1 símbolo, 1 dia), single-process é mais rápido.

**Mitigação:**
- **Pool persistente:** master mantém pool de N workers prontos (aquecidos), reusa entre jobs.
- **Threshold:** se total estimado <30s, usar single-process. Se >>30s ou multi-symbol, usar broker.
- Pyro mede em `bench_multi_symbol_overhead` (Story 1.4.5 + Epic 4).

---

## Consequências

### Positivas
- **Zero SQLITE_BUSY** em multi-symbol.
- **INV-6 preservada** — 1 catálogo único.
- **DuckDB queries simples** (cross-symbol UNION trivial).
- **Crash isolation** — worker crash não derruba master.
- **V1 → V2 path claro** — Protocol em V1 antecipa V2.

### Negativas
- **Esforço de implementação** — broker thread + Queue protocol + ACK correlation. Epic 4 absorve.
- **Latência adicional** — ~100-500µs por mutation. Aceitável (chunks são segundos).
- **Spawn overhead Windows** — pool persistente mitiga; threshold logic decide.
- **Complexidade debug** — multi-process tem stack traces espalhados.

### Neutras
- Pyro valida com `bench_multi_symbol_throughput` (Epic 4).

---

## Validações requeridas

- [ ] Aria valida Protocol `CatalogProtocol` (este ADR; ARCHITECTURE.md §6 amendment)
- [ ] Sol valida schema SQLite + WAL pragmas (Story 0.0)
- [ ] Pyro `bench_multi_symbol_overhead` define threshold single-vs-multi (Story 1.4.5)
- [ ] Pyro `bench_multi_symbol_throughput` valida sem SQLITE_BUSY (Epic 4)
- [ ] Quinn property test: N workers escrevendo concorrentemente → catálogo consistente (Epic 4)
- [ ] Quinn smoke: 5 símbolos paralelos → todos completam sem erro (Epic 4)
- [ ] Documentação em `docs/dev/MULTIPROCESS.md` (Aria + Sol)
