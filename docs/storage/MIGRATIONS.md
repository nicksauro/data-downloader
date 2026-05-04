# MIGRATIONS.md — Framework de Migração de Schema

**Owner:** 💾 Sol (Storage Engineer)
**Versão:** v1.0.0 (esqueleto)
**Status:** SCAFFOLD (será preenchido conforme primeira migração real surgir)

> Este documento descreve o **framework**. Migrações concretas (ex: `v1_0_0_to_v1_1_0.py`) são adicionadas em `src/data_downloader/storage/migrations/` quando necessárias e referenciadas em §6 abaixo.

---

## 0. Quando uma migração é necessária

Ver `SCHEMA.md` §6.1 — tabela de classificação de mudanças. Resumo:

| Tipo                                | Migração necessária? |
|-------------------------------------|----------------------|
| Bump minor (aditivo)                | NÃO. Leitor tolera ausência do campo em arquivos antigos. |
| Bump major (quebrador)              | SIM. Script obrigatório.                                  |
| Mudança de layout de particionamento| SIM + ADR + janela de manutenção.                         |
| Mudança no catálogo (DDL SQLite)    | SIM. Migração SQL via `_schema_meta.catalog_version`.     |

---

## 1. Estrutura de diretório

```
src/data_downloader/storage/migrations/
├── __init__.py
├── _registry.py                        # registry de migrações conhecidas
├── _runner.py                          # executor (dry-run, backup, rollback)
├── parquet/
│   ├── v1_0_0_to_v1_1_0.py            # exemplo: bump minor (aditivo) — geralmente vazio
│   ├── v1_x_to_v2_0_0.py              # exemplo: bump major
│   └── ...
└── catalog/
    ├── v1_0_0_to_v1_1_0.sql            # DDL ALTER TABLE
    └── ...
```

---

## 2. Anatomia de uma migração

### 2.1 Migration de schema Parquet (Python)

Cada migration implementa um Protocol estável:

```python
# src/data_downloader/storage/migrations/parquet/_base.py
from typing import Protocol
from pathlib import Path

class ParquetMigration(Protocol):
    """Migra um arquivo Parquet de uma versão para outra."""

    from_version: str        # "1.0.0"
    to_version: str          # "2.0.0"
    breaking: bool           # True se major bump
    description: str         # human-readable

    def applies_to(self, current_version: str) -> bool:
        """True se esta migration deve rodar partindo de `current_version`."""

    def migrate_file(self, src: Path, dst: Path, dry_run: bool = False) -> MigrationResult:
        """
        Lê src (Parquet v{from_version}), escreve dst (Parquet v{to_version}).
        Em dry_run: não escreve, apenas retorna stats.
        """

    def rollback_file(self, src: Path, dst: Path) -> MigrationResult:
        """
        Reverte: lê src (v{to_version}), escreve dst (v{from_version}).
        Pode raise NotImplementedError se rollback é impossível
        (ex: campo dropado sem cópia do dado original).
        """
```

### 2.2 Esqueleto de exemplo (`v1_0_0_to_v1_1_0.py`)

```python
"""
Migration: schema Parquet v1.0.0 -> v1.1.0
Tipo: aditivo (bump minor)
Mudança hipotética: adicionar campo `market_phase string nullable`.
"""
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from data_downloader.storage.migrations.parquet._base import MigrationResult

class Migration:
    from_version = "1.0.0"
    to_version = "1.1.0"
    breaking = False
    description = "Add nullable market_phase field."

    def applies_to(self, current_version: str) -> bool:
        return current_version == self.from_version

    def migrate_file(self, src: Path, dst: Path, dry_run: bool = False) -> MigrationResult:
        table = pq.read_table(src)
        new_col = pa.array([None] * table.num_rows, type=pa.string())
        new_table = table.append_column("market_phase", new_col)
        if dry_run:
            return MigrationResult(rows=table.num_rows, bytes_estimate=...)
        # update metadata
        existing_md = pq.read_metadata(src).metadata or {}
        new_md = {**existing_md, b'schema_version': b'1.1.0'}
        pq.write_table(new_table, dst, compression='snappy',
                       row_group_size=100_000, metadata_collector=None)
        # ... patch metadata ...
        return MigrationResult(rows=table.num_rows, bytes_actual=dst.stat().st_size)

    def rollback_file(self, src: Path, dst: Path) -> MigrationResult:
        table = pq.read_table(src)
        if "market_phase" in table.schema.names:
            table = table.drop(["market_phase"])
        # write with v1.0.0 metadata
        ...
```

