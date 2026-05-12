# ADR-018 — Frozen-Mode Path Boundary (`bundle_paths` as single source of truth)

- **Status:** ACCEPTED
- **Data:** 2026-05-06
- **Autor:** Aria (architect)
- **Stakeholders consultados (Wave 1 v1.1.0):** Felix-UI (consumer principal — QSS, dialogs), Nelo (DLL companions consumer), Dex (testabilidade), Pyro (R21 hot-path discipline), Pax (PO sign-off release)
- **Bloqueia release:** SIM — pré-requisito para v1.1.0 ship gate (Wave 4).
- **Relacionado:** ADR-021 (sys.frozen contract — companion ADR), ADR-009 (build determinism), Story v1.1.0 master plan §Wave 1.

> Localização canônica deste ADR: `docs/adr/` (segue numeração da pasta `docs/adr/`, NÃO `docs/architecture/` mencionada no master plan — `docs/adr/` é o convention real do repo, validado contra ADR-005…ADR-022 existentes).

---

## Contexto

Antes desta extração, **cinco call sites distintos** duplicavam a lógica de resolução de paths em modo frozen (PyInstaller `--onedir`) versus source (dev / pip-installed):

| Call site | Asset resolvido | Padrão local |
|-----------|----------------|--------------|
| `ui/app.py::main` | `assets/style.qss` (QSS do tema) | `getattr(sys, "_MEIPASS", "")` + 4 candidatos manuais |
| `ui/screens/settings_screen.py::_auto_detect_dll_path` | `ProfitDLL.dll` bundled | `getattr(sys, "frozen", False)` + `_MEIPASS` |
| `orchestrator/contracts.py::_resolve_default_seed_path` | `docs/storage/CONTRACTS.md` | mesma duplicação |
| `dll/wrapper.py::_resolve_default_dll_path` | `ProfitDLL.dll` default | mesma duplicação |
| `dll/wrapper.py::_load_verify_dll_companions` | `scripts/verify-dll-companions.py` | mesma duplicação |
| `_env_loader.py::bootstrap_env` | `.env` adjacente ao `.exe` | `getattr(sys, "frozen", False)` |

Cada call site tinha sua **própria ordem de candidatos**, **própria mensagem de erro**, **própria política de fallback**. Resultados:

1. **v1.0.4 QSS bug (Pichau live test 2026-05-06):** `app.py` procurava em `Path(__file__).parent / "assets"` que em frozen aponta para `<bundle>/data_downloader/ui/assets/` — caminho que NÃO existia (o spec bundla em `<bundle>/assets/`). QSS nunca carregava → botão "Salvar" sem styling visível ("n tem nhnum lugar para apertar save").
2. **v1.0.5 DLL companions bug:** `dll/wrapper.py` procurava companions em `<repo>/profitdll/...` mesmo em frozen → erro "DLL companions ausentes (missing=[])" mascarando como list vazia.
3. **v1.0.5 .env mismatch:** `_env_loader.bootstrap_env` adicionava `<exe-dir>/.env` apenas quando `getattr(sys, "frozen", False)`. Mas `settings_screen._config_path` usava paths user-home sem checar frozen — inconsistente.

Este é o padrão clássico de **drift arquitetural**: lógica idêntica copiada-e-adaptada em N pontos, cada uma evoluindo divergente. Cada novo bug causava o reflexo "vou fixar aqui também", eternizando o problema.

Adicionalmente, **testes unitários ficaram impossibilitados de mockar uniformemente o frozen-mode**: cada test precisava simular `sys.frozen=True` + `sys._MEIPASS=...` + `sys.executable=...` separadamente, e havia silent divergence (alguns tests setavam só `sys.frozen` sem `_MEIPASS` — passavam em prod-like fakes mas não em produção real).

## Decisão

**Adotamos `data_downloader._internal.bundle_paths` como ÚNICA fonte de verdade para resolução de paths em runtime.**

### API canônica (ver módulo)

```python
from data_downloader._internal.bundle_paths import (
    is_frozen,        # bool — frozen=True E _MEIPASS setado
    bundle_root,      # Path — _MEIPASS em frozen, pacote em source
    exe_dir,          # Path — Path(sys.executable).parent
    asset_path,       # Path — busca em [bundle_root, exe_dir/_internal, exe_dir, source]
    user_data_dir,    # Path — ~/.data-downloader/ (canônico — hífen)
    user_env_path,    # Path — ~/.data-downloader/.env
)
```

### Contrato

1. **Consumers (TODOS os módulos exceto `_internal/bundle_paths.py` e tests):**
   - **PROIBIDO** usar `sys._MEIPASS` direto.
   - **PROIBIDO** checar `getattr(sys, "frozen", False)` para fins de path resolution. (Outras semantics — ex.: `QFileDialog` native vs Qt-default — podem permanecer enquanto não envolverem path lookup.)
   - **OBRIGATÓRIO** delegar a `bundle_paths.*`.

