"""Integration tests — Status bar do MainWindow (Story 3.3 — Wave 18).

Owner: Felix (impl) | Audit: Pyro (consumer Protocol), Uma (microcopy).

Cobertura:
    - Status bar exibe DLL status placeholder + versão (graceful sem exporter).
    - MetricsPanel embedded na status bar.
    - set_metrics_exporter liga/desliga consumo (graceful degradation).
    - Adapter MetricsAdapter shutdown limpo no closeEvent.
    - DLL status muda via _on_dll_status_changed (sem regressão Story 3.2).

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import contextlib
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def main_window(qtbot):
    """MainWindow com cleanup automático dos adapters."""
    from data_downloader.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    yield window

    # Shutdown explícito de todos os adapters.
    for screen_id in ("download", "catalog", "settings"):
        with contextlib.suppress(Exception):
            screen = window._screens.get(screen_id)
            if screen is not None and hasattr(screen, "_adapter"):
                screen._adapter.shutdown()
    with contextlib.suppress(Exception):
        window._metrics_adapter.shutdown()


# =====================================================================
# Status bar layout
# =====================================================================


def test_status_bar_has_dll_label(main_window):
    """Status bar mostra DLL status placeholder no estado inicial."""
    assert main_window._dll_status_label is not None
    txt = main_window._dll_status_label.text()
    # Microcopy resolve.
    assert "<microcopy id not found" not in txt
    # Estado inicial = disconnected.
    assert main_window._dll_status_label.property("status") == "disconnected"


def test_status_bar_has_metrics_panel(main_window):
    """Status bar embeda MetricsPanel (Story 3.3)."""
    from data_downloader.ui.widgets.metrics_panel import MetricsPanel

    assert hasattr(main_window, "_metrics_panel")
    assert isinstance(main_window._metrics_panel, MetricsPanel)


def test_status_bar_has_metrics_adapter(main_window):
    """MetricsAdapter instanciado e iniciado."""
    from data_downloader.ui.widgets.metrics_panel import MetricsAdapter

    assert hasattr(main_window, "_metrics_adapter")
    assert isinstance(main_window._metrics_adapter, MetricsAdapter)


def test_status_bar_metrics_off_initially(main_window, qtbot):
    """Sem exporter setado → painel mostra 'off'."""
    qtbot.wait(150)
    panel = main_window._metrics_panel
    txt = panel._exporter_label.text()
    assert "off" in txt.lower() or "Métricas" in txt
    assert panel.exporter_url() is None


# =====================================================================
# DLL status changes (sem regressão Story 3.2)
# =====================================================================


def test_dll_status_changes_to_connected(main_window):
    main_window._on_dll_status_changed("connected")
    assert main_window._dll_status_label.property("status") == "connected"
    assert "<microcopy id not found" not in main_window._dll_status_label.text()


def test_dll_status_changes_to_testing(main_window):
    main_window._on_dll_status_changed("testing")
    assert main_window._dll_status_label.property("status") == "connecting"


def test_dll_status_changes_to_disconnected(main_window):
    main_window._on_dll_status_changed("connected")
    main_window._on_dll_status_changed("disconnected")
    assert main_window._dll_status_label.property("status") == "disconnected"


# =====================================================================
# set_metrics_exporter — graceful degradation
# =====================================================================


def test_set_metrics_exporter_with_real_exporter(main_window, qtbot):
    """Liga PrometheusExporter real → snapshots fluem para o panel."""
    from data_downloader.observability import PrometheusExporter

    exporter = PrometheusExporter(port=9098)
    try:
        exporter.set_gauge("active_downloads", 1)
        exporter.set_gauge("dll_queue_depth", 250)
        exporter.set_gauge("write_queue_depth", 12)
        exporter.incr_counter("parquet_writes_total", labels={"symbol": "WDOJ26"})

        main_window.set_metrics_exporter(exporter)

        # Aguarda 1 tick (default 1000ms; o panel já recebe imediato no start).
        panel = main_window._metrics_panel
        qtbot.waitUntil(
            lambda: panel.snapshot() is not None and panel.snapshot().active_downloads == 1,
            timeout=3000,
        )

        snap = panel.snapshot()
        assert snap is not None
        assert snap.active_downloads == 1
        assert snap.dll_queue_depth == 250
        assert snap.write_queue_depth == 12
        assert snap.parquet_writes_total == 1
        # Active highlight.
        assert panel._active_label.property("active") is True
    finally:
        exporter.stop()
        main_window.set_metrics_exporter(None)


def test_set_metrics_exporter_none_is_graceful(main_window, qtbot):
    """set_metrics_exporter(None) é graceful — não levanta."""
    main_window.set_metrics_exporter(None)
    qtbot.wait(50)
    # Panel continua existindo, em estado off.
    assert main_window._metrics_panel.exporter_url() is None


def test_close_event_shuts_down_metrics_adapter(qtbot):
    """closeEvent dispara shutdown limpo do adapter."""
    from data_downloader.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    # Guarda referência antes do close.
    adapter = window._metrics_adapter

    # Close window — dispara closeEvent.
    window.close()
    qtbot.wait(100)

    # Adapter deve ter thread None após shutdown.
    assert adapter._thread is None
