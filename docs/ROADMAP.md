# ROADMAP — data-downloader

**Owner:** 📋 Morgan (PM/Orquestrador)
**Última atualização:** 2026-05-03
**Fonte única de verdade** sobre "o que vamos fazer e quando".

---

## Visão geral

O data-downloader é a **fundação de ingestão de dados de mercado** para todos os projetos quant futuros. Construído em 4 epics com gates rigorosos: foundation primeiro, qualidade segundo, UI terceiro, library/release V1 quarto.

---

## Tabela de Epics

| Epic | Título | Status | Target estimado | Dep | Doc |
|------|--------|--------|-----------------|-----|-----|
| **0** | Pré-implementação (Stories 0.0..0.4) | in_progress | T+5d | — | (stories `0.x.story.md` em `docs/stories/`) |
| **1** | Foundation (MVP CLI: WDOJ26 30 dias idempotente) | ready | T+25d (5d adendos + 20d implementação) | Epic 0 | `docs/epics/EPIC-1-foundation.md` |
| **2** | Quality & Performance | draft | T+45d | Epic 1 | `docs/epics/EPIC-2-quality-perf.md` |
| **3** | Desktop UI (PySide6) | draft | T+60d | Epic 2 | `docs/epics/EPIC-3-desktop-ui.md` |
| **4** | Multi-asset & Library API (Release V1) | draft | T+80d | Epic 2 (paralelo Epic 3 possível em parte) | `docs/epics/EPIC-4-multi-asset-api.md` |

**Legenda status:**
- `draft` — escopo definido, stories preliminares
- `ready` — stories validadas (Morgan `*validate-story` GO em todas)
- `in_progress` — pelo menos 1 story em InProgress
- `done` — todas as stories Done + gate de epic PASS
- `blocked` — bloqueado por dependência externa

---

## Cronograma detalhado (Epic 0 + 1)

### Fase A — Adendos pré-implementação (~5d)

Paralelizável — múltiplos owners trabalham simultaneamente.

| Wave | Story | Owner | Estimate | Status | Bloqueia |
|------|-------|-------|----------|--------|----------|
| 1 | 0.0 — Sol cria SCHEMA + CONTRACTS + INTEGRITY (+ MIGRATIONS + QUERIES) | 💾 Sol | 1d | **Done** (2026-05-03) | 1.3, 1.4, 1.5, 1.6 |
| 1 | 0.1 — Environment Bootstrap (git init) | ⚙️ Gage | 0.5d | Ready | 1.1 |
| 1 | 0.3 — UX Foundation (Uma) | 🎨 Uma | 1d | **Done** (2026-05-03) | 1.7b |
| 1 | 0.4 — CodeRabbit decision | ⚙️ Gage + 🧪 Quinn | 0.5d | Ready | (paralelo) |
| 2 | 0.2 — Pre-commit Framework | ⚙️ Gage | 0.5d | Ready | 1.1 |
| 1-2 | ADRs Aria (007a, 008..017 + amendments) | 🏛️ Aria | 2d (paralelo a tudo) | in_progress | conforme story |

**Wave atual (2026-05-03):** Wave 1 parcialmente fechada (0.0 + 0.3 Done). Restam 0.1, 0.2, 0.4 + ADRs Aria para fechar Fase A. Stories 1.3/1.4/1.5/1.6/1.7b agora têm fonte única de verdade documental disponível — podem entrar em InProgress assim que a Fase B (Wave 3+) começar.

### Fase B — Implementação Epic 1 (~20d)

Sequência otimizada com paralelismo (Aria propõe wave analysis se quiser).

