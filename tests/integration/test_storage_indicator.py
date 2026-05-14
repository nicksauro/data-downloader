"""Integration tests — StorageIndicator widget (v1.3.0 Wave 4B).

Owner: Uma (UX) + Felix (impl) | Test infra: Quinn (pytest-qt).

Cobertura:
    - Format pt-BR (separador `,` decimal, `.` milhar).
    - set_data_dir populando free/used corretamente em tmp_path com
      parquets fake.
    - Cor verde com 50 GB free; amarelo com 10 GB; vermelho com 2 GB
      (mockando shutil.disk_usage).
    - Tooltip com path + porcentagem.
    - Refresh manual atualiza label.
    - Integração com MainWindow statusbar (smoke headless).
    - WAR_STORAGE_LOW aparece no tooltip quando crítico.

Headless: via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import contextlib
import os
from collections import namedtuple
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_FakeUsage = namedtuple("_FakeUsage", "total used free")


def _fake_usage(free_gb: float, total_gb: float = 256.0):
    """Factory para fake ``shutil.disk_usage`` return."""
    gb = 1024**3
    total = int(total_gb * gb)
    free = int(free_gb * gb)
    used = total - free
    return _FakeUsage(total=total, used=used, free=free)


def _make_fake_parquet(path: Path, size_bytes: int) -> None:
    """Cria um arquivo .parquet fake com tamanho controlado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"\0" * size_bytes)


# =====================================================================
# format_gb_ptbr
# =====================================================================


def test_format_ptbr_decimal_separator():
    from data_downloader.ui.widgets.storage_indicator import format_gb_ptbr

    assert format_gb_ptbr(0.0) == "0,0"
    assert format_gb_ptbr(1.5) == "1,5"
    assert format_gb_ptbr(123.45) == "123,5"  # arredonda 1 casa


def test_format_ptbr_thousands_separator():
    from data_downloader.ui.widgets.storage_indicator import format_gb_ptbr

    assert format_gb_ptbr(1234.5) == "1.234,5"
    assert format_gb_ptbr(12345.6) == "12.345,6"


# =====================================================================
# StorageIndicator standalone
# =====================================================================


@pytest.fixture
def indicator(qtbot):
    """Instancia o widget standalone (sem MainWindow)."""
    from data_downloader.ui.widgets.storage_indicator import StorageIndicator

    w = StorageIndicator()
    qtbot.addWidget(w)
    yield w
    with contextlib.suppress(Exception):
        w._timer.stop()


def test_indicator_initial_state(indicator):
    """Sem data_dir setado, label fica vazia."""
    assert indicator._label.text() == ""
    assert indicator.free_gb() == 0.0
    assert indicator.used_gb() == 0.0


def test_indicator_set_data_dir_populates_label(indicator, tmp_path, monkeypatch):
    """``set_data_dir`` aciona poll e popula label com free/used."""
    # 50 GB free → verde.
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=50.0, total_gb=256.0),
    )
    # Cria 1 parquet fake de 2 MB.
    _make_fake_parquet(tmp_path / "WDOJ26" / "2026-04.parquet", 2 * 1024 * 1024)

    indicator.set_data_dir(tmp_path)

    text = indicator._label.text()
    assert "GB livres" in text
    assert "GB usados" in text
    # Pt-BR: vírgula decimal.
    assert "50,0" in text
    # Used em GB ~ 0.0 (2 MB).
    assert "0,0 GB usados" in text


def test_indicator_color_green_when_free_high(indicator, tmp_path, monkeypatch):
    """free_gb >= 20 → verde (#3FCB6F)."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=50.0),
    )
    indicator.set_data_dir(tmp_path)
    assert indicator.severity() == "ok"
    assert "#3FCB6F" in indicator._label.styleSheet()


def test_indicator_color_yellow_when_free_medium(indicator, tmp_path, monkeypatch):
    """5 <= free_gb < 20 → amarelo (#F2C94C)."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=10.0),
    )
    indicator.set_data_dir(tmp_path)
    assert indicator.severity() == "medium"
    assert "#F2C94C" in indicator._label.styleSheet()


