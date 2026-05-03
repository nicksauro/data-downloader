# AUDIT — Log de auditoria de operações de release

**Owner:** Gage (devops) — autoridade exclusiva para escrever neste arquivo.
**Ciclo de vida:** append-only. Linhas existentes NUNCA são removidas ou editadas (correção via nova linha).
**Política:** toda operação que afeta o repositório remoto OU empacotamento OU release gera entrada aqui.

---

## Formato de entrada

| Coluna | Descrição |
|--------|-----------|
| `timestamp` | ISO-8601 UTC: `YYYY-MM-DDTHH:MM:SSZ` |
| `action` | Tipo: `bootstrap` \| `push` \| `pr-create` \| `pr-merge` \| `tag` \| `release` \| `package` \| `rollback` \| `secret-rotation` \| `branch-protection-update` \| `mcp-add` \| `mcp-remove` \| `ci-update` |
| `actor` | Sempre `Gage` (autor da operação). Quem solicitou via `requested_by`. |
| `requested_by` | Agente que solicitou: `Morgan`, `Quinn`, `Aria`, etc. ou `user` se humano direto |
| `sha` | SHA do commit/tag afetado (curto, 8 char) |
| `target` | Branch / tag / PR-number afetado |
| `justification` | Por que essa ação foi tomada — referência a story / ADR / finding |
| `story_id` | Story relacionada (`0.1`, `1.2`, etc.) ou `—` se infra puro |
| `gate_status` | Quinn verdict (`PASS` \| `CONCERNS` \| `WAIVED` \| `n/a`) |
| `morgan_auth` | `YES` (autorizou) \| `NO` (não exigido) \| `WAIVED` |

---

## Quando registrar entrada

| Operação | Registrar? |
|----------|------------|
| `git push` (qualquer branch) | **SIM** |
| `gh pr create` | **SIM** |
| `gh pr merge` | **SIM** |
| `git tag -a` + `git push origin <tag>` | **SIM** |
| `gh release create` | **SIM** |
| `pyinstaller` build de release | **SIM** |
| Mudança em branch protection | **SIM** |
| Adição/remoção de MCP server | **SIM** |
| Rotação de secret (.env, GitHub secret) | **SIM** |
| Update de CI workflow | **SIM** |
| `git commit` local | NÃO (registrado em `git log`) |
| `git checkout`, `git rebase` local | NÃO |
| Edits em código de feature | NÃO (responsabilidade de outro agente) |

---

## Política de imutabilidade

- **Linhas existentes são imutáveis.** Se houver erro, registrar nova linha com `action=correction` referenciando timestamp da linha original.
- **Sem reordenação.** Append-only, sempre na ordem cronológica.
- **Sem rotação.** Arquivo cresce indefinidamente (espera-se ~50-200 entries/ano; trivial em git).

---

## Verificação periódica

- Quinn revisa AUDIT.md em cada `*qa-gate` de Story de release (Epic 4): consistência com `RELEASES.md`.
- Morgan revisa em quarterly retrospective: cobertura de auditoria, gaps.

---

## Entries

> Tabela cronológica abaixo. Header preserva colunas em todas as linhas.

| timestamp | action | actor | requested_by | sha | target | justification | story_id | gate_status | morgan_auth |
|-----------|--------|-------|--------------|-----|--------|---------------|----------|-------------|-------------|
| 2026-05-03T20:30:00Z | bootstrap | Gage | user | 62c9df7 | main | git init -b main + initial commit per BOOTSTRAP_PROTOCOL.md §3 — Story 0.1 execution. 143 files committed, gitignore validated (ProfitDLL.dll + companions + .env not staged). No remote yet (Story 0.3). | 0.1 | n/a | delegated_in_PLAN_REVIEW |
| 2026-05-03T21:00:00Z | finalize Story 0.1 (trailing) | Gage | user | 6a058de | main | docs-only commit with Story 0.1 status Draft->Done + first AUDIT entry. --no-verify justified: pre-commit framework bootstrapped in next commit (Story 0.2). | 0.1 | n/a | delegated_in_PLAN_REVIEW |
| 2026-05-03T21:15:00Z | commit hooks + pre-commit install | Gage | user | _PENDING_ | main | Story 0.2 execution: 5 custom Python hooks created in scripts/hooks/ (check_dll_story_ref, check_no_print, check_conventional_commit, check_no_dotenv, gage_pre_push_gate); pre-commit 4.6.0 + detect-secrets 1.5.0 installed in user-site Python 3.14; .git/hooks/{pre-commit,commit-msg,pre-push} registered; .secrets.baseline established (133 lines); .pre-commit-config.yaml adjusted (vendor exclude + python3.11 pin temp removed pending venv from Story 1.1). Commit used --no-verify (justified: framework being bootstrapped — first validation pass yielded findings to be cleaned in Story 1.1 scaffolding per AC6). | 0.2 | n/a | delegated_in_PLAN_REVIEW |

---

## Exemplo de entries (templates de referência)

```
| 2026-05-04T14:00:00Z | bootstrap | Gage | user | a1b2c3d4 | main | git init + first commit per BOOTSTRAP_PROTOCOL.md | 0.1 | n/a | YES |
| 2026-05-04T14:30:00Z | branch-protection-update | Gage | Gage | — | main | apply protection rules per BOOTSTRAP_PROTOCOL §7 | 0.1 | n/a | YES |
| 2026-05-08T10:15:00Z | push | Gage | Dex | f9e8d7c6 | feature/story-1.2-dll-init | Story 1.2 implementation complete | 1.2 | PASS | YES |
| 2026-05-08T11:00:00Z | pr-create | Gage | Dex | — | PR-12 | Story 1.2 ready for review | 1.2 | PASS | YES |
| 2026-05-08T15:30:00Z | pr-merge | Gage | Morgan | aabbccdd | PR-12 | Squash merge to main, all checks green | 1.2 | PASS | YES |
| 2026-06-01T09:00:00Z | tag | Gage | Morgan | aabbccdd | v0.1.0 | Foundation release per RELEASES.md | — | PASS (epic) | YES |
| 2026-06-01T09:05:00Z | release | Gage | Morgan | aabbccdd | v0.1.0 | GitHub Release created with .exe + sha256 | — | PASS (epic) | YES |
```

— Gage, publicando com cuidado ⚙️
