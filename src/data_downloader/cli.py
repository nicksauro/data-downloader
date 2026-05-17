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
import warnings
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


# =====================================================================
# Story v1.0.2 fix B3 — dotenv bootstrap (Nelo+Aria 2026-05-05)
# =====================================================================
# Carrega ``.env`` de candidatos em ordem de precedência ANTES de qualquer
# leitura ``os.getenv``. Sem isto o usuário precisava ``export PROFITDLL_*``
# em cada terminal — fonte recorrente de "NL_NO_LICENSE" em smoke real.
#
# Ordem (primeiro arquivo encontrado vence):
#   1. ``cwd / .env``                              — projeto local (dev)
#   2. ``<exe-dir> / .env``                        — distribuição PyInstaller
#   3. ``~/.data-downloader/.env``                 — config user-global
#
# Graceful degrade: se ``python-dotenv`` não estiver instalado, retorna
# silenciosamente (variáveis precisam ser exportadas no shell — rota antiga).


def _bootstrap_env() -> None:
    """Carrega ``.env`` do primeiro candidato existente (cwd > exe > user-home).

    Story v1.0.5 (Pichau live test 2026-05-06): delega para módulo
    :mod:`data_downloader._env_loader` — single source of truth compartilhado
    com ``ui/app.py::main()`` para que UI mode também carregue o ``.env``
    user-global no boot. Antes da v1.0.5, o double-click do .exe abria UI
    sem nunca importar este módulo, então credenciais salvas via
    SettingsScreen ficavam órfãs.

    Idempotent — chamada múltipla é segura. Best-effort: qualquer erro é
    silenciado (CLI ainda funciona sem .env quando vars já estão no ambiente).
    """
    from data_downloader._env_loader import bootstrap_env

    bootstrap_env()


def _get_credential(canonical: str, deprecated: str | None = None) -> str | None:
    """Lê env var canônica com fallback warning para nome deprecated.

    Story v1.0.2 fix B2 (Nelo+Aria 2026-05-05): backwards-compat para os
    naming antigos ``PROFIT_USER`` / ``PROFIT_PASS`` (sem prefixo). Naming
    canônico é ``PROFITDLL_*``. Quando só o deprecated está set, emitimos
    ``DeprecationWarning`` e retornamos o valor — assim usuários com .env
    legado continuam funcionando até atualizar.

    Args:
        canonical: Nome canônico (``PROFITDLL_USER``).
        deprecated: Nome legado opcional (``PROFIT_USER``).

    Returns:
        Valor da var ou ``None`` quando nenhuma das duas está set.
    """
    val = os.getenv(canonical)
    if val:
        return val
    if deprecated is not None:
        legacy = os.getenv(deprecated)
        if legacy:
            warnings.warn(
                f"{deprecated} is deprecated; use {canonical} (Story v1.0.2 B2).",
                DeprecationWarning,
                stacklevel=2,
            )
            return legacy
    return None


# Executado em import (uma única vez). Idempotente — load_dotenv não
# sobrescreve vars já no ambiente.
_bootstrap_env()


# =====================================================================
# Story v1.0.2 fix B-Frozen #3 — sentinelas frozen-mode → microcopy
# =====================================================================
# Mapa de sentinelas internas (não-``NL_*``) que podem aparecer em
# ``DownloadResult.error_message`` quando algo falha no frozen mode
# (PyInstaller bundle). Cada uma traz microcopy específica; ``{tail}``
# (com fallbacks ``{path}``/``{symbol}``) vem do segmento após o ``:``
# no ``error_message`` (formato ``SENTINEL: <texto livre>``).
#
# Mantido módulo-level para evitar reconstrução em hot path do download_cmd
# (Pyro R21) e satisfazer ruff N806.