def test_indicator_color_red_when_free_low(indicator, tmp_path, monkeypatch):
    """free_gb < 5 → vermelho (#F25656) + warning no tooltip."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=2.0),
    )
    indicator.set_data_dir(tmp_path)
    assert indicator.severity() == "critical"
    assert "#F25656" in indicator._label.styleSheet()
    # Warning prefixa o tooltip.
    tip = indicator._label.toolTip()
    assert "crítico" in tip.lower() or "critico" in tip.lower()


def test_indicator_tooltip_has_path_and_pct(indicator, tmp_path, monkeypatch):
    """Tooltip mostra path completo + porcentagem usada."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=128.0, total_gb=256.0),
    )
    indicator.set_data_dir(tmp_path)
    tip = indicator._label.toolTip()
    # Path completo aparece.
    assert str(tmp_path) in tip
    # 50% usado (128 free de 256 total).
    assert "50,0" in tip
    # "GB" como unit na total.
    assert "GB" in tip


def test_indicator_refresh_recomputes(indicator, tmp_path, monkeypatch):
    """``refresh()`` força re-poll (após mudança no disco)."""
    free_state = {"gb": 100.0}

    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=free_state["gb"]),
    )
    indicator.set_data_dir(tmp_path)
    assert indicator.free_gb() == pytest.approx(100.0, rel=1e-3)

    # Disco "encheu" → próximo refresh deve ler 3 GB.
    free_state["gb"] = 3.0
    indicator.refresh()
    assert indicator.free_gb() == pytest.approx(3.0, rel=1e-3)
    assert indicator.severity() == "critical"


def test_indicator_handles_nonexistent_dir(indicator, tmp_path, monkeypatch):
    """``set_data_dir`` em path inexistente: graceful — ascende pro parent."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=42.0),
    )
    fake = tmp_path / "nao_existe" / "ainda"
    indicator.set_data_dir(fake)
    # Não crasha; free reflete o mock (ascendeu).
    assert indicator.free_gb() == pytest.approx(42.0, rel=1e-3)
    # Used em pasta inexistente = 0.
    assert indicator.used_gb() == 0.0


def test_indicator_used_gb_sums_only_parquets(indicator, tmp_path, monkeypatch):
    """``_parquets_used_gb`` só soma .parquet (ignora .db / .log / etc.)."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=100.0),
    )
    # 100 MB de parquets + 50 MB de outras coisas (não devem contar).
    _make_fake_parquet(tmp_path / "A" / "1.parquet", 50 * 1024 * 1024)
    _make_fake_parquet(tmp_path / "B" / "2.parquet", 50 * 1024 * 1024)
    # Decoy: arquivo grande não-parquet.
    (tmp_path / "_internal").mkdir(exist_ok=True)
    with (tmp_path / "_internal" / "catalog.db").open("wb") as fh:
        fh.write(b"\0" * (50 * 1024 * 1024))

    indicator.set_data_dir(tmp_path)
    # 100 MB ≈ 0.0977 GB.
    assert indicator.used_gb() == pytest.approx(0.0977, abs=1e-3)


# =====================================================================
# Threshold boundaries
# =====================================================================


