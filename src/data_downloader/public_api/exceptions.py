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

from datetime import date as _date

__all__ = [
    "AmbiguousRolloverError",
    "ConnectionLost",
    "DLLInitError",
    "DataDownloaderError",
    "DiskFull",
    "DownloadError",
    "IntegrityError",
    "InvalidContract",
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
    "AmbiguousRolloverError": "ERR_AMBIGUOUS_ROLLOVER",
    "DiskFull": "ERR_DISK_FULL",
    "DownloadError": "ERR_CHUNK_FAILED",
    "IntegrityError": "ERR_CATALOG_DRIFT",
    "OperationCancelled": "SUC_CANCEL_DONE",
    "ConnectionLost": "ERR_CONNECTION_LOST",
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


class AmbiguousRolloverError(InvalidContract):
    """Janela ``[start, end]`` cruza rollover sob uma raiz (Story 4.26 / ADR-028).

    Default-blocked behavior (Q-DRIFT-32 defense): ``download('WDO',
    2026-01-15, 2026-06-15)`` cruzaria 4-5 contratos vigentes WDO. Antes
    da v1.4.0 o orchestrator resolvia ``WDOG26`` uma única vez via
    ``config.start.date()`` e usava-o para todos os chunks — chunks fora
    da vigência de ``WDOG26`` retornavam 0 trades silenciosamente (perda
    de dados invisível).

    A v1.4.0 detecta o caso em ``_validate_config`` e levanta esta
    exceção com mensagem prescritiva listando os contratos detectados
    + as 3 opções de remediação:

      1. **Continuous future** (recomendado): ``download('WDOFUT', ...)``.
      2. **Contrato específico**: sub-range dentro da vigência.
      3. **Opt-in per-chunk**: ``resolve_contract_per_chunk=True`` — cada
         chunk re-resolve o vigente.

    Subclasse de :class:`InvalidContract` para que callers que já
    capturam ``InvalidContract`` continuem funcionando (compat). Quem
    quiser distinguir captura por tipo.

    Args:
        symbol_root: Raiz pedida (ex.: ``"WDO"``).
        start: Início da janela (date).
        end: Fim da janela (date).
        contracts_in_range: Lista ordenada de ``contract_code`` que
            cobrem o range (>= 2 obrigatório — < 2 é caso permitido).

    Attributes:
        symbol_root: Raiz consultada.
        start: Início da janela.
        end: Fim da janela.
        contracts_in_range: Contratos detectados no range.

    Story 4.26 — primeira implementação (raised por
    ``Orchestrator._validate_no_rollover_in_window`` quando
    ``resolve_contract=True AND resolve_contract_per_chunk=False``).
    """

    def __init__(
        self,
        symbol_root: str,
        start: _date,
        end: _date,
        contracts_in_range: list[str],
    ) -> None:
        codes = list(contracts_in_range)
        msg_lines = [
            f"Symbol root {symbol_root!r} cobre {len(codes)} contratos vigentes "
            f"no range [{start.isoformat()}, {end.isoformat()}]:",
        ]
        msg_lines.extend(f"  - {code}" for code in codes)
        msg_lines.extend(
            [
                "",
                "Cross-rollover downloads com raiz sao bloqueados por padrao (Q-DRIFT-32 defense).",
                "Escolha UMA opcao:",
                "",
                "  1. Use o continuous-future (recomendado para historico longo):",
                f"       download({symbol_root}FUT, start=..., end=...)",
                "",
                "  2. Use o contrato especifico (sub-range deve caber dentro da vigencia):",
                f"       download({codes[0] if codes else '<contract>'}, start=..., end=...)",
                "",
                "  3. Habilite re-resolucao por chunk explicitamente (opt-in avancado):",
                f"       download({symbol_root!r}, start=..., end=..., "
                "resolve_contract_per_chunk=True)",
                "       (cada dia baixa com o vigente correto; requer contracts "
                "table populada cobrindo todo o range).",
            ]
        )
        message = "\n".join(msg_lines)
        details: dict[str, object] = {
            "symbol_root": symbol_root,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "contracts_in_range": list(codes),
            "remedy": "use_continuous_future_or_split_or_opt_in_per_chunk",
        }
        # ``InvalidContract.__init__`` aceita ``message`` keyword e mescla
        # ``details``; passar ``on_date=start`` mantém compat com leitura
        # de ``.on_date`` em código existente que trate ``InvalidContract``.
        super().__init__(
            symbol_root,
            start,
            exchange="F",
            message=message,
            details=details,
        )
        self.symbol_root = symbol_root
        self.start = start
        self.end = end
        self.contracts_in_range = list(codes)


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
