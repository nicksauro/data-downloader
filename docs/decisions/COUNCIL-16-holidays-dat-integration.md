# COUNCIL-16 — Calendar B3 holidays.dat Integration (Story 2.5)

**Data:** 2026-05-03
**Convocação:** Mini-council Sol + Nelo + Dex — modo autônomo (Story 2.5)
**Participantes mentais:**
- 💾 Sol (Storage Engineer — custodian de calendar policy / consumer em gap detection)
- 🗝️ Nelo (ProfitDLL Specialist — autoridade sobre formato de arquivos auxiliares Nelogica)
- 💻 Dex (Backend Developer — implementer)

**Reviewers (downstream):**
- 🧪 Quinn (QA — gate Story 2.5)
- 📋 Morgan (PM — origem da story, finding F-S-1 Sol audit 2.1)

---

## Contexto

Story 2.5 substitui a tabela hardcoded de feriados B3 (2025-2026) em
`src/data_downloader/validation/calendar_b3.py` por leitura do arquivo oficial
`profitdll/DLLs/Win64/holidays.dat` distribuído pela Nelogica. Origem:
- Finding **F-S-1** Sol audit Story 2.1 (calendário hardcoded como caveat).
- COUNCIL-04 (decisão pandas para business-days, com calendário ainda placeholder).
- TODO no docstring de `calendar_b3.py` referenciando "PROFITDLL_KNOWLEDGE.md §X".

---

## Investigação de formato (Nelo authority)

### Manual ProfitDLL — silêncio

Manual oficial (PROFITDLL_KNOWLEDGE.md §1-8) **NÃO documenta** `holidays.dat`. Não há
seção sobre arquivos auxiliares distribuídos com a DLL. `validation_source` =
`reverse_engineered`.

### Análise empírica

Inspeção byte-a-byte do arquivo distribuído (33 976 bytes, geração
`//29/12/2025 14:16:19.813`):

- **Encoding:** UTF-8 com BOM (`EF BB BF`).
- **Line endings:** CRLF.
- **Layout linha:** `EE:YYYYMMDDHHMMSSF:OPEN:CLOSE:DESCRIPTION`.
- **`EE`:** 2 dígitos = código ASCII do exchange (66='B' Bovespa, 70='F' BMF, 35='#'
  B3 unified, 88='X', 99='c' — todos B3-related; 89='Y' NYSE, 96='\`' NASDAQ etc.
  estrangeiros).
- **Cobertura:** 2013-2035 (23 anos), 843 linhas de dados.
- **Quirk Nelogica:** feriados que caem em sábado/domingo **NÃO** são listados
  (ex: 2025-09-07 Independência domingo, omitido). Pontos facultativos
  (24/12, 31/12) são listados como full-day.

Doc completo: `docs/dll/HOLIDAYS_DAT_FORMAT.md` (Nelo authority).

---

## Decisões

### D1 — Estratégia união (parser + hardcoded)

**Decisão:** API consumer (`is_holiday`, `b3_holidays`) usa **união** entre parser
e tabela hardcoded estendida 2020-2030. Nenhuma fonte sozinha é completa:

| Fonte | Cobre | Omite |
|-------|-------|-------|
| Parser (DAT) | 2013-2035, pontos facultativos (24/12, 31/12) | Feriados em FDS |
| Hardcoded | 2020-2030 nacionais (incluindo FDS) | Pontos facultativos |
| **União** | 2013-2035 com superset semântico | — |

**Sol sign-off:** API pública preservada (`is_holiday`, `is_b3_business_day`,
`b3_business_days_range` mantêm assinatura). Para gap detection, união é a
escolha conservadora (menos falso positivo).

**Nelo sign-off:** Parser respeita ground truth Nelogica (apenas exchanges B3,
ignora pregão parcial em V1). Documentação de formato registrada com caveats
de reverse engineering.

### D2 — Cache mtime-based

**Decisão:** Parser cacheia resultado por path com chave (mtime_ns).
Calendário cacheia conjunto efetivo (parser ∪ hardcoded) também por mtime_ns
do `holidays.dat`. Re-parse automático quando Nelogica atualizar o arquivo.

**Sol concerns endereçadas:** Custo amortizado O(1) por chamada após boot.
Lock garante thread-safety em primeiro uso simultâneo.

### D3 — Fallback graceful (AC8)

**Decisão:** Se `holidays.dat` ausente OU parse falha, sistema usa hardcoded
puro + log INFO/WARN. CI roda sem ProfitDLL → tudo passa.

