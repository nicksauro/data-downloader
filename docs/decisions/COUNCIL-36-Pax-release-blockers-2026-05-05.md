# COUNCIL-36 — Pax (@po): Release-Blockers — Schema Integrity + Volume Gap

**Persona:** Pax (Product Owner)
**Council:** 36 — pós-COUNCIL-32/35 (mini-council de release readiness)
**Data:** 2026-05-05
**Modo:** Autônomo (decisão sem escalação humana)
**Escopo:** Decidir release-blockers P0 e tocar Story 1.7g
**Stories afetadas:** 1.7d (smoke validado), 1.7b (WAIVER pendente), 1.8 (schema bump deferido)

---

## TL;DR

**RELEASE BLOQUEADO.** Dois problemas P0 não-negociáveis identificados pela ownership/PO:

1. **Silent column drop NÃO PODE OCORRER** — autoridade do dono do produto. Schema parquet v1.0.0 descarta `buy_agent_name`, `sell_agent_name`, `trade_type_name` silenciosamente porque não estão no schema (Nelo/COUNCIL-32 confirmou). O writer atual aceita esse comportamento — isto é um BUG de integridade de dados, não trade-off aceitável. **Bump v1.0.0 → v1.1.0 OBRIGATÓRIO**, com guard-rail que faz o writer **falhar loudly** ao receber colunas não mapeadas.

2. **Volume capturado parece estar ~50% abaixo do esperado** — usuário afirma que 1 dia útil WDOFUT = 600-700k trades. Smoke real captura ~301k/dia útil completo (05/04 = 307.010 em 9.5h). Janela cobriu 4 dias calendário (01-05/05) mas só 2 foram úteis (01/05 = feriado Labor Day, 02/05 = sáb, 03/05 = dom, 04/05 = seg, 05/05 = ter parcial). A explicação "duas dias úteis × 300k = 603k confere com expectativa" estava **convicta porque ninguém perguntou ao dono qual é a expectativa real**. **Investigação volume é P0** — pode haver perda silenciosa em `subscribe_ticker → GetHistoryTrades` ordering, callback v2 race, LAST_PACKET prematuro, ou janela mal computada.

3. **SCHEMA.md L33 trade_type comment errado** (Nelo/COUNCIL-32) — vira docs P0 (analista usaria mapping errado para todos os 603k trades observados).

4. **Comentário Q-DRIFT-35 errado em wrapper.py L731-745** (Nelo/COUNCIL-32) — `-2147483636 = NL_NOT_FOUND (0x8000000C)`, não `0x80000004 reinterpretado`. Custo zero corrigir, mantém código auditável.

---

## 1. Volumetria — Esperado vs Observado

### Inputs

| Fonte | Valor |
|-------|-------|
| Usuário (autoridade ownership) | 1 dia WDOFUT = **600-700k trades** |
| Smoke real (4 dias calendário) | **603.770 trades** total |
| Janela solicitada à DLL | `dt_start='01/05/2026 12:49:47'` → `dt_end='05/05/2026 12:49:47'` (4 dias) |
| Dias úteis dentro da janela | **2** (04/05 seg, 05/05 ter — 01/05 Labor Day BR, 02/05 sáb, 03/05 dom) |
| Dia 04/05 (sex no doc, mas seg real) | 307.010 trades em 09:00-18:29 BRT (~9h25m) — dia COMPLETO |
| Dia 05/05 (sáb no doc, mas ter real) | 296.758 trades em 09:00-13:02 BRT (~4h) — dia PARCIAL (até `now-10min`) |

### Análise do gap

| Cenário | Cálculo | Resultado |
|---------|---------|-----------|
| Dia 04/05 (completo, 9h25 trading) | 307.010 trades | **307k captured** |
| Pro-rated full day (~10h trading) | 307.010 × 10/9.42 | ~326k esperado se taxa atual está correta |
| Expectativa do dono | 600-700k/dia | **2× a 2.3× maior** |
| Gap absoluto | 650k − 326k | **~324k trades/dia perdidos** |
| Gap percentual | 1 − 326/650 | **~50% data loss** |

### Hipóteses de root-cause (ranked)

