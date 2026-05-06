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
        action="Configure PROFITDLL_USER e PROFITDLL_PASS em .env.",
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
        detail="Defina PROFITDLL_KEY, PROFITDLL_USER, PROFITDLL_PASS no ambiente.",
        action="Configure em ~/.data-downloader/.env e reinicie o terminal.",
    ),
    # Story 2.11 — IDs novos (Uma sign-off COUNCIL-17). Cancelamento H10
    # + ConnectionLost Q02-E. IDs em dot-notation seguem padrão error.*.{title,description}
    # alinhado com MICROCOPY_CATALOG.md §6.
    "error.cancelled.title": MicrocopyEntry(
        msg_type="error",
        title="Download cancelado",
    ),
    "error.cancelled.description": MicrocopyEntry(
        msg_type="error",
        title="Download cancelado",
        detail=(
            "Você cancelou o download. {trades_preserved} trades já " "baixados foram preservados."
        ),
        action="Retomar com: `data-downloader download --symbol {symbol} --resume`",
    ),
    "error.connection_lost.title": MicrocopyEntry(
        msg_type="error",
        title="Conexão perdida",
    ),
    "error.connection_lost.description": MicrocopyEntry(
        msg_type="error",
        title="Conexão perdida",
        detail=(
            "Conexão com a corretora caiu. Tentando reconectar... "
            "(até 30 minutos é normal — Q02-E)"
        ),
        action="Aguarde até 30 minutos. Se persistir, rode `data-downloader doctor`.",
    ),
    # Alias UPPER_SNAKE para compatibilidade com humanized_message public_api.
    "ERR_CONNECTION_LOST": MicrocopyEntry(
        msg_type="error",
        title="Conexão perdida",
        detail=(
            "Conexão com a corretora caiu. Tentando reconectar... "
            "(até 30 minutos é normal — Q02-E)"
        ),
        action="Aguarde até 30 minutos. Se persistir, rode `data-downloader doctor`.",
    ),
    # Aliases used by ERR_CHUNK_FAILED + ERR_CATALOG_DRIFT (referenciados pelo
    # mapa _PUBLIC_ERROR_MICROCOPY_ID em public_api/exceptions.py).
    "ERR_CHUNK_FAILED": MicrocopyEntry(
        msg_type="error",
        title="Chunk falhou após retries",
        detail="Chunk {chunk_id} ({start}-{end}) falhou {n} vezes.",
        action="Use `--resume` para retomar do último sucesso.",
    ),
    "ERR_CATALOG_DRIFT": MicrocopyEntry(
        msg_type="error",
        title="Catálogo desincronizado",
        detail="Detectei diferença entre o catálogo SQLite e os arquivos no disco.",
        action="Rode reconciliação: `data-downloader doctor --reconcile`.",
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
    # =================================================================
    # §17b — Epic 3 IDs (Story 3.1+ — Uma authority via MICROCOPY_CATALOG.md)
    # =================================================================
    # §17b.1 — DownloadScreen
    "BTN_DOWNLOAD": MicrocopyEntry(msg_type="button", title="Baixar Histórico"),
    "BTN_DOWNLOAD_PRIMARY": MicrocopyEntry(msg_type="button", title="⬇ BAIXAR HISTÓRICO"),
    "BTN_LIST_CONTRACTS": MicrocopyEntry(msg_type="button", title="Listar Contratos Vigentes"),
    "BTN_DETAILS": MicrocopyEntry(msg_type="button", title="Detalhes"),
    "BTN_DETAILS_HIDE": MicrocopyEntry(msg_type="button", title="Esconder Detalhes"),
    "LBL_SYMBOL": MicrocopyEntry(msg_type="label", title="Símbolo"),
    "LBL_PERIOD": MicrocopyEntry(msg_type="label", title="Período"),
    "LBL_START_DATE": MicrocopyEntry(msg_type="label", title="Data inicial"),
    "LBL_END_DATE": MicrocopyEntry(msg_type="label", title="Data final"),
    "LBL_OUTPUT_FOLDER": MicrocopyEntry(msg_type="label", title="Pasta de Destino"),
    "LBL_CURRENT_CONTRACT": MicrocopyEntry(msg_type="label", title="Contrato atual"),
    "LBL_DOWNLOAD_SCREEN_TITLE": MicrocopyEntry(msg_type="label", title="Baixar Histórico"),
    "LBL_DOWNLOAD_SCREEN_SUBTITLE": MicrocopyEntry(
        msg_type="label", title="Selecione, configure e clique em baixar"
    ),
    "LBL_DOWNLOAD_SCREEN_SUBTITLE_DOWNLOADING": MicrocopyEntry(
        msg_type="label", title="Baixando {symbol}"
    ),
    "LBL_PERIOD_RANGE_DISPLAY": MicrocopyEntry(
        msg_type="label", title="{start} → {end} (~{duration})"
    ),
    "LBL_ESTIMATE_RANGE": MicrocopyEntry(msg_type="label", title="Estimativa: {min}-{max} minutos"),
    "LBL_ESTIMATE_UNAVAILABLE": MicrocopyEntry(
        msg_type="label", title="Estimativa indisponível — depende do volume"
    ),
    "LBL_ADVANCED_DRAWER": MicrocopyEntry(
        msg_type="label", title="Avançado (chunk size, retry, pasta)"
    ),
    "LBL_NAVIGATION_HINT": MicrocopyEntry(
        msg_type="label",
        title="UI não bloqueia — pode navegar para Catálogo enquanto baixa",
    ),
    "LBL_FOOTER_SHORTCUTS": MicrocopyEntry(
        msg_type="label",
        title="Atalhos: Ctrl+D iniciar  •  Ctrl+R repetir último  •  Ctrl+/ todos",
    ),
    "PLH_SYMBOL": MicrocopyEntry(msg_type="placeholder", title="ex: WDOFUT, PETR4"),
    "PLH_SYMBOL_SUGGESTED_HINT": MicrocopyEntry(
        msg_type="placeholder", title="{symbol} sugerido — contrato vigente do {asset}"
    ),
    "TIP_SYMBOL": MicrocopyEntry(
        msg_type="label",
        title=(
            "Código do ativo. Para futuros use continuous (ex: WDOFUT, WINFUT). "
            "Para ações use ticker B3 (ex: PETR4, VALE3)."
        ),
    ),
    "TIP_PERIOD": MicrocopyEntry(
        msg_type="label",
        title=(
            "Período de histórico para baixar. Default: mês corrente. "
            "Períodos > 30 dias são divididos em chunks."
        ),
    ),
    "TIP_BTN_DOWNLOAD": MicrocopyEntry(msg_type="label", title="Iniciar download (Ctrl+D)."),
    "TIP_BTN_CANCEL": MicrocopyEntry(
        msg_type="label",
        title=(
            "Cancelar download em progresso. Trades já baixados são preservados. " "(Ctrl+C ou Esc)"
        ),
    ),
    "TIP_CANCEL_DURING_RECONNECT": MicrocopyEntry(
        msg_type="label",
        title="Reconnect normal — cancelar agora pode forçar re-baixar tudo.",
    ),
    # §17b.4 — MainWindow / StatusBar
    "LBL_NAV_DOWNLOAD": MicrocopyEntry(msg_type="label", title="Download"),
    "LBL_NAV_CATALOG": MicrocopyEntry(msg_type="label", title="Catálogo"),
    "LBL_NAV_SETTINGS": MicrocopyEntry(msg_type="label", title="Settings"),
    "LBL_STATUSBAR_DLL_CONNECTED": MicrocopyEntry(
        msg_type="label", title="✓ DLL: conectada ({version})"
    ),
    "LBL_STATUSBAR_DLL_DISCONNECTED": MicrocopyEntry(msg_type="label", title="✗ DLL: desconectada"),
    "LBL_STATUSBAR_DLL_CONNECTING": MicrocopyEntry(msg_type="label", title="↻ DLL: conectando..."),
    "LBL_STATUSBAR_APP_VERSION": MicrocopyEntry(msg_type="label", title="v{version}"),
    "LBL_STATUSBAR_SHORTCUTS": MicrocopyEntry(msg_type="label", title="Ctrl+/"),
    "LBL_NAV_BADGE_DOWNLOADING": MicrocopyEntry(msg_type="label", title="↻"),
    # §17b.2 — CatalogScreen (Story 3.2)
    "LBL_CATALOG_SCREEN_TITLE": MicrocopyEntry(msg_type="label", title="Catálogo"),
    "LBL_CATALOG_LOADING": MicrocopyEntry(msg_type="label", title="Carregando catálogo..."),
    "LBL_CATALOG_FOOTER_SUMMARY": MicrocopyEntry(
        msg_type="label", title="{n_partitions} partições  •  {total_mb} MB total"
    ),
    "LBL_CATALOG_FOOTER_DRIFT": MicrocopyEntry(msg_type="label", title="⚠ {n_drift} com drift"),
    "LBL_FILTERS_DROPDOWN": MicrocopyEntry(msg_type="label", title="Filtros"),
    "LBL_DETAIL_PANEL_HEADER": MicrocopyEntry(
        msg_type="label", title="Detalhes: {symbol} (selecionado)"
    ),
    "LBL_DETAIL_FOLDER": MicrocopyEntry(msg_type="label", title="Pasta"),
    "LBL_DETAIL_SCHEMA": MicrocopyEntry(msg_type="label", title="Schema"),
    "LBL_DETAIL_DLL_VERSION": MicrocopyEntry(msg_type="label", title="DLL"),
    "LBL_DETAIL_CHECKSUM": MicrocopyEntry(msg_type="label", title="Checksum"),
    "LBL_DETAIL_CHECKSUM_VALID": MicrocopyEntry(
        msg_type="label", title="✓ válido (sha256: {prefix}...)"
    ),
    "LBL_DETAIL_CHECKSUM_INVALID": MicrocopyEntry(
        msg_type="label", title="✗ inválido — re-baixar recomendado"
    ),
    "LBL_DETAIL_ROW_COUNT": MicrocopyEntry(msg_type="label", title="Row count"),
    "BTN_REVALIDATE_CHECKSUM": MicrocopyEntry(msg_type="button", title="Re-validar Checksum"),
    "BTN_RECONCILE": MicrocopyEntry(msg_type="button", title="Reconciliar"),
    "BTN_CLEAR_FILTERS": MicrocopyEntry(msg_type="button", title="Limpar Filtros"),
    "BTN_REFRESH_CATALOG": MicrocopyEntry(msg_type="button", title="↻ Atualizar (Ctrl+R)"),
    "BTN_DELETE": MicrocopyEntry(msg_type="button", title="Apagar Histórico"),
    "BTN_DELETE_CONFIRM": MicrocopyEntry(msg_type="button", title="Apagar permanentemente"),
    "BTN_OPEN_FOLDER": MicrocopyEntry(msg_type="button", title="Abrir Pasta"),
    "BTN_VALIDATE_CONTRACT": MicrocopyEntry(msg_type="button", title="Validar Contrato"),
    "BTN_REPEAT_LAST": MicrocopyEntry(msg_type="button", title="Repetir Último Download"),
    "EMP_CATALOG_FIRST_RUN_TITLE": MicrocopyEntry(
        msg_type="empty", title="Nenhum dado baixado ainda"
    ),
    "EMP_CATALOG_FIRST_RUN_SUBTITLE": MicrocopyEntry(
        msg_type="empty", title="Comece baixando um símbolo (futures continuous ou ações B3)."
    ),
    # Story 4.6 (UX polish, Pichau directive 2026-05-05) — empty state CTA.
    "BTN_DOWNLOAD_FIRST_SYMBOL": MicrocopyEntry(
        msg_type="button", title="Baixar primeiro símbolo (Ctrl+D)"
    ),
    "EMP_CATALOG_FILTER_NO_MATCH_TITLE": MicrocopyEntry(
        msg_type="empty", title='Nenhum histórico encontrado para "{filter}".'
    ),
    "EMP_CATALOG_FILTER_NO_MATCH_SUBTITLE": MicrocopyEntry(
        msg_type="empty", title="Tente outros filtros ou liste tudo."
    ),
    "WAR_CATALOG_DRIFT_ROW": MicrocopyEntry(
        msg_type="warning",
        title="Diferença detectada entre catálogo e arquivos. Reconcilie para corrigir.",
    ),
    "WAR_CATALOG_DELETE_ACTIVE_DOWNLOAD": MicrocopyEntry(
        msg_type="warning",
        title="Download em progresso para este símbolo. Aguarde ou cancele primeiro.",
    ),
    "MOD_DELETE_PERMANENT_BODY": MicrocopyEntry(
        msg_type="prompt",
        title=(
            "Apagar PERMANENTEMENTE histórico de {symbol}? "
            "Esta operação é irreversível. Trades serão removidos do disco e do catálogo."
        ),
    ),
    "MOD_DELETE_PERMANENT_HINT": MicrocopyEntry(
        msg_type="label", title="Digite APAGAR para confirmar"
    ),
    "TST_RECONCILE_DONE": MicrocopyEntry(
        msg_type="success",
        title="✓ Catálogo reconciliado. {n_added} adicionadas, {n_removed} removidas.",
    ),
    "TST_DELETE_DONE_TOAST": MicrocopyEntry(
        msg_type="info", title="Histórico de {symbol} apagado."
    ),
    # CatalogScreen — column headers
    "LBL_COL_SYMBOL": MicrocopyEntry(msg_type="label", title="Símbolo"),
    "LBL_COL_EXCHANGE": MicrocopyEntry(msg_type="label", title="Bolsa"),
    "LBL_COL_PERIOD": MicrocopyEntry(msg_type="label", title="Período"),
    "LBL_COL_TRADES": MicrocopyEntry(msg_type="label", title="Trades"),
    "LBL_COL_SIZE_MB": MicrocopyEntry(msg_type="label", title="Tamanho (MB)"),
    "LBL_COL_LAST_UPDATE": MicrocopyEntry(msg_type="label", title="Atualizado"),
    "LBL_COL_SCHEMA": MicrocopyEntry(msg_type="label", title="Schema"),
    "PLH_SEARCH_CATALOG": MicrocopyEntry(msg_type="placeholder", title="Buscar por símbolo..."),
    # §17b.3 — SettingsScreen (Story 3.2)
    "LBL_SETTINGS_SCREEN_TITLE": MicrocopyEntry(msg_type="label", title="Configurações"),
    "LBL_SETTINGS_SECTION_DLL": MicrocopyEntry(msg_type="label", title="ProfitDLL"),
    "LBL_SETTINGS_SECTION_STORAGE": MicrocopyEntry(msg_type="label", title="Storage"),
    "LBL_SETTINGS_SECTION_PERFORMANCE": MicrocopyEntry(
        msg_type="label", title="Performance (read-only)"
    ),
    "LBL_SETTINGS_SECTION_ABOUT": MicrocopyEntry(msg_type="label", title="About"),
    "LBL_DLL_STATUS_CONNECTED": MicrocopyEntry(
        msg_type="label", title="✓ Conectada (versão {version})"
    ),
    "LBL_DLL_STATUS_DISCONNECTED": MicrocopyEntry(msg_type="label", title="✗ Não conectou"),
    "LBL_DLL_STATUS_TESTING": MicrocopyEntry(msg_type="label", title="↻ Testando conexão..."),
    "LBL_DLL_STATUS_NOT_CONFIGURED": MicrocopyEntry(msg_type="label", title="⚠ Não configurado"),
    "LBL_DLL_PATH": MicrocopyEntry(msg_type="label", title="DLL path"),
    "LBL_ENV_VARS": MicrocopyEntry(msg_type="label", title="Variáveis .env"),
    "LBL_STORAGE_DATA_DIR": MicrocopyEntry(msg_type="label", title="Pasta data"),
    "LBL_STORAGE_FREE_SPACE": MicrocopyEntry(
        msg_type="label", title="{free_gb} GB livres de {total_gb} GB total"
    ),
    "LBL_STORAGE_CATALOG_OK": MicrocopyEntry(
        msg_type="label", title="✓ íntegro ({n_partitions} partições registradas)"
    ),
    "LBL_STORAGE_CATALOG_DRIFT": MicrocopyEntry(
        msg_type="label",
        title="⚠ {n_drift} diferenças detectadas — rode reconciliar",
    ),
    "LBL_PERF_DLL_QUEUE_SIZE": MicrocopyEntry(msg_type="label", title="DLL queue size"),
    "LBL_PERF_STORAGE_QUEUE_SIZE": MicrocopyEntry(msg_type="label", title="Storage queue size"),
    "LBL_PERF_CHUNK_SIZE": MicrocopyEntry(msg_type="label", title="Chunk size"),
    "LBL_PERF_MAX_RETRIES": MicrocopyEntry(msg_type="label", title="Max retries"),
    "LBL_PERF_NOTE_ADVANCED": MicrocopyEntry(
        msg_type="label",
        title="(Mudanças requerem advanced flags — consulte docs/perf/)",
    ),
    "LBL_PERF_SQLITE_PROFILE": MicrocopyEntry(msg_type="label", title="SQLite profile"),
    "LBL_ABOUT_APP_VERSION": MicrocopyEntry(msg_type="label", title="data-downloader v{version}"),
    "LBL_ABOUT_DLL_VERSION": MicrocopyEntry(msg_type="label", title="ProfitDLL: {version}"),
    "LBL_ABOUT_SCHEMA_VERSION": MicrocopyEntry(msg_type="label", title="Schema: {version}"),
    "LBL_ABOUT_DOCS_LINK": MicrocopyEntry(msg_type="label", title="📖 Documentação"),
    "LBL_ABOUT_BUG_LINK": MicrocopyEntry(msg_type="label", title="🐛 Reportar bug"),
    "BTN_TEST_CONNECTION": MicrocopyEntry(msg_type="button", title="Testar Conexão"),
    "BTN_OPEN_DLL_FOLDER": MicrocopyEntry(msg_type="button", title="Abrir Pasta DLL"),
    "BTN_CHANGE_DATA_DIR": MicrocopyEntry(msg_type="button", title="Mudar Pasta"),
    "BTN_OPEN_DATA_DIR": MicrocopyEntry(msg_type="button", title="Abrir no Explorer"),
    "BTN_INTEGRITY_CHECK": MicrocopyEntry(msg_type="button", title="Verificar Integridade"),
    # Story 4.10 v1.0.3 — Settings/Storage actions (integrity + reconcile from
    # SettingsScreen). Distintos dos toasts do CatalogScreen pois o fluxo aqui
    # é "validar todas partições" (integrity) ou "reconciliar tudo" (reconcile).
    "TST_SETTINGS_INTEGRITY_RUNNING": MicrocopyEntry(
        msg_type="info",
        title="↻ Verificando integridade de {n_partitions} partições...",
    ),
    "TST_SETTINGS_INTEGRITY_OK": MicrocopyEntry(
        msg_type="success",
        title="✓ Integridade OK ({n_ok}/{n_total} partições válidas).",
    ),
    "TST_SETTINGS_INTEGRITY_DRIFT": MicrocopyEntry(
        msg_type="warning",
        title="⚠ {n_bad} de {n_total} partições com drift detectado.",
    ),
    "TST_SETTINGS_RECONCILE_RUNNING": MicrocopyEntry(
        msg_type="info", title="↻ Reconciliando catálogo..."
    ),
    "TST_SETTINGS_OPERATION_ERROR": MicrocopyEntry(
        msg_type="error", title="✗ Erro ao executar operação: {error}"
    ),
    "BTN_DOCTOR_FULL": MicrocopyEntry(msg_type="button", title="Diagnóstico Completo (doctor)"),
    "BTN_SAVE_SETTINGS": MicrocopyEntry(msg_type="button", title="Salvar"),
    "BTN_OPEN_ENV_FOLDER": MicrocopyEntry(msg_type="button", title="Abrir Pasta .env"),
    "BTN_EDIT_ENV": MicrocopyEntry(msg_type="button", title="Editar .env"),
    "BTN_SHOW_SECRET": MicrocopyEntry(msg_type="button", title="Mostrar"),
    "BTN_HIDE_SECRET": MicrocopyEntry(msg_type="button", title="Esconder"),
    "EMP_SETTINGS_DLL_FIRST_RUN_TITLE": MicrocopyEntry(
        msg_type="empty",
        title="Para começar, configure suas credenciais ProfitDLL",
    ),
    "EMP_SETTINGS_DLL_FIRST_RUN_STEP1": MicrocopyEntry(
        msg_type="empty",
        title="1. Obtenha sua chave em https://nelogica.com.br",
    ),
    "EMP_SETTINGS_DLL_FIRST_RUN_STEP2": MicrocopyEntry(
        msg_type="empty",
        title=(
            "2. Crie/edite ~/.data-downloader/.env com PROFITDLL_KEY, "
            "PROFITDLL_USER, PROFITDLL_PASS"
        ),
    ),
    "EMP_SETTINGS_DLL_FIRST_RUN_STEP3": MicrocopyEntry(
        msg_type="empty", title="3. Clique em Testar Conexão"
    ),
    "SUC_SETTINGS_SAVED": MicrocopyEntry(msg_type="success", title="Configurações salvas."),
    "TST_SETTINGS_SAVED": MicrocopyEntry(msg_type="success", title="✓ Configurações salvas."),
    "TST_TEST_CONNECTION_OK": MicrocopyEntry(msg_type="success", title="✓ Conexão OK."),
    "TST_TEST_CONNECTION_FAIL": MicrocopyEntry(
        msg_type="error", title="✗ Conexão falhou. Veja detalhes."
    ),
    "TST_VALIDATION_PASSED": MicrocopyEntry(
        msg_type="success", title="✓ Validação OK: nenhuma inconsistência."
    ),
    "TST_VALIDATION_FAILED": MicrocopyEntry(
        msg_type="error", title="✗ Validação encontrou {n_issues} problemas."
    ),
    # §17b.5 — Toasts e modais
    "TST_DOWNLOAD_DONE": MicrocopyEntry(
        msg_type="success",
        title="✓ {symbol}: {n_trades} trades em {n_files} arquivos.",
    ),
    "TST_CANCEL_DONE": MicrocopyEntry(
        msg_type="info",
        title="↻ Download cancelado. Parcial salvo.",
    ),
    "MOD_QUIT_DURING_DOWNLOAD_TITLE": MicrocopyEntry(
        msg_type="prompt", title="Sair durante download em progresso?"
    ),
    "MOD_QUIT_DURING_DOWNLOAD_BODY": MicrocopyEntry(
        msg_type="prompt",
        title="Trades já baixados serão preservados (cache em re-tentativa).",
    ),
    "BTN_QUIT_AND_CANCEL": MicrocopyEntry(msg_type="button", title="Sim, sair (cancelar download)"),
    "BTN_KEEP_DOWNLOADING": MicrocopyEntry(msg_type="button", title="Continuar baixando"),
    # Empty state DownloadScreen
    "EMP_DOWNLOAD_NEW_USER": MicrocopyEntry(
        msg_type="empty",
        title="Bem-vindo ao data-downloader",
        detail="Selecione um símbolo + período + clique em Baixar.",
    ),
    # =================================================================
    # §17b.6 — Metrics panel (Story 3.3 — Wave 18 — Felix+Uma+Pyro)
    # Status bar metrics integrados com Story 2.4 PrometheusExporter.
    # =================================================================
    "LBL_STATUSBAR_METRICS_PORT": MicrocopyEntry(msg_type="label", title="Métricas: :{port}"),
    "LBL_METRICS_OFF": MicrocopyEntry(msg_type="label", title="Métricas: off"),
    "LBL_METRICS_ACTIVE_DOWNLOADS": MicrocopyEntry(msg_type="label", title="↓ {n}"),
    "LBL_METRICS_QUEUE_DEPTH": MicrocopyEntry(msg_type="label", title="Q: {dll}/{write}"),
    "LBL_METRICS_TRADES_TOTAL": MicrocopyEntry(msg_type="label", title="Σ {n}"),
    "BTN_COPY_METRICS_URL": MicrocopyEntry(msg_type="button", title="Copiar URL"),
    "TST_METRICS_URL_COPIED": MicrocopyEntry(
        msg_type="success", title="✓ URL copiada para clipboard"
    ),
    "MOD_METRICS_DETAILS_TITLE": MicrocopyEntry(msg_type="label", title="Métricas Detalhadas"),
    # =================================================================
    # §17b.7 — Updates section (Story 4.4 — Felix+Gage+Aria COUNCIL-30)
    # Auto-updater stub V1.0 (notify-only). Full tufup integration V1.1.
    # IDs registrados via Uma R17 — sign-off implícito por ausência de
    # disputa em COUNCIL-30 (microcopy curtinho + linha pt-BR consistente).
    # =================================================================
    "LBL_SETTINGS_SECTION_UPDATES": MicrocopyEntry(msg_type="label", title="Atualizações"),
    "LBL_UPDATE_CURRENT_VERSION": MicrocopyEntry(
        msg_type="label", title="Versão atual: v{version}"
    ),
    "LBL_UPDATE_LATEST_VERSION": MicrocopyEntry(msg_type="label", title="Disponível: v{version}"),
    "LBL_UPDATE_STATUS_UNCHECKED": MicrocopyEntry(msg_type="label", title="Clique para verificar."),
    "LBL_UPDATE_STATUS_UP_TO_DATE": MicrocopyEntry(
        msg_type="label", title="✓ Você está com a versão mais recente."
    ),
    "LBL_UPDATE_STATUS_OUTDATED": MicrocopyEntry(
        msg_type="label", title="↑ Nova versão v{version} disponível."
    ),
    "LBL_UPDATE_STATUS_ERROR": MicrocopyEntry(
        msg_type="label", title="✗ Não foi possível verificar updates."
    ),
    "LBL_UPDATE_NOTICE_MANUAL_V1": MicrocopyEntry(
        msg_type="label",
        title=(
            "V1.0: download manual — auto-update automático chega na V1.1. "
            "Veja docs/release/INSTALL.md."
        ),
    ),
    "BTN_CHECK_FOR_UPDATES": MicrocopyEntry(msg_type="button", title="Verificar atualizações"),
    "BTN_DOWNLOAD_UPDATE_MANUAL": MicrocopyEntry(msg_type="button", title="Baixar manualmente"),
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
