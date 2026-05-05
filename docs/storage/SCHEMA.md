# SCHEMA.md — Schema Parquet Canônico (Trades)

**Owner:** 💾 Sol (Storage Engineer)
**Versão atual:** v1.1.0
**Status:** ACCEPTED (Story 1.7g — 2026-05-05, Nelo Council 32 release blocker)
**Aplicável a:** `data/history/{exchange}/{symbol}/{year}/{month}.parquet`

---

## 0. Princípios não-negociáveis

1. **Schema é contrato perpétuo.** Cada Parquet escrito carrega `schema_version` no metadata. Leitor sempre verifica.
2. **Mudança aditiva** (campo novo nullable, default seguro) = **bump minor** (1.0.0 → 1.1.0). Não exige rewrite.
3. **Mudança quebradora** (rename, type change, drop, nullability YES→NO) = **bump major** (1.0.0 → 2.0.0) + script de migração + ADR + comunicação a Morgan/Aria + projetos downstream.
4. **No Invention** (Constitution Art. IV): nenhum campo entra no schema sem rastreamento a um trade real do callback `HistoryTrade*` ou a uma necessidade explícita de operação interna (ex: `chunk_id` para auditoria).
5. **Tudo BRT NAIVE** (lei de Nelo, R2): timestamps são nanos desde epoch interpretados como horário Brasil sem fuso anexado. DST: B3 não observa desde 2019 — para histórico < 2020 ver `INTEGRITY.md` §6.

---

## 1. Schema Trades v1.1.0 — definição

### 1.1 Tabela canônica

| # | Campo                 | Tipo pyarrow         | Null | Origem                                  | Descrição                                                                 |
|---|-----------------------|----------------------|------|------------------------------------------|---------------------------------------------------------------------------|
| 1 | `symbol`              | `string`             | NO   | DLL `pwcTicker`                          | Ticker como aceito pela DLL (ex: `WDOJ26`, `PETR4`).                      |
| 2 | `exchange`            | `string` (length=1)  | NO   | DLL `pwcBolsa`                           | `F` (BMF) ou `B` (Bovespa).                                               |
| 3 | `timestamp_ns`        | `int64`              | NO   | parse de `pwcDate` BRT NAIVE             | Nanos desde epoch (1970-01-01 00:00:00 BRT). **Lei do Nelo R2.**          |
| 4 | `timestamp_str`       | `string`             | NO   | DLL `pwcDate` literal                    | `"DD/MM/YYYY HH:mm:SS.ZZZ"` original do callback (auditoria + rollback).  |
| 5 | `price`               | `float64`            | NO   | DLL `dPrice`                             | Preço do trade.                                                           |
| 6 | `quantity`            | `int64`              | NO   | DLL `nQtd`                               | Quantidade negociada.                                                     |
| 7 | `trade_id`            | `int64`              | YES  | DLL `nTradeID` (V2)                      | ID único do trade. NULL para histórico antigo (callback V1).              |
| 8 | `trade_type`          | `uint8`              | NO   | DLL `nTradeType` (TConnectorTradeType)   | Enum 0..13 — ver §1.5 (TTradeType, fonte canônica `LegacyProfitDataTypesU.pas` L33-46). |
| 9 | `buy_agent_id`        | `int32`              | YES  | DLL `nBuyAgent`                          | ID do agente comprador. NULL se não disponível.                           |
| 10| `sell_agent_id`       | `int32`              | YES  | DLL `nSellAgent`                         | ID do agente vendedor. NULL se não disponível.                            |
| 11| `flags`               | `uint32`             | NO   | DLL `nFlags`                             | Bitmask: `TC_IS_EDIT`, `TC_LAST_PACKET`, etc.                             |
| 12| `source_callback`     | `string`             | NO   | constante interna                        | `"history_v2"` ou `"history_v1"`. Quem produziu este trade.               |
| 13| `side`                | `uint8`              | YES  | derivado / DLL                           | `0=unknown`, `1=buy`, `2=sell`. **NEW v1.0.0 (finding H1).**              |
| 14| `ingestion_ts_ns`     | `int64`              | NO   | `time.time_ns()` no momento do callback  | Quando o trade chegou ao nosso sistema (vs `timestamp_ns` = quando ocorreu na bolsa). **NEW v1.0.0 (finding H1, H19).** Permite medir latência DLL→disk e detectar reprocessamento. |
| 15| `chunk_id`            | `string`             | YES  | UUID gerado pelo DLL ingestor            | Identifica o chunk DLL que produziu este trade. Usado para auditoria, retry idempotente, e correlação com logs. **NEW v1.0.0 (finding H1).** |
| 16| `dll_version`         | `string`             | NO   | `GetDLLVersion()` no boot do processo    | Ex.: `"4.0.0.34"`. Capturado uma vez por processo, propagado em todos os trades dessa execução. **NEW v1.0.0 (finding H19).** |
| 17| `sequence_within_ns`  | `uint16`             | NO   | contador local do writer                 | 0, 1, 2, ... N — trades distintos com o mesmo `(symbol, timestamp_ns)`. Resolve colisão quando a granularidade do timestamp da DLL não chega a nanos reais. **NEW v1.0.0 (finding H2).** |
| 18| `buy_agent_name`      | `string`             | YES  | DLL `GetAgentName(nBuyAgent)`            | Nome humano da corretora compradora (resolvido pelo `AgentResolver`). NULL se ID==0 (desconhecido) ou DLL retornou `NL_NOT_FOUND`. **NEW v1.1.0 (Nelo Council 32 P0).** |
| 19| `sell_agent_name`     | `string`             | YES  | DLL `GetAgentName(nSellAgent)`           | Idem `buy_agent_name`. **NEW v1.1.0 (Nelo Council 32 P0).** |
| 20| `trade_type_name`     | `string`             | YES  | mapping enum `TConnectorTradeType`       | Nome humano de `trade_type` (ex. `"AgressionBuy"`). NULL se id desconhecido (fora 0..13). **NEW v1.1.0 (Nelo Council 32 P0).** |

