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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "ConnectionLost",
    "DLLInitError",
    "DataDownloaderError",
    "DiskFull",
    "DownloadError",
    "IntegrityError",
    "InvalidContract",
    "MaxHIDError",
    "OperationCancelled",
]


# Mapa público → microcopy ID (Uma — MICROCOPY_CATALOG.md).
# Usado por ``DataDownloaderError.humanized_message`` para obter o ID
# canônico de microcopy associado ao tipo. Não embute o texto pt-BR aqui
# (Uma authority — single source = MICROCOPY_CATALOG.md / microcopy_loader).
# Subclasses sem entrada no mapa caem em ``ERR_DLL_GENERIC`` via property.
_PUBLIC_ERROR_MICROCOPY_ID: dict[str, str] = {
    "DLLInitError": "ERR_DLL_NOT_INITIALIZED",
    "InvalidContract": "ERR_INVALID_CONTRACT",
    "DiskFull": "ERR_DISK_FULL",
    "DownloadError": "ERR_CHUNK_FAILED",
    "IntegrityError": "ERR_CATALOG_DRIFT",
    "OperationCancelled": "SUC_CANCEL_DONE",
    "ConnectionLost": "ERR_CONNECTION_LOST",
    # Story 4.29 — MaxHID detection (DLL nativa reporta ActivationResult=
    # MaxHID quando licença Nelogica está em uso em outro processo). Microcopy
    # ID dedicado prescreve remedies via portal Nelogica + reinício.
    "MaxHIDError": "ERR_DLL_MAX_HID",
    "DataDownloaderError": "ERR_DLL_GENERIC",
}


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

    @property
    def humanized_message(self) -> str:
        """Microcopy ID canônico para esta exceção (Story 2.11 — Uma).

        Retorna o ID (string) que o caller (CLI / Qt UI) usa para
        renderizar a mensagem humana via
        :func:`data_downloader.ui.microcopy_loader.format_msg` ou via
        :func:`humanize_nl_error`. NÃO retorna o texto em si — Uma é
        a única autoridade sobre as strings (R17). UI faz o lookup.

        Subclasses não-mapeadas em ``_PUBLIC_ERROR_MICROCOPY_ID`` caem
        em ``ERR_DLL_GENERIC`` (fallback documentado em
        MICROCOPY_CATALOG.md §5).

        Returns:
            ID UPPER_SNAKE_CASE compatível com microcopy_loader.MSG.
        """
        return _PUBLIC_ERROR_MICROCOPY_ID.get(type(self).__name__, "ERR_DLL_GENERIC")


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

    Ex.: ``download('WDO', 2026-03-15)`` quando o catálogo de contratos
    não tem nenhuma linha cobrindo ``2026-03-15`` para ``WDO``.

    Sugestão de correção: rodar ``data-downloader contracts add`` para
    inserir o contrato vigente, ou ``data-downloader contracts list``
    para ver o que está cadastrado.

    Story 1.6 — primeira implementação efetiva (raised pelo resolver
    ``orchestrator.contracts.vigent_contract``).

    Args:
        symbol_root: Raiz do contrato pedido (ex.: ``"WDO"``).
        on_date: Data sobre a qual a vigência foi consultada.
        exchange: Bolsa pedida (``"F"`` ou ``"B"``). Default ``"F"``.
        message: Mensagem opcional; se ausente, é construída a partir dos
            campos acima.

    Attributes:
        symbol_root: Raiz consultada.
        on_date: Data consultada (ISO em ``details``).
        exchange: Bolsa consultada (em ``details``).
    """

    def __init__(
        self,
        symbol_root: str,
        on_date: object,
        *,
        exchange: str = "F",
        message: str | None = None,
        cause: Exception | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        msg = message or (
            f"No vigent contract for symbol_root={symbol_root!r} "
            f"on_date={on_date!s} (exchange={exchange!r}). "
            "Use 'data-downloader contracts list' to inspect catalog."
        )
        merged_details: dict[str, object] = {
            "symbol_root": symbol_root,
            "on_date": str(on_date),
            "exchange": exchange,
        }
        if details:
            merged_details.update(details)
        super().__init__(msg, cause=cause, details=merged_details)
        self.symbol_root = symbol_root
        self.on_date = on_date
        self.exchange = exchange


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


# ---------------------------------------------------------------------
# Story 2.11 — adições H10 (cancel) e Q02-E (ConnectionLost).
# ---------------------------------------------------------------------


class OperationCancelled(DataDownloaderError):  # noqa: N818  ADR-011 canonical name
    """Operação foi cancelada cooperativamente (H10 — :meth:`DownloadHandle.cancel`).

    Não é erro de execução — é sinal de que o usuário pediu cancel.
    Caller que estava em :meth:`DownloadHandle.result` recebe esta exceção
    quando o worker cooperativo termina o cancelamento gracioso.

    Atributos esperados em ``details``:

    - ``trades_preserved``: ``int`` — trades já committados (parcial salvo).
    - ``chunks_completed``: ``int`` — chunks que terminaram antes do cancel.

    Microcopy UI (MICROCOPY_CATALOG.md §16+):
        - Título: ``error.cancelled.title`` ("Download cancelado").
        - Detalhe: ``error.cancelled.description`` (com {trades_preserved}).

    Story 2.11 — primeira implementação (raised por
    :meth:`DownloadHandle.cancel`/``result`` quando cancelamento OK).
    """


class ConnectionLost(DataDownloaderError):  # noqa: N818  ADR-011 canonical name
    """Conexão com a corretora caiu de forma não-recuperável.

    Diferente do quirk Q11-99 (reconexão normal até 30 minutos — não
    raised, apenas warning ``WAR_99_RECONNECT``). Esta exceção sinaliza
    que o reconnect ULTRAPASSOU a janela esperada (Q02-E hard timeout)
    e o caller precisa decidir (retry manual? doctor?).

    Microcopy UI:
        - Título: ``error.connection_lost.title``.
        - Detalhe: ``error.connection_lost.description`` (referência Q02-E).

    Story 2.11 — primeira implementação (traduzido de
    :class:`_DLLDisconnected` interno via adapter).
    """


# ---------------------------------------------------------------------
# Story 4.29 — MaxHID detection (DLL nativa reporta licença em uso).
# ---------------------------------------------------------------------


class MaxHIDError(DLLInitError):
    """Servidor Nelogica recusou login com ``ActivationResult=MaxHID``.

    Story 4.29 — UX fix do bug Pichau 2026-05-17. A DLL nativa Nelogica
    grava ``TInfoClientProcessor.ProcessLoginResult`` no LogDesktop
    quando o servidor de autenticação recusa o login porque **todos
    os HIDs (computadores/sessões) da licença já estão em uso**. A DLL
    marca ``Profit Dll Valid=False`` e NUNCA emite o estado
    ``(MARKET_DATA, MARKET_CONNECTED=4)`` esperado pelo Python — sem
    detecção proativa, :meth:`ProfitDLL.wait_market_connected` espera
    o timeout completo (3 retries x 300s, ~990s) com spinner infinito.

    Detecção: :func:`data_downloader.dll.log_reader.parse_login_result_from_log`
    lê o bloco em <1s pós-login; se ``activation_result == "MaxHID"``,
    o wrapper raise esta exception em vez de seguir o path legacy
    (``DLLInitError(NL_WAITING_SERVER)`` genérico).

    Subclasse de :class:`DLLInitError` (compatibilidade com adapters
    existentes que tratam ``except DLLInitError``). ``code=-1`` (sentinela
    sem NL_* equivalente direto), ``name="MAX_HID"``.

    Remedies prescritivos (microcopy ``ERR_DLL_MAX_HID``):

    1. Feche o ProfitChart e qualquer outra instância do data-downloader
       (em qualquer máquina).
    2. Acesse https://www.nelogica.com.br/area-cliente e desconecte
       todos os HIDs ativos.
    3. Aguarde 5-30min e tente de novo; se persistir, abra ticket em
       suporte@nelogica.com.br com assunto "licença travada em MaxHID".

    Attributes:
        activation_result: Valor literal do servidor (``"MaxHID"``).
        server_message: Texto humanizado do servidor (ex.: ``"Todos os
            seus logins estão em uso"``).
        timestamp: Datetime BRT naive do bloco no LogDesktop (``None``
            se timestamp não pôde ser parseado).

    Microcopy UI (MICROCOPY_CATALOG.md §5 + Uma sign-off Story 4.29):
        - Título: "Licença Nelogica em uso"
        - Detalhe: "Sua chave de licença Nelogica está em uso em outro
          computador ou sessão..."
        - Ação primária: "Tentar de novo"
        - Ação secundária: "Abrir portal Nelogica"
    """

    def __init__(
        self,
        activation_result: str,
        server_message: str,
        timestamp: datetime | None,
        *,
        cause: Exception | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        # ``message`` carrega o microcopy ID dedicado como prefixo — UI
        # parsing ("ID: detail") dispara lookup direto via MSG.get; sem
        # depender do mapeamento NL_*. Padrão alinhado ao hotfix v1.1.0
        # ``ERR_DLL_MARKET_RETRY_EXHAUSTED`` (Felix+Aria Story 4.21).
        msg = (
            "ERR_DLL_MAX_HID: Licenca Nelogica em uso "
            f"(ActivationResult={activation_result!r}, server_message="
            f"{server_message!r}). Remedies: 1) Feche ProfitChart e outras "
            "instancias do data-downloader; 2) Acesse "
            "https://www.nelogica.com.br/area-cliente e desconecte HIDs "
            "ativos; 3) Aguarde 5-30min e tente de novo. Suporte: "
            "suporte@nelogica.com.br ('licenca travada em MaxHID')."
        )
        merged_details: dict[str, object] = {
            "activation_result": activation_result,
            "server_message": server_message,
            "timestamp": timestamp.isoformat() if timestamp is not None else None,
        }
        if details:
            merged_details.update(details)
        # ``code=-1`` sentinela (sem NL_* equivalente direto). ``name="MAX_HID"``
        # é um identificador simbólico interno para logs/structlog — adapters
        # legacy podem inspecionar via ``exc.name`` se quiserem.
        super().__init__(
            -1,
            "MAX_HID",
            msg,
            cause=cause,
            details=merged_details,
        )
        self.activation_result = activation_result
        self.server_message = server_message
        self.timestamp = timestamp
