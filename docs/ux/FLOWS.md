# FLOWS — Fluxos Principais Epic 3-Ready

> Fluxos detalhados Epic-3-ready para a UI Qt. Cada flow descreve atores com
> responsabilidades exatas, etapas com (input usuário, ação sistema, microcopy ID,
> duração estimada), decisões textuais, edge cases exaustivos e os 5 estados
> (normal, loading, error, empty, success) com microcopy + ação visual.

**Versão:** 0.2.0 (Epic 3 prep — COUNCIL-12)
**Data:** 2026-05-03
**Status:** ready (Story 0.3 + COUNCIL-12 expansion)
**Autoridade:** Uma — exclusiva sobre fluxos
**Implementação:** Felix (Epic 3 stories 3.1-3.8)

---

## Convenção de Notação

```
[USUÁRIO] = ação humana
[SISTEMA] = ação automática
[DECISÃO] = ramificação (com critério if/then/else textual)
[ERRO]    = caminho de erro tratado
{var}     = variável de runtime
(MID)     = referência a microcopy ID em MICROCOPY_CATALOG.md
~Xs       = duração estimada (Pyro baseline ou empírico)
```

---

## Flow 1 — Baixar Histórico (Golden Path: 1 Clique)

**Cenário:** caso 80% dos usuários — baixar histórico do contrato vigente
do mês corrente. **Promessa de produto inegociável: 1 clique.**

### Atores e Responsabilidades

| Ator | Responsabilidade exata |
|------|------------------------|
| Usuário | Apertar 1 botão (BAIXAR HISTÓRICO). Em casos avançados pode mudar símbolo/período antes. |
| UI Qt — DownloadScreen | Renderizar form com defaults inteligentes; emitir signal de start; consumir progress via QueuedConnection; trocar estado visual (normal → loading → success/error). |
| DownloadAdapter (QObject + QThread) | Bridge entre MainThread Qt e public_api. Chama `download()` em thread separada; itera `handle.stream()`; emite `progress`/`error`/`finished`. |
| public_api (Aria/Dex) | `download(symbol, start, end) -> DownloadHandle`; `handle.stream() -> Iterator[DownloadProgress]`; `handle.cancel()`. Fronteira estável SemVer. |
| Orchestrator | Chunker + retry + commit Parquet. Roda em threads próprias (R11). |
| ProfitDLL (Nelo) | Recebe pedidos de chunk; emite eventos via callbacks. Reconnect ~99% é normal (P4). |
| Storage (Sol) | Atomic write Parquet + registro SQLite catálogo. Schema v1.0.0. |

### Pré-condições

- App instalado e aberto.
- DLL inicializada (Story 1.2 garante via singleton).
- `.env` com `PROFITDLL_KEY`, `PROFIT_USER`, `PROFIT_PASS` válidos.
- Conexão internet ativa.

### Etapas

| # | (a) Input usuário | (b) Ação sistema | (c) Microcopy ID | (d) Duração est. |
|---|-------------------|------------------|------------------|------------------|
| 1 | Abre o app | Carrega `app.py` → `QApplication` → `MainWindow` → `DownloadScreen` (default). | — | < 3s (cold start, target P0) |
| 2 | (passivo) | Lê cache `~/.data-downloader/last_symbol`. Se existe, usa. Senão, consulta `vigent_contract("WDO")` para sugerir contrato vigente do WDO. | `LBL_SYMBOL`, `LBL_CONTRACT_VALID_UNTIL` | < 200ms |
| 3 | (passivo) | Pré-preenche **Período** = `PLH_PERIOD_CURRENT_MONTH` (preset). | `LBL_PERIOD` | < 50ms |
| 4 | (passivo) | Pré-preenche **Pasta** = `~/data-downloader/data/` (cria se não existe). | `LBL_OUTPUT_FOLDER` | < 100ms |
| 5 | (passivo) | Mostra estimativa banda honesta consultando Pyro baseline. | `LBL_ESTIMATE` ("~3-7 min") | — |
| 6 | Clica **[⬇ BAIXAR HISTÓRICO]** OU pressiona Ctrl+D | DownloadScreen → `on_download_clicked()` → `QMetaObject.invokeMethod(adapter, 'start', Qt.QueuedConnection, ...)`. | `BTN_DOWNLOAD` | < 16ms (slot MainThread) |
| 7 | (aguarda) | Tela transforma para estado **loading**: campos viram readonly; aparece QProgressBar + subtitle + log expansível; botão troca para `BTN_CANCEL`. | `INF_STARTING_DOWNLOAD` | < 200ms (transição) |
| 8 | (aguarda; pode navegar) | Adapter.start() em QThread invoca `download()`. Backend abre sessão DLL, faz chunker, emite progress. UI **NÃO bloqueia** — usuário pode ir para Catálogo. | `INF_FETCHING_CHUNK` (template `Chunk {x} de {y}`) | varia (30s–30min) |
| 9 | (passivo; observa) | Cada `progress` recebido: atualiza barra, label `current_contract` (M16), tempo elapsed/remaining. | `LBL_PROGRESS`, `LBL_REMAINING`, `LBL_ELAPSED` | < 16ms por update |
| 10 | (passivo) | Conclui. Adapter emite `finished(DownloadResult)`. UI mostra estado **success**: toast verde 5s + tela volta ao normal com campos ainda preenchidos. | `SUC_DOWNLOAD_DONE`, `TST_DOWNLOAD_DONE`, `BTN_VIEW_CATALOG` | toast 5s |

