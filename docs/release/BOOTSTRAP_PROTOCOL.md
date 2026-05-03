# BOOTSTRAP_PROTOCOL — Story 0.1 Environment Bootstrap

**Owner:** Gage (devops)
**Status:** spec — aprovação pendente Morgan + Aria (ADR-008)
**Story:** 0.1 — Environment Bootstrap
**Bloqueia:** Story 1.1 (R12 inoperante até `git init` + branch protection)
**Coordena com:** ADR-008 (DLL Distribution Strategy), Story 0.2 (pre-commit), Story 0.4 (CodeRabbit)

---

## 1. Objetivo

Levar o repositório `data-downloader` de **diretório solto** → **repo git rastreado, com branch protection, pre-commit gates, política de DLL definida e remote GitHub configurado** — em ordem determinística e reversível.

Findings endereçados:
- **C1** Repo não é git → `git init`
- **C2** DLL no repo sem decisão → coordenado com ADR-008 (gitignore + bootstrap script)
- **H17** Pre-push hook não versionado → `.pre-commit-config.yaml` + `pre-push` stage (Story 0.2)
- **H18** Branch model não definido → `BRANCH_MODEL.md` (paralelo)

---

## 2. Pré-condições

| # | Condição | Como verificar |
|---|----------|----------------|
| P1 | Working tree limpo (sem `.git/` existente) | `Test-Path .git` retorna `False` |
| P2 | `.gitignore` definitivo presente (criado por Gage) | `Test-Path .gitignore` retorna `True` |
| P3 | `.env.example` presente | `Test-Path .env.example` retorna `True` |
| P4 | `.pre-commit-config.yaml` presente | `Test-Path .pre-commit-config.yaml` retorna `True` |
| P5 | `scripts/bootstrap-dll.ps1` presente | `Test-Path scripts/bootstrap-dll.ps1` retorna `True` |
| P6 | `scripts/verify-dll-companions.py` presente | exit code 0 ou 1 (ambos válidos para esta verificação) |
| P7 | ADR-008 (Aria) **aprovado** | `docs/adr/008-*.md` status = accepted |
| P8 | Morgan autorizou bootstrap (não aguardar Story 1.1) | Mensagem explícita registrada em AUDIT.md |

**ABORTAR** se qualquer pré-condição falhar.

---

## 3. Sequência de comandos — `git init`

> Executar do diretório raiz `C:\Users\Pichau\Desktop\data-downloader\`.
> Todos os comandos abaixo são idempotentes ou abortam claramente se inválidos.

### 3.1 Inicializar repo com branch `main` (NÃO `master`)

```powershell
# Garantir branch padrão = main globalmente (idempotente)
git config --global init.defaultBranch main

# Inicializar
git init

# Verificar — deve imprimir "main"
git branch --show-current
```

### 3.2 Configurar identidade do squad (apenas para este repo)

> **DECISÃO:** Cada agente commita com nome próprio + email do usuário.
> Author de commits gerados automaticamente é registrado via `Co-Authored-By` no rodapé.

```powershell
# Identidade humana (do usuário)
git config user.name  "Nicolas Carasai Baptista"
git config user.email "nicolascarasaibaptista@gmail.com"
```

### 3.3 Primeiro commit (vazio, sem arquivos)

> **POR QUÊ vazio?** Estabelece SHA inicial estável antes de qualquer arquivo entrar.
> Permite rebase/cherry-pick limpos no futuro. Padrão de repos disciplinados.

```powershell
git commit --allow-empty -m @'
chore: initial commit (squad data-downloader)

Repositorio inicializado pelo squad data-downloader.
Branch padrao: main (trunk-based, ver docs/release/BRANCH_MODEL.md).

Owner do bootstrap: Gage (devops).
Aprovado por: Morgan (PM).

Co-Authored-By: Gage <gage@data-downloader.local>
Co-Authored-By: Morgan <morgan@data-downloader.local>
'@
```

### 3.4 Adicionar arquivos de bootstrap em commit dedicado

> Mantém SHA inicial reservado. Bootstrap em commit separado para auditoria clara.

```powershell
# Stage seletivo — NUNCA git add -A no bootstrap
git add .gitignore
git add .env.example
git add .pre-commit-config.yaml
git add docs/release/BOOTSTRAP_PROTOCOL.md
git add docs/release/BRANCH_MODEL.md
git add docs/release/CODERABBIT_DECISION.md
git add docs/release/AUDIT.md
git add docs/release/RELEASES.md
git add scripts/bootstrap-dll.ps1
git add scripts/verify-dll-companions.py

# Verificar staged
git status
git diff --cached --stat

git commit -m @'
chore(bootstrap): add gitignore, pre-commit, env template, DLL scripts [Story 0.1]

