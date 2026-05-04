"""Smoke MVP Gate — Story 1.7b AC9 (Epic 1 final gate).

Gated por env vars (PROFITDLL_KEY, PROFITDLL_USER, PROFITDLL_PASS — alinhado
com ``.env.example``) — em CI sem credenciais reais o teste é skipped
automaticamente. Ver ``docs/qa/SMOKE_PROTOCOL.md`` para protocolo formal de
execução manual pelo humano (Quinn valida a evidência produzida).

Q-DRIFT-03 (smoke 2026-05-04): env vars padronizadas para ``PROFITDLL_*``
(versões anteriores usavam ``PROFIT_USER`` / ``PROFIT_PASS`` — divergência
com ``.env.example``).

Cenário (full smoke conforme SMOKE_PROTOCOL.md §4.2):

1. Roda ``data-downloader download --symbol WDOJ26 --start 2026-03-01
   --end 2026-03-30`` via subprocess (caminho real CLI).
2. Verifica:
   - exit code 0
   - >= 1 arquivo Parquet em ``data/history/F/WDOJ26/2026/03.parquet``
   - catalog.db tem partição com ``row_count > 0``
   - Re-rodar = no-op (cache hit message)
   - DuckDB lê todos os trades sem exception
   - ``data-downloader integrity check --symbol WDOJ26`` retorna clean
3. Salva evidência em ``docs/qa/SMOKE_EVIDENCE/1.7b-{ts}.md`` com hash
   Parquet + log estruturado (SMOKE_PROTOCOL.md §6).

Quinn (validador) lê a evidência produzida e checa critérios PASS-1..6.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

_HAS_CREDS = all(os.getenv(k) for k in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"))

# Symbol/range canônicos do gate (alinha com SMOKE_PROTOCOL.md §4.2).
_SMOKE_SYMBOL = "WDOJ26"
_SMOKE_START = "2026-03-01"
_SMOKE_END = "2026-03-30"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _save_evidence(
    *,
    repo_root: Path,
    symbol: str,
    start: str,
    end: str,
    cmd: list[str],
    first_run: subprocess.CompletedProcess[str],
    second_run: subprocess.CompletedProcess[str],
    integrity_run: subprocess.CompletedProcess[str],
    parquet_files: list[Path],
    duckdb_count: int,
) -> Path:
    """Salva markdown com hash, log, e critérios PASS — SMOKE_PROTOCOL.md §6."""
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H%M%SZ")
    out_dir = repo_root / "docs" / "qa" / "SMOKE_EVIDENCE"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"1.7b-{ts}.md"

    hash_lines = []
    for f in sorted(parquet_files):
        try:
            h = _sha256(f)
            size = f.stat().st_size
        except OSError as exc:
            h = f"<error: {exc}>"
            size = -1
        # Sanitiza path (remove username) — SMOKE_PROTOCOL.md §11.
        try:
            rel = f.relative_to(repo_root)
        except ValueError:
            rel = f
        hash_lines.append(f"  {h}  {rel}  ({size} bytes)")

    body = (
        f"# Smoke Run — Story 1.7b — {ts}\n\n"
        "## Mode\n\n"
        "full (gate Epic 1 — automated subprocess; "
        "manual run per SMOKE_PROTOCOL.md)\n\n"
        f"## Symbol / Range\n\n- symbol: `{symbol}`\n- start: `{start}`\n- end: `{end}`\n\n"
        f"## Command\n\n```\n{' '.join(cmd)}\n```\n\n"
        "## First run (download)\n\n"
        f"- exit_code: `{first_run.returncode}`\n"
        f"- stdout (head):\n```\n{first_run.stdout[:2000]}\n```\n\n"
        "## Second run (idempotency / cache hit)\n\n"
        f"- exit_code: `{second_run.returncode}`\n"
        f"- stdout (head):\n```\n{second_run.stdout[:1000]}\n```\n\n"
        "## Integrity check\n\n"
        f"- exit_code: `{integrity_run.returncode}`\n"
        f"- stdout (head):\n```\n{integrity_run.stdout[:1500]}\n```\n\n"
        "## Parquet files written\n\n"
        f"- count: `{len(parquet_files)}`\n\n"
        "### SHA256 hashes\n\n"
        "```\n" + "\n".join(hash_lines) + "\n```\n\n"
        "## DuckDB read\n\n"
        f"- COUNT(*) from read_parquet(...): `{duckdb_count}`\n\n"
        "## Verdict\n\n"
        "(Quinn valida — ver SMOKE_PROTOCOL.md §7 critérios PASS-1..6)\n"
    )
    out.write_text(body, encoding="utf-8")
    return out


@pytest.mark.smoke
@pytest.mark.skipif(
    not _HAS_CREDS,
    reason="MVP gate requer PROFITDLL_KEY + PROFITDLL_USER + PROFITDLL_PASS (manual run)",
)
def test_mvp_gate_full_smoke(tmp_path: Path) -> None:
    """Full smoke conforme SMOKE_PROTOCOL.md §4.2 + AC9 da Story 1.7b."""
    # Repo root = parents[2] de tests/smoke/test_mvp_gate.py
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "data_downloader.cli",
        "download",
        "--symbol",
        _SMOKE_SYMBOL,
        "--start",
        _SMOKE_START,
        "--end",
        _SMOKE_END,
        "--data-dir",
        str(data_dir),
    ]

    # ---- 1. First run ----
    # F-H-5: encoding="utf-8" + errors="replace" evita UnicodeDecodeError
    # em Windows onde subprocess.run(text=True) cai em cp1252 e o stdout
    # do CLI emite microcopy com emojis/box-drawing.
    first = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(repo_root),
        timeout=1800,  # 30 min hard cap (SMOKE_PROTOCOL.md FAIL-8)
        check=False,
    )
    assert first.returncode == 0, (
        f"First download exited {first.returncode}\n"
        f"stdout: {first.stdout}\nstderr: {first.stderr}"
    )

    # ---- 2. Verify Parquet written ----
    parquet_dir = data_dir / "history" / "F" / _SMOKE_SYMBOL / "2026"
    assert parquet_dir.exists(), f"Parquet dir not created: {parquet_dir}"
    parquet_files = sorted(parquet_dir.glob("*.parquet"))
    assert parquet_files, f"No Parquet files in {parquet_dir}"

    # ---- 3. Verify catalog has partition with row_count > 0 ----
    import sqlite3

    catalog_db = data_dir / "history" / "catalog.db"
    assert catalog_db.exists(), f"Catalog DB missing: {catalog_db}"
    conn = sqlite3.connect(str(catalog_db))
    try:
        rows = conn.execute(
            "SELECT row_count FROM partitions WHERE symbol = ?",
            (_SMOKE_SYMBOL,),
        ).fetchall()
        assert rows, "No partition rows in catalog for symbol"
        assert all(r[0] > 0 for r in rows), "Partition with row_count <= 0"
        total_rows = sum(r[0] for r in rows)
    finally:
        conn.close()

    # ---- 4. Re-run = no-op (cache hit) ----
    second = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(repo_root),
        timeout=300,
        check=False,
    )
    assert second.returncode == 0, f"Second run exited {second.returncode}\nstdout: {second.stdout}"
    assert (
        "Já estava baixado" in second.stdout or "cache" in second.stdout.lower()
    ), f"No cache_hit message in second run:\n{second.stdout}"

    # ---- 5. DuckDB lê todos os trades ----
    import duckdb

    glob = str(data_dir / "history" / "F" / _SMOKE_SYMBOL / "**" / "*.parquet")
    duck_conn = duckdb.connect(":memory:")
    try:
        result = duck_conn.execute(f"SELECT COUNT(*) FROM read_parquet('{glob}')").fetchone()
        duck_count = int(result[0]) if result else 0
        assert duck_count > 0, "DuckDB read 0 rows"
        assert (
            duck_count == total_rows
        ), f"DuckDB count ({duck_count}) != catalog total ({total_rows})"
    finally:
        duck_conn.close()

    # ---- 6. integrity check clean ----
    integrity_cmd = [
        sys.executable,
        "-m",
        "data_downloader.cli",
        "integrity",
        "check",
        "--symbol",
        _SMOKE_SYMBOL,
        "--data-dir",
        str(data_dir),
    ]
    integrity = subprocess.run(
        integrity_cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(repo_root),
        timeout=120,
        check=False,
    )
    # 0 = all checks passed; 2 = violations (FAIL-6 do SMOKE_PROTOCOL).
    assert integrity.returncode == 0, (
        f"Integrity check failed (exit {integrity.returncode}):\n"
        f"{integrity.stdout}\n{integrity.stderr}"
    )

    # ---- 7. Salva evidência (SMOKE_PROTOCOL.md §5/§6) ----
    evidence_path = _save_evidence(
        repo_root=repo_root,
        symbol=_SMOKE_SYMBOL,
        start=_SMOKE_START,
        end=_SMOKE_END,
        cmd=cmd,
        first_run=first,
        second_run=second,
        integrity_run=integrity,
        parquet_files=parquet_files,
        duckdb_count=duck_count,
    )
    print(f"\n[SMOKE EVIDENCE] {evidence_path}")