### 2.3 Migration de catálogo SQLite (SQL)

```sql
-- src/data_downloader/storage/migrations/catalog/v1_0_0_to_v1_1_0.sql
-- Aditivo: adiciona coluna `market_phase` em partitions (opcional)
BEGIN;
ALTER TABLE partitions ADD COLUMN observed_phases TEXT;
UPDATE _schema_meta SET value = '1.1.0' WHERE key = 'catalog_version';
COMMIT;
```

Migrations de catálogo são executadas em ordem por `_schema_meta.catalog_version`.

---

## 3. CLI

### 3.1 Comando público

```
data-downloader migrate [opções]
```

Opções:

| Flag                           | Descrição                                                                    |
|--------------------------------|------------------------------------------------------------------------------|
| `--from {ver}`                 | Versão de origem (auto-detectada se omitida).                               |
| `--to {ver}`                   | Versão de destino (default: latest).                                        |
| `--dry-run`                    | Não escreve nada. Reporta plano de migração + estimativas.                  |
| `--backup-dir {path}`          | Diretório para backup pré-migração. **Obrigatório** salvo `--i-have-backup`.|
| `--i-have-backup`              | Confirma explicitamente que usuário fez backup externo. Loga warning.        |
| `--symbol {X}`                 | Migra apenas partições de um símbolo (sandbox/teste).                        |
| `--parallel {N}`               | Workers paralelos (default 1; cuidado com I/O).                              |
| `--rollback`                   | Reverte de `--to` para `--from` (se rollback suportado).                     |
| `--continue-on-error`          | Continua se uma partição falhar (default: para na primeira).                 |

### 3.2 Workflow padrão (recomendado)

```bash
# 1. Inspeção
data-downloader migrate --to 2.0.0 --dry-run

# Output mostra:
#   - 47 partitions atualmente em 1.0.0
#   - Estimativa: 12.4 GB lidos, 13.1 GB escritos, ~22 minutos
#   - 3 catálogos SQLite a migrar
#   - Migration v1_0_0_to_v2_0_0: BREAKING — drops field `flags`, renames `quantity → qty`
#   - Rollback disponível: SIM (preserva `flags` em coluna lateral _legacy_flags)

# 2. Backup
data-downloader migrate --to 2.0.0 --backup-dir /backups/2026-05-03/

# Backup copia data/history/** + catalog.db inteiro antes de tocar nada.

# 3. Verificação pós-migração
data-downloader integrity-check --checks all
```

### 3.3 Pré-condições obrigatórias

Antes de executar (não dry-run):

1. Catálogo `_pending_commits` deve estar vazio (nenhuma escrita pendente).
2. Nenhum processo do data-downloader ativo (lock file `data/.migrate.lock` adquirido).
3. Espaço em disco >= 2× tamanho atual de `data/history/` (para backup + escrita paralela).
4. Backup confirmado (via `--backup-dir` ou `--i-have-backup`).

Falha em qualquer pré-condição → migration aborta com exit code 4.

---

## 4. Política de rollback

### 4.1 Quando rollback é possível

- **Aditivo (minor)**: trivial — drop da coluna nova.
- **Quebrador (major) com preservação**: migration deve copiar dado original para coluna lateral `_legacy_*`. Rollback restaura.
- **Quebrador (major) sem preservação**: migration declara `rollback_supported = False`. Único rollback é restaurar do backup.

### 4.2 Regra dura

Migration que NÃO suporta rollback **deve** documentar isso no docstring + emitir warning grande no CLI:

```
WARNING: Migration v1.0.0 -> v2.0.0 does NOT support rollback.
         Field `flags` will be dropped without preservation.
         Confirm with --i-understand-no-rollback to proceed.
```

Sem a flag `--i-understand-no-rollback`, CLI recusa.

### 4.3 Rollback parcial

Se migration falha no meio (ex: 23 de 47 partições migradas, então erro de I/O):

