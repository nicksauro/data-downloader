"""data_downloader.storage.duckdb_reader — Leitura via DuckDB.

Owner: Sol (queries) | Impl: Dex.
Refs:

- ``docs/storage/QUERIES.md`` (read_history canônico)
- ``docs/adr/ADR-002-storage-stack.md`` (DuckDB engine)
- ``docs/adr/ADR-004-partition-layout.md`` (glob pattern)

Conexão DuckDB persistente (lazy init) para amortizar overhead de
``connect`` em queries repetidas. Reader é stateful — usar como context
manager ou chamar ``.close()`` explicitamente.

Pruning: DuckDB faz row group pruning quando o filtro é em coluna
ordenada (``timestamp_ns`` é monotônico dentro da partição). Sempre
incluir ``WHERE timestamp_ns BETWEEN ? AND ?`` (QUERIES.md §5.1).
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

import duckdb
import pyarrow as pa

from data_downloader.storage.schema import pyarrow_schema


@dataclass
class DuckDBReader:
    """Reader DuckDB sobre Parquet particionado.

    Args:
        data_dir: Raiz dos dados (mesmo valor do writer).

    Use como context manager para garantir close::

        with DuckDBReader(Path("data")) as reader:
            table = reader.read("WDOJ26", start_ns, end_ns)
    """

    data_dir: Path
    _conn: duckdb.DuckDBPyConnection | None = field(default=None, init=False, repr=False)

    def _connection(self) -> duckdb.DuckDBPyConnection:
        """Lazy init da conexão in-memory."""
        if self._conn is None:
            self._conn = duckdb.connect(":memory:")
        return self._conn

    def _glob_pattern(self, symbol: str, exchange: str) -> str:
        """Constrói o glob ADR-004 para uma combinação ``(exchange, symbol)``."""
        return str(self.data_dir / "history" / exchange / symbol / "**" / "*.parquet")

    def _resolved_paths(self, symbol: str, exchange: str) -> list[str]:
        """Resolve glob para paths concretos existentes (vazio se nada)."""
        pattern = self._glob_pattern(symbol, exchange)
        return sorted(glob.glob(pattern, recursive=True))

    def read(
        self,
        symbol: str,
        start_ts_ns: int,
        end_ts_ns: int,
        *,
        exchange: str = "F",
    ) -> pa.Table:
        """Lê trades de um símbolo no intervalo ``[start_ts_ns, end_ts_ns]``.

        Args:
            symbol: Código exato do contrato (ex.: ``"WDOJ26"``).
            start_ts_ns: Lower bound (inclusivo) em nanos epoch BRT NAIVE.
            end_ts_ns: Upper bound (inclusivo) em nanos epoch BRT NAIVE.
            exchange: ``"F"`` (BMF, default) ou ``"B"`` (Bovespa).

        Returns:
            ``pa.Table`` ordenada por ``timestamp_ns ASC``. Vazia se
            nenhum trade no intervalo OU nenhuma partição existe (não
            levanta).
        """
        paths = self._resolved_paths(symbol, exchange)
        if not paths:
            return pyarrow_schema().empty_table()

        conn = self._connection()
        sql = (
            "SELECT * FROM read_parquet(?) "
            "WHERE timestamp_ns BETWEEN ? AND ? "
            "ORDER BY timestamp_ns ASC"
        )
        arrow_obj = conn.execute(sql, [paths, start_ts_ns, end_ts_ns]).arrow()
        # DuckDB pode retornar pa.Table OU pa.RecordBatchReader dependendo
        # da versão; normalizamos para pa.Table.
        if isinstance(arrow_obj, pa.Table):
            return arrow_obj
        return arrow_obj.read_all()

    def count(self, symbol: str, *, exchange: str = "F") -> int:
        """Conta trades persistidos para ``(symbol, exchange)``.

        Args:
            symbol: Código exato do contrato.
            exchange: ``"F"`` (default) ou ``"B"``.

        Returns:
            Total de linhas. ``0`` se nenhuma partição existe.
        """
        paths = self._resolved_paths(symbol, exchange)
        if not paths:
            return 0

        conn = self._connection()
        result = conn.execute("SELECT COUNT(*) FROM read_parquet(?)", [paths]).fetchone()
        if result is None:
            return 0
        return int(result[0])

    def close(self) -> None:
        """Fecha a conexão DuckDB. Idempotente."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> DuckDBReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


__all__ = ["DuckDBReader"]
