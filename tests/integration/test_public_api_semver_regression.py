"""Regression SemVer test suite — V0.x → V1.0 backwards-compat.

Owner: Aria (architect — fronteira pública) + Dex (impl).
Story 4.3 — AC7.

Verifica que TODOS os símbolos exportados em V0.x continuam disponíveis e
mantêm assinatura/comportamento em V1.0. Falha do teste = breaking change
não anunciado = bug constitucional (Article IV — No Invention).

Cobertura:

1. Import surface — todos os símbolos importáveis via
   ``from data_downloader.public_api import ...``.
2. Type identity — funções/classes têm tipo esperado (não foram
   renomeadas para placeholders).
3. Signature shape — assinaturas mantém parâmetros essenciais.
4. Dataclass fields — ``DownloadProgress``/``DownloadResult`` têm
   campos esperados (frozen dataclasses).
5. Exception hierarchy — todas exceções são subclasses de
   ``DataDownloaderError`` e expõem ``humanized_message``.
6. ``__api_version__`` bumped para >=1.0.
7. ``DownloadHandle`` API methods (cancel, result, events,
   peek_result, cancelled, is_cancelled).

NB: testes de comportamento (round-trip download/read) ficam em outras
suites; aqui o foco é **shape/contract regression**, não execução.
"""

from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass
from typing import get_args

import pyarrow as pa
import pytest

# =====================================================================
# 1. Import surface — todos os símbolos públicos importam
# =====================================================================


def test_import_all_functions() -> None:
    """Todas as 4 funções públicas importam via fronteira."""
    from data_downloader.public_api import (  # noqa: F401
        download,
        read,
        read_continuous,
        vigent_contract,
    )


def test_import_all_handle_classes() -> None:
    """DownloadHandle + 2 dataclasses + DownloadStatus importam."""
    from data_downloader.public_api import (  # noqa: F401
        DownloadHandle,
        DownloadProgress,
        DownloadResult,
        DownloadStatus,
    )


def test_import_all_exceptions() -> None:
    """8 exceções públicas importam via fronteira."""
    from data_downloader.public_api import (  # noqa: F401
        ConnectionLost,
        DataDownloaderError,
        DiskFull,
        DLLInitError,
        DownloadError,
        IntegrityError,
        InvalidContract,
        OperationCancelled,
    )


def test_import_api_version() -> None:
    """__api_version__ é exportado e segue SemVer string."""
    from data_downloader.public_api import __api_version__

    assert isinstance(__api_version__, str)
    parts = __api_version__.split(".")
    assert len(parts) == 3, f"Expected MAJOR.MINOR.PATCH, got {__api_version__!r}"
    for p in parts:
        int(p)  # raises ValueError if non-numeric → fails the test


def test_api_version_bumped_to_v1() -> None:
    """V1.0 release: __api_version__ deve ser >= 1.0.0."""
    from data_downloader.public_api import __api_version__

    major = int(__api_version__.split(".")[0])
    assert major >= 1, f"Expected MAJOR >= 1, got {__api_version__!r}"


def test_all_listed_symbols_importable() -> None:
    """Cada nome em __all__ deve resolver via getattr."""
    import data_downloader.public_api as pa_mod

    for name in pa_mod.__all__:
        assert hasattr(pa_mod, name), f"__all__ lists {name!r} but module has no such attribute"


# =====================================================================
# 2. Type identity — funções e classes não foram renomeadas
# =====================================================================


def test_download_is_callable() -> None:
    from data_downloader.public_api import download

    assert callable(download)


def test_read_is_callable() -> None:
    from data_downloader.public_api import read

    assert callable(read)


def test_read_continuous_is_callable() -> None:
    from data_downloader.public_api import read_continuous

    assert callable(read_continuous)


def test_vigent_contract_is_callable() -> None:
    from data_downloader.public_api import vigent_contract

    assert callable(vigent_contract)


def test_download_handle_is_class() -> None:
    from data_downloader.public_api import DownloadHandle

    assert inspect.isclass(DownloadHandle)


