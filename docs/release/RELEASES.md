# RELEASES — Histórico de releases do data-downloader

**Owner:** Gage (devops) — autoridade exclusiva para escrever neste arquivo.
**Coordena com:** `AUDIT.md` (cada entry aqui referencia entry em AUDIT) e `CHANGELOG-{version}.md` (detalhes técnicos).
**Política:** append-only. Toda release oficial (tag SemVer pushed) gera entry.

---

## Formato

| Coluna | Descrição |
|--------|-----------|
| `versão` | SemVer: `vX.Y.Z` ou `vX.Y.Z-rc.N` para pre-release |
| `data` | ISO-8601 UTC: `YYYY-MM-DD` |
| `tag` | git tag annotated (sempre `vX.Y.Z`) |
| `sha` | commit SHA da tag (curto, 8 char) |
| `tipo` | `MAJOR` \| `MINOR` \| `PATCH` \| `PRERELEASE` \| `HOTFIX` |
| `changelog` | Link relativo para `docs/release/CHANGELOG-vX.Y.Z.md` |
| `sha256_exe` | SHA256 do `.exe` artifact (32 char curto exibido aqui, completo no GitHub Release) |
| `audit_ref` | timestamp da entry em `AUDIT.md` |

---

## Critérios para entrada nesta tabela

Apenas releases **oficialmente publicadas** (tag pushed para origin + GitHub Release criada).

NÃO entram aqui:
- Builds locais de teste
- `.exe` de desenvolvimento
- Tags privadas/locais não pushed

---

## Política de SemVer

| Bump | Quando |
|------|--------|
| **MAJOR** (`1.0.0 → 2.0.0`) | Breaking change em `public_api/` ou em schema Parquet |
| **MINOR** (`1.0.0 → 1.1.0`) | Feature aditiva (campo Parquet novo nullable, nova função pública) |
| **PATCH** (`1.0.0 → 1.0.1`) | Bugfix sem mudança de interface |
| **PRERELEASE** | `vX.Y.Z-rc.N`, `-alpha.N`, `-beta.N` antes de release final |
| **HOTFIX** | PATCH bump emergencial em release em produção (ver BRANCH_MODEL §6.4) |

> **v0.x.x:** foundation em construção; pode haver breaking sem MAJOR bump (sempre documentado em CHANGELOG).

---

## Pré-condições para qualquer release

> Mesmo lista do `agents/devops.md` checklist `release`:

1. Morgan `*release-readiness` retornou GO
2. Quinn PASS em todas as stories do milestone
3. Pyro: nenhuma regressão > budget configurado
4. Sol: `*data-validate` clean no dataset de teste
5. CHANGELOG escrito e revisado
6. Versão bumpada em `pyproject.toml`
7. Tag SemVer criada e pushed
8. `.exe` construído via PyInstaller + verificado (smoke `--version`)
9. SHA256 calculado
10. GitHub Release criado com artefatos
11. Esta tabela atualizada
12. AUDIT.md registrou ação

---

## Releases

| versão | data | tag | sha | tipo | changelog | sha256_exe | audit_ref |
|--------|------|-----|-----|------|-----------|------------|-----------|
| _(nenhuma release ainda — primeira esperada: v0.1.0 ao fechar Epic 1)_ | | | | | | | |

---

## Próxima release planejada

| Item | Valor |
|------|-------|
| Versão | `v0.1.0` |
| Tipo | MINOR (foundation, primeira release pública) |
| Milestone | Epic 1 fechado (Stories 0.0..0.4 + 1.0..1.7b + 1.8 + 2.1) |
| ETA | TBD (depende conclusão Story 0.x + Epic 1) |
| Bloqueadores ativos | Stories 0.0, 0.1, 0.2, 0.3, 0.4 + Aria ADR-008..017 |
| Owner do release | Gage (publicar) + Morgan (autorizar) + Quinn (PASS) |

---

## Histórico de auditorias / mudanças nesta tabela

| data | mudança | quem |
|------|---------|------|
| 2026-05-03 | Arquivo criado (placeholder) | Gage (Story 0.1 spec) |

— Gage, publicando com cuidado ⚙️