**Total campos v1.1.0:** 20 (17 v1.0.0 + 3 nullable aditivos).

### 1.2 Definição pyarrow exata

```python
import pyarrow as pa

SCHEMA_TRADES_V1_1_0 = pa.schema([
    pa.field("symbol",             pa.string(),  nullable=False),
    pa.field("exchange",           pa.string(),  nullable=False),  # length=1 enforçado em validação
    pa.field("timestamp_ns",       pa.int64(),   nullable=False),
    pa.field("timestamp_str",      pa.string(),  nullable=False),
    pa.field("price",              pa.float64(), nullable=False),
    pa.field("quantity",           pa.int64(),   nullable=False),
    pa.field("trade_id",           pa.int64(),   nullable=True),
    pa.field("trade_type",         pa.uint8(),   nullable=False),
    pa.field("buy_agent_id",       pa.int32(),   nullable=True),
    pa.field("sell_agent_id",      pa.int32(),   nullable=True),
    pa.field("flags",              pa.uint32(),  nullable=False),
    pa.field("source_callback",    pa.string(),  nullable=False),
    pa.field("side",               pa.uint8(),   nullable=True),
    pa.field("ingestion_ts_ns",    pa.int64(),   nullable=False),
    pa.field("chunk_id",           pa.string(),  nullable=True),
    pa.field("dll_version",        pa.string(),  nullable=False),
    pa.field("sequence_within_ns", pa.uint16(),  nullable=False),
    # v1.1.0 — Nelo Council 32 release blocker P0:
    pa.field("buy_agent_name",     pa.string(),  nullable=True),
    pa.field("sell_agent_name",    pa.string(),  nullable=True),
    pa.field("trade_type_name",    pa.string(),  nullable=True),
])
```

### 1.5 TConnectorTradeType — mapping canônico (v1.1.0)

Fonte canônica: **`profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas` L33-46**
(`TTradeType` enum). Total de 14 valores (0..13). Bug histórico: SCHEMA.md
v1.0.0 documentava `2=normal` — errado; o valor real é `ttAgressionBuy`
(Nelo Council 32 §3.1).

