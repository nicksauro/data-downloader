# ADR-002 — Storage stack: Parquet (Snappy) + DuckDB + SQLite

**Status:** accepted
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💾 Sol, ⚡ Pyro
**Supersedes:** —
**Related:** ADR-004 (particionamento)

---

## Contexto

O data-downloader é a **fundação de TODOS os projetos futuros** (R1). O storage decidido aqui será carregado por backtest engine, live signal generator, risk monitor, research notebooks. A escolha precisa otimizar:

1. **Longevidade** — formato que ainda exista e seja lido em 5+ anos.
2. **Throughput de escrita** — >= 100k trades/s sustentado (R16, target Pyro).
3. **Throughput de leitura** — projetos downstream lerão N vezes; leitura importa mais que escrita.
4. **Query rica** — backtest precisa filtrar por timestamp, agregar por símbolo, fazer joins.
5. **Catálogo separado** — saber "o que está baixado" sem abrir todos os arquivos.
6. **Idempotência** (R5) — re-rodar download não duplica.
7. **Versionamento de schema** (R4) — schema muda; leitor de 2027 lê arquivo de 2026.

---

## Opções Consideradas

### Opção A — Parquet (Snappy) + DuckDB + SQLite (catálogo)
- **Parquet** = formato colunar, comprimido, padrão indústria (Spark, Pandas, Polars, DuckDB, Trino, BigQuery, etc).
- **DuckDB** = engine OLAP embarcada, lê Parquet zero-copy via Arrow, query SQL com pruning.
- **SQLite** = catálogo (tabelas `downloads`, `partitions`, `gaps`, `contracts`).

**Prós:**
- Parquet vive 20+ anos no ecossistema. Leitura garantida em qualquer ferramenta.
- DuckDB faz pruning por row group + column → leitura filtrada extremamente rápida (alvo Pyro: >= 5M trades/s filtrado).
- Snappy: compressão razoável + leitura rápida (vs ZSTD que comprime mais mas lê mais devagar — para tick data que é lido N vezes, Snappy é Pareto-ótimo na escolha leitura-vs-tamanho).
- SQLite é local, zero-config, suporta WAL para concorrência leitor/escritor.
- Tudo embarcado, zero serviço externo.
- Arrow (PyArrow) é a moeda comum: catálogo SQLite → query DuckDB → resultado Arrow → consumidor.

**Contras:**
- Parquet append não-trivial (tem que reescrever arquivo ou criar novo). Mitigação: 1 arquivo por mês × símbolo (ADR-004) → append é "criar próximo mês".
- DuckDB ainda em rápida evolução (> 1.0 estável agora).

### Opção B — Arctic (MongoDB-based)
**Prós:** library do MAN AHL para tick data, append trivial, versioning embutido.
**Contras:** dep MongoDB (serviço externo, contradiz desktop single-machine), formato proprietário (vendor lock-in), comunidade menor que Parquet.

### Opção C — KDB+ / kdb tick
**Prós:** padrão de fato em quant funds para tick data.
**Contras:** licença comercial, q language alta curva, overkill para single-user, contradição com R1 (foundation aberta).

### Opção D — TimescaleDB (PostgreSQL)
**Prós:** SQL estável, hypertables otimizadas para time series.
**Contras:** dep Postgres (serviço externo), throughput de escrita inferior a Parquet, ler para projeto downstream exige conexão DB (não arquivo portável).

### Opção E — Raw HDF5 / Feather / sqlite3
**Prós:** simples.
**Contras:** HDF5 thread-unsafe na escrita; Feather sem versionamento de schema robusto; sqlite3 puro = perde tudo de colunar/pruning para datasets grandes.

---

## Decisão

**Opção A — Parquet (Snappy) + DuckDB (query) + SQLite (catálogo).**

Configurações decididas:
- **Compressão:** Snappy (não ZSTD). Validar empiricamente em Pyro `*parquet-tune`.
- **row_group_size:** 100_000 (não default 1M) — pruning fino para queries de minutos/horas.
- **page_size:** 1MB (default).
- **use_dictionary:** True.
- **write_statistics:** True (DuckDB usa para pruning).
- **SQLite WAL:** habilitado (concorrência leitor/escritor).

---

## Consequências

### Positivas
- Stack embarcada, single-machine, sem serviço externo.
- Leitura por qualquer ferramenta moderna (Pandas, Polars, Spark, DuckDB CLI, Trino).
- Pyro valida targets de throughput em Story 2.2.
- Sol mantém schema versionado (R4) → migrações explícitas.
- Catálogo SQLite responde "o que temos" em <5ms (target Pyro).

### Negativas
- 3 tecnologias para manter (Parquet, DuckDB, SQLite). Aceitável — todas são triviais de operar.
- Schema migration exige script (Sol mantém em `docs/storage/MIGRATIONS.md`).
- SQLite WAL não funciona em filesystems remotos (NFS) — não é restrição (single-machine).

### Neutras
- DuckDB em rápida evolução: pinning de versão em `pyproject.toml`; bump deliberado.

---

## Layout de tabelas SQLite (resumo)

Detalhes em `docs/storage/SCHEMA.md`. Tabelas:
- `downloads(job_id, symbol, exchange, requested_*, actual_*, status, ...)`
- `partitions(partition_path, symbol, exchange, year, month, row_count, first_ts_ns, last_ts_ns, schema_version, checksum_sha256, ...)`
- `gaps(symbol, exchange, gap_start, gap_end, reason, detected_at)`
- `contracts(symbol_root, contract_code, vigent_from, vigent_until, validated_at, validation_source)`

---

## Validações requeridas

- [ ] Pyro `*bench_parquet_write` >= 100k trades/s (Story 2.2)
- [ ] Pyro `*bench_parquet_read` (DuckDB full scan) >= 1M trades/s
- [ ] Pyro `*bench_parquet_read` (filtrado com pruning) >= 5M trades/s
- [ ] Sol `*integrity-check` clean após smoke test (Story 1.7)
- [ ] Quinn property-test idempotência clean (Story 2.1)
