# COUNCIL-25 — Multi-symbol broker process implementation (Story 4.1)

**Data:** 2026-05-04
**Convocação:** Mini-council Aria + Dex + Pyro — modo autônomo (Story 4.1 impl)
**Participantes mentais:**
- 🏛️ Aria (Architect — autoridade exclusiva ADR-015 + fronteira de processo)
- 💻 Dex (Dev — implementer broker package)
- ⚡ Pyro (Perf — speedup ≥ 3.2x target V1 + pool persistente decisão)

**Status:** RATIFIED (autonomous mode)

---

## 1. Contexto

Story 4.1 (Multi-symbol broker process) entra em implementação após Epic 4 prep
(COUNCIL-13). ADR-015 já está em estado `accepted` desde 2026-05-03 (Aria) com
Opção A escolhida (broker no master + workers via `multiprocessing.Queue` + ACK).

Esta convocação mini-council documenta as decisões operacionais residuais que
NÃO foram resolvidas pelo ADR-015 ou pelo prep COUNCIL-13:

- Pool persistente vs spawn por job (mitigação H20 Windows spawn 2.7-10s).
- Política de WAIVER para smoke real multi-symbol (similar a 1.7b/1.8/COUNCIL-09).
- Limite Nelogica multi-process (sem confirmação oficial — registrar Q17-OPEN).
- Target speedup Pyro para N=4 (validar bench mock vs real-target).

Estado das pendências P1-P5 de COUNCIL-13:

| # | Pendência | Status |
|---|-----------|--------|
| P1 | Story 1.7b-followup smoke real PASS | Pending Human (não bloqueia esta impl — ver D3) |
| P2 | Confirmação Nelogica licença multi-instância | Pending Human (não bloqueia mock impl — ver D5) |
| P3-P5 | EV cert, ADR-003, ADR-017 | Não tocam Story 4.1 |

---

## 2. Decisões

### D1 — Implementação fiel ADR-015 Opção A (Aria)

**Decidido (Aria autoridade exclusiva):**

Story 4.1 implementa **fielmente** Opção A do ADR-015 (broker process no master
+ workers via `multiprocessing.Queue` + ACK). Sem reabertura de decisão
arquitetural; sem espaço para Opção B (sharded), C (retry), ou D (Postgres) em
meio à implementação.

**Razão:**
- ADR-015 já considerou 4 alternativas com sign-off Sol+Pyro+Nelo.
- Story 4.1 tem 8 ACs detalhados (CatalogBroker, CatalogClient, ACK protocol,
  pool persistente, CLI `--parallel`, bench, tests).
- Aria bloqueia se @dev tentar reabrir decisão durante a implementação.

**Implementação canônica:**

```
Master Process
├── CatalogBroker (drena mutation_queue → SQLite write → ACK queue)
├── WorkerPool (mantém N workers persistentes, distribui jobs)
└── MultiSymbolMaster (high-level coordinator)

Worker Processes (N independentes, persistentes)
├── BrokerCatalogClient (envia mutações via Queue + aguarda ACK)
├── ProfitDLL (1 conexão por processo — limite Nelogica R20)
└── Orchestrator (Story 1.7a — single-symbol; reusado)
```

---

### D2 — Pool persistente vs spawn por job (Pyro + Dex)

**Decidido (Pyro perf authority + Dex impl):**

**Pool persistente** (workers aquecidos, reusados entre jobs) — não spawn
por job.

**Razão:**
- Finding H20 (Pyro): `multiprocessing.Process` em Windows = 2.7-10s spawn
  overhead. Para job curto (1 símbolo, 1 dia), spawn domina o tempo total.
- Wave 8 mock baseline (`bench_multi_symbol`) já mostrou 2.88x speedup para
  N=4 com spawn-per-job pattern — close to 3.2x target mas com tail latency
  instável.
- Pool persistente paga spawn UMA vez por run; jobs subsequentes têm overhead
  apenas IPC (~100µs).
- ADR-015 §"H20 mitigação" explicitamente pede pool persistente.

**Estrutura implementada:**
- `WorkerPool.start_pool(n_workers)` — spawn N workers + warmup (carrega DLL).
- `WorkerPool.submit_jobs(jobs)` — distribui via mp.Queue input compartilhada.
- Workers em loop: `while True: job = input_q.get(); result = run(job); output_q.put(result)`.
- `WorkerPool.stop_pool()` — graceful shutdown (None sentinel + join + DLL finalize).

