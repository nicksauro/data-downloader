# EPIC 4 — Multi-asset & Library API

**Status:** prep ready (Stories 4.1-4.4 detalhados via COUNCIL-13 em 2026-05-03)
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03 (placeholder); refinado 2026-05-03 (COUNCIL-13)
**Target:** expandir do MVP single-symbol (WDO) para multi-asset (WIN, equities) e estabilizar
public_api como library consumível por projetos downstream. Última fase de release V1.

---

## Objetivo

Tirar o data-downloader de "ferramenta WDO" para "biblioteca quant brasileira de
ingestão de mercado" — público alvo é o próprio squad em projetos futuros (backtest
engine, signal generator, risk monitor). Public_api estável significa: SemVer
estritamente enforced, breaking changes apenas via deprecation cycle, schema evolution
coordenada com backtest engine.

## Escopo IN

- **Multi-symbol broker process** (ADR-015 — broker dedicado serializa SQLite write
  lock; workers paralelos por símbolo; pool persistente mitiga H20 spawn overhead).
- **Multi-asset support:** WIN (índice futuro trimestral H/M/U/Z) + equities (PETR4,
  VALE3, ITUB4, BBDC4 — papel à vista, sem rollover).
- **public_api estável v1.0.0:** SemVer enforced, política de deprecação documentada,
  USAGE.md com exemplos de consumidor (backtest, signal generator, risk monitor),
  regression tests de backwards-compat.
- **Auto-updater** (ADR-017 — recomendação preliminar `tufup`, decisão final no
  início de 4.4 após POC em VM Windows).
- **Code signing Windows** (ADR-016 — EV cert ~$300/ano; opcional V1, condicional
  ao timing de emissão).
- **Release V1 packaging:** build determinístico (ADR-009), PyInstaller `--onedir`
  (ADR-003 amendment), GitHub Release pipeline com SHA256.

## Escopo OUT

- Real-time streaming (subscribe to live trades) — futuro Epic 5+.
- Order book (book of offers) — futuro.
- Outras bolsas (B3 outros mercados, CME, CBOE) — futuro.
- Multi-symbol via `public_api` (`download_batch(...)`) — Story V1.x futura;
  V1.0 mantém public_api single-symbol; multi-symbol vive na CLI via `--parallel`.
- Telemetria remota / analytics — fora de escopo permanente (privacidade).
- Sphinx/MkDocs site completo — `USAGE.md` markdown standalone é suficiente V1.

---

## Stories alocadas (pós-COUNCIL-13)

| ID  | Título                                                   | Owner / Implementer        | Estimativa | Depends on             |
|-----|----------------------------------------------------------|----------------------------|------------|------------------------|
| 4.1 | Multi-symbol broker process                              | 🏛️ Aria / 💻 Dex           | 4d         | 1.7a, 1.7b-followup    |
| 4.2 | Multi-asset support (WIN, equities)                      | 💾 Sol                     | 2d         | 1.7b-followup, 4.1     |
| 4.3 | Public API estável V1.0 release                          | 🏛️ Aria / 💻 Dex           | 1.5d       | 4.1, 4.2               |
| 4.4 | Auto-updater + packaging final V1 release                | ⚙️ Gage / 🖼️ Felix         | 3d         | 4.3                    |

**Total estimado:** ~10.5 dias = **2-3 sprints** (velocidade típica do squad).

---

## Cronograma estimado

```
Sprint A (semana 1):  4.1 (broker) ──────────── 4d
Sprint B (semana 2):  4.2 (multi-asset) ────── 2d
                      4.3 (public_api 1.0) ─── 1.5d
Sprint C (semana 3):  4.4 (release V1) ─────── 3d   + smoke humano + waiting cert
```

Smoke real WDOJ26 (Story 1.7b-followup, P0 pending) é **gating** para começar 4.1.
Sem smoke pré-existente, paralelizar via broker é prematuro.

---

## Gates do Epic

### Gate G-Multi-Asset (após 4.1 + 4.2)
- ✅ Broker estabilizado: 4 símbolos paralelos (`bench_multi_symbol` speedup ≥ 3.2x).
- ✅ Zero `SQLITE_BUSY` em stress test.
- ✅ Smoke gated humano: WINH26 + PETR4 1 dia cada → completam sem erro.
- ✅ `read_continuous` valida rollover trimestral WIN.
- ✅ Property tests Hypothesis cobrem invariantes do broker (INV-6).

### Gate G-Release-V1 (após 4.3 + 4.4)
- ✅ `__api_version__ = 1.0.0` publicado.
- ✅ Backtest engine (ou stub representativo) consome `public_api` sem hacks.
- ✅ Build determinístico: 2 builds independentes produzem hash idêntico (ADR-009).
- ✅ Auto-updater funcional: install N → release N+1 → check → apply → restart →
  version=N+1 (validado em VM Windows limpa por humano).
- ✅ Auto-updater rollback testado.
- ✅ Code signing presente (Caminho A) **OU** waiver documentado para V1.1
  (Caminho B — SmartScreen warning aceitável V1).
- ✅ Quinn full PASS em todas as 4 stories.
- ✅ Pyro: nenhuma regressão em bench suite.
- ✅ Sol: integridade clean cross-asset.
- ✅ Aria: nenhum ADR `proposed` em escopo.
- ✅ README + CHANGELOG + `INSTALL.md` + `USAGE.md` + `DEPRECATION_POLICY.md`
  publicados.

