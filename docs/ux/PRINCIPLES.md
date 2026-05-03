# PRINCIPLES — UX/UI do data-downloader

> Princípios inegociáveis da experiência. Toda decisão de tela, fluxo, microcopy
> ou theme cita pelo menos um princípio aqui ou uma heurística de Nielsen.
> Decisão sem citação = palpite, e palpite é vetado por Uma.

**Versão:** 1.0.0
**Data:** 2026-05-03
**Status:** ratificado (Story 0.3)
**Autoridade:** 🎨 Uma (UX/UI Designer) — exclusiva

---

## 1. Promessa de Produto (P0 — Inegociável)

> **"Selecionar símbolo + período + clicar 1 botão + aguardar."**
> — MANIFEST §1

Esta promessa é **não-negociável**. Toda funcionalidade que adiciona fricção ao
caminho comum (caso 80% dos usuários: baixar histórico do contrato vigente do
mês corrente) é vetada e re-desenhada.

### Métrica operacional

| Métrica | Alvo | Falha = |
|---------|------|---------|
| Cliques no caso comum (golden path) | **1** (apenas botão BAIXAR) | Re-desenho obrigatório |
| Inputs requeridos no caso comum | **0** (defaults inteligentes preenchem tudo) | Adicionar default |
| Tempo até primeira interação útil (cold start) | < 3s | Otimização Pyro + UX |
| Modais bloqueantes em fluxo principal | **0** (exceto confirmação destrutiva) | Refatorar para drawer/inline |

### O que conta como "1 clique"

- Defaults preenchidos (símbolo = contrato vigente sugerido; período = mês corrente).
- Usuário pode mudar antes de clicar — mas **não precisa**.
- Botão grande, primário, posição estável (canto inferior direito ou centro).

### O que NÃO conta como "1 clique"

- Wizard multi-step com "Next > Next > Confirm".
- Login obrigatório antes de cada download (sessão é persistida).
- Confirmação "Tem certeza?" para operação não-destrutiva.

---

## 2. As 10 Heurísticas de Nielsen — Aplicadas ao data-downloader

### H1 — Visibilidade do Status do Sistema

> O sistema deve sempre informar o usuário sobre o que está acontecendo.

**Aplicação:** durante download (operação longa, 30s-30min), UI mostra
**continuamente**:
- Barra de progresso percentual (chunks processados / total).
- Subtitle textual ("Baixando WDOJ26 — chunk 12 de 30").
- Tempo estimado ("Aproximadamente 4 minutos restantes").
- Quirk 99% reconnect: texto explícito ("A corretora está reconectando — é normal").

**Antipattern:** modal "Carregando..." sem progresso, ou silêncio por 5 minutos
seguido de "Concluído!".

### H2 — Correspondência entre Sistema e Mundo Real

> Falar a língua do usuário, não a do sistema.

**Aplicação:** termos do trader, não do programador.
- "Símbolo" (não "ticker_id"), "Período" (não "date_range"), "Pasta" (não "directory").
- Erro NL_INVALID_TICKER vira "WDOFUT não é um contrato vigente. Quer usar WDOJ26?".
- Quantidades: "1.2 milhões de trades em 3 arquivos" (não "1234567 rows in 3 files").

**Antipattern:** mostrar `NL_NOT_INITIALIZED` direto pro usuário. Erros de
sistema são traduzidos por Uma (ver MICROCOPY_CATALOG.md).

### H3 — Controle e Liberdade do Usuário

> Saídas de emergência claras. Cancelar, desfazer, voltar.

**Aplicação:**
- Botão **CANCELAR** sempre visível durante download.
- Ctrl+C na CLI cancela com graceful shutdown (drena fila + commita parcial).
- Esc na UI Qt fecha modal aberto, ou cancela download na DownloadScreen.
- Re-baixar período já baixado é seguro (idempotência + cache hit silencioso).

