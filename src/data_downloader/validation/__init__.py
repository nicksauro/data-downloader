"""data_downloader.validation — Validators executáveis (Story 2.1).

Co-owners: 💾 Sol (storage authority — invariantes INT-1..INT-12) +
🧪 Quinn (qa authority — gap detection contra calendário B3).

Este subpacote implementa em código os comandos historicamente
imaginários ``Sol *integrity-check`` e ``Quinn *data-validate``,
fechando o finding C4 do gate Epic 1 (Plan Review 2026-05-03).

Módulos:

- ``integrity.py`` — :class:`IntegrityChecker` (Sol). Roda queries
  DuckDB canônicas de ``docs/storage/INTEGRITY.md`` §2 sobre os Parquet
  e o catálogo. 6 checks principais cobrindo INT-1..INT-6.
- ``data_validator.py`` — :class:`DataValidator` (Quinn). Detecta
  gaps em datasets contra o calendário B3 (INT-9). Classifica cada gap
  como ``holiday``/``no_trades_day``/``missing_download``.
- ``calendar_b3.py`` — calendário B3 hardcoded para 2025-2026 (TODO:
  integrar com ``holidays.dat`` Nelogica em Story futura).

Política Sol+Quinn (mini-council):

- Validators são CÓDIGO. Não scripts ad-hoc.
- Toda violação de invariante (INT-1..INT-12) é serializável em
  :class:`IntegrityReport`.
- Calendário B3 é fonte canônica para gap detection — testes/benchmarks
  limitam-se a ``>= 2020-01-01`` (DST B3 ambiguidade — INTEGRITY.md §6).
"""

from __future__ import annotations

from data_downloader.validation.calendar_b3 import (
    b3_business_days_range,
    is_b3_business_day,
)
from data_downloader.validation.data_validator import (
    DataValidator,
    GapReport,
    validate_dataset,
)
from data_downloader.validation.integrity import (
    IntegrityCheck,
    IntegrityChecker,
    IntegrityReport,
)

__all__ = [
    "DataValidator",
    "GapReport",
    "IntegrityCheck",
    "IntegrityChecker",
    "IntegrityReport",
    "b3_business_days_range",
    "is_b3_business_day",
    "validate_dataset",
]
