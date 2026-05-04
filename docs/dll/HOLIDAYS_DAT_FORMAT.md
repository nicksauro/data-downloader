# HOLIDAYS_DAT_FORMAT — Formato de `holidays.dat` Nelogica

**Curador:** Nelo (profitdll-specialist)
**Co-reviewer:** Sol (storage-engineer / calendar consumer)
**Story:** 2.5
**Última análise:** 2026-05-03
**Validation source:** `reverse_engineered`
**Arquivo analisado:** `profitdll/DLLs/Win64/holidays.dat`
**SHA-256:** (calcular ao versionar — gerado em 2025-12-29 14:16:19.813 UTC pela Nelogica)
**Tamanho:** 33 976 bytes
**Linhas de dados:** 843 (após filtrar comentário de header)

---

## 1. Status de validação

| Critério | Status |
|----------|--------|
| Manual ProfitDLL documenta este arquivo? | NÃO (verificado em PROFITDLL_KNOWLEDGE.md — não há seção sobre auxiliary files) |
| Formato deduzido empiricamente? | SIM — texto plano, ASCII-decoded, padrão regex confirmado em 100% das 843 linhas |
| Cobertura validada vs ground truth oficial? | SIM — feriados 2024/2025/2026 batem com tabela B3 oficial publicada |
| `validation_source` (CONTRACTS.md §0 enum) | `reverse_engineered` |

> **Caveat Nelo:** Manual oficial não documenta `holidays.dat`. Formato foi inferido por inspeção. Caso Nelogica modifique o layout em update futuro da DLL, o parser pode quebrar — mitigado por (a) erro determinístico (`HolidaysDatParseError` com offset) e (b) fallback hardcoded preservado.

---

## 2. Layout

### 2.1 Encoding e line endings

- **Encoding:** UTF-8 com BOM (`EF BB BF`).
- **Line endings:** CRLF (`\r\n`).
- **Idioma:** Português brasileiro (descrições) + inglês (feriados estrangeiros).

### 2.2 Estrutura de linha

#### Cabeçalho (1 linha)

```
//DD/MM/YYYY HH:MM:SS.fff
```

Exemplo observado:
```
//29/12/2025 14:16:19.813
```

Indica timestamp de geração do arquivo pela Nelogica. Útil para auditoria de versão (mesmo arquivo distribuído em duas datas terá o mesmo header).

#### Linhas de dados (843 entradas)

Padrão regex (Python):

```python
r"^(?P<exchange>\d+):"
r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})\d+:"
r"(?P<open>\d*):"
r"(?P<close>\d*):"
r"(?P<desc>.*)$"
```

Esquema textual:

```
EE:YYYYMMDDHHMMSSF:OPEN:CLOSE:DESCRIPTION\r\n
```

| Campo | Tipo | Tamanho | Descrição |
|-------|------|---------|-----------|
| `EE` | dígitos | 2 | Código ASCII do exchange (ver §3) |
| `YYYYMMDDHHMMSSF` | dígitos | 15 | Timestamp do feriado. Sempre `YYYYMMDD000000000` para full holidays |
| `OPEN` | dígitos | 0..15 | Vazio = full holiday. Preenchido = pregão parcial (timestamp de abertura) |
| `CLOSE` | dígitos | 0..15 | Vazio = sem fechamento especial. Preenchido = horário fechamento |
| `DESCRIPTION` | texto | livre | Nome do feriado (UTF-8) |

**Exemplo de linha (full holiday — Natal 2025 BMF):**

```
70:202512250000000:::Natal
```

**Exemplo de linha (pregão parcial — Cinzas 2014 Bovespa, abre 13:00):**

```
66:201403050000000:201403051300000::Quarta-feira de Cinzas
```

---

## 3. Códigos de exchange (`EE`)

Os 2 dígitos de `EE` correspondem ao **código ASCII** do caractere identificador do exchange.

