# ADR-017 — Auto-updater strategy (tufup preliminar)

**Status:** accepted (deferred to Epic 4)
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🖼️ Felix, ⚙️ Gage
**Related:** ADR-009 (build determinism), ADR-016 (code signing), PLAN_REVIEW L4

---

## Contexto

Após release V1, usuário precisa receber atualizações sem re-baixar manualmente.

Demandas:
- **Detectar nova versão** disponível.
- **Baixar update** em background.
- **Aplicar update** com restart.
- **Rollback** se update corromper.
- **Signing aware** — verificar que update veio do vendor (squad).
- **Delta updates** (opcional) — baixar só diff vs versão atual.

Restrições:
- **PyInstaller `--onedir`** (após Amendment ADR-003) facilita update granular (substituir só arquivos changed).
- **Code signing** (ADR-016) — updater verifica assinatura antes de aplicar.
- **Sem servidor próprio** — preferencial: GitHub Releases ou similar gratuito.
- **Windows only V1**.

---

## Opções Consideradas

### Opção A — `tufup` (TUF-based, signing-aware)

- Implementa **The Update Framework** (TUF), padrão de signing/rollback resistance.
- Roles separadas (root, targets, snapshot, timestamp) para evitar single-key compromise.
- Backend agnóstico — funciona com S3, GitHub Releases, server simples.
- Maturidade crescente; ativa community.
- Curva de aprendizado: TUF tem conceitos (delegations, key rotation).

### Opção B — `PyUpdater` fork (mantido)

- Específico Python apps.
- Original PyUpdater abandonado (2020); existem forks ativos mas fragmentados.
- Sem TUF — segurança baseada em signature simples.
- Risco: comunidade pequena.

### Opção C — Custom polling de GitHub Releases + signing manual

```python
# Pseudo-code:
latest = github_api.get_latest_release()
if latest.tag > current_version:
    binary = download(latest.asset_url)
    if verify_signature(binary, our_pubkey):
        replace_files(binary)
        restart()
```

- Trivial conceitualmente.
- Reinventar update resilience (atomic replace, rollback).
- Security: precisa pubkey embedded; signature verification cuidadosa.

### Opção D — Sem auto-updater — usuário re-baixa manual

- Aceitável para MVP / Epic 4 inicial.
- Inviável a médio prazo (usuário esquece de atualizar; bugs persistem).

### Opção E — Windows Store (auto-update built-in)

- Já vetada (ADR-016): incompatível com DLL nativa.

### Opção F — Squirrel.Windows / Velopack

- Bibliotecas .NET focadas em apps desktop.
- Boas, mas não-Python (precisa wrapper).

---

## Análise

| Critério | A (tufup) | B (PyUpdater) | C (custom) | D (none) | F (Velopack) |
|---------|-----------|---------------|-----------|----------|--------------|
| Signing-aware | ✅ TUF | parcial | manual | n/a | ✅ |
| Rollback safety | ✅ | parcial | manual | n/a | ✅ |
| Maintained community | ativa | fragmentada | n/a | n/a | ativa (.NET) |
| Custo infra | $0 (GitHub Rel) | $0 | $0 | $0 | $0 |
| Esforço integração | médio-alto | médio | médio | baixo | alto (wrap) |
| Compatibilidade Python+ctypes | ✅ | ✅ | ✅ | ✅ | requer wrapper |
| Delta updates | ✅ | ✅ | manual | n/a | ✅ |

**Pontos críticos:**

- **Opção F** força .NET runtime — friction.
- **Opção D** OK V1, não OK V2.
- **Opção C** subestima dificuldade (atomic replace em Windows é doloroso; rollback robusto é complexo).
- **Opção B** abandono original = risco fork futuro.
- **Opção A** combina TUF (battle-tested signing) + Python-native + maintained. **Recomendação preliminar.**

---

## Decisão

**Opção A — `tufup` como recomendação preliminar.** **Status:** deferred to Epic 4 — decisão final após:
1. Bench de update flow em VM Windows.
2. Validação de TUF roles vs simplicidade.
3. Review com Felix (UI integration: notificação "Update disponível").

### Plano (esqueleto para Epic 4)

