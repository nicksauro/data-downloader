#!/usr/bin/env python3
"""check_no_dotenv.py — pre-commit hook (pre-commit stage).

Contrato pre-commit:
    pre-commit invoca: python scripts/hooks/check_no_dotenv.py
    (configurado com always_run + pass_filenames=false — escaneamos o staged ourselves.)

Bloqueia (exit 1) quando:
    - QUALQUER arquivo staged casa com pattern `.env` ou `.env.*`
      (excluindo whitelist explícita: `.env.example`, `.env.template`, `.env.sample`).
    - Conteúdo staged contém linhas suspeitas de credenciais (regex de segurança):
        * PROFITDLL_KEY=...
        * AWS_SECRET_ACCESS_KEY=...
        * api[_-]?key\\s*=\\s*['"][^'"]{16,}
        * password\\s*=\\s*['"][^'"]+

Justificativa:
    Defense-in-depth (gitignore + hook) para R18/R19 — uma vez no histórico git,
    sempre no histórico. Vazamento de chave Nelogica = incidente.

Owner: Gage (devops). Story 0.2.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

DOTENV_NAME_PATTERN = re.compile(r"(^|/)\.env(\..+)?$")
WHITELIST_SUFFIXES = (".example", ".template", ".sample", ".dist")
SECRET_PATTERNS = [
    re.compile(r"PROFITDLL_(KEY|USER|PASS)\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"AWS_SECRET_ACCESS_KEY\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"""api[_-]?key\s*=\s*['"][^'"]{16,}['"]""", re.IGNORECASE),
    re.compile(r"""password\s*=\s*['"][^'"]+['"]""", re.IGNORECASE),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
]


def staged_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, check=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def staged_blob(path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "show", f":{path}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return ""


def is_dotenv_violation(path: str) -> bool:
    norm = path.replace("\\", "/")
    name = PurePosixPath(norm).name
    if not DOTENV_NAME_PATTERN.search("/" + norm):
        return False
    return not any(name.endswith(suf) for suf in WHITELIST_SUFFIXES)


def main() -> int:
    files = staged_files()
    if not files:
        return 0
    violations: list[str] = []
    for f in files:
        if is_dotenv_violation(f):
            violations.append(f"  - {f}: matches .env pattern (not in whitelist {WHITELIST_SUFFIXES})")
            continue
        content = staged_blob(f)
        for pat in SECRET_PATTERNS:
            if pat.search(content):
                violations.append(f"  - {f}: contains secret pattern /{pat.pattern[:60]}.../")
                break
    if violations:
        print("BLOCKED: dotenv / credential content detected in staged files:", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        print("  Whitelist suffixes: .example .template .sample .dist", file=sys.stderr)
        print("  Move secrets to .env (gitignored) and commit only .env.example.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
