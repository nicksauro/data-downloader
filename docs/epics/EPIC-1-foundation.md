# EPIC 1 — Foundation (MVP CLI)

**Status:** ready
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03
**Target:** baixar 30 dias de WDO contrato vigente via CLI, idempotente, com integridade auditável.

---

## Objetivo

Construir a fundação inteira do data-downloader até o ponto em que **uma CLI baixa 30 dias de WDOJ26 sem intervenção manual, e re-rodar é no-op (idempotente)**. Foundation precisa estar perfeita porque será carregada por todos os projetos futuros (R1).

## Escopo IN

- Scaffolding do repositório Python 3.12.
- Wrapper ctypes da ProfitDLL (init/finalize + state + history callbacks).
- Primitive de download (1 símbolo / 1 chunk).
- Storage layer Parquet + DuckDB.
- Catálogo SQLite (downloads, partitions, gaps, contracts).
- Calendário de contratos vigentes WDO (Story 1.6).
- Orchestrator com chunking, retry, resume.
- CLI mínima (typer) com comando `download`.
- Smoke test E2E real contra DLL.

## Escopo OUT

- UI PySide6 (Epic 3).
- Multi-symbol em paralelo (Epic 4).
- WIN, equities (Epic 4).
- Public API completa (Epic 4 — versão mínima entra aqui).
- Empacotamento .exe (Epic 3).

## Stories planejadas

**ATUALIZADO 2026-05-03 conforme Plan Review** (12 stories total, era 7).

| ID | Título | Owner | Estimativa | Dep |
|----|--------|-------|------------|-----|
| 0.0 | Sol cria SCHEMA + CONTRACTS + INTEGRITY docs | 💾 Sol | 1d | — |
| 0.1 | Environment Bootstrap (git init + branch protection + bootstrap-dll.ps1) | ⚙️ Gage | 0.5d | ADR-008 |
| 0.2 | Pre-commit Framework (.pre-commit-config.yaml versionado) | ⚙️ Gage | 0.5d | 0.1 |
| 0.3 | UX Foundation (PRINCIPLES + CLI_PATTERNS + MICROCOPY_CATALOG + THEME + FLOWS + WIREFRAMES placeholder) | 🎨 Uma | 1d | — |
| 0.4 | CodeRabbit adoption decision (paralelo, não bloqueia) | ⚙️ Gage + 🧪 Quinn | 0.5d | — |
| 1.1 | Scaffolding (repo, pyproject, lint, pytest) | 💻 Dex | 1d | 0.0, 0.1, 0.2 |
| 1.2 | DLL wrapper: init/finalize + state callback | 💻 Dex (audit Nelo) | 2d | 1.1 |
| 1.3 | History download primitive: 1 símbolo / 1 chunk | 💻 Dex (audit Nelo) | 2d | 0.0, 1.2 |
| 1.4 | Storage layer: writer Parquet + leitor DuckDB | 💻 Dex (audit Sol) | 2d | 0.0, 1.1 |
| 1.4.5 | Synthetic perf baselines (mock DLL fixtures) | ⚡ Pyro | 1d | 1.4 |
| 1.5 | Catálogo SQLite + checkpoint/resume | 💻 Dex (audit Sol) | 2d | 1.4 |
| 1.5b | read_continuous + queries DuckDB canônicas + property tests rollover | 💻 Dex + 💾 Sol | 1d | 1.5, 1.6 |
| 1.6 | Contract calendar (WDO map vigente) | 💻 Dex (audit Sol+Nelo) | 1d | 1.2, 1.3, 1.5 |
| 1.7a | Orchestrator core (chunker + retry + state machine) | 💻 Dex | 2d | 1.3, 1.5, 1.6 |
| 1.7b | CLI typer + public_api mínima + smoke MVP gate | 💻 Dex (review Uma) | 2d | 1.7a, 0.3 |
| 1.8 | Pyro baselines reais + regression budgets | ⚡ Pyro | 1d | 1.7b |
| 2.1 | Data integrity validators como código (movida de Epic 2 — finding C4) | 💾 Sol + 🧪 Quinn | 2d | 1.7b |

