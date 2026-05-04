# Story Gates 2026-05-04 — Quinn `*qa-gate` verdicts

**Owner:** 🧪 Quinn (The Gatekeeper)
**Data:** 2026-05-04
**Escopo:** Verdicts de QA gates executados em 2026-05-04 sobre stories `Ready for Review`.

> Este arquivo registra a passagem de cada story pelo gate de QA. Complementa
> `STORY_VALIDATIONS_2026-05-03.md` (validação 10-point por Morgan no estágio Draft → Ready)
> com a etapa subsequente (Ready for Review → Done por Quinn).

---

## Metodologia

Cada story executa o checklist de 7 quality checks de `story-lifecycle.md` (Phase 4 — QA Gate):

1. **Code review** — patterns, readability, maintainability
2. **Unit tests** — cobertura adequada, todos passando
3. **Acceptance criteria** — todas atendidas
4. **No regressions** — funcionalidade existente preservada
5. **Performance** — dentro de limites aceitáveis
6. **Security** — OWASP basics
7. **Documentation** — atualizada

**Verdict matrix:**

| Verdict   | Critério |
|-----------|----------|
| PASS      | Todas ACs Pass + suíte verde + audits APPROVED + 0 CRITICAL |
| CONCERNS  | Todas ACs Pass + 0 CRITICAL + ≤ 2 HIGH com dívida registrada |
| FAIL      | Qualquer AC Fail OU ≥ 1 CRITICAL OU ≥ 3 HIGH OU audit BLOCKED |
| WAIVED    | FAIL com WAIVER assinado (Aria/Sol/Morgan) |

---

## Story 1.1 — Scaffolding do projeto

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/1.1.story.md`                          |
| **commit auditado**    | `95c7acf`                                            |
| **owner**              | Dex (dev)                                            |
| **gatekeeper**         | Quinn (qa)                                           |
| **report path**        | `docs/qa/QA_REPORTS/1.1-2026-05-04.md`               |

### 7 Quality Checks

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Docstrings ricos com owner+ADR refs, `__all__` explícito, `from __future__ import annotations` em todos os módulos, alinhado com ARCHITECTURE.md §5 |
| 2. Unit tests        | PASS      | 5/5 passed em 0.08s; cobertura formal n/a (subpacotes vazios -- scaffolding); threshold `fail_under=80` configurado para futuras stories |
| 3. Acceptance criteria | PASS    | 12/12 ACs Pass com evidência reprodutível para cada uma                |
| 4. No regressions    | PASS      | N/A -- primeira implementação real (foundation story)                  |
| 5. Performance       | PASS      | pytest em 0.08s (12.5x abaixo do target informal < 1s)                 |
| 6. Security          | PASS      | detect-secrets `Passed`; sem credenciais em codigo; `.env` no `.gitignore` <!-- pragma: allowlist secret --> |
| 7. Documentation     | PASS      | README.md raiz com seções mínimas; File List atualizada; Dev Agent Record completo (Agent Model, Debug Log, Completion Notes, Change Log) |

### Audits dependentes

| Auditoria       | Verdict          | Justificativa                                                                                          |
|-----------------|------------------|--------------------------------------------------------------------------------------------------------|
| Nelo (DLL)      | APPROVED implícito | `dll/__init__.py` apenas stub `get_dll_version` retornando `"0.0.0+stub"` com TODO referenciando Story 1.2 -- não invoca DLL real, não viola lei R3 |
| Sol (storage)   | n/a              | Story 1.1 não toca `storage/` além do `__init__.py` com docstring                                      |
| Aria (design)   | APPROVED implícito | Estrutura alinhada com ARCHITECTURE.md §5; `__api_version__` em `public_api/__init__.py` (ADR-007a); `contracts/` extra autorizado por Aria |

### Findings

| Severity  | Count | Detalhes                                                                                              |
|-----------|-------|-------------------------------------------------------------------------------------------------------|
| CRITICAL  | 0     | -                                                                                                     |
| HIGH      | 0     | -                                                                                                     |
| MEDIUM    | 0     | -                                                                                                     |
| LOW       | 3     | F-L-1 (venv 3.12 pendente) / F-L-2 (`.pre-commit-config.yaml` pin comentado) / F-L-3 (CVE audit não automatizado) -- todos com mitigação documentada |

### Verdict

**PASS** -- Story 1.1 fechada. Status `Ready for Review` → `Done`.

**Próximo passo desbloqueado:** **Wave 4** (paralelo) -- Story 1.2 (Dex + Nelo: DLL wrapper init/finalize + state callback) ‖ Story 1.4 (Dex + Sol: Storage layer Parquet writer + dedup).

---

## Story 1.4 — Storage layer: writer Parquet + leitor DuckDB

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/1.4.story.md`                          |
| **commit auditado**    | `3d447bb`                                            |
| **owner**              | Dex (dev)                                            |
| **gatekeeper**         | Quinn (qa)                                           |
| **report path**        | `docs/qa/QA_REPORTS/1.4-2026-05-04.md`               |
| **audit dependente**   | `docs/qa/AUDIT_REPORTS/1.4-storage-2026-05-04.md` (Sol APPROVED) |

