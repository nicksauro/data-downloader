"""data_downloader.ui.widgets.period_picker — Picker de período (Story 3.2).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Dois ``QDateEdit`` (start, end) com defaults inteligentes (mês corrente do
contrato vigente). Validação inline:

    - end >= start → senão mostra ``ERR_INVALID_PERIOD``.
    - end <= today → senão mostra ``ERR_PERIOD_FUTURE``.

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


class PeriodPicker(QWidget):
    """Range date picker (start, end) com defaults mês corrente.

    API pública:
        range() -> tuple[date, date]: (start, end).
        set_range(start, end): set programaticamente.
        validate() -> str | None: retorna mensagem de erro humana ou None.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._label = QLabel(format_msg("LBL_PERIOD"), self)
        self._label.setProperty("role", "subtitle")

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
        self.set_range(first_of_month, today)

        self._range_display = QLabel("", self)
        self._range_display.setProperty("role", "muted")
        self._update_range_display()

        # Conecta para atualizar display em tempo real.
        self._start_edit.dateChanged.connect(self._update_range_display)
        self._end_edit.dateChanged.connect(self._update_range_display)

        self.setToolTip(format_msg("TIP_PERIOD"))

        # Layout: label / [start - end] / display formatado.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(self._label)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(format_msg("LBL_START_DATE"), self))
        row.addWidget(self._start_edit, stretch=1)
        row.addWidget(QLabel("→", self))
        row.addWidget(QLabel(format_msg("LBL_END_DATE"), self))
        row.addWidget(self._end_edit, stretch=1)
        outer.addLayout(row)
        outer.addWidget(self._range_display)

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
    # Helpers
    # ------------------------------------------------------------------

    def _update_range_display(self) -> None:
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

    @staticmethod
    def _qdate_to_date(qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())
