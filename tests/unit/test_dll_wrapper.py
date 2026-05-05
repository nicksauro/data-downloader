"""tests/unit/test_dll_wrapper.py — Story 1.2.

Cobertura de ``data_downloader.dll.wrapper.ProfitDLL``:

- AC9: path resolution (arg / env / default).
- AC12: ``_verify_companions`` raises COMPANIONS_MISSING quando faltam.
- ``initialize_market_only`` raises UNSUPPORTED_PLATFORM em não-Windows.
- AC2/AC11: Mock ``WinDLL`` — ``SetEnabledLogToDebug(0)`` ANTES de
  ``DLLInitializeMarketLogin`` que recebe 11 args.
- AC7: retorno < 0 raises DLLInitError.
- AC5/Q-AMB-01: ``wait_market_connected`` aceita result ∈ {2, 4} para
  conn_type=2.
- AC5: timeout retorna False.
- AC6/Q-AMB-02: ``finalize`` tenta DLLFinalize → fallback Finalize.
- AC4: ``finalize`` NÃO chama ``_cb_refs.clear()``.
- Context manager.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from data_downloader.dll import callbacks as cb_module
from data_downloader.dll.errors import DLLInitError
from data_downloader.dll.types import (
    LOGIN,
    MARKET_CONNECTED,
    MARKET_DATA,
    MARKET_LOGIN,
    MARKET_WAITING,
    ROTEAMENTO,
)
from data_downloader.dll.wrapper import DEFAULT_DLL_PATH, ProfitDLL


@pytest.fixture(autouse=True)
def _isolate_cb_refs() -> Iterator[None]:
    """Isola ``_cb_refs`` entre testes."""
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


@pytest.fixture(autouse=True)
def _isolate_cwd() -> Iterator[None]:
    """Isola ``cwd`` entre testes (Q-DRIFT-10).

    ``initialize_market_only`` agora chama ``os.chdir`` antes de ``WinDLL``.
    Mesmo com ``WinDLL`` mockado, o ``os.chdir`` é real (chamado direto). Sem
    isolamento, um teste que mocka init mas não restaura cwd vaza o estado
    para os próximos testes.
    """
    original = Path.cwd()
    try:
        yield
    finally:
        # Restauração best-effort: se algum teste apagou o cwd original,
        # não temos como restaurar (raro/impossível em fluxo normal).
        with contextlib.suppress(OSError):
            os.chdir(str(original))


# =====================================================================
# AC9 — Path resolution
# =====================================================================


@pytest.mark.unit
def test_path_resolution_explicit_arg_wins(tmp_path: Path) -> None:
    """Arg ``dll_path`` tem precedência sobre env e default."""
    explicit = tmp_path / "custom.dll"
    explicit.touch()
    dll = ProfitDLL(dll_path=explicit)
    assert dll._dll_path == explicit.resolve()


@pytest.mark.unit
def test_path_resolution_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env ``PROFITDLL_PATH`` usado quando arg ausente."""
    env_path = tmp_path / "env.dll"
    env_path.touch()
    monkeypatch.setenv("PROFITDLL_PATH", str(env_path))
    dll = ProfitDLL()
    assert dll._dll_path == env_path.resolve()


