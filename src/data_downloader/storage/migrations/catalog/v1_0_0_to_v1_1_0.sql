-- Migration de catálogo SQLite v1.0.0 -> v1.1.0 (Story 2.3 AC8 + §2.1).
--
-- Owner: Sol (DDL/policy) | Impl: Dex.
-- Escopo: aditivo — adiciona tabela `_migration_log` (checkpoint resumível
-- do framework de migration de Parquet schema).
--
-- Note: A partir de v1.1.0 (ADR-024) o catalog vive em data/_internal/.
-- Migration silenciosa em runtime; este SQL é só para forensics manual.
--
-- NOTA: Esta DDL é REFERÊNCIA DOCUMENTAL. A fonte de verdade
-- executável vive em `data_downloader.storage.catalog._DDL_V1_1_0_DELTAS`
-- (aplicada via `Catalog._apply_migrations` no boot — idempotente).
-- Mantemos este arquivo para alinhar com a convenção AC1 (regex
-- `v\d+_\d+_\d+_to_v\d+_\d+_\d+\.sql`) e auditoria histórica.
--
-- Para aplicar manualmente em um catálogo existente sem reiniciar o
-- processo:
--
--     sqlite3 data/_internal/catalog.db < v1_0_0_to_v1_1_0.sql

BEGIN;

CREATE TABLE IF NOT EXISTS _migration_log (
    run_id            TEXT NOT NULL,
    partition_path    TEXT NOT NULL,
    from_version      TEXT NOT NULL,
    to_version        TEXT NOT NULL,
    status            TEXT NOT NULL CHECK(status IN
                          ('pending','migrated','rolled_back','failed')),
    started_at        TIMESTAMP,
    completed_at      TIMESTAMP,
    error             TEXT,
    PRIMARY KEY (run_id, partition_path)
);

CREATE INDEX IF NOT EXISTS idx_migration_log_run
    ON _migration_log(run_id, status);

UPDATE _schema_meta SET value = '1.1.0' WHERE key = 'catalog_version';

COMMIT;
