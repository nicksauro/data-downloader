# Known Test Failures — v1.1.0 (task #10 triage)

**Owner:** Quinn (@qa)
**Created:** 2026-05-11
**Context:** Saída do `V1.1.0-FIX-PLAN.md` task #10 — destrancar a suite de
integração (deadlock) + triagem dos FAILs pré-existentes.

> Os FAILs **resolvidos** nesta task não estão listados aqui (ver §"Resolvidos").
> Os itens abaixo são os que **permanecem** após task #10, com classificação,
> motivo de não-correção nesta task, e dono do follow-up.

---

## Estado atual da suite (após task #10)

| Suite | Comando | Resultado | Evidência |
|-------|---------|-----------|-----------|
| unit + property | `pytest tests/unit tests/property -q` | **1263 passed, 1 skipped, 0 fail** | `docs/qa/junit-v1.1.0-r2-unit-FULL.xml` (317s) |
| integration | `pytest tests/integration --timeout=120 -q` | **451 passed, 2 skipped, exit code 0, zero ruído Qt** (após task #14; ~186s) | `docs/qa/task14-full-final.txt` |

> **Atualização task #14 (2026-05-11, Felix @ui):** o ruído de teardown Qt no Windows
> (`access violation` / `Timers cannot be stopped from another thread` / `QThread:
> Destroyed while thread '' is still running` → exit code 9 mesmo com 100% dos testes
> passando) foi **eliminado**. `pytest tests/integration --timeout=120 -q` agora retorna
> **exit 0 limpo** (451 passed, 2 skipped). Ver §4 abaixo. Os 2 fails determinísticos de
> drift da Wave A (`test_finished_signal_shows_success_toast`, `test_qss_no_unauthorized_colors`)
> também já tinham sido resolvidos entre tasks #11–#13 — suite de integração está verde.

> **Atualização task #11 (2026-05-11):** o cluster UI flaky foi **resolvido** —
> `QTimer.singleShot` órfão em `settings_screen.py` substituído por `QTimer` parented
> em `self` (idem `catalog_screen.py` / `download_screen.py` toast-hide). `pytest
> tests/integration -k ui` rodado 3x → exatamente **2 fails determinísticos** em todos
> os runs (`test_finished_signal_shows_success_toast` + `test_qss_no_unauthorized_colors`,
> ambos drift da Wave A — ver §2/§3), zero erro flaky. Suite de integração esperada
> agora: ~443 passed, 0 xfailed, 2 skipped, **2 failed** estáveis (os 2 acima —
> `test_contracts_cli` resolvido em task #13; os 4 xfail ADR-023 recalculados em
> task #12). Evidência: `docs/qa/pytest-v1.1.0-r2-ui-recheck.txt`.

`1 skipped` (unit) = `test_pool_lifecycle.py::test_start_stop_cycle` — waiver formal
pré-existente em `docs/qa/WAIVERS/test_pool_lifecycle_broker_dead_code.md` (não
mexido por task #10).

`2 skipped` (integration) = `test_installer_build` (InnoSetup não instalado nesta
máquina — skip ambiental legítimo).

`0 xfailed` (integration) — os 4 xfail ADR-023 foram **resolvidos** em task #12
(ver §"Quarentenados (xfail) — RESOLVIDO em task #12").

---

## Resolvidos por task #10

| Teste(s) | Causa raiz | Fix |
|----------|-----------|-----|
| `test_multi_symbol_mock.py` (3) — pendurava a suite inteira | `catalog_broker.py:164/186/192` usava `extra={"name": ...}` no logging stdlib; `name` é atributo reservado de `LogRecord` → `KeyError` quando um teste anterior configura handler stdlib. Só manifestava na suite completa (isolado o root logger não tem handler). **Esta era a fonte do deadlock** (combinada com o drift dos mocks abaixo). | `catalog_broker.py`: renomeado `name` → `broker_name` nos `extra=` (produção, ≤6 linhas). |
| `test_orchestrator.py`, `test_orchestrator_with_metrics.py`, `test_orchestrator_with_retry.py`, `test_orchestrator_emits_chunk_events.py`, `test_multi_asset_mock.py`, `test_multi_symbol_mock.py`, `tests/property/test_orchestrator_idempotent.py` | **Signature drift** dos mocks `_FakeProfitDLL`: implementavam a API V1 antiga `translate_trade(handle, struct) -> int` (mutava struct) e o progress callback de 4 args; produção migrou (Story 1.7b-followup / Q-DRIFT-05) para `translate_trade(handle) -> TradeFields\|None` e progress callback de 2 args `(TAssetID, c_int)`. Resultado: `download_chunk` chamava `translate_trade(handle)` → `TypeError` engolido → 0 trades, 0 progress, `last_packet_seen=False` → `download.timeout` (10–1800s) → retry exponencial → suite "pendura". | Atualizados todos os mocks para a API V2. Também: quando o mock fica sem `rounds` configurados, emite agora um chunk vazio mas **completo** (progress=100) em vez de retornar 0 e nunca sinalizar fim — evita timeout/retry/deadlock quando o chunker ADR-023 (1d) gera mais chunks que rounds. |
| `test_migrate_cli.py` (2) | Fixture/asserções usavam `data/history/catalog.db`; ADR-024 (v1.1.0) moveu o catálogo canônico para `data/_internal/catalog.db`. A CLI `migrate` abre `_internal/`; o fixture criava em `history/` (que era movido na abertura do `Catalog` e ficava vazio na reabertura). | `tests/integration/test_migrate_cli.py`: `history` → `_internal` (3 ocorrências). |
| `test_cli_doctor.py::test_doctor_schema_outdated_warns_but_not_fail` (1) | `_seed_catalog` semeava em `history/catalog.db`; `_check_schema` lê de `_internal/catalog.db` (ADR-024) → não achava o `catalog_version=1.0.0` semeado. | `tests/unit/test_cli_doctor.py`: `_seed_catalog(... "_internal" ...)` em todas as chamadas. |
| `test_storage_writer_reader.py::test_read_empty_dir_returns_empty_table` (1) | Esperava `len(table.schema) == 17`; schema v1.1.0 é aditivo (+`buy_agent_name`/`sell_agent_name`/`trade_type_name`) → 20 colunas. | Asserção agora deriva de `pyarrow_schema()` (não enrijece o número). |

---

## ~~Quarentenados (xfail) — follow-up ADR-023~~ — ✅ RESOLVIDO em task #12 (Dex @dev, 2026-05-11)

Os 4 testes que tinham `@pytest.mark.xfail(strict=False, reason="...ADR-023...")`
foram **recalculados para a política 1d** (`DEFAULT_CHUNK_DAYS=1`, `_CHUNK_OVERRIDES={}`).
`@pytest.mark.xfail` removido; asserções de contagem ajustadas. Janela de teste comum:
2026-03-02 (seg) → 2026-03-13 (sex) = **10 dias úteis = 10 chunks de 1d**. O
`_FakeProfitDLL` (atualizado em task #10) já trata "out-of-rounds" devolvendo chunk
vazio mas completo (progress=100) → chunks excedentes viram `no_trades`.

| Teste | Asserção stale (antes) | Recalculada (depois) |
|-------|------------------------|----------------------|
| `test_orchestrator.py::test_orchestrator_happy_path_two_chunks` | `chunks_completed == 2` | `chunks_completed == 10`; `partitions_written==2` / `parts[0].row_count==7` mantidos |
| `test_orchestrator.py::test_orchestrator_partial_when_one_chunk_fails` | `chunks_completed==1`; `len(gaps)==1` | `chunks_completed==9`; `len(gaps)==9` (1 `failed_chunk` + 8 `no_trades`); assert robusto `len(failed_gaps)==1` |
| `test_orchestrator.py::test_orchestrator_failed_when_all_chunks_fail` | `chunks_failed==2`; `rounds=[fail]*6` | `chunks_failed==10`; `rounds=[fail]*30` (10 chunks × 3 attempts) p/ status='failed' |
| `test_orchestrator_with_metrics.py::test_orchestrator_emits_metrics_for_two_chunks` | `len(chunk_durations)==2` | `len(chunk_durations)==10`; `chunks_done` (`status=success`) `len==2` mantido |

**Validação task #12:** `pytest tests/integration/test_orchestrator.py
tests/integration/test_orchestrator_with_metrics.py tests/integration/test_orchestrator_with_retry.py
--timeout=120 -q --no-header` → **24 passed**, **0 xfailed**. Zero prod code tocado
(a política 1d já estava implementada — só os testes estavam desatualizados).

---

## Permanecem como FAIL/ERROR — NÃO resolvidos por task #10 (fora de escopo)

### 1. ~~`test_contracts_cli.py::test_cli_contracts_list_empty` — FAIL~~ — ✅ RESOLVIDO em task #13 (Dex @dev, 2026-05-11)

- **Sintoma (era):** espera `'Nenhum contrato cadastrado'` no output; recebe uma
  tabela populada (`wup.` etc.).
- **Causa raiz REAL (≠ hipótese original):** não era poluição cwd/`contracts.json`
  — o teste falhava **isolado também**. `cli._open_catalog()` faz **auto-populate
  do seed bundled** (`docs/storage/CONTRACTS.md`, ADR-024 first-run) sempre que o
  catálogo está vazio; logo `contracts list` num catálogo "vazio" nunca permanece
  vazio. O branch "Nenhum contrato cadastrado" do `contracts list` é, na prática,
  inalcançável sem `--root` filtrando nada (ou sem neutralizar o seed).
- **Fix (task #13):** em `test_cli_contracts_list_empty`, `monkeypatch.setattr(
  data_downloader.orchestrator.contracts, "populate_contracts_from_seed", lambda
  *a,**k: None)` — neutraliza o auto-populate só nesse teste, exercitando o branch
  da mensagem amigável. Também: fixture `_isolated_cwd` (autouse no módulo) faz
  `monkeypatch.chdir(tmp_path)` (defesa-em-profundidade contra qualquer fallback
  cwd-relativo do CLI/seed), e `isolated_catalog_path` agora aponta para
  `data/_internal/catalog.db` (era `data/history/...`, comentário stale pré-ADR-024).
- **Validação:** `pytest tests/integration/test_contracts_cli.py` → 9 passed;
  rodado junto com `test_validation_cli.py` + `test_metrics_cli.py` → 18 passed;
  `ruff check` limpo.
- **Follow-up (opcional, não-bloqueante):** o branch "Nenhum contrato cadastrado"
  do `contracts list` (sem `--root`) é efetivamente dead-code dado o auto-populate
  — considerar removê-lo ou só mantê-lo para o caso `--root` sem matches. Dono: a
  definir (não corrigido em task #13 — fora de escopo, exige decisão de produto).

### 2. ~~Cluster FLAKY de testes de UI~~ — ✅ RESOLVIDO em task #11 (Dex @dev, 2026-05-11)

- **Era:** "Exceptions caught in Qt event loop" / `RuntimeError: Signal source has been deleted` / `QThread: Destroyed while thread '' is still running` durante setup/call/teardown de testes de UI; 8–10 fail/err variando por run; todos passavam isolados.
- **Causa raiz (única):** `QTimer.singleShot(3000, lambda: self._set_state(STATE_NORMAL))` em `settings_screen.py:1242` (lambda captura `self` — a `SettingsScreen`). Quando um teste destruía a screen antes dos 3s, o timer disparava no teste seguinte sobre o objeto C++ já deletado.
- **Fix (task #11):** `QTimer` membro parented em `self` (`self._state_restore_timer = QTimer(self); setSingleShot(True); timeout.connect(...)`; `.start(3000)` em `_on_save_clicked`). Mesmo padrão aplicado aos `QTimer.singleShot(duration_ms, self._toast.hide)` órfãos em `settings_screen.py` / `catalog_screen.py` / `download_screen.py` (`_show_toast`) e ao toast auto-detect de 250ms em `settings_screen._load_initial_values`. Timer com parent `self` é destruído junto com a screen → não vaza.
- **Validação:** `pytest tests/integration -k ui` rodado 3x → cluster `test_ui_status_bar` / `test_ui_theming` / `test_ui_download_screen` / `test_ui_symbol_picker` **estável** (mesmas 2 falhas determinísticas em todos os runs — itens §3 abaixo + §2-bis); zero erro flaky. `pytest tests/unit/ui` 32 passed; `ruff` limpo.

### 2-bis. `test_ui_download_screen.py::test_finished_signal_shows_success_toast` — FAIL DETERMINÍSTICO — Wave A drift

- **Sintoma:** espera `current_state() == "normal"` após `_on_finished`; recebe `"success"`. Falha **isolado também** (não-flaky).
- **Causa:** hotfix v1.1.0 2026-05-07 (Wave A) mudou `_on_finished` para `_set_state(STATE_SUCCESS)` (card persistente até ação do usuário) em vez de `STATE_NORMAL`; o teste não foi atualizado.
- **Por que não corrigido na task #11:** fora de escopo (constraint: não reverter/mexer em fixes da Wave A; task #11 = só QTimer leak).
- **Follow-up:** atualizar a asserção do teste para `"success"` (alinhado ao novo comportamento) — dono Wave A / Felix.

### 3. `test_ui_theming.py::test_qss_no_unauthorized_colors` — FAIL — needs THEME.md update

- **Sintoma:** `Cores não autorizadas no QSS (R17): {'#2FB85C'}` — cor verde adicionada ao `style.qss` (toast de sucesso, Wave A / Uma) sem registro em `docs/ux/THEME.md`.
- **Classe:** PROD/DOCS drift — a cor é legítima, falta documentá-la.
- **Por que não corrigido aqui:** toca `docs/ux/THEME.md` e/ou `style.qss` (Wave A / Uma).
- **Follow-up (Uma):** registrar `#2FB85C` em `THEME.md` (paleta de feedback positivo) **ou** remapear o toast de sucesso para uma cor já autorizada.

### 4. ~~Ruído de teardown Qt no Windows → `pytest tests/integration` exit code 9~~ — ✅ RESOLVIDO em task #14 (Felix @ui, 2026-05-11)

- **Era:** `pytest tests/integration` (e `-k ui`) com **todos os testes passando** abortava no shutdown do interpretador com `Windows fatal exception: access violation` (×N), `QObject::~QObject: Timers cannot be stopped from another thread` (×~18), `QThread: Destroyed while thread '' is still running` → exit code 9 (0xC0000409). Não afetava pass/fail dos testes, mas quebrava o gating de CI por exit-code.
- **Causas-raiz (3, todas leak de QThread/QTimer no teardown):**
  1. **`MetricsAdapter` (`metrics_panel.py`):** o `QTimer` interno é criado em `_on_thread_started` e pertence à worker thread; `shutdown()` parava o timer **a partir do MainThread** (errado) e o adapter ficava com afinidade à worker thread morta — destruição posterior (GC no `atexit`) disparava `Timers cannot be stopped from another thread` em loop. Bônus-bug: o `Qt.ConnectionType...` em `shutdown()` lançava `NameError` silencioso porque `Qt` não estava importado.
  2. **`MainWindow.closeEvent`** só dava `shutdown()` no `_metrics_adapter`, não nos adapters dos screens (`DownloadAdapter`/`CatalogAdapter`) — screens-filhos não recebem `closeEvent` quando a janela principal fecha, então essas `QThread` ficavam vivas no teardown.
  3. **`test_ui_download_screen.py::test_clicking_download_with_valid_inputs_transitions_to_loading`** disparava um download REAL via `adapter.start` (sem DLL/.env → loop de retry/timeout na worker thread) que não respeitava `cancel` a tempo → `DownloadAdapter` vazava a `QThread 'download-adapter'` no teardown.
- **Fix (task #14, ~70 linhas):**
  - `metrics_panel.py`: `import Qt`; `shutdown()` pede via `QMetaObject.invokeMethod(BlockingQueuedConnection)` que a worker thread pare o timer **e** chame `self.moveToThread(QCoreApplication.instance().thread())` (move adapter+timer de volta ao MainThread) antes do `quit()/wait()`; novos slots `@Slot() _on_thread_started` / `_teardown_in_worker`.
  - `main_window.py`: `closeEvent` agora itera `self._screens` e dá `shutdown()` em cada `screen._adapter` além do `_metrics_adapter`.
  - `download_adapter.py` / `catalog_adapter.py`: `QThread.setObjectName(...)` (debug); `DownloadAdapter.shutdown()` pede `handle.cancel(timeout=0.0)` antes do `quit()` + `wait(5000)` (sem `terminate()` — abortar thread mid-native-call gera `access violation`).
  - `settings_screen.py`: `setObjectName` nos 3 worker threads lazy (debug).
  - `test_ui_download_screen.py`: o teste de transição mocka `public_api.download` (devolve handle vazio) — não é o download que ele valida, e o download real travava o worker; fixture `download_screen` chama `_adapter.cancel()` antes do `shutdown()`.
- **Validação:** `pytest tests/integration -k ui --timeout=120 -q` rodado 2× → **exit 0, ZERO** `access violation` / `Timers cannot` / `QThread: Destroyed`. `pytest tests/integration --timeout=120 -q` (suite completa) → **451 passed, 2 skipped, exit 0, zero ruído Qt**. `ruff check` limpo nos arquivos tocados. Evidência: `docs/qa/task14-kui-final.txt`, `docs/qa/task14-full-final.txt`, `docs/qa/task14-diag.txt`.

---

## Configuração de timeout adicionada

`pyproject.toml [tool.pytest.ini_options]`:

```toml
timeout = 120
timeout_method = "thread"
```

- `pytest-timeout>=2.3` adicionado a `[project.optional-dependencies].test`.
- `timeout_method = "thread"` porque `SIGALRM` (método signal) não existe em Windows.
  ⚠️ Nota operacional: o método `thread` faz `os._exit(1)` ao estourar — mata a
  sessão inteira (sem junit-xml). Por isso o **objetivo primário** foi eliminar a
  causa-raiz do deadlock (drift dos mocks + `KeyError` do logging) para que o timeout
  **nunca dispare** na prática. Com os fixes acima, a suite roda em ~153s, bem abaixo
  do limite de 120s/teste.
- Testes legitimamente lentos (subprocess de `.exe`, spawn de `multiprocessing`)
  continuam abaixo de 120s; nenhum precisou de `@pytest.mark.timeout(300)` local
  até agora — adicionar pontualmente se algum teste de `.exe` real demorar mais.