@pytest.mark.unit
def test_path_resolution_default_when_no_arg_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default ``DEFAULT_DLL_PATH`` quando nem arg nem env presentes."""
    monkeypatch.delenv("PROFITDLL_PATH", raising=False)
    dll = ProfitDLL()
    assert dll._dll_path == DEFAULT_DLL_PATH.resolve()


# =====================================================================
# AC12 — verify companions
# =====================================================================


@pytest.mark.unit
def test_verify_companions_raises_when_path_missing(tmp_path: Path) -> None:
    """Path inexistente → DLLInitError(COMPANIONS_MISSING)."""
    bogus = tmp_path / "does-not-exist" / "ProfitDLL.dll"
    dll = ProfitDLL(dll_path=bogus)
    with pytest.raises(DLLInitError) as exc:
        dll._verify_companions()
    assert exc.value.name == "COMPANIONS_MISSING"
    assert exc.value.code == -1


# =====================================================================
# Platform check — UNSUPPORTED_PLATFORM em Linux/Mac
# =====================================================================


@pytest.mark.unit
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="UNSUPPORTED_PLATFORM só dispara em não-Windows",
)
def test_initialize_market_only_raises_on_non_windows(tmp_path: Path) -> None:
    """Em Linux/Mac, init raises UNSUPPORTED_PLATFORM (testes mockados ok)."""
    # Para chegar até a checagem de plataforma, _verify_companions tem que
    # passar — usamos mock dele.
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    with (
        patch.object(dll, "_verify_companions"),
        pytest.raises(DLLInitError) as exc,
    ):
        dll.initialize_market_only("k", "u", "p")
    assert exc.value.name == "UNSUPPORTED_PLATFORM"


# =====================================================================
# AC2 + AC11 — init com mock de WinDLL
# =====================================================================


def _make_mock_dll_module() -> tuple[Any, Any]:
    """Helper: monta MagicMock de WinDLL retornando um mock_dll instance.

    Retorna ``(windll_class_mock, dll_instance_mock)`` — ambos passíveis
    de inspeção via ``mock_calls``.
    """
    dll_instance = MagicMock(name="DLLInstance")
    dll_instance.SetEnabledLogToDebug = MagicMock(return_value=0)
    dll_instance.DLLInitializeMarketLogin = MagicMock(return_value=0)
    dll_instance.DLLFinalize = MagicMock(return_value=0)
    dll_instance.GetDLLVersion = MagicMock(return_value="4.0.0.34")
    windll_mock = MagicMock(return_value=dll_instance)
    return windll_mock, dll_instance


@pytest.mark.unit
def test_initialize_market_only_calls_set_enabled_log_to_debug_before_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC11 — ``SetEnabledLogToDebug(0)`` chamado ANTES de DLLInitializeMarketLogin."""
    # Forçamos sys.platform = win32 para passar checagem; mockamos WinDLL.
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    # Bypass companions check (testado separadamente).
    with (
        patch.object(dll, "_verify_companions"),
        patch.dict(
            "sys.modules",
            {"ctypes": __import__("ctypes")},  # garante ctypes carregado
        ),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS")

    # Ordem: SetEnabledLogToDebug ANTES de DLLInitializeMarketLogin.
    # mock_calls do dll_instance preserva ordem.
    method_names = [c[0] for c in dll_instance.method_calls]
    assert "SetEnabledLogToDebug" in method_names
    assert "DLLInitializeMarketLogin" in method_names
    assert method_names.index("SetEnabledLogToDebug") < method_names.index(
        "DLLInitializeMarketLogin"
    )


@pytest.mark.unit
def test_initialize_market_only_passes_11_args_no_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 — DLLInitializeMarketLogin recebe 11 args, NENHUM ``None``."""
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS")

    # Verifica chamada de DLLInitializeMarketLogin.
    init_call = dll_instance.DLLInitializeMarketLogin.call_args
    assert init_call is not None, "DLLInitializeMarketLogin não foi chamado"
    args = init_call.args
    assert len(args) == 11, f"Esperado 11 args, recebido {len(args)}: {args}"
    # Nenhum dos 11 é None (Q11-E):
    for i, a in enumerate(args):
        assert a is not None, f"arg[{i}] é None — viola Q11-E (slots None corrompem)"


@pytest.mark.unit
def test_initialize_market_only_raises_dllinit_error_on_negative_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7 — retorno < 0 raises DLLInitError com decode."""
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()
    dll_instance.DLLInitializeMarketLogin.return_value = -2147483393  # NL_INVALID_ARGS

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
        pytest.raises(DLLInitError) as exc,
    ):
        dll.initialize_market_only("KEY", "BADUSER", "BADPASS")
    assert exc.value.code == -2147483393
    assert exc.value.name == "NL_INVALID_ARGS"


# =====================================================================
# Story 1.7b-followup smoke 5 — register_extra_callbacks default OFF
# =====================================================================


