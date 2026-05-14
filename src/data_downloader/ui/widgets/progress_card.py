"""data_downloader.ui.widgets.progress_card — Card de progresso (Story 3.2).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Card visível em estado **Loading** da DownloadScreen. Encapsula barra de
progresso, label do contrato atual (M16 — ``current_contract``), subtítulo
textual com ETA, log expansível e botão CANCELAR.

Estados visuais (via property dinâmica ``state`` no QProgressBar):
    - normal      → cor accent.cyan #3DD0E1
    - reconnecting → warning.yellow #F2C94C (quirk 99% — Flow 4)
    - cancelling  → warning.yellow + texto INF_GRACEFUL_SHUTDOWN
    - complete    → success.green #3FCB6F

Texto LITERAL canônico ``WAR_99_RECONNECT`` (MICROCOPY §18) — proibido editar
sem autorização Uma + Nelo.

v1.3.0 Wave 2C (Uma — ProgressCard polish 2026-05-13):
    - Hierarquia tipográfica: ``Baixando {symbol}`` vira manchete H1 do card
      (20px bold) acima da barra; ``current_contract`` deixa de ser pareado
      inline e vira protagonista.
    - Ícones unicode nas labels do grid de stats (⏱ Decorrido / ⏳ Restante
      / ⚡ Throughput / ✓ Baixados / ⚠ Perdidos / ↻ Retries).
    - Cores semânticas dinâmicas em throughput / trades perdidos / retries
      (verde / cyan / amarelo / vermelho segundo thresholds de saúde).
    - Barra segmentada custom (``_SegmentedProgressBar``) — proporção
      verde (sucesso) ↔ amarela (falha) na MESMA barra via paintEvent
      override. Caso default (sem falhas) delega ao QSS normal — visual
      idêntico ao pre-Wave 2C.
    - Divisores 1px ``border.subtle`` (#2D2D33) entre seções para dar
      respiração ao card (antes "parede de info").
    - "Calculando plano de download…" (microcopy ``INF_CALCULATING_PLAN``)
      sobre a barra indeterminada quando ``total == -1``.
    - Botão CANCELAR maior (40px, fonte 14px bold, ícone unicode ⏹) +
      hint contextual ``LBL_CANCELLING_HINT`` abaixo durante cancelling.

Sinais:
    cancel_requested(): emitido quando usuário clica no botão CANCELAR.
    view_catalog_requested(symbol): v1.3.0 Wave 2B — emitido quando o
        usuário clica no CTA "Ver no Catálogo" exibido no sub-estado
        ``complete`` (success). O signal carrega o symbol do download para
        que o MainWindow consiga aplicar o filtro automaticamente em
        :class:`CatalogScreen` (Uma proposal — "Catálogo pós-download").
        O CTA é parte específica da Wave 2B; o polish visual do success
        sub-state segue contrato Wave 2C — o botão usa ``variant=primary``
        e fica oculto fora de ``state == "complete"``.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from data_downloader.ui.microcopy_loader import format_msg

__all__ = ["ProgressCard"]


# Texto canônico Uma — replicado byte-a-byte de MICROCOPY_CATALOG.md §18.
# Não editar sem nova autorização Uma + Nelo (R17).
WAR_99_RECONNECT_LITERAL = (
    "A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele."
)


# v1.3.0 Wave 2C — paleta canônica replicada de docs/ux/THEME.md §2.
# Replicadas como constantes Python apenas para uso em paintEvent (QSS
# não cobre subclasses custom de QProgressBar). NÃO inventar cores novas;
# qualquer adição requer Uma + THEME.md sign-off (R17).
_COLOR_BG_INPUT = "#26262B"
_COLOR_BORDER_SUBTLE = "#2D2D33"
_COLOR_ACCENT_CYAN = "#3DD0E1"
_COLOR_SUCCESS_GREEN = "#3FCB6F"
_COLOR_SUCCESS_GREEN_HI = "#5BD884"
_COLOR_WARNING_YELLOW = "#F2C94C"
_COLOR_WARNING_YELLOW_HI = "#FFD86B"
_COLOR_ERROR_RED = "#F25656"


class _SegmentedProgressBar(QProgressBar):
    """QProgressBar com paintEvent custom — 2 segmentos verde/amarelo.

    Wave 2C (Uma — 2026-05-13): a barra mostra a proporção real entre
    trades baixados (verde) e trades perdidos (amarelo) na MESMA barra,
    em vez de um chunk monocromático. Caso default (trades_failed == 0,
    fix Q-DRIFT-40), a barra mostra só verde/cyan — visualmente idêntica
    à versão pre-Wave 2C (delegamos ao paintEvent base do Qt para
    preservar gradiente do QSS).

    Mantém compatibilidade com a property dinâmica ``state`` (normal /
    reconnecting / cancelling / complete) — quando ``state != "normal"``
    o paintEvent delega ao estilo padrão do Qt para preservar o gradiente
    amarelo/verde definido no QSS.

    API extra:
        set_segments(success, failed): atualiza a proporção verde/amarela.
            Ambos são contagens absolutas (ex.: trades_received vs
            trades_failed); o paintEvent calcula a proporção.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._success_count: int = 0
        self._failed_count: int = 0

    def set_segments(self, success: int, failed: int) -> None:
        """Define contagens de sucesso/falha para o split visual.

        Args:
            success: trades baixados (segmento verde).
            failed: trades perdidos (segmento amarelo).
        """
        self._success_count = max(0, int(success))
        self._failed_count = max(0, int(failed))
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 — Qt signature
        # Em modo indeterminado (range 0,0) ou estados não-normais delegamos
        # ao QSS default — preserva a animação de busy e os gradientes
        # state-aware (reconnecting/cancelling/complete).
        state = self.property("state") or "normal"
        if self.maximum() == 0 or state != "normal":
            super().paintEvent(event)
            return

        # Sem falhas → caminho default (cyan gradiente). Mantém Q-DRIFT-40
        # fix: trades_failed == 0 = barra pura cyan.
        if self._failed_count <= 0:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        # Fundo (track) — mesmo bg.input do QSS para continuidade visual.
        track_color = QColor(_COLOR_BG_INPUT)
        painter.setBrush(QBrush(track_color))
        painter.setPen(QPen(QColor(_COLOR_BORDER_SUBTLE), 1))
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 4.0, 4.0)

        # Quanto da barra está preenchida (done / total) — replica o
        # comportamento default de fillRatio.
        max_v = max(1, self.maximum() - self.minimum())
        progress = max(0, min(max_v, self.value() - self.minimum()))
        fill_w = (rect.width() - 2) * (progress / max_v)
        if fill_w <= 0:
            painter.end()
            return

        # Split verde/amarelo dentro da região preenchida — proporção
        # real sucesso/falha.
        total_split = self._success_count + self._failed_count
        if total_split <= 0:
            painter.end()
            return
        green_w = fill_w * (self._success_count / total_split)
        yellow_w = fill_w - green_w

        inset = 1.0
        bar_top = rect.top() + inset
        bar_height = rect.height() - 2 * inset
        x = rect.left() + inset

        # Segmento verde (sucesso).
        if green_w > 0:
            green_rect = QRectF(x, bar_top, green_w, bar_height)
            green_grad = QLinearGradient(green_rect.topLeft(), green_rect.topRight())
            green_grad.setColorAt(0.0, QColor(_COLOR_SUCCESS_GREEN))
            green_grad.setColorAt(1.0, QColor(_COLOR_SUCCESS_GREEN_HI))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(green_grad))
            painter.drawRoundedRect(green_rect, 3.0, 3.0)
            x += green_w

        # Segmento amarelo (falhas) — colado à direita do verde.
        if yellow_w > 0:
            yellow_rect = QRectF(x, bar_top, yellow_w, bar_height)
            yellow_grad = QLinearGradient(yellow_rect.topLeft(), yellow_rect.topRight())
            yellow_grad.setColorAt(0.0, QColor(_COLOR_WARNING_YELLOW))
            yellow_grad.setColorAt(1.0, QColor(_COLOR_WARNING_YELLOW_HI))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(yellow_grad))
            painter.drawRoundedRect(yellow_rect, 3.0, 3.0)

        # Texto sobreposto (mesmo formato "%p%" ou setFormat). Preserva
        # contraste sobre os segmentos coloridos.
        text_format = self.format()
        if text_format and self.isTextVisible():
            painter.setPen(QPen(QColor("#0E0E10")))
            display = text_format.replace("%p", str(int(progress / max_v * 100)))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, display)
        painter.end()


