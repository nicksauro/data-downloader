#!/usr/bin/env python3
# ruff: noqa: N802, N803, N806, N816
"""Probe diagnostico: copia exemplo Nelogica EXATAMENTE para isolar bug.

Objetivo: rodar o caminho mais "puro" possivel de inicializacao da
ProfitDLL — usando os mesmos `WINFUNCTYPE`s, as mesmas structs e o mesmo
formato de chamada que o `main.py` oficial da Nelogica
(`profitdll/Exemplo Python/main.py`). Se este probe NAO conectar
(`bMarketConnected` permanece False, MARKET_DATA fica em result=1), o bug
NAO esta no nosso wrapper — eh ambiental (servidor, rede, horario, conta).

NOTA SOBRE NAMING (ruff noqa N8xx, E501):
  Nomes mixedCase intencionais (stateCallback, bAtivo, nType, sOpen, ...)
  e linhas longas — espelho EXATO do exemplo Nelogica. Trocar nomes
  romperia o "espelho" e introduziria divergencia que invalidaria o
  proposito do probe (isolar bug do nosso wrapper vs. caminho canonico).
  Por isso o noqa eh file-level: este script eh DESCARTAVEL/DIAGNOSTICO,
  nao codigo de producao.

Uso (PowerShell):
  $envFile = Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' }
  $envFile | ForEach-Object {
      $kv = $_ -split '=',2
      [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
  }
  $env:PYTHONIOENCODING='utf-8'
  python scripts/probe_init.py
"""

from __future__ import annotations

import os
import sys
import time
from ctypes import (
    WINFUNCTYPE,
    WinDLL,
    c_double,
    c_int,
    c_int32,
    c_wchar_p,
)
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env local
load_dotenv()


# Adiciona profitdll/Exemplo Python ao path para reusar profitTypes EXATO
EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "profitdll" / "Exemplo Python"
sys.path.insert(0, str(EXAMPLE_DIR))

from profitTypes import TAssetID  # noqa: E402  — struct EXATA do exemplo

# ---------------------------------------------------------------------------
# Variaveis de controle GLOBAIS (mesma estrutura do main.py L54-57)
# ---------------------------------------------------------------------------
bAtivo = False
bMarketConnected = False
bConnectado = False
bBrokerConnected = False


# ---------------------------------------------------------------------------
# Callbacks com SIGNATURE EXATA do exemplo Nelogica
# ---------------------------------------------------------------------------
@WINFUNCTYPE(None, c_int32, c_int32)
def stateCallback(nType, nResult):
    """Mirror EXATO de main.py:194-241."""
    global bAtivo, bMarketConnected, bConnectado, bBrokerConnected

    nConnStateType = nType
    result = nResult

    if nConnStateType == 0:  # Login
        if result == 0:
            bConnectado = True
            print("[STATE] Login: conectado", flush=True)
        else:
            bConnectado = False
            print(f"[STATE] Login: {result}", flush=True)
    elif nConnStateType == 1:  # Roteamento/Broker
        if result == 5:
            bBrokerConnected = True
            print("[STATE] Broker: Conectado.", flush=True)
        elif result > 2:
            bBrokerConnected = False
            print("[STATE] Broker: Sem conexao com corretora.", flush=True)
        else:
            bBrokerConnected = False
            print(f"[STATE] Broker: Sem conexao com servidores ({result})", flush=True)
    elif nConnStateType == 2:  # Market data
        if result == 4:
            bMarketConnected = True
            print("[STATE] Market: Conectado", flush=True)
        else:
            bMarketConnected = False
            print(f"[STATE] Market: {result}", flush=True)
    elif nConnStateType == 3:  # Ativacao
        if result == 0:
            bAtivo = True
            print("[STATE] Ativacao: OK", flush=True)
        else:
            bAtivo = False
            print(f"[STATE] Ativacao: {result}", flush=True)
    else:
        print(f"[STATE] nType={nType} result={nResult} (desconhecido)", flush=True)

    if bMarketConnected and bAtivo and bConnectado:
        print("[STATE] >>> Servicos Conectados <<<", flush=True)


@WINFUNCTYPE(None, TAssetID, c_int)
def progressCallBack(assetId, nProgress):
    print(f"[PROGRESS] {assetId.ticker} | {nProgress}", flush=True)


@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)
def tinyBookCallBack(assetId, price, qtd, side):
    side_name = "Buy" if side == 0 else "Sell"
    print(f"[TINYBOOK] {assetId.ticker} | {side_name}: {price} x {qtd}", flush=True)


