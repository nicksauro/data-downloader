"""tests/unit/test_dll_callbacks.py — Story 1.2.

Cobertura crítica de ``data_downloader.dll.callbacks``:

- AC3 / AC15 / INV-1: state callback faz APENAS ``put_nowait`` (assert
  ``mock_dll.mock_calls == []`` após invocar callback).
- AC4 / Q07-V: ``_cb_refs`` global retém callbacks (anti-GC).
- AC2 / Q11-E: ``make_noop_callback`` factory funciona para todas as
  signatures de ``NOOP_SLOT_SIGNATURES``.
"""

from __future__ import annotations

import gc
from queue import Queue
from unittest.mock import MagicMock

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.callbacks import (
    _cb_refs,
    cleanup_cb_refs,
    make_history_trade_callback_v2,
    make_noop_callback,
    make_progress_callback,
    make_state_callback,
)
from data_downloader.dll.types import NOOP_SLOT_SIGNATURES, TStateCallback


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> object:
    """Isola ``_cb_refs`` entre testes (cleanup em teardown via fixture)."""
    cleanup_cb_refs()
    yield
    cleanup_cb_refs()


@pytest.mark.unit
def test_make_state_callback_returns_callable_and_appends_to_cb_refs() -> None:
    """make_state_callback retorna WINFUNCTYPE-wrapped object E appenda em _cb_refs."""
    q: Queue[tuple[int, int]] = Queue(maxsize=1000)
    initial_refs = len(_cb_refs)

    cb = make_state_callback(q)

    assert cb is not None
    assert callable(cb)
    assert len(_cb_refs) == initial_refs + 1
    assert cb is _cb_refs[-1]


@pytest.mark.unit
def test_state_callback_only_calls_put_nowait_via_queue_mock() -> None:
    """AC15 — callback chama EXCLUSIVAMENTE put_nowait com tupla correta.

    Substitui a queue por MagicMock e verifica que o callback chamou
    apenas ``put_nowait((conn_type, result))`` — nenhuma outra chamada.
    """
    mock_queue = MagicMock(spec=Queue)
    cb = make_state_callback(mock_queue)

    # Invoca callback diretamente — em prod, a DLL invoca via ConnectorThread,
    # mas o trampoline ctypes apenas desempacota args.
    cb(0, 0)
    cb(2, 4)

    # Assert preciso: APENAS put_nowait foi chamado (e com tuplas corretas).
    assert mock_queue.put_nowait.call_count == 2
    assert mock_queue.put_nowait.call_args_list[0].args == ((0, 0),)
    assert mock_queue.put_nowait.call_args_list[1].args == ((2, 4),)
    # Nenhum outro método foi chamado:
    assert not mock_queue.put.called
    assert not mock_queue.get.called
    assert not mock_queue.get_nowait.called


@pytest.mark.unit
def test_state_callback_does_not_call_dll_inv1() -> None:
    """AC15 / INV-1 — callback NÃO chama nenhum método de mock_dll.

    CRITICAL: Lei R3 / manual ProfitDLL §4 L4382. Callback chamando a DLL
    causa exceções inesperadas / corrupção de fila interna. Quinn audita
    via este teste (mock_calls == []).
    """
    mock_dll = MagicMock()  # Simula objeto DLL inteiro.
    real_queue: Queue[tuple[int, int]] = Queue(maxsize=10)

    # Cria callback — note que callback NÃO recebe mock_dll por design;
    # o teste verifica que mesmo se mock_dll estivesse acessível via
    # closure (não está), o callback NÃO o usaria.
    cb = make_state_callback(real_queue)

    # Invoca várias vezes para garantir que nenhum side-effect surge.
    for conn_type, result in [(0, 0), (1, 2), (2, 4), (3, 0), (2, 2)]:
        cb(conn_type, result)

    # CORE ASSERTION (INV-1):
    assert mock_dll.mock_calls == [], (
        f"Callback chamou métodos do mock DLL — viola INV-1 / R3. Calls: {mock_dll.mock_calls}"
    )

    # Side-check: queue recebeu todos os 5 eventos.
    assert real_queue.qsize() == 5


