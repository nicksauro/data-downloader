"""tests/unit/test_app_dispatcher.py — Story 1.7b-followup v1.0.1 fix.

Cobertura de :func:`data_downloader.ui.app._cli_or_ui_dispatch`:

Bug v1.0.0: dispatcher só inspecionava ``argv[1]``, então
``data_downloader.exe --log-level DEBUG download ...`` caía no fallback
UI → carregava Qt em paralelo com CLI → crash 0xC0000409 no Windows.

v1.0.1: dispatcher pula flags globais (com/sem valor, forma ``--flag=val``)
e identifica o primeiro token não-flag. Só rota CLI quando esse token
é subcommand conhecido (ou quando ``--help/--version`` aparece sozinho).

Testes mockam ``main`` (UI) e ``cli.app`` (Typer) — não carregam
PySide6 nem CLI Typer real. Roda em qualquer ambiente Python.
"""

from __future__ import annotations

import sys

import pytest

from data_downloader.ui import app as ui_app

# =====================================================================
# Helpers
# =====================================================================


def _run_with_argv(argv_tail: list[str]) -> int:
    """Executa ``_cli_or_ui_dispatch`` simulando ``sys.argv = ["prog", *tail]``.

    Mocka ``main`` e ``data_downloader.cli.app`` para evitar carregar
    PySide6 / executar Typer real. Retorna o exit code do dispatcher.

    Side-effect: incrementa ``main_calls`` / ``cli_calls`` via closures
    inspecionáveis nos testes.
    """
    raise NotImplementedError  # pragma: no cover — usamos fixture abaixo


