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

## Story 2.2 — Perf Write Optimization (vectorize ParquetWriter) — validada em 2026-05-04

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a Pyro responsável por throughput sustentado / I want vectorizar hot path interno do `ParquetWriter` (`_trades_to_table`, `validate_record`, `dedup`, `_sha256_file`) usando `pa.compute` + `pa.array` direto + `hashlib` streaming / So that o gap de **-72%** medido em Story 1.4.5 / re-confirmado em Story 1.8 (production writer 27_638 trades/s vs target 100k/s) seja eliminado, atingindo >= 100k trades/s sustained sem alterar contrato externo nem schema canônico Parquet." |
| P2 | ✅ | 8 AC numeradas e testáveis (todas com critério verificável: AC1 throughput numérico, AC2-AC5 vectorização específica + flag legacy, AC6 property tests, AC7 regression suite, AC8 diff vazio fronteira) |
| P3 | ✅ | Cobre golden path (vectorize + property test + regression) E edge cases (flag legacy fallback, dedup variantes pareto-ótimo, RSS peak SHA256 streaming). Constraints documentam casos limítrofes ("se complexidade > 30%, escalonar Aria") |
| P4 | ✅ | 8 tasks, 19 subtasks — cada subtask < 1 dia (Task 1 baseline 0.25d, Task 2 vectorize table_builder 0.5d, Task 3 vectorize validate 0.5d, Task 4 vectorize dedup com 2 variantes 1d, Task 5 SHA256 0.25d, Task 6 Hypothesis suite 0.5d, Task 7 regression 0.25d, Task 8 reviews 0.25d) |
| P5 | ✅ | Refs ricos: COUNCIL-02 (causa raiz original 1.4.5), COUNCIL-10 (decisão de criar 1.8), BASELINES.md v1.0.0-synthetic + v1.1.0-mock, TARGETS_V1.md (gap-tracked-by-2.2), INTEGRITY.md INV-2/3/7, agents/perf-engineer.md (Pyro), agents/storage-engineer.md (Sol) |
| P6 | ✅ | Testing detalhado: Unit (equivalência outputs vectorized vs loop legacy), Property (Hypothesis cobre INV-2/3/7 + classificação valid/invalid + 100 examples mín), Integration (test_parquet_writer.py re-rodado), Bench (AC1 numérico), Regression (suite completa < 10% gap em 6 benchs) |
| P7 | ✅ | depends_on: [1.4] explícito (canonical ParquetWriter Story 1.4 Done APPROVED Sol) |
| P8 | ✅ | Owner: perf-engineer (Pyro); Reviewers: storage-engineer (Sol — schema authority), architect (Aria — fronteira), qa (Quinn — regression gate) |
| P9 | ✅ | Foundation impact alto declarado: vectorização do writer afeta todo Epic 2/3/4 downstream. Constraint forte: NÃO mudar SCHEMA.md, NÃO mudar public_api. Aria + Sol endossaram via COUNCIL-10. |
| P10 | ✅ | 3d (no teto Morgan, justificado por 4 vectorizações + suite Hypothesis dedicada + 2 variantes dedup com benchmark comparativo) |

**Score: 10/10 → VERDICT: GO**

Observações:
- Story criada via mini-council Pyro+Sol+Aria em COUNCIL-10 — sign-off arquitetural
  já presente (Aria *review-design APPROVED em `docs/qa/AUDIT_REPORTS/1.8-design-2026-05-04.md`).
- Re-baseline contra v1.0.0-real é **constraint declarada** (per COUNCIL-10 §6 — Aria
  endorsement). Story 1.8-followup encadeia.
- Constraint "se complexidade > 30%, escalonar Aria" cria gate adicional para evitar
  refactor rebote — disciplina forte para story de perf optimization.
- Property tests Hypothesis OBRIGATÓRIOS (Aria recomendação 7 COUNCIL-02) — gate
  apropriado para refactor de risco. Pyro implementa com defesa em profundidade.
- Status **`Draft` → `Ready`** em 2026-05-04 (este registro). Pyro desbloqueado
  para iniciar implementação após Morgan dar GO formal em `*plan` semanal.

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

