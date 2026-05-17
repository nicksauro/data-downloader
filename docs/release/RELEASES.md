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
| v1.1.0 | 2026-05-12 | `v1.1.0` | `c305672d` | MINOR | [release-notes/v1.1.0-draft.md](../release-notes/v1.1.0-draft.md) | `77485049...345DD5` | pending — backfill |
| v1.1.1 | 2026-05-12 | `v1.1.1` | `56c17628` | HOTFIX | [release-notes/v1.1.1.md](../release-notes/v1.1.1.md) | `7E029046...CE5BA1` | pending — backfill |
| v1.2.0 | 2026-05-12 | `v1.2.0` | `bf1448e3` | MINOR | [release-notes/v1.2.0.md](../release-notes/v1.2.0.md) | `DFBB70DC...27ED6A5` | pending — backfill |
| v1.3.0 | 2026-05-13 | `v1.3.0` | `a57b6e38` | MINOR | [release-notes/v1.3.0.md](../release-notes/v1.3.0.md) | `8F7EFA81...BADAE48` | pending — backfill |

> Nota — backfill 2026-05-16 (Story 4.31 AC5): linhas reconstruídas a partir de
> `CHANGELOG.md`, `docs/release-notes/v1.x.x.md` (SHA256 dos installers Setup.exe)
> e tags git. v1.0.x não constam: foram **consolidadas** no single ship v1.1.0
> (ver CHANGELOG.md §1.1.0 "Highlights — Single ship consolidado") — nenhuma tag
> pushed/GitHub Release foi criada para v1.0.0..v1.0.7, então o critério
> "oficialmente publicadas" da seção acima as exclui. `audit_ref` ficou
> `pending — backfill` porque o AUDIT.md atual cobre apenas Stories 0.1..1.7b;
> entries das tags v1.x serão append-only por @devops em manutenção futura.

---

## Próxima release planejada

| Item | Valor |
|------|-------|
| Versão | `v1.4.0` (tentativa — pode bumpar para MAJOR conforme escopo) |
| Tipo | MINOR (UX hardening + CI/security) ou MAJOR (se quebrar public_api) |
| Milestone | Stories 4.22..4.30 (roadmap v1.4.0 — atomicidade storage, CI pipeline, code signing, refator cli.py) |
| ETA | TBD |
| Bloqueadores ativos | em planning |
| Owner do release | Gage (publicar) + Morgan (autorizar) + Quinn (PASS) |

---

## Histórico de auditorias / mudanças nesta tabela

| data | mudança | quem |
|------|---------|------|
| 2026-05-03 | Arquivo criado (placeholder) | Gage (Story 0.1 spec) |
| 2026-05-16 | Backfill v1.1.0..v1.3.0 (Story 4.31 AC5) | @dev (Dex) sob orientação @aiox-master Orion |

— Gage, publicando com cuidado ⚙️
