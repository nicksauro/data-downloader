"""synthetic_trades.py — Gerador de trades sintéticos realistas.

Objetivo:
    Gerar trades sintéticos que imitam características estatísticas reais de
    WDO (mini dólar) na B3, para benchmarks rodarem SEM ProfitDLL real.

Características modeladas:
    - Preço: random walk em torno de 5000 (preço típico WDO), volatility ~0.1%
      por tick, com clusters de movimento (não passeio aleatório puro).
    - Quantidade: distribuição skewed, mediana ~5, p99 ~100, outliers até 500.
    - Timestamp: monotonic increasing com jitter (rate ~1kHz médio, picos
      ~4kHz na abertura).
    - trade_id: monotonic increasing (mas com gaps simulando reconnect).
    - sequence_within_ns: 0-N para trades no mesmo ns (modela H2 finding —
      múltiplos trades no mesmo timestamp_ns).

Schema produzido (alinhar com Sol Story 0.0):
    {
        "trade_id": int | None,         # None se Quirk DLL trade_id NULL
        "timestamp_ns": int,            # ns since epoch
        "sequence_within_ns": int,      # 0..N para mesma ts
        "symbol": str,
        "price": float,
        "quantity": int,
        "side": str | None,             # "buy"|"sell"|None
        "ingestion_ts_ns": int,         # ns when generated (mock = same as ts)
        "chunk_id": str | None,         # populado pelo writer
        "dll_version": str,             # mock value
    }

Uso:
    from benchmarks.fixtures.synthetic_trades import generate
    for trade in generate(n=10_000_000, symbol="WDOJ26"):
        process(trade)
"""

from __future__ import annotations

import random  # noqa: F401  # used by commented-out skeleton body
import time  # noqa: F401  # used by commented-out skeleton body
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    import pyarrow as pa


# TODO: alinhar schema final com Sol Story 0.0 — campos podem mudar
DEFAULT_PRICE_BASE = 5000.0
DEFAULT_VOLATILITY_PER_TICK = 0.0001  # 0.01% por tick (random walk)
DEFAULT_MEAN_RATE_HZ = 1000.0
DEFAULT_PEAK_RATE_HZ = 4000.0
MOCK_DLL_VERSION = "4.0.0.30-mock"


def generate(
    n: int,
    symbol: str = "WDOJ26",
    start_ts_ns: int | None = None,
    *,
    seed: int | None = 42,
    price_base: float = DEFAULT_PRICE_BASE,
    rate_profile: str = "constant",  # "constant" | "realistic_b3"
    null_trade_id_pct: float = 0.0,  # simular Quirk DLL
    multi_trade_per_ns_pct: float = 0.05,  # 5% dos trades partilham ns
) -> Iterator[dict]:
    """Gera N trades sintéticos.

    Args:
        n: número de trades a gerar.
        symbol: ticker.
        start_ts_ns: timestamp inicial (default: now).
        seed: random seed (None = não-determinístico).
        price_base: preço inicial.
        rate_profile: "constant" (taxa fixa) ou "realistic_b3" (rampup
            abertura, plateau, queda fechamento).
        null_trade_id_pct: 0.0-1.0 — fração com trade_id=None (testa Quirk).
        multi_trade_per_ns_pct: fração de trades com sequence_within_ns > 0.

    Yields:
        dict no schema canônico (ver docstring do módulo).
    """
    # TODO: implementar quando schema final estiver definido por Sol
    # rng = random.Random(seed)
    # if start_ts_ns is None:
    #     start_ts_ns = time.time_ns()
    #
    # current_price = price_base
    # current_ts = start_ts_ns
    # last_ts = current_ts
    # seq_in_ns = 0
    #
    # for trade_id_seq in range(n):
    #     # Random walk price
    #     change_pct = rng.gauss(0, DEFAULT_VOLATILITY_PER_TICK)
    #     current_price *= (1 + change_pct)
    #     # Round para tick mínimo 0.5 (WDO)
    #     current_price = round(current_price * 2) / 2
    #
    #     # Quantity skewed
    #     quantity = max(1, int(rng.lognormvariate(1.5, 1.0)))
    #     quantity = min(quantity, 500)
    #
    #     # Timestamp jitter
    #     if rate_profile == "constant":
    #         interval_ns = int(1e9 / DEFAULT_MEAN_RATE_HZ)
    #     else:  # realistic_b3
    #         # rate varia conforme posição em janela 9h-17h
    #         pos = trade_id_seq / n
    #         if pos < 0.05:  # rampup
    #             rate = DEFAULT_MEAN_RATE_HZ + (DEFAULT_PEAK_RATE_HZ - DEFAULT_MEAN_RATE_HZ) * (pos / 0.05)
    #         elif pos > 0.95:  # queda fechamento
    #             rate = DEFAULT_MEAN_RATE_HZ * (1 - (pos - 0.95) / 0.05)
    #         else:
    #             rate = DEFAULT_MEAN_RATE_HZ
    #         interval_ns = int(1e9 / max(rate, 1))
    #
    #     # Multi trade per ns
    #     if rng.random() < multi_trade_per_ns_pct:
    #         current_ts = last_ts  # mesmo ns
    #         seq_in_ns += 1
    #     else:
    #         current_ts += interval_ns
    #         last_ts = current_ts
    #         seq_in_ns = 0
    #
    #     trade_id = None if rng.random() < null_trade_id_pct else trade_id_seq
    #     side = rng.choice(["buy", "sell"]) if rng.random() > 0.05 else None
    #
    #     yield {
    #         "trade_id": trade_id,
    #         "timestamp_ns": current_ts,
    #         "sequence_within_ns": seq_in_ns,
    #         "symbol": symbol,
    #         "price": current_price,
    #         "quantity": quantity,
    #         "side": side,
    #         "ingestion_ts_ns": current_ts,
    #         "chunk_id": None,
    #         "dll_version": MOCK_DLL_VERSION,
    #     }
    raise NotImplementedError(
        "synthetic_trades.generate aguarda confirmação de schema final "
        "por Sol (Story 0.0). Esqueleto pronto, código comentado acima."
    )


def generate_batch_arrow(n: int, **kwargs) -> "pa.Table":  # type: ignore
    """Versão batch otimizada que retorna pa.Table direto (sem pylist intermediário)."""
    # TODO: implementar versão vectorized via numpy + pa.array para
    # benchmarks que precisam de 10M+ trades sem overhead de pyloop
    raise NotImplementedError("Versão arrow-batch — implementar quando necessária")