def _build_known_sentinels() -> dict[str, _MicrocopyEntryT]:
    """Lazy builder do mapa de sentinelas — evita import circular cli↔microcopy."""
    from data_downloader.ui.microcopy_loader import MicrocopyEntry

    return {
        "VERIFY_SCRIPT_MISSING": MicrocopyEntry(
            msg_type="error",
            title="Script de verificação ausente",
            detail=(
                "O script ``verify-dll-companions.py`` não foi encontrado "
                "no bundle PyInstaller. Provável corrupção do build."
            ),
            action=("Reinstale o data-downloader (ou rode `data-downloader doctor`)."),
        ),
        "VERIFY_SCRIPT_LOAD_FAILED": MicrocopyEntry(
            msg_type="error",
            title="Falha ao carregar verify-dll-companions",
            detail="Importlib não conseguiu carregar o script de verificação.",
            action="Reinstale o data-downloader.",
        ),
        "COMPANIONS_MISSING": MicrocopyEntry(
            msg_type="error",
            title="DLL companions ausentes",
            detail="Arquivos companions da ProfitDLL não foram encontrados ({tail}).",
            action=(
                "Rode `bootstrap-dll.ps1` ou reinstale o data-downloader "
                "para restaurar os companions."
            ),
        ),
        "WINDLL_LOAD_FAILED": MicrocopyEntry(
            msg_type="error",
            title="Falha ao carregar ProfitDLL.dll",
            detail="Não consegui carregar a ProfitDLL ({tail}).",
            action="Verifique que o Windows é x64 e que a DLL não está bloqueada.",
        ),
        "UNSUPPORTED_PLATFORM": MicrocopyEntry(
            msg_type="error",
            title="Plataforma não suportada",
            detail="data-downloader requer Windows x64 (ProfitDLL é Win64-only).",
            action="Use uma máquina Windows 10/11 x64.",
        ),
        "InvalidContract": MicrocopyEntry(
            msg_type="error",
            title="Contrato inválido",
            detail="O símbolo ``{tail}`` não é um contrato vigente.",
            action="Liste vigentes: `data-downloader contracts list`.",
        ),
    }


# Type alias para referência forward (preenchido na 1ª chamada de
# ``_get_known_sentinels``). Evitamos importar MicrocopyEntry aqui pra
# manter cli.py importável sem ui/ resolvido (R17 — lazy load).
if TYPE_CHECKING:
    from data_downloader.ui.microcopy_loader import MicrocopyEntry as _MicrocopyEntryT
else:
    _MicrocopyEntryT = object  # placeholder runtime; concreto via TYPE_CHECKING
_KNOWN_SENTINELS: dict[str, _MicrocopyEntryT] | None = None


def _get_known_sentinels() -> dict[str, _MicrocopyEntryT]:
    """Retorna o mapa cacheado de sentinelas (lazy build na 1ª chamada)."""
    global _KNOWN_SENTINELS
    if _KNOWN_SENTINELS is None:
        _KNOWN_SENTINELS = _build_known_sentinels()
    return _KNOWN_SENTINELS


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

# Wave 1 P0 (Quinn BIG COUNCIL 2026-05-06): self-check minimal para validar
# que o ``.exe`` frozen consegue importar módulos críticos + configurar
# logging — coisa que ``pytest`` em dev mode NÃO testa (subprocess é
# obrigatório). NÃO inicializa DLL (diferente de ``doctor``); zero
# dependências externas.
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