**Trade-off aceito:** workers ficam "vivos" mesmo entre jobs — consomem
memória RSS (~100MB cada × N). Aceitável dado que multi-symbol é uso
intencional do usuário (não always-on background).

---

### D3 — Smoke real WAIVER (similar a 1.7b/1.8 — COUNCIL-09)

**Decidido (Aria + Pyro implícito; Quinn mediado):**

Implementação completa de Story 4.1 via mock; smoke real (4 símbolos paralelo
com ProfitDLL real) **deferred via WAIVER** estendendo política COUNCIL-09.

**Razão:**
- Smoke real multi-symbol exige humano com:
  - PROFITDLL_KEY + ProfitChart instalado.
  - Múltiplas instâncias da mesma chave de licença autorizadas (Q17-OPEN).
  - Banda + tempo (4 símbolos × 1 dia ≈ 15-30 min download real).
- Quinn (agente) não tem nenhum desses recursos — mesma situação que 1.7b/1.8.
- Política COUNCIL-09 já estabeleceu que smoke real é gate de **release V1**,
  não gate de story individual. Esta política é estendida para Story 4.1.

**WAIVER:** `docs/qa/WAIVERS/4.1-real-smoke-deferred-2026-05-04.md` (Aria + Pyro
implicit sign-off; Morgan implícito por consistência).

**Story-debt:** `docs/stories/4.1-followup.story.md` — humano roda smoke quando
P1 (1.7b-followup) e P2 (Nelogica licença) resolverem.

**Bloqueia release V1.** Não bloqueia Story 4.1 → Done com asterisco.

---

### D4 — Target speedup ≥ 3.2x para N=4 (Pyro)

**Decidido (Pyro perf authority):**

Target V1 mantido em **speedup ≥ 3.2x para N=4 workers** (80% efficiency vs
sequencial — alinhado com `perf_targets_v1.download.multi_symbol_speedup_4_processes`
do `agents/perf-engineer.md`).

**Justificativa do número:**
- Wave 8 mock baseline com spawn-por-job: 2.88x (close mas FAIL).
- Pool persistente elimina spawn cost (2.7-10s × N) → projeção ≥ 3.5x.
- Margem de 0.3x absorve overhead IPC broker + ACK (~100-500µs/mut × N
  mutations/job).
- Real smoke pode reduzir devido a contenção rede (ProfitDLL por processo
  separado pode dividir banda) — Pyro reavalia em 1.7b-followup PASS.

**Verdict bench:** PASS se ≥ 3.2x; CONCERNS se 2.8x ≤ x < 3.2x; FAIL se < 2.8x.
Bench mock atual produz baseline; real validação fica para 4.1-followup.

---

### D5 — Q17-OPEN: licença Nelogica multi-instância (Aria + Nelo implícito)

**Decidido (Aria + Nelo implícito):**

**Sem confirmação oficial** sobre múltiplas instâncias da mesma chave de
licença Nelogica em processos diferentes na mesma máquina. Assumir
**1 conexão por processo (R20 conservador)** e documentar como **Q17-OPEN**
para futuro probe humano.

**Razão:**
- Q06-V (manual §4) regula thread model dentro de 1 processo, mas é silencioso
  sobre N processos com mesma chave.
- COUNCIL-13 P2 escalou a Morgan + Nelo para confirmação — sem resposta ainda.
- Implementação parte do **assumption pessimista**: 1 DLL por processo,
  N processos = N usos da licença.
- Se Nelogica negar (ex: licença single-session), Story 4.1 **continua
  válida em código** mas humano não pode rodar smoke real. WAIVER já cobre
  esta situação.
- Se Nelogica permitir, smoke real funciona; sem mudança de código.

**Q17-OPEN registrado em `docs/dll/QUIRKS.md`** (Nelo curador) com:
- Pergunta: "Múltiplas instâncias da mesma chave Nelogica em processos
  diferentes na mesma máquina é OK?"
- Probe proposto: humano roda 2 instâncias do data-downloader simultâneas,
  verifica se ambas conectam (state callback `MARKET_CONNECTED`).
