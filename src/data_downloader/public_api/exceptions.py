"""data_downloader.public_api.exceptions — Hierarquia pública de exceções.

Owner: Aria (design) + Dex (impl). Ref: ADR-011 (exception hierarchy).

Esta hierarquia é a fronteira ESTÁVEL (SemVer-tracked) entre o backend e
qualquer caller (UI, CLI, notebooks). Internals (em ``_internal/`` futuro)
levantam ``_InternalError``-derived; ``public_api/`` traduz na fronteira.

Regras (ADR-011):
    1. Internals NUNCA importam de ``public_api/``.
    2. ``public_api/`` captura toda subclasse de ``_InternalError`` e traduz.
    3. ``raise X from y`` sempre — preserva chain para debug.
    4. ``.cause`` é detalhe interno — UI mostra mensagem amigável.

Story 1.2: define ``DataDownloaderError`` + ``DLLInitError`` (consumido pelo
wrapper DLL). Demais subclasses deixadas como placeholders aditivos para
stories futuras (1.4 ``DiskFull``/``IntegrityError``, 1.6 ``InvalidContract``,
1.7 ``DownloadError``).
"""

from __future__ import annotations

__all__ = [
    "DLLInitError",
    "DataDownloaderError",
    "DiskFull",
    "DownloadError",
    "IntegrityError",
    "InvalidContract",
]


class DataDownloaderError(Exception):
    """Base de todas as exceções públicas do data-downloader.

    Caller pode pegar ``DataDownloaderError`` para tratar genericamente, ou
    subclasses específicas para tratamento granular.

    Args:
        message: Mensagem principal (humana, mostrável em UI).
        cause: Exceção interna preservada para debug forense (opcional).
        details: Dict estruturado (chunk_id, file_path, etc.) para log/UI.

    Attributes:
        cause: Exceção interna ou ``None``. UI **não** deve renderizar.
        details: Info estruturada para observabilidade. UI pode renderizar
            campos específicos via Uma's ``MICROCOPY_CATALOG.md``.
    """

    def __init__(
        self,
        message: str,
        *,
        cause: Exception | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.details: dict[str, object] = details or {}


class DLLInitError(DataDownloaderError):
    """ProfitDLL não pôde ser inicializada.

    Causas comuns (consultar ``data_downloader.dll.errors`` para mapa NL_*):

    - **Credenciais inválidas** — ``NL_NO_LOGIN``, ``NL_NO_LICENSE``.
    - **Companions ausentes** — ``COMPANIONS_MISSING`` (Story 1.2 AC12);
      verificado por ``scripts/verify-dll-companions.py`` antes do
      ``WinDLL()``.
    - **Args inválidos** — ``NL_INVALID_ARGS`` (chave/user/password vazios).
    - **Plataforma não suportada** — ``UNSUPPORTED_PLATFORM`` (DLL é
      Windows-only; raised em Linux/Mac para permitir testes mockados).

    Attributes:
        code: Código numérico ``NL_*`` da DLL ou ``-1`` para sentinelas
            internas (``COMPANIONS_MISSING``, ``UNSUPPORTED_PLATFORM``).
        name: Nome simbólico (ex. ``"NL_INVALID_ARGS"``).
        message: Mensagem humanizada (refs Uma ``MICROCOPY_CATALOG.md``).

    Microcopy UI (ADR-011 §"Mapeamento erro → UI"):
        Título: "Não foi possível conectar"
        Detalhe: "Verifique as credenciais e a conexão."
        Ação: Botão "Configurações"
    """

    def __init__(
        self,
        code: int,
        name: str,
        message: str,
        *,
        cause: Exception | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, cause=cause, details=details)
        self.code = code
        self.name = name
        # Mensagem da Exception base é o ``message`` humanizado; ``code/name``
        # ficam acessíveis via attrs e em ``__str__`` (debug-friendly).

    def __str__(self) -> str:
        # Formato canônico: "DLL init failed: NL_INVALID_ARGS (code=-2147483393): <msg>"
        # Usado em logs estruturados (structlog dict_tracebacks) e em UI fallback.
        return f"DLL init failed: {self.name} (code={self.code}): {self.args[0]}"


class InvalidContract(DataDownloaderError):  # noqa: N818  ADR-011 canonical name
    """Símbolo não resolve para contrato vigente na data informada.

    Ex.: ``download('WDO', 2026-03-15)`` — ``WDO`` é raiz, não contrato.
    Sugestão de correção: usar ``vigent_contract('WDO', date)`` (Epic 1.6).

    Story 1.2: placeholder (resolução em Story 1.6).
    """


class DiskFull(DataDownloaderError):  # noqa: N818  ADR-011 canonical name
    """Disco cheio durante escrita Parquet ou SQLite.

    Story 1.2: placeholder (raised por storage layer em Story 1.4).
    """


class DownloadError(DataDownloaderError):
    """Erro genérico durante download. Inspecionar ``.cause`` para detalhe.

    Story 1.2: placeholder (raised por orchestrator em Story 1.7).
    """


class IntegrityError(DataDownloaderError):
    """Dado inconsistente detectado (schema drift, dedup gap, hash mismatch).

    Crítica: caller deve parar e investigar; não corrigir silenciosamente.

    Story 1.2: placeholder (raised por storage/validator em Story 2.1).
    """
