#!/usr/bin/env python3
"""check_conventional_commit.py — pre-commit hook (commit-msg stage).

Contrato pre-commit (commit-msg):
    pre-commit invoca: python scripts/hooks/check_conventional_commit.py <commit-msg-file>
    sys.argv[1] = path para arquivo temporário com a mensagem de commit candidata.

Bloqueia (exit 1) quando:
    - Linha de subject (primeira linha não-vazia) NÃO casa com regex conventional commits:
        ^(feat|fix|docs|chore|refactor|test|perf|build|ci|style|revert)(\\([\\w\\-./]+\\))?(!)?:\\s.+
    - Subject excede 100 caracteres (warning leve, não bloqueia)
    - Comentários (#...) e linhas vazias no topo são ignorados (modo `git commit -v`)

Aceita (não bloqueia):
    - Commits de merge (`Merge branch ...`)
    - Commits de revert auto-gerados (`Revert "..."`)
    - Commits fixup/squash (`fixup!`, `squash!`)

Justificativa:
    Trilha de auditoria limpa (R19), changelogs auto-gerados (Morgan *changelog),
    SemVer disciplinado por Gage (`feat:` minor, `fix:` patch, `feat!:` major).

Owner: Gage (devops). Story 0.2.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CONVENTIONAL_PATTERN = re.compile(
    r"^(feat|fix|docs|chore|refactor|test|perf|build|ci|style|revert)"
    r"(\([\w\-./]+\))?"
    r"(!)?"
    r":\s.+"
)
BYPASS_PREFIXES = ("Merge ", "Revert ", "fixup!", "squash!", "amend!")
MAX_SUBJECT_LEN = 100


def first_real_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("ERROR: check_conventional_commit.py requires commit-msg file as argv[1]", file=sys.stderr)
        return 1
    commit_msg_file = Path(argv[1])
    if not commit_msg_file.exists():
        print(f"ERROR: commit-msg file not found: {commit_msg_file}", file=sys.stderr)
        return 1
    msg = commit_msg_file.read_text(encoding="utf-8", errors="replace")
    subject = first_real_line(msg)
    if not subject:
        print("BLOCKED: empty commit message.", file=sys.stderr)
        return 1
    if subject.startswith(BYPASS_PREFIXES):
        return 0
    if not CONVENTIONAL_PATTERN.match(subject):
        print("BLOCKED: commit subject does not follow Conventional Commits.", file=sys.stderr)
        print(f"  Got: {subject!r}", file=sys.stderr)
        print("  Expected: <type>(<scope>)?: <subject>  e.g. 'feat(dll): add reconnection (Story 1.4)'", file=sys.stderr)
        print("  Allowed types: feat, fix, docs, chore, refactor, test, perf, build, ci, style, revert", file=sys.stderr)
        return 1
    if len(subject) > MAX_SUBJECT_LEN:
        print(f"WARN: subject is {len(subject)} chars (>{MAX_SUBJECT_LEN}). Consider shortening.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
