"""data_downloader.cli — pacote CLI raiz (Story 4.28 P0-A1 refactor).

Owner: Sol (Story 4.28) — pacotificação do monolito ``src/data_downloader/cli.py``
(2.374 LOC) em 8 arquivos com responsabilidades separadas.

**Backward-compat (AC2 — entry point intacto):** ``pyproject.toml``
mantém ``[project.scripts] data-downloader = "data_downloader.cli:app"``
sem alteração; o símbolo ``app`` continua exportado por
``data_downloader.cli`` (agora pacote, antes módulo). ``data-downloader
--help`` lista exatamente os mesmos sub-comandos.

Layout do pacote:

```
src/data_downloader/cli/
├── __init__.py        # este módulo — app + bootstrap + global callback + registry
├── _helpers.py        # microcopy formatters, last_symbol cache, sentinels, console
├── contracts.py       # sub-app contracts (list/add/validate/vigent — Story 1.6)
├── integrity.py       # sub-app integrity (check/validate-data — Story 2.1)
├── migrate.py         # sub-app migrate (plan/execute/rollback/cleanup — Story 2.3)
├── catalog.py         # sub-app catalog stub (Story 4.22 placeholder)
├── doctor.py          # comando doctor + 6 _check_* helpers (Story 4.9)
└── download.py        # comando download + _download_one_symbol + auto-resume
```

Cada submódulo expõe ``register(app)`` que chama ``app.add_typer`` ou
``app.command``. ``cli/__init__.py`` invoca os 6 ``register`` em ordem
determinística após criar ``app`` e configurar o global callback.

**Test surface preservada:** os seguintes símbolos são re-exportados via
este ``__init__.py`` para que callsites de testes continuem funcionando
sem mudança:

- ``app`` — entry point Typer.
- ``_bootstrap_env`` / ``_get_credential`` (test_env_bootstrap.py).
- ``_open_catalog`` (test_contracts_cli.py).
- ``run_doctor_checks`` (settings_screen.py, test_ui_settings_doctor_button.py).
- ``_check_*`` helpers (test_cli_doctor.py monkey-patches).
"""

from __future__ import annotations

# =====================================================================
# Q-DRIFT-04 (smoke 2026-05-04) — UTF-8 reconfigure ANTES de importar
# Rich/typer. Em Windows, console default cp1252 causa UnicodeEncodeError
# ao tentar emitir emojis em Rich Panel. Setar via env não basta porque
# Python 3.12+ pode já ter populado os wrappers — usamos ``reconfigure``
# quando disponível (Python 3.7+).
# =====================================================================
import contextlib as _contextlib_bootstrap
import os as _os_bootstrap
import sys as _sys_bootstrap

_os_bootstrap.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(_sys_bootstrap, _stream_name, None)
    if _stream is not None:
        _reconfigure = getattr(_stream, "reconfigure", None)
        if callable(_reconfigure):
            with _contextlib_bootstrap.suppress(Exception):
                _reconfigure(encoding="utf-8", errors="replace")


# =====================================================================
# Imports normais — APÓS reconfigure (Q-DRIFT-04)
# =====================================================================
import os  # noqa: E402  — reconfigure deve rodar primeiro
import sys  # noqa: E402

import typer  # noqa: E402

# Re-exports para preservar test surface (AC6 — imports absolutos).
from data_downloader.cli._helpers import (  # noqa: E402
    _approx_size_mb,
    _bootstrap_env,
    _build_known_sentinels,
    _default_period,
    _format_duration,
    _format_microcopy,
    _get_credential,
    _get_known_sentinels,
    _last_symbol_cache_path,
    _load_last_symbol,
    _make_console,
    _migrate_legacy_last_symbol_cache,
    _open_catalog,
    _open_catalog_for_validation,
    _save_last_symbol,
)
from data_downloader.cli.doctor import (  # noqa: E402
    _check_connectivity,
    _check_credentials,
    _check_disk,
    _check_dll_companions,
    _check_dll_handshake,
    _check_schema,
    run_doctor_checks,
)

__all__ = [
    "_approx_size_mb",
    "_bootstrap_env",
    "_build_known_sentinels",
    "_check_connectivity",
    "_check_credentials",
    "_check_disk",
    "_check_dll_companions",
    "_check_dll_handshake",
    "_check_schema",
    "_default_period",
    "_format_duration",
    "_format_microcopy",
    "_get_credential",
    "_get_known_sentinels",
    "_last_symbol_cache_path",
    "_load_last_symbol",
    "_make_console",
    "_migrate_legacy_last_symbol_cache",
    "_open_catalog",
    "_open_catalog_for_validation",
    "_save_last_symbol",
    "app",
    "run_doctor_checks",
]


# =====================================================================
# Typer app + module-level singletons p/ typer.Option (evita ruff B008).
# =====================================================================

app = typer.Typer(
    name="data-downloader",
    help="Downloader de histórico de ativos via ProfitDLL.",
    no_args_is_help=True,
)


# =====================================================================
# Story v1.0.2 fix B3 — dotenv bootstrap (Nelo+Aria 2026-05-05)
# Carrega ``.env`` user-global ANTES de qualquer leitura ``os.getenv``.
# Idempotent. Executado em import time (uma vez por processo).
# =====================================================================
_bootstrap_env()


