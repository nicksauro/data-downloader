"""Migrations de catálogo SQLite (DDL .sql).

Arquivos ``.sql`` nomeados conforme regex
``v\\d+_\\d+_\\d+_to_v\\d+_\\d+_\\d+\\.sql``. Carregados pelo
``MigrationRunner`` apenas quando há mudança real no DDL do catálogo
(o catálogo já tem seu próprio sistema de migrations versionadas em
``catalog.MIGRATIONS`` — ver Story 1.5).
"""

from __future__ import annotations

__all__: list[str] = []
