# ARCHITECTURE — data-downloader

> Snapshot vivo da arquitetura. Mantido por Aria. Mudanças exigem ADR.

**Versão:** 1.1.0
**Data:** 2026-05-03
**Maintainer:** 🏛️ Aria

---

## 1. Visão de Camadas

```
                        ┌──────────────────────────┐
                        │ 🖼️ ui/  (PySide6)        │ ← Felix
                        │ - main_window            │
                        │ - screens/               │
                        │ - adapters/ (QThread)    │
                        └────────────┬─────────────┘
                                     │ signals/slots (QueuedConnection)
                        ┌────────────┴─────────────┐
                        │ 🔵 public_api/           │ ← Aria + Dex (SemVer)
                        │ - download(s, a, b)      │
                        │ - history.read(...)      │
                        └────────────┬─────────────┘
                                     │
        ┌──────────────┬─────────────┼──────────────┬───────────────┐
        │              │             │              │               │
┌───────┴──────┐ ┌─────┴───────┐ ┌──┴──────────┐ ┌─┴─────────┐ ┌──┴──────┐
│ 💻 cli/      │ │ 🟣 orchestr.│ │ 💾 storage/ │ │ 🗝️ dll/   │ │ utils/  │
│              │ │             │ │             │ │           │ │         │
│ typer cmds   │ │ chunker     │ │ parquet_w   │ │ wrapper   │ │ logger  │
│              │ │ calendar    │ │ duckdb_r    │ │ callbacks │ │ time    │
│              │ │ contracts   │ │ catalog     │ │ types     │ │         │
│              │ │ retry       │ │ dedup       │ │ errors    │ │         │
└──────────────┘ └─────────────┘ └─────────────┘ └───────────┘ └─────────┘
                                       │              │
                                       │              │ ctypes
                                       │              ▼
                                       │      ┌───────────────┐
                                       │      │ ProfitDLL.dll │
                                       │      │ (Nelogica)    │
                                       │      └───────────────┘
                                       ▼
                          ┌──────────────────────────┐
                          │ FILESYSTEM               │
                          │ data/history/{...}.parquet
                          │ data/_internal/catalog.db│
                          └──────────────────────────┘
```

**Ownership:**
- 🗝️ **Nelo**: `dll/` (audit). Implementação por Dex.
- 💾 **Sol**: `storage/`, schema, catálogo, contratos. Implementação por Dex (com audit Sol).
- 🟣 **Dex**: `orchestrator/`, `cli/`, `dll/` (impl).
- 🔵 **Aria + Dex**: `public_api/` (Aria desenha interface, Dex implementa).
- 🖼️ **Felix**: `ui/`. UX por Uma.

---

## 2. Thread Model (CRÍTICO)

> Lei R3 do MANIFEST: **callback DLL = `queue.put_nowait()` apenas**.

### 2.1 Threads no processo

| # | Thread | Owner | Faz | NÃO pode |
|---|--------|-------|-----|----------|
| 1 | **MainThread (Qt)** | PySide6 | Eventos UI, slots Qt | Bloquear (>16ms); chamar DLL |
| 2 | **ConnectorThread** | ProfitDLL | Dispara callbacks | Ser controlada por nós |
| 3 | **IngestorThread** | orchestrator | Drena `dll_queue` → valida → repassa para `write_queue` | Chamar DLL |
| 4 | **WriterThread** | storage | Drena `write_queue` → escreve Parquet → atualiza catálogo | Chamar DLL |
| 5 | **OrchestratorThread** | orchestrator | Loop chunking, dispara `GetHistoryTrades`, retry | Bloquear UI |

### 2.2 Filas (todas bounded)

| Fila | Capacidade | Política overflow | Produtor → Consumidor |
|------|-----------|-------------------|------------------------|
| `dll_queue` | 10_000 | **block** | ConnectorThread → IngestorThread |
| `write_queue` | 5_000 | **block** | IngestorThread → WriterThread |
| `ui_progress_queue` | 100 | **drop-oldest** | OrchestratorThread → MainThread (via Qt signal) |

**Razão da política:** download cria back-pressure quando disco é mais lento que callbacks. `block` na ingestão é correto — segura a fila DLL, que segura a ConnectorThread, que naturalmente reduz throughput de chamadas. Para UI, drop-oldest evita acúmulo de progressos obsoletos.

### 2.3 Diagrama