| # | Hipótese | Evidência a procurar | Prob. |
|---|----------|----------------------|-------|
| H1 | `subscribe_ticker` chamado **DEPOIS** de `GetHistoryTrades` ou em ordem ruim — perde trades antes do subscribe ativar | Log: `subscribe_ticker_return code=0` em 12:59:49 + `get_history_trades_call` em 12:59:49 (mesmo segundo — race?) | 30% |
| H2 | LAST_PACKET emitido prematuramente pela DLL — IngestorThread sai antes de receber todos os pacotes do dia | `last_packet_seen=True` em 13:01:54 (apenas 125s — pode ser cedo demais para 300k+ trades históricos) | 30% |
| H3 | TranslateTrade descarta sentinelas legítimas — 26.305 `translate_failures` em 603.770 = 4,4% (Nelo disse 0,12% no log anterior, mas neste smoke é maior). Se cada "sentinela" Q-DRIFT-34 estiver descartando trades reais... | Comparar `translate_failures` vs `trades_count` por chunk; investigar a guard `wYear<=1900` (pode estar dropping trades com timestamp 1990s legítimos? — possível em mercados antigos) | 20% |
| H4 | Janela de 5 dias é cap silencioso da DLL — ela retorna apenas N trades mesmo com janela maior. Q12-E menciona "janela máx 5 dias GetHistoryTrades" | Validar com janela de 1 dia explícito: smoke 1d deveria render ≥500k | 15% |
| H5 | Callback V2 buffer overflow em alta liquidez — DLL drop trades quando ringbuffer interno enche | Comparar trades/segundo no horário de pico vs vendor docs | 5% |

### Decisão Pax

**INVESTIGAÇÃO P0 BLOQUEIA RELEASE.** Não podemos shipar v1 sem confirmar se estamos capturando ≥500k trades em 1 dia útil de WDOFUT. Se gap real for ~50%, qualquer analista que use o parquet vai tirar conclusões erradas sobre microestrutura de mercado.

---

## 2. P0 priorizados (4 release-blockers)

| # | Bloqueador | Severidade | Esforço | Owner sugerido |
|---|-----------|------------|---------|----------------|
| **B1** | Schema parquet bump v1.0.0 → v1.1.0 com `buy_agent_name`, `sell_agent_name`, `trade_type_name` NOT NULL (com fallback string `Agent#{id}` / `TradeType#{n}`) | CRÍTICO | 0.5d | Dex |
| **B2** | Writer **FALHA LOUDLY** se schema receber colunas não mapeadas — ZERO silent drops permitidos. Adicionar `validate_columns(record_keys, schema_columns)` no hot path | CRÍTICO | 0.25d | Dex |
| **B3** | Investigar gap de ~50% volume (smoke 1 dia WDOFUT deve render ≥500k trades) — diff intraday por hora vs ProfitChart desktop, validar callback V2 ordering vs subscribe_ticker | CRÍTICO | 1d | Quinn (medição) + Nelo (DLL audit) |
| **B4** | Docs: SCHEMA.md L33 trade_type mapping correto + tabela TTradeType 14 valores (Sol/Nelo COUNCIL-32 §3.1); comentário Q-DRIFT-35 wrapper.py L731-745 (NL_NOT_FOUND, não 0x80000004 reinterpretado) | ALTA | 0.25d | Dex |

---

## 3. Story 1.7g criada

**Path:** `docs/stories/1.7g.story.md`
**Status:** Draft (após Pax sign-off → Ready imediato — este council valida)
**Título:** "P0 release-blockers — schema integrity + volume completude"

### Acceptance Criteria

- **AC1** — schema parquet v1.1.0 inclui `buy_agent_name`, `sell_agent_name`, `trade_type_name` NOT NULL (fallbacks string)
- **AC2** — writer FALHA LOUDLY se schema receber colunas não mapeadas (no silent drop)
- **AC3** — smoke real WDOFUT 1 dia retorna ≥500k trades (validação volume)
- **AC4** — `trades_per_day` no parquet ≥500k para cada dia útil dentro da janela
- **AC5** — SCHEMA.md tabela TTradeType de 14 valores
- **AC6** — comentário Q-DRIFT-35 wrapper.py corrigido (NL_NOT_FOUND)

---

## 4. Recomendação de execução para @aiox-master

Critical path = AC1+AC2+AC5+AC6 (Dex, sequencial, ~1d) **‖** AC3+AC4 (Quinn medição + Nelo DLL audit, paralelo, ~1d).

### Despacho recomendado (paralelo onde possível)

| Track | Agente | AC | Bloqueia? | Notas |
|-------|--------|----|-----------| ------|
| 1 (critical path code+docs) | **Dex (@dev)** | AC1, AC2, AC5, AC6 | Sim (release) | Pode iniciar imediato — toda informação está em COUNCIL-32 |
| 2 (volume measurement) | **Quinn (@qa)** | AC3, AC4 | Sim (release) | Smoke 1 dia explícito; comparar trades/15min vs ProfitChart |
| 3 (DLL audit, paralelo a Track 2) | **Nelo (DLL specialist)** | AC3 (ajuda) | Suporta Track 2 | Audit `download_chunk` flow em `wrapper.py` — quando subscribe_ticker é chamado vs GetHistoryTrades; LAST_PACKET timing; callback V2 race |