| `trade_type` (uint8) | `trade_type_name` (string) | Semântica |
|----------------------|----------------------------|-----------|
| 0  | `Zero`            | placeholder; aparece em sentinel structs (Q-DRIFT-34) |
| 1  | `CrossTrade`      | trade casado (cross) |
| 2  | `AgressionBuy`    | agressão do lado comprador (NÃO "normal") |
| 3  | `AgressionSell`   | agressão do lado vendedor |
| 4  | `Auction`         | leilão |
| 5  | `Surveillance`    | sob vigilância da B3 |
| 6  | `Expit`           | EXPIT (operação fora da bolsa) |
| 7  | `OptionsExercise` | exercício de opção |
| 8  | `OverTheCounter`  | OTC |
| 9  | `DerivativeTerm`  | termo |
| 10 | `Index`           | trade de índice |
| 11 | `BTC`             | empréstimo de ações (BTC) |
| 12 | `OnBehalf`        | on behalf |
| 13 | `RLP`             | Retail Liquidity Provider (mesa B3) |

**Cross-ref canônico:** `src/data_downloader/storage/schema.py::TRADE_TYPE_NAME`
(mapping autoritativo). Resolver helper: `resolve_trade_type_name(trade_type_id)`
retorna `None` para IDs fora de 0..13 — orchestrator aplica fallback
`f"TradeType#{n}"` antes de gravar (Story 1.7g AC1, schema v1.1.0).

### 1.3 Justificativas de tipo

| Campo                | Por que esse tipo                                                                 |
|----------------------|-----------------------------------------------------------------------------------|
| `timestamp_ns int64` | Nanos cabem em int64 até ~292 anos pós-epoch — sobra muito. Permite aritmética direta sem conversão. |
| `price float64`      | B3 cota com até 6 casas; float32 perde precisão em valores altos (>1M).           |
| `trade_type uint8`   | TConnectorTradeType cabe em 8 bits. Reduz tamanho on-disk em ~7 bytes/trade.      |
| `flags uint32`       | DLL define bitmask em 32 bits. Manter raw bitmap evita perda semântica.           |
| `side uint8`         | 3 valores possíveis (0/1/2). uint8 é menor e mais comprimível que string.         |
| `sequence_within_ns uint16` | 0..65535 trades no mesmo nanosegundo é absurdamente seguro para qualquer cenário realista (B3 picos: ~50k trades/s = 50µs entre trades). |
| `chunk_id string`    | UUID v4 (~36 chars) é legível em logs; espaço extra justificado por debugabilidade. |
| `dll_version string` | Formato livre (`"4.0.0.34"`); raramente muda — Snappy comprime quase para zero.   |

### 1.4 Nullability — política

- **NO** = leitor pode assumir presença sem checar. Writer DEVE rejeitar trade que falte esse campo (erro fatal).
- **YES** = leitor DEVE checar `is_null()` antes de usar. Writer aceita ausência sem erro.

Mudar **NO → YES** é aditivo (downstream pode passar a tratar null). Mudar **YES → NO** é quebrador (downstream que dependia de null para sinalizar ausência quebra). Ambos exigem bump apropriado.

---

## 2. Dedup key — chave canônica (REFORMULADA, finding H2)

### 2.1 Regra

```
DEDUP_KEY(trade) = (
    symbol,
    timestamp_ns,
    trade_id
) IF trade_id IS NOT NULL
ELSE (
    symbol,
    timestamp_ns,
    price,
    quantity,
    buy_agent_id,
    sell_agent_id,
    sequence_within_ns
)
```

### 2.2 Por que duas variantes

- **Callback V2** entrega `trade_id` único por trade. Chave canônica = `(symbol, ts_ns, trade_id)`. Ótimo: 3 colunas, lookup barato em DuckDB.
- **Callback V1** (histórico antigo) NÃO entrega `trade_id`. Tentar `(symbol, ts_ns, price, quantity)` quebra quando dois trades distintos têm preço e quantidade idênticos no mesmo nanosegundo (cenário real em leilão / cross). Adicionar `buy_agent_id + sell_agent_id` reduz colisão; `sequence_within_ns` garante unicidade local mesmo se tudo o mais coincidir.

### 2.3 Escrita — passo a passo

1. Writer recebe lote de trades do `dll_queue`.
2. Para cada trade do lote:
   - Computa `(symbol, timestamp_ns)` como bucket-chave.
   - Atribui `sequence_within_ns` = contador local que reseta a cada novo `(symbol, timestamp_ns)` visto, incrementa para repetições.
