"""Integration tests — MetricsPanel + MetricsAdapter (Story 3.3 — Wave 18).

Owner: Felix (impl) | Audit: Pyro (consumer MetricsEmitter), Aria (Protocol
fronteira observability).

Cobertura:
    - MetricsPanel renderiza snapshot (compact mode).
    - Microcopy resolve sem <microcopy id not found>.
    - Off state quando exporter desabilitado.
    - Active state highlight quando active_downloads > 0.
    - Backpressure highlight quando filas grandes.
    - URL exporter aparece quando running + clipboard copy.
    - MetricsAdapter graceful quando exporter=None (sem crash).
    - MetricsAdapter polling do PrometheusExporter real (smoke).

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def metrics_panel(qtbot):
    """Cria MetricsPanel compact em modo standalone."""
    from data_downloader.ui.widgets.metrics_panel import MetricsPanel

    panel = MetricsPanel(compact=True)
    qtbot.addWidget(panel)
    panel.show()
    yield panel


@pytest.fixture
def real_exporter():
    """Instancia PrometheusExporter real (sem start HTTP — apenas registry)."""
    from data_downloader.observability import PrometheusExporter

    exporter = PrometheusExporter(port=9099)
    yield exporter
    # Best-effort stop (start nunca chamado).
    exporter.stop()


# =====================================================================
# MetricsPanel — render snapshot
# =====================================================================


def test_panel_starts_in_off_state(metrics_panel):
    """Sem snapshot → mostra placeholders + 'Métricas: off'."""
    assert metrics_panel.exporter_url() is None
    # Labels iniciais devem ter o texto da microcopy (sem <not found>).
    txt = metrics_panel._exporter_label.text()
    assert "<microcopy id not found" not in txt
    assert "off" in txt.lower() or "Métricas" in txt


def test_panel_microcopy_resolves(metrics_panel):
    """Nenhum label visível mostra '<microcopy id not found>'."""
    for lbl in (
        metrics_panel._active_label,
        metrics_panel._queue_label,
        metrics_panel._trades_label,
        metrics_panel._exporter_label,
    ):
        assert "<microcopy id not found" not in lbl.text()


def test_panel_renders_active_downloads(metrics_panel):
    """set_snapshot atualiza display de active_downloads."""
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(active_downloads=3))
    # Microcopy é "↓ {n}".
    assert "3" in metrics_panel._active_label.text()
    # active=True quando n > 0 (highlight).
    assert metrics_panel._active_label.property("active") is True


def test_panel_no_active_highlight_when_zero(metrics_panel):
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(active_downloads=0))
    assert "0" in metrics_panel._active_label.text()
    assert metrics_panel._active_label.property("active") is False


def test_panel_renders_queue_depth(metrics_panel):
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(dll_queue_depth=42, write_queue_depth=7))
    txt = metrics_panel._queue_label.text()
    assert "42" in txt
    assert "7" in txt


def test_panel_backpressure_highlight(metrics_panel):
    """Fila > 50_000 (DLL) ou > 2_500 (write) aciona property active=True."""
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(dll_queue_depth=80_000))
    assert metrics_panel._queue_label.property("active") is True

    metrics_panel.set_snapshot(MetricsSnapshot(dll_queue_depth=10))
    assert metrics_panel._queue_label.property("active") is False


def test_panel_renders_trades_total_human_format(metrics_panel):
    """parquet_writes_total formatado como pt-BR (12.345 não 12,345)."""
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(parquet_writes_total=12_345))
    txt = metrics_panel._trades_label.text()
    assert "12.345" in txt


def test_panel_shows_exporter_url_when_running(metrics_panel):
    """Quando exporter_running + port → URL exibida + clicable."""
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(exporter_running=True, exporter_port=9090))
    assert metrics_panel.exporter_url() == "http://localhost:9090/metrics"
    txt = metrics_panel._exporter_label.text()
    assert "9090" in txt
    # Tooltip deve conter URL completa.
    assert "9090" in metrics_panel._exporter_label.toolTip()


def test_panel_off_when_exporter_not_running(metrics_panel):
    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(exporter_running=False, exporter_port=None))
    assert metrics_panel.exporter_url() is None
    txt = metrics_panel._exporter_label.text()
    assert "off" in txt.lower() or "Métricas" in txt


def test_panel_link_click_copies_url(metrics_panel, qtbot):
    """Click no link do exporter copia URL para clipboard."""
    from PySide6.QtGui import QGuiApplication

    from data_downloader.ui.widgets.metrics_panel import MetricsSnapshot

    metrics_panel.set_snapshot(MetricsSnapshot(exporter_running=True, exporter_port=9091))
    # Aciona o slot diretamente (linkActivated com payload "copy").
    metrics_panel._on_link_clicked("copy")
    qtbot.wait(20)

    cb = QGuiApplication.clipboard()
    assert cb is not None
    assert cb.text() == "http://localhost:9091/metrics"


# =====================================================================
# MetricsAdapter — graceful behavior
# =====================================================================


def test_adapter_graceful_when_no_exporter(qtbot):
    """Adapter sem exporter emite exporter_unavailable e fica idle."""
    from data_downloader.ui.widgets.metrics_panel import MetricsAdapter

    received_unavailable = []
    received_snapshots = []
    adapter = MetricsAdapter(interval_ms=250)
    adapter.exporter_unavailable.connect(lambda: received_unavailable.append(1))
    adapter.metrics_updated.connect(received_snapshots.append)
    adapter.start()
    try:
        qtbot.wait(400)  # > 1 tick
        # Sem exporter → unavailable emitted (uma vez no tick inicial).
        assert len(received_unavailable) >= 1
        # Nenhum snapshot deve ser emitido.
        assert received_snapshots == []
    finally:
        adapter.shutdown()


def test_adapter_polls_real_exporter(qtbot, real_exporter):
    """Adapter conectado a exporter real → emite snapshots periódicos."""
    from data_downloader.ui.widgets.metrics_panel import (
        MetricsAdapter,
        MetricsSnapshot,
    )

    # Setar alguns valores no exporter.
    real_exporter.set_gauge("active_downloads", 2)
    real_exporter.set_gauge("dll_queue_depth", 100)
    real_exporter.set_gauge("write_queue_depth", 5)
    real_exporter.incr_counter("parquet_writes_total", labels={"symbol": "WDOJ26"})
    real_exporter.incr_counter("parquet_writes_total", labels={"symbol": "WDOJ26"})

    received: list[MetricsSnapshot] = []
    adapter = MetricsAdapter(interval_ms=250)
    adapter.set_exporter(real_exporter)
    adapter.metrics_updated.connect(received.append)
    adapter.start()
    try:
        qtbot.waitUntil(lambda: len(received) >= 1, timeout=3000)
    finally:
        adapter.shutdown()

    assert received, "Adapter deveria emitir ao menos 1 snapshot."
    snap = received[-1]
    assert snap.active_downloads == 2
    assert snap.dll_queue_depth == 100
    assert snap.write_queue_depth == 5
    assert snap.parquet_writes_total == 2
    assert snap.exporter_port == 9099
    # is_running=False porque não chamamos start() — teste graceful.
    assert snap.exporter_running is False


def test_adapter_shutdown_idempotent(qtbot):
    """shutdown() chamado 2x não levanta."""
    from data_downloader.ui.widgets.metrics_panel import MetricsAdapter

    adapter = MetricsAdapter(interval_ms=250)
    adapter.start()
    qtbot.wait(50)
    adapter.shutdown()
    adapter.shutdown()  # idempotente


def test_adapter_can_swap_exporter(qtbot, real_exporter):
    """set_exporter pode trocar de None → exporter → None sem crash."""
    from data_downloader.ui.widgets.metrics_panel import MetricsAdapter

    adapter = MetricsAdapter(interval_ms=250)
    adapter.start()
    try:
        adapter.set_exporter(real_exporter)
        qtbot.wait(400)
        adapter.set_exporter(None)
        qtbot.wait(400)
    finally:
        adapter.shutdown()
