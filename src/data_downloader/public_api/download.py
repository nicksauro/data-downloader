"""data_downloader.public_api.download — fronteira pública para download.

Owner: Aria (design — public_api SemVer ADR-007a) + Dex (impl).
Story 1.7b — AC7 (download function), AC8 (DownloadHandle exports).

Wrapper estável sobre :class:`Orchestrator.run` (Story 1.7a). Garantias
contratuais (ADR-007a):

1. **Estável** — assinatura SemVer-tracked. Bumpa
   ``__api_version__`` 0.2.0 → 0.3.0 (minor aditivo).
2. **Async** — retorna :class:`DownloadHandle` imediatamente; worker
   thread executa o pipeline. Não bloqueia o caller.
3. **BRT naive (R7)** — ``date`` ou ``datetime`` aceitos; convertidos
   para naive datetime alinhado em meia-noite (start) / 23:59:59 (end).
4. **Cancelamento graceful** — ``handle.cancel()`` checa Event entre
   chunks; drena writer + commita parcial; marca job como ``cancelled``
   no catalog.

Microcopy (R17 — Uma):
    Esta camada NÃO emite strings ao usuário; quem renderiza é o caller
    (CLI ou Qt). Eventos via :class:`DownloadProgress.message` carregam
    IDs de microcopy ou texto técnico curto — caller deve mapear via
    ``ui.microcopy_loader.format_msg``.

Notas de implementação:
    - Worker thread é daemon — se o processo morre, thread morre junto.
      Para cleanup determinístico, caller usa ``handle.result()`` (join).
    - Catalog/DLL/Writer são instanciados DENTRO do worker — owner
      semantics claras (worker dono do lifecycle).
"""

from __future__ import annotations

import contextlib
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from data_downloader.public_api.handle import (
    DownloadHandle,
    DownloadProgress,
    DownloadResult,
)

if TYPE_CHECKING:
    import queue
    import threading
    from collections.abc import Callable

    from data_downloader.contracts.observability import MetricsEmitter

__all__ = [
    "DownloadHandle",
    "DownloadProgress",
    "DownloadResult",
    "download",
]


# Default chunk size para hint de "starting" event.
_DEFAULT_DATA_DIR_NAME = "data"