## Story 2.3 — Schema Migration Framework (Epic 2 — refino COUNCIL-10)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a squad / I want framework migrar schema_version / So that R4 (schema contrato perpétuo) sem re-baixar histórico" |
| P2 | ✅ | 10 AC numeradas e testáveis (estrutura pacote, ABC, CLI, dry-run, checkpoint, catalog update, rollback, migration exemplo v1.0.0→v1.1.0, suite tests, docs) |
| P3 | ✅ | Cobre golden path (migrate aditiva) + edge cases (resume após crash, rollback, dry-run, pre-conditions duras, migration sem rollback_supported) |
| P4 | ✅ | 8 tasks decompostas; cada subtask < 1 dia (pacote scaffold, log SQLite, CLI, backup/rollback, migration exemplo, tests, docs, reviews) |
| P5 | ✅ | Refs: MIGRATIONS.md (esqueleto), SCHEMA.md §6 política, INTEGRITY.md INV-2/INV-7, ADR-002, ADR-004, finding H16, agents/storage-engineer.md, Stories 1.4 + 1.5 |
| P6 | ✅ | Unit + Integration (resume após crash) + Property (Hypothesis preserve campos comuns) + Smoke (dataset real opcional) |
| P7 | ✅ | depends_on: [1.4] explícito |
| P8 | ✅ | Owner: storage-engineer; Reviewers: architect, qa, dev |
| P9 | ✅ | Foundation **ALTO** — toca storage/, base de toda evolução de schema. Sol audit obrigatório + Aria revisa CLI integration. Property test obrigatório como gate. |
| P10 | ✅ | 2d estimativa (dentro do limite 3d) |

**Score: 10/10 → VERDICT: GO**

Observação: Story implementa esqueleto Sol (MIGRATIONS.md SCAFFOLD) em código real. Migration aditiva v1.0.0→v1.1.0 (campo `liquidity_classification`) serve de teste end-to-end + referência para futuras. Constraint forte de backup obrigatório + transação atômica catálogo+arquivo.

---

## Story 2.4 — Prometheus Observability Exporter V2 (Epic 2 — refino COUNCIL-10)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a operadores+Pyro+Aria / I want exportar métricas via /metrics HTTP / So that Grafana/Alertmanager scraping em vez de parsing logs JSON" |
| P2 | ✅ | 8 AC numeradas e testáveis (dep, pacote, métricas conforme ADR-013, HTTP exporter porta configurável, hook orchestrator via Protocol, CLI flag, suite tests, docs ops) |
| P3 | ✅ | Cobre golden path (start exporter + scrape) + edge cases (porta ocupada, opt-in default, REGISTRY singleton testes, cardinality LRU símbolos, format compliance Prometheus exposition) |
| P4 | ✅ | 9 tasks decompostas; cada subtask < 1 dia (setup dep, métricas, HTTP, hook orchestrator, CLI, tests, bench, docs, reviews) |
| P5 | ✅ | Refs: ADR-013 (fonte primária), COUNCIL-05 D3 (ProgressEmitter Protocol), ADR-005 thread model, ADR-010 R21, MANIFEST §R21, finding H22, agents/architect.md + perf-engineer.md, Stories 1.7a + 1.7b |
| P6 | ✅ | Unit (cada métrica + emitter) + Integration (HTTP server porta efêmera + format compliance via parser) + Bench (overhead) + Smoke (gated env) |
| P7 | ✅ | depends_on: [1.7a] explícito (orchestrator emite eventos via Protocol) |
| P8 | ✅ | Owner: architect (Aria — fronteira); Reviewers: perf-engineer, dev, devops |
| P9 | ✅ | Foundation **MÉDIO** — módulo novo sem dependentes; hook via Protocol (subscribe), sem refactor de orchestrator. Bug afeta ops/dashboard, não integridade dados. |
| P10 | ✅ | 2d estimativa |

**Score: 10/10 → VERDICT: GO**

Observação: V2 deferred originalmente para Epic 4 em ADR-013 — antecipado para Epic 2 porque release readiness V1 exige métricas live. Constraint chave: NÃO refactorar orchestrator (fronteira Aria); usar subscribe pattern via ProgressEmitter Protocol. Opt-in (zero overhead default).

---