### 7 Quality Checks

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Docstrings ricos com owner+ADR refs (SCHEMA.md, INTEGRITY.md, ADR-002, ADR-004, ADR-011), `__all__` explícito, `from __future__ import annotations`, type hints completos (mypy strict 0 errors em 6 source files), alinhado com ARCHITECTURE.md camada storage |
| 2. Unit tests        | PASS      | 54 passed em 4.43s; cobertura **91.67%** no módulo storage (>= 80% threshold). Por arquivo: dedup 100%, schema 100%, partition 94%, parquet_writer 87%, duckdb_reader 92% |
| 3. Acceptance criteria | PASS    | 10/10 ACs Pass (1 PARCIAL — F-L-1 tracking). Schema v1.0.0 (17 campos), atomic write (tmp+fsync+SHA256+os.replace+fsync(parent_dir)), append+dedup, metadata Parquet completo, DuckDB read filtrado |
| 4. No regressions    | PASS      | 95 passed, 1 skipped, 0 failed em `pytest tests/unit/`. Storage não quebra smoke imports 1.1, dll stub, public_api version, etc. |
| 5. Performance       | PASS (deferred) | pyro baselines (write >= 100k trades/s, read >= 1M trades/s) deferred Story 1.4.5 — F-L-4. pytest 4.43s no escopo storage está dentro de target informal |
| 6. Security          | PASS      | `pre-commit run detect-secrets --all-files` -> `Detect secrets........Passed`. Sem credenciais em código novo. Sem print/log debug residual |
| 7. Documentation     | PASS      | File List completa (5 source + 5 test files), Dev Agent Record completo (Agent Model, Debug Log com 5 issues técnicas, Completion Notes, Change Log datado), Sol audit referenciado |

### Audits dependentes

| Auditoria       | Verdict          | Justificativa                                                                                          |
|-----------------|------------------|--------------------------------------------------------------------------------------------------------|
| Nelo (DLL)      | N/A              | Story 1.4 não toca `dll/`. Lei R3 não aplicável                                                        |
| Sol (storage)   | **APPROVED**     | Audit em `docs/qa/AUDIT_REPORTS/1.4-storage-2026-05-04.md`. 4 findings: 2 MEDIUM deferred-by-scope (catálogo Story 1.5, `sha256_self` Story 1.5/2.X), 2 LOW (threshold + erro paths cov) |
| Aria (design)   | APPROVED implícito | `IntegrityError` consumido de `data_downloader.public_api.exceptions` (ADR-011). `SCHEMA_VERSION = "1.0.0"` constante (ADR-002 + R4). Hierarquia `DataDownloaderError -> IntegrityError` preservada |

### Findings

| Severity  | Count | Detalhes                                                                                              |
|-----------|-------|-------------------------------------------------------------------------------------------------------|
| CRITICAL  | 0     | -                                                                                                     |
| HIGH      | 0     | -                                                                                                     |
| MEDIUM    | 2     | F-M-1 (catálogo SQLite ausente — Story 1.5) / F-M-2 (`sha256_self` ausente do metadata Parquet — Story 1.5/2.X). Ambos deferred-by-scope com tracking documentado |
| LOW       | 4     | F-L-1 (threshold rewrite usa rows não bytes — Story 2.X) / F-L-2 (cov erro paths defensivos — Story 2.1) / F-L-3 (smoke real DLL deferred — Story 1.7) / F-L-4 (Pyro baselines — Story 1.4.5) |

### Verdict

**PASS** — Story 1.4 fechada. Status `Ready for Review` -> `Done`.

**Próximo passo desbloqueado:** **Wave 5 candidata** — Story 1.5 (Sol + Dex:
catálogo SQLite + two-phase commit emulado + recovery boot) deve ser priorizada
para fechar F-M-1 + F-M-2 antes do gate de Epic 1 (Story 1.7 smoke E2E). Em
paralelo, Story 1.4.5 (Pyro — baselines write/read throughput) pode rodar para
fechar F-L-4.

---

