"""Helper do run_smoke_real.ps1 — conta chunks/dias distintos nos parquets baixados.

Uso: ``python tests/smoke/_count_chunks.py <data_dir> [symbol]``

Saída (uma linha, key=value): ``rows=<N> chunks=<C> days=<D> files=<F> range=<min>..<max>``
Exit 0 sempre (a interpretação fica no .ps1); exit 2 se nenhum parquet for achado.

Por que não contar arquivos no .ps1: o schema particiona parquets por ANO/MÊS
(``history/F/WDOFUT/2026/05.parquet``), então N dias úteis do mesmo mês viram
1 arquivo. A política ADR-023 (1 chunk = 1 dia útil) é validada pelo nº de
``chunk_id`` distintos (= nº de chunks emitidos) e/ou dias-calendário distintos
nos timestamps — não pelo nº de arquivos no disco.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: _count_chunks.py <data_dir> [symbol]", file=sys.stderr)
        return 2
    data_dir = Path(sys.argv[1])
    symbol = sys.argv[2] if len(sys.argv) > 2 else None

    history = data_dir / "history"
    pattern = "**/*.parquet"
    files = sorted(history.glob(pattern)) if history.exists() else []
    if symbol:
        files = [f for f in files if symbol.upper() in str(f).upper()]
    if not files:
        print(f"rows=0 chunks=0 days=0 files=0 range=none (no parquet under {history})")
        return 2

    glob_arg = str(history / pattern).replace("\\", "/")
    con = duckdb.connect()
    rel = f"read_parquet('{glob_arg}', union_by_name=true)"
    if symbol:
        rel = f"(SELECT * FROM {rel} WHERE upper(symbol) = '{symbol.upper()}')"

    rows = con.sql(f"SELECT COUNT(*) FROM {rel}").fetchone()[0]
    chunks = con.sql(f"SELECT COUNT(DISTINCT chunk_id) FROM {rel}").fetchone()[0]
    days = con.sql(
        f"SELECT COUNT(DISTINCT CAST(to_timestamp(timestamp_ns/1e9) AS DATE)) FROM {rel}"
    ).fetchone()[0]
    rng = con.sql(
        f"SELECT MIN(CAST(to_timestamp(timestamp_ns/1e9) AS DATE)), "
        f"MAX(CAST(to_timestamp(timestamp_ns/1e9) AS DATE)) FROM {rel}"
    ).fetchone()
    print(f"rows={rows} chunks={chunks} days={days} files={len(files)} range={rng[0]}..{rng[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
