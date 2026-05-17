# CI Validation — rodar a suite local (espelha `test.yml`)

**Owner:** @devops (Gage) / @data-engineer (Sol).
**Story:** 4.25 (CI Pipeline GitHub Actions) AC10.
**ADR:** ADR-027.

Este documento descreve como rodar localmente os **mesmos comandos** que
`test.yml` roda em CI — para validar PR antes de abrir e evitar loops de
"push → CI fail → fix → push". Smoke check pre-merge obrigatório.

---

## 1. Pré-requisitos

| Tool | Versão mínima | Como verificar |
|------|---------------|----------------|
| Python | **3.12.x** (R19 pinning — ADR-027 §2.2) | `python --version` → `Python 3.12.x` |
| Git | qualquer recente | `git --version` |
| pip | recente | `python -m pip --version` |
| Virtual env | recomendado | `python -m venv .venv && .venv\Scripts\Activate.ps1` (PowerShell) ou `source .venv/Scripts/activate` (Git Bash) |

**Atenção: Python 3.14 NÃO é suportado.** `scripts/build_release.py` tem
guard runtime (Story 4.31 AC8) que bloqueia execução em ≠3.12; CI também roda
exclusivamente 3.12. Se você está em 3.13/3.14, instale 3.12 paralelo via
`pyenv-win` ou Microsoft Store.

### Instalar deps (1x por venv)

```powershell
pip install -e ".[test,dev,build,ui]"
```

Isso cobre todos os extras consumidos pelos 4 jobs de `test.yml`. Subset
mínimo por job:

| Job | Extras mínimos |
|-----|----------------|
| `lint-type` | `[dev]` |
| `unit-tests` | `[test,dev]` |
| `integration-property-tests` | `[test,dev]` |
| `pre-commit` | (apenas pre-commit) `pip install pre-commit` |

---

## 2. Comandos espelho — `test.yml`

Rodar nesta ordem antes de abrir PR:

### 2.1 lint-type job
```powershell
# Equivalente ao job "lint-type" em test.yml
ruff check src/ tests/
mypy --strict src/data_downloader/
```

Esperado: ambos exit 0, sem warnings.

### 2.2 unit-tests job
```powershell
pytest tests/unit -v --maxfail=5 --timeout=60
```

Esperado: **1222 passed, 0 failed** (baseline v1.3.0). Tempo: ~90s.

### 2.3 integration-property-tests job
```powershell
pytest tests/integration tests/property -v --maxfail=3 --timeout=180 -m "not smoke"
```

Esperado: **494 integration + 65 property passed**. Tempo: ~3-5min.

**Por que `-m "not smoke"`:** smoke tests exigem `ProfitChart` instalado +
`PROFITDLL_KEY` env var + credenciais Nelogica reais. Não rodam em CI nem
no laptop sem setup. Para rodar smoke local: ver
`docs/release/SMOKE_PROTOCOL.md`.

### 2.4 pre-commit job
```powershell
pre-commit run --all-files --show-diff-on-failure
```

Esperado: todos os hooks PASS (bandit, pip-audit, detect-secrets, ruff,
ruff-format, mypy, actionlint, dll-story-discipline, no-print-in-src,
no-dotenv, conventional-commits).

**Primeira execução demora** (5-15min): instala envs Python+Go+Node de cada
hook. Cache em `~/.cache/pre-commit/` reutiliza nas execuções seguintes
(< 30s típico).

---

## 3. Suite full em um único comando (recomendado pre-PR)

```powershell
# All-in-one — exit não-zero se qualquer etapa falhar.
ruff check src/ tests/ ; if ($LASTEXITCODE -ne 0) { exit 1 } ;
mypy --strict src/data_downloader/ ; if ($LASTEXITCODE -ne 0) { exit 1 } ;
pytest tests/unit -v --maxfail=5 --timeout=60 ; if ($LASTEXITCODE -ne 0) { exit 1 } ;
pytest tests/integration tests/property -v --maxfail=3 --timeout=180 -m "not smoke" ; if ($LASTEXITCODE -ne 0) { exit 1 } ;
pre-commit run --all-files --show-diff-on-failure
```

Tempo total esperado: ~5-8min em laptop típico (Pichau benchmark v1.3.0).

---

## 4. Validação de workflows YAML (AC9)

Se você está alterando arquivos em `.github/workflows/`:

```powershell
# actionlint hook valida sintaxe (rodando isolado é mais rápido)
pre-commit run actionlint --files .github/workflows/test.yml .github/workflows/release.yml
```

Esperado: `Lint GitHub Actions workflow files....Passed`.

