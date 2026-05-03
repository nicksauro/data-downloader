# FLOWS — Esqueletos de Fluxos Principais

> Fluxos seed para Epic 3 (UI Qt). Placeholders detalhados — Epic 3 vai expandir
> com Felix. Cada flow descreve atores, etapas, decisões, edge cases e os 5
> estados (normal, loading, error, empty, success).

**Versão:** 0.1.0 (seed)
**Data:** 2026-05-03
**Status:** seed (Story 0.3) — refinamento no Epic 3
**Autoridade:** 🎨 Uma — exclusiva sobre fluxos

---

## Convenção de Notação

```
[USUÁRIO] = ação humana
[SISTEMA] = ação automática
[DECISÃO] = ramificação (com critério)
[ERRO] = caminho de erro tratado
{condição} = condição lógica
```

---

## Flow 1 — Baixar Histórico (Golden Path: 1 Clique)

**Cenário:** caso 80% dos usuários — baixar histórico do contrato vigente
do mês corrente. **Promessa de produto inegociável: 1 clique.**

**Atores:**
- 🧑 Usuário
- 🖼️ UI Qt (DownloadScreen)
- 💻 Backend (orchestrator)
- 🗝️ ProfitDLL
- 💾 Storage (Parquet + SQLite catálogo)

**Pré-condições:**
- App instalado e aberto.
- DLL inicializada (Story 1.2 garante).
- Conexão com corretora ativa.

**Etapas:**

1. `[USUÁRIO]` Abre o app.
2. `[SISTEMA]` Carrega DownloadScreen (default screen).
3. `[SISTEMA]` Pré-preenche campos com defaults inteligentes:
   - **Símbolo** = última usada (cache `~/.data-downloader/last_symbol`) OU contrato vigente do WDO.
   - **Período** = "Mês corrente" (preset).
   - **Pasta** = configurada (default `~/data-downloader/data/`).
4. `[SISTEMA]` Mostra estimativa: "Estimativa: ~3-5 minutos" (consultando Pyro baseline).
5. `[USUÁRIO]` Clica em **[BAIXAR HISTÓRICO]**.
6. `[SISTEMA]` Tela transforma para estado **loading**:
   - Campos viram readonly.
   - Aparece barra de progresso + subtitle + log expansível.
   - Botão troca para **[CANCELAR]**.
7. `[SISTEMA]` Backend inicia download em thread separada (R11).
8. `[SISTEMA]` Atualiza progresso a cada chunk (signal Qt → slot UI).
9. `[SISTEMA]` Conclui. Mostra estado **success**:
   - Toast verde 5s: "✓ WDOJ26: 1.234.567 trades em 3 arquivos."
   - Botão "Ver no Catálogo →" no toast.
   - Tela volta ao normal (campos editáveis, botão BAIXAR).

**Decisões:**

| Ponto | Decisão | Critério |
|-------|---------|----------|
| Step 3 | Cache hit vs default | Cache existe em `last_symbol`? Sim: cache. Não: WDO vigente. |
| Step 4 | Mostra estimativa? | Sim, sempre. Banda honesta (3-7 min, não "5 min"). |
| Step 6 | UI bloqueia? | NÃO. Usuário pode navegar para Catálogo durante. |
| Step 8 | Quirk 99% reconnect? | Se DLL emite reconnect: muda subtitle para WAR_99_RECONNECT, cor amarela. |

**5 Estados:**

| Estado | Descrição | Microcopy |
|--------|-----------|-----------|
| **Normal** | Campos preenchidos, botão BAIXAR ativo | "Selecione e clique" implícito |
| **Loading** | Download em andamento, barra/subtitle/log | INF_FETCHING_CHUNK |
| **Error** | DLL falhou ou disco cheio | ERR_DLL_* ou ERR_DISK_FULL + botão "Tentar Novamente" |
| **Empty** | Primeira vez (cache vazio) | EMP_DOWNLOAD_NEW_USER + defaults pré-preenchidos |
| **Success** | Download concluído | SUC_DOWNLOAD_DONE + toast + link catálogo |

