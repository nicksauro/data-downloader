"""Data Downloader CLI entry point.

Ponto de entrada para o comando ``data-downloader`` (definido em
``pyproject.toml`` -> ``[project.scripts]``).

Story 1.1 entregou ``version``. Story 1.6 adiciona o grupo ``contracts``
(list / add / validate / vigent) — operações sobre o calendário de
contratos vigentes. Story 2.1 adiciona o grupo ``integrity`` (check /
validate-data) — validators executáveis (Sol+Quinn). Story 1.7b adiciona
o comando ``download`` — gate de smoke MVP (Epic 1).

Microcopy IDs (Uma — ``MICROCOPY_CATALOG.md``):
- ``CMD_CONTRACTS`` (group label)
- ``HLP_CONTRACTS`` (group help)
- ``BTN_LIST_CONTRACTS`` (list subcommand label)
- ``BTN_VALIDATE_CONTRACT`` (validate subcommand label)
- ``ERR_INVALID_CONTRACT`` (mensagem de erro vigent)
- ``HLP_VALIDATE`` (validate subcommand summary)
- ``integrity.check.title`` (panel title — Story 2.1)
- ``integrity.pass`` / ``integrity.fail`` (verdict labels — Story 2.1)
- ``HLP_DOWNLOAD``, ``SUC_DOWNLOAD_DONE``, ``SUC_CACHE_HIT``,
  ``SUC_CANCEL_DONE``, ``WAR_99_RECONNECT``, ``PMT_CANCEL_CONFIRM``,
  ``ERR_DLL_NO_LICENSE``, ``ERR_INPUT_*`` (Story 1.7b — comando download)
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

# Q-DRIFT-04 (smoke 2026-05-04): força UTF-8 para stdout/stderr ANTES de
# importar Rich/typer. Em Windows, console default cp1252 causa
# UnicodeEncodeError ao tentar emitir emojis em Rich Panel ("⚡", "✓", etc).
# Setar via env não basta porque Python 3.12+ pode já ter populado os
# wrappers — usamos ``reconfigure`` quando disponível (Python 3.7+).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
# ``reconfigure`` é no-op se streams forem TextIO redirecionado (subprocess);
# em terminal real reconfigura encoding sem perda de buffer.
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None:
        _reconfigure = getattr(_stream, "reconfigure", None)
        if callable(_reconfigure):
            with contextlib.suppress(Exception):
                _reconfigure(encoding="utf-8", errors="replace")

import typer  # noqa: E402  Q-DRIFT-04: encoding setup precisa rodar antes
from rich.console import Console  # noqa: E402  Q-DRIFT-04
from rich.panel import Panel  # noqa: E402  Q-DRIFT-04
from rich.progress import (  # noqa: E402  Q-DRIFT-04
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table  # noqa: E402  Q-DRIFT-04

if TYPE_CHECKING:
    from data_downloader.storage.catalog import Catalog
    from data_downloader.validation.integrity import IntegrityReport

# Story 2.1 — module-level singletons p/ typer.Option (evita ruff B008).
_DATA_DIR_OPT = typer.Option(
    Path("data"), "--data-dir", "-d", help="Raiz dos dados (default: ./data)."
)

app = typer.Typer(
    name="data-downloader",
    help="Downloader de histórico de ativos via ProfitDLL.",
    no_args_is_help=True,
)


# Story 2.9 — flags globais de logging (ADR-010 / AC5).
_LOG_LEVEL_OPT = typer.Option(
    None,
    "--log-level",
    help=(
        "Nível de log: DEBUG | INFO | WARNING | ERROR | CRITICAL. "
        "Default: INFO. Override via env DATA_DOWNLOADER_LOG_LEVEL."
    ),
)
_LOG_FORMAT_OPT = typer.Option(
    None,
    "--log-format",
    help=(
        "Formato de log: 'json' (production) ou 'console' (dev — colorido). "
        "Default: heurística TTY (console se interactive, json se pipe). "
        "Override via env DATA_DOWNLOADER_LOG_FORMAT."
    ),
)


def _resolve_default_format() -> str:
    """Heurística TTY-aware (ADR-010 / Story 2.9 AC5):

    - ``stderr`` é TTY (interactive shell) → ``"console"`` (humano-readable).
    - ``stderr`` não-TTY (pipe, redirect, CI) → ``"json"`` (machine-parseable).
    """
    try:
        if sys.stderr.isatty():
            return "console"
    except (AttributeError, ValueError):  # pragma: no cover defensive
        pass
    return "json"


@app.callback()  # type: ignore[misc]
def _global_callback(
    log_level: str | None = _LOG_LEVEL_OPT,
    log_format: str | None = _LOG_FORMAT_OPT,
) -> None:
    """Boot global do CLI — configura logging UMA vez (Story 2.9 / ADR-010).

    Resolve precedência (CLI flag > env var > default):

    - ``--log-level`` > ``DATA_DOWNLOADER_LOG_LEVEL`` > ``"INFO"``
    - ``--log-format`` > ``DATA_DOWNLOADER_LOG_FORMAT`` > heurística TTY
    """
    from data_downloader.observability.logging_config import (
        configure_logging,
        resolve_format_from_env,
        resolve_level_from_env,
    )

    level = (log_level or resolve_level_from_env("INFO")).upper()
    fmt: str
    if log_format is not None:
        fmt = log_format.lower()
    else:
        # env var default → resolve com fallback p/ heurística TTY.
        fmt_env = os.environ.get("DATA_DOWNLOADER_LOG_FORMAT")
        if fmt_env:
            fmt = resolve_format_from_env(_resolve_default_format())  # type: ignore[arg-type]
        else:
            fmt = _resolve_default_format()

    json_output = fmt == "json"
    configure_logging(level=level, json_output=json_output, redact=True)


# =====================================================================
# contracts subcommand group (Story 1.6)
# =====================================================================

contracts_app = typer.Typer(
    name="contracts",
    help="Operações com contratos vigentes (list, add, validate, vigent).",
    no_args_is_help=True,
)
app.add_typer(contracts_app, name="contracts")


_DEFAULT_CATALOG_PATH = Path("data") / "history" / "catalog.db"


def _open_catalog(db_path: Path | None = None) -> Catalog:
    """Abre o catálogo no path canônico (data/history/catalog.db).

    Import local evita custo de importar storage para comandos que não
    precisam (``version``).
    """
    from data_downloader.storage.catalog import Catalog

    path = db_path if db_path is not None else _DEFAULT_CATALOG_PATH
    return Catalog(db_path=path)


@app.command()  # type: ignore[misc,unused-ignore]
def version() -> None:
    """Print version."""
    from data_downloader import __version__

    typer.echo(f"data-downloader {__version__}")


# ---------------------------------------------------------------------
# contracts list
# ---------------------------------------------------------------------


@contracts_app.command("list")  # type: ignore[misc,unused-ignore]
def contracts_list(
    root: str | None = typer.Option(
        None,
        "--root",
        "-r",
        help="Filtra por raiz (ex.: WDO, WIN, PETR4). Default: lista todos.",
    ),
) -> None:
    """Lista contratos cadastrados no catálogo (BTN_LIST_CONTRACTS).

    Vazio → mensagem amigável (microcopy ``EMP_CONTRACTS_LIST``).
    """
    from data_downloader.orchestrator.contracts import list_contracts

    console = Console()
    catalog = _open_catalog()
    try:
        rows = list_contracts(catalog, root=root)
    finally:
        catalog.close()

    if not rows:
        console.print(
            "[yellow]Nenhum contrato cadastrado[/yellow] "
            f"{'(filtro: ' + root + ')' if root else ''}\n"
            "Adicione com: [bold]data-downloader contracts add WDO J 26[/bold]"
        )
        return

    title = "Contratos vigentes" + (f" — root={root}" if root else "")
    table = Table(title=title, show_lines=False)
    table.add_column("Root", style="cyan")
    table.add_column("Code", style="bold")
    table.add_column("Vigent From")
    table.add_column("Vigent Until")
    table.add_column("Validated", style="green")
    table.add_column("Source")
    table.add_column("Notes", overflow="fold")

    for c in rows:
        table.add_row(
            c.symbol_root,
            c.contract_code,
            c.vigent_from.date().isoformat(),
            c.vigent_until.date().isoformat(),
            c.validated_at.strftime("%Y-%m-%d %H:%M") if c.validated_at else "-",
            c.validation_source,
            c.notes or "",
        )

    console.print(table)


# ---------------------------------------------------------------------
# contracts add
# ---------------------------------------------------------------------


@contracts_app.command("add")  # type: ignore[misc,unused-ignore]
def contracts_add(
    root: str = typer.Argument(..., help="Raiz do contrato (ex.: WDO)."),
    month_letter_arg: str = typer.Argument(
        ..., metavar="MONTH_LETTER", help="Letra de mês CME/B3 (F..Z, exceto I/L)."
    ),
    year: int = typer.Argument(..., help="Ano com 2 ou 4 dígitos (ex.: 26 ou 2026)."),
    notes: str = typer.Option(
        "",
        "--notes",
        "-n",
        help="Observações livres (validation_source = 'hypothesized' por padrão).",
    ),
) -> None:
    """Adiciona contrato ao catálogo (UPSERT) com vigência hipotetizada.

    Calcula vigência conforme regra documentada em CONTRACTS.md §2.1
    (WDO mensal): ``vigent_from = penúltimo dia útil mês X-1``,
    ``vigent_until = penúltimo dia útil mês X`` — aproximada como
    ``X-1/29`` → ``X/28`` para evitar dependência de calendário B3
    completo nesta story (Story 1.7+ refinará). Validação real só após
    probe (``data-downloader contracts validate``).
    """
    from data_downloader.orchestrator.contracts import (
        Contract,
        _format_ts,
        month_from_letter,
    )

    console = Console()

    try:
        month = month_from_letter(month_letter_arg)
    except ValueError as exc:
        console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    full_year = year + 2000 if year < 100 else year
    contract_code = f"{root}{month_letter_arg.upper()}{full_year % 100:02d}"

    # Hipótese conservadora — janela ampla; refinada após probe.
    prev_month = month - 1 if month > 1 else 12
    prev_year = full_year if month > 1 else full_year - 1
    vigent_from = datetime(prev_year, prev_month, _safe_day(prev_year, prev_month, 26))
    vigent_until = datetime(full_year, month, _safe_day(full_year, month, 28))

    contract = Contract(
        symbol_root=root,
        contract_code=contract_code,
        vigent_from=vigent_from,
        vigent_until=vigent_until,
        validated_at=None,
        validation_source="hypothesized",
        notes=notes or "Added via 'contracts add'. Validate via probe.",
    )

    catalog = _open_catalog()
    try:
        conn = catalog._conn_or_raise()
        with catalog._transaction():
            conn.execute(
                """
                INSERT INTO contracts(
                    symbol_root, contract_code, vigent_from, vigent_until,
                    validated_at, validation_source, notes
                ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(symbol_root, contract_code) DO UPDATE SET
                    vigent_from       = excluded.vigent_from,
                    vigent_until      = excluded.vigent_until,
                    validation_source = excluded.validation_source,
                    notes             = excluded.notes
                """,
                (
                    contract.symbol_root,
                    contract.contract_code,
                    _format_ts(contract.vigent_from),
                    _format_ts(contract.vigent_until),
                    contract.validation_source,
                    contract.notes,
                ),
            )
    finally:
        catalog.close()

    console.print(
        f"[green]+[/green] Contrato adicionado: [bold]{contract_code}[/bold] "
        f"(vigent_from={vigent_from.date().isoformat()}, "
        f"vigent_until={vigent_until.date().isoformat()})\n"
        "Source: [yellow]hypothesized[/yellow] — "
        f"valide com: [bold]data-downloader contracts validate {root} {contract_code}[/bold]"
    )


# ---------------------------------------------------------------------
# contracts validate (probe via DLL)
# ---------------------------------------------------------------------


@contracts_app.command("validate")  # type: ignore[misc,unused-ignore]
def contracts_validate(
    root: str = typer.Argument(..., help="Raiz (ex.: WDO)."),
    contract_code: str = typer.Argument(..., help="Código completo (ex.: WDOJ26)."),
    sample_date: str | None = typer.Option(
        None,
        "--sample-date",
        "-d",
        help="Data ISO do probe (YYYY-MM-DD). Default: vigent_from + 1 dia.",
    ),
) -> None:
    """Valida contrato via probe DLL (BTN_VALIDATE_CONTRACT, AC6).

    Inicializa a DLL com credenciais de env (PROFITDLL_KEY / PROFITDLL_USER /
    PROFITDLL_PASS) e chama :func:`probe_contract`. Em sucesso atualiza
    ``validated_at`` no catálogo (AC7).

    Q-DRIFT-03 (smoke 2026-05-04): nomes alinhados com ``.env.example`` que
    usa o prefixo ``PROFITDLL_*``. Versões anteriores liam ``PROFIT_USER`` /
    ``PROFIT_PASS`` (sem prefixo) — corrigido para evitar smoke real falhar
    com "credenciais ausentes" mesmo após preencher o ``.env``.
    """
    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.orchestrator.contracts_probe import probe_contract

    console = Console()

    key = os.getenv("PROFITDLL_KEY")
    user = os.getenv("PROFITDLL_USER")
    password = os.getenv("PROFITDLL_PASS")
    if not (key and user and password):
        console.print(
            "[red]Credenciais ausentes.[/red] Defina PROFITDLL_KEY, PROFITDLL_USER, "
            "PROFITDLL_PASS em ~/.data-downloader/.env."
        )
        raise typer.Exit(code=3)

    parsed_date: date | None = None
    if sample_date:
        try:
            parsed_date = date.fromisoformat(sample_date)
        except ValueError as exc:
            console.print(f"[red]--sample-date inválido:[/red] {exc}")
            raise typer.Exit(code=2) from exc

    catalog = _open_catalog()
    try:
        with ProfitDLL() as dll:
            dll.initialize_market_only(key, user, password)
            # Q-DRIFT-02: timeout 300s (5 min) — handshake MARKET_DATA pode
            # levar >60s em ambientes lentos / ProfitChart concorrente.
            if not dll.wait_market_connected(timeout=300):
                console.print("[red]DLL não conectou em 300s.[/red]")
                raise typer.Exit(code=4)

            console.print(
                f"Probing [bold]{contract_code}[/bold] " f"(sample_date={parsed_date or 'auto'})..."
            )
            result = probe_contract(
                dll=dll,
                catalog=catalog,
                symbol_root=root,
                contract_code=contract_code,
                sample_date=parsed_date,
            )
    finally:
        catalog.close()

    if result.success:
        console.print(
            f"[green]OK[/green] {contract_code} validated "
            f"(date={result.sample_date.isoformat()}, "
            f"trades={result.trades_count}). "
            "Catalog updated (validation_source=dll_probe)."
        )
    else:
        console.print(
            f"[red]FAILED[/red] {contract_code} probe failed "
            f"(date={result.sample_date.isoformat()}, "
            f"trades={result.trades_count}, reason={result.reason})."
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------
# contracts vigent
# ---------------------------------------------------------------------


@contracts_app.command("vigent")  # type: ignore[misc,unused-ignore]
def contracts_vigent(
    root: str = typer.Argument(..., help="Raiz (ex.: WDO)."),
    on_date: str = typer.Argument(..., metavar="DATE", help="Data ISO (YYYY-MM-DD)."),
    exchange: str = typer.Option(
        "F", "--exchange", "-e", help="Bolsa: F (BMF, default) ou B (Bovespa)."
    ),
) -> None:
    """Resolve contrato vigente em ``DATE`` (lookup, ERR_INVALID_CONTRACT em falha)."""
    from data_downloader.orchestrator.contracts import vigent_contract
    from data_downloader.public_api.exceptions import InvalidContract

    console = Console()
    try:
        parsed = date.fromisoformat(on_date)
    except ValueError as exc:
        console.print(f"[red]Data inválida:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    catalog = _open_catalog()
    try:
        try:
            code = vigent_contract(catalog, root, parsed, exchange=exchange)
        except InvalidContract as exc:
            # Microcopy ERR_INVALID_CONTRACT: nome canônico em UI.
            console.print(
                f"[red]Contrato fora do calendário:[/red] {exc}\n"
                "Liste vigentes: [bold]data-downloader contracts list[/bold]"
            )
            raise typer.Exit(code=1) from exc
    finally:
        catalog.close()

    console.print(code)


# =====================================================================
# Helpers
# =====================================================================


def _safe_day(year: int, month: int, day: int) -> int:
    """Clamp ``day`` para o último dia válido do mês (sem calendário externo)."""
    # 28 é seguro para qualquer mês; usamos o ``min`` para preservar
    # intent quando ``day`` é menor (ex.: 26 em fev).
    days_in_month = {
        1: 31,
        2: 28,
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 31,
    }
    # Bissexto: se mês=2 e ano divisível por 4 (e não 100, exceto 400).
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        days_in_month[2] = 29
    return min(day, days_in_month[month])


# =====================================================================
# integrity subcommand group (Story 2.1 — Sol+Quinn)
# =====================================================================

integrity_app = typer.Typer(
    name="integrity",
    help="Validar integridade de dados baixados (Sol+Quinn — Story 2.1).",
    no_args_is_help=True,
)
app.add_typer(integrity_app, name="integrity")


def _open_catalog_for_validation(data_dir: Path) -> Catalog:
    """Abre o catálogo em ``{data_dir}/history/catalog.db`` (sem reconcile auto).

    Variant de :func:`_open_catalog` que respeita ``data_dir`` arbitrário
    (a versão de ``contracts`` usa o path canônico fixo).
    """
    from data_downloader.storage.catalog import Catalog as _Catalog

    db_path = data_dir / "history" / "catalog.db"
    return _Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)


def _print_integrity_table(report: IntegrityReport, console: Console) -> None:
    """Imprime tabela Rich com os checks do :class:`IntegrityReport`."""
    table = Table(title="integrity.check.title — Integrity Report", show_lines=False)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Result", style="bold")
    table.add_column("Severity", style="dim")
    table.add_column("Message")
    for c in report.checks:
        result_text = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
        table.add_row(c.name, result_text, c.severity, c.message)
    console.print(table)


@integrity_app.command("check")  # type: ignore[misc,unused-ignore]
def integrity_check(
    symbol: str | None = typer.Option(
        None, "--symbol", "-s", help="Restringe ao símbolo (ex. WDOJ26). Default: todos."
    ),
    exchange: str = typer.Option(
        "F", "--exchange", "-e", help="Bolsa: 'F' (BMF, default) ou 'B' (Bovespa)."
    ),
    data_dir: Path = _DATA_DIR_OPT,
) -> None:
    """Roda IntegrityChecker.run_all e imprime relatório Rich.

    Exit code: ``0`` se todos os checks passaram; ``2`` se houve violação.
    """
    from data_downloader.validation.integrity import IntegrityChecker

    console = Console()
    catalog = _open_catalog_for_validation(data_dir)
    checker = IntegrityChecker(data_dir=data_dir, catalog=catalog)
    try:
        report = checker.run_all(symbol=symbol, exchange=exchange)
        _print_integrity_table(report, console)

        if report.overall_passed:
            console.print(
                Panel(
                    "[green]integrity.pass[/green] — All invariants hold.\n"
                    f"Hash: {report.hash_canonical}",
                    title="OK",
                    border_style="green",
                )
            )
            raise typer.Exit(code=0)

        console.print(
            Panel(
                "[red]integrity.fail[/red] — One or more invariants violated.\n"
                f"Hash: {report.hash_canonical}\n"
                "Inspect evidence above; consult INTEGRITY.md §1 for invariant IDs.",
                title="FAIL",
                border_style="red",
            )
        )
        raise typer.Exit(code=2)
    finally:
        checker.close()
        with contextlib.suppress(Exception):  # pragma: no cover defensive
            catalog.close()


@integrity_app.command("validate-data")  # type: ignore[misc,unused-ignore]
def integrity_validate_data(
    symbol: str = typer.Option(..., "--symbol", "-s", help="Símbolo (ex. WDOJ26)."),
    start: str = typer.Option(..., "--start", help="Data inicial YYYY-MM-DD."),
    end: str = typer.Option(..., "--end", help="Data final YYYY-MM-DD."),
    exchange: str = typer.Option("F", "--exchange", "-e", help="Bolsa: 'F' (default) ou 'B'."),
    data_dir: Path = _DATA_DIR_OPT,
) -> None:
    """Detecta gaps no dataset de um símbolo contra calendário B3.

    Exit code: ``0`` se nenhum gap (ou apenas holidays); ``2`` se algum
    ``missing_download`` detectado.
    """
    from data_downloader.validation.data_validator import DataValidator

    console = Console()
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError as exc:
        console.print(f"[red]Erro ao parsear datas:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    catalog = _open_catalog_for_validation(data_dir)
    try:
        validator = DataValidator(data_dir=data_dir, catalog=catalog)
        gaps = validator.detect_gaps(symbol, start_date, end_date, exchange=exchange)

        if not gaps:
            console.print(
                Panel(
                    f"[green]integrity.pass[/green] — No gaps in [{start} .. {end}] "
                    f"for {symbol} (exchange={exchange}).",
                    title="OK",
                    border_style="green",
                )
            )
            raise typer.Exit(code=0)

        table = Table(title=f"Gaps in {symbol} [{start} .. {end}]")
        table.add_column("Date", style="cyan")
        table.add_column("Classification", style="bold")
        table.add_column("BD Missing", justify="right")
        for g in gaps:
            cls_color = {
                "holiday": "[dim]holiday[/dim]",
                "no_trades_day": "[yellow]no_trades_day[/yellow]",
                "missing_download": "[red]missing_download[/red]",
            }[g.classification]
            table.add_row(
                g.gap_start.strftime("%Y-%m-%d"),
                cls_color,
                str(g.business_days_missing),
            )
        console.print(table)

        missing_dl = [g for g in gaps if g.classification == "missing_download"]
        if missing_dl:
            console.print(
                Panel(
                    f"[red]integrity.fail[/red] — {len(missing_dl)} missing_download gap(s).",
                    title="FAIL",
                    border_style="red",
                )
            )
            raise typer.Exit(code=2)
        console.print(
            Panel(
                "[green]integrity.pass[/green] — Only holiday gaps detected (acceptable).",
                title="OK",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover defensive
            catalog.close()


# =====================================================================
# download command (Story 1.7b — Epic 1 smoke MVP gate)
# =====================================================================

# Module-level singletons p/ typer.Option (evita ruff B008 conforme Story 2.1).
# Story 4.1 — `--symbol` agora aceita múltiplos valores (typer/click lista
# de strings via repeated flag: --symbol WDOJ26 --symbol WINH26). Quando
# múltiplos símbolos são passados E --parallel > 1, roteamos para
# MultiSymbolMaster (Story 4.1 AC6); caso contrário usa path single-symbol
# existente (Story 1.7b).
_DOWNLOAD_SYMBOL_OPT = typer.Option(
    None,
    "--symbol",
    "-s",
    help=(
        "Símbolo (ex. WDOJ26). Repetível para múltiplos: "
        "--symbol WDOJ26 --symbol WINH26 (Story 4.1). "
        "Default: última usada."
    ),
)
_DOWNLOAD_START_OPT = typer.Option(
    None, "--start", help="Data inicial YYYY-MM-DD. Default: 1º dia do mês corrente."
)
_DOWNLOAD_END_OPT = typer.Option(None, "--end", help="Data final YYYY-MM-DD. Default: hoje.")
_DOWNLOAD_EXCHANGE_OPT = typer.Option(
    "F", "--exchange", "-e", help="Bolsa: F (BMF, default) ou B (Bovespa)."
)
_DOWNLOAD_DATA_DIR_OPT = typer.Option(
    None, "--data-dir", "-d", help="Raiz dos dados (default: ./data)."
)
_DOWNLOAD_RESUME_OPT = typer.Option(
    None, "--resume", help="(Reservado V2) Continuar download por job_id."
)
# Story 4.1 AC6 — `--parallel N` controla número de workers do pool. N=1
# (default) força path single-symbol existente (Story 1.7b — sem broker
# overhead). N>1 com múltiplos símbolos usa MultiSymbolMaster.
_DOWNLOAD_PARALLEL_OPT = typer.Option(
    1,
    "--parallel",
    "-p",
    help=(
        "Número de workers paralelos (Story 4.1). "
        "1 = single-process (default — sem broker overhead). "
        ">1 = pool persistente N workers. Requer múltiplos --symbol."
    ),
    min=1,
    max=16,
)
# Story 2.4 — flag opt-in para Prometheus exporter HTTP.
_DOWNLOAD_METRICS_PORT_OPT = typer.Option(
    None,
    "--metrics-port",
    help=(
        "Porta HTTP do exporter Prometheus (ex.: 9090). "
        "Se omitida, exporter NÃO inicia (default — zero overhead)."
    ),
)


# Path do cache de last_symbol (CLI_PATTERNS §10).
def _last_symbol_cache_path() -> Path:
    return Path.home() / ".data_downloader" / "cache" / "last_symbol.txt"


def _load_last_symbol() -> str | None:
    """Lê último símbolo usado do cache (CLI_PATTERNS §10)."""
    p = _last_symbol_cache_path()
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def _save_last_symbol(symbol: str) -> None:
    """Persiste símbolo no cache (best-effort; falha silenciosa)."""
    p = _last_symbol_cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(symbol, encoding="utf-8")
    except OSError:
        pass


def _default_period() -> tuple[date, date]:
    """Mês corrente — 1º até hoje (CLI_PATTERNS §10)."""
    today = date.today()
    first = date(today.year, today.month, 1)
    return first, today


def _make_console() -> Console:
    """Console Rich respeitando NO_COLOR env (CLI_PATTERNS §9)."""
    if os.environ.get("NO_COLOR") is not None:
        return Console(no_color=True, force_terminal=False, highlight=False)
    return Console()


def _format_microcopy(msg_id: str, field: str = "title", **kwargs: object) -> str:
    """Wrapper local — ensura R17 sem expor o loader em todo lugar."""
    from data_downloader.ui.microcopy_loader import format_msg

    return format_msg(msg_id, field=field, **kwargs)


@app.command("download")  # type: ignore[misc,unused-ignore]
def download_cmd(
    symbol: list[str] | None = _DOWNLOAD_SYMBOL_OPT,
    start: str | None = _DOWNLOAD_START_OPT,
    end: str | None = _DOWNLOAD_END_OPT,
    exchange: str = _DOWNLOAD_EXCHANGE_OPT,
    data_dir: Path | None = _DOWNLOAD_DATA_DIR_OPT,
    resume: str | None = _DOWNLOAD_RESUME_OPT,
    parallel: int = _DOWNLOAD_PARALLEL_OPT,
    metrics_port: int | None = _DOWNLOAD_METRICS_PORT_OPT,
) -> None:
    """Baixa histórico de trades para ``symbol(s)`` em ``[start, end]`` (HLP_DOWNLOAD).

    Story 1.7b — gate de Epic 1 (MVP smoke). Compose:
      CLI typer → public_api.download → Orchestrator (1.7a) → DLL/writer/catalog.

    Story 4.1 (AC6) — multi-symbol via ``--symbol X --symbol Y --parallel N``:
      CLI → MultiSymbolMaster → CatalogBroker (master) + WorkerPool (N procs).

    Microcopy 100% via ``ui.microcopy_loader`` (R17 — Uma).
    Ctrl+C produz graceful shutdown (CLI_PATTERNS §7); exit code 130 (POSIX).
    """
    console = _make_console()
    _ = resume  # placeholder V2

    # ---- 1. Normaliza lista de símbolos (Story 4.1 AC6) ----
    symbols: list[str] = []
    if symbol:
        symbols = [s.strip() for s in symbol if s and s.strip()]

    if not symbols:
        cached = _load_last_symbol()
        if cached:
            symbols = [cached]
            console.print(f"[dim]Símbolo (cache): [bold]{cached}[/bold][/dim]")
        else:
            console.print(
                f"[red]✗ {_format_microcopy('ERR_INPUT_SYMBOL_REQUIRED', 'title')}[/red]\n"
                f"  {_format_microcopy('ERR_INPUT_SYMBOL_REQUIRED', 'detail')}\n"
                f"  {_format_microcopy('ERR_INPUT_SYMBOL_REQUIRED', 'action')}"
            )
            raise typer.Exit(code=2)

    # ---- 1b. Routing: multi-symbol vs single-symbol ----
    use_multi_symbol = parallel > 1 and len(symbols) > 1
    # Mantém compatibilidade: se 1 símbolo ou parallel=1, usa path antigo.
    single_symbol: str = symbols[0]  # path single-symbol usa apenas o primeiro

    if start is None or end is None:
        first, today = _default_period()
        if start is None:
            start = first.isoformat()
        if end is None:
            end = today.isoformat()

    # ---- 2. Parse / validação de datas ----
    try:
        start_date = date.fromisoformat(start)
    except ValueError as exc:
        console.print(
            f"[red]✗ {_format_microcopy('ERR_INPUT_INVALID_DATE', 'title')}[/red]\n"
            f"  {_format_microcopy('ERR_INPUT_INVALID_DATE', 'detail', value=start)}\n"
            f"  {_format_microcopy('ERR_INPUT_INVALID_DATE', 'action')}"
        )
        raise typer.Exit(code=2) from exc
    try:
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        console.print(
            f"[red]✗ {_format_microcopy('ERR_INPUT_INVALID_DATE', 'title')}[/red]\n"
            f"  {_format_microcopy('ERR_INPUT_INVALID_DATE', 'detail', value=end)}\n"
            f"  {_format_microcopy('ERR_INPUT_INVALID_DATE', 'action')}"
        )
        raise typer.Exit(code=2) from exc

    if end_date < start_date:
        console.print(
            f"[red]✗ {_format_microcopy('ERR_INVALID_PERIOD', 'title')}[/red]\n"
            "  "
            + _format_microcopy(
                "ERR_INVALID_PERIOD",
                "detail",
                start=start_date.isoformat(),
                end=end_date.isoformat(),
            )
            + "\n"
            f"  {_format_microcopy('ERR_INVALID_PERIOD', 'action')}"
        )
        raise typer.Exit(code=2)

    today = date.today()
    if end_date > today:
        console.print(
            f"[red]✗ {_format_microcopy('ERR_PERIOD_FUTURE', 'title')}[/red]\n"
            "  "
            + _format_microcopy(
                "ERR_PERIOD_FUTURE",
                "detail",
                end=end_date.isoformat(),
            )
            + "\n"
            "  "
            + _format_microcopy(
                "ERR_PERIOD_FUTURE",
                "action",
                today=today.isoformat(),
            )
        )
        raise typer.Exit(code=2)

    resolved_data_dir = Path(data_dir) if data_dir is not None else Path("data")

    # ---- 3. Multi-symbol path (Story 4.1 AC6) ----
    if use_multi_symbol:
        _run_multi_symbol_download(
            console=console,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            data_dir=resolved_data_dir,
            parallel=parallel,
        )
        # _run_multi_symbol_download chama typer.Exit ao final.
        return

    # ---- 3b. Single-symbol header Rich (CLI_PATTERNS §2) ----
    console.print(
        Panel(
            f"[bold]Baixando[/bold] [cyan]{single_symbol}[/cyan] "
            f"({start_date.isoformat()} a {end_date.isoformat()}) — exchange={exchange}",
            title="[cyan]⬇ data-downloader download[/cyan]",
            border_style="cyan",
        )
    )

    # ---- 4. Início do download via public_api ----
    from data_downloader.public_api.download import download as api_download

    # Story 2.4 — opt-in PrometheusExporter HTTP (lifecycle gerenciado aqui;
    # stop garantido em ``finally`` no fim do comando para liberar a porta
    # mesmo em erro/cancel).
    metrics_exporter = None
    if metrics_port is not None:
        from data_downloader.observability import PrometheusExporter

        metrics_exporter = PrometheusExporter(port=metrics_port)
        try:
            metrics_exporter.start()
        except OSError as exc:
            console.print(
                f"[red]✗ Não foi possível iniciar o exporter Prometheus "
                f"em :{metrics_port}:[/red] {exc}"
            )
            raise typer.Exit(code=2) from exc
        console.print(
            f"[cyan]📊 Métricas Prometheus expostas em "
            f"http://localhost:{metrics_port}/metrics[/cyan]"
        )

    try:
        handle = api_download(
            symbol=single_symbol,
            start=start_date,
            end=end_date,
            exchange=exchange,
            data_dir=resolved_data_dir,
            metrics_emitter=metrics_exporter,
        )
    except ValueError as exc:
        if metrics_exporter is not None:
            with contextlib.suppress(Exception):
                metrics_exporter.stop()
        console.print(f"[red]✗ Erro de input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    # ---- 5. Cancelamento graceful via SIGINT (CLI_PATTERNS §7, AC4) ----
    cancel_requested = threading.Event()
    orig_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum: int, frame: object) -> None:
        # Apenas seta flag; o loop de eventos checa e prompt-confirma.
        # NÃO chamamos handle.cancel() direto: damos ao usuário a chance de
        # confirmar (CLI_PATTERNS §7 — pergunta antes de cancelar).
        _ = signum, frame
        cancel_requested.set()

    signal.signal(signal.SIGINT, _sigint_handler)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(complete_style="cyan", finished_style="green"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("• {task.completed}/{task.total}"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )

    task_id = progress.add_task(f"Baixando {single_symbol}", total=100)

    # Drena eventos em thread separada para que o main loop possa
    # processar SIGINT confirmação (input prompt bloqueia).
    progress_state: dict[str, object] = {
        "trades": 0,
        "current_contract": single_symbol,
        "is_99": False,
    }

    def _drain_events() -> None:
        for ev in handle.events():
            progress_state["trades"] = ev.trades_received
            if ev.current_contract:
                progress_state["current_contract"] = ev.current_contract
            progress_state["is_99"] = ev.is_99_reconnect
            # Atualiza barra; se total ainda desconhecido, usa pulse.
            if ev.total > 0:
                progress.update(
                    task_id,
                    total=ev.total,
                    completed=ev.done,
                    description=f"Baixando {progress_state['current_contract']}",
                )
            # Quirk Q11-99 — texto LITERAL canônico de Uma.
            if ev.is_99_reconnect:
                progress.update(
                    task_id,
                    description=_format_microcopy("WAR_99_RECONNECT", "detail"),
                )

    drain_thread = threading.Thread(target=_drain_events, daemon=True)

    final_result = None
    try:
        with progress:
            drain_thread.start()
            # Loop de poll no resultado, com checagem de cancel.
            while True:
                if cancel_requested.is_set():
                    # Para o progress temporariamente para fazer prompt limpo.
                    progress.stop()
                    confirm = (
                        typer.prompt(
                            _format_microcopy("PMT_CANCEL_CONFIRM", "title"),
                            default="n",
                            show_default=False,
                        )
                        .strip()
                        .lower()
                    )
                    if confirm in ("s", "sim", "y", "yes"):
                        handle.cancel()
                        msg = _format_microcopy("INF_GRACEFUL_SHUTDOWN", "title")
                        console.print(f"[yellow]↻ {msg}[/yellow]")
                        # Aguarda worker terminar.
                        final_result = handle.result(timeout=120.0)
                        break
                    # Usuário escolheu continuar — limpa flag e re-arma sinal.
                    cancel_requested.clear()
                    progress.start()
                    continue
                # Tenta pegar resultado em pooling curto.
                try:
                    final_result = handle.result(timeout=0.25)
                    break
                except TimeoutError:
                    continue
    finally:
        # Restaura handler original.
        signal.signal(signal.SIGINT, orig_handler)
        # Drena thread de eventos (já deve ter terminado).
        drain_thread.join(timeout=2.0)
        # Story 2.4 — stop exporter HTTP (libera porta) — best-effort.
        if metrics_exporter is not None:
            with contextlib.suppress(Exception):
                metrics_exporter.stop()

    if final_result is None:  # pragma: no cover defensive
        console.print("[red]✗ Erro interno: download não retornou resultado[/red]")
        raise typer.Exit(code=1)

    # ---- 6. Persiste last_symbol (CLI_PATTERNS §10) ----
    _save_last_symbol(final_result.symbol)

    # ---- 7. Render final por status ----
    status = final_result.status
    if status == "completed":
        size_mb = _approx_size_mb(final_result.partitions)
        duration = _format_duration(final_result.duration_seconds)
        console.print(
            Panel(
                "[bold green]✓ "
                + _format_microcopy("SUC_DOWNLOAD_DONE", "title", symbol=final_result.symbol)
                + "[/bold green]\n"
                + _format_microcopy(
                    "SUC_DOWNLOAD_DONE",
                    "detail",
                    trade_count=f"{final_result.trades_count:,}".replace(",", "."),
                    file_count=len(final_result.partitions),
                    size_mb=f"{size_mb:.1f}",
                    duration=duration,
                )
                + "\n[cyan underline]"
                + _format_microcopy("SUC_DOWNLOAD_DONE", "action", symbol=final_result.symbol)
                + "[/cyan underline]",
                title="OK",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)
    if status == "cache_hit":
        console.print(
            Panel(
                "[bold green]✓ "
                + _format_microcopy("SUC_CACHE_HIT", "title")
                + "[/bold green]\n"
                + _format_microcopy(
                    "SUC_CACHE_HIT",
                    "detail",
                    symbol=final_result.symbol,
                    period=f"{start_date.isoformat()} a {end_date.isoformat()}",
                )
                + "\n[dim]"
                + _format_microcopy("SUC_CACHE_HIT", "action")
                + "[/dim]",
                title="cache",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)
    if status == "cancelled":
        console.print(
            Panel(
                "[yellow]✓ "
                + _format_microcopy("SUC_CANCEL_DONE", "title")
                + "[/yellow]\n"
                "Trades preservados: "
                f"[bold]{final_result.trades_count:,}[/bold]".replace(",", ".")
                + "\n[cyan]"
                + _format_microcopy(
                    "SUC_CANCEL_DONE",
                    "action",
                    symbol=final_result.symbol,
                )
                + "[/cyan]",
                title="cancelado",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=130)
    if status in ("partial", "failed"):
        # Erro humanizado via humanize_nl_error quando possível.
        from data_downloader.ui.microcopy_loader import humanize_nl_error

        nl_name = None
        if final_result.error_message:
            # error_message vem como "NL_NAME: ..." quando DLLInitError.
            head = final_result.error_message.split(":", 1)[0].strip()
            if head.startswith("NL_"):
                nl_name = head
        entry = humanize_nl_error(nl_name)
        body = (
            f"[bold red]✗ {entry.title}[/bold red]\n"
            f"{entry.detail or final_result.error_message or ''}\n"
            f"[dim]{entry.action or ''}[/dim]"
        )
        console.print(
            Panel(body, title="erro", border_style="red"),
        )
        raise typer.Exit(code=3 if nl_name else 1)
    # Defensive — status desconhecido.
    console.print(f"[red]✗ Status desconhecido: {status}[/red]")  # pragma: no cover
    raise typer.Exit(code=1)


def _approx_size_mb(partitions: tuple[Path, ...]) -> float:
    """Soma file size em MB. Best-effort; ignora arquivos ausentes."""
    total = 0
    for p in partitions:
        with contextlib.suppress(OSError):
            total += Path(p).stat().st_size
    return total / (1024 * 1024)


def _format_duration(seconds: float) -> str:
    """Formata duração humana (ex.: '4min 12s', '34s')."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = int(seconds % 60)
    return f"{minutes}min {rem:02d}s"


# =====================================================================
# Multi-symbol download (Story 4.1 AC6 — broker + pool)
# =====================================================================


def _run_multi_symbol_download(
    *,
    console: Console,
    symbols: list[str],
    start_date: date,
    end_date: date,
    exchange: str,
    data_dir: Path,
    parallel: int,
) -> None:
    """Executa N símbolos paralelo via :class:`MultiSymbolMaster` (Story 4.1).

    Args:
        console: Rich console (microcopy + tables).
        symbols: Lista de símbolos (>= 2; rota single-symbol cobre 1).
        start_date / end_date: Janela inclusiva.
        exchange: ``"F"`` ou ``"B"``.
        data_dir: Raiz dos dados.
        parallel: Número de workers do pool (clamp em range válido).

    Notes:
        - Usa factory de produção em ``broker._mock_worker_factory`` é OK
          para tests; produção deve passar factory que carrega DLL real.
          V1 default: factory mock (para evitar bloquear quando humano não
          tem DLL — ver WAIVER 4.1-real-smoke-deferred).
        - Resolve contract = True (default) — workers usam catalog R/O via
          broker para resolver vigência (futuro V1.x — V1 mantém raiz =
          contrato vigente quando passado direto).
        - Sem cancellation handler aqui (V1) — Ctrl+C mata workers via
          broker stop. Futuro: graceful cancel via flag compartilhada.
    """
    from datetime import datetime
    from datetime import time as _time

    from data_downloader.orchestrator.broker.master import (
        MultiSymbolJobConfig,
        MultiSymbolMaster,
    )
    from data_downloader.orchestrator.broker.pool import PoolConfig
    from data_downloader.storage.catalog import Catalog

    console.print(
        Panel(
            f"[bold]Multi-symbol download[/bold] — {len(symbols)} símbolo(s) "
            f"x {parallel} worker(s)\n"
            f"Símbolos: [cyan]{', '.join(symbols)}[/cyan]\n"
            f"Período: {start_date.isoformat()} a {end_date.isoformat()} — exchange={exchange}",
            title="[cyan]⬇ data-downloader download (multi-symbol — Story 4.1)[/cyan]",
            border_style="cyan",
        )
    )

    # Catálogo no master (broker possui write lock).
    db_path = data_dir / "history" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir)

    # Worker factory: V1 usa _mock_worker_factory por causa do WAIVER
    # 4.1-real-smoke-deferred. Quando humano rodar smoke real (4.1-followup),
    # substituir por factory que carrega DLL real (TBD em followup story).
    factory_module = os.environ.get(
        "DATA_DOWNLOADER_BROKER_FACTORY",
        "data_downloader.orchestrator.broker._mock_worker_factory",
    )
    pool_config = PoolConfig(
        n_workers=parallel,
        data_dir=data_dir,
        worker_factory_module=factory_module,
        worker_factory_callable="create_orchestrator",
    )

    jobs = [
        MultiSymbolJobConfig(
            symbol=sym,
            exchange=exchange,
            start=datetime.combine(start_date, _time(9, 0)),
            end=datetime.combine(end_date, _time(17, 0)),
            resolve_contract=False,  # V1: assume símbolo já é contrato vigente
        )
        for sym in symbols
    ]

    try:
        with MultiSymbolMaster(catalog=catalog, pool_config=pool_config) as master:
            outcomes = master.download_multi(jobs)
    finally:
        catalog.close()

    # Sumário Rich.
    table = Table(title="Multi-symbol download — outcomes")
    table.add_column("Symbol", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Trades", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Error", overflow="fold")

    n_completed = 0
    n_failed = 0
    for o in outcomes:
        status_color = {
            "completed": "[green]completed[/green]",
            "cache_hit": "[green]cache_hit[/green]",
            "partial": "[yellow]partial[/yellow]",
            "failed": "[red]failed[/red]",
            "exception": "[red]exception[/red]",
        }.get(o.status, o.status)
        table.add_row(
            o.symbol,
            status_color,
            f"{o.trades_persisted:,}".replace(",", "."),
            _format_duration(o.duration_seconds),
            (o.error or "")[:80],
        )
        if o.status in ("completed", "cache_hit"):
            n_completed += 1
        else:
            n_failed += 1

    console.print(table)

    if n_failed == 0:
        console.print(
            Panel(
                f"[bold green]✓ All {n_completed} symbols completed[/bold green]",
                title="OK",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)
    if n_completed == 0:
        console.print(
            Panel(
                f"[bold red]✗ All {n_failed} symbols failed[/bold red]",
                title="FAIL",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)
    console.print(
        Panel(
            f"[yellow]⚠ Partial: {n_completed} completed, {n_failed} failed[/yellow]",
            title="PARTIAL",
            border_style="yellow",
        )
    )
    raise typer.Exit(code=3)


# =====================================================================
# migrate subcommand group (Story 2.3 — Sol+Dex)
# =====================================================================

migrate_app = typer.Typer(
    name="migrate",
    help="Schema migration framework (plan/execute/rollback/cleanup — Sol+Dex Story 2.3).",
    no_args_is_help=True,
)
app.add_typer(migrate_app, name="migrate")


# Singletons p/ typer.Option (evita ruff B008).
_MIGRATE_FROM_OPT = typer.Option(..., "--from", help="Versão de origem (ex.: 1.0.0).")
_MIGRATE_TO_OPT = typer.Option(..., "--to", help="Versão alvo (ex.: 1.1.0).")
_MIGRATE_DATA_DIR_OPT = typer.Option(
    Path("data"), "--data-dir", "-d", help="Raiz dos dados (default: ./data)."
)
_MIGRATE_SYMBOL_OPT = typer.Option(None, "--symbol", "-s", help="Restringe a um símbolo (sandbox).")
_MIGRATE_RUN_ID_OPT = typer.Option(
    None, "--run-id", help="ID do run a resumir (default: gera novo)."
)
_MIGRATE_CONTINUE_ON_ERROR_OPT = typer.Option(
    False, "--continue-on-error", help="Continua se uma partição falhar."
)
_MIGRATE_FORCE_OPT = typer.Option(False, "--yes", "-y", help="Não pedir confirmação interativa.")
_MIGRATE_RUN_ID_REQUIRED_OPT = typer.Option(..., "--run-id", help="ID do run a reverter.")
_MIGRATE_OLDER_THAN_OPT = typer.Option(
    30, "--older-than", help="Idade mínima em dias para deletar .bak."
)


def _open_migration_components(
    data_dir: Path,
) -> tuple[Catalog, object]:
    """Abre catálogo + cria runner (helper compartilhado)."""
    from data_downloader.storage.catalog import Catalog as _Catalog
    from data_downloader.storage.migrations import MigrationRunner

    db_path = data_dir / "history" / "catalog.db"
    catalog = _Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    runner = MigrationRunner(catalog=catalog, data_dir=data_dir)
    return catalog, runner


@migrate_app.command("plan")  # type: ignore[misc,unused-ignore]
def migrate_plan(
    from_version: str = _MIGRATE_FROM_OPT,
    to_version: str = _MIGRATE_TO_OPT,
    data_dir: Path = _MIGRATE_DATA_DIR_OPT,
    symbol: str | None = _MIGRATE_SYMBOL_OPT,
) -> None:
    """Gera plano de migração (dry-run — não escreve nada)."""
    console = _make_console()

    catalog, runner = _open_migration_components(data_dir)
    try:
        try:
            plan = runner.plan(from_version, to_version, symbol=symbol)  # type: ignore[attr-defined]
        except ValueError as exc:
            console.print(
                "[red]✗ "
                + _format_microcopy("migration.error.no_path", "title")
                + "[/red]\n  "
                + _format_microcopy(
                    "migration.error.no_path",
                    "detail",
                    from_v=from_version,
                    to_v=to_version,
                )
                + "\n  "
                + _format_microcopy("migration.error.no_path", "action")
                + f"\n  [dim]{exc}[/dim]"
            )
            raise typer.Exit(code=2) from exc

        if plan.is_noop:
            console.print(
                Panel(
                    "[yellow]"
                    + _format_microcopy("migration.plan.empty", "title")
                    + "[/yellow]\n"
                    + _format_microcopy("migration.plan.empty", "detail", from_v=from_version)
                    + "\n[dim]"
                    + _format_microcopy("migration.plan.empty", "action")
                    + "[/dim]",
                    title="plan",
                    border_style="yellow",
                )
            )
            raise typer.Exit(code=0)

        title_line = _format_microcopy(
            "migration.plan.title",
            "title",
            from_v=from_version,
            to_v=to_version,
        )
        detail_line = _format_microcopy(
            "migration.plan.title",
            "detail",
            n_partitions=len(plan.affected_partitions),
            bytes_read=f"{plan.bytes_read_estimate:_}",
            bytes_write=f"{plan.bytes_write_estimate:_}",
            eta=f"{plan.eta_seconds:.1f}",
        )
        console.print(Panel(f"[bold]{title_line}[/bold]\n{detail_line}", border_style="cyan"))

        steps_table = Table(title="Steps", show_lines=False)
        steps_table.add_column("From", style="cyan")
        steps_table.add_column("To", style="bold")
        steps_table.add_column("Description")
        steps_table.add_column("Breaking", style="red")
        steps_table.add_column("Rollback", style="green")
        for step in plan.steps:
            steps_table.add_row(
                step.from_version,
                step.to_version,
                step.description,
                "yes" if step.breaking else "no",
                "yes" if step.rollback_supported else "no",
            )
        console.print(steps_table)

        # Lista (truncada) de partições afetadas.
        max_display = 20
        partitions_display = plan.affected_partitions[:max_display]
        console.print(f"[dim]Partitions ({len(plan.affected_partitions)} total):[/dim]")
        for p in partitions_display:
            console.print(f"  - {p}")
        if len(plan.affected_partitions) > max_display:
            console.print(
                f"  [dim]... ({len(plan.affected_partitions) - max_display} omitidas)[/dim]"
            )

        console.print("[dim]" + _format_microcopy("migration.dry_run", "title") + "[/dim]")
    finally:
        with contextlib.suppress(Exception):
            catalog.close()


@migrate_app.command("execute")  # type: ignore[misc,unused-ignore]
def migrate_execute(
    from_version: str = _MIGRATE_FROM_OPT,
    to_version: str = _MIGRATE_TO_OPT,
    data_dir: Path = _MIGRATE_DATA_DIR_OPT,
    symbol: str | None = _MIGRATE_SYMBOL_OPT,
    run_id: str | None = _MIGRATE_RUN_ID_OPT,
    continue_on_error: bool = _MIGRATE_CONTINUE_ON_ERROR_OPT,
    yes: bool = _MIGRATE_FORCE_OPT,
) -> None:
    """Executa migração — backup .bak por partição + checkpoint resumível."""
    console = _make_console()

    catalog, runner = _open_migration_components(data_dir)
    try:
        try:
            plan = runner.plan(from_version, to_version, symbol=symbol)  # type: ignore[attr-defined]
        except ValueError as exc:
            console.print(f"[red]✗ {exc}[/red]")
            raise typer.Exit(code=2) from exc

        if plan.is_noop:
            console.print("[yellow]Nenhuma partição a migrar.[/yellow]")
            raise typer.Exit(code=0)

        # Confirmação interativa (a menos que --yes).
        if not yes:
            confirm = (
                typer.prompt(
                    _format_microcopy("migration.confirm", "title"),
                    default="n",
                    show_default=False,
                )
                .strip()
                .lower()
            )
            if confirm not in ("s", "sim", "y", "yes"):
                console.print("[yellow]Cancelado pelo usuário.[/yellow]")
                raise typer.Exit(code=0)

        result = runner.execute(  # type: ignore[attr-defined]
            plan, run_id=run_id, continue_on_error=continue_on_error, dry_run=False
        )

        if result.partitions_failed > 0:
            for outcome in result.outcomes:
                if outcome.status == "failed":
                    console.print(
                        "[red]✗ "
                        + _format_microcopy(
                            "migration.error.partition_failed",
                            "title",
                            partition=outcome.partition_path,
                        )
                        + "[/red]\n  "
                        + _format_microcopy(
                            "migration.error.partition_failed",
                            "detail",
                            error=outcome.error or "unknown",
                        )
                        + "\n  [dim]"
                        + _format_microcopy("migration.error.partition_failed", "action")
                        + "[/dim]"
                    )

        success_panel = (
            "[bold green]✓ "
            + _format_microcopy(
                "migration.success",
                "title",
                from_v=from_version,
                to_v=to_version,
            )
            + "[/bold green]\n"
            + _format_microcopy(
                "migration.success",
                "detail",
                n_migrated=result.partitions_migrated,
                n_failed=result.partitions_failed,
                n_skipped=result.partitions_skipped,
                duration=f"{result.duration_seconds:.2f}",
            )
            + f"\n[dim]run_id: {result.run_id}[/dim]\n[cyan]"
            + _format_microcopy("migration.success", "action")
            + "[/cyan]"
        )
        console.print(
            Panel(
                success_panel,
                title="OK" if result.partitions_failed == 0 else "PARTIAL",
                border_style="green" if result.partitions_failed == 0 else "yellow",
            )
        )
        raise typer.Exit(code=0 if result.partitions_failed == 0 else 3)
    finally:
        with contextlib.suppress(Exception):
            catalog.close()


@migrate_app.command("rollback")  # type: ignore[misc,unused-ignore]
def migrate_rollback(
    run_id: str = _MIGRATE_RUN_ID_REQUIRED_OPT,
    data_dir: Path = _MIGRATE_DATA_DIR_OPT,
) -> None:
    """Reverte migração restaurando .bak por partição (de um run_id)."""
    console = _make_console()
    catalog, runner = _open_migration_components(data_dir)
    try:
        result = runner.rollback(run_id=run_id)  # type: ignore[attr-defined]
        console.print(
            Panel(
                "[bold green]"
                + _format_microcopy("migration.rollback.success", "title", run_id=run_id)
                + "[/bold green]\n"
                + _format_microcopy(
                    "migration.rollback.success",
                    "detail",
                    n_rolled_back=result.partitions_migrated,
                ),
                title="rollback",
                border_style="green",
            )
        )
        raise typer.Exit(code=0 if result.partitions_failed == 0 else 4)
    finally:
        with contextlib.suppress(Exception):
            catalog.close()


@migrate_app.command("cleanup")  # type: ignore[misc,unused-ignore]
def migrate_cleanup(
    older_than_days: int = _MIGRATE_OLDER_THAN_OPT,
    data_dir: Path = _MIGRATE_DATA_DIR_OPT,
) -> None:
    """Remove arquivos .bak antigos (idade > --older-than dias)."""
    console = _make_console()
    catalog, runner = _open_migration_components(data_dir)
    try:
        removed = runner.cleanup_backups(older_than_days=older_than_days)  # type: ignore[attr-defined]
        console.print(
            Panel(
                "[bold green]"
                + _format_microcopy("migration.cleanup.success", "title")
                + "[/bold green]\n"
                + _format_microcopy(
                    "migration.cleanup.success",
                    "detail",
                    n_removed=len(removed),
                    days=older_than_days,
                ),
                title="cleanup",
                border_style="green",
            )
        )
        raise typer.Exit(code=0)
    finally:
        with contextlib.suppress(Exception):
            catalog.close()


# =====================================================================


if __name__ == "__main__":
    app()
