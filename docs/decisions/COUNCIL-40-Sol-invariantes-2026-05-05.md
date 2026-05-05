# COUNCIL-40 — Sol (invariantes do sistema)

**Data:** 2026-05-05
**Council member:** Sol (knowledge guardian — QUIRKS, KNOWLEDGE, INVARIANTS, ADRs)
**Story:** 1.7g (release blocker hotfix — schema integrity + volume completeness)
**Escopo:** documentar invariantes recém-descobertas a partir de 2 P0 bugs (Q-DRIFT-36/37); criar `docs/INVARIANTS.md` canônico; expandir Quick Reference de PROFITDLL_KNOWLEDGE.md (5→8 regras).

---

## TL;DR

Squad descobriu **2 release blockers P0** durante smoke real postfix-35 + Nelo Council-32 (2026-05-05):

1. **Q-DRIFT-36** (storage/schema): writer parquet v1.0.0 silenciosamente descartava `buy_agent_name`/`sell_agent_name`/`trade_type_name` por não estarem mapeados no schema, embora pipeline DLL+IngestorThread populasse corretamente. **Hotfix em curso por Dex** (schema v1.1.0 + writer fail-loudly).

2. **Q-DRIFT-37** (history/volume): smoke real WDOFUT entregou 603k trades em ~4d úteis quando baseline 1d ≈ 600-700k → **perda silenciosa de 70-80%** do volume esperado. **Investigação em curso por Quinn (volume gap analysis) + Nelo (download flow audit)**.

Ambos têm em comum: **falha silenciosa**, ausência de error/warning, dados sumindo entre pipeline e disk OU entre solicitação e resposta. Padrão indica fragilidade arquitetural — **falta de invariantes formais com checks em CI/CD**.