@pytest.mark.unit
def test_initialize_market_only_skips_extra_callbacks_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default ``register_extra_callbacks=False`` NÃO chama _register_default_callbacks.

    Story 1.7b-followup smoke 5: 14 NoopCallback registrados via SetXxxCallback
    causaram access violations + stack overflow durante wait_market_connected
    (signatures genéricas vs. signatures DIFERENTES esperadas por cada
    Set*Callback). Fix conservador: registro EXTRA é opt-in.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, _dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch.object(dll, "_register_default_callbacks") as mock_register,
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS")

    # Default: opt-in NÃO acionado — método não foi chamado.
    mock_register.assert_not_called()


@pytest.mark.unit
def test_initialize_market_only_registers_extra_callbacks_when_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``register_extra_callbacks=True`` chama _register_default_callbacks (opt-in)."""
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, _dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch.object(dll, "_register_default_callbacks") as mock_register,
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS", register_extra_callbacks=True)

    # Opt-in acionado — método foi chamado uma vez.
    mock_register.assert_called_once()


@pytest.mark.unit
def test_initialize_market_only_skips_extra_callbacks_on_negative_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Erro no init NÃO deve chamar _register_default_callbacks (raise antes)."""
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()
    dll_instance.DLLInitializeMarketLogin.return_value = -2147483393

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch.object(dll, "_register_default_callbacks") as mock_register,
        patch("ctypes.WinDLL", windll_mock, create=True),
        pytest.raises(DLLInitError),
    ):
        # Mesmo com opt-in, erro no init impede registro extra.
        dll.initialize_market_only("KEY", "USER", "PASS", register_extra_callbacks=True)
    mock_register.assert_not_called()


# =====================================================================
# Story 1.7d — minimal_handshake espelho ESTRITO do probe (Q-DRIFT-12)
# =====================================================================


@pytest.mark.unit
def test_initialize_minimal_handshake_passes_none_in_slots_4_6_7_8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``minimal_handshake=True`` passa ``None`` literal nos slots 4/6/7/8.

    Story 1.7d (corrige bug 1.7c): espelho EXATO de ``scripts/probe_init.py``
    (linhas 239-251) e exemplo Nelogica ``main.py:742-743``. Slots
    ``newTradeCallback`` (4), ``newHistoryCallback`` (6), ``priceBookCallback``
    (7) e ``offerBookCallback`` (8) recebem ``None`` LITERAL — refuta
    empiricamente Q11-E ("JAMAIS None") porque o probe conecta em <3s
    com essa configuração.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS", minimal_handshake=True)

    init_call = dll_instance.DLLInitializeMarketLogin.call_args
    assert init_call is not None, "DLLInitializeMarketLogin não foi chamado"
    args = init_call.args
    assert len(args) == 11, f"Esperado 11 args, recebido {len(args)}: {args}"
    # Slots 0-2 = credenciais (c_wchar_p) — não-None.
    for i in range(3):
        assert args[i] is not None, f"credencial arg[{i}] não pode ser None"
    # Slot 3 = state callback REAL — não-None (sempre).
    assert args[3] is not None, "state callback (slot 3) não pode ser None"
    # Slots 4, 6, 7, 8 = None LITERAL (espelho probe Story 1.7d).
    for i in (4, 6, 7, 8):
        assert args[i] is None, (
            f"minimal_handshake (Story 1.7d): slot {i} esperado None, " f"recebido {args[i]!r}"
        )


