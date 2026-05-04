"""Unit tests — public_api.download / DownloadHandle (Story 1.7b AC7, AC8).

Cobertura:

- ``__api_version__`` em V1.0 (atualmente 1.0.0 — Story 4.3 release).
- ``DownloadHandle.cancel()`` é idempotente e reflete em ``is_cancelling()``.
- ``DownloadHandle.result()`` bloqueia até worker terminar e retorna
  ``DownloadResult``.
- ``DownloadHandle.events()`` yields progress events e termina graciosamente.
- ``download()`` valida exchange e ranges sincronamente (falha cedo).
- Imports da fronteira pública resolvem corretamente.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from data_downloader.public_api import (
    DownloadHandle,
    DownloadProgress,
    DownloadResult,
    __api_version__,
    download,
)


def test_api_version_bumped_to_1_0_0() -> None:
    """Story 4.3: V1.0 stable release (0.3.0 → 0.4.0 → 1.0.0)."""
    assert __api_version__ == "1.0.0"


def test_public_api_exports() -> None:
    """Fronteira pública expõe download + Handle/Progress/Result + status type."""
    import data_downloader.public_api as api

    assert api.DownloadHandle is DownloadHandle
    assert api.DownloadProgress is DownloadProgress
    assert api.DownloadResult is DownloadResult
    assert api.download is download


# =====================================================================
# DownloadHandle isolated tests (worker target injection)
# =====================================================================


def test_handle_cancel_is_idempotent() -> None:
    """Múltiplas chamadas a cancel() apenas seteam o flag uma vez."""
    started = threading.Event()
    proceed = threading.Event()

    def _worker(*, cancel_event, events_queue, set_result) -> None:
        started.set()
        proceed.wait(timeout=2.0)
        set_result(
            DownloadResult(
                job_id="test-job",
                symbol="WDOJ26",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=0,
                partitions=(),
                duration_seconds=0.0,
                status="cancelled",
            )
        )

    handle = DownloadHandle(worker_target=_worker)
    started.wait(timeout=1.0)

    assert not handle.is_cancelling()
    handle.cancel()
    handle.cancel()
    handle.cancel()
    assert handle.is_cancelling()
    proceed.set()
    handle.join(timeout=2.0)


def test_handle_result_blocks_until_complete() -> None:
    """result() bloqueia até worker terminar."""

    def _worker(*, cancel_event, events_queue, set_result) -> None:
        time.sleep(0.05)
        set_result(
            DownloadResult(
                job_id="job-1",
                symbol="WDOJ26",
                exchange="F",
                actual_start=datetime(2026, 3, 1),
                actual_end=datetime(2026, 3, 31),
                trades_count=42,
                partitions=(Path("/tmp/x.parquet"),),
                duration_seconds=0.05,
                status="completed",
            )
        )

    handle = DownloadHandle(worker_target=_worker)
    result = handle.result(timeout=5.0)
    assert result.status == "completed"
    assert result.trades_count == 42
    assert result.symbol == "WDOJ26"


def test_handle_result_timeout() -> None:
    """result(timeout=...) levanta TimeoutError se worker não termina."""
    proceed = threading.Event()

    def _worker(*, cancel_event, events_queue, set_result) -> None:
        proceed.wait(timeout=10.0)
        set_result(
            DownloadResult(
                job_id="x",
                symbol="X",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=0,
                duration_seconds=0.0,
                status="completed",
            )
        )

    handle = DownloadHandle(worker_target=_worker)
    with pytest.raises(TimeoutError):
        handle.result(timeout=0.1)
    proceed.set()
    handle.join(timeout=2.0)


def test_handle_events_yields_progress_then_stops() -> None:
    """events() yields cada DownloadProgress e termina ao final."""

    def _worker(*, cancel_event, events_queue, set_result) -> None:
        for i in range(3):
            events_queue.put(
                DownloadProgress(
                    total=3,
                    done=i + 1,
                    message=f"chunk {i + 1}",
                    trades_received=(i + 1) * 100,
                    current_contract="WDOJ26",
                )
            )
            time.sleep(0.005)
        set_result(
            DownloadResult(
                job_id="j",
                symbol="WDOJ26",
                exchange="F",
                actual_start=None,
                actual_end=None,
                trades_count=300,
                duration_seconds=0.0,
                status="completed",
            )
        )

    handle = DownloadHandle(worker_target=_worker)
    events = list(handle.events())
    assert len(events) == 3
    assert events[-1].done == 3
    assert events[-1].trades_received == 300

    result = handle.result(timeout=2.0)
    assert result.status == "completed"


def test_handle_worker_failure_still_completes() -> None:
    """Worker que falha sem set_result ainda libera events() + result()."""

    def _worker(*, cancel_event, events_queue, set_result) -> None:
        # Não chama set_result — simula worker bug.
        events_queue.put(DownloadProgress(total=1, done=0, message="started", trades_received=0))
        # Termina sem produzir resultado.

    handle = DownloadHandle(worker_target=_worker)
    events = list(handle.events())
    assert len(events) == 1
    with pytest.raises(RuntimeError, match="without producing"):
        handle.result(timeout=2.0)


# =====================================================================
# download() input validation
# =====================================================================


def test_download_rejects_invalid_exchange() -> None:
    with pytest.raises(ValueError, match="exchange"):
        download(symbol="WDOJ26", start=date(2026, 3, 1), end=date(2026, 3, 31), exchange="X")


def test_download_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match=">= start"):
        download(
            symbol="WDOJ26",
            start=date(2026, 3, 31),
            end=date(2026, 3, 1),
        )


def test_download_handle_returned_with_factories(tmp_path: Path) -> None:
    """Verifica que download() spawna worker e retorna handle imediatamente
    quando factories são injetadas (não chama DLL real)."""
    from data_downloader.storage.catalog import Catalog
    from data_downloader.storage.parquet_writer import ParquetWriter

    class _DummyDLL:
        dll_version = "test"

        def finalize(self) -> None:
            pass

    def _dll_factory() -> object:
        return _DummyDLL()

    def _catalog_factory(d: Path) -> Catalog:
        return Catalog(db_path=d / "history" / "catalog.db", data_dir=d)

    def _writer_factory(d: Path) -> ParquetWriter:
        return ParquetWriter(data_dir=d)

    handle = download(
        symbol="WDOJ26",
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
        exchange="F",
        data_dir=tmp_path,
        dll_factory=_dll_factory,
        catalog_factory=_catalog_factory,
        writer_factory=_writer_factory,
    )

    # Worker provavelmente vai falhar (Catalog vazio sem contrato) mas
    # handle deve retornar e produzir DownloadResult com status='failed'.
    result = handle.result(timeout=10.0)
    # Symbol "WDOJ26" não é root → resolve_contract=False → orchestrator usa
    # symbol direto, mas catalog não tem partições nem chunker espera trades.
    # O resultado pode ser failed (sem trades reais) ou cache_hit/partial — o
    # importante é que NÃO há leak de exception.
    assert result.status in ("failed", "completed", "partial", "cache_hit")
    assert isinstance(result, DownloadResult)


# =====================================================================
# Microcopy loader smoke
# =====================================================================


def test_microcopy_format_known_id() -> None:
    """format_msg resolve placeholder canônico."""
    from data_downloader.ui.microcopy_loader import format_msg

    out = format_msg("SUC_DOWNLOAD_DONE", "title", symbol="WDOJ26")
    assert out == "Download concluído: WDOJ26"


def test_microcopy_format_unknown_id_returns_sentinel() -> None:
    from data_downloader.ui.microcopy_loader import format_msg

    out = format_msg("DOES_NOT_EXIST")
    assert "DOES_NOT_EXIST" in out
    assert "not found" in out


def test_humanize_nl_error_known_code() -> None:
    """humanize_nl_error resolve NL_INVALID_TICKER para entry estruturado."""
    from data_downloader.ui.microcopy_loader import humanize_nl_error

    entry = humanize_nl_error("NL_INVALID_TICKER")
    assert entry.title == "Contrato inválido"
    assert "contrato vigente" in (entry.detail or "")


def test_humanize_nl_error_unknown_falls_back_to_generic() -> None:
    from data_downloader.ui.microcopy_loader import humanize_nl_error

    entry = humanize_nl_error("NL_DOES_NOT_EXIST", code=-9999)
    assert entry.title == "Erro não documentado da ProfitDLL"
    assert "9999" in (entry.detail or "")


def test_war_99_reconnect_text_is_canonical() -> None:
    """Quirk Q11-99: texto LITERAL preservado (Uma — MICROCOPY_CATALOG §18)."""
    from data_downloader.ui.microcopy_loader import format_msg

    text = format_msg("WAR_99_RECONNECT", "detail")
    assert text == (
        "A corretora está reconectando — é normal, " "aguarde até 30 minutos. Não cancele."
    )
