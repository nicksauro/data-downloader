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
from datetime import datetime

import pytest

from data_downloader.dll.wrapper import ProfitDLL
from data_downloader.orchestrator.download_primitive import download_chunk

# Skipif gate — credenciais ProfitDLL ausentes.
pytestmark = pytest.mark.skipif(
    not all(os.getenv(k) for k in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")),
    reason="Smoke real precisa PROFITDLL_KEY + PROFITDLL_USER + PROFITDLL_PASS env vars.",
)


# Data fixa: dia útil recente conhecido com volume.
# 2026-04-15 (quarta-feira) — pregão regular, contrato WDOJ26 (vigência abril 2026).
_SMOKE_SYMBOL = "WDOJ26"
_SMOKE_EXCHANGE = "F"
_SMOKE_DT_START = datetime(2026, 4, 15, 9, 0, 0)
_SMOKE_DT_END = datetime(2026, 4, 15, 17, 30, 0)


@pytest.mark.smoke
def test_download_chunk_real_wdoj26_one_day_returns_trades() -> None:
    """AC10 — baixa 1 dia WDOJ26 real → len(trades) > 0.

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

    with ProfitDLL() as dll:
        dll.initialize_market_only(key, user, password)
        # Q-DRIFT-02: 300s — handshake MARKET_DATA pode levar >60s.
        connected = dll.wait_market_connected(timeout=300)
        assert connected, "Market data não conectou em 300s — verificar credenciais/rede."

        result = download_chunk(
            dll,
            _SMOKE_SYMBOL,
            _SMOKE_EXCHANGE,
            _SMOKE_DT_START,
            _SMOKE_DT_END,
            timeout=600,  # 10 min — generoso para Q02-E quirk
        )

        assert result.status in ("completed", "timeout"), f"status inesperado: {result.status}"
        # AC10: trades > 0.
        assert len(result.trades) > 0, (
            f"Esperado >0 trades para {_SMOKE_SYMBOL} em "
            f"{_SMOKE_DT_START.date()}; recebido 0. "
            f"status={result.status}, progress={result.progress_history[-5:]}"
        )
        # Validação adicional: timestamps em ordem cronológica BRT naive.
        if result.actual_start is not None and result.actual_end is not None:
            assert result.actual_start <= result.actual_end
        # Cada trade tem dll_version preenchida (metadata Sol).
        assert all(t.dll_version for t in result.trades)
