# COUNCIL-23 — Epic 3 First Real Screen (MainWindow + DownloadScreen)

**Data:** 2026-05-03
**Convocação:** Mini-council Felix + Uma + Aria — modo autônomo (Story 3.1 implementação real)
**Participantes mentais:**
- 🖼️ Felix (Frontend Developer — autoridade exclusiva src/data_downloader/ui/)
- 🎨 Uma (UX/UI Designer — autoridade exclusiva fluxos/wireframes/microcopy R17)
- 🏛️ Aria (Architect — fronteira public_api / ADR-003 / ADR-007a)

**Reviewers (downstream):**
- 🧪 Quinn (QA — pytest-qt headless via offscreen)
- 📋 Morgan (PM — autoriza transição prep → in_progress de Epic 3)

---

## Contexto

COUNCIL-12 fechou o trabalho preparatório de Epic 3 (wireframes detalhados,
microcopy IDs §17b, skeleton placeholders, QSS esqueleto). Story 2.11 fechou
o finding H10 entregando `DownloadHandle.cancel()` real com semântica graceful
(drain + commit parcial + `OperationCancelled` exception pública).

Com H10 real disponível, Felix está UNBLOCKED para implementar a primeira
tela real Epic 3 — substituindo os 14 placeholders por código Qt funcional
que consome `public_api.download()` via `QThread` adapter.

---

## Estratégia

**Implementação real focada na primeira tela funcional, mantendo as outras
duas (Catálogo, Settings) como placeholders mínimos visíveis para preservar
a navegação.**

Stories 3.3 e 3.4 substituirão os placeholders com a implementação real.

Esta story entrega:
1. `app.py` real (não mais `NotImplementedError`).
2. `MainWindow` shell completo (sidebar + stack + status bar + atalhos).
3. `DownloadScreen` com 5 estados via `QStackedWidget` interno.
4. `DownloadAdapter` em `QThread` próprio com sinais tipados Queued.
5. 3 widgets compostos (`SymbolPicker`, `PeriodPicker`, `ProgressCard`).
6. Microcopy 100% catalog-sourced (R17), incluindo §17b Epic 3 IDs.
7. 24 tests pytest-qt headless via `QT_QPA_PLATFORM=offscreen`.

---

## Decisões

### D1 — Signal cross-thread em vez de `QMetaObject.invokeMethod`

**Decidido (Felix):** Despachar `start(...)` para o adapter via signal interno
da DownloadScreen (`_request_start`) conectado ao slot `DownloadAdapter.start`
com `Qt.QueuedConnection`. NÃO usar `QMetaObject.invokeMethod` com `Q_ARG`.

**Razão:**
- `Q_ARG(object, ...)` falha em PySide6 6.11 com erro
  `qArgDataFromPyType: Unable to find a QMetaType for "object"` — Q_ARG
  exige tipos registrados no QMetaSystem (str, int, float, bool, etc).
- Signal cross-thread carrega objetos arbitrários (Path, datetime, etc) sem
  registro, e o Qt faz auto-marshal via QueuedConnection.
- Padrão preferido por idiomática Qt — emitter/receiver decoupling natural.
- Mais testável: spy direto no signal `_request_start` via
  `signal.connect(handler)`.

**Trade-off aceito:**
- Mais signals (1 por método de adapter) em vez de chamadas de método. OK
  porque cada signal tem responsabilidade clara e é documentado.

### D2 — DownloadAdapter SEM parent Qt

**Decidido (Felix):** `DownloadAdapter.__init__(self, parent)` chama
`super().__init__(None)` (sem parent) e armazena o `parent` apenas como
`self._owner` (referência forte para evitar GC).

**Razão:**
- `QObject` com parent não pode ser movido para outra thread (PySide6 levanta
  `QObject::moveToThread: Cannot move objects with a parent`).
- Adapter precisa de `moveToThread(self._thread)` para o slot `start` rodar
  na thread separada.
- Caller (DownloadScreen) já mantém referência via atributo + chama
  `shutdown()` no `closeEvent`.

### D3 — DownloadScreen `closeEvent` chama `_adapter.shutdown()`

**Decidido (Felix + Aria):** Toda subclass de `QWidget` que cria adapter em
QThread DEVE override `closeEvent` para chamar `adapter.shutdown()`.
Garante encerramento limpo da thread (`self._thread.quit() + .wait()`).

**Razão:**
- Sem isso, Qt destrói widget sem terminar thread → `QThread: Destroyed
  while thread is still running` (warning + potencial crash).