def _hline(parent: QWidget) -> QFrame:
    """Cria um divisor horizontal 1px com cor border.subtle.

    Wave 2C (Uma) — usado entre as seções do card (título → barra →
    stats → log) para dar respiração. Token canônico THEME.md §2
    (#2D2D33). Não inventa cor.
    """
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {_COLOR_BORDER_SUBTLE}; border: none;")
    return line


class ProgressCard(QGroupBox):
    """Card de progresso com 4 sub-estados visuais.

    API pública:
        set_progress(DownloadProgress): atualiza barra + labels.
        set_state(str): "normal" | "reconnecting" | "cancelling" | "complete".
        set_cancel_enabled(bool): habilita/desabilita botão CANCELAR.
        append_log(str): adiciona linha ao log expansível.
        reset(): limpa para estado inicial.
    """

    cancel_requested = Signal()
    # v1.3.0 Wave 2B — BTN_VIEW_CATALOG no success_card (Uma proposal).
    # Emitido com o symbol do download para que MainWindow possa filtrar
    # CatalogScreen automaticamente (set_filter_symbol).
    view_catalog_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setFlat(True)
        # v1.3.0 Wave 2B — symbol do download corrente (alimenta o CTA
        # "Ver no Catálogo" do success card). Setado via :meth:`set_symbol`
        # ao iniciar o download.
        self._current_symbol: str = ""

        # ------------------------------------------------------------------
        # 1. Hierarquia tipográfica (Wave 2C — Uma): "Baixando {symbol}"
        #    vira H1 (20px bold) com `current_contract` como manchete; o
        #    label muted "Contrato atual" antigo foi removido.
        # ------------------------------------------------------------------
        self._title_label = QLabel("Baixando —", self)
        self._title_label.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #E8E8EA; padding: 2px 0;"
        )
        # Compat: testes legacy leem ``_contract_value.text() == "WDOJ26"``
        # diretamente. Mantemos o widget separado (hidden), atualizado em
        # paralelo, para preservar o contrato sem regredir testes.
        self._contract_value = QLabel("—", self)
        self._contract_value.setProperty("role", "code")
        self._contract_value.setVisible(False)

        contract_row = QHBoxLayout()
        contract_row.addWidget(self._title_label)
        contract_row.addWidget(self._contract_value)
        contract_row.addStretch(1)

        # ------------------------------------------------------------------
        # 4. Barra de progresso segmentada (Wave 2C — Uma):
        #    _SegmentedProgressBar pinta 2 segmentos verde/amarelo na
        #    mesma barra quando há trades_failed > 0. Caso default (sem
        #    falhas) delega ao QSS — visual idêntico ao pre-Wave 2C.
        # ------------------------------------------------------------------
        self._bar = _SegmentedProgressBar(self)
        self._bar.setMinimum(0)
        self._bar.setMaximum(100)
        self._bar.setValue(0)
        self._bar.setProperty("state", "normal")
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar.setTextVisible(True)
        # Bar um pouco mais alta para acomodar texto sobreposto durante
        # modo indeterminado ("Calculando plano de download…").
        self._bar.setMinimumHeight(18)

        # Subtitle textual (varia por state).
        self._subtitle = QLabel("", self)
        self._subtitle.setProperty("role", "secondary")
        self._subtitle.setWordWrap(True)

        # ------------------------------------------------------------------
        # 2. Grid de stats com ícones unicode (Wave 2C — Uma): 3x2 grid
        #    com ⏱ ⏳ ⚡ ✓ ⚠ ↻ prefixando cada label, melhorando
        #    scanability. Valores ganham cor semântica em
        #    _update_long_haul_stats.
        # ------------------------------------------------------------------
        self._stats_grid_box = QFrame(self)
        self._stats_grid_box.setProperty("role", "muted")
        stats_grid = QGridLayout(self._stats_grid_box)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setHorizontalSpacing(16)
        stats_grid.setVerticalSpacing(6)

        def _mk_value() -> QLabel:
            lbl = QLabel("—", self._stats_grid_box)
            lbl.setProperty("role", "secondary")
            return lbl

        self._eta_value = _mk_value()
        self._elapsed_value = _mk_value()
        self._throughput_value = _mk_value()
        self._trades_dl_value = _mk_value()
        self._trades_failed_value = _mk_value()
        self._retries_value = _mk_value()

        # Ícones unicode (texto inline com a label).
        _icon_clock = "⏱"  # ⏱
        _icon_hourglass = "⏳"  # ⏳
        _icon_bolt = "⚡"  # ⚡
        _icon_check = "✓"  # ✓
        _icon_warn = "⚠"  # ⚠
        _icon_retry = "↻"  # ↻
        _rows = (
            (
                (f"{_icon_clock} Decorrido:", self._elapsed_value),
                (f"{_icon_hourglass} Restante:", self._eta_value),
                (f"{_icon_bolt} Throughput:", self._throughput_value),
            ),
            (
                (f"{_icon_check} Baixados:", self._trades_dl_value),
                (f"{_icon_warn} Perdidos:", self._trades_failed_value),
                (f"{_icon_retry} Retries:", self._retries_value),
            ),
        )
        for r, triple in enumerate(_rows):
            for c, (label_text, value_lbl) in enumerate(triple):
                name_lbl = QLabel(label_text, self._stats_grid_box)
                name_lbl.setProperty("role", "muted")
                stats_grid.addWidget(name_lbl, r, c * 2)
                stats_grid.addWidget(value_lbl, r, c * 2 + 1)
        stats_grid.setColumnStretch(5, 1)

        # ETA tracking — usado para destacar ETA crescente em amarelo
        # (polish 3.4 — opcional). Inicializa None e atualiza em
        # _update_long_haul_stats.
        self._last_eta_s: float | None = None

        # Banner WAR_99_RECONNECT — só visível em state=reconnecting.
        self._reconnect_banner = QFrame(self)
        self._reconnect_banner.setProperty("role", "warning-card")
        banner_layout = QHBoxLayout(self._reconnect_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        self._reconnect_text = QLabel(WAR_99_RECONNECT_LITERAL, self._reconnect_banner)
        self._reconnect_text.setWordWrap(True)
        banner_layout.addWidget(self._reconnect_text)
        self._reconnect_banner.setVisible(False)

        # Log expansível (toggled).
        # Story v1.0.7 fix (Pichau live test 2026-05-06 — bug "nem aparece
        # que começou a baixar nos logs do aplicativo"): log view agora
        # inicia VISÍVEL e marcado como checked. Em windowed mode (.exe
        # com console=False) o stderr é detached → structlog não tem onde
        # escrever. O log view do ProgressCard é a única superfície de
        # log que o usuário vê. Usuário pode ocultar via botão "▾
        # Detalhes" se quiser.
        self._log_toggle = QPushButton("▾ " + format_msg("BTN_DETAILS_HIDE"), self)
        self._log_toggle.setProperty("variant", "link")
        self._log_toggle.setCheckable(True)
        self._log_toggle.setChecked(True)
        self._log_toggle.setCursor(self._log_toggle.cursor())
        self._log_toggle.clicked.connect(self._on_log_toggled)

        self._log_view = QTextEdit(self)
        self._log_view.setReadOnly(True)
        self._log_view.setVisible(True)
        self._log_view.setMaximumHeight(140)
        self._log_view.setProperty("role", "code")
        # v1.2.0 Wave 1D — limita o histórico do log: 30h de download não
        # acumula MB de texto. Auto-scroll preservado (QTextEdit.append rola
        # ao fim quando o cursor já está no fim, que é o comportamento padrão
        # após cada append). 0 = ilimitado, então usamos 2000 blocos.
        self._log_view.document().setMaximumBlockCount(2000)

        # v1.2.0 Wave 1D — "Abrir Pasta" visível DURANTE o download (não só
        # no success card). Aponta para o ``data_dir`` do job (setado via
        # :meth:`set_data_dir`). Hidden até termos um path.
        self._open_folder_btn = QPushButton(format_msg("BTN_OPEN_FOLDER"), self)
        self._open_folder_btn.setProperty("variant", "secondary")
        self._open_folder_btn.setObjectName("progressOpenFolderBtn")
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        self._open_folder_btn.setVisible(False)
        self._data_dir: Path | None = None

        # ------------------------------------------------------------------
        # 5. Botão CANCELAR maior (Wave 2C — Uma): 40px min-height, fonte
        #    14px bold, ícone unicode ⏹. Já tem variant=destructive.
        # ------------------------------------------------------------------
        self._cancel_btn = QPushButton("⏹  " + format_msg("BTN_CANCEL"), self)
        self._cancel_btn.setProperty("variant", "destructive")
        self._cancel_btn.setToolTip(format_msg("TIP_BTN_CANCEL"))
        self._cancel_btn.setMinimumHeight(40)
        # Felix nota: o stylesheet inline não sobrescreve variant=destructive
        # globalmente (QSS é mais específico no widget vs. inline) mas como
        # font-size/weight não estão definidos lá, herdam aqui sem conflito.
        self._cancel_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 600; padding: 8px 20px; }"
        )
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)

        # Hint contextual que só aparece durante cancelling.
        self._cancel_hint = QLabel("", self)
        self._cancel_hint.setProperty("role", "muted")
        self._cancel_hint.setWordWrap(True)
        self._cancel_hint.setVisible(False)

        # v1.3.0 Wave 2B: BTN_VIEW_CATALOG no success_card.
        # Visível apenas em state="complete" (sub-state success). Em todos
        # os outros estados (normal/reconnecting/cancelling) fica oculto
        # para não confundir o usuário. Wave 2C compatibility: o botão usa
        # ``variant=primary`` do QSS (tokens canônicos).
        self._view_catalog_btn = QPushButton(format_msg("BTN_VIEW_CATALOG"), self)
        self._view_catalog_btn.setProperty("variant", "primary")
        self._view_catalog_btn.setObjectName("progressViewCatalogBtn")
        self._view_catalog_btn.setVisible(False)
        self._view_catalog_btn.clicked.connect(self._on_view_catalog_clicked)

        cancel_row = QHBoxLayout()
        cancel_row.addWidget(self._open_folder_btn)
        cancel_row.addWidget(self._view_catalog_btn)
        cancel_row.addStretch(1)
        cancel_row.addWidget(self._cancel_btn)

        # ------------------------------------------------------------------
        # 6. Divisores 1px entre seções (Wave 2C — Uma).
        # ------------------------------------------------------------------
        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        outer.addLayout(contract_row)
        outer.addWidget(_hline(self))
        outer.addWidget(self._bar)
        outer.addWidget(self._subtitle)
        outer.addWidget(_hline(self))
        outer.addWidget(self._stats_grid_box)
        outer.addWidget(self._reconnect_banner)
        outer.addWidget(_hline(self))
        outer.addWidget(self._log_toggle)
        outer.addWidget(self._log_view)
        outer.addLayout(cancel_row)
        outer.addWidget(self._cancel_hint)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_progress(self, progress: object) -> None:
        """Atualiza barra + label do contrato a partir de ``DownloadProgress``.

        Story 4.16 (Pichau directive 2026-05-06): quando ``total > 0`` o
        subtitle mostra ``X/Y chunks (N trades) — Z%`` para que o usuário
        veja o progresso fino-granular ("quanto tempo falta"). Para
        ``message == "INF_CHUNK_COMPLETE"`` o subtitle prioriza a
        formatação de chunks; outras mensagens (INF_99_RECONNECT etc.)
        seguem o caminho normal de microcopy.
        """
        # Duck-typing — adapter sempre passa DownloadProgress, mas evitamos
        # importar diretamente para não acoplar a tipos no construtor.
        total = int(getattr(progress, "total", 0) or 0)
        done = int(getattr(progress, "done", 0) or 0)
        contract = getattr(progress, "current_contract", None) or "—"
        is_99 = bool(getattr(progress, "is_99_reconnect", False))
        message = str(getattr(progress, "message", "") or "")
        trades_received = int(getattr(progress, "trades_received", 0) or 0)
        # v1.2.0 Wave 1D — campos long-haul (defaults seguros se ausentes).
        elapsed_s = float(getattr(progress, "elapsed_s", 0.0) or 0.0)
        eta_raw = getattr(progress, "eta_s", None)
        eta_s = float(eta_raw) if eta_raw is not None else None
        trades_failed = int(getattr(progress, "trades_failed", 0) or 0)
        retries = int(getattr(progress, "retries", 0) or 0)

        # Title + contract (Wave 2C — manchete H1).
        self._contract_value.setText(str(contract))
        if contract and contract != "—":
            self._title_label.setText(format_msg("LBL_PROGRESS_TITLE_DOWNLOADING", symbol=contract))
        if total > 0:
            # Restaura range normal se estava indeterminado.
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setFormat("%p%")
            pct = max(0, min(100, int(done / total * 100)))
            self._bar.setValue(pct)
            # Atualiza split verde/amarelo para o paintEvent custom.
            self._bar.set_segments(trades_received, trades_failed)
            # Story v1.0.7 fix (Pichau live test 2026-05-06): força repaint
            # imediato. Em alguns cenários cross-thread o setValue marca
            # dirty mas o evento de repaint pode ser coalescido — chamar
            # ``update()`` explicitamente garante invalidate. R21 OK
            # (cool path: 1x por chunk).
            self._bar.update()
        elif total == -1:
            # v1.2.0 Wave 1D — plano de download ainda não calculado.
            # v1.3.0 Wave 2C — texto via microcopy ID (R17) sobre a barra
            # indeterminada. INF_CALCULATING_PLAN substitui o literal
            # hardcoded.
            self._bar.setRange(0, 0)
            self._bar.setFormat(format_msg("INF_CALCULATING_PLAN"))
            self._bar.update()
        elif done > 0:
            # Total desconhecido — modo indeterminado.
            self._bar.setRange(0, 0)
            self._bar.update()

        # v1.2.0 Wave 1D — atualiza grid de métricas long-haul.
        self._update_long_haul_stats(
            done=done,
            total=total,
            elapsed_s=elapsed_s,
            eta_s=eta_s,
            trades_received=trades_received,
            trades_failed=trades_failed,
            retries=retries,
        )
        # State (sub-state).
        if is_99:
            self.set_state("reconnecting")
            # Mantém posição (não regride).
        else:
            # Restaura state normal apenas se não estamos cancelando.
            if self._bar.property("state") == "reconnecting":
                self.set_state("normal")
        # Subtitle: Story 4.16 — chunk progress em formato "X/Y chunks
        # (N trades) — Z%" para dar feedback fino-granular ao usuário.
        # Quando o evento é INF_CHUNK_COMPLETE (orchestrator chunk_listener),
        # priorizamos o formato de chunks. Outros eventos (INF_*, WAR_*)
        # seguem o caminho normal de microcopy.
        if message == "INF_CHUNK_COMPLETE" and total > 0:
            pct = 100.0 * done / total
            n_trades_fmt = f"{trades_received:,}".replace(",", ".")
            self._subtitle.setText(f"{done}/{total} chunks ({n_trades_fmt} trades) — {pct:.1f}%")
        else:
            from data_downloader.ui.microcopy_loader import MSG

            if message in MSG:
                self._subtitle.setText(MSG[message].title or "")
            else:
                self._subtitle.setText(message)
        # Log linha.
        if message:
            self.append_log(message)

    # ------------------------------------------------------------------
    # v1.2.0 Wave 1D — long-haul helpers
    # ------------------------------------------------------------------

    def set_data_dir(self, data_dir: object) -> None:
        """Define a pasta do job — habilita o botão "Abrir Pasta" durante o download."""
        try:
            self._data_dir = Path(str(data_dir)) if data_dir else None
        except Exception:
            self._data_dir = None
        self._open_folder_btn.setVisible(self._data_dir is not None)

    def _on_open_folder(self) -> None:
        if self._data_dir is None:
            return
        with contextlib.suppress(Exception):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._data_dir)))

    def set_symbol(self, symbol: str) -> None:
        """v1.3.0 Wave 2B — define o symbol do download corrente.

        Alimenta o CTA "Ver no Catálogo" do success_card (``state=complete``):
        ao clicar, emite ``view_catalog_requested(symbol)`` para que o
        MainWindow navegue ao :class:`CatalogScreen` já filtrado.
        """
        self._current_symbol = str(symbol or "")

    def _on_view_catalog_clicked(self) -> None:
        """Handler do CTA "Ver no Catálogo" do success_card (Wave 2B)."""
        self.view_catalog_requested.emit(self._current_symbol)

    @staticmethod
    def _fmt_hms(seconds: float) -> str:
        """Formata segundos como 'Xh Ymin' / 'Ymin' / '<1min'."""
        s = max(0, round(seconds))
        if s < 60:
            return "<1min"
        hours, rem = divmod(s, 3600)
        minutes = rem // 60
        if hours > 0:
            return f"{hours}h {minutes:02d}min"
        return f"{minutes}min"

    @staticmethod
    def _fmt_int_ptbr(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    @staticmethod
    def _fmt_pct_ptbr(value: float) -> str:
        """Formata percentual em pt-BR (vírgula decimal). '2.34' -> '2,34'."""
        return f"{value:.2f}".replace(".", ",")

    def _update_long_haul_stats(
        self,
        *,
        done: int,
        total: int,
        elapsed_s: float,
        eta_s: float | None,
        trades_received: int,
        trades_failed: int,
        retries: int,
    ) -> None:
        # ------------------------------------------------------------------
        # Wave 2C (Uma) — cores semânticas dinâmicas.
        # ------------------------------------------------------------------

        # ETA — cyan estável; vira amarelo se a ETA cresce desde a última
        # medição (sinal de throughput degradando).
        if eta_s is not None and eta_s > 0:
            self._eta_value.setText("~" + self._fmt_hms(eta_s))
            if self._last_eta_s is not None and eta_s > self._last_eta_s * 1.10:
                # Crescimento > 10% — sinaliza degradação (warning).
                self._eta_value.setStyleSheet(f"color: {_COLOR_WARNING_YELLOW};")
            else:
                self._eta_value.setStyleSheet(f"color: {_COLOR_ACCENT_CYAN};")
            self._last_eta_s = eta_s
        else:
            self._eta_value.setText("—")
            self._eta_value.setStyleSheet("")

        # Tempo decorrido (text.secondary default — neutro).
        if elapsed_s > 0:
            self._elapsed_value.setText(self._fmt_hms(elapsed_s))
        else:
            self._elapsed_value.setText("—")

        # Throughput — verde >= 5k trades/s, cyan 1k-5k, amarelo < 1k.
        if elapsed_s > 0:
            trades_per_s = trades_received / elapsed_s
            chunks_per_h = (done / elapsed_s) * 3600.0 if done > 0 else 0.0
            tps_fmt = (
                f"{trades_per_s / 1000.0:.1f}k trades/s"
                if trades_per_s >= 1000
                else f"{trades_per_s:.0f} trades/s"
            )
            if chunks_per_h >= 1.0:
                self._throughput_value.setText(f"{tps_fmt} · {chunks_per_h:.1f} chunks/h")
            else:
                self._throughput_value.setText(tps_fmt)
            # Cor semântica.
            if trades_per_s >= 5000:
                self._throughput_value.setStyleSheet(f"color: {_COLOR_SUCCESS_GREEN};")
            elif trades_per_s >= 1000:
                self._throughput_value.setStyleSheet(f"color: {_COLOR_ACCENT_CYAN};")
            else:
                self._throughput_value.setStyleSheet(f"color: {_COLOR_WARNING_YELLOW};")
        else:
            self._throughput_value.setText("—")
            self._throughput_value.setStyleSheet("")

        # Trades baixados — neutro (manchete numérica).
        self._trades_dl_value.setText(self._fmt_int_ptbr(trades_received))

        # Trades perdidos — verde 0; amarelo < 0.1%; vermelho >= 0.1%.
        # Formato pt-BR ("N (X,YY%)" com vírgula decimal).
        if trades_failed > 0:
            denom = trades_received + trades_failed
            pct = (trades_failed / denom * 100.0) if denom > 0 else 0.0
            self._trades_failed_value.setText(
                f"{self._fmt_int_ptbr(trades_failed)} ({self._fmt_pct_ptbr(pct)}%)"
            )
            if pct >= 0.1:
                self._trades_failed_value.setStyleSheet(f"color: {_COLOR_ERROR_RED};")
            else:
                self._trades_failed_value.setStyleSheet(f"color: {_COLOR_WARNING_YELLOW};")
        else:
            self._trades_failed_value.setText("0")
            self._trades_failed_value.setStyleSheet(f"color: {_COLOR_SUCCESS_GREEN};")

        # Retries — cor por % (0=verde, <5% cyan, <20% amarelo, >=20% vermelho).
        # Denom = retries + done (chunks bem-sucedidos); fallback denom=done.
        if retries <= 0:
            self._retries_value.setText("0")
            self._retries_value.setStyleSheet(f"color: {_COLOR_SUCCESS_GREEN};")
        else:
            denom = max(done, 1) + retries
            pct = retries / denom * 100.0
            self._retries_value.setText(
                f"{self._fmt_int_ptbr(retries)} ({self._fmt_pct_ptbr(pct)}%)"
            )
            if pct < 5.0:
                self._retries_value.setStyleSheet(f"color: {_COLOR_ACCENT_CYAN};")
            elif pct < 20.0:
                self._retries_value.setStyleSheet(f"color: {_COLOR_WARNING_YELLOW};")
            else:
                self._retries_value.setStyleSheet(f"color: {_COLOR_ERROR_RED};")

    def set_state(self, state: str) -> None:
        """state: 'normal' | 'reconnecting' | 'cancelling' | 'complete'."""
        self._bar.setProperty("state", state)
        # Re-aplica QSS.
        self._bar.style().unpolish(self._bar)
        self._bar.style().polish(self._bar)

        self._reconnect_banner.setVisible(state == "reconnecting")
        # v1.3.0 Wave 2B — CTA "Ver no Catálogo" só aparece no success card.
        self._view_catalog_btn.setVisible(state == "complete")
        if state == "cancelling":
            # Bug 4 fix (v1.3.0): cancel é cooperativo (orchestrator checa o
            # cancel_event ENTRE chunks). Antes o botão mudava pra "Drenando
            # fila..." e o usuário pensava que travou. Agora: texto curto no
            # botão (`BTN_CANCELLING`) + microcopy clara no subtitle explicando
            # que o app está aguardando o dia atual da DLL terminar (~60s típico
            # pra WDOFUT em pregão; pode chegar a 5min em chunks lentos).
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setText(format_msg("BTN_CANCELLING"))
            self._subtitle.setText(format_msg("INF_GRACEFUL_SHUTDOWN"))
            # Wave 2C — hint contextual abaixo do botão.
            self._cancel_hint.setText(format_msg("LBL_CANCELLING_HINT"))
            self._cancel_hint.setVisible(True)
        elif state == "reconnecting":
            self._cancel_btn.setToolTip(format_msg("TIP_CANCEL_DURING_RECONNECT"))
            self._cancel_hint.setVisible(False)
        elif state == "complete":
            self._cancel_btn.setEnabled(False)
            self._cancel_hint.setVisible(False)
        else:
            self._cancel_btn.setToolTip(format_msg("TIP_BTN_CANCEL"))
            self._cancel_hint.setVisible(False)

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._cancel_btn.setEnabled(enabled)

    def append_log_line(self, line: str) -> None:
        """Adiciona linha já formatada ao log (Story v1.0.7).

        Diferente de :meth:`append_log` (que humaniza microcopy IDs),
        esta variante recebe linha **já formatada** — usada pelo slot
        conectado ao :class:`QtLogBridge.message_logged` que envia
        ``[HH:MM:SS] LEVEL event=...`` pronto.
        """
        if not line:
            return
        self._log_view.append(line)

    def append_log(self, line: str) -> None:
        """Adiciona linha ao log com timestamp + humanização de microcopy.

        Story v1.0.7 fix (Pichau live test 2026-05-06 — bug "nem aparece
        que começou a baixar nos logs"): se ``line`` é um microcopy ID
        conhecido, exibe o ``title`` em vez do ID cru — usuário vê
        "Iniciando download..." em vez de "INF_STARTING_DOWNLOAD".
        """
        if not line:
            return
        from datetime import datetime as _dt

        from data_downloader.ui.microcopy_loader import MSG

        # Humaniza microcopy ID se conhecido — caso contrário mantém raw.
        humanized = line
        entry = MSG.get(line)
        if entry is not None and entry.title:
            humanized = entry.title
        ts = _dt.now().strftime("%H:%M:%S")
        self._log_view.append(f"[{ts}] {humanized}")

    def reset(self) -> None:
        """Reseta para estado inicial."""
        self._contract_value.setText("—")
        self._title_label.setText("Baixando —")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("%p%")
        self._bar.set_segments(0, 0)
        self._bar.update()
        self.set_state("normal")
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("⏹  " + format_msg("BTN_CANCEL"))
        self._cancel_hint.setVisible(False)
        self._last_eta_s = None
        # v1.2.0 Wave 1D — reseta grid de métricas long-haul.
        for lbl in (
            self._eta_value,
            self._elapsed_value,
            self._throughput_value,
            self._trades_dl_value,
            self._retries_value,
        ):
            lbl.setText("—")
            lbl.setStyleSheet("")
        self._trades_failed_value.setText("0")
        self._trades_failed_value.setStyleSheet(f"color: {_COLOR_SUCCESS_GREEN};")
        self._retries_value.setStyleSheet(f"color: {_COLOR_SUCCESS_GREEN};")
        self._open_folder_btn.setVisible(self._data_dir is not None)
        # v1.3.0 Wave 2B — reset esconde o CTA do success card.
        self._view_catalog_btn.setVisible(False)
        self._log_view.clear()
        # Story v1.0.7 — log view sempre visível em loading state (Pichau
        # bug: usuário não via logs do download). Restaura toggle para
        # "Ocultar" para refletir estado atual.
        self._log_view.setVisible(True)
        self._log_toggle.setChecked(True)
        self._log_toggle.setText("▾ " + format_msg("BTN_DETAILS_HIDE"))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_log_toggled(self, checked: bool) -> None:
        self._log_view.setVisible(checked)
        if checked:
            self._log_toggle.setText("▾ " + format_msg("BTN_DETAILS_HIDE"))
        else:
            self._log_toggle.setText("▸ " + format_msg("BTN_DETAILS"))
