"""Structural conformance tests for the 5 Protocols (Story 4.28 AC9 / ADR-030).

Estes testes garantem que as implementações concretas (``Catalog``,
``ParquetWriter``, ``ProfitDLL``) conformam aos Protocols definidos em
``data_downloader.contracts._protocols`` **sem herança forçada**
(structural subtyping — ADR-030 §2.2 + INV-PROTO-1).

Suite serve dois propósitos:

1. **Smoke test (AC9):** assert ``isinstance(concrete, Protocol)`` retorna
   ``True`` para cada par implementação-Protocol. Falha aqui indica que
   a impl mudou a forma e divergiu do Protocol — disparar revisão (Aria
   + Sol).
2. **Audit grep (AC11):** combinado com ``grep "class .*\\((Writer|Catalog|
   DLLClient)Protocol)"`` em ``src/``, garante INV-PROTO-1 (impls
   concretas NÃO herdam dos Protocols).

Plataforma:

- ``Catalog`` / ``ParquetWriter`` rodam em qualquer SO (puro Python).
- ``ProfitDLL`` é Win64-only — pulado em Linux/macOS via
  ``pytest.mark.skipif``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data_downloader.contracts import (
    CatalogProtocol,
    DLLClientProtocol,
    DownloadHandle,
    ProgressEmitter,
    WriterProtocol,
)


def test_catalog_conforms_to_catalog_protocol(tmp_path: Path) -> None:
    """``Catalog`` (impl concreta) satisfaz ``CatalogProtocol`` structurally.

    Importante: o teste NÃO modifica ``Catalog`` — usa ``isinstance`` com
    Protocol ``runtime_checkable``. Se a conformidade quebrar, é sinal de
    que a impl deve ser atualizada OU o Protocol revisado em ADR amendment.
    """
    from data_downloader.storage.catalog import Catalog

    catalog = Catalog(db_path=tmp_path / "catalog.db")
    try:
        assert isinstance(catalog, CatalogProtocol), (
            "Catalog não conforma com CatalogProtocol structurally — "
            "verifique se métodos register_partition / completed_days / "
            "maybe_compact_month / close ainda existem."
        )
    finally:
        catalog.close()


def test_parquet_writer_conforms_to_writer_protocol(tmp_path: Path) -> None:
    """``ParquetWriter`` (impl concreta) satisfaz ``WriterProtocol`` structurally."""
    from data_downloader.storage.parquet_writer import ParquetWriter

    writer = ParquetWriter(data_dir=tmp_path)
    assert isinstance(writer, WriterProtocol), (
        "ParquetWriter não conforma com WriterProtocol structurally — "
        "verifique se o método ``write`` ainda existe."
    )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="ProfitDLL é Win64-only — ADR-014; skip em non-Windows.",
)
def test_profitdll_conforms_to_dllclient_protocol() -> None:
    """``ProfitDLL`` (impl concreta) satisfaz ``DLLClientProtocol`` structurally.

    Win64-only. Usa a CLASSE (não instância) para conformidade estrutural
    sem precisar carregar a DLL real — Protocol ``runtime_checkable`` checa
    presença dos métodos via ``hasattr`` em ``__dict__``/MRO.

    A instanciação real exigiria companions presentes e credenciais; aqui
    só validamos a forma da API. Os métodos existem como ``def`` na classe
    — suficiente para isinstance check de Protocol.
    """
    from data_downloader.dll.wrapper import ProfitDLL

    # Conformidade da CLASSE (não instância) é o que queremos verificar:
    # garantir que ProfitDLL expõe a superfície completa do Protocol.
    # ``isinstance`` em ``runtime_checkable`` Protocol verifica métodos
    # acessíveis via descriptor — funciona em INSTÂNCIA, não classe.
    # Solução: criar instância "leve" via __new__ (skipping __init__ que
    # carrega DLL) e checar isinstance.
    obj = ProfitDLL.__new__(ProfitDLL)
    assert isinstance(obj, DLLClientProtocol), (
        "ProfitDLL não conforma com DLLClientProtocol structurally — "
        "verifique métodos initialize_market_only / wait_market_connected / "
        "get_history_trades / subscribe_ticker / unsubscribe_ticker / "
        "finalize."
    )


def test_download_handle_concrete_conforms_to_download_handle_protocol() -> None:
    """A classe concreta ``DownloadHandle`` (public_api) conforma com o Protocol.

    Importante para ADR-030 §8 Q2 (re-export decision): Protocol e classe
    concreta TÊM o mesmo nome ``DownloadHandle`` mas vivem em módulos
    diferentes (``contracts._protocols`` vs ``public_api.handle``).
    Conformidade structural é validada via método ``__new__`` (skip
    ``__init__`` que tenta iniciar worker thread).
    """
    from data_downloader.public_api.handle import (
        DownloadHandle as ConcreteDownloadHandle,
    )

    obj = ConcreteDownloadHandle.__new__(ConcreteDownloadHandle)
    obj.job_id = ""  # type: ignore[misc]
    assert isinstance(obj, DownloadHandle), (
        "public_api.DownloadHandle não conforma com contracts.DownloadHandle "
        "Protocol — verifique cancel / result / events / job_id."
    )


def test_progress_emitter_duck_typed_fake_conforms() -> None:
    """Mock duck-typed satisfaz ``ProgressEmitter`` — caso de uso para tests."""

    class _FakeProgressEmitter:
        def emit(self, event: object) -> None:
            return None

    fake = _FakeProgressEmitter()
    assert isinstance(fake, ProgressEmitter), (
        "Fake duck-typed deveria conformar com ProgressEmitter — issue na declaração do Protocol."
    )


def test_protocols_runtime_checkable_decorator_present() -> None:
    """Garante que TODOS os 5 Protocols têm ``@runtime_checkable``.

    Sem ``runtime_checkable``, ``isinstance(obj, Protocol)`` levanta
    ``TypeError`` em runtime — quebra ADR-030 §2.1 convention.
    Detectamos via ``_is_runtime_protocol`` (typing internal) ou via
    smoke ``isinstance``.
    """
    from typing import _ProtocolMeta  # type: ignore[attr-defined]

    protocols = [
        CatalogProtocol,
        DLLClientProtocol,
        DownloadHandle,
        ProgressEmitter,
        WriterProtocol,
    ]
    for proto in protocols:
        assert isinstance(proto, _ProtocolMeta), (
            f"{proto.__name__} não é Protocol metaclass; verifique declaração."
        )
        # Cada um DEVE permitir ``isinstance`` checks sem TypeError.
        # Probe via objeto trivial — esperamos False sem raise.
        assert not isinstance(object(), proto), (
            f"object() não deveria conformar com {proto.__name__}; Protocol está muito permissivo."
        )


def test_no_concrete_inherits_from_protocol() -> None:
    """INV-PROTO-1 — implementações concretas NÃO herdam dos Protocols.

    Conformidade é structural (duck typing). Herança forçaria MRO change
    e quebraria suite legada. Audit defensivo: checa que as 3 classes
    concretas críticas (``Catalog``, ``ParquetWriter``, ``ProfitDLL``)
    NÃO listam nenhum Protocol em ``__mro__``.
    """
    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.storage.catalog import Catalog
    from data_downloader.storage.parquet_writer import ParquetWriter

    protocols = {
        CatalogProtocol,
        DLLClientProtocol,
        DownloadHandle,
        ProgressEmitter,
        WriterProtocol,
    }
    for cls in (Catalog, ParquetWriter, ProfitDLL):
        mro_set = set(cls.__mro__)
        intersection = mro_set & protocols
        assert not intersection, (
            f"INV-PROTO-1 violada: {cls.__name__} herda de Protocol(s) "
            f"{intersection}. Conformidade DEVE ser structural; remova herança."
        )
