#!/usr/bin/env python3
"""
verify-dll-companions.py — Pré-flight check para ProfitDLL companions.

Owner: Gage (devops)
Story: 0.1 — Environment Bootstrap
Coordena com: ADR-008 (Aria), Nelo (lista canônica de companions)

PROPÓSITO
---------
ProfitDLL.dll depende de várias outras DLLs e arquivos .dat para funcionar.
Faltar QUALQUER UM resulta em:
  - DLLInitializeMarketLogin retornando código de erro críptico, OU
  - Crash silencioso na primeira chamada à DLL, OU
  - Comportamento errático (Q11-E callback issues).

Este script DEVE ser executado ANTES de qualquer chamada a DLLInitialize, em:
  - CI smoke tests
  - Bootstrap local (após scripts/bootstrap-dll.ps1)
  - Pre-flight do .exe distribuído (futuro)

USO
---
  python scripts/verify-dll-companions.py
  python scripts/verify-dll-companions.py --path /custom/path/to/Win64
  python scripts/verify-dll-companions.py --json     # output machine-readable

EXIT CODES
----------
  0 = todos os artefatos presentes
  1 = pelo menos um artefato faltando (lista impressa)
  2 = caminho inválido ou erro inesperado
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# -----------------------------------------------------------------------------
# Lista canônica — fonte da verdade. Coordenada com:
#   - scripts/bootstrap-dll.ps1
#   - build/data_downloader.spec (PyInstaller, Story de Epic 3)
#   - Nelo (audit de wrapper DLL)
# -----------------------------------------------------------------------------
REQUIRED_DLLS: tuple[str, ...] = (
    "ProfitDLL.dll",
    "libcrypto-1_1-x64.dll",
    "libssl-1_1-x64.dll",
    "libeay32.dll",
    "ssleay32.dll",
)

REQUIRED_DAT_FILES: tuple[str, ...] = (
    "timezone2.dat",
    "holidays.dat",
    "exchangeinfo2.dat",
    "newagents.dat",
)

REQUIRED_DIRS: tuple[str, ...] = (
    "MarketHours2",
    "database",
)

OPTIONAL_DIRS: tuple[str, ...] = (
    "PopupManagerV2",
    "strategy",
)


# -----------------------------------------------------------------------------
# Resultado estruturado
# -----------------------------------------------------------------------------
@dataclass
class VerificationResult:
    base_path: Path
    found_dlls: list[str] = field(default_factory=list)
    missing_dlls: list[str] = field(default_factory=list)
    found_dats: list[str] = field(default_factory=list)
    missing_dats: list[str] = field(default_factory=list)
    found_dirs: list[str] = field(default_factory=list)
    missing_dirs: list[str] = field(default_factory=list)
    optional_dirs_present: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return (
            not self.missing_dlls
            and not self.missing_dats
            and not self.missing_dirs
            and not self.errors
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "base_path": str(self.base_path),
            "ok": self.is_ok,
            "dlls": {
                "found": self.found_dlls,
                "missing": self.missing_dlls,
            },
            "dat_files": {
                "found": self.found_dats,
                "missing": self.missing_dats,
            },
            "dirs_required": {
                "found": self.found_dirs,
                "missing": self.missing_dirs,
            },
            "dirs_optional_present": self.optional_dirs_present,
            "errors": self.errors,
        }


# -----------------------------------------------------------------------------
# Verificação principal
# -----------------------------------------------------------------------------
def verify(base_path: Path) -> VerificationResult:
    result = VerificationResult(base_path=base_path)

    if not base_path.exists():
        result.errors.append(f"Caminho nao existe: {base_path}")
        return result

    if not base_path.is_dir():
        result.errors.append(f"Caminho nao e diretorio: {base_path}")
        return result

    # DLLs
    for dll in REQUIRED_DLLS:
        target = base_path / dll
        if target.is_file():
            result.found_dlls.append(dll)
        else:
            result.missing_dlls.append(dll)

    # .dat files
    for dat in REQUIRED_DAT_FILES:
        target = base_path / dat
        if target.is_file():
            result.found_dats.append(dat)
        else:
            result.missing_dats.append(dat)

    # Diretórios obrigatórios
    for d in REQUIRED_DIRS:
        target = base_path / d
        if target.is_dir():
            result.found_dirs.append(d)
        else:
            result.missing_dirs.append(d)

    # Diretórios opcionais
    for d in OPTIONAL_DIRS:
        target = base_path / d
        if target.is_dir():
            result.optional_dirs_present.append(d)

    return result


# -----------------------------------------------------------------------------
# Renderização humana
# -----------------------------------------------------------------------------
def render_human(result: VerificationResult) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append("=" * 64)
    lines.append(" verify-dll-companions — pre-flight check ProfitDLL")
    lines.append("=" * 64)
    lines.append(f" Base path: {result.base_path}")
    lines.append("")

    def section(title: str, found: list[str], missing: list[str]) -> None:
        lines.append(f"[{title}]")
        for f in found:
            lines.append(f"  [OK]    {f}")
        for m in missing:
            lines.append(f"  [FALTA] {m}")
        if not found and not missing:
            lines.append("  (nada esperado)")
        lines.append("")

    section("DLLs", result.found_dlls, result.missing_dlls)
    section(".dat files", result.found_dats, result.missing_dats)
    section("Diretorios obrigatorios", result.found_dirs, result.missing_dirs)

    lines.append("[Diretorios opcionais presentes]")
    if result.optional_dirs_present:
        for d in result.optional_dirs_present:
            lines.append(f"  [OK]    {d}")
    else:
        lines.append("  (nenhum)")
    lines.append("")

    if result.errors:
        lines.append("[Erros]")
        for e in result.errors:
            lines.append(f"  - {e}")
        lines.append("")

    lines.append("=" * 64)
    if result.is_ok:
        lines.append(" RESULTADO: OK — todos os companions presentes.")
    else:
        total_missing = (
            len(result.missing_dlls) + len(result.missing_dats) + len(result.missing_dirs)
        )
        lines.append(f" RESULTADO: FALHA — {total_missing} artefato(s) ausente(s).")
        lines.append("")
        lines.append(" Acao sugerida:")
        lines.append("   1. Confirme que ProfitChart esta instalado.")
        lines.append("   2. Rode: scripts\\bootstrap-dll.ps1")
        lines.append("   3. Re-rode este script para validar.")
    lines.append("=" * 64)
    lines.append("")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    default_path = repo_root / "profitdll" / "DLLs" / "Win64"

    parser = argparse.ArgumentParser(
        description="Verifica presenca de ProfitDLL companions e .dat files.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=default_path,
        help=f"Caminho do diretorio Win64 (default: {default_path})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output em JSON em vez de relatorio humano.",
    )
    args = parser.parse_args(argv)

    try:
        result = verify(args.path.resolve())
    except Exception as exc:
        print(f"[ERRO INESPERADO] {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_human(result))

    return 0 if result.is_ok else 1


if __name__ == "__main__":
    sys.exit(main())
