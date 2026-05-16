"""scripts/build_release.py — Orquestrador de build release V1 (Story 4.4).

Owner: Gage (devops). Felix mantém ``build/data_downloader.spec.template``;
este script gera o spec final com tokens substituídos, seta env vars
determinísticas (ADR-009 §"Camada 2"), invoca PyInstaller, valida output
e emite ``build-manifest-v{version}.json``.

Uso:
    python scripts/build_release.py [--dry-run] [--version X.Y.Z]

Modos:
    --dry-run        Não invoca PyInstaller; apenas valida spec template +
                     emite manifest stub. Usado por
                     ``tests/integration/test_build_release_dry.py``.
    --version X.Y.Z  Força versão (default: lê de ``pyproject.toml``).

Pipeline:

    1. Lê versão de ``pyproject.toml`` (ou ``--version``).
    2. Captura git SHA + commit timestamp (para ``SOURCE_DATE_EPOCH``).
    3. Seta env vars determinísticas:
       - ``PYTHONHASHSEED=0``
       - ``SOURCE_DATE_EPOCH=<commit-timestamp>``
       - ``PYTHONDONTWRITEBYTECODE=1``
       - ``TZ=UTC``
       - ``LC_ALL=C.UTF-8``
    4. Gera ``build/data_downloader.spec`` substituindo tokens
       (``{{VERSION}}``, ``{{BUILD_TIMESTAMP}}``, ``{{ICON_PATH}}``).
       Spec final é artefato derivado — NÃO commitado (gitignore).
    5. Invoca ``python -m PyInstaller build/data_downloader.spec
       --noconfirm --clean`` (skip se ``--dry-run``).
    6. Valida output:
       - ``dist/data_downloader/data_downloader.exe`` existe (UI windowed).
       - ``dist/data_downloader/data_downloader-cli.exe`` existe (CLI console).
         (Story 4.8 dual EXE — Pichau directive 2026-05-06, council Aria
         Opção A: separar default UI sem janela preta de CLI explícita.)
       - DLLs companions presentes.
       - Tamanho total no range esperado (50-200 MB).
    7. Computa SHA256 de cada arquivo no ``dist/data_downloader/``
       (sorted by path).
    8. Empacota ``dist/data-downloader-v{version}-win64.zip``
       deterministicamente (ZIP_DEFLATED + sorted entries +
       fixed mtime via ``SOURCE_DATE_EPOCH``).
9. Emite ``dist/build-manifest-v{version}.json``:
       {
         "version": "1.0.0",
         "git_sha": "abc123...",
         "git_short_sha": "abc1234",
         "build_timestamp_iso": "2026-05-04T12:34:56Z",
         "source_date_epoch": 1700000000,
         "builder_hostname_sanitized": "ci-runner-XXXX",
         "spec_template_sha256": "...",
         "files": {
           "data_downloader.exe": {"size_bytes": ..., "sha256": "..."},
           ...
         },
         "zip": {
           "path": "data-downloader-v1.0.0-win64.zip",
           "size_bytes": ...,
           "sha256": "..."
         },
         "total_size_bytes": ...,
         "warnings": []  # populated if smoke divergence
       }

Limitações V1.0 (deferred V1.1):

    - Não roda em container Docker Windows (camada 4 ADR-009 deferred —
      Story 4.4-followup).
    - Não verifica determinismo bit-exato cross-build (camada 5 ADR-009
      deferred — exige CI controlled).

Saída exit codes:

    0  = success
    1  = pre-condition failed (missing file, invalid version, etc.)
    2  = PyInstaller failed
    3  = post-validation failed (output missing/corrupt)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# =====================================================================
# Constantes
# =====================================================================

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
BUILD_DIR: Final[Path] = REPO_ROOT / "build"
SPEC_TEMPLATE: Final[Path] = BUILD_DIR / "data_downloader.spec.template"
SPEC_FINAL: Final[Path] = BUILD_DIR / "data_downloader.spec"
DIST_DIR: Final[Path] = REPO_ROOT / "dist"
PYPROJECT_TOML: Final[Path] = REPO_ROOT / "pyproject.toml"
ICON_PATH_REL: Final[str] = "../src/data_downloader/ui/assets/icon.ico"
INSTALLER_DIR: Final[Path] = REPO_ROOT / "installer"
INSTALLER_ISS: Final[Path] = INSTALLER_DIR / "data_downloader.iss"

# Output directory name produced by spec (matches spec.coll.name).
ONEDIR_NAME: Final[str] = "data_downloader"

# Story 4.8 (Pichau directive 2026-05-06, council Aria Opção A): bundle agora
# emite DOIS executáveis no mesmo onedir — `data_downloader.exe` (windowed,
# default UI) e `data_downloader-cli.exe` (console, CLI explícita). Ambos
# precisam estar presentes no output para o build ser válido.
REQUIRED_EXECUTABLES: Final[tuple[str, ...]] = (
    "data_downloader.exe",
    "data_downloader-cli.exe",
)

# Size sanity range (MB).
#
# Story 4.4 (2026-05-04) inicial: 50-250 MB — estimativa pré-build empírico.
# Story 1.7b-followup release v1.0.0 (2026-05-05): build real entregou 879 MB
# devido a:
#   - Qt6WebEngineCore.dll (195 MB) — Chromium engine (não usado pela UI;
#     vem via ``collect_all('PySide6')`` default).
#   - qtwebengine_devtools_resources*.pak (~83 MB) — WebEngine resources.
#   - DuckDB native (~36 MB) + Arrow (~70 MB) + ProfitDLL (~45 MB) +
#     PySide6 core/widgets (~50 MB) + Python stdlib + numpy/pyarrow.
# Tech debt para v1.1 polish (Story 4.4-followup ou nova): replace
# ``collect_all('PySide6')`` com módulos explícitos (QtCore/Gui/Widgets) +
# excluir WebEngine/Multimedia → estimativa ~400 MB. Não bloqueia v1.0.0.
MIN_SIZE_MB: Final[int] = 50
MAX_SIZE_MB: Final[int] = 1000

# DLL companions that MUST be in output.
REQUIRED_DLL_COMPANIONS: Final[tuple[str, ...]] = (
    "ProfitDLL.dll",
    "libcrypto-1_1-x64.dll",
    "libssl-1_1-x64.dll",
)


# =====================================================================
# Data classes
# =====================================================================


@dataclass(frozen=True)
class BuildContext:
    """Contexto resolvido antes do build."""

    version: str
    git_sha: str
    git_short_sha: str
    source_date_epoch: int
    build_timestamp_iso: str
    dry_run: bool


# =====================================================================
# Helpers
# =====================================================================


def _read_version_from_pyproject() -> str:
    """Extrai ``version = "..."`` de pyproject.toml [project]."""
    if not PYPROJECT_TOML.exists():
        raise FileNotFoundError(f"pyproject.toml ausente em {PYPROJECT_TOML}")
    text = PYPROJECT_TOML.read_text(encoding="utf-8")
    # Match [project] block, then version.
    match = re.search(
        r'^\s*version\s*=\s*"(?P<v>[^"]+)"',
        text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError("Campo version não encontrado em pyproject.toml")
    return match["v"]


def _run_git(args: list[str], cwd: Path) -> str:
    """Roda ``git`` e retorna stdout (stripped). Raise em failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _resolve_git_context(repo_root: Path) -> tuple[str, str, int]:
    """Captura ``(git_sha, git_short_sha, commit_timestamp)``.

    Em ambientes sem git (tarball release), retorna placeholders.
    """
    try:
        sha = _run_git(["rev-parse", "HEAD"], repo_root)
        short = _run_git(["rev-parse", "--short", "HEAD"], repo_root)
        ts = int(_run_git(["log", "-1", "--format=%ct"], repo_root))
        return sha, short, ts
    except (RuntimeError, FileNotFoundError, ValueError):
        # Sem git — usar placeholders + epoch fixo (ADR-009 fallback).
        return "0" * 40, "0" * 7, 1700000000


