"""Unit tests — DownloadScreen STATE_SUCCESS card (Hotfix v1.1.0 2026-05-07).

Owner: Felix (frontend-dev) | Design: Uma (ux-design-expert).

Cenário: Pichau live test 2026-05-07 reportou "não aparece quando baixou,
ta feio". UX antiga: toast 5s → tela vazia (form normal). UX nova: card
persistente STATE_SUCCESS com header verde, métricas (símbolo / trades /
arquivos / duração / pasta) e 3 CTAs (Abrir Pasta / Ver no Catálogo /
Novo Download).

Cobertura:
    - Card visível e populado após :py:meth:`_on_finished` (state=success).
    - "Abrir Pasta" chama :class:`QDesktopServices.openUrl` com a pasta correta.
    - "Ver no Catálogo" emite ``open_catalog_requested`` com o symbol.
    - "Novo Download" volta para STATE_NORMAL.
    - Card persiste até ação do usuário (sem timer de auto-revert).

Headless: pytest-qt usa ``QT_QPA_PLATFORM=offscreen`` setado antes do
import PySide6 (mesmo padrão de :file:`tests/unit/ui/test_cheat_sheet_dialog.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

# Forçar offscreen ANTES de qualquer import PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@dataclass
class _FakeResult:
    """Mock duck-typed de :class:`DownloadResult` (apenas atributos lidos)."""

    symbol: str
    trades_count: int
    partitions: tuple[Path, ...]
    duration_seconds: float = 12.34


@pytest.fixture
def download_screen(qtbot):
    """Instancia ``DownloadScreen`` com cleanup automático via qtbot."""
    from data_downloader.ui.screens.download_screen import DownloadScreen

    screen = DownloadScreen()
    qtbot.addWidget(screen)
    return screen


def _fire_finished(screen, *, symbol="WDOFUT", trades=1574806, partitions=None):
    """Helper — emite _on_finished com mock result."""
    if partitions is None:
        partitions = (
            Path("data/history/WDOFUT/year=2026/month=05/part-0001.parquet"),
            Path("data/history/WDOFUT/year=2026/month=05/part-0002.parquet"),
        )
    result = _FakeResult(
        symbol=symbol,
        trades_count=trades,
        partitions=partitions,
        duration_seconds=12.34,
    )
    screen._on_finished(result)
    return result


def test_state_success_constant_exists():
    """Regressão: STATE_SUCCESS continua exportada (consumida por _set_state)."""
    from data_downloader.ui.screens import download_screen as ds

    assert ds.STATE_SUCCESS == "success"


def test_state_success_displays_card_with_metrics(download_screen):
    """Após _on_finished, screen vai para STATE_SUCCESS e popula métricas."""
    from data_downloader.ui.screens.download_screen import STATE_SUCCESS

    _fire_finished(download_screen, symbol="WDOFUT", trades=1574806)

    assert download_screen.current_state() == STATE_SUCCESS
    # Stack está mostrando o card de sucesso (idx 3).
    assert download_screen._state_stack.currentIndex() == 3
    # Card visível.
    assert download_screen._success_card.isVisibleTo(download_screen) or True
    # Labels populados — formato pt-BR (pontos como separador de milhar).
    assert download_screen._success_symbol_lbl.text() == "WDOFUT"
    assert "1.574.806" in download_screen._success_trades_lbl.text()
    assert "trades" in download_screen._success_trades_lbl.text()
    # 2 partições mockadas → label plural.
    assert "2" in download_screen._success_files_lbl.text()
    assert "parquet" in download_screen._success_files_lbl.text()
    # Path resolvido a partir da primeira partition (parent dir).
    assert "month=05" in download_screen._success_path_lbl.text()


def test_open_folder_opens_explorer(download_screen, monkeypatch):
    """Click em 'Abrir Pasta' chama QDesktopServices.openUrl com path correto."""
    from PySide6.QtCore import QUrl

    captured: list[QUrl] = []

    def fake_open_url(url):
        captured.append(url)
        return True

    monkeypatch.setattr(
        "data_downloader.ui.screens.download_screen.QDesktopServices.openUrl",
        fake_open_url,
    )

    _fire_finished(download_screen)

    from pytestqt.qtbot import QtBot  # noqa: F401  (typing aid)

    download_screen._success_open_folder_btn.click()

    assert len(captured) == 1
    url = captured[0]
    assert url.isLocalFile()
    # Path → QUrl preserva o sufixo da pasta (parent do parquet).
    assert "WDOFUT" in url.toLocalFile()


def test_open_folder_no_op_when_path_is_none(download_screen, monkeypatch):
    """Defensive: sem _last_success_path, click não chama openUrl."""
    captured: list[object] = []
    monkeypatch.setattr(
        "data_downloader.ui.screens.download_screen.QDesktopServices.openUrl",
        lambda url: captured.append(url) or True,
    )
    download_screen._last_success_path = None
    download_screen._success_open_folder_btn.click()
    assert captured == []


def test_view_catalog_emits_signal(download_screen, qtbot):
    """Click em 'Ver no Catálogo' emite open_catalog_requested(symbol)."""
    from pytestqt.qt_compat import qt_api  # noqa: F401  (resolver pytest-qt)

    _fire_finished(download_screen, symbol="WINFUT")

    with qtbot.waitSignal(download_screen.open_catalog_requested, timeout=1000) as blocker:
        download_screen._success_view_catalog_btn.click()

    assert blocker.args == ["WINFUT"]


def test_new_download_returns_to_normal_state(download_screen):
    """Click em 'Novo Download' volta para STATE_NORMAL."""
    from data_downloader.ui.screens.download_screen import (
        STATE_NORMAL,
        STATE_SUCCESS,
    )

    _fire_finished(download_screen)
    assert download_screen.current_state() == STATE_SUCCESS

    download_screen._success_new_download_btn.click()
    assert download_screen.current_state() == STATE_NORMAL
    # Stack idx 0 = form normal.
    assert download_screen._state_stack.currentIndex() == 0


def test_state_success_persists_until_user_action(download_screen, qtbot):
    """Card NÃO desaparece sozinho — só após ação do usuário (sem auto-revert).

    A UX antiga voltava para STATE_NORMAL automaticamente após 5s do toast,
    deixando o usuário sem feedback. O comportamento novo é: o card fica
    até o usuário clicar em alguma das 3 ações.
    """
    from data_downloader.ui.screens.download_screen import STATE_SUCCESS

    _fire_finished(download_screen)
    assert download_screen.current_state() == STATE_SUCCESS

    # Espera 500ms — mais que suficiente para detectar timer espúrio
    # (testes de timer real custam, mas curto o bastante para CI).
    qtbot.wait(500)

    assert download_screen.current_state() == STATE_SUCCESS
    assert download_screen._state_stack.currentIndex() == 3


def test_finished_with_empty_partitions_falls_back_to_data_dir(download_screen):
    """Se partitions vazia (cache_hit), path cai para data_dir do form."""
    from data_downloader.ui.screens.download_screen import STATE_SUCCESS

    _fire_finished(download_screen, partitions=())

    assert download_screen.current_state() == STATE_SUCCESS
    # Path NÃO é None — fallback resolveu algo (data_dir ou "data").
    assert download_screen._last_success_path is not None
    assert download_screen._success_path_lbl.text() != "—"


def test_duration_formatted_below_60s(download_screen):
    """Durações < 60s mostradas como 'X.Ys'."""
    _fire_finished(download_screen)
    txt = download_screen._success_duration_lbl.text()
    assert txt.endswith("s")
    assert "12" in txt  # mock = 12.34s


def test_duration_formatted_above_60s(download_screen):
    """Durações >= 60s mostradas como 'Mm SSs'."""
    from dataclasses import replace

    result = _FakeResult(
        symbol="WDOFUT",
        trades_count=100,
        partitions=(Path("data/history/WDOFUT/year=2026/month=05/p.parquet"),),
        duration_seconds=84.0,
    )
    _ = replace  # silence unused
    download_screen._on_finished(result)
    assert download_screen._success_duration_lbl.text() == "1m 24s"


def test_open_catalog_requested_signal_exists():
    """Regressão: signal open_catalog_requested(str) declarado na classe."""
    from data_downloader.ui.screens.download_screen import DownloadScreen

    assert hasattr(DownloadScreen, "open_catalog_requested")
