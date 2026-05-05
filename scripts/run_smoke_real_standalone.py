#!/usr/bin/env python3
"""Reproduz tests/smoke/test_download_primitive_real.py SEM pytest.

Story 1.7d — attempt 11 fast-path bisection.

Propósito: isolar se o bug está no harness pytest (qualquer plugin/hook/
config residual mesmo com PYTEST_DISABLE_PLUGIN_AUTOLOAD + --confcutdir)
ou no fluxo do test em si (subscribe/callback/download).

Reproduz o fluxo EXATO de
``tests/smoke/test_download_primitive_real.py::test_download_chunk_real_wdoj26_one_day_returns_trades``
sem invocar pytest:
  1. carrega .env via python-dotenv
  2. checa skipif de credenciais
  3. instancia ProfitDLL
  4. initialize_market_only(minimal_handshake=True)
  5. wait_market_connected(timeout=300) — mesmo timeout do test
  6. download_chunk(dll, WDOJ26, F, 2026-04-15 09:00 → 17:30, timeout=600)
  7. asserts equivalentes ao test (status, trades > 0, timestamps,
     dll_version)

Verdicts:
- PASS (conectou + trades > 0): bug é exclusivamente do harness pytest
  (algum hook/plugin/config residual que --confcutdir não desativa).
- FAIL-connect-timeout: bug NÃO é só pytest — wrapper class trava
  mesmo standalone com fluxo idêntico ao test (refuta hypotheses
  anteriores que diziam "wrapper standalone funciona em 2.21s").
- FAIL-download: handshake OK, mas download_chunk falha
  (bug em subscribe_ticker/set_history_callback/download_chunk).

Uso (PowerShell):
  Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
    ForEach-Object {
      $kv = $_ -split '=',2
      [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
    }
  $env:PYTHONIOENCODING='utf-8'
  $env:DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE='1'
  python scripts/run_smoke_real_standalone.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

# Imports EXATAMENTE como o test faz.
from data_downloader.dll.wrapper import ProfitDLL  # noqa: E402
from data_downloader.orchestrator.download_primitive import download_chunk  # noqa: E402

# Espelho EXATO do test (linhas 39-42), com data DINAMICA para Q-DRIFT-26.
# Janela curta de pregao recente: agora-2h até agora-10min (margem seguranca).
_SMOKE_SYMBOL = "WDOJ26"
_SMOKE_EXCHANGE = "F"
_SMOKE_DT_START = datetime.now() - timedelta(hours=2)
_SMOKE_DT_END = datetime.now() - timedelta(minutes=10)


def main() -> int:
    print(f"[INFO] Python {sys.version.split()[0]} ({sys.platform})", flush=True)
    print(f"[INFO] CWD: {Path.cwd()}", flush=True)
    print(f"[INFO] sys.argv: {sys.argv}", flush=True)

    # Replica skipif do test.
    required = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
    if not all(os.getenv(k) for k in required):
        print("[SKIP] credenciais ausentes — set PROFITDLL_KEY/USER/PASS.", flush=True)
        return 77  # convencional para SKIP

    key = os.environ["PROFITDLL_KEY"]
    user = os.environ["PROFITDLL_USER"]
    password = os.environ["PROFITDLL_PASS"]

    minimal_handshake = os.getenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    print(f"[INFO] minimal_handshake = {minimal_handshake}", flush=True)

    verdict = "ERROR"
    t0 = time.time()
    connect_elapsed = -1.0
    download_elapsed = -1.0
    n_trades = -1

    try:
        with ProfitDLL() as dll:
            print("[STEP] initialize_market_only...", flush=True)
            t_init = time.time()
            dll.initialize_market_only(key, user, password, minimal_handshake=minimal_handshake)
            init_elapsed = time.time() - t_init
            print(f"[OK] init em {init_elapsed:.2f}s", flush=True)

            print("[STEP] wait_market_connected(timeout=300)...", flush=True)
            t_wait = time.time()
            connected = dll.wait_market_connected(timeout=300)
            connect_elapsed = time.time() - t_wait
            print(
                f"[{'OK' if connected else 'FAIL'}] wait_market_connected="
                f"{connected} em {connect_elapsed:.2f}s",
                flush=True,
            )

            if not connected:
                print(
                    "[VERDICT] FAIL-connect-timeout — bug NAO eh apenas pytest "
                    "harness. Wrapper trava mesmo standalone com fluxo "
                    "identico ao test.",
                    flush=True,
                )
                verdict = "FAIL-connect-timeout"
                return 1

            print(
                f"[STEP] download_chunk({_SMOKE_SYMBOL}, {_SMOKE_EXCHANGE}, "
                f"{_SMOKE_DT_START} -> {_SMOKE_DT_END}, timeout=600)...",
                flush=True,
            )
            t_dl = time.time()
            result = download_chunk(
                dll,
                _SMOKE_SYMBOL,
                _SMOKE_EXCHANGE,
                _SMOKE_DT_START,
                _SMOKE_DT_END,
                timeout=600,
            )
            download_elapsed = time.time() - t_dl
            n_trades = len(result.trades)
            print(
                f"[OK] download_chunk: status={result.status} "
                f"trades={n_trades} em {download_elapsed:.2f}s",
                flush=True,
            )

            # Asserts equivalentes ao test (linhas 98-109).
            if result.status not in ("completed", "timeout"):
                print(
                    f"[FAIL] status inesperado: {result.status}",
                    flush=True,
                )
                verdict = "FAIL-download-status"
                return 2

            if n_trades == 0:
                print(
                    f"[FAIL] esperado >0 trades; recebido 0. "
                    f"status={result.status} "
                    f"progress={result.progress_history[-5:]}",
                    flush=True,
                )
                verdict = "FAIL-download-zero-trades"
                return 3

            if (
                result.actual_start is not None
                and result.actual_end is not None
                and result.actual_start > result.actual_end
            ):
                print("[FAIL] actual_start > actual_end", flush=True)
                verdict = "FAIL-timestamps-out-of-order"
                return 4

            if not all(t.dll_version for t in result.trades):
                print("[FAIL] alguns trades sem dll_version", flush=True)
                verdict = "FAIL-missing-dll-version"
                return 5

            print(
                f"[VERDICT] PASS — bug eh exclusivamente do harness pytest. "
                f"connect={connect_elapsed:.2f}s "
                f"download={download_elapsed:.2f}s "
                f"trades={n_trades}",
                flush=True,
            )
            verdict = "PASS"
            return 0

    except Exception as exc:
        print(
            f"[FAIL] {type(exc).__name__}: {exc}",
            flush=True,
        )
        import traceback

        traceback.print_exc()
        verdict = "ERROR-exception"
        return 99
    finally:
        total = time.time() - t0
        print(
            f"[SUMMARY] verdict={verdict} total={total:.2f}s "
            f"connect={connect_elapsed:.2f}s download={download_elapsed:.2f}s "
            f"trades={n_trades}",
            flush=True,
        )


if __name__ == "__main__":
    sys.exit(main())
