#!/usr/bin/env python3
"""Probe Q17-CLOSED: licença multi-process Nelogica (resolvido 2026-05-05).

✅ STATUS: Q17-CLOSED — Hipótese B confirmada por Pichau em 2026-05-05.
Licença Nelogica é **single-session** por chave; segundo init na mesma máquina
falha. Veredito empírico humano (autoridade ownership) substituiu necessidade
de rodar este probe.

Política arquitetural resultante: **ADR-022 Single-Session Sequential Download**
(`docs/adr/ADR-022-single-session-sequential-policy.md`). ADR-015 (broker
multi-process) foi REVOKED. Sub-package `src/data_downloader/orchestrator/broker/`
marcado DEAD-CODE.

Este script permanece como ferramenta diagnóstica histórica + sanity-check
caso a Nelogica mude política comercial no futuro (improvável). Para rodar
o probe (verificação periódica): credenciais reais em `.env`, comando único
`python scripts/probe_multi_process_license.py --n 2 --stagger 1.0`.
Esperado HOJE: B-PARTIAL (segundo worker falha).

Hipóteses testadas (mantidas para referência):
- A: licença per-machine — todos os N processos conectam (ALL_CONNECTED).
- B: licença single-session — segundo processo falha. **CONFIRMADA 2026-05-05.**
- C: degradação — todos conectam, mas timing dos posteriores aumenta
  significativamente (server-side rate limit por chave).

Uso (PowerShell):
  Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } |
    ForEach-Object {
      $kv = $_ -split '=',2
      [Environment]::SetEnvironmentVariable($kv[0], $kv[1])
    }
  $env:PYTHONIOENCODING='utf-8'
  $env:DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE='1'
  python scripts/probe_multi_process_license.py --n 2 --stagger 1.0

Design (ADR-015 / COUNCIL-25 / Q17-OPEN):
- Subprocess pattern (não threads) — espelho do que Story 4.1 broker faria.
- `--stagger`: offset entre starts; útil para distinguir Hipótese B (segundo
  falha imediato) de Hipótese C (segundo conecta mas mais devagar).
- Cada worker imprime UMA linha JSON em stdout com resultado estruturado.
- Workers usam `minimal_handshake=True` (caminho release-blocker validado
  em 1.7g — sem risk de regressão NL_NOT_FOUND etc).
- Sem download_chunk: probe NÃO consome dado, apenas valida `connect`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

WORKER_CODE = r"""
import json, os, sys, time
sys.path.insert(0, r"{src}")
from data_downloader.dll.wrapper import ProfitDLL  # noqa: E402

start = time.time()
result = {{
    "pid": os.getpid(),
    "connected": False,
    "init_elapsed": -1.0,
    "wait_elapsed": -1.0,
    "error_type": None,
    "error_msg": None,
}}
try:
    _flag = os.getenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", "").strip().lower()
    minimal = _flag in {{"1", "true", "yes"}}
    with ProfitDLL() as dll:
        t_init = time.time()
        dll.initialize_market_only(
            os.environ["PROFITDLL_KEY"],
            os.environ["PROFITDLL_USER"],
            os.environ["PROFITDLL_PASS"],
            minimal_handshake=minimal,
        )
        result["init_elapsed"] = time.time() - t_init
        t_wait = time.time()
        result["connected"] = bool(dll.wait_market_connected(timeout=120))
        result["wait_elapsed"] = time.time() - t_wait
except Exception as exc:
    result["error_type"] = type(exc).__name__
    result["error_msg"] = str(exc)
result["total_elapsed"] = time.time() - start
print(json.dumps(result), flush=True)
sys.exit(0 if result["connected"] else 2)
"""


def spawn_worker(idx: int, src_path: str) -> subprocess.Popen[str]:
    code = WORKER_CODE.format(src=src_path)
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Q17-OPEN multi-process license probe")
    p.add_argument("--n", type=int, default=2, help="processos paralelos (default 2)")
    p.add_argument(
        "--stagger",
        type=float,
        default=1.0,
        help="segundos de offset entre spawns (default 1.0s)",
    )
    p.add_argument(
        "--worker-timeout",
        type=float,
        default=180.0,
        help="timeout por worker em segundos (default 180s)",
    )
    return p.parse_args()


def classify(results: list[dict[str, Any]]) -> str:
    connected = [r for r in results if r.get("connected")]
    if len(connected) == len(results):
        wait_times = [r["wait_elapsed"] for r in connected]
        if max(wait_times) > 3 * min(wait_times) + 5:
            return "C-DEGRADED"
        return "A-ALL_CONNECTED"
    if connected:
        return "B-PARTIAL"
    return "FAIL-NONE_CONNECTED"


def main() -> int:
    args = parse_args()
    if not all(os.getenv(k) for k in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")):
        print("[SKIP] credenciais ausentes (PROFITDLL_KEY/USER/PASS).", flush=True)
        return 77

    src_path = str(ROOT / "src")
    print(
        f"[INFO] spawning {args.n} workers, stagger={args.stagger}s, "
        f"timeout={args.worker_timeout}s",
        flush=True,
    )

    procs: list[subprocess.Popen[str]] = []
    for i in range(args.n):
        if i > 0 and args.stagger > 0:
            time.sleep(args.stagger)
        procs.append(spawn_worker(i, src_path))
        print(f"[SPAWN] worker#{i} pid={procs[-1].pid}", flush=True)

    results: list[dict[str, Any]] = []
    for i, p in enumerate(procs):
        try:
            stdout, stderr = p.communicate(timeout=args.worker_timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            results.append({"worker": i, "rc": -1, "error": "timeout", "stderr": stderr[-500:]})
            continue
        last_line = (stdout or "").strip().splitlines()[-1] if stdout else ""
        try:
            r = json.loads(last_line) if last_line else {}
        except json.JSONDecodeError:
            r = {"raw_stdout": last_line}
        r["worker"] = i
        r["rc"] = p.returncode
        if p.returncode != 0:
            r["stderr_tail"] = (stderr or "")[-500:]
        results.append(r)

    verdict = classify(results)
    payload = {"verdict": verdict, "n": args.n, "stagger": args.stagger, "results": results}
    print("[RESULT]", json.dumps(payload, indent=2), flush=True)

    interp = {
        "A-ALL_CONNECTED": (
            "Hipótese A confirmada — licença per-machine; " "Story 4.1 multi-process OK."
        ),
        "B-PARTIAL": (
            "Hipótese B confirmada — licença single-session; " "Story 4.1 precisa redesign."
        ),
        "C-DEGRADED": (
            "Hipótese C confirmada — server-side rate limit; " "tunar concorrência em 4.1."
        ),
        "FAIL-NONE_CONNECTED": (
            "Falha base (nenhum conecta) — não isola Q17; " "investigar credenciais/ambiente."
        ),
    }
    print(f"[INTERP] {interp.get(verdict, 'Verdict não classificado')}", flush=True)

    return 0 if verdict.startswith(("A-", "C-")) else 1


if __name__ == "__main__":
    sys.exit(main())
