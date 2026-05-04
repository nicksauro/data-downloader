"""data_downloader.storage.dedup — Dedup canônico de trades.

Owner: Sol (chave) | Impl: Dex.
Ref: ``docs/storage/SCHEMA.md`` §2 (chave canônica).

Duas variantes de chave (SCHEMA.md §2.1):

- **Curta** (callback V2 com ``trade_id``):
  ``(symbol, timestamp_ns, trade_id)``.
- **Longa** (callback V1 sem ``trade_id``):
  ``(symbol, timestamp_ns, price, quantity, buy_agent_id,
  sell_agent_id, sequence_within_ns)``.

``sequence_within_ns`` desempata trades distintos no mesmo nanosegundo
(picos de leilão / cross em B3) — atribuído por
:func:`assign_sequence_within_ns` ANTES de :func:`dedup` quando
``trade_id`` é ``None``.

Invariantes (INTEGRITY.md INV-2):

- ``dedup(L ++ L) == dedup(L)`` (idempotência).
- ``dedup(dedup(L)) == dedup(L)``.

Implementação: ``dict`` preservando ordem de inserção (Python 3.7+
garantido) — primeira ocorrência da chave vence.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from data_downloader.storage.schema import TradeRecord


def compute_canonical_hash(trade: TradeRecord) -> tuple[Any, ...]:
    """Computa a chave canônica de dedup para um trade.

    Escolhe a variante curta vs longa em runtime baseado na presença de
    ``trade_id`` (SCHEMA.md §2.1). Retorna um ``tuple`` hashable para uso
    direto como chave de ``dict`` ou ``set``.

    Args:
        trade: Trade canônico (``TradeRecord``). DEVE ter ``symbol`` e
            ``timestamp_ns`` (NOT NULL no schema). DEVE ter
            ``sequence_within_ns`` se ``trade_id`` é ``None``.

    Returns:
        Tuple hashable representando a chave canônica do trade.

    Notes:
        Discriminador ``"V2"``/``"V1"`` no início do tuple evita colisão
        teórica entre as duas variantes (chave V2 nunca colide com V1
        mesmo se os 3 primeiros elementos coincidirem).
    """
    trade_id = trade.get("trade_id")
    if trade_id is not None:
        # Variante curta — V2 callback (SCHEMA.md §2.1)
        return ("V2", trade["symbol"], trade["timestamp_ns"], trade_id)

    # Variante longa — V1 callback (SCHEMA.md §2.1)
    return (
        "V1",
        trade["symbol"],
        trade["timestamp_ns"],
        trade["price"],
        trade["quantity"],
        trade.get("buy_agent_id"),
        trade.get("sell_agent_id"),
        trade["sequence_within_ns"],
    )


def assign_sequence_within_ns(trades: list[TradeRecord]) -> list[TradeRecord]:
    """Atribui ``sequence_within_ns`` 0..N por bucket ``(symbol, timestamp_ns)``.

    Trades com o mesmo ``(symbol, timestamp_ns)`` recebem 0, 1, 2, ...
    na ordem em que aparecem na lista. Essencial para a chave longa
    (SCHEMA.md §2.1) quando ``trade_id`` é ``None`` — sem sequence,
    trades genuinamente distintos com preço/qtd idênticos no mesmo ns
    seriam dedupados como duplicatas.

    Esta função preserva a ordem original e MUTA o campo
    ``sequence_within_ns`` no trade (TypedDict é dict — mutação ok).
    Retorna a mesma lista (in-place + return para encadeamento).

    Args:
        trades: Lista de trades. Pode ter ``sequence_within_ns`` já
            preenchido (será sobrescrito — esta função é a fonte
            canônica).

    Returns:
        Mesma lista, com ``sequence_within_ns`` atribuído por bucket.
    """
    counters: dict[tuple[str, int], int] = defaultdict(int)
    for trade in trades:
        bucket = (trade["symbol"], trade["timestamp_ns"])
        trade["sequence_within_ns"] = counters[bucket]
        counters[bucket] += 1
    return trades


def dedup(trades: list[TradeRecord]) -> list[TradeRecord]:
    """Remove duplicatas pela chave canônica preservando ordem.

    Estratégia: ``dict`` indexado pela chave canônica
    (:func:`compute_canonical_hash`). Em colisão, a PRIMEIRA ocorrência
    vence (Python ``dict.setdefault``). Ordem de inserção é preservada
    (Python 3.7+).

    Garantias (INV-2):

    - ``dedup(L ++ L) == dedup(L)`` — re-aplicar é seguro.
    - ``dedup(dedup(L)) == dedup(L)`` — idempotente.
    - Tamanho do retorno ``<= len(trades)``.
    - Ordem dos sobreviventes preservada.

    Pré-condição: trades sem ``trade_id`` DEVEM ter
    ``sequence_within_ns`` atribuído (chamar
    :func:`assign_sequence_within_ns` antes). O writer faz isso
    automaticamente.

    Args:
        trades: Lista de trades canônicos.

    Returns:
        Nova lista sem duplicatas (não muta entrada).
    """
    seen: dict[tuple[Any, ...], TradeRecord] = {}
    for trade in trades:
        key = compute_canonical_hash(trade)
        # setdefault: primeira ocorrência vence; chamadas subsequentes são no-op
        seen.setdefault(key, trade)
    return list(seen.values())


__all__ = [
    "assign_sequence_within_ns",
    "compute_canonical_hash",
    "dedup",
]
