# COUNCIL-13 — Epic 4 Prep (Multi-asset & Library API V1.0 Release)

**Data:** 2026-05-03
**Convocação:** Mini-council Aria + Sol + Felix — modo autônomo (Epic 4 prep task)
**Participantes mentais:**
- 🏛️ Aria (Architect — autoridade exclusiva ADRs, fronteira public_api,
  thread/process model)
- 💾 Sol (Storage Engineer — autoridade exclusiva schema Parquet, catálogo SQLite,
  contratos vigentes)
- 🖼️ Felix (Frontend Developer — autoridade exclusiva `src/data_downloader/ui/`,
  PyInstaller spec)

**Reviewers (downstream):**
- 📋 Morgan (PM — priorização Epic 4, gating 1.7b-followup)
- 💻 Dex (Dev — implementer broker, public_api docstrings, updater client)
- 🧪 Quinn (QA — gates G-Multi-Asset + G-Release-V1, smoke humano)
- ⚡ Pyro (Perf — bench_multi_symbol speedup ≥ 3.2x, threshold single-vs-broker)
- 🗝️ Nelo (DLL — quirks WIN/equity, confirmação licença Nelogica multi-instância)
- ⚙️ Gage (DevOps — release pipeline, code signing, tufup metadata)

---

## Contexto

Epic 4 (Multi-asset & Library API) estava em estado **placeholder** desde 2026-05-03
(criação inicial). A versão preliminar listava 8 stories (4.1-4.8) com estimativas
brutas (~19 dias) mas **sem detalhamento de ACs, dependências, gates, ou plano de
implementação**.

Esta convocação **não abre Epic 4** — apenas adianta artefatos preparatórios para
que, quando Morgan/PO autorizarem o início, as stories estejam:

- Ready para validação @po (10-point checklist passável).
- Com ACs testáveis (Given/When/Then-friendly).
- Com dependências mapeadas explicitamente.
- Com riscos endereçados ou escalados.
- Alinhadas com ADR-015 (broker), ADR-017 (auto-updater), ADR-007a (public_api),
  ADR-003 amendment (onedir), ADR-009 (build determinism), ADR-016 (signing).

Decisão estratégica do prep: **consolidar 8 stories preliminares em 4 stories**
melhor escopadas:

| Story preliminar (placeholder) | Story consolidada (COUNCIL-13)        |
|--------------------------------|---------------------------------------|
| 4.1 (WIN) + 4.2 (Equities)     | **4.2** Multi-asset (WIN + equities)  |
| 4.4 (Multi-symbol MP)          | **4.1** Multi-symbol broker process   |
| 4.3 (public_api v1.0.0)        | **4.3** Public API V1.0 release       |
| 4.5+4.6+4.7+4.8 (updater+sign+packaging+docs) | **4.4** Auto-updater + packaging final |

Razão da consolidação:
- **WIN + equities** compartilham 80% do trabalho (calendário multi-shape, probe DLL,
  testes paralelos). Splittar gera duplicação de overhead.
- **Code signing + packaging + auto-updater + docs release** são 1 release ritual —
  splittar gera 4 PRs em vez de 1 release coerente.
- Total estimado **10.5 dias** (vs 19 dias preliminar) — Aria + Sol + Felix
  acreditam que escopo realista é menor; preliminar tinha overlap.

---

## Estratégia

**Trabalho preparatório agora, implementação real depois (autorização Epic 4).**

Esta convocação produz:

1. `docs/stories/4.1.story.md` (broker — Aria + Dex impl, 4d).
2. `docs/stories/4.2.story.md` (multi-asset — Sol owner, 2d).
3. `docs/stories/4.3.story.md` (public_api v1.0 — Aria + Dex impl, 1.5d).
4. `docs/stories/4.4.story.md` (release V1 — Gage + Felix impl, 3d).
5. Refinamento `docs/epics/EPIC-4-multi-asset-api.md` (status `prep ready`,
   cronograma 2-3 sprints, gates G-Multi-Asset + G-Release-V1, riscos endereçados).
6. Esta convocação (sign-off Aria + Sol + Felix).

Implementação real continua reservada para Epic 4 stories 4.1-4.4 após autorização
do Morgan/PO **e** smoke real 1.7b-followup PASS (gating absoluto).

---

## Decisões

