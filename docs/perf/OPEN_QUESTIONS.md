# OPEN_QUESTIONS.md — Perguntas abertas de Pyro para o squad

**Owner:** Pyro (perf-engineer)
**Última atualização:** 2026-05-03 (Story 1.4.5 inicial)
**Política:** cada pergunta tem dono, prazo informal, e bloqueia bench/decisão específica.

---

## Q1 — ProfitDLL: bloqueia ou drop quando ConnectorThread está travada? [CRÍTICA]

**Para:** 🗝️ Nelo (profitdll-specialist)
**Bloqueia:** finalização de `bench_callback_to_disk` (cenário writer_pause=2000ms)
**Origem:** finding **H4** do `PLAN_REVIEW_2026-05-03.md`

### Contexto

`dll_queue=10000` representa apenas ~100ms de buffer @ 100k trades/s. Em condições reais no Windows:
- Garbage collection pause: 50-200ms.
- Page fault em swap: 100-500ms.
- Windows Defender real-time scan em arquivo grande: 500ms-3s.
- DLL load por outro processo: 100-500ms.

Quando o IngestorThread ou WriterThread Python pausam por esses motivos, a fila de callback DLL pode encher.

### Pergunta

Quando a callback Python (`SetTradeCallback`) NÃO retorna (thread travada com fila cheia em `put_nowait`), a ProfitDLL:

(A) **Bloqueia** o ConnectorThread interno aguardando callback retornar (back-pressure end-to-end até market data feed)?

(B) **Descarta** trades silenciosamente (drop-on-block, sem aviso)?

(C) **Buffereia internamente** até limite X, depois drop?

(D) **Outro comportamento** (qual)?

### Por que importa

- (A) → arquitetura segura: queue Python pode ser pequena, sem perder trades.
- (B) → CRÍTICO: precisamos `dll_queue` muito maior + métrica `dll_drops_total` exposta + estratégia de retry/recovery.
- (C) → híbrido: precisamos saber X.
- (D) → re-design.

### O que Nelo precisa entregar

1. Resposta em texto (referência a doc Nelogica se houver).
2. Se houver doc oficial, link.
3. Se NÃO houver doc, experimento empírico: forçar callback Python travada, medir comportamento.

### Status: ABERTA

---

## Q2 — Confirmar dedup key revisada com `sequence_within_ns`

**Para:** 💾 Sol (storage-engineer)
**Bloqueia:** implementação de `bench_dedup` (variante `fallback_composite`)
**Origem:** finding **H2** do plan review

### Contexto

Plano original usa `hash(price, qty)` como fallback quando `trade_id` é NULL. Sol detectou que isso é insuficiente (múltiplos trades legítimos com mesmo preço+qty no mesmo segundo são comuns na abertura).

Proposta Sol: incluir `sequence_within_ns` (contador 0-N para trades partilhando timestamp_ns) na chave.

### Pergunta

1. Confirmar dedup key final V1: `(symbol, timestamp_ns, sequence_within_ns, price, quantity)` quando `trade_id` é NULL?
2. Como `sequence_within_ns` é populado? Pelo wrapper DLL (Nelo Story 1.3) ou pelo writer (Sol Story 1.4)?
3. Schema final em SCHEMA.md (Sol Story 0.0) inclui esse campo?

### Status: ABERTA — depende de Sol terminar Story 0.0

---

## Q3 — ADR-013: qual transporte para métricas?

**Para:** 🏛️ Aria (architect)
**Bloqueia:** implementação real de `bench_log_overhead` (escolha de transporte muda CPU%) + HOT_PATH_RULES.md (R21.4 cita "transporte definido em ADR-013")
**Origem:** finding **H22** + ADR-013 listado em plan review §4

### Contexto

R21.4 (HOT_PATH_RULES.md) substitui logs per-trade por métricas agregadas (counters, gauges, histograms). Mas precisamos decidir transporte:

| Opção | Prós | Contras |
|-------|------|---------|
| **stdout JSON** (structlog) | simples, zero deps | sem agregação nativa; consumer precisa parsear |
| **prometheus_client** (HTTP /metrics) | padrão observability; Grafana fácil | deps + porta HTTP exposta; usuário final pode estranhar |
| **OpenTelemetry SDK** | futureproof; multi-backend | overhead maior; deps pesadas |
| **Arquivo .jsonl rotativo** | sem rede; auditável | sem dashboard out-of-the-box |

### Pergunta

Aria, qual transporte para V1? Considerar:
- App é desktop (PySide6), usuário final pode não ter Grafana.
- Mas devs/QA precisam observar perf em homologação.
- Trade-off complexidade vs observabilidade.

### Recomendação Pyro (sujeita a Aria)

**V1:** stdout JSON via structlog + métricas serializadas como eventos (`event="metric"`, `name=...`, `value=...`). Consumer simples (jq + sqlite-utils) basta para análise local.

**V2 (Epic 4):** adicionar prometheus_client opcional (flag `--enable-prometheus`).

### Status: ABERTA

---

## Q4 — Bench rodam em CI?

**Para:** 📋 Morgan (PM) + ⚙️ Gage (devops)
**Bloqueia:** `REGRESSION_BUDGETS.md` final (CI integration); decide se regression-check é automático ou manual
**Origem:** Pyro (Story 1.4.5)

### Contexto

Benchmarks são caros (10M trades, multi-process, etc.). Rodar em CI:
- **Custo:** GitHub Actions Windows runners são lentos (2 cores tipicamente) e caros vs Linux.
- **Fidelidade:** runner CI tem variabilidade alta (não-dedicated hardware) → ruído > sinal de regressão.
- **Vantagem:** automação real; PR não merge se regredir.

Alternativa: bench local + pre-push hook + dashboard manual em PR review.

### Pergunta

1. Bench rodam em CI? Se sim, quais (todos? subset rápido)?
2. Se sim, runner: GitHub-hosted Windows ou self-hosted Windows?
3. Se NÃO em CI: política para garantir que bench rodaram antes de merge?
   - Pre-push hook obrigatório?
   - Label `perf-regression-checked` aplicada manualmente?
   - Honor system?

### Recomendação Pyro

**V1:** subset rápido em CI (bench que rodam < 30s: `bench_dedup`, `bench_boot_cleanup`, `bench_log_overhead`). Bench longos (`bench_chunking`, `bench_multi_symbol`) ficam manuais com label obrigatório em PR.

**V2:** self-hosted Windows runner para suite completa em PR (depende de orçamento Gage).

### Status: ABERTA — depende de decisão de orçamento e infra

---

## Como contribuir

Outros agentes podem adicionar perguntas pendentes que afetem performance:
1. Edita este arquivo na seção "Q-N — título".
2. Define dono.
3. Marca origem (finding ID, story, ADR).
4. Adiciona ao final.

Pyro audita semanalmente e fecha perguntas resolvidas (move para `OPEN_QUESTIONS_RESOLVED.md` futuro).

— Pyro ⚡