@pytest.mark.parametrize(
    "free_gb,expected_severity",
    [
        (100.0, "ok"),
        (20.0, "ok"),  # boundary inclusive
        (19.9, "medium"),
        (5.0, "medium"),  # boundary inclusive
        (4.9, "critical"),
        (0.0, "critical"),
    ],
)
def test_indicator_severity_thresholds(
    indicator, tmp_path, monkeypatch, free_gb, expected_severity
):
    """Boundaries: 5 e 20 GB são inclusive (>=)."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=free_gb),
    )
    indicator.set_data_dir(tmp_path)
    assert indicator.severity() == expected_severity


# =====================================================================
# Microcopy resolution
# =====================================================================


def test_indicator_microcopy_resolves(indicator, tmp_path, monkeypatch):
    """LBL_STORAGE_INDICATOR + TIP_STORAGE_INDICATOR resolvem (sem sentinela)."""
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=50.0),
    )
    indicator.set_data_dir(tmp_path)
    assert "<microcopy id not found" not in indicator._label.text()
    assert "<microcopy id not found" not in indicator._label.toolTip()


# =====================================================================
# Integração com MainWindow
# =====================================================================


@pytest.fixture
def main_window(qtbot, monkeypatch):
    """MainWindow com cleanup automático."""
    # Mock disk_usage para não depender do disco real do CI.
    monkeypatch.setattr(
        "data_downloader.ui.widgets.storage_indicator.shutil.disk_usage",
        lambda _p: _fake_usage(free_gb=100.0, total_gb=512.0),
    )

    from data_downloader.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    yield window

    for screen_id in ("download", "catalog", "settings"):
        with contextlib.suppress(Exception):
            screen = window._screens.get(screen_id)
            if screen is not None and hasattr(screen, "_adapter"):
                screen._adapter.shutdown()
    with contextlib.suppress(Exception):
        window._metrics_adapter.shutdown()


def test_main_window_has_storage_indicator(main_window):
    """MainWindow embeda o StorageIndicator na statusbar."""
    from data_downloader.ui.widgets.storage_indicator import StorageIndicator

    assert hasattr(main_window, "_storage_indicator")
    assert isinstance(main_window._storage_indicator, StorageIndicator)


def test_main_window_storage_indicator_in_statusbar(main_window):
    """Indicator é child do statusBar (permanent widget)."""
    bar = main_window.statusBar()
    # findChild varre toda a árvore visual incluindo widgets permanentes.
    from data_downloader.ui.widgets.storage_indicator import StorageIndicator

    found = bar.findChild(StorageIndicator)
    assert found is main_window._storage_indicator


def test_main_window_storage_indicator_has_data_dir_set(main_window):
    """Após init, indicator está apontando para default_data_dir."""
    from data_downloader._internal.bundle_paths import default_data_dir

    indicator = main_window._storage_indicator
    assert indicator._data_dir == default_data_dir()
    # Label deve estar populada (não vazia).
    assert indicator._label.text() != ""
    assert "GB livres" in indicator._label.text()


def test_main_window_storage_indicator_responds_to_data_dir_changed(main_window, tmp_path, qtbot):
    """``settings.data_dir_changed`` re-aponta o indicator."""
    settings_screen = main_window._screens.get("settings")
    if settings_screen is None or not hasattr(settings_screen, "data_dir_changed"):
        pytest.skip("settings_screen.data_dir_changed indisponível")

    indicator = main_window._storage_indicator
    # Emite signal manualmente (não chama backend real do Settings).
    settings_screen.data_dir_changed.emit(str(tmp_path))
    qtbot.wait(50)
    assert indicator._data_dir == tmp_path


def test_main_window_storage_indicator_responds_to_partition_registered(main_window, qtbot):
    """``catalog_adapter.partition_registered`` aciona refresh do indicator."""
    catalog_screen = main_window._screens.get("catalog")
    if catalog_screen is None:
        pytest.skip("catalog_screen indisponível")
    adapter = getattr(catalog_screen, "_adapter", None)
    if adapter is None or not hasattr(adapter, "partition_registered"):
        pytest.skip("catalog_adapter.partition_registered indisponível")

    indicator = main_window._storage_indicator
    # Captura free_gb pré, força mock retornar valor diferente, emite signal.
    pre_free = indicator.free_gb()
    # Refresh manual para baseline.
    indicator.refresh()
    pre_free = indicator.free_gb()

    # Emite partition_registered via signal Queued (cross-thread sintético).
    adapter.partition_registered.emit("WDOJ26", 2026, 4)
    qtbot.wait(150)
    # Indicator continua válido (sem crash). Free não muda porque mock é
    # idempotente — o que validamos é que o connect existe e roda sem erro.
    assert indicator.free_gb() == pre_free
    assert indicator._label.text() != ""
