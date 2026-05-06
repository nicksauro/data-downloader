"""Migration: schema Parquet v1.0.0 -> v1.1.0 (ADITIVA — Nelo Council 32 P0).

Owner: Sol (schema/policy) | Impl: Dex.
Refs:

- ``docs/storage/SCHEMA.md`` v1.1.0 §1.1 (20 campos canônicos)
- ``docs/storage/SCHEMA.md`` §6 (política R4 — aditivo = bump minor)
- ``docs/storage/MIGRATIONS.md`` §6 (registry table)
- Story 1.7g (Nelo Council 32 release blocker P0 — schema integrity)
- Owners Council 2026-05-05 (Sol+Pax veredito P0 fix do bug B1)

## Mudança

Adiciona 3 campos ``string`` nullable ao schema v1.0.0 (17 campos) →
v1.1.0 (20 campos):

- ``buy_agent_name``  (string, nullable)
- ``sell_agent_name`` (string, nullable)
- ``trade_type_name`` (string, nullable)

Semântica: ``buy_agent_name`` / ``sell_agent_name`` são nomes humanos
das corretoras compradora/vendedora (``DLL.GetAgentName(nAgent)``).
``trade_type_name`` é o nome humano do enum ``TConnectorTradeType``
(L33-L46 ``LegacyProfitDataTypesU.pas``). Em v1.0.0 o pipeline em
memória já populava esses campos mas o writer (17-coluna) os
descartava silenciosamente — Story 1.7g restaurou a integridade.

## Fallback determinístico (sem perda de dados)

Para parquets v1.0.0 reais (já gravados em disco sem o pipeline
v1.1.0), não temos como reconstruir os nomes "verdadeiros" do
``AgentResolver`` retroativamente — a DLL pode ter restartado e o
mapping local pode ter mudado. Usamos um fallback DETERMINÍSTICO
(sem invenção, R4):

- ``buy_agent_name``  := ``f"Agent#{buy_agent_id}"`` se ``buy_agent_id`` não-null;
                        ``None`` caso contrário (campo era nullable em v1.0.0).
- ``sell_agent_name`` := ``f"Agent#{sell_agent_id}"`` (mesma regra).
- ``trade_type_name`` := ``TRADE_TYPE_NAME[trade_type]`` se id em 0..13;
                        ``f"TradeType#{trade_type}"`` caso contrário.

Não-invenção (Article IV): nenhum nome resolvido é "fabricado"; o
formato ``Agent#{id}`` / ``TradeType#{n}`` é uma chave determinística
que aponta de volta ao id original — análise downstream consegue
identificar inequivocamente que o nome veio do fallback.

## Garantias

- Campos existentes preservados byte-a-byte (property test).
- Nenhum dado v1.0.0 é descartado.
- Idempotência: rodar 2x produz schema/dados idênticos
  (skip se schema target já presente).
- Rollback suportado: drop das 3 colunas restaura schema v1.0.0.
- Schema do output bate exatamente com ``pyarrow_schema()`` v1.1.0
  (ordem de colunas + tipos + nullability).
"""

from __future__ import annotations

from typing import ClassVar

import pyarrow as pa
import pyarrow.compute as pc

from data_downloader.storage.migrations._base import ParquetMigration
from data_downloader.storage.schema import TRADE_TYPE_NAME, pyarrow_schema


