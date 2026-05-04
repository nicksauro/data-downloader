"""Integration tests — CatalogScreen (Story 3.2).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Cobertura:
    - Smoke: tela renderiza com 5 estados (loading/normal/empty/empty_filtered/error).
    - Mock catalog vazio → empty state.
    - Mock catalog populado → tabela mostra linhas + footer summary.
    - Filtro symbol funciona (proxy).
    - Click em deletar → dialog confirmação → delete chamado via signal.
    - Atalho Ctrl+R refresh.
    - Erro adapter → estado error com microcopy.

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Helpers — fake Partition (sem precisar de catálogo SQLite real).
# =====================================================================


def _make_partition(
    *,
    symbol: str = "WDOJ26",
    exchange: str = "F",
    year: int = 2026,
    month: int = 3,
    row_count: int = 1234567,
    file_size_bytes: int = 47452160,  # 45.2 MB
):
    from data_downloader.storage.catalog_models import Partition

    return Partition(
        partition_path=f"{exchange}/{symbol}/{year}/{month:02d}.parquet",
        symbol=symbol,
        exchange=exchange,
        year=year,
        month=month,
        row_count=row_count,
        first_ts_ns=0,
        last_ts_ns=0,
        schema_version="1.0.0",
        checksum_sha256="a3f7" + "0" * 60,
        file_size_bytes=file_size_bytes,
        written_at=datetime(2026, 5, 1, 12, 0, 0),
        job_id=None,
    )


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def catalog_screen(qtbot, tmp_path):
    """Cria CatalogScreen com data_dir vazio (catálogo não existe → empty)."""
    from data_downloader.ui.screens.catalog_screen import CatalogScreen

    screen = CatalogScreen(data_dir=tmp_path)
    qtbot.addWidget(screen)
    screen.show()
    # Espera carga inicial (deferred via QTimer.singleShot(0, refresh)).
    qtbot.wait(100)
    yield screen
    screen._adapter.shutdown()


# =====================================================================
# Smoke
# =====================================================================


def test_catalog_screen_starts_and_shows_empty(catalog_screen, qtbot):
    """Sem catálogo → empty state com microcopy first-run."""
    qtbot.waitUntil(lambda: catalog_screen.current_state() == "empty", timeout=2000)
    assert catalog_screen.current_state() == "empty"


def test_catalog_screen_microcopy_resolves(catalog_screen):
    """Nenhuma label mostra <microcopy id not found>."""
    title = catalog_screen._title.text()
    assert "<microcopy id not found" not in title
    refresh = catalog_screen._refresh_btn.text()
    assert "<microcopy id not found" not in refresh


def test_catalog_screen_has_search_and_filter(catalog_screen):
    assert catalog_screen._search_edit is not None
    assert catalog_screen._exchange_filter is not None
    assert catalog_screen._exchange_filter.count() == 3  # Todas, F, B


# =====================================================================
# Modelo populado — table mostra rows
# =====================================================================


def test_partitions_loaded_populates_table(catalog_screen, qtbot):
    """Recebendo lista mock de partições → tabela mostra + footer summary."""
    partitions = (
        _make_partition(symbol="WDOJ26", year=2026, month=3),
        _make_partition(symbol="WDOH26", year=2026, month=2, row_count=1876432),
        _make_partition(symbol="WINJ26", exchange="F", year=2026, month=3),
    )
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    assert catalog_screen._model.rowCount() == 3
    assert catalog_screen.current_state() == "normal"
    footer = catalog_screen._footer.text()
    assert "3 partições" in footer or "3 partições" in footer.replace("\xa0", " ")


def test_filter_by_symbol_narrows_rows(catalog_screen, qtbot):
    """Digitar 'WIN' no search → proxy mostra só WINJ26."""
    partitions = (
        _make_partition(symbol="WDOJ26"),
        _make_partition(symbol="WINJ26"),
    )
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    catalog_screen._search_edit.setText("WIN")
    qtbot.wait(50)
    # Source model continua com 2; proxy filtra.
    assert catalog_screen._model.rowCount() == 2
    assert catalog_screen._proxy.rowCount() == 1


def test_filter_no_match_shows_empty_filtered_state(catalog_screen, qtbot):
    """Filtro sem match → empty_filtered state."""
    partitions = (_make_partition(symbol="WDOJ26"),)
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    catalog_screen._search_edit.setText("XYZ")
    qtbot.wait(50)
    assert catalog_screen.current_state() == "empty_filtered"


def test_clear_filters_returns_to_normal(catalog_screen, qtbot):
    partitions = (_make_partition(symbol="WDOJ26"),)
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    catalog_screen._search_edit.setText("XYZ")
    qtbot.wait(50)
    assert catalog_screen.current_state() == "empty_filtered"

    catalog_screen._on_clear_filters_clicked()
    qtbot.wait(50)
    assert catalog_screen._search_edit.text() == ""
    assert catalog_screen.current_state() == "normal"


# =====================================================================
# Detail panel
# =====================================================================


def test_selecting_row_populates_detail_panel(catalog_screen, qtbot):
    partitions = (_make_partition(symbol="WDOJ26"),)
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    # Seleciona primeira linha do proxy.
    idx = catalog_screen._proxy.index(0, 0)
    catalog_screen._table.setCurrentIndex(idx)
    qtbot.wait(50)

    assert catalog_screen._detail_panel.isVisible()
    assert "WDOJ26" in catalog_screen._detail_title.text()


# =====================================================================
# Delete flow
# =====================================================================


def test_delete_dispatches_request_after_confirm(catalog_screen, qtbot, monkeypatch):
    """Delete + confirm modal → signal _request_delete emitido."""
    partitions = (_make_partition(symbol="WDOJ26"),)
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    idx = catalog_screen._proxy.index(0, 0)
    catalog_screen._table.setCurrentIndex(idx)

    delete_calls: list[tuple] = []
    catalog_screen._request_delete.connect(
        lambda data_dir, rel_path: delete_calls.append((data_dir, rel_path))
    )

    # Patch QMessageBox: simula click no botão DestructiveRole (confirma).
    from PySide6.QtWidgets import QMessageBox

    def fake_exec(self):
        # O botão confirm é o de role DestructiveRole — primeiro adicionado.
        # Forçamos clickedButton a retornar o primeiro botão custom adicionado
        # (que é o "Apagar permanentemente").
        destructive_role = QMessageBox.ButtonRole.DestructiveRole
        custom_buttons = [b for b in self.buttons() if self.buttonRole(b) == destructive_role]
        if custom_buttons:
            self._fake_clicked = custom_buttons[0]
        return 0

    def fake_clicked_button(self):
        return getattr(self, "_fake_clicked", None)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked_button)

    catalog_screen._on_delete_clicked()
    qtbot.waitUntil(lambda: len(delete_calls) > 0, timeout=2000)

    assert len(delete_calls) == 1
    _data_dir, rel_path = delete_calls[0]
    assert "WDOJ26" in rel_path


# =====================================================================
# Refresh shortcut
# =====================================================================


def test_refresh_dispatches_list_request(catalog_screen, qtbot):
    """Ctrl+R / refresh() → signal _request_list emitido."""
    list_calls: list = []
    catalog_screen._request_list.connect(lambda d: list_calls.append(d))

    catalog_screen.refresh()
    qtbot.waitUntil(lambda: len(list_calls) > 0, timeout=2000)

    assert len(list_calls) >= 1
    assert catalog_screen.current_state() == "loading"


# =====================================================================
# Error state
# =====================================================================


def test_error_signal_transitions_to_error_state(catalog_screen, qtbot):
    """Erro do adapter → estado error com microcopy populado."""
    from data_downloader.public_api.exceptions import IntegrityError

    exc = IntegrityError("catalog drift detected")
    catalog_screen._on_error(exc)
    qtbot.wait(50)

    assert catalog_screen.current_state() == "error"
    assert catalog_screen._error_title.text()


def test_handle_escape_clears_filters(catalog_screen, qtbot):
    """Esc com filtro ativo → limpa; sem filtro → no-op."""
    catalog_screen._search_edit.setText("WIN")
    qtbot.wait(20)
    assert catalog_screen.handle_escape() is True
    assert catalog_screen._search_edit.text() == ""

    # Segunda vez sem filtro = no-op.
    assert catalog_screen.handle_escape() is False


# =====================================================================
# State machine emits state_changed
# =====================================================================


def test_state_changed_signal_emitted(catalog_screen, qtbot):
    states: list[str] = []
    catalog_screen.state_changed.connect(states.append)

    catalog_screen._set_state("normal")
    catalog_screen._set_state("error")
    catalog_screen._set_state("loading")

    assert states[-3:] == ["normal", "error", "loading"]