3. Writer faz **anti-join via DuckDB** contra `partitions` existentes da mesma `(exchange, symbol, year, month)`:
   ```sql
   SELECT new.*
   FROM new_batch new
   ANTI JOIN read_parquet('F/WDOJ26/2026/03.parquet') existing
   ON  new.symbol       = existing.symbol
   AND new.timestamp_ns = existing.timestamp_ns
   AND COALESCE(new.trade_id, -1) = COALESCE(existing.trade_id, -1)
   AND (
       new.trade_id IS NOT NULL
       OR (
           new.price             = existing.price
           AND new.quantity      = existing.quantity
           AND COALESCE(new.buy_agent_id, -1)  = COALESCE(existing.buy_agent_id, -1)
           AND COALESCE(new.sell_agent_id, -1) = COALESCE(existing.sell_agent_id, -1)
           AND new.sequence_within_ns = existing.sequence_within_ns
       )
   )
   ```
4. Apenas linhas restantes são gravadas.

### 2.4 Custo medido (estimado, validar com Pyro Story 1.4.5)

- ~50ms por chunk de 10k trades em SSD NVMe + DuckDB single-thread.
- Linear no tamanho da partição lida (que é mensal — limite ~10M trades/mês para WDO líquido).
- Mitigação se ficar caro: usar Bloom filter por arquivo (Parquet 2.6+) para skip rápido — futuro.

---

## 3. Layout de partição

```
data/
└── history/
    ├── catalog.db                          # SQLite (fonte única de verdade)
    └── F/                                  # exchange = BMF
        ├── WDOJ26/                         # contrato
        │   ├── 2026/
        │   │   ├── 01.parquet
        │   │   ├── 02.parquet
        │   │   └── 03.parquet
        │   └── 2025/...
        └── WDOH26/...
```

Padrão de path: `data/history/{exchange}/{symbol}/{year:04d}/{month:02d}.parquet`.

**Particionamento é IMUTÁVEL em prod.** Mudar layout = migrar TODOS os arquivos = projeto explícito (ADR + script + janela de manutenção). Adições de campo dentro do Parquet são livres (bump minor).

> Decisão M4 (Sol): checksum **NÃO** vai em `_meta/checksum.json` separado. Vai em (a) metadata Parquet do próprio arquivo (chave `sha256_self`) com valor calculado **antes** do fechamento + redundância em (b) catálogo SQLite (`partitions.checksum_sha256`). Isso elimina dessincronização silenciosa entre arquivo e meta.

---

## 4. Metadata Parquet (chave-valor)

Toda escrita popula essas chaves no metadata custom do Parquet (acessível via `pq.read_metadata(path).metadata`):

| Chave                  | Tipo (string)        | Obrigatório | Descrição                                                       |
|------------------------|----------------------|-------------|-----------------------------------------------------------------|
| `schema_version`       | `"1.1.0"`            | YES         | Versão semver do schema usado para escrever (v1.1.0 atual).     |
| `row_count`            | `"123456"`           | YES         | Nº de linhas na partição. Redundante com Parquet footer mas barato. |
| `first_ts_ns`          | `"1709251200000000000"` | YES      | `min(timestamp_ns)` do arquivo.                                 |
| `last_ts_ns`           | `"1711929599999999999"` | YES      | `max(timestamp_ns)` do arquivo.                                 |
| `dll_version`          | `"4.0.0.34"`         | YES         | Coletado via `GetDLLVersion()` no boot do processo.             |
| `created_at`           | ISO8601 UTC          | YES         | `"2026-05-03T14:32:11Z"` — quando o arquivo foi finalizado.     |
| `chunk_id`             | UUID                 | NO          | Último chunk que escreveu. NULL se merge de múltiplos chunks.   |
| `download_job_id`      | UUID                 | YES         | Job de download que gerou (referencia `downloads.job_id`).      |
| `compression`          | `"snappy"`           | YES         | Para auditoria; lido também do footer. Default validado Pareto-ótimo em COUNCIL-21 (Story 2.8). |
| `row_group_size`       | `"100000"`           | YES         | Configuração usada na escrita. Default validado Pareto-ótimo em COUNCIL-21 (Story 2.8). |
| `sha256_self`          | hex(64)              | YES         | SHA256 dos bytes do arquivo (calculado antes do close — ver INTEGRITY §3). |

> **NOTA IMPORTANTE:** `sha256_self` é uma "chicken-and-egg": o hash é dos bytes do arquivo final, mas precisa estar dentro do arquivo. Resolução em INTEGRITY §3 (escrita em duas passadas: write tmp → hash tmp → reescrever metadata + atomic replace).