@pytest.mark.unit
def test_initialize_minimal_handshake_passes_real_callbacks_in_slots_5_9_10(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``minimal_handshake=True`` passa callbacks REAIS nos slots 5/9/10.

    Story 1.7d (Q-DRIFT-12): probe canônico (``scripts/probe_init.py``
    L239-251) e exemplo Nelogica (``main.py:742-743``) ambos passam
    callbacks reais nos slots ``newDailyCallback`` (5), ``progressCallBack``
    (9) e ``tinyBookCallBack`` (10). Hipótese: servidor Nelogica exige
    callback funcional nesses 3 slots para promover MARKET_DATA → result=4.

    Verifica que slots 5/9/10:
      - NÃO são ``None``.
      - Têm signatures ctypes ``TDailyCallback`` / ``TProgressCallback`` /
        ``TTinyBookCallback`` (todas com ``TAssetID`` por valor — Q-DRIFT-05).
    """
    from data_downloader.dll.types import (
        TDailyCallback,
        TProgressCallback,
        TTinyBookCallback,
    )

    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS", minimal_handshake=True)

    init_call = dll_instance.DLLInitializeMarketLogin.call_args
    assert init_call is not None, "DLLInitializeMarketLogin não foi chamado"
    args = init_call.args
    assert len(args) == 11, f"Esperado 11 args, recebido {len(args)}: {args}"

    # Slots 5/9/10 NÃO são None.
    for i in (5, 9, 10):
        assert args[i] is not None, (
            f"minimal_handshake (Story 1.7d / Q-DRIFT-12): slot {i} deve ser "
            f"callback REAL, recebido None"
        )

    # Slot 5 = TDailyCallback. Verificamos via isinstance() do tipo retornado
    # pelo factory — ctypes WINFUNCTYPE retorna instâncias do próprio funtype.
    assert isinstance(
        args[5], TDailyCallback
    ), f"slot 5 deve ser TDailyCallback; recebido {type(args[5]).__name__}"
    # Slot 9 = TProgressCallback.
    assert isinstance(
        args[9], TProgressCallback
    ), f"slot 9 deve ser TProgressCallback; recebido {type(args[9]).__name__}"
    # Slot 10 = TTinyBookCallback.
    assert isinstance(
        args[10], TTinyBookCallback
    ), f"slot 10 deve ser TTinyBookCallback; recebido {type(args[10]).__name__}"


@pytest.mark.unit
def test_initialize_minimal_handshake_skips_set_enabled_log_to_debug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``minimal_handshake=True`` NÃO chama ``SetEnabledLogToDebug``.

    Story 1.7c: probe canônico e exemplo Nelogica ``main.py`` NÃO chamam
    ``SetEnabledLogToDebug`` em lugar nenhum. Hipótese de causa-raiz #2
    para Q-DRIFT-02 — a chamada pode estar setando flag interna que afeta
    a promoção do market data.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS", minimal_handshake=True)

    # SetEnabledLogToDebug NÃO deve aparecer nas chamadas registradas.
    method_names = [c[0] for c in dll_instance.method_calls]
    assert "SetEnabledLogToDebug" not in method_names, (
        f"minimal_handshake: SetEnabledLogToDebug NÃO deve ser chamado; "
        f"chamadas: {method_names}"
    )
    # DLLInitializeMarketLogin DEVE ter sido chamado (init em si funciona).
    assert "DLLInitializeMarketLogin" in method_names


@pytest.mark.unit
def test_initialize_minimal_handshake_default_false_preserves_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default ``minimal_handshake=False``: comportamento legacy preservado.

    Story 1.7c: zero risco de regressão para callers existentes — mesma
    sequência (SetEnabledLogToDebug ANTES de init; 7 NoopCallback nos
    slots não-state, sem ``None``).
    """
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    # Não passa minimal_handshake — usa default False.
    with (
        patch.object(dll, "_verify_companions"),
        patch("ctypes.WinDLL", windll_mock, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS")

    method_names = [c[0] for c in dll_instance.method_calls]
    # Default DEVE chamar SetEnabledLogToDebug ANTES do init.
    assert (
        "SetEnabledLogToDebug" in method_names
    ), "default path deve manter SetEnabledLogToDebug (legacy comportamento)"
    assert method_names.index("SetEnabledLogToDebug") < method_names.index(
        "DLLInitializeMarketLogin"
    )
    # Default: 11 args, NENHUM None (NoopCallback nos 7 slots).
    init_call = dll_instance.DLLInitializeMarketLogin.call_args
    args = init_call.args
    assert len(args) == 11
    for i, a in enumerate(args):
        assert a is not None, f"default path: arg[{i}] não pode ser None (Q11-E legacy preservado)"


# =====================================================================
# AC5 / Q-AMB-01 — wait_market_connected
# =====================================================================


def _seed_state_queue(dll: ProfitDLL, pairs: list[tuple[int, int]]) -> None:
    for p in pairs:
        dll._state_queue.put(p)


@pytest.mark.unit
def test_wait_market_connected_returns_true_with_canonical_sequence() -> None:
    """Sequência canônica (0,0)+(1,2)+(2,4)+(3,0) → True após (2,4)."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    _seed_state_queue(
        dll,
        [
            (LOGIN, 0),
            (ROTEAMENTO, 2),
            (MARKET_DATA, MARKET_CONNECTED),  # =4
            (MARKET_LOGIN, 0),
        ],
    )
    assert dll.wait_market_connected(timeout=5) is True


@pytest.mark.unit
def test_wait_market_connected_does_not_accept_market_waiting_result_2() -> None:
    """Story 1.7b-followup — apenas result=4 conta como connected.

    Refuta Q-AMB-01: ``MARKET_WAITING=2`` é estado intermediário, NÃO
    "connected" (alinhado a manual + exemplo Nelogica main.py L223).
    Sem ``(MARKET_DATA, 4)`` na fila, ``wait`` deve atingir timeout.
    """
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    _seed_state_queue(
        dll,
        [
            (LOGIN, 0),
            (ROTEAMENTO, 2),
            (MARKET_DATA, MARKET_WAITING),  # =2 — NÃO basta para connected
        ],
    )
    # Drena 3 estados, nenhum é result=4 → timeout retorna False.
    assert dll.wait_market_connected(timeout=1) is False


@pytest.mark.unit
def test_wait_market_connected_returns_false_on_timeout() -> None:
    """Sem MARKET_DATA na fila dentro do timeout → False (sem raise)."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    _seed_state_queue(dll, [(LOGIN, 0), (ROTEAMENTO, 2)])  # falta market_data
    # timeout=1s — testes não devem demorar. Drena os 2 e bloqueia até timeout.
    assert dll.wait_market_connected(timeout=1) is False


@pytest.mark.unit
def test_wait_market_connected_returns_false_with_zero_timeout_and_empty_queue() -> None:
    """Timeout=0 + queue vazia → False imediato (sem espera)."""
    dll = ProfitDLL(dll_path=Path("/fake.dll"))
    assert dll.wait_market_connected(timeout=0) is False


# =====================================================================
# AC6 / Q-AMB-02 — finalize fallback
# =====================================================================


@pytest.mark.unit
def test_finalize_calls_dllfinalize_first(tmp_path: Path) -> None:
    """Q-AMB-02 — finalize tenta DLLFinalize primeiro."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.DLLFinalize = MagicMock(return_value=0)
    dll._dll = mock_dll

    dll.finalize()

    mock_dll.DLLFinalize.assert_called_once()
    # Não tentou Finalize (porque DLLFinalize existiu).
    assert not mock_dll.Finalize.called
    assert dll._dll is None


@pytest.mark.unit
def test_finalize_falls_back_to_finalize_when_dllfinalize_missing(
    tmp_path: Path,
) -> None:
    """Q-AMB-02 — AttributeError em DLLFinalize → fallback Finalize."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")

    # MagicMock(spec=...) restringe attrs. Aqui usamos um objeto plain
    # com APENAS Finalize (sem DLLFinalize).
    class _OldDLL:
        def __init__(self) -> None:
            self.finalize_called = False

        def Finalize(self) -> int:  # noqa: N802  ProfitDLL exposes this PascalCase name
            self.finalize_called = True
            return 0

    old_dll = _OldDLL()
    dll._dll = old_dll

    dll.finalize()

    assert old_dll.finalize_called is True
    assert dll._dll is None


@pytest.mark.unit
def test_finalize_no_op_when_dll_is_none(tmp_path: Path) -> None:
    """``finalize()`` em DLL não inicializada é no-op (não levanta)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll._dll is None
    dll.finalize()  # no raise
    assert dll._dll is None


# =====================================================================
# AC4 — finalize NÃO limpa _cb_refs
# =====================================================================


@pytest.mark.unit
def test_finalize_does_not_clear_cb_refs(tmp_path: Path) -> None:
    """AC4 — ConnectorThread pode ainda referenciar; clear = crash."""
    # Popula _cb_refs com callbacks reais.
    q: Queue[tuple[int, int]] = Queue()
    cb_module.make_state_callback(q)
    cb_module.make_noop_callback(
        __import__("data_downloader.dll.types", fromlist=["TStateCallback"]).TStateCallback
    )
    initial_count = len(cb_module._cb_refs)
    assert initial_count == 2

    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.DLLFinalize = MagicMock(return_value=0)
    dll._dll = mock_dll

    dll.finalize()

    # AC4 — _cb_refs INALTERADA.
    assert len(cb_module._cb_refs) == initial_count


# =====================================================================
# Context manager
# =====================================================================


@pytest.mark.unit
def test_context_manager_calls_finalize_on_exit(tmp_path: Path) -> None:
    """``with ProfitDLL() as dll`` chama finalize() em exit se inicializou."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.DLLFinalize = MagicMock(return_value=0)

    with dll as ctx_dll:
        assert ctx_dll is dll
        # Simula init.
        dll._dll = mock_dll

    # __exit__ deve ter chamado finalize → DLLFinalize.
    mock_dll.DLLFinalize.assert_called_once()
    assert dll._dll is None


@pytest.mark.unit
def test_context_manager_no_finalize_when_not_initialized(tmp_path: Path) -> None:
    """Sem init, __exit__ é no-op (não tenta chamar nada)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    with dll as ctx_dll:
        assert ctx_dll is dll
        # Sem dll._dll set.
    # No raise — __exit__ silencioso.


# =====================================================================
# AC13 — dll_version property
# =====================================================================


@pytest.mark.unit
def test_dll_version_returns_unknown_when_dll_not_initialized(tmp_path: Path) -> None:
    """dll_version sem init → 'unknown' (sem cachear)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    assert dll.dll_version == "unknown"
    # Não cacheou — próxima chamada também tenta resolver:
    assert dll._dll_version_cache is None


@pytest.mark.unit
def test_dll_version_cached_after_first_call(tmp_path: Path) -> None:
    """Após init, primeira chamada resolve via GetDLLVersion + cacheia."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")
    mock_dll = MagicMock()
    mock_dll.GetDLLVersion = MagicMock(return_value="4.0.0.34")
    dll._dll = mock_dll

    v1 = dll.dll_version
    v2 = dll.dll_version

    assert v1 == "4.0.0.34"
    assert v2 == "4.0.0.34"
    # GetDLLVersion chamado UMA vez (cache).
    assert mock_dll.GetDLLVersion.call_count == 1


@pytest.mark.unit
def test_dll_version_returns_unknown_on_attribute_error(tmp_path: Path) -> None:
    """Se GetDLLVersion não existe → 'unknown' + warn (não levanta)."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")

    class _DLLWithoutVersion:
        pass

    dll._dll = _DLLWithoutVersion()
    assert dll.dll_version == "unknown"
    assert dll._dll_version_cache == "unknown"


# =====================================================================
# state alias resolution (AC8 logger)
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    ("conn_type", "result", "expected_alias"),
    [
        (LOGIN, 0, "LOGIN_CONNECTED"),
        (ROTEAMENTO, 2, "ROTEAMENTO_CONNECTED"),
        (MARKET_DATA, MARKET_WAITING, "MARKET_WAITING"),
        (MARKET_DATA, MARKET_CONNECTED, "MARKET_CONNECTED"),
        (MARKET_LOGIN, 0, "MARKET_LOGIN_OK"),
    ],
)
def test_resolve_state_alias_canonical_pairs(
    conn_type: int, result: int, expected_alias: str
) -> None:
    """Pares canônicos resolvem para alias humano correto."""
    assert ProfitDLL._resolve_state_alias(conn_type, result) == expected_alias


