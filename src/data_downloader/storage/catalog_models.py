"""data_downloader.storage.catalog_models — Dataclasses imutáveis do catálogo SQLite.

Owner: Sol (schema/policy) | Impl: Dex.
Refs:

- ``docs/storage/SCHEMA.md`` §5 (DDL completo)
- ``docs/storage/INTEGRITY.md`` §4 (two-phase commit), §5 (drift A/B/C)
- Story 1.5 — AC4 (métodos), AC8 (resume), AC9/AC11 (reconcile)

Modelos puros (sem I/O) consumidos por ``catalog.Catalog``. Cada classe é
``frozen=True`` para permitir uso seguro como chave/valor em estruturas
auxiliares e para reforçar imutabilidade após a query.

Função pura ``compute_pending_chunks`` calcula a diferença lógica entre
o intervalo solicitado (``Job.requested_*``) e os meses já completos em
``partitions`` — base do mecanismo de checkpoint/resume (Story 1.5 AC8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class Job:
    """Linha de ``downloads`` (SCHEMA.md §5.2).

    Status canônicos: ``pending`` -> ``in_progress`` -> ``completed`` |
    ``failed`` | ``partial`` | ``cancelled``.
    """

    job_id: str
    symbol: str
    exchange: str
    requested_start: datetime
    requested_end: datetime
    status: str
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    trades_count: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    dll_version: str | None = None


@dataclass(frozen=True)
class Partition:
    """Linha de ``partitions`` (SCHEMA.md §5.3 + ADR-025 §2.1).

    ``partition_path`` é a chave primária e contém o caminho RELATIVO a
    ``data/history/`` (ex.: ``F/WDOJ26/2026/03.parquet`` para mensal,
    ``F/WDOJ26/2026/03/15.parquet`` para diário). O catálogo nunca persiste
    paths absolutos — eles dependem de onde ``data_dir`` foi montado.

    ADR-025 (v1.3.0+): ``day`` é ``None`` para partições MENSAIS compactadas
    e ``1..31`` para partições DIÁRIAS parciais. Coexistência durante o mês
    corrente (vários diários) é normal; após ``maybe_compact_month`` só o
    mensal sobrevive.
    """

    partition_path: str
    symbol: str
    exchange: str
    year: int
    month: int
    row_count: int
    first_ts_ns: int
    last_ts_ns: int
    schema_version: str
    checksum_sha256: str
    file_size_bytes: int
    written_at: datetime
    job_id: str | None = None
    day: int | None = None


@dataclass(frozen=True)
class Gap:
    """Linha de ``gaps`` (SCHEMA.md §5.4).

    Gap = intervalo ``[gap_start, gap_end]`` em que esperávamos trades
    e não havia. ``reason`` é categórico (CHECK constraint no DDL).
    """

    symbol: str
    exchange: str
    gap_start: datetime
    gap_end: datetime
    reason: str
    detected_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class ChunkRange:
    """Intervalo ``[start, end]`` (inclusivo) ainda pendente em um job.

    Granularidade canônica: mensal (alinha com o layout de partição
    ADR-004). ``compute_pending_chunks`` produz uma lista de
    ``ChunkRange`` cobrindo apenas os meses que faltam.
    """

    symbol: str
    exchange: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ResumePlan:
    """Saída de ``Catalog.resume_job`` (Story 1.5 AC8).

    - ``completed_partitions``: lista de ``Partition`` já gravadas
      pertencentes a este job.
    - ``pending_chunks``: meses ainda não cobertos dentro do range
      solicitado original.
    - ``job``: snapshot do ``Job`` no momento do resume.
    """

    job: Job
    completed_partitions: tuple[Partition, ...]
    pending_chunks: tuple[ChunkRange, ...]


@dataclass(frozen=True)
class ReconcileReport:
    """Saída de ``Catalog.reconcile`` (Story 1.5 AC9/AC11).

    Drift A: arquivo Parquet existe em disco, sem entrada em
    ``partitions`` (catálogo desatualizado). Em modo auto-correct, é
    re-registrado.

    Drift B: entrada em ``partitions`` sem arquivo correspondente
    (arquivo deletado externamente). NUNCA auto-corrigido — só
    reportado.

    Drift C: ``partitions.checksum_sha256`` diverge do SHA256 atual do
    arquivo on-disk (corrupção / edição externa). NUNCA auto-corrigido.

    ``auto_corrected_paths`` lista os caminhos relativos que foram
    re-registrados durante o reconcile (subset de ``drift_a``).
    """

    drift_a: tuple[str, ...] = field(default_factory=tuple)
    drift_b: tuple[str, ...] = field(default_factory=tuple)
    drift_c: tuple[str, ...] = field(default_factory=tuple)
    auto_corrected_paths: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        """``True`` se não houver nenhum drift (A, B ou C) detectado."""
        return not (self.drift_a or self.drift_b or self.drift_c)


def compute_pending_chunks(
    *,
    symbol: str,
    exchange: str,
    requested_start: datetime,
    requested_end: datetime,
    completed_partitions: list[Partition],
) -> list[ChunkRange]:
    """Calcula os meses ainda não cobertos dentro do range solicitado.

    Granularidade canônica: mensal — alinhada ao layout de partição
    ADR-004 (``{year}/{month}.parquet``). Para cada mês entre
    ``requested_start`` e ``requested_end`` (inclusivo nos dois
    extremos), verifica se há uma ``Partition`` em
    ``completed_partitions`` cobrindo aquele ``(year, month)``. Se não
    há, emite um ``ChunkRange`` cobrindo o mês inteiro.

    Política de fronteira de mês:

    - Início do chunk = ``max(requested_start, primeiro dia do mês)``.
    - Fim do chunk = ``min(requested_end, último dia do mês 23:59:59)``.

    Edge case: se TODOS os meses já estão em ``completed_partitions``,
    retorna lista vazia (download está completo).

    Args:
        symbol: Código do contrato (ex.: ``"WDOJ26"``).
        exchange: ``"F"`` ou ``"B"``.
        requested_start: Início do intervalo solicitado.
        requested_end: Fim do intervalo solicitado (inclusivo).
        completed_partitions: Partições já completas (de
            ``Catalog.get_completed_partitions`` ou subset filtrado por
            job_id).

    Returns:
        Lista de ``ChunkRange`` cobrindo apenas os meses pendentes.
        Vazia se range completamente coberto.
    """
    if requested_end < requested_start:
        return []

    completed_keys: set[tuple[int, int]] = {
        (p.year, p.month)
        for p in completed_partitions
        if p.symbol == symbol and p.exchange == exchange
    }

    pending: list[ChunkRange] = []
    year = requested_start.year
    month = requested_start.month
    end_year = requested_end.year
    end_month = requested_end.month

    while (year, month) <= (end_year, end_month):
        if (year, month) not in completed_keys:
            month_start = datetime(year, month, 1)
            # Último dia do mês: pular para o mês seguinte e voltar 1 microssegundo.
            if month == 12:
                next_month_start = datetime(year + 1, 1, 1)
            else:
                next_month_start = datetime(year, month + 1, 1)
            # Final do mês = último instante representável antes do próximo.
            month_end = datetime(
                next_month_start.year,
                next_month_start.month,
                1,
                0,
                0,
                0,
            )
            # Recorta nas fronteiras do range solicitado.
            chunk_start = max(month_start, requested_start)
            # ``requested_end`` é inclusivo; cap em ``min(requested_end, month_end - 1us)``.
            # Para granularidade mensal o consumidor (orchestrator) só usa
            # year/month — preservamos o instante exato para auditoria.
            if requested_end < month_end:
                chunk_end = requested_end
            else:
                # Último instante do mês representável (23:59:59.999999).
                last_day = _last_day_of_month(year, month)
                chunk_end = datetime(year, month, last_day, 23, 59, 59, 999999)
            pending.append(
                ChunkRange(
                    symbol=symbol,
                    exchange=exchange,
                    start=chunk_start,
                    end=chunk_end,
                )
            )

        # Avança 1 mês.
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return pending


def _last_day_of_month(year: int, month: int) -> int:
    """Último dia do mês (28-31). Helper para ``compute_pending_chunks``."""
    next_first = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return (next_first - timedelta(days=1)).day


def relative_partition_path(absolute: Path, data_dir: Path) -> str:
    """Converte path absoluto Parquet -> path relativo a ``data/history/``.

    Ex.: ``data/history/F/WDOJ26/2026/03.parquet`` ->
    ``F/WDOJ26/2026/03.parquet``.

    Args:
        absolute: Path absoluto do arquivo Parquet.
        data_dir: Raiz dos dados (mesma usada no writer).

    Returns:
        String com path relativo a ``data_dir/history/``, sempre com
        separador ``/`` (POSIX) — independente do OS, porque o catálogo
        precisa ser portável.
    """
    history_root = data_dir / "history"
    rel = absolute.resolve().relative_to(history_root.resolve())
    return rel.as_posix()


__all__ = [
    "ChunkRange",
    "Gap",
    "Job",
    "Partition",
    "ReconcileReport",
    "ResumePlan",
    "compute_pending_chunks",
    "relative_partition_path",
]
