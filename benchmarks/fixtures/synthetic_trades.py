"""synthetic_trades.py — Gerador de trades sintéticos realistas.

Objetivo:
    Gerar trades sintéticos que imitam características estatísticas reais de
    WDO (mini dólar) na B3, para benchmarks rodarem SEM ProfitDLL real.

Características modeladas:
    - Preço: random walk em torno de 5000 (preço típico WDO), variação ±2%
      total em janelas curtas, com tick mínimo 0.5.
    - Quantidade: distribuição long-tail; maioria 1-5, p99 ~50, máx 100.
    - Timestamp: monotônico crescente com jitter (média ~1ms entre trades).
    - trade_id: monotônico crescente; 10% NULL (Quirk Q01-V — força chave longa).
    - 1% trades duplicados intencionalmente (testa dedup).
    - sequence_within_ns: 0 inicial — writer/dedup atribui via
      assign_sequence_within_ns. Aqui yieldamos 0 default.

Schema produzido: dict-shape compatível com
``data_downloader.storage.schema.TradeRecord`` (17 campos) — ver
:func:`pyarrow_schema()`.

Uso:
    from benchmarks.fixtures.synthetic_trades import generate
    trades = list(generate(1_000_000, symbol="WDOJ26"))
    # ou em lote vectorizado:
    table = generate_batch_arrow(1_000_000, symbol="WDOJ26")
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa


# Defaults realistas para WDO (mini dólar B3).
DEFAULT_PRICE_BASE = 5000.0
DEFAULT_TICK_SIZE = 0.5  # WDO tick mínimo
DEFAULT_VOLATILITY_PER_TICK = 0.0001  # 0.01% por trade (random walk)
DEFAULT_INTERVAL_NS = 1_000_000  # 1ms médio entre trades
MOCK_DLL_VERSION = "4.0.0.30-mock"

# Default Quirk Q01-V (callback V1 — sem trade_id).
DEFAULT_NULL_TRADE_ID_PCT = 0.10
# Default duplicates intencional para validar dedup.
DEFAULT_DUPLICATE_PCT = 0.01


def _round_to_tick(price: float, tick: float = DEFAULT_TICK_SIZE) -> float:
    """Arredonda preço para múltiplo do tick (WDO = 0.5)."""
    return round(price / tick) * tick


def generate(
    n: int,
    symbol: str = "WDOJ26",
    start_ts_ns: int | None = None,
    *,
    seed: int | None = 42,
    price_base: float = DEFAULT_PRICE_BASE,
    null_trade_id_pct: float = DEFAULT_NULL_TRADE_ID_PCT,
    duplicate_pct: float = DEFAULT_DUPLICATE_PCT,
    exchange: str = "F",
) -> Iterator[dict]:
    """Gera N trades sintéticos.

    Args:
        n: número de trades a gerar.
        symbol: ticker (default WDOJ26).
        start_ts_ns: timestamp inicial (default: ``time.time_ns()``).
        seed: random seed (None = não-determinístico). Default 42 para
            reproducibility.
        price_base: preço inicial.
        null_trade_id_pct: 0.0-1.0 — fração com ``trade_id=None``
            (Quirk Q01-V força chave canônica longa).
        duplicate_pct: 0.0-1.0 — fração de trades duplicados (mesma chave
            canônica) intercalados na sequência.
        exchange: "F" (BMF, default) ou "B" (Bovespa).

    Yields:
        ``dict`` no schema canônico v1.0.0 (17 campos compatíveis com
        ``TradeRecord``).
    """
    rng = random.Random(seed)
    if start_ts_ns is None:
        start_ts_ns = time.time_ns()

    current_price = price_base
    current_ts = start_ts_ns
    trade_id_seq = 0
    yielded = 0

    # Buffer pequeno para reinjetar duplicatas (~1%).
    recent: list[dict] = []
    recent_window = 100

    while yielded < n:
        # Decidir se emite duplicata (re-yield de um trade recente).
        if recent and rng.random() < duplicate_pct:
            dup = dict(recent[rng.randrange(len(recent))])
            yield dup
            yielded += 1
            continue

        # Random walk price (volatility ~0.01% por tick).
        change_pct = rng.gauss(0, DEFAULT_VOLATILITY_PER_TICK)
        current_price *= 1 + change_pct
        # Clamp ±2% do base para não derivar muito longe.
        upper = price_base * 1.02
        lower = price_base * 0.98
        current_price = max(lower, min(upper, current_price))
        price_rounded = _round_to_tick(current_price)

        # Quantidade long-tail: maioria 1-5, p99 ~50, máx 100.
        # Usar exponencial deslocada — barato e bem-comportado.
        qty_raw = int(rng.expovariate(1 / 4.0)) + 1  # média ~5
        quantity = min(qty_raw, 100)

        # Timestamp jitter: ~1ms ± 50%.
        interval = max(1, int(DEFAULT_INTERVAL_NS * (0.5 + rng.random())))
        current_ts += interval

        trade_id: int | None
        if rng.random() < null_trade_id_pct:
            trade_id = None  # Quirk Q01-V — chave longa
        else:
            trade_id_seq += 1
            trade_id = trade_id_seq

        # side: 0/1/None (tristate). Schema usa uint8 nullable.
        side_roll = rng.random()
        if side_roll < 0.475:
            side: int | None = 0  # buy
        elif side_roll < 0.95:
            side = 1  # sell
        else:
            side = None  # cross / desconhecido

        trade = {
            "symbol": symbol,
            "exchange": exchange,
            "timestamp_ns": current_ts,
            "timestamp_str": str(current_ts),  # placeholder formatável
            "price": price_rounded,
            "quantity": quantity,
            "trade_id": trade_id,
            "trade_type": 1,  # regular
            "buy_agent_id": rng.randint(1, 999) if rng.random() > 0.1 else None,
            "sell_agent_id": rng.randint(1, 999) if rng.random() > 0.1 else None,
            "flags": 0,
            "source_callback": "history",
            "side": side,
            "ingestion_ts_ns": current_ts,
            "chunk_id": None,
            "dll_version": MOCK_DLL_VERSION,
            "sequence_within_ns": 0,  # writer/dedup atribui
        }

        # Atualiza buffer de duplicatas (sliding window).
        if len(recent) >= recent_window:
            recent.pop(0)
        recent.append(trade)

        yield trade
        yielded += 1


def generate_batch_arrow(n: int, **kwargs) -> pa.Table:  # type: ignore
    """Versão batch — gera lista, converte para ``pa.Table``.

    Implementação simples (sem vetorização numpy): para benchmarks de
    write o overhead da geração não é o foco; ParquetWriter recebe
    ``list[TradeRecord]`` mesmo. Esta função é conveniência para
    benchmarks de read que precisam de ``pa.Table`` direto.
    """
    import pyarrow as pa

    from data_downloader.storage.schema import pyarrow_schema

    trades = list(generate(n, **kwargs))
    schema = pyarrow_schema()
    columns: dict[str, list[object]] = {f.name: [] for f in schema}
    for trade in trades:
        for f in schema:
            columns[f.name].append(trade.get(f.name))
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)