---

## Definition of Done (Epic)

- [ ] Story 4.1 Done (broker + pool persistente + bench speedup ≥ 3.2x).
- [ ] Story 4.2 Done (WIN + equities cobertos, smoke humano PASS).
- [ ] Story 4.3 Done (public_api v1.0.0 frozen, USAGE + DEPRECATION docs publicados).
- [ ] Story 4.4 Done (release V1 publicado em GitHub Release, instalador validado em
  VM limpa, auto-updater testado).
- [ ] Backtest engine prototype (ou stub) consome public_api sem hack.
- [ ] Auto-updater rollback testado em VM Windows.
- [ ] CHANGELOG.md seção "Release V1.0.0" publicada com todas garantias SemVer.
- [ ] ADR-015 + ADR-016 (se Caminho A) + ADR-017 todos em estado `accepted` final.

---

## Riscos identificados

| Risco                                                                  | Mitigação                                                                                                                                                                                                  |
|------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Multi-symbol multiprocessing introduz race em catálogo SQLite (C9)     | **Resolvido por ADR-015** (broker dedicado). Story 4.1 implementa fielmente; property tests garantem INV-6.                                                                                                |
| Multi-symbol Windows spawn = 2.7-10s overhead/subprocess (H20)         | **Pool persistente** em Story 4.1 AC5 (workers aquecidos, reuso entre jobs). Bench documenta crossover threshold single-vs-broker.                                                                          |
| Licença Nelogica para N processos (1 conexão DLL/proc) — múltiplas instâncias da mesma chave OK? | **Pendência operacional** — Morgan + Nelo confirmam com Nelogica antes de Story 4.1 começar. Se NOT OK: pivot para 1 processo + N threads (rejeita ADR-015) ou 1 conexão sequencial (sem ganho).            |
| WIN + equities têm quirks DLL não documentados                         | Nelo audita DLL via probe na Story 4.2 AC3 com WINH26 + PETR4 reais. Quirks descobertos = issue separada se severo.                                                                                         |
| Tooling auto-updater (tufup) ainda imaturo                             | ADR-017 reabre no D-1 da Story 4.4 com POC obrigatória + comparação Velopack. Aria assina decisão final em COUNCIL-14.                                                                                      |
| Code signing EV cert custo + processo (3-5 dias hábeis emissão)        | Gage inicia processo PARALELO ao Epic 4 começar (D-7). Caminho B (sem cert V1) documentado em INSTALL.md + Story 4.4-followup formaliza upgrade V1.1 com signing. Não bloqueia release V1.                  |
| public_api freeze dificulta evolução futura                            | Política de deprecação clara em `DEPRECATION_POLICY.md` (Story 4.3). Decorador `@deprecated` força anúncio N → remoção N+major+1 (mín 6 meses). Roadmap V1.x aditivo planejado.                              |
| Smoke real (1.7b-followup) ainda Pending Human — gating Story 4.1      | Morgan + Quinn priorizam 1.7b-followup ANTES de Sprint A começar. Sem smoke real WDO, paralelizar é prematuro.                                                                                              |

---

## Dependência externa explícita

- **Humano com ProfitDLL real:** smoke 1.7b-followup (pré-Epic 4) + smoke 4.2
  (WIN+equity) + smoke 4.4 (instalador VM limpa). Total ~3 sessões de ~1h cada
  + setup VM (~2h).
- **Nelogica:** confirmação operacional sobre múltiplas instâncias da mesma chave
  (R1 na tabela acima).
- **Code signing CA (se Caminho A):** Sectigo / DigiCert / Azure Trusted Signing
  para EV cert. Lead time emissão 3-5 dias úteis.

---

## Após o Epic

**Release V1 publicado.** Próximos epics são adições não-bloqueantes:

- **V1.1:** code signing (se Caminho B foi escolhido em V1) + Story 4.4-followup.
- **V1.x (minor aditivos):** `download_batch(...)` em public_api se backtest engine
  pedir; novas symbol roots conforme demanda; melhorias em `read_continuous` (lazy,
  streaming, etc.) — todas SemVer minor.
- **V2.0 (major):** nenhum breaking change planejado intencionalmente. Definição em
  PRD futuro se necessário.
- **Epic 5+:** real-time streaming, order book, outras bolsas — escopo OUT V1.

---

## Referências

- `docs/adr/ADR-015-multiprocess-catalog.md` (broker process — `accepted`)
- `docs/adr/ADR-016-code-signing.md` (EV cert)
- `docs/adr/ADR-017-auto-updater.md` (tufup preliminar — final no início Story 4.4)
- `docs/adr/ADR-007a-public-api-redesign.md` (DownloadHandle)
- `docs/adr/ADR-009-build-determinism.md`
- `docs/adr/ADR-003-front-pyside6.md` (+ amendment `--onedir`)
- `docs/storage/CONTRACTS.md` (seed multi-asset — expandido em Story 4.2)
- `docs/decisions/COUNCIL-13-epic4-prep.md` (esta convocação)
- `docs/stories/4.1.story.md`, `4.2.story.md`, `4.3.story.md`, `4.4.story.md`
- Pré-requisito gating: `docs/stories/1.7b-followup.story.md` (P0 Pending Human)