def test_download_progress_is_frozen_dataclass() -> None:
    from data_downloader.public_api import DownloadProgress

    assert is_dataclass(DownloadProgress)
    # frozen=True
    instance = DownloadProgress(total=10, done=5, message="x")
    with pytest.raises((AttributeError, TypeError)):  # frozen → FrozenInstanceError
        instance.done = 6  # type: ignore[misc]


def test_download_result_is_frozen_dataclass() -> None:
    from data_downloader.public_api import DownloadResult

    assert is_dataclass(DownloadResult)


# =====================================================================
# 3. Signature shape — funções mantêm parâmetros essenciais
# =====================================================================


def test_download_signature_has_required_params() -> None:
    from data_downloader.public_api import download

    sig = inspect.signature(download)
    params = sig.parameters
    # required positional params
    assert "symbol" in params
    assert "start" in params
    assert "end" in params
    # kw-only with defaults
    assert "exchange" in params
    assert params["exchange"].default == "F"
    assert "data_dir" in params


def test_read_signature_has_required_params() -> None:
    from data_downloader.public_api import read

    sig = inspect.signature(read)
    params = sig.parameters
    assert "symbol" in params
    assert "start" in params
    assert "end" in params
    assert "exchange" in params
    assert params["exchange"].default == "F"
    assert "columns" in params


def test_read_continuous_signature_has_required_params() -> None:
    from data_downloader.public_api import read_continuous

    sig = inspect.signature(read_continuous)
    params = sig.parameters
    assert "symbol_root" in params
    assert "start" in params
    assert "end" in params
    assert "catalog" in params
    # catalog is keyword-only and required
    assert params["catalog"].kind == inspect.Parameter.KEYWORD_ONLY


def test_vigent_contract_signature_has_required_params() -> None:
    from data_downloader.public_api import vigent_contract

    sig = inspect.signature(vigent_contract)
    params = sig.parameters
    assert "symbol_root" in params
    assert "on_date" in params
    assert "catalog" in params
    assert params["catalog"].kind == inspect.Parameter.KEYWORD_ONLY


# =====================================================================
# 4. Dataclass fields — DownloadProgress / DownloadResult shape
# =====================================================================


def test_download_progress_fields() -> None:
    from data_downloader.public_api import DownloadProgress

    field_names = {f.name for f in fields(DownloadProgress)}
    expected = {
        "total",
        "done",
        "message",
        "trades_received",
        "current_contract",
        "is_99_reconnect",
    }
    assert expected.issubset(field_names), f"Missing fields: {expected - field_names}"


def test_download_result_fields() -> None:
    from data_downloader.public_api import DownloadResult

    field_names = {f.name for f in fields(DownloadResult)}
    expected = {
        "job_id",
        "symbol",
        "exchange",
        "actual_start",
        "actual_end",
        "trades_count",
        "partitions",
        "duration_seconds",
        "status",
        "error_message",
    }
    assert expected.issubset(field_names), f"Missing fields: {expected - field_names}"


def test_download_status_literal_values() -> None:
    """DownloadStatus Literal expõe os 5 status finais."""
    from data_downloader.public_api import DownloadStatus

    args = set(get_args(DownloadStatus))
    expected = {"completed", "partial", "failed", "cache_hit", "cancelled"}
    assert args == expected, f"Expected {expected}, got {args}"


# =====================================================================
# 5. Exception hierarchy — todas subclasses de DataDownloaderError
# =====================================================================


def test_all_exceptions_are_subclasses_of_base() -> None:
    from data_downloader.public_api import (
        ConnectionLost,
        DataDownloaderError,
        DiskFull,
        DLLInitError,
        DownloadError,
        IntegrityError,
        InvalidContract,
        OperationCancelled,
    )

    for exc_cls in (
        DLLInitError,
        InvalidContract,
        DiskFull,
        DownloadError,
        IntegrityError,
        OperationCancelled,
        ConnectionLost,
    ):
        assert issubclass(
            exc_cls, DataDownloaderError
        ), f"{exc_cls.__name__} must subclass DataDownloaderError"


def test_data_downloader_error_has_humanized_message() -> None:
    from data_downloader.public_api import DataDownloaderError

    err = DataDownloaderError("test message")
    assert hasattr(err, "humanized_message")
    msg_id = err.humanized_message
    assert isinstance(msg_id, str)
    assert msg_id.isupper() or "_" in msg_id  # microcopy ID format