```
ProfitDLL ConnectorThread
  │
  │ callback (put_nowait, block se cheio)
  ▼
┌─────────────┐     IngestorThread
│ dll_queue   │────► drain → validate → enqueue
│ size 10000  │            │
│ block       │            ▼
└─────────────┘     ┌──────────────┐     WriterThread
                    │ write_queue  │────► drain → batch → Parquet append → SQLite update
                    │ size 5000    │            │
                    │ block        │            └─► emit progress event
                    └──────────────┘
                           │
                           ▼
                    ┌──────────────────┐
                    │ ui_progress_queue│   (drop-oldest, size 100)
                    │ → Qt signal      │
                    └─────────┬────────┘
                              │ QueuedConnection
                              ▼
                       MainThread (Qt)
                       - update progress bar
                       - update log view
```

### 2.4 Multi-symbol (Epic 4+)

Cada DLL exige processo próprio (limite Nelogica — 1 conexão por processo). Multi-symbol = N processos via `multiprocessing`, não N threads na mesma DLL.

```
┌──────────────────────────────────┐
│ Master Process (UI + coord)      │
│ - PySide6 MainWindow             │
│ - Subprocess pool manager        │
└──────┬─────────┬─────────┬───────┘
       │         │         │
       ▼         ▼         ▼
   ┌──────┐ ┌──────┐  ┌──────┐
   │Proc 1│ │Proc 2│  │Proc N│
   │WDOJ26│ │WINH26│  │PETR4 │
   │ DLL  │ │ DLL  │  │ DLL  │
   └──────┘ └──────┘  └──────┘
       │         │         │
       └─────────┴─────────┘
                 │
                 ▼
          shared filesystem
          (catálogo SQLite via WAL)
```

Validação por Pyro `*multi-symbol-bench` (Epic 2). Coordenação inter-process detalhada em ~~ADR-015 (Multiprocess catalog coordination)~~ — broker process serializa escritas SQLite via `multiprocessing.Queue` para evitar `SQLITE_BUSY`.

> **AMENDMENT 2026-05-05 (pendente formalização v1.1.2):** ADR-015 foi **REVOKED 2026-05-05** após confirmação do dono do produto que a licença Nelogica é single-session (não permite N conexões simultâneas com a mesma chave). Multi-symbol em V1.0.0+ é **serial em 1 processo** conforme **ADR-022 (Single-Session Sequential Download Policy)**. O diagrama acima e a referência a broker process são histórico — não usar como fonte de verdade ativa. Ver `docs/adr/ADR-022-single-session-sequential-policy.md`.

---

## 3. Public API (Fronteira SemVer)

> `src/data_downloader/public_api/` — Aria desenha; Dex implementa; SemVer separado.

### 3.1 Funções V1 propostas

```python
# src/data_downloader/public_api/download.py

from dataclasses import dataclass
from collections.abc import Iterator
from datetime import date

@dataclass(frozen=True)
class DownloadProgress:
    total: int          # nº de chunks
    done: int           # chunks concluídos
    message: str        # humano (microcopy de Uma)
    trades_received: int

@dataclass(frozen=True)
class DownloadResult:
    job_id: str         # UUID
    symbol: str
    exchange: str
    actual_start: date
    actual_end: date
    trades_count: int
    partitions: list[str]  # paths Parquet escritos
    duration_seconds: float

def download(
    symbol: str,
    start: date,
    end: date,
    *,
    exchange: str = 'F',
    stream: bool = False,
) -> DownloadResult | Iterator[DownloadProgress]:
    """
    Baixa histórico de trades para `symbol` no intervalo [start, end].

    Idempotente: re-rodar é no-op (não duplica).

    Args:
        symbol: ticker DLL (ex: 'WDOJ26'). Use `vigent_contract()` para resolver.
        start: data inicial (inclusive).
        end: data final (inclusive).
        exchange: 'F' (BMF) ou 'B' (Bovespa). Default 'F'.
        stream: se True, retorna iterador de DownloadProgress.

    Returns:
        DownloadResult (stream=False) ou Iterator[DownloadProgress] (stream=True)

    Raises:
        DLLInitError: chave de licença inválida ou DLL não conecta.
        InvalidContract: símbolo não é contrato vigente.
        DiskFull: erro de IO.
    """
    ...
```

