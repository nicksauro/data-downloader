"""data_downloader.public_api._deprecation — ``@deprecated`` decorator.

Owner: Aria (design — política SemVer estrito) + Dex (impl).
Story 4.3 — AC4 (deprecation policy + decorator).

Decorator infraestrutural para marcar funções/classes como deprecated em
release MINOR (com aviso) e remoção planejada em release MAJOR seguinte.
NÃO exportado em :mod:`data_downloader.public_api` (prefixo ``_`` no
módulo) — uso interno apenas, aplicado pelo squad ao deprecar símbolos.

Política completa em ``docs/public_api/DEPRECATION_POLICY.md``.

Exemplo de uso (NÃO aplicar a nenhum símbolo real ainda — V1.0 é baseline):

.. code-block:: python

    from data_downloader.public_api._deprecation import deprecated

    @deprecated(
        since="1.2.0",
        removed_in="2.0.0",
        replacement="data_downloader.public_api.download_batch",
    )
    def download_many(symbols, start, end):
        '''Legacy batch download — use download_batch instead.'''
        ...

Ao chamar ``download_many(...)`` pela primeira vez, o caller recebe::

    DeprecationWarning: download_many is deprecated since v1.2.0 and will
    be removed in v2.0.0. Use data_downloader.public_api.download_batch
    instead.

E a docstring runtime ganha prefix ``[DEPRECATED since v1.2.0]``.
"""

from __future__ import annotations

import functools
import warnings
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["deprecated"]


F = TypeVar("F", bound="Callable[..., object]")


def deprecated(
    *,
    since: str,
    removed_in: str,
    replacement: str | None = None,
) -> Callable[[F], F]:
    """Marca função/classe como deprecated; emite :class:`DeprecationWarning`.

    Decorator factory — chama com kwargs e aplica ao callable. Comportamento:

    1. Na **primeira** chamada do callable, emite
       :class:`DeprecationWarning` com ``stacklevel=2`` (aponta para o
       caller, não para o decorator).
    2. Sub-chamadas pelo mesmo callsite ficam silenciadas pelo Python
       default warning filter (``"default"`` action).
    3. Modifica a docstring runtime: prefixa com
       ``"[DEPRECATED since v{since}, removed in v{removed_in}] ..."``.
       Permite que ``help(func)`` e Sphinx renderizem o aviso.

    Args:
        since: Versão MINOR onde a deprecação foi anunciada (e.g. ``"1.2.0"``).
            Deve ser >= versão atual.
        removed_in: Versão MAJOR onde o símbolo será removido (e.g. ``"2.0.0"``).
            Deve ser >= 2 versões depois de ``since`` (mínimo 6 meses real time).
        replacement: Opcional — string descrevendo o substituto. Pode ser
            um path qualificado (``"data_downloader.public_api.foo"``) ou
            uma frase humana (``"use foo() with bar=True"``).

    Returns:
        Decorator que envolve o callable. Preserva ``__name__``,
        ``__doc__``, ``__qualname__``, ``__module__``, ``__wrapped__`` via
        :func:`functools.wraps`.

    Examples:
        Deprecar função::

            @deprecated(since="1.1.0", removed_in="2.0.0", replacement="new_func")
            def old_func(x): ...

        Deprecar classe (aplica ao ``__init__``)::

            class OldClass:
                @deprecated(since="1.1.0", removed_in="2.0.0")
                def __init__(self, x): ...

    Notes:
        - **Não** silencia o warning entre processos: cada interpreter
          fresh emite na primeira call. Production logging é responsabilidade
          do caller (capturar via ``warnings.catch_warnings`` ou logger).
        - Compatível com :func:`functools.wraps` chains — pode empilhar
          com outros decorators.
        - Aria valida deprecações via ``*review-design``: cada novo
          ``@deprecated`` requer entrada no CHANGELOG.md "Deprecated"
          section + linha em DEPRECATION_POLICY.md tracker.
    """
    msg_parts = [
        f"is deprecated since v{since}",
        f"and will be removed in v{removed_in}",
    ]
    if replacement:
        msg_parts.append(f"Use {replacement} instead.")
    base_msg = " ".join(msg_parts) + ("." if not replacement else "")

    docstring_prefix = f"[DEPRECATED since v{since}, removed in v{removed_in}] "

    def decorator(obj: F) -> F:
        @functools.wraps(obj)
        def wrapper(*args: object, **kwargs: object) -> object:
            warnings.warn(
                f"{obj.__name__} {base_msg}",
                category=DeprecationWarning,
                stacklevel=2,
            )
            return obj(*args, **kwargs)

        # Mutate docstring runtime para sinalizar visualmente em help().
        original_doc = obj.__doc__ or ""
        wrapper.__doc__ = docstring_prefix + original_doc
        # Marker introspectivo para tools (e.g. test que verifica
        # CHANGELOG.md tem entrada para todo símbolo @deprecated).
        wrapper.__deprecated__ = {  # type: ignore[attr-defined]
            "since": since,
            "removed_in": removed_in,
            "replacement": replacement,
        }
        return cast("F", wrapper)

    return decorator
