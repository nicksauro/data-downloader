"""data_downloader.cli.integrity — sub-app ``integrity`` (Story 2.1).

Owner: Sol (Story 4.28 P0-A1 — split do monolito ``cli.py``).

Sub-app Typer com 2 comandos:

- ``data-downloader integrity check [--symbol S] [--exchange E] [--data-dir D]``
- ``data-downloader integrity validate-data --symbol S --start D --end D
  [--exchange E] [--data-dir D]``

Validators executáveis (Sol+Quinn). Microcopy: ``integrity.check.title``,
``integrity.pass``, ``integrity.fail``.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from data_downloader.cli._helpers import _open_catalog_for_validation

if TYPE_CHECKING:
    from data_downloader.validation.integrity import IntegrityReport

__all__ = ["integrity_app", "register"]


integrity_app = typer.Typer(
    name="integrity",
    help="Validar integridade de dados baixados (Sol+Quinn — Story 2.1).",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Registra o sub-app ``integrity`` no ``app`` raiz."""
    app.add_typer(integrity_app, name="integrity")


# Module-level singletons p/ typer.Option (evita ruff B008 conforme Story 2.1).
_DATA_DIR_OPT = typer.Option(
    Path("data"), "--data-dir", "-d", help="Raiz dos dados (default: ./data)."
)


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
