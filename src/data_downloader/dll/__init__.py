"""data_downloader.dll — Wrapper ctypes da ProfitDLL.

Owner: Dex (impl) | Audit: Nelo (DLL specialist).

Este pacote isola TODA interação com ``ProfitDLL.dll`` (Win64 stdcall):

- ``wrapper.py``    — loader ctypes, init/finalize (Story 1.2+).
- ``callbacks.py``  — definições WINFUNCTYPE + ``_cb_refs`` (anti-GC).
- ``types.py``      — espelho tipado de ``profitTypes.py`` (Nelogica).
- ``errors.py``     — tradução ``NL_*`` -> ``Exception`` (ADR-011).

Lei do Nelo (manual ProfitDLL §4): callbacks fazem APENAS ``queue.put_nowait()``.
Processamento real ocorre em outra thread (ingestor).

Stories que tocam este pacote DEVEM consultar Nelo via ``*consult nelo {pergunta}``.
"""

from __future__ import annotations

__all__ = ["get_dll_version"]


def get_dll_version() -> str:
    """Retorna a versão da ProfitDLL carregada.

    Stub para Story 1.1 — a implementação real (chamada a ``GetDLLVersion`` via
    ctypes) entra na Story 1.2, junto do bootstrap completo do wrapper. Retorna
    a sentinela ``"0.0.0+stub"`` para que (a) o schema Parquet de Sol
    (SCHEMA.md §1, campo ``dll_version`` NOT NULL) tenha um valor estável em
    builds onde a DLL ainda não está disponível e (b) o metadata Parquet (§4)
    seja gravável sem falha em testes.

    TODO(Story 1.2): substituir stub pela chamada real
    ``profit_dll.GetDLLVersion`` (signature em ``profit_dll.py`` Nelogica).

    Returns:
        Versão semver da DLL ou ``"0.0.0+stub"`` se a DLL não estiver carregada.
    """
    return "0.0.0+stub"