**Edge Cases:**

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Símbolo não-vigente digitado | Validação inline + sugestão (ERR_DLL_INVALID_TICKER) |
| EC2 | Período > 30 dias | Warning inline + confirmação (PMT_LARGE_PERIOD_CONFIRM) |
| EC3 | Disco cheio durante write | Erro graceful + parcial preservado (ERR_DISK_FULL) |
| EC4 | DLL desconecta no meio | Auto-retry interno; se falhar, ERR_DLL_DISCONNECTED |
| EC5 | Quirk 99% reconnect | Subtitle amarelo (WAR_99_RECONNECT), barra mantém posição, NÃO cancelar |
| EC6 | Re-baixar período já baixado | Cache hit silencioso (SUC_CACHE_HIT) — sem trabalho duplicado |
| EC7 | Período inclui feriado/weekend sem trades | Continua, marca como vazio no log; ERR_HOLIDAY_NO_TRADES se TODO o range |
| EC8 | Rollover de contrato no meio do período | Detect + download continuous (Story 1.5b) |
| EC9 | Conexão internet cai completamente | ERR_NO_INTERNET + retry button |
| EC10 | App fecha durante download | Confirmação modal "Cancelar download?" |

---

## Flow 2 — Browse Catálogo

**Cenário:** usuário quer ver/gerenciar histórico já baixado.

**Atores:**
- 🧑 Usuário
- 🖼️ UI Qt (CatalogScreen)
- 💾 Storage (SQLite catálogo + filesystem)

**Pré-condições:**
- App aberto.
- Catálogo SQLite existe (criado no primeiro download ou por bootstrap).

**Etapas:**

1. `[USUÁRIO]` Clica em "Catálogo" no nav OU pressiona Ctrl+B.
2. `[SISTEMA]` Carrega CatalogScreen, mostra loading skeleton.
3. `[SISTEMA]` Lê SQLite (DuckDB join Parquet metadata se necessário).
4. `[SISTEMA]` Renderiza tabela:
   - Colunas: Símbolo, Período, Trades, Arquivos, Tamanho, Última Atualização.
   - Ordenação default: Última Atualização desc.
5. `[USUÁRIO]` Pode:
   - **Filtrar** por símbolo (campo busca, Ctrl+F).
   - **Ordenar** clicando em coluna.
   - **Selecionar** item (Enter abre detalhe).
   - **Apagar** item (Delete → confirmação destrutiva).
   - **Validar** item (botão linha → roda validate).
   - **Abrir pasta** (botão linha → Explorer).
6. `[SISTEMA]` Refresh: Ctrl+R recarrega.

**Decisões:**

| Ponto | Decisão | Critério |
|-------|---------|----------|
| Step 4 | Mostrar item se cache drift detectado? | Sim, com warning ⚠ "drift" e CTA "reconciliar" |
| Step 5 (apagar) | Confirmação? | SIM, destrutiva: PMT_DELETE_CONFIRM digitar APAGAR |

**5 Estados:**

| Estado | Descrição | Microcopy |
|--------|-----------|-----------|
| **Normal** | Tabela populada com items | (sem mensagem) |
| **Loading** | Carregando catálogo | "Carregando catálogo..." (skeleton) |
| **Error** | Falha ao ler SQLite/disco | ERR_CATALOG_DRIFT ou ERR_DISK_PERMISSION |
| **Empty** | Catálogo vazio (primeira vez ou tudo apagado) | EMP_CATALOG_FIRST_RUN + CTA |
| **Success** | (não aplicável; tela de browse) | — |

**Edge Cases:**

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Catálogo > 1000 partições | Paginação ou virtual scroll |
| EC2 | Drift detectado (catalog ≠ disco) | Warning inline + CTA reconciliar |
| EC3 | Filtro sem resultado | EMP_CATALOG_FILTERED + botão "Limpar filtros" |
| EC4 | Arquivo corrompido | Indicador ⚠ na linha + tooltip ERR_CORRUPTED_PARQUET |
| EC5 | Outro processo escrevendo (lock) | Read-only mode + warning "Catálogo em uso" |
| EC6 | Apagar enquanto download em progresso do mesmo símbolo | Bloquear apagar, warning "Download em progresso" |

