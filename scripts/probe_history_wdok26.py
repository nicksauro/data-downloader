#!/usr/bin/env python3
"""Probe MINIMAL ctypes puro — variante WDOK26 (maio/2026 — vigente em 2026-05-05).

Story 1.7d — sanity check: discriminar H1 (conta sem permissao) vs H4
(contrato WDOJ26 vencido). Se WDOK26 retorna trades > 0 enquanto WDOJ26
nao retorna, H4 confirmada — fix trivial e usar contrato vigente.

Espelha probe_history_minimal.py exatamente, trocando apenas:
  - ticker: WDOJ26 -> WDOK26
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    WinDLL,
    c_double,
    c_int,
    c_int32,
    c_int64,
    c_size_t,
    c_ubyte,
    c_uint,
    c_wchar_p,
)
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "profitdll" / "Exemplo Python"
sys.path.insert(0, str(EXAMPLE_DIR))
load_dotenv(ROOT / ".env")

from profitTypes import TAssetID, TConnectorAssetIdentifier, TConnectorTrade  # noqa: E402

state_market_connected = False
state_login_ok = False
state_ativo = False
trades_received = 0
last_packet_seen = False
first_trade_at: float | None = None
state_log: list[tuple[float, int, int]] = []


@WINFUNCTYPE(None, c_int32, c_int32)
def stateCallback(nType, nResult):  # noqa: N802 N803
    global state_market_connected, state_login_ok, state_ativo
    state_log.append((time.time(), int(nType), int(nResult)))
    if nType == 0:
        if nResult == 0:
            state_login_ok = True
            print("[STATE] LOGIN_OK", flush=True)
        else:
            print(f"[STATE] LOGIN_RESULT={nResult}", flush=True)
    elif nType == 2:
        if nResult == 4:
            state_market_connected = True
            print("[STATE] MARKET_CONNECTED", flush=True)
        else:
            print(f"[STATE] MARKET_RESULT={nResult}", flush=True)
    elif nType == 3:
        if nResult == 0:
            state_ativo = True
            print("[STATE] ATIVO", flush=True)
        else:
            print(f"[STATE] ATIVACAO_RESULT={nResult}", flush=True)
    else:
        print(f"[STATE] type={nType} result={nResult}", flush=True)


@WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
)
def newDailyCallbackNoop(*args):  # noqa: N802
    pass


@WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,
    c_uint,
    c_double,
    c_double,
    c_int,
    c_int,
    c_int,
    c_int,
)
def newHistoryCallbackV1Noop(*args):  # noqa: N802
    pass


@WINFUNCTYPE(
    None,
    TAssetID,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_double,
    POINTER(c_ubyte),
    POINTER(c_ubyte),
)
def priceBookCallbackNoop(*args):  # noqa: N802
    pass


@WINFUNCTYPE(
    None,
    TAssetID,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int64,
    c_double,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_wchar_p,
    POINTER(c_ubyte),
    POINTER(c_ubyte),
)
def offerBookCallbackNoop(*args):  # noqa: N802
    pass


@WINFUNCTYPE(None, TAssetID, c_int)
def progressCallbackNoop(assetId, nProgress):  # noqa: N802 N803
    print(f"[PROG] {nProgress}%", flush=True)


@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)
def tinyBookCallbackNoop(*args):  # noqa: N802
    pass


TC_LAST_PACKET = 0x00000002


@WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)
def historyTradeCallbackV2(assetId, pTrade, flags):  # noqa: N802 N803
    global trades_received, last_packet_seen, first_trade_at
    trades_received += 1
    if first_trade_at is None:
        first_trade_at = time.time()
        print(
            f"[HIST] FIRST trade at {first_trade_at:.2f} flags={flags}",
            flush=True,
        )
    if flags & TC_LAST_PACKET:
        last_packet_seen = True
        print(f"[HIST] LAST_PACKET (trades={trades_received})", flush=True)
    if trades_received % 100 == 0:
        print(f"[HIST] {trades_received} trades flags={flags}", flush=True)


def main() -> int:
    print(f"[INFO] Python {sys.version.split()[0]} ({sys.platform})", flush=True)
    print("[INFO] PROBE WDOK26 (maio/2026, vigente) — sanity check H4", flush=True)

    required = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
    if not all(os.getenv(k) for k in required):
        print("[SKIP] credenciais ausentes — set PROFITDLL_KEY/USER/PASS.", flush=True)
        return 77

    key = os.environ["PROFITDLL_KEY"]
    user = os.environ["PROFITDLL_USER"]
    password = os.environ["PROFITDLL_PASS"]

    dll_path = ROOT / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll"
    if not dll_path.exists():
        print(f"[FAIL] DLL nao encontrada: {dll_path}", flush=True)
        return 99

    original_cwd = Path.cwd()
    os.chdir(dll_path.parent)
    print(f"[INFO] cwd: {Path.cwd()}", flush=True)
    print(f"[INFO] dll: {dll_path}", flush=True)

    profit_dll = WinDLL(str(dll_path))

    profit_dll.DLLInitializeMarketLogin.restype = c_int
    profit_dll.DLLFinalize.restype = c_int

    profit_dll.SetEnabledLogToDebug.argtypes = [c_int]
    profit_dll.SetEnabledLogToDebug.restype = c_int

    profit_dll.SetHistoryTradeCallbackV2.restype = c_int

    profit_dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
    profit_dll.SubscribeTicker.restype = c_int
    profit_dll.UnsubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
    profit_dll.UnsubscribeTicker.restype = c_int

    profit_dll.GetHistoryTrades.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]
    profit_dll.GetHistoryTrades.restype = c_int

    profit_dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]
    profit_dll.TranslateTrade.restype = c_int

    log_ret = profit_dll.SetEnabledLogToDebug(0)
    print(f"[INFO] SetEnabledLogToDebug(0) ret={log_ret}", flush=True)

    print("[STEP] DLLInitializeMarketLogin...", flush=True)
    t_init = time.time()
    init_ret = profit_dll.DLLInitializeMarketLogin(
        c_wchar_p(key),
        c_wchar_p(user),
        c_wchar_p(password),
        stateCallback,
        newDailyCallbackNoop,
        newHistoryCallbackV1Noop,
        priceBookCallbackNoop,
        offerBookCallbackNoop,
        progressCallbackNoop,
        tinyBookCallbackNoop,
    )
    init_elapsed = time.time() - t_init
    print(f"[INIT] ret={init_ret} elapsed={init_elapsed:.2f}s", flush=True)

    if init_ret < 0:
        print(f"[FAIL] DLLInitializeMarketLogin retornou {init_ret}", flush=True)
        os.chdir(original_cwd)
        return 1

    print("[STEP] aguardando MARKET_CONNECTED...", flush=True)
    t0 = time.time()
    while time.time() - t0 < 60:
        if state_market_connected:
            elapsed = time.time() - t0
            print(f"[OK] connected em {elapsed:.2f}s", flush=True)
            break
        time.sleep(0.2)
    else:
        print("[FAIL] timeout aguardando MARKET_CONNECTED", flush=True)
        with contextlib.suppress(Exception):
            profit_dll.DLLFinalize()
        os.chdir(original_cwd)
        return 2

    time_to_market_connected = time.time() - t0

    print("[STEP] SetHistoryTradeCallbackV2...", flush=True)
    set_cb_ret = profit_dll.SetHistoryTradeCallbackV2(historyTradeCallbackV2)
    print(f"[CB] SetHistoryTradeCallbackV2 ret={set_cb_ret}", flush=True)

    # ----- DIFF vs probe_history_minimal.py: WDOK26 (maio/2026 vigente) -----
    ticker = "WDOK26"
    exchange = "F"
    print(f"[STEP] SubscribeTicker({ticker}, {exchange})...", flush=True)
    sub_ret = profit_dll.SubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
    print(f"[SUB] {ticker}/{exchange} ret={sub_ret}", flush=True)

    if sub_ret < 0:
        print(f"[FAIL] SubscribeTicker retornou {sub_ret}", flush=True)
        with contextlib.suppress(Exception):
            profit_dll.DLLFinalize()
        os.chdir(original_cwd)
        return 3

    time.sleep(2.0)

    end = datetime.now() - timedelta(minutes=10)
    start = end - timedelta(hours=2)
    start_str = start.strftime("%d/%m/%Y %H:%M:%S")
    end_str = end.strftime("%d/%m/%Y %H:%M:%S")

    print(f"[REQ] GetHistoryTrades {ticker} '{start_str}' -> '{end_str}'", flush=True)
    t_req = time.time()
    hist_ret = profit_dll.GetHistoryTrades(
        c_wchar_p(ticker),
        c_wchar_p(exchange),
        c_wchar_p(start_str),
        c_wchar_p(end_str),
    )
    print(f"[REQ] GetHistoryTrades ret={hist_ret} elapsed={time.time()-t_req:.2f}s", flush=True)

    if hist_ret < 0:
        print(f"[FAIL] GetHistoryTrades retornou {hist_ret}", flush=True)
        with contextlib.suppress(Exception):
            profit_dll.UnsubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
        with contextlib.suppress(Exception):
            profit_dll.DLLFinalize()
        os.chdir(original_cwd)
        return 4

    print("[STEP] aguardando trades (timeout 120s)...", flush=True)
    t_wait = time.time()
    last_log = t_wait
    while time.time() - t_wait < 120:
        if last_packet_seen:
            print("[OK] LAST_PACKET visto", flush=True)
            break
        if time.time() - last_log >= 10:
            print(
                f"[WAIT] +{int(time.time()-t_wait)}s trades={trades_received}",
                flush=True,
            )
            last_log = time.time()
        time.sleep(0.5)

    wait_elapsed = time.time() - t_wait
    print(
        f"[FINAL] trades_received={trades_received} "
        f"last_packet={last_packet_seen} wait={wait_elapsed:.2f}s",
        flush=True,
    )
    print(
        f"[FINAL] time_to_market_connected={time_to_market_connected:.2f}s",
        flush=True,
    )

    try:
        unsub_ret = profit_dll.UnsubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
        print(f"[CLEANUP] UnsubscribeTicker ret={unsub_ret}", flush=True)
    except Exception as exc:
        print(f"[CLEANUP] UnsubscribeTicker erro: {exc}", flush=True)

    try:
        fin_ret = profit_dll.DLLFinalize()
        print(f"[CLEANUP] DLLFinalize ret={fin_ret}", flush=True)
    except Exception as exc:
        print(f"[CLEANUP] DLLFinalize erro: {exc}", flush=True)

    os.chdir(original_cwd)

    if trades_received > 0:
        print(
            f"[VERDICT] WDOK26_OK => trades={trades_received}. "
            f"Contrato vigente funciona — H4 CONFIRMADA (WDOJ26 vencido).",
            flush=True,
        )
        return 0
    else:
        print(
            "[VERDICT] WDOK26_ZERO => zero trades em WDOK26 tambem. "
            "Bug nao e contrato vencido — checar PETR4 para H1.",
            flush=True,
        )
        return 10


if __name__ == "__main__":
    sys.exit(main())
