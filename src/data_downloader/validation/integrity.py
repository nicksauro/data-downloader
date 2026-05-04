"""data_downloader.validation.integrity — Integrity checker (Sol).

Owner: 💾 Sol (storage authority — invariantes INT-1..INT-12).
Co-reviewer: 🧪 Quinn (gate de QA depende destes checks).

Refs:

- ``docs/storage/INTEGRITY.md`` §1 (invariantes), §2 (queries DuckDB
  canônicas), §5 (drift A/B/C via Catalog.reconcile)
- Story 2.1 (esta) — finding C4 do Plan Review 2026-05-03
- Story 1.5 (Catalog.reconcile)

Pipeline canônico (uso conceitual; CLI real em ``cli.py``):

    checker = IntegrityChecker(data_dir, catalog)
    report = checker.run_all(symbol="WDOJ26")
    if not report.overall_passed:
        # Iterar report.checks e logar via structlog (ADR-010).
        ...

Cada método ``check_*`` retorna :class:`IntegrityCheck` com:

- ``passed: bool`` — invariante mantida.
- ``severity`` — ``"critical"`` (corrupção / perda) | ``"high"``
  (violação clara) | ``"medium"`` (alerta operacional).
- ``evidence: dict | None`` — payload curto para o relatório (counts,
  primeiros offenders, etc.).

Política Sol:

- Queries são EXATAMENTE as de INTEGRITY.md §2 — qualquer divergência é
  bug.
- Não inventar checks novos — toda invariante nova precisa de bump em
  INTEGRITY.md primeiro.
"""

from __future__ import annotations

import glob
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb
import pyarrow.parquet as pq

from data_downloader.storage.catalog import Catalog

# Severities canônicas (alinhado com STORY_GATES_2026-05-04 verdict matrix).
Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass(frozen=True)
class IntegrityCheck:
    """Resultado de uma checagem individual de invariante.

    Attributes:
        name: Identificador estável (ex.: ``"INT-2.no_duplicates"``).
        passed: ``True`` se a invariante é mantida.
        severity: Gravidade caso ``not passed``. Ignorado se passou.
        message: Texto humano-legível sobre o resultado.
        evidence: Payload opcional (counts, primeiros offenders, etc.).
    """

    name: str
    passed: bool
    severity: Severity
    message: str
    evidence: dict[str, object] | None = None


