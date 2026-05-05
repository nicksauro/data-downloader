#!/usr/bin/env python3
"""Probe MINIMAL ctypes puro — reproduz fluxo de download HISTORICO espelhando
exemplo oficial Nelogica (C++ main.cpp + Python main.py + PROFITDLL_KNOWLEDGE.md
secao 2.7).

Story 1.7d — experimento decisivo final.

Objetivo: SEM nossa wrapper, SEM nosso orchestrator, SEM pytest. Apenas ctypes
puro reproduzindo a sequencia que o exemplo oficial usa para download
historico de trades.

Fluxo (referencia: PROFITDLL_KNOWLEDGE.md §2.7 + C++ main.cpp:875-892):

    1. WinDLL(ProfitDLL.dll) com cwd = pasta da DLL (Q-DRIFT-10)
    2. SetEnabledLogToDebug(0) ANTES do init
    3. DLLInitializeMarketLogin(key, user, password,
           state_cb,             # slot 4 — ATIVO
           NoopCallback,         # slot 5 — newDailyCallback (signature exata)
           NoopCallback,         # slot 6 — newHistoryCallback V1 (signature exata)
           NoopCallback,         # slot 7 — priceBookCallback (signature exata)
           NoopCallback,         # slot 8 — offerBookCallback (signature exata)
           NoopCallback,         # slot 9 — progressCallback
           NoopCallback,         # slot 10 — tinyBookCallback
       )
    4. wait MARKET_CONNECTED (state callback nType=2, nResult=4) ate 60s
    5. SetHistoryTradeCallbackV2(history_v2_cb) — callback V2 = nosso target
    6. SubscribeTicker(WDOFUT, F) — pre-requisito Q-DRIFT-07
    7. GetHistoryTrades(WDOFUT, F, "dd/MM/yyyy HH:MM:SS", ...) janela <= 5 dias
    8. Aguardar trades por ate 120s
    9. Verdict: A (trades>0 — bug nosso) ou B (zero trades — bug externo)

NOTA SOBRE FORMATO DE DATA: O exemplo C++ usa apenas data ("12/01/2021"
"13/01/2021") — sem hora. Vou reproduzir EXATAMENTE esse formato para
maximizar fidelidade ao exemplo. Nosso codigo usa "dd/MM/yyyy HH:mm:ss"
mas se o probe minimal funcionar com formato curto, isso ja sinaliza algo.

Saida: linhas com prefixos [STATE] [INIT] [SUB] [REQ] [HIST] [WAIT] [FINAL]
[VERDICT]. Linha final: CENARIO_A ou CENARIO_B.
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

# Importar APENAS structs do exemplo oficial (sem nossa wrapper).
from profitTypes import TAssetID, TConnectorAssetIdentifier, TConnectorTrade  # noqa: E402

# ====================================================================
# Estado global (acessado pelos callbacks)
# ====================================================================
state_market_connected = False
state_login_ok = False
state_ativo = False
trades_received = 0
last_packet_seen = False
first_trade_at: float | None = None
state_log: list[tuple[float, int, int]] = []


# ====================================================================
# Callbacks (signatures EXATAS do exemplo Nelogica)
# ====================================================================


# ---------- State callback (slot 4 do init) ----------
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


# ---------- Slot 5: newDailyCallback (Python main.py L346-351) ----------
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


# ---------- Slot 6: newHistoryCallback V1 (C++ main.cpp:194 + Delphi) ----------
# Signature: (assetId: TAssetID, date: wchar_p, tradeNumber: uint, price: double,
#             vol: double, qtd: int, buyAgent: int, sellAgent: int, tradeType: int)
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
    # NOTA: V1 callback do init slot 6. Nao incrementamos aqui — usaremos V2.
    pass


# ---------- Slot 7: priceBookCallback ----------
# C++ main.cpp:224 — (assetId, nAction, nPosition, Side, nQtd, nCount,
#                     sPrice, pArraySell*, pArrayBuy*)
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


# ---------- Slot 8: offerBookCallback (V1, NAO V2) ----------
# C++ main.cpp:291 — (assetId, nAction, nPosition, Side, nQtd, nAgent, nOfferID,
#                     dPrice, bHasPrice, bHasQtd, bHasDate, bHasOfferID, bHasAgent,
#                     date, pArraySell*, pArrayBuy*)
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


# ---------- Slot 9: progressCallback ----------
# C++ main.cpp:370 — (assetId: TAssetID, nProgress: int)
@WINFUNCTYPE(None, TAssetID, c_int)
def progressCallbackNoop(assetId, nProgress):  # noqa: N802 N803
    print(f"[PROG] {nProgress}%", flush=True)


# ---------- Slot 10: tinyBookCallback ----------
# C++ main.cpp:375 — (assetId, price, qtd, side)
@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)
def tinyBookCallbackNoop(*args):  # noqa: N802
    pass


# ---------- HistoryTradeCallback V2 (target real do nosso teste) ----------
# Manual §3.2 L1912 + PROFITDLL_KNOWLEDGE.md §3.1 L249:
# usa TConnectorTradeCallback: (asset: TConnectorAssetIdentifier,
#                               pTrade: c_size_t, flags: c_uint)
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


# ====================================================================
# Main
# ====================================================================


def main() -> int:
    print(f"[INFO] Python {sys.version.split()[0]} ({sys.platform})", flush=True)

    required = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
    if not all(os.getenv(k) for k in required):
        print("[SKIP] credenciais ausentes — set PROFITDLL_KEY/USER/PASS.", flush=True)
        return 77

    key = os.environ["PROFITDLL_KEY"]
    user = os.environ["PROFITDLL_USER"]
    password = os.environ["PROFITDLL_PASS"]

    # ----- Setup paths e cwd (Q-DRIFT-10) -----
    dll_path = ROOT / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll"
    if not dll_path.exists():
        print(f"[FAIL] DLL nao encontrada: {dll_path}", flush=True)
        return 99

    original_cwd = Path.cwd()
    os.chdir(dll_path.parent)
    print(f"[INFO] cwd: {Path.cwd()}", flush=True)
    print(f"[INFO] dll: {dll_path}", flush=True)

    profit_dll = WinDLL(str(dll_path))

    # ----- Argtypes/restypes minimos (Q-DRIFT-08) -----
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

    # ----- Silenciar log da DLL ANTES do init (AC11) -----
    log_ret = profit_dll.SetEnabledLogToDebug(0)
    print(f"[INFO] SetEnabledLogToDebug(0) ret={log_ret}", flush=True)

    # ----- Init com TODOS os 11 slots preenchidos (Q-DRIFT-05) -----
    print("[STEP] DLLInitializeMarketLogin...", flush=True)
    t_init = time.time()
    init_ret = profit_dll.DLLInitializeMarketLogin(
        c_wchar_p(key),
        c_wchar_p(user),
        c_wchar_p(password),
        stateCallback,  # slot 4 — state ATIVO
        newDailyCallbackNoop,  # slot 5 — newDailyCallback
        newHistoryCallbackV1Noop,  # slot 6 — newHistoryCallback V1 (Noop, vamos usar V2)
        priceBookCallbackNoop,  # slot 7 — priceBookCallback
        offerBookCallbackNoop,  # slot 8 — offerBookCallback
        progressCallbackNoop,  # slot 9 — progressCallback (loga %)
        tinyBookCallbackNoop,  # slot 10 — tinyBookCallback
    )
    init_elapsed = time.time() - t_init
    print(f"[INIT] ret={init_ret} elapsed={init_elapsed:.2f}s", flush=True)

    if init_ret < 0:
        print(f"[FAIL] DLLInitializeMarketLogin retornou {init_ret}", flush=True)
        os.chdir(original_cwd)
        return 1

    # ----- Aguardar MARKET_CONNECTED ate 60s -----
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

    # ----- Setar HistoryTradeCallbackV2 DEPOIS de connected -----
    # (PROFITDLL_KNOWLEDGE.md §2.7 sugere subscribe antes de set callback,
    #  mas ordem real do exemplo C++ tem set callbacks na init e subscribe
    #  depois. Para V2 precisamos chamar Set explicitamente.)
    print("[STEP] SetHistoryTradeCallbackV2...", flush=True)
    set_cb_ret = profit_dll.SetHistoryTradeCallbackV2(historyTradeCallbackV2)
    print(f"[CB] SetHistoryTradeCallbackV2 ret={set_cb_ret}", flush=True)

    # ----- SubscribeTicker WDOFUT / F (Q-DRIFT-07) -----
    # Story 1.7d (correção 2026-05-04): usuário corrigiu — WDOFUT (continuous
    # future) funciona; não é necessário contrato específico WDOJ26/WDOK26.
    ticker = "WDOFUT"
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

    # Pequeno delay para subscribe propagar (mesmo padrao do nosso codigo)
    time.sleep(2.0)

    # ----- GetHistoryTrades — janela MAX 5 dias (Q-DRIFT-31) -----
    # Story 1.7d (correção 2026-05-04): usuário corrigiu — limite de janela
    # do GetHistoryTrades é ~5 dias (chunker.py:56 e QUIRKS.md:310 já indicam
    # WDO=5 dias úteis). Sintoma B (zero trades) provavelmente era janela
    # muito grande (não falta de permissão BMF).
    # C++ main.cpp:877 usa janela de 2 dias ("12/01/2021" -> "13/01/2021"),
    # apenas data sem hora. Aqui usamos 4 dias para margem.
    end = datetime.now() - timedelta(minutes=10)
    start = end - timedelta(days=4)

    # Formato COM hora (formato que nosso codigo usa)
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

    # ----- Aguardar trades por ate 120s -----
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

    # ----- Cleanup -----
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

    # ----- Verdict -----
    if trades_received > 0:
        print(
            f"[VERDICT] CENARIO_A => trades chegaram ({trades_received}). "
            f"Bug e no NOSSO wrapper/orchestrator.",
            flush=True,
        )
        return 0
    else:
        print(
            "[VERDICT] CENARIO_B => zero trades. Bug e EXTERNO "
            "(conta/exchange/contrato/permissao).",
            flush=True,
        )
        return 10


if __name__ == "__main__":
    sys.exit(main())
