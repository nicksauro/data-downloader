"""Unit tests — Exception hierarchy 3-camadas (Story 2.11 ADR-011).

Cobertura:

- Camada 1 — internals (``_internal/exceptions``): ``_InternalError`` base
  + 7 subclasses; marker ``_internal: ClassVar[Literal[True]]``.
- Camada 2 — adapter (``_internal/exception_adapter``): testado em
  ``test_exception_adapter.py``.
- Camada 3 — public_api (``public_api/exceptions``): hierarquia pública
  + ``humanized_message`` property + novos tipos ``OperationCancelled`` e
  ``ConnectionLost`` (Story 2.11 H10 + Q02-E).

Aria audit:
- 3 camadas isoladas (internals NÃO importam public_api; public_api
  consome adapter, não internals diretos).
- Marker ``_internal=True`` permite property test de no-leak.
- Hierarquia public é estável (subclasses adicionadas, nada removido).
"""

from __future__ import annotations

import pytest

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
    DiskFull,
    DLLInitError,
    DownloadError,
    IntegrityError,
    InvalidContract,
    OperationCancelled,
)

# =====================================================================
# Camada 1 — Internals
# =====================================================================


class TestInternalHierarchy:
    """Camada interna: _InternalError + 7+ subclasses."""

    def test_internal_error_is_exception_subclass(self) -> None:
        assert issubclass(_InternalError, Exception)

    def test_internal_error_has_marker(self) -> None:
        """Marker ``_internal=True`` permite detecção mecânica."""
        assert getattr(_InternalError, "_internal", False) is True

    @pytest.mark.parametrize(
        "cls",
        [
            _DLLProbeFailed,
            _DLLDisconnected,
            _ChunkTimedOut,
            _ChunkRetryExhausted,
            _QueueOverflow,
            _FormatParseError,
            _StateTransitionError,
            _OperationCancelled,
        ],
    )
    def test_subclasses_inherit_marker(self, cls: type[_InternalError]) -> None:
        """Todas subclasses herdam marker (mesmo sem redeclarar)."""
        assert issubclass(cls, _InternalError)
        assert getattr(cls, "_internal", False) is True

    def test_internal_error_init_with_context(self) -> None:
        exc = _ChunkRetryExhausted(
            "chunk failed after 3 retries",
            context={"chunk_id": "abc", "attempts": 3},
        )
        assert str(exc) == "chunk failed after 3 retries"
        assert exc.context == {"chunk_id": "abc", "attempts": 3}

    def test_internal_error_default_context_is_empty(self) -> None:
        exc = _DLLProbeFailed("probe failed")
        assert exc.context == {}

    def test_internal_error_message_optional(self) -> None:
        exc = _StateTransitionError()
        assert exc.context == {}

    def test_internals_do_not_import_public_api(self) -> None:
        """ADR-011 §Regras: internals NUNCA importam de public_api/.

        Verificação mecânica via inspecção do source (importação resolveria
        em ImportError circular se cruzasse fronteira).
        """
        import data_downloader._internal.exceptions as m

        with open(m.__file__, encoding="utf-8") as fh:
            src = fh.read()
        # Não pode haver "from data_downloader.public_api" no módulo internal.
        assert "from data_downloader.public_api" not in src


# =====================================================================
# Camada 3 — Public API hierarchy
# =====================================================================


class TestPublicHierarchy:
    """Camada pública: DataDownloaderError + subclasses."""

    @pytest.mark.parametrize(
        "cls",
        [
            DLLInitError,
            InvalidContract,
            DiskFull,
            DownloadError,
            IntegrityError,
            OperationCancelled,
            ConnectionLost,
        ],
    )
    def test_subclass_of_data_downloader_error(self, cls: type[Exception]) -> None:
        assert issubclass(cls, DataDownloaderError)

    def test_data_downloader_error_init(self) -> None:
        exc = DataDownloaderError("oops", details={"k": "v"})
        assert str(exc) == "oops"
        assert exc.details == {"k": "v"}
        assert exc.cause is None

    def test_data_downloader_error_chain(self) -> None:
        inner = ValueError("root")
        outer = DataDownloaderError("wrapped", cause=inner)
        assert outer.cause is inner

    def test_humanized_message_known_types(self) -> None:
        """Cada subclasse retorna ID canônico de microcopy (Uma)."""
        assert OperationCancelled("x").humanized_message == "SUC_CANCEL_DONE"
        assert ConnectionLost("x").humanized_message == "ERR_CONNECTION_LOST"
        assert DiskFull("x").humanized_message == "ERR_DISK_FULL"
        assert DownloadError("x").humanized_message == "ERR_CHUNK_FAILED"
        assert IntegrityError("x").humanized_message == "ERR_CATALOG_DRIFT"
        assert InvalidContract("WDO", "2026-01-01").humanized_message == "ERR_INVALID_CONTRACT"
        assert DLLInitError(-1, "NL_X", "msg").humanized_message == "ERR_DLL_NOT_INITIALIZED"

    def test_humanized_message_unknown_falls_back(self) -> None:
        """Subclasse adicionada futuramente sem mapping cai em ERR_DLL_GENERIC."""

        class _NewSubclass(DataDownloaderError):  # noqa: N818  test fixture
            pass

        assert _NewSubclass("x").humanized_message == "ERR_DLL_GENERIC"

    def test_operation_cancelled_carries_details(self) -> None:
        exc = OperationCancelled(
            "cancelled by user",
            details={"trades_preserved": 100, "job_id": "job-x"},
        )
        assert exc.details["trades_preserved"] == 100
        assert exc.details["job_id"] == "job-x"

    def test_connection_lost_basic(self) -> None:
        exc = ConnectionLost("Q02-E timeout exceeded")
        assert "Q02-E" in str(exc)
        assert isinstance(exc, DataDownloaderError)


# =====================================================================
# Cross-layer — public exports
# =====================================================================


class TestPublicExports:
    """Story 2.11 — novos símbolos exportados em public_api.__init__."""

    def test_operation_cancelled_exported(self) -> None:
        from data_downloader.public_api import OperationCancelled as Pub

        assert Pub is OperationCancelled

    def test_connection_lost_exported(self) -> None:
        from data_downloader.public_api import ConnectionLost as Pub

        assert Pub is ConnectionLost

    def test_all_includes_new_exceptions(self) -> None:
        import data_downloader.public_api as api

        assert "OperationCancelled" in api.__all__
        assert "ConnectionLost" in api.__all__
