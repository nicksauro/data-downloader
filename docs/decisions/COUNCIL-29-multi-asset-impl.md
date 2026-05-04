# COUNCIL-29 — Multi-asset Support Implementation (Story 4.2)

**Story:** 4.2 — Multi-asset support (WIN trimestral H/M/U/Z + equities)
**Date:** 2026-05-04
**Conveners:** Sol 💾 (storage authority — seed CONTRACTS.md) + Dex 💻
(builder — chunker + probe) + Nelo 🗝️ (DLL authority — vigência hipotetizada,
Q-OPEN)
**Status:** RATIFIED (autonomous mini-council mode — modelo COUNCIL-25)

---

## 1. Situação

A Story 4.2 entrega multi-asset support sobre o pipeline já provado para
WDO (Stories 1.x, 2.x, 4.1):

- **WIN trimestral H/M/U/Z** — 8 contratos (WINH26..WINZ27) cobrindo
  2 anos com letras de mês (CME convention) Março/Junho/Setembro/Dezembro.
- **Equities sem vencimento** — 6 tickers líquidos (PETR4, VALE3, ITUB4,
  BBDC4, BBAS3, ABEV3) na exchange Bovespa (`B`), `vigent_from=1900-01-01`,
  `vigent_until=9999-12-31`.

A decisão arquitetural (Story 4.2 contexto + COUNCIL-13 Epic 4 prep)
foi: **expandir o seed sem mudar o schema** — nem `contracts` SQLite
nem `partitions` precisam de coluna nova. O eixo de extensão é (a) seed
data + (b) detecção de equity em chunker + (c) probe estendido.

Story 4.1 (broker multi-symbol) já está Done* (com WAIVER smoke real),
liberando o paralelismo necessário para baixar 4 símbolos heterogêneos
simultaneamente. Esta story complementa ao garantir que cada um dos
3 asset shapes (WDO mensal, WIN trimestral, equity infinita) funciona
identicamente na fronteira pública.

---

## 2. Decisões

### D1 — Seed expansion (Sol 💾 authority)

| Aspecto | Decisão | Justificativa |
|---------|---------|---------------|
| WIN entries | 8 contratos (H26..Z27) | 2 anos completos, alinhado a horizonte de backtest (Sol mantém regra: contrato adicionado <60d antes da vigência, mas seed inicial 4.2 inclui todos para cobrir gates Quinn) |
| WIN `validation_source` | `hypothesized` | Regra B3 (5º dia útil X-3 → quarta mais próxima 15/X) é aproximação. Q18-OPEN no QUIRKS.md força probe humano antes de `dll_probe` |
| Equity entries | 6 tickers líquidos | Cobre top liquid Bovespa por volume + setores diferentes (energy, mineração, banking, consumer staples) |
| Equity `validation_source` | `manual` | Tickers conhecidos publicamente; smoke real (WAIVER 4.2) confirma |
| Equity exchange | `B` (Bovespa) | R8 / Q05-V — `F` (BMF) retorna `NL_EXCHANGE_UNKNOWN` para equities |
| Schema | **NÃO mudar** | Campo `symbol` em Parquet já é arbitrário; `contracts` SQLite já genérica |

**Sol verdict:** APPROVED. Seed v1.1.0 preservation.

### D2 — Chunker equity detection (Dex 💻 + COUNCIL-05 §D4)

| Aspecto | Decisão | Justificativa |
|---------|---------|---------------|
| Detecção equity | Regex `^[A-Z]{4}\d$` | Convenção B3 — 4 letras + 1 dígito (3=ON, 4=PN, 11=UNT). Determinístico, sem ambiguidade |
| Função pública | `is_equity_ticker(symbol) -> bool` | Reusada por `chunker.chunk_days_for_symbol` E `contracts_probe._resolve_sample_date` |
| Equity chunk_days | 1 (`DEFAULT_EQUITY_CHUNK_DAYS`) | Já era o fallback. Confirmado para equity explícita também |
| WIN chunk_days | 5 | **Já em CHUNK_DAYS** desde Story 1.7a — não é alteração nesta story |

**Tabela final consolidada (CONTRACTS.md §3.1):**

| Prefix / Pattern    | chunk_days | exchange | asset_class |
|---------------------|------------|----------|-------------|
| `WDO*`              | 5          | F        | future_mini |
| `WIN*`              | 5          | F        | future_mini |
| `IND*`, `DOL*`      | 5          | F        | future_full |
| `^[A-Z]{4}\d$` regex| 1          | B        | equity      |
| Outros              | 1 (fallback)| variável | unknown    |

**Dex verdict:** APPROVED. Função pequena, type-safe, retro-compatível
(comportamento prévio para WDO/WIN/IND/DOL inalterado).

### D3 — Probe equity (Dex 💻 + Nelo 🗝️)

| Aspecto | Decisão | Justificativa |
|---------|---------|---------------|
| `_resolve_sample_date` | Detecta equity → `today() - 7d` | `vigent_from=1900-01-01` é semanticamente ruim para probe; -7d garante dia útil recente |
| `probe_contract` | Caller passa `exchange="B"` para equity | API já permite — sem mudança de assinatura |
| `ProbeResult` | Mesma estrutura | Reusabilidade total |
| CLI hint | Documentar em `data-downloader contracts validate --symbol PETR4 --exchange B` | Story 4.2 AC3 |

**Nelo verdict:** APPROVED com Q18-OPEN registrado. Probe equity é
trivial DLL-wise (Q05-V garante exchange='B'); o risco é só vigência
WIN (Q18) — expectativa é que probe humano confirma seed dentro de ±1 dia.

### D4 — `read_continuous` para WIN + equity (Sol 💾 + Dex 💻)

