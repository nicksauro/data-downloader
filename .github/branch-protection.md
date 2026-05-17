# Branch Protection — `main`

**Owner:** @devops (Gage) — squad data-downloader.
**Story:** 4.25 (CI Pipeline GitHub Actions) AC5.
**ADR:** ADR-027 §2.7.

Esta configuração **não é automatizada** — GH Actions não tem API para
auto-configurar branch protection. Humano deve aplicar via UI (Settings →
Branches → Add rule) ou via `gh api` (script ao fim deste doc).

---

## 1. Rule: `main` protected

Settings → **Branches** → **Add branch protection rule** → Branch name pattern: `main`.

### 1.1 Restrict deletions
- [x] Lock branch (apenas auto-AUDIT bot pode push direto via `release.yml`).
- [x] Restrict deletions.

### 1.2 Require linear history
- [x] Require linear history (sem merge commits — squash ou rebase).

### 1.3 Require pull request reviews
- [x] Require a pull request before merging.
- [x] Require approvals: **1**.
- [x] Dismiss stale pull request approvals when new commits are pushed.
- [ ] Require review from Code Owners (opcional — sem CODEOWNERS hoje).

### 1.4 Required status checks (strict mode)

- [x] Require status checks to pass before merging.
- [x] Require branches to be up to date before merging (**strict mode**).
- **Status checks (4, todos do `test.yml`):**
  - `lint-type` (ruff + mypy --strict)
  - `unit-tests` (pytest tests/unit)
  - `integration-property-tests` (pytest tests/integration + tests/property)
  - `pre-commit` (bandit + pip-audit + detect-secrets + ruff format)

### 1.5 Conversation resolution
- [x] Require conversation resolution before merging.

### 1.6 Restrict who can push to matching branches
- [x] Restrict pushes to matching branches.
- **Allow list:**
  - PR-only para humanos.
  - `github-actions[bot]` (auto-AUDIT bot via `release.yml` → `auto-audit-and-release` job, autenticado com `GITHUB_TOKEN`). Mensagem do commit inclui `[skip ci]` para não retriggerar `test.yml`.

### 1.7 Outras opções
- [ ] Require signed commits (deferred v1.5.0 — exige GPG/SSH key onboarding squad).
- [ ] Allow force pushes: **NÃO** (sem exceções).
- [x] Include administrators (regras valem para Pichau também).

---

## 2. Aplicação via `gh api` (alternativa ao UI)

Substitua `{owner}/{repo}` (ex.: `nicksauro/data-downloader`):

```bash
# Pré-req: gh auth login com admin scope no repo.
gh api -X PUT "/repos/{owner}/{repo}/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "lint-type",
      "unit-tests",
      "integration-property-tests",
      "pre-commit"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
JSON
```

Validação:

```bash
gh api "/repos/{owner}/{repo}/branches/main/protection" | jq '.required_status_checks.contexts'
# Output esperado: ["lint-type","unit-tests","integration-property-tests","pre-commit"]
```

---

## 3. Bypass list (auto-AUDIT bot)

O job `auto-audit-and-release` em `release.yml` precisa push direto a `main`
para atualizar `docs/release/RELEASES.md`. Mecanismo:

1. Authenticação via `${{ secrets.GITHUB_TOKEN }}` (built-in).
2. Commit message inclui `[skip ci]` → `test.yml` NÃO dispara (evita loop infinito).
3. Bypass list opcional: adicionar `github-actions[bot]` em "People, teams, or apps that can bypass these restrictions" — **só necessário se restrict pushes estiver com lock_branch=true**.

Hoje (Story 4.25 v1.4.0), `restrict pushes` não bloqueia bots autenticados via
`GITHUB_TOKEN` com `contents:write` permission (configurado no workflow). Se
no futuro endurecermos (lock_branch=true), adicionar `github-actions` ao
bypass.

---

## 4. Troubleshooting

| Sintoma | Causa provável | Fix |
|---------|----------------|-----|
| PR mostra "Branch is not up to date with base" | `strict: true` em status checks; alguém fez merge depois | Rebase PR sobre main (`git fetch origin && git rebase origin/main`) e force-push para o branch do PR |
| Status check "lint-type" não aparece | Workflow ainda não rodou (primeiro commit do PR) | Aguardar primeira execução do `test.yml`; depois aparece |
| auto-AUDIT bot push rejected | `GITHUB_TOKEN` permission `contents:write` não setado | Verificar `permissions: contents: write` no job `auto-audit-and-release` (release.yml) |
| Force push em main precisa ser feito (rollback) | Política bloqueia (allow_force_pushes=false) | Temporariamente desabilitar a rule (UI), force push, reabilitar. **Coordenar com Pichau.** |

---

## 5. Histórico

| Data | Quem | Mudança |
|------|------|---------|
| 2026-05-17 | Sol (@data-engineer) | Documento inicial, Story 4.25 AC5. Status checks alinhados com `test.yml` jobs. |