### D1 — Consolidar 8 stories preliminares em 4 stories

**Decidido (Aria + Sol + Felix):**

Total estimado revisado de 19d → 10.5d via consolidação descrita na tabela acima.

**Razão:**
- WIN + equities têm overhead compartilhado (calendário, probe, testes) — splittar
  gera duplicação.
- Release ritual (signing + packaging + updater + docs) é unidade coerente — 1 PR
  é melhor que 4.
- Stories menores (1.5d, 2d, 3d, 4d) preservam granularidade aceitável para
  rollback / paralelismo de trabalho dentro do squad.

**Alternativa rejeitada:** manter 8 stories preliminares — overhead de orquestração
e splits artificiais. Morgan pode re-splittar se preferir, mas Aria recomenda
consolidação.

---

### D2 — Story 4.1 (broker) implementa fielmente ADR-015 sem novas decisões

**Decidido (Aria autoridade exclusiva):**

ADR-015 (Multiprocess catalog coordination — broker process) está em estado
`accepted` desde 2026-05-03. Story 4.1 é **implementação fiel** da Opção A do
ADR — não reabre decisão arquitetural.

**Razão:**
- ADR-015 já considerou 4 alternativas (broker, sharded catalogs, retry com
  backoff, Postgres). Decisão tomada com sign-off de Sol (catálogo) + Pyro (perf)
  + Nelo (DLL).
- Implementação tem 8 ACs detalhados (CatalogBroker thread, CatalogClient stub,
  ACK protocol, pool persistente, CLI `--parallel`, bench speedup ≥ 3.2x, tests
  integration + property + smoke).
- Sem espaço para "redesign" — Aria bloqueia se @dev tentar reabrir Opção B/C/D
  em meio à Story 4.1.

**Pendência operacional:** confirmação Nelogica sobre múltiplas instâncias mesma
chave (R1 em EPIC-4 §Riscos). Se Nelogica negar: ADR-015 vira `superseded` por
novo ADR (Aria reabre); Epic 4 escopo revisitado.

---

### D3 — Story 4.2 owner = Sol (não Aria/Dex)

**Decidido (Sol + Aria):**

Story 4.2 (Multi-asset support) tem Sol como owner — não Dex como nas stories de
implementação core. Razão: o eixo crítico é **`docs/storage/CONTRACTS.md`** +
calendário trimestral WIN + vigência infinita equity = território exclusivo de Sol.
@dev (Dex) implementa testes + integração com chunker/orchestrator existente, mas
decisão sobre estrutura de seed, regras de vigência, e probe protocol é Sol.

**Razão:**
- COUNCIL-07 + COUNCIL-06 já estabeleceram autoridade de Sol sobre contracts/rollover.
- Schema Parquet é genérico (campo `symbol` carrega ticker arbitrário) — sem
  decisão de schema necessária. Mas calendário multi-shape (mensal vs trimestral
  vs infinito) é decisão de modelagem de domínio.

---

### D4 — Story 4.3 implementer = @dev, mas content owner = Aria

**Decidido (Aria + Dex):**

Story 4.3 (Public API v1.0) tem owner=architect mas implementer=dev. Aria escreve
USAGE.md + DEPRECATION_POLICY.md (docs arquiteturais — território Aria). @dev (Dex)
implementa decorator `@deprecated`, completa docstrings restantes, escreve regression
tests SemVer. Aria revisa via `*review-design`.

**Razão:**
- Aria não escreve código de produção (regra dura da persona). Decorator é código.
- Aria define contrato + escreve docs arquiteturais. @dev implementa.
- Tests SemVer regression são responsabilidade compartilhada — @dev escreve com
  base na lista `__all__` v0.3.0 (Aria fornece).

---

### D5 — Story 4.4 owner = devops (Gage), implementer = Felix + Gage

**Decidido (Felix + Gage):**

Story 4.4 (release V1) tem owner=devops porque pipeline de release + signing +
tufup metadata + GitHub Release são território exclusivo de @devops (delegation
matrix `agent-authority.md`). Felix implementa UI integration (toast notification,
settings opt-out auto-check) — território exclusivo dele (`src/data_downloader/ui/`).

**Razão:**
- @devops authority exclusivo: `git push`, `gh pr create`, MCP add/remove, CI/CD
  pipeline, **release management**.
