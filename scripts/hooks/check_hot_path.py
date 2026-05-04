#!/usr/bin/env python3
"""check_hot_path.py — pre-commit wrapper para audit_hot_path.

Story 2.7 / COUNCIL-22 (Pyro). Contrato pre-commit:

    pre-commit invoca: python scripts/hooks/check_hot_path.py FILE1 FILE2 ...
    sys.argv[1:] = lista de arquivos staged que casam com `files:` regex.

Bloqueia (exit 1) quando algum dos arquivos staged está no
``_HOT_PATH_REGISTRY`` E contém violação R21 (estructlog/print/etc em
hot path).

Importante: este hook é OPT-IN. Não é instalado automaticamente em
``.pre-commit-config.yaml`` na Story 2.7 — Pyro decide ativação após
sign-off do registry definitivo + sem violações na main.

Activate (futuro):

    # .pre-commit-config.yaml
    - repo: local
      hooks:
        - id: check-hot-path
          name: Audit R21 hot-path compliance
          entry: python scripts/hooks/check_hot_path.py
          language: system
          types: [python]
          files: ^src/data_downloader/.*\\.py$
"""

from __future__ import annotations

import sys
from pathlib import Path

# Permite import quando rodado via `python scripts/hooks/check_hot_path.py`.
_THIS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from audit_hot_path import _default_src_root, audit  # noqa: E402  type: ignore[import-not-found]


def main(argv: list[str]) -> int:
    if not argv:
        # pre-commit pode não passar arquivos se nada matched — no-op.
        return 0

    src_root = _default_src_root()
    paths = [Path(arg).resolve() for arg in argv]
    report = audit(src_root, paths=paths)

    if report.clean:
        return 0

    print(
        f"FAIL: {len(report.violations)} violacao(oes) R21 em hot path:",
        file=sys.stderr,
    )
    for v in report.violations:
        print(v.format_human(), file=sys.stderr)
    print(
        "\nVer docs/perf/HOT_PATH_RULES.md para regras + exemplos validos.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
