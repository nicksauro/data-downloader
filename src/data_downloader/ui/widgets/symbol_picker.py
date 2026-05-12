"""data_downloader.ui.widgets.symbol_picker — Picker de símbolo (Story 3.2).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

``QComboBox`` editável com autocomplete e cache do último símbolo usado em
``~/.data-downloader/cache/last_symbol.txt`` (path canônico — hífen, alinhado
a :func:`data_downloader._internal.bundle_paths.user_data_dir`). Resolução
do contrato vigente (via :func:`vigent_contract`) é oportunística — fica em
modo "stub" se a DLL/catálogo não estiver disponível, sem bloquear a UI.

Microcopy IDs (R17 — Uma):
    - ``LBL_SYMBOL`` (label)
    - ``PLH_SYMBOL`` (placeholder)
    - ``BTN_LIST_CONTRACTS`` (botão "Listar Vigentes" — V2)
    - ``TIP_SYMBOL`` (tooltip)
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from data_downloader._internal.bundle_paths import user_data_dir
from data_downloader.ui.microcopy_loader import format_msg

__all__ = ["SymbolPicker"]

_log = logging.getLogger("data_downloader.ui.widgets.symbol_picker")

# Canonical path uses HYPHEN (``~/.data-downloader/``) — alinhado a
# :func:`bundle_paths.user_data_dir`. Pré-fix este módulo usava
# UNDERSCORE (``~/.data_downloader/``), criando diretório fantasma.
# Migração silenciosa best-effort em ``_migrate_legacy_cache``.
_CACHE_DIR = user_data_dir() / "cache"
_CACHE_FILE = _CACHE_DIR / "last_symbol.txt"

_LEGACY_CACHE_DIR = Path.home() / ".data_downloader" / "cache"
_LEGACY_CACHE_FILE = _LEGACY_CACHE_DIR / "last_symbol.txt"


def _migrate_legacy_cache() -> None:
    """Migra ``~/.data_downloader/cache/last_symbol.txt`` (underscore legacy)
    para o path canônico (hífen) se este último ainda não existir.

    Best-effort: qualquer ``OSError`` é apenas logado em ``warning`` e
    suprimido — UX cache é opcional, nunca pode quebrar a UI.
    """
    try:
        if _LEGACY_CACHE_FILE.exists() and not _CACHE_FILE.exists():
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_bytes(_LEGACY_CACHE_FILE.read_bytes())
    except OSError as exc:
        _log.warning("symbol_picker cache legacy migration skipped: %s", exc)


# Story 4.6 (UX simplification, Pichau directive 2026-05-05):
# Sugestões alinhadas a Q-DRIFT-32 ("SEMPRE usar continuous futures").
# Equities populares B3 (top liquid) + futures principais.

_FUTURES_SUGGESTIONS: tuple[str, ...] = (
    "WDOFUT",  # Mini-dólar continuous
    "WINFUT",  # Mini-Ibovespa continuous
    "INDFUT",  # Indice futuro continuous
    "DOLFUT",  # Dólar futuro continuous
)

_EQUITIES_SUGGESTIONS: tuple[str, ...] = (
    "PETR4",  # Petrobras PN
    "VALE3",  # Vale ON
    "ITUB4",  # Itaú PN
    "BBDC4",  # Bradesco PN
    "BBAS3",  # Banco do Brasil ON
    "ABEV3",  # Ambev ON
    "B3SA3",  # B3 ON
    "MGLU3",  # Magalu ON
)

# Backwards-compat: ainda aceita WDOJ26/WINJ26 etc se digitado, mas
# não sugere (resolver no CLI/orchestrator emite warning recomendando
# WDOFUT — ver `data_downloader.orchestrator.symbol_alias`).
_DEFAULT_SUGGESTIONS: tuple[str, ...] = _FUTURES_SUGGESTIONS + _EQUITIES_SUGGESTIONS


class SymbolPicker(QWidget):
    """Combobox com autocomplete + label + hint do contrato vigente.

    API pública:
        value() -> str: símbolo digitado (uppercase, trimmed).
        set_value(str) -> None: programaticamente preenche.
        save_to_cache(): persiste o valor atual em ``last_symbol.txt``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._label = QLabel(format_msg("LBL_SYMBOL"), self)
        self._label.setProperty("role", "subtitle")

        self._combo = QComboBox(self)
        self._combo.setEditable(True)
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo.setToolTip(format_msg("TIP_SYMBOL"))

        # Placeholder ("ex: WDOJ26") — em QComboBox é via lineEdit.
        line_edit = self._combo.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText(format_msg("PLH_SYMBOL"))

        # Popula sugestões agrupadas: futures (continuous) + separator + equities.
        # Story 4.6 — Pichau directive: futures continuous PRIMEIRO (Q-DRIFT-32).
        for sym in _FUTURES_SUGGESTIONS:
            self._combo.addItem(sym)
        self._combo.insertSeparator(self._combo.count())
        for sym in _EQUITIES_SUGGESTIONS:
            self._combo.addItem(sym)

        cached = self._load_from_cache()
        if cached:
            self.set_value(cached)
        else:
            # Default = 1ª sugestão (WDOFUT — futures continuous).
            self.set_value(_FUTURES_SUGGESTIONS[0])

        # Hint do contrato vigente (atualizado quando vigent_contract roda).
        self._hint = QLabel("", self)
        self._hint.setProperty("role", "muted")

        # Layout vertical: label + combo (com botão futuro side-by-side).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(self._label)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._combo, stretch=1)
        outer.addLayout(row)

        outer.addWidget(self._hint)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def value(self) -> str:
        """Retorna símbolo atual (uppercase, trimmed)."""
        return (self._combo.currentText() or "").strip().upper()

    def set_value(self, symbol: str) -> None:
        """Define símbolo programaticamente."""
        sym = (symbol or "").strip().upper()
        # Adiciona se não existir.
        idx = self._combo.findText(sym)
        if idx < 0:
            self._combo.addItem(sym)
            idx = self._combo.findText(sym)
        self._combo.setCurrentIndex(idx)

    def set_hint(self, text: str) -> None:
        """Atualiza o hint embaixo (ex: 'WDOJ26 sugerido — vigente até ...')."""
        self._hint.setText(text)

    def save_to_cache(self) -> None:
        """Persiste o valor atual em ``~/.data-downloader/cache/last_symbol.txt``."""
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_text(self.value(), encoding="utf-8")
        except OSError:
            # Best-effort — UX cache é opcional.
            pass

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _load_from_cache(self) -> str:
        _migrate_legacy_cache()
        try:
            if _CACHE_FILE.exists():
                return _CACHE_FILE.read_text(encoding="utf-8").strip().upper()
        except OSError:
            pass
        return ""
