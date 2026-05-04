"""Migration: schema Parquet v1.0.0 -> v1.1.0 (ADITIVA — Story 2.3 AC8).

Owner: Sol (schema/policy) | Impl: Dex.
Refs:

- ``docs/storage/SCHEMA.md`` §6 (política R4 — aditivo = bump minor)
- ``docs/storage/MIGRATIONS.md`` §2.2 (esqueleto de exemplo)
- Story 2.3 AC8 (migration aditiva exemplo: liquidity_classification)

## Mudança

Adiciona campo ``liquidity_classification: uint8 nullable`` ao schema
v1.0.0 (17 campos) → v1.1.0 (18 campos).

Semântica do campo: classificação de liquidez do trade (futuro Epic 4
multi-asset; em v1.1.0 todos os valores são NULL — placeholder para
backfill posterior). NULL preserva a invariante R4 (leitor v1.0.0 lendo
arquivo v1.1.0 ignora a coluna nova).

## Garantias

- Campos existentes preservados byte-a-byte (verify via property test).
- Nova coluna sempre NULL no migrate (sem invenção de dados).
- Idempotência: rodar migration duas vezes detecta schema_version já
  v1.1.0 (via ``applies_to``) e skip.
- Rollback suportado: drop coluna nova restaura schema v1.0.0.
"""

from __future__ import annotations

from typing import ClassVar

import pyarrow as pa

from data_downloader.storage.migrations._base import ParquetMigration


class V100ToV110(ParquetMigration):
    """Aditivo v1.0.0 -> v1.1.0: campo ``liquidity_classification`` (uint8 nullable).

    Migration concreta de exemplo + teste real do framework. Serve de
    referência para futuras migrations aditivas.
    """

    from_version: ClassVar[str] = "1.0.0"
    to_version: ClassVar[str] = "1.1.0"
    breaking: ClassVar[bool] = False
    description: ClassVar[str] = (
        "Aditivo: campo liquidity_classification (uint8 nullable) — "
        "placeholder para Epic 4 multi-asset."
    )
    rollback_supported: ClassVar[bool] = True

    # Nome canônico da nova coluna (constante para reuso em testes/verify).
    NEW_FIELD_NAME: ClassVar[str] = "liquidity_classification"

    def transform(self, table: pa.Table) -> pa.Table:
        """Adiciona ``liquidity_classification`` (uint8 NULL) preservando todos os campos.

        Idempotência: se coluna já existe, retorna table sem mudança.
        """
        if self.NEW_FIELD_NAME in table.schema.names:
            return table

        new_col = pa.array([None] * table.num_rows, type=pa.uint8())
        return table.append_column(
            pa.field(self.NEW_FIELD_NAME, pa.uint8(), nullable=True),
            new_col,
        )

    def verify(self, src_old: object, dst_new: object) -> bool:
        """Pós-check: arquivo dst_new tem o campo novo + tipo correto.

        Override do default (``ParquetMigration.verify`` checa apenas
        schema_version metadata) — adiciona check estrutural do campo.
        """
        # Reusa o default primeiro (schema_version metadata = '1.1.0').
        from pathlib import Path

        import pyarrow.parquet as pq

        src_path = Path(str(src_old))
        dst_path = Path(str(dst_new))

        base_ok = super().verify(src_path, dst_path)
        if not base_ok:
            return False

        try:
            schema = pq.read_schema(dst_path)
        except (OSError, ValueError):
            return False

        if self.NEW_FIELD_NAME not in schema.names:
            return False
        field = schema.field(self.NEW_FIELD_NAME)
        if not pa.types.is_uint8(field.type):
            return False
        return bool(field.nullable)


__all__ = ["V100ToV110"]