**Total:** ~20 dias estimados (era 13d; +7d honestos vs 30%+ surpresa). Ordem de execução com paralelismo: ver `docs/ROADMAP.md`.

## Gates do Epic

### Gate G-Foundation (Story 1.7b — smoke MVP)
**Critério:** rodar via terminal:
```
python -m data_downloader.cli download --symbol WDOJ26 --start 2026-03-01 --end 2026-03-30
```
e ter:
- ✅ Download conclui sem intervenção (timeout 1800s aceitável durante 99% reconnect quirk)
- ✅ Pelo menos 1 arquivo Parquet em `data/history/F/WDOJ26/2026/03.parquet`
- ✅ `catalog.db` registra a partição com row_count > 0
- ✅ Re-rodar mesmo comando = no-op (mesma partição, sem duplicação) — validação Sol `*integrity-check` (Story 2.1)
- ✅ DuckDB lê todos os trades sem erro
- ✅ Quinn `*qa-gate 1.7b` retorna PASS
- ✅ Hash Parquet + log smoke salvos em `docs/qa/SMOKE_EVIDENCE.md` (eliminação honor system)

### Gate G-Foundation-Close (Stories 1.8 + 2.1)
- ✅ Pyro baseline real registrado em `docs/perf/BASELINES.md` (Story 1.8)
- ✅ Sol + Quinn validators como código (Story 2.1) — `integrity check` + `validate` retornam clean

## Definition of Done (Epic)

- [ ] Todas as 12 stories em status `Done` (0.0..0.4 + 1.1..1.6 + 1.4.5 + 1.5b + 1.7a + 1.7b + 1.8 + 2.1)
- [ ] Quinn PASS em cada uma
- [ ] Pyro: `bench_callback_to_disk` p99 < 100ms registrado em BASELINES.md (Story 1.8)
- [ ] Pyro: `bench_parquet_write` >= 100k trades/s registrado (Story 1.4.5 synthetic + 1.8 real)
- [ ] Sol: `*integrity-check` (CLI Story 2.1) clean no dataset gerado pelo gate
- [ ] Aria: nenhum ADR `proposed` em escopo do epic (ADRs 007a, 008..017 todos accepted)
- [ ] CLI documentada em README.md
- [ ] **Smoke test rodável em VM Windows limpa** OU container — apenas com README + .env + ProfitDLL.dll, sem instruções extras (reformulado de "reproduzível por outro contribuidor" — squad é de agentes, não humanos)

## Riscos identificados

| Risco | Mitigação |
|-------|-----------|
| DLL exige licença Nelogica que não temos no momento do gate | Configurar `.env.example` + instruções; gate roda em máquina do usuário |
| `GetHistoryTrades` retornar 0 trades para WDOJ26 (quirk) | Sol valida contrato vigente via probe (Story 1.6 ANTES de 1.7a/b) |
| Throughput Parquet abaixo do alvo | Pyro tuna row_group_size em Story 2.2 (Epic 2) — não bloqueia 1.7b |
| Crash deixa Parquet `.tmp` órfão | Story 1.5 implementa cleanup ao boot |
| **Schema drift entre 1.4 ↔ 1.7** (campo novo aparece em uma sem outra) | Story 0.0 fixa SCHEMA.md como fonte única; Quinn rastreia AC vs SCHEMA.md |
| **MARKET_WAITING quirk Q-AMB-01** (state code ambíguo entre WAITING=2 e CONNECTED=4) | Story 1.2 AC5 reescrita por Nelo; fixture session-scoped evita re-init issues |
| **Sample data em feriado / fim de semana** (smoke pode não ter trades) | Story 1.7b smoke fixa data conhecida (mar/26 dia útil); Story 2.1 integrity check com B3 holiday calendar |

## Após o Epic

Próximo: **Epic 2 — Quality & Performance** (validador integridade, baselines completos, retry inteligente). Depois: **Epic 3 — Desktop UI**.
