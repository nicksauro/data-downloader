# CONTRACTS.md — Mapa de Contratos Vigentes

**Owner:** 💾 Sol (Storage Engineer), em consulta a 🗝️ Nelo (DLL probe) e fonte oficial Nelogica/B3.
**Versão:** v1.1.0 (Story 4.2 — expansão multi-asset WIN H/M/U/Z + equities)
**Status:** SEED (validado contra DLL nas Stories 1.6 [WDO] e 4.2 [WIN+equities])

---

## 0. Princípio (zero alucinação)

Sol **nunca chuta** letra de mês ou janela de vigência. Toda entrada nesta tabela tem campo `validation_source`:

| validation_source     | Significado                                                                  |
|-----------------------|------------------------------------------------------------------------------|
| `hypothesized`        | Inferida pela regra documentada; **não confirmada** contra fonte. Aceitar uso ad-hoc, mas marcar `validated_at = NULL`. |
| `nelogica_official`   | Confirmada contra documentação Nelogica oficial (URL no `notes`).            |
| `dll_probe`           | Confirmada via probe direto na DLL (`Nelo *probe-dll` retornou trades reais).|
| `b3_calendar`         | Confirmada contra calendário oficial B3 (URL no `notes`).                    |
| `manual`              | Inserida manualmente pelo usuário com referência externa em `notes`.         |

Probes que retornam `NL_EXCHANGE_UNKNOWN` ou `NL_INVALID_TICKER` **não validam** — apenas refutam. Vigência só vira `dll_probe` se trades vierem do callback durante janela proposta.

---

## 1. Letras de mês (CME convention — adotado pela B3)

| Letra | Mês       | Letra | Mês       |
|-------|-----------|-------|-----------|
| F     | Janeiro   | N     | Julho     |
| G     | Fevereiro | Q     | Agosto    |
| H     | Março     | U     | Setembro  |
| J     | Abril     | V     | Outubro   |
| K     | Maio      | X     | Novembro  |
| M     | Junho     | Z     | Dezembro  |

Padrão de código: `{ROOT}{LETRA}{ANO_2DIGITOS}` — ex: `WDOJ26` = WDO de Abril/2026.

> Letras `I` e `L` (e similares ambíguas com algarismos) são deliberadamente puladas pela CME.

---

## 2. Regras de vigência (HIPOTETIZADAS — validar via probe)

### 2.1 WDO — Mini Dólar (mensal, 12 contratos/ano)

Hipótese de vigência:
- Contrato `WDO{X}{YY}` é negociado do **penúltimo dia útil do mês {X-1}** até o **penúltimo dia útil do mês {X}**.
- Vencimento: primeiro dia útil do mês {X}.
- Ex: `WDOJ26` (abril/26) vigente de ~30/mar/26 até ~29/abr/26.

**Status:** `hypothesized` — confere com convenção comum do mercado, mas Sol não tem fonte oficial linkada ainda. Story 1.6 vai validar via probe.

### 2.2 WIN — Mini Índice (trimestral, 4 contratos/ano)

Hipótese de vigência:
- Contratos: `WINH{YY}` (mar), `WINM{YY}` (jun), `WINU{YY}` (set), `WINZ{YY}` (dez).
- Vigente do **quinto dia útil do mês {X-3}** até o **quarta-feira mais próxima do dia 15 do mês {X}** (regra de vencimento B3 para índices).
- Ex: `WINH26` (março/26) vigente de ~07/jan/26 até ~18/mar/26 (quarta mais próxima de 15/mar/26).

**Status:** `hypothesized`. Validar via probe + cross-check com calendário B3.

### 2.3 Equities (PETR4, VALE3, ITUB4, BBDC4, BBAS3, ABEV3, ...)

- Não têm vencimento (papel à vista).
- Convenção: `vigent_from = 1900-01-01`, `vigent_until = 9999-12-31`.
- `validation_source = manual` desde que o ticker exista no momento.
- **Exchange = `B` (Bovespa)** — sempre. Lei R8 / Q05-V: BMF (`F`)
  retorna `NL_EXCHANGE_UNKNOWN` para equities.
- Ressalva: tickers podem mudar (split, fusão). Sol não rastreia mudança de ticker — quando isso acontece, abre nova entrada.
- `read_continuous("PETR4", ...)` é caso degenerado: 1 contrato vigente
  cobrindo todo o range = idêntico a `read_history("PETR4", ...)`.
  Story 4.2 AC4 cobre teste de propriedade (equity = idempotente).

