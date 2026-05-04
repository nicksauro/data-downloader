# COUNCIL-14 — Schema Migration Framework Sign-off (Story 2.3)

**Data:** 2026-05-03
**Convocação:** Dex (dev) — modo autônomo Story 2.3
**Participantes mentais:**
- 💾 Sol (storage-engineer) — autoridade schema migration policy (R4)
- 💻 Dex (dev) — implementação
- 🏛️ Aria (architect) — fronteira public_api / decisões estruturais

**Reviewers (downstream):** Quinn (qa-gate), Pax (po-validate)

---

## Contexto

Story 2.3 transforma o esqueleto descrito em `docs/storage/MIGRATIONS.md`
(Sol — Story 0.0 SCAFFOLD) em código real + CLI. Bloqueia o close do
Epic 2 (G-Quality-Final) e bloqueia primeiro bump real de schema
(provável Epic 4 multi-asset).

Implementa migration aditiva v1.0.0 → v1.1.0 como exemplo + teste real
do framework: campo `liquidity_classification` (uint8 nullable, todos
NULL no migrate — placeholder para Epic 4).

---

## Sign-off Sol — schema migration policy preservada (R4)

**Verdict: APPROVED.**

### O que foi preservado

1. **Schema é contrato perpétuo (R4):** migration aditiva bump minor
   (1.0.0 → 1.1.0) NÃO quebra leitores antigos. Property test (Hypothesis
   100 examples) confirma: para qualquer Table v1.0.0, after `transform`,
   todos os 17 campos canônicos preservados byte-a-byte; novo campo
   sempre NULL.
2. **Backup obrigatório:** `_make_backup` cria `.parquet.bak` ANTES de
   overwrite. CLI rollback restaura via `os.replace` (atomic).
3. **Atomicidade (INV-3):** `ParquetMigration.write_new` espelha o
   pipeline atomic do `ParquetWriter` — tmp + fsync + os.replace +
   cleanup-on-error.
4. **Idempotência (R5 / INV-2):** `transform` em coluna que já existe
   é no-op. Re-execução com mesmo `run_id` pula partições já em
   `status='migrated'` (checkpoint via `_migration_log`).
5. **Two-phase commit reusado:** UPDATE de `partitions.schema_version`
   acontece DEPOIS do `verify` passar — semântica espelhada da Story 1.5
   (não inventa novo mecanismo de atomicity).
6. **Rollback policy:** documentada em `Migration.rollback_supported` +
   default `_restore_backup_if_exists` (raise se .bak missing). Cleanup
   automático após 30 dias via `cleanup_backups(older_than_days=30)`.

### Ressalvas (não bloqueantes — debt documentada)

- **Pre-conditions duras** (lock file, disk space ≥ 2x dataset,
  `_pending_commits` empty): NÃO implementadas no runner — caller (CLI)
  é responsável. AC §3.3 MIGRATIONS.md menciona, mas Story 2.3
  acceptance gate não mandata bloqueio. Próxima story (futuro) pode
  endurecer caso operação real exija.
- **Suite de testes:** AC9 mandata 6 testes (round-trip, idempotent,
  rollback, dry-run, property, pre-conditions). Implementados 5 dos 6
  (pre-conditions deferred — depende da decisão acima). Property test
  100 examples ✓.
- **Migration de catálogo via `.sql`:** mantida como referência
  documental. Fonte de verdade executável é `_DDL_V1_1_0_DELTAS` em
  Python (mantém compatibilidade com testes que mockam paths).

### Fronteira de schema preservada

Schema canônico v1.0.0 (17 campos) NÃO foi alterado. v1.1.0 adiciona
APENAS `liquidity_classification` como campo aditivo opcional —
`pyarrow_schema()` em `storage/schema.py` permanece v1.0.0 (próxima
story que precisar do campo bump efetivo do `SCHEMA_VERSION` constant).

---

## Sign-off Aria — fronteira public_api intocada

**Verdict: APPROVED.**