| `EE` | Char ASCII | Mercado | Tratamento no parser |
|------|------------|---------|----------------------|
| `35` | `#` | B3 unified (post-merger) | INCLUÍDO |
| `66` | `B` | Bovespa (legado pré-merger 2017) | INCLUÍDO |
| `70` | `F` | BMF (legado pré-merger 2017) | INCLUÍDO |
| `88` | `X` | Variante observada B3 (raro) | INCLUÍDO |
| `99` | `c` | Variante observada pós-2017 | INCLUÍDO |
| `89` | `Y` | NYSE | IGNORADO |
| `96` | `` ` `` | NASDAQ (?) | IGNORADO |
| `80` | `P` | Outro mercado estrangeiro | IGNORADO |
| `68` | `D` | Desconhecido (raro) | IGNORADO |
| `65` | `A` | Desconhecido (raro) | IGNORADO |
| `77` | `M` | Mercado norte-americano | IGNORADO |
| `78` | `N` | Mercado norte-americano | IGNORADO |

**Política Sol+Nelo:** apenas exchanges B3-related entram em `b3_holidays()`. Códigos estrangeiros são silenciosamente descartados.

---

## 4. Cobertura observada

| Aspecto | Valor |
|---------|-------|
| Range de anos | 2013 — 2035 (23 anos) |
| Linhas de dados B3 (66/70/35/88/99) full-day | ≈ 230 |
| Anos com cobertura ≥ 9 holidays | 2014-2030 |
| Conformidade com Sol policy `>= 2020-01-01` | OK |

### Quirk: feriados em fim de semana

Nelogica **NÃO** lista feriados que caem em sábado/domingo (provavelmente porque já não há pregão nesses dias). Exemplo: em 2025, o `holidays.dat` omite `2025-09-07` (domingo, Independência), `2025-10-12` (domingo, Aparecida), `2025-11-02` (domingo, Finados), `2025-11-15` (sábado, Proclamação).

A tabela hardcoded em `calendar_b3.py` **inclui** essas datas para completude semântica (caller pode querer saber "é feriado?" mesmo num fim de semana). A estratégia de união (parser ∪ hardcoded) garante:

1. Pontos facultativos (24/12, 31/12) que o parser detecta mas o hardcoded omite.
2. Feriados oficiais em fim de semana que o hardcoded inclui mas o parser omite.

---

## 5. Estratégia de parse (Sol+Nelo decisão COUNCIL-16)

| Decisão | Razão |
|---------|-------|
| Apenas `OPEN` vazio = feriado | Pregão parcial (Cinzas) é dia útil com sessão reduzida, não feriado |
| Filtrar exchanges B3 only | NYSE/NASDAQ não afetam pregão B3 |
| Cache mtime-based (parser + calendar) | Re-parse só quando arquivo muda; perf O(1) por chamada após boot |
| Fallback hardcoded sempre disponível | CI sem ProfitDLL + contributors externos |
| União `parser ∪ hardcoded` | Cobre tanto pontos facultativos quanto feriados em FDS |

---

## 6. Limitações conhecidas

1. **Pontos facultativos pré-meio-dia (24/12, 31/12, vésperas):** parser trata como feriado full-day porque `OPEN` está vazio na DAT. Isso pode diferir de uma definição rigorosa B3 que considera pregão até 13:00 nessas datas. Para gap detection é o trade-off seguro (não detectar gap espúrio).
2. **Reverse-engineered:** se Nelogica mudar o formato em update da DLL, parser quebra. Mitigado por `HolidaysDatParseError` com offset (debug fácil).
3. **Cobertura > 2030:** parser cobre até 2035; hardcoded vai até 2030. Para anos 2031-2035, depende exclusivamente do parser (sem fallback).
4. **Feriados regionais** (ex: aniversário de SP 25/01) **não** estão no escopo de B3 — DAT não os lista, hardcoded também não.

---

## 7. Validação ground truth (2025)

Comparação `parser(B3 full-day)` vs hardcoded:

| Data | No parser? | No hardcoded? | Cobertura efetiva (união) |
|------|-----------|---------------|---------------------------|
| 2025-01-01 Confraternização | ✓ | ✓ | ✓ |
| 2025-03-03 Carnaval | ✓ | ✓ | ✓ |
| 2025-03-04 Carnaval | ✓ | ✓ | ✓ |
| 2025-04-18 Sexta Santa | ✓ | ✓ | ✓ |
| 2025-04-21 Tiradentes | ✓ | ✓ | ✓ |
| 2025-05-01 Trabalho | ✓ | ✓ | ✓ |
| 2025-06-19 Corpus | ✓ | ✓ | ✓ |
| **2025-09-07 Independência (DOM)** | ✗ (omitido) | ✓ | ✓ |
| **2025-10-12 Aparecida (DOM)** | ✗ (omitido) | ✓ | ✓ |
| **2025-11-02 Finados (DOM)** | ✗ (omitido) | ✓ | ✓ |
| **2025-11-15 Proclamação (SÁB)** | ✗ (omitido) | ✓ | ✓ |
| 2025-11-20 Consciência Negra | ✓ | ✓ | ✓ |
| **2025-12-24 Véspera Natal** | ✓ | ✗ | ✓ |
| 2025-12-25 Natal | ✓ | ✓ | ✓ |
| **2025-12-31 Véspera Ano Novo** | ✓ | ✗ | ✓ |

União final 2025 (15 feriados full-day): coincide com calendário oficial B3 ampliado com pontos facultativos.

---

## 8. Referências

- `src/data_downloader/validation/holidays_dat_parser.py` — parser
- `src/data_downloader/validation/calendar_b3.py` — consumer + fallback
- `tests/unit/test_holidays_dat_parser.py` — testes parser
- `tests/unit/test_calendar_b3_extended.py` — ground truth 2020-2030
- `tests/integration/test_calendar_b3_holidays_dat.py` — integração
- `docs/storage/INTEGRITY.md` §6 (M17 DST policy ≥ 2020)
- `docs/storage/CONTRACTS.md` §0 (`validation_source` enum)
- `docs/decisions/COUNCIL-16-holidays-dat-integration.md` — registro mini-council
- `docs/dll/PROFITDLL_KNOWLEDGE.md` — referência DLL

---

## 9. Open questions

- **Q16-OPEN:** Faltam exchange codes 35/88/99 distinguidos no manual oficial? Ainda não documentado pela Nelogica. Sugerido para `Nelo *probe-manual` futuro com Nelogica diretamente.

— Nelo, formato decifrado.
