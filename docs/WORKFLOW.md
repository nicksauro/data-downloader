# WORKFLOW — Story Lifecycle do Squad

> Como uma story nasce, é validada, implementada, revisada, e vira release.

**Versão:** 1.0.0
**Data:** 2026-05-03

---

## 1. Lifecycle de Story

```
   Draft ──validate──▶ Ready ──develop──▶ InProgress ──finish──▶ InReview
                                                                     │
                                                          qa-gate ◀──┘
                                                             │
                              FAIL (≤2x) ──fix──┐            │
                                                ▼            │
                                            apply-qa-fixes   │
                                                │            │
                                                └────────────┘
                                                             │
                                                          PASS │
                                                             ▼
                                                          Done
                                                             │
                                              release-readiness?
                                                             │
                                                            GO
                                                             ▼
                                                          Released
```

### Estados

| Status | Quem move | Pré-condição |
|--------|-----------|--------------|
| `Draft` | Morgan | Story criada via `*create-story` |
| `Ready` | Morgan | `*validate-story` retornou GO (>= 8/10) |
| `InProgress` | Dex/Felix | Implementação iniciada |
| `InReview` | Dex/Felix | Marca após auto-checklist Ready-for-Review |
| `Done` | Quinn | QA gate retornou PASS |
| `Blocked` | Qualquer | Bloqueio externo (DLL down, dep faltando, etc.) |
| `Released` | Gage | Após push + tag (ou após próxima release) |

---

## 2. Quatro Workflows Primários

### 2.1 Story Development Cycle (SDC) — workflow padrão

#### Fase 1: Create (Morgan)
- Comando: `*create-story {N.M} {título}`
- Input: epic existente, dependências resolvidas
- Output: `docs/stories/{N.M}.story.md` (status: Draft)

#### Fase 2: Validate (Morgan)
- Comando: `*validate-story {N.M}`
- 10 pontos:
  1. User Story clara
  2. AC numeradas e testáveis
  3. AC cobre golden path + edge cases
  4. Subtasks < 1 dia cada
  5. Dev Notes referenciam ARCHITECTURE/ADR/manual
  6. Testing notes específicas
  7. Depends-On explícito
  8. Owner + reviewers atribuídos
  9. Foundation impact avaliado
  10. Estimativa <= 3 dias
- Decisão: **GO** (>= 8/10) ou **NO-GO** (lista de fixes)

#### Fase 3: Implement (Dex ou Felix)
- Comando (Dex): `*develop {N.M}` (default: interactive; opções: --yolo, --preflight)
- Padrão de execução:
  ```
  Para cada Task:
    Para cada Subtask:
      1. Implementar produção
      2. Escrever teste(s)
      3. Marcar [x]
    Marcar Task [x]
  Atualizar File List
  Rodar *run-tests + *lint
  Atualizar Dev Agent Record
  Status → InReview
  ```
- **Consultas obrigatórias** durante implementação:
  - Toca DLL → `*consult nelo`
  - Toca storage → `*consult sol`
  - Cruza camadas → `*consult aria`
  - Microcopy/log para usuário → `*consult uma`
- **HALT conditions**:
  - 3 falhas em fix repetido → escalar
  - Ambiguidade após re-leitura → consultar Morgan
  - Dep não-aprovada → consultar Aria

#### Fase 4: QA Gate (Quinn)
- Comando: `*qa-gate {N.M}`
- Checklist completa em `agents/qa.md` (qa_gate_full)
- Verdicts:
  - **PASS** — story Done
  - **CONCERNS** — Done com débito registrado em `docs/debt/`
  - **FAIL** — `*qa-fix-request` gerado; volta a Dex
  - **WAIVED** — exceção; exige assinatura Aria/Sol/Morgan

### 2.2 QA Loop (max 2 iterações)

```
Quinn FAIL → Dex *apply-qa-fixes → Quinn re-gate
                                       │
                            FAIL (2ª) ─┴─ PASS → Done
                                  │
                       FAIL (3ª) → escalar Morgan/Aria
```

Limite: 2 iterações automáticas. Após 3ª falha:
- Morgan reavalia escopo (decompor story?)
- Aria reavalia design (problema arquitetural?)

### 2.3 Spec Pipeline (para features complexas)

Para stories complexas (Foundation impact alto OU > 3 dias estimado), antes de SDC:

