# ADR-025 — Parquet-per-day layout HÍBRIDO com auto-compactação mensal

- **Status:** Accepted (v1.3.0)
- **Date:** 2026-05-13
- **Author:** Aria (@architect) + Sol (@data-engineer)
- **Driver:** Pichau directive "vamos fazer o possível para a nova v ser excepcional" (2026-05-13)
- **Supersedes:** ADR-004 (partition layout) — partition layout passa de "puramente mensal" para "híbrido diário/mensal compactado"

---

## 1. Contexto

A v1.2.0 escrevia partições mensais (`{ex}/{sym}/{YYYY}/{MM}.parquet`) usando o ciclo *read–merge–rewrite* a cada chunk diário: para cada novo dia útil baixado, lê o `MM.parquet` existente, concatena com os novos trades, reordena, reescreve. Pior caso N(N+1)/2 escritas para baixar um mês inteiro — para uma WDOFUT mensal real (~10–13M trades) o terceiro dia já paga 30M+ rows reescritos. Pyro mediu o overhead em **+2.35h por símbolo por 7 anos** apenas neste laço.

Pichau decidiu (2026-05-13) substituir o layout por uma estratégia HÍBRIDA:

- **Write sempre diário** (`{DD}.parquet`, *write-once*, sem read-merge-rewrite). Elimina o O(N²).
- **Auto-compactação mensal** quando o último dia útil do mês fecha *e* todos os outros dias úteis daquele mês já estão como diários: lê os ~20 diários, escreve `MM.parquet`, deleta os diários.
- **Read** via DuckDB com `parquet_scan('history/**/*.parquet')` — lê os dois formatos juntos transparentemente.
- **Migração** v1.2→v1.3 *não converte* parquets mensais existentes: eles já são exatamente o formato final pós-compactação. Apenas bump de `CATALOG_VERSION` + delta SQL para a coluna `day`.

## 2. Decisão

### 2.1 Path canônico

| Tipo | Path | Quando |
|------|------|--------|
| Partição diária parcial | `{data_dir}/history/{ex}/{sym}/{YYYY}/{MM}/{DD}.parquet` | Imediatamente após `_process_chunk` (1 chunk = 1 dia útil B3) |
| Partição mensal compactada | `{data_dir}/history/{ex}/{sym}/{YYYY}/{MM}.parquet` | Pós auto-compact ao fechar o mês útil; OU já existente legacy v1.2.x |

`partitions` SQL ganha coluna `day INTEGER NULL CHECK(day IS NULL OR (day BETWEEN 1 AND 31))`:
`day IS NULL` ⇒ partição mensal compactada. `day IS NOT NULL` ⇒ partição diária parcial.

### 2.2 Escrita (`ParquetWriter.write`)

- Caminho diário (`partition.day is not None`): **write-once**, sem `_read_existing_table` + merge. Atomic via `tmp + os.replace`, SHA256 streaming, fsync. Re-baixar o mesmo dia sobrescreve atomicamente (idempotente).
- Caminho mensal (`partition.day is None`): preserva o caminho legacy de read-merge-rewrite + dedup. Usado em (a) compact_month escrevendo o mensal definitivo, (b) re-baixar mês legacy já compactado (raro mas suportado).

### 2.3 Compactação mensal (`compact_month` + `maybe_compact_month`)

Disparada após cada `register_partition` diário pelo orchestrator. Lê o `chunk_ledger` para a janela `(symbol, exchange, year, month)`; se TODOS os dias úteis B3 daquele mês têm row com `status IN ('completed','no_trades')` (`is_month_complete`), executa:

1. `INSERT INTO compactions(...) VALUES(..., started_at=now, completed_at=NULL)` — marca o início.
2. Lê os `{DD}.parquet` da pasta `{ex}/{sym}/{YYYY}/{MM}/` em ordem alfabética (= cronológica, dado padding 2-dig).
3. `pa.concat_tables` + sort por `(timestamp_ns, sequence_within_ns)` + dedup defensivo.
4. Escreve `{MM}.parquet.tmp.{uuid}`, fsync, SHA256, `os.replace` para `{MM}.parquet`.
5. DELETE batch dos `{DD}.parquet` consumidos.
6. UPSERT `partitions` com `day=NULL` (mensal); DELETE rows diárias do mesmo `(symbol,year,month)` em `partitions`.
7. `UPDATE compactions SET completed_at=now`.

`maybe_compact_month` é **idempotente**: se `MM.parquet` já existe e os diários do mês não — no-op.

