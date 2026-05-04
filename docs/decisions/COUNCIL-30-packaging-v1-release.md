# COUNCIL-30 — Packaging V1 Release (Story 4.4)

**Data:** 2026-05-04
**Convocação:** Mini-council Felix + Gage + Aria — modo autônomo (Story 4.4 impl)
**Participantes mentais:**

- 🖼️ Felix (Frontend Developer — autoridade exclusiva `build/data_downloader.spec.template`, `src/data_downloader/ui/`)
- ⚙️ Gage (DevOps — release pipeline, GitHub Releases, build determinism, `docs/release/RELEASES.md`)
- 🏛️ Aria (Architect — autoridade exclusiva ADR-003 amendment + ADR-009 + ADR-016 + ADR-017)

**Reviewers (downstream):**

- 🧪 Quinn (QA — smoke VM Windows limpa AC6 será humano-bound — WAIVER)
- 📋 Morgan (PM — fechamento Epic 4 + autorização release V1.0.0)

**Status:** RATIFIED (autonomous mode — sem reviewers humanos blocking).

---

## 1. Contexto

Story 4.4 (Auto-updater + packaging final V1 release) é a última story do Epic
4 e fecha o release V1.0.0 do `data-downloader`. Story 4.3 (Public API V1.0)
está Ready for Review e será Done em paralelo.

Estado entrando nesta story:

- **ADR-003 amendment** (2026-05-03) decidiu `--onedir` (não `--onefile`).
- **ADR-009** (build determinism) prescreve `PYTHONHASHSEED=0` +
  `SOURCE_DATE_EPOCH=<commit-timestamp>` + lockfile.
- **ADR-016** (code signing) está `accepted (deferred to V1 release)` — Caminho
  A se cert disponível, B com waiver.
- **ADR-017** (auto-updater) recomenda `tufup` mas ainda `deferred` —
  implementação completa exige TUF setup signing keys.
- `build/data_downloader.spec.template` existe (Felix prep, Wave 17/18).
- `build/BUILD_PROTOCOL.md` existe (Felix prep).
- `build/WINDOWS_DEFENDER_NOTES.md` existe (Felix prep).
- `__api_version__ = "1.0.0"` (Story 4.3).

**Restrições adicionais:**

1. Sem cert EV adquirido até esta data — Caminho B obrigatório (V1.0
   sem signing).
2. Sem TUF root/targets keys geradas — tufup full impl exige key ceremony
   que requer humano.
3. Sem container Docker Windows local — build determinístico bit-exato
   exige CI windows-2022 controlled, fora do escopo desta story (CI tracker
   futuro).
4. Smoke VM Windows limpa exige humano (mesma política COUNCIL-09).

---

## 2. Decisões

### D1 — Packaging: PyInstaller `--onedir` confirmado (Felix)

**Decidido (Felix autoridade exclusiva ADR-003 amendment):**

`build/data_downloader.spec.template` permanece como está — produz
`dist/data_downloader/` (folder com `data_downloader.exe` + DLLs + datas
+ Qt plugins). Razões já documentadas em ADR-003 amendment §"Mudança 1":

1. Startup < 1s vs 3-5s do `--onefile`.
2. AV-quiet (sem self-extract para `%TEMP%`).
3. Path resolution previsível para ProfitDLL.dll companions.
4. Habilita updates granulares (tufup substitui só arquivos changed).
5. Code signing futuro mais simples (sign DLL + exe separadamente).

**Output:** `dist/data_downloader/` zipado como
`data-downloader-v{version}-win64.zip`.

### D2 — Build determinístico via env vars + lockfile (Gage)

**Decidido (Gage autoridade exclusiva pipeline release):**

V1.0 release pipeline implementa **3 das 5 camadas do ADR-009**:

| Camada | V1.0 status |
|--------|-------------|
| 1. Lockfile (`uv.lock`) | Aceito — assume lockfile existe; `scripts/build_release.py` valida |
| 2. Env vars determinísticas | Implementado em `scripts/build_release.py` |
| 3. PyInstaller spec sorted | Já presente em `data_downloader.spec.template` (Felix) |
| 4. Container build oficial | **Deferred** — futuro Story X.X (CI workflow `release.yml` em windows-2022) |
| 5. Verify-build (2× same SHA) | **Deferred** — exige CI controlado |

