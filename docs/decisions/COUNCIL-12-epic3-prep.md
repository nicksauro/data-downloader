# COUNCIL-12 — Epic 3 Prep (Wireframes Detalhados + UI Skeleton)

**Data:** 2026-05-03
**Convocação:** Mini-council Uma + Felix + Aria — modo autônomo (Epic 3 prep task)
**Participantes mentais:**
- 🎨 Uma (UX/UI Designer — autoridade exclusiva fluxos/wireframes/microcopy)
- 🖼️ Felix (Frontend Developer — autoridade exclusiva src/data_downloader/ui/)
- 🏛️ Aria (Architect — fronteira public_api / ADR-003 / ADR-007a)

**Reviewers (downstream):**
- 📋 Morgan (PM — priorização Epic 3)
- 🧪 Quinn (QA — validação visual + a11y na execução)
- ⚙️ Gage (DevOps — packaging PyInstaller --onedir)
- ⚡ Pyro (Perf — baselines de estimativa, métrica ui_progress_dropped_count)

---

## Contexto

Epic 3 (Desktop UI PySide6) está **planejado** mas seus artefatos UX
(wireframes, flows) estavam em estado **placeholder/seed** desde Story 0.3.
A versão preliminar cobria os fluxos em alto nível mas faltava:

- Detalhamento Epic-3-ready (atores com responsabilidades exatas, etapas
  com input/ação/microcopy/duração, decisões textuais if/then/else, edge
  cases exaustivos, 5 estados com microcopy + ação visual).
- Wireframes ASCII de **MainWindow** (frame geral) e **SettingsScreen**
  (até então só tinha esqueleto).
- Microcopy IDs específicos das telas Qt (existia catálogo CLI completo +
  IDs gerais, mas não cobria componentes Qt-specific como sidebar nav,
  status bar, drawer Avançado, detail panel, etc.).
- Skeleton `src/data_downloader/ui/` reservando nomes de módulos +
  documentando contratos esperados (até então só `__init__.py` + `microcopy_loader.py`).
- QSS esqueleto aplicando paleta canônica de THEME.md (Felix tinha apenas
  os exemplos inline em THEME.md §3 — sem arquivo QSS criado).

Esta task é **trabalho preparatório** que:
- Reduz lead time Epic 3 em ~3-5 dias (sem precisar parar para detalhar
  flow/wireframe a cada story 3.x).
- Permite Felix começar Story 3.1 com estrutura de módulos pronta,
  contratos documentados e QSS base aplicável.
- Quinn pode validar a11y/visual fidelity contra wireframes detalhados em
  vez de inferir do esqueleto.
- Mantém **rigor R17** (microcopy é design — toda string visível tem ID
  no catálogo antes de implementação).

---

## Estratégia

**Trabalho preparatório agora, implementação real depois (autorização Epic 3).**

Esta convocação **NÃO** abre Epic 3 — apenas adianta artefatos preparatórios:

1. Uma expande `docs/ux/FLOWS.md` e `docs/ux/WIREFRAMES.md` para Epic-3-ready
   (atores com responsabilidades exatas, decisões textuais, edge cases
   exaustivos, 5 estados com microcopy + ação visual).
2. Uma adiciona IDs novos em `MICROCOPY_CATALOG.md §17b` (DownloadScreen,
   CatalogScreen, SettingsScreen, MainWindow/StatusBar, toasts/modais).
3. Felix cria skeleton `src/data_downloader/ui/` (14 arquivos placeholder)
   com docstrings explicando propósito + referências cruzadas.
4. Felix cria `assets/style.qss` esqueleto aplicando paleta de THEME.md.
5. Aria valida que skeleton **não cruza fronteira** (UI nunca importa
   internals do backend — apenas `public_api`).

Implementação real continua reservada para Epic 3 stories 3.1-3.8 após
autorização do Morgan/PO.

---

## Decisões

### D1 — Padrão de navegação: QStackedWidget + sidebar nav

**Decidido (Felix + Uma):**

`MainWindow` usa `QMainWindow` com sidebar `QFrame` esquerda + `QStackedWidget`
central (Download / Catálogo / Settings) + `QStatusBar` inferior.

**Razão:**
- Sidebar nav é convenção forte em apps desktop modernos (VS Code, Discord,
  Slack) — usuário reconhece sem aprender (H6).
- `QStackedWidget` mantém telas em memória → navegação instantânea (sem
  re-render); permite estado preservado durante download em progresso
  (Flow 1 EC8).
- Status bar inferior aproveita real estate sem competir com main area
  (densidade comfortable — PRINCIPLES P8).

**Alternativa rejeitada:** tabs no topo (mais cluttered, menos espaço para
nav adicional Settings/About).

