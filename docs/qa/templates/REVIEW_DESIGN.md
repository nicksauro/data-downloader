# Design Review — Architecture (Aria)

> Template para `Aria *review-design`. Preencher um arquivo deste por revisão,
> salvar em `docs/qa/AUDITS/design/{{ story_id }}-{{ date }}.md`.

---

## 1. Header

| Campo                | Valor                                             |
|----------------------|---------------------------------------------------|
| **story_id**         | `{{ story_id }}` (ex: 1.7a)                       |
| **agente_auditado**  | `{{ agent_audited }}` (ex: Dex, Felix)            |
| **arquivo_auditado** | `{{ artifact_path }}` (story `.md`, design doc, ou diff de PR) |
| **data**             | `{{ YYYY-MM-DD }}`                                |
| **sha_commit**       | `{{ commit_sha }}` (do design ou PR)              |
| **auditor**          | Aria 🏛️ (architect)                                |
| **adr_refs**         | `{{ ADR-XXX, ADR-YYY }}` (ADRs invocados)         |

---

## 2. Escopo

- **Em escopo:** `{{ in_scope }}` (ex: thread model, fronteiras de camada, public API surface)
- **Fora de escopo:** `{{ out_of_scope }}` (ex: detalhes de implementação interna)
- **Componentes tocados:**
  - `{{ component_1 }}` (ex: `orchestrator/`)
  - `{{ component_2 }}` (ex: `storage/`)
- **Cruza fronteiras?** `{{ yes/no }}` — se sim, listar quais

---

## 3. Checklist (design_review)

> Origem: `agents/architect.md` → `checklists.design_review`

- [ ] **Respeita thread model?** (ConnectorThread vs IngestorThread vs OrchestratorThread vs WriterThread vs UIThread — INV-11 separação física)
- [ ] **Respeita fronteiras de camada?** (`dll/` ↔ `orchestrator/` ↔ `storage/` ↔ `ui/` via `contracts/`)
- [ ] **Toda fila tem `maxsize` E política de back-pressure?** (drop-oldest, block, raise — documentada)
- [ ] **É idempotente onde precisa ser?** (re-rodar download = no-op; re-aplicar migration = no-op)
- [ ] **Introduz dependência nova?** Se sim, há ADR justificando? (R8/R10)
- [ ] **Schema Parquet alterado?** Sol foi consultada e auditou?
- [ ] **Wrapper DLL alterado?** Nelo foi consultado e auditou?
- [ ] **Public API alterada?** Bump de versão planejado? (ADR-007a)
- [ ] **Erro propaga corretamente?** (internals → public_api → UI conforme ADR-011)
- [ ] **Hot path respeitado?** (sem logging per-trade, sem alocação per-callback — R21)
- [ ] **Shutdown desenhado?** (ADR-005 amendment: state machine `Running→DrainingDLL→DrainingWrite→Committed`; INV-12)

---

## 4. Achados (Findings)

### F-{{ N }} — `{{ severity }}` — `{{ title }}`

- **Arquivo:** `{{ file_path }}:{{ line }}` ou seção da story (ex: `1.7a.story.md` AC6)
- **Descrição:** `{{ design_smell_or_violation }}`
- **ADR/INV ref:** `{{ ADR-XXX | INV-N | MANIFEST.Rxx }}`
- **Sugestão de fix:** `{{ design_change_proposal }}`
- **Trade-off alternativo (se aplicável):** `{{ alt_a vs alt_b com prós/contras }}`

<!-- Repetir bloco F-N para cada achado. Se 0 findings, escrever "Nenhum finding." -->

---

## 5. Decisão

| Verdict             | Marcar |
|---------------------|--------|
| ✅ APPROVED         | [ ]    |
| 🟡 CHANGES_REQUESTED | [ ]    |
| 🔴 BLOCKED          | [ ]    |

**Justificativa:** `{{ verdict_rationale }}`

**Próxima ação:**
- APPROVED → Dex/Felix podem implementar; Quinn aguarda QA gate
- CHANGES_REQUESTED → Story refinement obrigatório (Morgan/Sm) ou refactor de design
- BLOCKED → Aria abre/atualiza ADR, retorna a Morgan para replanning

---

## 6. ADRs/Invariantes invocados ou criados

| ID            | Status nesta revisão                            |
|---------------|--------------------------------------------------|
| `{{ ADR-N }}` | applied / proposed / amendment-needed / blocker |
| `{{ INV-N }}` | preserved / violated / new                       |

---

## 7. Assinatura digital

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **agente**       | `aria (architect)`                             |
| **commit_sha**   | `{{ audit_commit_sha }}`                       |
| **co_authored**  | `Co-Authored-By: Aria (Architect) <agent@data-downloader.local>` |
| **timestamp**    | `{{ ISO8601 }}`                                |

— Aria 🏛️