### 2.4 Atomicidade da compactação

Crash no meio (`MM.parquet` escrito, diários ainda no disco):

- **Decisão:** reconcile **COMPLETA** o cleanup (deleta os diários e marca `compactions.completed_at`) sempre que detectar `compactions` com `started_at` sem `completed_at` E o `MM.parquet` existe E contém >= soma de rows dos diários remanescentes. Caso `MM.parquet` exista mas tenha menos rows que os diários (sinal de write parcial), o reconcile **REVERTE**: deleta `MM.parquet`, mantém os diários, deixa o `compactions` row marcado como `failed` para inspeção humana.
- Justificativa: completar o cleanup é seguro porque o `MM.parquet` já foi escrito atomicamente (`os.replace`); SHA256 + row_count assertam integridade. Reverter quando o `MM.parquet` é menor que a soma dos diários previne perda silenciosa.

### 2.5 Leitura

`DuckDBReader._glob_pattern` e `continuous_reader._glob_pattern` já usam `**/*.parquet` recursivo — sem mudança. Funciona transparentemente para mistura de mensais (1 nível abaixo de `{YYYY}`) e diários (2 níveis abaixo, dentro de `{YYYY}/{MM}/`).

### 2.6 Migração v1.2 → v1.3

`Catalog._apply_migrations` executa os deltas do registry quando detecta `catalog_version < 1.3.0`:

- `ALTER TABLE partitions ADD COLUMN day INTEGER NULL CHECK(day IS NULL OR (day BETWEEN 1 AND 31))`.
- `CREATE INDEX idx_partitions_symbol_ymd ON partitions(symbol, year, month, day)`.
- `CREATE TABLE compactions (symbol, exchange, year, month, started_at, completed_at NULL, error NULL, PRIMARY KEY(symbol,exchange,year,month))`.
- Bump `catalog_version='1.3.0'`.

**Parquets mensais existentes não são modificados** — entram como "já compactados" (`day=NULL`).

## 3. Cenários verificados

| Cenário | Resultado |
|---------|-----------|
| Download jan/2018 inteiro (22 dias úteis) | 22 diários durante; após o 22º, auto-compact → 1 `01.parquet`, 22 diários deletados |
| Download 10 dias de jan/2018 (mês incompleto) | 10 diários, não compacta |
| Misto: jan inteiro + 10 dias fev | jan vira mensal, fev fica 10 diários; DuckDB read retorna ambos |
| Mês com feriado (dez/2024 com Natal) | `is_month_complete` ignora feriados B3 (~21 dias úteis = mês completo) |
| Re-baixar mês já compactado | idempotente, sem duplicatas, mensal sobrescrito atomicamente |
| Crash entre write `MM.parquet` e DELETE diários | reconcile detecta órfão, completa cleanup |
| Resume após crash parcial | `chunk_ledger` continua granular, re-run baixa só dias faltantes |
| Migração v1.2→v1.3 com mensais v1.2.0 | mensais intactos, `partitions.day=NULL`, bump catalog_version |

## 4. Consequências

### Positivas

- Elimina `O(N²)` de read-merge-rewrite no fast path. Pyro estima −2.35h por símbolo por 7 anos.
- Resume granular per-day "barato" (write-once + chunk_ledger são fonte de verdade).
- Downloads parciais (mid-month) já entregam dados consumíveis sem custo extra.
- Compatibilidade: v1.2.0 parquets continuam funcionando sem migração de dados.

### Negativas / trade-offs

- Mais arquivos durante o mês corrente (~20 vs 1 antes da compactação). DuckDB lida com isso bem (glob recursivo), mas filesystem mostra mais entradas. Mitigado pela compactação mensal automática.
- `compact_month` é uma operação a mais no fechamento do mês (~100MB-1GB de IO concentrado num único momento). Aceitável vs. o ganho amortizado.
- Reconcile precisa entender 2 layouts; lógica de parse_partition_path mais complexa.

## 5. Referências

- `src/data_downloader/storage/partition.py` (PartitionKey + paths)
- `src/data_downloader/storage/parquet_writer.py` (write-once + compact_month)
- `src/data_downloader/storage/catalog.py` (`is_month_complete`, `maybe_compact_month`)
- `tests/integration/test_parquet_per_day_hybrid.py` (T1-T9)
- `tests/property/test_parquet_per_day_hybrid_property.py` (invariantes Hypothesis)
- ADR-004 (partition layout legacy — referenced)
- `docs/qa/V1.3.0-PLAN.md` § Wave 3