```
Morgan *create-story (rascunho)
  → Aria *adr-new (se exige decisão arquitetural)
    → Aria consulta Nelo / Sol / Uma
    → Aria *adr-accept
  → Morgan refina story com referência ao ADR
    → Morgan *validate-story → GO
      → SDC procede
```

### 2.4 Release Pipeline

```
Morgan *release-readiness {milestone}
  ├─ Pyro: regression-check todos baselines (sem regression > budget)
  ├─ Quinn: PASS em todas stories do milestone
  ├─ Sol: data-validate clean em dataset teste
  ├─ Aria: 0 ADR proposed em escopo
  └─ Felix: build PyInstaller smoke
  
  → GO RELEASE (todos PASS) → Morgan autoriza Gage
  → BLOCKED → lista de bloqueios; Morgan decide

Gage *release {version}
  ├─ Bump pyproject.toml versão
  ├─ Morgan *changelog → CHANGELOG.md atualizado
  ├─ git tag vX.Y.Z
  ├─ Gage *push --tag vX.Y.Z
  ├─ Gage *package --mode release → dist/data_downloader-X.Y.Z.exe
  ├─ Gage *package-verify {exe} → SHA256
  ├─ Gage gh release create vX.Y.Z {exe} --notes-from CHANGELOG
  └─ Gage append docs/release/RELEASES.md + AUDIT.md
```

---

## 3. Gates Inegociáveis

> Sem o gate, sem a transição. Cada gate tem dono único.

| # | Gate | Dono | Bloqueia | Override |
|---|------|------|----------|----------|
| G1 | **Story Validation** | Morgan | Início implementação | — |
| G2 | **DLL Audit** | Nelo | Merge PR em `dll/` | — |
| G3 | **Storage Audit** | Sol | Merge PR em `storage/` | — |
| G4 | **Architecture Review** | Aria | Merge PR cross-camada | ADR novo |
| G5 | **UX Approval** | Uma | Implementação tela por Felix | — |
| G6 | **Responsiveness Audit** | Felix | Merge tela | — |
| G7 | **QA Gate** | Quinn | Story → Done; Release | WAIVED (Aria/Sol/Morgan) |
| G8 | **Performance Regression** | Pyro | Merge se regrediu > budget | Aria/Morgan |
| G9 | **Release Readiness** | Morgan | Tag de release | — |
| G10 | **Pre-push** | Gage | `git push` | — |

---

## 4. Quirks e Padrões Específicos do Projeto

### 4.1 ProfitDLL "99% reconectando"
**Quirk validado por Nelo (manual §3.1):** durante `GetHistoryTrades`, o progresso pode ficar em 99% por minutos enquanto a DLL cicla a conexão. **Não é travamento.** Implementação:
- Timeout mínimo 1800s (não 60s).
- UI mostra mensagem honesta: *"A corretora está reconectando — é normal."* (Uma)
- Retry com backoff só após 1800s sem nenhum trade chegando.

### 4.2 Contratos vigentes (não chutar letras)
**Lei R9:** mapa em `docs/storage/CONTRACTS.md`. Validação por Sol via `*contract --validate` (probe Nelo). Nunca usar `WDOFUT` / `WINFUT` (retornam `NL_EXCHANGE_UNKNOWN` em janelas históricas).

### 4.3 Bolsa = uma letra
**Lei R8:** `Bovespa="B"`, `BMF="F"`. Usar `"BMF"` retorna erro silencioso em algumas funções.

### 4.4 Timestamps BRT naive
**Lei R7:** **não converter para UTC.** Armazenar como `timestamp_ns` desde epoch BRT naive + `timestamp_str` original do callback.

### 4.5 Callback DLL = `queue.put_nowait()`
**Lei R3:** zero processamento dentro do callback. `_cb_refs` global previne GC. Quinn detecta violação via mock que monitora.

### 4.6 V2 functions only
**Lei R10:** quando trading entrar (não no MVP), usar V2 (`SendOrder`, `SendChangeOrderV2`, etc.). Nunca V1 obsoletas.

---

## 5. Convenções de Commit

```
<tipo>: <descrição curta> [Story N.M]

<corpo opcional>

<footer opcional>
```

**Tipos:**
- `feat` — nova funcionalidade
- `fix` — correção de bug
- `test` — adição/refatoração de teste
- `docs` — apenas documentação
- `refactor` — refatoração sem mudança comportamental
- `perf` — melhoria de performance (com baseline registrado)
- `chore` — infra, deps, ferramental