```python
# src/data_downloader/public_api/history.py

import duckdb
import pyarrow as pa
from datetime import datetime

def read(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    exchange: str = 'F',
    columns: list[str] | None = None,
) -> pa.Table:
    """
    Lê trades históricos de `symbol` no intervalo via DuckDB.

    Args:
        symbol: contrato (ex: 'WDOJ26')
        start, end: BRT naive (lei R7)
        exchange: 'F' ou 'B'
        columns: colunas a retornar; None = todas

    Returns:
        pyarrow.Table ordenada por timestamp_ns ASC

    Garantias:
        - Sem duplicatas (lei R5)
        - Ordenado por timestamp
        - Schema versionado (campo schema_version no metadata)
    """
    ...

def read_continuous(
    symbol_root: str,
    start: datetime,
    end: datetime,
    *,
    exchange: str = 'F',
) -> pa.Table:
    """
    Como read(), mas concatena contratos vigentes ao longo do intervalo
    (ex: WDOH26 + WDOJ26 + WDOK26 conforme rollover).
    """
    ...

def vigent_contract(
    symbol_root: str,
    on_date: date,
    *,
    exchange: str = 'F',
) -> str:
    """
    Resolve contrato vigente. Ex: vigent_contract('WDO', date(2026,3,15)) → 'WDOJ26'

    Fonte: docs/storage/CONTRACTS.md (mantido por Sol).
    """
    ...
```

### 3.2 SemVer Policy (lei R4 + R15)

| Mudança | Bump | Exemplo |
|---------|------|---------|
| Bug fix sem mudar interface | PATCH | 1.0.0 → 1.0.1 |
| Função nova; campo novo opcional | MINOR | 1.0.0 → 1.1.0 |
| Renomear/remover função; mudar tipo de campo | MAJOR | 1.0.0 → 2.0.0 |

**v0.x.x** — foundation em construção. Breaking changes sem major bump são tolerados (documentados em CHANGELOG).

---

## 4. Invariantes Arquiteturais

> Toda implementação deve preservar. Quinn audita via testes.

| # | Invariante | Auditor |
|---|-----------|---------|
| **INV-1** | Nenhuma chamada à ProfitDLL ocorre dentro de callback da DLL (lei R3 / manual §4) | Quinn (mock que monitora) |
| **INV-2** | `dedup(L ++ L) == dedup(L)` para qualquer L | Quinn (Hypothesis) |
| **INV-3** | `download(s, [a,b])` é idempotente — re-rodar não duplica nem corrompe | Quinn (Hypothesis) |
| **INV-4** | Toda fila tem `maxsize > 0` e política de overflow declarada | Aria (review de PR) |
| **INV-5** | Schema do Parquet é versionado (`schema_version` em metadata) | Sol (`*audit-storage-pr`) |
| **INV-6** | Catálogo SQLite é fonte única de verdade sobre "o que está baixado" | Sol (`*catalog --reconcile`) |
| **INV-7** | `read()` ordena por `timestamp_ns` ascendente | Quinn |
| **INV-8** | Public API segue SemVer | Aria |
| **INV-9** | `migrate_v_n_to_v_m(read_v_n(p))` preserva campos comuns | Quinn |
| **INV-10** | MainThread Qt nunca bloqueia >16ms | Felix (`*responsiveness-audit`) + Pyro |
| **INV-11** | OrchestratorThread ≠ IngestorThread ≠ ConnectorThread (separação física obrigatória — sem fusão) | Quinn (enumera `threading.enumerate()` em testes) |
| **INV-12** | "Fim de chunk" só pode ser declarado quando: `dll_queue.empty()` AND `write_queue.empty()` AND último write committou em SQLite catalog | Quinn (property test com kill-process entre commits) |

---

## 5. Estrutura de Diretórios