class V100ToV110(ParquetMigration):
    """Aditivo v1.0.0 → v1.1.0: 3 campos resolvidos (``buy_agent_name``,
    ``sell_agent_name``, ``trade_type_name``).

    Migration concreta P0 (Nelo Council 32 / Owners Council 2026-05-05).
    Substitui versão errada anterior (``liquidity_classification``, que
    era exemplo da Story 2.3 e não correspondia ao schema v1.1.0 real).
    """

    from_version: ClassVar[str] = "1.0.0"
    to_version: ClassVar[str] = "1.1.0"
    breaking: ClassVar[bool] = False
    description: ClassVar[str] = (
        "Aditivo: campos buy_agent_name/sell_agent_name/trade_type_name "
        "(string nullable) — Nelo Council 32 P0 schema integrity."
    )
    rollback_supported: ClassVar[bool] = True

    # Nomes canônicos das 3 colunas adicionadas (constantes para reuso em tests).
    NEW_FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "buy_agent_name",
        "sell_agent_name",
        "trade_type_name",
    )

    def transform(self, table: pa.Table) -> pa.Table:
        """Adiciona 3 campos resolvidos via fallback determinístico.

        Pipeline:

        1. Idempotência: se as 3 colunas já existem, retorna schema canônico
           v1.1.0 (re-cast para preservar ordem/tipos exatos).
        2. Constrói ``buy_agent_name`` / ``sell_agent_name`` via fallback
           ``f"Agent#{id}"`` (None onde id é null).
        3. Constrói ``trade_type_name`` via lookup em ``TRADE_TYPE_NAME``
           (fallback ``f"TradeType#{n}"`` para ids fora 0..13).
        4. Re-arranja para schema canônico v1.1.0 (ordem definida em
           ``pyarrow_schema()``).
        """
        target_schema = pyarrow_schema()

        # Idempotência: se as 3 já existem, só re-cast para schema canônico.
        existing_names = set(table.schema.names)
        if all(name in existing_names for name in self.NEW_FIELD_NAMES):
            return self._cast_to_canonical(table, target_schema)

        n = table.num_rows

        # ----- buy_agent_name -----
        if "buy_agent_name" not in existing_names:
            buy_agent_name = self._build_agent_name_column(table, "buy_agent_id", n)
            table = table.append_column(
                pa.field("buy_agent_name", pa.string(), nullable=True),
                buy_agent_name,
            )

        # ----- sell_agent_name -----
        if "sell_agent_name" not in existing_names:
            sell_agent_name = self._build_agent_name_column(table, "sell_agent_id", n)
            table = table.append_column(
                pa.field("sell_agent_name", pa.string(), nullable=True),
                sell_agent_name,
            )

        # ----- trade_type_name -----
        if "trade_type_name" not in existing_names:
            trade_type_name = self._build_trade_type_name_column(table, n)
            table = table.append_column(
                pa.field("trade_type_name", pa.string(), nullable=True),
                trade_type_name,
            )

        return self._cast_to_canonical(table, target_schema)

    @staticmethod
    def _build_agent_name_column(
        table: pa.Table,
        agent_id_field: str,
        n: int,
    ) -> pa.Array:
        """Constrói ``f"Agent#{id}"`` (None onde ``agent_id`` é null).

        Args:
            table: Tabela v1.0.0 (deve ter ``agent_id_field``).
            agent_id_field: Nome da coluna source (``buy_agent_id`` /
                ``sell_agent_id``).
            n: ``table.num_rows`` (cached).

        Returns:
            ``pa.Array`` (string, nullable) com fallback aplicado.
        """
        if n == 0:
            return pa.array([], type=pa.string())

        # Materializa em pylist — agent_id é int32 nullable; n é tipicamente
        # <100k em uma partição mensal, custo aceitável para migration única.
        ids = table.column(agent_id_field).to_pylist()
        names: list[str | None] = [None if i is None else f"Agent#{int(i)}" for i in ids]
        return pa.array(names, type=pa.string())

    @staticmethod
    def _build_trade_type_name_column(table: pa.Table, n: int) -> pa.Array:
        """Constrói nome humano de ``trade_type`` via ``TRADE_TYPE_NAME``.

        Fallback: ``f"TradeType#{n}"`` para ids fora de 0..13. Em v1.0.0,
        ``trade_type`` é uint8 NOT NULL — sempre tem valor.
        """
        if n == 0:
            return pa.array([], type=pa.string())

        types = table.column("trade_type").to_pylist()
        names: list[str | None] = []
        for t in types:
            if t is None:
                # Defensive: schema v1.0.0 tinha trade_type NOT NULL,
                # mas se algum arquivo legacy tem null, propagate.
                names.append(None)
                continue
            t_int = int(t)
            mapped = TRADE_TYPE_NAME.get(t_int)
            names.append(mapped if mapped is not None else f"TradeType#{t_int}")
        return pa.array(names, type=pa.string())

    @staticmethod
    def _cast_to_canonical(table: pa.Table, target_schema: pa.Schema) -> pa.Table:
        """Re-arranja colunas para a ordem/tipo do schema canônico v1.1.0.

        Garante ``result.schema.equals(target_schema)`` mesmo que o input
        tenha colunas em ordem diferente ou tipos próximos (ex.: int64 vs
        int32 no agent_id). Preserva os dados via ``cast``.
        """
        existing = {name: table.column(name) for name in table.schema.names}
        arrays: list[pa.Array | pa.ChunkedArray] = []
        for f in target_schema:
            col = existing.get(f.name)
            if col is None:
                # Não deve acontecer pós-transform, mas defensive: NULL.
                if not f.nullable:
                    raise ValueError(
                        f"Migration v1.0.0 -> v1.1.0: NOT NULL field "
                        f"{f.name!r} ausente no input — arquivo corrupto?"
                    )
                arrays.append(pa.nulls(table.num_rows, type=f.type))
            else:
                # Cast preserva dados; raises se conversão impossível.
                arrays.append(pc.cast(col, f.type))
        return pa.Table.from_arrays(arrays, schema=target_schema)

    def verify(self, src_old: object, dst_new: object) -> bool:
        """Pós-check: arquivo dst_new tem os 3 campos novos + schema_version.

        Estende o default (``ParquetMigration.verify`` checa
        ``schema_version`` metadata) com check estrutural dos 3 campos.
        """
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

        for name in self.NEW_FIELD_NAMES:
            if name not in schema.names:
                return False
            field = schema.field(name)
            if not pa.types.is_string(field.type):
                return False
            if not field.nullable:
                return False
        return True


__all__ = ["V100ToV110"]