def test_dll_init_error_has_code_and_name() -> None:
    from data_downloader.public_api import DLLInitError

    err = DLLInitError(-1, "NL_TEST", "test message")
    assert err.code == -1
    assert err.name == "NL_TEST"
    assert "test message" in str(err)


def test_invalid_contract_has_symbol_root() -> None:
    from datetime import date

    from data_downloader.public_api import InvalidContract

    err = InvalidContract("WDO", on_date=date(2026, 1, 1))
    assert err.symbol_root == "WDO"
    assert err.on_date == date(2026, 1, 1)
    assert "WDO" in str(err)


def test_operation_cancelled_accepts_details() -> None:
    from data_downloader.public_api import OperationCancelled

    err = OperationCancelled(
        "cancelled by user",
        details={"trades_preserved": 1000, "job_id": "abc-123"},
    )
    assert err.details["trades_preserved"] == 1000
    assert err.details["job_id"] == "abc-123"


# =====================================================================
# 6. DownloadHandle public API surface
# =====================================================================


def test_download_handle_has_cancel_method() -> None:
    from data_downloader.public_api import DownloadHandle

    assert hasattr(DownloadHandle, "cancel")
    assert callable(DownloadHandle.cancel)


def test_download_handle_has_result_method() -> None:
    from data_downloader.public_api import DownloadHandle

    assert hasattr(DownloadHandle, "result")
    assert callable(DownloadHandle.result)


def test_download_handle_has_events_method() -> None:
    from data_downloader.public_api import DownloadHandle

    assert hasattr(DownloadHandle, "events")
    assert callable(DownloadHandle.events)


def test_download_handle_has_peek_result() -> None:
    from data_downloader.public_api import DownloadHandle

    assert hasattr(DownloadHandle, "peek_result")
    assert callable(DownloadHandle.peek_result)


def test_download_handle_has_cancelled() -> None:
    from data_downloader.public_api import DownloadHandle

    assert hasattr(DownloadHandle, "cancelled")
    assert callable(DownloadHandle.cancelled)


def test_download_handle_has_is_cancelled_property() -> None:
    from data_downloader.public_api import DownloadHandle

    assert hasattr(DownloadHandle, "is_cancelled")
    # property descriptor
    assert isinstance(inspect.getattr_static(DownloadHandle, "is_cancelled"), property)


# =====================================================================
# 7. Round-trip (instanciação básica) — DownloadHandle integra
# =====================================================================


def test_download_handle_cancel_returns_bool() -> None:
    """cancel() retorna bool (mesmo em handle sem worker real)."""
    from data_downloader.public_api import DownloadHandle

    # Worker que não faz nada (apenas seta resultado vazio)
    def noop_worker(*, cancel_event, events_queue, set_result):  # type: ignore[no-untyped-def]
        from data_downloader.public_api.handle import DownloadResult

        set_result(
            DownloadResult(
                job_id="",
                symbol="",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=0,
            )
        )

    handle = DownloadHandle(worker_target=noop_worker)
    handle.join(timeout=5.0)
    result = handle.cancel(timeout=2.0)
    assert isinstance(result, bool)


def test_download_handle_result_returns_download_result() -> None:
    """result() em handle terminado retorna DownloadResult."""
    from data_downloader.public_api import DownloadHandle, DownloadResult

    def noop_worker(*, cancel_event, events_queue, set_result):  # type: ignore[no-untyped-def]
        set_result(
            DownloadResult(
                job_id="test-job",
                symbol="WDOJ26",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=0,
            )
        )

    handle = DownloadHandle(worker_target=noop_worker)
    result = handle.result(timeout=5.0)
    assert isinstance(result, DownloadResult)
    assert result.job_id == "test-job"
    assert result.symbol == "WDOJ26"


