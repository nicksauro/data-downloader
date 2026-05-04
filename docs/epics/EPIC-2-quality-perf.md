# EPIC 2 — Quality & Performance

**Status:** active (refinado em 2026-05-04 pós-COUNCIL-10 + Stories 1.7b/1.8 close Epic 1)
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03
**Última refino:** 2026-05-04
**Target:** elevar foundation a nível production-grade — observabilidade, perf
tuning, schema migration framework, retry inteligente, calendário B3 oficial.
Pós-Epic 1 (que fecha quando 1.7b-followup + 1.8-followup PASS humano).

---

## Objetivo

Transformar foundation funcional (Epic 1) em foundation **production-grade**:
observabilidade real (não logs ad-hoc), performance otimizada (gap -72% no
write fechado via vectorização), evolução de schema sem dor (framework
versioned migrations), retry inteligente (categorização de erros NL_*),
calendário B3 oficial via Nelogica `holidays.dat` (substituir tabela
hardcoded de Story 2.1). Sem este Epic, Epic 3 (UI) e Epic 4 (multi-asset)
construiriam em cima de fundação ainda crua.

## Escopo IN

- **Pyro perf-write-optimization** (Story 2.2 — vectorize ParquetWriter,
  fechar gap -72% medido em 1.4.5 + 1.8) — **stories já criada via COUNCIL-10**
- **Real baselines** (Story 1.8-followup — humano + Pyro pós smoke real;
  baselines `v1.0.0-real` substituem `v1.1.0-mock`) — **encadeada com
  1.7b-followup**
- **Schema migration framework** (finding H16 PLAN_REVIEW — bumpa
  `schema_version` sem re-baixar tudo; migration scripts versionados;
  rollback documentado) — **Story 2.3 nova**
- **Observabilidade ADR-013 implementada** (Prometheus exporter V2:
  counters `dll_drops_total`, `ingest_queue_depth`, `write_queue_depth`,
  histograms latência por chunk, gauges RSS/CPU; expostos via `/metrics`
  HTTP endpoint) — **Story 2.4 nova**
- **Calendário B3 integrado com `holidays.dat` Nelogica** (substituir
  tabela hardcoded 2025-2026 de Story 2.1 `validation/calendar_b3.py`;
  finding F-S-1 do Sol audit 2.1) — **Story 2.5 nova**
- **Retry inteligente** (categorização de erros NL_*; retry policy por
  categoria; circuit breaker para timeouts repetidos)
- **Hot path tuning** (eliminar/mover structlog do hot path — finding H22;
  HOT_PATH_RULES.md aplicado per R21)
- **Storage perf tuning** (row_group_size, compression matrix Snappy/ZSTD
  final, cache PRAGMAs ajustadas — finding M6)
- **Logging strategy ADR-010 implementada** (correlation_id global,
  redaction de secrets, formato estruturado JSON)
- **Test strategy ADR-014 formalizada** (mock DLL fixture compartilhada,
  fake clock, layered fixtures, Hypothesis property tests core suite)
- **Exception hierarchy ADR-011 implementada** (internals → public_api →
  UI propaga errors com contexto)

## Escopo OUT

- UI PySide6 (Epic 3)
- Multi-asset / multi-symbol (Epic 4)
- Auto-updater (Epic 4)
- Code signing (Epic 4)
- Release V1 packaging (Epic 4)
- ProfitDLL streaming live (Epic 5+)

**NOTA — Reorganização pós-COUNCIL-10:**

- **Story 2.1 (validators)** — **JÁ MOVIDA para Epic 1** conforme finding C4 (Done em 2026-05-04).
- **Story 2.2 (perf-write-optimization)** — **JÁ CRIADA** via COUNCIL-10 (Status `Ready`, Pyro owner).
- **Stories 1.7b-followup + 1.8-followup** — **alocadas a Epic 2** (são debt rastreado por WAIVERS de Epic 1; fecham smoke real + baselines reais; bloqueiam release V1).

---

## Stories alocadas a Epic 2