---

## Flow 3 — Cancelar Download em Progresso

**Cenário:** usuário muda de ideia ou notou erro e quer parar download.

**Atores:**
- 🧑 Usuário
- 🖼️ UI Qt (DownloadScreen) ou CLI
- 💻 Backend (orchestrator)
- 💾 Storage (commit parcial)

**Pré-condições:**
- Download em progresso (estado loading).

**Etapas (UI Qt):**

1. `[USUÁRIO]` Clica em **[CANCELAR]** OU pressiona Esc OU Ctrl+C.
2. `[SISTEMA]` Mostra modal de confirmação (não bloqueante visualmente — mas
   modal por destrutividade): PMT_CANCEL_CONFIRM.
3. `[DECISÃO]` Usuário escolhe:
   - **Continuar baixando**: modal fecha, download segue.
   - **Sim, cancelar**: passa para step 4.
4. `[SISTEMA]` Estado **cancelando**:
   - Botão CANCELAR vira "Cancelando..." (disabled).
   - Spinner amarelo.
   - Subtitle: "↻ Drenando fila + commitando parcial..."
5. `[SISTEMA]` Backend: para chunker, drena callback queue, commita parcial,
   atualiza catálogo com partições parciais marcadas.
6. `[SISTEMA]` Conclui cleanup. Mostra estado **success do cancel**:
   - Toast info: "↻ Download cancelado. Parcial salvo: 234.567 trades."
   - Tela volta ao normal.

**Etapas (CLI):**

1. `[USUÁRIO]` Pressiona Ctrl+C.
2. `[SISTEMA]` Captura SIGINT (handler graceful).
3. `[SISTEMA]` Inline prompt: PMT_CANCEL_CONFIRM.
4. `[DECISÃO]`: Sim → continua step 5. Não → retoma.
5. `[SISTEMA]` Mostra "↻ Cancelando..." e drena.
6. `[SISTEMA]` SUC_CANCEL_DONE + exit code 130.

**5 Estados:**

| Estado | Descrição | Microcopy |
|--------|-----------|-----------|
| **Normal** | (n/a — fluxo é transição) | — |
| **Loading (cancelando)** | Drenando fila, commitando parcial | INF_GRACEFUL_SHUTDOWN |
| **Error** | Cleanup falhou (raro) | "Erro ao cancelar limpo. Dados parciais podem estar inconsistentes." + CTA `doctor` |
| **Empty** | (n/a) | — |
| **Success** | Cancelado com parcial preservado | SUC_CANCEL_DONE + retomar com `--resume` |

**Edge Cases:**

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Usuário cancela depois cancela de novo (Ctrl+C 2x) | Force quit, warning "buffer pode estar perdido" |
| EC2 | Cleanup demora > 30s | Toast com botão "Forçar saída" (SIGKILL) |
| EC3 | Disco cheio durante commit parcial | Aviso, parcial pode ficar incompleto, log para reconcile |
| EC4 | Cancelamento durante quirk 99% reconnect | Aviso "Reconnect normal — confirma cancelar?" extra |
| EC5 | Após cancelar, usuário tenta retomar | `--resume` lê catalog parcial, continua do último chunk OK |

---

## Flow 4 — Quirk 99% Reconnect Acontecendo

**Cenário:** download chega em ~99% e a corretora "desconecta" para
re-sincronizar. Comportamento normal validado por Nelo. UI deve informar
sem assustar.

**Atores:**
- 🖼️ UI Qt (DownloadScreen) ou CLI (progress)
- 🗝️ ProfitDLL
- 💻 Backend (orchestrator)
- 🧑 Usuário (observador)

**Pré-condições:**
- Download em progresso (estado loading).
- Chegou em ~99% e DLL emitiu evento de reconnect.

**Etapas:**