@pytest.mark.unit
def test_resolve_state_alias_unknown_pair_falls_back() -> None:
    """Par desconhecido → fallback ``CONN_NAME/result``."""
    # MARKET_DATA com result inesperado (e.g., 99) não está em STATE_CODE_ALIAS.
    alias = ProfitDLL._resolve_state_alias(MARKET_DATA, 99)
    assert alias == "MARKET_DATA/99"


@pytest.mark.unit
def test_resolve_state_alias_unknown_conn_type() -> None:
    """conn_type desconhecido → 'UNKNOWN_<type>/<result>'."""
    alias = ProfitDLL._resolve_state_alias(99, 5)
    assert alias == "UNKNOWN_99/5"


# =====================================================================
# Q-DRIFT-10 — chdir antes de WinDLL + restauração em finalize/__exit__
# =====================================================================
#
# Probe ``scripts/probe_init.py`` (commit 3ef7699) provou que ProfitDLL
# precisa que cwd seja a pasta da DLL para achar companions (libssl,
# libcrypto), arquivos .dat e escrever Logs/. Sem chdir, MARKET_DATA
# trava em result=1 (CONNECTING) e nunca chega a result=4. Tests abaixo
# garantem que ``initialize_market_only`` chama ``os.chdir(dll_path.parent)``
# ANTES de ``WinDLL(...)`` e restaura o cwd em finalize / __exit__ /
# path de erro.


