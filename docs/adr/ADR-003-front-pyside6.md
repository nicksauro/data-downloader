# ADR-003 — Front desktop = PySide6 (Qt6) single-process

**Status:** accepted
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🎨 Uma, 🖼️ Felix, ⚡ Pyro
**Supersedes:** —
**Related:** ADR-001 (Python), ADR-005 (thread model), ADR-007 (public_api)

---

## Contexto

A promessa de produto (MANIFEST §1) é: *"Selecionar símbolo + período + clicar 1 botão + aguardar."* O front desktop é Epic 3+, mas a escolha precisa ser feita agora porque afeta:
- Thread model (ADR-005) — UI thread interage com backend.
- Public API (ADR-007) — fronteira que UI consome.
- Packaging (Gage) — bundle final.

Restrições:
- Single-user, single-machine, Windows desktop (DLL é Windows).
- Mesmo runtime do backend Python (ADR-001) → idealmente mesmo processo.
- UI nunca bloqueia (lei R11) — slots MainThread < 16ms.
- Empacotável como `.exe` rodável em Windows limpo.
- Theming dark mode (uso noturno comum em trading).

---

## Opções Consideradas

### Opção A — PySide6 (Qt6 binding oficial)
**Prós:**
- Mesmo processo do backend Python → zero IPC overhead.
- Qt = framework UI desktop mais maduro do mundo (>30 anos).
- Sinais/slots thread-safe nativos (`QueuedConnection`).
- QThread = forma canônica de rodar trabalho fora do MainThread.
- High-DPI awareness suportado nativamente.
- QSS (Qt Style Sheets) para theming central.
- Licença LGPL (compatível com app proprietário; PyInstaller funciona).
- Felix tem experiência (background).

**Contras:**
- `.exe` resulta em ~80-150MB (Qt binaries grandes).
- Estilo "menos web" — Qt parece desktop (vantagem para trading apps; desvantagem para usuário acostumado a SaaS).

### Opção B — Tauri + React (Python sidecar)
**Prós:**
- UI moderna estilo web (React, Tailwind).
- Bundle menor (~10-30MB).
- Hot reload em desenvolvimento.

**Contras:**
- IPC overhead (Tauri ↔ Python sidecar via stdin/stdout ou HTTP local).
- Adiciona Rust ao stack.
- Empacotamento mais complexo (Tauri + Python sidecar + DLL Win32 nativo).
- Performance depende de marshalling JSON.
- Felix precisa aprender Rust básico.
- Risco de "tela web num app desktop" — feel inconsistente com finanças/trading.

### Opção C — FastAPI + React no browser local
**Prós:**
- Zero packaging UI (browser do usuário).
- Stack web familiar.

**Contras:**
- Browser não é app desktop (sem tray, sem atalhos OS, sem tema dark mode integrado).
- Usuário precisa abrir browser e digitar URL (fricção contra promessa "1 botão").
- Latência rede local + serialização JSON.
- Não cumpre "app de escolha" para usuário.

### Opção D — Electron + React (Python sidecar)
**Prós:**
- UI moderna web.
- Comunidade enorme.

**Contras:**
- Bundle gigante (~150-250MB inclui Chromium).
- IPC sidecar como Tauri.
- Reputação de pesado/lento.

---

## Decisão

**Opção A — PySide6 (Qt6) single-process.**

Razões:
1. **Zero IPC** — UI e backend no mesmo processo Python. Performance superior, debugging mais simples.
2. **Sinais/slots thread-safe** — solução canônica para UI ↔ worker (lei R11).
3. **Maturidade** — Qt6 é estável, bem documentado, usado em terminais de trading reais.
4. **Felix** tem experiência (vide `agents/frontend-dev.md`).
5. **PyInstaller** lida bem com Qt + ctypes + DLL companions (lei R19, Gage configura spec).
6. **Theming central via QSS** + `theme.py` (Uma define paleta).

---

## Consequências

### Positivas
- Stack unificado em Python — squad inteiro lê.
- Performance excelente (zero IPC).
- Felix entrega Epic 3 sem aprender stack novo.
- Testes E2E mais simples (pytest-qt para UI testing).
- `.exe` único distribuído por Gage com PyInstaller.

### Negativas
- Bundle ~80-150MB. Aceitável para app desktop; documentar em README.
- UI tem feel "desktop tradicional" — Uma compensa com theming moderno (dark + cores acentuadas).
- Empacotamento PyInstaller exige spec cuidadoso (carregar `ProfitDLL.dll` + companions). Gage mantém em `build/data_downloader.spec`.

### Neutras
- Fica em aberto: futura web view via FastAPI para uso remoto (Epic 5+, não no MVP).

---

## Padrão arquitetural decorrente

