"""scripts/github_release.py — Pipeline GitHub Release (Story 4.4).

Owner: Gage (devops). Roda APÓS ``scripts/build_release.py``: lê
``dist/build-manifest-v{version}.json`` + section relevante do
``CHANGELOG.md`` e cria GitHub Release via ``gh`` CLI.

Uso:
    python scripts/github_release.py --version 1.0.0 [--dry-run] [--prerelease]

Pré-condições:

1. ``scripts/build_release.py`` foi executado com sucesso (manifest +
   zip + onedir presentes em ``dist/``).
2. ``gh`` CLI instalado e autenticado (``gh auth status`` retorna OK).
3. Tag ``v{version}`` JÁ existe no remote (criada por @devops humano —
   convenção: tag pushed antes de release).
4. Section ``## [API v{version}]`` ou similar presente em ``CHANGELOG.md``.

Pipeline:

    1. Lê manifest JSON (valida campos críticos).
    2. Extrai section do CHANGELOG.md correspondente à versão.
    3. Compõe release body:
       - Resumo (CHANGELOG section).
       - SHA256 do .zip + manifest.
       - Link para INSTALL.md (raw GitHub URL ou path relativo).
       - Aviso SmartScreen (Caminho B / ADR-016).
    4. Invoca ``gh release create v{version} --title ... --notes-file ... \\
                 dist/data-downloader-v{version}-win64.zip
                 dist/build-manifest-v{version}.json``.
    5. Anexa link da release ao README.md (append "Latest release: ...").

Modos:

    --dry-run    Não invoca ``gh``; imprime comando que seria executado.
    --prerelease Marca release como pre-release (gh --prerelease).

Exit codes:

    0 = success
    1 = pre-condition failed
    2 = gh CLI failed
    3 = README update failed (não-fatal — release foi criado, só falhou append)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DIST_DIR: Final[Path] = REPO_ROOT / "dist"
CHANGELOG: Final[Path] = REPO_ROOT / "CHANGELOG.md"
README: Final[Path] = REPO_ROOT / "README.md"

# Marcador onde apenda link de "Latest release".
README_LATEST_MARKER: Final[str] = "<!-- LATEST-RELEASE -->"


# =====================================================================
# Helpers
# =====================================================================


def _read_manifest(version: str) -> dict[str, object]:
    """Lê + valida ``dist/build-manifest-v{version}.json``."""
    path = DIST_DIR / f"build-manifest-v{version}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Manifest ausente: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest não é objeto JSON: {path}")
    if payload.get("version") != version:
        raise ValueError(f"Manifest version {payload.get('version')!r} != esperado {version!r}")
    if payload.get("dry_run"):
        raise ValueError("Manifest é de dry-run; rode build_release.py sem --dry-run antes.")
    if not payload.get("zip"):
        raise ValueError("Manifest sem campo zip — build não produziu artefato.")
    return payload


def _extract_changelog_section(version: str) -> str:
    """Extrai section do CHANGELOG.md correspondente a ``[API v{version}]``.

    Aceita também rótulos curtos ``## [{version}]`` ou ``## v{version}``.
    Retorna texto vazio se não encontrar (caller decide se falha).
    """
    if not CHANGELOG.is_file():
        return ""
    text = CHANGELOG.read_text(encoding="utf-8")
    patterns = [
        rf"^##\s+\[API v{re.escape(version)}\][^\n]*\n",
        rf"^##\s+\[v?{re.escape(version)}\][^\n]*\n",
        rf"^##\s+v?{re.escape(version)}\s*\n",
    ]
    start = -1
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            start = match.end()
            break
    if start < 0:
        return ""
    # Próxima section ## marca fim.
    rest = text[start:]
    next_section = re.search(r"^##\s+", rest, re.MULTILINE)
    end = next_section.start() if next_section else len(rest)
    return rest[:end].strip()


def _compose_release_body(
    version: str,
    manifest: dict[str, object],
    changelog_section: str,
) -> str:
    """Compõe markdown body da GitHub Release."""
    zip_section = manifest.get("zip")
    zip_sha = (
        zip_section["sha256"]
        if isinstance(zip_section, dict) and isinstance(zip_section.get("sha256"), str)
        else "N/A"
    )
    zip_size = (
        zip_section["size_bytes"]
        if isinstance(zip_section, dict) and isinstance(zip_section.get("size_bytes"), int)
        else 0
    )
    git_short = manifest.get("git_short_sha", "N/A")

    # Story 4.17 — installer section (opcional, presente se --with-installer foi
    # usado em build_release.py). Manifest schema: installer = {path, size_bytes,
    # sha256} ou None.
    installer_section = manifest.get("installer")
    installer_sha = (
        installer_section["sha256"]
        if isinstance(installer_section, dict) and isinstance(installer_section.get("sha256"), str)
        else None
    )
    installer_size = (
        installer_section["size_bytes"]
        if isinstance(installer_section, dict)
        and isinstance(installer_section.get("size_bytes"), int)
        else 0
    )

    body_lines: list[str] = []
    body_lines.append(f"# Data Downloader v{version}")
    body_lines.append("")
    if changelog_section:
        body_lines.append("## Changelog")
        body_lines.append("")
        body_lines.append(changelog_section)
        body_lines.append("")
    body_lines.append("## Artifacts")
    body_lines.append("")
    if installer_sha is not None:
        body_lines.append(
            f"- **`data-downloader-Setup-v{version}.exe`** "
            f"({installer_size / (1024 * 1024):.1f} MB) — "
            "**recomendado** (1-clique, Start Menu, Add/Remove Programs)"
        )
        body_lines.append(f"  - SHA256: `{installer_sha}`")
    body_lines.append(
        f"- `data-downloader-v{version}-win64.zip` "
        f"({zip_size / (1024 * 1024):.1f} MB) — portable / advanced users"
    )
    body_lines.append(f"  - SHA256: `{zip_sha}`")
    body_lines.append(f"- Git SHA: `{git_short}`")
    body_lines.append(f"- `build-manifest-v{version}.json` (full audit trail)")
    body_lines.append("")
    body_lines.append("## Installation")
    body_lines.append("")
    body_lines.append(
        "Veja [`docs/release/INSTALL.md`](docs/release/INSTALL.md) "
        "para o passo-a-passo completo."
    )
    body_lines.append("")
    body_lines.append("### SmartScreen warning")
    body_lines.append("")
    body_lines.append(
        "Esta release V1.0 **não é assinada** (code signing deferred V1.1 — "
        "ver ADR-016). Na primeira execução o Windows mostra "
        '*"Aplicativo não reconhecido"*. Clique em **Mais informações** '
        "→ **Executar mesmo assim**. Detalhes em "
        "[`build/WINDOWS_DEFENDER_NOTES.md`](build/WINDOWS_DEFENDER_NOTES.md)."
    )
    body_lines.append("")
    body_lines.append("## Verification")
    body_lines.append("")
    body_lines.append("```powershell")
    body_lines.append("# Compare SHA256 do zip baixado:")
    body_lines.append(f"Get-FileHash -Algorithm SHA256 data-downloader-v{version}-win64.zip")
    body_lines.append(f"# Esperado: {zip_sha}")
    body_lines.append("```")
    body_lines.append("")

    return "\n".join(body_lines)


def _ensure_gh_available() -> None:
    """Valida que ``gh`` CLI está disponível no PATH."""
    if shutil.which("gh") is None:
        raise RuntimeError("gh CLI não encontrado no PATH (instale GitHub CLI).")


def _invoke_gh_release(
    version: str,
    title: str,
    body_path: Path,
    artifacts: list[Path],
    *,
    prerelease: bool,
    dry_run: bool,
) -> None:
    """Invoca ``gh release create``. Raises on failure."""
    cmd = [
        "gh",
        "release",
        "create",
        f"v{version}",
        "--title",
        title,
        "--notes-file",
        str(body_path),
    ]
    if prerelease:
        cmd.append("--prerelease")
    cmd.extend(str(p) for p in artifacts)

    if dry_run:
        print("[github_release] DRY-RUN — comando que seria invocado:")
        print(" ", " ".join(cmd))
        return

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh release create falhou (rc={result.returncode})")


def _append_readme_latest(version: str, release_url: str) -> None:
    """Append/replace 'Latest release' marker em README.md."""
    if not README.is_file():
        return
    text = README.read_text(encoding="utf-8")
    line = f"{README_LATEST_MARKER} Latest release: [v{version}]({release_url})"
    if README_LATEST_MARKER in text:
        # Substitui linha existente.
        new_text = re.sub(
            rf"{re.escape(README_LATEST_MARKER)}[^\n]*",
            line,
            text,
        )
    else:
        new_text = text.rstrip() + "\n\n" + line + "\n"
    README.write_text(new_text, encoding="utf-8")


def _construct_release_url(version: str, manifest: dict[str, object]) -> str:
    """Best-effort construct release URL (humano-friendly)."""
    # gh CLI determina remote automaticamente; aqui apenas formato canônico.
    return f"https://github.com/{_resolve_repo_slug()}/releases/tag/v{version}"


def _resolve_repo_slug() -> str:
    """Tenta resolver owner/repo via ``gh repo view``."""
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            slug = result.stdout.strip()
            if slug:
                return slug
    except (OSError, FileNotFoundError):
        pass
    return "nicksauro/data-downloader"


# =====================================================================
# CLI
# =====================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub Release pipeline (Story 4.4).")
    parser.add_argument("--version", required=True, help="Versão SemVer (ex: 1.0.0)")
    parser.add_argument("--dry-run", action="store_true", help="Não invoca gh CLI.")
    parser.add_argument("--prerelease", action="store_true", help="Marca como pre-release.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    version: str = args.version

    # 1. Validate manifest + artifacts.
    try:
        manifest = _read_manifest(version)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[github_release] PRE-COND FAILED: {exc}", file=sys.stderr)
        return 1

    zip_path = DIST_DIR / f"data-downloader-v{version}-win64.zip"
    manifest_path = DIST_DIR / f"build-manifest-v{version}.json"
    if not zip_path.is_file():
        print(f"[github_release] zip ausente: {zip_path}", file=sys.stderr)
        return 1
    if not manifest_path.is_file():
        print(f"[github_release] manifest ausente: {manifest_path}", file=sys.stderr)
        return 1

    # Story 4.17 — detectar installer (opcional). Se manifest tem section
    # ``installer`` E o arquivo Setup.exe existe em disco, anexamos como
    # artifact da release. Sem installer, fluxo legado intacto (AC2).
    installer_path = DIST_DIR / f"data-downloader-Setup-v{version}.exe"
    has_installer = installer_path.is_file() and bool(manifest.get("installer"))
    if has_installer:
        print(f"[github_release] installer detectado: {installer_path.name}")
    else:
        print("[github_release] installer ausente (fluxo zip-only)")

    if not args.dry_run:
        try:
            _ensure_gh_available()
        except RuntimeError as exc:
            print(f"[github_release] {exc}", file=sys.stderr)
            return 1

    # 2. Extract CHANGELOG section.
    changelog_section = _extract_changelog_section(version)
    if not changelog_section:
        print(
            f"[github_release] WARN: section CHANGELOG.md para v{version} ausente; "
            "release body usará apenas artifact info.",
            file=sys.stderr,
        )

    # 3. Compose body + write to temp file.
    body = _compose_release_body(version, manifest, changelog_section)
    body_path = DIST_DIR / f"release-body-v{version}.md"
    body_path.write_text(body, encoding="utf-8")
    print(f"[github_release] body composed → {body_path}")

    # 4. Invoke gh — anexa Setup.exe se disponível.
    artifacts = [zip_path, manifest_path]
    if has_installer:
        artifacts.append(installer_path)
    try:
        _invoke_gh_release(
            version=version,
            title=f"Data Downloader v{version}",
            body_path=body_path,
            artifacts=artifacts,
            prerelease=bool(args.prerelease),
            dry_run=bool(args.dry_run),
        )
    except RuntimeError as exc:
        print(f"[github_release] GH FAILED: {exc}", file=sys.stderr)
        return 2

    # 5. Append README link (best-effort).
    if not args.dry_run:
        try:
            release_url = _construct_release_url(version, manifest)
            _append_readme_latest(version, release_url)
            print(f"[github_release] README.md atualizado: {release_url}")
        except OSError as exc:
            print(f"[github_release] WARN: README append falhou: {exc}", file=sys.stderr)
            return 3

    suffix = "(dry-run)" if args.dry_run else "published"
    print(f"[github_release] OK — release v{version} {suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