| ID | Título | Owner | Estimativa | Status atual | Notas |
|----|--------|-------|------------|--------------|-------|
| 1.7b-followup | Real smoke MVP gate (humano + ProfitDLL real) | humano + qa | 1h | Pending Human | Bloqueia release V1; encadeia 1.8-followup |
| 1.8-followup | Real baselines (humano roda smoke + Pyro re-baseline v1.0.0-real) | humano + perf-engineer | 2h | Pending Human | Depends 1.7b-followup; bloqueia merge final 2.2 |
| 2.1 | Data integrity validators como código (subpacote validation/) | storage-engineer + qa | 2d | **Done (2026-05-04)** | Movida para Epic 1 conforme finding C4 — registrada aqui para rastreabilidade |
| **2.2** | **Perf Write Optimization (vectorize ParquetWriter)** | **perf-engineer** | **3d** | **Ready (2026-05-04)** | **Criada via COUNCIL-10; Aria APPROVED design; Morgan validated 10/10** |
| 2.3 | Schema Migration Framework (finding H16) | storage-engineer + dev | 3d | Draft (a criar) | Bumpa `schema_version` v1.0.0 → v1.0.1 sem re-baixar; scripts versionados; rollback |
| 2.4 | Observabilidade runtime (ADR-013 Prometheus exporter V2) | dev + architect | 2d | Draft (a criar) | `/metrics` HTTP endpoint; `dll_drops_total` + queue depths + latência |
| 2.5 | Calendar B3 integração com holidays.dat Nelogica | storage-engineer + dev | 2d | Draft (a criar) | Substitui tabela hardcoded Story 2.1; finding F-S-1 Sol; COUNCIL-04 caveat |
| 2.6 | Retry inteligente + circuit breaker | dev | 2d | Draft (existente) | Categorização NL_*; retry policy por categoria |
| 2.7 | Hot path tuning (HOT_PATH_RULES.md aplicado) | perf-engineer + dev | 2d | Draft (existente) | Remove structlog hot path; finding H22 |
| 2.8 | Storage perf tuning (row_group, compression final) | storage-engineer + perf-engineer | 2d | Draft (existente) | Finding M6; cache PRAGMAs |
| 2.9 | Logging strategy ADR-010 implementada | dev + architect | 1d | Draft (existente) | correlation_id global; redaction |
| 2.10 | Test strategy ADR-014 (fixtures + Hypothesis suite) | qa + dev | 2d | Draft (existente) | Extrai mock DLL fixture (F-S-4 Sol audit 1.8); Hypothesis core suite |
| 2.11 | Exception hierarchy ADR-011 implementada | dev + architect | 2d | Draft (existente) | Internals → public_api → UI propaga errors |

**Total:** ~24-26 dias estimados (preliminar — Morgan refinará Wave-by-Wave).

**Stories prioritárias P1 (bloqueiam release V1):**
- 1.7b-followup → 1.8-followup (humano-dependent, paralelo com Pyro impl 2.2)
- 2.2 (perf-write-optimization, fecha gap -72%)
- 2.4 (observabilidade) — exigida por release readiness

**Stories P2 (qualidade incremental):**
- 2.3, 2.5, 2.6, 2.7, 2.8, 2.10, 2.11

**Stories P3 (cosméticas):**
- 2.9 (logging structured) — útil mas não bloqueante

---

## Dependências entre stories

```
1.7b ✅ (Done w/ WAIVER)
   └─ 1.7b-followup (humano)
         └─ 1.8-followup (humano + Pyro pós-smoke)
                  └─ 2.2 merge final (re-baseline contra v1.0.0-real)

2.2 (Pyro vectorize) — pode iniciar com v1.1.0-mock como baseline
   └─ paralelo com 1.7b-followup / 1.8-followup
   └─ merge final BLOCKED por 1.8-followup PASS

2.3 (Schema migration framework)
   └─ depends_on: [1.4 ✅, 1.5 ✅]
   └─ não bloqueia 2.2

2.4 (Observabilidade ADR-013)
   └─ depends_on: [1.7a ✅] (orchestrator emite eventos)
   └─ paralelo com 2.2 / 2.3

2.5 (Calendar B3 holidays.dat)
   └─ depends_on: [2.1 ✅] (substitui calendar_b3.py)
   └─ paralelo com 2.2 / 2.3 / 2.4

2.6 / 2.7 / 2.8 / 2.9 / 2.10 / 2.11
   └─ paralelos entre si após 2.2 / 2.3 / 2.4 estabilizarem
```

---

## Gates do Epic 2

### Gate G-Quality (intermediário — após cada Wave)

- ✅ Quinn `*qa-gate 2.X` PASS em cada story Done (sem CRITICAL/HIGH).
- ✅ Pyro `*regression-check` clean (sem regressão > regression budget vs
  `BASELINES.md` v1.0.0-real ou v1.1.0-mock se followup ainda pendente).
- ✅ Sol audit APPROVED para stories que tocam `storage/` (2.3, 2.5, 2.8).
- ✅ Aria audit APPROVED para stories que tocam fronteira/ADR (2.4
  ADR-013, 2.6 retry policy boundary, 2.9 ADR-010, 2.11 ADR-011).

### Gate G-Quality-Final (close de Epic 2)

- ✅ **1.7b-followup PASS** (humano rodou smoke real, evidência arquivada).
- ✅ **1.8-followup PASS** (Pyro registrou `BASELINES.md` v1.0.0-real;
  flame graphs entregues).
- ✅ **Story 2.2 PASS** com merge final contra v1.0.0-real (improvement
  >= +400% em `bench_parquet_write` production confirmado contra real).
- ✅ Schema migration framework testado em migração v1.0.0 → v1.0.1 (caso
  real ou simulado).
- ✅ Observabilidade exposta: `curl http://localhost:9091/metrics` retorna
  200 com métricas válidas (`dll_drops_total`, queue depths, latency
  histograms).