def _sanitize_hostname() -> str:
    """Hostname sanitizado (preserva primeiros 3 + sufixo hash) para audit."""
    raw = os.environ.get("COMPUTERNAME", "") or os.environ.get("HOSTNAME", "") or "unknown"
    # Mantém apenas alphanum + último-dígito-hash truncado para evitar PII.
    clean = re.sub(r"[^A-Za-z0-9]", "", raw)
    if not clean:
        clean = "unknown"
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:8]
    prefix = clean[:3] if len(clean) >= 3 else clean
    return f"{prefix}-XXXX-{digest}"


def _hash_file(path: Path) -> tuple[int, str]:
    """Retorna ``(size_bytes, sha256_hex)`` do arquivo."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return size, h.hexdigest()


# =====================================================================
# Pipeline steps
# =====================================================================


def render_spec(ctx: BuildContext) -> None:
    """Render spec template substituindo tokens. Escreve em SPEC_FINAL.

    Se ``icon.ico`` não existir em assets, troca ``icon=ICON_PATH`` por
    ``icon=None`` no spec (PyInstaller aceita None como "sem ícone custom" —
    usa o default do sistema). Permite build em ambientes sem asset
    customizado (e.g. esta release v1.0.0 ainda não tem icon dedicado;
    Story 4.5 ou follow-up adiciona).
    """
    if not SPEC_TEMPLATE.exists():
        raise FileNotFoundError(f"Template ausente: {SPEC_TEMPLATE}")
    template = SPEC_TEMPLATE.read_text(encoding="utf-8")
    icon_path_resolved = (BUILD_DIR / ICON_PATH_REL).resolve()
    has_icon = icon_path_resolved.is_file()
    rendered = (
        template.replace("{{VERSION}}", ctx.version)
        .replace("{{BUILD_TIMESTAMP}}", ctx.build_timestamp_iso)
        .replace("{{ICON_PATH}}", ICON_PATH_REL if has_icon else "")
    )
    if not has_icon:
        # Substitui o uso da variável por None literal — evita PyInstaller
        # tentar abrir o arquivo (falharia com FileNotFoundError).
        rendered = rendered.replace("icon=ICON_PATH,", "icon=None,")
    SPEC_FINAL.write_text(rendered, encoding="utf-8")


def apply_deterministic_env(ctx: BuildContext) -> dict[str, str]:
    """Seta env vars determinísticas (ADR-009 §"Camada 2"). Retorna snapshot."""
    snapshot = {
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": str(ctx.source_date_epoch),
        "PYTHONDONTWRITEBYTECODE": "1",
        "TZ": "UTC",
        "LC_ALL": "C.UTF-8",
    }
    os.environ.update(snapshot)
    return snapshot


def run_pyinstaller() -> None:
    """Invoca PyInstaller no spec final. Raises on failure."""
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FINAL),
        "--noconfirm",
        "--clean",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PyInstaller failed (rc={result.returncode})")


def validate_output() -> Path:
    """Valida ``dist/data_downloader/`` existe + companions presentes.

    Returns:
        Path da pasta onedir.

    Raises:
        FileNotFoundError: se output ausente.
        ValueError: se DLL companion ausente ou tamanho fora do range.
    """
    onedir = DIST_DIR / ONEDIR_NAME
    if not onedir.is_dir():
        raise FileNotFoundError(f"Output onedir ausente: {onedir}")

    # Story 4.8: dual EXE — ambos `data_downloader.exe` (windowed) e
    # `data_downloader-cli.exe` (console) precisam estar presentes.
    for exe_name in REQUIRED_EXECUTABLES:
        exe_path = onedir / exe_name
        if not exe_path.is_file():
            raise FileNotFoundError(
                f"Executável ausente: {exe_path} (Story 4.8 dual EXE — UI + CLI ambos requeridos)"
            )

    for companion in REQUIRED_DLL_COMPANIONS:
        # PyInstaller 6.x default isola binaries em ``_internal/``. Aceitar
        # ambos: layout legado (DLL sibling ao .exe) e PyI6 (``_internal/``).
        # Spec template tenta forçar legacy via ``contents_directory='.'``
        # mas PyI 6.x ignora silenciosamente — fallback runtime aqui.
        candidates = (onedir / companion, onedir / "_internal" / companion)
        if not any(c.is_file() for c in candidates):
            raise ValueError(
                f"DLL companion ausente: {companion} (procurado em "
                f"{', '.join(str(c) for c in candidates)})"
            )

    total_bytes = sum(p.stat().st_size for p in onedir.rglob("*") if p.is_file())
    total_mb = total_bytes / (1024 * 1024)
    if not (MIN_SIZE_MB <= total_mb <= MAX_SIZE_MB):
        raise ValueError(
            f"Tamanho fora do range esperado: {total_mb:.1f} MB "
            f"(min={MIN_SIZE_MB}, max={MAX_SIZE_MB})"
        )
    return onedir


def compute_file_manifest(onedir: Path) -> dict[str, dict[str, object]]:
    """Retorna ``{relative_path: {size_bytes, sha256}}`` ordenado por path."""
    manifest: dict[str, dict[str, object]] = {}
    files = sorted(p for p in onedir.rglob("*") if p.is_file())
    for path in files:
        rel = path.relative_to(onedir).as_posix()
        size, digest = _hash_file(path)
        manifest[rel] = {"size_bytes": size, "sha256": digest}
    return manifest


def create_deterministic_zip(onedir: Path, version: str, source_date_epoch: int) -> Path:
    """Cria zip determinístico com sorted entries + fixed mtime.

    Returns:
        Path do zip criado.
    """
    zip_path = DIST_DIR / f"data-downloader-v{version}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()

    # ZIP archives use 2-second resolution mtimes via DOS time fields. The
    # tuple is (Y, M, D, H, M, S) — all from SOURCE_DATE_EPOCH UTC.
    fixed_struct = time.gmtime(source_date_epoch)
    fixed_date = (
        fixed_struct.tm_year,
        fixed_struct.tm_mon,
        fixed_struct.tm_mday,
        fixed_struct.tm_hour,
        fixed_struct.tm_min,
        fixed_struct.tm_sec,
    )

    files = sorted(p for p in onedir.rglob("*") if p.is_file())
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as zf:
        for file_path in files:
            arcname = (Path(ONEDIR_NAME) / file_path.relative_to(onedir)).as_posix()
            info = zipfile.ZipInfo(filename=arcname, date_time=fixed_date)
            info.compress_type = zipfile.ZIP_DEFLATED
            # Permissões UNIX 0644 + entry type "regular file" estáveis.
            info.external_attr = (0o644 & 0xFFFF) << 16
            with file_path.open("rb") as src:
                zf.writestr(info, src.read())
    return zip_path


# =====================================================================
# Installer (Story 4.17 — Pichau directive 2026-05-06, integrate v1.0.5)
# =====================================================================


def _resolve_iscc_path() -> Path:
    """Resolve caminho de ``ISCC.exe`` (InnoSetup compiler).

    Preferência:
    1. Variável de ambiente ``ISCC_PATH``.
    2. ``iscc`` no PATH (``shutil.which``).
    3. Caminhos típicos de instalação Windows (Program Files / x86).

    Raises:
        FileNotFoundError: se nenhum caminho válido for encontrado.
    """
    env_path = os.environ.get("ISCC_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate

    on_path = shutil.which("iscc") or shutil.which("ISCC")
    if on_path:
        return Path(on_path)

    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c

    raise FileNotFoundError(
        "InnoSetup compiler (ISCC.exe) não encontrado. Instale via "
        "'winget install JRSoftware.InnoSetup' ou setar ISCC_PATH."
    )


def compile_installer(version: str, repo_root: Path) -> Path:
    """Compila ``installer/data_downloader.iss`` via ISCC e retorna o Setup.exe.

    Pré-condição: ``dist/data_downloader/`` (PyInstaller onedir output) já
    existe — script .iss bundla a pasta. Versão é injetada via flag ``/D``.

    Args:
        version: SemVer (ex. "1.0.5"). Token ``AppVersion`` no .iss.
        repo_root: Raiz do repo (para resolver caminhos relativos).

    Returns:
        Path absoluto do ``data-downloader-Setup-vX.Y.Z.exe`` gerado.

    Raises:
        FileNotFoundError: ISCC ou .iss script ausente, ou Setup.exe não gerado.
        RuntimeError: ISCC retornou rc != 0.
    """
    iscc = _resolve_iscc_path()
    iss_path = repo_root / "installer" / "data_downloader.iss"
    if not iss_path.is_file():
        raise FileNotFoundError(f"InnoSetup script ausente: {iss_path}")

    cmd = [str(iscc), f"/DAppVersion={version}", str(iss_path)]
    result = subprocess.run(
        cmd,
        cwd=str(iss_path.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"InnoSetup compile failed (rc={result.returncode}):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    setup_exe = repo_root / "dist" / f"data-downloader-Setup-v{version}.exe"
    if not setup_exe.is_file():
        raise FileNotFoundError(
            f"Output Setup.exe não foi gerado: {setup_exe} (stdout: {result.stdout[:500]})"
        )
    return setup_exe


def write_build_manifest(
    ctx: BuildContext,
    file_manifest: dict[str, dict[str, object]],
    zip_path: Path | None,
    spec_template_sha256: str,
    warnings: list[str],
    installer_path: Path | None = None,
) -> Path:
    """Escreve ``dist/build-manifest-v{version}.json`` e retorna o path."""
    manifest_path = DIST_DIR / f"build-manifest-v{ctx.version}.json"
    total_size = 0
    for meta in file_manifest.values():
        size_obj = meta["size_bytes"]
        if isinstance(size_obj, int):
            total_size += size_obj
    zip_section: dict[str, object] | None = None
    if zip_path is not None and zip_path.exists():
        zip_size, zip_sha = _hash_file(zip_path)
        zip_section = {
            "path": zip_path.name,
            "size_bytes": zip_size,
            "sha256": zip_sha,
        }
    installer_section: dict[str, object] | None = None
    if installer_path is not None and installer_path.exists():
        ins_size, ins_sha = _hash_file(installer_path)
        installer_section = {
            "path": installer_path.name,
            "size_bytes": ins_size,
            "sha256": ins_sha,
        }
    payload = {
        "version": ctx.version,
        "git_sha": ctx.git_sha,
        "git_short_sha": ctx.git_short_sha,
        "build_timestamp_iso": ctx.build_timestamp_iso,
        "source_date_epoch": ctx.source_date_epoch,
        "builder_hostname_sanitized": _sanitize_hostname(),
        "spec_template_sha256": spec_template_sha256,
        "dry_run": ctx.dry_run,
        "files": file_manifest,
        "zip": zip_section,
        "installer": installer_section,
        "total_size_bytes": total_size,
        "warnings": warnings,
    }
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


# =====================================================================
# CLI entry
# =====================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build release pipeline (Story 4.4).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Não invoca PyInstaller; valida spec + emite manifest stub.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Força versão (default: lê pyproject.toml).",
    )
    parser.add_argument(
        "--with-installer",
        action="store_true",
        help=(
            "Após gerar zip determinístico, compila Setup.exe via InnoSetup "
            "(Story 4.17). Requer ISCC.exe no PATH ou ISCC_PATH env. "
            "Sem flag: build atual permanece intacto (backward compat AC2)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Story 4.31 AC8 — Python pinning guard (R19 / ADR-009):
    # PyInstaller bytecode + bundled stdlib são dependentes da minor
    # version. requires-python>=3.12 em pyproject não é o bastante:
    # build em 3.13/3.14 gera bundle que pode crashar no usuário final
    # (ABI breaks, deprecated stdlib modules). Para garantir
    # reproducibilidade bit-exata cross-build, exigimos 3.12.x explícito.
    #
    # Em ``--dry-run`` o guard é relaxado para warning porque dry-run
    # NÃO invoca PyInstaller (apenas valida spec template + emite
    # manifest stub para tests/integration). Builds reais continuam
    # bloqueados.
    if sys.version_info[:2] != (3, 12):
        msg = (
            f"build requires Python 3.12.x "
            f"(current: {sys.version_info.major}.{sys.version_info.minor}). "
            f"See R19 / ADR-009."
        )
        if args.dry_run:
            print(f"[build_release] WARNING (dry-run): {msg}", file=sys.stderr)
        else:
            print(f"[build_release] ERROR: {msg}", file=sys.stderr)
            return 1

    # 1. Resolve version + git context.
    try:
        version = args.version or _read_version_from_pyproject()
    except (FileNotFoundError, ValueError) as exc:
        print(f"[build_release] PRE-COND FAILED: {exc}", file=sys.stderr)
        return 1

    git_sha, git_short, source_epoch = _resolve_git_context(REPO_ROOT)
    # Story 4.31 AC7 — BUILD_TIMESTAMP determinístico:
    # DERIVADO de SOURCE_DATE_EPOCH (commit timestamp / fallback). NUNCA
    # usar datetime.utcnow() ou time.time() — quebra reproducibilidade
    # bit-exata cross-build (ADR-009 §"Camada 2"). Esta linha é
    # load-bearing: alterá-la requer revisar ADR-009 e re-validar o
    # smoke test test_build_release_dry.
    build_ts_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(source_epoch))

    ctx = BuildContext(
        version=version,
        git_sha=git_sha,
        git_short_sha=git_short,
        source_date_epoch=source_epoch,
        build_timestamp_iso=build_ts_iso,
        dry_run=bool(args.dry_run),
    )

    print(
        f"[build_release] version={ctx.version} git_sha={ctx.git_short_sha} "
        f"epoch={ctx.source_date_epoch} dry_run={ctx.dry_run}"
    )

    # 2. Render spec template.
    try:
        render_spec(ctx)
    except FileNotFoundError as exc:
        print(f"[build_release] SPEC RENDER FAILED: {exc}", file=sys.stderr)
        return 1

    spec_size, spec_template_sha = _hash_file(SPEC_TEMPLATE)
    print(f"[build_release] spec template sha256={spec_template_sha[:16]}... ({spec_size} bytes)")

    # 3. Apply deterministic env vars.
    apply_deterministic_env(ctx)

    warnings: list[str] = []

    if ctx.dry_run:
        # Dry-run: skip PyInstaller, emit stub manifest.
        warnings.append("dry_run=True; PyInstaller não invocado")
        if args.with_installer:
            warnings.append("dry_run=True; --with-installer ignorado (sem onedir input)")
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = write_build_manifest(
            ctx,
            file_manifest={},
            zip_path=None,
            spec_template_sha256=spec_template_sha,
            warnings=warnings,
            installer_path=None,
        )
        print(f"[build_release] DRY-RUN ok — manifest: {manifest_path}")
        return 0

    # 4. Clean dist/ before build (idempotent).
    if DIST_DIR.exists():
        for child in DIST_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    # 5. Run PyInstaller.
    try:
        run_pyinstaller()
    except RuntimeError as exc:
        print(f"[build_release] PYINSTALLER FAILED: {exc}", file=sys.stderr)
        return 2

    # 6. Validate output + compute manifest + zip.
    try:
        onedir = validate_output()
    except (FileNotFoundError, ValueError) as exc:
        print(f"[build_release] VALIDATION FAILED: {exc}", file=sys.stderr)
        return 3

    file_manifest = compute_file_manifest(onedir)
    zip_path = create_deterministic_zip(onedir, ctx.version, ctx.source_date_epoch)

    # Story 4.17 — compilar Setup.exe via InnoSetup quando --with-installer.
    installer_path: Path | None = None
    if args.with_installer:
        try:
            installer_path = compile_installer(ctx.version, REPO_ROOT)
            print(f"[build_release] OK — installer: {installer_path}")
        except (FileNotFoundError, RuntimeError) as exc:
            warnings.append(f"installer_compile_failed: {exc}")
            print(f"[build_release] INSTALLER FAILED: {exc}", file=sys.stderr)
            # Não retornamos rc != 0 aqui: zip + manifest base já existem.
            # Fail loud no log + warning no manifest (operador decide).

    manifest_path = write_build_manifest(
        ctx,
        file_manifest=file_manifest,
        zip_path=zip_path,
        spec_template_sha256=spec_template_sha,
        warnings=warnings,
        installer_path=installer_path,
    )

    print(f"[build_release] OK — onedir: {onedir}")
    print(f"[build_release] OK — zip: {zip_path}")
    print(f"[build_release] OK — manifest: {manifest_path}")
    if installer_path is not None:
        print(f"[build_release] OK — installer: {installer_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