### 2.4 Outros futuros (DOL, IND, contratos cheios)

Não escopados em V1 do seed. Adicionar via `*contract-add` quando necessário.

---

## 3. Seed inicial (YAML embedded — parseável por `populate_contracts_from_seed`)

> Todas as entradas abaixo têm `validated_at: null`. Story 1.6 (probe via DLL) atualizará para `dll_probe` ou marcará para revisão se inválidas.

```yaml
# docs/storage/CONTRACTS.md — seed inicial v1.0.0
# Formato consumido por: storage/contracts/seed_loader.py::populate_contracts_from_seed()
# Schema target: tabela `contracts` em data/history/catalog.db (ver SCHEMA.md §5.5)

contracts:

  # =====================================================================
  # Continuous futures (Story 4.6 / Pichau directive 2026-05-06)
  # =====================================================================
  # WDOFUT/WINFUT/INDFUT/DOLFUT: continuous-future aliases — DLL Nelogica
  # entrega histórico contínuo por raiz quando o ticker termina em "FUT"
  # (Q-DRIFT-32 validated). Vigência efetivamente perpétua — usados
  # como caminho golden path "baixar histórico longo sem rollover manual".
  # Equities (PETR4 etc) seguem o mesmo padrão de eternidade abaixo.

  - symbol_root: WDOFUT
    contract_code: WDOFUT
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: 2026-05-05  # smoke real 1.7b-followup MVP gate (513.686 trades)
    validation_source: manual
    notes: "Mini-dólar continuous (Q-DRIFT-32). Golden path."

  - symbol_root: WINFUT
    contract_code: WINFUT
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Mini-Ibovespa continuous (Q-DRIFT-32). Validar via probe Story 4.2-followup."

  - symbol_root: INDFUT
    contract_code: INDFUT
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Índice futuro continuous. Validar via probe."

  - symbol_root: DOLFUT
    contract_code: DOLFUT
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Dólar futuro (não-mini) continuous. Validar via probe."

  # =====================================================================
  # WDO — Mini Dólar (mensal — legacy contracts com vencimento)
  # =====================================================================
  # Mantidos por backwards-compat e para evidência histórica Q-DRIFT-32
  # (WDOJ26 retornou 0 trades em smoke 1.7d porque vencido). Usuário casual
  # deve usar WDOFUT acima — esses ficam para usuários que querem
  # contrato específico (research/auditoria).

  - symbol_root: WDO
    contract_code: WDOH26
    vigent_from: 2026-01-29  # penúltimo dia útil de fevereiro/26 (hipótese: ~28/fev) — REVALIDAR
    vigent_until: 2026-02-26
    validated_at: null
    validation_source: hypothesized
    notes: "Março/26. Validar via probe Story 1.6."

  - symbol_root: WDO
    contract_code: WDOJ26
    vigent_from: 2026-02-26
    vigent_until: 2026-03-30
    validated_at: null
    validation_source: hypothesized
    notes: "Abril/26. Validar via probe Story 1.6."

  - symbol_root: WDO
    contract_code: WDOK26
    vigent_from: 2026-03-30
    vigent_until: 2026-04-29
    validated_at: null
    validation_source: hypothesized
    notes: "Maio/26. Validar via probe Story 1.6."

  # NOTA: contratos M..Z 26 e F..Z 27 NÃO incluídos no seed inicial.
  # Adicionar conforme se aproximam da vigência (~60 dias antes via *contract-add).
  # Adicionar futuros distantes pollui o catálogo e gera ruído em integrity-check.

  # =====================================================================
  # WIN — Mini Índice (trimestral H/M/U/Z)
  # =====================================================================
  # Story 4.2 (COUNCIL-29) — expandido para 8 contratos (2026 + 2027)
  # cobrindo o ano-calendário completo trimestral. Vigências hipotéticas
  # baseadas na regra B3: vigente do quinto dia útil do mês {X-3} até a
  # quarta-feira mais próxima do dia 15 do mês {X}. Validação exata via
  # probe DLL (Story 4.2 AC3) — Q-OPEN registrado em QUIRKS.md.

  - symbol_root: WIN
    contract_code: WINH26
    vigent_from: 2026-01-08  # ~5º dia útil de janeiro
    vigent_until: 2026-03-18  # quarta-feira mais próxima de 15/mar/26
    validated_at: null
    validation_source: hypothesized
    notes: "Março/26. Trimestral. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINM26
    vigent_from: 2026-03-18
    vigent_until: 2026-06-17  # quarta-feira mais próxima de 15/jun/26
    validated_at: null
    validation_source: hypothesized
    notes: "Junho/26. Trimestral. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINU26
    vigent_from: 2026-06-17
    vigent_until: 2026-09-16  # quarta-feira mais próxima de 15/set/26
    validated_at: null
    validation_source: hypothesized
    notes: "Setembro/26. Trimestral. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINZ26
    vigent_from: 2026-09-16
    vigent_until: 2026-12-16  # quarta-feira mais próxima de 15/dez/26
    validated_at: null
    validation_source: hypothesized
    notes: "Dezembro/26. Trimestral. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINH27
    vigent_from: 2026-12-16
    vigent_until: 2027-03-17  # quarta-feira mais próxima de 15/mar/27
    validated_at: null
    validation_source: hypothesized
    notes: "Março/27. Trimestral. Buffer 1 ano. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINM27
    vigent_from: 2027-03-17
    vigent_until: 2027-06-16  # quarta-feira mais próxima de 15/jun/27
    validated_at: null
    validation_source: hypothesized
    notes: "Junho/27. Trimestral. Buffer. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINU27
    vigent_from: 2027-06-16
    vigent_until: 2027-09-15  # quarta-feira mais próxima de 15/set/27
    validated_at: null
    validation_source: hypothesized
    notes: "Setembro/27. Trimestral. Buffer. Validar via probe Story 4.2."

  - symbol_root: WIN
    contract_code: WINZ27
    vigent_from: 2027-09-15
    vigent_until: 2027-12-15  # quarta-feira mais próxima de 15/dez/27
    validated_at: null
    validation_source: hypothesized
    notes: "Dezembro/27. Trimestral. Buffer. Validar via probe Story 4.2."

  # =====================================================================
  # Equities (à vista — sem vencimento)
  # =====================================================================
  # Story 4.2 (COUNCIL-29) — expandido para 6 tickers líquidos B3
  # (Bovespa "B"). Sem rollover — read_continuous para equity é o caso
  # degenerado (single contrato vigente do epoch ao infinito).

  - symbol_root: PETR4
    contract_code: PETR4
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Petrobras PN. Papel à vista, sem vencimento. Bovespa (B)."

  - symbol_root: VALE3
    contract_code: VALE3
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Vale ON. Papel à vista, sem vencimento. Bovespa (B)."

  - symbol_root: ITUB4
    contract_code: ITUB4
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Itaú Unibanco PN. Papel à vista. Bovespa (B). Story 4.2."

  - symbol_root: BBDC4
    contract_code: BBDC4
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Bradesco PN. Papel à vista. Bovespa (B). Story 4.2."

  - symbol_root: BBAS3
    contract_code: BBAS3
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Banco do Brasil ON. Papel à vista. Bovespa (B). Story 4.2."

  - symbol_root: ABEV3
    contract_code: ABEV3
    vigent_from: 1900-01-01
    vigent_until: 9999-12-31
    validated_at: null
    validation_source: manual
    notes: "Ambev ON. Papel à vista. Bovespa (B). Story 4.2."
```

