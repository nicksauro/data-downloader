# BRANCH_MODEL — Squad data-downloader

**Owner:** Gage (devops) + Morgan (pm — escopo de features)
**Status:** spec — aprovação pendente Morgan
**Endereça:** finding H18 (PLAN_REVIEW_2026-05-03.md) — branch model não definido; Felix (Epic 3) e Dex (Epic 2) em paralelo sem isolamento.

---

## 1. Modelo: Trunk-based development

Squad data-downloader adota **trunk-based development com short-lived feature branches**.

| Princípio | Aplicação |
|-----------|-----------|
| `main` é sempre deployável | Cada merge passa Quinn `*qa-gate` PASS + CI verde |
| Branches feature são curtas | Vida útil < 3 dias; PR pequeno (< 500 LOC) sempre que possível |
| Sem long-lived branches | Não existe `develop`, `staging`, `release/*`. Apenas `main` + branches de trabalho |
| Releases são tags em `main` | `vX.Y.Z` (SemVer estrito) — não branches separadas |
| Hotfix idem | Branch curta `fix/...`, PR para `main`, tag `vX.Y.Z+1` |

---

## 2. Convenção de nomes

| Tipo de mudança | Padrão | Exemplo |
|-----------------|--------|---------|
| Feature de story | `feature/story-N.M-{slug}` | `feature/story-1.2-dll-init-wrapper` |
| Bugfix de story | `fix/story-N.M-{slug}` | `fix/story-1.4-fsync-parent-dir` |
| Chore/infra | `chore/{slug}` | `chore/pre-commit-autoupdate` |
| Refactor | `refactor/story-N.M-{slug}` | `refactor/story-1.5-catalog-api` |
| Hotfix release | `hotfix/v{X.Y.Z}-{slug}` | `hotfix/v0.1.1-dll-leak` |
| ADR doc | `docs/adr-{NNN}-{slug}` | `docs/adr-008-dll-distribution` |
| Spec/planejamento | `spec/{slug}` | `spec/epic-2-roadmap` |

### 2.1 Regras

- Slug: lowercase, kebab-case, max 40 char
- Não usar caracteres especiais (apenas `[a-z0-9-]`)
- Story-id obrigatório quando aplica (rastreabilidade R12)
- Sem branches pessoais (`gage/wip-stuff`) — squad é colaborativo

---

## 3. Fluxo de PR

### 3.1 Criação

```powershell
# Atualizar main local
git checkout main
git pull --ff-only

# Criar branch
git checkout -b feature/story-1.2-dll-init-wrapper

# Trabalhar (commits frequentes, mensagens conventional)
git add -p
git commit -m "feat(dll): scaffold DLLInitializeMarketLogin signature [Story 1.2]"

# Subir branch (Gage exclusivo)
# Outros agentes pedem: "Gage, push esta branch"
git push -u origin feature/story-1.2-dll-init-wrapper
```

### 3.2 PR

> Apenas Gage executa `gh pr create` (autoridade exclusiva).

```powershell
gh pr create `
  --title "feat(dll): DLLInitializeMarketLogin wrapper [Story 1.2]" `
  --body "$(Get-Content docs/release/PR_TEMPLATE.md)" `
  --base main `
  --label "story-1.2,epic-1,area-dll"
```

### 3.3 Pré-requisitos para merge

| # | Check | Quem aprova |
|---|-------|-------------|
| 1 | CI verde (lint, test, pre-commit) | GitHub Actions (futuro) |
| 2 | Branch atualizada com `main` (rebase ou merge) | Gage verifica antes de merge |
| 3 | Pelo menos 1 review **PASS** | Squad de agentes: Quinn `*qa-gate` PASS = review humano substituto |
| 4 | Especialista de área aprovou (se aplicável) | Nelo (DLL), Sol (storage), Aria (arch), Uma (ux), Felix (UI), Pyro (perf) |
| 5 | Conversation resolution: 0 comments abertos | GitHub branch protection |
| 6 | Linear history (rebase ou squash, NÃO merge commit) | Gage usa `--squash` |
| 7 | Morgan autorizou merge (escopo OK) | Mensagem explícita |

### 3.4 Merge mode: SQUASH

> **Decisão:** todos os PRs são merged via **squash**.

```powershell
gh pr merge {pr-number} --squash --delete-branch
```

Justificativa:
- `main` mantém 1 commit por story → história limpa
- Bisect futuro encontra problema na story certa imediatamente
- Branch deletada automaticamente após merge (housekeeping)
- WIP commits ("fix typo", "wip", "address review") somem da história

> Mensagem do squash commit: deve seguir **conventional commits** com subject = título do PR + `[Story N.M]`.

---

## 4. Tags & Releases

### 4.1 SemVer estrito

