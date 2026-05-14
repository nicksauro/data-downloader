"""data_downloader.storage.catalog — Catálogo SQLite (fonte única de verdade).

Owner: Sol (schema) | Impl: Dex.
Refs:

- ``docs/storage/SCHEMA.md`` §5 (DDL completo + PRAGMAs reduzidos M6)
- ``docs/storage/INTEGRITY.md`` §3 (cache de checksum), §4 (two-phase
  commit emulado), §5 (drift A/B/C)
- ``docs/storage/MIGRATIONS.md`` (framework de migração de catálogo)
- Story 1.5 — AC1..AC13 (13 critérios)

Responsabilidades:

1. **Estado**: cria/migra schema na inicialização (idempotente — AC2).
2. **Tracking**: registrar jobs, partições e gaps com transações curtas
   (AC4 + AC5).
3. **Idempotência** (R5 / AC6 / AC10): ``register_partition`` é UPSERT
   por ``partition_path``.
4. **Resume** (AC8): dado um ``job_id``, calcula o que falta baixar.
5. **Reconcile** (AC9 + AC11): detecta drift A/B/C; auto-corrige A em
   modo automático no startup.
6. **Cleanup** (AC7): remove ``.tmp.{uuid}`` antigos (>5 min) ao boot.
7. **Two-phase commit** (AC13): emula atomicidade entre write Parquet e
   INSERT em ``partitions`` via tabela ``_pending_commits``.
8. **WAL checkpoint** (AC12): força ``wal_checkpoint(TRUNCATE)`` após
   cada ``register_partition`` para evitar perda em crash entre write e
   checkpoint default.

Sol: este módulo é a fronteira entre o squad e o disco. Mudança de
schema = bump em ``MIGRATIONS`` + entry no changelog (SCHEMA.md §7).
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType

from data_downloader.storage._paths import hide_directory_windows
from data_downloader.storage.catalog_models import (
    ChunkRange,
    Gap,
    Job,
    Partition,
    ReconcileReport,
    ResumePlan,
    compute_pending_chunks,
    relative_partition_path,
)
from data_downloader.storage.parquet_writer import WriteResult, _sha256_file
from data_downloader.storage.partition import PartitionKey
from data_downloader.storage.sqlite_profiles import (
    DEFAULT_PROFILE,
    SQLiteProfile,
    apply_profile,
    resolve_profile,
)

_LOG = logging.getLogger(__name__)

# Versão do catálogo SQLite (independente do schema Parquet).
# v1.1.0 (Story 2.3): adiciona `_migration_log` para framework de migrations.
# v1.2.0 (Wave 1B — resume real): adiciona `chunk_ledger` (1 row por dia
#   útil baixado — granularidade DIÁRIA, resolve o "mês tocado conta como
#   completo" sem mexer no layout parquet mensal) + `idx_partitions_job`
#   (resume query indexada).
# v1.3.0 (ADR-025 — parquet-per-day híbrido + auto-compact): adiciona
#   coluna `partitions.day` (NULL = mensal compactado, NOT NULL = diário),
#   índice `idx_partitions_symbol_ymd`, tabela `compactions` (rastreio
#   atômico do estado da compactação mensal).
CATALOG_VERSION: str = "1.3.0"

# DDL inicial — schema v1.0.0 (SCHEMA.md §5.1..5.7).
# Nota: ``_schema_meta`` usa o formato chave/valor (SCHEMA.md §5.1)
# diferente do esqueleto da story; SCHEMA.md é fonte autoritativa.
_DDL_V1_0_0: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS _schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS downloads (
        job_id            TEXT PRIMARY KEY,
        symbol            TEXT NOT NULL,
        exchange          TEXT NOT NULL,
        requested_start   TIMESTAMP NOT NULL,
        requested_end     TIMESTAMP NOT NULL,
        actual_start      TIMESTAMP,
        actual_end        TIMESTAMP,
        status            TEXT NOT NULL CHECK(status IN
                              ('pending','in_progress','completed','failed','partial','cancelled')),
        trades_count      INTEGER,
        started_at        TIMESTAMP,
        completed_at      TIMESTAMP,
        error             TEXT,
        dll_version       TEXT,
        cli_invocation    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS partitions (
        partition_path     TEXT PRIMARY KEY,
        symbol             TEXT NOT NULL,
        exchange           TEXT NOT NULL,
        year               INTEGER NOT NULL,
        month              INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
        row_count          INTEGER NOT NULL CHECK(row_count >= 0),
        first_ts_ns        INTEGER NOT NULL,
        last_ts_ns         INTEGER NOT NULL,
        schema_version     TEXT NOT NULL,
        checksum_sha256    TEXT NOT NULL,
        file_size_bytes    INTEGER NOT NULL CHECK(file_size_bytes > 0),
        written_at         TIMESTAMP NOT NULL,
        job_id             TEXT,
        FOREIGN KEY(job_id) REFERENCES downloads(job_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gaps (
        symbol         TEXT NOT NULL,
        exchange       TEXT NOT NULL,
        gap_start      TIMESTAMP NOT NULL,
        gap_end        TIMESTAMP NOT NULL,
        reason         TEXT NOT NULL CHECK(reason IN
                           ('no_trades','holiday','weekend','failed_chunk','unknown','outside_vigency')),
        detected_at    TIMESTAMP NOT NULL,
        resolved_at    TIMESTAMP,
        PRIMARY KEY (symbol, gap_start, gap_end)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contracts (
        symbol_root        TEXT NOT NULL,
        contract_code      TEXT NOT NULL,
        vigent_from        TIMESTAMP NOT NULL,
        vigent_until       TIMESTAMP NOT NULL,
        validated_at       TIMESTAMP,
        validation_source  TEXT NOT NULL CHECK(validation_source IN
                               ('hypothesized','nelogica_official','dll_probe','b3_calendar','manual')),
        notes              TEXT,
        PRIMARY KEY (symbol_root, contract_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _checksum_cache (
        partition_path     TEXT PRIMARY KEY,
        file_size_bytes    INTEGER NOT NULL,
        mtime_ns           INTEGER NOT NULL,
        checksum_sha256    TEXT NOT NULL,
        cached_at          TIMESTAMP NOT NULL,
        FOREIGN KEY(partition_path) REFERENCES partitions(partition_path) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS _pending_commits (
        partition_path     TEXT PRIMARY KEY,
        started_at         TIMESTAMP NOT NULL,
        expected_sha256    TEXT NOT NULL,
        expected_size      INTEGER NOT NULL,
        job_id             TEXT,
        pid                INTEGER NOT NULL,
        FOREIGN KEY(job_id) REFERENCES downloads(job_id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_downloads_symbol_status ON downloads(symbol, status)",
    "CREATE INDEX IF NOT EXISTS idx_partitions_symbol_ym ON partitions(symbol, year, month)",
    "CREATE INDEX IF NOT EXISTS idx_partitions_exchange ON partitions(exchange)",
    """
    CREATE INDEX IF NOT EXISTS idx_gaps_symbol_unresolved
        ON gaps(symbol)
        WHERE resolved_at IS NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_contracts_root_vigency "
    "ON contracts(symbol_root, vigent_from, vigent_until)",
)