- `--continue-on-error` (default OFF) → para na primeira falha; migrations já feitas ficam em v2.0.0; restantes em v1.0.0. Estado misto.
- Sol exige que migration registre **estado de cada partição** em tabela `_migration_log`:

```sql
CREATE TABLE _migration_log (
    run_id            TEXT NOT NULL,        -- UUID por execução de migrate
    partition_path    TEXT NOT NULL,
    from_version      TEXT NOT NULL,
    to_version        TEXT NOT NULL,
    status            TEXT NOT NULL CHECK(status IN ('pending','migrated','rolled_back','failed')),
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
    error             TEXT,
    PRIMARY KEY (run_id, partition_path)
);
```

Permite continuar execução interrompida (`data-downloader migrate --resume {run_id}`).

---

## 5. Testes obrigatórios para cada migration

Toda migration nova deve trazer 4 testes em `tests/storage/migrations/`:

1. **`test_round_trip`** — escreve dados v{from}, migra para v{to}, lê e compara semanticamente. Para campos preservados deve bater bit-a-bit. Para drops, valida ausência.
2. **`test_idempotent`** — rodar `migrate_file` duas vezes seguidas = mesmo resultado da primeira (segunda é no-op).
3. **`test_rollback`** (se suportado) — migrate → rollback → comparar com original.
4. **`test_dry_run_no_io`** — `dry_run=True` não cria/altera arquivo (mock filesystem ou check mtime).

---

## 6. Migrations registradas

> Atualizar esta seção a cada nova migration adicionada.

| From    | To      | Tipo       | Rollback | PR / ADR  | Estado       |
|---------|---------|------------|----------|-----------|--------------|
| —       | 1.0.0   | (initial)  | —        | Story 0.0 | Em uso       |
| 1.0.0   | 1.1.0   | aditivo    | sim      | Story 2.3 | Disponível   |

### v1.0.0 → v1.1.0 — aditivo (Story 2.3)

- **Mudança:** adiciona campo `liquidity_classification` (uint8 nullable, todos NULL).
- **Rationale:** placeholder para Epic 4 multi-asset. NULL preserva R4
  (leitor v1.0.0 lendo arquivo v1.1.0 ignora a coluna nova).
- **Implementação:**
  `src/data_downloader/storage/migrations/parquet/v1_0_0_to_v1_1_0.py`
  (`V100ToV110` — herda `ParquetMigration`).
- **Catálogo:** DDL adicional `_migration_log` aplicada via
  `Catalog._apply_migrations` (CATALOG_VERSION=1.1.0).
- **Testes:** `tests/unit/test_migration_base.py`,
  `tests/unit/test_migration_runner.py` (round-trip + rollback +
  resume), `tests/property/test_migration_aditive.py` (Hypothesis 100
  examples — INV-9), `tests/integration/test_migrate_cli.py` (CLI).
- **CLI:**

  ```bash
  data-downloader migrate plan --from 1.0.0 --to 1.1.0
  data-downloader migrate execute --from 1.0.0 --to 1.1.0 --yes
  data-downloader migrate rollback --run-id <id>
  data-downloader migrate cleanup --older-than 30
  ```

### Como adicionar uma nova migration

1. Crie `src/data_downloader/storage/migrations/parquet/v{X}_{Y}_{Z}_to_v{A}_{B}_{C}.py`
   herdando `ParquetMigration` (implementar apenas `transform`).
2. Para mudanças no catálogo, adicione entry em `Catalog.MIGRATIONS`
   (Python — fonte de verdade) + arquivo `.sql` referência em
   `migrations/catalog/`.
3. Adicione testes obrigatórios (round-trip / idempotent / rollback /
   dry-run + property test) — ver §5 e este §6 como template.
4. Atualize esta tabela + CHANGELOG `SCHEMA.md` §7.
5. Sol audit obrigatório antes de merge.

---

## 7. Referências

- `SCHEMA.md` §6 — Política de migração (classificação aditivo vs quebrador).
- ADR a criar quando primeira migration major surgir (sugestão: `ADR-018-schema-vN-migration.md`).
- Story 0.0 — criação deste esqueleto.

— Sol, custodiando o histórico 💾
