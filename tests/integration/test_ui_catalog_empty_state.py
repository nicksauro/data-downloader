"""Integration tests — CatalogScreen empty state CTA (Story 4.6).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Cobertura HIGH polish (Pichau directive 2026-05-05):
    - Catalog vazio mostra empty card com CTA "Baixar primeiro símbolo".
    - Click no CTA emite ``request_navigate_to_download`` signal.
    - Catalog populado esconde empty state e mostra tabela.

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Helpers
# =====================================================================


def _make_partition(
    *,
    symbol: str = "WDOFUT",
    exchange: str = "F",
    year: int = 2026,
    month: int = 3,
    row_count: int = 1234567,
    file_size_bytes: int = 47452160,
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
    from data_downloader.ui.screens.catalog_screen import CatalogScreen

    screen = CatalogScreen(data_dir=tmp_path)
    qtbot.addWidget(screen)
    screen.show()
    qtbot.wait(100)
    yield screen
    screen._adapter.shutdown()


# =====================================================================
# Empty state — sem dados → mostra CTA
# =====================================================================


def test_catalog_screen_shows_empty_state_when_no_data(catalog_screen, qtbot):
    """Sem catálogo → estado empty + CTA visível."""
    qtbot.waitUntil(lambda: catalog_screen.current_state() == "empty", timeout=2000)
    assert catalog_screen.current_state() == "empty"
    # CTA button deve existir.
    assert hasattr(catalog_screen, "_empty_cta_btn")
    assert catalog_screen._empty_cta_btn is not None


def test_empty_state_cta_microcopy_resolves(catalog_screen, qtbot):
    """CTA texto não mostra <microcopy id not found> e menciona Ctrl+D."""
    qtbot.waitUntil(lambda: catalog_screen.current_state() == "empty", timeout=2000)
    btn_text = catalog_screen._empty_cta_btn.text()
    assert "<microcopy id not found" not in btn_text
    # Story 4.6: CTA deve mencionar Ctrl+D para reforçar atalho.
    assert "Ctrl+D" in btn_text


def test_empty_state_cta_emits_navigate_signal(catalog_screen, qtbot):
    """Click no CTA emite request_navigate_to_download."""
    qtbot.waitUntil(lambda: catalog_screen.current_state() == "empty", timeout=2000)

    nav_calls: list[bool] = []
    catalog_screen.request_navigate_to_download.connect(lambda: nav_calls.append(True))

    catalog_screen._empty_cta_btn.click()
    qtbot.wait(50)

    assert len(nav_calls) == 1


# =====================================================================
# Populated → tabela visível, empty escondido
# =====================================================================


def test_catalog_screen_shows_table_when_data_present(catalog_screen, qtbot):
    """Catalog populado → estado normal + tabela com rows."""
    partitions = (
        _make_partition(symbol="WDOFUT"),
        _make_partition(symbol="PETR4", exchange="B"),
    )
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    assert catalog_screen.current_state() == "normal"
    assert catalog_screen._model.rowCount() == 2


def test_catalog_screen_transitions_empty_to_normal(catalog_screen, qtbot):
    """Empty → on_partitions_loaded com dados → normal."""
    qtbot.waitUntil(lambda: catalog_screen.current_state() == "empty", timeout=2000)

    partitions = (_make_partition(symbol="WDOFUT"),)
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)

    assert catalog_screen.current_state() == "normal"


def test_catalog_screen_transitions_normal_to_empty_on_clear(catalog_screen, qtbot):
    """Normal → on_partitions_loaded com lista vazia → empty + CTA visível."""
    partitions = (_make_partition(symbol="WDOFUT"),)
    catalog_screen._on_partitions_loaded(partitions)
    qtbot.wait(50)
    assert catalog_screen.current_state() == "normal"

    catalog_screen._on_partitions_loaded(())
    qtbot.wait(50)
    assert catalog_screen.current_state() == "empty"


# =====================================================================
# Empty subtitle reflete nova microcopy (Story 4.6)
# =====================================================================


def test_empty_state_subtitle_mentions_categories(catalog_screen, qtbot):
    """Subtitle empty deve mencionar futures continuous + ações B3 (Story 4.6)."""
    qtbot.waitUntil(lambda: catalog_screen.current_state() == "empty", timeout=2000)
    # Encontra subtitle no empty card.
    from PySide6.QtWidgets import QLabel

    labels = catalog_screen._empty_card.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    combined = " | ".join(texts).lower()
    # Story 4.6 — nova microcopy menciona continuous OU ações B3.
    assert "continuous" in combined or "ações" in combined or "b3" in combined
