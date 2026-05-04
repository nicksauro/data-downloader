"""data_downloader.ui.widgets.metrics_panel — Painel de métricas (Story 3.3).

Owner: Felix (impl) | Design: Uma (microcopy + paleta) | Audit: Pyro
(consumo MetricsEmitter — sem polling pesado), Aria (fronteira observability
preservada — UI consome apenas Protocol público).

Wave 18 (COUNCIL-26): integração Story 2.4 Prometheus na UI.

Componentes:

- :class:`MetricsSnapshot` — dataclass tipada com gauges/counters
  relevantes ao usuário (active_downloads, dll_queue_depth,
  write_queue_depth, parquet_writes_total).
- :class:`MetricsAdapter` — :class:`QObject` em thread separada que faz
  polling local (mesma processo) de :class:`PrometheusExporter` ou
  HTTP scrape (futuro V2). Emite ``metrics_updated(MetricsSnapshot)``
  via :class:`Qt.QueuedConnection`. Graceful quando exporter não
  configurado: emite ``exporter_unavailable()`` uma vez.
- :class:`MetricsPanel` — :class:`QWidget` compacto pronto para embed
  em status bar OU em diálogo "Métricas Detalhadas" (Ctrl+Shift+M, V2).
  Atualiza via slot ``set_snapshot``. NÃO faz polling — só renderiza.

Padrões aplicados (D1/D2 COUNCIL-23):

- Adapter SEM parent Qt (move para QThread).
- Cross-thread via signal Queued.
- Microcopy 100% catalog-sourced (R17).
- Sem polling no MainThread — adapter tem QTimer próprio na worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from data_downloader.ui.microcopy_loader import format_msg

__all__ = [
    "MetricsAdapter",
    "MetricsPanel",
    "MetricsSnapshot",
]


@dataclass(frozen=True)
class MetricsSnapshot:
    """Snapshot imutável de métricas relevantes para a status bar.

    Todos os campos são opcionais — ``None`` significa "não disponível"
    (e.g. exporter não rodando ou métrica nunca foi setada). UI renderiza
    placeholders ``—`` nesses casos.

    Campos:
        active_downloads: Gauge ``data_downloader_active_downloads``.
        dll_queue_depth: Gauge ``data_downloader_dll_queue_depth``.
        write_queue_depth: Gauge ``data_downloader_write_queue_depth``.
        parquet_writes_total: Counter ``data_downloader_parquet_writes_total``
            (somatório de todos os labels symbol).
        exporter_port: Porta HTTP do exporter (None se desabilitado).
        exporter_running: True se servidor HTTP do exporter está vivo.
    """

    active_downloads: int | None = None
    dll_queue_depth: int | None = None
    write_queue_depth: int | None = None
    parquet_writes_total: int | None = None
    exporter_port: int | None = None
    exporter_running: bool = False


class MetricsAdapter(QObject):
    """Adapter QObject em QThread separada que faz polling do exporter local.

    NÃO acopla a :class:`PrometheusExporter` em hard-import — recebe
    referência opcional via setter. Quando ``set_exporter(None)`` (default),
    adapter emite ``exporter_unavailable`` e fica em modo idle (não
    consome CPU).

    Sinais:
        metrics_updated(object): Payload :class:`MetricsSnapshot` —
            cross-thread via QueuedConnection.
        exporter_unavailable(): Emitido uma vez quando exporter é None
            ou polling falha — UI mostra "métricas off".

    Padrão D2 COUNCIL-23 — adapter SEM parent Qt; movido para QThread
    via :meth:`start`. Caller mantém referência forte (``_owner``).
    """

    metrics_updated = Signal(object)
    exporter_unavailable = Signal()

    # Intervalo de polling (1s — Pyro: suficiente para UI, sem hot path).
    DEFAULT_INTERVAL_MS = 1000

    def __init__(
        self,
        owner: QObject | None = None,
        interval_ms: int = DEFAULT_INTERVAL_MS,
    ) -> None:
        # D2 COUNCIL-23: adapter sem parent Qt para permitir moveToThread.
        super().__init__(None)
        self._owner = owner  # referência forte (anti-GC)
        self._interval_ms = max(250, int(interval_ms))
        self._exporter: object | None = None
        self._thread: QThread | None = None
        self._timer: QTimer | None = None
        self._unavailable_emitted = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def set_exporter(self, exporter: object | None) -> None:
        """Define qual exporter consultar. ``None`` = adapter idle."""
        self._exporter = exporter
        if exporter is None:
            # Reset flag para que possamos emitir de novo se voltar a None
            # depois de ter um exporter (ex.: troca dinâmica V2).
            self._unavailable_emitted = False

    def start(self) -> None:
        """Sobe a worker thread + timer interno de polling."""
        if self._thread is not None:
            return
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._on_thread_started)
        self._thread.start()

    def shutdown(self) -> None:
        """Encerra worker thread limpo (D3 COUNCIL-23)."""
        if self._thread is None:
            return
        # Para timer no thread alvo via invokeMethod / direct stop.
        try:
            if self._timer is not None:
                self._timer.stop()
        except Exception:
            pass
        try:
            self._thread.quit()
            self._thread.wait(1500)
        except Exception:
            pass
        finally:
            self._thread = None
            self._timer = None

    # ------------------------------------------------------------------
    # Thread internals
    # ------------------------------------------------------------------

    def _on_thread_started(self) -> None:
        """Inicializa QTimer DENTRO da worker thread (parent = self)."""
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._poll_once)
        self._timer.start()
        # Tick imediato para render inicial.
        self._poll_once()

    def _poll_once(self) -> None:
        """Coleta snapshot atual do exporter e emite signal."""
        exporter = self._exporter
        if exporter is None:
            if not self._unavailable_emitted:
                self._unavailable_emitted = True
                self.exporter_unavailable.emit()
            return
        try:
            snapshot = self._extract_snapshot(exporter)
        except Exception:
            # Falha silenciosa — emite snapshot vazio + unavailable.
            if not self._unavailable_emitted:
                self._unavailable_emitted = True
                self.exporter_unavailable.emit()
            return
        self._unavailable_emitted = False
        self.metrics_updated.emit(snapshot)

    @staticmethod
    def _extract_snapshot(exporter: object) -> MetricsSnapshot:
        """Lê valores correntes do PrometheusExporter via API pública.

        Usa :meth:`render_text` para evitar dependência em internals
        (registry/_value). Parser minimalista — só os 4 campos que a
        status bar mostra. Falhas em parsing são absorvidas (campo fica
        ``None``).
        """
        # Acesso direto via dict interno é mais rápido que parse de texto;
        # o exporter expõe ``_gauges`` e ``_counters``. Preferimos a API
        # de introspecção pública quando existir.
        active = MetricsAdapter._read_gauge(exporter, "active_downloads")
        dll_q = MetricsAdapter._read_gauge(exporter, "dll_queue_depth")
        wr_q = MetricsAdapter._read_gauge(exporter, "write_queue_depth")
        parquet_total = MetricsAdapter._read_counter_sum(exporter, "parquet_writes_total")
        port = getattr(exporter, "port", None)
        running = bool(getattr(exporter, "is_running", False))
        return MetricsSnapshot(
            active_downloads=int(active) if active is not None else None,
            dll_queue_depth=int(dll_q) if dll_q is not None else None,
            write_queue_depth=int(wr_q) if wr_q is not None else None,
            parquet_writes_total=int(parquet_total) if parquet_total is not None else None,
            exporter_port=int(port) if port is not None else None,
            exporter_running=running,
        )

    @staticmethod
    def _read_gauge(exporter: object, name: str) -> float | None:
        """Lê valor corrente de um Gauge sem labels (canonical observability)."""
        gauges = getattr(exporter, "_gauges", None)
        if not isinstance(gauges, dict):
            return None
        gauge = gauges.get(name)
        if gauge is None:
            return None
        try:
            # prometheus_client Gauge sem labels: ._value.get() ou .collect().
            samples = list(gauge.collect())
            for metric_family in samples:
                for sample in metric_family.samples:
                    if sample.name.endswith(name):
                        return float(sample.value)
        except Exception:
            return None
        return None

    @staticmethod
    def _read_counter_sum(exporter: object, name: str) -> float | None:
        """Soma todos os labels de um Counter (e.g. parquet_writes_total{symbol})."""
        counters = getattr(exporter, "_counters", None)
        if not isinstance(counters, dict):
            return None
        counter = counters.get(name)
        if counter is None:
            return None
        try:
            total = 0.0
            for metric_family in counter.collect():
                for sample in metric_family.samples:
                    # Counter expõe samples ``_total`` (sufixado pelo client).
                    if sample.name.endswith(f"{name}_total") or sample.name.endswith(name):
                        total += float(sample.value)
            return total
        except Exception:
            return None


class MetricsPanel(QWidget):
    """Display compacto de métricas (active downloads / queues / trades).

    Pronto para embed em :class:`QStatusBar` (modo compact) ou em
    :class:`QDialog` (modo "Métricas Detalhadas" — V2 Ctrl+Shift+M).

    Atualiza via slot público :meth:`set_snapshot`. NÃO faz polling — é
    desacoplado da fonte de dados (Felix segue padrão signal/slot).

    Modos:
        compact (default): tudo em uma linha, ~250-400px, ideal status bar.
        detailed: linhas separadas com labels, ~280px wide, para diálogo.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        compact: bool = True,
    ) -> None:
        super().__init__(parent)
        self._compact = compact
        self._exporter_url: str | None = None
        self._snapshot: MetricsSnapshot | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Active downloads.
        self._active_label = QLabel(self)
        self._active_label.setProperty("role", "metric")
        layout.addWidget(self._active_label)

        # Queue depth (DLL/Write compactado: "Q: 0/0").
        self._queue_label = QLabel(self)
        self._queue_label.setProperty("role", "metric")
        layout.addWidget(self._queue_label)

        # Trades persisted total.
        self._trades_label = QLabel(self)
        self._trades_label.setProperty("role", "metric")
        layout.addWidget(self._trades_label)

        # Exporter URL link / off indicator (clickable copia URL).
        self._exporter_label = QLabel(self)
        self._exporter_label.setProperty("role", "metric-off")
        self._exporter_label.setCursor(self.cursor())
        # mousePressEvent custom em label simples — usamos linkActivated pattern.
        self._exporter_label.setOpenExternalLinks(False)
        self._exporter_label.linkActivated.connect(self._on_link_clicked)
        layout.addWidget(self._exporter_label)

        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Renderiza estado "off" inicial.
        self.set_snapshot(MetricsSnapshot())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_snapshot(self, snapshot: MetricsSnapshot) -> None:
        """Atualiza display com novo snapshot. Slot público (signal target)."""
        self._snapshot = snapshot

        # Active downloads — accent quando > 0.
        active = snapshot.active_downloads
        active_text = format_msg(
            "LBL_METRICS_ACTIVE_DOWNLOADS",
            n=("—" if active is None else str(active)),
        )
        self._active_label.setText(active_text)
        self._active_label.setProperty("active", bool(active and active > 0))
        self._refresh_property(self._active_label)

        # Queue depths (compacto: "Q: dll/write").
        dll_q = snapshot.dll_queue_depth
        write_q = snapshot.write_queue_depth
        queue_text = format_msg(
            "LBL_METRICS_QUEUE_DEPTH",
            dll=("—" if dll_q is None else str(dll_q)),
            write=("—" if write_q is None else str(write_q)),
        )
        self._queue_label.setText(queue_text)
        # Highlight quando alguma fila está cheia (>50% cap conhecido).
        backpressure = bool(
            (dll_q is not None and dll_q > 50000) or (write_q is not None and write_q > 2500)
        )
        self._queue_label.setProperty("active", backpressure)
        self._refresh_property(self._queue_label)

        # Trades total — formatação humana (12_345 → "12.345").
        trades = snapshot.parquet_writes_total
        trades_str = "—" if trades is None else f"{trades:,}".replace(",", ".")
        self._trades_label.setText(format_msg("LBL_METRICS_TRADES_TOTAL", n=trades_str))

        # Exporter URL / off.
        if snapshot.exporter_running and snapshot.exporter_port is not None:
            url = f"http://localhost:{snapshot.exporter_port}/metrics"
            self._exporter_url = url
            link_text = format_msg("LBL_STATUSBAR_METRICS_PORT", port=snapshot.exporter_port)
            # HTML link para clique copia (interno).
            self._exporter_label.setText(f'<a href="copy" style="color:#3DD0E1;">{link_text}</a>')
            self._exporter_label.setProperty("role", "metric-link")
            self._exporter_label.setToolTip(url)
        else:
            self._exporter_url = None
            self._exporter_label.setText(format_msg("LBL_METRICS_OFF"))
            self._exporter_label.setProperty("role", "metric-off")
            self._exporter_label.setToolTip("")
        self._refresh_property(self._exporter_label)

    def snapshot(self) -> MetricsSnapshot | None:
        """Último snapshot recebido (útil em testes)."""
        return self._snapshot

    def exporter_url(self) -> str | None:
        """URL do exporter atualmente exibida (None se off)."""
        return self._exporter_url

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_link_clicked(self, _link: str) -> None:
        """Click no label do exporter copia URL para clipboard + toast."""
        url = self._exporter_url
        if not url:
            return
        try:
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(url)
        except Exception:
            return
        # Toast tooltip-like via setToolTip refresh (simples, sem dep extra).
        self._exporter_label.setToolTip(format_msg("TST_METRICS_URL_COPIED"))

    @staticmethod
    def _refresh_property(widget: QWidget) -> None:
        """Re-aplica QSS após mudança de property dinâmica."""
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