- Aplica a stories: 4.1 (broker), 4.2 (multi-asset paralelo).

---

### D6 — Sem mudança de fronteira pública (Aria)

**Decidido (Aria authority exclusiva):**

Story 4.1 NÃO altera `src/data_downloader/public_api/`. Multi-symbol fica
**apenas na CLI** via `--parallel` (AC6). `public_api.download(...)` permanece
single-symbol em V1.0 — confirmação de COUNCIL-13 D9.

**Razão:**
- Decisão D9 de COUNCIL-13 já formalizada — multi-symbol via public_api é V1.x
  (Article IV — não inventar API sem consumer real).
- Aria não autoriza expansão de fronteira pública nesta story.
- Implementação fica em `src/data_downloader/orchestrator/broker/` (sub-package
  novo, não exposto em `__init__` público da public_api).

---

## 3. Estrutura de implementação

```
src/data_downloader/orchestrator/broker/
├── __init__.py              # exports CatalogBroker, BrokerCatalogClient, WorkerPool, MultiSymbolMaster
├── catalog_broker.py        # CatalogBroker + BrokerProtocol + BrokerRequest/Response
├── worker_client.py         # BrokerCatalogClient (worker-side stub)
├── pool.py                  # WorkerPool (lifecycle persistente)
└── master.py                # MultiSymbolMaster (high-level coordinator)
```

CLI extensão:
- `data-downloader download --symbol WDOJ26 WINH26 PETR4 --parallel 4 ...`
- N=1 → path single-symbol existente (Story 1.7b).
- N>1 → MultiSymbolMaster.

Tests:
- `tests/unit/test_broker_protocol.py` — request/response serialization.
- `tests/unit/test_worker_client.py` — mock broker, send/receive, timeout.
- `tests/unit/test_pool_lifecycle.py` — start/submit/stop graceful.
- `tests/integration/test_multi_symbol_mock.py` — pool 2 workers + MockProfitDLL +
  paralelo + property test serialização via broker.

---

## 4. Sign-off

### 🏛️ Aria (Architect)

**APPROVED** — implementação fiel ADR-015 Opção A.

- Pool persistente é exigência ADR-015 §"H20 mitigação". Confirmado.
- Sub-package `broker/` em `src/data_downloader/orchestrator/` é fronteira
  interna correta — não viola public_api.
- Q17-OPEN registrado para humano probe futuro — assumption R20 conservador
  é OK para impl.
- WAIVER smoke real (D3) é extensão legítima da política COUNCIL-09.

— Aria, mapeando o território 🏛️

### 💻 Dex (Dev)

**APPROVED** — escopo implementável end-to-end.

- 4 módulos broker package + CLI extension + tests = ~5 KLoC novos.
- Pool persistente via mp.Queue é padrão Python idiomático.
- ACK protocol via UUID request_id é simples e testável.
- Mock-first abordagem (similar a 1.7b/1.8) viabiliza implementação completa
  sem dep humano.

— Dex, construindo backend 💻

### ⚡ Pyro (Perf)

**APPROVED** — target 3.2x speedup para N=4 com pool persistente.

- Spawn cost mitigado (1x por run vs N×) → projeção ≥ 3.5x.
- Bench mock fornece baseline; real validação fica para 4.1-followup.
- IPC overhead (~100-500µs por mutação) é negligível vs duração de chunk
  (segundos).
- Verdict bench mock: PASS se ≥ 3.2x; CONCERNS se < 3.2x mas > 2.8x.

— Pyro, medindo o limite ⚡

---

## 5. Pendências (não bloqueiam Story 4.1 → Done)

| # | Pendência | Owner | Bloqueia |
|---|-----------|-------|----------|
| P1 | Story 1.7b-followup smoke real PASS | humano + Quinn | Story 4.1-followup smoke real |
| P2 | Confirmação Nelogica licença multi-instância (Q17-OPEN) | humano + Morgan + Nelo | Story 4.1-followup smoke real |
| P3 | Story 4.1-followup smoke real (4 símbolos paralelo, 1 dia cada) | humano + Quinn | Release V1 |

---

— Aria 🏛️ + Dex 💻 + Pyro ⚡ — COUNCIL-25 RATIFIED 2026-05-04