| Wave | Story | Owner | Estimate | Dep |
|------|-------|-------|----------|-----|
| 3 | 1.1 — Scaffolding | 💻 Dex | 1d | 0.0, 0.1, 0.2 |
| 4 | 1.2 — DLL wrapper (Nelo está atualizando AC) | 💻 Dex | 2d | 1.1 |
| 4 (paralelo 1.2) | 1.4 — Storage layer | 💻 Dex | 2d | 0.0, 1.1 |
| 5 | 1.3 — History download primitive | 💻 Dex | 2d | 0.0, 1.2 |
| 5 (paralelo 1.3) | 1.4.5 — Synthetic baselines | ⚡ Pyro | 1d | 1.4 |
| 6 | 1.5 — Catálogo SQLite | 💻 Dex | 2d | 1.4 |
| 7 | 1.6 — Contract calendar | 💻 Dex | 1d | 1.2, 1.3, 1.5 |
| 8 | 1.5b — read_continuous + queries DuckDB | 💻 Dex + 💾 Sol | 1d | 1.5, 1.6 |
| 8 (paralelo 1.5b) | 1.7a — Orchestrator core | 💻 Dex | 2d | 1.3, 1.5, 1.6 |
| 9 | 1.7b — CLI + public_api + smoke MVP gate | 💻 Dex (review Uma) | 2d | 1.7a, 0.3 |
| 10 | 1.8 — Pyro baselines reais | ⚡ Pyro | 1d | 1.7b |
| 10 (paralelo 1.8) | 2.1 — Validators como código | 💾 Sol + 🧪 Quinn | 2d | 1.7b |

**Gate G-Foundation (1.7b):** smoke MVP verde + Quinn PASS = squad pode prosseguir Epic 2/3 EM PARTE (validators 2.1 + baselines 1.8 ainda fechando).

**Gate G-Foundation-Close (1.8 + 2.1):** Epic 1 fechado oficialmente. Epic 2 inicia formalmente.

---

## Cronograma alto-nível (Epic 2 + 3 + 4)

| Período | Epic | Marco |
|---------|------|-------|
| T+25d a T+45d | Epic 2 | Stories 2.2..2.10 (~19d, sequencial com paralelismos) |
| T+45d a T+60d | Epic 3 | Stories 3.1..3.8 (~13d) |
| T+60d a T+80d | Epic 4 | Stories 4.1..4.8 (~19d) — Release V1 |

**Possibilidade de paralelismo Epic 3 + Epic 4:** após Epic 2 fechar, Felix pode iniciar Epic 3 em paralelo a Dex iniciando Epic 4 (branches isoladas conforme `docs/release/BRANCH_MODEL.md` — Story 0.1).

---

## Dependências críticas (resumo)

```
0.0 ──> 1.3, 1.4, 1.5, 1.6
0.1 ──> 0.2 ──> 1.1
0.3 ──> 1.7b
1.1 ──> 1.2 ──> 1.3
1.1 ──> 1.4 ──> 1.4.5
1.4 ──> 1.5
1.2 + 1.3 + 1.5 ──> 1.6
1.5 + 1.6 ──> 1.5b
1.3 + 1.5 + 1.6 ──> 1.7a ──> 1.7b
1.7b ──> 1.8
1.7b ──> 2.1
1.7b + 1.8 + 2.1 ──> Epic 1 close
Epic 1 close ──> Epic 2
Epic 2 close ──> Epic 3 (paralelo possível com Epic 4)
```

---

## Riscos macro do roadmap

| Risco | Severidade | Mitigação |
|-------|------------|-----------|
| ADRs 007a/008..017 atrasam ≥2d | HIGH | Aria entrega esqueletos em Wave 1; refinamento paralelo a Wave 3+ |
| DLL Nelogica não disponível para smoke real | HIGH | Smoke gated por env; gate roda em máquina com licença |
| Multi-symbol multiprocessing (Epic 4) revelar problemas de SQLite WAL não previstos | RESOLVED 2026-05-05 | ~~ADR-015~~ REVOKED (licença Nelogica single-session); multi-symbol é serial em 1 processo conforme **ADR-022** — risco de SQLite contention não existe mais |
| Felix indisponível em Epic 3 | MEDIUM | Felix pode atuar em parte de Epic 4 (packaging) se Epic 3 atrasar |
| Code signing EV cert tem lead time 3-5d | LOW | Gage inicia processo Epic 4 dia 1 |

---

## Como atualizar este ROADMAP

- Apenas Morgan edita este arquivo (`*roadmap` command).
- Status de epic muda quando: gate de epic PASS (Quinn + Pyro + Sol + Aria).
- Bumps de estimativa documentados em `docs/decisions/ROADMAP_BUMP_{date}.md`.
- Mudança de escopo (story entra/sai de epic) exige veto/approval Morgan + registro em `docs/decisions/SCOPE_CHANGE_{date}.md`.

— Morgan, orquestrando o squad 📋
