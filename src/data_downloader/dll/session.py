"""data_downloader.dll.session — DLL singleton process-global (task #21).

Owner: Dex (impl) | RCA: Nelo (@profitdll-specialist, Q08-E).

A ProfitDLL Classic 4.0.0.35 **não é re-inicializável** dentro do mesmo
processo: ``Finalize``/``DLLFinalize`` não zeram o estado interno (a
``ConnectorThread`` da 1ª sessão morre mas o estado global continua sujo),
então um 2º ``DLLInitializeMarketLogin`` no mesmo processo crasha — a
``ConnectorThread`` nova posta mensagens para a thread morta da 1ª sessão
(``ERROR_INVALID_THREAD_ID`` / ``ERROR_INVALID_WINDOW_HANDLE``) e
``CreateDataLoader`` pega um ponteiro de interface morto → access violation
em ``System.@IntfCopy`` (``Erro.log`` Pichau 2026-05-12).

Antes do task #21, a UI fazia DOIS inits no mesmo processo:

    1. "Testar Conexão" → ``_TestConnectionWorker.run`` →
       ``with ProfitDLL() as dll: dll.initialize_market_only(...)`` →
       ``__exit__`` chama ``finalize()`` (1º init + finalize).
    2. "Baixar" → ``public_api.download._build_real_dll`` cria OUTRA
       ``ProfitDLL()`` e re-inicializa (2º init → CRASH).

Fix: **uma única instância ``ProfitDLL`` por processo**. ``get_dll()``
inicializa na 1ª chamada e retorna a mesma instância nas seguintes (NÃO
re-inicializa, NÃO finaliza). ``shutdown_dll()`` finaliza UMA vez no
encerramento do processo (``atexit`` + ``MainWindow.closeEvent``).

Referências:
    - docs/dll/QUIRKS.md Q08-E
    - docs/adr/ADR-022-single-session-sequential-policy.md
"""

from __future__ import annotations

import atexit
import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL

__all__ = [
    "current_state",
    "get_dll",
    "has_active_dll",
    "register_state_observer",
    "resolve_dll_init_mode",
    "set_downloading",
    "shutdown_dll",
    "unregister_state_observer",
]

log: structlog.stdlib.BoundLogger = structlog.get_logger("data_downloader.dll.session")

# Estado process-global. Protegido por ``_LOCK`` — ``get_dll`` pode ser
# chamado de QThread workers (Test Connection) e da download worker thread.
_LOCK = threading.Lock()
_DLL_INSTANCE: ProfitDLL | None = None
_ATEXIT_REGISTERED = False
# v1.3.0 Wave 2A: usados para serializar 2 threads paralelos tentando init
# simultaneamente sem segurar ``_LOCK`` durante o init em si (caro). A 1ª
# thread seta ``_INIT_IN_PROGRESS`` antes do Initialize; a 2ª aguarda
# ``_INIT_DONE`` (Event) e depois retenta do topo.
_INIT_IN_PROGRESS = threading.Event()
_INIT_DONE = threading.Event()
_INIT_DONE.set()  # estado inicial: nenhum init em andamento
# init_kwargs com que ``_DLL_INSTANCE`` foi inicializada — usado para
# detectar descasamentos de modo entre call sites (fix #21b).
_DLL_INIT_KWARGS: dict[str, Any] = {}

# init_kwargs que afetam o MODO de inicialização da DLL (quais callbacks são
# registrados, signatures configuradas, etc.). Um descasamento nestes entre
# call sites é o que causou a falha funcional do fix #21 (Test Connection
# inicializava minimal → Download reusava a instância minimal → DLL crashava
# internamente ao traduzir trades). Credenciais (key/user/password) NÃO
# entram aqui — não afetam o modo.
_MODE_AFFECTING_KWARGS = ("minimal_handshake", "register_extra_callbacks")

_TRUTHY = {"1", "true", "yes"}

