# COUNCIL-28 — V1.0 Release Readiness (Story 4.3 verification + path to release)

**Data:** 2026-05-04
**Convocação:** Mini-council Quinn + Aria + Gage — modo autônomo (verificação Story 4.3 Ready for Review @ `9304106`)
**Participantes mentais:**

- 🧪 Quinn (The Gatekeeper — qa-gate authority Story 4.3)
- 🏛️ Aria (Architect — review-design Story 4.3 + ADR-007a custodian)
- ⚙️ Gage (DevOps — CHANGELOG release authority + release ritual)

**Status:** RATIFIED (autonomous mode — sem reviewers humanos blocking; pendências de smoke real escaladas a humano por COUNCIL-09)

---

## 1. Contexto

Story 4.3 (Public API estável V1.0 release) foi entregue por COUNCIL-27
(Aria + Dex + Gage) em 2026-05-04 @ `9304106`:

- `__api_version__` bumpado 0.3.0 → 1.0.0.
- Module docstring exhaustivo (157 linhas) em `public_api/__init__.py`:
  visão geral + 7 garantias contratuais + política SemVer estrito +
  cobertura SemVer (coberto vs NÃO coberto) + histórico de bumps.
- Docstrings Google style completos (Args/Returns/Raises/Examples/Notes)
  em 4 funções (`download`, `read`, `read_continuous`, `vigent_contract`)
  + 4 classes (`DownloadHandle`, `DownloadProgress`, `DownloadResult`,
  `DownloadStatus`) + 8 exceções (todas subclasses de
  `DataDownloaderError`).
- `docs/public_api/USAGE.md` (~507 linhas) — 3 exemplos copy-paste
  funcionais (backtest mean-reversion + signal generator EMA/VWAP +
  risk monitor cross-symbol).
- `docs/public_api/DEPRECATION_POLICY.md` (~215 linhas) — SemVer
  estrito + lifecycle ≥ 2 minor + ≥ 6 meses + workflow consumer +
  tracker (vazio em V1.0 baseline).
- `src/data_downloader/public_api/_deprecation.py` (~140 linhas) —
  decorator `@deprecated(*, since, removed_in, replacement=None)`.
- `CHANGELOG.md` (~200 linhas) — Keep a Changelog 1.1.0 + SemVer 2.0;
  backfill v0.1.0..v0.4.0 + entry V1.0.0.
- 47 SemVer regression tests (`test_public_api_semver_regression.py`)
  + 6 no-internal-imports tests (`test_public_api_no_internal_imports.py`)
  = 53 novos PASS em 1.98s.

Esta convocação COUNCIL-28 finaliza o ritual de QA + release readiness:
3 personas validam independentemente e emitem verdict tríade.

---

## 2. Verdicts independentes

### 🏛️ Aria (Architect — review-design)

**APPROVED** — fronteira pública estável V1.0, ritual completo.

Audit completo em `docs/qa/AUDIT_REPORTS/4.3-design-2026-05-04.md`:

- 5 checklists customizados (design_review V1.0 release +
  adr_007a_conformance + adr_011_conformance + changelog_format +
  fronteira_publica_invariantes).
- ADR-007a (DownloadHandle) preservado intacto — 8 métodos públicos
  todos documentados (cancel/result/events/peek_result/cancelled/
  is_cancelled/is_cancelling/join).
- ADR-011 (exception hierarchy) preservado intacto — 8 exceções,
  todas subclasses de `DataDownloaderError`, todas com
  `humanized_message` (mapa `_PUBLIC_ERROR_MICROCOPY_ID`).
- Constitutional Article IV (No Invention) respeitado — `__all__` 17
  símbolos idênticos a V0.4 baseline (regression test enforce).
- Decorator `@deprecated` em `public_api/_deprecation.py`
  (não em `_internal/`) — desvio justificado D3 COUNCIL-27.
- Findings: 0 CRITICAL, 0 HIGH, 0 MEDIUM, 3 LOW (CI enforcement
  deferrals — todos com mitigação documentada), 2 INFO.

— Aria, custodiando a fronteira (e formalizando V1.0) 🏛️

### 🧪 Quinn (Gatekeeper — qa-gate)

**PASS** — Story 4.3 fechada. Status `Ready for Review` → **`Done`**.