- ✅ Calendar B3 lê `holidays.dat` Nelogica em runtime (cobertura para
  2025-2030+); fallback para tabela hardcoded se DLL ausente.
- ✅ Hot path: structlog removido de hot path; CPU profile mostra log < 5%
  do tempo total.
- ✅ Pyro full benchmark suite (todos os 9 + 3 novos = 12 total) rodada
  contra v1.0.0-real; nenhum FAIL não-tracked.

---

## Definition of Done (Epic 2)

- [ ] Todas as stories Done (2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11)
- [ ] 1.7b-followup PASS (humano)
- [ ] 1.8-followup PASS (humano + Pyro)
- [ ] Quinn `*qa-gate 2.X` PASS em cada story
- [ ] Pyro: 0 regressões > regression budget vs `BASELINES.md` v1.0.0-real
- [ ] Sol: schema migration framework operacional (testado v1.0.0 → v1.0.1)
- [ ] Sol: calendar B3 Nelogica integrado (sem hardcoded 2025-2026)
- [ ] Aria: ADRs 010, 011, 013, 014 todos accepted
- [ ] Documentação de ops (como olhar métricas, como triagem de erros, como
  rodar migration)
- [ ] WAIVERS 1.7b + 1.8 marcados como Remediado
- [ ] Epic 1 formalmente fechado (gate close encadeado em 1.7b-followup +
  1.8-followup)
- [ ] Release V1 desbloqueado (@devops pode publicar quando Epic 4 OK)

---

## Riscos identificados

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Story 2.2 vectorização não atinge target +400% improvement | MEDIUM | HIGH | COUNCIL-10 §4 — escalar para Opção C (streaming-append) só se gap residual > 30%; Aria pré-aprovou amendment ADR-002 condicional. Property tests Hypothesis garantem equivalência. |
| Schema migration framework introduz complexidade que pesa Epic 1 retroativamente | LOW | MEDIUM | Sol limita escopo: migration framework opcional para datasets já criados; obrigatório para novos. Default = no-op (preserva 1.0.0). |
| Observabilidade adiciona overhead em hot path | MEDIUM | MEDIUM | Pyro mede ANTES e DEPOIS (Story 2.4 AC obrigatória); budget de overhead < 2% CPU em REGRESSION_BUDGETS.md |
| Retry inteligente pode mascarar bugs reais | MEDIUM | HIGH | Categorização explícita: erros DLL transitórios = retry; erros lógicos = fail fast; logs estruturados separam |
| Calendar B3 holidays.dat formato muda em update Nelogica | LOW | MEDIUM | Story 2.5 mantém fallback hardcoded; parser tolerante a versões; alarme se parse falhar |
| Humano demora para rodar 1.7b/1.8-followup | MEDIUM | HIGH (bloqueia release V1) | Morgan revisa semanalmente em `*plan`; escala para Aria + Sol se demora > 30 dias |
| Story 2.2 merge final fica bloqueada se 1.8-followup demora | MEDIUM | MEDIUM | Aria sugeriu fallback (F-A-3 audit 1.8): WAIVER `2.2-real-baseline-deferred` similar à 1.7b se necessário |

---

## Cronograma estimado

**Sprint 1 (semanas 1-2):**
- Story 2.2 vectorize ParquetWriter (Pyro — 3d)
- Story 2.4 observabilidade ADR-013 (Dex + Aria — 2d)
- Story 2.5 calendar B3 holidays.dat (Sol + Dex — 2d)
- 1.7b-followup quando humano disponível (paralelo)

**Sprint 2 (semanas 3-4):**
- Story 2.3 schema migration framework (Sol + Dex — 3d)
- Story 2.6 retry inteligente (Dex — 2d)
- Story 2.7 hot path tuning (Pyro + Dex — 2d)
- 1.8-followup quando 1.7b-followup PASS (paralelo)
- 2.2 merge final pós 1.8-followup

**Sprint 3 (semanas 5-6):**
- Story 2.8 storage perf tuning (Sol + Pyro — 2d)
- Story 2.9 logging strategy ADR-010 (Dex + Aria — 1d)
- Story 2.10 test strategy ADR-014 (Quinn + Dex — 2d)
- Story 2.11 exception hierarchy ADR-011 (Dex + Aria — 2d)

**Sprint 4 (semana 7):**
- Gate close Epic 2 (G-Quality-Final)
- Documentação ops
- Handoff para Epic 3 (Felix + Uma)

**Total estimado:** 6-8 semanas (com buffer para humano-dependent stories).

---

## Após o Epic

Próximo: **Epic 3 — Desktop UI** (PySide6 shell, telas Download/Catálogo/
Settings, packaging .exe). Bloqueado por:
- Epic 2 G-Quality-Final PASS.
- Foundation production-grade (observability + retry + migration framework).
- Stories Epic 4 dependentes (auto-updater, code signing) podem rodar em
  paralelo a Epic 3 quando Aria desbloquear via ADRs.

---

— Morgan 📋, orquestrando o squad