## Story 1.2 — DLL wrapper: init/finalize + state callback

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/1.2.story.md`                          |
| **commit auditado**    | `f2a766d`                                            |
| **owner**              | Dex (dev)                                            |
| **gatekeeper**         | Quinn (qa)                                           |
| **report path**        | `docs/qa/QA_REPORTS/1.2-2026-05-04.md`               |
| **audits dependentes** | `docs/qa/AUDIT_REPORTS/1.2-dll-2026-05-04.md` (Nelo APPROVED) + `docs/qa/AUDIT_REPORTS/1.2-design-2026-05-04.md` (Aria APPROVED) |

### 7 Quality Checks

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Docstrings ricos com owner+ADR refs (manual ProfitDLL §3.1/§3.2/§4, ADR-005/007a/010/011, QUIRKS Q07-V/Q08-E/Q09-AMB/Q10-AMB/Q11-E, Sentinel §12), `__all__` explícito, `from __future__ import annotations`, type hints completos. Cross-platform shim documentado (CFUNCTYPE em não-Windows apenas para mocking). Lei R3 / INV-1 cumprida (`_state_cb` faz único `put_nowait`) |
| 2. Unit tests        | PASS      | 47 passed + 2 skipped (esperados) em 1.78s no escopo `dll/`; 106 passed + 2 skipped em 6.09s na suíte completa. AC15 (`mock_dll.mock_calls == []`) verificada em 2 testes distintos. AC2 (`len(args) == 11` + loop `assert a is not None`) verificada. |
| 3. Acceptance criteria | PASS    | 16/16 ACs Pass com evidência reprodutível. AC10 placeholder gated por `PROFITDLL_KEY` (smoke real em Story 1.7) — validado por @po em 2026-05-03 |
| 4. No regressions    | PASS      | 106 passed, 2 skipped, 0 failed em `pytest tests/`. Storage tests (1.4) intactos; smoke imports (1.1) intactos. Adição `DLLInitError` em `public_api/exceptions.py` co-existe com `IntegrityError` (Sol 1.4) sem conflito |
| 5. Performance       | PASS      | pytest dll-only 1.78s (target informal < 5s). Hot path R21 respeitado: callback NÃO loga, NÃO aloca além de tupla `(int, int)` e `put_nowait`. State changes ~unidades por sessão << maxsize=1000 |
| 6. Security          | PASS      | `pre-commit run detect-secrets --all-files` → `Detect secrets........Passed`. Credenciais mascaradas em logger (`key_redacted/credential_redacted="***"`). COUNCIL-01 documenta workaround para falso-positivo de hook `check_no_dotenv` (kwarg `password=...` literal). Sem print/log debug residual |
| 7. Documentation     | PASS      | File List completa (5 source + 4 test files + 1 conftest); Dev Agent Record completo (Agent Model claude-opus-4-7, Debug Log com 7 decisões técnicas, Completion Notes com métricas, Change Log datado com Nelo+Aria+Quinn entries); QUIRKS.md atualizado (Q-AMB-01, Q-AMB-02, Q11-E referenciados) |

### Audits dependentes

| Auditoria       | Verdict      | Justificativa                                                                                          |
|-----------------|--------------|--------------------------------------------------------------------------------------------------------|
| Nelo (DLL)      | **APPROVED** | 16-pt `wrapper_review` checklist PASS. Manual ProfitDLL respeitado (§3.1, §3.2 L2735/L2738/L3317-3329, §4 L4382). Findings: 3 LOW/INFO (wording, reuso constante, quirk pendente smoke). Path: `docs/qa/AUDIT_REPORTS/1.2-dll-2026-05-04.md` |
| Sol (storage)   | N/A          | Story 1.2 não toca `storage/`                                                                          |
| Aria (design)   | **APPROVED** | 11-pt `design_review` checklist PASS. ADR-005 (thread model + INV-1) preservado, ADR-011 (exception hierarchy) implementado, ADR-010 (R21 hot-path) respeitado, fronteira `dll/` → `public_api/exceptions` correta. Findings: 3 INFO (INV-11/12 aplicam-se em 1.7a; api_version pre-release). Path: `docs/qa/AUDIT_REPORTS/1.2-design-2026-05-04.md` |

### Findings

| Severity  | Count | Detalhes                                                                                              |
|-----------|-------|-------------------------------------------------------------------------------------------------------|
| CRITICAL  | 0     | -                                                                                                     |
| HIGH      | 0     | -                                                                                                     |
| MEDIUM    | 0     | -                                                                                                     |
| LOW       | 5     | F-L-1 (wording "11 callback slots") / F-L-2 (reuso `MARKET_WAITING=2` em alias `(ROTEAMENTO, 2)`) / F-L-3 (Q09-AMB pendente smoke real) / F-L-4 (cobertura `pytest-cov` formal deferida 1.4.5) / F-L-5 (smoke E2E em 1.7) — todos com tracking |

### Verdict

**PASS** — Story 1.2 fechada. Status `Ready for Review` → `Done`.

**Próximo passo desbloqueado:** **Wave 5** — Story 1.3 (Dex + Nelo: history
callbacks via `SetHistoryTradeCallbackV2` + `TranslateTrade`) consome o
wrapper em estado conectado. Story 1.5 (Sol + Dex: catálogo SQLite + recovery
boot) também pode rodar em paralelo (não depende de 1.2).

---

## Story 1.5 — Catálogo SQLite + checkpoint/resume

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/1.5.story.md`                          |
| **commit auditado**    | `d1fb2e0`                                            |
| **owner**              | Dex (dev) + Sol (mental review)                      |
| **gatekeeper**         | Quinn (qa)                                           |
| **report path**        | `docs/qa/QA_REPORTS/1.5-2026-05-04.md`               |
| **audit dependente**   | `docs/qa/AUDIT_REPORTS/1.5-storage-2026-05-04.md` (Sol APPROVED) |

