# COUNCIL-07 — Contract Calendar Design Decisions (Story 1.6)

> Mini-council autônomo (Sol + Nelo + Quinn, claude-opus-4-7) durante
> a gate da Story 1.6 em 2026-05-04. Modo autônomo invocado via
> kickoff de Quinn — Dex marcou `Ready for Review` em commit `4f28b41`
> e a council foi convocada para formalizar três decisões implícitas
> que apareceram durante a auditoria (Sol §F-S-1, Nelo §F-N-15, Sol
> §F-S-5) — sem elas, futuras stories poderiam reverter intuições
> sem rastro.

---

## 0. Header

| Campo               | Valor                                                            |
|---------------------|------------------------------------------------------------------|
| **council_id**      | COUNCIL-07                                                       |
| **story_id**        | 1.6 (`docs/stories/1.6.story.md`)                                |
| **commit auditado** | `4f28b41` (`feat: contract calendar resolver + DLL probe + CLI`) |
| **data**            | 2026-05-04                                                       |
| **convocador**      | Quinn (qa) — gate `*qa-gate 1.6`                                 |
| **participantes**   | Sol 💾 (storage-engineer) · Nelo 🗝️ (profitdll-specialist) · Quinn 🧪 (qa) |
| **modo**            | autônomo (mental) — sem Aria (delegada implícita por cross-ref)  |
| **outputs**         | (1) ratificação 3 decisões + (2) tracking findings em Story 2.X  |

---

## 1. Contexto

Story 1.6 entregou:

- Resolver `vigent_contract(catalog, root, on_date) -> str` (lookup
  R9-compliant contra tabela `contracts` v1.0.0).
- Probe `probe_contract(dll, catalog, root, code, sample_date)` que
  delega `download_chunk` (Story 1.3) e atualiza catálogo em sucesso
  (`validation_source = 'dll_probe'`).
- CLI `data-downloader contracts {list|add|validate|vigent}`.
- Seed inicial em `docs/storage/CONTRACTS.md` (7 entradas, todas
  `hypothesized` ou `manual` — Story 1.6 valida só a engine, não o
  calendário B3 oficial).

Durante a auditoria, três decisões de design **não documentadas em ADR**
emergiram repetidamente nos comentários de Sol e Nelo. Quinn convocou
o mini-council para formalizar antes de fechar a gate.

---

## 2. Decisão D1 — Tabela `contracts` SEM coluna `exchange`

### 2.1 Problema

A tabela `contracts` v1.0.0 (SCHEMA.md §5.5, entregue por Story 1.5) NÃO
tem coluna `exchange`. A função `vigent_contract` aceita o parâmetro
mas apenas valida (`F`/`B`); `list_contracts` aceita o filtro mas não
filtra. CLI `contracts vigent` aceita `--exchange / -e` mas o valor é
silently descartado no SELECT.

Se a decisão não for ratificada, futuro Dex pode "consertar" adicionando
a coluna sem entender o trade-off.

### 2.2 Posições

**Sol 💾 (Storage):** Aceita por design. Bolsa é propriedade do USO
em V1, não do contrato — `WDOJ26` é sempre BMF/F; `PETR4` é sempre
Bovespa/B; ambiguidade real só existe para tickers raros (GLOB-2,
listings dual-exchange) que NÃO são alvo de V1. Adicionar coluna
agora seria over-engineering. Catálogo enxuto alinha com ADR-002.

**Nelo 🗝️ (DLL):** Concorda. A DLL ProfitDLL exige exchange como
parâmetro de `GetHistoryTrades` (manual §3.1 L1673), mas o operador
sempre sabe a bolsa pelo contexto do ticker. Probe usa default `"F"`
(WDO/WIN); equities usam `"B"` mas raramente são probadas (não fazem
rollover). Q05-V/R8 já valida na fronteira pública — defesa em
profundidade não precisa repetir no schema.

**Quinn 🧪 (QA):** Concorda com tracking. Risco baixo de
miscompreensão futura porque (a) parâmetro está documentado em
docstring, (b) Dev Notes explicitam, (c) audit Sol §F-S-1 + Nelo
§F-N-9 documentam.

### 2.3 Ratificação

**APROVADO unânime.** Tabela `contracts` permanece SEM `exchange` em
V1. Parâmetro `exchange` mantido nas APIs (`vigent_contract`,
`list_contracts`, CLI `vigent`) para:

1. **SemVer estável** — quando/se Story 2.X adicionar a coluna
   (cenário: cross-exchange ticker), API não muda.
2. **Validação R8/Q05-V** — fronteira pública rejeita `'BMF'`/`'BOVESPA'`/`'f'`/`'b'`
   etc.
3. **Documentação viva** — operador vê o parâmetro e sabe que bolsa
   é dimensão relevante mesmo que não filtre hoje.

