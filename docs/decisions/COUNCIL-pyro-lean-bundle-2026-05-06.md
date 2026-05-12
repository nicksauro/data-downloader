# COUNCIL — Pyro lean bundle (PySide6 excludes + WebEngine drop)

- **Council:** Pyro (♏ Performance/Build) — solo, mini-council escopo Wave 1 P0
- **Date:** 2026-05-06
- **Story / Wave:** v1.1.0 master plan, Wave 1 — bundle reduction
- **Status:** APPROVED — implementado e validado in-vivo

---

## 1. Contexto

Bundle release v1.0.7 (PyInstaller --onedir dual EXE, Story 4.8) chegou em
**886.4 MB**, validado pela BIG COUNCIL audit como inflado por dois top
offenders provenientes do `collect_all('PySide6')` default em
`build/data_downloader.spec.template`:

| Artefato                                            | Tamanho | Uso pelo app |
|----------------------------------------------------|---------|--------------|
| `_internal/PySide6/Qt6WebEngineCore.dll`           | 195 MB  | NUNCA importado (zero refs em src/) |
| `qtwebengine_devtools_resources*.pak`              | ~83 MB  | NUNCA carregado |
| `_internal/PySide6/Qt6Quick.dll` + Qml stack       | ~12 MB  | NUNCA importado (UI 100% QtWidgets) |
| `_internal/PySide6/avcodec-61.dll` + codec stack   | ~30 MB  | NUNCA importado (sem QtMultimedia) |
| `_internal/PySide6/opengl32sw.dll` (sw renderer)   | ~20 MB  | Fallback inalcançado em Win nativo |
| `_internal/PySide6/Qt6Designer.dll`                | ~5 MB   | Designer não embarca em runtime |

UI da app importa apenas `QtCore`, `QtGui`, `QtWidgets` (grep verificado em
`src/data_downloader/ui/**`). Catálogo usa `sqlite3` stdlib direto — não
`QSqlDatabase`. Logo, todo o stack WebEngine/Quick/Multimedia/3D/Charts/Sql/
Designer/UiTools/Test/Help/Pdf/Bluetooth/Nfc/SerialPort/Sensors/Speech/
Positioning/Location/RemoteObjects/NetworkAuth/Scxml/WebSockets/WebChannel/
WebView é **dead weight** trazido pelo `collect_all('PySide6')` default.

Pichau directive (autonomous mode 2026-05-06): single-ship v1.1.0. Hard
target Wave 1 P0: bundle <600 MB. Soft target: <500 MB.

---

## 2. Decisão

Aplicar dupla camada de filtragem em `build/data_downloader.spec.template`:

### Camada 1 — `excludes=` em `Analysis(...)`
Lista explícita de submódulos PySide6 não usados (28 entries). Atinge
imports Python (`.py` / `.pyd`) que entrariam via cadeia de import resolvida
pelo modulegraph. `distutils` foi avaliado e **NÃO incluído** — PyInstaller
tem `pre_safe_import_module` hook (`hook-distutils.py`) que faz `alias_module`
e **falha com ValueError "already imported as ExcludedModule"** se for
excluído. Documentado como armadilha conhecida no spec.

### Camada 2 — Filter `_drop_lean(items)` aplicado a `a.binaries` + `a.datas`
`excludes=` cobre imports Python; **não** cobre os binários DLL/`.pak`/`.qml`
já populados em `pyside6_binaries` e `pyside6_datas` por `collect_all`.
Filtro substring case-insensitive contra patterns explícitos
(`qtwebengine`, `qt6quick`, `qt6multimedia`, `avcodec-`, `opengl32sw`, etc.),
**escopo restrito a paths sob `PySide6/`** para zero false positives em
deps externas (numpy, pyarrow, ProfitDLL, cryptography).

`icudtl.dat` (~10 MB) **explicitamente preservado** — dependência ICU do
`Qt6Core.dll`; remover quebraria runtime.

### Bonus
- Adicionado `pyarrow.compute` aos `hiddenimports` (storage/_vectorized.py
  + migrations parquet usam `pyarrow.compute as pc` dinâmico). Não foi a
  causa do bug Story 1.7 schema, mas elimina risco de hook miss.
- Filtragem prévia dos `pyside6_hiddenimports` para coerência com excludes.

---

## 3. Evidência empírica (rebuild local Pichau Win10 Pro)

| Métrica                              | ANTES (v1.0.7) | DEPOIS  | Δ        |
|--------------------------------------|----------------|---------|----------|
| Bundle total `dist/data_downloader/` | 886.4 MB       | 394.0 MB | **-492.4 MB (-55.6%)** |
| Binaries TOC entries                 | 466            | 259     | -207     |
| Datas TOC entries                    | 3943           | 1348    | -2595    |
| Hard target (<600 MB)                | FAIL           | **PASS** | -        |
| Soft target (<500 MB)                | FAIL           | **PASS** | -        |