---

### D2 — Theme via QSS centralizado em assets/style.qss

**Decidido (Felix + Uma):**

Tema único `assets/style.qss` carregado em `app.py` via
`app.setStyleSheet(qss_path.read_text(encoding='utf-8'))`. Sem styling
inline (`widget.setStyleSheet(...)` apenas em casos extremos com
comentário justificando — QT_PATTERNS §5).

Property dinâmica (`setProperty("state", "reconnecting") + style.unpolish/polish`)
para state changes (ex: cor da QProgressBar muda automaticamente).

**Razão:**
- Theming central = consistência forte (H4 — mesma cor mesma coisa).
- Light mode V2 (futuro) substitui apenas o arquivo QSS — zero impacto código.
- Fácil auditar contraste WCAG AA (THEME.md §10) — uma única fonte de cores.
- Property dinâmica evita imperative styling em código Python.

**Esqueleto QSS criado** aplica paleta canônica de THEME.md §2 com
seletores para: window, typography, surface/cards, inputs, buttons (primary/
destructive/link), QProgressBar state-aware (normal/reconnecting/cancelling/
complete/error), sidebar nav, status bar, table, toast, error/warning cards,
scrollbar, tooltip.

---

### D3 — 5 estados por tela via QStackedWidget interno

**Decidido (Felix + Uma):**

Cada screen implementa os 5 estados (normal/loading/error/empty/success)
como `QStackedWidget` interno com índices nomeados via ENUM
`ScreenState.NORMAL/LOADING/ERROR/EMPTY/SUCCESS`. Transições fade 200ms
via `QPropertyAnimation` (THEME.md §9).

Sub-estados (Loading.reconnecting, Loading.cancelling) modificam o widget
do estado Loading via property dinâmica (QSS reativa).

**Razão:**
- PRINCIPLES P1: tela sem 5 estados desenhados = bug visual em produção.
  Implementação 1:1 com wireframe (audit-fidelity de Felix garante).
- `QStackedWidget` interno permite swap atômico (sem flicker).
- ENUM nomeado evita índices mágicos.

---

### D4 — Adapters QObject + QThread para todas as chamadas backend

**Decidido (Felix + Aria):**

Toda chamada `data_downloader.public_api.*` passa por adapter
(`ui/adapters/*.py`) vivendo em QThread separada. UI nunca importa
internals (orchestrator, dll, storage). Sinais carregam objetos tipados
(`Signal(object)` carregando `DownloadProgress`/`DownloadResult` —
NUNCA `Signal(dict)`). Conexões cross-thread declaram
`Qt.QueuedConnection` explícito.

**Razão:**
- R11 — UI não bloqueia. MainThread Qt < 16ms por slot.
- ADR-007 — public_api é fronteira firme; UI consome apenas a superfície
  estável (SemVer-governed).
- `Signal(object)` carregando dataclass força import do tipo no slot →
  refactor-safe; `Signal(dict)` aceita qualquer dict → quebra silenciosa
  quando schema muda (finding QT_PATTERNS §2.1).
- `Qt.QueuedConnection` explícito é defesa contra refactor que mova
  adapter para MainThread por engano (resolve para DirectConnection no
  AutoConnection — armadilha).

---

### D5 — Aria não cruza fronteira: skeleton apenas consome public_api

**Validado (Aria):**

Os 14 placeholders de `src/data_downloader/ui/` referenciam apenas:

- `data_downloader.public_api` (download, read, vigent_contract, DownloadHandle/Progress/Result/Status, exceções).
- Tipos da própria UI (QObject, QThread, signals).
- Documentação cruzada (FLOWS.md, WIREFRAMES.md, MICROCOPY_CATALOG.md, THEME.md, QT_PATTERNS.md, ADR-003, ADR-007a).

**NÃO há referência a:**
- `data_downloader.orchestrator.*` (internal)
- `data_downloader.dll.*` (internal — Nelo)
- `data_downloader.storage.*` (internal — Sol)
- `data_downloader.contracts.*` (internal — exposto via vigent_contract)

Adapters são a única camada que faz a ponte UI ↔ public_api. Fronteira
mantida (ADR-007 conformance).

---

### D6 — current_contract em DownloadProgress (M16) reforçado em widgets

**Reafirmado (Felix + Aria + Uma):**

`ProgressCard` exibe label `LBL_CURRENT_CONTRACT` atualizado a cada
`progress` recebido. Necessário para Flow 1 EC3 (rollover de contrato no
meio do período via `download_continuous`) — sem essa label, usuário
pensa que falhou ao ver símbolo inicial pós-rollover (finding M16).

