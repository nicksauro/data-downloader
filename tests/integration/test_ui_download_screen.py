"""Integration tests — DownloadScreen (Story 3.2).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Cobertura:
    - Smoke: tela renderiza com 5 estados (normal/loading/error/empty/success).
    - Form preenchido + click no botão dispara adapter.start() com args certos.
    - Sinal progress → ProgressCard.set_progress chamado.
    - Sinal error → estado error + microcopy correto.
    - Botão CANCELAR + confirm → adapter.cancel chamado.
    - Quirk 99% reconnect: banner amarelo + texto LITERAL preservado.

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def download_screen(qtbot, monkeypatch):
    """Cria DownloadScreen isolada (sem MainWindow), com adapter REAL.

    O adapter ainda usa QThread mas como nenhum start() acontece sem
    intervenção do teste, ele fica idle.
    """
    from data_downloader.ui.screens.download_screen import DownloadScreen

    screen = DownloadScreen()
    qtbot.addWidget(screen)
    screen.show()
    yield screen
    # Alguns testes (ex.: transition_to_loading) disparam um download real
    # via ``adapter.start`` que entra num loop bloqueante na worker thread —
    # se a screen for destruída com a thread ocupada, o Qt no Windows aborta
    # com ``QThread: Destroyed while thread 'download-adapter' is still
    # running'' (task #14 v1.1.0). Cancela explicitamente antes do shutdown
    # e dá ao worker uma chance de drenar.
    import contextlib

    with contextlib.suppress(Exception):
        screen._adapter.cancel()
    with contextlib.suppress(Exception):
        qtbot.wait(150)
    screen._adapter.shutdown()


# =====================================================================
# Smoke
# =====================================================================


def test_download_screen_starts_in_normal_state(download_screen):
    assert download_screen.current_state() == "normal"


def test_download_screen_has_primary_button(download_screen):
    assert download_screen._download_btn.property("variant") == "primary"
    assert download_screen._download_btn.isEnabled()


def test_download_screen_default_symbol_loaded(download_screen):
    """Default symbol vem do cache OU da lista de sugestões."""
    val = download_screen._symbol_picker.value()
    assert val
    assert val == val.upper()  # uppercase enforced


def test_download_screen_default_period_is_current_month(download_screen):
    start, end = download_screen._period_picker.range()
    today = date.today()
    assert start.year == today.year
    assert start.month == today.month
    assert start.day == 1
    assert end == today


def test_microcopy_resolves_no_missing_ids(download_screen):
    """Nenhuma label visível mostra <microcopy id not found>."""
    title = download_screen._title.text()
    assert "<microcopy id not found" not in title
    subtitle = download_screen._subtitle.text()
    assert "<microcopy id not found" not in subtitle
    footer = download_screen._footer.text()
    assert "<microcopy id not found" not in footer


# =====================================================================
# Adapter dispatch
# =====================================================================


def test_clicking_download_with_invalid_symbol_shows_error_toast(download_screen, qtbot):
    """Symbol vazio → toast de erro inline (não dispara adapter)."""
    download_screen._symbol_picker.set_value("")
    download_screen._on_download_clicked()
    qtbot.wait(100)
    # Estado segue normal (não vai para loading).
    assert download_screen.current_state() == "normal"
    assert download_screen._toast.isVisible()


def test_clicking_download_with_valid_inputs_transitions_to_loading(
    download_screen, qtbot, monkeypatch, tmp_path
):
    """Form válido + click → estado=loading + signal de start emitido."""
    # Mock ``public_api.download`` — sem isto, o worker QThread do adapter
    # entra num download real (sem DLL/.env → loop de retry/timeout) que não
    # respeita cancel a tempo, vazando a ``QThread`` no teardown e abortando
    # o processo no Windows (task #14 v1.1.0). O que este teste valida é o
    # dispatch form→adapter, não o download em si.
    import data_downloader.public_api as _public_api

    class _FakeHandle:
        def __iter__(self):
            return iter(())  # download "termina" imediatamente, sem progresso

        def result(self):
            return None

        def cancel(self, timeout: float = 0.0) -> None:
            _ = timeout
            return None

    monkeypatch.setattr(_public_api, "download", lambda *a, **k: _FakeHandle(), raising=False)

    # Spy no signal interno _request_start (emitido antes do
    # cross-thread dispatch para adapter.start).
    captured = []

    def on_request(symbol, exchange, start, end, data_dir):
        captured.append((symbol, exchange, start, end, data_dir))

    download_screen._request_start.connect(on_request)

    # Story 4.31 AC11: usa fixture ``tmp_path`` (per-test scratch dir) em vez
    # de ``Path.cwd() / "data"`` — elimina dependência de cwd no test order
    # e evita poluir o repo se o teste rodar fora do harness padrão.
    data_dir_path = tmp_path / "data"
    download_screen._symbol_picker.set_value("WDOJ26")
    download_screen._period_picker.set_range(date(2026, 3, 1), date(2026, 3, 31))
    download_screen._folder_edit.setText(str(data_dir_path))

    download_screen._on_download_clicked()
    qtbot.waitUntil(lambda: len(captured) > 0, timeout=2000)

    symbol, exchange, start, end, data_dir = captured[0]
    assert symbol == "WDOJ26"
    assert exchange == "F"
    assert start == date(2026, 3, 1)
    assert end == date(2026, 3, 31)
    assert data_dir == data_dir_path
    assert download_screen.is_download_active()
    assert download_screen.current_state() == "loading"


# =====================================================================
# Progress signal handling
# =====================================================================


def test_progress_signal_updates_progress_card(download_screen, qtbot):
    """Emitir progress → ProgressCard atualiza barra + contrato."""
    from data_downloader.public_api.handle import DownloadProgress

    download_screen._download_active = True
    download_screen._set_state("loading")

    p = DownloadProgress(
        total=10,
        done=4,
        message="INF_FETCHING_CHUNK",
        trades_received=1234,
        current_contract="WDOJ26",
    )
    download_screen._on_progress(p)
    qtbot.wait(50)

    assert download_screen._progress_card._contract_value.text() == "WDOJ26"
    assert download_screen._progress_card._bar.value() == 40


def test_progress_with_99_reconnect_shows_yellow_banner(download_screen, qtbot):
    """is_99_reconnect=True → banner amarelo visível com texto LITERAL."""
    from data_downloader.public_api.handle import DownloadProgress
    from data_downloader.ui.widgets.progress_card import (
        WAR_99_RECONNECT_LITERAL,
    )

    download_screen._download_active = True
    download_screen._set_state("loading")

    p = DownloadProgress(
        total=100,
        done=99,
        message="WAR_99_RECONNECT",
        trades_received=999_999,
        current_contract="WDOJ26",
        is_99_reconnect=True,
    )
    download_screen._on_progress(p)
    qtbot.wait(50)

    pc = download_screen._progress_card
    assert pc._reconnect_banner.isVisible()
    # Texto LITERAL preservado byte-a-byte (R17 Uma authority).
    assert pc._reconnect_text.text() == WAR_99_RECONNECT_LITERAL
    # Barra com state=reconnecting.
    assert pc._bar.property("state") == "reconnecting"


# =====================================================================
# Error / Cancel / Finished
# =====================================================================


def test_error_signal_transitions_to_error_state(download_screen, qtbot):
    from data_downloader.public_api.exceptions import DLLInitError

    download_screen._download_active = True
    download_screen._set_state("loading")

    exc = DLLInitError(-1, "NL_NO_LICENSE", "license expired")
    download_screen._on_error(exc)
    qtbot.wait(50)

    assert download_screen.current_state() == "error"
    assert not download_screen.is_download_active()
    # Título do error card carregado via humanized_message → microcopy entry.
    assert download_screen._error_title.text()


def test_cancelled_signal_returns_to_normal_with_toast(download_screen, qtbot):
    from data_downloader.public_api.exceptions import OperationCancelled

    download_screen._download_active = True
    download_screen._set_state("loading")

    exc = OperationCancelled("cancelled by user", details={"trades_preserved": 100})
    download_screen._on_cancelled(exc)
    qtbot.wait(50)

    assert download_screen.current_state() == "normal"
    assert not download_screen.is_download_active()
    assert download_screen._toast.isVisible()


def test_finished_signal_shows_success_toast(download_screen, qtbot):
    from data_downloader.public_api.handle import DownloadResult

    download_screen._download_active = True
    download_screen._set_state("loading")

    result = DownloadResult(
        job_id="job-1",
        symbol="WDOJ26",
        exchange="F",
        actual_start=None,
        actual_end=None,
        trades_count=1234,
        partitions=(),
        duration_seconds=12.3,
        status="completed",
    )
    download_screen._on_finished(result)
    qtbot.wait(50)

    # Wave A (Felix v1.0.8): _on_finished agora vai para STATE_SUCCESS
    # (card persistente "ta feio quando baixou" com CTA), não STATE_NORMAL.
    assert download_screen.current_state() == "success"
    assert not download_screen.is_download_active()
    assert download_screen._toast.isVisible()
    assert "WDOJ26" in download_screen._toast_text.text()


# =====================================================================
# Cancel handling
# =====================================================================


def test_request_cancel_when_active_dispatches_to_adapter(download_screen, qtbot, monkeypatch):
    """Cancel via API pública (sem dialog modal interativo)."""
    cancel_emits = []
    download_screen._request_cancel.connect(lambda: cancel_emits.append(True))

    # Setup loading state.
    download_screen._download_active = True
    download_screen._set_state("loading")

    # Simular escolha "Sim, cancelar" no QMessageBox via patch.
    from PySide6.QtWidgets import QMessageBox

    def fake_exec(self):
        # Simula clicar no primeiro botão (yes).
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0])

    download_screen._on_cancel_clicked()
    qtbot.waitUntil(lambda: len(cancel_emits) > 0, timeout=2000)
    assert len(cancel_emits) >= 1
    assert download_screen._progress_card._bar.property("state") == "cancelling"


def test_handle_escape_when_no_active_returns_false(download_screen):
    assert not download_screen.is_download_active()
    assert download_screen.handle_escape() is False


# =====================================================================
# State machine emits state_changed
# =====================================================================


def test_state_changed_signal_emitted(download_screen, qtbot):
    states = []
    download_screen.state_changed.connect(states.append)

    download_screen._set_state("loading")
    download_screen._set_state("error")
    download_screen._set_state("normal")

    assert states == ["loading", "error", "normal"]