Adiciona infra base do squad data-downloader:
- .gitignore com politica DLL (ADR-008): companions gitignored, bootstrap via script
- .env.example com vars Nelogica e tuning queues
- .pre-commit-config.yaml (Story 0.2 — finding H17)
- scripts/bootstrap-dll.ps1 + verify-dll-companions.py
- docs/release/* (BOOTSTRAP_PROTOCOL, BRANCH_MODEL, CODERABBIT_DECISION, AUDIT, RELEASES)

Refs: PLAN_REVIEW_2026-05-03.md (findings C1, C2, H17, H18, M3)

Co-Authored-By: Gage <gage@data-downloader.local>
'@
```

### 3.5 Instalar pre-commit hooks

```powershell
# Pre-requisito
pip install pre-commit

# Instalar hooks no .git/hooks/
pre-commit install
pre-commit install --hook-type commit-msg
pre-commit install --hook-type pre-push

# Validar — deve passar (ou apenas reformatar arquivos ainda não commitados)
pre-commit run --all-files
```

### 3.6 Inicializar baseline de detect-secrets

```powershell
# Cria .secrets.baseline para hook detect-secrets
detect-secrets scan --baseline .secrets.baseline

git add .secrets.baseline
git commit -m "chore(secrets): initialize detect-secrets baseline [Story 0.1]"
```

---

## 4. `.gitignore` — Decisão definitiva (cobrindo Story 1.1 antecipadamente)

> Spec já materializada em `/.gitignore` na raiz. Conteúdo resumido aqui para auditoria:

| Categoria | Padrão | Justificativa |
|-----------|--------|---------------|
| Python caches | `__pycache__/`, `*.pyc`, `.mypy_cache/`, `.ruff_cache/` | Lixo de runtime |
| Test caches | `.pytest_cache/`, `.coverage`, `htmlcov/` | Não rastreado |
| Build artifacts | `build/`, `dist/` | PyInstaller output |
| Virtual envs | `.venv/`, `venv/` | Local-only |
| **Secrets** | `.env`, `.env.*` (mas `!.env.example` allowlist) | R1 — zero secret |
| **Datasets** | `data/`, `*.parquet`, `*.duckdb*`, `*.sqlite` | Volume + privacidade |
| **DLL companions** (ADR-008) | `profitdll/DLLs/Win64/ProfitDLL.dll` + libssl/libcrypto/libeay/ssleay + `*.dat` + `Logs/` + `MarketHours2/` + `database/` + `strategy/` + `PopupManagerV2/` + `Erro.log` | Distribuição via `bootstrap-dll.ps1` |
| **Mantém no repo** | `profitdll/Manual/`, `profitdll/Exemplo Python/`, `profitdll/__init__.py` | Documentação + binding source |
| Logs runtime | `**/Logs/`, `*.log`, `logs/` | DLL grava `Logs/` em qualquer cwd |
| Local dev placeholder | `/dll/` | Convenção `bootstrap-dll.ps1 -DestinationPath ./dll` |

---

## 5. Decisão sobre ProfitDLL.dll (finding C2 — alinhamento ADR-008)

### 5.1 Contexto

ProfitDLL.dll + companions são propriedade da Nelogica, distribuídos com ProfitChart. Há 3 opções:

| Opção | Descrição | Contras |
|-------|-----------|---------|
| (a) Commitar no repo | Push direto para git | EULA Nelogica? Repo público? Atualização sem release? |
| (b) Git LFS | Tracked mas pesado, exige LFS server | Complexidade, custo storage, ainda problema EULA |
| **(c) Gitignore + bootstrap script** | DLL fica fora do repo, usuário roda script para popular | Onboarding tem 1 passo extra |

### 5.2 Recomendação Gage → ADR-008

**Adotar (c).** Justificativa:
1. **EULA-safe:** Não redistribuímos binário Nelogica.
2. **Atualização independente:** Nelogica atualiza ProfitChart → usuário roda `bootstrap-dll.ps1` novamente, sem PR no nosso repo.
3. **Repo leve:** ~50MB de DLL não inflam git history.
4. **Determinístico:** `verify-dll-companions.py` valida hash/presença antes de DLLInitialize.

### 5.3 O que **fica** no repo

```
profitdll/
├── __init__.py              # binding Python (Nelo é owner)
├── Manual/                  # PDFs documentação Nelogica (~uns MB, OK commitar)
└── Exemplo Python/          # exemplos oficiais Nelogica (referência)
```

### 5.4 O que **NÃO fica** no repo (gitignored)

```
profitdll/DLLs/Win64/
├── ProfitDLL.dll              # binário proprietário
├── libssl-1_1-x64.dll         # OpenSSL companion
├── libcrypto-1_1-x64.dll      # OpenSSL companion
├── libeay32.dll               # OpenSSL legado
├── ssleay32.dll               # OpenSSL legado
├── *.dat                      # config binária (timezone, holidays, etc.)
├── MarketHours2/              # diretório runtime
├── database/                  # diretório runtime
├── PopupManagerV2/            # opcional
├── strategy/                  # opcional
├── Logs/                      # logs DLL (runtime)
└── Erro.log                   # log erros DLL (runtime)
```

### 5.5 Fluxo do desenvolvedor

```powershell
git clone <repo>
cd data-downloader
.\scripts\bootstrap-dll.ps1                           # popula DLLs/Win64/
python scripts\verify-dll-companions.py               # valida (exit 0)
cp .env.example .env                                  # editar com credenciais
pip install -r requirements.txt
pre-commit install
```

> **Aria:** confirmar este fluxo na ADR-008. Se houver objeção legal (EULA exige distribuição com produto), reabrir decisão.

---

## 6. GitHub Remote Setup

> Executar APÓS Morgan autorizar tornar repo público (ou definitivamente private).

### 6.1 Criar repo no GitHub

```powershell
# Pre-req: gh auth status — deve estar autenticado
gh auth status