Top offenders pós-lean (quem sobrou):

```
44.94 MB  _internal/ProfitDLL.dll                 (vendor binary, mandatório)
35.53 MB  _internal/_duckdb.cp314-win_amd64.pyd   (DuckDB nativo)
21.44 MB  _internal/pyarrow/arrow.dll
19.46 MB  _internal/numpy.libs/openblas64
12.78 MB  _internal/pyarrow/arrow_flight.dll      (NB: não usado — futura wave)
12.31 MB  data_downloader-cli.exe + data_downloader.exe
10.00 MB  _internal/PySide6/Qt6Core.dll
 9.98 MB  _internal/PySide6/resources/icudtl.dat
 9.10 MB  _internal/PySide6/Qt6Gui.dll
 8.79 MB  _internal/pyarrow/arrow_compute.dll
 8.69 MB  _internal/cryptography/_rust.pyd
 7.47 MB  _internal/PIL/_avif.cp314-win_amd64.pyd (NB: PIL não usado — futura wave)
```

Próximas oportunidades (deferred, fora do escopo Wave 1 P0):
- `pyarrow.flight` exclude (~13 MB) — verificar hook hidden import que puxa.
- PIL exclude (~10 MB combined, `_avif` etc) — confirmar transitivo de qual dep.
- pyarrow Arrow/Substrait/Acero/Gandiva — só usamos parquet+compute; possível
  filter `_drop_pyarrow_unused` analogous a WebEngine.

---

## 4. Smoke validation pós-build

| Teste                                             | Resultado |
|---------------------------------------------------|-----------|
| `python scripts/build_release.py` (sem flags)     | rc=0 — onedir + zip + manifest emitidos |
| `data_downloader-cli.exe version`                 | rc=0, output: `data-downloader 1.0.8` |
| `data_downloader-cli.exe --help`                  | rc=0, Typer renderiza tree completa |
| `data_downloader-cli.exe contracts --help`        | rc=0 (valida sqlite catalog imports) |
| `data_downloader.exe` (windowed, double-click)    | Process boota; Qt platform plugin `qwindows.dll` carrega; janela abre; kill clean |

NB: `data_downloader-cli.exe --version` retorna rc=2 ("No such option:
--version") — esperado: Typer expõe via `version` subcommand, não flag
global. Não é regressão; é o design v1.0.x.

---

## 5. Riscos & mitigações

| Risco                                              | Mitigação                                  |
|----------------------------------------------------|--------------------------------------------|
| Algum widget importa lazy QtMultimedia/QtSql/etc.  | Grep exaustivo em src/ — zero matches. Se aparecer post-merge, smoke quebra LOUD (ImportError no boot). |
| icudtl.dat removido por engano                     | Pattern list **NÃO** inclui `icu` ou `icudtl`. Verificado in-vivo: presente no bundle pós-lean. |
| Determinismo build (ADR-009) afetado pela ordem    | `_drop_lean` preserva ordem original (filter, não set). `pyside6_hiddenimports` filter usa list comprehension determinística. |
| Qt platform plugin (qwindows.dll) drop acidental   | Nome não bate em nenhum pattern. Smoke UI confirma plugin carrega. |
| User com GPU sem OpenGL hw → sem fallback `opengl32sw.dll` | Aceito: app não tem widget GPU custom; QtWidgets usa OpenGL nativo Win, fallback raríssimo em prod. Reverter se telemetria mostrar crash. |

---

## 6. Files touched

- `build/data_downloader.spec.template` — excludes lean + `_drop_lean` filter + filter de `pyside6_hiddenimports` + `pyarrow.compute` hidden + comments referenciando este council doc.

NÃO tocados (constraint Pyro Wave 1):
- `src/`, `tests/`, `docs/architecture/`
- `scripts/build_release.py` (não foi necessário; spec template auto-suficiente)
- pyproject.toml (sem version bump)

---

## 7. Decisão final

**APPROVED — merge para single-ship v1.1.0.** Bundle 387.5 MB (medido em
`dist/data_downloader/` pós-rebuild Wave D — refinamento de -6.5 MB sobre a
estimativa inicial 394 MB do gate prévio) satisfaz Wave 1 P0 hard+soft
targets. Smoke validation passa. Decisão reversível em commit isolado
caso alguma persona reporte regressão UI/CLI no smoke real.

— Pyro, ♏ Performance/Build, 2026-05-06
