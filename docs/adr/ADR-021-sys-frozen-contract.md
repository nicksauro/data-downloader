# ADR-021 — `sys.frozen` Contract — Quem testa frozen mode

- **Status:** ACCEPTED
- **Data:** 2026-05-06
- **Autor:** Aria (architect)
- **Stakeholders consultados (Wave 1 v1.1.0):** Felix-UI (Qt dialog detection — exception ao banimento), Dex (test mock contract), Pyro (R21 hot-path), Pax (PO release sign-off)
- **Bloqueia release:** SIM — pré-requisito para v1.1.0 ship gate (Wave 4).
- **Relacionado:** ADR-018 (frozen-mode boundary — companion ADR estabelecendo `bundle_paths` como única autoridade de path resolution).

> Este ADR é a contraparte normativa do ADR-018: ADR-018 estabelece **O QUE** (`bundle_paths` é a fonte única); ADR-021 estabelece **QUEM** pode testar `sys.frozen` e em que circunstâncias.

---

## Contexto

ADR-018 introduziu `data_downloader._internal.bundle_paths` como única fonte para resolução de paths em runtime. Isso resolve o problema de **drift** mas deixa em aberto uma questão sutil: **outras semantics** dependem de "estamos em modo frozen?" — não-path semantics, mas igualmente legítimas. Exemplos identificados em Wave 1:

| Call site | Semantic | Path resolution? |
|-----------|----------|-----------------|
| `ui/screens/settings_screen.py::_on_dll_browse_clicked` | `QFileDialog.Option(0)` (Win32 native) vs `DontUseNativeDialog` (Qt fake — testável) | NÃO — UI dialog mode |
| `ui/screens/settings_screen.py::_on_change_data_dir_clicked` | idem | NÃO |
| `ui/screens/download_screen.py::_on_browse_folder` | idem | NÃO |

Essas três não envolvem path lookup; elas escolhem entre dois widgets Qt baseado em "estamos em produção (frozen) ou em dev/test?". Pichau live test 2026-05-06 (Story v1.0.5) documentou: em frozen, `DontUseNativeDialog` causava cores bugadas e zero shell integration; em dev/test, native dialog quebra mocks de `QFileDialog`. **Ambas as branches são corretas** — não é path resolution, é UX runtime mode.

Sem um contrato explícito, há risco de:

1. **Regressão arquitetural:** futuro dev veria essas linhas como "não migrei!" e tentaria usar `bundle_paths.is_frozen()` — funcionaria mas adiciona um import semanticamente errôneo (path module sendo usado para UX flag).
2. **Drift testular:** tests mockando `sys.frozen=True` para um propósito (UX) podem acidentalmente afetar outro (path) — diluindo isolation.
3. **Code review confusion:** reviewers seriam forçados a re-explicar a distinção a cada PR.

## Decisão

**Definimos o `sys.frozen` contract em três faixas:**

### Faixa 1 — `_internal/bundle_paths.py` (única autoridade path)

- **Pode** ler `sys.frozen` E `sys._MEIPASS` diretamente.
- **Deve** combinar os dois (`is_frozen()` exige ambos truthy/setados).
- **Único módulo** em `src/data_downloader/` autorizado a usar `sys._MEIPASS`.

### Faixa 2 — Consumers de path (UI app, settings auto-detect, contracts seed, DLL wrapper, env loader)

- **Devem** delegar a `bundle_paths.*` (`is_frozen`, `bundle_root`, `asset_path`, `exe_dir`).
- **Proibido** importar `sys._MEIPASS` ou usar `getattr(sys, "_MEIPASS", ...)`.
- **Proibido** usar `getattr(sys, "frozen", False)` para path decisions.

### Faixa 3 — Consumers de UX runtime mode (QFileDialog options, dialog flags, futuras flags análogas)