| Bump | Quando | Exemplo |
|------|--------|---------|
| MAJOR (`1.0.0 → 2.0.0`) | Breaking change em `public_api/` ou em schema Parquet | `v2.0.0` |
| MINOR (`1.0.0 → 1.1.0`) | Feature aditiva (campo Parquet novo nullable, nova função pública) | `v1.1.0` |
| PATCH (`1.0.0 → 1.0.1`) | Bugfix sem mudança de interface | `v1.0.1` |

> **v0.x.x:** foundation em construção; pode haver breaking sem MAJOR bump (documentado em CHANGELOG).

### 4.2 Criação de tag

> Apenas Gage. Apenas após Morgan `*release-readiness` GO + Quinn PASS no milestone.

```powershell
# Tag anotada (NÃO lightweight)
git tag -a v0.1.0 -m @'
v0.1.0 — First foundation release

Epic 1 fechado. Smoke MVP validado. ProfitDLL wrapper estavel.

Highlights:
- DLL init/finalize com 11 callback slots (Story 1.2)
- Storage Parquet+SQLite schema v1.0.0 (Story 1.4)
- CLI typer + smoke (Story 1.7b)

Detalhes: CHANGELOG.md
'@

# Push tag (Gage exclusivo)
git push origin v0.1.0
```

### 4.3 GitHub Release

```powershell
gh release create v0.1.0 `
  --title "v0.1.0 — Foundation" `
  --notes-file CHANGELOG-v0.1.0.md `
  dist/data_downloader-0.1.0.exe `
  dist/data_downloader-0.1.0.exe.sha256
```

Registrar em `docs/release/RELEASES.md` (entrada nova).

---

## 5. Política sobre `main`

| Regra | Valor |
|-------|-------|
| Push direto | **PROIBIDO** (branch protection bloqueia) |
| Force push | **PROIBIDO** sempre, mesmo Gage |
| Delete | **PROIBIDO** (branch protection bloqueia) |
| Required PR + reviews | YES (1) |
| Required status checks | `lint`, `test`, `pre-commit` (futuro: `bench`) |
| Linear history | YES (squash-only) |
| Conversation resolution | YES |
| Stale review dismissal | YES (novo push invalida reviews antigos) |

---

## 6. Casos especiais

### 6.1 Branches paralelas (Felix Epic 3 + Dex Epic 2 simultâneos)

> Cenário do finding H18.

**Política:**
1. Cada agente trabalha em branch própria (`feature/story-2.1-...`, `feature/story-3.1-...`).
2. Nenhuma branch faz merge entre si — sempre via `main`.
3. Se houver conflito potencial (ambos tocam mesmo módulo), Morgan sequencia: um termina, faz merge, outro rebase.
4. Aria adjudica conflito de design.

### 6.2 WIP que precisa rebase em `main`

```powershell
git checkout feature/story-1.2-dll-init-wrapper
git fetch origin
git rebase origin/main
# Resolver conflitos
git push --force-with-lease    # Permitido em branches feature, NUNCA em main
```

> `--force-with-lease` (não `--force`) — protege contra sobrescrever push de outro agente.

### 6.3 Branch ficou velha (> 7 dias sem commit)

- Morgan revisa: ainda relevante?
- Se SIM: rebase em `main`, retomar
- Se NÃO: Gage deleta com `git push origin --delete feature/...` (após Morgan autorizar)

### 6.4 Hotfix em produção

```powershell
# A partir da tag em produção
git checkout v0.1.0
git checkout -b hotfix/v0.1.1-dll-leak
# Fix
git commit -m "fix(dll): release callback handle on shutdown [hotfix v0.1.1]"
# PR para main
gh pr create --base main --title "hotfix(dll): release callback handle [v0.1.1]"
# Após merge:
git tag -a v0.1.1 -m "v0.1.1 hotfix DLL leak"
git push origin v0.1.1
```

---

## 7. O que NÃO existe neste modelo

- ❌ `develop` branch (não há)
- ❌ `release/*` long-lived branches
- ❌ `staging` / `qa` branches
- ❌ Personal branches (`gage/...`, `dex/...`)
- ❌ Merge commits (apenas squash)
- ❌ Force push em `main` (branch protection garante)

---

## 8. Resumo visual

```
main ─o──o──o──o──o──o──o──o──o─────o (v0.1.0)
       \         /\         /\      /
        feature 1   feature 2  fix 3
        (squashed)  (squashed) (squashed)
```

Cada `o` em `main` = 1 squash de 1 PR de 1 story. Releases são tags. Sem nada paralelo.

---

## 9. Pendências

- Morgan ratificar (especialmente §3.3 ponto 7 — política de "Morgan autoriza merge")
- Aria validar §6.1 (branches paralelas Epic 2 vs Epic 3)
- Quinn validar §3.3 ponto 3 (Quinn PASS = review humano substituto)

— Gage, publicando com cuidado ⚙️