## Story 2.6 — Retry inteligente + circuit breaker (NL_* taxonomy) (Epic 2 — escopo IN)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a orchestrator (Story 1.7a) que precisa atravessar quirks DLL... / I want policy formal de retry categorizado por tipo de erro NL_* + circuit breaker stateful por símbolo / So that download longo sobreviva a falhas transientes sem mascarar bugs lógicos nem cascatear loops infinitos" |
| P2 | ✅ | 8 AC numeradas e testáveis (taxonomia 12+ NL_*, RetryPolicy dataclass, CircuitBreaker 3 estados, Q02-E policy, hook orchestrator não-quebrador, structured logs, suite tests, env config) |
| P3 | ✅ | Cobre golden path (transient retry → success) + edge cases (PERMANENT fail fast, UNKNOWN fail fast, Q02-E 99% repeats não-conta, OPEN→HALF_OPEN→OPEN com janela ampliada, threading concorrente) |
| P4 | ✅ | 7 tasks, ~21 subtasks; cada subtask < 1d (taxonomy table, retry refactor, circuit breaker state machine, Q02-E hook, logs, doc, reviews) |
| P5 | ✅ | Refs: ADR-010 (logs), ADR-011 (CircuitOpenError hierarchy), ADR-013 (métricas), QUIRKS.md Q02-E, profitTypes.py NL_*, agents/profitdll-specialist.md (Nelo), Stories 1.7a + 2.4 |
| P6 | ✅ | Unit (taxonomy table-driven 12+ casos + RetryPolicy + CircuitBreaker transitions ≥ 8) + Property (Hypothesis sequências aleatórias) + Integration (mock DLL 50% fail) + Smoke deferred opcional |
| P7 | ✅ | depends_on: [1.7a, 2.4] explícito (orchestrator base + ProgressEmitter Protocol para métrica) |
| P8 | ✅ | Owner: dev (Dex); Reviewers: profitdll-specialist (Nelo — DLL semantics), architect (Aria — fronteira orchestrator), qa (Quinn) |
| P9 | ✅ | Foundation **MÉDIO-ALTO** declarado — toca `orchestrator/` + `dll/`. Bug = loop infinito ou abort precoce. Property test + Nelo audit + Aria audit como defesas. Sem mudança de fronteira public_api (CircuitOpenError integra hierarquia 2.11 quando essa concluir). |
| P10 | ✅ | 2d estimativa |

**Score: 10/10 → VERDICT: GO**

Observação: depends_on 2.4 é soft (métrica gauge `circuit_breaker_state` integra ProgressEmitter Protocol). Story 2.6 pode iniciar em paralelo com 2.4 — apenas o AC3 hook de métrica fica feature-flagged até 2.4 Done. Aria classificou esse desacoplamento como aceitável.

---

## Story 2.7 — Hot path tuning (HOT_PATH_RULES.md aplicado) (Epic 2 — escopo IN)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a Pyro + Aria / I want auditar todos os hot paths contra R21 + ADR-010 §hot-path-rules, remover structlog desses pontos, formalizar HOT_PATH_RULES.md / So that overhead de logging < 5% CPU em download contínuo" |
| P2 | ✅ | 8 AC numeradas e testáveis (HOT_PATH_RULES.md NEW, audit_hot_path.py + pre-commit, structlog removido callbacks/writer/orchestrator, per-chunk logs preservados, bench re-run com flame graph, async log path condicional, suite tests, F-Q-1 cobertura --cov workaround doc) |
| P3 | ✅ | Cobre golden path (clean hot paths → ganho de Pyro 2.2 não comido) + edge cases (negative result aceitável para AC6, F-Q-1 doc-only sem implementação) |
| P4 | ✅ | 7 tasks bem decompostas (HOT_PATH_RULES doc, audit script + pre-commit, refactor structlog, bench, async opcional, F-Q-1 doc, reviews) |
| P5 | ✅ | Refs: MANIFEST §R21, ADR-010 §hot-path-rules, ADR-013, Plan Review H22, QA Report 1.7a F-Q-1, agents/perf-engineer.md + architect.md, Stories 1.4.5/1.8/2.2 |
| P6 | ✅ | Unit (audit fixture violador + limpo) + Bench (callback_to_disk) + Property (log count = chunks count) + Regression (full bench suite) + Pre-commit hook |
| P7 | ✅ | depends_on: [1.7a, 1.8, 2.2] (orchestrator entry points + baselines + post-vectorize state) |
| P8 | ✅ | Owner: perf-engineer (Pyro); Reviewers: architect (Aria — boundary R21), dev (Dex — refactor), qa (Quinn — regression) |
| P9 | ✅ | Foundation **MÉDIO** — toca callbacks DLL (Nelo) + writer (Sol). Mudança cirúrgica (substituir structlog por contador). Auditoria mecânica em CI previne regressão. |
| P10 | ✅ | 2d estimativa |