1. `[SISTEMA]` Backend recebe sinal `dll.reconnecting` no listener.
2. `[SISTEMA]` Emite signal Qt `progressUpdate(state="reconnecting", percent=99)`.
3. `[SISTEMA]` UI/CLI atualiza:
   - Barra mantém em 99% (NÃO regride).
   - Cor da barra muda de **ciano** para **amarelo**.
   - Spinner ativo aparece ao lado da barra.
   - Subtitle muda para WAR_99_RECONNECT (texto exato): "A corretora está
     reconectando — é normal, aguarde até 30 minutos. Não cancele."
   - Botão CANCELAR ainda visível (usuário pode forçar se quiser, com warning extra).
4. `[USUÁRIO]` Aguarda (ou cancela com warning extra).
5. `[SISTEMA]` Backend recebe `dll.reconnected`.
6. `[SISTEMA]` Emite signal `progressUpdate(state="resuming", percent=99)`.
7. `[SISTEMA]` UI/CLI:
   - Subtitle volta ao normal.
   - Cor da barra volta para ciano.
   - Spinner some.
8. `[SISTEMA]` Download retoma, vai para 100%.
9. `[SISTEMA]` Mostra estado success normal (Flow 1 step 9).

**Decisões:**

| Ponto | Decisão | Critério |
|-------|---------|----------|
| Step 3 | Mostrar timer "X minutos esperando"? | NÃO. Pode dar falsa impressão de bug. Apenas spinner + texto. |
| Step 3 | Bloquear botão CANCELAR? | NÃO. H3 (controle do usuário) — sempre cancelável. Mas warning extra ao tentar. |
| Step 3 | Cor amarela ou vermelha? | AMARELA (warning, não erro). É comportamento normal. |
| Step 3 | Tocar som? | NÃO. Distrai. |
| Step 5 | Notificar reconnect? | Não com toast — apenas voltar ao normal silenciosamente. |

**5 Estados:** (este flow é estado especial dentro do Loading do Flow 1)

| Estado | Descrição | Microcopy |
|--------|-----------|-----------|
| **Loading.reconnecting** | Quirk 99% ativo | WAR_99_RECONNECT |
| **Loading.resuming** | Reconnect concluído, retomando | (transição rápida, sem mensagem específica) |

**Edge Cases:**

| # | Caso | Tratamento |
|---|------|-----------|
| EC1 | Reconnect demora > 30 min | Após 30min: warning "Reconnect demorando mais que o normal. Considere cancelar e tentar de novo mais tarde." (mas sem forçar cancel) |
| EC2 | Reconnect e desconecta de novo (loop) | Após 3 ciclos sem progresso real: erro hard "Conexão instável. ERR_DLL_DISCONNECTED" |
| EC3 | Usuário cancela durante reconnect | Confirmação extra: "A corretora está reconectando — cancelar agora pode forçar re-baixar tudo. Continuar cancelando?" |
| EC4 | Quirk acontece em < 99% (ex: 70%) | Mesmo tratamento — barra mantém posição, subtitle warning |
| EC5 | App fechado durante reconnect | Estado salvo no catalog; `--resume` retoma do último chunk OK |

---

## Glossário de Estados

- **Normal**: tela em uso comum, nenhuma operação ativa.
- **Loading**: operação assíncrona em andamento, UI continua responsiva (R11).
- **Error**: algo falhou; tela mostra microcopy + ação de recuperação.
- **Empty**: sem dados ainda — primeira vez ou filtro sem match. Educativo + CTA.
- **Success**: operação concluída — toast + próximo passo sugerido.

Sub-estados (ex: `Loading.reconnecting`, `Loading.cancelling`) são variações
de um dos 5 principais. Devem ser desenhados quando relevante (ex: Flow 4).

---

## Referências

- PRINCIPLES.md §1 (promessa de produto), §3 P1 (5 estados)
- MICROCOPY_CATALOG.md (todos os textos)
- THEME.md §6 (atalhos teclado)
- CLI_PATTERNS.md §3 (quirk 99%), §7 (cancelamento)
- MANIFEST.md R11 (UI não bloqueia)
- ARCHITECTURE.md (signals Qt entre threads)

---

— Uma, desenhando empatia 🎨
