# Story Validations 2026-05-03 — Morgan `*validate-story` em massa

**Owner:** 📋 Morgan
**Data:** 2026-05-03
**Escopo:** Validação 10-point das 12 stories do Epic 1 (incluindo as recém-criadas em Plan Review).

---

## Metodologia

Cada story avaliada contra os 10 pontos do checklist (`agents/pm.md` `validation_10_points`):

1. **P1:** User Story clara (As a / I want / So that)
2. **P2:** AC numeradas e testáveis (não-subjetivas)
3. **P3:** AC cobre golden path + edge cases
4. **P4:** Subtasks decompostas (cada < 1 dia)
5. **P5:** Dev Notes referenciam ARCHITECTURE / ADR / manual
6. **P6:** Testing notes específicas (unit, integration, smoke, property)
7. **P7:** Depends-On explícitas
8. **P8:** Owner e reviewers atribuídos
9. **P9:** Foundation impact avaliado
10. **P10:** Estimativa <= 3 dias

**Verdict:** GO (>= 7/10) ou NO-GO (< 7/10 com fixes listados).

**NOTA:** Story 1.2 re-validada em 2026-05-03 após reescrita do Nelo (ver seção "Story 1.2" abaixo).

---

## Story 0.0 — Sol cria SCHEMA + CONTRACTS + INTEGRITY

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a squad / I want Sol formalize / So that source-of-truth eliminate drift" |
| P2 | ✅ | 10 AC numeradas, todas testáveis (existência de arquivo, conteúdo de seção) |
| P3 | ✅ | Cobre versionamento, dedup key, two-phase commit, threshold rewrite, drift A/B/C |
| P4 | ✅ | 5 tasks, subtasks < 1d cada |
| P5 | ✅ | Refs: ADR-002, ADR-004, ADR-006, Plan Review findings explícitos |
| P6 | ⚠️ | Story de docs — sem testes automatizados; validação por review humana (Aria + Quinn + Morgan) declarada |
| P7 | ✅ | depends_on: [] (correto — fundamento) |
| P8 | ✅ | Owner: storage-engineer; Reviewers: qa, architect, pm |
| P9 | ✅ | Foundation impact alto — bloqueia 1.3/1.4/1.5/1.6 |
| P10 | ✅ | 1d estimativa |

**Score: 9/10 → VERDICT: GO**

Observação P6: aceitável para story de documentação. Quinn valida rastreabilidade.

---

## Story 0.1 — Environment Bootstrap

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis |
| P3 | ✅ | Cobre git init, .gitignore, branch model, bootstrap-dll, hooks, README |
| P4 | ✅ | 7 tasks pequenas |
| P5 | ✅ | Refs: ADR-008, Plan Review findings, MANIFEST.md R12/R18 |
| P6 | ✅ | Smoke + Manual declarados |
| P7 | ⚠️ | depends_on: [] mas DEPENDE de ADR-008 ser accepted antes de AC4. Documentado em Constraints + AC9. Aceitável (dependência é doc, não story). |
| P8 | ✅ | Owner: devops; Reviewers: architect, qa, pm |
| P9 | ✅ | Foundation crítica — bloqueia 1.1 |
| P10 | ✅ | 0.5d |

**Score: 10/10 → VERDICT: GO**

---

## Story 0.2 — Pre-commit Framework

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis |
| P3 | ✅ | Cobre hooks padrão + custom + secrets + DLL + parquet |
| P4 | ✅ | 4 tasks, subtasks pequenas |
| P5 | ✅ | Refs: ADR-009, MANIFEST R12/R18/R19/R20 |
| P6 | ✅ | Smoke + Manual |
| P7 | ✅ | depends_on: [0.1] |
| P8 | ✅ | Owner: devops |
| P9 | ✅ | Foundation — bloqueia 1.1 |
| P10 | ✅ | 0.5d |

**Score: 10/10 → VERDICT: GO**

---

## Story 0.3 — UX Foundation

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (cada um cita arquivo + conteúdo mínimo) |
| P3 | ✅ | Cobre PRINCIPLES, CLI_PATTERNS, MICROCOPY_CATALOG, THEME, FLOWS, WIREFRAMES |
| P4 | ✅ | 7 tasks, subtasks < 1d |
| P5 | ✅ | Refs: Plan Review findings H13/H14/H15/M8/M9/M10, MANIFEST R17 |
| P6 | ⚠️ | Story de docs — Manual review por Morgan + Quinn |
| P7 | ✅ | depends_on: [] |
| P8 | ✅ | Owner: ux-design-expert |
| P9 | ✅ | Foundation — bloqueia 1.7b + Epic 3 |
| P10 | ✅ | 1d |