# Criar repo PRIVATE (default — re-avaliar antes de tornar público)
gh repo create <usuario>/data-downloader --private --source=. --remote=origin --push=false

# Verificar remote
git remote -v
```

> **PLACEHOLDER:** `<usuario>` será preenchido quando Morgan confirmar o owner do repo (usuário pessoal vs organização).

### 6.2 Push inicial (autoridade exclusiva Gage)

```powershell
# Após Quinn PASS em Story 0.1 + Morgan autorização
git push -u origin main

# Registrar em AUDIT.md
# (template: Gage executa via *push command)
```

---

## 7. Branch Protection Rules em `main`

> Aplicar via `gh api` IMEDIATAMENTE após primeiro push. Sem isso `main` está aberto.

```powershell
gh api -X PUT "repos/<usuario>/data-downloader/branches/main/protection" `
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "test", "pre-commit"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON
```

### 7.1 Resumo das regras aplicadas

| Regra | Valor | Justificativa |
|-------|-------|---------------|
| Require PR | YES | Nenhum commit direto em `main` |
| Required reviews | 1 | Squad agentes: 1 = Quinn PASS substituto |
| Dismiss stale reviews | YES | Re-revisar após novo push |
| Strict status checks | YES | Branch atualizada com `main` antes de merge |
| Required checks | `lint`, `test`, `pre-commit` | Mínimo Epic 1; bench virá no Epic 2 |
| Linear history | YES | Squash-merge obrigatório (BRANCH_MODEL.md) |
| Force pushes | NO | Auditabilidade |
| Deletions | NO | `main` é imortal |
| Conversation resolution | YES | Sem comentários abertos no merge |

### 7.2 Verificar

```powershell
gh api "repos/<usuario>/data-downloader/branches/main/protection" | ConvertFrom-Json
```

---

## 8. Conventional Commits Enforcement

### 8.1 Onde acontece

1. **Local:** hook `commit-msg` em `.pre-commit-config.yaml` → `scripts/hooks/check_conventional_commit.py`
2. **PR:** GitHub Action (futura) `commitlint` valida todos os commits da PR
3. **Manual:** Gage roda `git log --format=%s` antes de release

### 8.2 Formato obrigatório

```
<type>(<scope>)?: <subject> [Story N.M]

<body opcional>

Co-Authored-By: <Agent> <email>
```

| Campo | Valores |
|-------|---------|
| `<type>` | `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`, `build`, `ci`, `style`, `revert` |
| `<scope>` (opcional) | área: `dll`, `storage`, `cli`, `ui`, `bootstrap`, `release`, etc. |
| `<subject>` | imperativo, lowercase, sem ponto final, max 72 char |
| `[Story N.M]` | obrigatório quando commit toca código de feature; opcional para `chore:` puro de infra |

### 8.3 Exemplos

```
feat(dll): implement DLLInitializeMarketLogin wrapper [Story 1.2]
fix(storage): handle SQLITE_BUSY on multi-symbol writer [Story 1.5b]
chore(bootstrap): add pre-commit framework [Story 0.2]
docs(adr): accept ADR-008 DLL Distribution Strategy
revert: "feat(cli): add export command [Story 1.7b]"
```

### 8.4 Bloqueios automáticos

- Commit sem `<type>:` → BLOCK
- Commit em `src/data_downloader/dll/` sem `[Story N.M]` → BLOCK (R12 disciplinada)
- Subject > 72 char → BLOCK
- Type inválido → BLOCK

---

## 9. Pós-bootstrap — handoff

Após este protocolo executado:

| Próximo agente | Ação |
|----------------|------|
| Quinn | `*qa-gate` em Story 0.1 (validar este protocolo executado, branch protection ativa) |
| Morgan | `*release-readiness` para autorizar push inicial |
| Gage | `*push` (após Quinn PASS + Morgan auth) → registra em AUDIT.md |
| Sm/Po | Criar Story 1.1 com pré-requisito `Story 0.1: GO` |

---

## 10. Plano de rollback

Caso bootstrap falhe a meio caminho:

```powershell
# Rollback total (mantém arquivos no working tree, descarta git)
Remove-Item -Recurse -Force .git
Remove-Item -Recurse -Force .pre-commit-config.yaml.bak  # se existir

# Re-executar do passo 3.1
```

> **NUNCA** rodar `git push --force` em `main`. Branch é imortal pós-criação.

---

## 11. Auditoria

Cada execução deste protocolo gera entrada em `docs/release/AUDIT.md`:

```
| 2026-05-03T18:00:00Z | bootstrap | Gage | (sha) | Story 0.1 conforme protocolo | 0.1 |
```

— Gage, publicando com cuidado ⚙️