---

## 5. Catálogo SQLite — DDL completo

Localização: `data/history/catalog.db`.

### PRAGMAs — 3 perfis selecionáveis (Story 2.8 / COUNCIL-21)

PRAGMAs aplicados via `data_downloader.storage.sqlite_profiles`. Default
é `default` profile (M6-reduzido, ratificado empiricamente):

```sql
-- Profile 'default' (default em produção):
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA cache_size   = -50000;      -- 50 MB
PRAGMA mmap_size    = 67108864;    -- 64 MB
PRAGMA foreign_keys = ON;
PRAGMA temp_store   = MEMORY;
```

| Profile        | cache_size           | mmap_size | Use case                              |
|----------------|---------------------:|----------:|---------------------------------------|
| `low_memory`   | -10000 (10 MB)       |    16 MB  | CI / containers / laptops apertados   |
| **`default`**  | **-50000 (50 MB)**   | **64 MB** | Padrão produção (M6-reduzido)         |
| `aggressive`   | -200000 (200 MB)     |   256 MB  | Workstation 32GB+ / cargas pesadas    |

**Selection precedence** (alta → baixa):

1. Argumento explícito: `Catalog(sqlite_profile="aggressive")` ou
   `Catalog(sqlite_profile=SQLiteProfile(...))`.
2. Env var: `DATA_DOWNLOADER_SQLITE_PROFILE=low_memory|default|aggressive`.
3. Default: `"default"`.

Sol decisão (COUNCIL-21): defaults validados por
`benchmarks/bench_sqlite_profiles.py` — `default` vence o composite
score (0.7 × register + 0.3 × query × 100); `aggressive` ganha apenas
~2% por 4x mais RAM (não compensa). Mudar profile a qualquer momento é
seguro (só afeta cache da sessão atual; schema imutável).

### 5.1 `_schema_meta` — versão do próprio catálogo

```sql
CREATE TABLE _schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO _schema_meta(key, value) VALUES
    ('catalog_version', '1.0.0'),
    ('parquet_schema_min_supported', '1.0.0'),
    ('created_at', strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    ('app_version', '');  -- preenchido em boot
```

### 5.2 `downloads` — histórico de jobs

```sql
CREATE TABLE downloads (
    job_id            TEXT PRIMARY KEY,        -- UUID
    symbol            TEXT NOT NULL,
    exchange          TEXT NOT NULL,
    requested_start   TIMESTAMP NOT NULL,
    requested_end     TIMESTAMP NOT NULL,
    actual_start      TIMESTAMP,               -- primeiro trade recebido
    actual_end        TIMESTAMP,               -- último trade recebido
    status            TEXT NOT NULL CHECK(status IN
                          ('pending','in_progress','completed','failed','partial','cancelled')),
    trades_count      INTEGER,
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
    error             TEXT,
    dll_version       TEXT,
    cli_invocation    TEXT                      -- linha de comando original (auditoria)
);
CREATE INDEX idx_downloads_symbol_status ON downloads(symbol, status);
```

### 5.3 `partitions` — registro por arquivo Parquet

```sql
CREATE TABLE partitions (
    partition_path     TEXT PRIMARY KEY,        -- ex 'F/WDOJ26/2026/03.parquet' (relativo a data/history/)
    symbol             TEXT NOT NULL,
    exchange           TEXT NOT NULL,
    year               INTEGER NOT NULL,
    month              INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
    row_count          INTEGER NOT NULL CHECK(row_count >= 0),
    first_ts_ns        INTEGER NOT NULL,
    last_ts_ns         INTEGER NOT NULL,
    schema_version     TEXT NOT NULL,
    checksum_sha256    TEXT NOT NULL,          -- redundante com metadata Parquet (ver §4)
    file_size_bytes    INTEGER NOT NULL CHECK(file_size_bytes > 0),
    written_at         TIMESTAMP NOT NULL,
    job_id             TEXT,                    -- referencia downloads.job_id
    FOREIGN KEY(job_id) REFERENCES downloads(job_id) ON DELETE SET NULL
);
CREATE INDEX idx_partitions_symbol_ym ON partitions(symbol, year, month);
CREATE INDEX idx_partitions_exchange  ON partitions(exchange);
```

### 5.4 `gaps` — intervalos não cobertos

