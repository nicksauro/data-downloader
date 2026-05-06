"""Integration tests — SymbolPicker widget (Story 4.6).

Owner: Felix (frontend-dev) | Test infra: Quinn (pytest-qt).

Cobertura:
    - Default suggestions são FUT (continuous) — Q-DRIFT-32 + Pichau directive
      2026-05-05 (NÃO mais WDOJ26).
    - Dropdown agrupa em duas categorias com QComboBox separator: futures
      primeiro (4 itens), separator, equities (8 itens).
    - Backwards-compat: usuário ainda pode digitar WDOJ26 no line edit
      mesmo não estando na lista pré-populada.

Headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def symbol_picker(qtbot, monkeypatch, tmp_path):
    """Cria SymbolPicker isolado com cache redirected para tmp_path."""
    # Redireciona cache para tmp_path para não interferir com cache real do dev.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    # IMPORTANTE: re-import para pegar Path.home() recalculado.
    import importlib

    from data_downloader.ui.widgets import symbol_picker as sp_module

    importlib.reload(sp_module)
    # Força os Path constants a reconsiderarem Path.home() — patch direto.
    monkeypatch.setattr(sp_module, "_CACHE_DIR", fake_home / ".data_downloader" / "cache")
    monkeypatch.setattr(
        sp_module, "_CACHE_FILE", fake_home / ".data_downloader" / "cache" / "last_symbol.txt"
    )

    widget = sp_module.SymbolPicker()
    qtbot.addWidget(widget)
    widget.show()
    yield widget


# =====================================================================
# Q-DRIFT-32 alignment — sugestões default são FUT
# =====================================================================


def test_symbol_picker_default_suggestions_are_fut(symbol_picker):
    """Primeiro item do dropdown é WDOFUT (continuous), não WDOJ26 (vencimento)."""
    combo = symbol_picker._combo
    first_item_text = combo.itemText(0)
    assert (
        first_item_text == "WDOFUT"
    ), f"Primeiro item esperado WDOFUT (Q-DRIFT-32 continuous), got {first_item_text!r}"

    # Default selecionado também deve ser WDOFUT (sem cache).
    assert symbol_picker.value() == "WDOFUT"


def test_symbol_picker_does_not_suggest_wdoj26(symbol_picker):
    """WDOJ26 (vencimento J/abril) NÃO deve aparecer no dropdown padrão."""
    combo = symbol_picker._combo
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "WDOJ26" not in items
    assert "WINJ26" not in items


def test_symbol_picker_includes_equities(symbol_picker):
    """Equities populares B3 devem estar no dropdown."""
    combo = symbol_picker._combo
    items = [combo.itemText(i) for i in range(combo.count())]
    # Top liquids B3 esperados.
    for ticker in ("PETR4", "VALE3", "ITUB4"):
        assert ticker in items, f"Equity {ticker} faltando no dropdown"


def test_symbol_picker_includes_futures(symbol_picker):
    """Futuros continuous principais devem estar no dropdown."""
    combo = symbol_picker._combo
    items = [combo.itemText(i) for i in range(combo.count())]
    for fut in ("WDOFUT", "WINFUT", "INDFUT", "DOLFUT"):
        assert fut in items, f"Future {fut} faltando no dropdown"


# =====================================================================
# Dropdown agrupado com separator
# =====================================================================


def test_symbol_picker_separator_between_categories(symbol_picker):
    """Há separator entre futures (4) e equities (8) — count > 12."""
    from data_downloader.ui.widgets.symbol_picker import (
        _EQUITIES_SUGGESTIONS,
        _FUTURES_SUGGESTIONS,
    )

    combo = symbol_picker._combo
    # 4 futures + 1 separator + 8 equities = 13 itens.
    n_futures = len(_FUTURES_SUGGESTIONS)
    n_equities = len(_EQUITIES_SUGGESTIONS)
    expected_min = n_futures + n_equities + 1  # +1 separator

    assert (
        combo.count() >= expected_min
    ), f"Esperava >= {expected_min} (futures+separator+equities), got {combo.count()}"


def test_symbol_picker_separator_position(symbol_picker):
    """Separator está exatamente após o último future (índice = len(futures))."""
    from data_downloader.ui.widgets.symbol_picker import _FUTURES_SUGGESTIONS

    combo = symbol_picker._combo
    # Em QComboBox, separators são items sem flag selectable. Verificamos por
    # ItemFlag — separator não tem ItemIsEnabled.
    from PySide6.QtCore import Qt

    sep_idx = len(_FUTURES_SUGGESTIONS)
    flags = combo.model().index(sep_idx, 0).flags()
    # Separator NÃO tem ItemIsEnabled nem ItemIsSelectable.
    assert not (
        flags & Qt.ItemFlag.ItemIsSelectable
    ), f"Item no índice {sep_idx} deveria ser separator (não-selectable)"


# =====================================================================
# Backwards compat — WDOJ26 ainda funciona como text entry
# =====================================================================


def test_symbol_picker_accepts_legacy_wdoj26_via_text_entry(symbol_picker):
    """Usuário pode digitar WDOJ26 mesmo não estando no dropdown sugestões."""
    combo = symbol_picker._combo
    items_before = [combo.itemText(i) for i in range(combo.count())]
    assert "WDOJ26" not in items_before  # confirma sanity

    # set_value adiciona se necessário — backwards-compat.
    symbol_picker.set_value("WDOJ26")
    assert symbol_picker.value() == "WDOJ26"


def test_symbol_picker_accepts_lowercase_text_entry(symbol_picker):
    """value() retorna uppercase mesmo se usuário digita lowercase."""
    symbol_picker.set_value("petr4")
    assert symbol_picker.value() == "PETR4"


# =====================================================================
# Microcopy resolves (no <microcopy id not found>)
# =====================================================================


def test_symbol_picker_microcopy_resolves(symbol_picker):
    """Placeholder e tooltip não mostram <microcopy id not found>."""
    line_edit = symbol_picker._combo.lineEdit()
    assert line_edit is not None
    placeholder = line_edit.placeholderText()
    assert "<microcopy id not found" not in placeholder
    # Story 4.6: novo placeholder mostra continuous + equity como exemplos.
    assert "WDOFUT" in placeholder or "PETR4" in placeholder

    tooltip = symbol_picker._combo.toolTip()
    assert "<microcopy id not found" not in tooltip