- Felix authority exclusivo: UI Qt — toast + settings screen.
- Aria reviewer porque define escolha final do tooling (re-abre ADR-017 conforme
  planejado).

---

### D6 — Code signing condicional V1 (Caminho A vs B)

**Decidido (Felix + Gage):**

Story 4.4 AC5 deliberadamente flag opcional V1:
- **Caminho A (cert disponível em window release):** signing integrado, instalador
  ganha "Verified Publisher" no SmartScreen.
- **Caminho B (cert não disponível):** documentar workaround SmartScreen em
  INSTALL.md + criar Story 4.4-followup para V1.1 com signing.

**Razão:**
- EV cert custa ~$300/ano + 3-5 dias úteis emissão. Gage começa processo PARALELO
  ao Epic 4 (D-7), mas pode não chegar a tempo.
- Caminho B é aceitável V1 (squad uso interno + early adopters externos sabem que
  é V1; SmartScreen "Run anyway" é UX friction aceitável temporariamente).
- Decisão Caminho A vs B no D+1 da story (Gage informa status do cert em standup).

**Alternativa rejeitada:** bloquear release V1 esperando cert. Não vale o risco
de slip indefinido por questão administrativa.

---

### D7 — Auto-updater tooling final TBD em Story 4.4 (POC obrigatória)

**Decidido (Aria):**

ADR-017 está em estado `accepted (deferred to Epic 4)` com Opção A (tufup) como
recomendação preliminar. Story 4.4 Task 1 reabre o ADR formalmente:
1. POC tufup em VM Windows (~2h, Aria + Gage).
2. Comparação atualizada Velopack (Opção F).
3. ADR-017 atualizado para `accepted — final decision: {tooling}` em COUNCIL-14.

**Razão:**
- ADR-017 explicitamente listou "decisão final pendente" no estado `deferred`.
- Story 4.4 é o momento natural — antes de implementar updater, decidir tooling.
- Aria assina decisão final em COUNCIL-14 (não nesta convocação — esta apenas
  organiza Epic 4).

---

### D8 — Smoke real obrigatório antes de Epic 4 fechar

**Decidido (Quinn pré-requisito + Aria + Sol concordam):**

Stories 4.1, 4.2, 4.4 todas têm dependência explícita em **smoke real humano**:
- Story 4.1 depende de 1.7b-followup (smoke WDOJ26 30d) PASS — sem isso,
  paralelizar é prematuro.
- Story 4.2 AC6 exige smoke humano WINH26 + PETR4 1 dia cada.
- Story 4.4 AC6 exige smoke em VM Windows limpa com instalador V1 + ciclo de
  update completo.

**Razão:**
- Constitutional: Article IV (No Invention) + COUNCIL-09 (MVP gate sem smoke real
  é débito). Epic 4 é release V1 — não pode ter débito de smoke.
- Backtest engine (primeiro consumer) precisa confiança que pipeline funciona
  cross-asset, não só WDO.
- Code signing + auto-updater são funcionalidades novas que não têm cobertura
  unit/integration suficiente — smoke é o único validador real.

**Pendência operacional gating:** Morgan + Quinn priorizam 1.7b-followup ANTES de
Sprint A do Epic 4. Sem smoke pré-existente, broker é construído sobre fundação
não validada.

---

### D9 — Multi-symbol via public_api fica para V1.x (não V1.0)

**Decidido (Aria):**

`public_api.download(...)` permanece **single-symbol** em V1.0. Multi-symbol vive
apenas na CLI via `--parallel` (Story 4.1 AC6) em V1.0.

**Razão:**
- Decisão de fronteira pública: `download_batch(symbols=[...], ...)` ou loop
  client-side é trade-off não óbvio. Adicionar em V1.0 sem necessidade de consumer
  real é especulação (Article IV violation).
- Se backtest engine pedir multi-symbol via API, Story V1.x adiciona aditivamente
  (minor bump): `from data_downloader.public_api import download_batch` é caso
  natural de extensão.
- CLI multi-symbol (Story 4.1) atende caso de uso operador humano — caso comum
  de batch download.

**Documentado:** EPIC-4 §Escopo OUT lista explicitamente multi-symbol via
public_api.

---

### D10 — Sphinx/MkDocs site fora do escopo V1.0

