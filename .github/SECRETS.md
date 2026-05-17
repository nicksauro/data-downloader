# Repository Secrets — `data-downloader`

**Owner:** @devops (Gage) — squad data-downloader.
**Story:** 4.25 (CI Pipeline GitHub Actions) AC7.
**ADR:** ADR-027 §2.5.

Lista de **GitHub Actions secrets** consumidos pelos workflows do repo.
Política: **repo-scope only** (sem Organization secrets) — blast radius
mínimo. Forks NÃO recebem secrets automaticamente por design GH.

---

## 1. Secrets ativos (v1.4.0)

| Nome | Tipo | Escopo | Onde é usado | Quem provisiona | Rotação |
|------|------|--------|--------------|-----------------|---------|
| `GITHUB_TOKEN` | Built-in | repo | `release.yml` job `auto-audit-and-release` (commit + push auto-AUDIT, GH Release creation via `gh` CLI) | GitHub (automatico por workflow) | Auto-rotated por GH; expira no fim do workflow run |

---

## 2. Secrets futuros (v1.4.0 fim — DLL bootstrap em CI)

Para fechar P0-R3 (DLL bootstrap em runner — hoje `release.yml` emite
`release-no-binary.json` quando secrets ausentes):

| Nome | Tipo | Escopo | Onde será usado | Quem provisiona | Rotação |
|------|------|--------|-----------------|-----------------|---------|
| `PROFITDLL_S3_BUCKET` | String | repo | `release.yml` job `build-windows` (URI do bucket S3 privado com `profitdll/DLLs/Win64/`) | Pichau (provisiona bucket AWS + define nome) | N/A — re-provisiona apenas se bucket migrar |
| `PROFITDLL_S3_KEY` | String | repo | `release.yml` job `build-windows` (`AWS_ACCESS_KEY_ID` para `aws s3 cp`) | Pichau (gera IAM user read-only no bucket) | Trimestral (recomendado AWS) ou em incidente |
| `PROFITDLL_S3_SECRET` | String | repo | `release.yml` job `build-windows` (`AWS_SECRET_ACCESS_KEY` para `aws s3 cp`) | Pichau (gera IAM user read-only no bucket) | Trimestral (recomendado AWS) ou em incidente |

**Blast radius se vazar:** acesso read-only às DLLs Nelogica empacotadas
para CI. **NÃO** dá acesso ao runtime ProfitChart, NÃO dá creds Nelogica
do usuário. Mitigado por IAM role com:
- `s3:GetObject` apenas no prefix `profitdll/DLLs/Win64/*`
- `s3:ListBucket` apenas no bucket configurado
- Sem `s3:PutObject` (read-only)

---

## 3. Secrets futuros (v1.5.0 — code signing — ADR-016)

Para fechar SmartScreen warning (`docs/release/INSTALL.md` §"SmartScreen workaround"):

| Nome | Tipo | Escopo | Onde será usado | Quem provisiona | Rotação |
|------|------|--------|-----------------|-----------------|---------|
| `CODE_SIGNING_CERT_PFX_BASE64` | String (base64) | env `production` | `release.yml` job `build-installer` (futuro: `signtool sign /f cert.pfx`) | Pichau (compra cert EV/OV de CA) | Anual (validade típica do cert) |
| `CODE_SIGNING_PASSWORD` | String | env `production` | `release.yml` job `build-installer` (`signtool /p ${password}`) | Pichau (gera senha forte, armazena em 1Password) | Junto com renovação do cert |

**Escopo `environment: production`:** requer manual approval antes do job
rodar (mitigação contra cert leak por workflow comprometido). Configurar
em GH Settings → Environments → Add environment "production".

---

## 4. Como adicionar / rotacionar secrets

### Via GH UI
1. Settings → **Secrets and variables** → **Actions** → **New repository secret**.
2. Name: exato como na tabela acima (case-sensitive).
3. Secret: cole o valor (sem aspas, sem espaços, sem newlines).
4. **Add secret**.

### Via `gh` CLI
```bash
# Repo-scope (default):
gh secret set PROFITDLL_S3_KEY --body "AKIA..."
gh secret set PROFITDLL_S3_SECRET --body "wJalrXUt..."

# Environment-scope (production):
gh secret set CODE_SIGNING_PASSWORD --env production --body "..."
```

### Validar (sem expor valor)
```bash
gh secret list
# Output esperado: nome + last updated, SEM valor.
```

### Rotação
1. Gerar nova credencial (AWS IAM access key, signing cert renewal etc.).
2. `gh secret set NAME --body "NEW_VALUE"` (sobrescreve atomicamente).
3. Disparar workflow manual (`gh workflow run release.yml -f version=X.Y.Z`)
   para validar que novo secret funciona ANTES de revogar o anterior.
4. Após validar: revogar/deletar credencial antiga (na fonte — AWS IAM,
   CA portal, etc.).

---

## 5. Política de segurança

### Repo-scope only
Não usar **Organization secrets** mesmo que disponíveis. Justificativa:
- Org-scope espalha blast radius para repos não-relacionados.
- Auditoria de quem usa fica diluída.
- Forks de outros repos da org podem ser vetor.

### Sem secrets em forks
Por design do GH, **fork-based PRs não recebem secrets** (segurança contra
injection via PR malicioso). Consequência:

- `test.yml` em fork PR: **roda OK** (sem secrets necessários).
- `release.yml` em fork: **NÃO roda** (não tem como criar tag em fork sem
  permissão write no upstream). Workflow_dispatch via fork também bloqueado.

Se contributor externo precisa testar release pipeline, fluxo é:
1. Maintainer revisa o PR.
2. Maintainer merge no main.
3. Maintainer cria tag a partir do main para disparar `release.yml` em
   contexto autenticado.

### Detect-secrets pre-commit
`.pre-commit-config.yaml` já tem `detect-secrets` hook (Story 4.31 AC6) que
bloqueia commits contendo padrões de credenciais conhecidas. Defense-in-depth.

### Política de logging
Workflows **NUNCA** devem `echo $SECRET_VAR` ou logar valor de secrets.
GH Actions auto-mascara secrets em logs, mas defense-in-depth: scripts em
PowerShell usam `Write-Host` somente para nomes de secrets (ex.: "secrets
detectados") nunca os valores.

---

## 6. Histórico

| Data | Quem | Mudança |
|------|------|---------|
| 2026-05-17 | Sol (@data-engineer) | Documento inicial, Story 4.25 AC7. GITHUB_TOKEN + secrets PROFITDLL_S3_* (v1.4.0 fim) + CODE_SIGNING_* (v1.5.0). |
