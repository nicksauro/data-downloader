#!/usr/bin/env python3
"""Probe usando classe ProfitDLL diretamente (standalone, sem pytest).

Story 1.7d — Experimento decisivo: isolar pytest harness vs wrapper class.

Probe minimal `scripts/probe_init.py` (script ctypes standalone) conecta em
~1.62s. Smoke pytest com `minimal_handshake=True` (espelho ESTRITO do probe)
trava 600s em result=1. Q-DRIFT-13/14/16 REFUTADAS. Auditorias Nelo+Aria
nao acharam diferenca de signature/threading/lifetime. Aria observou:
callback recebe 150x `(2, 1)` — handshake ESTA chegando, servidor nao
promove a `(2, 4)`.

Diferenca ainda nao isolada: probe e script Python standalone; smoke roda
DENTRO de pytest (com plugins, capsys, hooks, structlog config diferente).

Este probe usa a classe `ProfitDLL` da nossa codebase (initialize_market_only
+ wait_market_connected) FORA de pytest:
  - CENARIO_A (conectou em <60s): bug esta no harness pytest, NAO no wrapper.
  - CENARIO_B (timeout/erro): bug esta no wrapper class mesmo (nao pytest).

Instrumentacao adicional:
  - Q-DRIFT-15: argtypes/restype de DLLInitializeMarketLogin antes/depois init.
  - Q-DRIFT-17: hash sha256 da DLL e path absoluto.
  - Thread name antes do init.

Uso (PowerShell):
  Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
    ForEach-Object {
      $kv = $_ -split '=',2
      [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
    }
  $env:PYTHONIOENCODING='utf-8'
  python scripts/probe_wrapper_minimal.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from data_downloader.dll.wrapper import ProfitDLL  # noqa: E402

DLL_PATH = ROOT / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll"

# Q-DRIFT-17 instrumentation: hash + path absoluto
print(
    f"[INFO] DLL hash (sha256[:16]): " f"{hashlib.sha256(DLL_PATH.read_bytes()).hexdigest()[:16]}",
    flush=True,
)
print(f"[INFO] DLL path absoluto: {DLL_PATH.resolve()}", flush=True)
print(f"[INFO] DLL existe: {DLL_PATH.exists()}", flush=True)
print(f"[INFO] Thread atual: {threading.current_thread().name}", flush=True)
print(f"[INFO] Python: {sys.version.split()[0]} ({sys.platform})", flush=True)
print(f"[INFO] CWD inicial: {Path.cwd()}", flush=True)

key = os.environ.get("PROFITDLL_KEY") or ""
user = os.environ.get("PROFITDLL_USER") or ""
password = os.environ.get("PROFITDLL_PASS") or ""

if not (key and user and password):
    print("[FAIL] FALTAM credenciais em .env (PROFITDLL_KEY/USER/PASS).", flush=True)
    print(
        "CENARIO_ERROR => credenciais ausentes. Configure .env e tente novamente.",
        flush=True,
    )
    sys.exit(2)

print(
    f"[INFO] Credenciais carregadas (user={user[:2]}***, "
    f"key_len={len(key)}, pass_len={len(password)})",
    flush=True,
)

dll = ProfitDLL(dll_path=DLL_PATH)

verdict = "ERROR"
elapsed_total = -1.0

try:
    print(
        "[STEP] Chamando initialize_market_only(minimal_handshake=True, "
        "register_extra_callbacks=False)...",
        flush=True,
    )
    t0 = time.time()
    dll.initialize_market_only(
        key,
        user,
        password,
        register_extra_callbacks=False,
        minimal_handshake=True,
    )
    init_elapsed = time.time() - t0

    # Q-DRIFT-15 instrumentation: argtypes/restype POS-init
    init_func = dll._dll.DLLInitializeMarketLogin
    print(f"[Q-DRIFT-15] argtypes pos-init: {init_func.argtypes}", flush=True)
    print(f"[Q-DRIFT-15] restype  pos-init: {init_func.restype}", flush=True)
    print(f"[INFO] CWD pos-init: {Path.cwd()}", flush=True)
    print(f"[OK] init OK em {init_elapsed:.2f}s. Aguardando MARKET_CONNECTED...", flush=True)

    t1 = time.time()
    connected = dll.wait_market_connected(timeout=60, retry_attempts=1)
    wait_elapsed = time.time() - t1
    elapsed_total = time.time() - t0

    if connected:
        print(
            f"[OK] >>> MARKET_CONNECTED em {wait_elapsed:.2f}s "
            f"(total init+wait: {elapsed_total:.2f}s) <<<",
            flush=True,
        )
        print(
            "CENARIO_A => CONECTOU. Bug NAO esta no wrapper class — " "esta no pytest harness.",
            flush=True,
        )
        verdict = "CENARIO_A"
    else:
        print(
            f"[FAIL] wait_market_connected retornou False apos {wait_elapsed:.2f}s.",
            flush=True,
        )
        print(
            "CENARIO_B => NAO conectou. Bug ESTA no wrapper class (nao pytest).",
            flush=True,
        )
        verdict = "CENARIO_B"
except Exception as exc:
    print(f"[FAIL] {type(exc).__name__}: {exc}", flush=True)
    print(
        "CENARIO_B => NAO conectou (excecao). Bug ESTA no wrapper class (nao pytest).",
        flush=True,
    )
    verdict = "CENARIO_B"
finally:
    try:
        dll.finalize()
        print("[INFO] finalize OK.", flush=True)
    except Exception as exc:
        print(f"[WARN] finalize falhou: {type(exc).__name__}: {exc}", flush=True)

print(f"[VERDICT] {verdict}", flush=True)
sys.exit(0 if verdict == "CENARIO_A" else 1)