# DDL delta v1.0.0 → v1.1.0 — adiciona `_migration_log` (Story 2.3 AC2/AC5).
# Schema migration framework (parquet) usa esta tabela como checkpoint
# resumível de execução. Espelhada em
# `migrations/catalog/v1_0_0_to_v1_1_0.sql` — fonte de verdade aqui é
# Python (compatibilidade com testes); SQL é referência documental.
_DDL_V1_1_0_DELTAS: tuple[str, ...] = (
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
    """,
    "CREATE INDEX IF NOT EXISTS idx_migration_log_run ON _migration_log(run_id, status)",
)


# DDL delta v1.1.0 → v1.2.0 — Wave 1B (resume real).
#
# Background: chunks são DIÁRIOS (1 dia útil — ADR-023) mas ``partitions``
# é granularidade MENSAL (1 row por ``(year, month)``). Inferir "dias
# baixados" a partir de ``partitions`` é incorreto: se 2018-01 caiu no dia
# 12, todo janeiro/2018 contava como "completo" e os outros 21 dias úteis
# nunca eram re-baixados (perda silenciosa). ``chunk_ledger`` rastreia 1
# row por dia útil de fato baixado (``status='completed'`` ou ``'no_trades'``)
# — fonte de verdade para o cache-hit / resume / fresh-skip em granularidade
# diária, sem mexer no layout parquet mensal (ADR-025 parquet-per-day fica
# para Wave 2).
#
# ``idx_partitions_job`` cobre o resume query (``WHERE job_id = ?``) que
# antes só tinha índice composto ``(symbol, year, month)`` — o ``OR`` na
# query forçava full scan.
_DDL_V1_2_0_DELTAS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS chunk_ledger (
        symbol         TEXT NOT NULL,
        exchange       TEXT NOT NULL,
        chunk_date     TEXT NOT NULL,
        job_id         TEXT,
        status         TEXT NOT NULL CHECK(status IN
                           ('completed','no_trades','failed')),
        trades_count   INTEGER NOT NULL DEFAULT 0 CHECK(trades_count >= 0),
        written_at     TIMESTAMP NOT NULL,
        PRIMARY KEY (symbol, exchange, chunk_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunk_ledger_sym_ex_date "
    "ON chunk_ledger(symbol, exchange, chunk_date)",
    "CREATE INDEX IF NOT EXISTS idx_partitions_job ON partitions(job_id)",
)


# DDL delta v1.2.0 → v1.3.0 — ADR-025 parquet-per-day híbrido.
#
# ``partitions.day`` (NULL = mensal compactado, NOT NULL = diário 1..31).
# Permite que múltiplas rows convivam para o mesmo (symbol, year, month):
# 1 mensal + 0..N diários DURANTE o mês corrente; após auto-compact, só
# o mensal sobrevive (compact_month executa DELETE dos diários +
# UPSERT mensal). ``idx_partitions_symbol_ymd`` cobre lookups
# ``is_month_complete`` + reconcile mais granular.
#
# ``compactions`` rastreia atomicamente operações de compactação: cada
# (symbol, exchange, year, month) tem no máximo 1 row in-flight com
# ``started_at`` mas sem ``completed_at`` — o reconcile usa essa marca
# para detectar crashes no meio da compactação (ADR-025 §2.4) e
# decidir completar OU reverter.
_DDL_V1_3_0_DELTAS: tuple[str, ...] = (
    # SQLite não suporta ADD COLUMN com CHECK constraint em ALTER, mas
    # aceita ADD COLUMN com default NULL. CHECK fica embutido no schema
    # criado for fresh DBs via _DDL_V1_0_0 — não no ALTER. Para DBs
    # migrados, a validação fica em Python (register_partition).
    "ALTER TABLE partitions ADD COLUMN day INTEGER NULL",
    "CREATE INDEX IF NOT EXISTS idx_partitions_symbol_ymd ON partitions(symbol, year, month, day)",
    """
    CREATE TABLE IF NOT EXISTS compactions (
        symbol         TEXT NOT NULL,
        exchange       TEXT NOT NULL,
        year           INTEGER NOT NULL,
        month          INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
        started_at     TIMESTAMP NOT NULL,
        completed_at   TIMESTAMP,
        error          TEXT,
        PRIMARY KEY (symbol, exchange, year, month)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_compactions_inflight "
    "ON compactions(symbol, exchange) WHERE completed_at IS NULL",
)


# Registry de migrações ordenadas por versão.
# Cada entry = (versao_destino, lista de DDL statements).
MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1.0.0", _DDL_V1_0_0),
    ("1.1.0", _DDL_V1_1_0_DELTAS),
    ("1.2.0", _DDL_V1_2_0_DELTAS),
    ("1.3.0", _DDL_V1_3_0_DELTAS),
)


# Idade mínima (segundos) para considerar um arquivo .tmp.* órfão (AC7).
_ORPHAN_TMP_MAX_AGE_DEFAULT: int = 300


# ----------------------------------------------------------------------
# v1.3.0 Wave 2B — observer pattern (CatalogScreen auto-refresh)
# ----------------------------------------------------------------------
#
# CatalogScreen (UI) precisa atualizar a tabela de partições em runtime
# enquanto o orchestrator persiste novos arquivos. Antes da Wave 2B o
# usuário precisava fechar/reabrir a screen (ou Ctrl+R) — agora um
# callback puro-Python permite ao CatalogAdapter (Qt-side) receber
# notificações cross-thread e reemitir como signal Qt na MainThread.
#
# Design (Aria — keep it boring):
#   - Observer = ``Callable[[str, int, int], None]`` (symbol, year, month).
#   - Module-state list (process-wide) — único Catalog vivo por processo,
#     ADR-024.
#   - register/unregister são idempotentes (registrar 2x = uma entrada).
#   - ``register_partition`` e ``record_chunk`` notificam APÓS o commit
#     SQLite, com try/except por callback (observer não derruba write).
#   - NÃO importar Qt aqui — backend permanece puro.
PartitionObserver = Callable[[str, int, int], None]
_PARTITION_OBSERVERS: list[PartitionObserver] = []


def register_partition_observer(callback: PartitionObserver) -> None:
    """Registra ``callback(symbol, year, month)`` para receber notificações.

    Disparado após ``Catalog.register_partition`` (granularidade mensal —
    partições parquet) e ``Catalog.record_chunk`` (granularidade diária —
    chunk_ledger; ``year``/``month`` derivados de ``chunk_date``). Re-registro
    do mesmo callable é no-op (anti-duplicata).

    O callback roda DENTRO da thread que chamou ``register_partition`` —
    consumidores Qt (ex.: :class:`CatalogAdapter`) devem usar mecanismos
    cross-thread (``QTimer.singleShot``/``QMetaObject.invokeMethod``) para
    re-emitir signals na MainThread.

    Exceções no callback são capturadas e logadas — observer NUNCA
    derruba o write do catálogo.

    Args:
        callback: Callable que aceita ``(symbol, year, month)``.
    """
    if callback not in _PARTITION_OBSERVERS:
        _PARTITION_OBSERVERS.append(callback)


def unregister_partition_observer(callback: PartitionObserver) -> None:
    """Remove um observer previamente registrado. Idempotente."""
    with contextlib.suppress(ValueError):
        _PARTITION_OBSERVERS.remove(callback)


def _notify_partition_observers(symbol: str, year: int, month: int) -> None:
    """Dispatch interno — chamado pelo ``Catalog`` após commit. Best-effort.

    Cada observer roda em try/except isolado: uma falha não impede que os
    outros sejam notificados, e nunca propaga para o caller (que é o write
    SQLite — derrubá-lo geraria perda de dados).
    """
    if not _PARTITION_OBSERVERS:
        return
    # Snapshot — observer pode chamar unregister durante notificação.
    for cb in tuple(_PARTITION_OBSERVERS):
        try:
            cb(symbol, year, month)
        except Exception as exc:
            # Best-effort dispatch — observer NUNCA derruba o write do catálogo.
            _LOG.warning(
                "catalog.partition_observer.failed",
                extra={"err": str(exc), "symbol": symbol, "year": year, "month": month},
            )


def _utcnow_iso() -> str:
    """Timestamp ISO8601 UTC (compatível com SQLite TIMESTAMP textual)."""
    # Usa naive UTC no formato exato esperado pelo SQLite (datetime('now')).
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_job(row: sqlite3.Row) -> Job:
    """Adapta linha SQLite -> ``Job``."""
    return Job(
        job_id=row["job_id"],
        symbol=row["symbol"],
        exchange=row["exchange"],
        requested_start=_parse_ts(row["requested_start"]),
        requested_end=_parse_ts(row["requested_end"]),
        status=row["status"],
        actual_start=_parse_ts_or_none(row["actual_start"]),
        actual_end=_parse_ts_or_none(row["actual_end"]),
        trades_count=row["trades_count"],
        started_at=_parse_ts_or_none(row["started_at"]),
        completed_at=_parse_ts_or_none(row["completed_at"]),
        error=row["error"],
        dll_version=row["dll_version"],
    )


def _row_to_partition(row: sqlite3.Row) -> Partition:
    """Adapta linha SQLite -> ``Partition``."""
    # ADR-025 v1.3.0: coluna ``day`` adicionada em v1.3.0; rows pré-migração
    # têm ``day=NULL``. ``sqlite3.Row`` lança IndexError se a coluna não
    # existir (catálogo pré-migração lendo Row do schema antigo) — defensive.
    try:
        day = row["day"]
    except (IndexError, KeyError):  # pragma: no cover defensive
        day = None
    return Partition(
        partition_path=row["partition_path"],
        symbol=row["symbol"],
        exchange=row["exchange"],
        year=row["year"],
        month=row["month"],
        row_count=row["row_count"],
        first_ts_ns=row["first_ts_ns"],
        last_ts_ns=row["last_ts_ns"],
        schema_version=row["schema_version"],
        checksum_sha256=row["checksum_sha256"],
        file_size_bytes=row["file_size_bytes"],
        written_at=_parse_ts(row["written_at"]),
        job_id=row["job_id"],
        day=day,
    )


def _parse_ts(value: str | datetime) -> datetime:
    """Parse de TIMESTAMP textual SQLite -> datetime naive."""
    if isinstance(value, datetime):
        return value
    # SQLite formats: "YYYY-MM-DD HH:MM:SS" ou "YYYY-MM-DD HH:MM:SS.ffffff".
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Última tentativa — ISO format completo.
    return datetime.fromisoformat(value)


