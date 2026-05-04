"""data_downloader.storage.migrations — Schema migration framework.

Owner: Sol (policy/audit) | Impl: Dex.
Refs:

- ``docs/storage/MIGRATIONS.md`` — esqueleto Sol (v1.0.0 SCAFFOLD)
- ``docs/storage/SCHEMA.md`` §6 — política de migração R4
- Story 2.3 — implementa o esqueleto como código real + CLI

Pacote do framework de migração de schema Parquet. Migrations concretas
em ``parquet/v{from}_to_v{to}.py`` (Python — transform de dados);
migrations de catálogo SQLite em ``catalog/v{from}_to_v{to}.sql``
(DDL ALTER TABLE — futuro V2).

API pública (re-exportada para ergonomia)::

    from data_downloader.storage.migrations import (
        Migration,                # ABC base (ou via ParquetMigration mixin)
        MigrationRegistry,        # discovery por convenção de nome
        MigrationRunner,          # execução partition-a-partição
        MigrationPlan,            # plano dry-run
        MigrationResult,          # resultado por arquivo
        MigrationRunResult,       # resultado por run
    )

## Como adicionar nova migration

1. Crie ``parquet/v{X}_{Y}_{Z}_to_v{A}_{B}_{C}.py``:

   ```python
   from data_downloader.storage.migrations._base import ParquetMigration
   import pyarrow as pa

   class VXYZtoVABC(ParquetMigration):
       from_version = "X.Y.Z"
       to_version = "A.B.C"
       breaking = False  # True = bump major + ADR
       description = "Aditivo: campo foo (uint8 nullable)"
       rollback_supported = True

       def transform(self, table: pa.Table) -> pa.Table:
           # adicionar / transformar colunas conforme contrato
           return table.append_column(
               "foo", pa.array([None] * table.num_rows, type=pa.uint8())
           )
   ```

2. (Opcional) Crie ``catalog/v{X}_..._to_v{A}_....sql`` se a migration
   exige mudança no schema do catálogo SQLite.

3. Adicione testes obrigatórios em ``tests/unit/test_migration_*.py``
   (round-trip, idempotência, rollback, dry-run sem I/O — ver
   MIGRATIONS.md §5).

4. Atualize ``docs/storage/MIGRATIONS.md`` §6 (registry table) +
   ``docs/storage/SCHEMA.md`` (declaração da nova versão).

## Convenção de nome (regex AC1)

Arquivos em ``parquet/`` que NÃO seguem ``v\\d+_\\d+_\\d+_to_v\\d+_\\d+_\\d+\\.py``
são REJEITADOS pelo registry com mensagem clara em
``MigrationRegistry.invalid_files`` (não levanta — apenas ignora +
expõe para diagnóstico).
"""

from __future__ import annotations

from data_downloader.storage.migrations._base import (
    Migration,
    MigrationPlan,
    MigrationResult,
    MigrationRunResult,
    MigrationStep,
    ParquetMigration,
    PartitionMigrationOutcome,
)
from data_downloader.storage.migrations._registry import (
    MigrationRegistry,
    discover_catalog_migrations,
)
from data_downloader.storage.migrations._runner import MigrationRunner

__all__ = [
    "Migration",
    "MigrationPlan",
    "MigrationRegistry",
    "MigrationResult",
    "MigrationRunResult",
    "MigrationRunner",
    "MigrationStep",
    "ParquetMigration",
    "PartitionMigrationOutcome",
    "discover_catalog_migrations",
]
