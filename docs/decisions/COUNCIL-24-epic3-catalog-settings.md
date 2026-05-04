# COUNCIL-24 — Epic 3 CatalogScreen + SettingsScreen (Story 3.2)

**Data:** 2026-05-03
**Convocação:** Mini-council Felix + Uma + Aria — modo autônomo (Story 3.2 implementação real)
**Participantes mentais:**
- 🖼️ Felix (Frontend Developer — autoridade exclusiva src/data_downloader/ui/)
- 🎨 Uma (UX/UI Designer — autoridade exclusiva fluxos/wireframes/microcopy R17)
- 🏛️ Aria (Architect — fronteira public_api / ADR-003 / ADR-007a)

**Reviewers (downstream):**
- 🧪 Quinn (QA — pytest-qt headless via offscreen)
- 📋 Morgan (PM — autoriza Stories 3.3 e 3.4 condensadas em 3.2)

---

## Contexto

COUNCIL-23 fechou Story 3.1 entregando MainWindow + DownloadScreen funcionais.
Catalog/Settings ficaram como placeholders visíveis (D6 do COUNCIL-23) para
manter nav funcional sem bloquear MVP.

Story 3.2 substitui esses placeholders com implementações reais:

- **CatalogScreen:** browse de partições, 5 estados, filtros client-side
  via `QSortFilterProxyModel`, ações ABRIR PASTA / RE-VALIDAR / APAGAR
  com confirmação destrutiva (R17 — `MOD_DELETE_PERMANENT_*`).
- **SettingsScreen:** 4 seções (DLL/Storage/Performance/About) em
  `QScrollArea`, persistência em `~/.data_downloader/config.toml` (ADR-012),
  test connection com QTimer.singleShot defer.

Esta story consolida o que estava planejado para Stories 3.3 (Catálogo)
e 3.4 (Settings) do EPIC-3 plan.

---

## Estratégia

**Reuso máximo dos padrões consolidados em COUNCIL-23 (D1-D4).**

Nenhuma decisão arquitetural nova — apenas aplicação consistente:

1. Signals cross-thread em vez de `QMetaObject.invokeMethod` (D1).
2. Adapters sem parent Qt + `moveToThread` (D2).
3. `closeEvent` chama `adapter.shutdown()` (D3).
4. Microcopy 100% catalog-sourced — nenhuma string inventada (D4 / R17).

Esta story entrega:

1. `catalog_adapter.py` real (~280 LoC) — `list_partitions`,
   `delete_partition`, `revalidate_checksum`, `reconcile`.
2. `catalog_screen.py` real (~620 LoC) — `QTableView` + `QSortFilterProxyModel`
   + 5 estados via `QStackedWidget` interno, modal delete destrutivo.
3. `settings_screen.py` real (~570 LoC) — 4 seções `QGroupBox` em
   `QScrollArea`, persistência TOML, test connection com graceful fallback.
4. `microcopy_loader.py` extend — ~75 IDs novos (CatalogScreen +
   SettingsScreen + toasts).
5. `main_window.py` Edit minimal — substitui placeholders por screens
   reais + cross-screen wiring (Settings → Catalog data_dir change;
   Settings → MainWindow statusbar DLL status).
6. 26 tests pytest-qt headless via `QT_QPA_PLATFORM=offscreen` (13
   catalog + 13 settings).

---

## Decisões

### D1 — `PartitionTableModel` custom em vez de `QStandardItemModel`

**Decidido (Felix):** Implementar subclasse de `QAbstractTableModel` que
recebe `tuple[Partition, ...]` direto, em vez de copiar para
`QStandardItemModel` célula-a-célula.

**Razão:**
- Performance: para >1000 partições, copy célula-a-célula adiciona overhead
  desnecessário (`QStandardItemModel` aloca `QStandardItem` por célula).
- `QAbstractTableModel` permite acesso à `Partition` original via
  `partition_at(row)` — útil para detail panel e ações (delete usa
  `partition_path` direto).
- Formatação delegada ao próprio modelo (`data()` retorna string
  formatada por coluna) — DRY.

**Trade-off aceito:**
- Mais boilerplate (override de `rowCount`/`columnCount`/`data`/`headerData`).
  Aceitável dado que a interface é estável.

### D2 — `QSortFilterProxyModel` subclass para filtros multi-critério

**Decidido (Felix):** `_PartitionFilterProxy` override `filterAcceptsRow`
para combinar filtro por símbolo (substring) + exchange (==).

**Razão:**
- `setFilterFixedString` aceita só 1 critério; precisamos de 2 simultâneos.
- Custom permite case-insensitive uppercase comparison sem regex.
- API explícita: `proxy.set_filter(symbol, exchange)` — testável.

### D3 — `auto_reconcile=False` no `Catalog` aberto pelo adapter

**Decidido (Felix + Aria):** `CatalogAdapter._open_catalog` instancia
`Catalog(auto_reconcile=False, auto_cleanup_orphans=False)` — UI controla
reconcile explicitamente via botão Reconciliar.

