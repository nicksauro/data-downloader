"""data_downloader.cli.doctor — comando ``doctor`` (Story 4.9).

Owner: Sol (Story 4.28 P0-A1 — split do monolito ``cli.py``).

Diagnóstico do ambiente data-downloader. Owners Council B5 apontou que
6 microcopies + ``_CLI_SUBCOMMANDS`` em ``ui/app.py`` referenciam
``data-downloader doctor``, mas o comando NÃO estava implementado no
Typer CLI até esta story (v1.0.3 hotfix).

Checks (5 default + 1 opt-in):

1. DLL companions — ProfitDLL.dll + .dat companions presentes
2. Credenciais     — PROFITDLL_KEY/USER/PASS em os.environ não-vazios
3. Disk            — data_dir writável, espaço livre >100MB
4. Schema          — catalog SQLite acessível, schema_version >= 1.1.0
5. Connectivity    — DNS+TCP servers Nelogica (lightweight)
6. DLL handshake   — opt-in (--with-handshake) — initialize_market_only quick

Exit codes:
  - 0 — todos os checks PASS (inclui WARN se schema antigo, mas sem fail)
  - 1 — 1+ checks FAIL
  - 2 — erro inesperado (defensivo)

**IMPORTANTE (test backward-compat):** os helpers ``_check_*`` e a função
``run_doctor_checks`` são re-exportados via ``data_downloader.cli`` para
preservar o test surface (e.g. ``tests/unit/test_cli_doctor.py`` faz
``monkeypatch.setattr(cli_module, "_check_dll_companions", ...)`` para
mockar checks). Por isso ``run_doctor_checks`` resolve os helpers via
o **pacote** ``data_downloader.cli`` em runtime — late binding garante
que monkey-patches são efetivos.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel
from rich.table import Table

from data_downloader.cli._helpers import _get_credential, _make_console

if TYPE_CHECKING:
    from rich.console import Console


__all__ = [
    "_check_connectivity",
    "_check_credentials",
    "_check_disk",
    "_check_dll_companions",
    "_check_dll_handshake",
    "_check_schema",
    "doctor",
    "register",
    "run_doctor_checks",
]


def register(app: typer.Typer) -> None:
    """Registra o comando ``doctor`` no ``app`` raiz."""
    app.command()(doctor)


# =====================================================================
# Individual checks
# =====================================================================


def _check_dll_companions() -> tuple[str, str]:
    """Verifica ProfitDLL.dll + companions (.dat / DLLs auxiliares).

    Reusa a lógica de ``scripts/verify-dll-companions.py`` — busca o path
    base via ``DEFAULT_DLL_PATH`` (frozen-aware) ou env ``PROFITDLL_PATH``,
    deriva o diretório base e checa os artefatos esperados.

    Returns:
        Tupla ``(status, msg)`` — ``status`` ∈ ``{"PASS","FAIL","WARN"}``.
    """
    try:
        from data_downloader.dll.wrapper import DEFAULT_DLL_PATH
    except Exception as exc:  # pragma: no cover defensive
        return "FAIL", f"Falha ao importar wrapper: {exc}"

    env_path = os.getenv("PROFITDLL_PATH")
    if env_path:
        dll_path = Path(env_path)
        if not dll_path.is_absolute():
            # Mesma lógica de ProfitDLL.__init__ — relativo é dev-only.
            dll_path = DEFAULT_DLL_PATH
    else:
        dll_path = DEFAULT_DLL_PATH

    base_dir = dll_path.parent
    if not base_dir.exists():
        return "FAIL", f"Diretório base não existe: {base_dir}"

    # Lista canônica — alinhada com scripts/verify-dll-companions.py.
    required_dlls = (
        "ProfitDLL.dll",
        "libcrypto-1_1-x64.dll",
        "libssl-1_1-x64.dll",
        "libeay32.dll",
        "ssleay32.dll",
    )
    required_dats = (
        "timezone2.dat",
        "holidays.dat",
        "exchangeinfo2.dat",
        "newagents.dat",
    )

    missing: list[str] = []
    for name in (*required_dlls, *required_dats):
        if not (base_dir / name).is_file():
            missing.append(name)

    if missing:
        sample = ", ".join(missing[:3])
        more = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
        return "FAIL", f"{len(missing)} ausente(s) em {base_dir}: {sample}{more}"
    return "PASS", f"OK em {base_dir} ({len(required_dlls)} DLLs + {len(required_dats)} .dat)"


def _check_credentials() -> tuple[str, str]:
    """Verifica PROFITDLL_KEY/USER/PASS em ``os.environ``.

    Aceita também o naming legado ``PROFIT_USER`` / ``PROFIT_PASS`` (B2 —
    backwards-compat). Quando só legacy existe, retorna ``WARN``.
    """
    key = os.getenv("PROFITDLL_KEY")
    user = os.getenv("PROFITDLL_USER")
    password = os.getenv("PROFITDLL_PASS")
    legacy_user = os.getenv("PROFIT_USER")
    legacy_pass = os.getenv("PROFIT_PASS")

    missing: list[str] = []
    if not key:
        missing.append("PROFITDLL_KEY")
    if not user and not legacy_user:
        missing.append("PROFITDLL_USER")
    if not password and not legacy_pass:
        missing.append("PROFITDLL_PASS")

    if missing:
        return "FAIL", f"Ausentes: {', '.join(missing)}"

    if (not user and legacy_user) or (not password and legacy_pass):
        return "WARN", "OK via naming legado (PROFIT_USER/PASS) — migre para PROFITDLL_*."
    return "PASS", "PROFITDLL_KEY/USER/PASS preenchidos."


def _check_disk(data_dir: Path) -> tuple[str, str]:
    """Verifica que ``data_dir`` é writável e tem >100MB livres."""
    import shutil as _shutil

    target = data_dir if data_dir.exists() else data_dir.parent
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return "FAIL", f"Não posso criar {data_dir}: {exc}"

    # Probe write — cria + remove arquivo dummy (idempotente).
    probe = target / ".doctor_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return "FAIL", f"{target} não é writável: {exc}"

    try:
        usage = _shutil.disk_usage(str(target))
    except OSError as exc:
        return "WARN", f"Não consegui medir espaço livre: {exc}"

    free_mb = usage.free / (1024 * 1024)
    free_gb = free_mb / 1024
    if free_mb < 100:
        return "FAIL", f"Espaço crítico: {free_mb:.1f} MB livres em {target}"
    return "PASS", f"writável, {free_gb:.1f} GB livres em {target}"


def _check_schema(data_dir: Path) -> tuple[str, str]:
    """Verifica catalog SQLite acessível + schema_version >= 1.1.0 (ADR-024 path)."""
    db_path = data_dir / "_internal" / "catalog.db"
    if not db_path.exists():
        # First-run / pre-init é WARN (não FAIL) — catalog vazio é estado válido.
        return "WARN", f"catalog.db não existe ainda ({db_path})"

    try:
        import sqlite3

        # ``isolation_level=None`` evita lock; usamos só SELECT.
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT value FROM _schema_meta WHERE key = 'catalog_version' LIMIT 1"
            )
            row = cursor.fetchone()
    except sqlite3.Error as exc:
        return "FAIL", f"Erro abrindo catalog: {exc}"
    except Exception as exc:  # pragma: no cover defensive
        return "FAIL", f"Erro inesperado: {exc}"

    if row is None:
        return "WARN", "catalog acessível mas sem catalog_version em _schema_meta"

    found_version = str(row[0]).strip()
    # Comparação semver simples major.minor.patch.
    try:
        parts = [int(p) for p in found_version.split(".")[:3]]
    except ValueError:
        return "WARN", f"catalog_version não-semver: {found_version}"

    while len(parts) < 3:
        parts.append(0)
    if parts < [1, 1, 0]:
        return "WARN", f"catalog_version={found_version} (< 1.1.0; rode `migrate execute`)"
    return "PASS", f"catalog_version={found_version}"


def _check_connectivity() -> tuple[str, str]:
    """Ping lightweight a servidores Nelogica via DNS resolve + TCP open."""
    import socket

    hosts: tuple[tuple[str, int], ...] = (
        ("nelogica.com.br", 443),
        ("profitchart.com.br", 443),
    )
    last_err: str = ""
    ok_count = 0
    for host, port in hosts:
        try:
            with socket.create_connection((host, port), timeout=3.0):
                ok_count += 1
        except (socket.gaierror, OSError) as exc:
            last_err = f"{host}:{port} → {exc}"

    if ok_count == 0:
        return "FAIL", f"Nenhum host alcançável ({last_err})"
    if ok_count < len(hosts):
        return "WARN", f"{ok_count}/{len(hosts)} hosts alcançáveis ({last_err})"
    return "PASS", f"{ok_count}/{len(hosts)} hosts alcançáveis"


def _check_dll_handshake() -> tuple[str, str]:
    """Probe DLL handshake (opt-in via ``--with-handshake``)."""
    if sys.platform != "win32":
        return "WARN", "Skipped — DLL é Win64-only (plataforma atual: " + sys.platform + ")"

    key = _get_credential("PROFITDLL_KEY")
    user = _get_credential("PROFITDLL_USER", "PROFIT_USER")
    password = _get_credential("PROFITDLL_PASS", "PROFIT_PASS")
    if not (key and user and password):
        return "FAIL", "Credenciais ausentes — não posso fazer handshake"

    try:
        from data_downloader.dll.wrapper import ProfitDLL
    except Exception as exc:  # pragma: no cover defensive — Linux path
        return "FAIL", f"Falha ao importar ProfitDLL: {exc}"

    try:
        with ProfitDLL() as dll:
            dll.initialize_market_only(key, user, password)
            if not dll.wait_market_connected(timeout=10):
                return "FAIL", "Handshake timeout (10s) — credenciais inválidas?"
    except Exception as exc:
        return "FAIL", f"Handshake falhou: {exc}"
    return "PASS", "MARKET_DATA conectado"


# Module-level singletons p/ typer.Option (evita ruff B008).
_DOCTOR_DATA_DIR_OPT = typer.Option(
    Path("data"), "--data-dir", "-d", help="Raiz dos dados (default: ./data)."
)
_DOCTOR_WITH_HANDSHAKE_OPT = typer.Option(
    False,
    "--with-handshake",
    help=(
        "Inclui DLL handshake real (mais lento, ~3-10s). Default: False — "
        "apenas checks estáticos (DLL companions / creds / disk / schema / DNS)."
    ),
)
_DOCTOR_VERBOSE_OPT = typer.Option(
    False, "--verbose", "-V", help="Imprime detalhes adicionais por check."
)


def run_doctor_checks(
    *,
    data_dir: Path,
    with_handshake: bool = False,
    console: Console | None = None,
    verbose: bool = False,
) -> tuple[int, list[tuple[str, str, str]]]:
    """Executa todos os checks e renderiza resultado.

    Pure function — separa lógica de ``sys.exit`` p/ permitir reuso pela UI
    Settings (botão "Diagnóstico Completo"). Retorna tupla ``(exit_code,
    results)`` onde ``results`` é lista de ``(check_name, status, msg)``.

    **Backward-compat (test surface):** resolve cada helper ``_check_*`` via
    o pacote ``data_downloader.cli`` (late binding) para que monkey-patches
    em ``cli_module._check_dll_companions = ...`` (em
    ``tests/unit/test_cli_doctor.py``) sejam efetivos. Sem isso, os helpers
    seriam capturados no closure de import-time e os mocks falhariam.

    Args:
        data_dir: Raiz dos dados (default ``./data``).
        with_handshake: Se True, inclui check DLL handshake real.
        console: Console Rich para output (default: cria novo).
        verbose: Imprime detalhes adicionais.

    Returns:
        Tupla ``(exit_code, results)``:
        - ``exit_code``: 0 se todos PASS/WARN, 1 se algum FAIL.
        - ``results``: ``[(name, status, msg), ...]``.
    """
    if console is None:
        console = _make_console()

    # Late binding via o pacote — preserva monkey-patches.
    from data_downloader import cli as _cli_pkg

    checks: list[tuple[str, tuple[str, str]]] = [
        ("DLL companions", _cli_pkg._check_dll_companions()),
        ("Credenciais", _cli_pkg._check_credentials()),
        ("Disk", _cli_pkg._check_disk(data_dir)),
        ("Schema", _cli_pkg._check_schema(data_dir)),
        ("Connectivity", _cli_pkg._check_connectivity()),
    ]
    if with_handshake:
        checks.append(("DLL handshake", _cli_pkg._check_dll_handshake()))

    results: list[tuple[str, str, str]] = [(name, status, msg) for name, (status, msg) in checks]

    # Render Rich table.
    table = Table(title="data-downloader doctor — Diagnóstico", show_lines=False)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold", no_wrap=True)
    table.add_column("Detail", overflow="fold")

    icons = {
        "PASS": "[green]✓ PASS[/green]",
        "FAIL": "[red]✗ FAIL[/red]",
        "WARN": "[yellow]? WARN[/yellow]",
    }
    for name, status, msg in results:
        table.add_row(name, icons.get(status, status), msg)
    console.print(table)

    n_fail = sum(1 for _, status, _ in results if status == "FAIL")
    n_warn = sum(1 for _, status, _ in results if status == "WARN")
    n_pass = sum(1 for _, status, _ in results if status == "PASS")

    if n_fail == 0:
        summary = (
            f"[green]OK[/green] — {n_pass} PASS"
            + (f", {n_warn} WARN" if n_warn else "")
            + " (sem fails)."
        )
        console.print(Panel(summary, title="OK", border_style="green"))
        exit_code = 0
    else:
        summary = (
            f"[red]FAIL[/red] — {n_fail} fail(s), {n_warn} warn(s), {n_pass} pass.\n"
            "Inspecione tabela acima e corrija os items vermelhos."
        )
        console.print(Panel(summary, title="FAIL", border_style="red"))
        exit_code = 1

    if verbose:
        console.print("[dim]Verbose: results = " + repr(results) + "[/dim]")

    return exit_code, results


def doctor(
    data_dir: Path = _DOCTOR_DATA_DIR_OPT,
    with_handshake: bool = _DOCTOR_WITH_HANDSHAKE_OPT,
    verbose: bool = _DOCTOR_VERBOSE_OPT,
) -> None:
    """Diagnóstico completo do ambiente data-downloader.

    Verifica:

    - **DLL companions**: ``ProfitDLL.dll`` + ``.dat`` companions presentes
      no path resolvido (env ``PROFITDLL_PATH`` ou default frozen-aware).
    - **Credenciais**: ``PROFITDLL_KEY/USER/PASS`` em ``os.environ``
      (não-vazios; aceita naming legado com WARN).
    - **Disk**: ``data_dir`` writável e espaço livre >100MB.
    - **Schema**: catalog SQLite acessível, ``schema_version >= 1.1.0``.
    - **Connectivity**: DNS+TCP para servidores Nelogica (porta 443).
    - **DLL handshake** (opt-in via ``--with-handshake``): invoca
      ``initialize_market_only`` quick + aguarda MARKET_DATA conectar
      (~10s timeout).

    Exit codes:
        - ``0``: todos os checks PASS/WARN.
        - ``1``: 1+ checks FAIL.

    Story 4.9 (v1.0.3 hotfix — Owners Council B5).
    """
    # Late binding via o pacote — preserva monkey-patches do test surface.
    from data_downloader import cli as _cli_pkg

    exit_code, _ = _cli_pkg.run_doctor_checks(
        data_dir=data_dir,
        with_handshake=with_handshake,
        verbose=verbose,
    )
    raise typer.Exit(code=exit_code)
