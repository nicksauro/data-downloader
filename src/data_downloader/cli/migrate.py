"""data_downloader.cli.migrate — sub-app ``migrate`` (Story 2.3 — Sol+Dex).

Owner: Sol (Story 4.28 P0-A1 — split do monolito ``cli.py``).

Sub-app Typer com 4 comandos:

- ``data-downloader migrate plan --from V --to V [--data-dir D] [--symbol S]``
- ``data-downloader migrate execute --from V --to V [--data-dir D] [--symbol S]
  [--run-id R] [--continue-on-error] [--yes]``
- ``data-downloader migrate rollback --run-id R [--data-dir D]``
- ``data-downloader migrate cleanup [--older-than N] [--data-dir D]``

Schema migration framework (backup .bak por partição + checkpoint resumível).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel
from rich.table import Table

from data_downloader.cli._helpers import _format_microcopy, _make_console

if TYPE_CHECKING:
    from data_downloader.storage.catalog import Catalog


__all__ = ["migrate_app", "register"]


migrate_app = typer.Typer(
    name="migrate",
    help="Schema migration framework (plan/execute/rollback/cleanup — Sol+Dex Story 2.3).",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Registra o sub-app ``migrate`` no ``app`` raiz."""
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

    db_path = data_dir / "_internal" / "catalog.db"
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