@dataclass(frozen=True)
class IntegrityReport:
    """Relatório consolidado de :meth:`IntegrityChecker.run_all`.

    Attributes:
        checks: Lista ordenada de :class:`IntegrityCheck` executados.
        overall_passed: ``True`` se TODOS os checks passaram.
        dataset_path: Diretório raiz do dataset auditado (data_dir).
        ran_at: ISO8601 UTC do momento do run.
        hash_canonical: Hash determinístico do conteúdo do report (para
            referência cruzada em audit reports). String hex curta.
    """

    checks: tuple[IntegrityCheck, ...]
    overall_passed: bool
    dataset_path: str
    ran_at: str
    hash_canonical: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serializa o report como dict (para JSON / templates Markdown).

        Returns:
            Dict aninhado pronto para ``json.dumps``. Datetimes já em
            ISO8601 string.
        """
        return {
            "dataset_path": self.dataset_path,
            "ran_at": self.ran_at,
            "overall_passed": self.overall_passed,
            "hash_canonical": self.hash_canonical,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "severity": c.severity,
                    "message": c.message,
                    "evidence": c.evidence,
                }
                for c in self.checks
            ],
        }


@dataclass
class IntegrityChecker:
    """Roda os 6 checks principais de integridade sobre um dataset.

    Cada método ``check_*`` é puro (não muta estado) e idempotente —
    pode ser invocado isoladamente em CI.

    Args:
        data_dir: Raiz dos dados (mesma usada por writer/catalog).
        catalog: Instância de :class:`Catalog` (para drift A/B/C via
            ``catalog.reconcile``).
    """

    data_dir: Path
    catalog: Catalog
    _conn: duckdb.DuckDBPyConnection | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _connection(self) -> duckdb.DuckDBPyConnection:
        """Lazy DuckDB in-memory para queries cross-Parquet."""
        if self._conn is None:
            self._conn = duckdb.connect(":memory:")
        return self._conn

    def close(self) -> None:
        """Fecha conexão DuckDB. Idempotente."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _glob_paths(self, symbol: str | None, exchange: str = "F") -> list[str]:
        """Resolve glob de Parquets para ``(symbol, exchange)``.

        Se ``symbol is None``, varre todos os símbolos da exchange dada.
        """
        history_root = self.data_dir / "history"
        if not history_root.exists():
            return []
        if symbol is None:
            pattern = str(history_root / exchange / "**" / "*.parquet")
        else:
            pattern = str(history_root / exchange / symbol / "**" / "*.parquet")
        # Ignora .tmp.* — não são partições válidas.
        paths = sorted(p for p in glob.glob(pattern, recursive=True) if ".tmp." not in p)
        return paths

    # ------------------------------------------------------------------
    # INT-2 — duplicates (queries de INTEGRITY.md §2.2)
    # ------------------------------------------------------------------

    def check_no_duplicates(
        self, symbol: str | None = None, *, exchange: str = "F"
    ) -> IntegrityCheck:
        """INT-2: ``(symbol, timestamp_ns, trade_id)`` é único.

        Para trades com ``trade_id IS NULL`` cai na chave longa
        canônica de SCHEMA.md §2 (price, qty, agents, sequence_within_ns).

        Implementação fiel a INTEGRITY.md §2.2 — qualquer divergência é
        bug.
        """
        paths = self._glob_paths(symbol, exchange=exchange)
        if not paths:
            return IntegrityCheck(
                name="INT-2.no_duplicates",
                passed=True,
                severity="info",
                message="No partitions found for given (symbol, exchange) — vacuous PASS.",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": 0},
            )

        conn = self._connection()
        sql = """
            WITH all_keys AS (
                SELECT
                    symbol,
                    timestamp_ns,
                    trade_id,
                    CASE
                        WHEN trade_id IS NOT NULL
                            THEN CONCAT(symbol, '|', timestamp_ns, '|TID:', trade_id)
                        ELSE CONCAT(
                            symbol, '|', timestamp_ns,
                            '|', price, '|', quantity,
                            '|', COALESCE(CAST(buy_agent_id AS VARCHAR), 'NULL'),
                            '|', COALESCE(CAST(sell_agent_id AS VARCHAR), 'NULL'),
                            '|SEQ:', sequence_within_ns
                        )
                    END AS dedup_key
                FROM read_parquet(?)
            )
            SELECT dedup_key, COUNT(*) AS n
            FROM all_keys
            GROUP BY dedup_key
            HAVING COUNT(*) > 1
            ORDER BY n DESC
            LIMIT 10
        """
        rows = conn.execute(sql, [paths]).fetchall()
        if not rows:
            return IntegrityCheck(
                name="INT-2.no_duplicates",
                passed=True,
                severity="info",
                message=f"No duplicates in {len(paths)} partition(s).",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": len(paths)},
            )
        return IntegrityCheck(
            name="INT-2.no_duplicates",
            passed=False,
            severity="critical",
            message=f"Found {len(rows)} duplicate key(s) (showing top 10).",
            evidence={
                "symbol": symbol,
                "exchange": exchange,
                "paths_scanned": len(paths),
                "top_duplicates": [{"key": r[0], "count": int(r[1])} for r in rows],
            },
        )

    # ------------------------------------------------------------------
    # INT-3 — monotonic timestamps (INTEGRITY.md §2.3)
    # ------------------------------------------------------------------

    def check_monotonic_timestamps(
        self, symbol: str | None = None, *, exchange: str = "F"
    ) -> IntegrityCheck:
        """INT-3: ``timestamp_ns`` monotônico em
        ``ORDER BY (timestamp_ns, sequence_within_ns)``.
        """
        paths = self._glob_paths(symbol, exchange=exchange)
        if not paths:
            return IntegrityCheck(
                name="INT-3.monotonic_timestamps",
                passed=True,
                severity="info",
                message="No partitions found — vacuous PASS.",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": 0},
            )

        conn = self._connection()
        sql = """
            WITH ordered AS (
                SELECT
                    timestamp_ns,
                    sequence_within_ns,
                    LAG(timestamp_ns) OVER (
                        ORDER BY timestamp_ns, sequence_within_ns
                    ) AS prev_ts
                FROM read_parquet(?)
            )
            SELECT COUNT(*) AS regression_count
            FROM ordered
            WHERE prev_ts IS NOT NULL AND timestamp_ns < prev_ts
        """
        result = conn.execute(sql, [paths]).fetchone()
        regressions = int(result[0]) if result is not None else 0
        if regressions == 0:
            return IntegrityCheck(
                name="INT-3.monotonic_timestamps",
                passed=True,
                severity="info",
                message=f"All timestamps monotonic across {len(paths)} partition(s).",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": len(paths)},
            )
        return IntegrityCheck(
            name="INT-3.monotonic_timestamps",
            passed=False,
            severity="high",
            message=f"{regressions} timestamp regression(s) detected.",
            evidence={
                "symbol": symbol,
                "exchange": exchange,
                "paths_scanned": len(paths),
                "regression_count": regressions,
            },
        )

    # ------------------------------------------------------------------
    # INT-1 — schema_version_present (INTEGRITY.md §2.1)
    # ------------------------------------------------------------------

    def check_schema_version_present(
        self, symbol: str | None = None, *, exchange: str = "F"
    ) -> IntegrityCheck:
        """INT-1: todo Parquet tem ``schema_version`` no metadata.

        Lê metadata Parquet de cada arquivo no escopo. Acceita versões
        começando com ``"1."`` ou ``"2."`` (futuras majors aditivas
        precisam ajustar).
        """
        paths = self._glob_paths(symbol, exchange=exchange)
        if not paths:
            return IntegrityCheck(
                name="INT-1.schema_version_present",
                passed=True,
                severity="info",
                message="No partitions found — vacuous PASS.",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": 0},
            )

        offenders: list[str] = []
        for path in paths:
            try:
                md = pq.read_metadata(path).metadata or {}
            except (OSError, ValueError) as exc:
                offenders.append(f"{path} (read_metadata failed: {exc})")
                continue
            sv = md.get(b"schema_version")
            if sv is None:
                offenders.append(f"{path} (missing schema_version)")
                continue
            sv_str = sv.decode() if isinstance(sv, bytes) else str(sv)
            if not sv_str.startswith(("1.", "2.")):
                offenders.append(f"{path} (unknown schema_version={sv_str!r})")

        if not offenders:
            return IntegrityCheck(
                name="INT-1.schema_version_present",
                passed=True,
                severity="info",
                message=f"All {len(paths)} partition(s) carry valid schema_version.",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": len(paths)},
            )
        return IntegrityCheck(
            name="INT-1.schema_version_present",
            passed=False,
            severity="critical",
            message=f"{len(offenders)} partition(s) without valid schema_version.",
            evidence={
                "symbol": symbol,
                "exchange": exchange,
                "paths_scanned": len(paths),
                "offenders": offenders[:10],
            },
        )

    # ------------------------------------------------------------------
    # INT-4 — valid price/quantity (INTEGRITY.md §2.4)
    # ------------------------------------------------------------------

    def check_valid_price_quantity(
        self, symbol: str | None = None, *, exchange: str = "F"
    ) -> IntegrityCheck:
        """INT-4: ``price > 0 AND quantity > 0``."""
        paths = self._glob_paths(symbol, exchange=exchange)
        if not paths:
            return IntegrityCheck(
                name="INT-4.valid_price_quantity",
                passed=True,
                severity="info",
                message="No partitions found — vacuous PASS.",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": 0},
            )

        conn = self._connection()
        sql = """
            SELECT COUNT(*) AS bad_rows
            FROM read_parquet(?)
            WHERE price <= 0 OR quantity <= 0 OR price IS NULL OR quantity IS NULL
        """
        result = conn.execute(sql, [paths]).fetchone()
        bad = int(result[0]) if result is not None else 0
        if bad == 0:
            return IntegrityCheck(
                name="INT-4.valid_price_quantity",
                passed=True,
                severity="info",
                message=f"All trades have price>0 and quantity>0 across {len(paths)} partition(s).",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": len(paths)},
            )
        return IntegrityCheck(
            name="INT-4.valid_price_quantity",
            passed=False,
            severity="critical",
            message=f"{bad} trade(s) with invalid price/quantity.",
            evidence={
                "symbol": symbol,
                "exchange": exchange,
                "paths_scanned": len(paths),
                "bad_rows": bad,
            },
        )

    # ------------------------------------------------------------------
    # INT-5 — exchange code valid (INTEGRITY.md §2.5)
    # ------------------------------------------------------------------

    def check_exchange_code_valid(
        self, symbol: str | None = None, *, exchange: str = "F"
    ) -> IntegrityCheck:
        """INT-5: ``exchange ∈ {'F', 'B'}``."""
        paths = self._glob_paths(symbol, exchange=exchange)
        if not paths:
            return IntegrityCheck(
                name="INT-5.exchange_code_valid",
                passed=True,
                severity="info",
                message="No partitions found — vacuous PASS.",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": 0},
            )

        conn = self._connection()
        sql = """
            SELECT DISTINCT exchange
            FROM read_parquet(?)
            WHERE exchange NOT IN ('F', 'B')
        """
        rows = conn.execute(sql, [paths]).fetchall()
        if not rows:
            return IntegrityCheck(
                name="INT-5.exchange_code_valid",
                passed=True,
                severity="info",
                message=f"All exchanges valid across {len(paths)} partition(s).",
                evidence={"symbol": symbol, "exchange": exchange, "paths_scanned": len(paths)},
            )
        invalid = [r[0] for r in rows]
        return IntegrityCheck(
            name="INT-5.exchange_code_valid",
            passed=False,
            severity="critical",
            message=f"Invalid exchange code(s): {invalid!r}.",
            evidence={
                "symbol": symbol,
                "exchange": exchange,
                "paths_scanned": len(paths),
                "invalid_exchanges": invalid,
            },
        )

    # ------------------------------------------------------------------
    # INT-6 — catalog ↔ disk sync (delega Catalog.reconcile)
    # ------------------------------------------------------------------

    def check_catalog_disk_sync(self) -> IntegrityCheck:
        """INT-6: catálogo ↔ filesystem reconciliados (sem drift A/B/C).

        Delega a ``Catalog.reconcile(auto_correct=False)`` (read-only —
        não modifica estado). Drift detectado = FAIL.

        - Drift A (orfão em disco) — severity ``high``
        - Drift B (entry sem arquivo) — severity ``critical``
        - Drift C (checksum diverge) — severity ``critical``
        """
        report = self.catalog.reconcile(auto_correct=False)
        if report.is_clean:
            return IntegrityCheck(
                name="INT-6.catalog_disk_sync",
                passed=True,
                severity="info",
                message="Catalog and filesystem in sync (no drift).",
                evidence={"drift_a": 0, "drift_b": 0, "drift_c": 0},
            )

        # Severity escala com o pior drift presente.
        severity: Severity = "critical" if report.drift_b or report.drift_c else "high"

        return IntegrityCheck(
            name="INT-6.catalog_disk_sync",
            passed=False,
            severity=severity,
            message=(
                f"Catalog drift: A={len(report.drift_a)}, "
                f"B={len(report.drift_b)}, C={len(report.drift_c)}."
            ),
            evidence={
                "drift_a": list(report.drift_a),
                "drift_b": list(report.drift_b),
                "drift_c": list(report.drift_c),
            },
        )

    # ------------------------------------------------------------------
    # Run all
    # ------------------------------------------------------------------

    def run_all(self, symbol: str | None = None, *, exchange: str = "F") -> IntegrityReport:
        """Roda todos os 6 checks; retorna :class:`IntegrityReport`.

        Args:
            symbol: Restringe checagens de Parquet ao símbolo dado. Se
                ``None``, varre todos os símbolos da ``exchange``.
            exchange: ``"F"`` (BMF, default) ou ``"B"`` (Bovespa).

        Returns:
            :class:`IntegrityReport` com todos os checks executados em
            ordem canônica (INT-1, INT-2, INT-3, INT-4, INT-5, INT-6).
        """
        checks = (
            self.check_schema_version_present(symbol, exchange=exchange),
            self.check_no_duplicates(symbol, exchange=exchange),
            self.check_monotonic_timestamps(symbol, exchange=exchange),
            self.check_valid_price_quantity(symbol, exchange=exchange),
            self.check_exchange_code_valid(symbol, exchange=exchange),
            self.check_catalog_disk_sync(),
        )
        overall = all(c.passed for c in checks)
        ran_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Hash canonical: derived from check names + passed flags + ran_at.
        # Não é cripto — apenas referência para audit trail.
        hash_input = "|".join(f"{c.name}={'P' if c.passed else 'F'}" for c in checks) + f"@{ran_at}"
        hash_canonical = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

        return IntegrityReport(
            checks=checks,
            overall_passed=overall,
            dataset_path=str(self.data_dir),
            ran_at=ran_at,
            hash_canonical=hash_canonical,
        )


__all__ = [
    "IntegrityCheck",
    "IntegrityChecker",
    "IntegrityReport",
    "Severity",
]
