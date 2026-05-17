"""data_downloader.cli.download — comando ``download`` (Story 1.7b).

Owner: Sol (Story 4.28 P0-A1 — split do monolito ``cli.py``).

Comando que compõe: CLI typer → public_api.download → Orchestrator →
DLL/writer/catalog. Múltiplos ``--symbol`` são baixados SEQUENCIALMENTE
(ADR-022 — licença single-session). Auto-resume v1.2.0 detecta jobs
incompletos sem ``--resume`` explícito.

Microcopy IDs (R17): ``HLP_DOWNLOAD``, ``SUC_DOWNLOAD_DONE``,
``SUC_CACHE_HIT``, ``SUC_CANCEL_DONE``, ``WAR_99_RECONNECT``,
``PMT_CANCEL_CONFIRM``, ``ERR_DLL_NO_LICENSE``, ``ERR_INPUT_*``.
"""

from __future__ import annotations

import contextlib
import logging
import signal
import threading
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from data_downloader.cli._helpers import (
    _approx_size_mb,
    _default_period,
    _format_duration,
    _format_microcopy,
    _get_known_sentinels,
    _load_last_symbol,
    _make_console,
    _save_last_symbol,
)

if TYPE_CHECKING:
    from rich.console import Console


__all__ = ["download_cmd", "register"]


def register(app: typer.Typer) -> None:
    """Registra o comando ``download`` no ``app`` raiz."""
    app.command("download")(download_cmd)


# Module-level singletons p/ typer.Option (evita ruff B008).
_DOWNLOAD_SYMBOL_OPT = typer.Option(
    None,
    "--symbol",
    "-s",
    help=(
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
# `--parallel` — DEPRECADO (ADR-022): licença single-session.
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
    console = _make_console()

    # ---- 1. Normaliza lista de símbolos ----
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
            start = first.isoformat()  # type: ignore[attr-defined]
        if end is None:
            end = today.isoformat()  # type: ignore[attr-defined]

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
    ``None`` → auto-resume).
    """
    single_symbol = symbol
    # ---- Auto-resume detection (v1.2.0) ----
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

    # Story 2.4 — opt-in PrometheusExporter HTTP.
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

    # Import inline — evita custo de import de public_api em smoke tests.
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
            if ev.total > 0:
                progress.update(
                    task_id,
                    total=ev.total,
                    completed=ev.done,
                    description=f"Baixando {progress_state['current_contract']}",
                )
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
            while True:
                if cancel_requested.is_set():
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
                        final_result = handle.result(timeout=120.0)
                        break
                    cancel_requested.clear()
                    progress.start()
                    continue
                try:
                    final_result = handle.result(timeout=0.25)
                    break
                except TimeoutError:
                    continue
    finally:
        signal.signal(signal.SIGINT, orig_handler)
        drain_thread.join(timeout=2.0)
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
        # v1.2.0 — se o job terminou ``partial``, imprime comando de retomada.
        if status == "partial" and final_result.job_id:
            console.print(
                f"[yellow]↻ Alguns dias falharam.[/yellow] Rode "
                f"[bold]data-downloader download --symbol {single_symbol} "
                f"--resume {final_result.job_id}[/bold] para tentar de novo "
                "(ou re-rode o mesmo comando — os dias já baixados são pulados)."
            )
        return 3 if (nl_name or sentinel_name) else 1
    # Defensive — status desconhecido.
    console.print(f"[red]✗ Status desconhecido: {status}[/red]")  # pragma: no cover
    return 1


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
    com o range pedido. ``None`` se não houver. Best-effort: qualquer
    erro de catalog é suprimido (não bloqueia o download).
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
        logging.getLogger("data_downloader.cli").debug("auto-resume detection skipped: %s", exc)
        return None