**Score: 9/10 → VERDICT: GO**

Observação P6: aceitável; story de docs.

---

## Story 0.4 — CodeRabbit adoption decision

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 7 AC testáveis |
| P3 | ✅ | 3 opções avaliadas + condicional GO/NO-GO/ADAPT |
| P4 | ✅ | 4 tasks pequenas |
| P5 | ✅ | Refs: Plan Review findings M3, L7 |
| P6 | ✅ | Manual: decisão registrada em arquivo |
| P7 | ✅ | depends_on: [] |
| P8 | ✅ | Owner: devops; Reviewer: qa, pm |
| P9 | ⚠️ | Foundation impact baixo (não bloqueia) — declarado |
| P10 | ✅ | 0.5d |

**Score: 9/10 → VERDICT: GO**

---

## Story 1.1 — Scaffolding (atualizada)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 12 AC testáveis (incluindo AC11 pytest --collect-only, AC12 dll_version) |
| P3 | ✅ | Cobre pyproject + estrutura + .gitignore + README + collect-only + dll_version |
| P4 | ✅ | 4 tasks, subtasks < 1d |
| P5 | ✅ | Refs: ADR-001, MANIFEST R12/R18/R19, ARCHITECTURE §5, Plan Review L1, H19 |
| P6 | ⚠️ | Sem testes de produção; validação por execução de comandos |
| P7 | ✅ | depends_on: [0.0, 0.1, 0.2] (atualizado) |
| P8 | ✅ | Owner: dev; Reviewers: qa, architect |
| P9 | ✅ | Foundation crítica |
| P10 | ✅ | 1d |

**Score: 9/10 → VERDICT: GO**

---

## Story 1.2 — DLL wrapper: init/finalize + state callback (re-validada após reescrita Nelo)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a orchestrator / I want wrapper Python da ProfitDLL / So that 1.3 e 1.7 podem chamar GetHistoryTrades sem corrupção (Q11-E, Sentinel §12)" |
| P2 | ✅ | 16 AC numeradas, todas testáveis (mock_calls assertion, queue contents, file existence, code paths, fallback paths) |
| P3 | ✅ | Golden (init→connect→finalize) + edges: NL_* (AC7), COMPANIONS_MISSING (AC12), DLLFinalize fallback Finalize (AC6), MARKET_WAITING/CONNECTED (AC5/Q-AMB-01), SetEnabledLogToDebug ausente (AC11), GetDLLVersion ausente (AC13), queue full (AC16), session re-init proibido (AC14/M15) |
| P4 | ✅ | 10 tasks, 30+ subtasks atômicas (todas < 1 dia); estudo de fontes (T1) separado da implementação |
| P5 | ✅ | Refs canônicas: Manual §3.1/§3.2/§4 com linhas exatas (2738, 3317-3329, 4382), QUIRKS.md (Q07-V/Q09-AMB/Q10-AMB/Q11-E/M15), PROFITDLL_KNOWLEDGE.md, profit_dll.py/profitTypes.py, ADR-005/ADR-010, MANIFEST R3/R12/R21, ARCHITECTURE §2 + INV-1 |
| P6 | ✅ | Unit (6 arquivos com asserts específicos: mock_calls==[], 11 args sem None, fallback parametrizado, queue feed sintético), Smoke gated por PROFITDLL_KEY com fixture session-scoped + evidence path; Integration/Property declaradas n/a |
| P7 | ✅ | depends_on: [1.1] explícito no frontmatter |
| P8 | ✅ | Owner: dev (Dex); Reviewers: profitdll-specialist (Nelo), qa (Quinn), architect (Aria) |
| P9 | ✅ | Foundation crítica — wrapper é base de toda interação DLL; AC2/AC4/AC11/AC12/AC14 evitam corrupção que cascataria em 1.3/1.7; Q11-E é blast radius cross-story |
| P10 | ✅ | 2.5d (dentro do limite de 3d; teto aceitável dada complexidade de 16 AC + 10 tasks + companion script + fixture protocol) |