def _run_healthcheck() -> int:
    """Self-check minimal — Wave 1 P0 (Quinn BIG COUNCIL 2026-05-06).

    Valida que o binário consegue:
      1. Importar pacotes críticos (sem chamar Init na DLL).
      2. Configurar structlog (setup_logging).
      3. Emitir 1 log probe sem exceção.

    Retorna 0 em sucesso, 1 em qualquer ImportError/Exception. Imprime
    mensagem amigável em stdout — facilita pipe/grep em smoke tests.

    Caso de uso: ``data_downloader.exe --healthcheck`` em subprocess test
    do ``.exe`` frozen — exercita paths que pytest dev-mode não cobre
    (PyInstaller boot, módulos congelados, DLL companions resolvidas).
    """
    try:
        # Import sequencial dos módulos críticos. NÃO chama Init na DLL —
        # ``dll.wrapper`` é importado mas nenhum entry point é invocado.
        # Usamos ``importlib.import_module`` para evitar marcar imports
        # como F401 (variáveis ficam visíveis em runtime).
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
    sub-comando). Permite ``data_downloader.exe --healthcheck`` em
    subprocess test do binário frozen — usa ``invoke_without_command=True``
    para que o callback rode mesmo sem sub-comando explícito.
    """
    if healthcheck:
        raise typer.Exit(code=_run_healthcheck())

    # Sem ``--healthcheck`` e sem sub-comando: replicamos o comportamento
    # antigo de ``no_args_is_help=True`` (mostra help e exit 2). Mantemos
    # backwards-compat porque outros call sites assumem isso.
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
# contracts subcommand group (Story 1.6)
# =====================================================================

contracts_app = typer.Typer(
    name="contracts",
    help="Operações com contratos vigentes (list, add, validate, vigent).",
    no_args_is_help=True,
)
app.add_typer(contracts_app, name="contracts")


_DEFAULT_CATALOG_PATH = Path("data") / "_internal" / "catalog.db"


def _open_catalog(db_path: Path | None = None) -> Catalog:
    """Abre o catálogo no path canônico (data/_internal/catalog.db — ADR-024).

    Import local evita custo de importar storage para comandos que não
    precisam (``version``).

    Story v1.0.2 fix (Pichau smoke 2026-05-06): catalog vazio (first-run
    do .exe distribuído) auto-populava do seed YAML embutido em
    ``CONTRACTS.md``. Sem isso, primeiro ``download --symbol WDOFUT``
    falhava com ``InvalidContract`` mesmo com o seed atualizado, porque
    o catalog SQLite só era populado via ``contracts populate`` manual.
    """
    from data_downloader.orchestrator.contracts import (
        list_contracts,
        populate_contracts_from_seed,
    )
    from data_downloader.storage.catalog import Catalog

    path = db_path if db_path is not None else _DEFAULT_CATALOG_PATH
    catalog = Catalog(db_path=path)
    # First-run auto-populate: se catalog vazio, carregar seed (idempotente).
    try:
        existing = list_contracts(catalog)
        if not existing:
            populate_contracts_from_seed(catalog)
    except Exception as exc:
        # Defensivo — falha em populate não bloqueia comandos read-only.
        # Usuário verá InvalidContract downstream com hint para
        # `contracts list`/`contracts populate`.
        # Wave 1 P0 (Dex #5): NÃO mais silencioso — log warning para
        # diagnóstico via structlog (ADR-010).
        from data_downloader.observability.logging_config import get_logger

        get_logger(__name__).warning(
            "seed_populate_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            location="_open_catalog",
            db_path=str(path),
        )
    return catalog


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

    # Story v1.0.2 B2: leitura via _get_credential com fallback p/ naming
    # legado (PROFIT_USER / PROFIT_PASS) — emite DeprecationWarning.
    key = _get_credential("PROFITDLL_KEY")
    user = _get_credential("PROFITDLL_USER", "PROFIT_USER")
    password = _get_credential("PROFITDLL_PASS", "PROFIT_PASS")
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
                f"Probing [bold]{contract_code}[/bold] (sample_date={parsed_date or 'auto'})..."
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
    """Abre o catálogo em ``{data_dir}/_internal/catalog.db`` (sem reconcile auto — ADR-024).

    Variant de :func:`_open_catalog` que respeita ``data_dir`` arbitrário
    (a versão de ``contracts`` usa o path canônico fixo).

    Story v1.0.2 fix (Pichau smoke 2026-05-06): auto-populate seed se
    catalog vazio. Mesma motivação que :func:`_open_catalog` — first-run
    do .exe distribuído precisa contratos populados pra resolver
    ``WDOFUT/PETR4/etc`` em ``vigent_contract``.
    """
    from data_downloader.orchestrator.contracts import (
        list_contracts,
        populate_contracts_from_seed,
    )
    from data_downloader.storage.catalog import Catalog as _Catalog

    db_path = data_dir / "_internal" / "catalog.db"
    catalog = _Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    try:
        existing = list_contracts(catalog)
        if not existing:
            populate_contracts_from_seed(catalog)
    except Exception as exc:
        # Wave 1 P0 (Dex #5): warning audível em vez de silêncio.
        from data_downloader.observability.logging_config import get_logger

        get_logger(__name__).warning(
            "seed_populate_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            location="_open_catalog_for_validation",
            db_path=str(db_path),
        )
    return catalog


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
# `--symbol` aceita múltiplos valores (repeated flag: --symbol WDOFUT
# --symbol PETR4). Múltiplos símbolos são baixados SEQUENCIALMENTE, 1 por
# vez (ADR-022 — licença single-session; o broker multi-process foi
# removido em v1.2.0).
_DOWNLOAD_SYMBOL_OPT = typer.Option(
    None,
    "--symbol",
    "-s",
    help=(
        # Story v1.0.2 / 4.6 (Q-DRIFT-32 2026-05-05): help text simplificado.
        # WDOFUT/WINFUT (continuous future) é o ticker recomendado; antes
        # exemplificávamos WDOJ26 (vencimento), forçando o usuário a saber
        # letra-do-mês CME. Equities ficam diretos.
        "Símbolo (ex. WDOFUT, WINFUT, PETR4). Repetível para múltiplos: "
        "--symbol WDOFUT --symbol PETR4. "
        "Aliases (WDO/WIN/IND/DOL) viram <ROOT>FUT automaticamente. "
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
    None,
    "--resume",
    help=(
        "Retomar um download incompleto pelo job_id (v1.2.0). Baixa apenas "
        "os dias úteis ainda faltantes. Se omitido, um job incompleto para o "
        "mesmo (símbolo, exchange, período) é detectado e retomado "
        "automaticamente."
    ),
)
# `--parallel` — DEPRECADO (ADR-022): a licença Nelogica é single-session,
# então paralelizar símbolos exigiria N processos com N inits da DLL — o que
# não funciona (2º init falha). A flag é mantida só para compatibilidade de
# linha-de-comando: qualquer valor > 1 é ignorado com aviso e os símbolos
# são processados sequencialmente, 1 por vez. (Multi-symbol real = Epic
# futuro com N processos — Q08-E.)
_DOWNLOAD_PARALLEL_OPT = typer.Option(
    1,
    "--parallel",
    "-p",
    help=(
        "DEPRECADO (ADR-022 — licença single-session). N>1 é ignorado com "
        "aviso; múltiplos --symbol são baixados sequencialmente, 1 por vez."
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
#
# Canonical path uses HYPHEN (``~/.data-downloader/``) — alinhado a
# :func:`data_downloader._internal.bundle_paths.user_data_dir`. Pré-fix
# este módulo usava UNDERSCORE (``~/.data_downloader/``), criando um
# diretório fantasma divergente do resto do app. Migração silenciosa
# best-effort em :func:`_migrate_legacy_last_symbol_cache` (sem crash).
def _last_symbol_cache_path() -> Path:
    from data_downloader._internal.bundle_paths import user_data_dir

    return user_data_dir() / "cache" / "last_symbol.txt"


def _migrate_legacy_last_symbol_cache() -> None:
    """Migra ``~/.data_downloader/cache/last_symbol.txt`` (underscore legacy)
    para o path canônico (hífen) se este último ainda não existir.

    Best-effort: qualquer ``OSError`` é apenas logado em ``warning`` e
    suprimido — UX cache é opcional, nunca pode quebrar a CLI.
    """
    import logging

    legacy = Path.home() / ".data_downloader" / "cache" / "last_symbol.txt"
    canonical = _last_symbol_cache_path()
    try:
        if legacy.exists() and not canonical.exists():
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_bytes(legacy.read_bytes())
    except OSError as exc:
        logging.getLogger("data_downloader.cli").warning(
            "last_symbol cache legacy migration skipped: %s", exc
        )


def _load_last_symbol() -> str | None:
    """Lê último símbolo usado do cache (CLI_PATTERNS §10)."""
    _migrate_legacy_last_symbol_cache()
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

    Compose: CLI typer → public_api.download → Orchestrator → DLL/writer/catalog.

    Múltiplos ``--symbol`` são baixados SEQUENCIALMENTE, 1 por vez
    (ADR-022 — licença single-session). ``--resume <job_id>`` retoma um
    download incompleto; sem ``--resume``, um job incompleto pro mesmo
    ``(símbolo, exchange, período)`` é detectado e retomado automaticamente
    (v1.2.0).

    Microcopy 100% via ``ui.microcopy_loader`` (R17 — Uma).
    Ctrl+C produz graceful shutdown (CLI_PATTERNS §7); exit code 130 (POSIX).
    """
    # Story 4.31 AC13: gc.freeze() boot-only — antes era chamado por job no
    # Orchestrator.run() e o heap "permanente" do GC crescia
    # monotonicamente. Idempotente (no-op em re-chamadas dentro do mesmo
    # processo).
    from data_downloader._internal.gc_boot import freeze_once

    freeze_once()

    console = _make_console()

    # ---- 1. Normaliza lista de símbolos ----
    # Q-DRIFT-32 2026-05-05: aplicamos resolve_alias() antes do loop para
    # que o cache last_symbol guarde o canônico (evita warning repetido em
    # re-runs com cache hit).
    from data_downloader.orchestrator.symbol_alias import resolve_alias

    symbols: list[str] = []
    if symbol:
        symbols = [resolve_alias(s) for s in symbol if s and s.strip()]

    if not symbols:
        cached = _load_last_symbol()
        if cached:
            symbols = [resolve_alias(cached)]
            console.print(f"[dim]Símbolo (cache): [bold]{symbols[0]}[/bold][/dim]")
        else:
            console.print(
                f"[red]✗ {_format_microcopy('ERR_INPUT_SYMBOL_REQUIRED', 'title')}[/red]\n"
                f"  {_format_microcopy('ERR_INPUT_SYMBOL_REQUIRED', 'detail')}\n"
                f"  {_format_microcopy('ERR_INPUT_SYMBOL_REQUIRED', 'action')}"
            )
            raise typer.Exit(code=2)

    # ---- 1b. Routing: sempre single-session sequencial (ADR-022) ----
    # A licença Nelogica é single-session (Q17-CLOSED — Hipótese B confirmada
    # pelo usuário). O broker multi-process (ADR-015 REVOKED) não funciona:
    # o 2º init da DLL falha. v1.2.0 removeu ``orchestrator/broker/`` (dead
    # code ~2034 LOC + footgun: o default usava um mock factory → gravava
    # parquet com dados FALSOS silenciosamente). ``--parallel N>1`` agora só
    # emite aviso; se múltiplos símbolos forem passados, eles são baixados
    # SEQUENCIALMENTE, 1 por vez (loop abaixo). ``--parallel`` é mantida só
    # para compat de CLI.
    if parallel > 1:
        console.print(
            "[yellow]⚠ --parallel N>1 desabilitado:[/yellow] a licença Nelogica "
            "é single-session (ADR-022) — baixando símbolos sequencialmente, "
            "1 por vez. (Multi-symbol real = Epic futuro com N processos.)\n"
        )
    if len(symbols) > 1:
        console.print(
            f"[dim]{len(symbols)} símbolos enfileirados — serão baixados em "
            f"sequência: {', '.join(symbols)}[/dim]"
        )

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

    # ── data_dir → ABSOLUTO e RESOLVIDO AGORA (Task #18) ──────────────────
    # CRÍTICO: a ProfitDLL faz chdir() para o diretório dela ao carregar
    # (quirk Q-DRIFT-10) — em frozen mode isso é ``_internal/``. Se
    # ``resolved_data_dir`` for relativo, o parquet writer (que roda DURANTE
    # o download, com o cwd já trocado pela DLL) resolveria ``data/`` para
    # ``_internal/data/``, escrevendo dentro do bundle. ``.resolve()`` captura
    # o cwd ORIGINAL do shell AGORA, antes de ``api_download()`` carregar a DLL.
    resolved_data_dir = (
        Path(data_dir).expanduser() if data_dir is not None else Path.cwd() / "data"
    ).resolve()

    # ---- 3. Loop sequencial sobre os símbolos (ADR-022 — single-session) ----
    # 1 símbolo (caso comum) → 1 iteração. >1 → processa em sequência. Cada
    # iteração roda o pipeline single-symbol completo (DLL singleton process-
    # global é reusada entre iterações). O exit code final reflete o pior
    # status entre os símbolos.
    worst_exit_code = 0
    for sym_idx, single_symbol in enumerate(symbols):
        if len(symbols) > 1:
            console.print(f"\n[dim]── símbolo {sym_idx + 1}/{len(symbols)} ──[/dim]")
        rc = _download_one_symbol(
            console=console,
            symbol=single_symbol,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            resolved_data_dir=resolved_data_dir,
            resume=resume if sym_idx == 0 else None,
            metrics_port=metrics_port if sym_idx == 0 else None,
        )
        worst_exit_code = max(worst_exit_code, rc)
    raise typer.Exit(code=worst_exit_code)


