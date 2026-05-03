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
| `BTN_REPEAT_LAST` | button | Tela Catálogo / atalho Ctrl+R | Repetir Último Download | Repeat Last Download |
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
| `PLH_SYMBOL` | placeholder | Input símbolo vazio | ex: WDOJ26 | e.g.: WDOJ26 |
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
| `PMT_LARGE_PERIOD_CONFIRM` | prompt | Período > 30 dias detectado ({n_chunks} chunks, ~{eta} estimados). Continuar? [S/n]: | S | Period > 30 days detected ({n_chunks} chunks, ~{eta} estimated). Continue? [Y/n]: |
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
| `TIP_SYMBOL` | Input símbolo | Código do contrato (ex: WDOJ26 = WDO vencimento abril/2026). Use o autocomplete para ver vigentes. |
| `TIP_PERIOD` | Dropdown período | Período de histórico para baixar. Default: mês corrente. Períodos > 30 dias são divididos em chunks. |
| `TIP_OUTPUT_FOLDER` | Folder picker | Pasta onde os Parquets serão gravados. Será criada se não existir. |
| `TIP_CHUNK_SIZE` | Drawer avançado | Tamanho de cada chunk em dias. Menor = retry mais rápido em falhas. Maior = menos overhead. Default: 30. |
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