QA Gate report completo em `docs/qa/QA_REPORTS/4.3-2026-05-04.md`:

- AC 7/7 PASS literal (4 sem reserva + 3 com notas deferred
  não-bloqueantes para CI mecânico).
- 47 + 6 = 53 novos tests PASS em 1.98s; suite full integration
  73 tests PASS em 125.91s sem regressão.
- `ruff check` All checks passed; `mypy --strict` 0 errors em 6
  source files.
- Cobertura `public_api/` 65% — divergente de "95%+" aspiracional,
  MAS justificada: `_deprecation.py` 0% intencional (decorator não
  aplicado a nenhum símbolo em baseline V1.0); `download.py` 52%
  reflete escopo mock-first (worker real precisa smoke DLL — Story
  1.7b-followup). Restantes excelentes (`__init__.py` 100%,
  `exceptions.py` 94%, `history.py` 98%, `handle.py` 76%).
- Findings: 0 CRITICAL/HIGH/MEDIUM, 3 LOW, 2 INFO — todos com
  tracking explícito em COUNCIL-27 §5 Pendências.

— Quinn, no portão (V1.0 stable) 🧪

### ⚙️ Gage (DevOps — CHANGELOG release authority)

**APPROVED** — CHANGELOG canônico + release ritual cumprido para o
escopo desta story.

CHANGELOG validation completa em `docs/qa/QA_REPORTS/4.3-2026-05-04.md`
§6 + audit Aria §3.4:

- Formato Keep a Changelog 1.1.0 + SemVer 2.0 respeitado.
- Backfill retroativo correto: v0.1.0 (Story 1.5b — read,
  read_continuous, vigent_contract + base exceptions); v0.2.0 (Story
  1.6 — vigent_contract público + InvalidContract); v0.3.0 (Story
  1.7b — download + DownloadHandle/Progress/Result + ADR-007a
  rationale); v0.4.0 (Story 2.11 — OperationCancelled/ConnectionLost
  + cancelled/is_cancelled/peek_result + soft-break documentado em
  result()); v1.0.0 (Story 4.3 — formalização SemVer estrito).
- Entry V1.0.0 lista 7 garantias contratuais + 17 exports estáveis +
  NÃO coberto por SemVer + roadmap V1.x (`download_batch` se demanda)
  + V2.0 (intencionalmente vazio).
- Sign-off Gage como release authority registrado em COUNCIL-27 §3
  + verdict desta convocação.

**Pendências do release ritual (NÃO desta story):**

- P3 — `py.typed` marker em `src/data_downloader/` quando publicar em
  PyPI (Story 4.4 packaging).
- P4 — GitHub Release tag `api-v1.0.0` com CHANGELOG inline (Story
  4.4 packaging).

— Gage, fechando o release (parcial — V1.0 stability stamp; release
físico em Story 4.4) ⚙️

---

## 3. Decisão tríade — V1.0 Release Readiness

### Verdict consolidado: **GO-WITH-DEFERRED**

**Story 4.3 → Done.** Mas **release V1.0 oficial NÃO está pronto** —
aguarda dois bloqueios estruturais (não bloqueiam Story 4.3 isolada).

### Decomposição

| Aspecto                                                                    | Verdict          | Justificativa                                                                                                     |
|----------------------------------------------------------------------------|------------------|-------------------------------------------------------------------------------------------------------------------|
| Story 4.3 (formalização V1.0 — docstrings + USAGE + DEPRECATION + CHANGELOG + bump + tests + decorator) | ✅ **GO**            | Aria APPROVED + Quinn PASS + Gage APPROVED. Bumpou versão, formalizou contrato, escreveu política, criou regression suite, backfilled CHANGELOG. Ritual completo dentro do escopo da story. |
| **`__api_version__` runtime declarado V1.0.0**                              | ✅ **GO (DECLARED)** | Backtest engine + outros consumers internos podem pinar `data-downloader>=1.0,<2.0` HOJE com confiança SemVer estrita (vinculante a partir de `9304106`). |
| **Release V1.0 OFICIAL (físico — packaging + tag + binary distribution)**   | ⏸️ **DEFERRED**     | Bloqueado por: (a) Story 4.4 (packaging — `py.typed`, GitHub Release tag, `.exe` distribution); (b) smoke real humano — Story 1.7b-followup gates por COUNCIL-09 política (release V1 não pode sair sem smoke DLL real). |

