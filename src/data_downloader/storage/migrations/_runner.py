"""data_downloader.storage.migrations._runner — execução partition-by-partition.

Owner: Sol (policy) | Impl: Dex.
Refs:

- Story 2.3 — AC4 (dry-run no I/O), AC5 (checkpoint SQLite),
  AC6 (catalog atualizado pós-migration), AC7 (rollback policy).
- ``docs/storage/MIGRATIONS.md`` §3 (CLI), §4 (rollback).

``MigrationRunner`` orquestra:

1. ``plan(from, to, *, dry_run=False)`` — gera ``MigrationPlan`` listando
   partições afetadas + steps + estimativas (sem I/O em dry-run).
2. ``execute(plan, *, run_id=None, continue_on_error=False)`` — itera
   partições, para cada uma:
   - cria backup ``.parquet.bak``
   - lê via ``Migration.read_old`` (multi-step se aplicável)
   - aplica ``Migration.transform``
   - escreve atomicamente via ``Migration.write_new``
   - verifica via ``Migration.verify``
   - atualiza ``catalog.partitions.schema_version``
   - registra estado em ``_migration_log``
3. ``rollback(run_id)`` — reverte: restaura ``.bak`` + atualiza catalog.
4. ``cleanup_backups(*, older_than_days=30)`` — remove ``.bak`` antigos.

Resume: ``execute(plan, run_id=...)`` reutiliza ``_migration_log`` para
pular partições já ``status='migrated'`` (AC5).

Pre-conditions (AC3 §3.3 MIGRATIONS.md): caller (CLI) é responsável por
validar ``_pending_commits`` vazio + lock file + disk space ANTES de
chamar ``execute``. ``MigrationRunner`` é puro execução.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from data_downloader.storage.catalog import Catalog
from data_downloader.storage.migrations._base import (
    Migration,
    MigrationPlan,
    MigrationRunResult,
    MigrationStep,
    PartitionMigrationOutcome,
)
from data_downloader.storage.migrations._registry import MigrationRegistry

_LOG = logging.getLogger(__name__)

# Idade default para considerar .bak elegível para cleanup (AC §4.4).
_BACKUP_RETENTION_DAYS_DEFAULT: int = 30


def _utcnow_iso() -> str:
    """Timestamp ISO compatível com SQLite TIMESTAMP textual."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class _MigrationLogRow:
    """Linha de ``_migration_log`` (representação Python para tests)."""

    run_id: str
    partition_path: str
    from_version: str
    to_version: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