```
data-downloader/
├── agents/                       # personas (10 agentes)
│   ├── architect.md              # 🏛️ Aria
│   ├── dev.md                    # 💻 Dex
│   ├── devops.md                 # ⚙️ Gage
│   ├── frontend-dev.md           # 🖼️ Felix
│   ├── perf-engineer.md          # ⚡ Pyro
│   ├── pm.md                     # 📋 Morgan
│   ├── profitdll-specialist.md   # 🗝️ Nelo
│   ├── qa.md                     # 🧪 Quinn
│   ├── storage-engineer.md       # 💾 Sol
│   └── ux-design-expert.md       # 🎨 Uma
│
├── profitdll/                    # já existente — não tocar
│   ├── DLLs/{Win32,Win64}
│   ├── Manual/
│   ├── Exemplo Python/
│   └── bin/
│
├── docs/
│   ├── MANIFEST.md               # carta do squad (lei R*)
│   ├── ROLES.md                  # matriz de autoridade
│   ├── WORKFLOW.md               # story lifecycle
│   ├── ARCHITECTURE.md           # este arquivo
│   ├── ROADMAP.md                # visão de produto (Morgan)
│   │
│   ├── adr/                      # ADRs (Aria)
│   │   ├── ADR-001-python-runtime.md
│   │   ├── ADR-002-storage-stack.md
│   │   ├── ADR-003-front-pyside6.md
│   │   ├── ADR-004-partition-layout.md
│   │   ├── ADR-005-thread-model.md
│   │   ├── ADR-006-contract-calendar.md
│   │   └── ADR-007-public-api.md
│   │
│   ├── dll/                      # Nelo
│   │   ├── PROFITDLL_KNOWLEDGE.md
│   │   └── QUIRKS.md
│   │
│   ├── storage/                  # Sol
│   │   ├── SCHEMA.md
│   │   ├── CONTRACTS.md
│   │   ├── INTEGRITY.md
│   │   └── MIGRATIONS.md
│   │
│   ├── ux/                       # Uma
│   │   ├── PRINCIPLES.md
│   │   ├── FLOWS.md
│   │   ├── WIREFRAMES.md
│   │   ├── MICROCOPY.md
│   │   └── THEME.md
│   │
│   ├── perf/                     # Pyro
│   │   ├── BASELINES.md
│   │   └── REPORTS/
│   │
│   ├── qa/                       # Quinn
│   │   ├── QA_REPORTS/
│   │   └── INTEGRITY_REPORTS/
│   │
│   ├── release/                  # Gage
│   │   ├── RELEASES.md
│   │   └── AUDIT.md
│   │
│   ├── stories/                  # epics × stories
│   ├── epics/
│   ├── debt/                     # technical debt registry
│   └── decisions/                # vetos, mediações (Morgan)
│
├── src/
│   └── data_downloader/
│       ├── __init__.py
│       ├── dll/                  # 🗝️ audit Nelo
│       ├── orchestrator/         # 💻 Dex
│       ├── storage/              # 💾 audit Sol
│       ├── public_api/           # 🔵 Aria + Dex
│       ├── ui/                   # 🖼️ Felix (UX Uma)
│       └── cli.py                # typer
│
├── tests/                        # 🧪 Quinn
│   ├── unit/
│   ├── integration/
│   ├── property/                 # Hypothesis
│   ├── smoke/                    # E2E contra DLL real
│   └── fixtures/
│
├── benchmarks/                   # ⚡ Pyro
│   ├── bench_parquet_write.py
│   ├── bench_parquet_read.py
│   ├── bench_dedup.py
│   ├── bench_callback_to_disk.py
│   ├── bench_chunking.py
│   └── results/                  # JSON outputs
│
├── build/                        # ⚙️ Gage
│   └── data_downloader.spec
│
├── data/                         # gitignored — gerado
│   └── history/
│       ├── catalog.db
│       └── F/{symbol}/{year}/{month}.parquet
│
├── .github/                      # ⚙️ Gage (futuro)
│   └── workflows/
│
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── .gitignore
└── .env.example
```

---

## 6. Contracts (Protocols por fronteira)

> **Adicionado em v1.1.0 (2026-05-03)** — endereça PLAN_REVIEW H21.

Sem `Protocol`s explícitos em fronteiras, refator de internal quebra todo lugar que importa concreto. Aria define **interfaces tipadas** para cada fronteira de camada — implementações concretas adaptam, não substituem.

**Path canônico:** `src/data_downloader/contracts/`

```
src/data_downloader/contracts/
├── __init__.py
├── writer.py          # WriterProtocol
├── catalog.py         # CatalogProtocol
├── dll_client.py      # DLLClientProtocol
├── progress.py        # ProgressEmitter
└── handle.py          # DownloadHandle (Protocol; impl concreta em public_api/download.py)
```

### Protocols principais

#### `WriterProtocol`

Fronteira **storage interna** — qualquer implementação que aceita batches e persiste em formato suportado.