def _download_one_symbol(
    *,
    console: Console,
    symbol: str,
    start_date: date,
    end_date: date,
    exchange: str,
    resolved_data_dir: Path,
    resume: str | None,
    metrics_port: int | None,
) -> int:
    """Executa o pipeline single-symbol e retorna um exit code (0=ok).

    v1.2.0 — extraído de ``download_cmd`` para permitir o loop sequencial
    multi-symbol (ADR-022). ``resume`` é o job_id de ``--resume`` (ou
    ``None`` → auto-resume: se houver um job incompleto pro mesmo
    ``(symbol, exchange, [start, end])``, ele é retomado automaticamente).
    """
    single_symbol = symbol
    # ---- Auto-resume detection (v1.2.0) ----
    # Se o usuário não passou --resume, procuramos um job incompleto
    # (status partial/in_progress/failed/pending) pro mesmo (symbol,
    # exchange, range). Se houver, retomamos automaticamente (em vez de
    # registrar um job novo). Best-effort: erro de catalog não bloqueia.
    resume_job_id = resume
    if resume_job_id is None:
        resume_job_id = _detect_resumable_job(
            console=console,
            symbol=single_symbol,
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
            data_dir=resolved_data_dir,
        )

    # ---- 3b. Single-symbol header Rich (CLI_PATTERNS §2) ----
    resume_note = f" — retomando job {resume_job_id[:8]}…" if resume_job_id else ""
    console.print(
        Panel(
            f"[bold]Baixando[/bold] [cyan]{single_symbol}[/cyan] "
            f"({start_date.isoformat()} a {end_date.isoformat()}) — "
            f"exchange={exchange}{resume_note}",
            title="[cyan]⬇ data-downloader download[/cyan]",
            border_style="cyan",
        )
    )

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
            metrics_exporter = None
            return 2
        console.print(
            f"[cyan]📊 Métricas Prometheus expostas em "
            f"http://localhost:{metrics_port}/metrics[/cyan]"
        )

    # Import inline — evita custo de import de public_api quando o módulo CLI
    # é só importado (testes de smoke).
    from data_downloader.public_api.download import download as api_download

    try:
        handle = api_download(
            symbol=single_symbol,
            start=start_date,
            end=end_date,
            exchange=exchange,
            data_dir=resolved_data_dir,
            metrics_emitter=metrics_exporter,
            resume_job_id=resume_job_id,
        )
    except ValueError as exc:
        if metrics_exporter is not None:
            with contextlib.suppress(Exception):
                metrics_exporter.stop()
        console.print(f"[red]✗ Erro de input:[/red] {exc}")
        return 2

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
        return 1

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
        return 0
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
        return 0
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
        return 130
    if status in ("partial", "failed"):
        # Erro humanizado via humanize_nl_error quando possível.
        # Story v1.0.2 fix B-Frozen #3 (Nelo+Aria 2026-05-05): estender o mapping
        # para sentinelas internas usadas em frozen mode (verify script, DLL
        # load failure, etc.). Antes só humanizávamos prefix ``NL_*``; sentinelas
        # como ``COMPANIONS_MISSING``/``VERIFY_SCRIPT_MISSING`` caíam em
        # "Código ?: UNKNOWN", confundindo o usuário.
        from data_downloader.ui.microcopy_loader import (
            MicrocopyEntry,
            humanize_nl_error,
        )

        known_sentinels = _get_known_sentinels()
        sentinel_name: str | None = None
        nl_name: str | None = None
        tail: str = ""
        if final_result.error_message:
            head, _, tail_part = final_result.error_message.partition(":")
            head = head.strip()
            tail = tail_part.strip()
            if head.startswith("NL_"):
                nl_name = head
            elif head in known_sentinels:
                sentinel_name = head

        entry: MicrocopyEntry
        if sentinel_name is not None:
            template = known_sentinels[sentinel_name]
            # Substitui {tail} (e fallback {path}/{symbol}) — best-effort, sem
            # quebrar caso a sentinel não use placeholder.
            try:
                detail = (template.detail or "").format(tail=tail, path=tail, symbol=tail)
            except (KeyError, IndexError):  # pragma: no cover defensive
                detail = template.detail or ""
            entry = MicrocopyEntry(
                msg_type=template.msg_type,
                title=template.title,
                detail=detail,
                action=template.action,
            )
        else:
            entry = humanize_nl_error(nl_name)

        body = (
            f"[bold red]✗ {entry.title}[/bold red]\n"
            f"{entry.detail or final_result.error_message or ''}\n"
            f"[dim]{entry.action or ''}[/dim]"
        )
        console.print(
            Panel(body, title="erro", border_style="red"),
        )
        # v1.2.0 — se o job terminou ``partial`` (alguns chunks falharam),
        # imprime o comando para retomar só os faltantes.
        if status == "partial" and final_result.job_id:
            console.print(
                f"[yellow]↻ Alguns dias falharam.[/yellow] Rode "
                f"[bold]data-downloader download --symbol {single_symbol} "
                f"--resume {final_result.job_id}[/bold] para tentar de novo "
                "(ou re-rode o mesmo comando — os dias já baixados são pulados)."
            )
        # Exit code 3 indica erro mapeado/conhecido (NL_* ou sentinel),
        # 1 = erro não mapeado.
        return 3 if (nl_name or sentinel_name) else 1
    # Defensive — status desconhecido.
    console.print(f"[red]✗ Status desconhecido: {status}[/red]")  # pragma: no cover
    return 1


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
# Auto-resume detection (v1.2.0 Wave 1B)
# =====================================================================


