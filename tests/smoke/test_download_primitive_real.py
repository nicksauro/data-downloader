"""tests/smoke/test_download_primitive_real.py — Story 1.3 AC10.

Smoke test gated por env (3 vars de credencial ProfitDLL — KEY, USER,
PASS — alinhado com ``.env.example``). Baixa 1 dia de WDOJ26 real (data
fixa: dia útil recente conhecido) e valida ``len(trades) > 0``.

NUNCA roda em CI sem credenciais. Pular silenciosamente quando env ausente.

Para rodar localmente, defina as 3 env vars de credencial — KEY, USER,
PASS — e rode ``pytest -v tests/smoke/test_download_primitive_real.py``.

Q-DRIFT-03 (smoke 2026-05-04): env padronizada para ``PROFITDLL_PASS``
(versões anteriores usavam ``PROFITDLL_PASSWORD``, divergente do
``.env.example``).

(Doc evita exemplo literal `KEY[eq][value]` para não disparar regex do
pre-commit hook ``check_no_dotenv`` — vide COUNCIL-01.)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from data_downloader.dll.wrapper import ProfitDLL
from data_downloader.orchestrator.download_primitive import download_chunk

# Skipif gate — credenciais ProfitDLL ausentes.
pytestmark = pytest.mark.skipif(
    not all(os.getenv(k) for k in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")),
    reason="Smoke real precisa PROFITDLL_KEY + PROFITDLL_USER + PROFITDLL_PASS env vars.",
)


# Story 1.7d — alinhado ao standalone (run_smoke_real_standalone.py):
#   * WDOFUT (continuous future) — Q-DRIFT-31 valida com volume real
#   * Janela <= 5 dias (limite empírico GetHistoryTrades, Q-DRIFT-31)
#   * Datas DINÂMICAS (now-10min back 4d) para evitar "stale data"
# Anteriormente: WDOJ26 + 1 dia fixo (2026-04-15) que passou a falhar
# após contrato vencer + DLL passar a rejeitar dia fixo distante.
_SMOKE_SYMBOL = "WDOFUT"
_SMOKE_EXCHANGE = "F"


def _smoke_window() -> tuple[datetime, datetime]:
    """Janela dinâmica: now-10min até now-10min - 4 dias."""
    end = datetime.now() - timedelta(minutes=10)
    start = end - timedelta(days=4)
    return start, end


@pytest.mark.smoke
def test_download_chunk_real_wdoj26_one_day_returns_trades() -> None:
    """AC10 — baixa janela recente WDOFUT (<=5d) → len(trades) > 0.

    Este teste valida o caminho REAL ponta-a-ponta:
      1. Init ProfitDLL com credenciais reais.
      2. wait_market_connected.
      3. download_chunk de 1 dia de WDOJ26.
      4. Assert: trades > 0.

    Custo: ~30s a 5min dependendo do volume do dia + Q02-E (99% reconnect).
    """
    key = os.environ["PROFITDLL_KEY"]
    user = os.environ["PROFITDLL_USER"]
    password = os.environ["PROFITDLL_PASS"]

    # Story 1.7d — espelho ESTRITO do probe (testa Q-DRIFT-12). Quando
    # ``DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE`` está definida como
    # ``1``/``true``/``yes`` (case-insensitive), o init usa o caminho
    # que espelha EXATAMENTE o probe canônico ``scripts/probe_init.py``
    # L239-251 — pula ``_configure_dll_signatures`` em larga escala,
    # pula ``SetEnabledLogToDebug(0)``, passa ``None`` literal nos slots
    # 4/6/7/8 e callbacks REAIS (TDailyCallback, TProgressCallback,
    # TTinyBookCallback) nos slots 5/9/10 do ``DLLInitializeMarketLogin``.
    # Story 1.7c (commit 2d17923) tinha bug: passava ``None`` em todos
    # os 7 slots não-state — attempt 8 (FAIL-still-stuck) levantou Q-DRIFT-12.
    # Default (var ausente) preserva o caminho atual usado em attempts 4-7.
    minimal_handshake = os.getenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    with ProfitDLL() as dll:
        dll.initialize_market_only(key, user, password, minimal_handshake=minimal_handshake)
        # Q-DRIFT-02 (revisado Story 2.12): handshake é flakey — às vezes 1s,
        # às vezes timeout em 300s com mesma config. Retry policy interna
        # (3 tentativas, 300s timeout/tentativa, 30s cooldown) mitiga.
        connected = dll.wait_market_connected(timeout=300)
        assert connected, (
            "Market data não conectou após retries — verificar horário "
            "de pregão B3 (09:00-18:30 BRT), credenciais e rede."
        )

        dt_start, dt_end = _smoke_window()
        result = download_chunk(
            dll,
            _SMOKE_SYMBOL,
            _SMOKE_EXCHANGE,
            dt_start,
            dt_end,
            timeout=600,  # 10 min — generoso para Q02-E quirk
        )

        assert result.status in ("completed", "timeout"), f"status inesperado: {result.status}"
        # AC10: trades > 0.
        assert len(result.trades) > 0, (
            f"Esperado >0 trades para {_SMOKE_SYMBOL} em "
            f"{dt_start.date()}-{dt_end.date()}; recebido 0. "
            f"status={result.status}, progress={result.progress_history[-5:]}"
        )
        # Validação adicional: timestamps em ordem cronológica BRT naive.
        if result.actual_start is not None and result.actual_end is not None:
            assert result.actual_start <= result.actual_end
        # Cada trade tem dll_version preenchida (metadata Sol).
        assert all(t.dll_version for t in result.trades)