**Decidido (Aria + Felix):**

`USAGE.md` markdown standalone é suficiente para V1.0. Sphinx/MkDocs site completo
fica para futuro se necessário.

**Razão:**
- Markdown é universal, lê em qualquer editor / GitHub render / IDE.
- Sphinx/MkDocs adiciona deploy infra (gh-pages, Read the Docs, etc.) — overhead
  desproporcional para V1.0 com poucos consumers.
- Stories futuras podem adicionar se demanda surgir.

---

## Sign-off

### 🏛️ Aria (Architect)

**APPROVED** — fronteira public_api preservada + ADR-015 implementação fiel.

- Story 4.1 implementa fielmente ADR-015 Opção A (broker process). Sem espaço para
  redesign arquitetural — invariantes INV-6 + protocol pattern garantem.
- Story 4.3 formaliza public_api v1.0.0 com SemVer estrito + política de deprecação.
  Multi-symbol via public_api fica para V1.x aditivo (D9).
- Story 4.4 reabre ADR-017 conforme planejado para decisão final tooling
  auto-updater (POC obrigatória).
- ADR-003 amendment (`--onedir`) é pré-requisito Story 4.4 — confirmar `accepted`.
- Constitutional Article IV (No Invention) preservado: estimativas baseadas em
  bench existente + ADR-015 §Performance, não chutes.
- Risco operacional R1 (licença Nelogica multi-instância) escalado para Morgan +
  Nelo — bloqueador potencial de Story 4.1; Aria não pode resolver sozinha.

— Aria, mapeando o território 🏛️

---

### 💾 Sol (Storage Engineer)

**APPROVED** — schema preservado cross-symbol + contracts seed expandida.

- Story 4.2 expande seed `CONTRACTS.md` para WIN H/M/U/Z 2026+2027 + equities
  (PETR4, VALE3, ITUB4, BBDC4) — todas com `validation_source` correta
  (`hypothesized` para futuros até probe DLL, `manual` para equities).
- Schema Parquet (Story 1.4 v1.0.0) NÃO muda — campo `symbol` é genérico, suporta
  qualquer ticker. Zero migração de dado.
- `read_continuous` reusado para WIN (rollover trimestral usa mesma lógica WDO
  mensal — vigent_from/vigent_until governs). Caso degenerado equity (1 vigência
  infinita) tratado como caso normal.
- Probe DLL via Story 1.6 *validate path estendido para PETR4 (não só roots de
  futuros). Documentado em CONTRACTS.md §5.2.
- Property tests Hypothesis em Story 4.2 (`test_contract_calendar.py`) garantem
  invariante: para qualquer data, retorno único OU None OU AmbiguousContractError
  — nunca retorno errado silencioso.
- Risco quirks DLL WIN/equity escalado para Nelo via probe na Story 4.2 AC3.

— Sol, custodiando o histórico 💾

---

### 🖼️ Felix (Frontend Developer)

**APPROVED** — packaging strategy ADR-003 amendment + UI integration auto-updater.

- Story 4.4 packaging usa PyInstaller `--onedir` (ADR-003 amendment) — facilita
  updates granulares via tufup vs `--onefile` monolítico.
- Build determinístico (ADR-009) com `PYTHONHASHSEED=0` + `SOURCE_DATE_EPOCH` +
  lockfile — test compara 2 builds = mesmo SHA.
- UI integration auto-updater: toast notification (microcopy ID em
  `MICROCOPY_CATALOG.md` — Uma adiciona quando Story 4.4 começa) + settings
  screen opt-out auto-check (Story 4.4 alteração `settings_screen.py`).
- Companions PyInstaller: ProfitDLL.dll, libcrypto/libssl, *.dat, theme.qss,
  ícones — lista canônica do `frontend-dev.md` packaging_choices.
- Code signing Caminho A vs B (D6) — Felix não bloqueia se cert atrasar; INSTALL.md
  documenta workaround SmartScreen em pt-BR.
- Smoke VM Windows limpa (humano) é o único validador real do release — Felix
  consome protocolo `test_release_install.md`, não automatiza.

— Felix, construindo superfícies 🖼️

---

## Decisão chave consensual

**Smoke real obrigatório antes de Epic 4 fechar (D8).**

