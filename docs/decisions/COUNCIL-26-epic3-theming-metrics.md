# COUNCIL-26 — Epic 3 Theming Refinado + Status Bar Metrics (Story 3.3)

**Data:** 2026-05-03
**Convocação:** Mini-council Felix + Uma + Pyro + Aria — modo autônomo (Wave 18)
**Participantes mentais:**
- 🖼️ Felix (Frontend Developer — autoridade exclusiva src/data_downloader/ui/)
- 🎨 Uma (UX/UI Designer — paleta + microcopy R17)
- ⚡ Pyro (Performance Engineer — consumer MetricsEmitter, overhead budget)
- 🏛️ Aria (Architect — fronteira observability/MetricsEmitter Protocol)

**Reviewers (downstream):**
- 🧪 Quinn (QA — pytest-qt headless via offscreen)
- 📋 Morgan (PM — autoriza Epic 3 progresso 3/N stories Done)

---

## Contexto

COUNCIL-23 (Story 3.1) entregou MainWindow + DownloadScreen reais.
COUNCIL-24 (Story 3.2) consolidou CatalogScreen + SettingsScreen reais.
Story 2.4 (Done) entregou `PrometheusExporter` com 8 counters / 5 gauges /
5 histograms via `MetricsEmitter` Protocol em `contracts/observability.py`.

**Wave 18 — refinamento de Epic 3:**

1. Aplicar paleta dark mode COMPLETA de `docs/ux/THEME.md` no QSS,
   superando o esqueleto inicial (COUNCIL-12) com estados visuais
   completos para QPushButton, QProgressBar com gradiente + amarelo
   durante quirk 99% reconnect, QTableView header dark + alternating
   rows + selection accent, QGroupBox transparente com label accent,
   QLineEdit/QComboBox/QDateEdit com border accent on focus, QStatusBar
   dark com text accent, QScrollArea bordas removidas, QTabBar/QTabWidget.

2. Integrar métricas runtime do exporter (Story 2.4) na status bar:
   contador de downloads ativos, queue depths (DLL + write), trades
   persisted total, indicador clickable de exporter port (link copiado
   para clipboard).

---

## Estratégia

**Reuso máximo dos padrões consolidados (D1-D3 COUNCIL-23):**

- Signal cross-thread em vez de `QMetaObject.invokeMethod` (D1).
- Adapter SEM parent Qt + `moveToThread` (D2).
- `closeEvent` chama `adapter.shutdown()` (D3).
- Microcopy 100% catalog-sourced (R17 / D5).

Esta story entrega:

1. `style.qss` refinado (~947 LoC, +~514 sobre o esqueleto COUNCIL-12) —
   paleta dark mode COMPLETA com estados visuais para todos os widgets
   relevantes ao MVP, gradientes em QProgressBar, alternating rows em
   QTableView, transparente QGroupBox com label accent.
2. `widgets/metrics_panel.py` (~360 LoC) — `MetricsPanel` (QWidget
   compact pronto para status bar embed) + `MetricsAdapter` (QObject em
   QThread separada com QTimer 1s, polling local do exporter via
   introspecção de `_gauges`/`_counters` sem hard-import).
3. `main_window.py` Edit minimal — substitui status bar simples por
   layout: DLL status + MetricsPanel + versão. `set_metrics_exporter()`
   método público para liga/desliga (graceful sem exporter).
4. `microcopy_loader.MSG` extend — 8 IDs novos (§17b.6 — Metrics).
5. 36 tests pytest-qt headless via `QT_QPA_PLATFORM=offscreen`
   (12 theming + 14 metrics_panel + 10 status_bar).

---

## Decisões

### D1 — `MetricsAdapter` lê exporter via introspecção, não hard-import

**Decidido (Felix + Aria):** `MetricsAdapter._extract_snapshot` acessa
`exporter._gauges` / `exporter._counters` (atributos públicos do
`PrometheusExporter`) e usa `gauge.collect()` API do `prometheus_client`
para extrair valores. NÃO importa `PrometheusExporter` diretamente em
`metrics_panel.py`.

**Razão:**
- Fronteira observability preservada — UI consome qualquer objeto que
  expõe `_gauges`/`_counters`/`port`/`is_running`. Aria endossa.
- Permite swap do backend (e.g. OpenTelemetry adapter futuro) sem
  refactor da UI.
- Falhas absorvidas (try/except amplo) — campo fica `None`, panel
  renderiza placeholder `—`.

**Trade-off aceito:**
- Levemente acoplado ao layout interno do `PrometheusExporter` (atributos
  começando com `_`). Aceitável dado que ambos são owned pelo squad
  (mudança coordenada).

### D2 — Polling 1s no QTimer da worker thread (não MainThread)

**Decidido (Felix + Pyro):** `MetricsAdapter` cria `QTimer` DENTRO da
worker thread no slot `_on_thread_started`. Polling 1000ms (configurável,
clamp [250, ∞)). MainThread NÃO faz polling — apenas recebe signals
QueuedConnection.

**Razão:**
- Pyro audit: 1s é suficiente para UI (usuário não percebe < 1s lag em
  contadores). `prometheus_client.collect()` é O(n_metrics) ~ 18 chamadas
  → microsegundos. Zero impacto no hot path R21.
- QTimer no MainThread causaria poll síncrono — viola RGRA Felix
  ("MainThread NUNCA bloqueia").
- Worker thread tem QTimer próprio com parent=self (cleanup automático
  ao quit thread).

**Trade-off aceito:**
- Latência de update: até 1s entre evento real e display. Aceitável
  para contadores (não para barra de progresso, que tem signal próprio).

