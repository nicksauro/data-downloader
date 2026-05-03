"""Data Downloader CLI entry point.

Ponto de entrada para o comando ``data-downloader`` (definido em
``pyproject.toml`` -> ``[project.scripts]``). Story 1.1 entrega apenas o
esqueleto Typer + comando ``version``; comandos reais (``download``,
``read``, ``init``, ``config show``) entram nas Stories 1.5+ (CLI) e 3.x.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="data-downloader",
    help="Downloader de histórico de ativos via ProfitDLL.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print version."""
    from data_downloader import __version__

    typer.echo(f"data-downloader {__version__}")


if __name__ == "__main__":
    app()
