# MICROCOPY_CATALOG — Catálogo Exaustivo de Mensagens

> **Toda** string visível ao usuário tem entrada aqui. Felix/Dex consultam
> antes de implementar; não inventam texto em runtime (R17). Uma é a única
> autoridade.

**Versão:** 1.0.0
**Data:** 2026-05-03
**Status:** ratificado (Story 0.3, finding H14)
**Idiomas:** pt-BR (V1), en-US (placeholder para futuro V2)
**Autoridade:** 🎨 Uma — exclusiva

---

## 1. Convenções

### Tipos de mensagem

| Tipo | Uso | Cor (CLI/Qt) |
|------|-----|--------------|
| `button` | Botão clicável (Qt) ou comando CLI | primária/ciano |
| `label` | Texto descritivo de campo | branco |
| `placeholder` | Hint dentro de input vazio | dim |
| `error` | Algo falhou — bloqueia operação | red |
| `warning` | Atenção — não bloqueia | yellow |
| `success` | Operação concluída | green |
| `info` | Status durante operação | dim/info |
| `empty` | Estado vazio educativo | dim + cyan CTA |
| `prompt` | Pergunta interativa | yellow |

### ID

`[CATEGORIA]_[contexto]_[variante?]` em UPPER_SNAKE. Ex.: `BTN_DOWNLOAD`, `ERR_DLL_NOT_INITIALIZED`, `SUC_DOWNLOAD_DONE`.

### Variáveis

`{var_name}` (curly braces). Ex.: `{symbol}`, `{count}`, `{path}`.

### Quirk Q11-99 (texto canônico)

Aparece em múltiplos lugares. Texto **exato e imutável**:

> "A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele."

ID: `WAR_99_RECONNECT`. Ver §6.

---

## 2. Botões / Comandos CLI

| ID | Tipo | Contexto | pt-BR | en-US (placeholder) |
|----|------|----------|-------|---------------------|
| `BTN_DOWNLOAD` | button | Tela Download — ação primária | Baixar Histórico | Download History |
| `BTN_DOWNLOAD_SHORT` | button | Toolbar / espaço estreito | Baixar | Download |
| `BTN_CANCEL` | button | Durante download em progresso | Cancelar | Cancel |
| `BTN_CANCEL_CONFIRM` | button | Modal de confirmação cancel | Sim, cancelar | Yes, cancel |
| `BTN_CONTINUE` | button | Modal de confirmação cancel | Continuar baixando | Keep downloading |
| `BTN_VIEW_CATALOG` | button | Após sucesso (toast) | Ver no Catálogo | View Catalog |
| `BTN_VALIDATE_CONTRACT` | button | Tela Catálogo > item | Validar Contrato | Validate Contract |
| `BTN_LIST_CONTRACTS` | button | Tela Download > Símbolo | Listar Contratos Vigentes | List Active Contracts |
| `BTN_RETRY` | button | Após erro recuperável | Tentar Novamente | Try Again |
| `BTN_OPEN_FOLDER` | button | Tela Catálogo > item | Abrir Pasta | Open Folder |
| `BTN_DELETE` | button | Tela Catálogo > item (destrutivo) | Apagar Histórico | Delete History |
| `BTN_DELETE_CONFIRM` | button | Modal confirmação destrutiva | Apagar permanentemente | Delete permanently |
| `BTN_SETTINGS` | button | Header global | Configurações | Settings |
| `BTN_HELP` | button | Header global | Ajuda | Help |
| `BTN_DETAILS` | button | Expandir log na progress bar | Detalhes | Details |
| `BTN_DETAILS_HIDE` | button | Recolher log expandido | Esconder Detalhes | Hide Details |
| `CMD_DOWNLOAD` | command | CLI subcommand | `download` | `download` |
| `CMD_LIST` | command | CLI subcommand | `list` | `list` |
| `CMD_VALIDATE` | command | CLI subcommand | `validate` | `validate` |
| `CMD_CONTRACTS` | command | CLI subcommand | `contracts` | `contracts` |
| `CMD_REPEAT` | command | CLI subcommand | `repeat` | `repeat` |
| `CMD_DOCTOR` | command | CLI subcommand | `doctor` | `doctor` |

---

## 3. Labels

| ID | Tipo | Contexto | pt-BR | en-US |
|----|------|----------|-------|-------|
| `LBL_SYMBOL` | label | Campo de símbolo | Símbolo | Symbol |
| `LBL_PERIOD` | label | Campo de período | Período | Period |
| `LBL_START_DATE` | label | Data inicial | Data inicial | Start date |
| `LBL_END_DATE` | label | Data final | Data final | End date |
| `LBL_OUTPUT_FOLDER` | label | Pasta de destino | Pasta de Destino | Output folder |
| `LBL_ESTIMATE` | label | Estimativa de tempo | Estimativa | Estimate |
| `LBL_CHUNK_SIZE` | label | Drawer avançado | Tamanho do chunk (dias) | Chunk size (days) |
| `LBL_RETRY_POLICY` | label | Drawer avançado | Política de retry | Retry policy |
| `LBL_PROGRESS` | label | Barra de progresso | Progresso | Progress |
| `LBL_REMAINING` | label | Tempo restante | Restante | Remaining |
| `LBL_ELAPSED` | label | Tempo decorrido | Decorrido | Elapsed |
| `LBL_TRADES_COUNT` | label | Tabela catálogo coluna | Trades | Trades |
| `LBL_FILES_COUNT` | label | Tabela catálogo coluna | Arquivos | Files |
| `LBL_SIZE` | label | Tabela catálogo coluna | Tamanho | Size |
| `LBL_LAST_UPDATE` | label | Tabela catálogo coluna | Última Atualização | Last Update |
| `LBL_CONTRACT_VALID_UNTIL` | label | Sufixo no autocomplete | vigente até {date} | active until {date} |

---

## 4. Placeholders

