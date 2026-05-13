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

Sinais:
    cancel_requested(): emitido quando usuário clica no botão CANCELAR.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setFlat(True)

        # Label do contrato atual (M16 — current_contract).
        contract_row = QHBoxLayout()
        contract_label = QLabel(format_msg("LBL_CURRENT_CONTRACT") + ":", self)
        contract_label.setProperty("role", "muted")
        self._contract_value = QLabel("—", self)
        self._contract_value.setProperty("role", "code")
        contract_row.addWidget(contract_label)
        contract_row.addWidget(self._contract_value)
        contract_row.addStretch(1)

        # Barra de progresso.
        self._bar = QProgressBar(self)
        self._bar.setMinimum(0)
        self._bar.setMaximum(100)
        self._bar.setValue(0)
        self._bar.setProperty("state", "normal")
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar.setTextVisible(True)

        # Subtitle textual (varia por state).
        self._subtitle = QLabel("", self)
        self._subtitle.setProperty("role", "secondary")
        self._subtitle.setWordWrap(True)

        # v1.2.0 Wave 1D (Uma/Felix — long-haul UX): grid compacto de
        # mini-labels com ETA / tempo decorrido / throughput / trades
        # baixados / trades perdidos / chunks com retry. Layout 2 colunas
        # (label muted ↔ valor) para não poluir.
        self._stats_grid_box = QFrame(self)
        self._stats_grid_box.setProperty("role", "muted")
        stats_grid = QGridLayout(self._stats_grid_box)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setHorizontalSpacing(16)
        stats_grid.setVerticalSpacing(4)

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

        # 3 colunas de pares (6 métricas em 2 linhas).
        _rows = (
            (
                ("Tempo restante:", self._eta_value),
                ("Decorrido:", self._elapsed_value),
                ("Throughput:", self._throughput_value),
            ),
            (
                ("Trades baixados:", self._trades_dl_value),
                ("Trades perdidos:", self._trades_failed_value),
                ("Chunks com retry:", self._retries_value),
            ),
        )
        for r, triple in enumerate(_rows):
            for c, (label_text, value_lbl) in enumerate(triple):
                name_lbl = QLabel(label_text, self._stats_grid_box)
                name_lbl.setProperty("role", "muted")
                stats_grid.addWidget(name_lbl, r, c * 2)
                stats_grid.addWidget(value_lbl, r, c * 2 + 1)
        stats_grid.setColumnStretch(5, 1)

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

        # Botão CANCELAR.
        self._cancel_btn = QPushButton(format_msg("BTN_CANCEL"), self)
        self._cancel_btn.setProperty("variant", "destructive")
        self._cancel_btn.setToolTip(format_msg("TIP_BTN_CANCEL"))
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        cancel_row = QHBoxLayout()
        cancel_row.addWidget(self._open_folder_btn)
        cancel_row.addStretch(1)
        cancel_row.addWidget(self._cancel_btn)

        # Layout vertical.
        outer = QVBoxLayout(self)
        outer.setSpacing(12)
        outer.addLayout(contract_row)
        outer.addWidget(self._bar)
        outer.addWidget(self._subtitle)
        outer.addWidget(self._stats_grid_box)
        outer.addWidget(self._reconnect_banner)
        outer.addWidget(self._log_toggle)
        outer.addWidget(self._log_view)
        outer.addLayout(cancel_row)

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

        self._contract_value.setText(str(contract))
        if total > 0:
            # Restaura range normal se estava indeterminado.
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setFormat("%p%")
            pct = max(0, min(100, int(done / total * 100)))
            self._bar.setValue(pct)
            # Story v1.0.7 fix (Pichau live test 2026-05-06): força repaint
            # imediato. Em alguns cenários cross-thread o setValue marca
            # dirty mas o evento de repaint pode ser coalescido — chamar
            # ``update()`` explicitamente garante invalidate. R21 OK
            # (cool path: 1x por chunk).
            self._bar.update()
        elif total == -1:
            # v1.2.0 Wave 1D — plano de download ainda não calculado.
            # Em vez de barra indeterminada muda, mostramos texto explícito
            # "Calculando plano de download…" sobre a barra.
            self._bar.setRange(0, 0)
            self._bar.setFormat("Calculando plano de download…")
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
        # ETA.
        if eta_s is not None and eta_s > 0:
            self._eta_value.setText("~" + self._fmt_hms(eta_s))
        else:
            self._eta_value.setText("—")
        # Tempo decorrido.
        if elapsed_s > 0:
            self._elapsed_value.setText(self._fmt_hms(elapsed_s))
        else:
            self._elapsed_value.setText("—")
        # Throughput: trades/s + chunks/h. Para downloads longos (chunks de
        # 1 dia útil), chunks/h ≈ dias/h.
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
        else:
            self._throughput_value.setText("—")
        # Trades baixados (acumulado).
        self._trades_dl_value.setText(self._fmt_int_ptbr(trades_received))
        # Trades perdidos — verde "0" / amarelo "N (0.0X%)" se >0.
        if trades_failed > 0:
            denom = trades_received + trades_failed
            pct = (trades_failed / denom * 100.0) if denom > 0 else 0.0
            self._trades_failed_value.setText(f"{self._fmt_int_ptbr(trades_failed)} ({pct:.2f}%)")
            self._trades_failed_value.setStyleSheet("color: #F2C94C;")
        else:
            self._trades_failed_value.setText("0")
            self._trades_failed_value.setStyleSheet("color: #3FCB6F;")
        # Chunks com retry.
        self._retries_value.setText(self._fmt_int_ptbr(retries) if retries > 0 else "0")

    def set_state(self, state: str) -> None:
        """state: 'normal' | 'reconnecting' | 'cancelling' | 'complete'."""
        self._bar.setProperty("state", state)
        # Re-aplica QSS.
        self._bar.style().unpolish(self._bar)
        self._bar.style().polish(self._bar)

        self._reconnect_banner.setVisible(state == "reconnecting")
        if state == "cancelling":
            self._cancel_btn.setEnabled(False)
            self._cancel_btn.setText(format_msg("INF_GRACEFUL_SHUTDOWN"))
            self._subtitle.setText(format_msg("INF_GRACEFUL_SHUTDOWN"))
        elif state == "reconnecting":
            self._cancel_btn.setToolTip(format_msg("TIP_CANCEL_DURING_RECONNECT"))
        elif state == "complete":
            self._cancel_btn.setEnabled(False)
        else:
            self._cancel_btn.setToolTip(format_msg("TIP_BTN_CANCEL"))

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
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("%p%")
        self._bar.update()
        self.set_state("normal")
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText(format_msg("BTN_CANCEL"))
        # v1.2.0 Wave 1D — reseta grid de métricas long-haul.
        for lbl in (
            self._eta_value,
            self._elapsed_value,
            self._throughput_value,
            self._trades_dl_value,
            self._retries_value,
        ):
            lbl.setText("—")
        self._trades_failed_value.setText("0")
        self._trades_failed_value.setStyleSheet("color: #3FCB6F;")
        self._open_folder_btn.setVisible(self._data_dir is not None)
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