**Razão:**
- Reconcile pode ser caro (varre `data_dir/history/**`); rodar a cada
  `list_partitions` é desperdício.
- Cleanup_orphans em UI seria invasivo — usuário não espera apagar arquivos
  ao abrir Settings.
- `Catalog.reconcile(auto_correct=True)` continua disponível via slot
  dedicado (`_request_reconcile`).

### D4 — Persistência Settings em `~/.data_downloader/config.toml` (TOML manual)

**Decidido (Felix):** Escrita TOML manual em `_write_config` — sem dep
adicional (`tomli_w`) — em ~5 linhas de código.

**Razão:**
- Apenas 2 chaves (`dll_path`, `data_dir`); TOML simples não justifica
  `tomli_w`.
- Reduz superfície de deps do projeto (já temos pyarrow, duckdb, sqlite3 —
  evitar mais).
- Format alinha com ADR-012 (config.toml é a convenção do projeto).
- Env vars NUNCA persistidas em TOML (segurança) — usuário edita `.env`
  diretamente.

**Trade-off aceito:**
- Sem escape robusto (apenas backslash + aspas); ok para 2 paths.

### D5 — Test connection com graceful fallback (ambiente sem DLL)

**Decidido (Felix + Aria):** `_do_test_connection` envolve `open_session`
em `try/except Exception` amplo — em ambiente sem DLL (Linux/CI), retorna
falha rapidamente sem stack trace assustador.

**Razão:**
- DLL é Windows-only; testes pytest-qt rodam offscreen Linux/Windows.
- `try/except Exception` aqui é OK porque a UI mostra microcopy humanizada
  (`TST_TEST_CONNECTION_FAIL`) e o detalhe técnico vai para `_dll_empty_hint`
  apenas se houver mensagem.

### D6 — Cross-screen signals em vez de import circular

**Decidido (Felix):** `MainWindow._build_screens` conecta:
- `settings_screen.data_dir_changed → catalog_screen.set_data_dir`
- `settings_screen.dll_status_changed → main_window._on_dll_status_changed`

**Razão:**
- Settings não importa Catalog (e vice-versa) — comunicação via signals
  pelo MainWindow elimina acoplamento.
- Padrão idiomático Qt — telas são plug-and-play.

### D7 — Microcopy IDs Epic 3.2 adicionados ao `microcopy_loader.MSG`

**Decidido (Uma):** ~75 IDs novos para CatalogScreen + SettingsScreen
adicionados ao dict `MSG` em `microcopy_loader.py` com texto pt-BR
replicado de `MICROCOPY_CATALOG.md` §17b.2 e §17b.3.

**Razão:**
- Continuação do padrão estabelecido em Story 3.1 (D5 COUNCIL-23).
- Catálogo `MSG` agora cresce de 95 → ~170 IDs (consolidação do prep
  COUNCIL-12).
- Audit centralizado: `grep MSG_ID_NOT_FOUND` em runtime detecta IDs
  faltantes.

---

## Sign-off

- ✅ **Felix** — implementação Qt fiel aos wireframes Uma; padrões
  QT_PATTERNS respeitados (Signal cross-thread Queued, adapter em QThread,
  `DontUseNativeDialog` em folder picker, `QSortFilterProxyModel` para
  filtros client-side, `QAbstractTableModel` custom para perf).
- ✅ **Uma** — microcopy 100% catalog-sourced (R17); 5 estados
  implementados conforme WIREFRAMES.md Tela 2 e Tela 3; modal destrutivo
  com microcopy `MOD_DELETE_PERMANENT_*`.
- ✅ **Aria** — fronteira `public_api` preservada (UI consome apenas
  `data_downloader.public_api.*` + `Catalog` que é parte de storage
  publicado para UI). `CatalogAdapter` chama `Catalog` via APIs públicas
  do storage; nenhum import de `_internal/`.

---

## Métricas de Entrega

- **Arquivos modificados:** 4 (microcopy_loader, main_window,
  catalog_adapter, settings_screen).
- **Arquivos criados:** 5 (catalog_screen real, COUNCIL-24, Story 3.2,
  2 test files).
- **LoC implementação:** ~1470 (sem testes).
- **LoC testes:** ~430 (26 tests).
- **Microcopy IDs adicionados:** ~75 (Epic 3 §17b.2 + §17b.3 +
  delete/reconcile/validate toasts).
- **Tests UI passando:** 50/50 via `QT_QPA_PLATFORM=offscreen` (24 da
  Story 3.1 + 26 da Story 3.2 — sem regressão).
- **Ruff:** clean.

---

## Próximos Passos

- Morgan agenda Story 3.5 (Theming refinado / light mode).
- Felix coordena com Pyro para Story 3.8 (`ui_progress_dropped_count` +
  `current_contract` métricas reais).
- Quinn agenda smoke test visual em ambiente Windows real (não offscreen).
- Gage prepara Story 3.7 (PyInstaller `--onedir`).

---

— Felix, Uma, Aria 🖼️🎨🏛️