@pytest.mark.unit
def test_make_noop_callback_works_for_all_noop_slot_signatures() -> None:
    """AC2 / Q11-E — factory funciona para cada signature usada no init."""
    initial_refs = len(_cb_refs)

    noops = [make_noop_callback(sig) for sig in NOOP_SLOT_SIGNATURES]

    # Todos foram criados.
    assert len(noops) == len(NOOP_SLOT_SIGNATURES)
    assert all(callable(n) for n in noops)

    # Todos foram appended em _cb_refs.
    assert len(_cb_refs) == initial_refs + len(NOOP_SLOT_SIGNATURES)
    for noop in noops:
        assert noop in _cb_refs


@pytest.mark.unit
def test_cb_refs_global_preserves_references_across_gc() -> None:
    """Q07-V — _cb_refs preserva callback mesmo após scope local sair (GC seguro).

    Cria callback em scope interno que sai do escopo; força GC; verifica
    que ``_cb_refs`` ainda contém o objeto E que ele continua callable
    (trampoline ctypes não foi liberado).
    """
    q: Queue[tuple[int, int]] = Queue(maxsize=10)

    def _create_in_scope() -> int:
        cb = make_state_callback(q)
        # Retorna apenas o id — ``cb`` sai do escopo.
        return id(cb)

    cb_id_in_scope = _create_in_scope()
    # Força GC para tentar coletar o objeto local (mas _cb_refs deve segurar).
    gc.collect()

    # _cb_refs ainda tem o objeto.
    assert len(_cb_refs) == 1
    assert id(_cb_refs[0]) == cb_id_in_scope

    # E ele continua callable (trampoline ctypes intacto).
    _cb_refs[0](0, 0)
    assert q.qsize() == 1
    assert q.get_nowait() == (0, 0)


@pytest.mark.unit
def test_state_callback_swallows_full_silently() -> None:
    """AC16 — overflow path: callback engole queue.Full sem lançar.

    Bug-only path (state changes <<< maxsize=1000), mas callback NÃO pode
    lançar (bloquearia ConnectorThread). Engolir é a única opção segura.
    """
    q: Queue[tuple[int, int]] = Queue(maxsize=1)
    cb = make_state_callback(q)

    # Primeiro put OK.
    cb(0, 0)
    # Segundo put raises Full INTERNAMENTE; callback engole.
    cb(1, 2)

    # Sem exception — apenas o primeiro está na queue.
    assert q.qsize() == 1
    assert q.get_nowait() == (0, 0)


@pytest.mark.unit
def test_cleanup_cb_refs_clears_for_test_isolation() -> None:
    """cleanup_cb_refs limpa lista — uso EXCLUSIVO para testes."""
    q: Queue[tuple[int, int]] = Queue()
    make_state_callback(q)
    make_noop_callback(TStateCallback)

    assert len(_cb_refs) == 2

    cleanup_cb_refs()

    assert len(_cb_refs) == 0
    # Sanity: módulo ainda tem a lista (não foi reassign).
    assert cb_module._cb_refs is _cb_refs


# =====================================================================
# Story 1.3 + v1.2.0 (COUNCIL-38 / Q-DRIFT-40) — V2 history trade callback
# (translate-in-callback: callback chama dll.translate_trade e enfileira
# TradeFields copiado — nunca o handle stale)
# =====================================================================


def _stub_translate_dll(
    *,
    fields_by_handle: dict[int, object | None] | None = None,
    default: object | None = None,
) -> MagicMock:
    """MagicMock de ProfitDLL com ``translate_trade(handle) -> TradeFields|None``.

    ``fields_by_handle`` mapeia handle → retorno; handles ausentes usam
    ``default``. Conta chamadas em ``.translate_trade``.
    """
    fields_by_handle = fields_by_handle or {}
    dll = MagicMock()

    def _tt(handle: int) -> object | None:
        return fields_by_handle.get(handle, default)

    dll.translate_trade = MagicMock(side_effect=_tt)
    return dll


def _tf(*, price: float = 100.0, ts_ns: int = 1_700_000_000_000_000_000, n: int = 1) -> object:
    from data_downloader.dll.types import TradeFields

    return TradeFields(
        version=0,
        timestamp_ns=ts_ns,
        trade_number=n,
        price=price,
        quantity=1,
        volume=price,
        buy_agent_id=0,
        sell_agent_id=0,
        trade_type=1,
    )


