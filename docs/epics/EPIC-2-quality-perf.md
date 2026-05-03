# EPIC 2 — Quality & Performance

**Status:** draft
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03
**Target:** elevar foundation a nível production-grade — observabilidade, perf tuning, schema migration framework, retry inteligente. Pós-Epic 1.

---

## Objetivo

Transformar foundation funcional (Epic 1) em foundation **production-grade**: observabilidade real (não logs ad-hoc), performance otimizada (não palpites), evolução de schema sem dor, retry inteligente (não backoff naïve). Sem este Epic, Epic 3 (UI) e Epic 4 (multi-asset) construiriam em cima de fundação ainda crua.

## Escopo IN

- **Pyro full benchmarks** (todos os 9 benchmarks de `agents/perf-engineer.md` rodados, baselines + budgets vinculados)
- **Retry inteligente** (categorização de erros NL_*; retry policy por categoria; circuit breaker para timeouts repetidos)
- **Observabilidade ADR-013 implementada** (counters, gauges, histograms, expostos via /metrics ou Prometheus pull)
- **Schema migration framework** (finding H16 — bumpa schema_version sem re-baixar tudo; migration scripts versionados; rollback)
- **Hot path tuning** (eliminar/mover structlog do hot path — finding H22; HOT_PATH_RULES.md aplicado)
- **Storage perf tuning** (row_group_size, compression matrix Snappy/ZSTD final, cache PRAGMAs ajustadas — finding M6)
- **Logging strategy ADR-010 implementada** (correlation_id global, redaction de secrets, formato estruturado JSON)
- **Test strategy ADR-014 formalizada** (mock DLL, fake clock, fixtures, layers — código real)
- **Exception hierarchy ADR-011 implementada** (internals → public_api → UI propaga errors com contexto)

## Escopo OUT

- UI PySide6 (Epic 3)
- Multi-asset / multi-symbol (Epic 4)
- Auto-updater (Epic 4)
- Code signing (Epic 4)
- Release V1 packaging (Epic 4)

**NOTA:** Story 2.1 (validators como código) **foi movida para Epic 1** conforme finding C4. Não está mais aqui.

## Stories planejadas (preliminares)

| ID | Título | Owner | Estimativa |
|----|--------|-------|------------|
| 2.2 | Pyro full benchmarks (9 benchmarks de perf-engineer.md) | ⚡ Pyro | 3d |
| 2.3 | Retry inteligente + circuit breaker | 💻 Dex | 2d |
| 2.4 | Observabilidade (ADR-013 implementação) | 💻 Dex + 🏛️ Aria | 2d |
| 2.5 | Schema migration framework (finding H16) | 💾 Sol + 💻 Dex | 3d |
| 2.6 | Hot path tuning (HOT_PATH_RULES.md aplicado) | ⚡ Pyro + 💻 Dex | 2d |
| 2.7 | Storage perf tuning (row_group, compression final) | 💾 Sol + ⚡ Pyro | 2d |
| 2.8 | Logging strategy ADR-010 implementada | 💻 Dex + 🏛️ Aria | 1d |
| 2.9 | Test strategy ADR-014 (formalização + código de fixtures) | 🧪 Quinn + 💻 Dex | 2d |
| 2.10 | Exception hierarchy ADR-011 implementada | 💻 Dex + 🏛️ Aria | 2d |

**Total:** ~19 dias estimados (preliminar — Morgan refina ao iniciar Epic 2).

## Gates do Epic

### Gate G-Quality
- ✅ Pyro `*regression-check` clean (sem regressão vs baselines Story 1.8)
- ✅ Quinn `*qa-gate 2.x` PASS em todas as stories
- ✅ Schema migration framework testado em migration v1.0.0 → v1.0.1 (caso real ou simulado)
- ✅ Observabilidade exposta (curl /metrics retorna 200 com métricas válidas)
- ✅ Hot path: structlog removido de hot path; CPU profile mostra log < 5%

## Definition of Done (Epic)

- [ ] Todas as stories Done
- [ ] Quinn PASS em cada uma
- [ ] Pyro: 0 regressões > regression budget
- [ ] Sol: schema migration framework operacional
- [ ] Aria: ADRs 010, 011, 013, 014 todos accepted
- [ ] Documentação de ops (como olhar métricas, como triagem de erros)

## Riscos identificados

| Risco | Mitigação |
|-------|-----------|
| Schema migration framework introduz complexidade que pesa Epic 1 retroativamente | Sol limita escopo: migration framework opcional para datasets já criados; obrigatório para novos |
| Observabilidade adiciona overhead em hot path | Pyro mede ANTES e DEPOIS; budget de overhead definido em REGRESSION_BUDGETS.md |
| Retry inteligente pode mascarar bugs reais | Categorização explícita: erros DLL transitórios = retry; erros lógicos = fail fast |

## Após o Epic

Próximo: **Epic 3 — Desktop UI** (PySide6 shell, telas Download/Catálogo/Settings, packaging .exe).
