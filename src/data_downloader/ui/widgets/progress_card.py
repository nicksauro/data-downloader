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
        self._log_toggle = QPushButton("▸ " + format_msg("BTN_DETAILS"), self)
        self._log_toggle.setProperty("variant", "link")
        self._log_toggle.setCheckable(True)
        self._log_toggle.setCursor(self._log_toggle.cursor())
        self._log_toggle.clicked.connect(self._on_log_toggled)

        self._log_view = QTextEdit(self)
        self._log_view.setReadOnly(True)
        self._log_view.setVisible(False)
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
        """Atualiza barra + label do contrato a partir de ``DownloadProgress``."""
        # Duck-typing — adapter sempre passa DownloadProgress, mas evitamos
        # importar diretamente para não acoplar a tipos no construtor.
        total = int(getattr(progress, "total", 0) or 0)
        done = int(getattr(progress, "done", 0) or 0)
        contract = getattr(progress, "current_contract", None) or "—"
        is_99 = bool(getattr(progress, "is_99_reconnect", False))
        message = str(getattr(progress, "message", "") or "")

        self._contract_value.setText(str(contract))
        if total > 0:
            # Restaura range normal se estava indeterminado.
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            pct = max(0, min(100, int(done / total * 100)))
            self._bar.setValue(pct)
        elif done > 0:
            # Total desconhecido (-1) — modo indeterminado.
            self._bar.setRange(0, 0)
        # State (sub-state).
        if is_99:
            self.set_state("reconnecting")
            # Mantém posição (não regride).
        else:
            # Restaura state normal apenas se não estamos cancelando.
            if self._bar.property("state") == "reconnecting":
                self.set_state("normal")
        # Subtitle: usa microcopy ID se for um (INF_*), senão texto cru.
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

    def append_log(self, line: str) -> None:
        if not line:
            return
        self._log_view.append(line)

    def reset(self) -> None:
        """Reseta para estado inicial."""
        self._contract_value.setText("—")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self.set_state("normal")
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText(format_msg("BTN_CANCEL"))
        self._log_view.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_log_toggled(self, checked: bool) -> None:
        self._log_view.setVisible(checked)
        if checked:
            self._log_toggle.setText("▾ " + format_msg("BTN_DETAILS_HIDE"))
        else:
            self._log_toggle.setText("▸ " + format_msg("BTN_DETAILS"))
