"""data_downloader.storage — Camada de persistência (Parquet + DuckDB + SQLite).

Owner: Sol (schema/policy) | Impl: Dex (com audit Sol).

Responsabilidades:

- ``parquet_writer.py`` — escrita atômica conforme SCHEMA.md §1 (17 campos v1.0.0).
- ``duckdb_reader.py``  — query layer sobre Parquet particionado.
- ``catalog.py``        — SQLite (downloads, partitions, gaps, contracts).
- ``dedup.py``          — anti-join via DuckDB (SCHEMA.md §2).

Schema canônico: ``docs/storage/SCHEMA.md`` (v1.0.0). Mudança de schema =
consultar Sol (R4 — política de migração formal).
"""

from __future__ import annotations

__all__: list[str] = []
