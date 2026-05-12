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
import threading
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL

__all__ = ["get_dll", "has_active_dll", "shutdown_dll"]

log: structlog.stdlib.BoundLogger = structlog.get_logger("data_downloader.dll.session")

# Estado process-global. Protegido por ``_LOCK`` — ``get_dll`` pode ser
# chamado de QThread workers (Test Connection) e da download worker thread.
_LOCK = threading.Lock()
_DLL_INSTANCE: ProfitDLL | None = None
_ATEXIT_REGISTERED = False


def get_dll(*, market_only: bool = True, **init_kwargs: Any) -> ProfitDLL:
    """Retorna a instância ``ProfitDLL`` process-global, inicializando-a 1x.

    Na 1ª chamada cria ``ProfitDLL()`` e inicializa (``initialize_market_only``
    se ``market_only`` — único modo suportado hoje), guarda e devolve. Nas
    chamadas seguintes devolve a MESMA instância sem re-inicializar nem
    finalizar — a ProfitDLL Classic não tolera init→finalize→init no mesmo
    processo (Q08-E).

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
    global _DLL_INSTANCE, _ATEXIT_REGISTERED

    with _LOCK:
        if _DLL_INSTANCE is not None:
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
    global _DLL_INSTANCE

    with _LOCK:
        instance = _DLL_INSTANCE
        _DLL_INSTANCE = None

    if instance is None:
        return
    try:
        finalize_fn = getattr(instance, "finalize", None)
        if callable(finalize_fn):
            finalize_fn()
        log.info("dll.session.shutdown")
    except Exception as exc:  # pragma: no cover - defensivo no teardown
        log.warning("dll.session.shutdown_failed", error=str(exc))