### 2.4 Tracking

- **Backlog item:** ADR-006 (calendário de contratos) deve receber
  parágrafo explícito sobre essa decisão. Owner: Sol. Story: 2.X
  (`bizdays-integration` ou story dedicada `adr-update-006`).
- **F-S-3:** `list_contracts(exchange=...)` deve emitir
  `DeprecationWarning` se o parâmetro for usado em futuro próximo
  para evitar surprise. Tracking: Story 2.X.
- **F-N-1:** `contracts validate` CLI deve aceitar `--exchange` para
  alinhar com `contracts vigent`. Tracking: Story 1.7b (smoke MVP).

---

## 3. Decisão D2 — Probe usa `download_chunk` com timeout reduzido `PROBE_TIMEOUT_SECONDS = 300`

### 3.1 Problema

`probe_contract` chama `download_chunk(timeout=PROBE_TIMEOUT_SECONDS)`
com `300s` (5 min), enquanto `DEFAULT_TIMEOUT_SECONDS = 1800` (30 min)
no `download_chunk` original. Sem ratificação, futura otimização
("aumentar timeout para evitar falsos negativos") pode quebrar a
intenção semântica de probe.

### 3.2 Posições

**Nelo 🗝️ (DLL):** Aceita. Janela é 1 dia útil — pregão WDO/WIN
gera ~50k-200k trades em 9h; DLL responde em **segundos** com warm
cache. Q02-E (99% reconnect) ainda é tolerada porque
`_ProgressMonitor` (1.3) não interrompe — apenas detecta. 5 min é
folgado. Risco residual: cold-cache primeiro probe pós-init pode
chegar perto do limite — mitigação: operador re-roda
(`_mark_validated` é UPDATE simples, idempotente — re-marca apenas
timestamp).

**Sol 💾 (Storage):** Concorda. Probe é diagnóstico, não download de
produção. Falha de probe não bloqueia download (operador escolhe
outra `--sample-date`). Re-marcação idempotente via UPDATE preserva
INTEGRITY.md (sem duplicação).

**Quinn 🧪 (QA):** Concorda com tracking. Cobertura por
`tests/smoke/test_probe.py` (gated por env) prova end-to-end. Flag
CLI futura (`--timeout`) é nice-to-have.

### 3.3 Ratificação

**APROVADO unânime.** `PROBE_TIMEOUT_SECONDS = 300` é constante de
desenho; `Final[int]` em `contracts_probe.py:50`. Mudança requer:

1. Re-validação do trade-off via novo COUNCIL (DLL latência observada).
2. Atualização do docstring em `probe_contract`.
3. Smoke test re-rodado com novo timeout.

Aceitamos que probe pode falsamente falhar (`status=timeout`) em
cenários patológicos — mitigação operacional: re-roda, ou usa
`--sample-date` em data de alto volume.

### 3.4 Tracking

- **F-N-2:** Adicionar `--timeout` em CLI `contracts validate`.
  Tracking: Story 1.7b (smoke MVP onde latência real será observada).
- Considerar instrumentação `log.info("probe.duration", elapsed_s=...)`
  para coletar dados empíricos antes de qualquer ajuste futuro.

---

## 4. Decisão D3 — Parser YAML lite custom (sem PyYAML)

### 4.1 Problema

`populate_contracts_from_seed` parseia o seed YAML embutido em
`CONTRACTS.md` com regex + linha-a-linha (`_parse_seed_yaml` +
`_split_kv` em `contracts.py:421-503`) — **sem dep PyYAML**. Funciona
para o seed atual (mappings de escalares string), mas falha
silenciosamente em estruturas aninhadas (listas, maps).

Sem ratificação, futura adição de `tags: [bmf, monthly]` ou
`metadata: {source: ...}` no seed vai descartar dados sem warn.

### 4.2 Posições

**Sol 💾 (Storage):** Defende parser lite. Custo de adicionar PyYAML:
+1 dep (~250KB), +footprint pyinstaller (estimado +5-10MB),
inicialização +50ms. Benefício: zero hoje. Quando schema do seed
crescer, reabrir decisão. Política R0 (no_invention) e R5 (slim deps)
favorecem manter o parser custom.

**Nelo 🗝️ (DLL):** Neutro. Parser não toca DLL. Apenas garante que
o seed atual carrega corretamente — verificado por
`test_seed_loader_loads_default` + `test_seed_loader_is_idempotent`.

**Quinn 🧪 (QA):** Concorda com tracking. Risco silencioso é real
mas baixo (operador editando CONTRACTS.md notaria que campos novos
não aparecem). Adicionar test
`test_seed_loader_rejects_nested_yaml` (que atualmente passaria por
estar omisso) para forçar o erro explícito. Aria não foi consultada
(audit COUNCIL-07 mental); se Story 2.X precisar PyYAML, COUNCIL-06
formaliza com Aria.

