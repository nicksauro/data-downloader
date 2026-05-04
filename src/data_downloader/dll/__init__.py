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

__all__ = ["ProfitDLL", "get_dll_version"]


def get_dll_version() -> str:
    """Retorna a versão da ProfitDLL carregada.

    Stub para Story 1.1 — em Story 1.2, a chamada real está em
    ``ProfitDLL.dll_version`` (property cacheada após init). Esta função top-level
    permanece por compat: ``data_downloader.dll.get_dll_version()`` continua
    válido para módulos que precisam apenas de uma sentinela quando a DLL não
    foi inicializada (ex. metadata Parquet em testes sem DLL real).

    Para a versão real, use:

        with ProfitDLL() as dll:
            dll.initialize_market_only(...)
            version = dll.dll_version

    Returns:
        Sentinela ``"0.0.0+stub"`` (preservada para compat com Story 1.1).
        Versão real via ``ProfitDLL.dll_version`` property.
    """
    return "0.0.0+stub"


# Re-export do wrapper para ergonomia: ``from data_downloader.dll import ProfitDLL``.
# Lazy via __getattr__ para evitar custo de importar ctypes/structlog quando
# consumer só quer ``get_dll_version``.
def __getattr__(name: str) -> object:
    if name == "ProfitDLL":
        from data_downloader.dll.wrapper import ProfitDLL

        return ProfitDLL
    raise AttributeError(f"module 'data_downloader.dll' has no attribute {name!r}")
