"""Property test — round-trip preservation por compression (Story 2.8 AC6).

Owner: Sol (storage-engineer) + Pyro (perf-engineer) — COUNCIL-21.
Refs: ``docs/stories/2.8.story.md`` AC6 (round-trip por compression).

Property:

    read(write(table, compression=X)) == table

para X em ``{snappy, zstd-1, zstd-3, none}``. Garante que mudança
hipotética futura de compression default (em qualquer cell da Pareto
matrix) NÃO violaria preservação de dado on-disk.

Sol princípio: compression é metadata reversível por arquivo Parquet
(não toca schema). Mas Sol exige PROVA, não confiança — Hypothesis
gera tabelas variadas e valida cada round-trip byte-equivalente.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

COMPRESSION_VARIANTS: list[dict[str, Any]] = [
    {"compression": "snappy"},
    {"compression": "zstd", "compression_level": 1},
    {"compression": "zstd", "compression_level": 3},
    {"compression": None},  # uncompressed
]


def _make_table(n_rows: int, base_ts: int) -> pa.Table:
    """Tabela determinística com schema mínimo (5 colunas, exercitando dict + ints + floats)."""
    return pa.table(
        {
            "symbol": pa.array(["WDOJ26"] * n_rows, type=pa.string()),
            "timestamp_ns": pa.array(
                [base_ts + i * 1_000_000 for i in range(n_rows)], type=pa.int64()
            ),
            "price": pa.array([5000.0 + (i % 100) * 0.5 for i in range(n_rows)], type=pa.float64()),
            "quantity": pa.array([1 + (i % 10) for i in range(n_rows)], type=pa.int64()),
            "trade_id": pa.array(
                [i if i % 5 != 0 else None for i in range(n_rows)], type=pa.int64()
            ),
        }
    )


def _round_trip_equals(table: pa.Table, cfg: dict[str, Any], path: Path) -> bool:
    """Escreve com `cfg`, lê de volta, retorna True se idêntico."""
    pq.write_table(
        table,
        path,
        compression=cfg["compression"],
        compression_level=cfg.get("compression_level"),
        use_dictionary=True,
        write_statistics=True,
    )
    read_back = pq.read_table(path)
    return table.equals(read_back)


def _cfg_id(c: dict[str, Any]) -> str:
    return f"{c['compression'] or 'none'}-{c.get('compression_level', '')}"


@pytest.mark.property
@pytest.mark.parametrize("cfg", COMPRESSION_VARIANTS, ids=_cfg_id)
@given(
    n_rows=st.integers(min_value=1, max_value=500),
    base_ts=st.integers(min_value=1_000_000_000_000_000_000, max_value=2_000_000_000_000_000_000),
)
@settings(
    max_examples=25,  # 25 examples x 4 compressions = 100 round-trips
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_round_trip_preservation_by_compression(
    cfg: dict[str, Any], n_rows: int, base_ts: int, tmp_path: Path
) -> None:
    """Property — `read(write(table, compression=X)) == table`.

    Para cada variante de compression, gera tabela aleatória (n_rows ∈
    [1, 500]; base_ts ∈ janela int64 segura) e valida byte-equivalência
    via ``pa.Table.equals``.
    """
    table = _make_table(n_rows, base_ts)
    out_path = tmp_path / "round_trip.parquet"
    assert _round_trip_equals(table, cfg, out_path), (
        f"round-trip falhou para compression={cfg['compression']} "
        f"level={cfg.get('compression_level')} n_rows={n_rows}"
    )


@pytest.mark.property
@pytest.mark.parametrize("cfg", COMPRESSION_VARIANTS)
def test_round_trip_preservation_empty_table(cfg: dict[str, Any], tmp_path: Path) -> None:
    """Edge case — tabela vazia também round-trips para todas compressions."""
    table = _make_table(0, 1_700_000_000_000_000_000)
    out_path = tmp_path / f"empty_{cfg['compression'] or 'none'}.parquet"
    assert _round_trip_equals(
        table, cfg, out_path
    ), f"empty round-trip falhou para compression={cfg['compression']}"


@pytest.mark.property
@pytest.mark.parametrize("cfg", COMPRESSION_VARIANTS)
def test_compression_preserves_metadata_and_schema(cfg: dict[str, Any], tmp_path: Path) -> None:
    """Schema (campos, types, nullability) preservado em round-trip por compression."""
    table = _make_table(100, 1_700_000_000_000_000_000)
    out_path = tmp_path / f"schema_{cfg['compression'] or 'none'}.parquet"
    pq.write_table(
        table,
        out_path,
        compression=cfg["compression"],
        compression_level=cfg.get("compression_level"),
        use_dictionary=True,
        write_statistics=True,
    )
    read_back = pq.read_table(out_path)
    # Schema (field names + types) preservado.
    assert table.schema.names == read_back.schema.names
    for orig_field, read_field in zip(table.schema, read_back.schema, strict=True):
        assert orig_field.name == read_field.name
        assert orig_field.type == read_field.type
