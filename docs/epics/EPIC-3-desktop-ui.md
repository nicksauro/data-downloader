# EPIC 3 — Desktop UI

**Status:** draft
**Owner:** 📋 Morgan
**Data criação:** 2026-05-03
**Target:** entregar UI desktop nativa (PySide6) consumindo public_api estável (Epic 1) — golden path de download via clique, não terminal. Pós-Epic 2.

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

## Stories planejadas (preliminares)

| ID | Título | Owner | Estimativa |
|----|--------|-------|------------|
| 3.1 | PySide6 shell + main window + navigation | 🖼️ Felix | 2d |
| 3.2 | Tela Download (golden path completo) | 🖼️ Felix + 🎨 Uma | 3d |
| 3.3 | Tela Catálogo (lista partições + filtros) | 🖼️ Felix + 💾 Sol | 2d |
| 3.4 | Tela Settings (env vars, paths, theme) | 🖼️ Felix + 🎨 Uma | 1d |
| 3.5 | Theming (light/dark, QSS, DontUseNativeDialog) | 🖼️ Felix + 🎨 Uma | 1d |
| 3.6 | pytest-qt setup (finding L6) + UI tests | 🧪 Quinn + 🖼️ Felix | 1d |
| 3.7 | Packaging PyInstaller `--onedir` | 🖼️ Felix + ⚙️ Gage | 2d |
| 3.8 | Métrica ui_progress_dropped + current_contract no progress | 🖼️ Felix + ⚡ Pyro | 1d |

**Total:** ~13 dias estimados (preliminar).

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
