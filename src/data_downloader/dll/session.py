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
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL

__all__ = ["get_dll", "has_active_dll", "resolve_dll_init_mode", "shutdown_dll"]

log: structlog.stdlib.BoundLogger = structlog.get_logger("data_downloader.dll.session")

# Estado process-global. Protegido por ``_LOCK`` — ``get_dll`` pode ser
# chamado de QThread workers (Test Connection) e da download worker thread.
_LOCK = threading.Lock()
_DLL_INSTANCE: ProfitDLL | None = None
_ATEXIT_REGISTERED = False
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

    with _LOCK:
        if _DLL_INSTANCE is not None:
            # fix #21b: defensivo — se uma chamada subsequente pedir um modo
            # de init DIFERENTE do que a instância foi criada, NÃO
            # re-inicializamos (a DLL Classic não tolera — Q08-E), mas
            # logamos um warning claro para que o descasamento apareça no log
            # em vez de causar a falha funcional silenciosa do fix #21
            # (download status=failed trades=0 + PopulateTradeV0 AV na DLL).
            requested_mode = {k: init_kwargs[k] for k in _MODE_AFFECTING_KWARGS if k in init_kwargs}
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

        from data_downloader.dll.wrapper import ProfitDLL

        instance = ProfitDLL()
        # Init FORA do `_DLL_INSTANCE = instance` — se falhar, não guardamos.
        if market_only:
            instance.initialize_market_only(**init_kwargs)
        else:  # pragma: no cover - modo trading não implementado
            raise NotImplementedError("get_dll só suporta market_only=True hoje")

        _DLL_INSTANCE = instance
        _DLL_INIT_KWARGS = dict(init_kwargs)
        if not _ATEXIT_REGISTERED:
            atexit.register(shutdown_dll)
            _ATEXIT_REGISTERED = True
        log.info("dll.session.initialized")
        return instance


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