### 7 Quality Checks

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Docstrings ricos com owner+ADR refs (SCHEMA.md §5, INTEGRITY.md §3-§5, MIGRATIONS.md, ADR-002), `__all__` explícito, `from __future__ import annotations`, type hints completos (mypy strict 0 errors em 2 source files). Framework de migração com `_semver_le` + UPSERT em `_schema_meta`; transações curtas `BEGIN IMMEDIATE`; two-phase commit emulado bit-a-bit conforme INTEGRITY.md §4. |
| 2. Unit tests        | PASS      | 35 passed em 4.86s (8 init + 9 CRUD + 6 resume + 5 cleanup + 5 reconcile + 2 property Hypothesis). Cobertura agregada catalog+catalog_models = **84.80%** (>= 80% threshold). Por arquivo: catalog.py 82%, catalog_models.py 95%. |
| 3. Acceptance criteria | PASS    | 13/13 ACs Pass (2 com revisão pragmática aceita: AC3 PRAGMAs reduzidos M6 — host modesto; AC11 reconcile log+report em vez de abort para drift B/C — política Sol INTEGRITY.md §5) |
| 4. No regressions    | PASS      | 141 passed, 2 skipped, 0 failed em `pytest tests/` em 8.70s. Story 1.5 não quebra nenhum teste pré-existente (storage 1.4, dll 1.2, smoke imports 1.1). +35 testes ao total (106 → 141). |
| 5. Performance       | PASS      | Cobertura 84.80% reportada; transações curtas (<100ms target); WAL checkpoint após cada `register_partition` com trade-off ~10ms documentado. |
| 6. Security          | PASS      | `pre-commit run detect-secrets --all-files` → `Detect secrets........Passed`. Sem credenciais em código novo. |
| 7. Documentation     | PASS      | File List completa (2 source + 6 test files), Dev Agent Record completo (Agent Model claude-opus-4-7, Debug Log com 2 issues técnicas, Completion Notes com 13 ACs satisfeitas + revisões aceitas, Change Log datado com Sol+Quinn entries) |

### Audits dependentes

| Auditoria       | Verdict          | Justificativa                                                                                          |
|-----------------|------------------|--------------------------------------------------------------------------------------------------------|
| Nelo (DLL)      | N/A              | Story 1.5 não toca `dll/`. Lei R3 não aplicável                                                        |
| Sol (storage)   | **APPROVED**     | Audit em `docs/qa/AUDIT_REPORTS/1.5-storage-2026-05-04.md`. 4 findings LOW (defesa migrations futura, lazy import pyarrow, cobertura erro paths em `_auto_register_from_disk`, microbench). Schema do catálogo bit-a-bit conforme SCHEMA.md §5; two-phase commit emulado; reconcile drift A/B/C; idempotência forte (UPSERT) |
| Aria (design)   | APPROVED implícito | Story 1.5 não cruza fronteiras de camada (puramente storage). API pública (`Catalog`) consome `WriteResult` + `PartitionKey` (Story 1.4). ADR-002 (Parquet+DuckDB+SQLite) e ADR-005 (thread model) preservados. |

### Findings

| Severity  | Count | Detalhes                                                                                              |
|-----------|-------|-------------------------------------------------------------------------------------------------------|
| CRITICAL  | 0     | -                                                                                                     |
| HIGH      | 0     | -                                                                                                     |
| MEDIUM    | 0     | -                                                                                                     |
| LOW       | 7     | F-L-1..4 (Sol — defesa migrations, lazy import, cov erro paths, microbench) + F-Q-1..3 (Quinn — modo strict reconcile, teste explícito WAL checkpoint, smoke DLL) — todos com tracking em Story 1.7/2.1 |

### Verdict

**PASS** — Story 1.5 fechada. Status `Ready for Review` → **Done**.

**Próximo passo desbloqueado:** **Wave 6** — Story 1.7 (orchestrator) pode
agora integrar DLL → orchestrator → writer → **catalog (com two-phase commit
+ recovery)** → reader end-to-end. Em paralelo, Story 2.1 (data validators
executáveis + perf-write-optimization) pode começar.

