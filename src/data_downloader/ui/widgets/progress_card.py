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

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
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
    "A corretora está reconectando — é normal, " "aguarde até 30 minutos. Não cancele."
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

        # Botão CANCELAR.
        self._cancel_btn = QPushButton(format_msg("BTN_CANCEL"), self)
        self._cancel_btn.setProperty("variant", "destructive")
        self._cancel_btn.setToolTip(format_msg("TIP_BTN_CANCEL"))
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        cancel_row = QHBoxLayout()
        cancel_row.addStretch(1)
        cancel_row.addWidget(self._cancel_btn)

        # Layout vertical.
        outer = QVBoxLayout(self)
        outer.setSpacing(12)
        outer.addLayout(contract_row)
        outer.addWidget(self._bar)
        outer.addWidget(self._subtitle)
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

        self._contract_value.setText(str(contract))
        if total > 0:
            # Restaura range normal se estava indeterminado.
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            pct = max(0, min(100, int(done / total * 100)))
            self._bar.setValue(pct)
            # Story v1.0.7 fix (Pichau live test 2026-05-06): força repaint
            # imediato. Em alguns cenários cross-thread o setValue marca
            # dirty mas o evento de repaint pode ser coalescido — chamar
            # ``update()`` explicitamente garante invalidate. R21 OK
            # (cool path: 1x por chunk).
            self._bar.update()
        elif done > 0:
            # Total desconhecido (-1) — modo indeterminado.
            self._bar.setRange(0, 0)
            self._bar.update()
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
        self._bar.update()
        self.set_state("normal")
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText(format_msg("BTN_CANCEL"))
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