**Score: 10/10 → VERDICT: GO**

Observação: AC8 (F-Q-1 cobertura --cov) é **doc-only** — investigação + recomendação. Implementação real do workaround (downgrade Python ou bump duckdb ou plugin custom) pode virar Story 2.X separada se complexidade > 1d. Aceito por Morgan como escopo blindado (story ≤ 2d).

---

## Story 2.8 — Storage perf tuning (compression matrix + row_group + PRAGMA profiles) (Epic 2 — escopo IN)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a Sol + Pyro / I want finalizar matriz tuning storage (compression Pareto, row_group ótimo, PRAGMA profiles low/medium/high) / So that queries DuckDB típicas mínima latência, dataset pareto-ótimo em disco, SQLite não estoura RAM em laptop modesto" |
| P2 | ✅ | 8 AC numeradas e testáveis (matriz compression doc, row_group_size 4 valores, 3 PRAGMA profiles + heurística, threshold rewrite re-medido, BASELINES update, suite tests + property round-trip, Sol audit mandatory, docs canônicos) |
| P3 | ✅ | Cobre golden path (decisão Pareto explícita) + edge cases (RAM detection heurística, override env var, fallback profile, mudança aditiva sem migração) |
| P4 | ✅ | 7 tasks bem decompostas (bench infra, compression bench + análise, row_group, PRAGMA profiles + heurística, threshold rewrite, BASELINES + property, docs + reviews) |
| P5 | ✅ | Refs: SCHEMA.md §Layout Parquet, QUERIES.md §Performance, BASELINES.md, TARGETS_V1.md, REGRESSION_BUDGETS.md, Plan Review H5/H6/M6, parquet_writer.py + catalog.py, Stories 1.4/1.4.5/1.5/1.8/2.2 |
| P6 | ✅ | Unit (PRAGMA profiles 3×2=6 asserts) + Integration (row_group_size validado via metadata) + Property (round-trip por compression × 4 codecs × 100 examples) + Bench (matrix + PRAGMAs) + Regression |
| P7 | ✅ | depends_on: [1.4.5, 1.8, 2.2] explícito (synthetic + real baselines + post-vectorize) |
| P8 | ✅ | Owner: storage-engineer (Sol — defaults authority); Reviewers: perf-engineer (Pyro — bench numbers), dev, qa |
| P9 | ✅ | Foundation **ALTO** — defaults novos afetam datasets criados a partir desta story. Bug PRAGMA = OOM. Bug row_group = queries lentas. Sol audit + Pyro sign-off + property test round-trip são defesas. Mudança aditiva (R4 preserved). |
| P10 | ✅ | 2d estimativa |

**Score: 10/10 → VERDICT: GO**

Observação: depends_on 2.2 é **constraint forte** — measure pós-vectorize para evitar tunar contra writer antigo lento (gargalo seria mascarado). Pyro confirma ordem com Sol em mini-council se necessário.

---

## Story 2.9 — Logging strategy ADR-010 implementada (correlation_id + redaction + JSON) (Epic 2 — escopo IN)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a Aria + Quinn + operadores / I want implementar formalmente ADR-010 (structlog + contextvars correlation_id/job_id/chunk_id/symbol + redaction NL_USERNAME/NL_PASSWORD/NL_KEY + JSON renderer) / So that logs auditáveis, seguros, machine-parseable, prep Epic 3 UI live log" |
| P2 | ✅ | 8 AC numeradas e testáveis (logging_config.py + pipeline, contextvars audit + bind, redaction processor recursive, JSON renderer canônico + schema, CLI flag + env var + TTY detection, refactor call sites, suite tests + property + cross-thread, docs LOGGING.md) |
| P3 | ✅ | Cobre golden path (config único no boot → todo log estruturado) + edge cases (cross-thread isolation, secret nested redaction, TTY auto-detection, backwards compat call sites) |
| P4 | ✅ | 7 tasks pequenas (config + processors, contextvars audit, CLI integration, JSON schema, tests, refactor call sites, docs + reviews) |
| P5 | ✅ | Refs: ADR-010 (primária), MANIFEST §R21, ADR-005 thread model, MICROCOPY_CATALOG.md (Uma), Plan Review L2, cli.py, agents/architect.md + ux-design-expert.md, Story 2.7 (gemêa) |
| P6 | ✅ | Unit (cada processor) + Integration (CLI → JSON → schema validation) + Property (redaction preserva non-secret + masca secret × 100 examples) + Cross-thread (2 jobs concorrentes contextvars isolados) |
| P7 | ✅ | depends_on: [1.7a] (orchestrator entry points para bind contextvars) |
| P8 | ✅ | Owner: dev (Dex); Reviewers: architect (Aria — ADR-010 compliance), qa (Quinn — schema gate), ux-design-expert (Uma — microcopy CLI strings) |
| P9 | ✅ | Foundation **MÉDIO** — toca cli.py + entry points orchestrator. Mudança aditiva (logs ganham fields), sem breaking. INV-credenciais defendido por property test (zero secret leak). |
| P10 | ✅ | 1d estimativa (story menor — config + processors são bounded; refactor incremental) |