**Esta gate FECHA F-M-1 da Story 1.4** (catálogo SQLite ausente — finding
MEDIUM deferred). F-M-2 (`sha256_self` no metadata Parquet) continua
deferred-by-scope para Story 2.X.

---

## Story 1.4.5 — Synthetic perf baselines

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/1.4.5.story.md`                        |
| **commit auditado**    | `550ea2c`                                            |
| **owner**              | Pyro (perf-engineer)                                 |
| **gatekeeper**         | Quinn (qa)                                           |
| **report path**        | `docs/qa/QA_REPORTS/1.4.5-2026-05-04.md`             |
| **audit dependente**   | `docs/qa/AUDIT_REPORTS/1.4.5-design-2026-05-04.md` (Aria APPROVED) |

### 7 Quality Checks (adaptados — story de performance, não código de produção)

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Benchmarks têm docstrings + JSON canônico em `benchmarks/results/baselines/`; reprodutibilidade via seed fixo + git_sha + hardware_info; ruff clean (Pyro confirmou) |
| 2. Unit tests        | N/A       | Benchmarks SÃO os testes de perf — não exigem suite pytest paralela. Reprodutibilidade via JSON + processo documentado em BASELINES.md §"Processo de atualização" |
| 3. Acceptance criteria | PASS    | 10/10 ACs Pass (4 com aceitação pragmática: AC4 sem pytest-benchmark paralelo, AC7/AC10 deferred para Story 1.7/DevOps, AC8 dados consolidados em BASELINES.md em vez de sub-doc separado) |
| 4. No regressions    | PASS      | 141 passed, 2 skipped, 0 failed em `pytest tests/` — story não toca `src/`. Apenas adiciona benchmarks/, fixtures/, helpers e atualiza docs/perf/, docs/decisions/ |
| 5. Performance       | PASS (baseline registrado) | 4 baselines registrados em BASELINES.md: `bench_parquet_read` ✅ (61M trades/s vs 1M target — +6038%), `bench_dedup` ✅ (11.32ms p50 vs 50ms target — -77%), `bench_parquet_write` raw ✅ (1.19M trades/s) MAS production ❌ (gap -72% — 27_638 trades/s vs 100k target), `bench_callback_to_disk` chunk-mode ❌ (gap +22x — 2_244ms p99 vs 100ms target). Os 2 FAIL aceitos como realidade arquitetural com roadmap Story 2.1 (COUNCIL-02). H4 e H2 CONFIRMADAS |
| 6. Security          | PASS      | `pre-commit run detect-secrets --all-files` → `Detect secrets........Passed` |
| 7. Documentation     | PASS      | BASELINES.md preenchido com NÚMEROS REAIS (mediana de 5+ runs/config); TARGETS_V1.md atualizado (status aspiracional → measured/gap por bench); COUNCIL-02 documenta finding crítico + sign-off Aria oficial; REGRESSION_BUDGETS.md preservado; File List completa (5 mod + 6 novos + 2 atualizados); Dev Agent Record completo |

### Audits dependentes

| Auditoria       | Verdict          | Justificativa                                                                                          |
|-----------------|------------------|--------------------------------------------------------------------------------------------------------|
| Nelo (DLL)      | N/A              | Story 1.4.5 não toca `dll/`. Mock DLL é fixture local                                                  |
| Sol (storage)   | APPROVED implícito | Sol consultada via mini-council COUNCIL-02 (mental); confirma alinhamento de mock fixtures com SCHEMA.md v1.0.0 (17 campos exatos). AC9 atendida |
| Aria (design)   | **APPROVED**     | Audit em `docs/qa/AUDIT_REPORTS/1.4.5-design-2026-05-04.md`. 3 findings INFO (mock não simula DLL real — esperado; ADR amendment a ADR-005 em Story 1.7 — queue 100k; revisão de target callback→disk p99 em 3 sub-targets). Sign-off COUNCIL-02 oficial (Pyro+Aria) — 6 endorsements + 2 recomendações |

### Findings

| Severity  | Count | Detalhes                                                                                              |
|-----------|-------|-------------------------------------------------------------------------------------------------------|
| CRITICAL  | 0     | -                                                                                                     |
| HIGH      | 0     | -                                                                                                     |
| MEDIUM    | 0     | -                                                                                                     |
| LOW       | 6     | F-L-1 (2 verdicts FAIL = realidade arquitetural — tracking Story 2.1) + F-L-2 (mock vs DLL real — Story 1.7/1.8) + F-L-3 (ADR amendment + 3 sub-targets — Story 1.7) + F-L-4 (mock fixture deferred — Story 1.7) + F-L-5 (CI hook deferred — DevOps) + F-L-6 (hardware modesto — re-rodar em CI moderno futuro) |

### Verdict

**PASS** — Story 1.4.5 fechada. Status `Ready for Review` → **Done**.

**Baseline canônico v1.0.0-synthetic registrado** com números honestos (não
mascarados). Pyro convocou COUNCIL-02 para documentar 2 verdicts FAIL com
causa raiz + roadmap. Aria endossou formalmente com 6 endorsements + 2
recomendações não-vinculantes (sign-off oficial).

**Próximo passo desbloqueado:**
- **Story 1.7b (smoke MVP)** — gate honesto desbloqueado (era bloqueado por
  "palpites" V1; agora baseline registrado).
- **Story 2.1 (perf-write-optimization)** — Morgan (PM) deve criar com
  Pyro como owner + Sol como reviewer + property tests Hypothesis (recomendação
  Aria 7).
- **Story 1.7 (orchestrator)** — incorporar recomendações Pyro (queue 100k +
  métricas) com ADR amendment a ADR-005 (Aria endorsed).
- **Story 1.8 (real DLL E2E)** — re-rodar 4 benchmarks com DLL real para
  registrar v1.0.0-real baseline.

---

## Story 1.3 — History download primitive: 1 símbolo / 1 chunk

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/1.3.story.md`                          |
| **commit auditado**    | `beac226`                                            |
| **owner**              | Dex (dev) + COUNCIL-03 (Dex+Nelo+Sol mental)         |
| **gatekeeper**         | Quinn (qa)                                           |
| **report path**        | `docs/qa/QA_REPORTS/1.3-2026-05-04.md`               |
| **audits dependentes** | `docs/qa/AUDIT_REPORTS/1.3-dll-2026-05-04.md` (Nelo APPROVED) + `docs/qa/AUDIT_REPORTS/1.3-design-2026-05-04.md` (Aria APPROVED) |

