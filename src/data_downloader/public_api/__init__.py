"""data_downloader.public_api — Superfície pública estável (SemVer).

Owner: Aria (design) + Dex (impl).

Tudo que projetos downstream importam DEVE vir daqui. Mudanças de assinatura
são governadas por SemVer (ADR-007a):

- bump patch  — bug fix sem mudança de assinatura
- bump minor  — adição compatível (novo arg opcional, novo símbolo)
- bump major  — remoção / rename / mudança de tipo / mudança semântica

``__api_version__`` é a fonte de verdade da versão da API pública (independente
de ``data_downloader.__version__`` que rastreia o pacote inteiro).

Módulos previstos:

- ``download.py`` — ``download(symbol, start, end) -> JobResult``
- ``history.py``  — ``read(symbol, start, end) -> DataFrame``
"""

from __future__ import annotations

from data_downloader.public_api.exceptions import (
    DataDownloaderError,
    DiskFull,
    DLLInitError,
    DownloadError,
    IntegrityError,
    InvalidContract,
)
from data_downloader.public_api.history import (
    read,
    read_continuous,
    vigent_contract,
)

__api_version__ = "0.2.0"

__all__ = [
    "DLLInitError",
    "DataDownloaderError",
    "DiskFull",
    "DownloadError",
    "IntegrityError",
    "InvalidContract",
    "__api_version__",
    "read",
    "read_continuous",
    "vigent_contract",
]
