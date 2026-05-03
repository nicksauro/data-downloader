#!/usr/bin/env python3
"""check_dll_story_ref.py — pre-commit hook (commit-msg stage).

Contrato pre-commit (commit-msg):
    pre-commit invoca: python scripts/hooks/check_dll_story_ref.py <commit-msg-file>
    sys.argv[1] = path para arquivo temporário com a mensagem de commit candidata.

Bloqueia (exit 1) quando:
    - Diff staged toca QUALQUER arquivo sob src/data_downloader/dll/ E
    - A mensagem de commit NÃO contém referência explícita a story
      no formato `[Story N.M]` ou `Story N.M` (case-insensitive).

Justificativa:
    R12 (MANIFEST.md) — mudanças no wrapper DLL exigem rastreabilidade story-by-story.
    Sem story-id na mensagem, é impossível auditar regressões de comportamento DLL.

Owner: Gage (devops). Story 0.2.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DLL_PATH_PREFIX = "src/data_downloader/dll/"
STORY_PATTERN = re.compile(r"\[?\s*story\s+\d+\.\d+\s*\]?", re.IGNORECASE)


def staged_files() -> list[str]:
    """Retorna lista de arquivos staged (versus HEAD ou index inicial)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("ERROR: check_dll_story_ref.py requires commit-msg file as argv[1]", file=sys.stderr)
        return 1

    commit_msg_file = Path(argv[1])
    if not commit_msg_file.exists():
        print(f"ERROR: commit-msg file not found: {commit_msg_file}", file=sys.stderr)
        return 1

    files = staged_files()
    dll_touched = [f for f in files if f.replace("\\", "/").startswith(DLL_PATH_PREFIX)]
    if not dll_touched:
        return 0

    msg = commit_msg_file.read_text(encoding="utf-8", errors="replace")
    if STORY_PATTERN.search(msg):
        return 0

    print("BLOCKED: commit touches src/data_downloader/dll/ but lacks story reference.", file=sys.stderr)
    print("  Files touched:", file=sys.stderr)
    for f in dll_touched:
        print(f"    - {f}", file=sys.stderr)
    print("  Required: include `[Story N.M]` or `Story N.M` in commit message (R12).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