**Score: 10/10 → VERDICT: GO**

Observações:
- Reescrita absorveu 7 findings do Plan Review (C6/C7/C8/M15/H4/H19/H1) sem aumentar escopo além de 0.5d (de 2d → 2.5d).
- AC15 (mock_calls == []) é gold standard de auditoria R3 — Quinn deve usar este pattern como template para futuras stories com callback.
- AC14 (fixture session-scoped) cria precedente para todas as stories smoke da Epic 1 (1.3, 1.6, 1.7b, 2.1) — Quinn deve refletir em SMOKE_PROTOCOL.md.
- AC12 (companions check) cria utility reutilizável (`scripts/verify-dll-companions.py` + função importável) — reduz blast radius de erros crípticos do Windows loader.
- Status atualizado de Draft → Ready em 2026-05-03 (Change Log da story).

---

## Story 1.3 — History download primitive (atualizada)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (AC1 reescrito com decisão V1/V2 explícita) |
| P3 | ✅ | Cobre callbacks, parser timestamp, 99% reconnect, smoke gated |
| P4 | ✅ | 8 tasks, subtasks < 1d |
| P5 | ✅ | Refs: Manual ProfitDLL §3.1/§3.2, ADR-005, leis R3/R7/R8/R9, Plan Review H8 |
| P6 | ✅ | Unit + Integration + Smoke + Property declarados |
| P7 | ✅ | depends_on: [0.0, 1.2] (atualizado) |
| P8 | ✅ | Owner: dev; Reviewers: profitdll-specialist, qa, architect |
| P9 | ✅ | Foundation — bloqueia 1.7a |
| P10 | ✅ | 2d |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.4 — Storage layer (atualizada)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (AC1 referencia SCHEMA.md de Story 0.0; AC5 com fsync(parent_dir); AC8 threshold rewrite; AC10 reformulado removendo round-trip) |
| P3 | ✅ | Cobre writer + dedup + reader + atomicity + threshold + property tests |
| P4 | ✅ | 7 tasks bem decompostas |
| P5 | ✅ | Refs: ADR-002, ADR-004, leis R4/R5/R6, Plan Review H1/H2/H6/H7 |
| P6 | ✅ | Unit + Integration + Property + manual atomicity |
| P7 | ✅ | depends_on: [0.0, 1.1] (atualizado) |
| P8 | ✅ | Owner: dev; Reviewers: storage-engineer, qa, architect |
| P9 | ✅ | Foundation crítica |
| P10 | ✅ | 2d |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.4.5 — Synthetic perf baselines

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis |
| P3 | ✅ | Cobre 3 benchmarks + budgets + matriz compressão + mock fixture |
| P4 | ✅ | 6 tasks |
| P5 | ✅ | Refs: ADR-002, Plan Review H3/H5 |
| P6 | ✅ | Integration (benchmarks executáveis) + Property |
| P7 | ✅ | depends_on: [1.4] |
| P8 | ✅ | Owner: perf-engineer; Reviewers: storage-engineer, qa, pm |
| P9 | ✅ | Foundation — gate honesto |
| P10 | ✅ | 1d |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.5 — Catálogo SQLite (atualizada)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 13 AC testáveis (AC11 reconcile auto, AC12 WAL checkpoint, AC13 two-phase commit) |
| P3 | ✅ | Cobre CRUD, resume, reconcile, cleanup, two-phase commit |
| P4 | ✅ | 8 tasks |
| P5 | ✅ | Refs: ADR-002, leis R5/R6, INTEGRITY.md (Story 0.0) |
| P6 | ✅ | Unit + Integration + Property |
| P7 | ✅ | depends_on: [1.4] |
| P8 | ✅ | Owner: dev; Reviewers: storage-engineer, qa, architect |
| P9 | ✅ | Foundation crítica |
| P10 | ✅ | 2d |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.5b — read_continuous + queries DuckDB

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis |
| P3 | ✅ | Cobre rollover, queries canônicas, property tests, smoke |
| P4 | ✅ | 5 tasks |
| P5 | ✅ | Refs: ADR-002, ADR-007, INV-7, Plan Review M16 |
| P6 | ✅ | Integration + Property + Smoke |
| P7 | ✅ | depends_on: [1.5, 1.6] |
| P8 | ✅ | Owner: dev; Reviewers: storage-engineer, qa, architect |
| P9 | ✅ | Foundation — bloqueia gate Epic 1 |
| P10 | ✅ | 1d |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.6 — Contract calendar (atualizada)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis |
| P3 | ✅ | Cobre vigent_contract, populate seed, probe DLL, CLI commands |
| P4 | ✅ | 7 tasks |
| P5 | ✅ | Refs: ADR-006, CONTRACTS.md (Story 0.0), leis R8/R9 |
| P6 | ✅ | Unit + Integration + Property + Smoke |
| P7 | ✅ | depends_on: [1.2, 1.3, 1.5] (atualizado — finding H12 corrigido) |
| P8 | ✅ | Owner: dev; Reviewers: storage-engineer, profitdll-specialist, qa |
| P9 | ✅ | Foundation crítica |
| P10 | ✅ | 1d |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.7a — Orchestrator core

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (state machine, cache hit real, retry, idempotência) |
| P3 | ✅ | Cobre chunker, retry, state machine, integração 1.3/1.5/1.6, resume, cache hit |
| P4 | ✅ | 8 tasks |
| P5 | ✅ | Refs: Stories 1.3/1.5/1.6, ADR-005 + amendment, Plan Review C10/H8/H11/L2/R21 |
| P6 | ✅ | Unit + Integration + Property |
| P7 | ✅ | depends_on: [1.3, 1.5, 1.6] |
| P8 | ✅ | Owner: dev; Reviewers: profitdll-specialist, storage-engineer, qa, architect |
| P9 | ✅ | Foundation crítica |
| P10 | ✅ | 2d (decomposto do 1.7 original 3d) |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.7b — CLI typer + public_api + smoke MVP gate

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (CLI args, microcopy, Ctrl+C, public_api, smoke evidence) |
| P3 | ✅ | Cobre CLI, microcopy, Ctrl+C, public_api, smoke E2E + cache hit + integrity |
| P4 | ✅ | 7 tasks |
| P5 | ✅ | Refs: Story 1.7a, Story 0.3, ADR-007a, Plan Review H9/H10/H13/H14/H15/M8/C5 |
| P6 | ✅ | Smoke (gated) + Manual Ctrl+C |
| P7 | ✅ | depends_on: [1.7a, 0.3] |
| P8 | ✅ | Owner: dev; Reviewers: ux-design-expert (Uma — H13 obrigatório), profitdll-specialist, storage-engineer, qa, architect |
| P9 | ✅ | Foundation — gate Epic 1 |
| P10 | ✅ | 2d (decomposto do 1.7 original 3d) |

