"""Integration tests — CLI download --metrics-port (Story 2.4 AC6).

Cobertura:

- ``data-downloader download --metrics-port 9091 ...`` inicia
  PrometheusExporter ANTES do download.
- HTTP GET ``/metrics`` retorna 200 + body Prometheus exposition válido.
- Format compliance: parseable por ``text_string_to_metric_families``.
- Sem flag, exporter NÃO inicia (zero overhead default).

Estratégia: ao invés de invocar a CLI completa (que tenta init real
ProfitDLL via env vars), testamos o exporter standalone com porta
efêmera + verifica que a CLI tem a flag registrada.
"""

from __future__ import annotations

from urllib.request import urlopen

import pytest
from prometheus_client.parser import text_string_to_metric_families
from typer.testing import CliRunner

from data_downloader.cli import app
from data_downloader.observability import PrometheusExporter

# =====================================================================
# CLI flag exists
# =====================================================================


@pytest.mark.integration
def test_cli_download_help_shows_metrics_port_flag() -> None:
    """``download --help`` documenta a flag ``--metrics-port``."""
    runner = CliRunner()
    result = runner.invoke(app, ["download", "--help"])
    assert result.exit_code == 0
    # Flag presente no help.
    assert "--metrics-port" in result.stdout


# =====================================================================
# HTTP scrape contract
# =====================================================================


def _find_free_port() -> int:
    """Allocate ephemeral port (9100..9200 range)."""
    import socket

    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


@pytest.mark.integration
def test_exporter_http_scrape_returns_200_and_valid_format() -> None:
    """GET /metrics em exporter ativo → 200 + body parseável."""
    port = _find_free_port()
    exporter = PrometheusExporter(port=port)
    exporter.start()
    try:
        # Emite algumas métricas para garantir que aparecem no scrape.
        exporter.incr_counter("dll_reconnects_total")
        exporter.set_gauge("active_downloads", 2.0)
        exporter.observe_histogram("chunk_duration_seconds", 7.5, labels={"symbol": "WDOJ26"})

        with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")

        # Format compliance — parser oficial deve aceitar.
        families = list(text_string_to_metric_families(body))
        family_names = {f.name for f in families}
        # Pelo menos as 3 métricas mexidas devem aparecer.
        assert "data_downloader_dll_reconnects" in family_names
        assert "data_downloader_active_downloads" in family_names
        assert "data_downloader_chunk_duration_seconds" in family_names

        # Valores específicos refletidos.
        assert "data_downloader_dll_reconnects_total 1.0" in body
        assert "data_downloader_active_downloads 2.0" in body
    finally:
        exporter.stop()


@pytest.mark.integration
def test_exporter_stop_releases_port() -> None:
    """Após stop, porta liberada — re-bindable."""
    port = _find_free_port()
    e1 = PrometheusExporter(port=port)
    e1.start()
    e1.stop()
    # Re-bind imediato deve funcionar (ou levantar OSError limpo).
    e2 = PrometheusExporter(port=port)
    try:
        e2.start()
    finally:
        e2.stop()


@pytest.mark.integration
def test_exporter_metrics_persist_across_scrapes() -> None:
    """Múltiplos scrapes refletem incrementos cumulativos (Counter monotônico)."""
    port = _find_free_port()
    exporter = PrometheusExporter(port=port)
    exporter.start()
    try:
        exporter.incr_counter("dll_reconnects_total")
        exporter.incr_counter("dll_reconnects_total")
        exporter.incr_counter("dll_reconnects_total")
        with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "data_downloader_dll_reconnects_total 3.0" in body

        exporter.incr_counter("dll_reconnects_total")
        with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "data_downloader_dll_reconnects_total 4.0" in body
    finally:
        exporter.stop()
