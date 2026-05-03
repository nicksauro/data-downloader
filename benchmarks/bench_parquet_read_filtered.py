"""bench_parquet_read_filtered.py — Leitura com filtro WHERE timestamp_ns BETWEEN.

Objetivo:
    Medir trades/s ao fazer SELECT * FROM parquet_scan(...) WHERE timestamp_ns
    BETWEEN X AND Y. Mede impacto de row group pruning + page-level statistics.

Target V1:
    >= 5M trades/s (com pruning efetivo em row groups).

Hipóteses a testar:
    H1: row_group_size=100k é Pareto-ótimo (menor que 100k = overhead, maior
        = pruning menos seletivo) — validar contra bench_parquet_read.
    H2: write_statistics=True (default) é essencial; sem stats, pruning não
        funciona e benchmark cai para nível de full scan.
    H3: Filtro que cobre 1% dos trades roda ~100x faster que full scan
        (se pruning funciona).
    H4: Filtro que cobre 50% dos trades NÃO se beneficia de pruning
        (page-level skipping marginal).

Cenários:
    - filter_1pct: range cobre 1% dos trades (best case pruning)
    - filter_10pct: range cobre 10% dos trades
    - filter_50pct: range cobre 50% dos trades (pruning marginal)
    - filter_99pct: range cobre 99% (~ full scan)

Output:
    benchmarks/results/bench_parquet_read_filtered-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_parquet_read_filtered",
        "config_matrix": [
            {"row_group_size": ..., "filter_selectivity": "1pct",
             "trades_per_sec": ..., "trades_scanned": ...,
             "trades_returned": ..., "pruning_ratio": ...}
        ]
    }
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

# TODO: imports reais
# import duckdb
# import pyarrow.parquet as pq

RESULTS_DIR = Path(__file__).parent / "results"
N_TRADES_TOTAL = 10_000_000
N_RUNS_PER_CONFIG = 5
TARGET_TRADES_PER_SEC = 5_000_000

ROW_GROUP_SIZES = [10_000, 100_000, 500_000, 1_000_000]
FILTER_SELECTIVITIES = {
    "1pct": 0.01,
    "10pct": 0.10,
    "50pct": 0.50,
    "99pct": 0.99,
}


def setup_parquet_files(row_group_size: int, tmp_dir: Path) -> tuple[list[Path], int, int]:
    """Gera 10M trades; retorna (files, ts_min, ts_max)."""
    # TODO: gerar via fixtures.synthetic_trades, retornar range temporal
    raise NotImplementedError("Aguarda fixtures.synthetic_trades")


def compute_filter_range(ts_min: int, ts_max: int, selectivity: float) -> tuple[int, int]:
    """Retorna (lo, hi) que selecionam ~selectivity dos trades, centrados."""
    span = ts_max - ts_min
    width = int(span * selectivity)
    mid = (ts_min + ts_max) // 2
    return mid - width // 2, mid + width // 2


def measure_filtered_scan(
    parquet_files: list[Path], ts_lo: int, ts_hi: int
) -> dict[str, Any]:
    """SELECT com WHERE timestamp_ns BETWEEN; mede trades/s e pruning."""
    # TODO:
    # con = duckdb.connect(":memory:", config={"threads": 1})
    # glob = str(parquet_files[0].parent / "*.parquet")
    # t0 = time.perf_counter_ns()
    # result = con.execute(
    #     f"SELECT COUNT(*) FROM parquet_scan('{glob}') "
    #     f"WHERE timestamp_ns BETWEEN {ts_lo} AND {ts_hi}"
    # ).fetchone()
    # elapsed_ns = time.perf_counter_ns() - t0
    # # Para pruning_ratio: contar row groups efetivamente lidos via EXPLAIN ANALYZE
    # ...
    raise NotImplementedError("Aguarda código de produção (Story 1.5)")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO: rodar matriz row_group_size × selectivity, salvar JSON
    raise NotImplementedError(
        "bench_parquet_read_filtered é esqueleto sintético (Story 1.4.5)."
    )


if __name__ == "__main__":
    main()