**Score: 10/10 → VERDICT: GO**

Observação: Story complementar a 2.7 — 2.7 garante structlog NÃO no hot path; 2.9 garante structlog FORA do hot path segue ADR-010. Sem conflito de escopo (Aria confirma fronteira em mini-council se necessário).

---

## Story 2.10 — Test strategy ADR-014 (mock DLL fixture compartilhada + fake clock + Hypothesis core suite) (Epic 2 — escopo IN)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a Quinn + Aria + Dex/Nelo / I want formalizar estratégia testes ADR-014 com fixtures compartilhadas (mock DLL extraído + fake clock + layered fixtures + Hypothesis core suite cobrindo INV-1..12) + finalizar SMOKE_PROTOCOL.md / So that Epic 3/4 reuse fixtures consistentes, Hypothesis cresce estruturado, gate QA cobre invariantes formal, F-S-4 fechado" |
| P2 | ✅ | 8 AC numeradas e testáveis (pacote tests/_fixtures/, MockProfitDLL configurável + meta-test, FakeClock + isolamento, Hypothesis core ≥ 6 INV × 100 examples, SMOKE_PROTOCOL §6 finalizado, layered fixtures pyramid 4 layers, COVERAGE_STATUS.md, TEST_STRATEGY.md NEW) |
| P3 | ✅ | Cobre golden path (fixtures reusáveis + property tests INV cobrem invariantes) + edge cases (M15 session-scoped, parallelism safe fake clocks, backwards compat conftest re-export, cross-platform TTY) |
| P4 | ✅ | 7 tasks bem decompostas (estrutura + extract mock DLL, fake clock, Hypothesis suite, SMOKE_PROTOCOL §6, layered fixtures, docs, reviews) |
| P5 | ✅ | Refs: ADR-014 (primária), TEST_PYRAMID.md, SMOKE_PROTOCOL.md, INVARIANTS_TESTS.md, AUDIT 1.8 F-S-4, Plan Review C4/C6/M15, conftest.py Story 1.2, agents/qa.md + architect.md + profitdll-specialist.md, Stories 1.2/1.4/1.7a/2.3/2.5 |
| P6 | ✅ | Meta-tests (mock DLL determinismo + FakeClock invariants) + Property (≥ 6 INV × 100 examples) + Integration (layered fixtures demo) + Regression (zero impact suite atual) + Smoke (real DLL fixture session-scoped) |
| P7 | ✅ | depends_on: [1.2, 1.7a, 2.1] (mock DLL atual + orchestrator + validators) |
| P8 | ⚠️ | Owner: qa (Quinn — auto-gate como owner). Conflito potencial documentado: escalation para Aria se Aria/Nelo audit divergir do gate decision. Reviewers: dev, architect, profitdll-specialist. Aceitável com escalation explícito. |
| P9 | ✅ | Foundation **MÉDIO-ALTO** — toca tests/ infra (Quinn authority). Risco regressão se migração mal feita; full suite pré/pós obrigatório. Aria audit confirma ADR-014 compliance. Nelo audit confirma mock DLL fidelidade. |
| P10 | ✅ | 2d estimativa |

**Score: 9/10 → VERDICT: GO**

Observação P8: aceitável com escalation explícito a Aria. Quinn não auto-aprova story se há conflito com reviewer audit. Documento `docs/qa/TEST_STRATEGY.md` consolida governança.

---

