"""data_downloader.public_api — Stable public API surface (SemVer V1.0).

Owner: Aria (design — ADR-007a + ADR-011) + Dex (impl).
Story 4.3 — Public API V1.0 release.

Esta é a fronteira ESTÁVEL do data-downloader. Tudo que projetos downstream
(backtest engine, signal generator, risk monitor, notebooks Jupyter)
importam DEVE vir daqui — namespace ``data_downloader.public_api`` é o ÚNICO
caminho garantido a NÃO quebrar entre minor/patch versions.

================================================================================
Visão Geral da API
================================================================================

A API V1.0 expõe 4 funções, 4 classes e 8 exceções:

**Funções:**

- :func:`download` — download assíncrono de histórico (retorna handle).
- :func:`read` — lê trades de UM contrato (range fechado).
- :func:`read_continuous` — lê série contínua multi-contrato (rollover automático).
- :func:`vigent_contract` — resolve raiz + data → contract_code vigente.

**Classes (data + handle):**

- :class:`DownloadHandle` — handle assíncrono retornado por :func:`download`
  (cancel/result/events/peek_result/cancelled/is_cancelled).
- :class:`DownloadProgress` — evento imutável emitido pelo worker.
- :class:`DownloadResult` — resultado final imutável (job_id, partitions, status).
- :class:`DownloadStatus` — Literal type alias para os 5 status finais.

**Exceções (hierarquia ADR-011):**

- :class:`DataDownloaderError` — base de todas as exceções públicas.
- :class:`DLLInitError` — ProfitDLL não inicializou (credenciais/companions).
- :class:`InvalidContract` — símbolo não resolve em contrato vigente.
- :class:`DiskFull` — disco cheio durante write Parquet/SQLite.
- :class:`DownloadError` — erro genérico de download (inspect ``.cause``).
- :class:`IntegrityError` — schema drift / hash mismatch / dedup gap.
- :class:`OperationCancelled` — cancel cooperativo concluído (não é falha).
- :class:`ConnectionLost` — reconexão DLL ultrapassou janela (Q02-E).
- :class:`AmbiguousRolloverError` — range cruza rollover sob raiz (Story 4.26 / ADR-028).

================================================================================
Garantias Semânticas
================================================================================

Estas garantias são **contratuais** — quebrá-las exige bump major (V2.0+):

1. **Idempotência (R5)** — chamar :func:`download` para o mesmo
   ``(symbol, start, end, exchange)`` produz o mesmo resultado: trades
   duplicados são deduplicados pelo writer (chave canônica
   ``(timestamp_ns, trade_id, sequence_within_ns)``). Re-runs após crash
   são seguros.

2. **BRT naive (R7)** — TODOS os parâmetros e retornos ``datetime`` são
   "naive" (sem ``tzinfo``) e representam horário Brasil (BRT/BRST,
   UTC-3). Passar ``datetime`` aware causa strip de tz silencioso.
   Conversão BRT ↔ UTC é responsabilidade do caller.

3. **Dedup canônico (R5)** — :func:`read` e :func:`read_continuous` NUNCA
   retornam duplicatas. ``read_continuous`` aplica cut-off ``+1ns`` em
   rollover para garantir zero overlap entre contratos consecutivos.

4. **Ordem cronológica** — ``timestamp_ns`` é estritamente ascendente em
   :func:`read` e ascendente cross-contract em :func:`read_continuous`.

5. **Schema estável** — 17 campos canônicos (SCHEMA.md §1.2);
   ``read_continuous`` adiciona 2 colunas extras (``_contract_code``,
   ``_rollover_event``). ``schema_version`` exposto via metadata Parquet.

6. **Cancelamento graceful** — :meth:`DownloadHandle.cancel` NÃO mata
   thread; sinaliza Event e worker drena chunks em andamento. Trades já
   committados são preservados (catalog atomic). Status final
   ``"cancelled"``; :meth:`DownloadHandle.result` levanta
   :class:`OperationCancelled`.

7. **Sem leak de exceções internas** — código interno (em
   ``data_downloader._internal``, ``data_downloader.dll``,
   ``data_downloader.storage``, ``data_downloader.orchestrator``) lança
   ``_InternalError`` privadas; a fronteira ``public_api/`` traduz para
   :class:`DataDownloaderError` family. Caller pode pegar
   :class:`DataDownloaderError` para tratar genericamente.

================================================================================
Política SemVer Estrito (V1.x → V2.x)
================================================================================

A partir de V1.0.0, a API segue **SemVer estrito** (ADR-007a):

- **PATCH** (``1.0.0 → 1.0.1``) — bug fix sem mudança de assinatura.
- **MINOR** (``1.0.0 → 1.1.0``) — adição compatível: nova função, novo
  argumento opcional com default, novo símbolo em ``__all__``.
- **MAJOR** (``1.0.0 → 2.0.0``) — breaking change: remoção, rename,
  mudança de tipo, mudança semântica observável.

Símbolos deprecados em release N são **removidos no mais cedo em N+major+1**
(mínimo 6 meses entre anúncio e remoção). Ver
``docs/public_api/DEPRECATION_POLICY.md``.

Consumidores devem pinar:

.. code-block:: toml

    # pyproject.toml do consumer
    dependencies = ["data-downloader>=1.0,<2.0"]

E inspecionar :data:`__api_version__` em runtime para sanity checks.

================================================================================
Cobertura de SemVer (o que está / o que NÃO está)
================================================================================

**Coberto por SemVer:**

- Assinaturas (parâmetros, defaults, tipos) de tudo em :data:`__all__`.
- Comportamento documentado em docstrings.
- Hierarquia de exceções (subclasses de :class:`DataDownloaderError`).
- Schema canônico Parquet (17 campos + ``schema_version``).

**NÃO coberto por SemVer (sujeito a mudança sem bump):**

- Módulos ``_internal/``, ``dll/``, ``storage/``, ``orchestrator/``,
  ``ui/`` (privados).
- Comportamento de exceções internas (``_InternalError`` family).
- Performance / latência (governada por ``benchmarks/BASELINES.md``).
- Mensagens humanas (microcopy ID é estável; texto resolvido pode mudar
  via ``MICROCOPY_CATALOG.md`` — Uma authority).
- Conteúdo exato de logs estruturados (formato é estável; campos podem ser
  adicionados aditivamente).

================================================================================
Documentação Adicional
================================================================================

- ``docs/public_api/USAGE.md`` — exemplos copy-paste para 3 personas
  (backtest, signal generator, risk monitor).
- ``docs/public_api/DEPRECATION_POLICY.md`` — política formal de
  deprecação + decorator ``@deprecated``.
- ``docs/adr/ADR-007a-public-api-redesign.md`` — design rationale
  ``DownloadHandle``.
- ``docs/adr/ADR-011-exception-hierarchy.md`` — hierarquia de exceções.
- ``CHANGELOG.md`` — histórico de bumps.

================================================================================
Histórico de bumps
================================================================================

- ``0.1.0`` — Story 1.5b (read, read_continuous, vigent_contract).
- ``0.2.0`` — Story 1.6 (vigent_contract público + InvalidContract).
- ``0.3.0`` — Story 1.7b (download + DownloadHandle/Progress/Result) — minor aditivo.
- ``0.4.0`` — Story 2.11 (cancel cooperativo + OperationCancelled +
  ConnectionLost + DownloadHandle.cancelled/is_cancelled/peek_result) —
  minor aditivo + soft-break em :meth:`DownloadHandle.result`
  (``status='cancelled'`` agora levanta :class:`OperationCancelled`).
- ``1.0.0`` — Story 4.3 (Public API V1.0 release) — formalização
  SemVer estrito + política de deprecação + USAGE.md exemplos.
"""

from __future__ import annotations

from data_downloader.public_api.download import download
from data_downloader.public_api.exceptions import (
    AmbiguousRolloverError,
    ConnectionLost,
    DataDownloaderError,
    DiskFull,
    DLLInitError,
    DownloadError,
    IntegrityError,
    InvalidContract,
    OperationCancelled,
)
from data_downloader.public_api.handle import (
    DownloadHandle,
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
)
from data_downloader.public_api.history import (
    read,
    read_continuous,
    vigent_contract,
)

__api_version__ = "1.0.0"
"""Version of the stable public API (SemVer-tracked).

Independent of ``data_downloader.__version__`` (which tracks the package).
Bump rules in module docstring above. Consumers pin via
``data-downloader>=1.0,<2.0`` and may inspect this in runtime.
"""

__all__ = [
    "AmbiguousRolloverError",
    "ConnectionLost",
    "DLLInitError",
    "DataDownloaderError",
    "DiskFull",
    "DownloadError",
    "DownloadHandle",
    "DownloadProgress",
    "DownloadResult",
    "DownloadStatus",
    "IntegrityError",
    "InvalidContract",
    "OperationCancelled",
    "__api_version__",
    "download",
    "read",
    "read_continuous",
    "vigent_contract",
]