**Score: 10/10 → VERDICT: GO**

---

## Story 1.8 — Pyro baselines reais

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (bench reais, BASELINES update, flame graphs, hot path issues) |
| P3 | ✅ | Cobre bench_chunking, bench_callback_to_disk, regression, hot path |
| P4 | ✅ | 7 tasks |
| P5 | ✅ | Refs: Story 1.4.5, Story 1.7b, Plan Review H3/H4/H22 |
| P6 | ✅ | Smoke + Regression check |
| P7 | ✅ | depends_on: [1.7b] |
| P8 | ✅ | Owner: perf-engineer; Reviewers: storage-engineer, qa, architect, pm |
| P9 | ✅ | Foundation — gate close Epic 1 |
| P10 | ✅ | 1d |

**Score: 10/10 → VERDICT: GO**

---

## Story 2.1 — Data integrity validators como código (movida para Epic 1)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | Clara |
| P2 | ✅ | 10 AC testáveis (IntegrityChecker, DataValidator, Roundtrip, CLI commands, templates) |
| P3 | ✅ | Cobre validators + CLI + templates + waivers + B3 holiday calendar |
| P4 | ✅ | 8 tasks |
| P5 | ✅ | Refs: Story 1.5, Story 1.4 (round-trip movido), INTEGRITY.md, Plan Review C4/M1/M2/M17 |
| P6 | ✅ | Unit + Integration + Property + Smoke |
| P7 | ✅ | depends_on: [1.7b] |
| P8 | ✅ | Owners: storage-engineer + qa (co-owners); Reviewers: architect, pm |
| P9 | ✅ | Foundation — gate close Epic 1 |
| P10 | ✅ | 2d |

**Score: 10/10 → VERDICT: GO**

---

