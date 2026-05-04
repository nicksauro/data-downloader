"""data_downloader.testing.mock_dll — Mock fiel da ProfitDLL para testes.

Story 2.10 / ADR-014 — extrai e expande a fixture mock antes espalhada
entre ``tests/conftest.py`` e ``benchmarks/fixtures/mock_dll.py`` para uma
implementação canônica reutilizável.

Princípios (Quinn / Nelo audit):

- **Superfície idêntica:** mesmos métodos públicos do
  :class:`data_downloader.dll.wrapper.ProfitDLL` (init, wait, history,
  finalize, ``dll_version`` property). Caller pode trocar ``ProfitDLL``
  por :class:`MockProfitDLL` sem mudança de chamadas.
- **Determinismo:** sequência de trades injetada via :meth:`fire_trades`
  é entregue na ordem exata; nenhuma randomização sem seed.
- **Quirks documentados:** ``Q02-E`` reconnect 99% e ``Q11-E`` (11
  callback slots) são modeláveis via parâmetros do construtor.
- **Auditável:** :attr:`mock_calls` registra ordem de invocações da
  superfície pública para asserts de teste; :attr:`callback_violations`
  registra detecções de violação INV-1 (callback chamou DLL).

Lifecycle típico::

    mock = MockProfitDLL()
    mock.initialize_market_only("KEY", "USR", "PWD")
    assert mock.wait_market_connected(timeout=5)
    mock.set_history_trade_callback_v2(my_cb)
    mock.set_progress_callback(my_progress_cb)
    mock.fire_trades([...])  # determinístico — entrega via callback
    mock.finalize()

Limitações conscientes:

- Não simula latência de rede (use ``simulate_latency_seconds=...``).
- Não exercita o ABI ``ctypes`` real — testes de ABI ficam em
  ``tests/unit/test_dll_callbacks.py`` (compilam o trampoline real).
- Não substitui smoke (real DLL, real Nelógica) — mock é para tudo
  ``unit/integration/property``; smoke é gated por ``RUN_SMOKE=1``.
"""

from __future__ import annotations

import contextlib
import random
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import Any, Final, Literal, TypedDict

# =====================================================================
# Constantes de protocol — mirror de data_downloader.dll.types
# =====================================================================

# State codes (manual ProfitDLL §3.2 L3317-3329).
STATE_DISCONNECTED: Final[int] = 99
STATE_LOGIN_CONNECTED: Final[int] = 0
STATE_MARKET_WAITING: Final[int] = 2
STATE_MARKET_CONNECTED: Final[int] = 4

# conn_type — 1º arg do TStateCallback.
CONN_TYPE_LOGIN: Final[int] = 0
CONN_TYPE_ROUTING: Final[int] = 1
CONN_TYPE_MARKET_DATA: Final[int] = 2
CONN_TYPE_MARKET_LOGIN: Final[int] = 3

# Erros NL_* canônicos (subset usado em mocks de error injection).
NL_OK: Final[int] = 0
NL_NOT_INITIALIZED: Final[int] = -2147483646
NL_INTERNAL_ERROR: Final[int] = -2147483645
NL_DISCONNECT: Final[int] = -2147483644

# Q11-E: número fixo de callback slots no init.
EXPECTED_CALLBACK_SLOTS: Final[int] = 11

# Quirk Q02-E: probabilidade de 1 reconnect no início da sessão.
DEFAULT_RECONNECT_PROBABILITY: Final[float] = 0.99


# =====================================================================
# Tipos auxiliares
# =====================================================================


class TradeRecordSpec(TypedDict, total=False):
    """Spec mínima de um trade injetado via :meth:`MockProfitDLL.fire_trades`.

    Campos refletem a superfície ``TConnectorTrade`` que o callback V2
    receberia em produção. Apenas ``timestamp_ns`` + ``trade_id`` +
    ``symbol`` são obrigatórios; restante tem default razoável.
    """

    symbol: str
    timestamp_ns: int
    trade_id: int
    price: float
    quantity: int
    flags: int
    exchange: str


@dataclass(frozen=True)
class MockCall:
    """Snapshot de uma invocação da superfície pública do mock.

    Atributos:
        name: Nome do método invocado (ex.: ``"initialize_market_only"``).
        args: Tuple posicional sanitizado (credenciais redacted).
        kwargs: Dict de kwargs sanitizado.
    """

    name: str
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)


# =====================================================================
# MockProfitDLL — implementação canônica
# =====================================================================