# =====================================================================
# v1.3.0 Wave 2A — Observer pattern (puro Python, sem deps Qt)
# =====================================================================
#
# Antes da Wave 2A o lifecycle real da DLL (init/finalize, conectado/
# desconectado) só era observável pelo ``_TestConnectionWorker`` em
# ``settings_screen`` — a UI fazia o tracking manual e ficava desincronizada
# durante o download (Bug 3 Pichau: statusbar "DLL: desconectada" em pleno
# meio do download de WDOFUT).
#
# A solução é tornar o singleton ``dll.session`` a fonte única de verdade
# do estado, com um observer pattern puro Python (sem importar Qt aqui —
# session.py é módulo de baixo nível, consumido por CLI + UI + tests).
# A camada Qt (``ui.adapters.dll_session_adapter``) wrappeia esta API em
# um ``QObject`` com ``Signal(str, str)``.
#
# Estados (5, decisão Uma):
#   - ``"idle"``         — DLL ainda não inicializada / pós-shutdown
#   - ``"connecting"``   — get_dll começou ``Initialize`` (init em curso)
#   - ``"connected"``    — DLL conectada (MARKET_CONNECTED após handshake)
#   - ``"downloading"``  — orchestrator está rodando (set via set_downloading)
#   - ``"reconnecting"`` — state_monitor detectou MARKET_DATA != CONNECTED
#                          durante run; orchestrator pausou entre chunks
#   - ``"error"``        — init falhou ou DLL caiu de forma irrecuperável
#
# Thread-safety: ``_set_state`` toma ``_LOCK`` (mesmo lock do singleton)
# para atualizar module-state E snapshot a lista de observers. Os callbacks
# são invocados FORA do lock (evita deadlock se um callback chama
# ``current_state`` ou ``has_active_dll``). Observer falho é loggado e
# isolado — uma exceção em um cb NÃO derruba os outros nem altera o
# state já gravado.

_DLL_STATE: str = "idle"
_DLL_VERSION: str = "—"
_OBSERVERS: list[Callable[[str, str], None]] = []


def register_state_observer(cb: Callable[[str, str], None]) -> None:
    """Registra ``cb`` para ser invocado em cada transição de estado.

    ``cb(state, version)`` é chamado SÍNCRONO na thread que provocou a
    transição (pode ser worker, MainThread, atexit, etc.) — observers
    UI DEVEM marshalar para o MainThread internamente (ver
    ``DllSessionAdapter``).

    Idempotente: chamar 2x com a MESMA referência registra apenas 1x.

    Args:
        cb: Callable ``(state, version) -> None``. NÃO deve levantar —
            exceções são engolidas + logadas (não-fatal por design para
            que um observer bugado não derrube outros).
    """
    with _LOCK:
        if cb not in _OBSERVERS:
            _OBSERVERS.append(cb)


def unregister_state_observer(cb: Callable[[str, str], None]) -> None:
    """Remove ``cb`` da lista de observers (idempotente — no-op se ausente)."""
    import contextlib

    with _LOCK, contextlib.suppress(ValueError):
        _OBSERVERS.remove(cb)