```sql
CREATE TABLE gaps (
    symbol         TEXT NOT NULL,
    exchange       TEXT NOT NULL,
    gap_start      TIMESTAMP NOT NULL,
    gap_end        TIMESTAMP NOT NULL,
    reason         TEXT NOT NULL CHECK(reason IN
                       ('no_trades','holiday','weekend','failed_chunk','unknown','outside_vigency')),
    detected_at    TIMESTAMP NOT NULL,
    resolved_at    TIMESTAMP,
    PRIMARY KEY (symbol, gap_start, gap_end)
);
CREATE INDEX idx_gaps_symbol_unresolved
    ON gaps(symbol)
    WHERE resolved_at IS NULL;
```

### 5.5 `contracts` — mapa de contratos vigentes

```sql
CREATE TABLE contracts (
    symbol_root        TEXT NOT NULL,           -- 'WDO', 'WIN', 'PETR', ...
    contract_code      TEXT NOT NULL,           -- 'WDOJ26'
    vigent_from        TIMESTAMP NOT NULL,      -- primeiro dia vigente
    vigent_until       TIMESTAMP NOT NULL,      -- último dia vigente (inclusivo)
    validated_at       TIMESTAMP,               -- NULL = ainda não validado contra DLL
    validation_source  TEXT NOT NULL CHECK(validation_source IN
                           ('hypothesized','nelogica_official','dll_probe','b3_calendar','manual')),
    notes              TEXT,
    PRIMARY KEY (symbol_root, contract_code)
);
CREATE INDEX idx_contracts_root_vigency ON contracts(symbol_root, vigent_from, vigent_until);
```

> Seed em `CONTRACTS.md` §3.

### 5.6 `_checksum_cache` — cache de SHA256 por arquivo (evita rehash full em reconcile)

```sql
CREATE TABLE _checksum_cache (
    partition_path     TEXT PRIMARY KEY,
    file_size_bytes    INTEGER NOT NULL,
    mtime_ns           INTEGER NOT NULL,        -- os.stat().st_mtime_ns
    checksum_sha256    TEXT NOT NULL,
    cached_at          TIMESTAMP NOT NULL,
    FOREIGN KEY(partition_path) REFERENCES partitions(partition_path) ON DELETE CASCADE
);
```

Política: rehash apenas se `(file_size_bytes, mtime_ns)` mudou. Se cache hit → assume checksum válido (custo de erro: detecção atrasa 1 ciclo de reconcile). Ver `INTEGRITY.md` §3.

### 5.7 `_pending_commits` — escrita atômica two-phase emulada (finding M5/H7)

```sql
CREATE TABLE _pending_commits (
    partition_path     TEXT PRIMARY KEY,
    started_at         TIMESTAMP NOT NULL,
    expected_sha256    TEXT NOT NULL,           -- hash do tmp file ANTES do replace
    expected_size      INTEGER NOT NULL,
    job_id             TEXT,
    pid                INTEGER NOT NULL,        -- processo que iniciou — detecta crash de outro PID
    FOREIGN KEY(job_id) REFERENCES downloads(job_id) ON DELETE SET NULL
);
```

**Workflow** (detalhado em `INTEGRITY.md` §4):
1. INSERT em `_pending_commits` com hash do `.tmp`.
2. `os.replace(tmp, final)` (atomic em mesmo filesystem).
3. INSERT/UPDATE em `partitions`.
4. DELETE de `_pending_commits` (commit confirmado).

Se crash entre 2 e 3 → boot detecta `_pending_commits` órfão, valida hash do arquivo final, recupera ou marca para retry.

---

## 6. Política de migração (R4 — formal)

### 6.1 Classificação

| Tipo de mudança | Exemplo | Ação | Bump |
|----------------|---------|------|------|
| Adicionar campo nullable com default seguro | `+ market_phase string nullable` | Aditivo | minor |
| Adicionar metadata Parquet key | `+ created_by` no metadata | Aditivo | minor |
| Reduzir nullability `NO → YES` | `trade_type` aceita NULL | Aditivo (leitor é mais permissivo) | minor |
| Renomear campo | `quantity → qty` | Quebrador | major |
| Mudar tipo | `price float64 → decimal128` | Quebrador | major |
| Aumentar nullability `YES → NO` | `trade_id` vira obrigatório | Quebrador | major |
| Remover campo | `- timestamp_str` | Quebrador | major |
| Mudar layout de particionamento | `month → day` | Quebrador (catastrófico) | major + ADR |

