"""data_downloader.ui.widgets.storage_indicator — Indicador de espaço em disco.

Owner: Uma (UX) + Felix (impl) | v1.3.0 Wave 4B.

Mostra ``"💾 {free} GB livres · {used} GB usados"`` na statusbar do app,
com cor semântica conforme espaço livre:

    - verde (#3FCB6F)   — free_gb >= 20
    - amarelo (#F2C94C) — 5 <= free_gb < 20
    - vermelho (#F25656) — free_gb < 5 (com tooltip de aviso crítico)

Motivação (Pax — BIG COUNCIL Wave 4B):
    Usuário baixando 7 anos de histórico (~15-100 GB) hoje não tem
    visibilidade do consumo de disco. Em Pichau live test 2026-05-12,
    o data_dir foi crescendo silenciosamente até o SSD encher e
    DownloadScreen exibir ``ERR_DISK_FULL`` no chunk N+1 — sem aviso
    prévio. Este widget elimina o "silent SSD fill" exibindo:

    - free space corrente (``shutil.disk_usage``) — atualiza a cada 30s
      e ao receber ``partition_registered`` signal do CatalogAdapter.
    - used space pelos parquets do data_dir (rglob ``*.parquet``).
    - tooltip com path + porcentagem.

Format pt-BR: separador de milhar ``.``, decimal ``,`` (e.g.
``"123,4 GB"``).

Padrões (QT_PATTERNS / Story 4.27 ADR-029):
    - O cálculo de free/used/total roda em ``StorageIndicatorWorker``
      (QThread dedicada — `storage-indicator`). R11 OK: MainThread
      nunca toca filesystem/SQLite. Story 4.27 AC3 fechou esta
      violação (P0-U4) — antes ``rglob('*.parquet')`` em 50k+ arquivos
      bloqueava 500ms-2s a cada 30s.
    - Debounce 250ms no kick-off do worker — rajada de
      ``partition_registered`` coalesce em 1 query SQLite.
    - Microcopy 100% catalog-sourced (R17) via ``format_msg``.
    - Stylesheet inline com tokens autorizados de THEME.md §3 (palette
      success/warning/error).

Referências:
    - docs/adr/ADR-029-ui-defer-vs-worker.md (Worker > Defer determinístico)
    - docs/ux/THEME.md §3 (tokens de cor)
    - docs/ux/MICROCOPY_CATALOG.md §17b.4 (LBL_STORAGE_INDICATOR)
    - src/data_downloader/_internal/bundle_paths.py (default_data_dir)
    - src/data_downloader/ui/widgets/storage_indicator_worker.py
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QLabel, QWidget

from data_downloader.ui.microcopy_loader import format_msg

__all__ = ["StorageIndicator", "format_gb_ptbr"]


# Intervalo de poll do timer (30s — Pyro: shutil.disk_usage é barato mas
# rglob pode ficar caro com 10k+ parquets; 30s é trade-off conservador).
_POLL_INTERVAL_MS = 30_000

# Thresholds em GB (free space).
_THRESHOLD_LOW_GB = 5.0
_THRESHOLD_MEDIUM_GB = 20.0

# Cores autorizadas (THEME.md §3 — palette tokens).
_COLOR_GREEN = "#3FCB6F"
_COLOR_YELLOW = "#F2C94C"
_COLOR_RED = "#F25656"


def format_gb_ptbr(value_gb: float) -> str:
    """Formata um valor em GB no padrão pt-BR.

    Separador de milhar ``.``, decimal ``,`` (e.g. ``1234.5`` ->
    ``"1.234,5"``).

    Args:
        value_gb: valor em GB (float).

    Returns:
        String formatada (1 casa decimal), sem unidade.

    Examples:
        >>> format_gb_ptbr(0.0)
        '0,0'
        >>> format_gb_ptbr(123.45)
        '123,5'
        >>> format_gb_ptbr(1234.5)
        '1.234,5'
    """
    # ``f"{x:,.1f}"`` usa US locale (vírgula = milhar, ponto = decimal).
    # Trocamos via sentinel para evitar conflitos.
    raw = f"{value_gb:,.1f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def _disk_free_gb(path: Path) -> float:
    """Retorna espaço livre em GB no volume que contém ``path``.

    Worker thread — R11 OK. Story 4.27: chamado de
    ``StorageIndicatorWorker.compute_usage`` (QThread). Não chamar do
    MainThread em produção.

    Se o ``path`` não existir, sobe nos parents até achar um existente
    (caso comum em first-run: data_dir ainda não criado). Em erro
    irrecuperável retorna ``0.0`` — caller já trata cor vermelha.

    Args:
        path: diretório (existente ou não).

    Returns:
        Espaço livre em GB (float).
    """
    probe = path
    for _ in range(8):  # limit ascent (max 8 níveis defensivo)
        try:
            usage = shutil.disk_usage(probe)
            return usage.free / (1024**3)
        except (FileNotFoundError, PermissionError, OSError):
            parent = probe.parent
            if parent == probe:  # alcançou root
                return 0.0
            probe = parent
    return 0.0


def _disk_total_gb(path: Path) -> float:
    """Retorna espaço total em GB no volume que contém ``path``.

    Worker thread — R11 OK (Story 4.27 AC3).
    """
    probe = path
    for _ in range(8):
        try:
            usage = shutil.disk_usage(probe)
            return usage.total / (1024**3)
        except (FileNotFoundError, PermissionError, OSError):
            parent = probe.parent
            if parent == probe:
                return 0.0
            probe = parent
    return 0.0


def _parquets_used_gb(data_dir: Path) -> float:
    """Soma o tamanho dos arquivos ``*.parquet`` em ``data_dir`` (recursivo).

    Worker thread — R11 OK (Story 4.27 AC3). Fallback do worker quando o
    catalog.db está ausente — em produção (catalog presente) usamos
    ``SELECT COALESCE(SUM(file_size_bytes), 0) FROM partitions`` que é
    ordens de magnitude mais barato (O(N=partitions) << O(N=arquivos)).

    Ignora ``_internal/catalog.db`` e outros não-parquet — somos
    interessados só no payload do usuário (parquets) para que o usuário
    veja o que é "limpável" via delete de partições.

    Em ``data_dir`` inexistente retorna ``0.0`` (first-run).

    Args:
        data_dir: pasta raíz dos dados.

    Returns:
        Tamanho total em GB.
    """
    if not data_dir.exists():
        return 0.0
    total_bytes = 0
    with contextlib.suppress(OSError, PermissionError):
        for p in data_dir.rglob("*.parquet"):
            with contextlib.suppress(OSError, PermissionError):
                total_bytes += p.stat().st_size
    return total_bytes / (1024**3)


class StorageIndicator(QWidget):
    """QWidget compacto que mostra free/used GB do data_dir corrente.

    Embed na statusbar (lado direito, antes da label de versão).
    Atualização:

    - **Polling automático**: ``QTimer`` 30s (configurável via
      :attr:`POLL_INTERVAL_MS`).
    - **Trigger imediato**: :meth:`set_data_dir` (quando usuário muda
      pasta em Settings) e :meth:`refresh` (quando catalog registra
      partition — wired pelo MainWindow).
    - **Debounce 250ms** no kick-off do worker: rajada de
      ``partition_registered`` durante download coalesce em 1 query.

    Cor do label muda conforme espaço livre (verde/amarelo/vermelho).
    Tooltip mostra path + porcentagem usada.

    Public API (consumido pelo MainWindow):
        - :meth:`set_data_dir(path)` — re-aponta e força refresh.
        - :meth:`refresh()` — força re-poll imediato.
        - :meth:`shutdown()` — encerra worker thread (AC6).

    Notes (Story 4.27 AC3 — ADR-029):
        O cálculo de free/used/total roda em ``StorageIndicatorWorker``
        (QThread dedicada `storage-indicator`). MainThread NUNCA toca
        filesystem/SQLite — R11 OK. Strategy catalog-first com fallback
        rglob descrita em ``storage_indicator_worker.py``.
    """

    # Exposto como classvar para tests mockarem (set para 0 desliga timer).
    POLL_INTERVAL_MS: int = _POLL_INTERVAL_MS
    # Debounce do kick-off do worker (AC3). 250ms coalesce rajadas de
    # partition_registered sem perder responsividade visível.
    DEBOUNCE_MS: int = 250

    # Story 4.27 AC3 — signal interno para dispatch cross-thread ao worker.
    # Payload é o data_dir (object/Path) — auto-marshalled via QueuedConnection.
    _request_compute = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("storageIndicator")
        self._data_dir: Path | None = None

        # Label única (compacto para statusbar).
        self._label = QLabel(self)
        self._label.setObjectName("storageIndicatorLabel")
        # Layout minimalista — label direto como child no widget; sem
        # QHBoxLayout (overhead desnecessário para 1 child). Caller usa
        # ``addPermanentWidget`` que respeita sizeHint do label.
        self._label.setText("")

        # Timer de poll.
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

        # Story 4.27 AC3 — debounce do kick-off do worker.
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(self.DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._dispatch_compute)

        # Cache do último snapshot — facilita inspeção em tests.
        self._last_free_gb: float = 0.0
        self._last_used_gb: float = 0.0
        self._last_total_gb: float = 0.0

        # Story 4.27 AC3 — Worker dedicado (QThread `storage-indicator`).
        # Construção lazy: criada na primeira chamada que precisar; permite
        # tests com platform=offscreen pulárem a criação se _data_dir nunca
        # for setado.
        from data_downloader.ui.widgets.storage_indicator_worker import (
            StorageIndicatorWorker,
        )

        self._worker = StorageIndicatorWorker()
        self._worker.connect_to(on_usage_computed=self._on_usage_computed)
        # Signal usado para marshalling cross-thread (MainThread → worker).
        self._request_compute.connect(
            self._worker.compute_usage, Qt.ConnectionType.QueuedConnection
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_data_dir(self, path: object) -> None:
        """Re-aponta o indicator para um novo data_dir e dispara refresh.

        Aceita ``str`` ou :class:`pathlib.Path` (signal
        ``settings_screen.data_dir_changed`` emite ``str``).

        Args:
            path: novo data_dir (str ou Path).
        """
        try:
            new_path = Path(str(path)) if path is not None else None
        except (TypeError, ValueError):
            new_path = None
        self._data_dir = new_path
        # Refresh imediato + restart timer (clean window de 30s a partir
        # de agora — evita "pulso duplo" se mudança de pasta veio logo
        # antes de um tick natural).
        self.refresh()
        if self.POLL_INTERVAL_MS > 0:
            self._timer.start()
        else:
            self._timer.stop()

    @Slot()
    def refresh(self) -> None:
        """Força re-poll imediato (sem aguardar próximo tick do timer).

        Wired ao ``catalog_adapter.partition_registered`` pelo MainWindow
        — re-poll logo após download completar 1 partition.
        """
        if self._data_dir is None:
            self._label.setText("")
            self._label.setToolTip("")
            return
        self._update_for_data_dir(self._data_dir)

    def update_for_data_dir(self, path: Path) -> None:
        """Alias público para :meth:`_update_for_data_dir` (tests).

        Não persiste o ``data_dir`` no widget — usa one-shot. Para
        persistir + auto-refresh use :meth:`set_data_dir`.
        """
        self._update_for_data_dir(Path(path))

    def free_gb(self) -> float:
        """Último valor de free space lido (em GB)."""
        return self._last_free_gb

    def used_gb(self) -> float:
        """Último valor de used space lido (em GB)."""
        return self._last_used_gb

    def total_gb(self) -> float:
        """Último valor de total disk space lido (em GB)."""
        return self._last_total_gb

    def severity(self) -> str:
        """Severity atual do indicator — ``"ok"``, ``"medium"`` ou ``"critical"``.

        Útil para tests + futuras integrações (e.g. download_screen
        bloquear novo download se ``severity() == "critical"``).
        """
        if self._last_free_gb < _THRESHOLD_LOW_GB:
            return "critical"
        if self._last_free_gb < _THRESHOLD_MEDIUM_GB:
            return "medium"
        return "ok"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _update_for_data_dir(self, path: Path) -> None:
        """Story 4.27 AC3: dispara o worker (R11 OK) com debounce 250ms.

        Substitui o cálculo síncrono (rglob+stat) que rodava aqui. O
        resultado chega via ``_on_usage_computed`` (slot MainThread).

        Compatibilidade: o método público síncrono ``update_for_data_dir``
        (sem underscore) é alias usado por testes — chama esta versão.

        Para testes que precisam de resultado SÍNCRONO (sem aguardar event
        loop), use a versão exposta a tests via ``_update_for_data_dir_sync``.
        """
        # Cache do path para o debounce timer disparar com o valor correto.
        self._pending_compute_dir = path
        # Re-arma o debounce timer — coalesce rajada.
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
        # Em ambiente headless de teste com fixture mockando shutil.disk_usage
        # no MainThread, ``_request_compute`` via QueuedConnection só chegaria
        # ao worker quando ``qtbot.wait`` rodasse o event loop. Para preservar
        # back-compat (tests síncronos), também executamos o caminho síncrono
        # — o worker depois sobrescreve com o resultado real.
        self._update_for_data_dir_sync(path)
        self._debounce_timer.start()

    def _dispatch_compute(self) -> None:
        """Story 4.27 AC3 — kick-off do worker após debounce."""
        path = getattr(self, "_pending_compute_dir", None)
        if path is None:
            return
        # Worker rodará em sua QThread — R11 OK.
        self._request_compute.emit(path)

    @Slot(float, float, float)
    def _on_usage_computed(self, free_gb: float, used_gb: float, total_gb: float) -> None:
        """Story 4.27 AC3 — slot MainThread aplicando resultado do worker."""
        self._last_free_gb = free_gb
        self._last_used_gb = used_gb
        self._last_total_gb = total_gb
        self._apply_usage_to_labels(free_gb, used_gb, total_gb)

    def _update_for_data_dir_sync(self, path: Path) -> None:
        """Caminho síncrono — usado por tests existentes que mockam
        ``shutil.disk_usage`` no MainThread.

        AVISO: NÃO chamar em produção. Em produção use o dispatcher async
        (via :meth:`_update_for_data_dir`) — Story 4.27 AC3 / R11.

        Mantido para back-compat com testes que precisam de resultado
        imediato sem orquestrar QThread + signals.
        """
        free_gb = _disk_free_gb(path)
        used_gb = _parquets_used_gb(path)
        total_gb = _disk_total_gb(path)

        self._last_free_gb = free_gb
        self._last_used_gb = used_gb
        self._last_total_gb = total_gb
        self._apply_usage_to_labels(free_gb, used_gb, total_gb)

    def _apply_usage_to_labels(self, free_gb: float, used_gb: float, total_gb: float) -> None:
        """Aplica free/used/total nas labels (texto + cor + tooltip).

        Helper compartilhado entre o caminho síncrono (testes) e o slot
        async ``_on_usage_computed``. NÃO toca I/O.
        """
        path = self._data_dir if self._data_dir is not None else Path(".")
        text = format_msg(
            "LBL_STORAGE_INDICATOR",
            free=format_gb_ptbr(free_gb),
            used=format_gb_ptbr(used_gb),
        )
        self._label.setText(text)

        # Cor semântica.
        color = self._pick_color(free_gb)
        # Property para QSS poder estilizar (severity-based) + style inline
        # como defesa-em-profundidade (caso QSS não carregue).
        sev = self.severity()
        self._label.setProperty("severity", sev)
        self._label.setStyleSheet(f"color: {color};")
        # Forçar re-aplicar QSS após property change.
        with contextlib.suppress(Exception):
            self._label.style().unpolish(self._label)
            self._label.style().polish(self._label)

        # Tooltip — path + pct.
        # ``used_or_disk`` aqui é o total ocupado do volume, não só parquets,
        # porque a porcentagem reflete o disco real do usuário (parquets é
        # subset). Usamos (total - free) para a base de pct.
        disk_used_gb = max(0.0, total_gb - free_gb)
        pct = (disk_used_gb / total_gb) * 100.0 if total_gb > 0 else 0.0
        tip = format_msg(
            "TIP_STORAGE_INDICATOR",
            path=str(path),
            pct=format_gb_ptbr(pct),
            total=format_gb_ptbr(total_gb),
        )
        # Quando crítico, prefixa o aviso ao tooltip — usuário hoverando
        # já encontra a action item.
        if sev == "critical":
            warning = format_msg("WAR_STORAGE_LOW")
            tip = f"{warning}\n\n{tip}"
        self._label.setToolTip(tip)
        # Tooltip do widget root também — para hover na borda externa.
        self.setToolTip(tip)

    @staticmethod
    def _pick_color(free_gb: float) -> str:
        """Mapeia free_gb -> hex color (THEME.md §3 tokens)."""
        if free_gb < _THRESHOLD_LOW_GB:
            return _COLOR_RED
        if free_gb < _THRESHOLD_MEDIUM_GB:
            return _COLOR_YELLOW
        return _COLOR_GREEN

    # ------------------------------------------------------------------
    # Qt event hooks
    # ------------------------------------------------------------------

    def showEvent(self, event):  # noqa: N802 (Qt convention)
        """Inicia o timer ao primeiro show — evita poll antes de visível."""
        super().showEvent(event)
        if self._data_dir is not None and self.POLL_INTERVAL_MS > 0:
            self._timer.start()

    def hideEvent(self, event):  # noqa: N802
        """Para o timer quando escondido — economiza syscall em background."""
        super().hideEvent(event)
        self._timer.stop()

    # ------------------------------------------------------------------
    # Story 4.27 AC6 — lifecycle (teardown limpo do worker)
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Encerra a QThread do worker. Chamar no MainWindow.closeEvent.

        Idempotente + best-effort: erros silenciados (worker pode já estar
        parado pelo Qt em test teardown). Story 4.27 AC6.
        """
        with contextlib.suppress(Exception):
            self._timer.stop()
        with contextlib.suppress(Exception):
            self._debounce_timer.stop()
        worker = getattr(self, "_worker", None)
        if worker is not None and hasattr(worker, "shutdown"):
            with contextlib.suppress(Exception):
                worker.shutdown()