## Stories Done (2026-05-03) — encerradas pela Fase A

### Story 0.0 — DONE

- **Verdict QA gate (documental, delegado a Morgan):** PASS
- **Owner entregador:** 💾 Sol
- **Arquivos:** `docs/storage/SCHEMA.md` (414L), `docs/storage/CONTRACTS.md` (265L), `docs/storage/INTEGRITY.md` (403L), `docs/storage/MIGRATIONS.md` (266L), `docs/storage/QUERIES.md` (379L)
- **AC cobertas:** AC1..AC10 — todas PASS (ver `docs/stories/0.0.story.md` Dev Agent Record)
- **Status:** Draft → Done
- **Desbloqueia:** Stories 1.3, 1.4, 1.5, 1.6 (consomem SCHEMA.md/CONTRACTS.md/INTEGRITY.md como fonte única)

### Story 0.3 — DONE

- **Verdict QA gate (documental, delegado a Morgan):** PASS
- **Owner entregador:** 🎨 Uma
- **Arquivos:** `docs/ux/PRINCIPLES.md` (380L), `docs/ux/CLI_PATTERNS.md` (493L), `docs/ux/MICROCOPY_CATALOG.md` (353L, 16 NL_* refs), `docs/ux/THEME.md` (378L), `docs/ux/FLOWS.md` (312L, 4 fluxos), `docs/ux/WIREFRAMES.md` (336L, 3 telas × 5 estados), `docs/ux/QT_PATTERNS.md` (bônus para Epic 3)
- **AC cobertas:** AC1..AC10 — todas PASS (ver `docs/stories/0.3.story.md` Dev Agent Record)
- **Status:** Draft → Done
- **Desbloqueia:** Story 1.7b (CLI smoke MVP — Uma é reviewer obrigatório R17), prep para Epic 3

---

## Resumo consolidado

| Story | Verdict | Score | Notas |
|-------|---------|-------|-------|
| 0.0 | **GO** | 9/10 | docs only — P6 N/A aceitável |
| 0.1 | **GO** | 10/10 | — |
| 0.2 | **GO** | 10/10 | — |
| 0.3 | **GO** | 9/10 | docs only — P6 N/A aceitável |
| 0.4 | **GO** | 9/10 | foundation impact baixo (declarado) |
| 1.1 | **GO** | 9/10 | scaffolding — sem testes prod |
| 1.2 | **GO** | 10/10 | Re-validada após reescrita Nelo (Plan Review C6/C7/C8/M15/H4/H19/H1) |
| 1.3 | **GO** | 10/10 | — |
| 1.4 | **GO** | 10/10 | — |
| 1.4.5 | **GO** | 10/10 | — |
| 1.5 | **GO** | 10/10 | — |
| 1.5b | **GO** | 10/10 | — |
| 1.6 | **GO** | 10/10 | — |
| 1.7a | **GO** | 10/10 | — |
| 1.7b | **GO** | 10/10 | — |
| 1.8 | **GO** | 10/10 | — |
| 2.1 | **GO** | 10/10 | — |

**Total avaliado:** 17 stories (13 do Epic 1 + 4 da fase 0).
**Verdict GO:** 17/17 (Story 1.2 re-validada 2026-05-03 após reescrita Nelo).
**Verdict NO-GO:** 0.

**Próximo passo:** todas stories validadas. Wave 4 desbloqueada (Story 1.2 ‖ Story 1.4 podem iniciar em paralelo).

---

## Observações finais (Morgan)

1. **Foundation primeiro:** todas as stories 0.x são pré-requisitos não-negociáveis para Story 1.1. Nenhuma 0.x pode ser pulada.
2. **Story 1.7 deprecada:** preservada como `1.7-DEPRECATED.story.md` para rastreabilidade. NÃO consumir.
3. **Paralelismo possível:** Wave 4 (1.2 ‖ 1.4), Wave 5 (1.3 ‖ 1.4.5), Wave 8 (1.5b ‖ 1.7a), Wave 10 (1.8 ‖ 2.1).
4. **Gate Epic 1 NÃO fecha em 1.7b:** smoke MVP é gate intermediário; close formal só após 1.8 + 2.1 Done.
5. **Uma é reviewer obrigatório de 1.7b** — sem GO de Uma, story NÃO vai a InReview (R17).

— Morgan, validando o squad 📋