@dataclass
class MigrationRunner:
    """Executa migrations partição-a-partição com checkpoint resumível.

    Args:
        catalog: Instância de ``Catalog`` já inicializada.
        data_dir: Raiz dos dados (``data/``). Resolve paths relativos
            de partição contra ``data_dir / "history"``.
        registry: ``MigrationRegistry`` (default: descoberta automática).
    """

    catalog: Catalog
    data_dir: Path
    registry: MigrationRegistry = field(default_factory=MigrationRegistry.discover)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self._ensure_log_table()

    # ------------------------------------------------------------------
    # Schema log
    # ------------------------------------------------------------------

    def _ensure_log_table(self) -> None:
        """Cria ``_migration_log`` se ainda não existe (AC5).

        Idempotente — re-execução é no-op. DDL espelha
        MIGRATIONS.md §4.3.
        """
        conn = self.catalog._conn_or_raise()
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_migration_log_run " "ON _migration_log(run_id, status)"
        )

    # ------------------------------------------------------------------
    # plan()
    # ------------------------------------------------------------------

    def plan(
        self,
        from_version: str,
        to_version: str,
        *,
        symbol: str | None = None,
    ) -> MigrationPlan:
        """Gera plano: partições afetadas + steps + estimativas (sem I/O).

        Args:
            from_version: Versão de origem.
            to_version: Versão alvo.
            symbol: Restringe a um símbolo (opcional — sandbox/teste).

        Returns:
            ``MigrationPlan`` imutável.

        Raises:
            ValueError: Não há path entre as versões.
        """
        # 1. Calcular path de migration.
        chain = self.registry.find_path(from_version, to_version)
        steps = tuple(
            MigrationStep(
                from_version=mig.from_version,
                to_version=mig.to_version,
                description=mig.description,
                breaking=mig.breaking,
                rollback_supported=mig.rollback_supported,
            )
            for mig in chain
        )

        # 2. Identifica partições afetadas (status atual = from_version).
        conn = self.catalog._conn_or_raise()
        if symbol:
            rows = conn.execute(
                "SELECT partition_path, file_size_bytes FROM partitions "
                "WHERE schema_version = ? AND symbol = ? "
                "ORDER BY partition_path",
                (from_version, symbol),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT partition_path, file_size_bytes FROM partitions "
                "WHERE schema_version = ? "
                "ORDER BY partition_path",
                (from_version,),
            ).fetchall()
        affected = tuple(r["partition_path"] for r in rows)
        bytes_total = int(sum(r["file_size_bytes"] for r in rows))

        # 3. ETA simplificado: 50 MB/s heurística (ADR-002 dedup throughput).
        eta = (bytes_total / (50 * 1024 * 1024)) if bytes_total else 0.0

        return MigrationPlan(
            steps=steps,
            affected_partitions=affected,
            bytes_read_estimate=bytes_total,
            bytes_write_estimate=bytes_total,  # heurística aditivo: ~similar
            eta_seconds=eta,
        )

    # ------------------------------------------------------------------
    # execute()
    # ------------------------------------------------------------------

    def execute(
        self,
        plan: MigrationPlan,
        *,
        run_id: str | None = None,
        continue_on_error: bool = False,
        dry_run: bool = False,
    ) -> MigrationRunResult:
        """Executa um plano de migração partição-a-partição.

        Args:
            plan: Plano gerado por :meth:`plan`.
            run_id: UUID do run. Se ``None``, gera novo. Se provido e
                já existe em ``_migration_log``, RESUME (skip migrated).
            continue_on_error: Se ``True``, registra falhas e continua;
                se ``False``, para na primeira falha (default — AC5).
            dry_run: Se ``True``, simula sem escrever (AC4).

        Returns:
            ``MigrationRunResult`` imutável.
        """
        if run_id is None:
            run_id = uuid.uuid4().hex

        if not plan.steps:
            return MigrationRunResult(
                run_id=run_id,
                partitions_migrated=0,
                partitions_failed=0,
                partitions_skipped=0,
                duration_seconds=0.0,
            )

        chain = [self.registry.get(s.from_version, s.to_version) or _missing(s) for s in plan.steps]
        # MyPy: lista de Migration garantida (assert acima).
        chain_typed: list[Migration] = [m for m in chain if m is not None]

        start_time = time.time()
        outcomes: list[PartitionMigrationOutcome] = []
        n_migrated = n_failed = n_skipped = 0

        for rel_path in plan.affected_partitions:
            # Resume: skip se já migrated neste run.
            if self._is_already_migrated(run_id, rel_path):
                n_skipped += 1
                outcomes.append(
                    PartitionMigrationOutcome(
                        partition_path=rel_path,
                        from_version=chain_typed[0].from_version,
                        to_version=chain_typed[-1].to_version,
                        status="skipped",
                    )
                )
                continue

            self._record_log(
                run_id, rel_path, chain_typed[0].from_version, chain_typed[-1].to_version, "pending"
            )

            disk_path = (self.data_dir / "history" / rel_path).resolve()
            if not disk_path.exists():
                err = f"partition file not found: {disk_path}"
                self._update_log(run_id, rel_path, "failed", error=err)
                outcomes.append(
                    PartitionMigrationOutcome(
                        partition_path=rel_path,
                        from_version=chain_typed[0].from_version,
                        to_version=chain_typed[-1].to_version,
                        status="failed",
                        error=err,
                    )
                )
                n_failed += 1
                if not continue_on_error:
                    break
                continue

            t0 = time.time()
            try:
                rows = self._migrate_one_partition(disk_path, chain_typed, dry_run=dry_run)
                elapsed = time.time() - t0

                if not dry_run:
                    self._update_catalog_schema_version(rel_path, chain_typed[-1].to_version)
                    self._update_catalog_checksum(rel_path, disk_path)

                self._update_log(run_id, rel_path, "migrated")
                n_migrated += 1
                outcomes.append(
                    PartitionMigrationOutcome(
                        partition_path=rel_path,
                        from_version=chain_typed[0].from_version,
                        to_version=chain_typed[-1].to_version,
                        status="migrated",
                        rows=rows,
                        duration_s=elapsed,
                    )
                )
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                _LOG.exception("migration.partition_failed", extra={"path": rel_path})
                # Rollback automático desta partição (restaura .bak).
                if not dry_run:
                    self._restore_backup_if_exists(disk_path)
                self._update_log(run_id, rel_path, "failed", error=err)
                outcomes.append(
                    PartitionMigrationOutcome(
                        partition_path=rel_path,
                        from_version=chain_typed[0].from_version,
                        to_version=chain_typed[-1].to_version,
                        status="failed",
                        error=err,
                    )
                )
                n_failed += 1
                if not continue_on_error:
                    break

        duration = time.time() - start_time
        return MigrationRunResult(
            run_id=run_id,
            partitions_migrated=n_migrated,
            partitions_failed=n_failed,
            partitions_skipped=n_skipped,
            duration_seconds=duration,
            outcomes=tuple(outcomes),
        )

    def _migrate_one_partition(
        self, disk_path: Path, chain: list[Migration], *, dry_run: bool
    ) -> int:
        """Aplica chain de migrations sequencialmente em UMA partição.

        Returns: rows migrated.
        """
        if not dry_run:
            self._make_backup(disk_path)

        current_path = disk_path
        rows = 0
        for mig in chain:
            table = mig.read_old(current_path)
            new_table = mig.transform(table)
            result = mig.write_new(new_table, current_path, dry_run=dry_run)
            rows = result.rows

            if not dry_run:
                # Verify NOT em dry-run — arquivo só existe pós-write real.
                ok = mig.verify(current_path, current_path)
                if not ok:
                    raise RuntimeError(
                        f"verify() failed for {disk_path} after migration "
                        f"{mig.from_version} -> {mig.to_version}"
                    )
        return rows

    # ------------------------------------------------------------------
    # rollback()
    # ------------------------------------------------------------------

    def rollback(self, run_id: str) -> MigrationRunResult:
        """Restaura ``.bak`` de cada partição com ``status='migrated'``.

        Args:
            run_id: ID do run a reverter.

        Returns:
            ``MigrationRunResult`` com estatísticas do rollback.
        """
        rows = self._fetch_log_rows(run_id, status="migrated")
        if not rows:
            return MigrationRunResult(
                run_id=run_id,
                partitions_migrated=0,
                partitions_failed=0,
                partitions_skipped=0,
                duration_seconds=0.0,
            )

        start_time = time.time()
        outcomes: list[PartitionMigrationOutcome] = []
        n_migrated = n_failed = 0

        for r in rows:
            disk_path = (self.data_dir / "history" / r.partition_path).resolve()
            try:
                self._restore_backup_if_exists(disk_path, raise_if_missing=True)
                # Restaurar checksum + schema_version no catálogo.
                self._update_catalog_schema_version(r.partition_path, r.from_version)
                self._update_catalog_checksum(r.partition_path, disk_path)
                self._update_log(run_id, r.partition_path, "rolled_back")
                n_migrated += 1
                outcomes.append(
                    PartitionMigrationOutcome(
                        partition_path=r.partition_path,
                        from_version=r.to_version,
                        to_version=r.from_version,
                        status="rolled_back",
                    )
                )
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                _LOG.exception("migration.rollback_failed", extra={"path": r.partition_path})
                self._update_log(run_id, r.partition_path, "failed", error=f"rollback: {err}")
                outcomes.append(
                    PartitionMigrationOutcome(
                        partition_path=r.partition_path,
                        from_version=r.to_version,
                        to_version=r.from_version,
                        status="failed",
                        error=err,
                    )
                )
                n_failed += 1

        duration = time.time() - start_time
        return MigrationRunResult(
            run_id=run_id,
            partitions_migrated=n_migrated,
            partitions_failed=n_failed,
            partitions_skipped=0,
            duration_seconds=duration,
            outcomes=tuple(outcomes),
        )

    # ------------------------------------------------------------------
    # cleanup_backups()
    # ------------------------------------------------------------------

    def cleanup_backups(
        self, *, older_than_days: int = _BACKUP_RETENTION_DAYS_DEFAULT
    ) -> list[Path]:
        """Remove ``.bak`` antigos sob ``data/history/**``.

        Args:
            older_than_days: Idade mínima (dias) para deletar.

        Returns:
            Lista de paths removidos (auditoria).
        """
        history_root = self.data_dir / "history"
        if not history_root.exists():
            return []

        cutoff = time.time() - (older_than_days * 24 * 3600)
        removed: list[Path] = []
        for path in history_root.rglob("*.parquet.bak"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime > cutoff:
                continue
            try:
                path.unlink()
                removed.append(path)
            except OSError as exc:
                _LOG.warning(
                    "migration.cleanup.unlink_failed",
                    extra={"path": str(path), "err": str(exc)},
                )
        return removed

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _make_backup(self, path: Path) -> Path:
        """Cria ``.bak`` antes de overwrite (AC7).

        Returns: caminho do backup criado.

        Política: se ``.bak`` já existe (resume parcial), preserva o
        existente — assumimos que é o original PRÉ-migração.
        """
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            return backup
        # Cópia byte-a-byte (não usar rename — original deve permanecer
        # legível durante migration).
        backup.write_bytes(path.read_bytes())
        # fsync best-effort.
        try:
            fd = os.open(str(backup), os.O_RDWR)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        return backup

    def _restore_backup_if_exists(self, path: Path, *, raise_if_missing: bool = False) -> bool:
        """Restaura ``{path}.bak`` em ``path`` se existir.

        Args:
            path: Path do arquivo a restaurar.
            raise_if_missing: Se ``True`` e ``.bak`` não existe, raise.

        Returns:
            ``True`` se restauração ocorreu.
        """
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            if raise_if_missing:
                raise FileNotFoundError(f"backup file missing for rollback: {backup}")
            return False
        # Atomic replace.
        os.replace(backup, path)
        return True

    def _record_log(
        self,
        run_id: str,
        partition_path: str,
        from_version: str,
        to_version: str,
        status: str,
    ) -> None:
        """INSERT em ``_migration_log`` (UPSERT em conflito)."""
        conn = self.catalog._conn_or_raise()
        with self.catalog._transaction():
            conn.execute(
                """
                INSERT INTO _migration_log(
                    run_id, partition_path, from_version, to_version,
                    status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, partition_path) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at,
                    error = NULL,
                    completed_at = NULL
                """,
                (run_id, partition_path, from_version, to_version, status, _utcnow_iso()),
            )

    def _update_log(
        self,
        run_id: str,
        partition_path: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        """Atualiza status (e completed_at) de uma entrada existente."""
        conn = self.catalog._conn_or_raise()
        with self.catalog._transaction():
            conn.execute(
                """
                UPDATE _migration_log
                SET status = ?, completed_at = ?, error = ?
                WHERE run_id = ? AND partition_path = ?
                """,
                (status, _utcnow_iso(), error, run_id, partition_path),
            )

    def _is_already_migrated(self, run_id: str, partition_path: str) -> bool:
        """Resume helper: ``True`` se entry já tem status='migrated'."""
        conn = self.catalog._conn_or_raise()
        row = conn.execute(
            "SELECT status FROM _migration_log " "WHERE run_id = ? AND partition_path = ?",
            (run_id, partition_path),
        ).fetchone()
        if row is None:
            return False
        return bool(row["status"] == "migrated")

    def _fetch_log_rows(self, run_id: str, *, status: str | None = None) -> list[_MigrationLogRow]:
        """Lê linhas de ``_migration_log`` (filtro opcional por status)."""
        conn = self.catalog._conn_or_raise()
        if status:
            rows = conn.execute(
                "SELECT * FROM _migration_log WHERE run_id = ? AND status = ? "
                "ORDER BY partition_path",
                (run_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM _migration_log WHERE run_id = ? " "ORDER BY partition_path",
                (run_id,),
            ).fetchall()
        return [
            _MigrationLogRow(
                run_id=r["run_id"],
                partition_path=r["partition_path"],
                from_version=r["from_version"],
                to_version=r["to_version"],
                status=r["status"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                error=r["error"],
            )
            for r in rows
        ]

    def _update_catalog_schema_version(self, partition_path: str, schema_version: str) -> None:
        """Atualiza ``partitions.schema_version`` (AC6)."""
        conn = self.catalog._conn_or_raise()
        with self.catalog._transaction():
            conn.execute(
                "UPDATE partitions SET schema_version = ? WHERE partition_path = ?",
                (schema_version, partition_path),
            )

    def _update_catalog_checksum(self, partition_path: str, disk_path: Path) -> None:
        """Recalcula SHA256 + atualiza ``partitions.checksum_sha256``.

        Após migration, conteúdo do arquivo mudou — checksum NA
        ``partitions`` precisa refletir o novo conteúdo. Cache é
        invalidado em casacata (CASCADE FK).
        """
        from data_downloader.storage.parquet_writer import _sha256_file

        if not disk_path.exists():
            return
        new_checksum = _sha256_file(disk_path)
        new_size = disk_path.stat().st_size
        conn = self.catalog._conn_or_raise()
        with self.catalog._transaction():
            conn.execute(
                "UPDATE partitions SET checksum_sha256 = ?, file_size_bytes = ? "
                "WHERE partition_path = ?",
                (new_checksum, new_size, partition_path),
            )
            # Invalida cache (CASCADE FK pode não disparar em UPDATE).
            conn.execute(
                "DELETE FROM _checksum_cache WHERE partition_path = ?",
                (partition_path,),
            )


def _missing(step: MigrationStep) -> Migration | None:
    """Helper de erro — lança ValueError se um step do plano não tem migration."""
    raise ValueError(f"No migration registered for {step.from_version} -> {step.to_version}")


# Re-export para conveniência de imports.
__all__ = [
    "MigrationRunner",
]