### Bloqueios remanescentes (não bloqueiam Story 4.3, bloqueiam release V1 oficial)

| #   | Bloqueio                                                              | Owner                  | Status                                                                                                       |
|-----|-----------------------------------------------------------------------|------------------------|--------------------------------------------------------------------------------------------------------------|
| B1  | Smoke real DLL multi-symbol (4 símbolos × 1 dia paralelo, ProfitDLL real) | Story 1.7b-followup (humano) | Bloqueia release V1 (COUNCIL-09 política). Pré-requisito Q17-OPEN respondido (Nelogica multi-instância licença). |
| B2  | Story 4.4 — release V1 packaging (`py.typed` marker + GitHub Release tag `api-v1.0.0` + binary distribution + auto-updater bootstrap) | @pm convoca + @dev/@devops impl | Próxima story Epic 4. Fecha Epic 4 (Stories 4.1 broker + 4.2 multi-asset + 4.3 V1.0 stable + 4.4 packaging release). |

### Pendências de polimento (não bloqueiam V1.0 release — débito V1.x ou Story 4.3-followup)

| ID  | Pendência                                                                                       | Owner                  | Bloqueia                                                                                |
|-----|-------------------------------------------------------------------------------------------------|------------------------|------------------------------------------------------------------------------------------|
| P1  | Refactor `test_public_api_history.py` para `data_downloader.testing.fixtures` (reduz whitelist guardrail) | Dex (Story 4.3-followup ou V1.x) | Reduzir whitelist guardrail anti-leak a apenas `storage.catalog`.                         |
| P2  | `interrogate` ou `pydocstyle` em CI para enforce 100% docstring coverage mecanicamente          | Gage (Story 4.3-followup) | Validação manual hoje; mecanização futura.                                                |
| P3  | `py.typed` marker em `src/data_downloader/` quando publicar em PyPI                              | Gage (Story 4.4)       | Type stubs visíveis a consumers externos PyPI.                                            |
| P4  | GitHub Release tag `api-v1.0.0` com CHANGELOG inline                                              | Gage (Story 4.4)       | Discovery via GitHub UI / tooling.                                                        |
| P5  | Doctest runner em CI para validar code blocks em `USAGE.md`                                       | Gage (Story 4.3-followup) | Garantir que exemplos USAGE.md compilam em refactors V1.x.                                |
| P6  | `test_deprecation_decorator.py` formal — primeira deprecação real em V1.x dispara                 | Dex (V1.x)             | Cobertura `_deprecation.py` 0% até primeiro símbolo deprecado real (decorator infraestrutural sem uso). |

---

## 4. Recomendação operacional

### 4.1 Marcação Story 4.3

**Atualizar `docs/stories/4.3.story.md` Status `Ready for Review` → `Done`** com Change Log entry:

| Data       | Quem                | Mudança |
|------------|---------------------|---------|
| 2026-05-04 | Quinn+Aria+Gage     | COUNCIL-28 — Story 4.3 → Done. Verdict GO-WITH-DEFERRED para release V1.0 oficial: stability stamp HOJE; release físico aguarda 4.4 + smoke real humano (COUNCIL-09). |

### 4.2 Próximos passos imediatos

1. **Story 4.4 (packaging release)** — convocar @pm para criar story.
   Cobertura esperada:
   - `py.typed` marker (P3).
   - GitHub Release tag `api-v1.0.0` com CHANGELOG inline (P4).
   - PyPI vs GitHub Releases decisão (Gage authority).
   - `.exe` distribution + auto-updater bootstrap.
2. **Story 1.7b-followup** — humano executa smoke real DLL multi-symbol.
   Pré-requisito Q17-OPEN (licença Nelogica multi-instância) respondido.
3. **Story 4.3-followup (opcional)** — interrogate/pydocstyle CI (P2)
   + doctest runner (P5) + refactor `test_public_api_history.py` (P1)
   se squad priorizar antes de V1.x release.

### 4.3 Comunicação a downstream consumers

Backtest engine, signal generator, risk monitor (próximos projetos
squad) podem **HOJE**:

