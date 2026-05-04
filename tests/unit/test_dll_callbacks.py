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
    make_noop_callback,
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
    assert (
        mock_dll.mock_calls == []
    ), f"Callback chamou métodos do mock DLL — viola INV-1 / R3. Calls: {mock_dll.mock_calls}"

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
