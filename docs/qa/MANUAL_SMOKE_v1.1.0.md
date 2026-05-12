# Manual Smoke Checklist v1.1.0

> **Owner:** Uma (UX) | **Wave:** 3 P1 | **Diretiva Pichau:** single ship v1.1.0
>
> Lista determinística de 16 estados a validar em build frozen (`dist/data_downloader/`)
> antes de release. Marque PASS / FAIL / N-A. Para cada FAIL, anexar screenshot +
> commit hash em `docs/qa/SMOKE_EVIDENCE/`.

---

**Tester:** ___________________________________________
**Date:** _____________ (YYYY-MM-DD)
**Build:** `dist/data_downloader/data_downloader.exe`
**Commit hash:** ___________________________
**Setup invocação:** `dist\data_downloader\data_downloader.exe` (frozen) **OU** Setup.exe instalado

---

## Onboarding (3 itens)

- [ ] **1.** Primeiro launch sem `~/.data-downloader/.env` exibe banner de onboarding
      no topo da MainWindow com microcopy "Configure suas credenciais ProfitDLL para começar"
      e CTA "Configurar Credenciais" visível.
- [ ] **2.** Click no CTA "Configurar Credenciais" navega imediatamente para
      `SettingsScreen` (sidebar destaca Settings active).
- [ ] **3.** Após preencher PROFITDLL_KEY/USER/PASS + Save, banner de onboarding
      desaparece e DLL Status muda para "Configurado, não testado" (transição
      `not_configured` → `disconnected`) sem reiniciar app.

## Settings (4 itens)

- [ ] **4.** Campos `PROFITDLL_KEY` / `PROFITDLL_USER` / `PROFITDLL_PASS` aceitam
      input texto; toggle [Mostrar]/[Esconder] alterna echoMode (Password ↔ Normal)
      sem perder o valor digitado.
- [ ] **5.** Em launch sem `PROFITDLL_PATH` setado, auto-detect popula DLL Path se
      `ProfitDLL.dll` está em `bundle_root()` (frozen) **ou** em
      `C:\Program Files\Nelogica\ProfitChart\DLLs\Win64\`. Toast info
      "DLL detectada automaticamente" aparece ~250ms após boot.
- [ ] **6.** Botão "Procurar DLL..." abre `QFileDialog` (nativo Win32 em frozen,
      Qt-default em dev) iniciando em `Path(current).parent` se já há valor;
      filtro padrão "ProfitDLL (ProfitDLL.dll)". Selecionar arquivo preenche o
      campo + dispara validação visual (✓ verde / ⚠ ambar / ✗ vermelho).
- [ ] **7.** "Testar Conexão" com creds válidas mostra status "↻ Testando..."
      durante a chamada e resolve para "✓ Conectado (vX.Y)" (toast verde 3s) **OU**
      "Desconectado" (toast vermelho 5s + erro técnico no hint do empty state).
      Botão fica disabled durante o teste.

## Download (4 itens)

- [ ] **8.** Selecionar `WDOFUT` no SymbolPicker, escolher período (preset OU
      custom-range), click "BAIXAR" → ProgressCard renderiza dentro de 200ms,
      barra de progresso atualiza chunk-by-chunk com subtitle dinâmico
      "Chunk N/M — XXX trades".
- [ ] **9.** Logs do download streaming aparecem na log view do ProgressCard
      durante a operação (qt_log_handler bridging). Mensagens cruciais visíveis:
      DLL connect, trade history start, chunk progress.
- [ ] **10.** Botão "CANCELAR" (ou Esc/Ctrl+C) para download cleanly: estado
      transita para `STATE_NORMAL` sem zombie threads (verificar via
      Task Manager: nenhum thread `data_downloader.exe` permanece após cancel).
- [ ] **11.** Final summary toast verde 5s mostra `"{symbol}: {n_trades} trades em
      {n_files} arquivos"` (formato pt-BR — separador de milhar `.`). Parquet
      gravado em `data/history/SYMBOL=WDOFUT/...` e accessible via DuckDB.

