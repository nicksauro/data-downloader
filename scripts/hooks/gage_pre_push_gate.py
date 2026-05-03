#!/usr/bin/env python3
"""gage_pre_push_gate.py — pre-commit hook (pre-push stage).

Contrato pre-commit (pre-push):
    pre-commit invoca: python scripts/hooks/gage_pre_push_gate.py
    stdin recebe linhas: <local_ref> <local_sha> <remote_ref> <remote_sha>\\n
    (configurado com always_run + pass_filenames=false; lemos stdin diretamente.)

Bloqueia (exit 1) quando:
    - Push toca commits que referenciam Story N.M sem QA report PASS
      em docs/qa/QA_REPORTS/{N.M}-*.md (verifica `verdict: PASS` no frontmatter).
    - Working tree não está limpo (uncommitted changes).
    - Push para tag sem CHANGELOG correspondente (warning, não bloqueia ainda).

Permite (exit 0) quando:
    - Push é deleção de branch (todos zeros em local_sha).
    - QA_REPORTS/ ainda não existe (squad em fase pre-Story 1.x — fail-open).
    - Variável env GAGE_BYPASS=1 está setada (uso emergencial — registra warning).

Justificativa:
    Última linha de defesa antes de Gage publicar. Quinn PASS é mandatório
    para qualquer push de código de feature (R20).

Owner: Gage (devops). Story 0.2.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QA_REPORTS_DIR = REPO_ROOT / "docs" / "qa" / "QA_REPORTS"
STORY_REF_PATTERN = re.compile(r"\[?\s*story\s+(\d+\.\d+)\s*\]?", re.IGNORECASE)
ZERO_SHA = "0" * 40


def read_push_refs() -> list[tuple[str, str, str, str]]:
    refs: list[tuple[str, str, str, str]] = []
    for line in sys.stdin:
        parts = line.strip().split()
        if len(parts) == 4:
            refs.append((parts[0], parts[1], parts[2], parts[3]))
    return refs


def commits_in_range(local_sha: str, remote_sha: str) -> list[str]:
    if remote_sha == ZERO_SHA:
        rev_range = local_sha
        extra = ["--max-count=50"]
    else:
        rev_range = f"{remote_sha}..{local_sha}"
        extra = []
    try:
        # Force UTF-8 to avoid cp1252 UnicodeDecodeError on Windows (Task #38 fix)
        result = subprocess.run(
            ["git", "log", "--format=%H%x00%B%x1e", rev_range, *extra],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return [c for c in result.stdout.split("\x1e") if c.strip()]
    except subprocess.CalledProcessError:
        return []


def working_tree_clean() -> bool:
    try:
        # Force UTF-8 to avoid cp1252 UnicodeDecodeError on Windows (Task #38 fix)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return not result.stdout.strip()
    except subprocess.CalledProcessError:
        return True


def qa_report_pass(story_id: str) -> bool:
    if not QA_REPORTS_DIR.exists():
        return True  # fail-open: pre-Story 1.x
    matches = list(QA_REPORTS_DIR.glob(f"{story_id}-*.md")) + list(
        QA_REPORTS_DIR.glob(f"{story_id}.md")
    )
    if not matches:
        return False
    for report in matches:
        content = report.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*verdict\s*:\s*PASS\b", content, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def main() -> int:
    if os.environ.get("GAGE_BYPASS") == "1":
        print(
            "WARN: GAGE_BYPASS=1 active — pre-push gate skipped (audit this!).",
            file=sys.stderr,
        )
        return 0
    if not working_tree_clean():
        print("BLOCKED: working tree not clean. Commit or stash before pushing.", file=sys.stderr)
        return 1
    refs = read_push_refs()
    if not refs:
        return 0
    referenced_stories: set[str] = set()
    for _local_ref, local_sha, _remote_ref, remote_sha in refs:
        if local_sha == ZERO_SHA:
            continue
        for commit_block in commits_in_range(local_sha, remote_sha):
            for match in STORY_REF_PATTERN.finditer(commit_block):
                referenced_stories.add(match.group(1))
    failing = [sid for sid in sorted(referenced_stories) if not qa_report_pass(sid)]
    if failing:
        print("BLOCKED: push references stories without QA PASS report:", file=sys.stderr)
        for sid in failing:
            print(
                f"  - Story {sid}: no PASS in {QA_REPORTS_DIR.relative_to(REPO_ROOT)}/{sid}-*.md",
                file=sys.stderr,
            )
        print(
            "  Quinn must produce QA report with `verdict: PASS` before Gage pushes.",
            file=sys.stderr,
        )
        print(
            "  Bypass: GAGE_BYPASS=1 git push (emergency only — log in AUDIT.md).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
