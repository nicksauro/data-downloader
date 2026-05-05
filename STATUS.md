# 📊 STATUS — data-downloader

> Resumo executivo do estado do projeto. Atualizado: **2026-05-05** (Orion @aiox-master — pós-1.7g Done + Q17-CLOSED + ADR-022 Accepted)

## 🎯 Estado consolidado

| Epic | Stories | Status |
|------|---------|--------|
| **1 — Foundation** | 18/18 | ✅ Done — 1.7g release-blockers P0 fechados (schema v1.1.0 + queue 2M + queue_dropped counter); 1.7c Deprecated (Q-DRIFT-02 refutado) |
| **2 — Quality & Performance** | 11/12 | ⚠️ Done* — 2.8 (storage perf tuning) Ready for Review aguarda QA gate Quinn |
| **3 — Desktop UI** | 3/N | ✅ Done (3.1 + 3.2 + 3.3) — funcional |
| **4 — Multi-asset & V1.0** | 3/4 + 1 deprecated | ⚠️ ajustada — 4.1 Deprecated (ADR-015 REVOKED, broker single-session inviável); 4.2/4.3/4.4 Done; 4.1-followup Cancelled; 4.2-followup ajustada para serial |

**Mudança crítica 2026-05-05:** Pichau (autoridade ownership) confirmou empiricamente que **licença Nelogica é single-session** (Q17-CLOSED Hipótese B). Multi-process broker arquiteturalmente inviável.

- ✅ **ADR-015 (Multi-Symbol Broker Process)** REVOKED
- ✅ **ADR-022 (Single-Session Sequential Download Policy)** Accepted — `for symbol in symbols: download_chunk(...)` SERIAL em 1 processo único
- ✅ CLI `--parallel N>1` desabilitado com warning + força parallel=1

---

## 🔢 Números

- **~80 commits** no `main` (12 deste push de hoje em github.com/nicksauro/data-downloader)
- **Repo público:** https://github.com/nicksauro/data-downloader
- **~1042 testes** PASS (16/16 callbacks, 27/27 download_primitive, 17/17 schema/telemetry/sentinel + suites)
- **2 testes flake pré-existente** (test_holidays_dat_parser cwd-dependente, isolado PASS)
- **Cobertura ~88%** em camadas críticas (storage, orchestrator, dll)
- **~40 documentos de decisão (COUNCILs)** registrados (incl. COUNCIL-31..40 desta semana)
- **22 ADRs** (incl. ADR-019 schema-as-contract, ADR-020 volume-completeness, ADR-022 single-session policy)
- **Q-DRIFT-01..37** rastreados em `docs/dll/QUIRKS.md`
- **WAIVERs abertos:** 1 (Sintoma A pytest harness — 1.7b — não bloqueia release)

---

## 🚦 O que falta para publicar V1.0.0 oficial

**Trabalho 100% offline pendente (autonomizável):**