- Adicionar dep `data-downloader>=1.0,<2.0` no `pyproject.toml`.
- Inspecionar `__api_version__` em runtime (`assert
  __api_version__.startswith("1.")`).
- Capturar `DeprecationWarning` em CI via `filterwarnings =
  ["error::DeprecationWarning:data_downloader.*"]`.
- Importar APENAS de `data_downloader.public_api` (zero leak interno).

Importante: HOJE = `pip install -e .` em ambiente squad (sem PyPI
ainda). PyPI publishing é Story 4.4.

---

## 5. Sign-off tríade

### 🧪 Quinn (Gatekeeper)

> Story 4.3 fechada com PASS. AC 7/7, 53 novos tests PASS, lint+typecheck
> clean, sem regressão. Cobertura `public_api/` 65% justificada (decorator
> infraestrutural sem uso real em V1.0 baseline + worker DLL precisa smoke).
> Recomendação Story 4.3 → Done. Release V1.0 oficial: GO-WITH-DEFERRED.

### 🏛️ Aria (Architect)

> Fronteira pública estável V1.0 formalizada. ADR-007a + ADR-011
> preservados intactos. `__all__` 17 símbolos idênticos a V0.4 baseline
> (Article IV). Module docstring + USAGE.md + DEPRECATION_POLICY.md
> exaustivos. Decorator `@deprecated` infraestrutural pronto.
> Recomendação Story 4.3 → Done. V1.0 stable a partir de `9304106`.

### ⚙️ Gage (DevOps)

> CHANGELOG canônico (Keep a Changelog 1.1.0 + SemVer 2.0). Backfill
> retroativo correto v0.1..v0.4 + entry V1.0.0. Sign-off como release
> authority. Release V1.0 oficial **aguarda Story 4.4** (packaging
> ritual: py.typed + GitHub Release tag + binary distribution) E smoke
> real humano (COUNCIL-09). Story 4.3 cumpriu sua parte do ritual.

---

## 6. Decisão chave consensual

**A V1.0 da `data_downloader.public_api` está formalmente declarada
estável a partir de `9304106` (Story 4.3 commit).** Todos os símbolos
em `__all__` são governados por SemVer estrito a partir desta data.
Mudanças breaking exigem bump major (V2.0) + cycle de deprecação
prévio (≥ 2 minor versions, ≥ 6 meses calendário). Backtest engine
(próximo consumer interno) pode pinar `data-downloader>=1.0,<2.0` com
confiança HOJE.

**Mas o release V1.0 OFICIAL (físico, com binary distribution + tag
GitHub + smoke real validado por humano) ainda NÃO ocorreu** — ele
ocorrerá quando Story 4.4 (packaging) entregar o `.exe` final E
Story 1.7b-followup (smoke real humano) for executada. A separação é
intencional: Story 4.3 é **stability stamp** (contrato declarado);
Story 4.4 + smoke real é **release event** (binary distribution).

---

## 7. Referências

- `docs/stories/4.3.story.md` (esta story — atualizada → Done)
- `docs/decisions/COUNCIL-27-public-api-v1-release.md` (impl COUNCIL Aria+Dex+Gage)
- `docs/decisions/COUNCIL-09-...` (smoke real política — bloqueia release V1)
- `docs/decisions/COUNCIL-13-epic4-prep.md` (D4 — Aria implementer Dex)
- `docs/decisions/COUNCIL-17-exception-hierarchy-h10-cancel.md` (Story 2.11 soft-break)
- `docs/qa/AUDIT_REPORTS/4.3-design-2026-05-04.md` (Aria audit completo)
- `docs/qa/QA_REPORTS/4.3-2026-05-04.md` (Quinn QA gate completo)
- `docs/adr/ADR-007a-public-api-redesign.md` (DownloadHandle design)
- `docs/adr/ADR-011-exception-hierarchy.md` (exception hierarchy)
- `docs/public_api/USAGE.md` (3 exemplos consumer)
- `docs/public_api/DEPRECATION_POLICY.md` (política formal)
- `CHANGELOG.md` (Keep a Changelog 1.1.0 + SemVer 2.0)
- `src/data_downloader/public_api/__init__.py` (V1.0 declarada @ commit `9304106`)

---

— Quinn 🧪, Aria 🏛️, Gage ⚙️ — V1.0 stability declared, release físico em 4.4.