### 6.2 Processo

**Bump minor (aditivo)**:
1. Atualiza `SCHEMA.md` com novo campo + bump versão (`1.0.0 → 1.1.0`).
2. Atualiza changelog (§7).
3. Atualiza writer para popular novo campo.
4. Atualiza leitor para tolerar ausência (Parquet < 1.1.0 não tem o campo → leitor entrega NULL).
5. **Não migra arquivos existentes.** Eles continuam válidos como v1.0.0.
6. Documenta em `MIGRATIONS.md`.

**Bump major (quebrador)**:
1. ADR obrigatório (`docs/adr/ADR-XXX-schema-vN.md`).
2. Aprovação Aria + comunicação a Morgan (impacto downstream).
3. Script de migração em `storage/migrations/vN_M_P_to_vM_N_P.py` (ver `MIGRATIONS.md`).
4. CLI: `data-downloader migrate --from 1.x.y --to 2.0.0 --dry-run`.
5. Backup obrigatório antes de migração real (`migrate` recusa rodar sem `--backup-dir` ou `--i-have-backup`).
6. `_schema_meta.parquet_schema_min_supported` é atualizado para `2.0.0` apenas após migração 100% verificada.

---

## 7. Changelog

### v1.1.0 — 2026-05-05 — Nelo Council 32 release blocker P0 (aditivo)

- **3 novos campos nullable** (não exige rewrite — leitor v1.0.0 lê v1.1.0
  como NULL):
  - `buy_agent_name` (string nullable) — resolvido via `AgentResolver`
    (DLL `GetAgentName`).
  - `sell_agent_name` (string nullable) — idem.
  - `trade_type_name` (string nullable) — humano do enum `TConnectorTradeType`
    (ver §1.5).
- **Bug fix:** SCHEMA.md v1.0.0 documentava `trade_type=2 → "normal"` (errado).
  Valor real é `ttAgressionBuy` (Nelo Council 32 §3.1; fonte
  `LegacyProfitDataTypesU.pas` L33-46).
- **Writer fail-loudly (`SchemaIntegrityError`):** `parquet_writer.write`
  agora levanta se algum campo do `TradeRecord` cair fora do schema
  canônico — força bump explícito em vez de drop silencioso. Causa raiz
  histórica: o pipeline em memória populava `buy_agent_name` etc. mas o
  writer (v1.0.0) iterava só sobre os 17 nomes do schema → drop silencioso.
- **Forward-compat:** `_read_existing_table` preenche colunas v1.1.0
  ausentes em parquet legacy com NULL (R4 — bump minor não exige migração).

### v1.0.0 — 2026-05-03 — INITIAL

- 17 campos definidos (12 originais do squad seed + 5 novos da revisão de plano):
  - `side` (uint8, nullable) — finding H1.
  - `ingestion_ts_ns` (int64, NOT NULL) — finding H1, H19.
  - `chunk_id` (string, nullable) — finding H1.
  - `dll_version` (string, NOT NULL) — finding H19.
  - `sequence_within_ns` (uint16, NOT NULL) — finding H2.
- Dedup key reformulada: variante curta com `trade_id` quando disponível, longa sem.
- Catálogo SQLite com `_schema_meta`, `_checksum_cache`, `_pending_commits` adicionados (findings M4, M5, H7).
- PRAGMAs SQLite reduzidos: `cache_size=-50000`, `mmap_size=67108864` (finding M6).
- Checksum colocado em metadata Parquet + redundância no catálogo (finding M4 — abandono de `_meta/checksum.json` separado).

---

## 8. Referências

- ADR-002: Escolha Parquet+DuckDB+SQLite.
- ADR-004: Particionamento `{exchange}/{symbol}/{year}/{month}.parquet`.
- `docs/storage/CONTRACTS.md`: mapa de contratos vigentes.
- `docs/storage/INTEGRITY.md`: checks e queries DuckDB de validação.
- `docs/storage/MIGRATIONS.md`: framework de migração.
- `docs/storage/QUERIES.md`: queries canônicas para projetos downstream.
- `docs/decisions/PLAN_REVIEW_2026-05-03.md`: findings H1, H2, H19, M4, M5, M6, H7.

— Sol, custodiando o histórico 💾