@pytest.mark.unit
def test_init_changes_cwd_to_dll_dir_before_windll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q-DRIFT-10 — ``os.chdir(dll_dir)`` é chamado ANTES de ``WinDLL(...)``.

    Espelha receita do probe ``scripts/probe_init.py`` (commit 3ef7699)
    que conectou em ~1.82s usando exatamente esse padrão. Nosso wrapper
    sem chdir trava em MARKET_CONNECTING — fix root cause Q-DRIFT-10.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    # Mock ``os.chdir`` para gravar a sequência de chamadas SEM mudar
    # cwd real. Captura também a relação temporal com ``WinDLL`` via
    # ``call_order`` compartilhada.
    call_order: list[str] = []

    def _record_chdir(path: str) -> None:
        call_order.append(f"chdir:{path}")

    def _record_windll(_path: str) -> Any:
        call_order.append("WinDLL")
        instance = MagicMock(name="DLLInstance")
        instance.SetEnabledLogToDebug = MagicMock(return_value=0)
        instance.DLLInitializeMarketLogin = MagicMock(return_value=0)
        instance.DLLFinalize = MagicMock(return_value=0)
        return instance

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)
    expected_dir = fake_dll_path.parent.resolve()

    with (
        patch.object(dll, "_verify_companions"),
        patch("data_downloader.dll.wrapper.os.chdir", side_effect=_record_chdir),
        patch("ctypes.WinDLL", _record_windll, create=True),
    ):
        dll.initialize_market_only("KEY", "USER", "PASS")

    # Pelo menos um chdir disparado, e DEVE preceder a chamada WinDLL.
    chdir_events = [c for c in call_order if c.startswith("chdir:")]
    assert chdir_events, f"os.chdir não foi chamado; call_order={call_order}"
    first_chdir_idx = call_order.index(chdir_events[0])
    windll_idx = call_order.index("WinDLL")
    assert (
        first_chdir_idx < windll_idx
    ), f"os.chdir DEVE preceder WinDLL (Q-DRIFT-10); call_order={call_order}"
    # E o destino do chdir é a pasta da DLL.
    assert (
        chdir_events[0] == f"chdir:{expected_dir}"
    ), f"chdir destino esperado {expected_dir}; got {chdir_events[0]}"
    # Estado interno: ``_original_cwd`` permanece setado APÓS init bem-sucedido
    # (só é limpo em finalize / __exit__ / path de erro).
    assert dll._original_cwd is not None, (
        "_original_cwd deve permanecer setado após init OK para permitir " "restauração em finalize"
    )