def _detect_resumable_job(
    *,
    console: Console,
    symbol: str,
    exchange: str,
    start_date: date,
    end_date: date,
    data_dir: Path,
) -> str | None:
    """Procura no catalog um job incompleto pro mesmo ``(symbol, exchange, range)``.

    Retorna o ``job_id`` mais recente cujo ``status`` ∈ ``{pending,
    in_progress, partial, failed}`` E cujo ``requested_start/end`` casam
    com o range pedido. ``None`` se não houver (→ registra job novo). Em
    modo não-interativo apenas loga; não pergunta (autônomo). Best-effort:
    qualquer erro de catalog é suprimido (não bloqueia o download).
    """
    try:
        import sqlite3 as _sqlite3

        from data_downloader.public_api.download import _to_datetime  # reuse
        from data_downloader.storage.catalog import _format_ts

        start_dt = _to_datetime(start_date, end_of_day=False)
        end_dt = _to_datetime(end_date, end_of_day=True)
        db_path = data_dir / "_internal" / "catalog.db"
        if not db_path.exists():
            return None
        conn = _sqlite3.connect(str(db_path))
        conn.row_factory = _sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT job_id, status, started_at, requested_start, requested_end "
                "FROM downloads "
                "WHERE symbol = ? AND exchange = ? "
                "AND status IN ('pending','in_progress','partial','failed') "
                "AND requested_start = ? AND requested_end = ? "
                "ORDER BY COALESCE(started_at, '') DESC",
                (symbol, exchange, _format_ts(start_dt), _format_ts(end_dt)),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return None
        job_id = str(rows[0]["job_id"])
        status = str(rows[0]["status"])
        console.print(
            f"[yellow]↻ Job incompleto encontrado[/yellow] "
            f"([dim]{job_id[:8]}…[/dim], status={status}) — retomando "
            "(baixa só os dias úteis faltantes)."
        )
        return job_id
    except Exception as exc:  # pragma: no cover defensive — auto-resume é opcional
        import logging

        logging.getLogger("data_downloader.cli").debug("auto-resume detection skipped: %s", exc)
        return None