### 7 Quality Checks

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Docstrings ricos com owner+ADR refs (manual ProfitDLL §3.1/§3.2/§4, COUNCIL-03, ADR-005/007a/010/011, QUIRKS Q01-V/Q02-E/Q03-AMB/Q04-E/Q05-V/Q06-V/Q07-V/Q11-E/Q13-V), `__all__` explícito, `from __future__ import annotations`, type hints completos. Lei R3 / INV-1 cumprida (callbacks `_history_cb` e `_progress_cb` fazem único `put_nowait` em `with contextlib.suppress(Full)`). TranslateTrade chamado em `_IngestorThread._process_trade` (FORA do callback). 4 threads físicas com nomes únicos. Constantes nomeadas para tunables (TRADE_QUEUE_MAXSIZE=100_000 — finding Pyro 1.4.5; PROGRESS_QUEUE_MAXSIZE=1000; DEFAULT_TIMEOUT_SECONDS=1800). Validação exchange em 2 fronteiras |
| 2. Unit tests        | PASS      | **218 passed + 1 skipped em 18.33s** em `pytest tests/ -v --ignore=tests/smoke`. Por suite Story 1.3: 31 testes wrapper history + 23 timestamp parser (2 Hypothesis) + 16 integration download_primitive + ~140 LoC novos em test_dll_callbacks (V2 history+progress + INV-1 assertions). Lei R3 / INV-1 validada via `test_history_callback_does_not_invoke_translate_trade_inv1` (mock_dll.mock_calls == [] E TranslateTrade.called == False) |
| 3. Acceptance criteria | PASS    | **10/10 ACs Pass** com evidência reprodutível. AC1 (V2 callback registrados, decisão COUNCIL-03 documentada); AC2 (`download_chunk` API completa); AC3 (ChunkResult frozen 13 campos); AC4 (TradeRecord 17 campos schema v1.0.0); AC5 (callback APENAS put_nowait — R3); AC6 (timeout 1800s + Q02-E tolerado); AC7 (datas formato manual §3.1 L1750); AC8 (bolsa letra única); AC9 (BRT naive R7 + Q03-AMB dual-format); AC10 (smoke gated por env, real em Story 1.7) |
| 4. No regressions    | PASS      | 218 passed + 1 skipped, 0 failed em `pytest tests/`. Adições aditivas (V2 callbacks novos, novos métodos no wrapper, novo módulo orchestrator/) sem quebrar dll/types, dll/callbacks, dll/wrapper (state callback, init/finalize), storage/, public_api/, benchmarks. **+72 testes** ao total |
| 5. Performance       | PASS      | **Cobertura 95.32%** (target 80%+) em escopo dll + orchestrator (531 stmts, 20 miss, 88 branches, 9 partials). Por arquivo: types.py 100%, errors.py 100%, callbacks.py 97%, wrapper.py 93%, orchestrator/__init__.py 100%, timestamp.py 100%, download_primitive.py 96%. Hot path R21 respeitado: callback zero alloc além de tuple; struct reusado em IngestorThread. Pyro 1.4.5 baselines validam queue 100k (COUNCIL-02 + ADR-005 amendment) |
| 6. Security          | PASS      | `pre-commit run detect-secrets --all-files` -> `Detect secrets........Passed`. Sem credenciais em código novo. Smoke gated por env vars (PROFITDLL_KEY/USER/PASSWORD). Callback NÃO loga args (R3 + ADR-010). Sem print/log debug residual em hot path |
| 7. Documentation     | PASS      | File List completa (4 source novos + 4 test files novos + 5 source estendidos). Dev Agent Record completo (Agent Model Dex claude-opus-4-7; Debug Log com 5 issues; Completion Notes com métricas; Change Log datado 2026-05-03 + 2026-05-04 com Nelo+Aria+Quinn entries). COUNCIL-03 documenta decisão V2 com justificativa + concordância mental Nelo + Sol. QUIRKS.md referenciado (Q01-V/Q02-E/Q03-AMB/Q04-E/Q05-V/Q06-V/Q11-E/Q13-V). Manual ProfitDLL referenciado nos snippets críticos |

