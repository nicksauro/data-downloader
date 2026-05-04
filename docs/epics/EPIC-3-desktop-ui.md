# EPIC 3 — Desktop UI

**Status:** in_progress (Story 3.1 Done — primeira tela real entregue via COUNCIL-23)
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03
**Última atualização:** 2026-05-03 (COUNCIL-23 — Story 3.1 Done; transição prep → in_progress)
**Target:** entregar UI desktop nativa (PySide6) consumindo public_api estável (Epic 1) — golden path de download via clique, não terminal. Pós-Epic 2.

## Preparatório completo (COUNCIL-12)

O trabalho preparatório para Epic 3 está completo:

- ✅ **Flows detalhados Epic-3-ready** — `docs/ux/FLOWS.md` v0.2.0 com 4 fluxos
  expandidos (atores com responsabilidades exatas, etapas com input/ação/microcopy/duração,
  decisões textuais if/then/else, edge cases exaustivos, 5 estados com microcopy + ação visual).
- ✅ **Wireframes Epic-3-ready** — `docs/ux/WIREFRAMES.md` v0.2.0 com 4 telas (MainWindow
  frame geral + DownloadScreen + CatalogScreen + SettingsScreen) e 5 estados ASCII detalhados.
- ✅ **Microcopy IDs novos** — `docs/ux/MICROCOPY_CATALOG.md` §17b com ~70 IDs novos Epic 3
  (DownloadScreen, CatalogScreen, SettingsScreen, MainWindow/StatusBar, toasts/modais).
- ✅ **Skeleton `src/data_downloader/ui/`** — 14 arquivos placeholder com docstrings
  detalhadas + referências cruzadas.
- ✅ **QSS esqueleto** — `src/data_downloader/ui/assets/style.qss` aplicando paleta canônica
  de THEME.md.
- ✅ **COUNCIL-12** sign-off Uma + Felix + Aria.

Lead time esperado Epic 3 reduzido em ~3-5 dias graças a este prep.

**Pendências antes de abrir** (ver COUNCIL-12 §Pendências):
- P1: ADR-007a (DownloadHandle.cancel) precisa estar `accepted` (Aria)
- P2: DownloadProgress deve incluir `current_contract: str` (Aria → Dex, finding M16)
- P3: Pyro baselines para estimativa banda honesta (Pyro)
- P4: PyInstaller spec `--onedir` configurado (Felix + Gage)
- P5: pytest-qt dev dependency adicionada (Quinn)

---

## Objetivo

Empacotar foundation + qualidade (Epics 1 + 2) em uma UI desktop usável por quant brasileiro sem terminal. Felix lidera a implementação Qt; Uma valida cada tela contra `docs/ux/` (Story 0.3 + refinamentos). Public_api é a fronteira — UI NÃO toca em DLL/storage diretamente (R15).

## Escopo IN

- **PySide6 shell** (main window, navigation, status bar)
- **Tela Download** (golden path: usuário escolhe symbol/range, clica baixar, vê progresso, summary)
- **Tela Catálogo** (lista de partições baixadas, filtros, query DuckDB inline básica)
- **Tela Settings** (env vars, paths, theme switch)
- **Theming** (light/dark conforme `docs/ux/THEME.md`; QSS aplicado; flag `DontUseNativeDialog` para QFileDialog — finding M9)
- **Packaging .exe** com PyInstaller (`--onedir` conforme amendment ADR-003 — finding H23)
- **Atalhos** context-aware (Esc/F5/Ctrl+R conforme decisão Uma — finding M10)
- **Métrica `ui_progress_dropped_count`** exposta (finding M11)
- **`current_contract` em DownloadProgress** (finding M16 — usuário vê rollover)

## Escopo OUT

- Auto-updater (Epic 4 — ADR-017)
- Code signing Windows EV cert (Epic 4 — ADR-016)
- Multi-symbol UI (Epic 4)
- Telemetria remota / opt-in analytics
- Internacionalização EN (PT-BR primeiro)

## Stories planejadas (preliminares — IDs reservados pelo COUNCIL-12)

| ID | Título | Owner | Estimativa | Artefatos prep ready |
|----|--------|-------|------------|----------------------|
| 3.1 | **DONE** — MainWindow + DownloadScreen funcional consumindo public_api (COUNCIL-23) | 🖼️ Felix | 3d (real) | WIREFRAMES MainWindow + Tela 1 + skeleton + style.qss seções 1/7/8 |
| 3.2 | (consolidado em 3.1) Tela Download — refinements + drawer Avançado | 🖼️ Felix + 🎨 Uma | 1d | (Story 3.1 entregou primeira versão funcional) |
| 3.3 | Tela Catálogo (lista partições + filtros) | 🖼️ Felix + 💾 Sol | 2d | WIREFRAMES Tela 2 + FLOWS 2 + skeleton catalog_screen.py + catalog_adapter |
| 3.4 | Tela Settings (env vars, paths, theme) | 🖼️ Felix + 🎨 Uma | 1d | WIREFRAMES Tela 3 + skeleton settings_screen.py + microcopy §17b.3 |
| 3.5 | Theming (light/dark, QSS, DontUseNativeDialog) | 🖼️ Felix + 🎨 Uma | 1d | style.qss esqueleto completo (Felix refina/expande) |
| 3.6 | pytest-qt setup (finding L6) + UI tests | 🧪 Quinn + 🖼️ Felix | 1d | (depende de stories implementadas) |
| 3.7 | Packaging PyInstaller `--onedir` | 🖼️ Felix + ⚙️ Gage | 2d | ADR-003 amendment + COUNCIL-12 D8 |
| 3.8 | Métrica ui_progress_dropped + current_contract no progress | 🖼️ Felix + ⚡ Pyro | 1d | M11 + M16 referenciados em download_adapter.py + ProgressCard |

**Total:** ~13 dias estimados (preliminar). Lead time efetivo reduzido em ~3-5 dias graças ao prep COUNCIL-12.

## Gates do Epic

### Gate G-UI
- ✅ Golden path: usuário inicia UI → escolhe WDOJ26 → clica baixar → vê progresso → summary OK
- ✅ Quinn `*qa-gate 3.x` PASS em todas
- ✅ Uma `*review-flow` GO em todas as telas
- ✅ Build `.exe` (PyInstaller --onedir) inicia em VM Windows limpa
- ✅ Pyro: latência UI ≤ 100ms (sem freeze por overhead Qt)

## Definition of Done (Epic)

- [ ] Todas as stories Done
- [ ] Quinn PASS em cada uma
- [ ] Uma GO em cada tela
- [ ] PyInstaller build smoke OK (--onedir, sem AV flag)
- [ ] README atualizado com screenshots
- [ ] Smoke UI completo em VM Windows limpa

## Riscos identificados

| Risco | Mitigação |
|-------|-----------|
| QFileDialog nativo Windows = inconsistência visual com QSS custom | Flag `DontUseNativeDialog` documentada em ADR-003 amendment (finding M9) |
| PyInstaller `--onefile` (default antigo) = startup lento + AV flag | Mudar para `--onedir` per amendment ADR-003 (finding H23) |
| public_api não suporta cancel() na UI = mentira para usuário | ADR-007a + DownloadHandle.cancel() (finding H10) — implementado em Story 1.7b |
| Atalhos Esc/F5 conflitam com input fields | Context-aware bindings + decisão Uma (finding M10) |

## Após o Epic

Próximo: **Epic 4 — Multi-asset & Library API** (WIN, equities, public_api estável, multi-symbol via multiprocessing, auto-updater, code signing).
