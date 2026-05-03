# ADR-004 — Particionamento `data/history/{exchange}/{symbol}/{year}/{month}.parquet`

**Status:** accepted
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💾 Sol, ⚡ Pyro
**Supersedes:** —
**Related:** ADR-002 (storage stack)

---

## Contexto

Definido o storage (Parquet + DuckDB + SQLite — ADR-002), precisamos definir **layout de particionamento**. Decisão impacta:
- Velocidade de leitura filtrada (DuckDB pruning).
- Tamanho de cada arquivo (overhead Parquet vs granularidade).
- Append-friendliness (Parquet não suporta append in-place; estratégia precisa minimizar reescrita).
- Escalabilidade futura (multi-bolsa, multi-asset).
- Custo de mudar layout depois (= migrar TODOS os arquivos).

**Restrições:**
- Idempotência (R5) — re-rodar download não duplica nem corrompe arquivos prontos.
- Schema versioning (R4) — cada arquivo carrega metadata `schema_version`.
- Catálogo é fonte única de verdade (R6) — toda partição registrada em SQLite.

---

## Opções Consideradas

### Opção A — `{exchange}/{symbol}/{year}/{month}.parquet`
Ex: `data/history/F/WDOJ26/2026/03.parquet`
- 1 arquivo por símbolo × mês.
- Estimativa WDO: ~1-3M trades/mês = ~30-100MB Parquet (Snappy).

### Opção B — `{exchange}/{symbol}/{year}/{month}/{day}.parquet`
Ex: `data/history/F/WDOJ26/2026/03/15.parquet`
- 1 arquivo por dia.
- Estimativa WDO: ~50-150k trades/dia = ~2-5MB Parquet.

### Opção C — `{exchange}/{symbol}.parquet` (single file per symbol)
Ex: `data/history/F/WDOJ26.parquet`

### Opção D — Apache Iceberg / Delta Lake-style
Layout com metadata layer (manifest files, snapshots).

---

## Análise

| Aspecto | A (mês) | B (dia) | C (single) | D (Iceberg) |
|---------|---------|---------|------------|-------------|
| Nº arquivos / 1 ano WDO | 12 | 252 | 1 | 252+ |
| Tamanho médio arquivo | 30-100MB | 2-5MB | ~1GB | varia |
| Append friendly | ✅ (próximo mês) | ✅✅ (próximo dia) | ❌ (reescrever) | ✅ (snapshot) |
| Pruning DuckDB | bom (mês) | excelente (dia) | row_group only | excelente |
| Overhead Parquet (small files) | baixo | **alto** | nenhum | médio |
| Re-baixar 1 dia | reescrever 1 mês | reescrever 1 dia | reescrever tudo | snapshot novo |
| Complexidade implementação | baixa | baixa | média | **alta** |
| Compatibilidade ferramenta | total | total | total | restrita |

**Pontos críticos:**

- **Opção B (dia):** muitos arquivos pequenos. Parquet tem overhead fixo por arquivo (footer + metadata + magic bytes); para arquivos < 2MB, overhead pode ser 10-30% do tamanho. Pyro estima: dataset 5 anos WDO + WIN + 5 equities = ~12k arquivos → catálogo SQLite handles, mas filesystem performance degrada em diretórios com >1000 entries (mitigado pela árvore /year/month/day, mas ainda).

- **Opção A (mês):** sweet spot. Arquivos de 30-100MB são tamanho ideal para Parquet (overhead < 1%). Pruning DuckDB por row_group_size=100k (ADR-002) entrega granularidade de minutos dentro do arquivo.

- **Opção C (single):** rebuild para qualquer mudança = inviável para tick data.

- **Opção D (Iceberg):** poderoso mas adiciona dep significativa (PyIceberg) + complexidade conceitual. Overkill para single-user single-machine. Reavaliar se projeto crescer para multi-tenant.

---

## Decisão

**Opção A — `data/history/{exchange}/{symbol}/{year}/{month}.parquet`.**

Razões:
1. **Arquivo size sweet spot** — 30-100MB elimina overhead de small files.
2. **Append simples** — próximo mês = próximo arquivo, sem reescrever existentes.
3. **Pruning suficiente** — DuckDB faz pruning por arquivo (mês) + row_group (intra-arquivo, granularidade ~minutos com row_group=100k).
4. **Re-download 1 dia** — reescreve 1 arquivo de mês (operação atômica via tmp + rename); aceitável.
5. **Compatibilidade total** — qualquer ferramenta lê (`pyarrow.dataset`, DuckDB, Polars, Spark).
6. **Catálogo SQLite** registra cada partição com first_ts_ns / last_ts_ns / row_count → "tem este dia?" responde sem abrir arquivo.

**Layout completo:**

```
data/
└── history/
    ├── catalog.db                          # SQLite (R6 — fonte única)
    ├── F/                                  # exchange = BMF
    │   ├── WDOJ26/
    │   │   ├── 2026/
    │   │   │   ├── 01.parquet
    │   │   │   ├── 02.parquet
    │   │   │   ├── 03.parquet
    │   │   │   └── _meta/
    │   │   │       └── checksum.json       # SHA256 por arquivo
    │   │   └── 2025/...
    │   ├── WDOH26/...
    │   ├── WINH26/...
    │   └── WDOK26/...
    └── B/                                  # exchange = Bovespa
        ├── PETR4/...
        └── VALE3/...
```

**Atomicidade da escrita:**
1. Writer escreve em `01.parquet.tmp.{uuid}`.
2. Calcula SHA256.
3. `os.replace(tmp, '01.parquet')` (atômico no Windows + Linux).
4. Atualiza `_meta/checksum.json`.
5. Atualiza `catalog.db.partitions` na mesma transação SQLite.
6. SQLite commit = ponto de truth.

---

## Consequências

### Positivas
- 12 arquivos por ano × símbolo (240 para 5 anos × 4 símbolos = 960 arquivos no MVP). Filesystem confortável.
- Re-baixar 1 mês = reescreve 1 arquivo, atomicamente.
- Pruning funciona em 2 níveis: arquivo (mês) + row_group (minutos).
- Catálogo SQLite responde queries de "está baixado?" em <5ms.
- Multi-bolsa (B vs F) e multi-asset suportados sem reestrutura.

### Negativas
- Re-baixar 1 dia específico = reescreve mês inteiro. Mitigação: dedup detecta o que já existe; só novos trades são adicionados; re-escrita é I/O mas não trabalho de lookup.
- Mudar layout depois = migração (script). Lei R4: schema_version inclui layout; bump major exige migração.
- Sem Iceberg-style time-travel — se precisar histórico de "como o catálogo estava ontem", precisa de snapshot externo (não no MVP).

### Neutras
- Volume estimado MVP (1 ano de WDO + WIN, ~24 arquivos): ~3GB Parquet.
- Volume estimado V1 (5 anos × 5 símbolos, ~300 arquivos): ~30-50GB Parquet.

---

## Validações requeridas

- [ ] Pyro `*partition-estimate WDOJ26 2026-01-01 2026-12-31` produz dimensões esperadas (Story 1.6)
- [ ] Sol `*integrity-check` clean após smoke test (Story 1.7)
- [ ] Quinn property-test confirma escrita atômica (sem arquivo `.tmp` órfão após crash) (Story 2.1)
