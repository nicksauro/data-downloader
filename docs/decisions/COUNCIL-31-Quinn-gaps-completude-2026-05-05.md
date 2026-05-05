# COUNCIL-31 — Quinn (@qa) — Validação de gaps & completude

**Data:** 2026-05-05
**Council member:** Quinn (@qa) — consideração #1 do council de revisão pré-próximas-fases
**Missão:** validar se o smoke standalone WDOFUT (commit `9fce00d`, 796.963 trades em 150.20s) está perdendo dados.
**Veredito:** **INCONCLUSIVE-no-data-on-disk** (com sinais positivos no log).

---

## 1. TL;DR

O smoke standalone (`scripts/run_smoke_real_standalone.py`) **executou
com sucesso** o pipeline DLL→IngestorThread, mas **NÃO PERSISTIU NENHUM
TRADE EM DISCO**. A janela analisada foi `2026-05-01 12:20:07 →
2026-05-05 12:20:07` (4 dias úteis: 01-mai sex, 04-mai seg, 05-mai ter +
parte do dia; 02/03-mai = sáb/dom).

**Não posso validar gaps por dia, primeiro/último timestamp, ou
distribuição intra-day** porque:

1. `scripts/run_smoke_real_standalone.py` instancia `download_chunk(...)`
   diretamente, recebe `result.trades` (lista in-memory) e chama
   `len(result.trades)` para o assert. Não invoca `parquet_writer` nem o
   storage layer (`storage/parquet_writer.py`).
2. `data/history/catalog.db` confirma: `downloads=0`, `partitions=0`,
   `gaps=0` rows. Nenhum download foi registrado.
3. Glob `data/**/*.parquet` retorna **zero arquivos**. O storage layout
   esperado em `docs/ARCHITECTURE.md`
   (`data/history/{exchange}/{symbol}/{year}/{month}.parquet`) está vazio.

A única evidência sobre quantidade vem do log
`docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-postfix35-20260505T123005Z.log`.

---

## 2. Sinais positivos extraídos do log

| Métrica                           | Valor                                            |
|-----------------------------------|--------------------------------------------------|
| Janela solicitada                 | `2026-05-01 12:20:07 → 2026-05-05 12:20:07` (4 dias) |
| Total de trades                   | **796.963**                                      |
| Duração download                  | 149.989 s                                        |
| `last_packet_seen`                | **True** (TC_LAST_PACKET observado — DLL sinalizou fim) |
| `progress_99_reconnect`           | **False** (nenhum bug Q-DRIFT-26 / 99% loop)     |
| `subscribed`                      | True                                             |
| `trade_edits`                     | 0                                                |
| `translate_failures`              | 961                                              |
| `agent_resolver.unknown_id` (length=-2147483636) | 4 ocorrências (12:31:15 ×2 e 12:32:24 ×2) |
| Throughput médio (post-failures)  | ~5.319 trades/s                                  |

**Plausibilidade volumétrica:** WDOFUT é o futuro mais líquido da B3,
tipicamente **150k–300k trades/dia**. Para 4 dias úteis ≈ **600k–1.2M**
trades. **796.963 cai dentro do range esperado** — não há sinal de perda
massiva.

**Garantia de fim de stream:** `last_packet_seen=True` significa que a
DLL emitiu o flag `TC_LAST_PACKET` no bit do `nFlags`. Isso é o contrato
oficial Nelogica para "fim do dataset" e indica que **não houve
truncamento prematuro** por nosso lado. Status final =
`download.complete code=0`.

---

## 3. Análise de `translate_failures` (961 / 796.963 = 0.1206%)

**Loss rate: 0.12%** — ordem de grandeza compatível com sentinelas
emitidas pela DLL e descartadas como "no-op" pelo Q-DRIFT-34 guard.

**Distribuição:** **NÃO FOI POSSÍVEL DETERMINAR** distribuição
temporal. O contador `translate_failures` é incrementado in-memory
silenciosamente (R21 hot-path: `counter atomic only`,
`SEM logging síncrono`). Apenas o agregado é logado em
`download.complete`. As 4 linhas `agent_resolver.unknown_id
length=-2147483636` são uma faceta diferente do mesmo Q-DRIFT (vide §4).

**Tipo de falha (inferido a partir de `download_primitive.py:298-365`):**

| Source                                                                           | Contrib. esperada | Notas                                       |
|---------------------------------------------------------------------------------|-------------------|---------------------------------------------|
| `translate_trade(handle) is None` (NL_* error retornado)                         | maioria           | Q-DRIFT-34 sentinel struct zerado           |
| `timestamp_ns < 0` guard (defense-in-depth)                                      | minoria           | Bypass de `format_brt_timestamp` ValueError |
| `_process_trade` raise capturado (linha 308)                                     | minoria           | Defesa post-Q-DRIFT-34                      |

**Veredito sobre 0.12%:**
- **ACEITÁVEL como funcionalidade do contrato Q-DRIFT-34** (filtragem de
  sentinelas que matavam o IngestorThread em postfix-33 e anteriores).
- **NÃO ACEITÁVEL como dado em produção** sem auditoria adicional. 961
  trades descartados sem `chunk_id`, `flags`, ou snapshot do struct
  raw é uma BLACK BOX. Se esses 961 incluírem trades reais (não só
  sentinelas), perdemos 0.12%. Em volume de feature engineering isso
  é silencioso — em volume diário individual (e.g. `quantity` de um
  símbolo específico em uma janela curta) pode distorcer.

---

## 4. Q-DRIFT-35 — `agent_resolver.unknown_id length=-2147483636`