**Antipattern:** modal sem X, download sem botão Cancelar, "operação iniciada,
não pode parar".

### H4 — Consistência e Padrões

> Mesma palavra, mesma cor, mesmo lugar = mesma coisa.

**Aplicação:**
- Vermelho = erro/destrutivo SEMPRE; verde = sucesso SEMPRE; ciano = link/foco SEMPRE.
- Botão primário sempre canto inferior direito (Qt) ou única ação na linha (CLI).
- "Baixar Histórico" é o verbo — nunca "Download", "Get Data", "Fetch".
- Atalhos consistentes entre CLI e Qt (Ctrl+D download, Ctrl+B browse).

**Antipattern:** "Salvar" em uma tela, "Gravar" em outra; verde em um lugar
significando "sucesso", em outro "ativo".

### H5 — Prevenção de Erros

> Validar antes do envio. Confirmar antes de destruir.

**Aplicação:**
- Símbolo inválido detectado **antes** de chamar DLL: autocomplete só sugere
  contratos vigentes válidos.
- Período > 30 dias: aviso inline "vai fazer N chunks, ~X minutos" antes do
  start (não bloqueia, informa).
- "Apagar histórico baixado" exige confirmação modal com texto exato
  ("Digite APAGAR para confirmar"). Outros não.

**Antipattern:** botão "Deletar tudo" sem confirmação; chamar DLL com input
inválido só pra mostrar erro depois.

### H6 — Reconhecer em vez de Lembrar

> Opções visíveis. Usuário não decora; reconhece.

**Aplicação:**
- Autocomplete de símbolos com contrato vigente em destaque
  ("**WDOJ26** (vigente até 28/03/2026)").
- Dropdown de período com presets nomeados (Hoje, Ontem, Esta semana, Mês
  corrente, Mês anterior, Customizado).
- Catálogo lista downloads anteriores com filtros pré-construídos
  (por símbolo, por mês).

**Antipattern:** campo livre exigindo "ex: digite WDO + letra do mês + 2
dígitos do ano"; usuário tem que decorar mapa J/K/M/N/Q/U/V/X/Z/F/G/H.

### H7 — Flexibilidade e Eficiência

> Defaults para iniciantes. Atalhos para avançados.

**Aplicação:**
- Caso comum: 1 clique sem mexer em nada.
- Caso avançado: atalhos de teclado (Ctrl+D direto download), CLI puro
  (`data-downloader download --symbol WDOJ26`), drawer de configurações
  (chunk size, retry policy).
- "Repetir último download" via Ctrl+R ou comando CLI `data-downloader repeat`.

**Antipattern:** UI única para todos — ou trivial demais para o avançado, ou
intimidante demais para o novato.

### H8 — Design Estético e Minimalista

> Mostrar o que importa. Esconder o resto.

**Aplicação:**
- Tela Download: 3 campos visíveis (Símbolo, Período, Botão). Restante em drawer
  "Avançado" (chunk size, retry, validação).
- Catálogo: lista compacta com colunas essenciais (símbolo, período, tamanho,
  data); detalhe em painel lateral ou expand.
- Logs técnicos em painel expansível (clique em "Detalhes"), nunca padrão visível.

**Antipattern:** dashboard com 47 widgets, cada um piscando uma métrica diferente.

### H9 — Ajudar a Reconhecer, Diagnosticar e Recuperar de Erros

> Mensagens claras. Sugestões de ação. Sem códigos crípticos.

**Aplicação:** toda mensagem de erro segue o template:

```
[ÍCONE ✗] [TÍTULO HUMANO]
[O QUE ACONTECEU em 1 frase]
[O QUE O USUÁRIO PODE FAZER em 1 frase imperativa]
[opcional: link "Mais detalhes" para log técnico]
```

Exemplo:

```
✗ Não conectei à ProfitDLL
A chave de licença pode estar inválida ou expirada.
Verifique a chave em Configurações > DLL e clique em Testar.
[Mais detalhes...]
```