```python
from typing import Protocol
from collections.abc import Iterable

class WriterProtocol(Protocol):
    def write_batch(self, symbol: str, trades: Iterable[Trade]) -> WriteResult: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

Implementações: `ParquetWriter` (V1), futuro `ArcticWriter` ou similar.

#### `CatalogProtocol`

Fronteira **catalog** — hides single-process SQLite vs multi-process broker (~~ADR-015~~ REVOKED 2026-05-05; multi-process branch é dead-code — ver ADR-022).

```python
class CatalogProtocol(Protocol):
    def register_partition(self, symbol: str, path: str, ...) -> None: ...
    def mark_chunk_done(self, chunk_id: str) -> None: ...
    def is_chunk_done(self, chunk_id: str) -> bool: ...
    def reconcile(self) -> ReconciliationReport: ...
```

Implementações: `LocalCatalogClient` (V1 single-process), `MultiprocessCatalogClient` (V2 Epic 4).

#### `DLLClientProtocol`

Fronteira **DLL** — abstrai `ProfitDLLWrapper` real do mock de teste.

```python
class DLLClientProtocol(Protocol):
    def initialize(self, *, key: str, user: str, password: str) -> None: ...
    def register_history_trade_callback(self, cb: Callable[[Trade], None]) -> None: ...
    def request_history(self, symbol: str, start: datetime, end: datetime) -> None: ...
    def finalize(self) -> None: ...
```

Implementações: `ProfitDLLWrapper` (concreto), `MockProfitDLL` (testes — ADR-014).

#### `ProgressEmitter`

Fronteira **orchestrator → UI** — abstrai Qt signal vs CLI Rich progress vs noop.

```python
class ProgressEmitter(Protocol):
    def emit(self, progress: DownloadProgress) -> None: ...
    def emit_finished(self, result: DownloadResult) -> None: ...
    def emit_failed(self, error: DataDownloaderError) -> None: ...