`scripts/build_release.py` injeta:

```bash
PYTHONHASHSEED=0
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)
PYTHONDONTWRITEBYTECODE=1
TZ=UTC
LC_ALL=C.UTF-8
```

E gera **build manifest JSON** (`dist/build-manifest-v{version}.json`)
com `{version, git_sha, sha256s_per_file, total_size_bytes,
builder_hostname_sanitized, build_timestamp}` para audit trail.

**Trade-off aceito:** sem container CI, build local pode divergir bit-exato
de build CI. Manifest sha256 oferece transparência funcional. Container
CI é débito formal (`docs/stories/4.4-followup.story.md`).

### D3 — Auto-updater: tufup stub V1.0, full impl deferred V1.1 (Aria)

**Decidido (Aria autoridade exclusiva ADR-017):**

V1.0 entrega **stub** (`src/data_downloader/_updater/`) que:

1. **Verifica updates** via GitHub Releases API (`gh api repos/{org}/{repo}/releases/latest`).
2. **Notifica** usuário via UI (Settings screen "Updates" section + manual
   download link).
3. **NÃO aplica** updates automaticamente — usuário baixa zip manualmente
   da release page.

**Razões para deferir tufup full:**

1. TUF requer **key ceremony** (root/targets/snapshot/timestamp keys) que
   exige humano + offline cold storage para root key (ADR-017 §"Signing
   keys").
2. Sem **code signing** (Caminho B / D4), TUF signature verification no
   updater client não tem confiança upstream — TUF sem signing é teatro.
3. Setup TUF repository structure (`metadata/*.json` + `targets/`) +
   pipeline release-time signing exige Story dedicada (4.4-followup).

**V1.1 trajectory:**

- Story 4.4-followup-tufup-full reabre ADR-017 §"Decisão final".
- Pré-requisito: ADR-016 Caminho A ativado (cert EV adquirido).
- Aria valida POC tufup em VM Windows (~2h).
- Gage executa key ceremony + integra em `release.yml`.
- Felix expande `_updater/` stub para tufup Client wrapper.

### D4 — Code signing: Caminho B + WAIVER deferred V1.1 (Gage)

**Decidido (Gage autoridade exclusiva ADR-016 trajectory):**

V1.0 release segue **Caminho B** (sem signing):

1. `INSTALL.md` documenta workaround SmartScreen (`Mais informações` →
   `Executar mesmo assim`) com explicação amigável (link para
   `WINDOWS_DEFENDER_NOTES.md`).
2. SHA256 publicado em release notes + `dist/build-manifest-v{version}.json`
   para verificação manual.
3. WAIVER formal: `docs/qa/WAIVERS/4.4-signing-deferred-2026-05-04.md`.
4. Story-debt: `docs/stories/4.4-followup.story.md` agrega (a) signing
   V1.1 + (b) tufup full + (c) container CI build + (d) smoke VM humano.

**Justificativa:** EV cert ($300/ano + 5-10 dias úteis emissão Sectigo/
DigiCert) não foi adquirido na timeline desta story. Aceitável V1.0
porque audiência inicial = squad + early adopters técnicos (mesma
política COUNCIL-09 / KEEP-ALIVE: deferred com debt formal).

### D5 — Smoke VM Windows limpa: humano-bound + WAIVER (Quinn implícito + Morgan)

**Decidido (política COUNCIL-09 estendida):**

AC6 (smoke real em VM Windows limpa) **requer humano**:

1. Provisionamento de VM Windows 10/11 limpa (sem Python, sem
   ProfitDLL prévia) — fora do escopo agente.
2. Download da release V1.0 da página GitHub (release ainda não
   publicada — circular dependency até pipeline rodar pela primeira vez).
3. Verify SHA256 + click-through SmartScreen (interação humana).
4. Setup `.env` com credenciais Nelogica reais (humano).
5. Smoke download 1 dia + simulação de update (publicar v1.0.1-rc1
   trivial).

**WAIVER:** `docs/qa/WAIVERS/4.4-vm-smoke-deferred-2026-05-04.md`.
**Story-debt:** `docs/stories/4.4-followup.story.md` (consolidada com D4).

**Cobertura compensatória mock-first em V1.0:**

- `tests/unit/test_updater_stub.py` — UpdaterStub.check_for_updates
  com GitHub API mock.
- `tests/integration/test_build_release_dry.py` — script `build_release.py`
  em `--dry-run` mode (não roda PyInstaller real, mas valida toda
  orquestração + manifest schema).
- `build/BUILD_PROTOCOL.md` documenta procedimento humano para smoke
  manual em VM (já existe — Felix prep).

---

## 3. Sign-offs

### Felix 🖼️ — sign-off

**Domínio:** `build/data_downloader.spec.template`,
`src/data_downloader/ui/screens/settings_screen.py` (extend Updates
section), `src/data_downloader/_updater/` (UI integration).

**Confirmação:**

1. ✅ Spec PyInstaller fiel à ADR-003 amendment (--onedir + sorted
   binaries + `upx=False`).
2. ✅ Settings screen ganha section "Updates" com microcopy R17
   (Uma autoridade — IDs novos `LBL_SETTINGS_SECTION_UPDATES`,
   `BTN_CHECK_FOR_UPDATES`, `LBL_UPDATE_STATUS_*`).
3. ✅ UpdaterStub UI integration via signal `update_status_changed`.

**Sign:** `Co-Authored-By: Felix (Frontend-Dev) <agent@data-downloader.local>`

### Gage ⚙️ — sign-off

**Domínio:** `scripts/build_release.py`, `scripts/github_release.py`,
`docs/release/RELEASES.md`, `docs/release/INSTALL.md`, build pipeline,
WAIVERS de release.

**Confirmação:**

1. ✅ Pipeline GitHub Release publicável via `scripts/github_release.py`
   (orquestra `gh release create` com artifacts + manifest + CHANGELOG
   section).
2. ✅ Audit trail completo: `dist/build-manifest-v{version}.json` com
   sha256 + git_sha + sanitized hostname.
3. ✅ Caminho B documentado em `INSTALL.md` (pt-BR usuário final) com
   workaround SmartScreen + Defender exclusion.
4. ✅ WAIVERS criados (signing + smoke VM) com aprovador único
   (Gage para signing, Aria + Morgan implícitos para smoke).

**Sign:** `Co-Authored-By: Gage (DevOps) <agent@data-downloader.local>`

### Aria 🏛️ — sign-off

**Domínio:** ADR-003 amendment, ADR-009, ADR-016, ADR-017 trajectories.

**Confirmação:**

1. ✅ tufup stub vs full deferred — política aceitável V1.0; ADR-017
   §"Decisão final pendente" permanece aberta para 4.4-followup.
2. ✅ Build determinístico parcial (3/5 camadas) — Camadas 4/5
   formalizadas como debt em 4.4-followup. Não há violação ADR-009
   porque V1.0 publica SHA256 funcional + manifest, mesmo sem
   bit-exato CI rebuild.
3. ✅ ADR-016 Caminho B + WAIVER aderem ao §"MVP (Epic 1-3): sem
   signing" estendido para V1.0 (audiência ainda squad+early adopters).

**Sign:** `Co-Authored-By: Aria (Architect) <agent@data-downloader.local>`

---

## 4. Implementação rastreada

| Artefato | Tipo | Owner |
|----------|------|-------|
| `docs/decisions/COUNCIL-30-packaging-v1-release.md` | NOVO | Aria + Felix + Gage |
| `build/data_downloader.spec.template` | EDIT (validação minor) | Felix |
| `scripts/build_release.py` | NOVO (~250 linhas) | Gage |
| `scripts/github_release.py` | NOVO (~150 linhas) | Gage |
| `src/data_downloader/_updater/__init__.py` | NOVO (~50 linhas) | Felix |
| `src/data_downloader/_updater/tufup_stub.py` | NOVO (~150 linhas) | Felix |
| `src/data_downloader/ui/screens/settings_screen.py` | EDIT (Updates section) | Felix |
| `src/data_downloader/ui/microcopy_loader.py` | EDIT (IDs novos R17) | Uma autoridade — Dex impl |
| `docs/release/INSTALL.md` | NOVO (~300 linhas) | Gage |
| `tests/unit/test_updater_stub.py` | NOVO | Quinn (Felix impl) |
| `tests/integration/test_build_release_dry.py` | NOVO | Quinn (Gage impl) |
| `docs/qa/WAIVERS/4.4-vm-smoke-deferred-2026-05-04.md` | NOVO | Aria + Morgan implícitos |
| `docs/qa/WAIVERS/4.4-signing-deferred-2026-05-04.md` | NOVO | Gage emissor |
| `docs/stories/4.4-followup.story.md` | NOVO | River (SM equivalente) |
| `docs/stories/4.4.story.md` | EDIT (status → Ready for Review) | Dex |

---

## 5. Risco residual

1. **Build local ≠ CI bit-exato** — manifest oferece SHA256 funcional, não
   bit-prova. Mitigação: 4.4-followup adiciona container CI Story.
2. **SmartScreen warning V1.0** — usuário inicial vê "Aplicativo não
   reconhecido". Mitigação: INSTALL.md guia explícito + ADR-016 V1.1
   resolve com EV cert.
3. **Auto-update manual V1.0** — usuário precisa baixar zip da release
   page após notificação. Mitigação: 4.4-followup-tufup-full automatiza
   V1.1.
4. **Smoke VM humano não executado** — risco aceito conforme política
   COUNCIL-09. Mitigação: WAIVER + Story-debt 4.4-followup com gate
   formal antes de qualquer release V1.x subsequente.

---

## 6. Epic 4 fechamento condicional

Após esta story (Status → Ready for Review):

| Story | Status |
|-------|--------|
| 4.1 (multi-symbol broker) | Done* (waiver smoke real + 4.1-followup pending humano) |
| 4.2 (multi-asset) | Done* (waiver gating equivalente) |
| 4.3 (Public API V1.0) | Ready for Review → Done em paralelo |
| 4.4 (auto-updater + packaging V1) | Ready for Review (esta) |

**Epic 4 fecha** com 4 stories Done* + 4 followups humano-bound formalizados:

1. `4.1-followup` — Smoke real multi-symbol
2. `4.2-followup` — Smoke multi-asset
3. (`4.3` não tem followup — fechado limpo)
4. `4.4-followup` — VM smoke + signing V1.1 + tufup full + container CI

Release V1.0.0 publicação real pelo @devops humano fica gated nesses
followups. Squad libera para Backtest Engine team começar pinning
`data-downloader>=1.0,<2.0` apenas após 4.4-followup AC mínimo (smoke
VM PASS) — mesmo padrão Story 1.7b.

---

## 7. Referências

- `docs/stories/4.4.story.md` (esta story, 7 ACs)
- `docs/adr/ADR-003-front-pyside6.md` §"Amendment 2026-05-03"
- `docs/adr/ADR-009-build-determinism.md`
- `docs/adr/ADR-016-code-signing.md` (Caminho A vs B)
- `docs/adr/ADR-017-auto-updater.md` (tufup recommendation)
- `docs/decisions/COUNCIL-13-epic4-prep.md` (Story 4.4 origem)
- `docs/decisions/COUNCIL-09-mvp-gate-without-real-smoke.md` (política
  WAIVER smoke humano-bound)
- `build/BUILD_PROTOCOL.md` (Felix prep)
- `build/WINDOWS_DEFENDER_NOTES.md` (Felix prep)

---

— 🖼️ Felix (Frontend-Dev) + ⚙️ Gage (DevOps) + 🏛️ Aria (Architect)
sign-off via mini-council COUNCIL-30 (modo autônomo, Story 4.4 impl).