# Daily callback — signature EXATA de main.py:346-348 (19 args + assetID + date)
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
def newDailyCallback(
    assetID,
    date,
    sOpen,
    sHigh,
    sLow,
    sClose,
    sVol,
    sAjuste,
    sMaxLimit,
    sMinLimit,
    sVolBuyer,
    sVolSeller,
    nQtd,
    nNegocios,
    nContratosOpen,
    nQtdBuyer,
    nQtdSeller,
    nNegBuyer,
    nNegSeller,
):
    print(
        f"[DAILY] {assetID.ticker} | {date} O={sOpen} H={sHigh} L={sLow} C={sClose}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Carregar DLL — usar caminho absoluto da pasta DLLs/Win64 do projeto
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DLL_DIR = PROJECT_ROOT / "profitdll" / "DLLs" / "Win64"
DLL_PATH = DLL_DIR / "ProfitDLL.dll"

print(f"[INIT] DLL path: {DLL_PATH}", flush=True)
print(f"[INIT] DLL exists: {DLL_PATH.exists()}", flush=True)

# IMPORTANTE: ProfitDLL precisa achar suas dependencias (libssl, libcrypto,
# *.dat files) e escrever logs no cwd. Mudar para o diretorio das DLLs
# antes de carregar — eh o que o exemplo faz implicitamente quando rodado
# a partir de "Exemplo Python/" com a DLL copiada para la.
original_cwd = os.getcwd()
os.chdir(str(DLL_DIR))
print(f"[INIT] cwd alterado para: {os.getcwd()}", flush=True)

try:
    profit_dll = WinDLL(str(DLL_PATH))
except OSError as exc:
    print(f"[INIT] FALHA ao carregar DLL: {exc}", flush=True)
    os.chdir(original_cwd)
    sys.exit(1)

print("[INIT] DLL carregada com sucesso.", flush=True)


# ---------------------------------------------------------------------------
# Credenciais
# ---------------------------------------------------------------------------
key = os.environ.get("PROFITDLL_KEY") or ""
user = os.environ.get("PROFITDLL_USER") or ""
password = os.environ.get("PROFITDLL_PASS") or ""

if not (key and user and password):
    print("[INIT] FALTAM credenciais em .env (PROFITDLL_KEY/USER/PASS).", flush=True)
    os.chdir(original_cwd)
    sys.exit(2)

print(
    f"[INIT] Credenciais: key={key[:6]}*** user={user[:4]}*** pass=***",
    flush=True,
)


# ---------------------------------------------------------------------------
# DLLInitializeMarketLogin — assinatura EXATA de main.py L742-743
# ---------------------------------------------------------------------------
# Args (11 total):
#   0: key (c_wchar_p)
#   1: user (c_wchar_p)
#   2: password (c_wchar_p)
#   3: stateCallback                   <-- crucial
#   4: None  (newTradeCallback)
#   5: newDailyCallback                <-- exemplo passa REAL
#   6: None  (newHistoryCallback)
#   7: None  (priceBookCallback)
#   8: None  (offerBookCallback)
#   9: progressCallBack                <-- exemplo passa REAL
#  10: tinyBookCallBack                <-- exemplo passa REAL
print("[INIT] Chamando DLLInitializeMarketLogin...", flush=True)
init_start = time.time()
result = profit_dll.DLLInitializeMarketLogin(
    c_wchar_p(key),
    c_wchar_p(user),
    c_wchar_p(password),
    stateCallback,
    None,
    newDailyCallback,
    None,
    None,
    None,
    progressCallBack,
    tinyBookCallBack,
)
print(
    f"[INIT] DLLInitializeMarketLogin retornou: {result} (em {time.time() - init_start:.2f}s)",
    flush=True,
)


# ---------------------------------------------------------------------------
# Aguardar conexao plena (mesma logica de main.py:wait_login com timeout)
# ---------------------------------------------------------------------------
TIMEOUT_S = 60
print(f"[WAIT] Aguardando bMarketConnected por ate {TIMEOUT_S}s...", flush=True)

wait_start = time.time()
last_log = wait_start
connected = False
while time.time() - wait_start < TIMEOUT_S:
    if bMarketConnected:
        elapsed = time.time() - wait_start
        print(f"[WAIT] >>> bMarketConnected em {elapsed:.2f}s <<<", flush=True)
        connected = True
        break
    # Heartbeat a cada 5s para visibilidade
    if time.time() - last_log >= 5.0:
        print(
            f"[WAIT] +{int(time.time() - wait_start)}s "
            f"bConnectado={bConnectado} "
            f"bMarketConnected={bMarketConnected} "
            f"bAtivo={bAtivo} "
            f"bBrokerConnected={bBrokerConnected}",
            flush=True,
        )
        last_log = time.time()
    time.sleep(0.2)

elapsed_total = time.time() - wait_start
if not connected:
    print(
        f"[WAIT] TIMEOUT {TIMEOUT_S}s. Estado final: "
        f"bConnectado={bConnectado} "
        f"bMarketConnected={bMarketConnected} "
        f"bAtivo={bAtivo} "
        f"bBrokerConnected={bBrokerConnected}",
        flush=True,
    )

# ---------------------------------------------------------------------------
# Veredicto
# ---------------------------------------------------------------------------
print("", flush=True)
print("=" * 60, flush=True)
print("VEREDICTO PROBE:", flush=True)
print(f"  init_return       = {result}", flush=True)
print(f"  bConnectado       = {bConnectado}", flush=True)
print(f"  bMarketConnected  = {bMarketConnected}", flush=True)
print(f"  bAtivo            = {bAtivo}", flush=True)
print(f"  bBrokerConnected  = {bBrokerConnected}", flush=True)
print(f"  tempo_total       = {elapsed_total:.2f}s", flush=True)
if bMarketConnected:
    print("  CENARIO_A => CONECTOU. Bug esta no NOSSO wrapper.", flush=True)
else:
    print(
        "  CENARIO_B => NAO conectou. Provavelmente AMBIENTAL (rede/horario/conta).",
        flush=True,
    )
print("=" * 60, flush=True)


# ---------------------------------------------------------------------------
# Finalize (best effort)
# ---------------------------------------------------------------------------
try:
    fin_result = profit_dll.DLLFinalize()
    print(f"[FINI] DLLFinalize retornou: {fin_result}", flush=True)
except (AttributeError, OSError) as exc:
    print(f"[FINI] DLLFinalize falhou: {exc}", flush=True)

os.chdir(original_cwd)
print("[FINI] cwd restaurado, probe finalizado.", flush=True)