## Story 2.11 — Exception hierarchy ADR-011 implementada (internals → public_api → UI) (Epic 2 — escopo IN)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a Aria + Felix/Uma + Dex / I want implementar hierarquia exceptions ADR-011 (3 camadas: internals com prefixo _, public_api com hierarchy estável, UI ramifica por tipo público) + microcopy mapping NL_* + cancel() finalmente implementado / So that caller robusto, internals evoluem sem quebrar contrato R8, Felix/Uma têm mapa estável" |
| P2 | ✅ | 8 AC numeradas e testáveis (hierarquia 12+ classes documentada, internals prefixo _ + audit mecânico, adapter pattern + from e, microcopy mapping NL_* → exception, cancel() cooperativo + state Cancelled + rollback parcial, suite tests + property no leak, Aria audit MANDATORY, docs EXCEPTIONS.md + MICROCOPY_CATALOG update) |
| P3 | ✅ | Cobre golden path (download success + adapter handles internal) + edge cases (concurrent cancel + wait, partial chunks preservados como incomplete, Hypothesis no internal type leak, SemVer impact classificação) |
| P4 | ✅ | 7 tasks bem decompostas (hierarchy classes, internals refactor + audit, adapter pattern, cancel() impl, microcopy mapping, tests + property, docs + reviews) |
| P5 | ✅ | Refs: ADR-011 (primária), ADR-007a (DownloadHandle), ADR-005 amendment (state Cancelled), MICROCOPY_CATALOG.md (Uma), Plan Review H10/H11, public_api/, agents/architect.md + ux-design-expert.md, Stories 1.7a/1.7b/2.6 |
| P6 | ✅ | Unit (cada exception class + adapter pattern) + Property (Hypothesis no internal type leak × 100 examples) + Integration (download falha → tipo público + chain) + Integration cancel (concurrent → SLA) |
| P7 | ✅ | depends_on: [1.7a, 1.7b] (orchestrator + public_api existentes) |
| P8 | ✅ | Owner: dev (Dex); Reviewers: architect (Aria — fronteira MANDATORY), ux-design-expert (Uma — microcopy NL_*), qa (Quinn) |
| P9 | ✅ | Foundation **ALTO** — toca public_api/ (R8 SemVer). Bug afeta toda evolução futura. Property test no-leak + Aria audit + Uma microcopy review são as 3 defesas. Adapter pattern minimiza risco (internals podem evoluir). |
| P10 | ✅ | 2d estimativa |

**Score: 10/10 → VERDICT: GO**

Observação: Story 2.6 produz `CircuitOpenError` que entra na hierarquia desta story. Coordenação soft via dependência (2.6 e 2.11 podem rodar em paralelo; merge order: 2.6 → 2.11 ou contrário com hierarchy stub provisório). Aria define ordem em mini-council se conflito.

---

## Story 2.5 — Calendar B3 holidays.dat Integration (Epic 2 — refino COUNCIL-10)

| P | Status | Nota |
|---|--------|------|
| P1 | ✅ | "As a sistema (DataValidator+IntegrityChecker) / I want ler holidays.dat oficial Nelogica / So that fonte autoritativa substitui hardcoded 2025-2026" |
| P2 | ✅ | 8 AC numeradas e testáveis (investigação formato, parser dedicado, integração transparente, cobertura 2020-2030, refresh mtime, ground truth tests, doc HOLIDAYS_DAT_FORMAT, graceful fallback) |
| P3 | ✅ | Cobre golden path (parse + uso) + edge cases (arquivo ausente, malformado, mtime mudou, cobertura insuficiente, CI sem ProfitDLL) |
| P4 | ✅ | 6 tasks decompostas; cada subtask < 1 dia (Nelo investigação, parser, integração calendar_b3, tests, doc, reviews) |
| P5 | ✅ | Refs: calendar_b3.py docstring TODO, finding F-S-1 audit 2.1, COUNCIL-04 caveat, CONTRACTS.md §0 validation_source, INTEGRITY.md M17 DST, agents/profitdll-specialist.md + storage-engineer.md, Story 2.1 |
| P6 | ✅ | Unit + Integration (parser + fallback) + Property (Hypothesis parser vs hardcoded equivalência 2025-2026) + Smoke (dev box ProfitDLL) |
| P7 | ✅ | depends_on: [2.1] explícito (substitui calendar_b3 nascido em 2.1) |
| P8 | ✅ | Owner: storage-engineer; Reviewers: profitdll-specialist (Nelo — DLL authority), qa, dev |
| P9 | ✅ | Foundation **MÉDIO** — substituição de fonte transparente. API pública estável. Bug = falsos positivos gap detection (não-fatal). Nelo audit + property test são defesas. |
| P10 | ✅ | 2d estimativa (Task 1 investigação pode escalar se formato é proprietário sem doc — mini-council Sol+Nelo+Aria já previsto como escalation path) |