@pytest.mark.unit
def test_finalize_restores_cwd(tmp_path: Path) -> None:
    """Q-DRIFT-10 — ``finalize`` restaura cwd salvo em ``_original_cwd``.

    Após init bem-sucedido o cwd do processo aponta para a pasta da DLL.
    ``finalize`` (e ``__exit__``) DEVE devolver o cwd original que existia
    antes do init para não vazar efeito colateral processo-wide.
    """
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")

    # Simula estado pós-init: DLL atribuída + cwd original salvo.
    mock_dll = MagicMock()
    mock_dll.DLLFinalize = MagicMock(return_value=0)
    dll._dll = mock_dll
    saved_cwd = tmp_path / "saved_cwd"
    saved_cwd.mkdir()
    dll._original_cwd = saved_cwd

    chdir_calls: list[str] = []
    with patch(
        "data_downloader.dll.wrapper.os.chdir",
        side_effect=lambda p: chdir_calls.append(str(p)),
    ):
        dll.finalize()

    # ``_restore_cwd_if_changed`` chamou os.chdir com saved_cwd.
    assert (
        str(saved_cwd) in chdir_calls
    ), f"finalize deve chamar os.chdir(saved_cwd); calls={chdir_calls}"
    # ``_original_cwd`` zerado após restaurar (idempotência de futuras chamadas).
    assert dll._original_cwd is None
    # DLL real foi finalizada também.
    mock_dll.DLLFinalize.assert_called_once()
    assert dll._dll is None


