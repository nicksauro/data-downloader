# ADR-030 — Protocol-First Boundary Policy: opt-in migration over big-bang

- **Status:** Proposed
- **Date:** 2026-05-17
- **Author:** Aria (@architect)
- **Consultados:** Sol (@data-engineer — impl Story 4.28), Quinn (@qa — audit), Dex (@dev — caller callsites)
- **Implementor:** Sol (@data-engineer) — Story 4.28
- **Supersedes:** —
- **Related:** ARCHITECTURE.md §6 (Protocols & interface contracts, v1.1.0 — H21), ADR-007 (public API SemVer boundary), ADR-007a (DownloadHandle), ADR-011 (exception hierarchy), Story 2.4 (MetricsEmitter — primeiro Protocol concreto), Story 4.28 (cli pacote + Protocols)

---

## 1. Contexto

`ARCHITECTURE.md §6` (linhas 426-500), introduzida em v1.1.0 (H21) por Aria,
prescreve **5 Protocols** em `src/data_downloader/contracts/` para abstrair
fronteiras entre `dll/`, `storage/`, `orchestrator/`, `ui/` e `public_api/`:

| Protocol            | Responsabilidade                                                    | Status hoje                |
|---------------------|---------------------------------------------------------------------|----------------------------|
| `WriterProtocol`    | Storage interna — batches → parquet/arctic                          | **Não existe** (só `ParquetWriter` concreto) |
| `CatalogProtocol`   | Catalog operations (single-process SQLite, hides ADR-022)           | **Não existe** (só `Catalog` concreto)        |
| `DLLClientProtocol` | DLL wrapper (concreto vs mock — ADR-014)                            | **Não existe** (só `ProfitDLL` concreto)       |
| `ProgressEmitter`   | orchestrator → UI (Qt signal vs Rich CLI vs Null)                   | **Não existe** (callbacks ad-hoc)              |
| `DownloadHandle`    | public_api boundary (handle retornado por `download()`, ADR-007a)   | **Não existe** como Protocol (só impl concreta) |

A única Protocol realmente implementada hoje é `MetricsEmitter` (Story 2.4)
em `contracts/observability.py`. As cinco prometidas em §6 ficaram como
`TODO` por 4 releases (v1.1.0 → v1.3.0).

A revisão consolidada do squad (BIG COUNCIL Frente 5 — 2026-05-16) elevou
isto a **P0-A2**: "Boundary violations: refator de storage força mudanças
em 6 outros lugares. Sem Protocols, qualquer breaking change interna
quebra todo callsite que importa `ParquetWriter`/`Catalog`/`ProfitDLL`
diretamente."

### Restrições para a solução

- **Constitutional Article IV (No Invention):** Protocols só existem se
  cabíveis na realidade do código atual; não podemos prescrever métodos
  que nenhum caller usa.