```

Implementações: `QtProgressEmitter` (UI Epic 3), `RichProgressEmitter` (CLI), `NullProgressEmitter` (Jupyter).

#### `DownloadHandle`

Fronteira **public_api** — handle retornado de `download()` (ADR-007a).

Spec completa em ADR-007a. Aqui só re-exporta como Protocol para ser importado por adapters/tests.

### Regras

1. **Fronteiras importam apenas Protocols** — `cli/`, `ui/`, `tests/` nunca importam classes concretas de `dll/`, `storage/`.
2. **Implementações concretas estão em seus módulos de origem** (`storage/parquet_writer.py` define `class ParquetWriter` que satisfaz `WriterProtocol` sem `import`-ar o Protocol — duck typing + structural).
3. **Aria aprova mudanças em `contracts/`** — quebra de Protocol = breaking change na fronteira interna; pode forçar atualização cross-camada.
4. **`Protocol` (não `ABC`)** — duck typing structural; implementações não precisam herdar.

---

## 7. ADRs

> Índice canônico completo em [`docs/adr/README.md`](./adr/README.md). Tabela abaixo reflete status atual.

| ADR | Título | Status |
|-----|--------|--------|
| ADR-001 | Python 3.12 + ctypes como runtime | accepted |
| ADR-002 | Storage = Parquet (Snappy) + DuckDB + SQLite | accepted |
| ADR-003 | Front desktop = PySide6 (Qt6) single-process | accepted (+ amendment 2026-05-03) |
| ADR-004 | Particionamento `{exchange}/{symbol}/{year}/{month}.parquet` | accepted |
| ADR-005 | Thread model com bounded queues block back-pressure | accepted (+ amendment 2026-05-03) |
| ADR-006 | Calendário de contratos = tabela estática versionada | accepted |
| ADR-007 | Public API SemVer separado do core (princípio) | superseded by ADR-007a |
| ADR-007a | Public API redesign: `DownloadHandle.cancel()` (supersede shape ADR-007) | accepted |
| ADR-008 | DLL distribution: gitignore + bootstrap-dll.ps1 | accepted |
| ADR-009 | Build determinístico (lockfile + SOURCE_DATE_EPOCH + container) | accepted |
| ADR-010 | Logging strategy: structlog + contextvars + R21 hot-path | accepted |
| ADR-011 | Exception hierarchy: pública vs `_InternalError` + tradução | accepted |
| ADR-012 | Configuration: env vars + TOML + Pydantic Settings | accepted |
| ADR-013 | Runtime observability: counters/gauges/histograms | accepted |
| ADR-014 | Test strategy: layers + mock DLL + fake clock + Hypothesis | accepted |
| ADR-015 | Multiprocess catalog coordination (broker process) | **REVOKED 2026-05-05** (superseded by ADR-022) |
| ADR-016 | Windows code signing & SmartScreen | accepted (deferred to V1 release) |
| ADR-017 | Auto-updater (tufup preliminar) | accepted (deferred to Epic 4) |
| ADR-018 | Frozen-Mode Path Boundary (`bundle_paths` SSOT) | accepted (2026-05-06) |
| ADR-019 | Schema as Contract — Never Drop Columns | proposed (2026-05-05) |
| ADR-020 | Volume Completeness Invariant | proposed (2026-05-05) |
| ADR-021 | `sys.frozen` Contract — Quem testa frozen mode | accepted (2026-05-06) |
| ADR-022 | Single-Session Sequential Download Policy | accepted (2026-05-05) — supersedes ADR-015 |
| ADR-023 | Uniform 1-day Chunk Policy | accepted (2026-05-07) |
| ADR-024 | Catalog SQLite em `data/_internal/` | accepted (2026-05-07) |
| ADR-025 | Parquet-per-day híbrido com auto-compactação mensal | accepted (2026-05-13) — supersedes ADR-004 |

---

## 8. Dependências Externas

### Diretas (autorizadas)
- `pyarrow` (Parquet)
- `duckdb`
- `PySide6` (UI)
- `structlog` (logging)
- `rich` (CLI UX)
- `typer` (CLI framework)
- `pydantic` (validação) — **pendente**: ADR para uso transversal vs apenas em fronteiras

### Test
- `pytest`, `pytest-cov`, `pytest-mock`, `hypothesis`

### Dev
- `ruff` (lint+format)
- `mypy` (type-check)

### Build
- `pyinstaller`

### Sistema (Win64)
- `ProfitDLL.dll` + companions (`libssl-1_1-x64.dll`, `libcrypto-1_1-x64.dll`, `libeay32.dll`, `ssleay32.dll`)
- `.dat` files (`timezone2.dat`, `holidays.dat`, `exchangeinfo2.dat`, `newagents.dat`)
- Diretórios (`MarketHours2`, `database`, `PopupManagerV2`, `strategy`)

Toda nova dep transversal exige ADR (lei R15).

---

## 9. Mudanças nesta Arquitetura

Cada mudança aqui exige:
1. ADR aceito.
2. Atualização deste documento por Aria.
3. Bump de versão deste arquivo.
4. Comunicação ao squad (especialmente: Dex, Sol, Felix).

### Changelog
- **1.1.2-pending** (2026-05-05) — ADR-015 (Multiprocess catalog coordination) **REVOKED** após confirmação do dono do produto de que licença Nelogica é single-session. Multi-symbol passa a ser sequencial em 1 processo conforme **ADR-022 (Single-Session Sequential Download Policy)**. §2.4 e §6 (CatalogProtocol) ganharam nota de redirect; refator completo da §2.4 (remover diagrama broker) será finalizado em amendment formal v1.1.2. Tabela §7 reflete REVOKED + ADR-022 accepted. ADR-019/020 (schema-as-contract, volume-completeness) listados como proposed (council 2026-05-05).
- **1.1.1** (2026-05-03) — ADR governance: ADRs 007a, 008-017 promovidos `proposed → accepted` por Aria após validação cross-ADR. ADR-007 marcado `superseded by ADR-007a`. ADR-016 e ADR-017 ficam `accepted (deferred)`. Índice canônico criado em `docs/adr/README.md`. Tabela §7 reflete status atualizado.
- **1.1.0** (2026-05-03) — Adendos pós-PLAN_REVIEW: §6 nova (Contracts/Protocols), INV-11 e INV-12 adicionadas, §2.4 multi-symbol agora referencia ADR-015 (broker process). ADRs novos: 007a, 008, 009, 010, 011, 012, 013, 014, 015, 016, 017. Amendments: ADR-003 (--onedir + DontUseNativeDialog), ADR-005 (state machine de shutdown), ROLES (cli.py ownership).
- **1.0.0** (2026-05-03) — Versão inicial. 6 camadas, 5 threads, 3 filas, 10 invariantes, 7 ADRs planejados.

---

*— Squad data-downloader, ARCHITECTURE v1.1.1 — 2026-05-03 — maintainer 🏛️ Aria*