### Decisões (if/then/else)

| Ponto | Decisão textual |
|-------|----------------|
| Step 2 — escolha de símbolo | **IF** cache `last_symbol` existe e arquivo legível **THEN** usa cache **ELSE IF** `vigent_contract("WDO")` retorna válido **THEN** usa contrato vigente **ELSE** mostra empty state `EMP_DOWNLOAD_NEW_USER` com placeholder `PLH_SYMBOL` ("ex: WDOJ26"). |
| Step 5 — estimativa | **IF** Pyro baseline disponível para tamanho de período **THEN** mostra banda (3-7 min) **ELSE** mostra "Estimativa indisponível — depende do volume" (sem inventar número — P9 zero alucinação). |
| Step 6 — validação inline | **IF** símbolo inválido (não-vigente, formato errado) **THEN** bloqueia botão + mostra erro inline `ERR_DLL_INVALID_TICKER` ao lado do campo **ELSE IF** período > 30 dias **THEN** mostra warning inline `WAR_LARGE_PERIOD` (não bloqueia, informa) **ELSE** habilita botão. |
| Step 8 — navegação durante download | **IF** usuário clica em "Catálogo" no nav **THEN** muda QStackedWidget para CatalogScreen, mantém adapter rodando, badge visual no nav Download mostra "↻ baixando". |
| Step 9 — quirk 99% reconnect | **IF** `progress.state == "reconnecting"` **THEN** ver Flow 4. |
| Step 10 — pós-sucesso | Toast aparece top-right, auto-dismiss 5s, dismissable manual. Click no link "Ver no Catálogo" navega para CatalogScreen filtrado pelo símbolo recém-baixado. |

### 5 Estados