1. **Story 2.8 QA gate** (~2h) — storage perf tuning Ready for Review; Quinn 7-checks Phase 4.
2. **STATUS / RELEASE-READINESS** — este documento (concluindo).
3. **QUIRKS.md consolidação → docs/debt/** (~2h) — separar refutadas/históricas.
4. **`orchestrator/broker/*` annotation** — DEAD-CODE ADR-015 REVOKED em headers; remoção em story 2.X-cleanup futura.
5. **Q-DRIFT-18 (WIN vigência B3) probe design** (~2-4h) — bloqueia rollover Epic 2.5+ e 4.2-followup.

**Bloqueado por execução humana + DLL real:**

6. **Story 1.7b-followup** — primeiro gate end-to-end real com ProfitDLL (~45 min). Validação pós-1.7g em produção.
7. **Story 1.8-followup** — Pyro re-baseline `v1.0.0-real` (vs `v1.1.0-mock`) (~30 min).
8. **Story 4.2-followup** — smoke real WIN/PETR4 SERIAL single-process (~30 min após item 6).
9. **Story 4.4-followup** — VM smoke + EV cert signing + tufup + container CI (~3-5d lead time vendor).
10. **Build PyInstaller** (Gage @devops) — ~5 min.
11. **GitHub Release v1.0.0 draft** (Gage @devops) — ~2 min.

**Caminho crítico para ship v1.0.0:**

`item 6 (smoke real 1.7b-followup) → item 7 (baselines) → item 10 (build) → item 11 (release)` — total ~1h30 corrido. Pré-requisitos: `.env` com `PROFITDLL_KEY/USER/PASS` válidos + máquina Windows. **ProfitChart NÃO precisa estar aberto** (Q-DRIFT-02 refutado 2026-05-05).

---

## 🗝️ Histórico de bloqueios resolvidos esta semana

| Bloqueio | Status | Resolução |
|----------|--------|-----------|
| Q-DRIFT-02 (handshake travado) | ⚠️ refuted (root cause = 11/12/33/34/35) | probe `probe_init.py` 2026-05-05 conectou 1.6s — handshake autônomo, ProfitChart não é pré-requisito |
| Q-DRIFT-33 (TranslateTrade.argtypes em minimal_handshake) | 🐛 HOTFIX-APPLIED | postfix-35 commit `0f6c2ea` |
| Q-DRIFT-34 (sentinel struct wYear≤1900) | 🐛 HOTFIX-APPLIED | guard `_process_trade` + 3 testes unit (Story 1.7g) |
| Q-DRIFT-35 (NL_NOT_FOUND comment + signatures) | 🐛 HOTFIX-APPLIED | wrapper.py L731-748 + GetAgentName argtypes (Story 1.7g) |
| Q-DRIFT-36 (silent column drop schema) | 🐛 HOTFIX-APPLIED | schema v1.1.0 + writer fail-loudly + SchemaIntegrityError (Story 1.7g) |
| Q-DRIFT-37 (volume gap 71% silent) | 🐛 HOTFIX-APPLIED | TRADE_QUEUE_MAXSIZE 100k→2M + queue_dropped counter (Story 1.7g) |
| Q17-OPEN (multi-process licensing) | ✅ Q17-CLOSED Hipótese B | Pichau confirmou single-session 2026-05-05; ADR-022 substitui ADR-015 |

---

## 📁 Como usar agora (sem release oficial pública)

```powershell
# 1. Verificar .env com PROFITDLL_KEY/USER/PASS
# 2. Baixar 1 símbolo (ProfitChart NÃO precisa estar aberto — Q-DRIFT-02 refutado):
python -m data_downloader.cli download --symbol WDOFUT --start 2026-04-28 --end 2026-05-02

# 4. Para múltiplos símbolos: invocar 1 vez por símbolo (ADR-022 — serial):
python -m data_downloader.cli download --symbol WDOFUT --start ... --end ...
python -m data_downloader.cli download --symbol WINH26 --start ... --end ...

# 5. Em projetos downstream:
from data_downloader.public_api import download, read, vigent_contract
contract = vigent_contract('WDO', date(2026, 4, 28))
table = read(contract, datetime(2026, 4, 28), datetime(2026, 5, 2))
```

API V1.0 **estável** — pinar como `data_downloader>=1.0.0,<2.0.0`.

⚠️ Note: `--parallel N>1` foi desabilitado por ADR-022 (licença single-session). CLI emite warning e força parallel=1.

---

## 🚀 Modo autônomo (atual)

Trabalho offline restante **autônomo viável**:
- Story 2.8 QA gate (Quinn) — em andamento
- QUIRKS.md consolidação → docs/debt/ (Aria) — em andamento
- Broker dead-code annotation (Dex/Orion)
- Q-DRIFT-18 probe design (Aria + Nelo)

**Quando você quiser destravar ship v1.0.0:**
- Rodar smoke real 1.7b-followup com `.env` válido (item 6 acima — ~45 min, ProfitChart não precisa estar aberto)

---

## 📚 Onde ler mais

- **Visão geral:** `README.md`
- **Princípios:** `docs/MANIFEST.md` (R1..R21)
- **Quem decide:** `docs/ROLES.md`
- **Arquitetura:** `docs/ARCHITECTURE.md`
- **ADRs:** `docs/adr/` (22 ADRs incl. ADR-022 single-session policy)
- **Stories:** `docs/stories/` (~38 stories)
- **Decisões:** `docs/decisions/` (~40 COUNCILs)
- **Quirks/Drifts:** `docs/dll/QUIRKS.md` (vivo) + `docs/debt/QUIRKS_*` (histórico — em consolidação)
- **WAIVERs abertos:** `docs/qa/WAIVERS/` (1 ativo: Sintoma A pytest)
- **Uso público:** `docs/public_api/USAGE.md`
- **Instalação:** `docs/release/INSTALL.md`