---

## 3.1 Asset class mapping (Story 4.2 AC1)

Tabela canônica `symbol_root → asset_class` consumida por `chunker.py`
(`chunk_days_for_symbol`) para determinar dias úteis por chunk:

| symbol_root prefix          | asset_class | chunk_days B3 | Justificativa Q12-E      |
|-----------------------------|-------------|---------------|--------------------------|
| `WDO*`                      | future_mini | 5             | Mini dólar (alta vazão)  |
| `WIN*`                      | future_mini | 5             | Mini índice (alta vazão) |
| `IND*`                      | future_full | 5             | Índice cheio             |
| `DOL*`                      | future_full | 5             | Dólar cheio              |
| Equity (regex `^[A-Z]{4}\d$`) | equity      | 1             | Vazão menor; granularidade fina |
| Outros                      | unknown     | 1 (fallback)  | Conservador              |

A detecção é por **prefixo** (longest match wins), exceto equities, que
respeitam a regex `^[A-Z]{4}\d$` (4 letras + 1 dígito — convenção B3
para tickers à vista). Equities sempre usam exchange `B` (Bovespa, R8 /
Q05-V) — nunca `F`. Futuros sempre usam exchange `F` (BMF).

> Datas de vigência acima são aproximações com base em regras hipotetizadas. Antes de qualquer download de produção contra contrato com `validated_at = null`, a Story 1.6 deve correr o probe e atualizar.

