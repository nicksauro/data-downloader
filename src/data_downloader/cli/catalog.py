"""data_downloader.cli.catalog — sub-app ``catalog`` (placeholder Story 4.22).

Owner: Sol (Story 4.28 P0-A1 — split do monolito ``cli.py``).

**AC5 cenário B:** Story 4.22 (``catalog recover-pending``, Frente 1 —
storage atomicity) NÃO foi mergeada antes da Story 4.28. Este submódulo
serve como **stub vazio** pronto para receber o comando ``recover-pending``
quando a 4.22 for mergeada — SEM exigir refactor do registry em
``cli/__init__.py``.

Quando Story 4.22 mergear:

- Adicionar ``@catalog_app.command("recover-pending")`` neste arquivo.
- Implementar lógica que delega para ``Catalog.recover_pending_commits()``
  (método introduzido pela 4.22 em ``storage/catalog.py``).
- Atualizar AC5 da story 4.22 marcando o "absorve em ``cli/catalog.py``".

Não há comandos ainda — apenas o sub-app registrado para que
``data-downloader catalog --help`` retorne o help vazio padrão Typer
em vez de "Unknown command".
"""

from __future__ import annotations

import typer

__all__ = ["catalog_app", "register"]


catalog_app = typer.Typer(
    name="catalog",
    help="Operações sobre o catálogo (recover-pending — Story 4.22 pending merge).",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Registra o sub-app ``catalog`` no ``app`` raiz.

    Hoje apenas o sub-app vazio. Quando Story 4.22 mergear, este
    submódulo ganha ``@catalog_app.command("recover-pending")`` e o
    ``register`` permanece inalterado.
    """
    app.add_typer(catalog_app, name="catalog")