| ID | Tipo | Contexto | pt-BR | en-US |
|----|------|----------|-------|-------|
| `PLH_SYMBOL` | placeholder | Input símbolo vazio | ex: WDOFUT, PETR4 | e.g.: WDOFUT, PETR4 |
| `PLH_PERIOD` | placeholder | Dropdown período fechado | Selecione o período | Select period |
| `PLH_START_DATE` | placeholder | DatePicker | dd/mm/aaaa | mm/dd/yyyy |
| `PLH_END_DATE` | placeholder | DatePicker | dd/mm/aaaa | mm/dd/yyyy |
| `PLH_OUTPUT_FOLDER` | placeholder | Folder picker | ~/data-downloader/data/ | ~/data-downloader/data/ |
| `PLH_SEARCH_CATALOG` | placeholder | Busca catálogo | Buscar por símbolo... | Search by symbol... |
| `PLH_PERIOD_CURRENT_MONTH` | preset | Período: mês corrente | Mês corrente | Current month |
| `PLH_PERIOD_LAST_MONTH` | preset | Período: mês anterior | Mês anterior | Last month |
| `PLH_PERIOD_TODAY` | preset | Período: hoje | Hoje | Today |
| `PLH_PERIOD_YESTERDAY` | preset | Período: ontem | Ontem | Yesterday |
| `PLH_PERIOD_THIS_WEEK` | preset | Período: esta semana | Esta semana | This week |
| `PLH_PERIOD_CUSTOM` | preset | Período: customizado | Customizado | Custom |

---

## 5. Mensagens de Erro — DLL (NL_*)

> Mapa exaustivo NL_* → mensagem humana. Quando código DLL não está mapeado,
> usa fallback `ERR_DLL_GENERIC` com código numérico exposto no `--verbose`.

### Estrutura padrão (todos)

- **Título** (1 linha, vermelho bold): O QUE ACONTECEU em humano.
- **Detalhe** (1 linha branco): contexto curto.
- **Ação** (1 linha branco imperativo): O QUE O USUÁRIO FAZ AGORA.