def test_download_handle_result_raises_operation_cancelled_when_status_cancelled() -> None:
    """Story 2.11 H10 — result() levanta OperationCancelled para status='cancelled'."""
    from data_downloader.public_api import (
        DownloadHandle,
        DownloadResult,
        OperationCancelled,
    )

    def cancel_worker(*, cancel_event, events_queue, set_result):  # type: ignore[no-untyped-def]
        set_result(
            DownloadResult(
                job_id="cancelled-job",
                symbol="WDOJ26",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=42,
                status="cancelled",
            )
        )

    handle = DownloadHandle(worker_target=cancel_worker)
    with pytest.raises(OperationCancelled) as excinfo:
        handle.result(timeout=5.0)
    assert excinfo.value.details["trades_preserved"] == 42
    assert excinfo.value.details["job_id"] == "cancelled-job"


def test_download_handle_peek_result_no_raise_on_cancelled() -> None:
    """peek_result() não levanta para status='cancelled' (vs result())."""
    from data_downloader.public_api import DownloadHandle, DownloadResult

    def cancel_worker(*, cancel_event, events_queue, set_result):  # type: ignore[no-untyped-def]
        set_result(
            DownloadResult(
                job_id="cancelled-job",
                symbol="WDOJ26",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=10,
                status="cancelled",
            )
        )

    handle = DownloadHandle(worker_target=cancel_worker)
    handle.join(timeout=5.0)
    result = handle.peek_result()
    assert result is not None
    assert result.status == "cancelled"
    assert result.trades_count == 10


# =====================================================================
# 8. Functions return contractual types
# =====================================================================


def test_read_input_validation() -> None:
    """read() levanta ValueError para args inválidos (sync, no DLL needed)."""
    from datetime import datetime

    from data_downloader.public_api import read

    with pytest.raises(ValueError, match="exchange"):
        read("WDOJ26", datetime(2026, 1, 1), datetime(2026, 1, 2), exchange="X")

    with pytest.raises(ValueError, match="start"):
        read("WDOJ26", datetime(2026, 1, 5), datetime(2026, 1, 1))


def test_download_input_validation() -> None:
    """download() levanta ValueError sync para args inválidos."""
    from datetime import date

    from data_downloader.public_api import download

    with pytest.raises(ValueError, match="exchange"):
        download("WDOJ26", date(2026, 1, 1), date(2026, 1, 2), exchange="X")

    with pytest.raises(ValueError, match=r"(?:end|start)"):
        download("WDOJ26", date(2026, 1, 5), date(2026, 1, 1))


def test_pa_table_is_actual_pyarrow_table() -> None:
    """Sanity check: pyarrow Table type é o que esperamos."""
    table = pa.table({"x": [1, 2, 3]})
    assert isinstance(table, pa.Table)


# =====================================================================
# 9. Type hints discoverable (mypy --strict alignment)
# =====================================================================


def test_download_has_complete_type_hints() -> None:
    """download() expõe type annotations (mypy --strict pre-condition).

    Usa ``__annotations__`` direto em vez de :func:`get_type_hints` para
    evitar resolução forward-ref de imports TYPE_CHECKING (e.g. ``Callable``
    de :mod:`collections.abc`).
    """
    from data_downloader.public_api import download

    annotations = download.__annotations__
    assert "symbol" in annotations
    assert "start" in annotations
    assert "end" in annotations
    assert "return" in annotations


def test_read_has_complete_type_hints() -> None:
    from data_downloader.public_api import read

    annotations = read.__annotations__
    assert "symbol" in annotations
    assert "return" in annotations


# =====================================================================
# 10. __all__ list integrity
# =====================================================================


def test_all_list_contains_v0_4_symbols() -> None:
    """V1.0 deve preservar TODOS os símbolos da V0.4 baseline."""
    import data_downloader.public_api as pa_mod

    # Lista hardcoded do __all__ de v0.4.0 (Story 2.11)
    v0_4_symbols = {
        "ConnectionLost",
        "DLLInitError",
        "DataDownloaderError",
        "DiskFull",
        "DownloadError",
        "DownloadHandle",
        "DownloadProgress",
        "DownloadResult",
        "DownloadStatus",
        "IntegrityError",
        "InvalidContract",
        "OperationCancelled",
        "__api_version__",
        "download",
        "read",
        "read_continuous",
        "vigent_contract",
    }
    actual = set(pa_mod.__all__)
    missing = v0_4_symbols - actual
    assert not missing, f"V1.0 dropped V0.4 symbols: {missing}"