- **R20 (suite estável):** mudança não pode quebrar callers existentes
  da v1.3.0 — UI, public_api e CLI hoje importam concretos. A Frente 4
  está aberta em paralelo (PR #5 — Story 4.27 mexe em `ui/`).
- **ADR-007 (SemVer boundary):** `public_api/` é fronteira pública.
  Adicionar `DownloadHandle` como Protocol é **estendido**, não
  substituído — duck-typing structural preserva backward-compat.
- **Custo de migração:** 6 callsites usam `Catalog` direto, 8 usam
  `ParquetWriter`, ~12 usam `ProfitDLL`. Migrar todos num único PR
  geraria ~600 LOC de mudança transversal e conflito com PRs concorrentes
  (Frente 4 — UI).

### O que motiva esta ADR (e não apenas a Story)

A decisão a ser tomada não é "implementar os Protocols". Isso é tarefa
mecânica (Story 4.28). A decisão é **a política de migração** — em
particular, **quem está obrigado a usar Protocols depois desta story?**.

- Opção naive: "ninguém pode mais importar `Catalog` ou `ParquetWriter` —
  todos os callers migram agora". → big-bang, alto risco, conflito com
  Frente 4.
- Opção minimalista: "ninguém precisa migrar; Protocols existem só como
  documentação". → não resolve P0-A2 (ainda há acoplamento estrutural).
- Opção híbrida (opt-in): "Protocols disponíveis; callers existentes
  permanecem; código novo DEVE usar Protocols; migração de callers
  legados é planejada em PRs subsequentes". → esta ADR.

---

## 2. Decisão

**Opt-in gradual migration with deterministic obligations for new code.**

### 2.1 Protocols disponibilizados em `contracts/` (Story 4.28)

Cinco Protocols `runtime_checkable` adicionados em
`src/data_downloader/contracts/_protocols.py` (ou submódulos por
Protocol — TBD em Story 4.28; layout não afeta a política):

```python
# Exemplo da forma — assinaturas detalhadas vivem no código.

@runtime_checkable
class WriterProtocol(Protocol):
    def write(
        self,
        trades: "Iterable[Trade]",
        partition: "PartitionKey",
        *,
        catalog: "CatalogProtocol | None" = None,
        job_id: str | None = None,
    ) -> "WriteResult": ...

    def compact_month(self, partition: "PartitionKey") -> "WriteResult": ...
    def close(self) -> None: ...


@runtime_checkable
class CatalogProtocol(Protocol):
    def register_partition(self, /, *args: object, **kwargs: object) -> None: ...
    def recover_pending_commits(self) -> "PendingRecoveryReport": ...
    def pending_commit(self, /, *args: object, **kwargs: object) -> "AbstractContextManager[object]": ...
    def list_contracts_in_range(self, /, *args: object, **kwargs: object) -> "Sequence[object]": ...
    def completed_days(self, symbol: str, exchange: str) -> "frozenset[date]": ...
    def maybe_compact_month(self, partition: "PartitionKey") -> None: ...
    def close(self) -> None: ...
    # Métodos privados (_conn_or_raise, _transaction) NÃO entram no Protocol.


@runtime_checkable
class DLLClientProtocol(Protocol):
    def initialize_market_only(self, key: str, user: str, password: str) -> None: ...
    def wait_market_connected(self, *, timeout: float) -> bool: ...
    def get_history_trades(self, /, *args: object, **kwargs: object) -> "Iterable[Trade]": ...
    def subscribe_ticker(self, ticker: str, exchange: str) -> int: ...
    def unsubscribe_ticker(self, ticker: str, exchange: str) -> int: ...
    def finalize(self) -> None: ...


@runtime_checkable
class ProgressEmitter(Protocol):
    def emit(self, event: "ProgressEvent") -> None: ...


@runtime_checkable
class DownloadHandle(Protocol):
    job_id: str
    def cancel(self, *, timeout: float = 30.0) -> "DownloadResult": ...
    def events(self) -> "Iterator[DownloadProgress]": ...
    def result(self, timeout: float | None = None) -> "DownloadResult": ...
```

**Convenções (não-negociáveis):**

- `runtime_checkable` em todos — `isinstance(obj, WriterProtocol)`
  precisa funcionar para asserts defensivos em testes.
- Métodos privados (`_conn_or_raise`, `_transaction`, internals) NÃO
  entram no Protocol — eles são detalhes de implementação.
- Métodos com kwargs complexas usam `*args: object, **kwargs: object`
  no Protocol e a assinatura precisa vive na classe concreta (Aria
  decidiu: Protocol é forma mínima reconhecível, não duplicata da impl).
- Exports via `contracts/__init__.py`:
  ```python
  from data_downloader.contracts._protocols import (
      CatalogProtocol,
      DLLClientProtocol,
      DownloadHandle,
      ProgressEmitter,
      WriterProtocol,
  )
  __all__ = [
      "CatalogProtocol",
      "DLLClientProtocol",
      "DownloadHandle",
      "MetricsEmitter",  # já existe — Story 2.4
      "NullMetricsEmitter",
      "ProgressEmitter",
      "WriterProtocol",
  ]
  ```

### 2.2 Política de uso — regra determinística

| Quem                                          | Obrigação                                                                                              |
|-----------------------------------------------|---------------------------------------------------------------------------------------------------------|
| **Código existente (v1.3.0 e anterior)**      | **Mantém imports concretos.** Nenhuma refactor forçada. ZERO mudança no comportamento.                  |
| **Código NOVO (>= v1.4.0, post-Story 4.28)**  | **DEVE** depender via Protocols quando cruzar fronteira de camada (ex.: `ui/`/`cli/` → `storage/`).     |
| **Testes novos**                              | **DEVEM** type-hint via Protocols para que mocks duck-typed funcionem sem herança.                      |
| **Implementações concretas** (`ParquetWriter`, `Catalog`, etc.) | **NÃO** herdam do Protocol (`class ParquetWriter:` continua sem base). Structural subtyping garante conformidade. |

**Tie-breaker:** em dúvida, **usar Protocol**. Custo de adicionar import
extra é nulo; benefício de inverter dependência é estrutural.

### 2.3 O que NÃO está sendo decidido aqui

- **Não migrar callers existentes nesta story.** UI (`screens/`,
  `widgets/`, `adapters/`), `public_api/download.py`, `cli.py` continuam
  importando concretos. Migração planejada em PRs futuros (v1.5.0+),
  uma camada de cada vez (ordem sugerida: `tests/` → `cli/` → `public_api/` → `ui/`).
- **Não substituir `MetricsEmitter`.** Já é Protocol acabado desde Story
  2.4; permanece como está em `contracts/observability.py`.
- **Não bloquear PRs em curso.** Frente 4 (PR #5 / Story 4.27 — UI
  threading) prossegue sem mexer em `contracts/`.

### 2.4 Atualização da ARCHITECTURE.md §6

`ARCHITECTURE.md §6` ganha amendment (Story 4.28 AC):

```markdown
> **Amendment 2026-05-17 (Story 4.28 / ADR-030):** Os 5 Protocols
> prometidos em v1.1.0 estão implementados em
> `src/data_downloader/contracts/_protocols.py`. Migração de callers
> segue política opt-in: código novo DEVE usar Protocols ao cruzar
> fronteira; código legado (v1.3.0) MANTÉM imports concretos. Big-bang
> migration foi rejeitada (ver ADR-030 Opção A).
```

---

## 3. Opções consideradas

### Opção A — Big-bang: migrar todos os callers no mesmo PR

Adicionar Protocols **+** trocar todos os imports concretos por Protocols
em `ui/`, `cli/`, `public_api/`, `tests/`.

- **Prós:** estado final consistente; ninguém mais "esquece" e
  importa concreto.
- **Contras:**
  - ~600 LOC de mudança transversal num PR.
  - Conflito com Frente 4 (PR #5 toca `ui/`).
  - Conflito com `cli.py` pacotificação (este mesmo PR Story 4.28 P0-A1).
  - Quebra hidden assumptions (UI testa via `isinstance(catalog, Catalog)`
    em 2 lugares — Pyro audit 2026-05-15).
  - Pichau directive (2026-05-13): "rigidamente implementar e testar" —
    PRs grandes têm taxa de regressão maior; preferir PRs pequenos.
- **Veredito:** rejeitada — alto risco, baixo benefício marginal.

### Opção B — Pure documentation: Protocols como `.pyi` stubs

Definir Protocols apenas em arquivos `.pyi` (type-stubs), sem implementação.

- **Prós:** zero impacto em runtime; type-checker valida estrutura.
- **Contras:**
  - `runtime_checkable` (`isinstance`) não funciona com `.pyi` puro.
  - Testes precisam runtime check para mocks duck-typed.
  - Dual maintenance: `.py` (impl) + `.pyi` (forma) — diverge com facilidade.
  - Não resolve P0-A2: callers ainda importam concretos; refator
    quebra mesmas N callsites.
- **Veredito:** rejeitada — só desloca o problema.

### Opção C — Opt-in com obrigação para código novo (escolhida)

Protocols disponíveis em `contracts/`; callers existentes mantêm-se;
código novo deve usar Protocols ao cruzar fronteira.

- **Prós:**
  - Migração incremental, baixo risco por PR.
  - Não conflita com Frente 4 em curso.
  - Estabelece a fronteira sem forçar refactor.
  - Tornar testes novos resilientes (mocks duck-typed) IMEDIATAMENTE.
- **Contras:**
  - Estado "misto" (alguns callsites concretos, outros Protocol-based)
    persiste por ~1-2 releases.
  - Risco de "esquecer" — código novo importando concreto por hábito.
    Mitigação: regra explícita em `.claude/rules/coding-standards.md`
    (Story 4.28 AC9) + grep auditável no CI.

### Opção D — `abc.ABC` em vez de `typing.Protocol`

Classes abstratas com herança obrigatória; conformidade via `class
ParquetWriter(WriterABC):`.

- **Prós:** explicit > implicit; MRO claro.
- **Contras:**
  - Quebra v1.3.0: forçar `class Catalog(CatalogABC)` muda a class
    hierarchy — `isinstance(catalog, Catalog)` continua OK, mas testes
    que usavam Mock subclassing quebram.
  - ARCHITECTURE.md §6 já escolheu Protocol (`**Protocol** (não ABC)** —
    duck typing structural; implementações não precisam herdar.`).
  - Ferir convenção do projeto.
- **Veredito:** rejeitada — fora de manifesto.

---

## 4. Consequências

### Positivas

- P0-A2 endereçado: novo código fica desacoplado por padrão; migração
  legada destravada (PRs futuros não bloqueiam por "primeiro precisamos
  dos Protocols").
- Testes podem usar mocks duck-typed sem herança: `class FakeWriter:
  def write(self, ...): ...` e `assert isinstance(fake, WriterProtocol)`.
- Story 4.28 fica acotada — não toca callers, apenas adiciona
  `contracts/_protocols.py` + actualiza `ARCHITECTURE.md §6`.
- Frente 4 e Frente 5 não colidem.

### Negativas

- Estado misto por 1-2 releases. Mitigação:
  - Tabela em `ARCHITECTURE.md §6` (amendment) lista quais callsites
    ainda usam concretos (atualizada a cada PR de migração).
  - `Grep` auditável: `grep -rn "from data_downloader.storage.catalog import Catalog" src/data_downloader/ui src/data_downloader/cli` retorna lista finita; convertida em
    issue/backlog.
- Risco de "drift": código novo importa concreto por hábito.
  Mitigação:
  - Regra explícita em `.claude/rules/` (Story 4.28 AC9).
  - Code review: revisores devem rejeitar PR novo que importe concreto
    cruzando camada (ex.: `ui/foo.py` importando `storage.catalog.Catalog`).
  - Lint custom (futuro — não nesta story): `ruff` plugin que flagga
    imports concretos cross-layer.

### Neutras

- Performance: zero. `runtime_checkable` adiciona overhead apenas em
  chamadas `isinstance` — não há call no hot path.
- Mypy --strict: Protocols funcionam nativamente; nada muda.
- Documentação: `ARCHITECTURE.md §6` ganha amendment + tabela; ADR-030
  é referenciada em `docs/adr/README.md`.

---

## 5. Invariantes derivadas

- **INV-PROTO-1:** Implementações concretas (`ParquetWriter`, `Catalog`,
  `ProfitDLL`) NÃO herdam dos Protocols (sem `class Catalog(CatalogProtocol):`).
  Conformidade é structural — duck typing.
- **INV-PROTO-2:** Métodos privados (prefixo `_`) NÃO entram em Protocols
  públicos. Se um Protocol precisa de algo `_private`, ou o método vira
  público, ou o Protocol não captura a fronteira certa.
- **INV-PROTO-3:** Código novo (post-2026-05-17) que cruza fronteira de
  camada DEVE depender via Protocol. Code review enforça; falha de
  enforcement = ADR-030 violation.
- **INV-PROTO-4:** `contracts/` NUNCA importa de `storage/`, `dll/`,
  `orchestrator/`, `ui/`, `public_api/`. Protocols vivem isoladas —
  cycle-free por construção.

---

## 6. Validações requeridas (Story 4.28)

- [ ] Sol — `contracts/_protocols.py` cria as 5 Protocols com
  `runtime_checkable`. Mypy `--strict` passa.
- [ ] Sol — `contracts/__init__.py` exporta as 5 (+ `MetricsEmitter`/
  `NullMetricsEmitter` existentes).
- [ ] Sol — `isinstance(Catalog(...), CatalogProtocol)` retorna True em
  smoke test (sem mexer em `Catalog` — structural).
- [ ] Sol — `isinstance(ProfitDLL(), DLLClientProtocol)` retorna True.
- [ ] Sol — `isinstance(ParquetWriter(...), WriterProtocol)` retorna True.
- [ ] Sol — ARCHITECTURE.md §6 amendment commitado junto com a story.
- [ ] Sol — `.claude/rules/coding-standards.md` (ou equivalente) ganha
  parágrafo curto referenciando ADR-030 (regra opt-in).
- [ ] Quinn — audit grep documentado: `grep -rn "from data_downloader\.storage\.catalog import Catalog" src/data_downloader/{ui,cli}` retorna lista atual (baseline para PRs futuros).
- [ ] Quinn — suite verde (`ruff` + `mypy --strict` + `pytest`).

---

## 7. Rollback

Se a política opt-in se mostrar inviável (ex.: PRs futuros descobrem
incompat entre o Protocol e a impl real):

1. **Plano A — refinar Protocol.** A maioria dos casos resolve-se
   ajustando a assinatura no Protocol para `*args: object, **kwargs: object`
   ou para tipo mais permissivo. Não exige reverter.
2. **Plano B — revogar ADR-030.** `contracts/_protocols.py` permanece
   (não tem caller obrigatório). Apenas a obrigação "código novo DEVE
   usar Protocols" é suspensa. ARCHITECTURE.md §6 ganha amendment
   "ADR-030 superseded por ADR-NNN".
3. **Plano C — adotar ADR alternativa.** Se duck typing structural
   provar-se insuficiente (ex.: mypy não consegue inferir conformidade
   em casos reais), considerar Opção D (ABC) numa ADR futura.

Nenhum rollback toca callers — eles já não dependem do Protocol.

---

## 8. Open questions

- **Q1 — `compact_month` na `WriterProtocol`?** Sol pode preferir manter
  só `write` no Protocol e `compact_month` como detalhe de impl
  (`ParquetWriter`-only). Aria endossa: avaliar em revisão de PR; default
  recomendado é **inclui** (`compact_month` é usado por `Catalog.maybe_compact_month`
  → fronteira real).
- **Q2 — `DownloadHandle` como Protocol vs re-export?** ADR-007a já
  define a class concreta `DownloadHandle` em `public_api/handle.py`.
  Opções:
  (a) Definir Protocol homônimo em `contracts/` — risco de confusão de
  import path;
  (b) Re-export simples (`from data_downloader.public_api.handle import DownloadHandle`)
  e usar a class concreta como "Protocol de fato";
  (c) Renomear a class concreta para `_DownloadHandleImpl` e o nome
  público vira Protocol — quebra de API (rejeitado).
  Decisão proposta: **(b) re-export**. ADR-007a já estabeleceu shape;
  Protocol seria duplicação. Confirmar em Story 4.28 AC4.
- **Q3 — `ProgressEmitter` recebe `ProgressEvent` único ou métodos
  separados (`emit_progress`/`emit_finished`/`emit_failed` como em
  ARCHITECTURE.md §6)?** A versão da §6 tem 3 métodos; o orchestrator
  hoje emite um único evento `ProgressEvent` na fila. Decisão proposta:
  **um método `emit(event)`** — alinha com o real; ARCHITECTURE.md §6
  é amended.

---

## 9. Sign-off

- Aria (@architect) — autor.
- Sol (@data-engineer) — implementor, Story 4.28.
- Quinn (@qa) — validação via audit grep + suite verde.
- Dex (@dev) — revisão de callsites no PR de Story 4.28.

Status `Proposed` muda para `Accepted` no commit final da Story 4.28
após AC11 PASS (suite verde + sign-off Quinn).