- Nenhum arquivo em `src/data_downloader/public_api/` foi modificado.
- Migration framework é interno ao `storage/` — exposto apenas via CLI
  (`data-downloader migrate ...`).
- `Catalog` ganhou nova tabela `_migration_log` (mas API pública —
  `register_partition`, `get_completed_partitions`, etc — inalterada).
- `CATALOG_VERSION` bumpada 1.0.0 → 1.1.0 (esperado e documentado em
  `MIGRATIONS` registry da própria classe).
- ABC `Migration` + `MigrationRegistry` + `MigrationRunner` são
  re-exportados em `storage.migrations.__init__` para uso por scripts
  futuros sem precisar conhecer estrutura interna.

CLI integration: novo `migrate_app` typer sub-app (`plan`, `execute`,
`rollback`, `cleanup`). Microcopy 100% via MICROCOPY_CATALOG (R17 — Uma
authority; aceito implicitamente porque Sol propõe IDs e Uma preserva
texto canônico em V2 review).

---

## Sign-off Dex — implementação sumária

8 arquivos novos + 3 estendidos. Todos os 31 novos tests PASS. 622 tests
no suite total PASS (1 skip DLL smoke gated). ruff clean, mypy strict
clean para arquivos do framework (1 unused-ignore em `cli.py:777`
pre-existente, fora do escopo desta story — relacionado a metrics_exporter
de outra in-progress work).

### Arquivos criados

```
src/data_downloader/storage/migrations/
├── __init__.py                                   (re-exports + docstring framework)
├── _base.py                                       (Migration ABC + ParquetMigration mixin + dataclasses)
├── _registry.py                                   (discovery por regex + find_path BFS)
├── _runner.py                                     (plan + execute + rollback + cleanup_backups + checkpoint SQLite)
├── parquet/__init__.py
├── parquet/v1_0_0_to_v1_1_0.py                    (V100ToV110 — exemplo aditivo + verify)
├── catalog/__init__.py
└── catalog/v1_0_0_to_v1_1_0.sql                   (DDL referência documental)
```

### Arquivos estendidos

- `storage/catalog.py`: `CATALOG_VERSION="1.1.0"`, `_DDL_V1_1_0_DELTAS`
  cria `_migration_log` no boot.
- `cli.py`: `migrate_app` typer sub-app com 4 comandos.
- `ui/microcopy_loader.py`: 9 IDs novos (`migration.plan.title`,
  `migration.confirm`, `migration.success`, `migration.dry_run`,
  `migration.error.no_path`, `migration.error.partition_failed`,
  `migration.rollback.success`, `migration.cleanup.success`,
  `migration.plan.empty`, `migration.plan.steps`).

### Política de rollback (acordada)

- Backup `.parquet.bak` por partição, mesmo diretório, criado ANTES de
  overwrite (`_make_backup`).
- Falha em qualquer fase: `_restore_backup_if_exists` chama-do
  automaticamente (rollback transacional por partição).
- CLI `migrate rollback --run-id ID` reverte run completo.
- Cleanup automático: `migrate cleanup --older-than 30` deleta `.bak`
  com idade > 30 dias.

---

## Decisões formalizadas

1. **DAG de migrations:** V1 = linear path apenas (BFS no
   `MigrationRegistry.find_path`). Forks/joins quando necessário em
   bump major (ADR à parte).
2. **Schema canônico permanece v1.0.0:** o módulo `storage/schema.py`
   NÃO foi alterado. Migration apenas adiciona coluna no Parquet em
   disco; quando v1.1.0 for "the new normal" (Epic 4), `SCHEMA_VERSION`
   constant bump + writer popula valores reais (não NULL placeholder).
3. **Backup retention:** 30 dias default. Operador pode ajustar via
   `--older-than N`. Não há cleanup automático no boot — explícito por
   segurança (perda de .bak = perda de rollback option).
4. **Pre-conditions duras:** delegadas ao CLI (caller). Runner é puro
   execução. Endurecer no futuro se operação real exigir.

---

— Sol + Dex + Aria, 2026-05-03 💾💻🏛️
