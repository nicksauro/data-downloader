"""Unit tests — PrometheusExporter (Story 2.4 AC2/AC3/AC4).

Cobertura:

- Registry contém todos os Counters/Gauges/Histograms canônicos
  (ADR-013 §Métricas V1 + COUNCIL-05 §D3) com prefixo
  ``data_downloader_``.
- ``incr_counter`` incrementa Counter; valor é refletido em
  ``render_text`` (formato Prometheus exposition).
- ``set_gauge`` seta Gauge.
- ``observe_histogram`` registra observações (bucket counts).
- ``render_text`` produz output parseável por
  ``prometheus_client.parser.text_string_to_metric_families``.
- Emitter desconhecido → log warning, não levanta.
- Registries isolados (cada exporter tem seu próprio) — testes não
  precisam de fixture global de reset.
"""

from __future__ import annotations

import pytest
from prometheus_client.parser import text_string_to_metric_families

from data_downloader.observability.prometheus_exporter import (
    CANONICAL_COUNTERS,
    CANONICAL_GAUGES,
    CANONICAL_HISTOGRAMS,
    METRIC_PREFIX,
    MultiTargetEmitter,
    PrometheusExporter,
)

# =====================================================================
# Registry contains all canonical metrics
# =====================================================================


@pytest.mark.unit
def test_registry_contains_all_canonical_counters() -> None:
    """Cada Counter canônico está presente no registry com prefixo."""
    exporter = PrometheusExporter(port=0)
    text = exporter.render_text()
    for spec in CANONICAL_COUNTERS:
        # Counter é exposto como ``<name>_total`` no formato exposition;
        # nosso ``name`` JÁ tem ``_total`` no fim, então prometheus
        # exposition usa o nome como está.
        full_name = METRIC_PREFIX + spec.name
        assert f"# TYPE {full_name} counter" in text, f"Counter {full_name} not registered"


@pytest.mark.unit
def test_registry_contains_all_canonical_gauges() -> None:
    """Cada Gauge canônico está presente no registry com prefixo."""
    exporter = PrometheusExporter(port=0)
    text = exporter.render_text()
    for spec in CANONICAL_GAUGES:
        full_name = METRIC_PREFIX + spec.name
        assert f"# TYPE {full_name} gauge" in text, f"Gauge {full_name} not registered"


@pytest.mark.unit
def test_registry_contains_all_canonical_histograms() -> None:
    """Cada Histogram canônico está presente no registry com prefixo."""
    exporter = PrometheusExporter(port=0)
    text = exporter.render_text()
    for spec in CANONICAL_HISTOGRAMS:
        full_name = METRIC_PREFIX + spec.name
        assert f"# TYPE {full_name} histogram" in text, f"Histogram {full_name} not registered"


@pytest.mark.unit
def test_canonical_counts_match_story_spec() -> None:
    """Story 2.4 AC3 exige 8 counters, 5 gauges, 5 histograms."""
    assert len(CANONICAL_COUNTERS) == 8
    assert len(CANONICAL_GAUGES) == 5
    assert len(CANONICAL_HISTOGRAMS) == 5


# =====================================================================
# Counter / Gauge / Histogram operations
# =====================================================================


@pytest.mark.unit
def test_incr_counter_no_labels_increments() -> None:
    """incr_counter sem labels (dll_reconnects_total) incrementa de 0 → 1."""
    exporter = PrometheusExporter(port=0)
    exporter.incr_counter("dll_reconnects_total")
    text = exporter.render_text()
    assert "data_downloader_dll_reconnects_total 1.0" in text


@pytest.mark.unit
def test_incr_counter_with_labels() -> None:
    """incr_counter com labels (chunks_completed_total) incrementa série rotulada."""
    exporter = PrometheusExporter(port=0)
    exporter.incr_counter(
        "chunks_completed_total", labels={"symbol": "WDOJ26", "status": "success"}
    )
    exporter.incr_counter(
        "chunks_completed_total", labels={"symbol": "WDOJ26", "status": "success"}
    )
    text = exporter.render_text()
    assert 'data_downloader_chunks_completed_total{status="success",symbol="WDOJ26"} 2.0' in text


@pytest.mark.unit
def test_set_gauge_no_labels() -> None:
    """set_gauge no Gauge sem labels reflete o valor."""
    exporter = PrometheusExporter(port=0)
    exporter.set_gauge("active_downloads", 3.0)
    text = exporter.render_text()
    assert "data_downloader_active_downloads 3.0" in text


@pytest.mark.unit
def test_observe_histogram_with_labels() -> None:
    """observe_histogram registra observação no bucket correto."""
    exporter = PrometheusExporter(port=0)
    exporter.observe_histogram("chunk_duration_seconds", 12.0, labels={"symbol": "WDOJ26"})
    text = exporter.render_text()
    # Bucket >= 30 deve conter 1 (12 < 30).
    assert "chunk_duration_seconds_count" in text
    # Sum deve refletir 12.0.
    assert 'data_downloader_chunk_duration_seconds_sum{symbol="WDOJ26"} 12.0' in text


# =====================================================================
# Format compliance — parser parses output
# =====================================================================