**Exemplos:**
```
feat: implementa wrapper init/finalize da ProfitDLL [Story 1.2]
fix: dedup falhava em re-download cross-chunk [Story 2.1]
test: adiciona property-based para schema migration [Story 2.4]
```

---

## 6. Convenções de Branch

```
{tipo}/story-{N.M}-{slug-curto}
```

**Exemplos:**
- `feature/story-1.2-dll-wrapper-init`
- `feature/story-1.4-parquet-writer`
- `fix/story-2.1-dedup-cross-chunk`
- `chore/story-1.1-scaffolding`

Branch criada por Dex/Felix antes de iniciar `*develop`. Push delegado a Gage no final.

---

## 7. Dependências entre Stories

Story tem campo `depends_on: [N.M, ...]` no frontmatter. Morgan resolve antes de iniciar sprint.

**Regras:**
- Story só vai para `Ready` se todas as `depends_on` estão em `Done`.
- Dependência circular → Morgan recusa, decompõe.
- Dependência cross-epic → permitida; epic pai aguarda dep do epic dependência.

---

## 8. Comunicação Entre Agentes

### Padrão de consulta (`*consult`)
```
@dex *consult nelo "como inicializar DLL para mercado-only?"
  → Nelo responde com (a) snippet executável, (b) ref manual §X linha Y
  → Dex documenta resposta no Dev Agent Record da story (campo Debug Log)
  → Dex implementa
```

### Padrão de auditoria
```
PR/commit toca dll/ → Nelo *audit-wrapper {path}
  → APPROVED → Quinn QA gate
  → CHANGES_REQUESTED → Dex aplica → re-audit

PR/commit toca storage/ → Sol *audit-storage-pr {path}
  → APPROVED → Quinn QA gate
  → CHANGES_REQUESTED → Dex aplica → re-audit
```

### Padrão de delegação para push
```
@dex *commit-and-handoff {story-id}
  → Verifica File List commitada
  → Verifica Quinn PASS
  → Mensagem: "Story N.M pronta para push. PASS Quinn em {data}. Branch: {nome}."
  → @gage assume

@gage *push --branch {nome}
  → Pre-push hook (sem secrets, working tree clean)
  → git push
  → Append AUDIT.md
```

---

## 9. Quando Escalar Para o Usuário (Humano)

- Conflito persistente entre 2+ agentes após mediação de Aria/Morgan.
- Decisão de produto que reescreve o MANIFEST.
- Bug crítico em produção que exige rollback.
- Detecção de credencial vazada (Gage).
- Quirk novo da DLL que não bate com o manual nem com prática anterior (Nelo escala).

---

## 10. Anti-padrões — bloqueados pelo workflow

❌ **Story sem AC clara** — Morgan retém em Draft.
❌ **Implementação sem consulta a especialista** — Quinn FAIL no gate.
❌ **Push sem PASS Quinn** — Gage recusa.
❌ **Schema mudando sem ADR** — Sol bloqueia merge.
❌ **Callback DLL processando dentro do callback** — Quinn finding CRITICAL.
❌ **Otimização sem baseline** — Pyro recusa.
❌ **Microcopy inventado por Felix/Dex** — Quinn finding HIGH.
❌ **Dep nova sem ADR** — Aria bloqueia merge.
❌ **Push direto por Dex/Felix/etc** — bloqueado por convenção (R12).
❌ **`Optional[X]` em código novo** — usar `X | None` (Python 3.12).

---

## 11. Resumo Operacional

```
┌────────────────────────────────────────────────────────────────┐
│ DAILY OPS                                                      │
├────────────────────────────────────────────────────────────────┤
│ 1. Morgan *next-story        → próxima story a iniciar         │
│ 2. Dex/Felix *develop {N.M}  → implementação                   │
│ 3. Quinn *qa-gate {N.M}      → verdict                         │
│ 4. Gage *push (se autorizado) → publica                        │
│                                                                │
│ WEEKLY OPS                                                     │
│ 1. Morgan *plan --horizon 1week → priorização da semana        │
│ 2. Pyro *regression-check        → verifica saúde de perf      │
│ 3. Sol *integrity-check          → verifica integridade        │
│                                                                │
│ MILESTONE OPS                                                  │
│ 1. Morgan *release-readiness     → gate                        │
│ 2. Gage *release {version}       → tag + build + GitHub        │
└────────────────────────────────────────────────────────────────┘
```

---

*— Squad data-downloader, WORKFLOW v1.0.0 — 2026-05-03*