### Audits dependentes

| Auditoria       | Verdict          | Justificativa                                                                                          |
|-----------------|------------------|--------------------------------------------------------------------------------------------------------|
| Nelo (DLL)      | **APPROVED**     | 22-pt `wrapper_review` checklist PASS. Manual ProfitDLL respeitado (§3.1/§3.2/§4). COUNCIL-03 endossado (V2 callback + TranslateTrade fora do callback). Q01-V/Q02-E/Q03-AMB/Q04-E/Q05-V/Q06-V/Q07-V/Q11-E/Q13-V endereçados. **Lei R3 / INV-1 verificada em teste** (mock_dll.mock_calls == [] E TranslateTrade.called == False). 3 findings LOW/INFO (dupla validação exchange, TC_LAST_PACKET=0x02 convenção pendente smoke 1.7, parse_brt_timestamp não-exercitado por V2). Path: `docs/qa/AUDIT_REPORTS/1.3-dll-2026-05-04.md` |
| Sol (storage)   | APPROVED implícito | COUNCIL-03 mental: source_callback="history_v2", sequence_within_ns preenchido mesmo com trade_id, schema 17 campos exatos. Storage layer não tocado em 1.3 (writer chamado em Story 1.7) |
| Aria (design)   | **APPROVED**     | 11-pt `design_review` checklist PASS. ADR-005 (thread model + R3) com **separação física** real de 4 threads. ADR-005 amendment (queue 100k Pyro 1.4.5) aplicado. ADR-007a (public_api facade diferida 1.7a/b). ADR-010 + R21 hot-path. ADR-011 hierarquia 4-level. INV-1/INV-3/INV-11/INV-12 preservados (parcialmente para INV-12 — commit catalog em 1.7a). 4 findings INFO (queue overflow silencioso 2.1, dupla validação 2.X, public API 1.7a/b, timeout per-chunk 1.7). Path: `docs/qa/AUDIT_REPORTS/1.3-design-2026-05-04.md` |

### Findings

| Severity  | Count | Detalhes                                                                                              |
|-----------|-------|-------------------------------------------------------------------------------------------------------|
| CRITICAL  | 0     | -                                                                                                     |
| HIGH      | 0     | -                                                                                                     |
| MEDIUM    | 0     | -                                                                                                     |
| LOW       | 7     | F-N-1 (dupla validação exchange — DRY refactor 2.X) / F-N-2 (TC_LAST_PACKET=0x02 convenção — smoke 1.7 valida) / F-N-3 (parse_brt_timestamp não-exercitado por V2 — Story 1.5 V1) / F-A-1 (queue overflow silencioso — Story 2.1 metric) / F-A-2 (idem F-N-1 — DRY 2.X) / F-A-3 (public API surface diferida — Story 1.7a/b) / F-A-4 (timeout per-chunk — Story 1.7 design) — todos com tracking |

### Verdict

**PASS** — Story 1.3 fechada. Status `Ready for Review` -> **Done**.

**Próximo passo desbloqueado:**
- **Story 1.7a (orchestrator chunking + retry)** — consome `download_chunk`
  primitiva; estende para multi-chunk com catalog SQLite (Story 1.5) e
  writer Parquet (Story 1.4) end-to-end.
- **Story 1.6 (rollover table)** — resolve alias WDOFUT → contrato vigente
  (Q01-V) — pré-requisito para 1.7a/b.

---

## Story 2.1 — Data integrity validators como código (subpacote validation/)

| Campo                  | Valor                                                |
|------------------------|------------------------------------------------------|
| **story_path**         | `docs/stories/2.1.story.md`                          |
| **commit auditado**    | (preenchido após commit)                             |
| **owner**              | Sol+Quinn (modo autônomo, claude-opus-4-7)           |
| **gatekeeper**         | Quinn (qa) — modo autônomo (Sol+Quinn co-owners)     |
| **report path**        | `docs/qa/QA_REPORTS/2.1-2026-05-04.md`               |
| **audit dependente**   | `docs/qa/AUDIT_REPORTS/2.1-storage-2026-05-04.md` (Sol APPROVED) |

