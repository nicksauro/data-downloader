"""Property tests — Invariante "no _InternalError leak" (Story 2.11 ADR-011).

Hypothesis verifica que para QUALQUER cenário sintético, funções públicas
em ``public_api/`` NUNCA propagam ``_InternalError`` (ou subclasses).

Estratégia:

1. Estratégia gera tuplas ``(internal_subclass, message, context)``.
2. Sintetizamos uma "função pública" decorada com ``@translate_internal``
   que raise a exception interna.
3. Asserção: exception capturada é instância de ``DataDownloaderError``
   E NÃO de ``_InternalError`` (no-leak).

Marker ``_internal=True`` permite filtrar dinamicamente subclasses internas
sem importar cada nome — future-proof a novas subclasses.

Aria audit (Story 2.11 AC2):
- Garante a fronteira ADR-011 §Regras de forma exaustiva (não só
  parametrizada — Hypothesis explora 100 examples por default).
- Reforça o adapter como single point of translation.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from data_downloader._internal.exception_adapter import translate_internal
from data_downloader._internal.exceptions import (
    _ChunkRetryExhausted,
    _ChunkTimedOut,
    _DLLDisconnected,
    _DLLProbeFailed,
    _FormatParseError,
    _InternalError,
    _OperationCancelled,
    _QueueOverflow,
    _StateTransitionError,
)
from data_downloader.public_api.exceptions import DataDownloaderError

_INTERNAL_SUBCLASSES = [
    _ChunkRetryExhausted,
    _ChunkTimedOut,
    _DLLDisconnected,
    _DLLProbeFailed,
    _FormatParseError,
    _OperationCancelled,
    _QueueOverflow,
    _StateTransitionError,
]


@given(
    cls=st.sampled_from(_INTERNAL_SUBCLASSES),
    msg=st.text(min_size=0, max_size=200),
    ctx_keys=st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=5, unique=True),
    ctx_vals=st.lists(
        st.one_of(st.integers(), st.text(max_size=50), st.booleans()),
        min_size=0,
        max_size=5,
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_no_internal_leak_property(
    cls: type[_InternalError],
    msg: str,
    ctx_keys: list[str],
    ctx_vals: list[object],
) -> None:
    """Para QUALQUER (subclass, message, context), translate_internal
    NUNCA propaga _InternalError.
    """
    context = dict(zip(ctx_keys, ctx_vals[: len(ctx_keys)], strict=False))

    @translate_internal
    def _public_entry() -> None:
        raise cls(msg, context=context)

    try:
        _public_entry()
    except DataDownloaderError as exc:
        # OK — pública, conforme contrato.
        assert not isinstance(
            exc, _InternalError
        ), f"LEAK detectado: {type(exc).__name__} ainda é _InternalError"
    except _InternalError as exc:
        msg_err = (
            f"LEAK CRÍTICO: _InternalError ({type(exc).__name__}) propagou "
            f"através de @translate_internal — invariante ADR-011 violada."
        )
        raise AssertionError(msg_err) from exc


@given(
    msg=st.text(min_size=0, max_size=100),
)
@settings(max_examples=50)
def test_unmapped_subclass_still_translates_safely(msg: str) -> None:
    """Subclasse adicionada futuramente sem mapping update vira DataDownloaderError genérico.

    Defesa em profundidade: garante que evolução de _internal sem update
    do adapter NÃO causa leak.
    """

    class _FutureSubclass(_InternalError):  # noqa: N818  test fixture
        """Subclasse hipotética ainda não mapeada no adapter."""

    @translate_internal
    def _entry() -> None:
        raise _FutureSubclass(msg)

    try:
        _entry()
    except DataDownloaderError as exc:
        assert not isinstance(exc, _InternalError)
        # Vira genérico (DataDownloaderError direto, não subclasse específica).
        assert type(exc).__name__ == "DataDownloaderError"


@given(cls=st.sampled_from(_INTERNAL_SUBCLASSES))
@settings(max_examples=20)
def test_internal_marker_present_on_all_subclasses(cls: type[_InternalError]) -> None:
    """Marker ``_internal=True`` está em TODAS subclasses (herança)."""
    assert getattr(cls, "_internal", False) is True