#### 1. Estrutura

```
data-downloader/
├── src/data_downloader/updater/
│   ├── __init__.py
│   ├── client.py         # tufup Client wrapper
│   ├── notifier.py       # UI notification (Felix)
│   └── installer.py      # apply-update logic
└── repository/            # TUF metadata (versionado em GitHub Releases)
    ├── metadata/
    │   ├── root.json
    │   ├── targets.json
    │   ├── snapshot.json
    │   └── timestamp.json
    └── targets/
        └── data-downloader-1.0.0.tar.gz
```

#### 2. Update flow

```
Application startup:
  ↓
  Check for updates (tufup Client.check_for_updates)
  ↓
  if update_available:
    Download in background (verify TUF signatures)
    ↓
    Notify UI (toast: "Update X.Y.Z disponível")
    ↓
    User clicks "Install" → restart with --apply-update
    ↓
    Installer replaces files atomically (.tmp + os.replace)
    ↓
    Restart
    ↓
    if startup fails 3x → rollback to previous version
```

#### 3. Signing keys (TUF roles)

- **Root key** — armazenada offline (cold storage, USB criptografado, hardware key). Rotação rara (anos).
- **Targets/Snapshot/Timestamp keys** — em CI (vendor cloud HSM, ADR-016).
- Compromise de chave online ≠ compromise total (root protege).

#### 4. UI integration (Felix Epic 4)

- Toast no canto da MainWindow: "Update X.Y.Z disponível [Instalar agora] [Mais tarde]".
- Settings screen: opt-out de auto-check.
- Microcopy: Uma cataloga em MICROCOPY_CATALOG.md.

#### 5. CLI integration

```bash
data-downloader self-update                # check + install
data-downloader self-update --check-only
data-downloader self-update --rollback     # voltar versão anterior
```

#### 6. Servidor de updates

V1: **GitHub Releases** (gratuito, hash-stable URLs).
V2 (se necessário): **S3 + CloudFront** (faster CDN; custo médio $5-20/mês).

#### 7. Telemetria

- Counter: `updates_checked_total`, `updates_applied_total`, `updates_failed_total`.
- ADR-013 cobre.

### Cross-references

- **Pré-requisito:** ADR-016 (signing) — sem signing, update verification falha.
- **Pré-requisito:** ADR-009 (build determinism) — sem build determinístico, hashes não batem.
- **Pré-requisito:** ADR-003 amendment (`--onedir`) — `--onefile` complica update granular.

---

## Consequências (quando implementado)

### Positivas
- **Update sem fricção** — usuário não precisa lembrar de baixar.
- **Security** — TUF previne man-in-the-middle, replay attack, key compromise (parcial).
- **Rollback** — bug em update reversível.
- **Telemetria** — Pyro vê adoption rate.

### Negativas
- **Setup inicial alto** — TUF roles + key ceremony.
- **Disciplina key management** — perda de root key = catástrofe.
- **CI complexity** — release pipeline assina TUF metadata.
- **UI surface** — Felix implementa notificação; Uma cataloga microcopy.

### Neutras
- Tufup ativa mas comunidade média; Aria monitora estabilidade antes de bater martelo.

---

## Validações requeridas (quando ativado)

- [ ] Aria valida tufup escolha vs alternativas pós-bench (Epic 4)
- [ ] Gage configura TUF repository + key ceremony (Epic 4)
- [ ] Gage integra signing TUF metadata em release pipeline (Epic 4)
- [ ] Felix implementa update notification UI (Epic 4)
- [ ] Uma cataloga microcopy "Update disponível" (Epic 4)
- [ ] Quinn smoke: install N → release N+1 → check → apply → restart → version=N+1 (Epic 4)
- [ ] Quinn smoke: rollback funciona após update corrompido (Epic 4)
- [ ] Documentação em `docs/release/AUTO_UPDATE.md` (Aria + Gage)

### Decisão final pendente

Aria reabre este ADR no início do Epic 4 com:
- POC de tufup em VM Windows.
- Comparação atualizada de alternativas (PyUpdater fork status, Velopack adoption).
- Decisão final: confirmar Opção A ou pivotar.