def _set_state(state: str, version: str = "") -> None:
    """Atualiza estado module-global + notifica todos os observers.

    Thread-safe: ``_LOCK`` protege update + snapshot da lista de observers.
    Callbacks rodam FORA do lock (evita deadlock). Cada callback é
    isolado em try/except — observer falho NÃO interrompe os outros.

    Args:
        state: novo estado (``idle`` / ``connecting`` / ``connected`` /
            ``downloading`` / ``reconnecting`` / ``error``).
        version: string da versão DLL — passado para "connected" /
            "downloading"; ignorado (mantém valor anterior) se vazio em
            transições que não envolvem reset de versão.
    """
    global _DLL_STATE, _DLL_VERSION

    with _LOCK:
        prev_state = _DLL_STATE
        _DLL_STATE = state
        if version:
            _DLL_VERSION = version
        elif state in ("idle", "error"):
            _DLL_VERSION = "—"
        snapshot = list(_OBSERVERS)
        current_version = _DLL_VERSION

    log.info(
        "dll.session.state",
        state=state,
        prev=prev_state,
        version=current_version,
    )

    for cb in snapshot:
        try:
            cb(state, current_version)
        except Exception as exc:
            log.warning(
                "dll.session.observer_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )


def current_state() -> tuple[str, str]:
    """Snapshot read-only do estado atual ``(state, version)``.

    Usado pela UI no boot para se sincronizar — antes do observer ser
    registrado o estado já pode ter avançado de ``idle`` (cli boot
    inicializou a DLL antes do MainWindow construir).
    """
    with _LOCK:
        return _DLL_STATE, _DLL_VERSION


def set_downloading(symbol: str = "") -> None:
    """Helper para o orchestrator marcar estado ``downloading``.

    Encapsula ``_set_state("downloading", ...)`` — symbol é opcional
    (passado como "version" pelo signal pra UI exibir; default ``"—"``
    quando vazio).
    """
    _set_state("downloading", symbol or "—")


def resolve_dll_init_mode() -> dict[str, Any]:
    """Resolve o MODO de inicialização da ProfitDLL a partir do ambiente.

    Fonte única da verdade compartilhada por TODOS os call sites de
    ``get_dll`` (``public_api.download._build_real_dll`` e
    ``ui.screens.settings_screen._TestConnectionWorker.run``) — garante que
    Test Connection e Download SEMPRE concordem no modo, para que o singleton
    process-global possa reusar a instância sem causar a falha funcional do
    fix #21 (a DLL Classic não é re-inicializável — Q08-E — então uma vez
    inicializada num modo, esse modo vale para o processo todo).

    Hoje resolve apenas ``minimal_handshake`` a partir de
    ``DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE`` (``1``/``true``/``yes``
    case-insensitive → ``True``; ausente/qualquer outro → ``False``). O
    default ``False`` = modo COMPLETO (registra os callbacks de trade), que é
    o único validado para baixar histórico (smoke real WDOFUT 5d = 2.8M
    trades). Novos kwargs que afetem o modo devem ser resolvidos aqui.

    Returns:
        ``dict`` de init_kwargs de modo, ex.: ``{"minimal_handshake": False}``.
    """
    minimal_handshake = (
        os.getenv("DATA_DOWNLOADER_DLL_MINIMAL_HANDSHAKE", "").strip().lower() in _TRUTHY
    )
    return {"minimal_handshake": minimal_handshake}


def get_dll(*, market_only: bool = True, **init_kwargs: Any) -> ProfitDLL:
    """Retorna a instância ``ProfitDLL`` process-global, inicializando-a 1x.

    Na 1ª chamada cria ``ProfitDLL()`` e inicializa (``initialize_market_only``
    se ``market_only`` — único modo suportado hoje), guarda e devolve. Nas
    chamadas seguintes devolve a MESMA instância sem re-inicializar nem
    finalizar — a ProfitDLL Classic não tolera init→finalize→init no mesmo
    processo (Q08-E).

    fix #21b: se uma chamada subsequente passar um modo de init DIFERENTE do
    que a instância foi criada (qualquer kwarg em ``_MODE_AFFECTING_KWARGS``,
    ex.: ``minimal_handshake``), a instância existente é devolvida no modo
    ORIGINAL e um ``warning`` ``dll.session.mode_mismatch`` é logado — NÃO
    re-inicializamos. Os call sites (``_build_real_dll`` / Test Connection)
    devem usar ``resolve_dll_init_mode()`` para concordar no modo e evitar
    isso.

    Se o init falhar, a exceção propaga e a instância NÃO é guardada — a
    próxima chamada tenta de novo (init nunca completou, então não houve
    estado sujo). Se o init de fato *crashar* o processo não há o que fazer;
    o singleton existe justamente para prevenir o 2º init, que é a falha
    real do Q08-E.

    Args:
        market_only: Se ``True`` (default), inicializa via
            ``initialize_market_only``. Reservado para um futuro modo de
            trading; hoje só ``True`` é suportado.
        **init_kwargs: Repassados a ``initialize_market_only``. Esperado:
            posicional via kwargs ``key``/``user``/``password`` OU
            ``minimal_handshake``/``register_extra_callbacks``. Quando o
            caller já passou credenciais como argumentos posicionais,
            converta-os para kwargs antes de chamar (ver
            ``_build_real_dll`` / ``_TestConnectionWorker``).

    Returns:
        Instância ``ProfitDLL`` inicializada (compartilhada por todo o
        processo).
    """
    global _DLL_INSTANCE, _ATEXIT_REGISTERED, _DLL_INIT_KWARGS

    # v1.3.0 Wave 2A: lifecycle do singleton agora emite estados via
    # ``_set_state`` para observers (UI). ``_set_state`` adquire ``_LOCK``
    # internamente — chamá-lo de dentro do ``with _LOCK:`` deadlockaria;
    # então separamos em 3 fases:
    #   1. Check reuse + grava ``needs_init`` (rapidinho, segura o lock).
    #   2. Emite ``connecting`` + roda Initialize FORA do lock (caro).
    #   3. Re-adquire o lock para gravar a instância + emitir ``connected``.
    # Para serializar 2ª chamada concorrente (race threads paralelas
    # querendo init), usamos ``_INIT_BARRIER`` (Event): a 1ª chamada o
    # *clear* antes do init e *set* ao fim; chamadas subsequentes que
    # entrarem com ``_DLL_INSTANCE is None`` aguardam no Event antes de
    # tentar de novo.
    while True:
        with _LOCK:
            if _DLL_INSTANCE is not None:
                # fix #21b: defensivo — se uma chamada subsequente pedir um modo
                # de init DIFERENTE do que a instância foi criada, NÃO
                # re-inicializamos (a DLL Classic não tolera — Q08-E), mas
                # logamos um warning claro para que o descasamento apareça no log
                # em vez de causar a falha funcional silenciosa do fix #21
                # (download status=failed trades=0 + PopulateTradeV0 AV na DLL).
                requested_mode = {
                    k: init_kwargs[k] for k in _MODE_AFFECTING_KWARGS if k in init_kwargs
                }
                active_mode = {
                    k: _DLL_INIT_KWARGS[k] for k in _MODE_AFFECTING_KWARGS if k in _DLL_INIT_KWARGS
                }
                if requested_mode != active_mode:
                    log.warning(
                        "dll.session.mode_mismatch",
                        requested=requested_mode,
                        active=active_mode,
                        note=(
                            "reusing existing DLL instance in its ORIGINAL mode; "
                            "callers must agree on init mode (see resolve_dll_init_mode)"
                        ),
                    )
                else:
                    log.debug("dll.session.reuse")
                return _DLL_INSTANCE

            # Tenta tomar o ownership do init. Se outro thread já está
            # inicializando (_INIT_IN_PROGRESS), liberamos o lock e
            # aguardamos o Event, depois retentamos do topo.
            if _INIT_IN_PROGRESS.is_set():
                in_progress_event = _INIT_DONE
            else:
                _INIT_IN_PROGRESS.set()
                _INIT_DONE.clear()
                in_progress_event = None

        if in_progress_event is not None:
            in_progress_event.wait(timeout=120)
            continue
        break

    try:
        from data_downloader.dll.wrapper import ProfitDLL

        _set_state("connecting", "")
        instance = ProfitDLL()
        try:
            # Init FORA do `_DLL_INSTANCE = instance` — se falhar, não guardamos.
            if market_only:
                instance.initialize_market_only(**init_kwargs)
            else:  # pragma: no cover - modo trading não implementado
                raise NotImplementedError("get_dll só suporta market_only=True hoje")
        except Exception:
            # init falhou — não guardamos a instance; UI deve mostrar "error".
            _set_state("error", "")
            raise

        with _LOCK:
            _DLL_INSTANCE = instance
            _DLL_INIT_KWARGS = dict(init_kwargs)
            if not _ATEXIT_REGISTERED:
                atexit.register(shutdown_dll)
                _ATEXIT_REGISTERED = True
            log.info("dll.session.initialized")

        # Tenta extrair versão; default ``"—"`` se a property ainda não estiver
        # disponível ou levantar (não-bloqueante — versão é metadata).
        version = "—"
        try:
            raw_version = getattr(instance, "dll_version", None)
            if raw_version:
                version = str(raw_version)
        except Exception:
            pass
        _set_state("connected", version)
        return instance
    finally:
        with _LOCK:
            _INIT_IN_PROGRESS.clear()
            _INIT_DONE.set()


def has_active_dll() -> bool:
    """``True`` se já existe uma instância DLL process-global ativa."""
    with _LOCK:
        return _DLL_INSTANCE is not None


def shutdown_dll() -> None:
    """Finaliza a instância DLL process-global, se houver (idempotente).

    Chamado UMA vez no encerramento do processo: via ``atexit`` (registrado
    na 1ª ``get_dll``) e explicitamente por ``MainWindow.closeEvent`` (UI) /
    fim do ``cli.py download`` (CLI). Best-effort: erros no ``finalize`` são
    logados e engolidos — não queremos quebrar o teardown.
    """
    global _DLL_INSTANCE, _DLL_INIT_KWARGS

    with _LOCK:
        instance = _DLL_INSTANCE
        _DLL_INSTANCE = None
        _DLL_INIT_KWARGS = {}

    if instance is None:
        return
    try:
        finalize_fn = getattr(instance, "finalize", None)
        if callable(finalize_fn):
            finalize_fn()
        log.info("dll.session.shutdown")
    except Exception as exc:  # pragma: no cover - defensivo no teardown
        log.warning("dll.session.shutdown_failed", error=str(exc))
    # v1.3.0 Wave 2A: emite ``idle`` para o observer chain — UI deve voltar
    # ao estado "DLL: aguardando" após shutdown (e.g. closeEvent).
    _set_state("idle", "")
