"""bench_subprocess_spawn.py — Cold start de 1 worker DLL no Windows.

Objetivo:
    Medir tempo de cold-start de 1 worker subprocess no Windows: Python init
    + import dependencies + DLL load + DLLInitializeMarketLogin + login auth.
    CRÍTICO para decidir multi-symbol via PROCESSO PERSISTENTE (worker pool)
    vs SPAWN-PER-JOB (descartável).

Target V1:
    Informativo — não há target absoluto. Resultado decide arquitetura.
    Esperado: 2-10s no Windows (vs ~50ms em Linux fork).

Hipóteses a testar:
    H1: Python init + imports = ~500ms-1.5s.
    H2: DLL load (LoadLibrary) = ~50-200ms.
    H3: DLLInitializeMarketLogin + auth (rede) = ~1-5s — DOMINANTE.
    H4: Total: 2-10s — se confirmar, multi-symbol via spawn-per-job só
        compensa para jobs > 5min (validar com bench_multi_symbol H1/H2).
    H5: Worker pool persistente: spawn 1x no boot, depois 0ms por job.
        Ganho enorme se confirmar H3.

Estágios medidos (timestamp em cada um):
    - python_init_ms (interpreter ready)
    - imports_ms (data_downloader.* importado)
    - dll_load_ms (LoadLibrary OK)
    - dll_init_ms (DLLInitializeMarketLogin OK)
    - login_auth_ms (recebe MARKET_CONNECTED)
    - total_cold_start_ms

Output:
    benchmarks/results/bench_subprocess_spawn-{date}-{git_sha}.json

JSON schema:
    {
        "benchmark": "bench_subprocess_spawn",
        "n_runs": 10,
        "stages": {
            "python_init_ms": {"p50": 0, "p99": 0},
            "imports_ms": {...},
            "dll_load_ms": {...},
            "dll_init_ms": {...},
            "login_auth_ms": {...},
            "total_cold_start_ms": {"p50": 0, "p99": 0}
        },
        "recommendation": "worker_pool_persistente|spawn_per_job"
    }
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# TODO: imports
# from benchmarks.fixtures.mock_dll import MockProfitDLL

RESULTS_DIR = Path(__file__).parent / "results"
N_RUNS = 10

# Script-helper que será spawned. Cada estágio printa JSON com timestamp_ns.
WORKER_SCRIPT = """
import time, json, sys
t0 = time.perf_counter_ns()
print(json.dumps({"stage": "python_init", "ns": t0}))

# TODO: imports reais
# import data_downloader.dll_wrapper
# import data_downloader.ingest
t_imports = time.perf_counter_ns()
print(json.dumps({"stage": "imports", "ns": t_imports}))

# TODO: load DLL (real ou mock conforme env)
# import os
# if os.environ.get("DATA_DOWNLOADER_USE_MOCK") == "1":
#     from benchmarks.fixtures.mock_dll import MockProfitDLL as DLL
# else:
#     from data_downloader.dll_wrapper import ProfitDLL as DLL
# dll = DLL.load()
t_dll_load = time.perf_counter_ns()
print(json.dumps({"stage": "dll_load", "ns": t_dll_load}))

# dll.initialize(...)
t_dll_init = time.perf_counter_ns()
print(json.dumps({"stage": "dll_init", "ns": t_dll_init}))

# wait MARKET_CONNECTED
# dll.wait_state("MARKET_CONNECTED", timeout=10)
t_login = time.perf_counter_ns()
print(json.dumps({"stage": "login_auth", "ns": t_login}))

print(json.dumps({"stage": "ready", "ns": time.perf_counter_ns()}))
sys.exit(0)
"""


def measure_one_spawn() -> dict[str, Any]:
    """Spawna 1 subprocess, captura stages."""
    # TODO:
    # spawn_t0 = time.perf_counter_ns()
    # proc = subprocess.Popen(
    #     [sys.executable, "-c", WORKER_SCRIPT],
    #     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    #     env={**os.environ, "DATA_DOWNLOADER_USE_MOCK": "1"},
    # )
    # stdout, stderr = proc.communicate(timeout=30)
    # stages = {}
    # for line in stdout.decode().splitlines():
    #     try:
    #         msg = json.loads(line)
    #         stages[msg["stage"]] = msg["ns"]
    #     except (json.JSONDecodeError, KeyError):
    #         continue
    # # Calcular deltas
    # return {
    #     "python_init_ms": (stages["python_init"] - spawn_t0) / 1e6,
    #     "imports_ms": (stages["imports"] - stages["python_init"]) / 1e6,
    #     "dll_load_ms": (stages["dll_load"] - stages["imports"]) / 1e6,
    #     "dll_init_ms": (stages["dll_init"] - stages["dll_load"]) / 1e6,
    #     "login_auth_ms": (stages["login_auth"] - stages["dll_init"]) / 1e6,
    #     "total_cold_start_ms": (stages["ready"] - spawn_t0) / 1e6,
    # }
    raise NotImplementedError("Aguarda dll_wrapper (Story 1.2) + mock_dll")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # TODO:
    # runs = [measure_one_spawn() for _ in range(N_RUNS)]
    # stages_agg = {}
    # for stage in runs[0].keys():
    #     vals = [r[stage] for r in runs]
    #     stages_agg[stage] = {
    #         "p50": statistics.median(vals),
    #         "p99": sorted(vals)[int(0.99 * len(vals))] if len(vals) > 1 else vals[0],
    #     }
    # # Recomendação:
    # # se total_cold_start_ms p50 > 5000: "worker_pool_persistente" (forte)
    # # se 2000 <= p50 <= 5000: "worker_pool_persistente" (moderado, depende de duração de jobs)
    # # se p50 < 2000: "spawn_per_job" (aceitável)
    raise NotImplementedError(
        "bench_subprocess_spawn é esqueleto sintético (Story 1.4.5). "
        "Resultado informa decisão arquitetural (Aria + ADR-013)."
    )


if __name__ == "__main__":
    main()
