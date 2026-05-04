"""data_downloader.storage.migrations._base — ABC + mixins + dataclasses.

Owner: Sol (policy) | Impl: Dex.
Refs:

- ``docs/storage/MIGRATIONS.md`` §2 (anatomia de uma migration)
- ``docs/storage/SCHEMA.md`` §6 (política de migração R4)
- Story 2.3 — AC2 (Classe base ``Migration``)

A ABC ``Migration`` é o contrato estável para qualquer migration de
schema Parquet. Migrations concretas vivem em
``migrations/parquet/v{from}_to_{to}.py`` e implementam ``transform``
(default ``read_old`` / ``write_new`` em :class:`ParquetMigration`).

Mixin ``ParquetMigration`` provê implementação default de ``read_old``
(``pq.read_table``) e ``write_new`` (atomic tmp + ``os.replace`` +
metadata custom — espelha a semântica de
:class:`data_downloader.storage.parquet_writer.ParquetWriter`).
"""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq

# =====================================================================
# Dataclasses imutáveis (resultado / plano)
# =====================================================================


@dataclass(frozen=True)
class MigrationResult:
    """Resultado imutável da execução de uma migration sobre 1 partição.

    Atributos:
        rows: Número de linhas migradas.
        bytes_estimate: Estimativa de bytes a escrever (para ``dry_run``).
        bytes_actual: Bytes efetivamente escritos (``0`` em dry-run).
        duration_s: Duração em segundos (wallclock).
        status: ``"migrated"`` | ``"dry_run"`` | ``"skipped"`` | ``"failed"``.
    """

    rows: int = 0
    bytes_estimate: int = 0
    bytes_actual: int = 0
    duration_s: float = 0.0
    status: str = "migrated"


@dataclass(frozen=True)
class MigrationStep:
    """Um passo dentro de um plano de migração (1 hop entre versões)."""

    from_version: str
    to_version: str
    description: str
    breaking: bool
    rollback_supported: bool


@dataclass(frozen=True)
class MigrationPlan:
    """Plano completo de migração — N partições * M steps.

    Output do ``MigrationRunner.plan(...)``. Em ``dry_run=True``, é o
    único artefato produzido (nenhuma escrita acontece).
    """

    steps: tuple[MigrationStep, ...]
    affected_partitions: tuple[str, ...]
    bytes_read_estimate: int = 0
    bytes_write_estimate: int = 0
    eta_seconds: float = 0.0

    @property
    def is_noop(self) -> bool:
        """``True`` se não há partições afetadas ou steps a aplicar."""
        return not self.affected_partitions or not self.steps


@dataclass(frozen=True)
class PartitionMigrationOutcome:
    """Resultado da migração de UMA partição (membro de ``MigrationRunResult``).

    Trace completo do que aconteceu — usado por testes e reports.
    """

    partition_path: str
    from_version: str
    to_version: str
    status: str  # "migrated" | "skipped" | "failed" | "rolled_back"
    rows: int = 0
    duration_s: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class MigrationRunResult:
    """Resultado completo de uma execução (``MigrationRunner.execute``)."""

    run_id: str
    partitions_migrated: int
    partitions_failed: int
    partitions_skipped: int
    duration_seconds: float
    outcomes: tuple[PartitionMigrationOutcome, ...] = field(default_factory=tuple)


# =====================================================================
# ABC Migration
# =====================================================================


class Migration(ABC):
    """ABC — contrato estável para migrations de schema Parquet.

    Subclasses concretas declaram metadata como atributos de classe
    (``ClassVar``) e implementam ``transform``. ``read_old`` /
    ``write_new`` têm defaults em :class:`ParquetMigration` (mixin
    canônico para 99% dos casos).

    Política R4 (SCHEMA.md §6):

    - ``breaking=False`` (minor) — leitor antigo tolera arquivo novo;
      campo novo é nullable; nenhum drop/rename/type change.
    - ``breaking=True`` (major) — exige ADR + janela de manutenção +
      rollback policy explícita.
    """

    # Atributos OBRIGATÓRIOS em subclasses concretas (ClassVar).
    from_version: ClassVar[str] = ""
    to_version: ClassVar[str] = ""
    breaking: ClassVar[bool] = False
    description: ClassVar[str] = ""
    rollback_supported: ClassVar[bool] = True

    def applies_to(self, current_version: str) -> bool:
        """``True`` se esta migration deve rodar partindo de ``current_version``.

        Default: igualdade exata com ``from_version``. Subclasses podem
        sobrescrever para suportar matching mais permissivo (ex.: "qualquer
        v1.x.y").
        """
        return current_version == self.from_version

    @abstractmethod
    def read_old(self, path: Path) -> pa.Table:
        """Lê o arquivo Parquet antigo (versão ``from_version``)."""

    @abstractmethod
    def transform(self, table: pa.Table) -> pa.Table:
        """Transforma a tabela para o schema ``to_version``.

        Implementação concreta de cada migration. NUNCA muda metadata
        custom — isso é responsabilidade de ``write_new`` (que espelha o
        contrato do :class:`ParquetWriter`).
        """

    @abstractmethod
    def write_new(self, table: pa.Table, dst: Path, *, dry_run: bool = False) -> MigrationResult:
        """Escreve atomicamente a tabela transformada em ``dst``.

        Em ``dry_run=True``, apenas calcula estimativa de bytes e retorna
        ``MigrationResult(status='dry_run', bytes_actual=0)`` SEM tocar
        no disco.
        """

    def verify(self, src_old: Path, dst_new: Path) -> bool:
        """Pós-check da migração — overrideable por subclasses.

        Default: confirma que o arquivo ``dst_new`` existe, é não-vazio
        e tem o ``schema_version`` esperado no metadata custom.

        Retorna ``False`` se algum invariante quebrar — runner trata
        isso como falha e dispara rollback.
        """
        if not dst_new.exists() or dst_new.stat().st_size == 0:
            return False
        try:
            md = pq.read_metadata(dst_new).metadata
        except (OSError, ValueError):
            return False
        if md is None:
            return False
        raw = md.get(b"schema_version", b"")
        actual: str = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return actual == self.to_version


