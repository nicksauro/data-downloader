# ADR-023 — Uniform 1-day Chunk Policy

**Status:** ACCEPTED
**Date:** 2026-05-07
**Owner:** @architect (Aria) — directive Pichau live smoke v1.1.0
**Supersedes:** Story 4.16 directive 2026-05-06 (WDOFUT=5d, WINFUT=1d, equities=5d)

## Context

A directive original Story 4.16 (Pichau 2026-05-06) estabeleceu chunks per-symbol:
WDOFUT/INDFUT/DOLFUT/equities=5d, WINFUT=1d. Foi mitigation Q-DRIFT-37 (queue overflow
risk WINFUT em 5d).

Em smoke live v1.1.0 (2026-05-07), Pichau identificou desejo de feedback granular
per-day E observou que policy mista era complexa de explicar ao usuário ("por que WIN
é diferente?").

## Decision

Política única: **TODOS os ativos baixam em chunks de 1 dia útil B3**.

- `chunk_strategy.DEFAULT_CHUNK_DAYS = 1` (foi 5)
- `chunk_strategy._CHUNK_OVERRIDES = {}` (foi {"WINFUT":1})
- `chunker.CHUNK_DAYS = {"WDO":1, "WIN":1, "IND":1, "DOL":1}` (foi 5)
- `chunker.DEFAULT_EQUITY_CHUNK_DAYS = 1` (sem mudança — já era 1)

## Consequences

**Positive:**
- UX: progress per-day visível em tempo real (cada chunk = 1 dia útil → 1 update da progress bar)
- Q-DRIFT-37: FULLY mitigated — todos os símbolos longe do limite 2M trades/queue
- Resilience: falha em 1 chunk perde apenas 1 dia (era até 5d)
- Simplicidade: política única, fácil de documentar e raciocinar

**Negative / Trade-offs:**
- Mais overhead RPC: download 30d agora = 30 chunks (era 6 chunks WDO 5d)
- Latency total ligeiramente maior (mais init/teardown por chunk)
- Aceitável: Pichau prioriza feedback granular sobre throughput máximo

## Compliance check

- `chunk_strategy.DEFAULT_CHUNK_DAYS == 1`
- `len(chunk_strategy._CHUNK_OVERRIDES) == 0`
- All values in `chunker.CHUNK_DAYS == 1`
- Todos tests `pytest tests/unit/test_chunk*.py` PASS

## References

- ADR-020 (volume completeness invariant) — não impactado
- Q-DRIFT-37 (queue overflow risk) — promove de CLOSED-MITIGATED para CLOSED-FULLY-MITIGATED
- Story 4.16 (chunk strategy per-symbol) — superseded

## Revisão

Revisar em v1.2.0 se Pichau quiser per-symbol granularity de novo (e.g. WDOFUT em 2d
para reduzir RPC se latency virar problema medido).
