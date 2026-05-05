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

import sys
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
def _isolate_cb_refs() -> object:
    """Isola ``_cb_refs`` entre testes."""
    cb_module.cleanup_cb_refs()
    yield
    cb_module.cleanup_cb_refs()


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
