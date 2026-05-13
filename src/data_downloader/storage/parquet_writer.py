"""data_downloader.storage.parquet_writer — Escrita atômica Parquet.

Owner: Sol (policy) | Impl: Dex.
Refs:

- ``docs/storage/SCHEMA.md`` v1.0.0 (17 campos)
- ``docs/storage/INTEGRITY.md`` (atomicity, dedup, fsync)
- ``docs/adr/ADR-002-storage-stack.md`` (Snappy, row_group=100k)
- ``docs/adr/ADR-004-partition-layout.md`` (path layout)
- ``docs/adr/ADR-011-exception-hierarchy.md`` (IntegrityError)
- ``docs/decisions/COUNCIL-10-perf-optimization-roadmap.md`` (vectorização Story 2.2)

Pipeline canônico de :meth:`ParquetWriter.write` (Story 2.2 — vectorizado):

    1. converter list[TradeRecord] -> pa.Table (vectorizado, single-pass)
    2. validar registros via pa.compute boolean masks
    3. enriquecer com ingestion_ts_ns + dll_version + chunk_id (pa.array constantes)
    4. assign_sequence_within_ns se algum trade não tem trade_id (DuckDB ROW_NUMBER)
    5. dedup do batch (DuckDB ROW_NUMBER OVER chave canônica)
    6. se arquivo existe: ler -> union -> dedup -> verificar threshold 5M
    7. resolve path; mkdir -p
    8. escreve em ``{path}.tmp.{uuid4}`` com metadata canônico
    9. fsync(file)
    10. SHA256 streaming (chunks 1MB)
    11. fsync(parent_dir) — best-effort (Linux semantics; Windows no-op)
    12. os.replace(tmp, final) — atômico Windows + Linux
    13. retorna ``WriteResult``

Threshold rewrite (finding H6, deferred): se ``existing_rows + new_rows
> 5_000_000``, raise ``IntegrityError`` — sub-particionamento é Story
2.X.

Story 2.2 — refactor interno para fechar gap perf de -72% vs target V1
(100k trades/s sustained). Comportamento externo INTACTO: mesmo schema,
mesma idempotência (R5), mesma atomicidade (INV-3), mesmo SHA256.
Validado por property tests Hypothesis em
``tests/property/test_vectorized_equivalence.py``.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from data_downloader.public_api.exceptions import IntegrityError
from data_downloader.storage._vectorized import (
    assign_sequence_within_ns_vectorized,
    compute_sha256_streaming,
    dedup_table_vectorized,
    enrich_table_vectorized,
    trades_to_table_vectorized,
    validate_records_vectorized,
)
from data_downloader.storage.partition import (
    PartitionKey,
    resolve_partition_path,
)
from data_downloader.storage.schema import (
    SCHEMA_VERSION,
    SchemaIntegrityError,
    TradeRecord,
    pyarrow_schema,
)

_LOG = logging.getLogger(__name__)

# Configuração Parquet (ADR-002).
_COMPRESSION: str = "snappy"
_ROW_GROUP_SIZE: int = 100_000
_USE_DICTIONARY: bool = True
_WRITE_STATISTICS: bool = True

# Threshold paliativo (finding H6 — sub-particionamento real é ADR-025
# "parquet-per-day", planejado para v1.2.0 Wave 2 — ver docs/qa/V1.2.0-PLAN.md).
#
# Antes: 5_000_000 — pequeno demais; um mês de WDOFUT chega a ~10-13M trades
# e o write abortava com IntegrityError no meio do download. Subido para 50M
# como folga até o particionamento diário estar pronto. NÃO é um limite "de
# verdade": é um guard de sanidade contra partições absurdas (ex: símbolo
# errado, range de anos). Quando ADR-025 entrar, este threshold passa a ser
# por-dia e cai para algo na casa de 1-2M.
_PARTITION_ROW_LIMIT: int = 50_000_000


def _check_no_field_drop(sample: TradeRecord) -> None:
    """Guard fail-loudly: NUNCA descartar campos do TradeRecord.

    Nelo Council 32 (release blocker P0). Compara as chaves do
    ``TradeRecord`` recebido (em runtime, TypedDict é ``dict``) contra os
    nomes do ``pa.Schema`` canônico. Qualquer chave extra (no record mas
    não no schema) levanta :class:`SchemaIntegrityError` — força bump
    explícito de ``SCHEMA_VERSION`` em vez de drop silencioso.

    Args:
        sample: 1º trade do batch (representativo — todos os trades de um
            batch vêm do mesmo orchestrator path).

    Raises:
        SchemaIntegrityError: ``record_fields - schema_fields != ∅``.
    """
    record_fields = set(sample.keys())
    schema_fields = set(pyarrow_schema().names)
    missing_in_schema = record_fields - schema_fields
    if missing_in_schema:
        raise SchemaIntegrityError(
            f"Schema v{SCHEMA_VERSION} would drop fields: "
            f"{sorted(missing_in_schema)}. "
            f"Bump schema version and add columns explicitly — "
            f"NEVER drop columns silently (Nelo Council 32).",
            details={
                "schema_version": SCHEMA_VERSION,
                "missing_in_schema": sorted(missing_in_schema),
                "record_fields": sorted(record_fields),
                "schema_fields": sorted(schema_fields),
            },
        )


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
    """SHA256 hex de um arquivo, lido em chunks (1MB default).

    Wrapper backwards-compatible para
    :func:`data_downloader.storage._vectorized.compute_sha256_streaming`
    — Story 2.2 moveu a implementação para o módulo vectorized; este nome
    permanece exportado para callers externos (``catalog.py``).
    """
    return compute_sha256_streaming(path, chunk_size=chunk_size)


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


def _read_existing_table(path: Path) -> pa.Table:
    """Lê arquivo Parquet existente como ``pa.Table`` (para merge vectorizado).

    Retorna table com schema canônico forçado — re-impõe campos na ordem
    correta caso Parquet tenha sido escrito por versão anterior com
    ordem diferente.

    Forward-compat (Nelo Council 32 / v1.1.0): arquivos legacy sem os
    campos aditivos v1.1.0 (``buy_agent_name``, ``sell_agent_name``,
    ``trade_type_name``) recebem coluna NULL preenchida — SCHEMA.md §6
    "bump minor: leitor entrega NULL para campos ausentes".
    """
    table = pq.read_table(path)
    schema = pyarrow_schema()
    existing_names = set(table.schema.names)
    arrays: list[pa.Array | pa.ChunkedArray] = []
    for f in schema:
        if f.name in existing_names:
            arrays.append(table.column(f.name).cast(f.type))
        else:
            if not f.nullable:
                raise IntegrityError(
                    f"Existing parquet missing NOT NULL field {f.name!r}; "
                    f"requires major migration (Story 2.X).",
                    details={"path": str(path), "missing_field": f.name},
                )
            arrays.append(pa.nulls(table.num_rows, type=f.type))
    return pa.Table.from_arrays(arrays, schema=schema)


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
                ``_PARTITION_ROW_LIMIT`` (guard paliativo; particionamento
                diário real é ADR-025 — v1.2.0 Wave 2).
        """
        if not trades:
            # No-op semântico — não cria arquivo vazio.
            raise IntegrityError(
                "write called with empty trade list",
                details={"partition": str(partition)},
            )

        # Nelo Council 32 (release blocker P0): NUNCA descartar colunas
        # silenciosamente. Schema v1.0.0 silenciosamente droppava
        # ``buy_agent_name`` / ``sell_agent_name`` / ``trade_type_name``
        # populados pelo ingestor. Schema v1.1.0 mapeia explicitamente os 3
        # campos; este guard garante que QUALQUER campo futuro que apareça
        # em ``TradeRecord`` mas não no schema cause uma falha alta e
        # imediata (forçando bump schema_version) em vez de drop silencioso.
        # Inspeciona o primeiro trade — TradeRecord é TypedDict (dict
        # built-in em runtime); fields adicionais aparecem como chaves
        # extras. Iterar sobre TODOS os trades seria O(N) hot path; o
        # primeiro é representativo (tipo é uniforme dentro do batch
        # gerado pelo orchestrator/ingestor).
        _check_no_field_drop(trades[0])

        # 1. Converte para pa.Table imediatamente (vectorizado).
        ingestion_ts_ns = time.time_ns()
        new_table = trades_to_table_vectorized(trades)

        # 2. Valida via pa.compute boolean masks.
        validate_records_vectorized(new_table)

        # 3. Enriquece via pa.array constantes (sem loop Python).
        new_table = enrich_table_vectorized(
            new_table,
            ingestion_ts_ns=ingestion_ts_ns,
            dll_version=dll_version,
            chunk_id=chunk_id,
        )

        # 4. assign_sequence_within_ns vectorizado se algum trade não tem trade_id.
        trade_id_col = new_table.column("trade_id")
        # null_count está disponível em ChunkedArray sem materializar.
        needs_sequence = trade_id_col.null_count > 0
        if needs_sequence:
            new_table = assign_sequence_within_ns_vectorized(new_table)
        # Caminho V2 puro: sequence_within_ns já está 0 default
        # (pyarrow_schema é uint16 NOT NULL; trades_to_table_vectorized
        # converte trade.get('sequence_within_ns', 0) -> 0).

        # 5. dedup vectorizado (DuckDB ROW_NUMBER particionado pela chave).
        deduped_new_table = dedup_table_vectorized(new_table)

        # 6. Path + merge se já existe.
        path = resolve_partition_path(partition, self.data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing_table = _read_existing_table(path)
            # Threshold deferred (finding H6).
            projected_rows = existing_table.num_rows + deduped_new_table.num_rows
            if projected_rows > _PARTITION_ROW_LIMIT:
                raise IntegrityError(
                    f"Partition exceeds {_PARTITION_ROW_LIMIT:_} rows; "
                    f"needs sub-partitioning — ADR-025 (parquet-per-day)",
                    details={
                        "partition": str(partition),
                        "existing_rows": existing_table.num_rows,
                        "new_rows": deduped_new_table.num_rows,
                        "projected_rows": projected_rows,
                        "limit": _PARTITION_ROW_LIMIT,
                    },
                )
            # Union e re-dedup. Existing primeiro (preserva ordem; dedup
            # mantém primeira ocorrência — INV-2).
            merged_pre = pa.concat_tables(
                [existing_table, deduped_new_table], promote_options="default"
            )
            table = dedup_table_vectorized(merged_pre)
        else:
            table = deduped_new_table

        # 7. Ordena por (timestamp_ns, sequence_within_ns) — INV-3.
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

            # 9. SHA256 streaming do tmp (= SHA256 do final, já que replace é atômico).
            checksum = compute_sha256_streaming(tmp_path)
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


__all__ = [
    "ParquetWriter",
    "WriteResult",
]