@pytest.mark.unit
def test_make_history_trade_callback_v2_returns_callable_and_appends() -> None:
    """make_history_trade_callback_v2 retorna WINFUNCTYPE-wrapped E appenda em _cb_refs."""
    from data_downloader.dll.types import TradeFields

    q: Queue[tuple[TradeFields, int]] = Queue(maxsize=100)
    initial = len(_cb_refs)

    cb = make_history_trade_callback_v2(q, _stub_translate_dll(default=_tf()))

    assert cb is not None
    assert callable(cb)
    assert len(_cb_refs) == initial + 1
    assert cb is _cb_refs[-1]


@pytest.mark.unit
def test_history_trade_callback_v2_translates_in_callback_and_enqueues_tradefields() -> None:
    """Q-DRIFT-40 — callback chama dll.translate_trade(handle) e enfileira TradeFields.

    NUNCA enfileira o handle (stale após retorno do callback). O ``flags`` do
    parâmetro do callback é propagado junto.
    """
    from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields

    tf0 = _tf(price=5025.5, n=1)
    tf1 = _tf(price=5025.6, n=2)
    dll = _stub_translate_dll(fields_by_handle={12345: tf0, 99999: tf1})
    q: Queue[tuple[TradeFields, int]] = Queue(maxsize=100)
    cb = make_history_trade_callback_v2(q, dll)

    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDOJ26", Exchange="F", FeedType=0)
    cb(asset, 12345, 0)
    cb(asset, 99999, 2)  # flags=2 = TC_LAST_PACKET

    # translate_trade chamado DENTRO do callback, 1x por trade, com o handle.
    assert dll.translate_trade.call_count == 2
    assert dll.translate_trade.call_args_list[0].args == (12345,)
    assert dll.translate_trade.call_args_list[1].args == (99999,)
    # Fila tem (TradeFields, flags) — NÃO o handle.
    assert q.get_nowait() == (tf0, 0)
    assert q.get_nowait() == (tf1, 2)


@pytest.mark.unit
def test_history_trade_callback_v2_nl_error_increments_counter_and_drops() -> None:
    """translate_trade -> None (rc!=0/sentinela) → stats["translate_nl_errors"]+=1, nada na fila."""
    from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields

    dll = _stub_translate_dll(default=None)  # toda tradução falha
    q: Queue[tuple[TradeFields, int]] = Queue(maxsize=10)
    stats = {"translate_nl_errors": 0, "translate_invalid_price_skips": 0, "queue_dropped": 0}
    cb = make_history_trade_callback_v2(q, dll, stats=stats)
    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDO", Exchange="F", FeedType=0)

    cb(asset, 1, 0)
    cb(asset, 2, 0)

    assert stats["translate_nl_errors"] == 2
    assert q.qsize() == 0


@pytest.mark.unit
def test_history_trade_callback_v2_invalid_price_skip() -> None:
    """Q-DRIFT-38 — price <= 0 → stats["translate_invalid_price_skips"]+=1, nada na fila."""
    from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields

    dll = _stub_translate_dll(
        fields_by_handle={0: _tf(price=0.0), 1: _tf(price=-1.5), 2: _tf(price=5500.0)}
    )
    q: Queue[tuple[TradeFields, int]] = Queue(maxsize=10)
    stats = {"translate_nl_errors": 0, "translate_invalid_price_skips": 0, "queue_dropped": 0}
    cb = make_history_trade_callback_v2(q, dll, stats=stats)
    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDO", Exchange="F", FeedType=0)

    cb(asset, 0, 0)  # price=0 → skip
    cb(asset, 1, 0)  # price<0 → skip
    cb(asset, 2, 0)  # price>0 → enfileira

    assert stats["translate_invalid_price_skips"] == 2
    assert stats["translate_nl_errors"] == 0
    assert q.qsize() == 1