2. **Ordem de candidatos em `asset_path`** (determinística, sem fallback silencioso):
   1. `bundle_root() / rel`  — frozen `_MEIPASS` ou pacote source.
   2. `exe_dir() / "_internal" / rel`  — `--onedir` runtime layout.
   3. `exe_dir() / rel`  — flat layout defensivo.
   4. `Path(__file__).parent.parent / rel`  — explicit source-mode fallback.
   - Se nenhum existe, levanta `FileNotFoundError` listando TODOS os candidatos tentados (debug em frozen é doloroso sem isso).

3. **Hot-path discipline (R21):** `bundle_paths.*` NÃO faz I/O no import (sem `is_file()` em module-level). Resolução é lazy — só chamada quando consumer precisa.

4. **Mockabilidade:** testes mockam `bundle_paths.is_frozen` (ou `Path.home`, `sys.executable`, `sys._MEIPASS` em conjunto). API uniforme → fixtures reusáveis.

### Compliance check (Wave 4 release gate)

```bash
# Deve retornar APENAS bundle_paths.py em src/.
grep -rn "_MEIPASS" src/data_downloader/ --include="*.py" | grep -v "_internal/bundle_paths.py"
# saída esperada: vazia OU somente comentários/docstrings (zero código ativo)
```

## Consequências

### Positivas

1. **Bug fix consolidado:** v1.0.4 QSS, v1.0.5 DLL, v1.0.5 .env — todos os fixes pontuais ficam alinhados em uma única implementação testada.
2. **Testabilidade:** `monkeypatch` em `bundle_paths.is_frozen` é o único stub necessário; tests determinísticos sem dependência de `sys._MEIPASS` na sandbox.
3. **Ergonomia para novos call sites:** futuro asset bundleado (ex.: ícones, microcopy YAML) usa `asset_path("icons/foo.svg")` — uma linha, sem boilerplate.
4. **Documentation as code:** `bundle_paths.py` docstring documenta o layout PyInstaller `--onedir` e source — referência viva.

### Negativas / Custos

1. **Migração one-shot:** 5 call sites tocados em Wave 1; cada um perdeu o seu fallback "ad-hoc" preferido. Risco mitigado por test coverage (43 tests passam após migração).
2. **Tightening de `is_frozen`:** antes era `getattr(sys, "frozen", False)` (qualquer bool truthy). Agora exige `_MEIPASS` setado também. Test `test_bootstrap_env_frozen_uses_exe_dir` precisou ser atualizado para setar ambos. Behavior change deliberada: `sys.frozen=True` sem `_MEIPASS` é estado inválido (PyInstaller real sempre seta os dois) — fail-loudly no tightening expõe testes mock-too-loose.
3. **Acoplamento do `_internal`:** `bundle_paths` está em `_internal/` (privado por convenção). Consumers em `public_api/` não devem importar — mas hoje nenhum precisa (assets são internos por natureza).

### Riscos residuais

- **`--onefile` extraction:** PyInstaller `--onefile` extrai para um tempdir único e seta `_MEIPASS` para esse tempdir. `bundle_paths` cobre, mas `--onefile` não é o build mode oficial (data_downloader usa `--onedir`).
- **Code signing path mutation:** futuras assinaturas Authenticode podem mover o `.exe` post-build (ex.: para `signed/`). `exe_dir()` continua válido; `bundle_root()` (via `_MEIPASS`) é resolvido em runtime — sem impacto.

## Validação

Wave 1 deliverables (Aria):

- [x] `src/data_downloader/_internal/bundle_paths.py` (NEW) com 6 funções tipadas (mypy strict 0 errors, ruff 0 errors).
- [x] `tests/unit/test_bundle_paths.py` 12 tests passing (cobrem source/frozen/missing/error paths).
- [x] Migração: `_env_loader.py`, `ui/app.py`, `ui/screens/settings_screen.py`, `orchestrator/contracts.py`, `dll/wrapper.py` — 6 call sites atualizados.
- [x] Compliance check: `grep _MEIPASS src/data_downloader/` retorna apenas `bundle_paths.py` em código ativo.
- [x] Test suite afetado (`test_env_bootstrap.py`, `test_env_loader.py`, `test_ui_settings_dll_picker.py`, `test_logging_cross_thread.py`, `test_dll_wrapper.py`) — 86 testes passando, 1 skipped (não relacionado).

## Notas

- ADR companheiro: **ADR-021** (sys.frozen contract) — formaliza QUEM pode chamar quem (`bundle_paths` é o único cliente legítimo de `sys.frozen` / `sys._MEIPASS`).
- Master plan §Wave 1 (Aria) lista este ADR como bloqueador de release.