```
src/data_downloader/ui/
├── app.py                       # QApplication, main entry
├── main_window.py               # QMainWindow com sidebar
├── theme.py + assets/style.qss  # tema (Uma)
├── shortcuts.py                 # QShortcut centralizados
├── adapters/                    # bridges QThread → backend
│   ├── download_adapter.py
│   └── catalog_adapter.py
├── screens/
│   ├── download_screen.py
│   ├── catalog_screen.py
│   └── settings_screen.py
└── widgets/                     # custom widgets
    ├── symbol_picker.py
    ├── period_picker.py
    ├── progress_card.py
    └── log_view.py
```

**Comunicação UI ↔ Backend:**
- Adapter (QObject em QThread) chama `public_api.*`
- Adapter emite sinais (`progress`, `error`, `finished`) com `QueuedConnection`
- Tela conecta sinais a slots de update visual

---

## Validações requeridas

- [ ] PyInstaller produz `.exe` rodável em Windows limpo (Gage, Epic 3)
- [ ] Felix `*responsiveness-audit` aprovado para todas as telas (R11)
- [ ] Smoke E2E via pytest-qt passa (Quinn, Epic 3)
- [ ] Bundle size <= 200MB (target)

---

## Amendment 2026-05-03 — Packaging `--onedir` + `DontUseNativeDialog`

**Autor:** 🏛️ Aria
**Consultados:** 🖼️ Felix, ⚙️ Gage, 🎨 Uma
**Origem:** PLAN_REVIEW H23 + M9
**Related:** ADR-009 (build determinism), ADR-017 (auto-updater)

### Mudança 1 — Packaging primário: `--onedir` (não `--onefile`)

Felix (H23) levantou que `--onefile` é armadilha:
- **Startup 3-5s** — `.exe` é arquivo SFX que extrai PYZ para `%TEMP%` em cada execução.
- **AV flag positivo** — comportamento "executa de tempdir após self-extract" é assinatura de malware comum.
- **Paths quebram** — `__file__` aponta para `%TEMP%\_MEIxxx\...` que muda a cada run; código que persiste paths relativos a `__file__` falha.
- **Update granular impossível** (ADR-017) — auto-updater precisa substituir só arquivos changed; `--onefile` força re-baixar tudo.

**Decisão amendment:**
- **Distribuição primária: `--onedir`** — pasta com `.exe` + DLLs + libs.
- ZIP da pasta (`data-downloader-1.0.0-win64.zip`) como artefato release.
- Usuário extrai e roda — sem self-extract overhead.
- `--onefile` opcional como artefato secundário se houver demanda (ex: distribuição via canais que não suportam ZIP).

Spec PyInstaller (Felix mantém `build/data_downloader.spec`):
```python
# Antes (proibido):
exe = EXE(pyz, a.scripts, a.binaries, ..., name='data-downloader')

# Depois (preferido):
exe = EXE(pyz, a.scripts, exclude_binaries=True, name='data-downloader')
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name='data-downloader')
```

Output: `dist/data-downloader/data-downloader.exe` + `dist/data-downloader/*.dll`.

### Mudança 2 — `QFileDialog.DontUseNativeDialog` documentado

Felix (M9) levantou inconsistência visual: QSS theming customizado + `QFileDialog` nativo Windows = mistura de aparência (dark mode da nossa UI vs branco do dialog Windows).

**Decisão:** usar dialog Qt-rendered (não nativo) em **todos** os file/folder pickers da UI:

```python
# src/data_downloader/ui/screens/download_screen.py

def _pick_data_dir(self):
    dialog = QFileDialog(self, 'Selecione pasta de dados')
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)   # <<< documentado
    dialog.setFileMode(QFileDialog.Directory)
    if dialog.exec():
        return dialog.selectedFiles()[0]
```

**Razões:**
- Theming consistente — QSS aplica.
- Test em `pytest-qt` mais previsível (dialog nativo é não-mockável).
- Cross-version Windows menos imprevisível (Win10 vs Win11 dialog differ).

**Trade-off aceito:** dialog Qt é menos familiar para usuário Windows. Mitigação: Uma cataloga microcopy + tooltips + breadcrumb claro.

### Impacto em outras decisões

- **ADR-009 (build determinism):** `--onedir` tem mais arquivos a determinizar (cada `.dll` e `.so` precisa hash-stable). Spec ajustado para sort de binaries.
- **ADR-017 (auto-updater):** `--onedir` viabiliza delta updates — substituir só arquivos changed. tufup `targets.json` lista cada arquivo.
- **Bundle size:** `--onedir` mantém ~80-150MB. `--onefile` é mesma soma + overhead de PE.

### Validações adicionais

- [ ] Felix atualiza `build/data_downloader.spec` para `--onedir` (Epic 3)
- [ ] Felix UI test: nenhum dialog nativo Windows aparece em fluxo principal (Epic 3)
- [ ] Gage smoke: `dist/data-downloader/data-downloader.exe` roda em VM Windows limpa em <1s startup (Epic 3)
- [ ] Documentação em `docs/release/PACKAGING.md` (Felix + Gage)
