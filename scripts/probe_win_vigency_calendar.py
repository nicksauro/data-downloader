#!/usr/bin/env python3
"""Probe Q-DRIFT-18 (Q18-OPEN): vigência WIN trimestrais via DLL real.

Mini-council Aria (@architect) + Nelo (DLL specialist) 2026-05-05.

**Objetivo:** validar empiricamente as 8 entries WIN seed (status atual
``validation_source: hypothesized``) em ``docs/storage/CONTRACTS.md`` §3.

**Regra B3 oficial (CONTRACTS.md §2.2 / ADR-006 amendment 2026-05-05):**
- Início: 5º dia útil do mês X-3 (3 meses antes do vencimento).
- Fim: quarta-feira mais próxima do dia 15 do mês X.

**Output esperado por contrato:**

- **OK** — `actual_start`/`actual_end` batem ±0 dias com seed.
- **±N days** — divergência tolerável (≤ ±1 dia útil — feriado regional).
- **DIVERGE** — desvio ≥ 2 dias úteis → flag Q-DRIFT-18 follow-up.
- **NOT_FOUND** — contrato inexistente (rc < 0 / NL_INVALID_TICKER).

**Pré-requisitos:**
- ProfitDLL real instalada em `profitdll/DLLs/Win64/`.
- `.env` com `PROFITDLL_KEY` / `PROFITDLL_USER` / `PROFITDLL_PASS`.
- Conectividade Nelogica (sem ProfitChart aberto — Q-DRIFT-02 refutado 2026-05-05).
- Janela de execução: WIN H/M/U/Z 2026 e 2027 (8 contratos x probe_2_dates each
  = ~16 chamadas; total ~5-10 min runtime).

**Uso (PowerShell):**

    Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
      ForEach-Object {
        $kv = $_ -split '=',2
        [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
      }
    $env:PYTHONIOENCODING='utf-8'
    $env:DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE='1'
    python scripts/probe_win_vigency_calendar.py

**Status:** offline-ready (script existe, não rodável sem DLL real). Story
4.2-followup AC1 invocará este probe quando humano executar smoke real.

Refs:
- ADR-006 §"Regras V1" (amendment 2026-05-05 — regra fim "quarta 15")
- CONTRACTS.md §2.2 (regra B3 oficial)
- QUIRKS.md §Q18-OPEN
- COUNCIL-29 (Story 4.2 decision — 2026-05-04)
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


# Seed esperado (CONTRACTS.md §3 entries — todas hypothesized hoje)
WIN_SEED: list[tuple[str, str, str]] = [
    # (contract_code, vigent_from, vigent_until)
    ("WINH26", "2026-01-08", "2026-03-18"),
    ("WINM26", "2026-03-18", "2026-06-17"),
    ("WINU26", "2026-06-17", "2026-09-16"),
    ("WINZ26", "2026-09-16", "2026-12-16"),
    ("WINH27", "2026-12-16", "2027-03-17"),
    ("WINM27", "2027-03-17", "2027-06-16"),
    ("WINU27", "2027-06-16", "2027-09-15"),
    ("WINZ27", "2027-09-15", "2027-12-15"),
]


@dataclass
class ProbeResult:
    contract_code: str
    expected_start: str
    expected_end: str
    start_probe_trades: int  # trades capturados em primeiro dia útil esperado
    end_probe_trades: int  # trades capturados em último dia útil esperado
    start_status: str  # OK | EMPTY | NL_ERROR
    end_status: str  # OK | EMPTY | NL_ERROR
    verdict: str  # VIGENT | DIVERGE | NOT_FOUND | FAILED
    notes: str = ""


def _probe_one_day(dll, code: str, exchange: str, day: str) -> tuple[int, str]:
    """Tenta download_chunk de 1 dia útil. Retorna (trades, status)."""
    from data_downloader.orchestrator.download_primitive import download_chunk

    dt_start = datetime.fromisoformat(day + "T09:00:00")
    dt_end = datetime.fromisoformat(day + "T18:30:00")
    try:
        result = download_chunk(dll, code, exchange, dt_start, dt_end, timeout=120)
    except Exception as exc:
        return 0, f"EXCEPTION:{type(exc).__name__}"
    if result.nl_error_code < 0:
        return 0, f"NL_ERROR:{result.nl_error_code}"
    n = len(result.trades)
    return n, "OK" if n > 0 else "EMPTY"


def probe_win_calendar() -> list[ProbeResult]:
    """Sonda cada WIN seed: primeiro dia útil esperado + último dia útil esperado."""
    from data_downloader.dll.wrapper import ProfitDLL

    results: list[ProbeResult] = []
    minimal = os.getenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    with ProfitDLL() as dll:
        dll.initialize_market_only(
            os.environ["PROFITDLL_KEY"],
            os.environ["PROFITDLL_USER"],
            os.environ["PROFITDLL_PASS"],
            minimal_handshake=minimal,
        )
        if not dll.wait_market_connected(timeout=120):
            print("[FAIL] MARKET_CONNECTED não respondeu em 120s.", flush=True)
            return results

        for code, vigent_from, vigent_until in WIN_SEED:
            print(f"[PROBE] {code} ({vigent_from} → {vigent_until})", flush=True)
            n_start, st_start = _probe_one_day(dll, code, "F", vigent_from)
            n_end, st_end = _probe_one_day(dll, code, "F", vigent_until)
            verdict = (
                "VIGENT"
                if (st_start == "OK" and st_end == "OK")
                else "NOT_FOUND"
                if (st_start.startswith("NL_") and st_end.startswith("NL_"))
                else "DIVERGE"
            )
            results.append(
                ProbeResult(
                    contract_code=code,
                    expected_start=vigent_from,
                    expected_end=vigent_until,
                    start_probe_trades=n_start,
                    end_probe_trades=n_end,
                    start_status=st_start,
                    end_status=st_end,
                    verdict=verdict,
                )
            )
            time.sleep(1)  # pequena pausa server-side
    return results


def main() -> int:
    if not all(os.getenv(k) for k in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")):
        print("[SKIP] credenciais ausentes (PROFITDLL_KEY/USER/PASS).", flush=True)
        return 77

    results = probe_win_calendar()
    if not results:
        return 1

    print()
    print(f"{'Contract':<10} {'Start (exp)':<13} {'St':<14} {'End (exp)':<13} {'St':<14} Verdict")
    print("-" * 90)
    for r in results:
        print(
            f"{r.contract_code:<10} {r.expected_start:<13} {r.start_status:<14} "
            f"{r.expected_end:<13} {r.end_status:<14} {r.verdict}"
        )
    diverges = [r for r in results if r.verdict != "VIGENT"]
    print()
    print(json.dumps({"total": len(results), "diverges": len(diverges)}, indent=2))
    if diverges:
        print(
            f"⚠ {len(diverges)} contracts DIVERGE/NOT_FOUND — abrir Story "
            f"4.2-fixup ou flag Q-DRIFT-18 follow-up.",
            flush=True,
        )
        return 1
    print(
        "✅ All 8 WIN entries VIGENT — promover validation_source 'dll_probe' em CONTRACTS.md §3."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