def _parse_ts_or_none(value: str | None) -> datetime | None:
    """Versão que tolera ``NULL``."""
    if value is None:
        return None
    return _parse_ts(value)


def _format_ts(value: datetime) -> str:
    """Format de datetime -> string SQLite TIMESTAMP."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _migrate_legacy_catalog_path(data_dir: Path, new_path: Path) -> None:
    """v1.1.0+: migra ``catalog.db`` de ``data/history/`` para ``data/_internal/``.

    Background (ADR-024 — directive Pichau 2026-05-07): catalog SQLite
    convivia com os parquets em ``data/history/``; usuário via Explorer
    estranhava o ``.db``. Movemos para ``data/_internal/`` e aplicamos
    Windows Hidden attribute no diretório.

    Semântica (silenciosa, idempotente, segura para re-execução):

    - ``old`` ausente → no-op.
    - ``old`` existe, ``new`` ausente → move (rename atômico) + WAL/SHM.
      Log ``catalog_migrated``.
    - ``old`` existe, ``new`` existe → preserva ``new`` (assume já migrado);
      log ``catalog_legacy_path_kept``.
    - Falha de I/O → log ``catalog_migration_failed`` e retorna; ``Catalog``
      tentará abrir ``new`` (que pode falhar de forma mais clara depois).

    Args:
        data_dir: Raiz dos dados (procura ``old`` em ``data_dir/history/``).
        new_path: Path de destino (tipicamente ``data_dir/_internal/catalog.db``).
    """
    old_path = data_dir / "history" / "catalog.db"
    if old_path.resolve() == new_path.resolve():
        # Caller usou o path legado explicitamente — nada a migrar.
        return
    if not old_path.exists():
        return
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _LOG.error(
            "catalog_migration_failed",
            extra={"old": str(old_path), "new": str(new_path), "err": str(exc)},
        )
        return

    if new_path.exists():
        _LOG.warning(
            "catalog_legacy_path_kept",
            extra={
                "old": str(old_path),
                "new": str(new_path),
                "reason": "both_exist_kept_new",
            },
        )
        return

    try:
        # rename atômico (mesmo filesystem garantido — ambos sob ``data_dir``).
        old_path.rename(new_path)
        # Move WAL/SHM auxiliares se existirem (sqlite WAL mode).
        for ext in (".db-wal", ".db-shm"):
            old_aux = old_path.with_suffix(ext)
            if old_aux.exists():
                new_aux = new_path.with_suffix(ext)
                old_aux.rename(new_aux)
        _LOG.warning(
            "catalog_migrated",
            extra={"old": str(old_path), "new": str(new_path)},
        )
    except OSError as exc:
        _LOG.error(
            "catalog_migration_failed",
            extra={"old": str(old_path), "new": str(new_path), "err": str(exc)},
        )
        # Não levanta — Catalog tentará abrir ``new`` (que pode estar limpo
        # ou inexistente; modo de falha mais claro downstream).


@dataclass
class Catalog:
    """Catálogo SQLite — fonte única de verdade do estado de downloads.

    Inicializa o DB na primeira instância (cria, aplica DDL/migrations,
    configura PRAGMAs, executa cleanup de tmp órfãos e auto-reconcile
    drift A). Re-init em DB existente é no-op (idempotente — AC2).

    Args:
        db_path: Caminho do arquivo SQLite. Diretório pai é criado se
            não existe. Convenção (ADR-024): ``data/_internal/catalog.db``
            (legacy ``data/history/catalog.db`` é migrado silenciosamente
            no primeiro boot pós-v1.1.0).
        data_dir: Raiz dos dados (``data/``). Necessária para reconcile,
            cleanup_orphans, cálculo de paths relativos e migration ADR-024.
            Defaults para ``db_path.parent.parent`` (assumindo layout
            ``data/_internal/catalog.db`` ou legacy ``data/history/catalog.db``).
        auto_reconcile: Se ``True`` (default), executa
            ``reconcile(auto_correct=True)`` em ``__init__``. Pode ser
            desligado em testes que querem inspecionar o estado pré-reconcile.
        auto_cleanup_orphans: Se ``True`` (default), executa
            ``cleanup_orphans()`` em ``__init__`` (AC7).
        sqlite_profile: Perfil de PRAGMAs SQLite (Story 2.8 / COUNCIL-21).
            ``None`` = resolução automática via env var
            ``DATA_DOWNLOADER_SQLITE_PROFILE`` (``low_memory``,
            ``default``, ``aggressive``) ou ``DEFAULT_PROFILE``.
            Pode receber instância ``SQLiteProfile`` ou nome string.
    """

    db_path: Path
    data_dir: Path | None = None
    auto_reconcile: bool = True
    auto_cleanup_orphans: bool = True
    sqlite_profile: SQLiteProfile | str | None = None
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _resolved_profile: SQLiteProfile = field(default=DEFAULT_PROFILE, init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        if self.data_dir is None:
            # Assume layout convencional: db está em data/_internal/catalog.db
            # (ADR-024) ou legacy data/history/catalog.db. Em ambos os casos
            # data_dir = data/ (i.e. db_path.parent.parent).
            self.data_dir = self.db_path.parent.parent
        else:
            self.data_dir = Path(self.data_dir)

        # ADR-024: migra silenciosamente catalog.db legado de
        # ``data/history/`` para ``data/_internal/`` antes de abrir conexão.
        # Idempotente: no-op se já migrado, se old não existe ou se caller
        # passou o path legado explicitamente.
        _migrate_legacy_catalog_path(self.data_dir, self.db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # ADR-024: best-effort hide do diretório do catálogo no Windows
        # Explorer (no-op em outros OS). Não interfere com Path operations.
        hide_directory_windows(self.db_path.parent)

        # Story 2.8 — resolve perfil PRAGMA (explicit > env > default).
        self._resolved_profile = resolve_profile(self.sqlite_profile)

        self._conn = self._open_connection()
        self._apply_pragmas()
        self._apply_migrations()

        if self.auto_cleanup_orphans:
            try:
                removed = self.cleanup_orphans()
                if removed:
                    _LOG.info(
                        "catalog.cleanup_orphans.startup",
                        extra={"removed_count": len(removed)},
                    )
            except OSError as exc:
                _LOG.warning("catalog.cleanup_orphans.failed", extra={"err": str(exc)})

        if self.auto_reconcile:
            try:
                report = self.reconcile(auto_correct=True)
                if not report.is_clean:
                    _LOG.warning(
                        "catalog.reconcile.startup_drift",
                        extra={
                            "drift_a": len(report.drift_a),
                            "drift_b": len(report.drift_b),
                            "drift_c": len(report.drift_c),
                            "auto_corrected": len(report.auto_corrected_paths),
                        },
                    )
            except OSError as exc:
                _LOG.warning("catalog.reconcile.failed", extra={"err": str(exc)})

    # ------------------------------------------------------------------
    # Connection / lifecycle
    # ------------------------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        """Abre conexão SQLite com row_factory ``Row`` para acesso por nome.

        Não usa ``detect_types`` — converters de TIMESTAMP padrão estão
        deprecated em Python 3.12+; tratamos parsing manualmente em
        ``_parse_ts`` para evitar dependência de behavior obsoleto.
        """
        conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,  # autocommit; transações explícitas via BEGIN.
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _conn_or_raise(self) -> sqlite3.Connection:
        """Retorna conexão garantida — levanta se ``close`` foi chamado."""
        if self._conn is None:
            raise RuntimeError("Catalog connection is closed.")
        return self._conn

    def _apply_pragmas(self) -> None:
        """Aplica PRAGMAs do perfil resolvido (Story 2.8 / COUNCIL-21).

        Profile (default, low_memory, aggressive) é resolvido em
        ``__post_init__`` e armazenado em ``self._resolved_profile``.
        Documentação completa em
        :mod:`data_downloader.storage.sqlite_profiles`.
        """
        conn = self._conn_or_raise()
        apply_profile(conn, self._resolved_profile)

    def _apply_migrations(self) -> None:
        """Aplica migrations pendentes (idempotente — AC2).

        Cria ``_schema_meta`` se não existe, lê versão atual e aplica
        cada DDL versionado em ``MIGRATIONS`` cuja versão > atual. Cada
        migration roda em transação própria; falha = rollback dessa
        versão (versões anteriores permanecem aplicadas).

        Idempotência ADR-025 (v1.3.0): ``ALTER TABLE ... ADD COLUMN`` não
        aceita ``IF NOT EXISTS``; antes de aplicar, checamos se a coluna
        já existe via ``PRAGMA table_info`` e pulamos o ALTER. Necessário
        porque DBs criados *fresh* em v1.3.0 já têm a coluna pelo bootstrap
        (registry roda as 4 migrations em sequência sobre DB vazio: a
        v1.0.0 cria ``partitions`` sem ``day``; v1.3.0 ADD COLUMN aplica
        normal). Para DBs migrados de v1.2.0 também funciona — coluna
        ainda não existe. Para re-runs de v1.3.0+ (no-op no loop pela
        comparação semver), o guard nem é exercitado.
        """
        conn = self._conn_or_raise()
        # Bootstrap: garantir _schema_meta antes de qualquer leitura.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

        current_version = self._get_meta("catalog_version")
        for version, ddl_statements in MIGRATIONS:
            if current_version is not None and _semver_le(version, current_version):
                continue
            with self._transaction():
                for stmt in ddl_statements:
                    # Idempotente: pula ADD COLUMN se a coluna já existe.
                    if _is_add_column_stmt(stmt) and _column_exists(conn, stmt):
                        continue
                    conn.execute(stmt)
                # Atualiza meta dentro da mesma transação.
                conn.execute(
                    "INSERT INTO _schema_meta(key, value) VALUES('catalog_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (version,),
                )
                conn.execute(
                    "INSERT INTO _schema_meta(key, value) "
                    "VALUES('parquet_schema_min_supported', '1.0.0') "
                    "ON CONFLICT(key) DO NOTHING"
                )
                conn.execute(
                    "INSERT INTO _schema_meta(key, value) VALUES('created_at', ?) "
                    "ON CONFLICT(key) DO NOTHING",
                    (_utcnow_iso(),),
                )
            current_version = version

    def _get_meta(self, key: str) -> str | None:
        """Lê valor de ``_schema_meta`` ou ``None`` se ausente."""
        conn = self._conn_or_raise()
        try:
            row = conn.execute("SELECT value FROM _schema_meta WHERE key = ?", (key,)).fetchone()
        except sqlite3.OperationalError:
            # Tabela ainda não existe (primeira inicialização).
            return None
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Transação curta com BEGIN IMMEDIATE (lock writer ASAP)."""
        conn = self._conn_or_raise()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def close(self) -> None:
        """Fecha a conexão. Idempotente."""
        if self._conn is not None:
            with contextlib.suppress(sqlite3.Error):
                # WAL checkpoint final para garantir durabilidade ao fechar.
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Catalog:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # AC4 — métodos públicos
    # ------------------------------------------------------------------

    def register_job(
        self,
        symbol: str,
        exchange: str,
        requested_start: datetime,
        requested_end: datetime,
    ) -> str:
        """Registra novo job em ``downloads``. Retorna ``job_id`` UUID.

        Status inicial = ``"pending"``. Usar ``update_job_progress`` para
        avançar o lifecycle (AC5).

        Args:
            symbol: Código do contrato (ex.: ``"WDOJ26"``).
            exchange: ``"F"`` ou ``"B"``.
            requested_start: Início da janela solicitada.
            requested_end: Fim da janela solicitada.

        Returns:
            ``job_id`` (UUID4 hex) — chave primária em ``downloads``.
        """
        job_id = uuid.uuid4().hex
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                """
                INSERT INTO downloads(
                    job_id, symbol, exchange, requested_start, requested_end, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                (
                    job_id,
                    symbol,
                    exchange,
                    _format_ts(requested_start),
                    _format_ts(requested_end),
                ),
            )
        return job_id

    def update_job_progress(
        self,
        job_id: str,
        status: str | None = None,
        *,
        actual_start: datetime | None = None,
        actual_end: datetime | None = None,
        trades_count: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        error: str | None = None,
        dll_version: str | None = None,
    ) -> None:
        """Atualiza campos parciais de um job (AC4 + AC5).

        Apenas campos não-``None`` são atualizados. Status válidos:
        ``pending``, ``in_progress``, ``completed``, ``failed``,
        ``partial``, ``cancelled``.

        Args:
            job_id: UUID retornado por ``register_job``.
            status: Novo status (opcional).
            actual_start: Primeiro trade recebido.
            actual_end: Último trade recebido.
            trades_count: Total de trades persistidos.
            started_at: Início real da execução.
            completed_at: Fim da execução.
            error: Mensagem de erro (se ``status='failed'``).
            dll_version: Versão da DLL no momento do download.

        Raises:
            ValueError: ``job_id`` não existe ou ``status`` inválido.
        """
        updates: list[str] = []
        params: list[object] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if actual_start is not None:
            updates.append("actual_start = ?")
            params.append(_format_ts(actual_start))
        if actual_end is not None:
            updates.append("actual_end = ?")
            params.append(_format_ts(actual_end))
        if trades_count is not None:
            updates.append("trades_count = ?")
            params.append(trades_count)
        if started_at is not None:
            updates.append("started_at = ?")
            params.append(_format_ts(started_at))
        if completed_at is not None:
            updates.append("completed_at = ?")
            params.append(_format_ts(completed_at))
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if dll_version is not None:
            updates.append("dll_version = ?")
            params.append(dll_version)

        if not updates:
            return

        params.append(job_id)
        with self._transaction():
            conn = self._conn_or_raise()
            cursor = conn.execute(
                f"UPDATE downloads SET {', '.join(updates)} WHERE job_id = ?",
                params,
            )
            if cursor.rowcount == 0:
                raise ValueError(f"job_id not found: {job_id}")

    def register_partition(
        self,
        write_result: WriteResult,
        partition: PartitionKey,
        *,
        job_id: str | None = None,
        day: int | None = None,
    ) -> None:
        """Registra (UPSERT) uma partição escrita pelo writer.

        Implementa o two-phase commit emulado (AC13):

        1. INSERT em ``_pending_commits`` com hash esperado.
        2. (writer já fez ``os.replace`` antes desta chamada — assumimos
           atomicidade do replace.)
        3. UPSERT em ``partitions`` + DELETE de ``_pending_commits``.

        UPSERT por ``partition_path`` torna a operação idempotente
        (AC6): re-registrar a mesma partição atualiza row_count,
        timestamps e checksum sem duplicar linhas.

        Após commit bem-sucedido, força ``wal_checkpoint(TRUNCATE)``
        (AC12) para evitar perda em crash entre write e checkpoint
        default. Trade-off: ~10ms extra por partição vs. ganho de
        durabilidade — aceitável dado que partições são escritas em
        granularidade mensal (não por trade).

        Args:
            write_result: Saída de ``ParquetWriter.write``.
            partition: ``PartitionKey`` correspondente.
            job_id: UUID do job que originou esta escrita (opcional).

        Raises:
            sqlite3.IntegrityError: Violação de constraint (ex:
                ``row_count < 0`` — defesa contra bug de writer).
        """
        if self.data_dir is None:  # pragma: no cover  defensive
            raise RuntimeError("data_dir not set; required for register_partition")

        rel_path = relative_partition_path(write_result.path, self.data_dir)
        now = _utcnow_iso()
        pid = os.getpid()

        # ADR-025 v1.3.0: ``day`` derivado em prioridade da ``PartitionKey``
        # (fonte canônica do layout); caller pode sobrescrever via kwarg
        # ``day`` se quiser registrar uma partição mensal a partir de uma
        # PartitionKey diária (uso raro — defensivo). NULL = mensal
        # compactado; NOT NULL = diário parcial.
        resolved_day = day if day is not None else partition.day

        # Fase 1 — pending commit (AC13).
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                """
                INSERT INTO _pending_commits(
                    partition_path, started_at, expected_sha256, expected_size, job_id, pid
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(partition_path) DO UPDATE SET
                    started_at = excluded.started_at,
                    expected_sha256 = excluded.expected_sha256,
                    expected_size = excluded.expected_size,
                    job_id = excluded.job_id,
                    pid = excluded.pid
                """,
                (
                    rel_path,
                    now,
                    write_result.checksum_sha256,
                    write_result.file_size_bytes,
                    job_id,
                    pid,
                ),
            )

        # Fase 2 — arquivo já está em disco (writer fez os.replace antes).
        # Fase 3 — UPSERT em partitions + clear pending commit.
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                """
                INSERT INTO partitions(
                    partition_path, symbol, exchange, year, month, day,
                    row_count, first_ts_ns, last_ts_ns, schema_version,
                    checksum_sha256, file_size_bytes, written_at, job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(partition_path) DO UPDATE SET
                    row_count = excluded.row_count,
                    first_ts_ns = excluded.first_ts_ns,
                    last_ts_ns = excluded.last_ts_ns,
                    schema_version = excluded.schema_version,
                    checksum_sha256 = excluded.checksum_sha256,
                    file_size_bytes = excluded.file_size_bytes,
                    day = excluded.day,
                    written_at = excluded.written_at,
                    job_id = COALESCE(excluded.job_id, partitions.job_id)
                """,
                (
                    rel_path,
                    partition.symbol,
                    partition.exchange,
                    partition.year,
                    partition.month,
                    resolved_day,
                    write_result.row_count,
                    write_result.first_ts_ns,
                    write_result.last_ts_ns,
                    self._get_meta("parquet_schema_min_supported") or "1.0.0",
                    write_result.checksum_sha256,
                    write_result.file_size_bytes,
                    now,
                    job_id,
                ),
            )
            conn.execute(
                "DELETE FROM _pending_commits WHERE partition_path = ?",
                (rel_path,),
            )

        # AC12 — WAL checkpoint forçado após cada register_partition.
        try:
            conn = self._conn_or_raise()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            _LOG.warning("catalog.wal_checkpoint.failed", extra={"err": str(exc)})

        # v1.3.0 Wave 2B — notifica observers (CatalogScreen auto-refresh).
        # APÓS o commit/checkpoint para que listeners que re-consultem o
        # catálogo enxerguem a partition recém-gravada.
        _notify_partition_observers(partition.symbol, partition.year, partition.month)

    def register_gap(
        self,
        symbol: str,
        exchange: str,
        gap_start: datetime,
        gap_end: datetime,
        reason: str,
    ) -> None:
        """Registra um gap em ``gaps``. UPSERT por chave composta.

        Args:
            symbol: Código do contrato.
            exchange: ``"F"`` ou ``"B"``.
            gap_start: Início do intervalo sem trades.
            gap_end: Fim do intervalo sem trades.
            reason: Categoria — ``no_trades``, ``holiday``, ``weekend``,
                ``failed_chunk``, ``unknown``, ``outside_vigency``.

        Raises:
            sqlite3.IntegrityError: ``reason`` não está na lista
                aceita pelo CHECK constraint.
        """
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                """
                INSERT INTO gaps(
                    symbol, exchange, gap_start, gap_end, reason, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, gap_start, gap_end) DO UPDATE SET
                    reason = excluded.reason,
                    exchange = excluded.exchange
                """,
                (
                    symbol,
                    exchange,
                    _format_ts(gap_start),
                    _format_ts(gap_end),
                    reason,
                    _utcnow_iso(),
                ),
            )

    # ------------------------------------------------------------------
    # Wave 1B — chunk_ledger (granularidade DIÁRIA — resume real)
    # ------------------------------------------------------------------

    def record_chunk(
        self,
        *,
        symbol: str,
        exchange: str,
        chunk_date: date,
        job_id: str | None,
        status: str,
        trades_count: int = 0,
    ) -> None:
        """Registra (UPSERT) 1 dia útil baixado em ``chunk_ledger`` (Wave 1B).

        Granularidade DIÁRIA — 1 row por ``(symbol, exchange, chunk_date)``.
        Chamado pelo orchestrator ao completar um chunk (sucesso ou
        ``no_trades``; ``failed`` registrado também, mas não conta como
        "feito" no resume/cache-hit). UPSERT torna re-runs idempotentes.

        Args:
            symbol: Contrato vigente (ex.: ``"WDOJ26"``) — NÃO a raiz.
            exchange: ``"F"`` ou ``"B"``.
            chunk_date: Dia útil B3 coberto por este chunk.
            job_id: UUID do job que originou (pode ser ``None``).
            status: ``"completed"`` (trades persistidos), ``"no_trades"``
                (dia válido vazio) ou ``"failed"`` (falha definitiva).
            trades_count: Trades persistidos neste dia (0 em no_trades/failed).
        """
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                """
                INSERT INTO chunk_ledger(
                    symbol, exchange, chunk_date, job_id, status, trades_count, written_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, exchange, chunk_date) DO UPDATE SET
                    job_id = excluded.job_id,
                    status = excluded.status,
                    trades_count = excluded.trades_count,
                    written_at = excluded.written_at
                """,
                (
                    symbol,
                    exchange,
                    chunk_date.isoformat(),
                    job_id,
                    status,
                    trades_count,
                    _utcnow_iso(),
                ),
            )

        # v1.3.0 Wave 2B — notifica observers (granularidade diária). UI usa
        # ``(year, month)`` derivados do ``chunk_date`` para coalescer múltiplos
        # chunks do mesmo mês num único refresh (debounce 500ms no adapter).
        _notify_partition_observers(symbol, chunk_date.year, chunk_date.month)

    def completed_days(
        self,
        symbol: str,
        exchange: str,
        start: date,
        end: date,
    ) -> set[date]:
        """Dias úteis já baixados (status ``completed``/``no_trades``) em ``[start, end]``.

        Consulta ``chunk_ledger`` (granularidade diária — Wave 1B). Usado
        pelo orchestrator no fresh-path skip + resume + cache-hit check
        para NÃO re-baixar dias já presentes. ``failed`` NÃO conta (queremos
        re-tentar dias que falharam definitivamente num run anterior).

        Args:
            symbol: Contrato vigente resolvido (ex.: ``"WDOJ26"``).
            exchange: ``"F"`` ou ``"B"``.
            start: Início do range (inclusive).
            end: Fim do range (inclusive).

        Returns:
            ``set`` de ``date`` — dias já baixados dentro do range. Vazio
            se nenhum.
        """
        conn = self._conn_or_raise()
        rows = conn.execute(
            "SELECT chunk_date FROM chunk_ledger "
            "WHERE symbol = ? AND exchange = ? AND status IN ('completed','no_trades') "
            "AND chunk_date >= ? AND chunk_date <= ?",
            (symbol, exchange, start.isoformat(), end.isoformat()),
        ).fetchall()
        out: set[date] = set()
        for r in rows:
            try:
                out.add(date.fromisoformat(str(r["chunk_date"])))
            except ValueError:  # pragma: no cover defensive — corrupted row
                continue
        return out

    # ------------------------------------------------------------------
    # ADR-025 Wave 3 — auto-compactação mensal (parquet-per-day híbrido)
    # ------------------------------------------------------------------

    def is_month_complete(
        self,
        symbol: str,
        exchange: str,
        year: int,
        month: int,
    ) -> bool:
        """``True`` se TODOS os dias úteis B3 de ``(year, month)`` estão no ledger.

        ADR-025 §2.3 / Wave 3: gate da auto-compactação mensal. Usa
        :func:`b3_business_days_range` (que respeita feriados B3 — dez/2024
        com Natal vira 21 dias úteis, não 22) e checa que cada dia útil
        tem row em ``chunk_ledger`` com ``status IN ('completed','no_trades')``.

        Args:
            symbol: Contrato vigente (ex.: ``"WDOJ26"``).
            exchange: ``"F"`` ou ``"B"``.
            year: Ano (4 dígitos).
            month: Mês 1..12.

        Returns:
            ``True`` se mês está completo no ledger; ``False`` caso contrário.
        """
        from calendar import monthrange

        from data_downloader.validation.calendar_b3 import b3_business_days_range

        last_day = monthrange(year, month)[1]
        first = date(year, month, 1)
        last = date(year, month, last_day)
        business_days = set(b3_business_days_range(first, last))
        if not business_days:
            # Mês sem dia útil (extremamente improvável; defensivo) — nada
            # a compactar.
            return False

        done = self.completed_days(symbol, exchange, first, last)
        return business_days.issubset(done)

    def maybe_compact_month(
        self,
        symbol: str,
        exchange: str,
        year: int,
        month: int,
        *,
        dll_version: str = "",
    ) -> bool:
        """Compacta o mês se ``is_month_complete``; idempotente; atômico (ADR-025).

        Pipeline:

        1. Checa ``is_month_complete`` — se False, no-op.
        2. INSERT em ``compactions`` (started_at=now, completed_at=NULL).
        3. Chama :func:`compact_month` (lê diários → write mensal atômico → DELETE diários).
        4. UPSERT na tabela ``partitions``: row mensal (day=NULL) + DELETE
           das rows diárias do mesmo ``(symbol, exchange, year, month)``.
        5. UPDATE ``compactions`` completed_at=now.

        Crash entre passos 3 e 5: ``reconcile`` detecta ``compactions``
        in-flight e completa (se ``MM.parquet`` íntegro) OU reverte
        (se inconsistente) — ver ADR-025 §2.4.

        Idempotência: se ``compact_month`` retorna ``None`` (no-op — já
        compactado, sem diários), apenas garante que o estado SQLite
        reflete a realidade (UPSERT mensal se necessário).

        Args:
            symbol: Contrato vigente.
            exchange: ``"F"`` ou ``"B"``.
            year: Ano.
            month: Mês 1..12.
            dll_version: Versão DLL p/ metadata (best-effort).

        Returns:
            ``True`` se compactou (executou IO); ``False`` se no-op
            (mês incompleto OU já compactado).
        """
        if self.data_dir is None:  # pragma: no cover defensive
            return False

        if not self.is_month_complete(symbol, exchange, year, month):
            return False

        # Import lazy para evitar ciclo (parquet_writer já importa schema).
        from data_downloader.storage.parquet_writer import compact_month

        now = _utcnow_iso()
        # Marca início da compactação (idempotente — UPSERT).
        try:
            with self._transaction():
                conn = self._conn_or_raise()
                conn.execute(
                    """
                    INSERT INTO compactions(
                        symbol, exchange, year, month, started_at, completed_at, error
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL)
                    ON CONFLICT(symbol, exchange, year, month) DO UPDATE SET
                        started_at = excluded.started_at,
                        completed_at = NULL,
                        error = NULL
                    """,
                    (symbol, exchange, year, month, now),
                )
        except sqlite3.Error as exc:
            _LOG.warning(
                "catalog.maybe_compact_month.tracker_failed",
                extra={"err": str(exc), "symbol": symbol, "year": year, "month": month},
            )

        try:
            result = compact_month(
                self.data_dir,
                exchange=exchange,
                symbol=symbol,
                year=year,
                month=month,
                dll_version=dll_version,
            )
        except Exception as exc:
            with contextlib.suppress(sqlite3.Error), self._transaction():
                conn = self._conn_or_raise()
                conn.execute(
                    "UPDATE compactions SET error = ? "
                    "WHERE symbol = ? AND exchange = ? AND year = ? AND month = ?",
                    (str(exc), symbol, exchange, year, month),
                )
            _LOG.warning(
                "catalog.maybe_compact_month.failed",
                extra={"err": str(exc), "symbol": symbol, "year": year, "month": month},
            )
            return False

        # Persistir estado SQLite ATOMICAMENTE:
        # - DELETE rows diárias do (symbol, exchange, year, month) em partitions
        # - UPSERT row mensal (day=NULL) se compact_month executou
        # - UPDATE compactions completed_at
        finished = _utcnow_iso()
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                "DELETE FROM partitions WHERE symbol = ? AND exchange = ? "
                "AND year = ? AND month = ? AND day IS NOT NULL",
                (symbol, exchange, year, month),
            )
            if result is not None:
                rel_path = relative_partition_path(result.path, self.data_dir)
                conn.execute(
                    """
                    INSERT INTO partitions(
                        partition_path, symbol, exchange, year, month, day,
                        row_count, first_ts_ns, last_ts_ns, schema_version,
                        checksum_sha256, file_size_bytes, written_at, job_id
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(partition_path) DO UPDATE SET
                        row_count = excluded.row_count,
                        first_ts_ns = excluded.first_ts_ns,
                        last_ts_ns = excluded.last_ts_ns,
                        schema_version = excluded.schema_version,
                        checksum_sha256 = excluded.checksum_sha256,
                        file_size_bytes = excluded.file_size_bytes,
                        day = NULL,
                        written_at = excluded.written_at
                    """,
                    (
                        rel_path,
                        symbol,
                        exchange,
                        year,
                        month,
                        result.row_count,
                        result.first_ts_ns,
                        result.last_ts_ns,
                        self._get_meta("parquet_schema_min_supported") or "1.0.0",
                        result.checksum_sha256,
                        result.file_size_bytes,
                        finished,
                    ),
                )
            conn.execute(
                "UPDATE compactions SET completed_at = ? "
                "WHERE symbol = ? AND exchange = ? AND year = ? AND month = ?",
                (finished, symbol, exchange, year, month),
            )

        _LOG.info(
            "catalog.maybe_compact_month.success",
            extra={
                "symbol": symbol,
                "exchange": exchange,
                "year": year,
                "month": month,
                "rows": result.row_count if result is not None else 0,
                "noop": result is None,
            },
        )

        if result is not None:
            _notify_partition_observers(symbol, year, month)
        return result is not None

    def get_completed_partitions(self, symbol: str, exchange: str) -> list[Partition]:
        """Lista partições registradas para ``(symbol, exchange)``.

        Ordenado por ``(year, month)`` ascendente.

        Args:
            symbol: Código do contrato.
            exchange: ``"F"`` ou ``"B"``.

        Returns:
            Lista de ``Partition`` (vazia se nenhuma).
        """
        conn = self._conn_or_raise()
        rows = conn.execute(
            "SELECT * FROM partitions WHERE symbol = ? AND exchange = ? "
            "ORDER BY year ASC, month ASC",
            (symbol, exchange),
        ).fetchall()
        return [_row_to_partition(r) for r in rows]

    def get_job(self, job_id: str) -> Job | None:
        """Busca job por ``job_id``. ``None`` se não existe."""
        conn = self._conn_or_raise()
        row = conn.execute("SELECT * FROM downloads WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return _row_to_job(row)

    def list_jobs(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[Job]:
        """Lista jobs do catálogo, mais recentes primeiro.

        v1.2.0 Wave 1D (Uma/Felix — detecção de download interrompido):
        a UI consulta jobs com ``status in ('in_progress','partial')`` ao
        reabrir o app para oferecer "Retomar".

        Args:
            statuses: Filtra por status (ex.: ``("in_progress", "partial")``).
                ``None`` = todos.
            limit: Limita o número de linhas retornadas. ``None`` = sem limite.

        Returns:
            Lista de :class:`Job` ordenada por ``started_at``/``completed_at``
            descendente (jobs sem timestamp ao final).
        """
        conn = self._conn_or_raise()
        sql = "SELECT * FROM downloads"
        params: list[object] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        sql += " ORDER BY COALESCE(completed_at, started_at) DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_job(r) for r in rows]

    def get_gaps(self, symbol: str) -> list[Gap]:
        """Lista gaps para um símbolo (resolvidos e não-resolvidos)."""
        conn = self._conn_or_raise()
        rows = conn.execute(
            "SELECT * FROM gaps WHERE symbol = ? ORDER BY gap_start ASC",
            (symbol,),
        ).fetchall()
        return [
            Gap(
                symbol=r["symbol"],
                exchange=r["exchange"],
                gap_start=_parse_ts(r["gap_start"]),
                gap_end=_parse_ts(r["gap_end"]),
                reason=r["reason"],
                detected_at=_parse_ts(r["detected_at"]),
                resolved_at=_parse_ts_or_none(r["resolved_at"]),
            )
            for r in rows
        ]

    def get_pending_chunks(self, job_id: str) -> list[ChunkRange]:
        """Calcula chunks pendentes para um job (AC4 + AC8).

        Combina: ``Job.requested_*`` (range solicitado) - partições já
        completas associadas a este job. Granularidade mensal.

        Args:
            job_id: UUID do job.

        Returns:
            Lista de ``ChunkRange`` cobrindo meses não baixados.

        Raises:
            ValueError: ``job_id`` não existe.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job_id not found: {job_id}")

        # Wave 1B — `OR` impedia uso de índice (full scan @ 90k rows no
        # resume). UNION de dois SELECTs: o 1º usa `idx_partitions_job`
        # (job_id), o 2º usa `idx_partitions_symbol_ym` (symbol, year,
        # month). UNION (não UNION ALL) já dedup linhas idênticas.
        conn = self._conn_or_raise()
        rows = conn.execute(
            "SELECT * FROM partitions WHERE job_id = ? "
            "UNION "
            "SELECT * FROM partitions WHERE symbol = ? AND exchange = ? "
            "ORDER BY year ASC, month ASC",
            (job_id, job.symbol, job.exchange),
        ).fetchall()
        completed = [_row_to_partition(r) for r in rows]

        return compute_pending_chunks(
            symbol=job.symbol,
            exchange=job.exchange,
            requested_start=job.requested_start,
            requested_end=job.requested_end,
            completed_partitions=completed,
        )

    def resume_job(self, job_id: str) -> ResumePlan:
        """Plano de resume para um job interrompido (AC8).

        Combina o snapshot do ``Job``, suas partições já gravadas e os
        chunks pendentes — tudo o que o orchestrator precisa para
        continuar de onde parou.

        Args:
            job_id: UUID do job.

        Returns:
            ``ResumePlan`` imutável.

        Raises:
            ValueError: ``job_id`` não existe.
        """
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job_id not found: {job_id}")

        completed = self.get_completed_partitions(job.symbol, job.exchange)
        pending = compute_pending_chunks(
            symbol=job.symbol,
            exchange=job.exchange,
            requested_start=job.requested_start,
            requested_end=job.requested_end,
            completed_partitions=completed,
        )
        return ResumePlan(
            job=job,
            completed_partitions=tuple(completed),
            pending_chunks=tuple(pending),
        )

    # ------------------------------------------------------------------
    # AC7 — cleanup de tmp órfãos
    # ------------------------------------------------------------------

    def cleanup_orphans(self, max_age_seconds: int = _ORPHAN_TMP_MAX_AGE_DEFAULT) -> list[Path]:
        """Remove arquivos ``.tmp.{uuid}`` antigos (>``max_age_seconds``).

        Varre ``data_dir/history/**`` em busca de arquivos cujo nome
        contém ``.tmp.`` (padrão writer Story 1.4 AC5) e cuja idade
        (now - mtime) excede o limite. Deleta com log.

        Args:
            max_age_seconds: Idade mínima em segundos para considerar
                órfão. Default 300 (5 min) — alinha com janela razoável
                de write atômico.

        Returns:
            Lista de paths efetivamente removidos.
        """
        if self.data_dir is None:  # pragma: no cover defensive
            return []

        history_root = self.data_dir / "history"
        if not history_root.exists():
            return []

        removed: list[Path] = []
        now = time.time()
        threshold = now - max_age_seconds

        # Padrão: writer escreve em ``{name}.tmp.{uuid4hex}``.
        for path in history_root.rglob("*.tmp.*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime > threshold:
                # Recente — possivelmente write em curso, não tocar.
                continue
            try:
                path.unlink()
                removed.append(path)
                _LOG.info(
                    "catalog.cleanup_orphans.removed",
                    extra={"path": str(path), "age_seconds": int(now - stat.st_mtime)},
                )
            except OSError as exc:
                _LOG.warning(
                    "catalog.cleanup_orphans.unlink_failed",
                    extra={"path": str(path), "err": str(exc)},
                )
        return removed

    # ------------------------------------------------------------------
    # AC9 + AC11 — reconcile (drift A/B/C)
    # ------------------------------------------------------------------

    def reconcile(self, *, auto_correct: bool = False) -> ReconcileReport:
        """Compara catálogo vs filesystem; reporta drift A/B/C.

        Tipos de drift (INTEGRITY.md §5):

        - **A** — arquivo Parquet em disco SEM entrada em ``partitions``
          (catálogo desatualizado). Em ``auto_correct=True``, é
          re-registrado com metadata mínima derivada do disco.
        - **B** — entrada em ``partitions`` SEM arquivo correspondente
          (deletado externamente). NUNCA auto-corrigido — só reportado.
        - **C** — entrada + arquivo presentes mas
          ``checksum_sha256`` diverge (corrupção / edição externa).
          NUNCA auto-corrigido.

        Drift A é o único auto-corrigível porque os outros podem
        mascarar perda/corrupção real e devem requerer investigação
        humana. Política Sol — INTEGRITY.md §5.

        Args:
            auto_correct: Se ``True``, re-registra drift A. Default
                ``False`` para uso ad-hoc; ``__init__`` chama com
                ``True`` (AC11).

        Returns:
            ``ReconcileReport`` com listas de paths relativos por
            categoria + lista de auto-corrigidos.
        """
        if self.data_dir is None:  # pragma: no cover defensive
            return ReconcileReport()

        # ADR-025 §2.4 — antes de comparar drift, resolve compactações
        # in-flight (crash entre write {MM}.parquet e DELETE diários).
        # Faz isso ANTES da varredura de disk_paths para que o estado
        # filesystem reflita a decisão (cleanup ou revert).
        if auto_correct:
            try:
                self._recover_inflight_compactions()
            except Exception as exc:  # pragma: no cover  defensive
                _LOG.warning(
                    "catalog.reconcile.recover_inflight_failed",
                    extra={"err": str(exc)},
                )

        history_root = self.data_dir / "history"
        catalog_paths = self._list_catalog_partition_paths()

        # Paths em disco (relativos a history_root).
        disk_paths: dict[str, Path] = {}
        if history_root.exists():
            for parquet in history_root.rglob("*.parquet"):
                if not parquet.is_file():
                    continue
                # Excluir arquivos .tmp.* (não são partições válidas).
                if ".tmp." in parquet.name:
                    continue
                rel = parquet.relative_to(history_root).as_posix()
                disk_paths[rel] = parquet

        drift_a: list[str] = sorted(set(disk_paths.keys()) - set(catalog_paths.keys()))
        drift_b: list[str] = sorted(set(catalog_paths.keys()) - set(disk_paths.keys()))
        drift_c: list[str] = []
        auto_corrected: list[str] = []

        # Drift C — checksum diverge.
        for rel in sorted(set(catalog_paths.keys()) & set(disk_paths.keys())):
            expected = catalog_paths[rel]
            actual = self._get_or_compute_checksum(disk_paths[rel], rel)
            if actual != expected:
                drift_c.append(rel)

        # AC11 — auto-correct drift A (apenas).
        if auto_correct and drift_a:
            for rel in drift_a:
                disk_path = disk_paths[rel]
                if self._auto_register_from_disk(rel, disk_path):
                    auto_corrected.append(rel)

        return ReconcileReport(
            drift_a=tuple(drift_a),
            drift_b=tuple(drift_b),
            drift_c=tuple(drift_c),
            auto_corrected_paths=tuple(auto_corrected),
        )

    def _recover_inflight_compactions(self) -> None:
        """Resolve compactações in-flight (ADR-025 §2.4).

        Crash entre write ``{MM}.parquet`` e DELETE diários deixa rows em
        ``compactions`` com ``started_at`` mas sem ``completed_at``. Para
        cada uma:

        - Se ``{MM}.parquet`` íntegro (row_count >= sum(daily.row_count)):
          completa cleanup (DELETE diários + UPDATE compactions.completed_at).
          O Parquet mensal já foi escrito atomicamente — completar é seguro.
        - Caso contrário (`MM.parquet` inexistente OU menor que diários):
          REVERTE — deleta o `{MM}.parquet` se existir, marca
          ``compactions.error='reverted'`` para inspeção humana.
        """
        if self.data_dir is None:  # pragma: no cover defensive
            return

        conn = self._conn_or_raise()
        try:
            rows = conn.execute(
                "SELECT symbol, exchange, year, month FROM compactions WHERE completed_at IS NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            # Tabela ainda não existe (DB pré-v1.3.0 sem migrations
            # aplicadas) — no-op.
            return

        for r in rows:
            symbol = str(r["symbol"])
            exchange = str(r["exchange"])
            year = int(r["year"])
            month = int(r["month"])
            self._resolve_inflight_compaction(symbol, exchange, year, month)

    def _resolve_inflight_compaction(
        self, symbol: str, exchange: str, year: int, month: int
    ) -> None:
        """Aplica a política ADR-025 §2.4 para uma compactação in-flight."""
        if self.data_dir is None:  # pragma: no cover defensive
            return

        monthly_partition = PartitionKey(exchange=exchange, symbol=symbol, year=year, month=month)
        from data_downloader.storage.partition import resolve_partition_path

        monthly_path = resolve_partition_path(monthly_partition, self.data_dir)
        month_dir = monthly_path.with_suffix("")  # {MM}/ directory.

        # Coleta diários remanescentes (file system).
        daily_paths: list[Path] = []
        if month_dir.is_dir():
            for p in sorted(month_dir.glob("*.parquet")):
                if ".tmp." in p.name:
                    continue
                daily_paths.append(p)

        # Soma row_count das rows em ``partitions`` para os diários
        # remanescentes (cheaper than re-reading parquet).
        conn = self._conn_or_raise()
        daily_rows_in_catalog = conn.execute(
            "SELECT COALESCE(SUM(row_count), 0) AS total FROM partitions "
            "WHERE symbol = ? AND exchange = ? AND year = ? AND month = ? "
            "AND day IS NOT NULL",
            (symbol, exchange, year, month),
        ).fetchone()
        daily_total_rows = int(daily_rows_in_catalog["total"]) if daily_rows_in_catalog else 0

        monthly_rows = 0
        monthly_exists = monthly_path.is_file()
        if monthly_exists:
            try:
                import pyarrow.parquet as pq

                md = pq.read_metadata(monthly_path).metadata
                if md is not None and b"row_count" in md:
                    monthly_rows = int(md[b"row_count"].decode())
                else:
                    monthly_rows = int(pq.read_metadata(monthly_path).num_rows)
            except Exception as exc:  # pragma: no cover defensive
                _LOG.warning(
                    "catalog.recover_inflight.metadata_read_failed",
                    extra={"path": str(monthly_path), "err": str(exc)},
                )
                monthly_rows = -1

        # Política ADR-025 §2.4.
        # - Completa cleanup se monthly_rows >= daily_total_rows (e file íntegro).
        # - Reverte caso contrário.
        if monthly_exists and monthly_rows >= daily_total_rows and monthly_rows > 0:
            # Completa cleanup — deleta diários (file + catalog).
            for p in daily_paths:
                try:
                    p.unlink()
                except OSError as exc:
                    _LOG.warning(
                        "catalog.recover_inflight.daily_unlink_failed",
                        extra={"path": str(p), "err": str(exc)},
                    )
            try:
                if month_dir.is_dir() and not any(month_dir.iterdir()):
                    month_dir.rmdir()
            except OSError:
                pass
            with self._transaction():
                c = self._conn_or_raise()
                c.execute(
                    "DELETE FROM partitions WHERE symbol = ? AND exchange = ? "
                    "AND year = ? AND month = ? AND day IS NOT NULL",
                    (symbol, exchange, year, month),
                )
                c.execute(
                    "UPDATE compactions SET completed_at = ? "
                    "WHERE symbol = ? AND exchange = ? AND year = ? AND month = ?",
                    (_utcnow_iso(), symbol, exchange, year, month),
                )
            _LOG.info(
                "catalog.recover_inflight.completed_cleanup",
                extra={"symbol": symbol, "year": year, "month": month},
            )
        else:
            # Reverte — deleta {MM}.parquet (se inconsistente) e mantém diários.
            if monthly_exists:
                try:
                    monthly_path.unlink()
                except OSError as exc:
                    _LOG.warning(
                        "catalog.recover_inflight.monthly_unlink_failed",
                        extra={"path": str(monthly_path), "err": str(exc)},
                    )
            with self._transaction():
                c = self._conn_or_raise()
                # Remove a row mensal do partitions se existir (drift seria
                # capturado depois, mas explícito é melhor).
                c.execute(
                    "DELETE FROM partitions WHERE symbol = ? AND exchange = ? "
                    "AND year = ? AND month = ? AND day IS NULL",
                    (symbol, exchange, year, month),
                )
                c.execute(
                    "UPDATE compactions SET error = 'reverted', completed_at = ? "
                    "WHERE symbol = ? AND exchange = ? AND year = ? AND month = ?",
                    (_utcnow_iso(), symbol, exchange, year, month),
                )
            _LOG.warning(
                "catalog.recover_inflight.reverted",
                extra={
                    "symbol": symbol,
                    "year": year,
                    "month": month,
                    "monthly_rows": monthly_rows,
                    "daily_total_rows": daily_total_rows,
                },
            )

    def _list_catalog_partition_paths(self) -> dict[str, str]:
        """Retorna ``{partition_path: checksum_sha256}`` de ``partitions``."""
        conn = self._conn_or_raise()
        rows = conn.execute("SELECT partition_path, checksum_sha256 FROM partitions").fetchall()
        return {r["partition_path"]: r["checksum_sha256"] for r in rows}

    def _get_or_compute_checksum(self, path: Path, rel_path: str) -> str:
        """Busca checksum em cache; recomputa se ``(size, mtime)`` mudou.

        Política INTEGRITY.md §3.2 — rehash apenas se metadata diverge.
        Ambiente alvo (Windows + NTFS) honra ``mtime_ns`` corretamente.
        """
        conn = self._conn_or_raise()
        try:
            stat = path.stat()
        except OSError:
            return ""

        cached = conn.execute(
            "SELECT checksum_sha256 FROM _checksum_cache "
            "WHERE partition_path = ? AND file_size_bytes = ? AND mtime_ns = ?",
            (rel_path, stat.st_size, stat.st_mtime_ns),
        ).fetchone()
        if cached is not None:
            return str(cached["checksum_sha256"])

        digest = _sha256_file(path)
        try:
            with self._transaction():
                conn.execute(
                    """
                    INSERT INTO _checksum_cache(
                        partition_path, file_size_bytes, mtime_ns, checksum_sha256, cached_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(partition_path) DO UPDATE SET
                        file_size_bytes = excluded.file_size_bytes,
                        mtime_ns = excluded.mtime_ns,
                        checksum_sha256 = excluded.checksum_sha256,
                        cached_at = excluded.cached_at
                    """,
                    (rel_path, stat.st_size, stat.st_mtime_ns, digest, _utcnow_iso()),
                )
        except sqlite3.IntegrityError:
            # FK violation — partition_path não existe em partitions ainda.
            # OK; cache é puro otimização.
            pass
        return digest

    def _auto_register_from_disk(self, rel_path: str, disk_path: Path) -> bool:
        """Re-registra um arquivo Parquet em ``partitions`` (drift A fix).

        Lê metadata Parquet para extrair ``row_count``, ``first_ts_ns``,
        ``last_ts_ns``, ``schema_version`` e calcula SHA256. Se metadata
        ausente/corrompida, NÃO registra (drift A vira candidato a
        quarantine futura — INTEGRITY.md §5.1).

        Returns:
            ``True`` se registrado com sucesso.
        """
        try:
            import pyarrow.parquet as pq

            md_obj = pq.read_metadata(disk_path).metadata
        except (OSError, ValueError) as exc:
            _LOG.warning(
                "catalog.auto_register.metadata_read_failed",
                extra={"path": rel_path, "err": str(exc)},
            )
            return False

        if md_obj is None:
            _LOG.warning("catalog.auto_register.no_metadata", extra={"path": rel_path})
            return False

        try:
            row_count = int(md_obj.get(b"row_count", b"0").decode())
            first_ts = int(md_obj.get(b"first_ts_ns", b"0").decode())
            last_ts = int(md_obj.get(b"last_ts_ns", b"0").decode())
            schema_version = md_obj.get(b"schema_version", b"1.0.0").decode()
        except (ValueError, AttributeError) as exc:
            _LOG.warning(
                "catalog.auto_register.metadata_parse_failed",
                extra={"path": rel_path, "err": str(exc)},
            )
            return False

        # Extrai (exchange, symbol, year, month, [day]) do path relativo.
        # ADR-025 v1.3.0: 2 layouts aceitos:
        #   - mensal: "{exchange}/{symbol}/{year}/{MM}.parquet"  (4 parts)
        #   - diário: "{exchange}/{symbol}/{year}/{MM}/{DD}.parquet"  (5 parts)
        parts = rel_path.split("/")
        day: int | None = None
        try:
            if len(parts) == 4 and parts[3].endswith(".parquet"):
                exchange = parts[0]
                symbol = parts[1]
                year = int(parts[2])
                month = int(parts[3].removesuffix(".parquet"))
            elif len(parts) == 5 and parts[4].endswith(".parquet"):
                exchange = parts[0]
                symbol = parts[1]
                year = int(parts[2])
                month = int(parts[3])
                day = int(parts[4].removesuffix(".parquet"))
            else:
                _LOG.warning("catalog.auto_register.invalid_layout", extra={"path": rel_path})
                return False
        except ValueError:
            _LOG.warning("catalog.auto_register.parse_failed", extra={"path": rel_path})
            return False

        try:
            file_size = disk_path.stat().st_size
        except OSError as exc:
            _LOG.warning(
                "catalog.auto_register.stat_failed",
                extra={"path": rel_path, "err": str(exc)},
            )
            return False

        checksum = _sha256_file(disk_path)
        now = _utcnow_iso()
        with self._transaction():
            conn = self._conn_or_raise()
            conn.execute(
                """
                INSERT INTO partitions(
                    partition_path, symbol, exchange, year, month, day,
                    row_count, first_ts_ns, last_ts_ns, schema_version,
                    checksum_sha256, file_size_bytes, written_at, job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(partition_path) DO UPDATE SET
                    row_count = excluded.row_count,
                    first_ts_ns = excluded.first_ts_ns,
                    last_ts_ns = excluded.last_ts_ns,
                    schema_version = excluded.schema_version,
                    checksum_sha256 = excluded.checksum_sha256,
                    file_size_bytes = excluded.file_size_bytes,
                    day = excluded.day,
                    written_at = excluded.written_at
                """,
                (
                    rel_path,
                    symbol,
                    exchange,
                    year,
                    month,
                    day,
                    row_count,
                    first_ts,
                    last_ts,
                    schema_version,
                    checksum,
                    file_size,
                    now,
                ),
            )
        return True


def _semver_le(a: str, b: str) -> bool:
    """``a <= b`` para versões semver ``MAJOR.MINOR.PATCH`` (numéricas)."""
    pa = tuple(int(x) for x in a.split("."))
    pb = tuple(int(x) for x in b.split("."))
    return pa <= pb


def _is_add_column_stmt(stmt: str) -> bool:
    """``True`` se ``stmt`` é um ``ALTER TABLE ... ADD COLUMN ...`` (ADR-025)."""
    s = stmt.strip().upper()
    return s.startswith("ALTER TABLE") and "ADD COLUMN" in s


def _column_exists(conn: sqlite3.Connection, alter_stmt: str) -> bool:
    """Verifica via ``PRAGMA table_info`` se a coluna do ``ALTER`` já existe.

    Parser leve: extrai ``<table>`` e ``<column>`` do statement
    ``ALTER TABLE <table> ADD COLUMN <column> <rest...>``. NÃO é parser
    SQL completo — assume o formato dos statements do registry.
    """
    # Tokenize na ordem esperada (case-insensitive).
    tokens = alter_stmt.replace("(", " ( ").replace(",", " , ").split()
    upper = [t.upper() for t in tokens]
    try:
        i_table = upper.index("TABLE")
        table = tokens[i_table + 1]
        i_col = upper.index("COLUMN")
        column = tokens[i_col + 1]
    except (ValueError, IndexError):  # pragma: no cover  defensive
        return False
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:  # pragma: no cover defensive
        return False
    existing = {str(r[1]) for r in rows}
    return column in existing


__all__ = [
    "CATALOG_VERSION",
    "MIGRATIONS",
    "Catalog",
    "PartitionObserver",
    "register_partition_observer",
    "unregister_partition_observer",
]
