"""Integration tests — UI progress bar per chunk (Story 4.16).

Owner: Dex (impl) | Pichau directive 2026-05-07 (supersede 2026-05-06).

V1.1.0 política unificada: SEMPRE 1d/chunk para todos os ativos
(WDOFUT/WINFUT/INDFUT/DOLFUT/equities). 1 semana B3 cheia = 5 chunks.

Cobertura:
    - ProgressCard.set_progress traduz DownloadProgress(total=N, done=K,
      message='INF_CHUNK_COMPLETE') em barra preenchida em K/N * 100%.
    - Subtitle exibe "X/Y chunks (N trades) — Z%".
    - Múltiplos events movem a barra de 0 → 50% → 100%.

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
def progress_card(qtbot):
    from data_downloader.ui.widgets.progress_card import ProgressCard

    card = ProgressCard()
    qtbot.addWidget(card)
    card.show()
    yield card


def _make_progress(
    *,
    total: int,
    done: int,
    trades_received: int,
    contract: str = "WDOJ26",
    message: str = "INF_CHUNK_COMPLETE",
):
    """Constrói DownloadProgress real (frozen dataclass)."""
    from data_downloader.public_api.handle import DownloadProgress

    return DownloadProgress(
        total=total,
        done=done,
        message=message,
        trades_received=trades_received,
        current_contract=contract,
    )


# =====================================================================
# Tests
# =====================================================================


@pytest.mark.integration
def test_progress_card_advances_per_chunk(progress_card) -> None:
    """2 chunks → barra vai de 0 → 50% após chunk 1, 100% após chunk 2."""
    progress_card.set_progress(_make_progress(total=2, done=1, trades_received=100))
    assert progress_card._bar.value() == 50

    progress_card.set_progress(_make_progress(total=2, done=2, trades_received=250))
    assert progress_card._bar.value() == 100


@pytest.mark.integration
def test_progress_card_subtitle_shows_chunk_count(progress_card) -> None:
    """Subtitle formato 'X/Y chunks (N trades) — Z%'."""
    progress_card.set_progress(_make_progress(total=4, done=2, trades_received=1234))
    subtitle = progress_card._subtitle.text()
    assert "2/4" in subtitle
    assert "chunks" in subtitle
    # 1.234 (BR thousands separator).
    assert "1.234" in subtitle
    assert "trades" in subtitle
    # Percentual 50.0%.
    assert "50.0" in subtitle


@pytest.mark.integration
def test_progress_card_handles_winfut_per_day_chunks(progress_card) -> None:
    """V1.1.0+ política unificada (1d/chunk para TODOS os ativos):
    1 semana = 5 chunks → barra +20% por chunk.

    Simula uma semana com 5 chunks (1 chunk = 1 dia útil — Pichau
    directive 2026-05-07, supersede 2026-05-06).
    """
    progress_card.set_progress(_make_progress(total=5, done=1, trades_received=10))
    assert progress_card._bar.value() == 20

    progress_card.set_progress(_make_progress(total=5, done=3, trades_received=30))
    assert progress_card._bar.value() == 60

    progress_card.set_progress(_make_progress(total=5, done=5, trades_received=50))
    assert progress_card._bar.value() == 100
    subtitle = progress_card._subtitle.text()
    assert "5/5" in subtitle
    assert "100.0" in subtitle