| ID | Código DLL | Título | Detalhe | Ação |
|----|------------|--------|---------|------|
| `ERR_DLL_NOT_INITIALIZED` | NL_NOT_INITIALIZED | Não conectei à ProfitDLL | A DLL não foi inicializada nesta sessão. | Inicie o app de novo ou rode `data-downloader doctor`. |
| `ERR_DLL_EXCHANGE_UNKNOWN` | NL_EXCHANGE_UNKNOWN | Bolsa desconhecida | A bolsa "{exchange}" não foi reconhecida pela DLL. | Use "B" para Bovespa ou "F" para BMF. |
| `ERR_DLL_INTERNAL` | NL_INTERNAL_ERROR | Erro interno da ProfitDLL | A DLL retornou um erro não documentado. | Tente novamente em 1 minuto. Se persistir, abra ticket. |
| `ERR_DLL_NOT_LOGGED` | NL_NOT_LOGGED | Sessão não autenticada | A DLL conectou, mas não fez login. | Verifique usuário/senha em ~/.data-downloader/.env. |
| `ERR_DLL_INVALID_TICKER` | NL_INVALID_TICKER | Contrato inválido | "{symbol}" não é um contrato vigente. | Liste vigentes: `data-downloader contracts list`. |
| `ERR_DLL_NO_LOGIN` | NL_NO_LOGIN | Credenciais ausentes | Não encontrei usuário/senha para conectar. | Configure PROFIT_USER e PROFIT_PASS em .env. |
| `ERR_DLL_NO_LICENSE` | NL_NO_LICENSE | Licença ausente ou expirada | A chave de licença ProfitDLL é inválida ou expirou. | Renove em https://nelogica.com.br e atualize PROFITDLL_KEY. |
| `ERR_DLL_INVALID_ARGS` | NL_INVALID_ARGS | Argumentos inválidos | Parâmetros enviados à DLL são inválidos. | Verifique símbolo e período. Use `--verbose` para detalhes. |
| `ERR_DLL_WAITING_SERVER` | NL_WAITING_SERVER | Aguardando servidor | A DLL está esperando resposta do servidor da Nelogica. | Aguarde até 30s. Se passar disso, rode `doctor`. |
| `ERR_DLL_NO_TOKEN` | NL_NO_TOKEN | Token de sessão expirado | A sessão DLL expirou e precisa renovar. | Reinicie o app. |
| `ERR_DLL_FILE_ALREADY_EXISTS` | NL_FILE_ALREADY_EXISTS | Arquivo já existe | A DLL tentou criar um arquivo que já existe. | Verifique permissões na pasta de destino. |
| `ERR_DLL_PERMISSION_DENIED` | NL_PERMISSION_DENIED | Permissão negada pela DLL | A DLL recusou a operação por falta de permissão. | Verifique licença e perfil de usuário. |
| `ERR_DLL_DISCONNECTED` | NL_DISCONNECTED | Conexão caiu | A DLL perdeu conexão com a corretora. | Reconectando automaticamente — aguarde 30s. |
| `ERR_DLL_VERSION_MISMATCH` | NL_VERSION_MISMATCH | Versão da DLL incompatível | A DLL instalada não bate com a versão esperada pelo app. | Atualize ProfitDLL ou rode `data-downloader doctor`. |
| `ERR_DLL_GENERIC` | (catch-all) | Erro não documentado da ProfitDLL | Código {code}: {message}. | Use `--verbose` para detalhes. Reporte em github issues. |
| `ERR_DLL_MARKET_TIMEOUT` | (timeout interno) | Não conectei ao Market Data | MARKET_DATA não conectou após {timeout}s nesta tentativa. | Aguardando próxima tentativa de retry (Story 2.12 — Q-DRIFT-02). |
| `ERR_DLL_MARKET_RETRY_EXHAUSTED` | (retry interno) | Não conectei ao Market Data após retries | Market data não conectou após {max} tentativas. | Verifique horário de pregão B3 (09:00-18:30 BRT) e conexão de rede. Rode `data-downloader doctor` para diagnóstico completo. |
| `ERR_DLL_MAX_HID` | (servidor reportou MaxHID — Story 4.29) | Licença Nelogica em uso | Sua chave de licença Nelogica está em uso em outro computador ou sessão. Feche outras instâncias do data-downloader/ProfitChart e tente de novo, ou desconecte HIDs em https://www.nelogica.com.br/area-cliente. | Tentar de novo |
| `ERR_DLL_MAX_HID_ACTION_SECONDARY` | secondary CTA do banner MaxHID (Story 4.29) | Abrir portal Nelogica | (link externo — abre https://www.nelogica.com.br/area-cliente) | (sem ação adicional) |

> **Story 4.29 — Detecção MaxHID:** quando o servidor Nelogica recusa o login porque a licença está em uso em outro processo (`ActivationResult=MaxHID` no LogDesktop), o wrapper levanta `MaxHIDError(DLLInitError)`. A UI exibe banner com 3 remedies numerados (fechar outras instâncias, desconectar HIDs no portal, aguardar 5-30min) + 2 botões (`ERR_DLL_MAX_HID` action + `ERR_DLL_MAX_HID_ACTION_SECONDARY` link). Link "Ver logs" abre `BTN_OPEN_LOGS_FOLDER` (§17b.3 SettingsScreen).

---

## 6. Mensagens de Erro — Storage / Sistema

| ID | Tipo | Título | Detalhe | Ação |
|----|------|--------|---------|------|
| `ERR_DISK_FULL` | error | Disco cheio | Não há espaço suficiente em {path}. Restam {free} MB, preciso de ~{needed} MB. | Libere espaço ou mude pasta em Configurações > Pasta. |
| `ERR_DISK_PERMISSION` | error | Sem permissão na pasta | Não consigo escrever em {path}. | Verifique permissões ou escolha outra pasta. |
| `ERR_CORRUPTED_PARQUET` | error | Arquivo Parquet corrompido | {file} não pôde ser lido — arquivo provavelmente truncado ou corrompido. | Re-baixe o período: `data-downloader download --symbol {sym} --start {s} --end {e}`. |
| `ERR_CATALOG_DRIFT` | error | Catálogo desincronizado | Detectei diferença entre o catálogo SQLite e os arquivos no disco. | Rode reconciliação: `data-downloader doctor --reconcile`. |
| `ERR_INVALID_CONTRACT` | error | Contrato fora do calendário | "{symbol}" não consta no calendário oficial de contratos vigentes. | Liste vigentes: `data-downloader contracts list`. |
| `ERR_INVALID_PERIOD` | error | Período inválido | A data inicial ({start}) é depois da final ({end}). | Inverta as datas ou use presets como "Mês corrente". |
| `ERR_PERIOD_TOO_OLD` | error | Período fora do range disponível | A DLL só fornece histórico desde {min_date}. Você pediu {start}. | Ajuste data inicial para >= {min_date}. |
| `ERR_PERIOD_FUTURE` | error | Data no futuro | Data final ({end}) é no futuro. | Use uma data <= hoje ({today}). |
| `ERR_HOLIDAY_NO_TRADES` | error | Dia não-útil sem trades | {date} é feriado/fim-de-semana. Sem trades para baixar. | Escolha um dia útil ou um período mais amplo. |
| `ERR_CATALOG_LOCKED` | error | Catálogo em uso | Outro processo está escrevendo no catálogo. | Aguarde 5s e tente de novo. |
| `ERR_NO_INTERNET` | error | Sem conexão com a internet | Não consigo alcançar os servidores da Nelogica. | Verifique sua conexão e firewall. |
| `ERR_TIMEOUT` | error | Timeout da operação | A DLL não respondeu em {timeout}s. | Tente novamente. Se persistir, rode `doctor`. |
| `ERR_CHUNK_FAILED` | error | Chunk falhou após retries | Chunk {chunk_id} ({start}-{end}) falhou {n} vezes. | Use `--resume` para retomar do último sucesso. |
| `error.cancelled.title` | error | Download cancelado | (sem detalhe — combinar com .description) | (sem ação — combinar com .description) |
| `error.cancelled.description` | error | Download cancelado | Você cancelou o download. {trades_preserved} trades já baixados foram preservados. | Retomar com: `data-downloader download --symbol {symbol} --resume` |
| `error.connection_lost.title` | error | Conexão perdida | (sem detalhe — combinar com .description) | (sem ação — combinar com .description) |
| `error.connection_lost.description` | error | Conexão perdida | Conexão com a corretora caiu. Tentando reconectar... (até 30 minutos é normal — Q02-E) | Aguarde até 30 minutos. Se persistir, rode `data-downloader doctor`. |
| `ERR_CONNECTION_LOST` | error | Conexão perdida (alias public exception) | Conexão com a corretora caiu. Tentando reconectar... (até 30 minutos é normal — Q02-E) | Aguarde até 30 minutos. Se persistir, rode `data-downloader doctor`. |

---

## 7. Mensagens de Erro — UI/CLI

| ID | Tipo | Título | Detalhe | Ação |
|----|------|--------|---------|------|
| `ERR_INPUT_SYMBOL_REQUIRED` | error | Símbolo obrigatório | Você precisa especificar um símbolo. | Use `--symbol` ou rode em terminal interativo. |
| `ERR_INPUT_INVALID_DATE` | error | Data inválida | "{value}" não é uma data válida (esperado YYYY-MM-DD). | Exemplo: --start 2026-03-01 |
| `ERR_INPUT_UNKNOWN_FLAG` | error | Opção desconhecida | --{flag} não é uma opção válida. | Veja opções disponíveis: `data-downloader {cmd} --help`. |
| `ERR_NOT_TTY` | error | Modo interativo indisponível | Este comando precisa de terminal interativo. | Rode em um terminal real (não pipe/CI). |

---

## 8. Prompts Interativos

| ID | Tipo | Texto pt-BR | Default | Texto en-US |
|----|------|-------------|---------|-------------|
| `PMT_CANCEL_CONFIRM` | prompt | Cancelar download em progresso? Trades já baixados serão preservados. [s/N]: | N | Cancel download in progress? Already-downloaded trades will be preserved. [y/N]: |
| `PMT_RETRY_PROMPT` | prompt | Chunk falhou ({attempt}/{max_retries}). Tentar de novo? [S/n]: | S | Chunk failed ({attempt}/{max_retries}). Retry? [Y/n]: |
| `PMT_OVERWRITE_CONFIRM` | prompt | Histórico de {symbol}/{period} já existe. Sobrescrever? [s/N]: | N | History for {symbol}/{period} already exists. Overwrite? [y/N]: |
| `PMT_DELETE_CONFIRM` | prompt | Apagar PERMANENTEMENTE histórico de {symbol}? Digite APAGAR para confirmar: | (vazio) | Permanently DELETE history for {symbol}? Type DELETE to confirm: |
| `PMT_LARGE_PERIOD_CONFIRM` | prompt | Período > 180 dias detectado ({n_chunks} chunks, ~{eta} estimados). Continuar? [S/n]: | S | Period > 180 days detected ({n_chunks} chunks, ~{eta} estimated). Continue? [Y/n]: |
| `PMT_SYMBOL_INTERACTIVE` | prompt | Símbolo [{default}]: | (default) | Symbol [{default}]: |

---

## 9. Mensagens de Sucesso

| ID | Tipo | Título | Detalhe | Próximo passo |
|----|------|--------|---------|---------------|
| `SUC_DOWNLOAD_DONE` | success | Download concluído: {symbol} | {trade_count} trades em {file_count} arquivos ({size_mb} MB) — {duration} | Ver no catálogo: `data-downloader list --symbol {symbol}` |
| `SUC_DOWNLOAD_DONE_SHORT` | success | {symbol}: {trade_count} trades em {file_count} arquivos. | — | — |
| `SUC_CACHE_HIT` | success | Já estava baixado | {symbol} ({period}): nenhum dado novo para baixar. | Force re-download com `--force` se necessário. |
| `SUC_CONTRACT_VALIDATED` | success | Contrato válido: {symbol} | Vigente de {start} até {end}. {n_trades} trades baixados. | — |
| `SUC_CANCEL_DONE` | success | Download cancelado | Parcial salvo: {n_trades} trades (chunks {a}-{b} de {total}). | Retomar com: `data-downloader download --symbol {symbol} --resume` |
| `SUC_RECONCILE_DONE` | success | Catálogo reconciliado | {n_added} entradas adicionadas, {n_removed} removidas, {n_unchanged} OK. | — |
| `SUC_DOCTOR_OK` | success | Tudo certo | DLL conectada, disco com {free_gb} GB livres, catálogo íntegro. | — |
| `SUC_DELETE_DONE` | success | Histórico apagado | {symbol}: {n_files} arquivos removidos ({size_mb} MB liberados). | — |

---

## 10. Mensagens de Warning

| ID | Tipo | Título | Detalhe | Ação |
|----|------|--------|---------|------|
| `WAR_99_RECONNECT` | warning | (subtitle inline) | A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele. | (nenhuma — informativa) |
| `WAR_99_RECONNECT_SHORT` | warning | (terminal estreito) | Reconectando... (normal, aguarde) | — |
| `WAR_PARTIAL_CHUNK_FAILED` | warning | Chunk {chunk_id} falhou parcialmente | Recebi {got}/{expected} trades antes do erro. Vou retentar automaticamente. | (nenhuma) |
| `WAR_LARGE_PERIOD` | warning | Período grande detectado | Vai gerar {n_chunks} chunks (~{eta} minutos). | Considere baixar em pedaços menores se quiser cancelar facilmente. |
| `WAR_DST_AMBIGUOUS` | warning | Período inclui datas com DST ambíguo (< 2020) | Brasil tinha horário de verão até 2019. Timestamps podem ter ambiguidade. | Para análises sensíveis a tempo, limite o período a >= 2020. |
| `WAR_NO_VIGENTE` | warning | Contrato {symbol} não está mais vigente | Vigência terminou em {end_date}. Histórico ainda disponível. | OK para baixar histórico; para live, use {next_symbol}. |
| `WAR_HIGH_DLL_QUEUE` | warning | Fila DLL acima de {threshold}% | Sistema sob alta carga. Pode haver perda de eventos se não drenar. | Considere fechar outros apps pesados. |
| `WAR_LOW_DISK` | warning | Espaço em disco baixo | Restam apenas {free_mb} MB em {path}. | Libere espaço para evitar falha no meio do download. |
| `WAR_OLD_DLL_VERSION` | warning | Versão da DLL antiga ({version}) | Recomendado >= {min_version} para suporte completo. | Atualize ProfitDLL pelo cliente Nelogica. |
| `WAR_DLL_MARKET_RETRY` | warning | Reconectando market data | Reconectando market data — tentativa {n}/{max}... | (nenhuma — automática) |

---

## 11. Mensagens Informativas (Status / Progress)

| ID | Tipo | Texto pt-BR (template) |
|----|------|------------------------|
| `INF_STARTING_DLL` | info | Inicializando ProfitDLL... |
| `INF_DLL_READY` | info | DLL pronta. Versão: {version}. |
| `INF_LOGIN_OK` | info | Login OK (token válido até {expiry}). |
| `INF_FETCHING_CONTRACTS` | info | Buscando contratos vigentes para {asset}... |
| `INF_CONTRACT_SELECTED` | info | Contrato selecionado: {symbol} (vigente até {date}). |
| `INF_STARTING_DOWNLOAD` | info | Iniciando download de {period}... |
| `INF_FETCHING_CHUNK` | info | Baixando chunk {x} de {y} ({chunk_start} a {chunk_end})... |
| `INF_CHUNK_DONE` | info | Chunk {x}/{y} OK ({n_trades} trades em {duration}). |
| `INF_WRITING_PARQUET` | info | Gravando {file}... |
| `INF_REGISTERING_CATALOG` | info | Registrando partição no catálogo... |
| `INF_VALIDATING` | info | Validando integridade de {symbol}... |
| `INF_RECONCILING` | info | Reconciliando catálogo com arquivos... |
| `INF_GRACEFUL_SHUTDOWN` | info | Drenando fila + commitando parcial... |
| `INF_RESUMING` | info | Retomando download de chunk {x}/{y}... |

Cor: **dim** (cinza claro). Timestamp prefixado: `[HH:MM:SS]`. Suprimido por
default; aparece com `--verbose` ou no log expansível da progress bar.

---

## 12. Empty States

| ID | Contexto | Título | Subtítulo | CTA |
|----|----------|--------|-----------|-----|
| `EMP_CATALOG_FIRST_RUN` | Catálogo vazio (primeira vez) | Nenhum histórico baixado ainda | Comece baixando um símbolo. | [Baixar Histórico] / `data-downloader download` |
| `EMP_CATALOG_FILTERED` | Filtro sem resultado | Nenhum histórico encontrado para "{filter}" | Tente outros filtros ou liste tudo. | [Limpar filtros] / `data-downloader list` |
| `EMP_CONTRACTS_LIST` | Sem contratos vigentes (DLL fora do ar) | Não consegui listar contratos vigentes | A DLL está conectada? | [Diagnóstico] / `data-downloader doctor` |
| `EMP_DOWNLOAD_NEW_USER` | Tela Download primeira vez | Bem-vindo ao data-downloader | Selecione um símbolo + período + clique em Baixar. | (defaults preenchidos) |
| `EMP_VALIDATION_REPORT_OK` | Validation report sem issues | Tudo íntegro | Nenhuma inconsistência detectada em {n_files} arquivos. | (nenhum) |

---

## 13. Tooltips

| ID | Contexto | Texto pt-BR |
|----|----------|-------------|
| `TIP_SYMBOL` | Input símbolo | Código do ativo. Para futuros use continuous (ex: WDOFUT, WINFUT). Para ações use ticker B3 (ex: PETR4, VALE3). |
| `TIP_PERIOD` | Dropdown período | Período de histórico para baixar. Dividido em chunks de 1 dia útil (política uniforme ADR-023). |
| `TIP_OUTPUT_FOLDER` | Folder picker | Pasta onde os Parquets serão gravados. Será criada se não existir. |
| `TIP_CHUNK_SIZE` | Drawer avançado | Tamanho de cada chunk em dias. Menor = retry mais rápido em falhas. Maior = menos overhead. Default: 1 dia útil. <!-- DEPRECATED: removido em v1.1.0 por ADR-023 (uniform 1d chunks) --> |
| `TIP_BTN_DOWNLOAD` | Botão BAIXAR | Iniciar download (Ctrl+D). |
| `TIP_BTN_CANCEL` | Botão CANCELAR | Cancelar download em progresso. Trades já baixados são preservados. (Ctrl+C ou Esc) |
| `TIP_BTN_VALIDATE` | Botão VALIDAR | Verificar integridade dos dados baixados. |
| `TIP_PROGRESS_DETAILS` | Botão expandir log | Mostrar log detalhado de eventos do download. |
| `TIP_BTN_DELETE` | Botão APAGAR | Apagar PERMANENTEMENTE este histórico do disco. Operação irreversível. |
| `TIP_DLL_VERSION` | Indicador no header | Versão da ProfitDLL conectada. {version}. |

---

## 14. Toasts (notificações temporárias Qt)

| ID | Tipo | Texto pt-BR | Duração |
|----|------|-------------|---------|
| `TST_DOWNLOAD_DONE` | success toast | ✓ {symbol}: {n_trades} trades em {n_files} arquivos. | 5s |
| `TST_CANCEL_DONE` | info toast | ↻ Download cancelado. Parcial salvo. | 3s |
| `TST_COPY_PATH` | info toast | Caminho copiado para a área de transferência. | 2s |
| `TST_FILE_OPENED` | info toast | Pasta aberta no Explorer. | 2s |
| `TST_VALIDATION_PASSED` | success toast | ✓ Validação OK: nenhuma inconsistência. | 4s |
| `TST_VALIDATION_FAILED` | error toast | ✗ Validação encontrou {n_issues} problemas. | 6s + ação "Ver relatório" |

---

## 15. Mensagens do `doctor` (diagnóstico)

| ID | Status | Texto pt-BR |
|----|--------|-------------|
| `DOC_DLL_OK` | ✓ | DLL conectada (versão {version}). |
| `DOC_DLL_FAIL` | ✗ | DLL não conectada: {error}. |
| `DOC_LOGIN_OK` | ✓ | Login OK (usuário {user}, token até {expiry}). |
| `DOC_LOGIN_FAIL` | ✗ | Login falhou: {error}. Verifique PROFIT_USER/PROFIT_PASS em .env. |
| `DOC_DISK_OK` | ✓ | Disco: {free_gb} GB livres em {path}. |
| `DOC_DISK_LOW` | ⚠ | Disco: apenas {free_gb} GB livres em {path}. Recomendado >= 5 GB. |
| `DOC_CATALOG_OK` | ✓ | Catálogo íntegro: {n_partitions} partições registradas. |
| `DOC_CATALOG_DRIFT` | ⚠ | Catálogo dessincronizado: {n_drift} diferenças. Rode `--reconcile`. |
| `DOC_PERMISSIONS_OK` | ✓ | Permissões OK em {path}. |
| `DOC_PERMISSIONS_FAIL` | ✗ | Sem permissão de escrita em {path}. |

---

## 16. Help Strings (subcomandos CLI)

| ID | Comando | Sumário curto pt-BR |
|----|---------|---------------------|
| `HLP_DOWNLOAD` | download | Baixar histórico de um símbolo. |
| `HLP_LIST` | list | Listar histórico já baixado (catálogo). |
| `HLP_CONTRACTS` | contracts | Operações com contratos vigentes (list, info). |
| `HLP_VALIDATE` | validate | Validar integridade de dados baixados. |
| `HLP_REPEAT` | repeat | Repetir o último download. |
| `HLP_DOCTOR` | doctor | Diagnóstico do ambiente (DLL, disco, catálogo). |
| `HLP_VERSION` | version | Mostrar versão do app + da ProfitDLL. |

---

## 17. Política de Atualização do Catálogo

- Toda nova string visível ao usuário **antes** de implementação tem entrada
  aqui (R17). Felix/Dex submetem PR adicionando ID + texto; Uma aprova.
- Strings em runtime sem ID neste catálogo = bug, bloqueia merge.
- Futuro V2: en-US preenchido por Uma + revisão nativa antes de release i18n.
- Variantes regionais (pt-PT, es-ES) ficam para após V2.

---

## 17b. IDs Adicionados — Epic 3 Prep (COUNCIL-12, 2026-05-03)

> Novos IDs para a UI Qt (Epic 3). Sem texto inventado em runtime — Felix
> consome estes IDs ao implementar telas. Uma é a autoridade exclusiva.

### 17b.1 — DownloadScreen (Story 3.2)

| ID | Tipo | Contexto | pt-BR |
|----|------|----------|-------|
| `LBL_CURRENT_CONTRACT` | label | DownloadScreen — label do contrato atual durante download (M16) | Contrato atual |
| `LBL_DOWNLOAD_SCREEN_TITLE` | label | DownloadScreen — título principal | Baixar Histórico |
| `LBL_DOWNLOAD_SCREEN_SUBTITLE` | label | DownloadScreen — subtítulo normal | Selecione, configure e clique em baixar |
| `LBL_DOWNLOAD_SCREEN_SUBTITLE_DOWNLOADING` | label | DownloadScreen — subtítulo durante download | Baixando {symbol} |
| `LBL_PERIOD_RANGE_DISPLAY` | label | DownloadScreen — display formatado do range (template) | {start} → {end} (~{duration}) |
| `LBL_ESTIMATE_RANGE` | label | DownloadScreen — estimativa em banda honesta (template) | Estimativa: {min}-{max} minutos |
| `LBL_ESTIMATE_UNAVAILABLE` | label | DownloadScreen — quando Pyro baseline indisponível | Estimativa indisponível — depende do volume |
| `LBL_ADVANCED_DRAWER` | label | DownloadScreen — header do drawer Avançado | Avançado (chunk size, retry, pasta) |
| `LBL_NAVIGATION_HINT` | label | DownloadScreen — hint de não-bloqueio | UI não bloqueia — pode navegar para Catálogo enquanto baixa |
| `LBL_FOOTER_SHORTCUTS` | label | DownloadScreen — footer com atalhos | Atalhos: Ctrl+D iniciar  •  Ctrl+C cancelar  •  Ctrl+/ todos |
| `PLH_SYMBOL_SUGGESTED_HINT` | placeholder | DownloadScreen — hint quando sugerido | {symbol} sugerido — contrato vigente do {asset} |
| `TIP_CANCEL_DURING_RECONNECT` | tooltip | DownloadScreen — tooltip do CANCELAR durante quirk 99% | Reconnect normal — cancelar agora pode forçar re-baixar tudo. |

### 17b.2 — CatalogScreen (Story 3.3)

| ID | Tipo | Contexto | pt-BR |
|----|------|----------|-------|
| `LBL_CATALOG_SCREEN_TITLE` | label | CatalogScreen — título principal | Catálogo |
| `LBL_CATALOG_LOADING` | label | CatalogScreen — texto durante loading | Carregando catálogo... |
| `LBL_CATALOG_FOOTER_SUMMARY` | label | CatalogScreen — footer summary (template) | {n_partitions} partições  •  {total_mb} MB total |
| `LBL_CATALOG_FOOTER_DRIFT` | label | CatalogScreen — footer drift indicator (template) | ⚠ {n_drift} com drift |
| `LBL_FILTERS_DROPDOWN` | label | CatalogScreen — dropdown de filtros | Filtros |
| `LBL_DETAIL_PANEL_HEADER` | label | CatalogScreen — header do detail panel (template) | Detalhes: {symbol} (selecionado) |
| `LBL_DETAIL_FOLDER` | label | CatalogScreen — detail panel — pasta | Pasta |
| `LBL_DETAIL_SCHEMA` | label | CatalogScreen — detail panel — schema | Schema |
| `LBL_DETAIL_DLL_VERSION` | label | CatalogScreen — detail panel — versão DLL | DLL |
| `LBL_DETAIL_CHECKSUM` | label | CatalogScreen — detail panel — checksum | Checksum |
| `LBL_DETAIL_CHECKSUM_VALID` | label | CatalogScreen — detail panel — checksum OK (template) | ✓ válido (sha256: {prefix}...) |
| `LBL_DETAIL_CHECKSUM_INVALID` | label | CatalogScreen — detail panel — checksum mismatch | ✗ inválido — re-baixar recomendado |
| `LBL_DETAIL_ROW_COUNT` | label | CatalogScreen — detail panel — row count | Row count |
| `BTN_REVALIDATE_CHECKSUM` | button | CatalogScreen — botão re-validar checksum | Re-validar Checksum |
| `BTN_RECONCILE` | button | CatalogScreen — botão reconciliar (drift) | Reconciliar |
| `BTN_CLEAR_FILTERS` | button | CatalogScreen — botão limpar filtros | Limpar Filtros |
| `BTN_REFRESH_CATALOG` | button | CatalogScreen — botão refresh com atalho | ↻ Atualizar (Ctrl+R) |
| `EMP_CATALOG_FILTER_NO_MATCH_TITLE` | empty | CatalogScreen — empty filtrado título (template) | Nenhum histórico encontrado para "{filter}". |
| `EMP_CATALOG_FILTER_NO_MATCH_SUBTITLE` | empty | CatalogScreen — empty filtrado subtítulo | Tente outros filtros ou liste tudo. |
| `WAR_CATALOG_DRIFT_ROW` | warning | CatalogScreen — tooltip linha com drift | Diferença detectada entre catálogo e arquivos. Reconcilie para corrigir. |
| `WAR_CATALOG_DELETE_ACTIVE_DOWNLOAD` | warning | CatalogScreen — bloqueio delete durante download | Download em progresso para este símbolo. Aguarde ou cancele primeiro. |
| `BTN_DOWNLOAD_FIRST_SYMBOL` | button | CatalogScreen — empty state CTA (Story 4.6, Pichau 2026-05-05) | Baixar primeiro símbolo (Ctrl+D) |

### 17b.3 — SettingsScreen (Story 3.4)

| ID | Tipo | Contexto | pt-BR |
|----|------|----------|-------|
| `LBL_SETTINGS_SCREEN_TITLE` | label | SettingsScreen — título principal | Configurações |
| `LBL_SETTINGS_SECTION_DLL` | label | SettingsScreen — header seção DLL | ProfitDLL |
| `LBL_SETTINGS_SECTION_STORAGE` | label | SettingsScreen — header seção Storage | Storage |
| `LBL_SETTINGS_SECTION_PERFORMANCE` | label | SettingsScreen — header seção Performance | Performance (read-only) |
| `LBL_SETTINGS_SECTION_ABOUT` | label | SettingsScreen — header seção About | About |
| `LBL_DLL_STATUS_CONNECTED` | label | SettingsScreen — status DLL conectada (template) | ✓ Conectada (versão {version}) |
| `LBL_DLL_STATUS_DISCONNECTED` | label | SettingsScreen — status DLL desconectada | ✗ Não conectou |
| `LBL_DLL_STATUS_TESTING` | label | SettingsScreen — status durante teste | ↻ Testando conexão... |
| `LBL_DLL_STATUS_NOT_CONFIGURED` | label | SettingsScreen — status sem .env | ⚠ Não configurado |
| `LBL_DLL_PATH` | label | SettingsScreen — label do path DLL | DLL path |
| `LBL_ENV_VARS` | label | SettingsScreen — label de seção env | Variáveis .env |
| `LBL_STORAGE_DATA_DIR` | label | SettingsScreen — label pasta data | Pasta data |
| `LBL_STORAGE_FREE_SPACE` | label | SettingsScreen — label espaço livre (template) | {free_gb} GB livres de {total_gb} GB total |
| `LBL_STORAGE_CATALOG_OK` | label | SettingsScreen — catálogo íntegro (template) | ✓ íntegro ({n_partitions} partições registradas) |
| `LBL_STORAGE_CATALOG_DRIFT` | label | SettingsScreen — catálogo com drift (template) | ⚠ {n_drift} diferenças detectadas — rode reconciliar |
| `LBL_PERF_DLL_QUEUE_SIZE` | label | SettingsScreen — DLL queue size display | DLL queue size |
| `LBL_PERF_STORAGE_QUEUE_SIZE` | label | SettingsScreen — storage queue size display | Storage queue size |
| `LBL_PERF_CHUNK_SIZE` | label | SettingsScreen — chunk size display | Chunk size |
| `LBL_PERF_MAX_RETRIES` | label | SettingsScreen — max retries display | Max retries |
| `LBL_PERF_NOTE_ADVANCED` | label | SettingsScreen — nota sobre advanced flags | (Mudanças requerem advanced flags — consulte docs/perf/) |
| `LBL_ABOUT_APP_VERSION` | label | SettingsScreen — versão app (template) | data-downloader v{version} |
| `LBL_ABOUT_DLL_VERSION` | label | SettingsScreen — versão DLL (template) | ProfitDLL: {version} |
| `LBL_ABOUT_SCHEMA_VERSION` | label | SettingsScreen — versão schema (template) | Schema: {version} |
| `LBL_ABOUT_DOCS_LINK` | label | SettingsScreen — link docs | 📖 Documentação |
| `LBL_ABOUT_BUG_LINK` | label | SettingsScreen — link bugs | 🐛 Reportar bug |
| `BTN_TEST_CONNECTION` | button | SettingsScreen — testar conexão DLL | Testar Conexão |
| `BTN_OPEN_DLL_FOLDER` | button | SettingsScreen — abrir pasta DLL | Abrir Pasta DLL |
| `BTN_CHANGE_DATA_DIR` | button | SettingsScreen — mudar pasta data | Mudar Pasta |
| `BTN_OPEN_DATA_DIR` | button | SettingsScreen — abrir data dir no Explorer | Abrir no Explorer |
| `BTN_INTEGRITY_CHECK` | button | SettingsScreen — verificar integridade catálogo | Verificar Integridade |
| `BTN_DOCTOR_FULL` | button | SettingsScreen — diagnóstico completo | Diagnóstico Completo (doctor) |
| `BTN_SAVE_SETTINGS` | button | SettingsScreen — salvar | Salvar |
| `BTN_OPEN_ENV_FOLDER` | button | SettingsScreen — abrir pasta .env (empty state) | Abrir Pasta .env |
| `BTN_EDIT_ENV` | button | SettingsScreen — editar .env (error state) | Editar .env |
| `BTN_SHOW_SECRET` | button | SettingsScreen — mostrar valor mascarado | Mostrar |
| `BTN_HIDE_SECRET` | button | SettingsScreen — esconder valor | Esconder |
| `EMP_SETTINGS_DLL_FIRST_RUN_TITLE` | empty | SettingsScreen — empty DLL primeiro uso (título) | Para começar, configure suas credenciais ProfitDLL |
| `EMP_SETTINGS_DLL_FIRST_RUN_STEP1` | empty | SettingsScreen — empty DLL passo 1 | 1. Obtenha sua chave em https://nelogica.com.br |
| `EMP_SETTINGS_DLL_FIRST_RUN_STEP2` | empty | SettingsScreen — empty DLL passo 2 | 2. Crie/edite ~/.data-downloader/.env com PROFITDLL_KEY, PROFIT_USER, PROFIT_PASS |
| `EMP_SETTINGS_DLL_FIRST_RUN_STEP3` | empty | SettingsScreen — empty DLL passo 3 | 3. Clique em Testar Conexão |
| `SUC_SETTINGS_SAVED` | success | SettingsScreen — settings salvos | Configurações salvas. |
| `TST_SETTINGS_SAVED` | success toast | SettingsScreen — toast salvar | ✓ Configurações salvas. |
| `BTN_DLL_BROWSE` | button | SettingsScreen — botão "Procurar..." abrir QFileDialog (Story 4.14) | Procurar... |
| `TOOLTIP_DLL_BROWSE` | tooltip | SettingsScreen — tooltip do botão Procurar (Story 4.14) | Selecionar ProfitDLL.dll do disco |
| `LBL_DLL_PATH_AUTO_DETECTED` | info | SettingsScreen — toast quando auto-detect populou DLL path (Story 4.14) | DLL detectada automaticamente |
| `LBL_DLL_PATH_VALID` | label | SettingsScreen — status visual ✓ verde quando DLL válida (Story 4.14) | Arquivo encontrado |
| `LBL_DLL_PATH_NOT_DLL` | label | SettingsScreen — status visual ⚠ ambar quando arquivo existe mas não é ProfitDLL.dll (Story 4.14) | Arquivo existe mas não é ProfitDLL.dll |
| `LBL_DLL_PATH_NOT_FOUND` | label | SettingsScreen — status visual ✗ vermelho quando path inexistente (Story 4.14) | Arquivo não encontrado |

### 17b.4 — MainWindow / Status Bar (Story 3.1)

| ID | Tipo | Contexto | pt-BR |
|----|------|----------|-------|
| `LBL_NAV_DOWNLOAD` | label | MainWindow sidebar — item Download | Download |
| `LBL_NAV_CATALOG` | label | MainWindow sidebar — item Catálogo | Catálogo |
| `LBL_NAV_SETTINGS` | label | MainWindow sidebar — item Settings | Settings |
| `LBL_STATUSBAR_DLL_CONNECTED` | label | StatusBar — DLL conectada (template) | ✓ DLL: conectada ({version}) |
| `LBL_STATUSBAR_DLL_DISCONNECTED` | label | StatusBar — DLL desconectada | ✗ DLL: desconectada |
| `LBL_STATUSBAR_DLL_CONNECTING` | label | StatusBar — DLL conectando | ↻ DLL: conectando... |
| `LBL_STATUSBAR_APP_VERSION` | label | StatusBar — versão app (template) | v{version} |
| `LBL_STATUSBAR_SHORTCUTS` | label | StatusBar — atalho cheat sheet | Ctrl+/ |
| `LBL_NAV_BADGE_DOWNLOADING` | label | Sidebar — badge nav Download durante download | ↻ |

### 17b.5 — Toasts e modais novos (Stories 3.x)

| ID | Tipo | Contexto | pt-BR |
|----|------|----------|-------|
| `TST_RECONCILE_DONE` | success toast | Após reconciliar (template) | ✓ Catálogo reconciliado. {n_added} adicionadas, {n_removed} removidas. |
| `TST_DELETE_DONE_TOAST` | info toast | Após delete (template) | Histórico de {symbol} apagado. |
| `TST_TEST_CONNECTION_OK` | success toast | Settings — teste DLL OK | ✓ Conexão OK. |
| `TST_TEST_CONNECTION_FAIL` | error toast | Settings — teste DLL falhou | ✗ Conexão falhou. Veja detalhes. |
| `MOD_QUIT_DURING_DOWNLOAD_TITLE` | prompt | Modal sair durante download — título | Sair durante download em progresso? |
| `MOD_QUIT_DURING_DOWNLOAD_BODY` | prompt | Modal sair durante download — corpo | Trades já baixados serão preservados (cache em re-tentativa). |
| `BTN_QUIT_AND_CANCEL` | button | Modal sair durante download — confirmar | Sim, sair (cancelar download) |
| `BTN_KEEP_DOWNLOADING` | button | Modal sair durante download — negar | Continuar baixando |
| `MOD_CHEAT_SHEET_TITLE` | label | Modal Ctrl+/ — título | Atalhos disponíveis |
| `MOD_DELETE_PERMANENT_BODY` | prompt | Modal delete — corpo extra (template) | Apagar PERMANENTEMENTE histórico de {symbol}? Esta operação é irreversível. Trades serão removidos do disco e do catálogo. |
| `MOD_DELETE_PERMANENT_HINT` | label | Modal delete — hint para input | Digite APAGAR para confirmar |

---

## 18. Quirk Q11-99 — Texto Canônico (referência rápida)

Este quirk aparece em CLI, Qt, e potencialmente em logs. Um único texto
canônico, replicado **literalmente** em todos os lugares:

> **"A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele."**

Variação curta para terminal estreito (< 80 cols) ou status bar Qt:

> **"Reconectando... (normal, aguarde)"**

ID canônicos:
- `WAR_99_RECONNECT` (texto longo)
- `WAR_99_RECONNECT_SHORT` (texto curto)

Felix/Dex **não** podem editar este texto sem nova autorização de Uma + Nelo.

---

— Uma, desenhando empatia 🎨