def download(
    symbol: str,
    start: date | datetime,
    end: date | datetime,
    *,
    exchange: str = "F",
    data_dir: Path | None = None,
    dll_factory: Callable[[], object] | None = None,
    catalog_factory: Callable[[Path], object] | None = None,
    writer_factory: Callable[[Path], object] | None = None,
    metrics_emitter: MetricsEmitter | None = None,
) -> DownloadHandle:
    """Inicia download assíncrono de histórico para ``symbol`` em ``[start, end]``.

    Constrói DLL + catalog + writer + orchestrator dentro de uma worker
    thread, executa :meth:`Orchestrator.run`, e retorna handle imediatamente.
    Caller usa :meth:`DownloadHandle.events` para progress e
    :meth:`DownloadHandle.result` para resultado final.

    Args:
        symbol: Contrato vigente (``"WDOJ26"``) ou raiz (``"WDO"``). Se
            for raiz, orchestrator resolve via tabela ``contracts`` no
            catalog usando ``start`` como ``on_date``.
        start: Início do range. ``date`` ou ``datetime`` — convertidos
            para datetime naive BRT (00:00:00 do dia se ``date``).
        end: Fim inclusivo. ``date`` ou ``datetime`` — convertidos para
            datetime naive (23:59:59.999999 do dia se ``date``).
        exchange: ``"F"`` (BMF, default) ou ``"B"`` (Bovespa).
        data_dir: Raiz dos dados (default: ``Path("data")`` no cwd).
        dll_factory: Override para testes — callable sem args que retorna
            algo com a interface de :class:`ProfitDLL` já inicializada.
            Default: cria :class:`ProfitDLL` real e chama
            ``initialize_market_only`` com env vars.
        catalog_factory: Override para testes — callable que recebe
            ``data_dir`` e retorna :class:`Catalog`. Default: usa
            ``Catalog(db_path=data_dir/'history'/'catalog.db')``.
        writer_factory: Override para testes — callable que recebe
            ``data_dir`` e retorna :class:`ParquetWriter`. Default:
            ``ParquetWriter(data_dir=data_dir)``.
        metrics_emitter: Story 2.4 — emitter de métricas opcional
            (e.g. :class:`PrometheusExporter`). Default: ``None`` →
            orchestrator usa :class:`NullMetricsEmitter` (zero overhead).
            Lifecycle do exporter (start/stop HTTP server) é
            responsabilidade do caller.

    Returns:
        :class:`DownloadHandle` — async handle. Use ``handle.events()`` para
        progress, ``handle.result()`` para resultado final, ``handle.cancel()``
        para abortar (graceful drain).

    Raises:
        ValueError: ``exchange`` fora de ``{"F", "B"}`` ou ``end < start``.
            (Validado SÍNCRONAMENTE antes de spawnar worker.)

    Examples:
        Download síncrono (bloqueia até completar)::

            from datetime import date
            from data_downloader.public_api import download

            handle = download("WDOJ26", start=date(2026, 4, 1), end=date(2026, 4, 30))
            result = handle.result()
            # result.trades_count, result.partitions disponíveis para uso

        Download com progress UI (caller wires logging/UI update)::

            handle = download("WDOJ26", start=..., end=...)
            for event in handle.events():
                logger.info("progress", done=event.done, total=event.total, msg=event.message)
            result = handle.result()

        Cancelamento cooperativo::

            handle = download("WDOJ26", start=..., end=...)
            # ... em outra thread / após sigint:
            handle.cancel(timeout=30.0)
            try:
                handle.result()
            except OperationCancelled as exc:
                preserved = exc.details["trades_preserved"]
                logger.warning("cancelled", trades_preserved=preserved)

    Notes:
        - **Async** (R6): retorna handle imediatamente. Worker thread é
          daemon — se o processo morre, thread morre junto. Para cleanup
          determinístico, caller usa ``handle.result()`` (join).
        - **Idempotente** (R5): re-runs com mesmo ``(symbol, start, end,
          exchange)`` deduplicate via writer canonical key. Re-runs após
          crash são seguros.
        - **BRT naive** (R7): ``start``/``end`` são convertidos para
          datetime naive (00:00:00 e 23:59:59.999999 se ``date`` puro).
          ``datetime`` aware tem ``tzinfo`` removido silenciosamente.
        - **Cancel graceful**: ``handle.cancel()`` checa Event entre
          chunks; drena writer + commita parcial; marca job como
          ``cancelled`` no catalog. Status final ``"cancelled"``.
        - Componentes (DLL/catalog/writer) são instanciados DENTRO do
          worker — owner semantics claras (worker dono do lifecycle).
    """
    # Validação síncrona de inputs (falha cedo antes do thread).
    if exchange not in ("F", "B"):
        raise ValueError(f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}")

    start_dt = _to_datetime(start, end_of_day=False)
    end_dt = _to_datetime(end, end_of_day=True)
    if end_dt < start_dt:
        raise ValueError(f"end ({end_dt.isoformat()}) must be >= start ({start_dt.isoformat()})")

    resolved_data_dir = Path(data_dir) if data_dir is not None else Path(_DEFAULT_DATA_DIR_NAME)

    # Story 2.9 — captura snapshot de contextvars do thread chamador (CLI
    # main ou app caller) para propagar correlation_id eventual + qualquer
    # bind feito antes de chamar download(). Aplicado dentro do worker via
    # ctx.run.
    import contextvars as _contextvars

    parent_ctx = _contextvars.copy_context()

    # Worker target — recebe os signals via kwargs do DownloadHandle._runner.
    def _worker(
        *,
        cancel_event: threading.Event,
        events_queue: queue.Queue[object],
        set_result: Callable[[DownloadResult], None],
    ) -> None:
        # Story 2.9 — propaga contextvars do parent thread (orchestrator
        # vai bind seu próprio job_id, mas qualquer bind feito por caller
        # antes de download() é preservado — defesa em profundidade).
        def _go() -> None:
            _run_download_worker(
                symbol=symbol,
                exchange=exchange,
                start=start_dt,
                end=end_dt,
                data_dir=resolved_data_dir,
                cancel_event=cancel_event,
                events_queue=events_queue,
                set_result=set_result,
                dll_factory=dll_factory,
                catalog_factory=catalog_factory,
                writer_factory=writer_factory,
                metrics_emitter=metrics_emitter,
            )

        parent_ctx.run(_go)

    return DownloadHandle(worker_target=_worker)