**Comum:**
- Indentação errada de `steps:` (4 espaços vs 2)
- Falta de `shell: pwsh` em runners Windows (default é `bash`, mas
  `bash.exe` no `windows-latest` é Git Bash com quirks)
- `${{ ... }}` interpolation dentro de `run: |` blocks (escape se for
  literal — raro)

---

## 5. Troubleshooting

### 5.1 `pytest-qt + display em Windows headless`
- **Sintoma:** `pytest tests/integration` falha com `xcb` ou `cannot connect to display`.
- **Causa:** ambiente sem display (CI headless, RDP sem GPU).
- **Fix:** instalar `pytest-qt` + setar `QT_QPA_PLATFORM=offscreen`:
  ```powershell
  $env:QT_QPA_PLATFORM = 'offscreen'
  pytest tests/integration -v
  ```
- **CI:** `windows-latest` runner tem display headless; workflows já setam
  isso quando necessário (via `pytest.ini` markers ou step env:).

### 5.2 `ruff` divergence local vs CI
- **Sintoma:** local PASS, CI FAIL (ou vice-versa).
- **Causa:** versão diferente de `ruff`. Local: pip installed (mais novo).
  CI: lock via `[dev]` extra em `pyproject.toml`.
- **Fix:** alinhar via `pip install -e ".[dev]" --upgrade` local; ou no CI,
  `pip freeze | grep ruff` no job pra ver versão exata.

### 5.3 `mypy --strict` muito lento (> 60s)
- **Sintoma:** mypy demora 2-5min no primeiro run; rápido depois (<10s).
- **Causa:** mypy cache (`.mypy_cache/`) vazio.
- **Fix:** primeiro run é normal; runs subsequentes usam cache. Em CI,
  `actions/setup-python@v6` com `cache: 'pip'` invalida quando
  `pyproject.toml` muda — mypy cache regenera de tempos em tempos
  (não cached entre CI runs por design).

### 5.4 `pre-commit` quebra em `actionlint` (Go install)
- **Sintoma:** `pre-commit run actionlint` falha com `go: command not found` ou similar.
- **Causa:** primeiro run baixa Go toolchain (~100MB).
- **Fix:** aguardar download; se tiver Go já instalado, pre-commit detecta
  via `language: golang` no hook config.

### 5.5 `pip install -e ".[build]"` falha (PyInstaller)
- **Sintoma:** `ERROR: Could not find a version that satisfies pyinstaller>=6.4` em Python 3.14.
- **Causa:** PyInstaller 6.x não suporta Python 3.14 (ainda).
- **Fix:** **mudar para Python 3.12** (regra R19; ADR-027 §2.2). Nesse caso
  você não conseguiria nem `build_release.py` rodar.

### 5.6 Pre-commit "trailing-whitespace" / "end-of-file-fixer" surpresa
- **Sintoma:** commit bloqueado, hook auto-fixou os arquivos, mas precisa
  re-stage.
- **Fix:** `git add <arquivo>` e re-commit. Pre-commit hooks com auto-fix
  precisam ciclo de 2 commits (1: hook fixa; 2: aceita o fix).

### 5.7 Tests timing-sensitive falham local (não em CI)
- **Sintoma:** `tests/unit/test_dll_wrapper.py::test_wait_market_connected*` timeout em laptop carregado.
- **Causa:** `time.sleep(retry_cooldown)` em `wait_market_connected` é sensível
  a load do host (laptop com Chrome+IDE+Docker abertos).
- **Fix:** fechar apps pesados ou rerun. Não é flakiness no código —
  CI runner dedicado não vê isso.

---

## 6. Comparação local vs CI (resumo)

| Comando | Local | CI (`test.yml`) | Tempo CI |
|---------|-------|-----------------|----------|
| `ruff check` | sim | job `lint-type` | ~10s |
| `mypy --strict` | sim | job `lint-type` | ~30s |
| `pytest tests/unit` | sim | job `unit-tests` | ~2min |
| `pytest tests/integration tests/property` | sim | job `integration-property-tests` | ~5min |
| `pre-commit run --all-files` | sim | job `pre-commit` | ~2min |
| **Total wall-clock** | ~5-8min | ~5-7min (paralelo) | — |

CI roda paralelo (4 jobs), local roda sequencial — mas tempo similar pois
local não tem overhead de spin-up de runner.

---

## 7. Histórico

| Data | Quem | Mudança |
|------|------|---------|
| 2026-05-17 | Sol (@data-engineer) | Documento inicial, Story 4.25 AC10. Pré-req + 4 jobs espelho + troubleshooting. |