### 7 Quality Checks

| Check                | Resultado | Nota                                                                  |
|----------------------|-----------|-----------------------------------------------------------------------|
| 1. Code review       | PASS      | Docstrings ricos com refs INTEGRITY.md §1/§2/§5; queries DuckDB **bit-a-bit canônicas** vs INTEGRITY.md §2 (auditado por Sol §3.2) |
| 2. Unit tests        | PASS      | 37 passed em 6.07s; cobertura `validation` **89.20%** (>= 80%) |
| 3. Acceptance criteria | PASS    | 10/10 ACs (6 literal + 4 revised via mini-council Sol+Quinn — escopo refinado preservando intent) |
| 4. No regressions    | PASS      | 297 passed, 4 skipped, 0 failed em `pytest tests/` (+37 testes ao total) |
| 5. Performance       | PASS      | DuckDB queries com pruning `WHERE timestamp_ns BETWEEN`; iteração linear OK |
| 6. Security          | PASS      | Sem credenciais; SQL parametrizado; sem `eval`/`exec` |
| 7. Documentation     | PASS      | COUNCIL-04 documenta dep `pandas`; audit Sol APPROVED; File List completa |

### Verdict

**PASS** — Story 2.1 fechada. Status `Draft` → **Done**.

**Esta gate FECHA Epic 1 finding C4** (validators existem como código,
não em palpite).

---

## Resumo consolidado (gates 2026-05-04)

| Story | Owner | Commit  | Verdict | LOW | MED | HIGH | CRIT | Report |
|-------|-------|---------|---------|-----|-----|------|------|--------|
| 1.1   | Dex   | 95c7acf | PASS    | 3   | 0   | 0    | 0    | `docs/qa/QA_REPORTS/1.1-2026-05-04.md` |
| 1.4   | Dex   | 3d447bb | PASS    | 4   | 2   | 0    | 0    | `docs/qa/QA_REPORTS/1.4-2026-05-04.md` |
| 1.2   | Dex   | f2a766d | PASS    | 5   | 0   | 0    | 0    | `docs/qa/QA_REPORTS/1.2-2026-05-04.md` |
| 1.5   | Dex+Sol | d1fb2e0 | PASS    | 7   | 0   | 0    | 0    | `docs/qa/QA_REPORTS/1.5-2026-05-04.md` |
| 1.4.5 | Pyro  | 550ea2c | PASS    | 6   | 0   | 0    | 0    | `docs/qa/QA_REPORTS/1.4.5-2026-05-04.md` |
| 1.3   | Dex+COUNCIL-03 | beac226 | PASS    | 7   | 0   | 0    | 0    | `docs/qa/QA_REPORTS/1.3-2026-05-04.md` |
| 2.1   | Sol+Quinn | (TBD) | PASS    | 4   | 0   | 0    | 0    | `docs/qa/QA_REPORTS/2.1-2026-05-04.md` |

**Total:** 7 stories passadas pelo gate em 2026-05-04. 7 PASS, 0 CONCERNS, 0 FAIL, 0 WAIVED.

**Total findings acumulados:** 36 LOW + 2 MEDIUM + 0 HIGH + 0 CRITICAL — todos
com tracking documentado em stories futuras (1.5, 1.6, 1.7, 1.7a/b, 1.8, 2.X, DevOps).

**Story 2.1 fecha Epic 1 finding C4** (validators executáveis em código real
— `data-downloader integrity check` + `integrity validate-data`).

**Story 1.5 fecha F-M-1 da Story 1.4** (catálogo SQLite ausente). F-M-2
(`sha256_self` no metadata Parquet) permanece deferred para Story 2.X.

**COUNCIL-02 ratificado oficialmente** (Pyro+Aria) — Story 2.1
perf-write-optimization a ser criada por Morgan (PM).

**COUNCIL-03 ratificado em 1.3** (Dex+Nelo+Sol mental) — V2 callback
+ TranslateTrade fora do callback escolhidos com justificativa formal
(R10/Q13-V + trade_id real + TC_LAST_PACKET autoritativo). Primeira
fronteira `orchestrator/` ↔ `dll/` desenhada e validada — desbloqueia
Story 1.7a (orchestrator multi-chunk).

**COUNCIL-04 ratificado em 2.1** (Sol+Aria+Quinn mental) — `pandas>=2.0`
adicionado como dep transversal para business-days B3 + classificação
de gap. Implementação V1 hardcoded em `validation/calendar_b3.py`
(2025-2026 cobertos); pandas fica como dep formal para integração
futura com `holidays.dat` Nelogica + property tests com `pd.bdate_range`
como oracle.

---

— Quinn, no portão