### D4 — Texto WAR_99_RECONNECT replicado byte-a-byte em ProgressCard

**Decidido (Uma + Felix):** Texto canônico `WAR_99_RECONNECT` é exposto em
`progress_card.py` como constante module-level `WAR_99_RECONNECT_LITERAL`
e usado no banner. Test verifica `assert pc._reconnect_text.text() ==
WAR_99_RECONNECT_LITERAL` para garantir preservação byte-a-byte.

**Razão:**
- R17 — Uma é autoridade exclusiva sobre microcopy. Texto canônico de quirk
  Q11-99 (MICROCOPY §18) é IMUTÁVEL sem nova autorização Uma + Nelo.
- Constante module-level facilita audit (grep por nome) + teste de
  preservação automatizado.

### D5 — Microcopy IDs Epic 3 adicionados ao `microcopy_loader.MSG`

**Decidido (Uma):** Os ~30 IDs novos de §17b (DownloadScreen + MainWindow
+ toasts/modais) são adicionados ao dict `MSG` em `microcopy_loader.py` com
texto pt-BR replicado de `MICROCOPY_CATALOG.md`. NÃO cria novo módulo.

**Razão:**
- `microcopy_loader` já é a fonte single-source-of-truth (R17). Adicionar
  IDs novos lá mantém um único lugar para audit.
- Catálogo `MSG` agora tem 95 IDs (62 herdados de Story 1.7b + 33 novos
  Epic 3).

### D6 — Catálogo / Settings ficam como placeholders visíveis

**Decidido (Felix + Morgan):** Story 3.1 implementa MainWindow + DownloadScreen
real; Catálogo e Settings ficam como widgets mínimos com label central
"em construção — Story 3.x". Nav funciona (botão alterna stack), mas o
conteúdo é texto.

**Razão:**
- Mantém nav funcional para validar atalhos Ctrl+B / Ctrl+, sem bloquear
  Story 3.1 com escopo de Stories 3.3 e 3.4.
- Wireframes COUNCIL-12 já preveem essas telas; Stories futuras substituem
  os placeholders com implementação fiel.

### D7 — pytest-qt como dep test (NÃO ui)

**Decidido (Felix + Quinn):** `pytest-qt>=4.4` adicionado em
`[project.optional-dependencies].test`, NÃO em `ui`. Razão: testes
sempre podem rodar sem precisar de PySide6 instalado em prod (mas
testes UI exigem `pip install -e .[test,ui]`).

---

## Sign-off

- ✅ **Felix** — implementação Qt fiel aos wireframes Uma; padrões
  QT_PATTERNS respeitados (Signal cross-thread Queued, adapter em QThread,
  `DontUseNativeDialog` em folder picker, layout via QVBoxLayout/QHBoxLayout).
- ✅ **Uma** — microcopy 100% catalog-sourced (R17); WAR_99_RECONNECT
  byte-a-byte preservado; novos IDs §17b incorporados; 5 estados implementados
  conforme WIREFRAMES.md Tela 1.
- ✅ **Aria** — fronteira `public_api` preservada (UI consome apenas
  `data_downloader.public_api.*`, nunca internals); ADR-007a `DownloadHandle.cancel()`
  consumido via adapter; ADR-011 exception hierarchy honrada
  (`OperationCancelled` traduzido em sinal `cancelled` separado de `error`).

---

## Métricas de Entrega

- **Arquivos modificados:** 8 (app, main_window, download_screen, adapter,
  3 widgets, microcopy_loader).
- **Arquivos criados:** 3 (Story 3.1, COUNCIL-23, 2 test files).
- **LoC implementação:** ~1300 (sem testes).
- **LoC testes:** ~330 (24 tests).
- **Microcopy IDs adicionados:** 33 (Epic 3 §17b — DownloadScreen + MainWindow
  + toasts/modais).
- **Tests UI passando:** 24/24 via `QT_QPA_PLATFORM=offscreen`.
- **Ruff:** clean.

---

## Próximos Passos

- Morgan autoriza Epic 3 transição `prep_ready → in_progress`.
- Felix começa Story 3.3 (CatalogScreen) ou Story 3.4 (SettingsScreen).
- Quinn agenda QA gate visual em ambiente Windows real (não offscreen).
- Pyro mede `ui_progress_dropped_count` (M11) durante smoke real (Story 3.8).
- Gage prepara PyInstaller `--onedir` (Story 3.7).

---

— Felix, Uma, Aria 🖼️🎨🏛️
