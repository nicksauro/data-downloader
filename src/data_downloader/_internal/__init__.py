"""data_downloader._internal — Internal/private surface (NOT public API).

Owner: Aria (fronteira) + Dex (impl). Story 2.11 — ADR-011.

Tudo neste pacote tem prefixo ``_`` ou começa com ``_`` no nome do
sub-módulo: convenção FORTE indicando "não importável por consumidores
externos". A regra de tradução (ADR-011 §"Política de propagação") é:

1. Internals podem lançar livremente :class:`_InternalError` (ou
   subclasses) para sinalizar erros de domínio interno.
2. ``public_api/`` é a ÚNICA fronteira que captura esses erros e traduz
   para a hierarquia pública (``DataDownloaderError`` family) preservando
   ``__cause__`` chain via ``raise ... from e``.
3. Property test ``test_no_internal_leak.py`` (Hypothesis) garante a
   invariante: nenhuma função em ``public_api/`` propaga ``_InternalError``
   para fora.

Ver :mod:`data_downloader._internal.exceptions` e
:mod:`data_downloader._internal.exception_adapter`.
"""

from __future__ import annotations

__all__: list[str] = []