| Estado | Microcopy ID | Ação visual |
|--------|--------------|-------------|
| **Normal** | `LBL_SYMBOL`, `LBL_PERIOD`, `LBL_OUTPUT_FOLDER`, `LBL_ESTIMATE`, `BTN_DOWNLOAD` | Form preenchido com defaults; botão primário ativo (cor `primary` #4F8CFF); cursor disponível em campos. |
| **Loading** | `INF_STARTING_DOWNLOAD` → `INF_FETCHING_CHUNK` → `INF_WRITING_PARQUET` | Form readonly (opacity 60%); QProgressBar visível com cor `accent.cyan`; subtitle textual + ETA; log expansível (▸ Detalhes); botão muda para `BTN_CANCEL` (cor `error.red`). |
| **Error** | `ERR_DLL_*` ou `ERR_DISK_*` (depende da causa) | Card vermelho com título bold + detalhe + ação imperativa; ícone ✗; botão `BTN_RETRY` (primário) + link "▸ Mais detalhes" (expand log técnico). |
| **Empty** (primeira vez) | `EMP_DOWNLOAD_NEW_USER` | Subtitle "Bem-vindo!"; placeholder `PLH_SYMBOL`; defaults pré-preenchidos com sugestão WDO vigente; tooltip educativo no botão. |
| **Success** | `SUC_DOWNLOAD_DONE`, `TST_DOWNLOAD_DONE` | Toast verde top-right 5s com `BTN_VIEW_CATALOG`; tela volta ao normal mantendo campos preenchidos para próximo download. |

### Edge Cases (lista exaustiva)

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | DLL não conectou (chave inválida) | Estado **Error** com `ERR_DLL_NO_LICENSE`; botão `BTN_RETRY` + link "Abrir Configurações > DLL". |
| EC2 | Símbolo digitado não é contrato vigente | Validação inline antes de start: `ERR_DLL_INVALID_TICKER`; sugestão de contrato vigente próximo (ex: "Quer usar WDOJ26?"). |
| EC3 | Período > 1 contrato (rollover no meio) | Backend faz `download_continuous`; UI mostra `current_contract` atual (M16); subtitle muda automaticamente quando rollover detectado. |
| EC4 | Período > 30 dias | Warning inline `WAR_LARGE_PERIOD` antes do start ("Vai gerar N chunks, ~X minutos"); não bloqueia, informa. Confirmação `PMT_LARGE_PERIOD_CONFIRM` se > 90 dias. |
| EC5 | Disco cheio durante write | Erro graceful `ERR_DISK_FULL`; parcial preservado (atomic write); UI mostra estado Error com link "Mudar pasta em Configurações". |
| EC6 | Cancel mid-download (Ctrl+C / Esc / botão) | Ver Flow 3 completo. |
| EC7 | Quirk 99% reconnect | Ver Flow 4 completo. |
| EC8 | Smoke 30 dias real (primeira vez ambiente real) | Mesmo flow normal; Quinn valida via VM; sem tratamento especial UI. |
| EC9 | Re-baixar período já baixado (cache hit) | Cache hit silencioso `SUC_CACHE_HIT`; sem trabalho duplicado; toast info "Já estava baixado — nada novo." |
| EC10 | Conexão internet cai completamente | `ERR_NO_INTERNET`; estado Error com `BTN_RETRY`. |
| EC11 | DLL desconecta no meio (não 99% reconnect) | Auto-retry interno do orchestrator; se falhar > 3x, `ERR_DLL_DISCONNECTED`. |
| EC12 | App fecha durante download (Ctrl+Q ou X janela) | Confirmação modal "Cancelar download em progresso?" (PMT_CANCEL_CONFIRM); se confirma: drain + commit parcial (Flow 3); se nega: cancela close. |
| EC13 | Período inclui só feriado/weekend (sem trades) | `ERR_HOLIDAY_NO_TRADES` se range inteiro for inviável; senão continua e log marca dias vazios. |
| EC14 | Pasta de destino sem permissão de escrita | `ERR_DISK_PERMISSION` antes de start; bloqueia botão + link "Mudar pasta". |
| EC15 | Versão DLL desatualizada | Warning `WAR_OLD_DLL_VERSION` no startup (não bloqueia); aparece no Settings também. |
| EC16 | Catálogo SQLite locked por outro processo | `ERR_CATALOG_LOCKED`; estado Error com `BTN_RETRY` (auto após 5s). |
| EC17 | Período inválido (start > end) | Validação inline `ERR_INVALID_PERIOD` antes de start; bloqueia botão. |
| EC18 | Data no futuro | Validação inline `ERR_PERIOD_FUTURE`; bloqueia botão. |
| EC19 | Período fora do range disponível na DLL | `ERR_PERIOD_TOO_OLD`; sugere data inicial mínima. |
| EC20 | Métrica `ui_progress_dropped_count > 0` (M11) | Não bloqueia, mas registra log; se > threshold em sessão, hint dim no log expansível. |

---

## Flow 2 — Browse Catálogo

**Cenário:** usuário quer ver/gerenciar/validar histórico já baixado.

### Atores e Responsabilidades

| Ator | Responsabilidade exata |
|------|------------------------|
| Usuário | Navegar, filtrar, selecionar partições; pode deletar (com confirm) ou re-validar checksum. |
| UI Qt — CatalogScreen | Renderizar QTableView com `QSortFilterProxyModel`; gerenciar filtros; abrir confirm modals destrutivos. |
| CatalogAdapter (QObject + QThread) | Bridge para `public_api.read()` e queries SQLite. Lista partições com metadata (row_count, size, schema_version, checksum). |
| public_api | `read(symbol, start, end)`, queries auxiliares de catálogo (futuro Story 3.3). |
| Storage (Sol) | SQLite catalog DB + Parquet partitions. |

### Pré-condições

- App aberto.
- Catálogo SQLite existe (criado no primeiro download ou bootstrap).

### Etapas

| # | (a) Input usuário | (b) Ação sistema | (c) Microcopy ID | (d) Duração est. |
|---|-------------------|------------------|------------------|------------------|
| 1 | Clica em "Catálogo" no sidebar OU Ctrl+B | `MainWindow.stack.setCurrentWidget(catalog_screen)`. | — | < 16ms |
| 2 | (passivo) | CatalogScreen mostra loading skeleton. CatalogAdapter dispara `list_partitions()` em QThread. | "Carregando catálogo..." | < 500ms (típico) |
| 3 | (passivo) | Adapter executa query SQLite + (opcional) join com Parquet metadata. Emite `partitions(list)`. | — | < 200ms para < 1000 partições |
| 4 | (passivo) | UI popula QTableView com colunas: contract, year, month, row_count, size_mb, last_modified, schema_version. Default sort: `last_modified DESC`. | `LBL_TRADES_COUNT`, `LBL_FILES_COUNT`, `LBL_SIZE`, `LBL_LAST_UPDATE` | < 100ms |
| 5 | Filtro: digita em busca (Ctrl+F) | `QSortFilterProxyModel.setFilterFixedString(symbol)`. Debounce 300ms. | `PLH_SEARCH_CATALOG` | < 50ms por filtro |
| 6 | Filtro: escolhe exchange/date range no drawer "Filtros" | Aplica predicado custom no proxy model. | "Filtros" (`BTN_DETAILS` reused) | — |
| 7 | Seleciona linha (click ou Enter) | Mostra detail panel embaixo com: pasta completa, schema_version, dll_version, checksum status, ações. | `BTN_VALIDATE_CONTRACT`, `BTN_OPEN_FOLDER`, `BTN_DELETE` | < 50ms |
| 8 | Clica `BTN_DELETE` | Abre confirm modal destrutivo `PMT_DELETE_CONFIRM` (digitar APAGAR). | `PMT_DELETE_CONFIRM`, `BTN_DELETE_CONFIRM` | — |
| 9 | Confirma delete | Backend remove arquivos Parquet + entrada SQLite. Toast info `SUC_DELETE_DONE`. | `SUC_DELETE_DONE` | < 1s típico |
| 10 | Clica "Re-validar checksum" | Backend re-calcula checksum dos Parquets + compara com SQLite. Toast verde ou erro. | `TST_VALIDATION_PASSED` ou `TST_VALIDATION_FAILED` | depende do tamanho |
| 11 | Ctrl+R | Refresh: re-roda step 2-4. | `BTN_REFRESH_CATALOG` | — |

### Decisões (if/then/else)

| Ponto | Decisão textual |
|-------|----------------|
| Step 4 — drift detectado | **IF** alguma partição tem drift (catalog_size != disk_size, ou checksum mismatch) **THEN** marca linha com ⚠ + tooltip + CTA "Reconciliar" no footer. |
| Step 5 — busca sem match | **IF** filtro retorna 0 linhas **THEN** mostra empty state `EMP_CATALOG_FILTERED` com botão "Limpar filtros". |
| Step 8 — delete enquanto download em progresso do mesmo símbolo | **IF** símbolo ativamente sendo baixado **THEN** bloqueia delete + warning "Download em progresso. Aguarde ou cancele primeiro." |
| Step 10 — re-validar checksum mismatch | **IF** mismatch detectado **THEN** toast `TST_VALIDATION_FAILED` com link "Re-baixar período" (atalho para Flow 1 com símbolo+período pré-preenchidos). |

### 5 Estados

| Estado | Microcopy ID | Ação visual |
|--------|--------------|-------------|
| **Normal** | (sem mensagem específica; tabela populada) | QTableView com partições; detail panel embaixo (visível se row selected); footer summary "{N} partições, {total_mb} MB total". |
| **Loading** | "Carregando catálogo..." | Skeleton rows (░░░░ animado dim); barra busca disabled. |
| **Error** | `ERR_CATALOG_DRIFT` ou `ERR_DISK_PERMISSION` ou `ERR_CATALOG_LOCKED` | Card centralizado: ⚠ título + detalhe + ação ([RECONCILIAR] / [ABRIR PASTA] / [TENTAR NOVAMENTE]). |
| **Empty** | `EMP_CATALOG_FIRST_RUN` (zero partições) ou `EMP_CATALOG_FILTERED` (filtro 0 results) | Ícone xl 📁 (ou substituto) + título + subtítulo educativo + CTA primário [⬇ BAIXAR HISTÓRICO] (navega Flow 1) ou [Limpar Filtros]. |
| **Success** | `SUC_RECONCILE_DONE`, `SUC_DELETE_DONE`, `TST_VALIDATION_PASSED` | Toast top-right (verde para reconcile/validate OK; info para delete); tabela atualiza automaticamente. |

### Edge Cases

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Catálogo > 1000 partições | Virtual scroll automático via QTableView nativo; paginação opcional via drawer Avançado. |
| EC2 | Drift detectado (catalog ≠ disk) | Linha marcada com ⚠; CTA footer "Reconciliar"; click → roda `doctor --reconcile` em adapter. |
| EC3 | Filtro sem resultado | `EMP_CATALOG_FILTERED` + botão "Limpar filtros". |
| EC4 | Arquivo Parquet corrompido | Indicador ⚠ na linha + tooltip `ERR_CORRUPTED_PARQUET`; ação "Re-baixar". |
| EC5 | Outro processo escrevendo no SQLite (lock) | Read-only mode + warning "Catálogo em uso — atualizando em modo leitura"; retry automático após 5s. |
| EC6 | Apagar enquanto download em progresso do mesmo símbolo | Bloqueia delete + warning "Download em progresso. Aguarde ou cancele primeiro." |
| EC7 | Re-validar checksum em arquivo grande (> 100MB) | Progress bar inline na linha (não modal); cancelável. |
| EC8 | Filesystem lento (HDD remoto) | Loading state estende até completion; sem timeout artificial; usuário vê skeleton. |
| EC9 | Schema version legacy (não-v1.0.0) | Linha marcada com badge "v0.x"; tooltip "Schema legado — re-baixar para schema atual recomendado". |

---

## Flow 3 — Cancelar Download em Progresso

**Cenário:** usuário muda de ideia ou nota erro e quer parar download.

### Atores e Responsabilidades

| Ator | Responsabilidade exata |
|------|------------------------|
| Usuário | Apertar botão CANCELAR ou Ctrl+C ou Esc na DownloadScreen. |
| UI Qt — DownloadScreen | Capturar cancel intent; abrir modal confirm; após confirm, transitar para estado "cancelando"; chamar `adapter.cancel()` via `QMetaObject.invokeMethod`. |
| DownloadAdapter | `@Slot cancel()` chama `handle.cancel()` (ADR-007a). |
| public_api — DownloadHandle | `cancel()` sinaliza orchestrator para drain + commit parcial. |
| Orchestrator | Recebe sinal cancel: para chunker, drena dll_queue, commita Parquet parcial, atualiza catalog (`status="cancelled"`), fecha sessão DLL. |

### Pré-condições

- Download em progresso (estado **Loading** do Flow 1, com `current_handle != None`).

### Etapas (UI Qt)

| # | (a) Input usuário | (b) Ação sistema | (c) Microcopy ID | (d) Duração est. |
|---|-------------------|------------------|------------------|------------------|
| 1 | Clica `BTN_CANCEL` OU Esc OU Ctrl+C | DownloadScreen captura via QShortcut (WidgetWithChildrenShortcut scope). | `BTN_CANCEL` | < 16ms |
| 2 | (passivo) | Abre modal confirmação destrutivo (não-bloqueante visualmente, mas modal porque destrutivo). | `PMT_CANCEL_CONFIRM`, `BTN_CANCEL_CONFIRM`, `BTN_CONTINUE` | < 100ms |
| 3 | Escolhe ação | **IF** "Continuar baixando": modal fecha, download segue normal. **ELSE** ("Sim, cancelar"): step 4. | — | — |
| 4 | (aguarda) | Estado **Loading.cancelling** (sub-estado): botão CANCELAR vira "Cancelando..." disabled; spinner amarelo; subtitle troca para `INF_GRACEFUL_SHUTDOWN`. | `INF_GRACEFUL_SHUTDOWN` | — |
| 5 | (aguarda) | `QMetaObject.invokeMethod(adapter, 'cancel', QueuedConnection)` → `adapter.cancel()` → `handle.cancel()`. | — | < 16ms (slot) |
| 6 | (aguarda) | Backend: para chunker, drena dll_queue (até 30s típico), commita parcial Parquet (atomic), atualiza SQLite (`status="cancelled"`, `n_partial_trades`), fecha sessão DLL. | — | tipicamente < 30s |
| 7 | (passivo) | Adapter recebe último progress + emite `finished(DownloadResult(status=cancelled))`. | — | — |
| 8 | (passivo) | UI mostra estado **Success do cancel**: toast info `TST_CANCEL_DONE`; tela volta ao normal (campos preenchidos). | `SUC_CANCEL_DONE`, `TST_CANCEL_DONE` | toast 3s |

### Etapas (CLI — referência cruzada)

| # | Ação |
|---|------|
| 1 | Usuário aperta Ctrl+C |
| 2 | SIGINT capturado pelo handler graceful (NÃO termina abrupto) |
| 3 | Inline prompt `PMT_CANCEL_CONFIRM` |
| 4 | **IF** "s": continua step 5 **ELSE** retoma download |
| 5 | Drain + commit parcial |
| 6 | `SUC_CANCEL_DONE` + exit code 130 |

### Decisões (if/then/else)

| Ponto | Decisão textual |
|-------|----------------|
| Step 2 — modal | **IF** quirk 99% reconnect ativo no momento do cancel **THEN** modal mostra warning extra: "A corretora está reconectando. Cancelar agora pode forçar re-baixar tudo. Continuar cancelando?" (override do PMT_CANCEL_CONFIRM padrão). |
| Step 6 — drain demora > 30s | **IF** drain ainda em andamento após 30s **THEN** UI mostra toast com botão "Forçar saída" (SIGKILL/QThread.terminate, com warning "buffer pode ser perdido"). |
| Step 8 — pós-cancel | Tela mostra subtle hint: "Retomar com botão BAIXAR (período pré-preenchido com last range)" — convida resume natural. |

### 5 Estados

| Estado | Microcopy ID | Ação visual |
|--------|--------------|-------------|
| **Normal** | (n/a — flow é transição) | — |
| **Loading.cancelling** (sub-estado) | `INF_GRACEFUL_SHUTDOWN` | Botão "Cancelando..." disabled cinza; spinner amarelo no header da progress card; barra mantém última posição. |
| **Error** | "Erro ao cancelar limpo. Dados parciais podem estar inconsistentes." | Card amarelo (não vermelho — não é erro fatal); CTA "Rodar `doctor --reconcile`" + link "Abrir log". |
| **Empty** | (n/a) | — |
| **Success do cancel** | `SUC_CANCEL_DONE`, `TST_CANCEL_DONE` | Toast info top-right 3s "↻ Download cancelado. {N} trades já salvos preservados."; tela volta ao normal. |

### Edge Cases

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Usuário cancela depois cancela de novo (Ctrl+C 2x rápido) | Force quit (`QThread.terminate()`) + warning "buffer pode ter dados perdidos"; exit 130. |
| EC2 | Cleanup demora > 30s | Toast com botão "Forçar saída" após 30s. |
| EC3 | Disco cheio durante commit parcial | Aviso `ERR_DISK_FULL`; parcial pode ficar incompleto; log para reconcile manual posterior. |
| EC4 | Cancelamento durante quirk 99% reconnect | Confirmação extra com warning específico (ver Step 2 decisão). |
| EC5 | Após cancelar, usuário tenta retomar (Flow 1 mesmo símbolo+período) | Cache hit detecta partial; backend retoma do último chunk OK (ADR-007a `--resume` semântica). |
| EC6 | Backend não responde a cancel (handle.cancel() vapor) | Timeout 60s → `QThread.terminate()` + warning hard "Cancelamento forçado — verificar integridade com `doctor`". |
| EC7 | Cancel após 100% (já no commit final) | Bloqueia cancel + info "Quase pronto — finalizando salvamento ({Xs} restantes)". |

---

## Flow 4 — Quirk 99% Reconnect (NÃO é cancelar)

**Cenário:** download chega em ~99% e a corretora "desconecta" para
re-sincronizar. Comportamento normal validado por Nelo. UI deve informar
sem assustar e **NÃO oferecer cancel implicitamente**.

### Atores e Responsabilidades

| Ator | Responsabilidade exata |
|------|------------------------|
| ProfitDLL (Nelo) | Emite evento `dll.reconnecting` ao detectar reconnect; depois `dll.reconnected`. |
| Orchestrator | Captura evento, propaga via `DownloadProgress(state="reconnecting", percent=99, current_contract=...)`. |
| DownloadAdapter | Emite `progress` com state="reconnecting"; UI atualiza estado visual. |
| UI Qt — DownloadScreen | Detecta state="reconnecting"; muda cor barra (amarelo), mostra overlay/banner literal `WAR_99_RECONNECT`, mantém botão CANCELAR mas com tooltip warning. |
| Usuário | Aguarda (não cancela, conforme microcopy literal pede). |

### Pré-condições

- Download em progresso (Flow 1 estado Loading).
- DLL emitiu evento de reconnect (geralmente em ~99%, mas pode ser em outros %).

### Etapas

| # | (a) Input usuário | (b) Ação sistema | (c) Microcopy ID | (d) Duração est. |
|---|-------------------|------------------|------------------|------------------|
| 1 | (passivo; observa) | Backend recebe sinal `dll.reconnecting`. Orchestrator emite `DownloadProgress(state="reconnecting", percent=99, current_contract=X)`. | — | — |
| 2 | (passivo) | Adapter emite signal Qt `progress(DownloadProgress)` com state="reconnecting". | — | — |
| 3 | (passivo) | UI/CLI atualiza visual: barra **mantém em 99%** (NÃO regride); cor muda de **ciano** para **amarelo** (`warning.yellow` #F2C94C); spinner pulsante aparece ao lado da barra. | — | < 16ms |
| 4 | (passivo) | Aparece overlay/banner amarelo com texto LITERAL exato `WAR_99_RECONNECT`: "A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele." | `WAR_99_RECONNECT` (texto literal canônico — § MICROCOPY 18) | persiste até reconnect |
| 5 | (passivo) | Botão CANCELAR ainda visível (H3 — controle do usuário sempre disponível) MAS com tooltip warning: "Reconnect normal — cancelar agora pode forçar re-baixar tudo." | `BTN_CANCEL`, `TIP_BTN_CANCEL` (custom tooltip) | — |
| 6 | (aguarda) | Tipicamente 1-30 min (validado Nelo). Sem timer visível (P9 — não inventar tempo exato). | — | varia (1-30 min) |
| 7 | (passivo) | Backend recebe `dll.reconnected`. Emite `progress(state="resuming", percent=99)`. | — | — |
| 8 | (passivo) | UI: subtitle volta ao normal; cor barra volta para **ciano**; spinner some. Sem toast/notificação (P7 — sucesso silencioso). | `INF_FETCHING_CHUNK` (volta ao padrão) | < 16ms |
| 9 | (passivo) | Download retoma, vai para 100%, mostra `SUC_DOWNLOAD_DONE` (Flow 1 step 10). | `SUC_DOWNLOAD_DONE` | — |

### Decisões (if/then/else)

| Ponto | Decisão textual |
|-------|----------------|
| Step 3 — cor | **AMARELA** sempre (warning, não erro). É comportamento normal validado. Nunca vermelha. |
| Step 4 — timer "X minutos esperando" | **NÃO mostrar** timer numérico — pode dar falsa impressão de bug ou criar expectativa enganosa. Apenas spinner + texto literal. |
| Step 4 — variação curta | **IF** terminal estreito (< 80 cols) ou status bar Qt **THEN** usar `WAR_99_RECONNECT_SHORT` ("Reconectando... (normal, aguarde)"). Senão, texto longo. |
| Step 5 — bloquear botão CANCELAR | **NÃO bloquear**. H3 (controle do usuário). Mas tooltip warning extra explica risco. Confirmação modal extra se usuário insiste (ver Flow 3 EC4). |
| Step 5 — som | **NÃO tocar som**. Distrai. |
| Step 7 — notificar reconnect | **NÃO mostrar toast** "Reconectado". Voltar ao normal silenciosamente (P7). |
| Step 6 — > 30 min | **IF** reconnect demora > 30 min **THEN** atualizar microcopy para warning escalado: "Reconnect demorando mais que o normal. Considere cancelar e tentar de novo mais tarde." (mas ainda não força cancel). |
| Step 6 — loop reconnect/disconnect | **IF** > 3 ciclos sem progresso real **THEN** erro hard `ERR_DLL_DISCONNECTED` (Flow 1 estado Error). |

### 5 Estados (sub-estados de Flow 1.Loading)

| Estado | Microcopy ID | Ação visual |
|--------|--------------|-------------|
| **Loading.reconnecting** | `WAR_99_RECONNECT` | Barra mantém em 99% (ou % atual, se quirk acontece em outro %) com cor amarela `#F2C94C`; spinner pulsante; banner amarelo overlay com texto literal; botão CANCELAR com tooltip warning. |
| **Loading.resuming** | `INF_FETCHING_CHUNK` (volta ao padrão) | Transição rápida (< 1s); cor volta para ciano; spinner desaparece; banner some. |

### Edge Cases

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Reconnect demora > 30 min | Após 30 min: warning escalado "Reconnect demorando mais que o normal. Considere cancelar e tentar de novo mais tarde." Não força cancel. |
| EC2 | Reconnect e desconecta de novo (loop) | Após 3 ciclos sem progresso real: erro hard `ERR_DLL_DISCONNECTED` (Flow 1 estado Error). |
| EC3 | Usuário cancela durante reconnect | Confirmação extra: Flow 3 EC4 microcopy override. |
| EC4 | Quirk acontece em < 99% (ex: 70%) | Mesmo tratamento — barra mantém posição (não regride), subtitle warning. |
| EC5 | App fechado durante reconnect | Confirmação modal Flow 1 EC12; estado salvo no catalog; `--resume` retoma do último chunk OK. |
| EC6 | Métrica `ui_progress_dropped_count > 0` durante reconnect | Não bloqueia, mas log aumenta — Pyro instrumenta para detectar UI overhead. |
| EC7 | DLL emite reconnect mas `current_contract` muda no mesmo evento (rollover + reconnect simultâneo) | UI atualiza tanto label do contrato quanto subtitle warning; ambos coexistem sem conflito. |

---

## Glossário de Estados

- **Normal**: tela em uso comum, nenhuma operação ativa.
- **Loading**: operação assíncrona em andamento, UI continua responsiva (R11). Pode ter sub-estados (`Loading.reconnecting`, `Loading.cancelling`).
- **Error**: algo falhou; tela mostra microcopy + ação de recuperação.
- **Empty**: sem dados ainda — primeira vez ou filtro sem match. Educativo + CTA.
- **Success**: operação concluída — toast + próximo passo sugerido.

Sub-estados (ex: `Loading.reconnecting`, `Loading.cancelling`) são variações
de um dos 5 principais. Devem ser desenhados quando relevante (ver Flows 3 e 4).

---

## Referências

- PRINCIPLES.md §1 (promessa de produto), §3 P1 (5 estados), §3 P4 (quirk 99%)
- WIREFRAMES.md (telas correspondentes)
- MICROCOPY_CATALOG.md (todos os textos + IDs novos Epic 3 prep)
- THEME.md §6 (atalhos teclado), §3 (mapeamento Rich↔Qt)
- QT_PATTERNS.md (Felix — implementação Signal/Slot, QShortcut, QFileDialog)
- CLI_PATTERNS.md §3 (quirk 99% CLI), §7 (cancelamento CLI)
- ADR-003 + amendment (PySide6 single-process, --onedir, DontUseNativeDialog)
- ADR-007a (DownloadHandle.cancel())
- MANIFEST.md R11 (UI não bloqueia), R17 (microcopy é design)
- COUNCIL-12 (Epic 3 prep sign-off)

---

— Uma, desenhando empatia 🎨