Os três agentes (Aria + Sol + Felix) concordam: Epic 4 é release V1; não pode
fechar sem smoke real cobrindo:
1. WDOJ26 30 dias (Story 1.7b-followup — pré-requisito GATING).
2. WINH26 + PETR4 1 dia cada (Story 4.2 AC6).
3. Instalador V1 em VM Windows limpa + ciclo update completo (Story 4.4 AC6).

Sem essa cobertura, código vai para mãos de outros consumers (backtest engine,
adopters externos) com débito não pago — violação Article IV (No Invention) +
COUNCIL-09 (débito de smoke é dívida real).

---

## Pendências (não bloqueiam esta entrega — bloqueiam Epic 4 começar)

| #  | Pendência                                                                                        | Owner          | Bloqueia              |
|----|--------------------------------------------------------------------------------------------------|----------------|-----------------------|
| P1 | Story 1.7b-followup smoke real WDOJ26 30d PASS                                                   | humano + Quinn | Story 4.1 começar     |
| P2 | Confirmação Nelogica: múltiplas instâncias mesma chave OK (multi-process licença)                | Morgan + Nelo  | Story 4.1 começar     |
| P3 | EV cert iniciado (3-5d emissão) ou decisão Caminho B documentada                                 | Gage           | Story 4.4 AC5 final   |
| P4 | ADR-003 amendment (`--onedir`) confirmado em estado `accepted`                                   | Aria           | Story 4.4 Task 3      |
| P5 | Aria + Gage POC tufup em VM Windows + ADR-017 final decision em COUNCIL-14                       | Aria + Gage    | Story 4.4 Task 1      |

---

## Após esta convocação

- **Não abrir Epic 4** sem autorização Morgan/PO **e** P1 (smoke real) PASS.
- Ao autorizar Epic 4, Stories 4.1-4.4 começam com:
  - Detalhamento Epic-4-ready (esta COUNCIL).
  - ACs testáveis (Given/When/Then-friendly nas 4 stories).
  - Dependências mapeadas explicitamente.
  - Riscos endereçados ou escalados (R1-R7 em EPIC-4 §Riscos).
  - Pendências P1-P5 resolvidas (humano/Morgan/Nelo/Aria/Gage).
- Lead time esperado Epic 4 reduzido em ~3-5 dias graças a este prep.

---

## Estado dos Epics pós-COUNCIL-13

| Epic | Status                          | Detalhes                                                                                |
|------|---------------------------------|-----------------------------------------------------------------------------------------|
| 1    | ~17/17 stories conditional Done | Smoke real WDOJ26 (1.7b-followup) Pending Human — gate condicional fechado COUNCIL-09  |
| 2    | ~6/13 stories Done              | Story 2.2 (vectorized writer) Ready for Review; resto em planejamento                   |
| 3    | prep ready (COUNCIL-12)         | Wireframes/skeleton/QSS prontos; aguarda autorização Morgan/PO + P1-P5 do COUNCIL-12   |
| 4    | prep ready (COUNCIL-13 — esta)  | Stories 4.1-4.4 detalhados; aguarda autorização Morgan/PO + P1-P5 acima                 |

---

## Referências

- `docs/epics/EPIC-4-multi-asset-api.md` (refinado nesta convocação)
- `docs/stories/4.1.story.md`, `4.2.story.md`, `4.3.story.md`, `4.4.story.md`
- `docs/adr/ADR-015-multiprocess-catalog.md` (broker — `accepted`)
- `docs/adr/ADR-017-auto-updater.md` (tufup preliminar — final em Story 4.4)
- `docs/adr/ADR-007a-public-api-redesign.md` (DownloadHandle)
- `docs/adr/ADR-003-front-pyside6.md` (+ amendment `--onedir`)
- `docs/adr/ADR-009-build-determinism.md`
- `docs/adr/ADR-016-code-signing.md`
- `docs/storage/CONTRACTS.md` (seed multi-asset)
- `docs/decisions/COUNCIL-09-mvp-gate-without-real-smoke.md` (débito smoke real)
- `docs/decisions/COUNCIL-12-epic3-prep.md` (paralelo — Epic 3 prep)
- `docs/stories/1.7b-followup.story.md` (P0 Pending Human — gating Epic 4)

---

— Aria 🏛️, Sol 💾, Felix 🖼️ — Epic 4 prep completo.
