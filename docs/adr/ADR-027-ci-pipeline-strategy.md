# ADR-027 — CI Pipeline Strategy (GitHub Actions: test + release + auto-AUDIT)

- **Status:** Proposed
- **Date:** 2026-05-17
- **Author:** Aria (@architect) + consulta @devops (Gage), @qa (Quinn)
- **Driver:** Revisão consolidada Frente 2 v1.4.0 — repositório sem CI (`.github/` inexistente); R13/R14 (disciplina de gates pré-commit + AUDIT por release) dependem de execução humana sem barrier mecânico; build empírico em Python 3.14 contra `requires-python>=3.12` quase causou regressão (mitigado em Story 4.31 AC8 via guard `sys.version_info[:2] != (3, 12)` em `scripts/build_release.py`); `verify-dll-companions.py` falha durante o pipeline de build (`err1.log`); RELEASES.md backfilled em 4.31 AC5 mas sem auto-AUDIT garantido.
- **Supersedes:** — (complementa ADR-009 §"Camada 5: CI controlled" deferido, e ADR-016 §"Code signing" deferido para futuro)

---

## 1. Contexto

A v1.3.0 fechou um ciclo de 7 releases em ~13 dias com qualidade alta — mas inteiramente artesanal. Cada release foi:

1. Edição manual de `pyproject.toml` / `__init__.py` / `installer/data_downloader.iss` (drift recorrente; ver Story 4.31 AC4).
2. `scripts/build_release.py` invocado localmente em **Python 3.14** (no laptop de Pichau) apesar de `requires-python>=3.12` declarado. Mitigado parcialmente por AC8 (4.31) que adiciona guard, mas guard só dispara quando alguém roda — CI **previne** antes de tocar disk.
3. `pytest` + `ruff` + `mypy --strict` invocados manualmente. Suite full demora ~5min e foi pulada em pelo menos 2 ocasiões documentadas (`docs/qa/RELEASE-GATE-v1.1.0-RESULTS.md` round 1).
4. `gh release create` invocado em sequência manual com `scripts/github_release.py` (que existe, mas exige operador humano lembrar de chamar).
5. SHA256 dos artefatos calculado e copiado à mão para `docs/release/RELEASES.md` (4.31 AC5 backfilled mas sem mecanismo automático).

A revisão consolidada 2026-05-16 (Frente 2) classificou essa configuração como **risco P0-R1..R5**:

| ID | Risco | Estado atual | Severidade |
|----|-------|--------------|------------|
| **P0-R1** | Suite full não roda em PR | Disciplina humana | HIGH (regressão silenciosa) |
| **P0-R2** | Build Python wrong version | Guard ad-hoc (AC8 4.31) | MEDIUM (mitigado mas reativo) |
| **P0-R3** | `verify-dll-companions` falha no build | Erro em `err1.log` | MEDIUM (atualmente: build segue) |
| **P0-R4** | RELEASES.md sem auto-AUDIT | Backfill manual (AC5 4.31) | LOW (mas R14 violado) |
| **P0-R5** | SHA256 publicado fora-de-banda | Manual no commit pós-release | MEDIUM (auditabilidade) |

A solução exige decidir sobre **escopo, matriz, runners, secret management** antes de implementar — caso contrário a Story 4.25 vira "scope creep com workflows redundantes".

## 2. Decisão

### 2.1 Estrutura — 2 workflows core

```
.github/
  workflows/
    test.yml      # CI: PR, push para main, dispatch manual
    release.yml   # CD: tag v* (workflow_dispatch fallback)
```

**Por que apenas 2:** simplicidade > completude no v1.4.0. Workflow extras (CodeRabbit autoreview, dependabot auto-merge, scheduled smoke) ficam para v1.5.0+ se necessário. ADR-027 estabelece a fundação; iterações incrementais via stories curtas depois.

### 2.2 Matriz — single Python, single OS (Windows-only)

| Dimensão | Decisão | Justificativa |
|----------|---------|---------------|
| **Python** | `3.12` único | `requires-python>=3.12` declarado + lock by R19. Adicionar 3.13 multiplica tempo CI por 2 sem benefício imediato (não temos 3.13 user-base). |
| **OS** | `windows-latest` único | Projeto é **Windows-only** por ProfitDLL dependency (ADR-008). Linux runner não consegue importar `ProfitDLL.dll`. Custo `windows-latest` ~10× `ubuntu-latest` (~$0.08/min vs ~$0.008/min), mas alternativa é impraticável. |
| **Arch** | `x64` único | DLL é 64-bit. |
| **Caching** | `pip` via `actions/setup-python` builtin | Acelera ~2-3min em PRs subsequentes. Hash de `pyproject.toml` invalida. |