Este council:
- Criou Q-DRIFT-36 e Q-DRIFT-37 em `docs/dll/QUIRKS.md` com sintoma + causa raiz (hipotetizada para 37) + workaround + refs.
- Criou `docs/INVARIANTS.md` v1.0.0 canônico com **6 invariantes** (I1..I6) inegociáveis.
- Expandiu Quick Reference de PROFITDLL_KNOWLEDGE.md de 5 para 8 regras (#6 janela vs volume real, #7 NUNCA confiar em LAST_PACKET cego, #8 NL_NOT_FOUND é semântico).

---

## Passo 1 — Q-DRIFT-36 criado

### Onde
`docs/dll/QUIRKS.md` — entrada nova entre Q-DRIFT-35 e a seção histórica Q-DRIFT-13..25; tabela de índice atualizada.

### Conteúdo

- **Status:** 🐛 BUG-CÓDIGO — HOTFIX-IN-PROGRESS (Story 1.7g, Dex schema v1.1.0 + writer fail-loudly).
- **Severidade:** P0 release blocker.
- **Causa raiz:** `pa.Table.from_pylist(rows, schema=...)` descarta silenciosamente chaves não declaradas no schema. Writer recebia dict completo (17+ chaves) do IngestorThread mas schema v1.0.0 omitia `buy_agent_name`/`sell_agent_name`/`trade_type_name` → evaporavam entre dict e disk.
- **Detecção:** Nelo Council-32 (auditoria cruzada IngestorThread × parquet de saída).
- **Fix em curso:** schema v1.1.0 (bump aditivo 3 campos nullable) + writer envolvido em validação prévia (`SchemaContractViolation`) + test obrigatório `test_writer_raises_on_missing_schema_field`.
- **Prevenção sistêmica:** ADR-019 (Aria) + invariante I1 (`docs/INVARIANTS.md`).

---

## Passo 2 — Q-DRIFT-37 criado

### Onde
`docs/dll/QUIRKS.md` — entrada nova após Q-DRIFT-36; tabela de índice atualizada.

### Conteúdo

- **Status:** 🧪 HYPOTHESIS — INVESTIGATING (Story 1.7g, Quinn+Nelo).
- **Severidade:** P0 release blocker.
- **Sintoma:** smoke postfix-35 entregou 603 074 trades em janela de ~4 dias úteis WDOFUT/F + LAST_PACKET + return code 0. Baseline empírico 1d ≈ 600-700k → 4d deveriam render ~2.4M-2.8M; recebemos ~25-30%.
- **Hipóteses ativas (3 paralelas):**
  - **H37-A:** `TC_LAST_PACKET` prematuro (server envia antes de drenar volume).
  - **H37-B:** window cap server-side implícito (~600k trades/chamada) — exigiria split obrigatório por dia.
  - **H37-C:** subscribe race / chunk inicial perde buffer.
- **Trabalho:** Quinn Council-37 (mensurar baseline real por dia útil) + Nelo Council-38 (instrumentar chunks com timestamps + counters).
- **Workaround tentativo:** **NUNCA confiar em LAST_PACKET cego** — cross-check `last_trade_ts` vs `dt_end_str`; replay automático em gap detectado.
- **Prevenção sistêmica:** ADR-020 (Aria) + invariante I2 (`docs/INVARIANTS.md`).

---

## Passo 3 — `docs/INVARIANTS.md` v1.0.0 criado

### Estrutura

**6 invariantes inegociáveis**, cada um com: princípio, regras concretas, test obrigatório (CI), refs cruzadas a quirks de origem.

| # | Invariante | Origem | ADR formal | Test CI |
|---|-----------|--------|------------|---------|
| I1 | Schema-as-Contract | Q-DRIFT-36 | ADR-019 (Aria) | `test_writer_raises_on_missing_schema_field` |
| I2 | Volume Completeness | Q-DRIFT-37 | ADR-020 (Aria) | `test_volume_baseline_per_day_minimum` |
| I3 | Agent Name Resolution Graceful | Q-DRIFT-34 | — | `test_agent_resolver_unknown_id_returns_fallback` |
| I4 | Trade Type Resolution | COUNCIL-32 (Nelo) | — | `test_trade_type_unknown_id_returns_fallback` |
| I5 | Translate Failures Telemetria | Q-DRIFT-34 | — | `test_metrics_separate_sentinel_from_exceptions` |
| I6 | GetHistoryTrades Window Split | Q-DRIFT-37, Q-DRIFT-31 | ADR-020 (Aria) | (provisória até Nelo Council-38) |

### Princípio guarda-chuva

Constitution **Article V (Quality First)** + **Article IV (No Invention)**. Violação = falha constitucional bloqueante.

### Tabela CI checks recomendados

Documentada na seção final do INVARIANTS.md — 8 checks (5 unit/integration + 1 lint custom + 2 alertmanager runtime).

---

## Passo 4 — PROFITDLL_KNOWLEDGE.md Quick Reference expandido (5→8 regras)

### Antes
Quick Reference Canonical (top 5 do-and-don't) — regras #1..5 cobriam: WDOFUT vs contrato vencido, janela máx 5d, subscribe sempre antes, init slots None vs Noop, argtypes/restype canônicos.

### Agora (top 8)

Adicionadas:

- **Regra #6** — Janela GetHistoryTrades: confirmar limite empírico real **por dia** vs **5d agregado** (Nelo Council-38). Até validar, considerar split forçado por dia útil quando volume esperado > 600k. Refs Q-DRIFT-37, Q-DRIFT-31.

- **Regra #7** — NUNCA confiar em `TC_LAST_PACKET` cego: cross-checar `last_trade_timestamp` vs `dt_end_str` solicitado; se gap > threshold, agendar replay automático. Refs Q-DRIFT-37, INVARIANTS.md I2.

- **Regra #8** — `NL_NOT_FOUND` em `GetAgentName` é semântico, não bug: agent IDs >1M (mesas/gateways/RLP B3) frequentemente retornam `0x8000000C`/`-2147483636` — preencher com fallback string `"UNKNOWN_<id>"`; JAMAIS NULL silencioso. Refs Q-DRIFT-34, Q-DRIFT-36, INVARIANTS.md I3.

### Cross-ref adicionada

Bloco final do Quick Reference passa a referenciar `docs/INVARIANTS.md` explicitamente: "Invariantes do projeto: ver `docs/INVARIANTS.md` — princípios I1-I6 são inegociáveis e devem ser checados em CI/CD."

---

## Passo 5 — Tabela de índice QUIRKS atualizada

| ID | Status | Categoria | Sumário |
|----|--------|-----------|---------|
| [Q-DRIFT-36](../dll/QUIRKS.md#q-drift-36) | 🐛 bug-código (HOTFIX-IN-PROGRESS Story 1.7g) | storage / schema | Writer parquet v1.0.0 silenciosamente descartava `buy_agent_name`/`sell_agent_name`/`trade_type_name`; **P0 release blocker** |
| [Q-DRIFT-37](../dll/QUIRKS.md#q-drift-37) | 🧪 hypothesis (INVESTIGATING Story 1.7g) | history / volume completeness | GetHistoryTrades entrega ~603k trades em 4d WDOFUT vs baseline 1d ≈ 600-700k → perda silenciosa **70-80%**; **P0 release blocker** |

---

## Decisões tomadas (Sol, sob autoridade Knowledge guardian)

1. **Q-DRIFT-36 e Q-DRIFT-37 são quirks legítimos** — registrar formalmente (não apenas em smoke evidence ou council notes voláteis). Mesmo que Q-DRIFT-37 ainda seja hypothesis, a perda de volume é fato empírico — quirk com hipóteses paralelas.

2. **INVARIANTS.md é documento canônico do projeto** (não rule de agent, não checklist) — **L4 mutável** (`docs/`) mas com semântica de contrato perpétuo (mudar = bump major + ADR + comunicação a Morgan/Aria).

3. **Quick Reference expandida 5→8 não viola regra "top 5"** — o doc PROFITDLL_KNOWLEDGE.md já evolui regras conforme bugs aparecem (auditoria 2026-05-05 já consolidou; agora 2026-05-05 noite expande a partir de 1.7g blockers). Renomeado o título: "top 5" → "top 8".

4. **NÃO modifiquei código** — apenas documentação. Hotfix Q-DRIFT-36 é responsabilidade Dex Story 1.7g. Investigação Q-DRIFT-37 é responsabilidade Quinn (Council-37) + Nelo (Council-38). ADRs formais são responsabilidade Aria.

5. **NÃO arquivei nem refactorei** — escopo limitado a additivos. Refactor amplo → Story 1.7f conforme COUNCIL-35.

---

## Próximos passos (handoff)

- **Dex** — Story 1.7g schema v1.1.0 + writer fail-loudly + test red→green (`test_writer_raises_on_missing_schema_field`).
- **Aria** — ADR-019 (Schema-as-Contract) + ADR-020 (Volume Completeness) — formalizar I1 e I2 (atualmente referenciados como "em redação").
- **Quinn** — Council-37: medir baseline empírico WDOFUT por dia útil; comparar curvas 1d/2d/3d/4d/5d.
- **Nelo** — Council-38: instrumentar `GetHistoryTrades` callbacks com timestamps + counters por chunk; identificar LAST_PACKET prematuro vs cap real.
- **Pax** — Story 1.7g release blocker tracking (Q-DRIFT-36/37); validar I1-I6 antes de declarar release ready.
- **Sol (eu)** — após Nelo Council-38: atualizar I6 de PROVISÓRIA → ACCEPTED com decisão final de split obrigatório vs limite ajustado.

---

## Arquivos modificados (commit subsequente)

- `docs/dll/QUIRKS.md` (Q-DRIFT-36 + Q-DRIFT-37 novos; tabela de índice atualizada; header data 2026-05-05).
- `docs/dll/PROFITDLL_KNOWLEDGE.md` (Quick Reference 5→8 regras; cross-ref a INVARIANTS.md; header data 2026-05-05).
- `docs/INVARIANTS.md` (NOVO — v1.0.0 ACCEPTED).
- `docs/decisions/COUNCIL-40-Sol-invariantes-2026-05-05.md` (este arquivo).

---

## Refs

- COUNCIL-32 (Nelo — agents + trade types audit, descobriu Q-DRIFT-36).
- COUNCIL-35 (Sol — auditoria documentação 2026-05-05 manhã, base para esta).
- COUNCIL-36 (Pax — release blockers tracking).
- COUNCIL-37 (Quinn — volume gap analysis, em curso).
- COUNCIL-38 (Nelo — download flow audit, em curso).
- `docs/dll/QUIRKS.md` Q-DRIFT-36, Q-DRIFT-37, Q-DRIFT-34, Q-DRIFT-31.
- `docs/storage/SCHEMA.md` §0, §6.
- `profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas` (TConnectorTradeType).

— Sol, custodiando os princípios 💾
