"""Permite ``python -m data_downloader.cli`` rodar o app Typer.

Owner: Sol (Story 4.28 P0-A1).

Antes do refactor (Story 4.28), ``python -m data_downloader.cli`` rodava
o monolito ``cli.py`` via ``if __name__ == "__main__": app()``. Após
pacotificação, esse pattern não funciona em pacotes — Python procura
``__main__.py`` no diretório do pacote. Este arquivo restaura a
funcionalidade.
"""

from __future__ import annotations

from data_downloader.cli import app

if __name__ == "__main__":
    app()