**Trade-off documentado:** v1.5.0 pode reavaliar adicionar `windows-2022` se Microsoft deprecar `windows-latest` mapping para 2025. Hoje (2026-05-17), `windows-latest = windows-2022`. **Não** adicionamos `macos-latest`/`ubuntu-latest` — falsos positivos garantidos pela DLL.

### 2.3 `test.yml` — escopo

**Triggers:**

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  workflow_dispatch:  # manual rerun, debug
```

**Jobs:**

1. **`lint-type`** (paralelo, < 2min):
   - Checkout, setup Python 3.12, install `pip install -e ".[dev]"`.
   - `ruff check src/ tests/`.
   - `mypy --strict src/data_downloader/`.
   - Falha o job em qualquer warning/erro.

2. **`unit-tests`** (paralelo, < 5min):
   - Checkout, setup Python 3.12, install `pip install -e ".[test,dev]"`.
   - `pytest tests/unit -v --maxfail=5 --timeout=60`.
   - Upload `junit-unit-*.xml` como artifact (retention 30 dias).

3. **`integration-property-tests`** (paralelo, < 8min):
   - Idem unit, mas `pytest tests/integration tests/property -v --maxfail=3 --timeout=180`.
   - **Skip** tests marcados `@pytest.mark.smoke` (DLL real exige ProfitChart + credenciais reais — não disponíveis em GH runner).
   - Upload artifact.

4. **`pre-commit`** (paralelo, < 2min):
   - `pre-commit run --all-files`.
   - Inclui `bandit` + `pip-audit` + `detect-secrets` (já configurados pós-4.31 AC6).

**Convergência:** todos os 4 jobs devem ser PASS para merge habilitado (branch protection rule documentada em `.github/branch-protection.md` para humano configurar manualmente — GH Actions não tem API para auto-configurar). Status checks aparecem no PR via GH UI.

**O que NÃO entra no test.yml v1.4.0:**

- Coverage report. `pyproject.toml` já tem `[tool.coverage]` com `fail_under = 80` — adicionar coverage no CI exige `coverage run` + upload. Deferido para v1.5.0 (Story TBD) — adicionar Codecov ou similar.
- Tests `@pytest.mark.smoke` (real DLL). Sem ProfitChart no runner.
- Build PyInstaller. Caro (~5min) + exige DLL companions. Vai para release.yml.
- `verify-dll-companions.py`. Sem DLLs no runner. Vai para release.yml com escopo restrito ao bundle.

### 2.4 `release.yml` — escopo

**Trigger:**

```yaml
on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      version:
        description: 'Version to release (e.g. 1.4.0)'
        required: true
```

**Jobs (sequencial):**

1. **`validate-version`** (< 1min):
   - Extract tag → version. Validar `^v\d+\.\d+\.\d+$`.
   - Comparar com `version` em `pyproject.toml` + `__init__.py` + `installer/data_downloader.iss`. Falha se drift (defesa contra release tag sem version bump).
   - Verificar que `CHANGELOG.md` tem seção `## [v{version}]` ou `## v{version}` (matching regex de `scripts/github_release.py`).

2. **`full-test-suite`** (< 15min):
   - Re-roda `test.yml` jobs (lint-type + unit + integration-property + pre-commit). Defesa contra cenário em que tag foi criada de branch desatualizada.
   - Conditional skip se workflow_dispatch + input `skip_tests=true` (escape hatch para hotfixes; emite warning no summary).

3. **`build-windows`** (< 8min):
   - Setup Python 3.12 (guard de `sys.version_info` redundante mas reforça).
   - Install `pip install -e ".[build,test,dev]"`.
   - **Bootstrap DLLs:** problema. `scripts/bootstrap-dll.ps1` exige `C:\Profit\bin` (ProfitChart instalado). No runner não temos ProfitChart. **Decisão:** publicar `profitdll/DLLs/Win64/` num bucket privado (S3 ou similar) e baixar via `aws s3 cp` com creds em `secrets.PROFITDLL_S3_KEY`. **Alternativa rejeitada:** commitar DLLs no repo (viola ADR-008 — DLL é proprietária Nelogica).
   - **Fallback v1.4.0 (curto-prazo):** se segredos não estão configurados, build pula PyInstaller etapa e emite artefato `release-no-binary.json` apenas com a tag/changelog. Release humano completa o build localmente. Esse fallback deve emitir warning loud para forçar resolução em v1.4.1.
   - `python scripts/build_release.py --version $VERSION`.
   - Roda `python scripts/verify-dll-companions.py dist/data_downloader/` como pós-validation (corrige P0-R3 — bug atual é que script falha porque DLLs faltam; ao garantir bootstrap, passa OK).
   - Upload `dist/data-downloader-v{version}-win64.zip` + `dist/build-manifest-v{version}.json` como artifacts.

4. **`build-installer`** (< 3min, depende de build-windows):
   - Setup InnoSetup (`actions/setup-inno-setup` ou direct download).
   - `iscc installer/data_downloader.iss`.
   - Upload installer `.exe` como artifact.