**Env var:** `DATA_DOWNLOADER_HOLIDAYS_DAT_PATH` permite override (testes,
CI, contributors externos).

### D4 — Pregão parcial (Cinzas, vésperas) NÃO é feriado em V1

**Decisão:** Linhas com `OPEN` preenchido (pregão parcial) são SKIPADAS pelo
parser. Cinzas é dia útil B3 (com sessão reduzida). Story futura pode
adicionar suporte a "horário parcial" em separado.

### D5 — Cobertura hardcoded estendida 2020-2030 (AC4)

**Decisão:** Tabela hardcoded extendida de 2 anos (2025-2026) para 11 anos
(2020-2030), respeitando Sol policy `>= 2020-01-01` (M17 DST). Calculada via
algoritmo Páscoa (Gauss/Meeus) para feriados móveis. Consciência Negra
incluída apenas a partir de 2024 (Lei 14.759/2023).

---

## Implementação (Dex)

| Arquivo | Tipo | Linhas | Descrição |
|---------|------|--------|-----------|
| `src/data_downloader/validation/holidays_dat_parser.py` | NEW | ~205 | Parser + erros + cache mtime |
| `src/data_downloader/validation/calendar_b3.py` | EDITED | +200 | Estende hardcoded 2020-2030 + integração parser + fallback |
| `src/data_downloader/validation/__init__.py` | EDITED | +2 | Export `b3_holidays` |
| `docs/dll/HOLIDAYS_DAT_FORMAT.md` | NEW | ~180 | Doc formato (Nelo authority) |
| `tests/unit/test_holidays_dat_parser.py` | NEW | 13 testes | Parser unit (real DAT + sintética) |
| `tests/unit/test_calendar_b3_extended.py` | NEW | ~50 testes | Cobertura 2020-2030 hardcoded |
| `tests/integration/test_calendar_b3_holidays_dat.py` | NEW | 8 testes | União, fallback, refresh mtime, real DAT |
| `tests/property/test_calendar_b3_consistency.py` | NEW | 5 testes Hypothesis | Invariants is_business_day vs is_holiday |
| `docs/decisions/COUNCIL-16-holidays-dat-integration.md` | NEW | (este) | Registro mini-council |

**Validação:**
- ruff: clean (após fix de chars Unicode ambíguos).
- mypy strict: clean (5 source files).
- pytest validation/calendar suite: 174/174 PASS.
- pytest suite completa: **622 passed, 5 skipped** (zero regressão).

---

## Acceptance Criteria — Status

| AC | Status | Notas |
|----|--------|-------|
| AC1 — Investigação formato | ✓ | `HOLIDAYS_DAT_FORMAT.md` registra reverse engineering (manual silente) |
| AC2 — Parser dedicado | ✓ | `holidays_dat_parser.py` com erros tipados, sem deps novas |
| AC3 — Integração transparente | ✓ | `calendar_b3.py` API preservada, fonte interna troca |
| AC4 — Cobertura 2020-2030 | ✓ | Hardcoded estendido + união com DAT (cobertura 2013-2035) |
| AC5 — Refresh mtime | ✓ | Parser + calendar cacheiam por mtime; re-parse automático |
| AC6 — Test ground truth | ✓ | 50+ testes parametrizados + property tests (Hypothesis) |
| AC7 — Doc formato | ✓ | `HOLIDAYS_DAT_FORMAT.md` (Nelo audita) |
| AC8 — Graceful fallback | ✓ | Env var override + tests cobrindo arquivo ausente/corrompido |

---

## Q16-OPEN — Status

**Q16-OPEN:** Manual oficial Nelogica não documenta exchange codes 35/88/99. Format
deduzido empiricamente. Mantido como open question (deferred) — sugere `Nelo
*probe-manual` futuro com Nelogica. **Status:** RESOLVED para escopo da Story 2.5
(parser funcional via reverse engineering); **OPEN** para confirmação oficial
formal com Nelogica.

---

## Sign-offs

- **Sol (custodian):** ✓ API pública preservada, fallback CI safe, gap detection
  beneficiada por superset.
- **Nelo (DLL authority):** ✓ Formato documentado com caveats de reverse engineering;
  validation_source = `reverse_engineered`; fallback hardcoded aceitável.
- **Dex (impl):** ✓ 1 arquivo novo + 2 estendidos + 1 doc formato + 4 arquivos de
  teste; ruff + mypy strict + pytest todos verdes; zero regressão.

— Sol, Nelo, Dex 💾🗝️💻
