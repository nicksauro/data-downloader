"""data_downloader._internal.gc_boot — Boot-only ``gc.freeze`` helper.

Owner: Pyro (perf) | Story 4.31 AC13.

``gc.freeze()`` move todos os objetos vivos no momento da chamada para a
geração "permanente" do garbage collector — o GC nunca mais os varre.
É uma defesa custo-zero contra pausas de GC em processos longos
(downloads de horas, UI com múltiplos jobs num mesmo .exe).

Antes desta story, :meth:`Orchestrator.run` chamava ``gc.freeze`` a cada
job. Em processos UI longos (vários downloads sem reiniciar o app), o
heap "permanente" crescia monotonicamente com objetos efêmeros sendo
indevidamente promovidos a cada freeze — efeito oposto ao desejado.

Esta module-level guard garante que ``gc.freeze`` seja chamada **1x por
processo**, idealmente cedo no boot (após imports principais, antes de
iniciar trabalho). Re-chamadas são silenciosamente no-op.

Padrão de uso:

.. code-block:: python

    # cli.py / ui/app.py — early in process boot
    from data_downloader._internal.gc_boot import freeze_once
    freeze_once()
"""

from __future__ import annotations

import contextlib
import gc

__all__ = ["freeze_once"]


# Flag module-level que garante idempotência por processo. Como o módulo é
# carregado uma única vez (sys.modules cache), o estado é seguro mesmo em
# multi-threading dentro do mesmo processo.
_frozen = False


def freeze_once() -> bool:
    """Executa ``gc.freeze()`` uma única vez por processo.

    Returns:
        ``True`` se executou ``gc.freeze()`` neste call, ``False`` se já
        havia sido executado anteriormente (idempotente).
    """
    global _frozen
    if _frozen:
        return False
    # Best-effort: gc.freeze pode levantar em ambientes exóticos (Jython,
    # embed). Nunca queremos crashar o boot por causa de uma otimização.
    with contextlib.suppress(Exception):
        gc.freeze()
    _frozen = True
    return True