**Score: 10/10 → VERDICT: GO**

Observação: Zero alucinação (R23) — se Nelo não confirma formato via manual oficial, marca `validation_source: reverse_engineered` + lista hipóteses. Fallback hardcoded preservado para CI sem ProfitDLL. API pública INTACTA — apenas fonte interna troca.

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
| 2.2 | **GO** | 10/10 | Validada 2026-05-04 — refactor interno ParquetWriter (vectorize); sign-off Aria via COUNCIL-10; constraint forte "sem mudança fronteira public_api / SCHEMA" |
| 2.3 | **GO** | 10/10 | Validada 2026-05-03 — Schema Migration Framework (finding H16); foundation ALTO (toca storage/); Sol audit + property test obrigatórios; constraint backup + transação atômica |
| 2.4 | **GO** | 10/10 | Validada 2026-05-03 — Prometheus Exporter V2 (ADR-013 antecipado de Epic 4); subscribe pattern via ProgressEmitter (Aria fronteira); opt-in zero overhead default |
| 2.5 | **GO** | 10/10 | Validada 2026-05-03 — Calendar B3 holidays.dat (finding F-S-1 audit 2.1 + COUNCIL-04 caveat); Nelo reviewer obrigatório; fallback hardcoded preservado para CI |
| 2.6 | **GO** | 10/10 | Validada 2026-05-03 — Retry inteligente + circuit breaker NL_* (escopo IN EPIC-2; QUIRKS Q02-E formalizado em policy); foundation médio-alto; Nelo + Aria reviewers; depends_on [1.7a, 2.4] |
| 2.7 | **GO** | 10/10 | Validada 2026-05-03 — Hot path tuning HOT_PATH_RULES.md aplicado (finding H22 + R21); audit mecânico em CI; bench callback_to_disk re-run; AC8 inclui F-Q-1 cobertura --cov doc-only; depends_on [1.7a, 1.8, 2.2] |
| 2.8 | **GO** | 10/10 | Validada 2026-05-03 — Storage perf tuning (compression Pareto matrix + row_group + PRAGMA profiles; findings H5/H6/M6); foundation alto (Sol authority); Sol audit + Pyro sign-off; depends_on [1.4.5, 1.8, 2.2] |
| 2.9 | **GO** | 10/10 | Validada 2026-05-03 — Logging strategy ADR-010 implementada (correlation_id + redaction + JSON renderer + cross-thread isolation); finding L2; complementar à 2.7; Aria + Uma reviewers; depends_on [1.7a] |
| 2.10 | **GO** | 9/10 | Validada 2026-05-03 — Test strategy ADR-014 (mock DLL extract + fake clock + Hypothesis core suite ≥ 6 INV + SMOKE_PROTOCOL §6 + layered fixtures); F-S-4 fechado; P8 ⚠️ aceitável com escalation Aria; depends_on [1.2, 1.7a, 2.1] |
| 2.11 | **GO** | 10/10 | Validada 2026-05-03 — Exception hierarchy ADR-011 (3 camadas + adapter pattern + cancel() H10 + microcopy mapping); foundation alto (R8 SemVer); Aria audit MANDATORY + Uma microcopy review; depends_on [1.7a, 1.7b] |

**Total avaliado:** 27 stories (13 do Epic 1 + 4 da fase 0 + Stories 2.2/2.3/2.4/2.5/2.6/2.7/2.8/2.9/2.10/2.11 Epic 2).
**Verdict GO:** 27/27 (Story 1.2 re-validada 2026-05-03 após reescrita Nelo;
Story 2.2 validada 2026-05-04 pós-COUNCIL-10; Stories 2.3/2.4/2.5 validadas
2026-05-03 pós-COUNCIL-10 refino EPIC-2; Stories 2.6/2.7/2.8/2.9/2.10/2.11
validadas 2026-05-03 pós-EPIC-2 escopo IN — 6 stories Draft pendentes resolvidas).
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
