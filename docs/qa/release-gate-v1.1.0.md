# Release Gate v1.1.0 — QA Quinn (Wave 2 P0)

**Owner:** Quinn (QA — ♐ Sagittarius — test pyramid evangelist)
**Wave:** 2 do master plan v1.1.0 (`docs/stories/v1.1.0-master-plan.md`)
**Diretiva:** BIG COUNCIL 2026-05-06 — "ta bem bugado, na oadianta ficar
lançando 1 milhão de v" — nenhum teste pré-Wave 1 exercitava o `.exe`
real. Quinn fecha esse gap com cobertura subprocess + invariants do
bundle frozen.

## Resumo

| Test                                         | Cobre                                | Tipo                |
|----------------------------------------------|--------------------------------------|---------------------|
| `test_binary_exe.py`                         | `.exe` real via subprocess           | integration         |
| `test_frozen_assets.py`                      | Assets bundleados em `_internal/`    | integration         |
| `test_structlog_qt_bridge.py`                | structlog → stdlib bridge (caplog)   | integration         |
| `test_cross_process_creds.py`                | UI → CLI cred persistência (.env)    | integration         |
| `tests/smoke/run_smoke_real.ps1`             | Smoke real Pichau (DLL + B3)         | smoke (manual)      |

## Detalhamento por arquivo

### `tests/integration/test_binary_exe.py`

Exercita `dist/data_downloader/data_downloader-cli.exe` via `subprocess`.
Skipa clean se bundle ausente (`pytest.skip` com mensagem apontando o
build script). Cobre:

- **`test_cli_healthcheck_exit_zero`** — `--healthcheck` retorna 0 + stdout
  contém `healthcheck OK`. **XFAIL hoje** — Wave 1 GAP exposto pelo Quinn:
  Dex adicionou `--healthcheck` em `cli.py` mas NÃO atualizou
  `_CLI_GLOBAL_FLAGS_NO_VALUE` em `ui/app.py`. Como ambos `.exes`
  compartilham entry point `ui/app.py`, o dispatcher roteia
  `--healthcheck` para UI em vez do CLI Typer — subprocess hang até
  timeout em headless. **Fix sugerido (Wave 3):** adicionar `'--healthcheck'`
  ao set `_CLI_GLOBAL_FLAGS_NO_VALUE`. Quando o fix landar, xfail vira
  XPASS e força remoção do decorator (gate permanente).
- **`test_cli_version_works`** — `version` retorna 0 + identifica produto
  (`data-downloader` ou `data_downloader`). Tolerante a 1.0.7/1.0.8/1.1.0+.
- **`test_cli_help_works`** — `--help` retorna 0. Smoke do entrypoint
  Typer.
- **`test_cli_help_lists_healthcheck_flag`** — flag `--healthcheck` aparece
  em `--help`. Garante que está REGISTRADO no Typer mesmo enquanto o
  dispatcher upstream tem bug.
- **`test_cli_doctor_runs_without_traceback`** — `doctor` não crasha com
  Python traceback. Exit-code não-zero é tolerado (alguns checks podem
  reportar FAIL legitimamente).
- **`test_ui_exe_present_in_bundle`** — dual-EXE Story 4.8 (ambos
  `.exe` + `-cli.exe` presentes).
- **`test_bundle_internal_dir_exists`** — `_internal/` existe (sem ele,
  launcher PyI não inicia interpretador).

### `tests/integration/test_frozen_assets.py`

Probe direto do filesystem em candidatos canônicos do layout frozen.
Skipa clean se `_internal/` ausente. Cobre:

- **`test_qss_in_bundle`** — `assets/style.qss` (Felix-UI Story 1.0.4).
  Sem ele a UI carrega sem tema dark.
- **`test_qss_non_empty`** — QSS bundled tem >100 bytes (defesa contra
  placeholder vazio).
- **`test_contracts_seed_in_bundle`** — `CONTRACTS.md` para first-run
  auto-populate (Story v1.0.2 fix).
- **`test_profitdll_companion_present`** — `ProfitDLL.dll` side-by-side.
- **`test_profitdll_companion_size_sane`** — DLL > 1MB (defesa contra
  stub).
- **`test_python_runtime_present`** — `python3*.dll` em `_internal/`.
- **`test_base_library_zip_present`** — stdlib bundled.