`DownloadProgress` (definida pela Aria no public_api) **deve incluir**
`current_contract: str`. Validação acontece no Epic 3 Story 3.2 quando
Felix começa implementar — se ausente, Felix bloqueia com `*architect-consult`.

---

### D7 — Atalhos: Ctrl+R não F5; Esc context-aware

**Reafirmado (Uma + Felix — finding M10):**

- **Refresh** = `Ctrl+R` (NÃO `F5`). Razão: F5 tem side-effects históricos
  conflitantes (debugger, browser refresh, IDE debug start). Ctrl+R é
  convenção universal em apps desktop modernos (browsers, Discord, Slack,
  VS Code).
- **Esc** é context-aware (THEME §6 — ordem de prioridade): modal aberto
  → fecha modal; drawer aberto → fecha drawer; download em progresso →
  cancela; CatalogScreen com filtro → limpa filtros; senão no-op.
- Implementação via `eventFilter` no MainWindow despachando para handler
  do contexto ativo + `QShortcut(Qt.WidgetWithChildrenShortcut)` por
  tela (não `ApplicationShortcut`).

---

### D8 — DontUseNativeDialog em todos QFileDialog (ADR-003 amendment 2)

**Reafirmado (Felix + Uma — finding M9):**

Todos os `QFileDialog` da UI DEVEM usar `DontUseNativeDialog`. Wrapper
centralizado em `widgets/file_dialog.py` (Felix cria em Story 3.4) para
evitar esquecimento.

**Razão:** dialog nativo Windows ignora QSS — quebra tema escuro do app,
gera flash branco e fontes diferentes. Trade-off: dialog Qt menos polido
mas consistência visual prevalece.

---

### D9 — Microcopy IDs novos em §17b do catálogo

**Validado (Uma autoridade exclusiva R17):**

Adicionados ~70 IDs novos em `MICROCOPY_CATALOG.md §17b` cobrindo:

- §17b.1 DownloadScreen (12 IDs): label tela, current_contract, range
  display, estimativa banda, drawer avançado, navigation hint, footer
  shortcuts, sugestão hint, tooltip cancel reconnect.
- §17b.2 CatalogScreen (~22 IDs): título, loading, footer summary, drift
  indicator, filtros, detail panel headers/labels (folder, schema, dll,
  checksum, row count), botões reconcile/clear/refresh/revalidate, empty
  filtrado, warnings.
- §17b.3 SettingsScreen (~30 IDs): título, headers de seção (DLL/Storage/
  Performance/About), status DLL (connected/disconnected/testing/not_configured),
  labels env vars, storage display, performance display, about display,
  botões (test connection, change dir, integrity check, doctor, save,
  edit env, show/hide secret), empty state DLL primeira execução,
  success toast.
- §17b.4 MainWindow/StatusBar (8 IDs): nav items, status bar DLL status,
  versão app, atalhos, badge nav.
- §17b.5 Toasts e modais novos (8 IDs): reconcile done, delete done,
  test connection ok/fail, modal sair durante download, cheat sheet,
  delete permanent body/hint.

R17 reforçado: nenhum literal hardcoded no skeleton — todos placeholders
referenciam IDs do catálogo nas docstrings.

---

## Sign-off

### 🎨 Uma (UX/UI Designer)

**APPROVED** — wireframes/microcopy/flows.

- 4 fluxos expandidos para Epic-3-ready (atores com responsabilidades
  exatas, etapas com input/ação/microcopy/duração, decisões textuais,
  edge cases exaustivos, 5 estados).
- 4 telas com 5 estados ASCII detalhados (Tela 1 DownloadScreen com
  sub-estados Loading.reconnecting + Loading.cancelling + modal cancel;
  Tela 2 CatalogScreen com 5 estados + empty filtrado + modal delete;
  Tela 3 SettingsScreen 5 estados; MainWindow frame geral).
- Microcopy IDs novos catalogados em §17b — IDs não duplicam, não inventam,
  todos têm pt-BR + reservar slot en-US (V2).
- Quirk Q11-99 reforçado: texto LITERAL `WAR_99_RECONNECT` documentado em
  ProgressCard placeholder + Flow 4 + WIREFRAMES Tela 1 sub-estado.

— Uma, desenhando empatia 🎨

---

### 🖼️ Felix (Frontend Developer)

**APPROVED** — estrutura Qt + QSS esqueleto.

- 14 arquivos placeholder em `src/data_downloader/ui/` com docstrings
  detalhadas explicando propósito + referências (FLOWS, WIREFRAMES,
  MICROCOPY, THEME, QT_PATTERNS, ADR-003, COUNCIL-12).
- Estrutura de pastas conforme ADR-003 §"Padrão arquitetural decorrente":
  app.py, main_window.py, screens/{download,catalog,settings}_screen.py,
  widgets/{symbol_picker,period_picker,progress_card}.py, adapters/
  {download,catalog}_adapter.py, shortcuts.py, assets/style.qss.