@pytest.mark.unit
def test_render_text_is_parseable_by_prometheus_parser() -> None:
    """Output do exporter é parseável pelo parser oficial."""
    exporter = PrometheusExporter(port=0)
    exporter.incr_counter("dll_reconnects_total")
    exporter.set_gauge("active_downloads", 1.0)
    exporter.observe_histogram("chunk_duration_seconds", 5.0, labels={"symbol": "WDOJ26"})
    text = exporter.render_text()

    families = list(text_string_to_metric_families(text))
    family_names = {f.name for f in families}

    # Todas as métricas canônicas devem aparecer (nome sem _total para
    # counter, sem nada extra para gauge/histogram).
    expected_counter_names = {
        METRIC_PREFIX + spec.name.removesuffix("_total") for spec in CANONICAL_COUNTERS
    }
    expected_gauge_names = {METRIC_PREFIX + spec.name for spec in CANONICAL_GAUGES}
    expected_histogram_names = {METRIC_PREFIX + spec.name for spec in CANONICAL_HISTOGRAMS}

    for n in expected_counter_names:
        assert n in family_names, f"Counter family {n} missing in parsed output"
    for n in expected_gauge_names:
        assert n in family_names, f"Gauge family {n} missing in parsed output"
    for n in expected_histogram_names:
        assert n in family_names, f"Histogram family {n} missing in parsed output"


@pytest.mark.unit
def test_metric_types_are_correct_in_parsed_output() -> None:
    """Cada família tem o type correto após parse."""
    exporter = PrometheusExporter(port=0)
    text = exporter.render_text()
    families = {f.name: f for f in text_string_to_metric_families(text)}

    for spec in CANONICAL_COUNTERS:
        # Counter exposition: nome SEM ``_total`` no parse.
        name_no_total = METRIC_PREFIX + spec.name.removesuffix("_total")
        assert families[name_no_total].type == "counter"
    for spec in CANONICAL_GAUGES:
        full = METRIC_PREFIX + spec.name
        assert families[full].type == "gauge"
    for spec in CANONICAL_HISTOGRAMS:
        full = METRIC_PREFIX + spec.name
        assert families[full].type == "histogram"


# =====================================================================
# Unknown metrics
# =====================================================================


@pytest.mark.unit
def test_unknown_counter_is_silently_ignored() -> None:
    """Counter desconhecido não levanta — apenas log warning (verificado em runtime)."""
    exporter = PrometheusExporter(port=0)
    # Não levanta.
    exporter.incr_counter("totally_unknown_counter")
    exporter.set_gauge("totally_unknown_gauge", 1.0)
    exporter.observe_histogram("totally_unknown_histogram", 1.0)


# =====================================================================
# Lifecycle (HTTP server start/stop)
# =====================================================================


@pytest.mark.unit
def test_lifecycle_start_stop_idempotent() -> None:
    """start/stop podem ser chamados múltiplas vezes sem erro."""
    exporter = PrometheusExporter(port=0)  # port=0 → SO escolhe porta livre
    # Antes de start, is_running = False.
    assert not exporter.is_running
    exporter.start()
    try:
        assert exporter.is_running
        # Idempotente.
        exporter.start()
    finally:
        exporter.stop()
    assert not exporter.is_running
    # Idempotente.
    exporter.stop()


@pytest.mark.unit
def test_context_manager_starts_and_stops() -> None:
    """``with PrometheusExporter() as e:`` start + stop automaticamente."""
    with PrometheusExporter(port=0) as exporter:
        assert exporter.is_running
    assert not exporter.is_running


# =====================================================================
# MultiTargetEmitter
# =====================================================================


class _SpyEmitter:
    """Spy local — captura chamadas para asserts."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str] | None]] = []
        self.gauges: list[tuple[str, float, dict[str, str] | None]] = []
        self.observations: list[tuple[str, float, dict[str, str] | None]] = []

    def incr_counter(self, name: str, *, labels: dict[str, str] | None = None) -> None:
        self.counters.append((name, labels))

    def set_gauge(self, name: str, value: float, *, labels: dict[str, str] | None = None) -> None:
        self.gauges.append((name, value, labels))

    def observe_histogram(
        self, name: str, value: float, *, labels: dict[str, str] | None = None
    ) -> None:
        self.observations.append((name, value, labels))


@pytest.mark.unit
def test_multi_target_fans_out() -> None:
    """MultiTargetEmitter chama TODOS os targets para cada operação."""
    spy_a = _SpyEmitter()
    spy_b = _SpyEmitter()
    multi = MultiTargetEmitter([spy_a, spy_b])
    multi.incr_counter("foo", labels={"x": "1"})
    multi.set_gauge("bar", 2.0)
    multi.observe_histogram("baz", 0.5, labels={"y": "2"})
    for spy in (spy_a, spy_b):
        assert spy.counters == [("foo", {"x": "1"})]
        assert spy.gauges == [("bar", 2.0, None)]
        assert spy.observations == [("baz", 0.5, {"y": "2"})]


@pytest.mark.unit
def test_multi_target_empty_targets() -> None:
    """MultiTargetEmitter com 0 targets é no-op."""
    multi = MultiTargetEmitter([])
    multi.incr_counter("foo")
    multi.set_gauge("bar", 1.0)
    multi.observe_histogram("baz", 0.1)
    assert multi.targets == ()