5. **`auto-audit-and-release`** (< 2min, depende de build-windows + build-installer):
   - Download artifacts.
   - Computa SHA256 de cada artefato (já no manifest, mas re-valida).
   - Append entry em `docs/release/RELEASES.md` (auto-AUDIT — Frente 2 P0-R4):
     ```markdown
     ## v{version} — {date}
     - **Released:** {iso_timestamp_utc} via workflow run #{run_id}
     - **Tag:** v{version}
     - **Commit:** {git_sha}
     - **Artifacts:**
       - data-downloader-v{version}-win64.zip — `{sha256}` ({size_human})
       - data-downloader-v{version}-setup.exe — `{sha256}` ({size_human})
       - build-manifest-v{version}.json — `{sha256}` ({size_human})
     - **CHANGELOG:** [link to GH release]
     ```
   - Commit + push direto a `main` (push do bot via `secrets.GITHUB_TOKEN`). Use `actions/checkout@v5` com `token` configurado. **Mensagem:** `docs(release): auto-AUDIT v{version} [skip ci]` para não retriggerar.
   - Invoca `python scripts/github_release.py --version {version}` que cria o GitHub Release oficial com body do CHANGELOG section + assets anexados.

**Critical path:** `validate-version → full-test-suite → build-windows → (build-installer || auto-audit-and-release)`. Total estimado < 30min worst-case.

### 2.5 Secret management

| Secret | Uso | Storage |
|--------|-----|---------|
| `GITHUB_TOKEN` | Built-in. Auto-AUDIT commit + GH release creation. | GH Actions default |
| `PROFITDLL_S3_BUCKET` / `_KEY` / `_SECRET` (futuro) | Bootstrap DLLs no runner. | GitHub Secrets (repo-scope) |
| `CODE_SIGNING_CERT_PFX_BASE64` / `_PASSWORD` (futuro v1.5.0) | Assinar `.exe` (Bug 7 / SmartScreen — ADR-016 deferred). | GitHub Secrets (env-scope `production`) |

**Política:** **NÃO** usar Organization-level secrets — repo-scope only para manter blast radius pequeno. Documentar em `.github/SECRETS.md` (futuro, Story 4.25 AC) quais secrets exigem reconfiguração ao rodar fork.

### 2.6 Pinning & determinismo

- `actions/checkout@v5`, `actions/setup-python@v6`, `actions/upload-artifact@v5`, `actions/cache@v5` — versão major fixada. Bumps cobertos por dependabot (configuração em ADR futuro se justificar).
- Python: `python-version: '3.12'` (não `3.12.x`) — GH garante latest patch da minor. Combina com `requires-python>=3.12` sem dor de patch updates.
- Pip cache key: `${{ runner.os }}-pip-${{ hashFiles('pyproject.toml') }}`.

### 2.7 Branch protection (humano configura)

`.github/branch-protection.md` (NEW) documenta a configuração que humano deve aplicar via GH UI/API:

- `main` protected.
- Required status checks: `test.yml / lint-type`, `test.yml / unit-tests`, `test.yml / integration-property-tests`, `test.yml / pre-commit`. Strict mode (PR must be up-to-date com main).
- Require PR reviews: 1 approval (squad reviewer humano).
- Restrict push to `main`: apenas via PR ou via `release.yml` auto-AUDIT bot.

## 3. Cenários verificados

| Cenário | Comportamento esperado |
|---------|------------------------|
| PR aberta toca `src/` | `test.yml` dispara 4 jobs paralelos; merge bloqueado até PASS. |
| PR toca apenas `docs/` | `test.yml` ainda dispara (overhead aceitável < $0.10); evita drift em ADR/story formatting. |
| Push para main após merge | `test.yml` re-roda em main (sanity). |
| Tag `v1.4.0` pushed | `release.yml` dispara validate → test → build → audit → publish. |
| Tag `v1.4.0-rc1` pushed | `release.yml` dispara mas `gh release create --prerelease` (já suportado em `scripts/github_release.py:--prerelease`). |
| Tag pushed em branch != main | `release.yml` falha em validate (drift entre tag commit e main HEAD documentado como warning, não erro — para hotfixes). |
| Workflow rodando + segundo PR | GH Actions queues; runner concorre. Sem deadlock (jobs são stateless). |
| Secret `PROFITDLL_S3_KEY` ausente | `build-windows` job pula PyInstaller, emite `release-no-binary.json`, build manual posterior. |
| Suite test demora >15min | Timeout de job em 20min mata o job (defesa contra hang). |
| Pre-commit falha bandit | Job `pre-commit` falha → PR bloqueado. Fix exige commit subsequente. |
| Push direto a main (manual, sem PR) | Branch protection bloqueia. Exceção: workflow `release.yml` via `GITHUB_TOKEN` bypass (`bypass list` documentada). |