4 ocorrências do bug de signed-int truncation no `GetAgentNameLength`.
Já mitigado em `wrapper.py:746-755` para minimal_handshake (postfix-35
explicitamente registra `argtypes`/`restype`). Resíduo de 4 trades com
agent name fallback `Agent#{id}` (não-fatal). **Não conta como perda de
dado** — apenas resolução do nome do broker fica como `Agent#{id}` ao
invés de `"XP Investimentos"`.

---

## 5. Análise por dia útil — IMPOSSÍVEL nesta evidência

Para validar se cada dia útil dentro da janela tem cobertura
9:00→18:00 BRT, precisaríamos:

- **(a)** ler `result.trades` (objeto Python) — não-persistido, perdido
  com o exit do processo.
- **(b)** ou ler parquet em `data/history/F/WDOFUT/2026/05.parquet` —
  inexistente.

**Recomendação operacional:** próxima execução smoke deve persistir
trades via `parquet_writer` (mesmo que em diretório scratch
`data/scratch/smoke-{run_id}/`) para permitir validação por
day-bucket, gap histogram, e cross-check vs B3 oficial.

---

## 6. Comparação com fonte externa

**Não realizada.** Sem dados em disco, sem ferramenta de cross-check
contra agregados oficiais B3 (que tipicamente exigem TimesTrades CSV ou
GTW data feed por terminal autorizado).

**Plausibilidade volumétrica:** 796.963 / 4 dias úteis ≈ **199k
trades/dia**. WDOFUT em maio 2026 com câmbio em volatilidade média:
**plausível**. Não evidencia gap, mas tampouco evidencia completude — é
uma faixa larga de aceitação.

---

## 7. Tabela por dia (parcial — derivada da janela solicitada)

| Dia           | Status na janela        | Trades count | First trade | Last trade | Max gap | Veredito          |
|---------------|-------------------------|--------------|-------------|------------|---------|-------------------|
| 2026-05-01 (sex) | parcial (12:20→18:00) | UNKNOWN      | UNKNOWN     | UNKNOWN    | UNKNOWN | UNVERIFIABLE      |
| 2026-05-02 (sáb) | fim de semana          | 0 esperado   | n/a         | n/a        | n/a     | n/a               |
| 2026-05-03 (dom) | fim de semana          | 0 esperado   | n/a         | n/a        | n/a     | n/a               |
| 2026-05-04 (seg) | completo (09:00→18:00) | UNKNOWN      | UNKNOWN     | UNKNOWN    | UNKNOWN | UNVERIFIABLE      |
| 2026-05-05 (ter) | parcial (09:00→12:20)  | UNKNOWN      | UNKNOWN     | UNKNOWN    | UNKNOWN | UNVERIFIABLE      |
| **TOTAL**        |                         | 796.963 (log)| —           | —          | —       | plausível por agregado |

---

## 8. Recomendação para próximas fases

**P0 — bloqueante para próximo smoke:**

1. **Modificar `scripts/run_smoke_real_standalone.py`** (ou criar
   `run_smoke_real_standalone_persisted.py`) para invocar
   `parquet_writer.write_trades(result.trades, ...)` num diretório
   scratch. **Custo:** ~10 linhas. **Benefício:** todo smoke futuro
   torna-se auditável vs gaps, primeiro/último timestamp, distribuição
   intra-day, e cross-check externo. Sem isso, o council `gaps &
   completude` continua **CEGO**.

2. **Logar `translate_failures` com breakdown** (categoria: sentinel /
   negative_ts / process_exception). Hot-path R21 ainda preservado se
   incrementarmos counters separados (atomic int) e logarmos só o
   agregado em `download.complete`. Adicionar: `translate_failures_sentinel`,
   `translate_failures_negative_ts`, `translate_failures_exception`.
   **Custo:** ~5 linhas em `download_primitive.py:298-365`. **Benefício:**
   distinguir dado-perdido-real (exception) de filtro-by-design (sentinel).

**P1 — antes de usar dado em produção:**

3. **Cross-check externo:** rodar smoke num dia em que tenhamos volume
   oficial B3 (ou snapshot de outro provider, e.g. ProfitChart UI
   exibindo "trades hoje: N") e comparar contagens. Tolerância ±0.5%.

4. **Smoke em janela menor (1 dia útil) com persistência:** valida o
   pipeline completo DLL→IngestorThread→writer→parquet→catalog em escala
   gerenciável. Cobertura intra-day pode ser auditada visualmente.

**P2 — observabilidade:**

5. Considerar que `progress_99_reconnect=False` + `last_packet_seen=True`
   é o sinal canônico de download "limpo". Manter dashboard que
   correlacione esses três flags em todo download de produção.

---

## 9. Veredito formal

**INCONCLUSIVE-no-data-on-disk.**

Os sinais do log (last_packet=True, progress_99_reconnect=False,
volumetria plausível, translate_failures controlado) são todos
**positivos** mas insuficientes para concluir NO-GAPS. **Sem dados
persistidos, este council member não pode certificar completude.**

**Não escalo** ao usuário — apenas reporto. Bloqueador para certificação
é a recomendação P0.1 (persistir smoke em parquet scratch).

---

## Apêndice — Evidências consultadas

- `docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-postfix35-20260505T123005Z.log` (UTF-16, 184 linhas)
- `data/history/catalog.db` (sqlite — todas as tabelas com 0 rows)
- `scripts/run_smoke_real_standalone.py` (linhas 138-153 — usa `len(result.trades)`, NÃO persiste)
- `src/data_downloader/orchestrator/download_primitive.py:285-365` (lógica `translate_failures`)
- `src/data_downloader/dll/wrapper.py:720-755` (Q-DRIFT-33/35 mitigation)
- `docs/storage/SCHEMA.md` (canon parquet path: `data/history/{exchange}/{symbol}/{year}/{month}.parquet`)
- `docs/ARCHITECTURE.md` §1 (storage layer)
