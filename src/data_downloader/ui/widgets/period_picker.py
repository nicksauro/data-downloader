"""data_downloader.ui.widgets.period_picker — Picker de período (Story 3.2).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Dois ``QDateEdit`` (start, end) com defaults inteligentes (mês corrente do
contrato vigente). Validação inline:

    - end >= start → senão mostra ``ERR_INVALID_PERIOD``.
    - end <= today → senão mostra ``ERR_PERIOD_FUTURE``.

v1.2.0 Wave 1D (Uma — long-haul UX):
    - **Presets** via ``QComboBox``: "Mês corrente" (default), "Último ano",
      "Ano completo: YYYY" (anos 2018..hoje), "Tudo desde 2018",
      "Personalizado" (mostra os dois ``QDateEdit``).
    - **Aviso de duração**: range > ~60 dias úteis exibe ``WAR_LARGE_PERIOD``
      com estimativa real de chunks ("⚠ ~N dias úteis (~Xh-Yh)…").

Microcopy IDs (R17):
    - ``LBL_PERIOD``, ``LBL_START_DATE``, ``LBL_END_DATE``
    - ``LBL_PERIOD_RANGE_DISPLAY``
    - ``ERR_INVALID_PERIOD``, ``ERR_PERIOD_FUTURE``
    - ``WAR_LARGE_PERIOD``
    - ``TIP_PERIOD``
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from data_downloader.ui.microcopy_loader import format_msg

if TYPE_CHECKING:
    pass


__all__ = ["PeriodPicker"]


# v1.2.0 Wave 1D — limiar (dias corridos ~ dias uteis * 7/5) acima do qual
# exibimos o aviso de periodo grande. ~60 dias uteis ~ 84 dias corridos.
_LARGE_PERIOD_BUSINESS_DAYS_THRESHOLD = 60

# Primeiro ano com dados disponíveis (presets "desde 2018" / "Ano completo").
_FIRST_DATA_YEAR = 2018

# Estimativa grosseira: ~1 chunk = 1 dia útil; cada chunk leva ~30s-90s
# (depende de volume — ProgressCard mostra o real). Usado só para o aviso.
_CHUNK_SECONDS_LOW = 30.0
_CHUNK_SECONDS_HIGH = 90.0

_PRESET_CURRENT_MONTH = "Mês corrente"
_PRESET_LAST_YEAR = "Último ano"
_PRESET_SINCE_2018 = "Tudo desde 2018"
_PRESET_CUSTOM = "Personalizado"


def _business_days_between(start: date, end: date) -> int:
    """Conta dias úteis (seg-sex) entre ``start`` e ``end`` inclusive."""
    if end < start:
        return 0
    total = 0
    cur = start
    # Loop simples — ranges aqui são <= ~8 anos (~2900 dias), barato.
    from datetime import timedelta

    while cur <= end:
        if cur.weekday() < 5:  # 0=seg .. 4=sex
            total += 1
        cur += timedelta(days=1)
    return total


class PeriodPicker(QWidget):
    """Range date picker (start, end) com presets + aviso de período grande.

    API pública:
        range() -> tuple[date, date]: (start, end).
        set_range(start, end): set programaticamente.
        validate() -> str | None: retorna mensagem de erro humana ou None.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._label = QLabel(format_msg("LBL_PERIOD"), self)
        self._label.setProperty("role", "subtitle")

        # v1.2.0 Wave 1D — combo de presets.
        self._preset_combo = QComboBox(self)
        self._year_options: list[int] = list(range(_FIRST_DATA_YEAR, date.today().year + 1))
        self._preset_combo.addItem(_PRESET_CURRENT_MONTH)
        self._preset_combo.addItem(_PRESET_LAST_YEAR)
        for y in reversed(self._year_options):
            self._preset_combo.addItem(f"Ano completo: {y}")
        self._preset_combo.addItem(_PRESET_SINCE_2018)
        self._preset_combo.addItem(_PRESET_CUSTOM)

        self._start_edit = QDateEdit(self)
        self._start_edit.setDisplayFormat("dd/MM/yyyy")
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._end_edit = QDateEdit(self)
        self._end_edit.setDisplayFormat("dd/MM/yyyy")
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Default: mês corrente.
        today = date.today()
        first_of_month = today.replace(day=1)
        # Suprime sinais durante o set inicial (presets não disparam loop).
        self._suppress = True
        self.set_range(first_of_month, today)
        self._suppress = False

        # Linha dos QDateEdit — visível apenas no preset "Personalizado".
        self._date_row_widget = QWidget(self)
        date_row = QHBoxLayout(self._date_row_widget)
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.setSpacing(8)
        date_row.addWidget(QLabel(format_msg("LBL_START_DATE"), self._date_row_widget))
        date_row.addWidget(self._start_edit, stretch=1)
        date_row.addWidget(QLabel("→", self._date_row_widget))
        date_row.addWidget(QLabel(format_msg("LBL_END_DATE"), self._date_row_widget))
        date_row.addWidget(self._end_edit, stretch=1)
        self._date_row_widget.setVisible(False)

        self._range_display = QLabel("", self)
        self._range_display.setProperty("role", "muted")
        self._range_display.setWordWrap(True)

        # Aviso de período grande (WAR_LARGE_PERIOD) — hidden por default.
        self._large_period_warning = QLabel("", self)
        self._large_period_warning.setProperty("role", "warning")
        self._large_period_warning.setWordWrap(True)
        self._large_period_warning.setVisible(False)

        # Conexões.
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self._start_edit.dateChanged.connect(self._update_range_display)
        self._end_edit.dateChanged.connect(self._update_range_display)

        self.setToolTip(format_msg("TIP_PERIOD"))

        # Layout: label / preset / [start - end] (custom) / display / aviso.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(self._label)
        outer.addWidget(self._preset_combo)
        outer.addWidget(self._date_row_widget)
        outer.addWidget(self._range_display)
        outer.addWidget(self._large_period_warning)

        self._update_range_display()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def range(self) -> tuple[date, date]:
        """Retorna (start, end) como ``date``."""
        return (
            self._qdate_to_date(self._start_edit.date()),
            self._qdate_to_date(self._end_edit.date()),
        )

    def set_range(self, start: date, end: date) -> None:
        """Define o range programaticamente."""
        self._start_edit.setDate(QDate(start.year, start.month, start.day))
        self._end_edit.setDate(QDate(end.year, end.month, end.day))

    def validate(self) -> str | None:
        """Valida range; retorna mensagem humana se inválido, ou None."""
        start, end = self.range()
        if end < start:
            return format_msg(
                "ERR_INVALID_PERIOD",
                field="detail",
                start=start.isoformat(),
                end=end.isoformat(),
            )
        today = date.today()
        if end > today:
            return format_msg(
                "ERR_PERIOD_FUTURE",
                field="detail",
                end=end.isoformat(),
                today=today.isoformat(),
            )
        return None

    # ------------------------------------------------------------------
    # Presets (v1.2.0 Wave 1D)
    # ------------------------------------------------------------------

    def _on_preset_changed(self, text: str) -> None:
        today = date.today()
        is_custom = text == _PRESET_CUSTOM
        self._date_row_widget.setVisible(is_custom)
        if is_custom:
            return
        self._suppress = True
        try:
            if text == _PRESET_CURRENT_MONTH:
                self.set_range(today.replace(day=1), today)
            elif text == _PRESET_LAST_YEAR:
                try:
                    one_year_ago = today.replace(year=today.year - 1)
                except ValueError:  # 29/02
                    one_year_ago = today.replace(year=today.year - 1, day=28)
                self.set_range(one_year_ago, today)
            elif text == _PRESET_SINCE_2018:
                self.set_range(date(_FIRST_DATA_YEAR, 1, 1), today)
            elif text.startswith("Ano completo: "):
                year = int(text.rsplit(":", 1)[1].strip())
                start = date(year, 1, 1)
                end = date(year, 12, 31)
                if end > today:
                    end = today
                self.set_range(start, end)
        finally:
            self._suppress = False
        self._update_range_display()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_range_display(self) -> None:
        if getattr(self, "_suppress", False):
            return
        start, end = self.range()
        days = max((end - start).days, 0)
        if days == 0:
            duration = "1 dia"
        elif days < 31:
            duration = f"{days + 1} dias"
        elif days < 365:
            months = round((days + 1) / 30)
            duration = f"~{months} meses"
        else:
            years = round((days + 1) / 365, 1)
            duration = f"~{years} anos"
        text = format_msg(
            "LBL_PERIOD_RANGE_DISPLAY",
            start=start.strftime("%d/%m/%Y"),
            end=end.strftime("%d/%m/%Y"),
            duration=duration,
        )
        self._range_display.setText(text)

        # v1.2.0 Wave 1D — aviso de período grande + estimativa real de chunks.
        bdays = _business_days_between(start, end)
        if bdays > _LARGE_PERIOD_BUSINESS_DAYS_THRESHOLD:
            n_chunks = bdays  # ~1 chunk por dia útil (ADR-023 política unificada).
            h_low = max(1, round(n_chunks * _CHUNK_SECONDS_LOW / 3600.0))
            h_high = max(h_low, round(n_chunks * _CHUNK_SECONDS_HIGH / 3600.0))
            eta_str = f"{h_low}h" if h_low == h_high else f"{h_low}h-{h_high}h"
            self._large_period_warning.setText(
                f"⚠ ~{bdays} dias úteis (~{n_chunks} chunks, ~{eta_str} de download). "
                "Você pode pausar e retomar a qualquer momento."
            )
            self._large_period_warning.setVisible(True)
        else:
            self._large_period_warning.clear()
            self._large_period_warning.setVisible(False)

    @staticmethod
    def _qdate_to_date(qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())