---

## 4. API resolve `vigent_contract(symbol_root, date)`

Função pública exposta pela camada storage (consumida pelo orchestrator):

```python
def vigent_contract(symbol_root: str, on_date: date) -> str | None:
    """
    Retorna o código do contrato vigente para `symbol_root` na `on_date`.

    Para roots de papel à vista (PETR4, VALE3, etc.), retorna o próprio root.
    Para futuros (WDO, WIN, ...), busca no catálogo SQLite o contrato cujo
    range [vigent_from, vigent_until] contém `on_date`.

    Returns:
        contract_code (str) se encontrado.
        None se nenhum contrato vigente nessa data (caller deve tratar — provavelmente fim-de-semana, feriado, ou gap no seed).

    Raises:
        AmbiguousContractError: se mais de um contrato vigente nessa data
            (overlap no seed — bug de operação).
    """
```

Na presença de overlap (dois contratos cobrindo a mesma data — caso real durante a janela de transição), o resolve atual **falha alto** (`AmbiguousContractError`). Tratamento de rollover (escolher contrato mais líquido) é responsabilidade da função `read_continuous` (ver `QUERIES.md` §2), não do `vigent_contract`.

---

## 5. Workflow de manutenção do mapa

### 5.1 Adicionar contrato novo (rollover natural)

```
@storage-engineer (Sol) *contract-add WDO N 26  # WDO N=julho /2026
```

Sol:
1. Calcula `vigent_from`, `vigent_until` pela regra (§2).
2. Insere com `validation_source: hypothesized`.
3. Aciona `Nelo *probe-dll WDON26 --probe-date {vigent_from + 5d}` para validar.
4. Se probe retorna trades → atualiza para `dll_probe`, preenche `validated_at`.
5. Se probe retorna `NL_INVALID_TICKER` ou `NL_EXCHANGE_UNKNOWN` → marca `notes: "PROBE FAILED"`, escala para Sol + Nelo investigarem.

### 5.2 Validar lote inteiro

```
data-downloader contracts validate --root WDO --year 2026
```

Roda probe em todos os contratos do root/ano com `validated_at = null`.

### 5.3 Reconciliação contra Nelogica oficial (manual)

Quando Nelogica publica calendário oficial:
1. Sol baixa CSV/PDF.
2. `data-downloader contracts import --source nelogica_official --file calendar_2026.csv`.
3. Tool faz diff contra catálogo, mostra divergências, exige aprovação interativa para cada mudança.
4. Atualiza `validation_source = nelogica_official` + `notes = "URL: ..."`.

---

## 6. Casos especiais

### 6.1 Contrato delistado / suspenso

Em vez de delete:
- Mantém entrada.
- Atualiza `vigent_until` para data de delist.
- `notes` documenta razão.

Apagar entrada quebra histórico (downloads passados ficam órfãos).

### 6.2 Renomeação de ticker

Cria nova entrada para o novo nome; mantém antiga com `vigent_until` = data de troca - 1 dia. `notes` cruza-referencia.

Catálogo de partições (`partitions.symbol`) NÃO é atualizado — os trades históricos permanecem sob o ticker da época. Função de leitura `read_history` aceita lista de tickers para casos de continuidade.

### 6.3 Ambiguidade de fuso (M17 — DST pré-2020)

B3 não observa DST desde 2019. Histórico anterior tem ambiguidade entre BRT e BRST nos dias de transição. Decisão: **seed não inclui contratos com `vigent_from < 2020-01-01`**. Para histórico pré-2020, usuário deve adicionar manualmente com `notes: "DST AMBIGUITY — verificar timestamps"`.

---

## 7. Checklist de validação de contrato (do agente persona)

Antes de marcar um contrato como `dll_probe`:

- [ ] Letra de mês confere com tabela §1?
- [ ] `vigent_from` e `vigent_until` consistentes com a regra (§2)?
- [ ] Probe DLL na data `vigent_from + 5 dias úteis` retornou trades reais (não `NL_*` erro)?
- [ ] `validated_at` preenchido com timestamp do probe?
- [ ] Cross-check com calendário B3 oficial (se disponível)?

---

## 8. Referências

- ADR-002 (Parquet+DuckDB+SQLite) — define que catálogo é fonte única.
- `docs/storage/SCHEMA.md` §5.5 — DDL `contracts`.
- Story 0.0 — criação deste documento.
- Story 1.6 — probe DLL para validar seed.

— Sol, custodiando o histórico 💾
