"""Data Downloader CLI entry point.

Ponto de entrada para o comando ``data-downloader`` (definido em
``pyproject.toml`` -> ``[project.scripts]``).

Story 1.1 entregou ``version``. Story 1.6 adiciona o grupo ``contracts``
(list / add / validate / vigent) — operações sobre o calendário de
contratos vigentes. Story 2.1 adiciona o grupo ``integrity`` (check /
validate-data) — validators executáveis (Sol+Quinn).

Microcopy IDs (Uma — ``MICROCOPY_CATALOG.md``):
- ``CMD_CONTRACTS`` (group label)
- ``HLP_CONTRACTS`` (group help)
- ``BTN_LIST_CONTRACTS`` (list subcommand label)
- ``BTN_VALIDATE_CONTRACT`` (validate subcommand label)
- ``ERR_INVALID_CONTRACT`` (mensagem de erro vigent)
- ``HLP_VALIDATE`` (validate subcommand summary)
- ``integrity.check.title`` (panel title — Story 2.1)
- ``integrity.pass`` / ``integrity.fail`` (verdict labels — Story 2.1)
"""

from __future__ import annotations

import contextlib
import os
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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

    Inicializa a DLL com credenciais de env (PROFITDLL_KEY / PROFIT_USER /
    PROFIT_PASS) e chama :func:`probe_contract`. Em sucesso atualiza
    ``validated_at`` no catálogo (AC7).
    """
    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.orchestrator.contracts_probe import probe_contract

    console = Console()

    key = os.getenv("PROFITDLL_KEY")
    user = os.getenv("PROFIT_USER")
    password = os.getenv("PROFIT_PASS")
    if not (key and user and password):
        console.print(
            "[red]Credenciais ausentes.[/red] Defina PROFITDLL_KEY, PROFIT_USER, "
            "PROFIT_PASS em ~/.data-downloader/.env."
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
            if not dll.wait_market_connected(timeout=60):
                console.print("[red]DLL não conectou em 60s.[/red]")
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


if __name__ == "__main__":
    app()