class MockProfitDLL:
    """Mock fiel + auditável da :class:`data_downloader.dll.wrapper.ProfitDLL`.

    Uso (como drop-in replacement do wrapper real)::

        dll = MockProfitDLL(seed=42)
        dll.initialize_market_only("KEY", "USR", "PWD")
        assert dll.wait_market_connected(timeout=1)
        dll.set_history_trade_callback_v2(callback)
        dll.fire_trades([{"symbol": "WDOJ26", "timestamp_ns": ts, "trade_id": tid}, ...])
        dll.finalize()

    Args:
        seed: Seed do gerador interno (RNG). Mesmo seed → mesma sequência
            de quirks (reconnect 99%, etc.). Default 42.
        reconnect_probability: Probabilidade [0..1] de Q02-E (1 reconnect
            no início da sessão). Default :data:`DEFAULT_RECONNECT_PROBABILITY`.
        simulate_latency_seconds: Atraso artificial entre callbacks de
            trade — útil para benchmark. Default 0.0 (sem delay).
        nl_error_on_history: Se != :data:`NL_OK`, :meth:`get_history_trades`
            retorna esse código sem disparar callbacks (simulação de
            falha NL_*). Default :data:`NL_OK`.
        dll_version: String reportada pela property ``dll_version``.
    """

    def __init__(
        self,
        *,
        seed: int = 42,
        reconnect_probability: float = DEFAULT_RECONNECT_PROBABILITY,
        simulate_latency_seconds: float = 0.0,
        nl_error_on_history: int = NL_OK,
        dll_version: str = "0.0.0+mock",
    ) -> None:
        self._seed = seed
        self._rng = random.Random(seed)
        self._reconnect_probability = reconnect_probability
        self._latency = simulate_latency_seconds
        self._nl_error_on_history = nl_error_on_history
        self._dll_version_str = dll_version

        # Lifecycle state.
        self._initialized: bool = False
        self._finalized: bool = False
        self._market_connected: bool = False
        self._state_queue: Queue[tuple[int, int]] = Queue(maxsize=1000)

        # Callbacks registrados.
        self._state_callback: Callable[[int, int], None] | None = None
        self._noop_callbacks: list[Callable[..., Any]] = []
        self._history_trade_callback: Callable[..., Any] | None = None
        self._progress_callback: Callable[..., Any] | None = None

        # Thread mock — substitui ConnectorThread interna da DLL real.
        self._connector_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Auditoria.
        self._mock_calls: list[MockCall] = []
        self._callback_violations: list[str] = []
        self._in_callback: threading.local = threading.local()

    # =================================================================
    # Properties + auditoria
    # =================================================================

    @property
    def mock_calls(self) -> list[MockCall]:
        """Histórico ordenado de chamadas à superfície pública.

        Imutável após snapshot — caller pode comparar com lista esperada.
        """
        return list(self._mock_calls)

    @property
    def callback_violations(self) -> list[str]:
        """Lista de violações INV-1 detectadas (callback chamou DLL).

        Quinn audita: ``assert mock.callback_violations == []``.
        """
        return list(self._callback_violations)

    @property
    def dll_version(self) -> str:
        """Versão reportada — espelha :attr:`ProfitDLL.dll_version`."""
        self._record("dll_version")
        return self._dll_version_str

    @property
    def is_initialized(self) -> bool:
        """True após :meth:`initialize_market_only` bem sucedido."""
        return self._initialized and not self._finalized

    # =================================================================
    # Lifecycle — espelha data_downloader.dll.wrapper.ProfitDLL
    # =================================================================

    def initialize_market_only(self, key: str, user: str, password: str) -> None:
        """Mock de :meth:`ProfitDLL.initialize_market_only`.

        Args:
            key: Chave de licença (mascarada no histórico de mock_calls).
            user: Usuário B3.
            password: Senha (mascarada).

        Raises:
            RuntimeError: Se já inicializado E finalizado (Q08-E / M15 —
                DLL real não é idempotente, mock replica).
        """
        # M15 — re-init na mesma "sessão" é proibido.
        if self._finalized:
            raise RuntimeError(
                "MockProfitDLL: re-init após finalize não suportado "
                "(M15/Q08-E — DLL real é não-idempotente)."
            )
        self._record(
            "initialize_market_only",
            kwargs={"key_redacted": "***", "user": user, "password_redacted": "***"},
        )

        self._initialized = True
        self._stop_event.clear()
        self._connector_thread = threading.Thread(
            target=self._connector_loop,
            name="MockConnectorThread",
            daemon=True,
        )
        self._connector_thread.start()

    def wait_market_connected(self, timeout: int = 60) -> bool:
        """Mock de :meth:`ProfitDLL.wait_market_connected`.

        Drena a state queue (preenchida pelo connector loop mock) até
        ver ``(MARKET_DATA, MARKET_CONNECTED)`` ou timeout.

        Args:
            timeout: Timeout total em segundos.

        Returns:
            True se MARKET conectou dentro do timeout.
        """
        self._record("wait_market_connected", kwargs={"timeout": timeout})

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                conn_type, result = self._state_queue.get(timeout=remaining)
            except Empty:
                return False
            if conn_type == CONN_TYPE_MARKET_DATA and result in (
                STATE_MARKET_WAITING,
                STATE_MARKET_CONNECTED,
            ):
                self._market_connected = True
                return True

    def set_history_trade_callback_v2(self, callback: Callable[..., Any]) -> None:
        """Registra callback V2 — espelha :meth:`ProfitDLL.set_history_trade_callback_v2`.

        Raises:
            RuntimeError: Se DLL não inicializada (NL_NOT_INITIALIZED).
        """
        self._record("set_history_trade_callback_v2")
        if not self._initialized:
            raise RuntimeError("NL_NOT_INITIALIZED — chame initialize_market_only primeiro")
        self._history_trade_callback = callback

    def set_progress_callback(self, callback: Callable[..., Any]) -> None:
        """Registra callback de progress — espelha :meth:`ProfitDLL.set_progress_callback`."""
        self._record("set_progress_callback")
        if not self._initialized:
            raise RuntimeError("NL_NOT_INITIALIZED — chame initialize_market_only primeiro")
        self._progress_callback = callback

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start: str,
        dt_end: str,
    ) -> int:
        """Mock de :meth:`ProfitDLL.get_history_trades` — apenas valida args.

        A entrega de trades reais é controlada via :meth:`fire_trades`
        (modelo "explicit injection" — testes exercitam exatamente o que
        querem, sem dependência de RNG interno do mock).

        Returns:
            ``nl_error_on_history`` configurado no construtor (default
            :data:`NL_OK`).
        """
        self._record(
            "get_history_trades",
            kwargs={
                "ticker": ticker,
                "exchange": exchange,
                "dt_start": dt_start,
                "dt_end": dt_end,
            },
        )
        if not self._initialized:
            return NL_NOT_INITIALIZED
        if exchange not in ("F", "B"):
            raise ValueError(f"exchange deve ser 'F' ou 'B'; got {exchange!r}")
        # Validação superficial de formato — DLL real faz parsing similar.
        for label, value in (("dt_start", dt_start), ("dt_end", dt_end)):
            if not isinstance(value, str) or len(value) != 19:
                raise ValueError(
                    f"{label} deve estar em formato 'DD/MM/YYYY HH:mm:SS' (19 chars); "
                    f"got {value!r}"
                )
        return self._nl_error_on_history

    def finalize(self) -> None:
        """Mock de :meth:`ProfitDLL.finalize`."""
        self._record("finalize")
        if not self._initialized:
            return
        self._stop_event.set()
        if self._connector_thread is not None:
            self._connector_thread.join(timeout=5.0)
        self._finalized = True
        self._initialized = False
        self._market_connected = False

    def __enter__(self) -> MockProfitDLL:
        return self

    def __exit__(self, *args: object) -> None:
        if self._initialized:
            self.finalize()

    # =================================================================
    # Test helpers — injeção determinística + auditoria
    # =================================================================

    def fire_trades(
        self,
        trades: Sequence[TradeRecordSpec | dict[str, Any]],
        *,
        emit_progress: bool = True,
        last_packet_flag: int = 2,
    ) -> int:
        """Entrega ``trades`` via :attr:`_history_trade_callback` em ordem.

        Modelo "explicit injection" — os trades chegam EXATAMENTE como
        passados (sem RNG, sem dedup interno). Testes podem checar
        idempotência re-chamando ``fire_trades`` com a mesma lista.

        Args:
            trades: Sequência de trades (cada um dict com `timestamp_ns`,
                `trade_id`, `symbol` etc).
            emit_progress: Se True, emite progress 100 ao fim.
            last_packet_flag: Flag de fim-de-stream — default 2 reflete
                ``TC_LAST_PACKET`` da DLL real (manual §4 L4400).

        Returns:
            Quantidade de trades efetivamente entregues (== ``len(trades)``
            em caminho feliz; menor se o callback não foi registrado).
        """
        self._record("fire_trades", kwargs={"count": len(trades)})
        if self._history_trade_callback is None:
            return 0

        delivered = 0
        # Marca o thread atual como "em callback" para detecção INV-1.
        # Se o callback chama de volta a superfície pública do mock
        # (qualquer método decorado com _record), registramos violation.
        token = self._enter_callback_scope()
        try:
            for i, trade in enumerate(trades):
                if self._latency > 0:
                    time.sleep(self._latency)
                flags = last_packet_flag if i == len(trades) - 1 else int(trade.get("flags", 0))
                # Compatível com a assinatura V2: (asset, handle, flags).
                # Tests que conhecem a struct passam um fake; outros
                # checam pelo dict direto.
                self._history_trade_callback(trade, trade.get("trade_id", i), flags)
                delivered += 1
                if emit_progress and self._progress_callback is not None:
                    pct = int((i + 1) / max(len(trades), 1) * 100)
                    self._progress_callback(
                        trade.get("symbol", "?"),
                        trade.get("exchange", "F"),
                        0,
                        pct,
                    )
        finally:
            self._exit_callback_scope(token)
        return delivered

    def fire_state(self, conn_type: int, result: int) -> None:
        """Injeta um par ``(conn_type, result)`` na fila de estado.

        Útil para testes que exercitam :meth:`wait_market_connected` sem
        depender do connector loop automático.
        """
        self._record("fire_state", kwargs={"conn_type": conn_type, "result": result})
        with contextlib.suppress(Full):  # pragma: no cover — queue tem maxsize=1000
            self._state_queue.put_nowait((conn_type, result))

    def reset_audit(self) -> None:
        """Limpa :attr:`mock_calls` e :attr:`callback_violations`.

        Útil entre fases de um teste longo (setup phase vs assertion
        phase). NÃO altera estado de inicialização.
        """
        self._mock_calls.clear()
        self._callback_violations.clear()

    # =================================================================
    # Internal — connector loop e auditoria de callbacks
    # =================================================================

    def _connector_loop(self) -> None:
        """Reproduz a sequência canônica de states + Quirk Q02-E."""
        # Sequência canônica: LOGIN → ROTEAMENTO → MARKET_DATA(2) →
        # MARKET_DATA(4) → MARKET_LOGIN(0).
        canonical_sequence: list[tuple[int, int]] = [
            (CONN_TYPE_LOGIN, STATE_LOGIN_CONNECTED),
            (CONN_TYPE_ROUTING, STATE_MARKET_WAITING),
            (CONN_TYPE_MARKET_DATA, STATE_MARKET_WAITING),
            (CONN_TYPE_MARKET_DATA, STATE_MARKET_CONNECTED),
            (CONN_TYPE_MARKET_LOGIN, STATE_LOGIN_CONNECTED),
        ]
        for state in canonical_sequence:
            if self._stop_event.is_set():
                return
            try:
                self._state_queue.put_nowait(state)
            except Full:  # pragma: no cover
                return
            # Yield curto para simular ConnectorThread asincrona — sem
            # impacto em testes determinísticos (queue.get espera).
            self._stop_event.wait(0.001)

        # Quirk Q02-E: 99% das sessões reconectam 1x logo após.
        if self._rng.random() < self._reconnect_probability:
            if self._stop_event.is_set():
                return
            try:
                self._state_queue.put_nowait((CONN_TYPE_MARKET_DATA, STATE_DISCONNECTED))
                self._state_queue.put_nowait((CONN_TYPE_MARKET_DATA, STATE_MARKET_CONNECTED))
            except Full:  # pragma: no cover
                return

    def _enter_callback_scope(self) -> Literal[True]:
        """Marca o thread atual como "dentro de callback"."""
        self._in_callback.flag = True
        return True

    def _exit_callback_scope(self, _token: bool) -> None:
        """Limpa o marcador de "dentro de callback"."""
        self._in_callback.flag = False

    def _is_in_callback(self) -> bool:
        return bool(getattr(self._in_callback, "flag", False))

    def _record(
        self,
        name: str,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Registra invocação E detecta violação INV-1 se houver.

        Se o método é chamado *de dentro de* um callback (i.e., o thread
        está com :meth:`_is_in_callback` = True), considera violação INV-1.
        """
        kw = dict(kwargs or {})
        self._mock_calls.append(MockCall(name=name, args=args, kwargs=kw))
        if self._is_in_callback():
            self._callback_violations.append(
                f"INV-1 violado: {name}() chamado de dentro de callback"
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