## 4. Consequências

### Positivas

- **R13 (gates pré-commit) mecanizado.** Suite full obrigatória em PR; humano não pode pular.
- **R14 (AUDIT por release) automatizado.** RELEASES.md atualizado pelo bot a cada tag. Backfill nunca mais.
- **R19 (Python pinning) defendido em runtime.** CI roda exclusivamente em 3.12; guard do AC8 (Story 4.31) torna-se redundância de cinto-e-suspensórios.
- **Reproducibilidade de build cross-machine.** SOURCE_DATE_EPOCH determinístico (já em build_release.py) + runner Windows estável + manifest com SHA256 = qualquer reviewer pode validar binário.
- **Onboarding de novos contributors.** PR check status visível, sem precisar instalar full toolchain local para validar.
- **Defense-in-depth security.** bandit + pip-audit + detect-secrets rodam em CI (não só pré-commit local, que pode ser pulado).

### Negativas / trade-offs

- **Custo financeiro.** `windows-latest` runner ~$0.08/min. Estimativa: ~30min/release × 1 release/semana × 4 = ~2h/mês = ~$10/mês. PRs adicionam ~15min cada (test.yml) — em ~20 PRs/mês = ~5h = ~$25/mês. **Total: ~$35/mês.** Aceitável para o escopo. Compara com horas humanas economizadas em re-trabalho de bugs slip-through.
- **Latência de feedback.** PRs hoje têm feedback em ~5min (humano roda suite). CI adiciona ~10min (queue + setup + execução). Trade aceitável dado mecanização.
- **DLL bootstrap em CI.** Sem solução end-to-end no v1.4.0 — fallback é build manual. Resolve em v1.4.1 (Story TBD: provisionar S3 bucket privado + creds via Pichau).
- **Code signing diferido.** SmartScreen warning continua. ADR-016 estabelece path; v1.5.0 endereça.
- **Lock-in GitHub Actions.** Migrar para self-hosted runner ou outro CI (CircleCI/GitLab) custaria reescrita. Aceito — GH é onde estamos.
- **Test surface adicional.** Cada workflow YAML é código que pode quebrar. Mitigado por `actionlint` em pre-commit (consideração para Story 4.25 AC; adicionar se trivial).

## 5. Alternativas consideradas

| Opção | Por que rejeitada |
|-------|-------------------|
| Self-hosted runner (Pichau laptop) | Disponibilidade ad-hoc, single point of failure, custo elétrico/cognitivo > $35/mês. |
| Matriz Python 3.12 + 3.13 + 3.14 | Tempo CI × 3, custo × 3, sem usuário 3.13/3.14 — viola minimal-decision principle. |
| `ubuntu-latest` runner (cross-platform tests sem DLL) | DLL é core do projeto; tests Linux passariam tudo, escondendo bugs Windows. False negative > zero confidence. |
| Cobrir TUDO em test.yml (smoke, build, signing) | Pipeline >40min, custo > $50/PR. Quebra fluxo dev. |
| Workflow único monolítico | Re-trigger seletivo difícil; falha em uma etapa exige re-run tudo. Modular é debug-friendly. |
| Não fazer CI (manter status quo) | R13/R14 perpetuamente violados; bug slip-through estatisticamente garantido em proporção a release rate. |
| Migrar para CircleCI/GitLab CI | Sem ganho funcional vs GH Actions; GH já é nosso host. Custo de aprendizado + migração desnecessário. |

## 6. Referências

- `pyproject.toml` (`requires-python>=3.12`, dev/test/build extras)
- `scripts/build_release.py` (pipeline existente — já tem hooks para CI consumir)
- `scripts/github_release.py` (criação de GH Release — usado por release.yml job 5)
- `scripts/verify-dll-companions.py` (pré-flight DLLs — usado por build job)
- `scripts/bootstrap-dll.ps1` (gap: exige ProfitChart local; CI precisa S3 alternative)
- `docs/release/RELEASES.md` (target de auto-AUDIT — backfilled em Story 4.31 AC5)
- ADR-008 (DLL distribution — DLLs não vão para repo; CI precisa source alternativa)
- ADR-009 §"Camada 5: CI controlled" (deferido até esta ADR)
- ADR-016 (code signing — deferido para v1.5.0)
- Story 4.31 AC8 (Python pinning guard runtime — complementar ao CI gate)
- Story 4.31 AC5 (RELEASES.md backfill — auto-AUDIT garante daqui pra frente)
- Story 4.31 AC6 (bandit/pip-audit em pre-commit — CI rodando reforça)
- `err1.log` (verify-dll-companions falhando durante build atual)
- Revisão consolidada 2026-05-16 (Frente 2: CI Pipeline)

— Aria 🏛️, mapeando o pipeline