- **Permitido** usar `getattr(sys, "frozen", False)` para semântica não-path.
- **Recomendado** delegar a `bundle_paths.is_frozen()` quando a semântica for "produção vs dev" genérica (consistência > duplicação trivial).
- **Documentar** no comentário inline o RACIONAL — por que "frozen" implica essa decisão UX especificamente.

### Test contract

- Tests **devem** monkeypatch via `bundle_paths.is_frozen` quando o code-under-test consome `bundle_paths`.
- Tests podem monkeypatch `sys.frozen` + `sys._MEIPASS` em conjunto quando o code-under-test usa `bundle_paths.is_frozen()` indiretamente.
- Tests **proibido** monkeypatch só `sys.frozen=True` esperando que `bundle_paths.is_frozen()` retorne True — ele exige BOTH (PyInstaller real seta ambos; um sem o outro é estado inválido que NÃO deve ser simulado).

## Consequências

### Positivas

1. **Determinismo:** test mocks são uniformes — `bundle_paths.is_frozen` é o stub canônico.
2. **Code review automation:** linter rule (futura) pode banir `sys._MEIPASS` fora de `_internal/bundle_paths.py` deterministicamente.
3. **Documentation locality:** três faixas explícitas eliminam ambiguidade — reviewer não precisa adivinhar intent.
4. **Faixa 3 não vira loophole:** preserva pragmatismo (UI dialogs continuam funcionando) sem abrir back-door para path checks ad-hoc.

### Negativas / Custos

1. **Faixa 3 ainda usa `getattr(sys, "frozen", False)`:** auditoria visual de "uses of sys.frozen" precisa filtrar por contexto. Mitigation: comentário inline obrigatório (ex.: "frozen = produção .exe; UX dialog mode").
2. **Linter enforcement não-imediato:** rule custom para `flake8-bandit`-style ainda não escrito. Wave 1 audita por code review; Wave 4+ pode automatizar.

### Riscos

- **Faixa 3 expansion:** se mais semantics não-path surgirem (ex.: log format diferente, telemetry endpoint diferente), tentação de criar `bundle_paths.is_production()` separado. Não fazer agora — `is_frozen()` é suficiente; promover para `is_production()` apenas se houver real divergência (ex.: dev mode com .exe assinado para QA).

## Validação

Wave 1 deliverables (Aria):

- [x] `bundle_paths.is_frozen` é a única implementação com lógica `sys.frozen + sys._MEIPASS`.
- [x] Faixa 2 migrada: 6 call sites em 5 arquivos (vide ADR-018 §Validação).
- [x] Faixa 3 documentada in-place: `download_screen.py:408`, `settings_screen.py:855`, `settings_screen.py:912` mantêm `getattr(sys, "frozen", False)` com comentário racional ("nativo Windows (frozen / .exe)" ou "DontUseNativeDialog em dev/tests").
- [x] Test contract honrado: `test_env_loader.py::test_bootstrap_env_frozen_uses_exe_dir` e `test_env_bootstrap.py::test_bootstrap_env_frozen_uses_exe_dir` foram atualizados para setar `sys._MEIPASS` em conjunto com `sys.frozen`.

## Compliance audit (Wave 4 release gate)

```bash
# Faixa 1 — única ref a _MEIPASS deve ser bundle_paths.
grep -rn "_MEIPASS" src/data_downloader/ --include="*.py" | grep -v "_internal/bundle_paths.py"
# Esperado: zero matches em código ativo.

# Faixa 2 — sys.frozen em consumers de path deve ter sumido.
grep -rn 'getattr(sys, "frozen"' src/data_downloader/ --include="*.py" | \
    grep -v "_internal/bundle_paths.py" | \
    grep -v "QFileDialog\|Dialog\|dialog"
# Esperado: zero matches (Faixa 3 é exclusivamente dialog).
```

## Notas

- Master plan §Wave 1 (Aria) lista este ADR como bloqueador de release.
- ADR companheiro: **ADR-018** (estabelece o ÚNICO source of truth: `bundle_paths`).
