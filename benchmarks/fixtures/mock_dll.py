"""mock_dll.py — Mock completo da ProfitDLL para benchmarks.

Objetivo:
    Implementar a interface da ProfitDLL via Python puro, suficiente para
    benchmarks rodarem SEM ProfitDLL.dll real. Replica:
    - DLLInitializeMarketLogin / DLLFinalize
    - SetTradeCallback / SetStateCallback / SetHistoryTradeCallback
    - GetHistoryTrades (entrega trades sintéticos via callback)
    - State machine (LOGIN_CONNECTED, MARKET_CONNECTED, etc.)
    - Quirks observados: 99% reconnect, NULL trade_id ocasional.

Não objetivo:
    - NÃO substitui Story 1.2 (wrapper real). Mock vive em benchmarks/.
    - NÃO testa lógica de produção — testes de produção usam tests/mocks/.
    - Mock é para perf/scaling; nuance de comportamento real não garantida.

Convenção:
    Mesma assinatura do wrapper real (a ser definido em Story 1.2 por Dex
    com auditoria de Nelo). Mock implementa apenas o subset usado em bench.

Uso:
    from benchmarks.fixtures.mock_dll import MockProfitDLL
    dll = MockProfitDLL()
    dll.bind_trade_callback(lambda trade: print(trade))
    dll.initialize(activation_key="...", username="...", password="...")
    dll.get_history_trades(symbol="WDOJ26", date_start="2026-04-01", date_end="2026-04-01")
    dll.finalize()
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Iterator

# TODO: imports
# from benchmarks.fixtures.synthetic_trades import generate

# State machine values (alinhar com Quirk Q-AMB-01 — Nelo Story 1.2)
STATE_LOGIN_CONNECTED = 1
STATE_MARKET_WAITING = 2  # Q-AMB-01: 2 vs 4 ambíguo
STATE_MARKET_CONNECTED = 4
STATE_DISCONNECTED = 99

# Callback signatures (placeholder — alinhar com WINFUNCTYPE real Story 1.2)
TradeCallback = Callable[[dict], None]
StateCallback = Callable[[int, str], None]
HistoryTradeCallback = Callable[[dict], None]
ProgressCallback = Callable[[float], None]


class MockProfitDLL:
    """Mock da ProfitDLL — interface compatível com wrapper real (Story 1.2).

    Limitações conscientes:
        - NÃO carrega DLL real; tudo Python puro.
        - Não simula latência de rede (use `simulate_network_latency_ms`).
        - Não simula a totalidade de quirks; apenas os que afetam benchmarks.
        - Thread model simplificado (1 ConnectorThread mock — fiel à DLL real).
    """

    def __init__(
        self,
        *,
        simulate_reconnect_pct: float = 0.99,  # Quirk Q-RECON
        simulate_null_trade_id_pct: float = 0.0,
        simulate_network_latency_ms: float = 0.0,
        rate_profile: str = "realistic_b3",
    ) -> None:
        self._initialized = False
        self._state = STATE_DISCONNECTED
        self._trade_cb: TradeCallback | None = None
        self._state_cb: StateCallback | None = None
        self._history_cb: HistoryTradeCallback | None = None
        self._progress_cb: ProgressCallback | None = None
        self._connector_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._reconnect_pct = simulate_reconnect_pct
        self._null_trade_id_pct = simulate_null_trade_id_pct
        self._latency_ms = simulate_network_latency_ms
        self._rate_profile = rate_profile

    # =====================================================================
    # Init / Finalize
    # =====================================================================

    def initialize(
        self,
        activation_key: str,
        username: str,
        password: str,
        # Q11-E: 11 callback slots fixos (Nelo Story 1.2 AC2)
        trade_callback: TradeCallback | None = None,
        state_callback: StateCallback | None = None,
        history_trade_callback: HistoryTradeCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        # ... 7 outros slots placeholder
    ) -> int:
        """Mock de DLLInitializeMarketLogin.

        Returns:
            0 = sucesso, código de erro caso contrário.
        """
        # TODO:
        # if self._initialized:
        #     # Quirk: DLL não-idempotente em init→finalize→init (M15)
        #     return -2147483648  # ERR_REINIT
        # self._trade_cb = trade_callback
        # self._state_cb = state_callback
        # self._history_cb = history_trade_callback
        # self._progress_cb = progress_callback
        # self._initialized = True
        # # Inicia ConnectorThread mock — emite states em ordem realista
        # self._connector_thread = threading.Thread(
        #     target=self._connector_loop, daemon=True
        # )
        # self._connector_thread.start()
        # return 0
        raise NotImplementedError("Aguarda implementação")

    def finalize(self) -> int:
        """Mock de DLLFinalize."""
        # TODO:
        # self._stop_event.set()
        # if self._connector_thread:
        #     self._connector_thread.join(timeout=5)
        # self._initialized = False
        # self._state = STATE_DISCONNECTED
        # return 0
        raise NotImplementedError("Aguarda implementação")

    # =====================================================================
    # Bind callbacks (alternative API)
    # =====================================================================

    def bind_trade_callback(self, cb: TradeCallback) -> None:
        self._trade_cb = cb

    def bind_state_callback(self, cb: StateCallback) -> None:
        self._state_cb = cb

    def bind_history_callback(self, cb: HistoryTradeCallback) -> None:
        self._history_cb = cb

    def bind_progress_callback(self, cb: ProgressCallback) -> None:
        self._progress_cb = cb

    # =====================================================================
    # Operations
    # =====================================================================

    def get_history_trades(
        self,
        symbol: str,
        date_start: str,
        date_end: str,
        *,
        n_trades_synthetic: int | None = None,
    ) -> int:
        """Mock de GetHistoryTrades — entrega trades sintéticos via callback.

        Args:
            symbol: ticker.
            date_start: YYYY-MM-DD.
            date_end: YYYY-MM-DD.
            n_trades_synthetic: override; default = ~500k por dia útil.

        Returns:
            0 sucesso.
        """
        # TODO:
        # if not self._initialized:
        #     return -1
        # if self._state != STATE_MARKET_CONNECTED:
        #     return -2
        # if self._history_cb is None:
        #     return -3
        #
        # n = n_trades_synthetic or self._estimate_n_trades(date_start, date_end)
        # # Spawn thread mock que entrega trades + progress callbacks
        # threading.Thread(
        #     target=self._deliver_history,
        #     args=(symbol, n),
        #     daemon=True,
        # ).start()
        # return 0
        raise NotImplementedError("Aguarda implementação")

    def fire_trade(self, trade_id: int, *, inject_marker: bool = False,
                   inject_ts_ns: int | None = None) -> bool:
        """Helper para benchmarks: força injeção de 1 trade no callback.

        Returns:
            False se callback rejeitou (back-pressure / queue full).
        """
        # TODO: usar para bench_callback_to_disk
        raise NotImplementedError("Aguarda implementação")

    def set_rate_profile(self, profile: str) -> None:
        """Configura perfil de taxa (constant, realistic_b3, burst)."""
        self._rate_profile = profile

    # =====================================================================
    # Internal — ConnectorThread mock
    # =====================================================================

    def _connector_loop(self) -> None:
        """Simula sequência realista de states e Quirk Q-RECON."""
        # TODO:
        # # Sequência real (Nelo Story 1.2 AC5):
        # # DISCONNECTED → LOGIN_CONNECTED → MARKET_WAITING → MARKET_CONNECTED
        # for state in [STATE_LOGIN_CONNECTED, STATE_MARKET_WAITING, STATE_MARKET_CONNECTED]:
        #     if self._stop_event.wait(0.05):
        #         return
        #     self._state = state
        #     if self._state_cb:
        #         self._state_cb(state, "mock_state_change")
        #
        # # Quirk Q-RECON: ~99% das sessões reconectam 1x logo após
        # if random.random() < self._reconnect_pct and not self._stop_event.is_set():
        #     time.sleep(0.1)
        #     self._state = STATE_DISCONNECTED
        #     if self._state_cb:
        #         self._state_cb(STATE_DISCONNECTED, "mock_quirk_recon")
        #     time.sleep(0.05)
        #     self._state = STATE_MARKET_CONNECTED
        #     if self._state_cb:
        #         self._state_cb(STATE_MARKET_CONNECTED, "mock_reconnected")
        raise NotImplementedError("Aguarda implementação")

    def _deliver_history(self, symbol: str, n_trades: int) -> None:
        """Entrega N trades via _history_cb com taxa realista."""
        # TODO:
        # for i, trade in enumerate(generate(
        #     n=n_trades, symbol=symbol,
        #     null_trade_id_pct=self._null_trade_id_pct,
        #     rate_profile=self._rate_profile,
        # )):
        #     if self._stop_event.is_set():
        #         break
        #     if self._latency_ms > 0:
        #         time.sleep(self._latency_ms / 1000)
        #     if self._history_cb:
        #         self._history_cb(trade)
        #     if self._progress_cb and i % 10000 == 0:
        #         self._progress_cb(i / n_trades * 100)
        # if self._progress_cb:
        #     self._progress_cb(100.0)
        raise NotImplementedError("Aguarda implementação")

    def _estimate_n_trades(self, date_start: str, date_end: str) -> int:
        """Estima trades realistas baseado em range de dias úteis."""
        # TODO: parsing de datas + ~500k/dia útil
        return 500_000
