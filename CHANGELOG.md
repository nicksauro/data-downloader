# Changelog

Todas as mudanças notáveis do projeto `data-downloader` são documentadas
neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [Semantic Versioning 2.0](https://semver.org/lang/pt-BR/).

Este arquivo documenta **dois eixos de versão** independentes:

1. **Package version (`data_downloader.__version__`)** — rastreia o pacote
   inteiro (CLI, UI, build, internals). Histórico em
   `## [<versão>]` abaixo (ex.: `[1.1.0]`).
2. **Public API version (`__api_version__`)** — fronteira
   SemVer-estrita `data_downloader.public_api`. Política de deprecação
   formal em
   [`docs/public_api/DEPRECATION_POLICY.md`](docs/public_api/DEPRECATION_POLICY.md).
   Histórico em `## [API v<versão>]` abaixo (ex.: `[API v1.0.0]`).

Os dois eixos podem evoluir em ritmos distintos: bumps de package não
implicam bumps de API, e vice-versa.

---

## [1.2.0] — 2026-05-12

> **Download robusto + períodos extensos.** BIG COUNCIL round 3 (6 agentes).
> Foco: a ProfitDLL passa a traduzir ~100% dos trades; resume funcional;
> baixar desde 2018; UX para downloads longos; remoção de dead-code.

### Corrigido (Fixed)

- **`translate_failures` ≈ 0 — a ProfitDLL não perdia mais trades** (Q-DRIFT-40,
  Story 4.20). O callback V2 de trade histórico só enfileirava o `handle`
  (`a_pTrade: Pointer`) e o `TranslateTrade` era feito depois no IngestorThread —
  mas o handle só é válido **dentro do escopo do callback** (a DLL recicla o
  buffer interno do pacote). Com milhões de trades enfileirados, ~0.01% dos
  handles ficavam stale → `ConnectorMarketDataLibraryU.PopulateTradeV0` lia
  memória liberada → access violation interna da DLL (SILENT MODE) → trade
  perdido. Fix: o callback agora chama `TranslateTrade` **dentro do escopo**
  (padrão do exemplo Nelogica) e enfileira o `TradeFields` já copiado, não o
  handle. R3/ADR-005 emendado (callback V2 de trade pode chamar `TranslateTrade`
  — ~µs, não bloqueia a ConnectorThread; demais callbacks seguem `put_nowait`
  only). Cinto-e-suspensório: retry do chunk se `completeness_pct < 99.99%`
  (máx. 2); métrica `download_chunk_completeness_pct` exportada.
- **Download de períodos extensos não abortava mais em mês movimentado.** O
  `ParquetWriter` levantava `IntegrityError` quando o parquet mensal passava de
  5M linhas — um mês de WDOFUT (~10-13M trades) abortava o job por volta do 10º
  dia útil. Paliativo: `_PARTITION_ROW_LIMIT` 5M → 50M (a solução definitiva,
  parquet-por-dia / ADR-025, fica para a v1.2.1 — ver `docs/qa/V1.2.0-PLAN.md`).
- **Resume silencioso de dados corrigido.** O catálogo registrava partições por
  **mês**, mas os chunks são **diários** (ADR-023): se um mês caía no dia 12, o
  mês inteiro contava como "completo" e os outros ~21 dias **não eram baixados**.
  Fix: nova tabela `chunk_ledger` (1 row por dia útil baixado, status
  `completed`/`no_trades`/`failed`); `CATALOG_VERSION` 1.1.0 → 1.2.0 (migração
  automática). `resume`/cache-hit/fresh-skip passam a operar em granularidade
  diária — re-baixar só o que falta de verdade.
- **Multi-symbol footgun removido.** `download SYM1 SYM2 -p N>1` usava um
  *mock factory* por default → gravava parquet com **dados falsos** silenciosamente.
  Agora `-p N>1` é deprecado (licença Nelogica é single-session, ADR-022) →
  cai no loop sequencial single-symbol com aviso. O dead-code do broker
  (`orchestrator/broker/`, ~2034 LOC + 4 test files) foi removido.
- **`busy_timeout=5000`** no perfil SQLite — `wal_checkpoint(TRUNCATE)` (por
  `register_partition`) não falha mais com `database is locked` quando a UI tem
  uma read-tx aberta.
- **`get_pending_chunks`**: `WHERE job_id=? OR (...)` → `UNION` de dois SELECTs
  indexados (+ `idx_partitions_job`) — não vira mais full scan no resume query.
- Gate: `test_smoke_imports::test_root_package_exposes_version` agora deriva da
  fonte (`_PACKAGE_VERSION`) em vez de enrijecer o literal — não regride a cada
  bump de versão. `ruff` UP047 (PEP-695) adicionado ao `ignore` (migração
  diferida para v1.3.0).

### Adicionado (Added)

- **`--resume <job_id>`** funcional na CLI (era no-op). + **auto-resume**: se há
  um job incompleto pro mesmo `(symbol, exchange, range)`, retoma automaticamente;
  ao fim de um job `partial`, imprime o hint `--resume {job_id}`.
- **`download(symbol, start, end, *, resume_job_id=...)`** na public API.
- **`fresh-path skip`** — re-rodar `download` do mesmo range é idempotente e
  barato (consulta o `chunk_ledger`, baixa só os dias faltantes), com ou sem
  `--resume`.
- **`DownloadProgress`** += `elapsed_s`, `eta_s`, `trades_failed`, `retries`
  (kwarg-only, defaults — SemVer-safe).
- **UX para downloads longos** (Story 4.21): ProgressCard mostra tempo restante
  (ETA), tempo decorrido, throughput (trades/s, chunks/h), trades baixados,
  trades perdidos, chunks com retry; barra mostra "Calculando plano de
  download…" quando o plano ainda não foi computado; log view limitado a 2000
  blocos (não acumula em downloads de horas); botão "Abrir Pasta" durante o
  download. PeriodPicker ganhou presets ("Mês corrente" / "Último ano" /
  "Ano completo: YYYY" / "Tudo desde 2018" / "Personalizado") + aviso de duração
  para ranges grandes ("⚠ ~N dias úteis, ~Xh-Yh de download — você pode pausar e
  retomar"). Ao reabrir o app com um download interrompido: banner "Retomar
  download de {symbol}? (parou em X/Y chunks)" com [Retomar]/[Começar do
  zero]/[Descartar]. `Catalog.list_jobs()` (read-only) suporta isso.
- `completeness_pct` por chunk logado em `download.complete` /
  `orchestrator.chunk_complete`.

### Removido (Removed)

- `orchestrator/broker/` (multi-process broker — dead-code pós-ADR-022): ~2034
  LOC + `test_pool_lifecycle.py` / `test_broker_protocol.py` /
  `test_worker_client.py` / `test_multi_symbol_mock.py` / `test_multi_asset_mock.py`.
- `ui/shortcuts.py` — placeholders nunca chamados (atalhos `Ctrl+R`/`Ctrl+L`/
  `Ctrl+E`/`Ctrl+O` sem handler — folclore).
- Microcopy `BTN_REPEAT_LAST` ("Repetir Último Download") — feature prometida
  sem implementação.
- Waiver `docs/qa/WAIVERS/test_pool_lifecycle_broker_dead_code.md` — obsoleto
  (o teste passa; o broker foi removido).

### Notas

- Suite: ruff 0 / mypy --strict 0 (87 source files) / pytest **1194 unit + 508
  integration+property, 0 fail** (3 skips ambientais: plataforma não-Windows).
- ADR-005 (thread model) emendado 2026-05-12; ADR-025 (parquet-por-dia) planejado
  para v1.2.1 — ver `docs/qa/V1.2.0-PLAN.md`.
- `KNOWN-TEST-FAILURES-v1.1.0.md` → `KNOWN-TEST-FAILURES-v1.2.0.md`.
- **Pendente de smoke real (Pichau, em pregão B3):** download de 1 mês WDOFUT via
  CLI + via UI (validar `translate_failures` ≈ 0 e completeness ~100%); resume
  real (matar o `.exe` no meio, reabrir, retomar); download de período extenso
  por blocos.

---

## [1.1.1] — 2026-05-12

> **Hotfix** — corrige o crash do app GUI ao baixar histórico (a v1.1.0
> ficou afetada; o CLI nunca foi). Descoberto via smoke real Pichau
> 2026-05-12. Story 4.19 + tasks #21/#21b.

### Corrigido (Fixed)

- **App GUI crashava ao baixar histórico** — `data_downloader.exe` abortava
  em `Qt6Core.dll` (`0xc0000409`) ao clicar "Baixar", precedido de
  `CreateDataLoader Failed | Access violation` no `Erro.log` da ProfitDLL
  e `WM_LOGIN_RESULT`/`WM_VALID_LICENSE` perdidos (`ERROR_INVALID_THREAD_ID`).
  Duas causas, ambas corrigidas:
  1. **Duplo init da ProfitDLL no mesmo processo (Q08-E):** "Testar Conexão"
     inicializava+finalizava a DLL; "Baixar" inicializava de novo — a DLL
     Classic não é re-inicializável. Fix: `data_downloader/dll/session.py`
     — `get_dll()` mantém uma instância process-global (lazy, thread-safe);
     "Testar Conexão" e "Baixar" reusam a mesma; `finalize()` só no
     encerramento (`atexit` + `MainWindow.closeEvent`). **Bug latente desde
     v1.0.5** (quando "Testar Conexão" foi adicionado).
  2. **Frozen windowed (`console=False`) → stdio inválido:** `sys.stdout`/
     `sys.stderr` eram `None` e os handles OS de stdio ficavam inválidos →
     a DLL Delphi crashava ao tocá-los. Fix: `ui/app.py::_ensure_valid_stdio()`
     na 1ª linha de `main()` reabre os 3 std fds para `os.devnull` antes de
     qualquer uso da DLL. (Q-DRIFT-39, novo.)
- **Modo de init da DLL alinhado entre "Testar Conexão" e "Baixar"** (#21b):
  `resolve_dll_init_mode()` é a fonte única do modo (`minimal_handshake`) —
  os dois caminhos sempre concordam, então o singleton reusa sem descasamento;
  `get_dll()` loga `dll.session.mode_mismatch` (warning) se algum caller pedir
  modo divergente.

### Notas

- Toda a árvore da v1.1.0 está incluída (esta é v1.1.0 + hotfix UI).
- `--healthcheck`, smoke real do `.exe` e o resto da suite (1199 unit /
  451 integration, todos exit 0) seguem verdes.

---

## [1.1.0] — 2026-05-12

> **Single solid release** — consolidação de 8 hotfixes (v1.0.0 → v1.0.7)
> + sweep BIG COUNCIL pré-v1.1.0. Primeira release com testes subprocess
> do `.exe` real e bundle reduzido em **55,6%** (886MB → 387.5MB).

### Highlights

- **Single ship consolidado** v1.0.0 → v1.0.7 → v1.1.0 — sem releases
  intermediários instáveis. Toda a árvore de hotfixes acumulada vira um
  único release estável.
- **Bundle 55,6% menor** (886MB → 387.5MB medido em `dist/data_downloader/`)
  via PySide6 lean spec — drop Qt6WebEngineCore + qtwebengine_devtools_resources
  + **32 submodules** PySide6 não usados (Pyro, COUNCIL-pyro-lean-bundle).
- **Primeira release com testes subprocess do `.exe` real** — flag
  `--healthcheck` (Dex) + `tests/integration/test_binary_exe.py` (Quinn).
  v1.0.x dependiam apenas de import do source — bug de empacotamento
  passava silencioso até o usuário rodar.
- **Q-DRIFT-37 mitigated** — `chunk_strategy` 1d para WINFUT previne
  saturação da queue do callback DLL (Nelo).

### Adicionado (Added)

- `data_downloader-cli.exe --healthcheck` — self-test minimal
  (imports + structlog probe), exit 0/1 (Dex).
- `src/data_downloader/_internal/bundle_paths.py` — resolução central de
  paths em frozen-mode (`is_frozen`, `bundle_root`, `asset_path`,
  `user_data_dir`, `user_env_path`, `exe_dir`); fim do
  `_MEIPASS` espalhado pelo código (Aria, ADR-018/021).
- `CheatSheetDialog` (atalho **Ctrl+/**) — modal de atalhos de teclado
  e ações rápidas (Uma).
- Onboarding banner — exibe CTA "Configurar Credenciais" no primeiro
  launch quando `.env` está ausente (Uma).
- Deep-link "Abrir Settings" em toasts de erro de credenciais
  (Felix-UI).
- `tests/integration/test_binary_exe.py` — subprocess tests do `.exe`
  real (Quinn).
- `tests/integration/test_frozen_assets.py` — valida QSS + contracts +
  ícone bundled corretamente (Quinn).
- `tests/integration/test_structlog_qt_bridge.py` — cobre regressão do
  bug v1.0.7 (bridge structlog → stdlib em UI thread) (Quinn).
- `tests/integration/test_cross_process_creds.py` — valida persistência
  de credenciais cross-process via `.env` user dir (Quinn).
- `tests/smoke/run_smoke_real.ps1` — script smoke real Pichau (Windows
  local, sem VM) (Quinn).
- `tests/smoke/run_smoke_q-drift-37.ps1` — smoke 5d com counters
  `queue_dropped` / `invalid_price_skips` / `completeness_pct` (Nelo).
- ADR-018 — frozen-mode boundary (Aria).
- ADR-021 — sys.frozen contract (Aria).
- ADR-023 — uniform chunk policy 1d/dia útil para todos ativos
  (Aria + Pax + Dex, hotfix Pichau live 2026-05-07).
- ADR-024 — catalog SQLite movido para `data/_internal/catalog.db`
  (Aria + Sol, hotfix UX Pichau live 2026-05-07).
- Story 4.18 (Q-DRIFT-38) — filtro `price <= 0` em
  `_IngestorThread._process_trade` evita abort do JOB inteiro por
  anomalia isolada da DLL (counter `translate_invalid_price_skips`
  exposto em `download.complete`).

### Mudado (Changed)

- **Bundle**: drop `Qt6WebEngineCore`, `qtwebengine_devtools_resources` +
  32 submodules PySide6 não usados via filter `_drop_lean(items)` em
  `a.binaries` + `a.datas` — bundle medido **886MB → 387.5MB** (Pyro).
- **Worker thread em download adapter** emite logs stdlib diretos —
  defense em profundidade (bypass structlog se setup ainda não rodou no
  thread) (Felix-UI).
- **`CatalogScreen`** adiciona `@Slot(...)` em 5 métodos cross-thread —
  fix do mesmo padrão de bug v1.0.7 (progress bar travada) (Felix-UI,
  B1 critical).
- **`MetricsAdapter`** usa `Qt.QueuedConnection` explícito em todas
  conexões cross-thread (Felix-UI, B2).
- **`test_connection`, `integrity_check`, `reconcile`** movidos para
  QThread workers — UI não freeza mais durante I/O lento (Felix-UI,
  B3+B4).
- **Version display em UI** agora dinâmico via
  `importlib.metadata.version("data_downloader")` com fallback literal
  `_PACKAGE_VERSION` (Felix v1.0.8 RCA — version display era o bug, não
  o bridge).
- **`setup_logging(bridge_to_stdlib=True)`** confirmado correto desde
  v1.0.7 (Felix v1.0.8 RCA; nenhuma alteração de comportamento — apenas
  documentação).
- **`validate_record`** documenta delegação de I3/I4 ao schema CHECK
  SQLite (Sol — defense-in-depth com single source of truth no schema).
- **Q-DRIFT-37**: HIGH/OPEN → CLOSED-MITIGATED — `chunk_strategy=1d`
  para WINFUT cap saturação da queue do callback DLL (Nelo).
- **Q-DRIFT-38**: NEW → CLOSED-FILTERED — filter `price <= 0` em
  `IngestorThread` (Nelo).
- **Hotfix Pichau live 2026-05-07:** Policy uniforme **1 dia útil/chunk para TODOS os ativos** (ADR-023). Supersede directive 2026-05-06 (WDOFUT=5/WINFUT=1). Q-DRIFT-37 promove para CLOSED-FULLY-MITIGATED.
- **Catalog SQLite path:** `data/history/catalog.db` → `data/_internal/catalog.db` (ADR-024). UX fix Pichau live 2026-05-07 — usuário estranhava `catalog.db` lado a lado com Parquets em `data/history/`.

### Corrigido (Fixed)

- `copy_context_to_thread` aceita `target=None` — elimina `TypeError`
  silenciado em `catalog_adapter:214` (Aria).
- `get_logger` retorna `BoundLogger` (cast explícito) — mypy `--strict`
  agora 0 errors em `observability/` (Dex).
- Populate-seed em `_open_catalog` e `_open_catalog_for_validation` agora
  loga warning em vez de silenciar exceção (Dex).
- ruff: 7 → 0 errors em escopo Wave 1 (RUF022, RUF100 autofix) (Dex).
- Microcopy catalog sync — test garante zero drift entre loader e
  `MICROCOPY_CATALOG.md` (Felix-UI + Uma).

### Documentação

- `docs/storage/INVARIANTS.md` clarifica `dll_companions` vs
  `dll_session_log` purpose (Sol).
- `docs/dll/QUIRKS.md` — RCAs finais Q-DRIFT-37 e Q-DRIFT-38 (Nelo).
- `docs/qa/MANUAL_SMOKE_v1.1.0.md` — checklist 15 estados de UI para
  smoke manual pré-release (Uma).
- `docs/decisions/COUNCIL-pyro-lean-bundle-2026-05-06.md` — racional
  do drop de Qt6WebEngineCore + lean spec (Pyro).
- `docs/release-notes/v1.1.0-draft.md` — release notes para GitHub
  Release.

### Constitutional / Architecture

- ADR-018 (frozen-mode boundary) ratificado (Aria).
- ADR-021 (sys.frozen contract) ratificado (Aria).

### Notas técnicas

- Bundle medido em **387.5MB** (`dist/data_downloader/` uncompressed)
  com filter `_drop_lean(items)` em `a.binaries` + `a.datas`. Zip
  distribuível `data-downloader-v1.1.0-win64.zip` ~157.6MB.
- Smoke real Pichau 2026-05-04: **1.574M trades** em 5 dias úteis
  WDOFUT, `queue_dropped=0`, `completeness_pct > 99%`.
- **1167+ tests** (unit + integration + property) — re-gate v1.1.0-r2
  em execução (ver `docs/qa/V1.1.0-FIX-PLAN.md` Wave D).

### Known issues (carregados para v1.2.0)

- Broker dead-code 2013 LOC pendente cleanup (Dex code-quality #4).
- Coverage tool incompatibility com Python 3.14 — workaround: pin
  Python 3.13 OU coverage 7.6 (Dex code-quality #3).

---

## [1.0.7] — 2026-05-05

Último hotfix da linha v1.0.x antes da consolidação v1.1.0. Histórico
detalhado preservado em `git log --oneline v1.0.6..v1.0.7`.

Highlights:

- Fix structlog → stdlib bridge em UI thread (sintoma: progress bar
  travada).
- Schema v1.1.0 NEVER drops + Q-DRIFT-35 telemetry (Sol, Story 1.7g).

## [1.0.6] — 2026-05-05

Hotfix consolidado em v1.0.x → v1.1.0. Ver `git log v1.0.5..v1.0.6`.

## [1.0.5] — 2026-05-05

Hotfix consolidado em v1.0.x → v1.1.0. Ver `git log v1.0.4..v1.0.5`.

## [1.0.4] — 2026-05-05

Hotfix consolidado em v1.0.x → v1.1.0. Ver `git log v1.0.3..v1.0.4`.

## [1.0.3] — 2026-05-04

Hotfix consolidado em v1.0.x → v1.1.0. Ver `git log v1.0.2..v1.0.3`.

## [1.0.2] — 2026-05-04

Hotfix consolidado em v1.0.x → v1.1.0. Ver `git log v1.0.1..v1.0.2`.

## [1.0.1] — 2026-05-04

Hotfix consolidado em v1.0.x → v1.1.0. Ver `git log v1.0.0..v1.0.1`.

## [1.0.0] — 2026-05-04

Primeira release estável. UI desktop (PySide6) + CLI + Public API
(`data_downloader.public_api` v1.0.0). Histórico completo via
`git log --oneline ...v1.0.0`.

---

# Histórico Public API (`__api_version__`)

A partir desta seção, entradas se referem **exclusivamente** à fronteira
`data_downloader.public_api`, governada por SemVer estrito.

---

## [API v1.0.0] — 2026-05-04

### Stable Public API release

Primeiro release **estável** da fronteira pública `data_downloader.public_api`.
A partir desta versão, garantias semânticas, assinaturas e hierarquia de
exceções são governadas por **SemVer estrito** (Story 4.3, COUNCIL-27).

- `__api_version__`: **0.4.0 → 1.0.0**.
- Política de deprecação formal em
  `docs/public_api/DEPRECATION_POLICY.md`.
- Exemplos de consumo (backtest, signal generator, risk monitor) em
  `docs/public_api/USAGE.md`.
- Decorator `@deprecated` (lifecycle `since`/`removed_in`/`replacement`)
  disponível em `data_downloader.public_api._deprecation` (uso interno).
- Regression test suite SemVer (`test_public_api_semver_regression.py`)
  garante que TODOS os símbolos da V1.0 mantêm assinatura cross-version.
- Guardrail anti-leak: `test_public_api_no_internal_imports.py` impede
  que tests consumer importem de internals (`dll`, `storage`,
  `orchestrator`, `_internal`).

### Exports estáveis (`__all__`)

**Funções:**

- `download(symbol, start, end, *, exchange="F", data_dir=None, ...) -> DownloadHandle`
- `read(symbol, start, end, *, exchange="F", data_dir=None, columns=None) -> pa.Table`
- `read_continuous(symbol_root, start, end, *, exchange="F", data_dir=None, catalog) -> pa.Table`
- `vigent_contract(symbol_root, on_date, *, exchange="F", catalog) -> str`

**Classes:**

- `DownloadHandle` (`cancel`, `result`, `events`, `cancelled`, `is_cancelled`,
  `is_cancelling`, `peek_result`, `join`)
- `DownloadProgress` (frozen dataclass — `total`, `done`, `message`,
  `trades_received`, `current_contract`, `is_99_reconnect`)
- `DownloadResult` (frozen dataclass — `job_id`, `symbol`, `exchange`,
  `actual_start`, `actual_end`, `trades_count`, `partitions`,
  `duration_seconds`, `status`, `error_message`)
- `DownloadStatus` (`Literal["completed", "partial", "failed", "cache_hit", "cancelled"]`)

**Exceções:**

- `DataDownloaderError` (base)
- `DLLInitError`
- `InvalidContract`
- `DiskFull`
- `DownloadError`
- `IntegrityError`
- `OperationCancelled` (Story 2.11)
- `ConnectionLost` (Story 2.11)

### Garantias V1.0 (contratuais — quebrar exige bump major)

1. **Idempotência (R5)** — re-run com mesmo `(symbol, start, end, exchange)` é
   seguro; trades duplicados são deduplicados pelo writer.
2. **BRT naive (R7)** — todos `datetime` são naive (sem `tzinfo`),
   horário Brasil (UTC-3).
3. **Dedup canônico (R5)** — `read`/`read_continuous` nunca retornam
   duplicatas (cut-off `+1ns` em rollovers).
4. **Ordem cronológica** — `timestamp_ns` ascendente.
5. **Schema estável** — 17 campos canônicos + `schema_version` em
   metadata Parquet.
6. **Cancel graceful** — `cancel()` drena chunks; trades committados
   preservados; status final `"cancelled"` levanta `OperationCancelled`
   em `result()`.
7. **Sem leak de exceções internas** — internals lançam
   `_InternalError`; fronteira traduz para `DataDownloaderError` family.

### Mudanças desde v0.x (cumulativo)

Todas as mudanças listadas abaixo já existiam em código (V0.x); este
release **formaliza** a fronteira como estável — não introduz novas
funções nem altera comportamento.

- **Docstrings completos** em todas funções/classes públicas (formato
  Google style com `Args`, `Returns`, `Raises`, `Examples`, `Notes`).
- Module docstring em `public_api/__init__.py` com:
  - Visão geral da API.
  - Garantias semânticas detalhadas.
  - Política SemVer.
  - Cobertura SemVer (o que está / o que NÃO está).
  - Histórico de bumps.
- Type annotations completas (mypy `--strict` clean em `public_api/`).

### Deprecated

_Nenhum em V1.0.0 — baseline._ Primeira deprecação será anunciada em
V1.x se/quando necessário, conforme política em
`docs/public_api/DEPRECATION_POLICY.md`.

### Removed

_Nenhum em V1.0.0 — baseline._

### Não coberto por SemVer (sujeito a mudança sem bump)

- Módulos `_internal/`, `dll/`, `storage/`, `orchestrator/`, `ui/`.
- Comportamento de exceções internas (`_InternalError` family).
- Performance / latência (governada por `benchmarks/BASELINES.md`).
- Mensagens humanas (microcopy ID estável; texto pode mudar via
  `MICROCOPY_CATALOG.md` — Uma authority).

### Roadmap

- **V1.x (minor):** possíveis adições aditivas — `download_batch(symbols=[...])`
  se backtest engine demandar; `read(columns=...)` push-down quando
  `DuckDBReader` expor.
- **V2.0 (major):** **nada planejado**. Declarado intencionalmente —
  V1.0 é projetado como contrato estável de longo prazo.

---

## [API v0.4.0] — 2026-05-03

### Added (Story 2.11 — H10 closure + Q02-E)

- `OperationCancelled` exception — sinaliza cancel cooperativo concluído
  (não é falha; trades parciais preservados em `details`).
- `ConnectionLost` exception — reconexão DLL ultrapassou janela
  esperada (Q02-E hard timeout).
- `DownloadHandle.cancelled()` — non-blocking probe se cancel
  concluído.
- `DownloadHandle.is_cancelled` (property alias).
- `DownloadHandle.is_cancelling()` — `True` se cancel pedido (ainda
  pode estar drenando).
- `DownloadHandle.peek_result()` — non-blocking, no-raise inspection do
  `DownloadResult` (não levanta `OperationCancelled` para
  `status='cancelled'` como `result()` faz).

### Changed (soft-break)

- `DownloadHandle.result()` agora **levanta** `OperationCancelled` quando
  `status == "cancelled"` (anteriormente retornava o `DownloadResult`
  com status). Soft-break porque consumers que tratavam `result.status
  == "cancelled"` continuam funcionando se trocarem o pattern para
  `try/except OperationCancelled`. Justificado em COUNCIL-17 (exception
  hierarchy H10 cancel) — sinal explícito é UX correto.

---

## [API v0.3.0] — 2026-05-03

### Added (Story 1.7b — ADR-007a)

- `download(symbol, start, end, *, exchange='F', ...) -> DownloadHandle`
  — função primária da API; retorna handle assíncrono.
- `DownloadHandle` class com `cancel`, `result`, `events`.
- `DownloadProgress` frozen dataclass.
- `DownloadResult` frozen dataclass.
- `DownloadStatus` Literal type alias.
- `DownloadError` exception (placeholder pré-existente, agora ativo).

### Design rationale

ADR-007a: handle pattern (vs. union return) elimina violação Liskov +
viabiliza cancel real (H10) + carrega `current_contract` em rollover
(M16).

---

## [API v0.2.0] — 2026-05-03

### Added (Story 1.6)

- `vigent_contract(symbol_root, on_date, *, exchange='F', catalog) -> str`
  — resolve raiz + data → `contract_code` vigente.
- `InvalidContract` exception — símbolo não resolve em contrato vigente.

---

## [API v0.1.0] — 2026-05-03

### Added (Story 1.5b)

- `read(symbol, start, end, *, exchange='F', data_dir=None, columns=None) -> pa.Table`
- `read_continuous(symbol_root, start, end, *, exchange='F', data_dir=None, catalog) -> pa.Table`
- `DataDownloaderError` (base exception).
- `DLLInitError`, `DiskFull`, `IntegrityError` (placeholders).

### Design rationale

ADR-007: fronteira `public_api/` separada das internals. SemVer-tracked
desde v0.1.0 mas **não-estável** até v1.0 (esperado quebrar entre
minor versions durante alpha).