- QSS esqueleto cobre 13 seções (base, typography, surface, inputs,
  buttons, progress bar state-aware, sidebar nav, status bar, table,
  toast, error/warning cards, scrollbar, tooltip) aplicando paleta
  canônica de THEME.md §2.
- Padrão Signal/Slot canônico documentado em adapters: Signal(object) +
  Qt.QueuedConnection + adapter QObject em QThread (QT_PATTERNS §2.3).
- DontUseNativeDialog reforçado em SettingsScreen docstring + wrapper
  futuro em widgets/file_dialog.py (Story 3.4).
- Métrica ui_progress_dropped_count (M11) anotada em download_adapter
  docstring para implementação Epic 3.
- shortcuts.py registry centralizado documenta atalhos canônicos lendo
  THEME.md §6 — Felix mantém em sync; mudança = consulta Uma.

— Felix, construindo superfícies 🖼️

---

### 🏛️ Aria (Architect)

**APPROVED** — fronteira backend↔UI mantida.

- Skeleton **não cruza fronteira public_api** (D5 validado): zero imports
  de orchestrator/dll/storage internals.
- Adapter pattern (D4) reforçado: única camada que faz ponte UI →
  public_api. Sinais tipados (Signal(object) carregando dataclasses do
  public_api) — refactor-safe (QT_PATTERNS §2.1).
- M16 (current_contract em DownloadProgress) reafirmado como dependência
  Aria → Felix antes de Story 3.2 começar (D6).
- ADR-003 amendment (--onedir + DontUseNativeDialog) referenciado em
  app.py + WIREFRAMES.md notas implementação + COUNCIL-12 D8.
- ADR-007a (DownloadHandle.cancel()) referenciado em download_adapter.py
  docstring §"Padrão" + QT_PATTERNS §8 — necessário accepted antes de
  Story 3.2 (Felix bloqueia se ainda em draft).
- Constitution Article IV (No Invention) respeitado: estimativas de
  duração nas etapas dos flows são "tipicamente Xs" (não números
  inventados); P9 zero alucinação reforçado em PeriodPicker docstring
  (LBL_ESTIMATE_UNAVAILABLE quando Pyro baseline indisponível).

— Aria 🏛️

---

## Pendências (não bloqueiam esta entrega — bloqueiam Epic 3 começar)

| # | Pendência | Owner | Bloqueia |
|---|-----------|-------|----------|
| P1 | ADR-007a (DownloadHandle.cancel) precisa estar `accepted` | Aria | Story 3.2 |
| P2 | DownloadProgress deve incluir `current_contract: str` | Aria → Dex | Story 3.2 |
| P3 | Pyro baselines para estimativa banda honesta | Pyro | Story 3.2 (LBL_ESTIMATE_RANGE) |
| P4 | PyInstaller spec `--onedir` configurado | Felix + Gage | Story 3.7 |
| P5 | pytest-qt dev dependency adicionada | Quinn | Story 3.6 |

---

## Após esta convocação

- **Não abrir Epic 3** sem autorização Morgan/PO.
- Ao autorizar Epic 3, Stories 3.1-3.8 começam com:
  - Wireframes/flows ready (este COUNCIL).
  - Skeleton estrutural ready (este COUNCIL).
  - QSS base ready (este COUNCIL).
  - Microcopy IDs ready (este COUNCIL).
  - Pendências P1-P5 resolvidas (Aria/Pyro/Gage/Quinn).
- Lead time esperado Epic 3 reduzido em ~3-5 dias graças a este prep.

---

## Referências

- docs/epics/EPIC-3-desktop-ui.md (status: planning → ready, story IDs preliminares)
- docs/ux/FLOWS.md (v0.2.0 Epic 3 prep — 4 flows expandidos)
- docs/ux/WIREFRAMES.md (v0.2.0 Epic 3 prep — 4 telas com 5 estados detalhados)
- docs/ux/MICROCOPY_CATALOG.md §17b (IDs novos Epic 3)
- docs/ux/THEME.md §2 (paleta canônica), §6 (atalhos)
- docs/ux/QT_PATTERNS.md (padrões técnicos Felix)
- docs/ux/PRINCIPLES.md (P1, P4, P9 reforçados)
- docs/adr/ADR-003-front-pyside6.md + amendment (--onedir, DontUseNativeDialog)
- docs/adr/ADR-007 (public_api fronteira)
- src/data_downloader/ui/ (14 arquivos skeleton)

---

— Uma 🎨, Felix 🖼️, Aria 🏛️ — Epic 3 prep completo.