# =====================================================================
# Worker implementation
# =====================================================================


def _run_download_worker(
    *,
    symbol: str,
    exchange: str,
    start: datetime,
    end: datetime,
    data_dir: Path,
    cancel_event: threading.Event,
    events_queue: queue.Queue[object],
    set_result: Callable[[DownloadResult], None],
    dll_factory: Callable[[], object] | None,
    catalog_factory: Callable[[Path], object] | None,
    writer_factory: Callable[[Path], object] | None,
    metrics_emitter: MetricsEmitter | None = None,
) -> None:
    """Worker: instancia componentes, roda Orchestrator.run, traduz JobResult.

    Captura todas as exceções e produz ``DownloadResult(status='failed')``
    com mensagem humana — fronteira pública NÃO leaka exceptions internas.
    """
    # Imports inline — evita custo de import quando o módulo é só importado
    # para tipo (TYPE_CHECKING above).
    from data_downloader.orchestrator.orchestrator import (
        JobConfig,
        JobResult,
        Orchestrator,
    )
    from data_downloader.public_api.exceptions import (
        DataDownloaderError,
        DLLInitError,
        DownloadError,
    )
    from data_downloader.storage.catalog import Catalog
    from data_downloader.storage.parquet_writer import ParquetWriter

    job_id = ""
    contract_code = symbol
    started = time.monotonic()
    actual_start: datetime | None = None
    actual_end: datetime | None = None

    # ---- Componentes ----
    dll: object | None = None
    catalog: Catalog | None = None
    writer: ParquetWriter | None = None
    own_dll = False  # Se criamos a DLL aqui, finalizamos no fim.

    try:
        # 1. Catalog.
        if catalog_factory is not None:
            catalog = catalog_factory(data_dir)  # type: ignore[assignment]
        else:
            db_path = data_dir / "history" / "catalog.db"
            catalog = Catalog(db_path=db_path, data_dir=data_dir)

        # 2. Writer.
        if writer_factory is not None:
            writer = writer_factory(data_dir)  # type: ignore[assignment]
        else:
            writer = ParquetWriter(data_dir=data_dir)

        # 3. DLL — caller pode passar mock; senão init real.
        if dll_factory is not None:
            dll = dll_factory()
        else:
            dll = _build_real_dll(events_queue)
            own_dll = True

        # 4. Cancel check antes de qualquer trabalho pesado.
        if cancel_event.is_set():
            _emit(events_queue, _progress_cancel(0, 0, "cancelled before start"))
            set_result(
                _make_result(
                    job_id=job_id,
                    symbol=contract_code,
                    exchange=exchange,
                    actual_start=None,
                    actual_end=None,
                    trades_count=0,
                    partitions=(),
                    duration=0.0,
                    status="cancelled",
                )
            )
            return

        # 5. Compose Orchestrator. ``catalog``/``writer``/``dll`` foram
        # criados no try acima (sempre não-None aqui); afirma-se para mypy.
        assert catalog is not None
        assert writer is not None
        assert dll is not None
        orchestrator = Orchestrator(
            dll=dll,  # type: ignore[arg-type]
            catalog=catalog,
            writer=writer,
            metrics_emitter=metrics_emitter,
        )
        config = JobConfig(
            symbol=symbol,
            exchange=exchange,
            start=start,
            end=end,
            # resolve_contract: True se symbol é raiz (sem letra+ano), False senão.
            resolve_contract=_looks_like_root(symbol),
        )

        _emit(
            events_queue,
            DownloadProgress(
                total=-1,
                done=0,
                message="INF_STARTING_DOWNLOAD",
                trades_received=0,
                current_contract=symbol,
            ),
        )

        # 6. Execute. Story 2.11 — H10 closure: passa cancel_event ao
        # orchestrator. Loop interno checa entre chunks (graceful drain,
        # NÃO interrompe chunk em andamento). Após retorno, verificamos
        # cancel_event.is_set() para decidir entre status='cancelled' e
        # status normal (mapeamento de JobResult.status).
        result_obj: JobResult = orchestrator.run(config, cancel_event=cancel_event)

        contract_code = result_obj.contract_code
        job_id = result_obj.job_id
        actual_start = result_obj.metrics.started_at
        actual_end = result_obj.metrics.completed_at

        # Se cancelamento foi pedido durante run, marca job como cancelled
        # (catalog) e retorna DownloadResult(status='cancelled').
        if cancel_event.is_set():
            with contextlib.suppress(Exception):
                catalog.update_job_progress(job_id, status="cancelled")
            duration = time.monotonic() - started
            set_result(
                _make_result(
                    job_id=job_id,
                    symbol=contract_code,
                    exchange=exchange,
                    actual_start=actual_start,
                    actual_end=actual_end,
                    trades_count=result_obj.metrics.trades_persisted,
                    partitions=result_obj.partitions_written,
                    duration=duration,
                    status="cancelled",
                )
            )
            return

        # Status final — espelha JobResult.status.
        status_map = {
            "completed": "completed",
            "partial": "partial",
            "failed": "failed",
            "cache_hit": "cache_hit",
        }
        final_status = status_map.get(result_obj.status, "failed")
        duration = time.monotonic() - started
        set_result(
            _make_result(
                job_id=job_id,
                symbol=contract_code,
                exchange=exchange,
                actual_start=actual_start,
                actual_end=actual_end,
                trades_count=result_obj.metrics.trades_persisted,
                partitions=result_obj.partitions_written,
                duration=duration,
                status=final_status,
            )
        )

    except DataDownloaderError as exc:
        # Erros públicos já vêm humanizados (DLLInitError tem .name → microcopy).
        duration = time.monotonic() - started
        err_msg = str(exc)
        # DLLInitError tem .name (NL_*); guardamos para o CLI mapear.
        if isinstance(exc, DLLInitError):
            err_msg = f"{exc.name}: {exc.args[0]}"
        set_result(
            _make_result(
                job_id=job_id,
                symbol=contract_code,
                exchange=exchange,
                actual_start=actual_start,
                actual_end=actual_end,
                trades_count=0,
                partitions=(),
                duration=duration,
                status="failed",
                error_message=err_msg,
            )
        )
    except (DownloadError, OSError, RuntimeError, AttributeError, ValueError) as exc:
        # Erros não-públicos — fronteira não pode leak exception.
        duration = time.monotonic() - started
        set_result(
            _make_result(
                job_id=job_id,
                symbol=contract_code,
                exchange=exchange,
                actual_start=actual_start,
                actual_end=actual_end,
                trades_count=0,
                partitions=(),
                duration=duration,
                status="failed",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        )
    finally:
        # Cleanup determinístico — ordem reversa de criação.
        if own_dll and dll is not None:
            finalize_fn = getattr(dll, "finalize", None)
            if callable(finalize_fn):
                with contextlib.suppress(Exception):
                    finalize_fn()
        if catalog is not None:
            with contextlib.suppress(Exception):
                catalog.close()


# =====================================================================
# Helpers
# =====================================================================


def _to_datetime(value: date | datetime, *, end_of_day: bool) -> datetime:
    """Converte ``date`` ou ``datetime`` para datetime naive BRT.

    - ``datetime`` aware → strip tz (assume já BRT — R7).
    - ``date`` puro → ``00:00:00`` (start) ou ``23:59:59.999999`` (end).
    """
    if isinstance(value, datetime):
        # datetime is subclass of date → check first.
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value
    # ``date`` puro.
    if end_of_day:
        return datetime(value.year, value.month, value.day, 23, 59, 59, 999_999)
    return datetime(value.year, value.month, value.day, 0, 0, 0)


def _looks_like_root(symbol: str) -> bool:
    """Heurística simples: ``"WDO"`` é raiz; ``"WDOJ26"`` é contrato vigente.

    Regra: contrato vigente termina em letra-mês + 2 dígitos (ex.: ``J26``).
    Se o símbolo tem >= 4 chars E os 2 últimos são dígitos, consideramos
    "contrato vigente" (não resolve via catalog).

    Usado por :func:`download` para decidir ``resolve_contract`` flag.
    """
    if len(symbol) < 4:
        return True  # ex.: 'WDO', 'WIN' — claramente raiz
    last_two = symbol[-2:]
    return not last_two.isdigit()


def _build_real_dll(events_queue: queue.Queue[object]) -> object:
    """Constrói e inicializa uma instância real de :class:`ProfitDLL`.

    Lê credenciais de env (``PROFITDLL_KEY``, ``PROFITDLL_USER``,
    ``PROFITDLL_PASS``) — naming canônico alinhado com ``.env.example``
    (Q-DRIFT-03).

    O timeout do handshake ``MARKET_DATA`` é configurável via
    ``DATA_DOWNLOADER_DLL_CONNECT_TIMEOUT`` (default 300s) — Q-DRIFT-02
    documenta que o handshake pode levar minutos quando o ProfitChart
    não está aberto concorrentemente.

    **Story 1.7d (espelho ESTRITO do probe — Q-DRIFT-12):** quando
    ``DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE`` ∈ ``{"1","true","yes"}``
    (case-insensitive), o init usa o caminho ``minimal_handshake=True``
    que espelha o probe canônico EXATAMENTE — pula
    ``_configure_dll_signatures`` em larga escala, pula
    ``SetEnabledLogToDebug(0)``, passa ``None`` literal nos slots 4/6/7/8
    e callbacks REAIS (``TDailyCallback``, ``TProgressCallback``,
    ``TTinyBookCallback``) nos slots 5/9/10 do ``DLLInitializeMarketLogin``.
    Corrige o bug da Story 1.7c (que passava ``None`` em todos os 7 slots
    não-state, divergindo do probe). Default (var ausente / vazia)
    preserva o caminho atual.

    Args:
        events_queue: usado para emitir progresso "starting DLL" antes do
            init real (que pode demorar 5-30s em prod).

    Returns:
        Instância de :class:`ProfitDLL` já conectada.
    """
    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.public_api.exceptions import DLLInitError

    key = os.getenv("PROFITDLL_KEY")
    user = os.getenv("PROFITDLL_USER")
    password = os.getenv("PROFITDLL_PASS")
    if not (key and user and password):
        raise DLLInitError(
            -1,
            "NL_NO_LICENSE",
            "ERR_DLL_NO_LICENSE",
        )

    _emit(
        events_queue,
        DownloadProgress(
            total=-1,
            done=0,
            message="INF_STARTING_DLL",
            trades_received=0,
        ),
    )
    dll = ProfitDLL()
    # Story 1.7d — espelho ESTRITO do probe (testa Q-DRIFT-12). Quando
    # ``DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE`` está definida como ``1``,
    # ``true`` ou ``yes`` (case-insensitive), o init usa o caminho que
    # espelha EXATAMENTE o probe canônico (``scripts/probe_init.py``
    # L239-251) — pula ``_configure_dll_signatures`` em larga escala,
    # pula ``SetEnabledLogToDebug(0)``, passa ``None`` literal nos slots
    # 4/6/7/8 e callbacks REAIS (TDailyCallback, TProgressCallback,
    # TTinyBookCallback) nos slots 5/9/10 do ``DLLInitializeMarketLogin``.
    # Default ``False`` preserva o comportamento atual.
    minimal_handshake = os.getenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    dll.initialize_market_only(key, user, password, minimal_handshake=minimal_handshake)
    # Story 2.12 — retry policy mitiga flakiness Q-DRIFT-02 revisado.
    # Defaults: 300s/tentativa, 3 tentativas, 30s cooldown — cap superior
    # 990s no pior caso (3*300 + 2*30). Operador ajusta via env vars se
    # rede/horário exigir.
    connect_timeout = _env_int("DATA_DOWNLOADER_DLL_CONNECT_TIMEOUT", 300, minimum=1)
    retry_attempts = _env_int("DATA_DOWNLOADER_DLL_CONNECT_RETRY_ATTEMPTS", 3, minimum=1)
    retry_cooldown = _env_float("DATA_DOWNLOADER_DLL_CONNECT_RETRY_COOLDOWN", 30.0, minimum=0.0)
    if not dll.wait_market_connected(
        timeout=connect_timeout,
        retry_attempts=retry_attempts,
        retry_cooldown=retry_cooldown,
    ):
        raise DLLInitError(
            -1,
            "NL_WAITING_SERVER",
            (
                f"MARKET_DATA não conectou após {retry_attempts} tentativas "
                f"de {connect_timeout}s (cooldown {retry_cooldown:.0f}s). "
                "Verifique horário de pregão B3 (09:00-18:30 BRT) e conexão "
                "de rede (Q-DRIFT-02)."
            ),
        )
    _emit(
        events_queue,
        DownloadProgress(
            total=-1,
            done=0,
            message="INF_DLL_READY",
            trades_received=0,
        ),
    )
    return dll


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    """Lê env var como int com fallback robusto (Story 2.12).

    Valores inválidos (não-int, abaixo de ``minimum``) caem para ``default``
    silenciosamente — env malformada não para o sistema.

    Args:
        name: Nome da env var.
        default: Valor a usar se ausente ou inválido.
        minimum: Valor mínimo aceitável (>= ``minimum``).

    Returns:
        Int válido (env value ou default).
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    """Lê env var como float com fallback robusto (Story 2.12).

    Args:
        name: Nome da env var.
        default: Valor a usar se ausente ou inválido.
        minimum: Valor mínimo aceitável (>= ``minimum``).

    Returns:
        Float válido (env value ou default).
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def _emit(events_queue: queue.Queue[object], event: DownloadProgress) -> None:
    """Tenta colocar evento na queue; descarta silenciosamente em caso de queue full.

    Telemetria é best-effort (R21 — observability não pode bloquear hot path).
    """
    with contextlib.suppress(Exception):
        events_queue.put_nowait(event)


def _progress_cancel(done: int, total: int, message: str) -> DownloadProgress:
    return DownloadProgress(
        total=total,
        done=done,
        message=message,
        trades_received=0,
    )


def _make_result(
    *,
    job_id: str,
    symbol: str,
    exchange: str,
    actual_start: datetime | None,
    actual_end: datetime | None,
    trades_count: int,
    partitions: tuple[Path, ...],
    duration: float,
    status: str,
    error_message: str | None = None,
) -> DownloadResult:
    """Helper para reduzir verbosidade na construção do DownloadResult."""
    return DownloadResult(
        job_id=job_id,
        symbol=symbol,
        exchange=exchange,
        actual_start=actual_start,
        actual_end=actual_end,
        trades_count=trades_count,
        partitions=partitions,
        duration_seconds=duration,
        status=status,  # type: ignore[arg-type]
        error_message=error_message,
    )


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
