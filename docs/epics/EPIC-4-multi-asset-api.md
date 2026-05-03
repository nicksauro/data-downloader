# EPIC 4 — Multi-asset & Library API

**Status:** draft
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03
**Target:** expandir do MVP single-symbol (WDO) para multi-asset (WIN, equities) e estabilizar public_api como library consumível por projetos downstream. Última fase de release V1.

---

## Objetivo

Tirar o data-downloader de "ferramenta WDO" para "biblioteca quant brasileira de ingestão de mercado" — público alvo é o próprio squad em projetos futuros (backtest engine, signal generator, risk monitor). Public_api estável significa: semver enforced, breaking changes via deprecation cycle, schema evolution coordenada com backtest engine.

## Escopo IN

- **WIN support** (índice futuro — diferenças vs WDO: trimestral H/M/U/Z, contratos vigentes diferentes, talvez quirks DLL)
- **Equities** (PETR4, VALE3 — bolsa B vs F, sem rollover de contrato, mas múltiplos símbolos populares)
- **public_api estável v1.0.0** (ADR-007a finalizado; semver enforced; CHANGELOG público)
- **Multi-symbol via multiprocessing** (ADR-015 — coordination de catalog SQLite entre processos; resolver finding C9 SQLite WAL N writers)
- **Auto-updater** (ADR-017 — tufup ou alternativa)
- **Code signing Windows** (ADR-016 — EV cert $300/ano, gerencia Gage)
- **Release V1 packaging** (build determinístico ADR-009; instalador .msi opcional)
- **Documentação library** (Sphinx/MkDocs com exemplos consumindo public_api)

## Escopo OUT

- Real-time streaming (subscribe to live trades) — futuro Epic 5+
- Order book (book of offers) — futuro
- Outras bolsas (B3 outros mercados, CME, CBOE) — futuro
- Telemetria remota / analytics — fora de escopo permanente (privacidade)

## Stories planejadas (preliminares)

| ID | Título | Owner | Estimativa |
|----|--------|-------|------------|
| 4.1 | WIN support (contract calendar trimestral H/M/U/Z) | 💻 Dex + 💾 Sol + 🗝️ Nelo | 2d |
| 4.2 | Equities support (PETR4, VALE3 — bolsa B) | 💻 Dex + 🗝️ Nelo | 2d |
| 4.3 | public_api v1.0.0 freeze (semver, CHANGELOG, deprecation policy) | 🏛️ Aria + 💻 Dex | 2d |
| 4.4 | Multi-symbol multiprocessing (ADR-015 implementação) | 💻 Dex + 🏛️ Aria | 4d |
| 4.5 | Auto-updater (ADR-017 implementação) | 🖼️ Felix + ⚙️ Gage | 3d |
| 4.6 | Code signing Windows EV cert (ADR-016) | ⚙️ Gage | 1d (após cert) |
| 4.7 | Release V1 packaging (build determinístico, .msi) | ⚙️ Gage + 🖼️ Felix | 3d |
| 4.8 | Documentação library (Sphinx/MkDocs) | 🏛️ Aria + 💻 Dex | 2d |

**Total:** ~19 dias estimados (preliminar).

## Gates do Epic

### Gate G-Library
- ✅ public_api v1.0.0 publicado (semver freeze)
- ✅ Backtest engine (ou stub representativo) consome public_api sem hacks
- ✅ Multi-symbol bench: 4 símbolos paralelos não geram SQLITE_BUSY
- ✅ WIN + Equities: smoke download real OK

### Gate G-Release
- ✅ Build determinístico: 2 builds independentes produzem hash idêntico (ADR-009)
- ✅ Code signing: instalador assinado, SmartScreen sem alerta
- ✅ Auto-updater: rollback testado
- ✅ Quinn full PASS
- ✅ Pyro: nenhuma regressão
- ✅ Sol: integridade clean
- ✅ Aria: nenhum ADR proposed em escopo
- ✅ README + CHANGELOG + docs library publicados

## Definition of Done (Epic)

- [ ] Todas as stories Done
- [ ] Release V1 publicado (instalador assinado disponível)
- [ ] Library documentada (docs/api/)
- [ ] Backtest engine prototype consome public_api sem hack
- [ ] Auto-updater rollback testado em VM Windows

## Riscos identificados

| Risco | Mitigação |
|-------|-----------|
| Multi-symbol multiprocessing introduz race em catalog SQLite (finding C9) | ADR-015 define padrão (broker dedicado, OU sharded por symbol, OU retry com backoff) — Aria escolhe ANTES de Story 4.4 |
| Multi-symbol Windows spawn = 2.7-10s overhead/subprocess (finding H20) | Pyro mede; multi-symbol pode ser opt-in (não default); bench documenta break-even |
| WIN + equities têm quirks DLL não documentados | Nelo audit DLL com exemplos reais; smoke gated por env |
| Code signing EV cert custo + processo (3-5 dias hábeis para emissão) | Gage inicia processo PARALELO ao Epic 4 começar; não bloqueia outras stories |
| public_api freeze dificulta evolução futura | Deprecation policy clara em ADR-007a; semver MAJOR para breaking changes |

## Após o Epic

**Release V1 publicado.** Próximos epics são adições não-bloqueantes (real-time streaming, order book, outras bolsas, etc.) — definição em PRD futuro.
