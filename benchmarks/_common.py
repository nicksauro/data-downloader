"""benchmarks/_common.py — Helpers compartilhados (git_sha, hardware, JSON).

Owner: Pyro (perf-engineer).
Ref: ``benchmarks/results/README.md`` — schema canônico de output.

Funções utilitárias para todos os benchmarks:
- :func:`git_sha`: hash curto do HEAD (+ "-dirty" se workdir tem mods).
- :func:`hardware_info`: snapshot CPU/RAM/disk/OS.
- :func:`python_info`: versão Python e implementação.
- :func:`dependencies_info`: versões de pyarrow/duckdb/psutil.
- :func:`save_results`: persiste JSON no schema canônico.
- :func:`percentile`: percentil simples (sem dependência de numpy).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

RESULTS_DIR = Path(__file__).parent / "results"


def git_sha() -> tuple[str, bool]:
    """Retorna (sha_short, dirty). 'unknown' se git não disponível."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return sha, bool(status)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown", False


def hardware_info() -> dict[str, Any]:
    """Snapshot CPU/RAM/OS. Disk type best-effort (Windows não expõe trivialmente)."""
    return {
        "cpu_model": platform.processor() or "unknown",
        "cpu_cores_physical": psutil.cpu_count(logical=False) or 0,
        "cpu_cores_logical": psutil.cpu_count(logical=True) or 0,
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "os": f"{platform.system()} {platform.release()} {platform.version()}",
        "machine": platform.machine(),
    }


def python_info() -> dict[str, str]:
    """Versão Python e implementação."""
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
    }


def dependencies_info() -> dict[str, str]:
    """Versões das deps relevantes para benchmarks."""
    deps: dict[str, str] = {}
    try:
        import pyarrow

        deps["pyarrow"] = pyarrow.__version__
    except ImportError:
        deps["pyarrow"] = "missing"
    try:
        import duckdb

        deps["duckdb"] = duckdb.__version__
    except ImportError:
        deps["duckdb"] = "missing"
    try:
        deps["psutil"] = psutil.__version__
    except AttributeError:
        deps["psutil"] = "unknown"
    return deps


def now_iso() -> str:
    """ISO timestamp UTC (Z)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile(values: list[float], pct: float) -> float:
    """Percentil simples (linear interpolation). pct em [0, 1]."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def build_result_envelope(
    benchmark_name: str,
    *,
    config: dict[str, Any],
    scenarios: list[dict[str, Any]],
    summary: dict[str, Any],
    notes: str = "",
    dll_version: str = "mock-1.0",
) -> dict[str, Any]:
    """Constrói o envelope canônico de resultado (schema benchmarks/results/README.md)."""
    sha, dirty = git_sha()
    return {
        "benchmark": benchmark_name,
        "version": "1.0.0",
        "git_sha": sha,
        "git_dirty": dirty,
        "date": now_iso(),
        "hardware": hardware_info(),
        "python": python_info(),
        "dependencies": dependencies_info(),
        "dll_version": dll_version,
        "config": config,
        "scenarios": scenarios,
        "summary": summary,
        "notes": notes,
    }


def save_results(envelope: dict[str, Any]) -> Path:
    """Persiste envelope em ``RESULTS_DIR`` no formato canônico de nome.

    Returns:
        Path absoluto do JSON salvo.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = envelope["benchmark"]
    sha = envelope["git_sha"]
    if envelope.get("git_dirty"):
        sha = f"{sha}-dirty"
    date = envelope["date"][:10]  # YYYY-MM-DD
    filename = f"{name}-{date}-{sha}.json"
    path = RESULTS_DIR / filename
    path.write_text(json.dumps(envelope, indent=2, default=str), encoding="utf-8")
    return path


def print_summary(envelope: dict[str, Any]) -> None:
    """Pretty-print resumo do resultado para stdout."""
    print(f"\n{'=' * 60}")
    dirty_tag = "+dirty" if envelope.get("git_dirty") else ""
    print(f"benchmark: {envelope['benchmark']}  [git={envelope['git_sha']}{dirty_tag}]")
    print(f"date     : {envelope['date']}")
    hw = envelope["hardware"]
    print(f"hardware : {hw['cpu_cores_logical']} log cores, {hw['ram_gb']}GB RAM")
    py = envelope["python"]
    print(f"python   : {py['version']} ({py['implementation']})")
    deps = envelope["dependencies"]
    print(f"deps     : pyarrow={deps.get('pyarrow')}, duckdb={deps.get('duckdb')}")
    print(f"summary  : {json.dumps(envelope['summary'], indent=2, default=str)}")
    print("=" * 60)


def is_workdir_dirty_for_benchmarks() -> bool:
    """Reporta se sha está suja — não bloqueia, apenas informa."""
    _, dirty = git_sha()
    return dirty


# Defaults compartilhados.
DEFAULT_N_RUNS = 5
DEFAULT_WARMUP_RUNS = 1


# Suprime "unused import" para sys — import mantido para introspection futura.
_ = sys