### 4.3 Ratificação

**APROVADO unânime com tracking forte.** Parser YAML lite custom é
mantido em V1. Trigger para revisitar:

1. Seed precisa de listas/maps aninhados.
2. Operador externo (não-dev) começa a editar CONTRACTS.md.
3. Footprint atual permitir +PyYAML sem regressão.

### 4.4 Tracking

- **F-S-5:** Adicionar test
  `tests/unit/test_seed_loader.py::test_seed_loader_rejects_nested_yaml`
  que verifica `ValueError` em estrutura aninhada (em vez de
  silently descartar). Tracking: Story 2.X.
- **F-S-5+:** COUNCIL-06 a ser convocado por Aria + Sol + Pyro
  quando o trigger acima ativar. Decisão: PyYAML vs ruamel.yaml vs
  parser estendido.

---

## 5. Findings consolidados (cross-ref auditorias)

| ID gate Quinn | Cross-ref Sol | Cross-ref Nelo | Severidade | Tracking |
|---------------|---------------|----------------|------------|----------|
| F-Q-1 — `--exchange` flag CLI `validate` | F-S-1 (decisão D1) | F-N-1 | LOW | Story 1.7b |
| F-Q-2 — Vigência B3 oficial pendente | F-S-2 | (n/a) | LOW | Story 2.X (`bizdays-integration`) |
| F-Q-3 — `populate_*` reseta `validated_at` | F-S-4 | (n/a) | LOW | Story 2.X (flag `--preserve-validated`) |
| F-Q-4 — `_resolve_sample_date` ignora B3 | F-S-6 | F-N-3 | LOW | Story 2.X |
| F-Q-5 — Parser YAML lite (decisão D3) | F-S-5 | (n/a) | LOW | Story 2.X (test rejeição) + COUNCIL-06 futuro |
| F-Q-6 — `PROBE_TIMEOUT_SECONDS` (decisão D2) | (n/a) | F-N-2 | INFO | Story 1.7b (`--timeout` CLI) |
| F-Q-7 — Janela 09:00..18:00 hardcoded | (n/a) | F-N-4 | INFO | tracking opcional |
| F-Q-8 — Probe quota Nelogica | (n/a) | F-N-5 | INFO | Story 2.X (probe-em-massa back-off) |
| F-Q-9 — `list_contracts(exchange=...)` ignorado | F-S-3 | (n/a) | LOW | Story 2.X (DeprecationWarning) |
| F-Q-10 — `probe_contract.symbol_root` não validado vs `code` | F-S-7 | (n/a) | LOW | Story 2.X (defesa em profundidade) |

**Total:** 5 LOW + 5 INFO. **0 CRITICAL, 0 HIGH, 0 MEDIUM.**

---

## 6. Endorsements

| Agente | Endorsement | Nota |
|--------|-------------|------|
| **Sol 💾** | ✅ APPROVED | Decisões D1/D2/D3 ratificadas. Tracking F-S-1..F-S-7 alinhado. |
| **Nelo 🗝️** | ✅ APPROVED | D1/D2 não violam R3/INV-1 nem manual ProfitDLL. Tracking F-N-1..F-N-5. |
| **Quinn 🧪** | ✅ APPROVED | Gate `*qa-gate 1.6` PASS condicionada a este COUNCIL formalizado. |
| **Aria 🏛️** | (deferred, mental endorsement) | Cross-ref ADR-002 (catálogo enxuto) e ADR-006 (calendário). Sol+Nelo concordam que decisão D1 não cruza fronteira de design crítica; ADR update é tracking opcional. COUNCIL-06 (PyYAML) a ser convocado se trigger ativar. |

---

## 7. Próximos passos

1. **Quinn:** fecha gate Story 1.6 com PASS (registrado em
   `docs/decisions/STORY_GATES_2026-05-04.md` + `docs/qa/QA_REPORTS/1.6-2026-05-04.md`).
2. **Dex (Story 1.7a):** consome `vigent_contract` como pre-step de
   cada chunk multi-symbol — fecha **Q01-V end-to-end**.
3. **Dex (Story 1.7b):** roda smoke real
   `data-downloader contracts validate WDO WDOJ26` com creds
   Nelogica; preenche `validation_source = 'dll_probe'` no catálogo de
   produção. Adiciona `--exchange` flag (F-N-1/F-Q-1).
4. **Sol (Story 2.X — `bizdays-integration`):** integra `holidays.dat`
   Nelogica via pandas (alinha COUNCIL-04). Atualiza seed para
   `validation_source = 'b3_calendar'`. Fecha F-Q-2/F-Q-4.
5. **Aria (futuro):** COUNCIL-06 se trigger PyYAML ativar (F-Q-5).

---

— Sol 💾 · Nelo 🗝️ · Quinn 🧪