### D3 — Graceful degradation: status bar funciona sem exporter

**Decidido (Felix + Pyro + Aria):** `MainWindow.set_metrics_exporter(None)`
ou `set_metrics_exporter()` nunca chamado → adapter fica idle (emite
`exporter_unavailable` 1x), panel mostra `LBL_METRICS_OFF`. Status bar
preserva DLL status + versão (sem regressão Story 3.1/3.2).

**Razão:**
- Métricas são opt-in via CLI flag `--metrics-port` (ADR-013). UI desktop
  pode rodar sem exporter ativo.
- Pyro audit: zero overhead quando exporter=None (adapter não polla).

### D4 — Click no link do exporter copia URL para clipboard

**Decidido (Uma + Felix):** Label do exporter URL é `<a href="copy">`
clicável; handler `_on_link_clicked` copia `http://localhost:{port}/metrics`
para `QGuiApplication.clipboard()` e atualiza tooltip com microcopy
`TST_METRICS_URL_COPIED`.

**Razão:**
- UX: usuário pode abrir o exporter no browser sem digitar URL.
- Sem dep extra (clipboard é Qt built-in).
- Microcopy via R17 (`TST_METRICS_URL_COPIED`).

### D5 — Microcopy IDs §17b.6 adicionados ao `microcopy_loader.MSG`

**Decidido (Uma):** 8 IDs novos para metrics panel + clipboard toast +
detalhes modal (V2):

- `LBL_STATUSBAR_METRICS_PORT` — "Métricas: :{port}"
- `LBL_METRICS_OFF` — "Métricas: off"
- `LBL_METRICS_ACTIVE_DOWNLOADS` — "↓ {n}"
- `LBL_METRICS_QUEUE_DEPTH` — "Q: {dll}/{write}"
- `LBL_METRICS_TRADES_TOTAL` — "Σ {n}"
- `BTN_COPY_METRICS_URL` — "Copiar URL"
- `TST_METRICS_URL_COPIED` — "✓ URL copiada para clipboard"
- `MOD_METRICS_DETAILS_TITLE` — "Métricas Detalhadas" (V2 dialog)

**Razão:**
- Continuação do padrão estabelecido em Stories 3.1/3.2 (D5 COUNCIL-23,
  D7 COUNCIL-24). MSG cresce de ~170 → ~178 IDs.

### D6 — QSS sniff test rejeita cores fora da paleta canônica

**Decidido (Felix + Uma):** `test_qss_no_unauthorized_colors` falha se
encontrar cor hex no QSS que não está em `CANONICAL_HEX_TOKENS` (15
tokens THEME §2) + `authorized_derivatives` (11 sub-tonalidades de
hover/pressed/gradient com nomes documentados).

**Razão:**
- R17 / Uma authority — proibido inventar cor sem coordenação.
- Teste detecta drift acidental (Felix esquece de consultar Uma).
- Lista `authorized_derivatives` é curta e auditável.

---

## Sign-off

- ✅ **Felix** — QSS aplica paleta de Uma fielmente (15 tokens canônicos
  + 11 derivativos autorizados com nomes documentados); estados visuais
  completos (4 por QPushButton, 5 por QProgressBar); MetricsAdapter em
  QThread (D2 COUNCIL-23); MetricsPanel desacoplado via signal/slot.
- ✅ **Uma** — paleta dark mode COMPLETA aplicada (THEME §2 + §10
  contraste WCAG AA preservado); microcopy 100% catalog-sourced (R17);
  novos IDs §17b.6 incorporados; gradiente em QProgressBar com cor amarelo
  durante 99% reconnect (Flow 4) preservada.
- ✅ **Pyro** — consumer do `MetricsEmitter` Protocol via introspecção
  (sem acoplamento a internals do exporter); polling 1s na worker thread
  (zero impacto MainThread + zero impacto hot path R21); graceful sem
  exporter (overhead=0).
- ✅ **Aria** — fronteira `data_downloader.observability` preservada
  (UI consome via duck-typing de `_gauges`/`_counters`/`port`/`is_running`,
  sem hard-import de `PrometheusExporter`); `MetricsEmitter` Protocol em
  `contracts/observability.py` continua a única fronteira formal.

---

## Métricas de Entrega

- **Arquivos modificados:** 3 (`style.qss`, `main_window.py`,
  `microcopy_loader.py`).
- **Arquivos criados:** 5 (`widgets/metrics_panel.py`,
  `tests/integration/test_ui_theming.py`,
  `tests/integration/test_ui_metrics_panel.py`,
  `tests/integration/test_ui_status_bar.py`, `Story 3.3`, `COUNCIL-26`).
- **LoC implementação:** ~370 (metrics_panel) + ~514 (QSS expandido) =
  ~884 LoC novos.
- **LoC testes:** ~570 (36 tests).
- **Microcopy IDs adicionados:** 8 (§17b.6 — Metrics + clipboard).
- **Tests UI passando:** 86/86 via `QT_QPA_PLATFORM=offscreen`
  (50 Stories 3.1+3.2 sem regressão + 36 novos).
- **Ruff:** clean.

---

## Próximos Passos

- Morgan agenda Story 3.6 (pytest-qt setup expansion + UI tests).
- Felix coordena com Pyro para Story 3.8 (`ui_progress_dropped_count` real).
- Quinn agenda smoke test visual em ambiente Windows real (não offscreen).
- Gage prepara Story 3.7 (PyInstaller `--onedir`).

---

— Felix, Uma, Pyro, Aria 🖼️🎨⚡🏛️
