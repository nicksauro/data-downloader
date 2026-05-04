"""mock_dll.py — DEPRECATED stub.

Story 2.10: o mock canônico foi movido para
:mod:`data_downloader.testing.mock_dll` (subpackage testável publicado).
Este arquivo permanece apenas para **backwards compatibility** com
benchmarks que ainda fazem ``from benchmarks.fixtures.mock_dll import
MockProfitDLL``.

Novo código (testes, novos benchmarks) deve importar diretamente::

    from data_downloader.testing.mock_dll import MockProfitDLL

Este shim será removido em Epic 5 (após migração completa de benchmarks).
"""

from __future__ import annotations

from data_downloader.testing.mock_dll import (
    DEFAULT_RECONNECT_PROBABILITY,
    EXPECTED_CALLBACK_SLOTS,
    NL_DISCONNECT,
    NL_INTERNAL_ERROR,
    NL_NOT_INITIALIZED,
    NL_OK,
    STATE_DISCONNECTED,
    STATE_LOGIN_CONNECTED,
    STATE_MARKET_CONNECTED,
    STATE_MARKET_WAITING,
    MockCall,
    MockProfitDLL,
    TradeRecordSpec,
)

__all__ = [
    "DEFAULT_RECONNECT_PROBABILITY",
    "EXPECTED_CALLBACK_SLOTS",
    "NL_DISCONNECT",
    "NL_INTERNAL_ERROR",
    "NL_NOT_INITIALIZED",
    "NL_OK",
    "STATE_DISCONNECTED",
    "STATE_LOGIN_CONNECTED",
    "STATE_MARKET_CONNECTED",
    "STATE_MARKET_WAITING",
    "MockCall",
    "MockProfitDLL",
    "TradeRecordSpec",
]
