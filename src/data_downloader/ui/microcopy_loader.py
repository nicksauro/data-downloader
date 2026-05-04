"""data_downloader.ui.microcopy_loader — Microcopy registry (Story 1.7b).

Owner: Uma (microcopy texts — autoridade exclusiva R17) | Impl: Dex.

Fonte de verdade: ``docs/ux/MICROCOPY_CATALOG.md`` (Story 0.3, finding H14).
Este módulo replica os IDs canônicos como constantes Python para uso pelo
CLI e (futuro Story 3.x) pela UI Qt. A política R17 (no-invention) requer
que **toda** string visível ao usuário em runtime venha daqui — NUNCA
literal hardcoded.

Convenção:
    - IDs em UPPER_SNAKE (idêntico ao MICROCOPY_CATALOG.md).
    - Templates usam ``{var}`` (str.format / f-string) — ver tabela no .md.
    - Texto pt-BR (V1). en-US fica para V2 (catálogo terá ambas linhas).

Acesso:

    from data_downloader.ui.microcopy_loader import MSG, format_msg

    title = MSG["SUC_DOWNLOAD_DONE"].title       # "Download concluído: {symbol}"
    rendered = format_msg("SUC_DOWNLOAD_DONE", "title", symbol="WDOJ26")

Notas:
    - Felix (Story 3.x) replica este módulo (mesmo IDs) ou re-importa para Qt.
    - Mudanças aqui exigem PR + sign-off Uma (R17 — fora do canal Dex).
    - Quirk WAR_99_RECONNECT é texto LITERAL canônico (MICROCOPY_CATALOG §18).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "MSG",
    "MSG_ID_NOT_FOUND",
    "MicrocopyEntry",
    "format_msg",
    "humanize_nl_error",
]


@dataclass(frozen=True)
class MicrocopyEntry:
    """Entrada de microcopy — replica colunas do catálogo.

    Nem toda entry tem todos os campos preenchidos (ex.: ``button`` só usa
    ``title``). ``None`` significa "não aplicável neste tipo".
    """

    msg_type: str  # button | label | error | warning | success | info | empty | prompt
    title: str | None
    detail: str | None = None
    action: str | None = None


# =====================================================================
# Catálogo replicado de docs/ux/MICROCOPY_CATALOG.md (Story 0.3)
# =====================================================================

# §5 — Erros DLL (NL_*) — mapa NL_<code> → MicrocopyEntry.
_NL_ERROR_MAP: Final[dict[str, MicrocopyEntry]] = {
    "NL_NOT_INITIALIZED": MicrocopyEntry(
        msg_type="error",
        title="Não conectei à ProfitDLL",
        detail="A DLL não foi inicializada nesta sessão.",
        action="Inicie o app de novo ou rode `data-downloader doctor`.",
    ),
    "NL_EXCHANGE_UNKNOWN": MicrocopyEntry(
        msg_type="error",
        title="Bolsa desconhecida",
        detail='A bolsa "{exchange}" não foi reconhecida pela DLL.',
        action='Use "B" para Bovespa ou "F" para BMF.',
    ),
    "NL_INTERNAL_ERROR": MicrocopyEntry(
        msg_type="error",
        title="Erro interno da ProfitDLL",
        detail="A DLL retornou um erro não documentado.",
        action="Tente novamente em 1 minuto. Se persistir, abra ticket.",
    ),
    "NL_NOT_LOGGED": MicrocopyEntry(
        msg_type="error",
        title="Sessão não autenticada",
        detail="A DLL conectou, mas não fez login.",
        action="Verifique usuário/senha em ~/.data-downloader/.env.",
    ),
    "NL_INVALID_TICKER": MicrocopyEntry(
        msg_type="error",
        title="Contrato inválido",
        detail='"{symbol}" não é um contrato vigente.',
        action="Liste vigentes: `data-downloader contracts list`.",
    ),
    "NL_NO_LOGIN": MicrocopyEntry(
        msg_type="error",
        title="Credenciais ausentes",
        detail="Não encontrei usuário/senha para conectar.",
        action="Configure PROFIT_USER e PROFIT_PASS em .env.",
    ),
    "NL_NO_LICENSE": MicrocopyEntry(
        msg_type="error",
        title="Licença ausente ou expirada",
        detail="A chave de licença ProfitDLL é inválida ou expirou.",
        action="Renove em https://nelogica.com.br e atualize PROFITDLL_KEY.",
    ),
    "NL_INVALID_ARGS": MicrocopyEntry(
        msg_type="error",
        title="Argumentos inválidos",
        detail="Parâmetros enviados à DLL são inválidos.",
        action="Verifique símbolo e período. Use `--verbose` para detalhes.",
    ),
    "NL_WAITING_SERVER": MicrocopyEntry(
        msg_type="error",
        title="Aguardando servidor",
        detail="A DLL está esperando resposta do servidor da Nelogica.",
        action="Aguarde até 30s. Se passar disso, rode `doctor`.",
    ),
    "NL_NO_TOKEN": MicrocopyEntry(
        msg_type="error",
        title="Token de sessão expirado",
        detail="A sessão DLL expirou e precisa renovar.",
        action="Reinicie o app.",
    ),
    "NL_FILE_ALREADY_EXISTS": MicrocopyEntry(
        msg_type="error",
        title="Arquivo já existe",
        detail="A DLL tentou criar um arquivo que já existe.",
        action="Verifique permissões na pasta de destino.",
    ),
    "NL_PERMISSION_DENIED": MicrocopyEntry(
        msg_type="error",
        title="Permissão negada pela DLL",
        detail="A DLL recusou a operação por falta de permissão.",
        action="Verifique licença e perfil de usuário.",
    ),
    "NL_DISCONNECTED": MicrocopyEntry(
        msg_type="error",
        title="Conexão caiu",
        detail="A DLL perdeu conexão com a corretora.",
        action="Reconectando automaticamente — aguarde 30s.",
    ),
    "NL_VERSION_MISMATCH": MicrocopyEntry(
        msg_type="error",
        title="Versão da DLL incompatível",
        detail="A DLL instalada não bate com a versão esperada pelo app.",
        action="Atualize ProfitDLL ou rode `data-downloader doctor`.",
    ),
}


# Catálogo geral — todas as outras IDs usadas pelo CLI download.
MSG: Final[dict[str, MicrocopyEntry]] = {
    # §2 — botões / comandos
    "BTN_CANCEL": MicrocopyEntry(msg_type="button", title="Cancelar"),
    "BTN_CANCEL_CONFIRM": MicrocopyEntry(msg_type="button", title="Sim, cancelar"),
    "BTN_CONTINUE": MicrocopyEntry(msg_type="button", title="Continuar baixando"),
    "BTN_RETRY": MicrocopyEntry(msg_type="button", title="Tentar Novamente"),
    "BTN_VIEW_CATALOG": MicrocopyEntry(msg_type="button", title="Ver no Catálogo"),
    # §6 — Storage / Sistema
    "ERR_DISK_FULL": MicrocopyEntry(
        msg_type="error",
        title="Disco cheio",
        detail="Não há espaço suficiente em {path}.",
        action="Libere espaço ou mude pasta em Configurações > Pasta.",
    ),
    "ERR_DISK_PERMISSION": MicrocopyEntry(
        msg_type="error",
        title="Sem permissão na pasta",
        detail="Não consigo escrever em {path}.",
        action="Verifique permissões ou escolha outra pasta.",
    ),
    "ERR_INVALID_CONTRACT": MicrocopyEntry(
        msg_type="error",
        title="Contrato fora do calendário",
        detail='"{symbol}" não consta no calendário oficial de contratos vigentes.',
        action="Liste vigentes: `data-downloader contracts list`.",
    ),
    "ERR_INVALID_PERIOD": MicrocopyEntry(
        msg_type="error",
        title="Período inválido",
        detail="A data inicial ({start}) é depois da final ({end}).",
        action='Inverta as datas ou use presets como "Mês corrente".',
    ),
    "ERR_PERIOD_FUTURE": MicrocopyEntry(
        msg_type="error",
        title="Data no futuro",
        detail="Data final ({end}) é no futuro.",
        action="Use uma data <= hoje ({today}).",
    ),
    "ERR_TIMEOUT": MicrocopyEntry(
        msg_type="error",
        title="Timeout da operação",
        detail="A DLL não respondeu em {timeout}s.",
        action="Tente novamente. Se persistir, rode `doctor`.",
    ),
    # §7 — UI/CLI
    "ERR_INPUT_SYMBOL_REQUIRED": MicrocopyEntry(
        msg_type="error",
        title="Símbolo obrigatório",
        detail="Você precisa especificar um símbolo.",
        action="Use `--symbol` ou rode em terminal interativo.",
    ),
    "ERR_INPUT_INVALID_DATE": MicrocopyEntry(
        msg_type="error",
        title="Data inválida",
        detail='"{value}" não é uma data válida (esperado YYYY-MM-DD).',
        action="Exemplo: --start 2026-03-01",
    ),
    # §5 — fallback genérico (NL_* não mapeado)
    "ERR_DLL_GENERIC": MicrocopyEntry(
        msg_type="error",
        title="Erro não documentado da ProfitDLL",
        detail="Código {code}: {message}.",
        action="Use `--verbose` para detalhes. Reporte em github issues.",
    ),
    "ERR_DLL_NO_LICENSE": MicrocopyEntry(
        msg_type="error",
        title="Credenciais ausentes",
        detail="Defina PROFITDLL_KEY, PROFIT_USER, PROFIT_PASS no ambiente.",
        action="Configure em ~/.data-downloader/.env e reinicie o terminal.",
    ),
    # §8 — prompts
    "PMT_CANCEL_CONFIRM": MicrocopyEntry(
        msg_type="prompt",
        title=("Cancelar download em progresso? Trades já baixados serão preservados. [s/N]"),
    ),
    # §9 — sucesso
    "SUC_DOWNLOAD_DONE": MicrocopyEntry(
        msg_type="success",
        title="Download concluído: {symbol}",
        detail="{trade_count} trades em {file_count} arquivos ({size_mb} MB) — {duration}",
        action="Ver no catálogo: `data-downloader list --symbol {symbol}`",
    ),
    "SUC_CACHE_HIT": MicrocopyEntry(
        msg_type="success",
        title="Já estava baixado",
        detail="{symbol} ({period}): nenhum dado novo para baixar.",
        action="Force re-download com `--force` se necessário.",
    ),
    "SUC_CANCEL_DONE": MicrocopyEntry(
        msg_type="success",
        title="Download cancelado",
        detail="Parcial salvo: {n_trades} trades (chunks {a}-{b} de {total}).",
        action="Retomar com: `data-downloader download --symbol {symbol} --resume`",
    ),
    # §10 — warnings (texto LITERAL canônico — quirk Q11-99)
    "WAR_99_RECONNECT": MicrocopyEntry(
        msg_type="warning",
        title=None,  # subtitle inline (CLI_PATTERNS §3)
        detail=(
            "A corretora está reconectando — é normal, " "aguarde até 30 minutos. Não cancele."
        ),
    ),
    "WAR_99_RECONNECT_SHORT": MicrocopyEntry(
        msg_type="warning",
        title=None,
        detail="Reconectando... (normal, aguarde)",
    ),
    "WAR_LARGE_PERIOD": MicrocopyEntry(
        msg_type="warning",
        title="Período grande detectado",
        detail="Vai gerar {n_chunks} chunks (~{eta} minutos).",
        action="Considere baixar em pedaços menores se quiser cancelar facilmente.",
    ),
    # §11 — informativo (status durante download)
    "INF_STARTING_DLL": MicrocopyEntry(
        msg_type="info",
        title="Inicializando ProfitDLL...",
    ),
    "INF_DLL_READY": MicrocopyEntry(
        msg_type="info",
        title="DLL pronta. Versão: {version}.",
    ),
    "INF_LOGIN_OK": MicrocopyEntry(
        msg_type="info",
        title="Login OK.",
    ),
    "INF_FETCHING_CONTRACTS": MicrocopyEntry(
        msg_type="info",
        title="Buscando contratos vigentes para {asset}...",
    ),
    "INF_CONTRACT_SELECTED": MicrocopyEntry(
        msg_type="info",
        title="Contrato selecionado: {symbol} (vigente até {date}).",
    ),
    "INF_STARTING_DOWNLOAD": MicrocopyEntry(
        msg_type="info",
        title="Iniciando download de {period}...",
    ),
    "INF_FETCHING_CHUNK": MicrocopyEntry(
        msg_type="info",
        title="Baixando chunk {x} de {y} ({chunk_start} a {chunk_end})...",
    ),
    "INF_CHUNK_DONE": MicrocopyEntry(
        msg_type="info",
        title="Chunk {x}/{y} OK ({n_trades} trades em {duration}).",
    ),
    "INF_GRACEFUL_SHUTDOWN": MicrocopyEntry(
        msg_type="info",
        title="Drenando fila + commitando parcial...",
    ),
    "INF_RESUMING": MicrocopyEntry(
        msg_type="info",
        title="Retomando download de chunk {x}/{y}...",
    ),
    # §16 — help
    "HLP_DOWNLOAD": MicrocopyEntry(
        msg_type="label",
        title="Baixar histórico de um símbolo.",
    ),
    # §17 — migration framework (Story 2.3 — Sol+Uma mini-council)
    "migration.plan.title": MicrocopyEntry(
        msg_type="info",
        title="Plano de migração: {from_v} -> {to_v}",
        detail="Partições afetadas: {n_partitions} | Bytes (read/write est.): "
        "{bytes_read}/{bytes_write} | ETA: {eta}s",
    ),
    "migration.plan.empty": MicrocopyEntry(
        msg_type="empty",
        title="Nenhuma partição afetada",
        detail="Não há partições registradas em schema_version={from_v}.",
        action="Verifique versões com: `data-downloader integrity check`.",
    ),
    "migration.plan.steps": MicrocopyEntry(
        msg_type="info",
        title="Steps a aplicar:",
        detail="{from_v} -> {to_v}: {description} (breaking={breaking}, rollback={rollback})",
    ),
    "migration.confirm": MicrocopyEntry(
        msg_type="prompt",
        title="Confirmar execução? Backup .bak será criado por partição. [s/N]",
    ),
    "migration.success": MicrocopyEntry(
        msg_type="success",
        title="Migração concluída: {from_v} -> {to_v}",
        detail="{n_migrated} partições migradas, {n_failed} falharam, "
        "{n_skipped} skipped — duração: {duration}s.",
        action="Verifique: `data-downloader integrity check`.",
    ),
    "migration.dry_run": MicrocopyEntry(
        msg_type="info",
        title="DRY-RUN — nenhuma escrita realizada",
        detail="Use `--execute` (sem `--dry-run`) para aplicar.",
    ),
    "migration.error.no_path": MicrocopyEntry(
        msg_type="error",
        title="Sem migration disponível",
        detail="Não há path de {from_v} para {to_v}.",
        action="Liste migrations: `data-downloader migrate plan --help`.",
    ),
    "migration.error.partition_failed": MicrocopyEntry(
        msg_type="error",
        title="Falha em partição: {partition}",
        detail="{error}",
        action="Backup .bak preservado para inspeção manual.",
    ),
    "migration.rollback.success": MicrocopyEntry(
        msg_type="success",
        title="Rollback concluído (run_id: {run_id})",
        detail="{n_rolled_back} partições revertidas a partir de .bak.",
    ),
    "migration.cleanup.success": MicrocopyEntry(
        msg_type="success",
        title="Cleanup de backups concluído",
        detail="{n_removed} arquivos .bak removidos (idade > {days} dias).",
    ),
}


MSG_ID_NOT_FOUND: Final[str] = "<microcopy id not found: {msg_id}>"


def format_msg(msg_id: str, field: str = "title", **kwargs: object) -> str:
    """Formata uma entrada de microcopy aplicando ``str.format(**kwargs)``.

    Args:
        msg_id: ID canônico (ex.: ``"SUC_DOWNLOAD_DONE"``).
        field: Qual campo extrair — ``"title"``, ``"detail"``, ou ``"action"``.
            Default ``"title"``.
        **kwargs: Variáveis para substituição em placeholders.

    Returns:
        String formatada. Se o ID não existe, retorna sentinela visível
        (``"<microcopy id not found: {id}>"``) — facilita auditoria R17
        sem quebrar runtime.

    Raises:
        KeyError: Se algum placeholder esperado não veio em ``kwargs``.
    """
    entry = MSG.get(msg_id)
    if entry is None:
        return MSG_ID_NOT_FOUND.format(msg_id=msg_id)
    template = getattr(entry, field, None)
    if template is None:
        return ""
    return template.format(**kwargs)


def humanize_nl_error(nl_name: str | None, code: int | None = None) -> MicrocopyEntry:
    """Resolve um código NL_* para microcopy estruturada.

    Se ``nl_name`` está mapeado em §5, retorna o entry direto. Caso
    contrário, retorna ``ERR_DLL_GENERIC`` com placeholders preenchidos
    (``{code}`` / ``{message}``) — fallback documentado em
    MICROCOPY_CATALOG.md §5.

    Args:
        nl_name: Nome simbólico (ex.: ``"NL_INVALID_TICKER"``) ou ``None``.
        code: Código numérico para fallback (ignored se ``nl_name`` mapeado).

    Returns:
        ``MicrocopyEntry`` pronta para renderização.
    """
    if nl_name and nl_name in _NL_ERROR_MAP:
        return _NL_ERROR_MAP[nl_name]
    # Fallback genérico — preenche placeholders no clone do entry.
    generic = MSG["ERR_DLL_GENERIC"]
    code_str = str(code) if code is not None else "?"
    name_str = nl_name or "UNKNOWN"
    return MicrocopyEntry(
        msg_type=generic.msg_type,
        title=generic.title,
        detail=(generic.detail or "").format(code=code_str, message=name_str),
        action=generic.action,
    )
