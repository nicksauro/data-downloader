#!/usr/bin/env python3
"""check_no_print.py — pre-commit hook (pre-commit stage).

Contrato pre-commit:
    pre-commit invoca: python scripts/hooks/check_no_print.py FILE1 FILE2 ...
    sys.argv[1:] = lista de arquivos staged que casam com `files:` regex no
    .pre-commit-config.yaml (^src/.*\\.(py|ts|js|tsx|jsx)$).

Bloqueia (exit 1) quando:
    - Qualquer arquivo passado contém `print(` (Python) ou `console.log` (JS/TS)
      em linhas NÃO comentadas e NÃO marcadas com `# print-allowed: <reason>` /
      `// print-allowed: <reason>` (ou o legado `# noqa: print`).

Justificativa:
    Hot path performance (R21) + ADR-010 (structlog obrigatório). `print()` em
    src/ ignora structured logging, perde contexto e quebra benchmarks.

Wave 1 P0 (2026-05-06): preferimos ``# print-allowed: <reason>`` ao invés de
``# noqa: print`` porque ``print`` não é um código ruff válido — quando T20x
está habilitado no select de ruff, marcadores ``# noqa: print`` viram warnings
"invalid noqa directive". O pragma ``# print-allowed`` é semanticamente claro
e ignorado por ruff.

Owner: Gage (devops). Story 0.2.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PY_PATTERN = re.compile(r"(?<![\w.])print\s*\(")
JS_PATTERN = re.compile(r"console\s*\.\s*log\s*\(")
# Reconhece tanto o pragma novo ("# print-allowed: <reason>") quanto o legado
# (`#` + `noqa:` + `print`). Mantemos compat para não quebrar outras call sites.
NOQA_MARKER = re.compile(
    r"#\s*print-allowed\b|//\s*print-allowed\b|#\s*noqa:\s*print|//\s*noqa:\s*print",
    re.IGNORECASE,
)


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Retorna [(line_number, line_text), ...] para violações."""
    findings: list[tuple[int, str]] = []
    suffix = path.suffix.lower()
    pattern = PY_PATTERN if suffix == ".py" else JS_PATTERN
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"WARN: could not read {path}: {exc}", file=sys.stderr)
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if NOQA_MARKER.search(line):
            continue
        if pattern.search(line):
            findings.append((lineno, line.rstrip()))
    return findings


def main(argv: list[str]) -> int:
    files = [Path(p) for p in argv[1:] if p]
    if not files:
        return 0
    total_violations = 0
    for f in files:
        if not f.exists():
            continue
        findings = scan_file(f)
        if findings:
            total_violations += len(findings)
            print(
                f"BLOCKED: {f} has print()/console.log (R21 / ADR-010 structlog):",
                file=sys.stderr,
            )
            for lineno, line in findings:
                print(f"  L{lineno}: {line}", file=sys.stderr)
    if total_violations:
        print(
            f"  Total violations: {total_violations}. "
            "Use structlog or add `# print-allowed: <reason>`.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