## Catalog (2 itens)

- [ ] **12.** `CatalogScreen` (`Ctrl+B`) lista parquets disponíveis após o
      download da etapa 11; tabela mostra colunas Symbol / Date / Trades /
      Path. Empty state com CTA "Iniciar primeiro download" só aparece se
      catalog vazio.
- [ ] **13.** Botões "Verificar Integridade" + "Reconciliar" em `SettingsScreen`
      (seção Storage) executam em QThread e UI não freeza (≥60fps interagindo
      com sidebar durante operação). Toast progress + toast resultado com
      contadores `{n_ok}/{n_total}` e `{n_added}/{n_removed}`.

## Cheat Sheet + Help (2 itens)

- [ ] **14.** `Ctrl+/` em qualquer tela abre `CheatSheetDialog` (modal, ≈420×360px)
      com tabela de shortcuts em duas colunas (Atalho / Ação). Lista mínima:
      Ctrl+/, Ctrl+, , Ctrl+D, Ctrl+B, Ctrl+S, Esc, Ctrl+Q. Botão "Fechar"
      aceita o dialog.
- [ ] **15.** Seção About em `SettingsScreen` exibe versão correta do pacote
      (lida via `importlib.metadata.version("data_downloader")` ≡ valor em
      `pyproject.toml`), versão DLL após teste de conexão, schema version
      (CATALOG_VERSION), links docs/bugs e lista de agentes (10 emojis).

## Chunk policy real (1 item — BLOQUEANTE)

> Promovido de "additional A" para item bloqueante #16 em Quinn round 2
> review 2026-05-11 (G-1 + G-2): nenhum teste automatizado valida UI ↔
> source-of-truth de DEFAULT_CHUNK_DAYS em runtime real, então este check
> manual é a última linha de defesa antes de release.

- [ ] **16.** **ProgressCard atualiza N vezes (uma por chunk/dia útil); validar
      visualmente OU via `parquetCount == business_days` no log final.**
      Smoke 5 dias úteis WDOFUT real (5 chunks 1d cada — ADR-023 uniform
      policy hotfix Pichau 2026-05-07) → trades > 500k → parquet OK →
      `duckdb` query `SELECT COUNT(*)` confere com final summary.
      ProgressCard atualiza 5 vezes (uma por chunk/dia), não 1 vez.
      Alternativamente: rodar `tests/smoke/run_smoke_real.ps1 -Days 5` e
      verificar que log G-2 emite `OK (parquetCount >= business_days)`.

---

## Smoke real Pichau (additional, se aplicável)

> Apenas executável em ambiente com `.env` real + DLL real instalada.
> Não bloqueia release v1.1.0 (smoke real é R20 — Quinn agenda fora).

- [ ] **B.** Toast deep-link "Abrir Settings": forçar erro DLL (creds vazias)
      durante download → error card aparece com botão "Abrir Settings" que
      navega para `SettingsScreen`.

---

## Critérios de saída

- **Release-ready:** 16/16 PASS (itens 1-16) + zero FAIL crítico.
- **CONCERNS:** 1-2 FAIL não-bloqueantes documentados em
  `docs/qa/SMOKE_EVIDENCE/` com plano de fix follow-up.
- **NO-GO:** ≥3 FAIL OU qualquer FAIL em itens 7, 8, 10, 11, 16 (download path
  + chunk policy real).

> **Nota:** Itens 14 (Ctrl+/) e onboarding banner (1-3) são novos para v1.1.0
> Wave 3 (Uma). Item 16 promovido de "additional A" para bloqueante em Quinn
> round 2 review 2026-05-11 (G-1 + G-2 fixes). Demais itens herdam
> comportamento já validado em v1.0.x — esta checklist é a fonte da verdade
> para regressão.