# =====================================================================
# Story 2.9 — flags globais de logging (ADR-010 / AC5).
# =====================================================================

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

# Wave 1 P0 (Quinn BIG COUNCIL 2026-05-06) — self-check minimal.
_HEALTHCHECK_OPT = typer.Option(
    False,
    "--healthcheck",
    help=(
        "Self-check minimal — exit 0 se imports e logging OK. "
        "NÃO inicializa DLL (use 'doctor --with-handshake' para isso)."
    ),
    is_eager=True,
)


def _resolve_default_format() -> str:
    """Heurística TTY-aware (ADR-010 / Story 2.9 AC5).

    - ``stderr`` é TTY (interactive shell) → ``"console"`` (humano-readable).
    - ``stderr`` não-TTY (pipe, redirect, CI) → ``"json"`` (machine-parseable).
    """
    try:
        if sys.stderr.isatty():
            return "console"
    except (AttributeError, ValueError):  # pragma: no cover defensive
        pass
    return "json"


def _run_healthcheck() -> int:
    """Self-check minimal — Wave 1 P0 (Quinn BIG COUNCIL 2026-05-06).

    Valida que o binário consegue:
      1. Importar pacotes críticos (sem chamar Init na DLL).
      2. Configurar structlog (setup_logging).
      3. Emitir 1 log probe sem exceção.

    Retorna 0 em sucesso, 1 em qualquer ImportError/Exception. Imprime
    mensagem amigável em stdout — facilita pipe/grep em smoke tests.
    """
    try:
        # Import sequencial dos módulos críticos.
        import importlib

        critical_modules = [
            "data_downloader",
            "data_downloader.dll.wrapper",
            "data_downloader.observability.logging_config",
            "data_downloader.storage.catalog",
        ]
        for mod_name in critical_modules:
            importlib.import_module(mod_name)

        from data_downloader.observability.logging_config import (
            get_logger,
            setup_logging,
        )

        # Setup logging com defaults conservadores (WARNING, sem bridge).
        setup_logging(level="WARNING", bridge_to_stdlib=False)

        # Probe — emite 1 log canônico via pipeline configurado.
        get_logger("data_downloader.healthcheck").warning(
            "healthcheck_probe",
            phase="self_check",
        )
    except Exception as exc:  # catch-all intencional — gate de healthcheck
        typer.echo(f"healthcheck FAIL: {type(exc).__name__}: {exc}", err=True)
        return 1

    # Print versão + status — formato esperado por subprocess test.
    from data_downloader import __version__

    typer.echo(f"data_downloader {__version__}")
    typer.echo("healthcheck OK")
    return 0


@app.callback(invoke_without_command=True)  # type: ignore[misc,unused-ignore]
def _global_callback(
    ctx: typer.Context,
    log_level: str | None = _LOG_LEVEL_OPT,
    log_format: str | None = _LOG_FORMAT_OPT,
    healthcheck: bool = _HEALTHCHECK_OPT,
) -> None:
    """Boot global do CLI — configura logging UMA vez (Story 2.9 / ADR-010).

    Resolve precedência (CLI flag > env var > default):

    - ``--log-level`` > ``DATA_DOWNLOADER_LOG_LEVEL`` > ``"INFO"``
    - ``--log-format`` > ``DATA_DOWNLOADER_LOG_FORMAT`` > heurística TTY

    Flag ``--healthcheck`` (Wave 1 P0 / Quinn BIG COUNCIL): se presente,
    roda :func:`_run_healthcheck` e termina o processo (não delega para
    sub-comando).
    """
    if healthcheck:
        raise typer.Exit(code=_run_healthcheck())

    # Sem ``--healthcheck`` e sem sub-comando: mostra help e exit 2.
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=2)

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
# version command (Story 1.1)
# =====================================================================


@app.command()  # type: ignore[misc,unused-ignore]
def version() -> None:
    """Print version."""
    from data_downloader import __version__

    typer.echo(f"data-downloader {__version__}")


# =====================================================================
# Registry de sub-apps + comandos (ordem determinística)
# =====================================================================
#
# Cada submódulo expõe ``register(app)`` que se auto-instala no app raiz.
# Ordem fixa para que a saída de ``data-downloader --help`` seja
# determinística entre execuções (regressão de UX evitada).
#
# Importamos cada submódulo localmente e invocamos seu ``register``.
# Imports absolutos (AC6) — ``from data_downloader.cli import X`` em vez
# de ``from . import X`` para alinhar com a convenção do projeto
# (Article VI — Absolute Imports).
# =====================================================================

from data_downloader.cli import (  # noqa: E402  — registry after app + callback
    catalog as _catalog_mod,
)
from data_downloader.cli import (  # noqa: E402
    contracts as _contracts_mod,
)
from data_downloader.cli import (  # noqa: E402
    doctor as _doctor_mod,
)
from data_downloader.cli import (  # noqa: E402
    download as _download_mod,
)
from data_downloader.cli import (  # noqa: E402
    integrity as _integrity_mod,
)
from data_downloader.cli import (  # noqa: E402
    migrate as _migrate_mod,
)

_contracts_mod.register(app)
_integrity_mod.register(app)
_migrate_mod.register(app)
_catalog_mod.register(app)
_doctor_mod.register(app)
_download_mod.register(app)


# Permitir ``python -m data_downloader.cli`` rodar o app.
if __name__ == "__main__":
    app()