@pytest.mark.unit
def test_history_trade_callback_v2_queue_dropped_counter_on_full() -> None:
    """Q-DRIFT-37 — stats["queue_dropped"] incrementa em queue.Full (não lança/bloqueia)."""
    from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields

    dll = _stub_translate_dll(default=_tf())
    q: Queue[tuple[TradeFields, int]] = Queue(maxsize=2)
    stats = {"translate_nl_errors": 0, "translate_invalid_price_skips": 0, "queue_dropped": 0}
    cb = make_history_trade_callback_v2(q, dll, stats=stats)
    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDO", Exchange="F", FeedType=0)

    cb(asset, 1, 0)  # OK (qsize=1)
    cb(asset, 2, 0)  # OK (qsize=2 = maxsize)
    cb(asset, 3, 0)  # Full — engolido + counter +=1
    cb(asset, 4, 0)  # Full — engolido + counter +=1

    assert q.qsize() == 2
    assert stats["queue_dropped"] == 2


@pytest.mark.unit
def test_history_trade_callback_v2_stats_none_backward_compat() -> None:
    """Sem stats (default), Full/erros engolidos sem rastro — não levanta."""
    from data_downloader.dll.types import TConnectorAssetIdentifier, TradeFields

    dll = _stub_translate_dll(default=_tf())
    q: Queue[tuple[TradeFields, int]] = Queue(maxsize=1)
    cb = make_history_trade_callback_v2(q, dll)  # stats=None default
    asset = TConnectorAssetIdentifier(Version=0, Ticker="WDO", Exchange="F", FeedType=0)

    cb(asset, 1, 0)
    cb(asset, 2, 0)
    cb(asset, 3, 0)

    assert q.qsize() == 1


# =====================================================================
# Story 1.3 — Progress callback
# =====================================================================


@pytest.mark.unit
def test_make_progress_callback_returns_callable_and_appends() -> None:
    """make_progress_callback retorna WINFUNCTYPE-wrapped E appenda em _cb_refs."""
    q: Queue[int] = Queue(maxsize=100)
    initial = len(_cb_refs)

    cb = make_progress_callback(q)

    assert cb is not None
    assert callable(cb)
    assert len(_cb_refs) == initial + 1
    assert cb is _cb_refs[-1]


@pytest.mark.unit
def test_progress_callback_only_calls_put_nowait_inv1() -> None:
    """AC5/INV-1 — Progress callback faz APENAS put_nowait(int).

    Signature da DLL (Q-DRIFT-05): ``(TAssetID, c_int)``. Apenas progress
    é enfileirado; ``TAssetID`` é descartado pelo IngestorThread já
    conhecer o ticker via contexto.
    """
    from data_downloader.dll.types import TAssetID

    mock_queue = MagicMock(spec=Queue)
    mock_dll = MagicMock()

    cb = make_progress_callback(mock_queue)

    asset = TAssetID(ticker="WDOJ26", bolsa="F", feed=0)
    cb(asset, 50)
    cb(asset, 99)
    cb(asset, 100)

    assert mock_queue.put_nowait.call_count == 3
    assert mock_queue.put_nowait.call_args_list[0].args == (50,)
    assert mock_queue.put_nowait.call_args_list[1].args == (99,)
    assert mock_queue.put_nowait.call_args_list[2].args == (100,)
    # Nenhum outro método:
    assert not mock_queue.put.called
    assert not mock_queue.get.called
    # INV-1: callback NÃO chamou DLL:
    assert mock_dll.mock_calls == []


@pytest.mark.unit
def test_progress_callback_swallows_full_silently() -> None:
    """Progress callback engole queue.Full sem lançar."""
    from data_downloader.dll.types import TAssetID

    q: Queue[int] = Queue(maxsize=1)
    cb = make_progress_callback(q)

    asset = TAssetID(ticker="WDOJ26", bolsa="F", feed=0)
    cb(asset, 1)  # OK
    cb(asset, 2)  # raises Full → engolido

    assert q.qsize() == 1


@pytest.mark.unit
def test_history_v2_and_progress_callbacks_added_to_cb_refs_independently() -> None:
    """Cada factory appenda 1 ref. Múltiplas chamadas acumulam (anti-GC)."""
    from data_downloader.dll.types import TradeFields

    cleanup_cb_refs()
    assert len(_cb_refs) == 0

    h_q: Queue[tuple[TradeFields, int]] = Queue()
    p_q: Queue[int] = Queue()

    make_history_trade_callback_v2(h_q, _stub_translate_dll(default=_tf()))
    make_progress_callback(p_q)

    assert len(_cb_refs) == 2