@pytest.fixture
def dispatcher_spies(monkeypatch):
    """Fixture: mocka ``main()`` e ``cli.app`` e expõe contadores.

    Returns dict com:
        - ``set_argv(tail)`` — define ``sys.argv = ["prog", *tail]``.
        - ``run()`` — chama ``_cli_or_ui_dispatch()``.
        - ``main_calls`` / ``cli_calls`` — contadores read-only via property.
    """
    counters = {"main": 0, "cli": 0}

    def fake_main() -> int:
        counters["main"] += 1
        return 0

    def fake_cli_app() -> None:
        counters["cli"] += 1

    monkeypatch.setattr(ui_app, "main", fake_main)

    # cli.app é importado lazy dentro do dispatcher — interceptamos no
    # módulo `data_downloader.cli` (caminho que o dispatcher usa).
    import data_downloader.cli as cli_module

    monkeypatch.setattr(cli_module, "app", fake_cli_app, raising=True)

    def set_argv(tail: list[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["data_downloader.exe", *tail])

    def run() -> int:
        return ui_app._cli_or_ui_dispatch()

    return {
        "set_argv": set_argv,
        "run": run,
        "counters": counters,
    }


# =====================================================================
# Tests — primary acceptance criteria
# =====================================================================


def test_dispatch_no_args_calls_main_ui(dispatcher_spies):
    """``argv == ["prog"]`` (sem args) → UI.

    Caso default — usuário double-clicou o .exe.
    """
    dispatcher_spies["set_argv"]([])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["main"] == 1
    assert dispatcher_spies["counters"]["cli"] == 0


def test_dispatch_subcommand_first_calls_cli(dispatcher_spies):
    """``["download", "--symbol", "X"]`` → CLI.

    Caso simples: subcommand é o primeiro token.
    """
    dispatcher_spies["set_argv"](["download", "--symbol", "WDOFUT"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1
    assert dispatcher_spies["counters"]["main"] == 0


def test_dispatch_global_flag_then_subcommand_calls_cli(dispatcher_spies):
    """``["--log-level", "DEBUG", "download", ...]`` → CLI (BUG v1.0.0).

    Regression test do crash 0xC0000409 no binário publicado v1.0.0:
    flag global ANTES do subcommand não pode cair em UI.
    """
    dispatcher_spies["set_argv"](
        [
            "--log-level",
            "DEBUG",
            "download",
            "--symbol",
            "WDOFUT",
            "--start",
            "2026-05-04",
            "--end",
            "2026-05-04",
        ]
    )
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1
    assert dispatcher_spies["counters"]["main"] == 0


def test_dispatch_help_flag_alone_calls_cli(dispatcher_spies):
    """``["--help"]`` → CLI (Typer renderiza ajuda)."""
    dispatcher_spies["set_argv"](["--help"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1
    assert dispatcher_spies["counters"]["main"] == 0


def test_dispatch_unknown_subcommand_falls_to_ui(dispatcher_spies):
    """``["unknown-cmd"]`` → UI (per safety; Aria default).

    Rationale: usuário pode ter executado o .exe com lixo na linha de
    comando (e.g. atalho do Windows com path mal formado). UI é o
    comportamento default-seguro — Typer falharia com SystemExit caso
    routassemos para CLI.
    """
    dispatcher_spies["set_argv"](["unknown-cmd"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["main"] == 1
    assert dispatcher_spies["counters"]["cli"] == 0


# =====================================================================
# Tests — extra edge cases
# =====================================================================


def test_dispatch_global_flag_equals_form_then_subcommand(dispatcher_spies):
    """``["--log-level=DEBUG", "download", ...]`` → CLI.

    Forma ``--flag=valor`` é autocontida (1 token), não consome o próximo.
    """
    dispatcher_spies["set_argv"](
        ["--log-level=DEBUG", "--log-format=console", "download", "--symbol", "X"]
    )
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1


def test_dispatch_help_after_global_flag_calls_cli(dispatcher_spies):
    """``["--log-level", "DEBUG", "--help"]`` → CLI.

    Sem subcommand mas com `--help` em qualquer posição — Typer trata.
    """
    dispatcher_spies["set_argv"](["--log-level", "DEBUG", "--help"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1
    assert dispatcher_spies["counters"]["main"] == 0


def test_dispatch_only_global_flag_with_value_falls_to_ui(dispatcher_spies):
    """``["--log-level", "DEBUG"]`` (sem subcommand, sem help) → UI.

    Não há subcommand nem flag autocontida que justifique CLI — fallback
    seguro p/ UI (Typer iria erradar com missing command).
    """
    dispatcher_spies["set_argv"](["--log-level", "DEBUG"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["main"] == 1
    assert dispatcher_spies["counters"]["cli"] == 0


def test_dispatch_version_flag_alone_calls_cli(dispatcher_spies):
    """``["--version"]`` → CLI (Typer mostra version)."""
    dispatcher_spies["set_argv"](["--version"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1


def test_dispatch_version_subcommand_calls_cli(dispatcher_spies):
    """``["version"]`` (subcommand, não flag) → CLI."""
    dispatcher_spies["set_argv"](["version"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert dispatcher_spies["counters"]["cli"] == 1


# =====================================================================
# Tests — _first_non_flag_token (helper unitário)
# =====================================================================


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], None),
        (["download"], "download"),
        (["--log-level", "DEBUG", "download"], "download"),
        (["--log-level=DEBUG", "download"], "download"),
        (["--log-level", "DEBUG", "--log-format", "console", "download"], "download"),
        (["--help"], None),
        (["--log-level", "DEBUG"], None),
        (["--log-level", "DEBUG", "--help"], None),
        # Flag desconhecida (sem =) — assumimos autocontida; preserva próximo
        # como positional.
        (["--unknown", "download"], "download"),
        # Flag desconhecida com = — autocontida.
        (["--unknown=val", "download"], "download"),
    ],
)
def test_first_non_flag_token(args, expected):
    assert ui_app._first_non_flag_token(args) == expected


# =====================================================================
# Tests — verify CLI dispatch path does NOT import PySide6
# =====================================================================


def test_cli_dispatch_does_not_import_pyside6(dispatcher_spies, monkeypatch):
    """Sentinel: dispatch CLI não pode tocar em PySide6.

    Se algum import Qt vazar para o caminho CLI no futuro, este teste
    falha — protege contra regressão do crash 0xC0000409 que vinha da
    coexistência QApplication + Typer.
    """
    # Marca PySide6 como "envenenado": qualquer import quebra.
    poisoned = {"hits": 0}

    real_import = (
        __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
    )

    def guarded_import(name, *args, **kwargs):
        if name.startswith("PySide6"):
            poisoned["hits"] += 1
            raise AssertionError(f"CLI dispatch path imported PySide6 ({name}) — regression!")
        return real_import(name, *args, **kwargs)

    if isinstance(__builtins__, dict):
        monkeypatch.setitem(__builtins__, "__import__", guarded_import)
    else:
        monkeypatch.setattr(__builtins__, "__import__", guarded_import)

    dispatcher_spies["set_argv"](["--log-level", "DEBUG", "download", "--symbol", "X"])
    rc = dispatcher_spies["run"]()
    assert rc == 0
    assert poisoned["hits"] == 0
    assert dispatcher_spies["counters"]["cli"] == 1
