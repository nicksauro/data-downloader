"""Unit tests — DownloadScreen failure routing (Hotfix v1.1.0 2026-05-08).

Owner: Felix (frontend-dev) + Aria (architect) | Bug: Pichau smoke 2026-05-08.

Cenário: smoke real 2026-05-08T00:32:29 mostrou backend falhando com
``dll.market_connect_retry_exhausted attempts=3
microcopy_id=ERR_DLL_MARKET_RETRY_EXHAUSTED`` (3 tentativas timeout 300s
cada = 15min total) mas a UI exibia "Download concluído 0 trades" via
success card persistente do Wave 3. UX antiga: toast volátil 5s + tela
vazia. UX bugada Wave 3 piorou: card persistente declara vitória sem ter
baixado nada.

Cobertura:
    - ``_on_finished`` com ``status='failed'`` → routes para STATE_ERROR.
    - ``_on_finished`` com 0 trades + 0 partitions sem ``status='cache_hit'``
      → defesa em profundidade STATE_ERROR (ERR_DOWNLOAD_EMPTY).
    - ``_on_finished`` happy path (trades > 0, partitions != ()) →
      STATE_SUCCESS.
    - ``_on_error("ERR_DLL_MARKET_TIMEOUT: ...")`` → microcopy correto
      exibido (title/detail/action vindos da entry).
    - ``_on_error("ERR_DLL_MARKET_RETRY_EXHAUSTED: ...")`` → microcopy
      retry exhausted exibido.
    - ``_on_error("NL_WAITING_SERVER: ...")`` → fallback humanize_nl_error
      preservado (legado).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# Forçar offscreen ANTES de qualquer import PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@dataclass
class _FakeResult:
    """Mock duck-typed de :class:`DownloadResult`."""

    symbol: str = "WDOFUT"
    trades_count: int = 0
    partitions: tuple[Path, ...] = field(default_factory=tuple)
    duration_seconds: float = 0.0
    status: str = "completed"
    error_message: str | None = None


@pytest.fixture
def download_screen(qtbot):
    """Instancia ``DownloadScreen`` com cleanup automático via qtbot."""
    from data_downloader.ui.screens.download_screen import DownloadScreen

    screen = DownloadScreen()
    qtbot.addWidget(screen)
    return screen


def test_on_finished_status_failed_routes_to_error(download_screen):
    """status='failed' → STATE_ERROR (não STATE_SUCCESS)."""
    from data_downloader.ui.screens.download_screen import STATE_ERROR

    result = _FakeResult(
        symbol="WDOFUT",
        trades_count=0,
        partitions=(),
        status="failed",
        error_message="ERR_DLL_MARKET_RETRY_EXHAUSTED: 3 tentativas",
    )
    download_screen._on_finished(result)

    assert download_screen.current_state() == STATE_ERROR
    # Microcopy específico exibido.
    assert (
        "MARKET_DATA" in download_screen._error_title.text()
        or "Servidor" in download_screen._error_title.text()
    )


def test_on_finished_zero_trades_zero_partitions_routes_to_error(download_screen):
    """status='completed' mas 0 trades + 0 partitions → STATE_ERROR (defesa).

    Mesmo que upstream emita ``finished`` em vez de ``error`` (bug ou
    caminho futuro), a UI não pode declarar vitória sobre estado vazio.
    """
    from data_downloader.ui.screens.download_screen import STATE_ERROR

    result = _FakeResult(
        symbol="WDOFUT",
        trades_count=0,
        partitions=(),
        status="completed",
    )
    download_screen._on_finished(result)

    assert download_screen.current_state() == STATE_ERROR
    # Mensagem ERR_DOWNLOAD_EMPTY.
    assert (
        "vazio" in download_screen._error_title.text().lower()
        or "Download" in download_screen._error_title.text()
    )


def test_on_finished_cache_hit_zero_trades_routes_to_success(download_screen):
    """status='cache_hit' com 0 trades é caminho legítimo → STATE_SUCCESS."""
    from data_downloader.ui.screens.download_screen import STATE_SUCCESS

    result = _FakeResult(
        symbol="WDOFUT",
        trades_count=0,
        partitions=(),
        status="cache_hit",
    )
    download_screen._on_finished(result)

    assert download_screen.current_state() == STATE_SUCCESS


def test_on_finished_success_path_routes_to_success(download_screen):
    """trades > 0 + partitions != () + status='completed' → STATE_SUCCESS."""
    from data_downloader.ui.screens.download_screen import STATE_SUCCESS

    result = _FakeResult(
        symbol="WDOFUT",
        trades_count=1574806,
        partitions=(Path("data/history/WDOFUT/year=2026/month=05/p1.parquet"),),
        status="completed",
    )
    download_screen._on_finished(result)

    assert download_screen.current_state() == STATE_SUCCESS
    assert "1.574.806" in download_screen._success_trades_lbl.text()


def test_on_error_dll_market_timeout_shows_microcopy(download_screen):
    """_on_error com ERR_DLL_MARKET_TIMEOUT: ... extrai e exibe microcopy."""
    from data_downloader.ui.screens.download_screen import STATE_ERROR

    download_screen._on_error("ERR_DLL_MARKET_TIMEOUT: A DLL aguardou 300s")

    assert download_screen.current_state() == STATE_ERROR
    assert "Servidor de mercado" in download_screen._error_title.text()
    assert "MARKET_DATA" in download_screen._error_detail.text()
    assert "pregão" in download_screen._error_action.text().lower()


def test_on_error_retry_exhausted_shows_microcopy(download_screen):
    """_on_error com ERR_DLL_MARKET_RETRY_EXHAUSTED extrai e exibe microcopy."""
    from data_downloader.ui.screens.download_screen import STATE_ERROR

    download_screen._on_error("ERR_DLL_MARKET_RETRY_EXHAUSTED: 3 tentativas de 300s falharam")

    assert download_screen.current_state() == STATE_ERROR
    assert "MARKET_DATA" in download_screen._error_title.text()
    assert "Esgotamos" in download_screen._error_detail.text()


def test_on_error_nl_waiting_server_legacy_path(download_screen):
    """_on_error com NL_WAITING_SERVER: ... usa humanize_nl_error (legado)."""
    from data_downloader.ui.screens.download_screen import STATE_ERROR

    download_screen._on_error("NL_WAITING_SERVER: timeout retry")

    assert download_screen.current_state() == STATE_ERROR
    # NL_WAITING_SERVER é mapeado em _NL_ERROR_MAP no microcopy_loader.
    assert (
        "Aguardando" in download_screen._error_title.text()
        or "servidor" in download_screen._error_title.text().lower()
    )


def test_on_error_empty_download_microcopy_exists():
    """Regressão: microcopy ERR_DOWNLOAD_EMPTY é resolvível."""
    from data_downloader.ui.microcopy_loader import MSG

    assert "ERR_DOWNLOAD_EMPTY" in MSG
    assert MSG["ERR_DOWNLOAD_EMPTY"].title is not None


def test_on_error_market_timeout_microcopy_exists():
    """Regressão: microcopy ERR_DLL_MARKET_TIMEOUT é resolvível."""
    from data_downloader.ui.microcopy_loader import MSG

    assert "ERR_DLL_MARKET_TIMEOUT" in MSG
    assert MSG["ERR_DLL_MARKET_TIMEOUT"].title is not None


def test_on_error_retry_exhausted_microcopy_exists():
    """Regressão: microcopy ERR_DLL_MARKET_RETRY_EXHAUSTED é resolvível."""
    from data_downloader.ui.microcopy_loader import MSG

    assert "ERR_DLL_MARKET_RETRY_EXHAUSTED" in MSG
    assert MSG["ERR_DLL_MARKET_RETRY_EXHAUSTED"].title is not None
