"""data_downloader.public_api — Superfície pública estável (SemVer).

Owner: Aria (design) + Dex (impl).

Tudo que projetos downstream importam DEVE vir daqui. Mudanças de assinatura
são governadas por SemVer (ADR-007a):

- bump patch  — bug fix sem mudança de assinatura
- bump minor  — adição compatível (novo arg opcional, novo símbolo)
- bump major  — remoção / rename / mudança de tipo / mudança semântica

``__api_version__`` é a fonte de verdade da versão da API pública (independente
de ``data_downloader.__version__`` que rastreia o pacote inteiro).

Módulos:

- ``download.py`` — :func:`download` (Story 1.7b)
- ``handle.py``   — :class:`DownloadHandle`, :class:`DownloadProgress`,
                    :class:`DownloadResult` (Story 1.7b — ADR-007a)
- ``history.py``  — :func:`read`, :func:`read_continuous`, :func:`vigent_contract`
                    (Story 1.5b)
- ``exceptions.py`` — Hierarquia pública de exceções (ADR-011)

Histórico de bumps:

- ``0.1.0`` — Story 1.5b (read, read_continuous, vigent_contract)
- ``0.2.0`` — Story 1.6 (vigent_contract público + InvalidContract)
- ``0.3.0`` — Story 1.7b (download + DownloadHandle/Progress/Result) — minor aditivo
"""

from __future__ import annotations

from data_downloader.public_api.download import download
from data_downloader.public_api.exceptions import (
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

__api_version__ = "0.3.0"

__all__ = [
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