**Antipattern:** "Error: NL_NOT_INITIALIZED (-2147483635)".

### H10 — Ajuda e Documentação Contextual

> Documentação encontrada onde é precisa.

**Aplicação:**
- Tooltips em ícones-only (botões com apenas glifo).
- Help inline em campos complexos (chunk size: tooltip "padrão: 30 dias; menor =
  retry mais rápido em falhas, maior = menos overhead").
- `--help` na CLI com exemplos práticos, não só sumário de flags.
- Erro tem link "Mais detalhes" → abre log filtrado pela ocorrência.

**Antipattern:** documentação só no README do GitHub, separada do produto.

---

## 3. Princípios Próprios do Squad

### P1 — Golden Path + Edge Cases + 5 Estados (R17 reforçado)

Toda tela é desenhada com:

1. **Normal/Golden** — caso comum, 80% dos usuários.
2. **Loading** — operação em andamento, com progresso honesto.
3. **Error** — algo falhou, com microcopy clara + ação sugerida.
4. **Empty** — primeira vez, sem dados ainda — educativo + CTA.
5. **Success** — operação concluída, celebrada silenciosamente.

**Tela sem 5 estados desenhados = bug visual em produção.** Felix não
implementa tela aprovada por Uma sem os 5 estados.

### P2 — Microcopy é Design (R17)

Toda mensagem ao usuário responde:

- **(a) O que aconteceu** — fato em linguagem humana, sem jargão técnico.
- **(b) O que o usuário pode fazer agora** — ação imperativa, concreta.

Uma tem **autoridade exclusiva** sobre microcopy. Felix/Dex não inventam texto
em runtime — consultam MICROCOPY_CATALOG.md ou pedem entrada para Uma.

### P3 — UI Nunca Bloqueia (R11)

Download é tarefa longa (30s-30min). UI continua responsiva durante:

- Usuário pode cancelar a qualquer momento.
- Usuário pode navegar para Catálogo ver downloads anteriores.
- Usuário pode iniciar segundo download em paralelo (multi-symbol).
- Modais bloqueantes **só** para confirmação destrutiva (apagar histórico).

**Antipattern:** `QApplication.processEvents()` chamado em loop, ou modal de
"Carregando..." que congela o resto.

### P4 — Progresso Honesto (incluindo o quirk 99%)

Quirk validado por Nelo: a corretora frequentemente "desconecta" ao chegar em
~99% e demora 1-30 minutos pra reconectar. **Isso é normal**, não é erro.

UI deve dizer textualmente:

> "Quase lá — a corretora está reconectando. É normal demorar até 30 minutos.
> Não cancele."

Esconder isso (ex: fingir que travou em 99%) **mente para o usuário** e gera
medo (cancelar e refazer = duplicação, frustração). Vetado.

### P5 — Defaults Inteligentes

- Símbolo: contrato vigente do ativo mais usado (cache local da última escolha).
- Período: mês corrente do contrato vigente.
- Pasta: `~/data-downloader/data/` (criada automaticamente, sem perguntar).
- Chunk size: 30 dias (escondido em drawer "Avançado").

Default = caminho de menor surpresa. Usuário muda se quiser, mas não precisa.

### P6 — Empty State Educativo

Catálogo vazio nunca é literalmente vazio. É:

```
[ilustração simples]
"Você ainda não baixou nenhum histórico."
"Clique em Baixar Histórico para começar."
[BAIXAR HISTÓRICO]  ← botão primário
```

Vale para qualquer lista (filtros sem resultado, busca sem match): sempre
explica o que está faltando + sugere ação.

### P7 — Sucesso Silencioso e Celebrado

Sucesso não interrompe — comunica. Toast verde ~5s, dismissable:

```
✓ WDOJ26: 1.2M trades em 3 arquivos.
[Ver no Catálogo →]
```

**Antipattern:** modal "Sucesso! Clique OK". Modal de sucesso é punição por
acertar.

### P8 — Density Comfortable por Default

Telas têm respiro. Fonte 14px, espaçamento múltiplo de 4px (ver THEME.md).
Modo "Compacto" opcional para usuários avançados que querem mais densidade.

### P9 — Zero Alucinação de Comportamento

Uma **não inventa** quanto tempo demora um download — consulta Pyro
(perf-engineer) para baseline. Estimativa mostrada como banda honesta:

> "Estimativa: 3-7 minutos (baseado em downloads anteriores deste tamanho)"

Não:

> "Estimativa: 4 minutos" ← falsa precisão

---

## 4. Acessibilidade

### NO_COLOR (CLI)

CLI respeita variável de ambiente `NO_COLOR` (https://no-color.org/). Quando
setada (qualquer valor), Rich desativa cores e usa apenas texto.

**Implementação:** `Console(no_color=os.environ.get('NO_COLOR') is not None)`.

### Fallback ASCII

Em terminais Windows antigos (cmd.exe sem suporte UTF-8) ou quando
`PYTHONIOENCODING != utf-8`, símbolos Unicode (✓ ✗ ⚠ ↻) são substituídos por
ASCII equivalente: `[OK] [X] [!] [~]`. Detecção automática + flag manual
`--ascii-only`.

Mapeamento canônico em THEME.md §5.

### Contraste WCAG AA

Toda combinação foreground/background na UI Qt e CLI Rich respeita contraste
mínimo **4.5:1** para texto normal, **3:1** para texto grande (>=18px ou bold
14px). Auditado por Uma via `*audit-screen`.

### Atalhos de Teclado

CLI:
- **Ctrl+C** — cancelar download em progresso (graceful: drena fila, commita
  parcial, mostra resumo).

UI Qt (ver THEME.md §6 para tabela completa):
- **Ctrl+D** — focar na tela Download / iniciar download se já configurado.
- **Ctrl+B** — focar na tela Catálogo (Browse).
- **Ctrl+R** — refresh contextual (NÃO F5 — F5 tem side-effects históricos
  em outras ferramentas).
- **Esc** — context-aware: fecha dialog se aberto; senão, cancela download na
  DownloadScreen; senão, no-op.
- **F1** — Ajuda contextual (futuro).
- **Tab** / **Shift+Tab** — navegação entre campos com foco visível.

### Foco Teclado Visível

Toda tela tem ordem de foco lógica. Estado de foco visualmente distinto
(borda ciano 2px ou anel de foco, NUNCA `outline: none` sem substituto).

### Tooltips Descritivos

Botões com apenas ícone (sem texto) **devem** ter tooltip. Tooltip não
duplica label visível — adiciona contexto (atalho de teclado, descrição
detalhada).

### Labels Associados

Inputs sempre têm label associado (`QLabel.setBuddy(input)`). Screen readers
funcionam por padrão.

---

## 5. Hierarquia de Decisão

Quando dois princípios entram em conflito:

1. **Promessa de produto (§1)** vence tudo.
2. **Heurísticas de Nielsen (§2)** vencem princípios próprios.
3. **Acessibilidade (§4)** vence estética.
4. Em empate: Uma decide e documenta o porquê em ADR ou comentário no doc.

---

## 6. Referências

- Nielsen Norman Group — 10 Usability Heuristics.
  https://www.nngroup.com/articles/ten-usability-heuristics/
- WCAG 2.1 — Web Content Accessibility Guidelines.
  https://www.w3.org/WAI/WCAG21/quickref/
- NO_COLOR convention — https://no-color.org/
- MANIFEST.md §1 (promessa de produto), R11 (UI não bloqueia), R17 (microcopy é design).
- ROLES.md (autoridade Uma sobre UX).

---

— Uma, desenhando empatia 🎨