@pytest.mark.unit
def test_init_restores_cwd_on_negative_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q-DRIFT-10 — erro NL_* no init restaura cwd antes de levantar.

    Se ``DLLInitializeMarketLogin`` retorna < 0, o caller fica com
    ``DLLInitError`` e ``self._dll = None`` (cleanup parcial). O cwd DEVE
    ser restaurado também — caller não recebe ``self`` em estado
    finalizável (``self._dll is None`` faz ``finalize`` virar no-op).
    """
    monkeypatch.setattr(sys, "platform", "win32")
    windll_mock, dll_instance = _make_mock_dll_module()
    dll_instance.DLLInitializeMarketLogin.return_value = -2147483393  # NL_INVALID_ARGS

    fake_dll_path = tmp_path / "ProfitDLL.dll"
    fake_dll_path.touch()
    dll = ProfitDLL(dll_path=fake_dll_path)

    chdir_calls: list[str] = []
    with (
        patch.object(dll, "_verify_companions"),
        patch(
            "data_downloader.dll.wrapper.os.chdir",
            side_effect=lambda p: chdir_calls.append(str(p)),
        ),
        patch("ctypes.WinDLL", windll_mock, create=True),
        pytest.raises(DLLInitError),
    ):
        dll.initialize_market_only("KEY", "BAD", "BAD")

    # Pelo menos 2 chdir: 1 inicial (para dll_dir) + 1 restauração.
    assert len(chdir_calls) >= 2, f"Esperado pelo menos 2 chdir (init + restore); got {chdir_calls}"
    # Último chdir é a restauração para o cwd original.
    # ``_original_cwd`` zerado após restaurar.
    assert dll._original_cwd is None


@pytest.mark.unit
def test_restore_cwd_if_changed_is_idempotent(tmp_path: Path) -> None:
    """Helper ``_restore_cwd_if_changed`` é seguro de chamar repetidamente."""
    dll = ProfitDLL(dll_path=tmp_path / "fake.dll")

    # Sem _original_cwd setado: no-op (não chama os.chdir).
    chdir_calls: list[str] = []
    with patch(
        "data_downloader.dll.wrapper.os.chdir",
        side_effect=lambda p: chdir_calls.append(str(p)),
    ):
        dll._restore_cwd_if_changed()
        dll._restore_cwd_if_changed()
    assert chdir_calls == [], "Sem _original_cwd, _restore_cwd_if_changed não deve chamar os.chdir"

    # Com _original_cwd setado: 1 chdir, depois zerado → próximas chamadas no-op.
    saved = tmp_path / "saved"
    saved.mkdir()
    dll._original_cwd = saved
    with patch(
        "data_downloader.dll.wrapper.os.chdir",
        side_effect=lambda p: chdir_calls.append(str(p)),
    ):
        dll._restore_cwd_if_changed()
        dll._restore_cwd_if_changed()  # 2ª chamada deve ser no-op
        dll._restore_cwd_if_changed()  # 3ª chamada deve ser no-op
    assert chdir_calls == [str(saved)], f"Esperado exatamente 1 chdir(saved); got {chdir_calls}"
    assert dll._original_cwd is None
