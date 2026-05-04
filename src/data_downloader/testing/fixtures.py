"""data_downloader.testing.fixtures — Fixtures pytest reutilizáveis.

Story 2.10 / ADR-014 — fixtures canônicas que substituem boilerplate
ad-hoc em ``tests/conftest.py`` e em conftests específicos.

Uso típico (em ``tests/conftest.py``)::

    from data_downloader.testing.fixtures import (
        fake_clock,
        mock_dll_session,
        synthetic_trades_factory,
        tmp_catalog,
    )

    __all__ = [
        "fake_clock",
        "mock_dll_session",
        "synthetic_trades_factory",
        "tmp_catalog",
    ]

Princípios (ADR-014 §6):

- **Layer 1 (atomic):** :func:`mock_dll_session`, :func:`fake_clock`,
  :func:`tmp_catalog` — mocks puros sem composição.
- **Layer 2 (composto):** :func:`synthetic_trades_factory`, depende de
  ``random.Random`` com seed.
- **Test parallelism safe:** cada fixture cria nova instância (sem state
  compartilhado entre tests).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from data_downloader.testing.fake_clock import FakeClock
from data_downloader.testing.mock_dll import MockProfitDLL, TradeRecordSpec

# =====================================================================
# Constants
# =====================================================================

DEFAULT_SYMBOL = "WDOJ26"
DEFAULT_EXCHANGE = "F"
DEFAULT_BASE_TIMESTAMP_NS = 1_700_000_000_000_000_000  # 2023-11-14 UTC ~

# =====================================================================
# Layer 1 — atomic fixtures
# =====================================================================


@pytest.fixture  # type: ignore[misc, unused-ignore]
def fake_clock() -> FakeClock:
    """:class:`FakeClock` parado em ``0.0`` — caller avança como quiser.

    Não patcha ``time`` globalmente — caller faz ``with clock.patch_time():``
    se precisa interceptar ``time.time()`` / ``time.perf_counter()``.

    Returns:
        Nova instância de :class:`FakeClock` por teste (test parallelism
        safe).
    """
    return FakeClock()


@pytest.fixture  # type: ignore[misc, unused-ignore]
def mock_dll_session() -> Generator[MockProfitDLL, None, None]:
    """:class:`MockProfitDLL` inicializado, conectado, pronto para uso.

    Lifecycle gerenciado: init no setup, finalize no teardown (mesmo se
    teste falha — usa ``yield``).

    Yields:
        :class:`MockProfitDLL` já em estado MARKET_CONNECTED.
    """
    dll = MockProfitDLL(seed=42)
    dll.initialize_market_only("FAKE_KEY", "fake_user", "fake_pwd")
    assert dll.wait_market_connected(timeout=5)
    try:
        yield dll
    finally:
        dll.finalize()


@pytest.fixture  # type: ignore[misc, unused-ignore]
def mock_dll_uninitialized() -> Generator[MockProfitDLL, None, None]:
    """:class:`MockProfitDLL` SEM inicialização — caller controla."""
    dll = MockProfitDLL(seed=42)
    try:
        yield dll
    finally:
        if dll.is_initialized:
            dll.finalize()


@pytest.fixture  # type: ignore[misc, unused-ignore]
def tmp_catalog(tmp_path: Path) -> Path:
    """Diretório temporário para catálogo SQLite (1 por teste)."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir(exist_ok=True)
    return catalog_dir


@pytest.fixture  # type: ignore[misc, unused-ignore]
def tmp_data_dir(tmp_path: Path) -> Path:
    """Diretório temporário layout-canônico ``data/history/``."""
    data_dir = tmp_path / "data"
    (data_dir / "history").mkdir(parents=True, exist_ok=True)
    return data_dir


# =====================================================================
# Layer 2 — composed fixtures (factories)
# =====================================================================


@pytest.fixture  # type: ignore[misc, unused-ignore]
def synthetic_trades_factory() -> Callable[..., list[TradeRecordSpec]]:
    """Factory de listas de trades sintéticos com seed determinístico.

    Returns:
        Função ``make(n=N, *, seed=42, symbol="WDOJ26", base_ts=..., gap_ns=1_000_000)``
        que produz ``list[TradeRecordSpec]`` com IDs sequenciais e
        timestamps monotônicos.
    """

    def _make(
        n: int = 100,
        *,
        seed: int = 42,
        symbol: str = DEFAULT_SYMBOL,
        exchange: str = DEFAULT_EXCHANGE,
        base_ts_ns: int = DEFAULT_BASE_TIMESTAMP_NS,
        gap_ns: int = 1_000_000,
    ) -> list[TradeRecordSpec]:
        rng = random.Random(seed)
        trades: list[TradeRecordSpec] = []
        for i in range(n):
            trades.append(
                TradeRecordSpec(
                    symbol=symbol,
                    exchange=exchange,
                    timestamp_ns=base_ts_ns + i * gap_ns,
                    trade_id=i + 1,
                    price=round(5_000.0 + rng.uniform(-50, 50), 2),
                    quantity=rng.randint(1, 100),
                    flags=0,
                )
            )
        return trades

    return _make


__all__ = [
    "DEFAULT_BASE_TIMESTAMP_NS",
    "DEFAULT_EXCHANGE",
    "DEFAULT_SYMBOL",
    "fake_clock",
    "mock_dll_session",
    "mock_dll_uninitialized",
    "synthetic_trades_factory",
    "tmp_catalog",
    "tmp_data_dir",
]