| Aspecto | Decisão | Justificativa |
|---------|---------|---------------|
| WIN rollover | Já implementado em `continuous_reader.py` | Story 1.5b — função é genérica, lê 4 contratos H/M/U/Z igual aos 3 WDO existentes |
| Equity degenerado | 1 contrato vigente cobrindo todo range = `read_history` | Sem mudança de implementação — caso degenerado natural |
| Test coverage | Property test equity = idempotente | `tests/property/test_continuous_equity.py` (novo) |
| WIN coverage | Já coberto por `tests/property/test_continuous_rollover.py` | 3 contratos contíguos = mesma estrutura WIN H→M→U |

**Sol verdict:** APPROVED. Zero mudança em `continuous_reader.py` —
implementação Story 1.5b é genérica desde então.

### D5 — WAIVER smoke real (Sol + Dex + Nelo, política COUNCIL-09)

| Aspecto | Decisão | Justificativa |
|---------|---------|---------------|
| Smoke real WIN+PETR4 | DEFERRED via WAIVER | Mesma política Story 4.1 e 1.7b — agente não tem ProfitDLL nem licença |
| WAIVER path | `docs/qa/WAIVERS/4.2-real-smoke-deferred-2026-05-04.md` | Mesmo padrão 4.1 |
| Story-debt | `docs/stories/4.2-followup.story.md` | Smoke real humano + atualização `validation_source` |
| Bloqueia release | V1 | Igual 4.1 — gate Epic 4 fechamento |
| Cobertura mock | Integration test `test_multi_asset_mock.py` (3 cenários) | MockProfitDLL fire_trades + WINH26 + PETR4 + WDOJ26 |

**Sign-off implícito:** Sol (storage), Dex (impl), Nelo (DLL probe) —
todos os 3 inputs estavam alinhados desde COUNCIL-13.

---

## 3. Razão (Article IV — No Invention)

Cada decisão acima rastreia a artefato existente:

| Decisão | Trace |
|---------|-------|
| D1 WIN seed 8 contratos | Story 4.2 AC2 (literal "WIN: H/M/U/Z para 2026 + 2027 (8 contratos mínimo)") |
| D1 Equity seed 6 tickers | Story 4.2 AC2 (literal "PETR4 + VALE3 (já no seed) + ITUB4 + BBDC4 (4 mínimo)") + adicionados BBAS3 + ABEV3 para diversificação setorial |
| D2 Chunker equity regex | Story 4.2 AC1 + COUNCIL-05 §D4 + Q12-E (chunk size adaptativo já validado) |
| D3 Probe equity | Story 4.2 AC3 (literal "Probe contra `PETR4` em qualquer dia útil recente") |
| D4 read_continuous | Story 4.2 AC4 + Story 1.5b (read_continuous implementação genérica) |
| D5 WAIVER | Política COUNCIL-09 estendida (mesmo padrão Story 4.1 WAIVER) |

Nenhuma decisão deste COUNCIL-29 inventa requirement não rastreável.

---

## 4. Débito documentado

| Campo | Valor |
|-------|-------|
| **Tipo** | Real smoke deferred-by-protocol |
| **WAIVER path** | `docs/qa/WAIVERS/4.2-real-smoke-deferred-2026-05-04.md` |
| **Story-followup** | `docs/stories/4.2-followup.story.md` |
| **Q-OPEN registrado** | Q18-OPEN (vigência exata WIN) — `docs/dll/QUIRKS.md` |
| **Prazo** | Antes do release V1 (Epic 4 fechamento) |
| **Bloqueio release** | V1 |
| **Aprovador** | Sol (seed authority) + Dex (chunker/probe impl) + Nelo (DLL probe + Q-OPEN) — implícito Aria + Pyro + Morgan via COUNCIL-09 |

---

## 5. Quando o smoke real rodar (4.2-followup)

1. Humano configura `.env` com `PROFITDLL_KEY` / `PROFIT_USER` / `PROFIT_PASS`.
2. Humano roda `data-downloader contracts validate --root WIN --year 2026`
   → probe atualiza `validation_source=dll_probe` para WIN H/M/U/Z 26.
3. Humano roda `data-downloader contracts validate --symbol PETR4 --exchange B`
   → probe atualiza `validation_source=dll_probe` para PETR4.
4. Humano roda smoke completo `tests/smoke/test_multi_asset_smoke.py`
   (download 1 dia WINH26 + 1 dia PETR4 → partições + integrity check PASS).
5. Evidência sanitizada salva em `docs/qa/SMOKE_EVIDENCE/4.2-{ts}.md`.
6. Quinn lê evidência e emite `qa-gate 4.2-followup` PASS.
7. Q18-OPEN movido para `validated` (ou ajustado para `ambiguous` se
   probe revelar divergência ±5d na regra B3).
8. Story 4.2-followup fecha → débito remediado em
   `docs/qa/WAIVERS/4.2-real-smoke-deferred-2026-05-04.md`.

---

## 6. Sign-off consolidado

**RATIFIED** — 4.2 vai a Ready for Review com:

- Seed CONTRACTS.md v1.1.0 (8 WIN + 6 equity)
- Chunker `is_equity_ticker` regex + comportamento WDO/WIN inalterado
- Probe `_resolve_sample_date` aware de equity
- Q18-OPEN registrado em QUIRKS.md
- WAIVER smoke real (mesma política COUNCIL-09 / 4.1)
- Tests novos: contracts multi-asset + chunker equity + integration mock + property equity rollover

Esta decisão preserva (a) zero schema migration, (b) extensibilidade
multi-asset sem breaking changes, (c) modo autônomo legítimo (humano
fecha gap empírico via 4.2-followup).

---

— Sol 💾 (seed authority) | Dex 💻 (chunker+probe impl) | Nelo 🗝️ (DLL probe + Q18-OPEN)