### Ordem temporal

1. **t=0**: Dex inicia AC1+AC2 (schema bump + validate_columns); Quinn+Nelo iniciam AC3 paralelo
2. **t=0.5d**: Dex faz AC5+AC6 (docs); Quinn fecha medição volume
3. **t=1d**: Story 1.7g pronta para QA gate
4. **t=1d+**: @qa valida via smoke real persistido (mesmo padrão do 1.7d) — se PASS, @devops faz push e v1 release destrava

### Bloqueios de cascata

- Se AC3 mostrar gap real ≥30% **e** root-cause estiver em wrapper/DLL não trivialmente fixável → escalar para **mini-council Aria + Nelo + Pax** (não tentar resolver autonomamente; pode envolver decisão de qual contrato usar — Q-DRIFT-32 menciona WDOFUT mas pode ser que precise contrato específico para histórico denso).
- Se AC1 quebrar testes de regressão (parquet v1.0.0 readers) → migration helper em `storage/schema.py` (não bloqueia release v1, sim release de readers downstream).

---

## 5. Decisões de não-fazer (escopo proteção)

| Item | Decisão | Justificativa |
|------|---------|---------------|
| STATUS.md update | **NÃO modificar agora** | 1.7g precisa executar antes de declarar v1 ready/blocked |
| WAIVER 1.7b update | **NÃO modificar agora** | Sintoma A pytest harness é separado de 1.7g; aguardar fim de 1.7g |
| Story 1.8 (schema bump original) | **Absorvida em 1.7g** | Não é mais "future story" — virou release-blocker pelo princípio "no silent drop" |
| Telemetria translate_failures (Nelo COUNCIL-32 §4) | **Diferida para 1.7h ou 1.8** | Observability nice-to-have, não bloqueia release |
| Filtro adicional preço/quantidade fora de range plausível | **Diferido** | 0.039% anomalias, validate_record já filtra a maioria — não bloqueia |
| Q-DRIFT-13..30 consolidação docs | **Diferida para 1.7f** | Sol já recomendou; refactor amplo |

---

## 6. Pode shipar v1 com estado atual?

**NÃO.**

| Critério release | Estado | Decisão |
|------------------|--------|---------|
| Smoke real PASS | ✅ standalone validated 1.7d | OK |
| Schema integridade (no silent drops) | ❌ 3 colunas perdidas silenciosamente | **BLOCKER** |
| Volume completude (1 dia ≥500k) | ❓ Não medido — observado parece 50% baixo | **BLOCKER** |
| Docs canonical correto | ⚠️ SCHEMA.md L33 errado, Q-DRIFT-35 comment errado | **BLOCKER (P0 doc)** |
| WAIVER 1.7b sintoma A | ⚠️ Pendente, ACCEPT-AS-TECH-DEBT (Aria) | aceitável |

Release destrava após Story 1.7g PASS QA gate.

---

## 7. Sign-off

- **Pax (@po):** APPROVED — Story 1.7g é release-blocker, mover para Ready imediatamente após este council ser commitado.
- **Próximo agente:** @aiox-master deve despachar Dex (AC1+AC2) e Quinn+Nelo (AC3) em paralelo.

---

## 8. Reporte JSON (council aggregator)

```json
{
  "council_id": 36,
  "persona": "Pax (@po)",
  "verdict": "RELEASE-BLOCKED",
  "blockers_count": 4,
  "story_created": "1.7g",
  "story_path": "docs/stories/1.7g.story.md",
  "p0_blockers": [
    "B1 schema bump v1.1.0 + agent_names + trade_type_name NOT NULL",
    "B2 writer fail-loudly em colunas não mapeadas (no silent drop)",
    "B3 investigar volume gap ~50% (smoke 1 dia >= 500k trades)",
    "B4 SCHEMA.md trade_type mapping + Q-DRIFT-35 comment fix"
  ],
  "volume_expected_per_day": 650000,
  "volume_observed_full_day": 307010,
  "volume_gap_pct": 50,
  "release_can_ship": false,
  "next_action": "aiox-master despacha Dex (AC1+AC2 critical path) e Quinn+Nelo (AC3 paralelo)"
}
```

— Pax, Product Owner, modo autônomo