# =====================================================================
# doctor command (Story 4.9 — v1.0.3 hotfix)
# =====================================================================
#
# Diagnóstico do ambiente data-downloader. Owners Council B5 apontou que
# 6 microcopies + ``_CLI_SUBCOMMANDS`` em ``ui/app.py`` referenciam
# ``data-downloader doctor``, mas o comando NÃO estava implementado no
# Typer CLI até esta story. UI Settings tem botão "Diagnóstico Completo"
# (``BTN_DOCTOR_FULL``) — agora cabeado em :class:`SettingsScreen`.
#
# Checks (5 default + 1 opt-in):
#   1. DLL companions  — ProfitDLL.dll + .dat companions presentes
#   2. Credenciais     — PROFITDLL_KEY/USER/PASS em os.environ não-vazios
#   3. Disk            — data_dir writável, espaço livre >100MB
#   4. Schema          — catalog SQLite acessível, schema_version >= 1.1.0
#   5. Connectivity    — DNS+TCP servers Nelogica (lightweight)
#   6. DLL handshake   — opt-in (--with-handshake) — initialize_market_only quick
#
# Exit codes:
#   0 — todos os checks PASS (inclui WARN se schema antigo, mas sem fail)
#   1 — 1+ checks FAIL
#   2 — erro inesperado (defensivo)


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
    # Comparação semver simples major.minor.patch — suficiente para
    # 1.0.0 vs 1.1.0 vs 1.2.0.
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
    """Ping lightweight a servidores Nelogica via DNS resolve + TCP open.

    Não usa HTTP request real (Nelogica não expõe endpoint público
    bem-definido) — checa que o host resolve E aceita TCP em porta
    conhecida. Timeout curto (3s).
    """
    import socket

    hosts: tuple[tuple[str, int], ...] = (
        # Hosts conhecidos da família Nelogica (Story 4.9 — checagem
        # estática; futuro: ler de config). Porta 443 é HTTPS padrão.
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
    """Probe DLL handshake (opt-in via ``--with-handshake``).

    Mais lento (~3s) — invoca ``initialize_market_only`` + aguarda conexão
    com timeout reduzido. Útil em smoke real para validar credenciais
    end-to-end antes de iniciar download.
    """
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

    checks: list[tuple[str, tuple[str, str]]] = [
        ("DLL companions", _check_dll_companions()),
        ("Credenciais", _check_credentials()),
        ("Disk", _check_disk(data_dir)),
        ("Schema", _check_schema(data_dir)),
        ("Connectivity", _check_connectivity()),
    ]
    if with_handshake:
        checks.append(("DLL handshake", _check_dll_handshake()))

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


@app.command()  # type: ignore[misc,unused-ignore]
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
    exit_code, _ = run_doctor_checks(
        data_dir=data_dir,
        with_handshake=with_handshake,
        verbose=verbose,
    )
    raise typer.Exit(code=exit_code)


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


# =====================================================================


if __name__ == "__main__":
    app()