# =====================================================================
# Mixin ParquetMigration — defaults read_old/write_new
# =====================================================================


class ParquetMigration(Migration):
    """Default ``read_old`` / ``write_new`` para migrations Parquet.

    Subclasses só precisam implementar ``transform`` (e opcionalmente
    sobrescrever ``verify`` para checks específicos do campo novo).

    A escrita usa o pipeline atomic do writer principal:
    tmp + fsync + os.replace + fsync(parent_dir). NÃO copia código —
    importa ``compute_sha256_streaming`` para manter consistência de
    SHA256 (R4 — schema metadata canônico).
    """

    # Configuração Parquet — espelha ADR-002 (snappy, row_group=100k).
    _COMPRESSION: ClassVar[str] = "snappy"
    _ROW_GROUP_SIZE: ClassVar[int] = 100_000

    def read_old(self, path: Path) -> pa.Table:
        """Lê Parquet via :func:`pq.read_table` (sem cast de schema).

        Não força schema canônico — migration pode estar lendo arquivo
        de versão antiga onde o schema canônico ATUAL não se aplica.
        """
        return pq.read_table(path)

    def _build_metadata(self, table: pa.Table) -> dict[bytes, bytes]:
        """Monta metadata Parquet custom — espelha SCHEMA.md §4.

        ``schema_version`` é forçada para ``self.to_version``.
        """
        if table.num_rows == 0:
            first_ts = 0
            last_ts = 0
        else:
            ts_col = table.column("timestamp_ns") if "timestamp_ns" in table.schema.names else None
            if ts_col is None:
                first_ts = 0
                last_ts = 0
            else:
                first_ts = int(pa.compute.min(ts_col).as_py())
                last_ts = int(pa.compute.max(ts_col).as_py())
        return {
            b"schema_version": self.to_version.encode("utf-8"),
            b"row_count": str(table.num_rows).encode("utf-8"),
            b"first_ts_ns": str(first_ts).encode("utf-8"),
            b"last_ts_ns": str(last_ts).encode("utf-8"),
            b"created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ").encode("utf-8"),
            b"compression": self._COMPRESSION.encode("utf-8"),
            b"row_group_size": str(self._ROW_GROUP_SIZE).encode("utf-8"),
            b"migrated_from": self.from_version.encode("utf-8"),
        }

    def write_new(self, table: pa.Table, dst: Path, *, dry_run: bool = False) -> MigrationResult:
        """Escreve atomicamente: tmp + fsync + os.replace.

        Em ``dry_run=True``, NÃO escreve nada — apenas estima bytes via
        soma das colunas (heurística) e retorna ``MigrationResult``.
        """
        # Aplica metadata custom no schema ANTES de escrever (pyarrow exige).
        metadata = self._build_metadata(table)
        table_with_md = table.replace_schema_metadata(metadata)

        if dry_run:
            # Estimativa simplificada: ~size_of_pa_table_in_memory.
            # Não acessa disco; usa nbytes do pyarrow.
            bytes_estimate = int(table_with_md.nbytes)
            return MigrationResult(
                rows=table_with_md.num_rows,
                bytes_estimate=bytes_estimate,
                bytes_actual=0,
                duration_s=0.0,
                status="dry_run",
            )

        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f"{dst.name}.tmp.{uuid.uuid4().hex}")

        try:
            with pq.ParquetWriter(
                tmp,
                table_with_md.schema,
                compression=self._COMPRESSION,
            ) as writer:
                writer.write_table(table_with_md, row_group_size=self._ROW_GROUP_SIZE)

            # fsync(file) — Windows + Linux.
            fd = os.open(str(tmp), os.O_RDWR)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

            file_size = tmp.stat().st_size
            # Atomic replace.
            os.replace(tmp, dst)
        except Exception:
            if tmp.exists():
                import contextlib

                with contextlib.suppress(OSError):
                    tmp.unlink()
            raise

        return MigrationResult(
            rows=table_with_md.num_rows,
            bytes_estimate=int(table_with_md.nbytes),
            bytes_actual=file_size,
            duration_s=0.0,
            status="migrated",
        )


__all__ = [
    "Migration",
    "MigrationPlan",
    "MigrationResult",
    "MigrationRunResult",
    "MigrationStep",
    "ParquetMigration",
    "PartitionMigrationOutcome",
]
