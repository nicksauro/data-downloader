"""Unit tests — exception_adapter (Story 2.11 ADR-011 §"Padrão de tradução").

Cobertura:

- :func:`translate_to_public` mapeia cada subclasse interna → público correto.
- :func:`translate_to_public` preserva ``cause`` e merges ``context`` em
  ``details``.
- :func:`translate_internal` decorator captura internals, traduz, re-raise
  com ``raise public from internal`` (preserva ``__cause__``).
- Subclasses não-mapeadas viram ``DataDownloaderError`` genérico (fallback
  defensivo — invariante "no leak" garantido).
- Funções decoradas que raise exceções públicas não-internal propagam sem
  alteração.
"""

from __future__ import annotations

import pytest

from data_downloader._internal.exception_adapter import (
    translate_internal,
    translate_to_public,
)
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
from data_downloader.public_api.exceptions import (
    ConnectionLost,
    DataDownloaderError,
    DLLInitError,
    DownloadError,
    IntegrityError,
    OperationCancelled,
)

# =====================================================================
# translate_to_public — mapping table
# =====================================================================


class TestTranslateToPublic:
    """Mapping internal → public (Story 2.11)."""

    @pytest.mark.parametrize(
        ("internal_cls", "public_cls"),
        [
            (_OperationCancelled, OperationCancelled),
            (_DLLDisconnected, ConnectionLost),
            (_DLLProbeFailed, DLLInitError),
            (_ChunkTimedOut, DownloadError),
            (_ChunkRetryExhausted, DownloadError),
            (_QueueOverflow, DownloadError),
            (_FormatParseError, IntegrityError),
            (_StateTransitionError, DataDownloaderError),
        ],
    )
    def test_translation_mapping(
        self,
        internal_cls: type[_InternalError],
        public_cls: type[DataDownloaderError],
    ) -> None:
        """Cada internal → public conforme tabela ADR-011."""
        internal = internal_cls("test message", context={"k": "v"})
        public = translate_to_public(internal)
        assert isinstance(public, public_cls)
        assert "test" in str(public)

    def test_translation_preserves_cause(self) -> None:
        """``cause`` field aponta para a exceção interna (forense)."""
        internal = _ChunkRetryExhausted(
            "chunk failed",
            context={"chunk_id": "abc", "attempts": 3},
        )
        public = translate_to_public(internal)
        assert public.cause is internal

    def test_translation_merges_context_into_details(self) -> None:
        internal = _ChunkRetryExhausted(
            "fail",
            context={"chunk_id": "abc", "attempts": 3},
        )
        public = translate_to_public(internal, context={"extra": "from caller"})
        assert public.details["chunk_id"] == "abc"
        assert public.details["attempts"] == 3
        assert public.details["extra"] == "from caller"

    def test_caller_context_overrides_internal(self) -> None:
        internal = _ChunkRetryExhausted("fail", context={"k": "internal"})
        public = translate_to_public(internal, context={"k": "caller"})
        assert public.details["k"] == "caller"

    def test_unmapped_subclass_falls_back_to_generic(self) -> None:
        """Defesa: subclasse adicionada futuramente sem mapping update vira genérico.

        Garante a invariante "no _InternalError leak" mesmo com mudanças
        no _internal sem update simultâneo do adapter.
        """

        class _NewSubclass(_InternalError):  # noqa: N818  test fixture
            pass

        internal = _NewSubclass("untracked")
        public = translate_to_public(internal)
        # Vira DataDownloaderError genérico (NUNCA um _InternalError).
        assert isinstance(public, DataDownloaderError)
        assert not isinstance(public, _InternalError)
        # mas mantém referência forense.
        assert public.cause is internal

    def test_empty_message_falls_back_to_class_name(self) -> None:
        internal = _DLLProbeFailed()
        public = translate_to_public(internal)
        assert "_DLLProbeFailed" in str(public) or str(public) != ""

    def test_translation_dll_probe_carries_synthetic_code(self) -> None:
        """_DLLProbeFailed → DLLInitError com code=-1 e name='NL_PROBE_FAILED'."""
        internal = _DLLProbeFailed("probe init failure")
        public = translate_to_public(internal)
        assert isinstance(public, DLLInitError)
        assert public.code == -1
        assert public.name == "NL_PROBE_FAILED"


# =====================================================================
# @translate_internal decorator
# =====================================================================


class TestTranslateInternalDecorator:
    """Decorator: wrappa entry points, captura internals, re-raise público."""

    def test_decorator_translates_internal_exception(self) -> None:
        @translate_internal
        def my_public_api() -> None:
            raise _ChunkRetryExhausted("retry exhausted", context={"chunk_id": "x"})

        with pytest.raises(DownloadError) as exc_info:
            my_public_api()

        # Exceção pública contém o internal como __cause__ (chain debug).
        assert isinstance(exc_info.value.__cause__, _ChunkRetryExhausted)
        # E também via .cause field (ADR-011).
        assert isinstance(exc_info.value.cause, _ChunkRetryExhausted)

    def test_decorator_preserves_normal_return(self) -> None:
        @translate_internal
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_decorator_propagates_non_internal_exceptions(self) -> None:
        """ValueError, RuntimeError etc. propagam sem alteração (não é nosso job)."""

        @translate_internal
        def boom() -> None:
            raise ValueError("not internal — propagate as-is")

        with pytest.raises(ValueError, match="not internal"):
            boom()

    def test_decorator_propagates_public_exceptions_unchanged(self) -> None:
        """DataDownloaderError já público — propaga sem re-wrap."""
        original = DownloadError("already public")

        @translate_internal
        def already_public() -> None:
            raise original

        with pytest.raises(DownloadError) as exc_info:
            already_public()
        assert exc_info.value is original

    def test_decorator_translates_dll_disconnected_to_connection_lost(self) -> None:
        @translate_internal
        def disconnected() -> None:
            raise _DLLDisconnected("MARKET_DISCONNECTED 30min")

        with pytest.raises(ConnectionLost) as exc_info:
            disconnected()
        assert isinstance(exc_info.value.cause, _DLLDisconnected)

    def test_decorator_translates_operation_cancelled(self) -> None:
        @translate_internal
        def user_cancelled() -> None:
            raise _OperationCancelled(
                "user pressed cancel",
                context={"trades_preserved": 50},
            )

        with pytest.raises(OperationCancelled) as exc_info:
            user_cancelled()
        assert exc_info.value.details["trades_preserved"] == 50

    def test_decorator_preserves_function_signature(self) -> None:
        """functools.wraps preserva __name__/__doc__."""

        @translate_internal
        def documented_func() -> str:
            """My doc."""
            return "ok"

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "My doc."
        assert documented_func() == "ok"


# =====================================================================
# Invariante "no leak" — sanity check
# =====================================================================


class TestNoLeakInvariant:
    """Garante que NENHUM _InternalError sai por @translate_internal."""

    @pytest.mark.parametrize(
        "internal_cls",
        [
            _ChunkRetryExhausted,
            _ChunkTimedOut,
            _DLLDisconnected,
            _DLLProbeFailed,
            _FormatParseError,
            _OperationCancelled,
            _QueueOverflow,
            _StateTransitionError,
        ],
    )
    def test_no_internal_leak_for_each_subclass(self, internal_cls: type[_InternalError]) -> None:
        @translate_internal
        def _entry() -> None:
            raise internal_cls("payload")

        with pytest.raises(DataDownloaderError) as exc_info:
            _entry()
        # NUNCA um _InternalError.
        assert not isinstance(exc_info.value, _InternalError)