### `tests/integration/test_structlog_qt_bridge.py`

Complementa `test_structlog_bridges_to_qt.py` (Felix) com cobertura via
pytest `caplog` — SEM dependência de Qt. Roda em CI headless puro.

- **`test_structlog_bridge_to_stdlib_emits_records`** — bug v1.0.7 RCA:
  sem bridge, structlog não dispara `LogRecord` no stdlib root.
- **`test_structlog_bridge_redaction_applied`** — defesa em profundidade
  pós-bridge (senhas continuam mascaradas).
- **`test_structlog_bridge_cross_thread`** — worker threads também
  propagam (cobre orchestrator/DLL wrapper QThreads).

### `tests/integration/test_cross_process_creds.py`

Bug v1.0.5 (UI Save → fecha → reabre → vazio). Simula ciclo via
subprocess Python + `bundle_paths.user_env_path`.

- **`test_env_written_by_helper_visible_to_subprocess`** — `.env` em
  `~/.data-downloader/` é lido por subprocess que invoca `bootstrap_env`.
- **`test_user_env_path_canonical_hyphen`** — single source of truth
  hífen (NÃO underscore). Valida que legacy `_env_loader.user_env_path`
  delega para `bundle_paths.user_env_path` (Wave 1 Aria ADR-018).
- **`test_bootstrap_env_returns_false_when_no_env_present`** — graceful
  degrade (não crasha quando ausente).

### `tests/smoke/run_smoke_real.ps1`

PowerShell smoke para Pichau rodar localmente (Windows, fora do CI).

**NÃO é replacement para pytest.** Exercita `.exe` real + ProfitDLL +
servidores B3. Pré-requisitos: bundle frozen + credentials válidas.

Fluxo:
1. Pré-check do CLI exe + `.env` user-global.
2. `--healthcheck` (gate antes de qualquer download).
3. `download {Symbol} --start ... --end ... --exchange F` (janela
   `-Days+2` dias calendário terminando ontem).
4. Conta parquets em `data/history/**/*.parquet`.
5. `contracts list` (sanity catalog SQLite).
6. Verdict SMOKE PASS / FAIL.

Uso típico:
```powershell
.\tests\smoke\run_smoke_real.ps1
.\tests\smoke\run_smoke_real.ps1 -Symbol WINFUT -Days 3
```

## Como rodar

```powershell
# Build do bundle (pré-requisito para test_binary_exe.py + test_frozen_assets.py)
python scripts\build_release.py

# Suite integration completa (skipa real_dll)
pytest tests\integration -q -k "not real_dll"

# Apenas testes Wave 2 Quinn
pytest tests\integration\test_binary_exe.py tests\integration\test_frozen_assets.py `
       tests\integration\test_structlog_qt_bridge.py `
       tests\integration\test_cross_process_creds.py -v

# Smoke real Pichau (manual, fora do CI)
.\tests\smoke\run_smoke_real.ps1
```

## Constraints respeitados

- NÃO toca `src/` — apenas `tests/` + `docs/qa/`.
- Skip elegante quando bundle ausente — não falha CI antes do release build.
- Versão tolerante (1.0.7 / 1.0.8 / 1.1.0+) — Wave 4 bumpará pyproject sem regredir.
- PowerShell sintaxe nativa Windows.
- NÃO commit (responsabilidade do lead após review).

## Pendências / Próximas Waves

- [ ] **Wave 3 P0 — Felix-UI ou Dex hotfix:** adicionar `'--healthcheck'`
      ao set `_CLI_GLOBAL_FLAGS_NO_VALUE` em
      `src/data_downloader/ui/app.py`. Sem isso, `--healthcheck` continua
      roteando para UI em ambos os `.exes` e o test xfail nunca vira
      XPASS. Cobertura: `test_cli_healthcheck_exit_zero` (xfail strict
      vai detectar quando o fix landar).
- [ ] Wave 3: integrar `run_smoke_real.ps1` ao QA loop oficial (artefato
      em `docs/qa/SMOKE_EVIDENCE/`).
- [ ] Wave 4: bump pyproject 1.0.7 → 1.1.0 + tag de release.
- [ ] Future: telemetria de tempo de boot do `.exe` (regressão watch).
