"""data_downloader.storage.parquet_writer — Escrita atômica Parquet.

Owner: Sol (policy) | Impl: Dex.
Refs:

- ``docs/storage/SCHEMA.md`` v1.0.0 (17 campos)
- ``docs/storage/INTEGRITY.md`` (atomicity, dedup, fsync)
- ``docs/adr/ADR-002-storage-stack.md`` (Snappy, row_group=100k)
- ``docs/adr/ADR-004-partition-layout.md`` (path layout)
- ``docs/adr/ADR-011-exception-hierarchy.md`` (IntegrityError)

Pipeline canônico de :meth:`ParquetWriter.write`:

    1. validar registros (storage.schema.validate_record)
    2. enriquecer com ingestion_ts_ns + dll_version + chunk_id
    3. assign_sequence_within_ns se algum trade não tem trade_id
    4. dedup do batch
    5. se arquivo existe: ler -> union -> dedup -> verificar threshold 5M
    6. resolve path; mkdir -p
    7. escreve em ``{path}.tmp.{uuid4}`` com metadata canônico
    8. fsync(file)
    9. SHA256 do tmp
    10. fsync(parent_dir) — best-effort (Linux semantics; Windows no-op)
    11. os.replace(tmp, final) — atômico Windows + Linux
    12. retorna ``WriteResult``

Threshold rewrite (finding H6, deferred): se ``existing_rows + new_rows
> 5_000_000``, raise ``IntegrityError`` — sub-particionamento é Story
2.X.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from data_downloader.public_api.exceptions import IntegrityError
from data_downloader.storage.dedup import (
    assign_sequence_within_ns,
    dedup,
)
from data_downloader.storage.partition import (
    PartitionKey,
    resolve_partition_path,
)
from data_downloader.storage.schema import (
    SCHEMA_VERSION,
    TradeRecord,
    pyarrow_schema,
    validate_record,
)

_LOG = logging.getLogger(__name__)

# Configuração Parquet (ADR-002).
_COMPRESSION: str = "snappy"
_ROW_GROUP_SIZE: int = 100_000
_USE_DICTIONARY: bool = True
_WRITE_STATISTICS: bool = True

# Threshold deferred (finding H6 — sub-particionamento Story 2.X).
_PARTITION_ROW_LIMIT: int = 5_000_000


@dataclass(frozen=True)
class WriteResult:
    """Resultado imutável de :meth:`ParquetWriter.write`.

    Atributos:
        path: Path absoluto do arquivo Parquet finalizado.
        row_count: Linhas no arquivo final (após dedup + merge).
        first_ts_ns: ``min(timestamp_ns)`` no arquivo.
        last_ts_ns: ``max(timestamp_ns)`` no arquivo.
        checksum_sha256: SHA256 hex (64 chars) do arquivo final.
        file_size_bytes: Tamanho on-disk do arquivo final.
    """

    path: Path
    row_count: int
    first_ts_ns: int
    last_ts_ns: int
    checksum_sha256: str
    file_size_bytes: int


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA256 hex de um arquivo, lido em chunks de 1MB."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _fsync_directory(directory: Path) -> None:
    """fsync(parent_dir) — best-effort.

    POSIX semantics: garante que a entrada do diretório (rename do
    ``replace``) é persistida antes de continuarmos. Em Windows
    ``os.fsync`` em FD de diretório falha; capturamos e logamos.
    """
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except (OSError, NotImplementedError) as exc:
        _LOG.warning("fsync_directory.open_failed", extra={"dir": str(directory), "err": str(exc)})
        return
    try:
        os.fsync(fd)
    except (OSError, NotImplementedError) as exc:
        # Windows: fsync(dir_fd) não é suportado — ok.
        _LOG.warning("fsync_directory.unsupported", extra={"dir": str(directory), "err": str(exc)})
    finally:
        os.close(fd)


def _trades_to_table(trades: list[TradeRecord]) -> pa.Table:
    """Converte ``list[TradeRecord]`` em ``pa.Table`` aderente ao schema."""
    schema = pyarrow_schema()
    # Constrói arrays coluna a coluna respeitando o schema.
    columns: dict[str, list[object]] = {f.name: [] for f in schema}
    for trade in trades:
        for f in schema:
            columns[f.name].append(trade.get(f.name))
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def _table_to_trades(table: pa.Table) -> list[TradeRecord]:
    """Inverso de :func:`_trades_to_table` — para o caminho de merge."""
    rows: list[dict[str, object]] = table.to_pylist()
    # to_pylist() retorna list[dict[str, Any]]; tratamos como TradeRecord
    # (TypedDict total=False aceita campos opcionais).
    return [cast(TradeRecord, row) for row in rows]


def _read_existing(path: Path) -> list[TradeRecord]:
    """Lê arquivo Parquet existente e retorna trades (para merge+dedup)."""
    table = pq.read_table(path)
    return _table_to_trades(table)


def _build_metadata(
    table: pa.Table,
    *,
    dll_version: str,
    chunk_id: str | None,
) -> dict[bytes, bytes]:
    """Monta o metadata custom do Parquet (SCHEMA.md §4)."""
    if table.num_rows == 0:
        first_ts_ns = 0
        last_ts_ns = 0
    else:
        ts_col = table.column("timestamp_ns")
        first_ts_ns = int(pa.compute.min(ts_col).as_py())
        last_ts_ns = int(pa.compute.max(ts_col).as_py())

    md: dict[bytes, bytes] = {
        b"schema_version": SCHEMA_VERSION.encode("utf-8"),
        b"row_count": str(table.num_rows).encode("utf-8"),
        b"first_ts_ns": str(first_ts_ns).encode("utf-8"),
        b"last_ts_ns": str(last_ts_ns).encode("utf-8"),
        b"dll_version": dll_version.encode("utf-8"),
        b"created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ").encode("utf-8"),
        b"compression": _COMPRESSION.encode("utf-8"),
        b"row_group_size": str(_ROW_GROUP_SIZE).encode("utf-8"),
    }
    if chunk_id is not None:
        md[b"chunk_id"] = chunk_id.encode("utf-8")
    return md


@dataclass(frozen=True)
class ParquetWriter:
    """Writer atômico de partições Parquet.

    Construído com a raiz dos dados (``data_dir``); cada chamada a
    :meth:`write` resolve o path da partição via ``partition.py``.

    Stateless — instâncias são thread-safe se ``data_dir`` não muda.
    Writers paralelos sobre a MESMA partição são race-condition (last
    writer wins via ``os.replace``); coordenação cabe ao orchestrator
    (Story 1.7).

    Args:
        data_dir: Raiz dos dados (tipicamente ``Path("data")``).
    """

    data_dir: Path

    def write(
        self,
        trades: list[TradeRecord],
        partition: PartitionKey,
        *,
        dll_version: str,
        chunk_id: str | None = None,
    ) -> WriteResult:
        """Escreve um lote de trades atomicamente.

        Pipeline (ver módulo docstring). Append + dedup automático se a
        partição já existe (idempotência R5).

        Args:
            trades: Lote a persistir. Cópia defensiva é feita
                internamente — a lista do caller não é mutada (mas os
                ``TradeRecord`` SIM, pois TypedDict é dict).
            partition: ``PartitionKey`` da partição alvo.
            dll_version: ``GetDLLVersion()`` capturado pelo orchestrator
                no boot (NOT NULL no schema).
            chunk_id: UUID do chunk de origem (auditoria). Pode ser
                ``None`` se merge de múltiplos chunks.

        Returns:
            ``WriteResult`` com path, row_count, bounds, SHA256, size.

        Raises:
            IntegrityError: registro inválido OU partição excede
                ``_PARTITION_ROW_LIMIT`` (sub-particionamento é Story
                2.X).
        """
        if not trades:
            # No-op semântico — não cria arquivo vazio.
            raise IntegrityError(
                "write called with empty trade list",
                details={"partition": str(partition)},
            )

        # 1. Valida cada registro (filtro de "obviamente quebrado").
        for trade in trades:
            validate_record(trade)

        # 2. Enriquece com metadata por trade.
        ingestion_ts_ns = time.time_ns()
        for trade in trades:
            trade.setdefault("ingestion_ts_ns", ingestion_ts_ns)
            trade["dll_version"] = dll_version
            if chunk_id is not None:
                trade.setdefault("chunk_id", chunk_id)
            else:
                trade.setdefault("chunk_id", None)

        # 3. assign_sequence_within_ns se ALGUM trade não tem trade_id.
        needs_sequence = any(t.get("trade_id") is None for t in trades)
        if needs_sequence:
            assign_sequence_within_ns(trades)
        else:
            # Mesmo no caminho V2, sequence_within_ns é NOT NULL — preencher 0.
            for trade in trades:
                trade.setdefault("sequence_within_ns", 0)

        # 4. dedup do batch.
        deduped_new = dedup(trades)

        # 5. Path + merge se já existe.
        path = resolve_partition_path(partition, self.data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = _read_existing(path)
            # Threshold deferred (finding H6).
            projected_rows = len(existing) + len(deduped_new)
            if projected_rows > _PARTITION_ROW_LIMIT:
                raise IntegrityError(
                    f"Partition exceeds {_PARTITION_ROW_LIMIT:_} rows; "
                    f"needs sub-partitioning — Story 2.X",
                    details={
                        "partition": str(partition),
                        "existing_rows": len(existing),
                        "new_rows": len(deduped_new),
                        "projected_rows": projected_rows,
                        "limit": _PARTITION_ROW_LIMIT,
                    },
                )
            # Union e re-dedup. Existing primeiro (preserva ordem e dedup
            # mantém primeira ocorrência).
            merged = dedup(existing + deduped_new)
        else:
            merged = deduped_new

        # 6. Constrói tabela.
        table = _trades_to_table(merged)
        # Ordena por (timestamp_ns, sequence_within_ns) — INV-3.
        table = table.sort_by([("timestamp_ns", "ascending"), ("sequence_within_ns", "ascending")])

        metadata = _build_metadata(table, dll_version=dll_version, chunk_id=chunk_id)
        # pyarrow exige metadata anexado ao schema do writer.
        table = table.replace_schema_metadata(metadata)

        # 7. Escreve em tmp.
        tmp_path = path.with_name(f"{path.name}.tmp.{uuid.uuid4().hex}")

        try:
            # Escrita parquet com configs ADR-002 + fsync explícito.
            with pq.ParquetWriter(
                tmp_path,
                table.schema,
                compression=_COMPRESSION,
                use_dictionary=_USE_DICTIONARY,
                write_statistics=_WRITE_STATISTICS,
            ) as writer:
                writer.write_table(table, row_group_size=_ROW_GROUP_SIZE)

            # 8. fsync(file). Reabrimos em append-binary (não trunca) só para
            # obter um FD válido para fsync — no Windows fsync exige um FD
            # aberto para escrita.
            fd = os.open(str(tmp_path), os.O_RDWR)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

            # 9. SHA256 do tmp (= SHA256 do final, já que replace é atômico).
            checksum = _sha256_file(tmp_path)
            file_size = tmp_path.stat().st_size

            # 10. fsync(parent_dir) — best-effort.
            _fsync_directory(path.parent)

            # 11. os.replace (atômico Windows + Linux).
            os.replace(tmp_path, path)

            # 12. fsync(parent_dir) novamente para persistir a entrada renomeada.
            _fsync_directory(path.parent)
        except Exception:
            # Cleanup tmp em caso de qualquer falha.
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    _LOG.warning(
                        "parquet_writer.tmp_cleanup_failed",
                        extra={"tmp": str(tmp_path)},
                    )
            raise

        # WriteResult bounds vêm da tabela final (já ordenada).
        if table.num_rows == 0:
            # Defesa — não devíamos chegar aqui (input validado não vazio).
            first_ts_ns = 0
            last_ts_ns = 0
        else:
            ts_col = table.column("timestamp_ns")
            first_ts_ns = int(pa.compute.min(ts_col).as_py())
            last_ts_ns = int(pa.compute.max(ts_col).as_py())

        return WriteResult(
            path=path,
            row_count=table.num_rows,
            first_ts_ns=first_ts_ns,
            last_ts_ns=last_ts_ns,
            checksum_sha256=checksum,
            file_size_bytes=file_size,
        )


# Suprime "unused import" para duckdb — reservado para anti-join futuro
# (SCHEMA.md §2.3) na Story 2.X. Mantemos o import pois orchestrator
# pode passar a usar este path no merge avançado.
_ = duckdb


__all__ = [
    "ParquetWriter",
    "WriteResult",
]
