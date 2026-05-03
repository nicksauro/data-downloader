# ADR-016 — Windows code signing & SmartScreen

**Status:** accepted (deferred to V1 release)
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** ⚙️ Gage
**Related:** ADR-009 (build determinism), ADR-008 (DLL distribution), MANIFEST §R12, PLAN_REVIEW L5

---

## Contexto

`.exe` distribuído sem assinatura no Windows resulta em:
- **SmartScreen warning** ("Windows protegeu seu PC. Aplicativo não reconhecido.") — bloqueia abertura inicial.
- **AV false positives** — Windows Defender quarantena binário aleatoriamente.
- **Sem prova de integridade** — usuário não consegue verificar que `.exe` é nosso.

Code signing resolve:
- Assinatura digital (X.509) → SmartScreen confia após reputação acumulada.
- AV vendors honram signing CAs reconhecidas.
- Hash do binário coberto pela assinatura → tampering detectável.

Custos:
- **EV (Extended Validation) certificate**: ~$300-700/ano (DigiCert, Sectigo, GlobalSign).
- **OV (Organization Validation)**: ~$80-200/ano, mas exige reputação building (semanas-meses até SmartScreen confiar).
- **Hardware token (HSM)** obrigatório para EV após 2023 (mandate Microsoft).
- Build pipeline integration.

PLAN_REVIEW L5: status **deferred** até release V1 (final do Epic 4 ou Epic 5). MVP (Epic 1-3) distribui apenas para usuário (squad-de-1) — SmartScreen warning aceitável.

---

## Opções Consideradas

### Opção A — EV cert + signing em CI release pipeline

- Assinatura confiável imediatamente (sem reputation building).
- HSM + token = setup inicial complexo.
- ~$300-700/ano ongoing.
- Microsoft Authenticode é padrão.

### Opção B — OV cert + signing + reputation building

- Mais barato ($80-200/ano).
- SmartScreen warning persiste por semanas/meses até reputation acumular.
- Não-EV certs perdendo confiança em SmartScreen.

### Opção C — Self-signed + manual install de cert

- Grátis.
- Usuário precisa importar cert manualmente.
- Não escalável.

### Opção D — Sem signing — distribuir checksum SHA256 + instruções

- Grátis.
- Usuário tem que clicar "Mais informações" → "Executar mesmo assim".
- Aceitável para audiência técnica (squad+ = trader + dev experiente).

### Opção E — Microsoft Store (assinatura + sandbox automáticos)

- Distribuição cara em compliance (UWP packaging, certificação Microsoft).
- Sandbox impede acesso DLL nativa direta (incompatível com ProfitDLL).
- **Inviável.**

---

## Análise

| Critério | A (EV) | B (OV) | C (self) | D (none) | E (Store) |
|---------|--------|--------|----------|----------|-----------|
| SmartScreen sem warning desde dia 1 | ✅ | ❌ | ❌ | ❌ | ✅ |
| AV false positives | mínimo | médio | alto | alto | mínimo |
| Custo anual | $300-700 | $80-200 | $0 | $0 | $99 dev fee |
| Setup inicial | complexo | médio | trivial | trivial | muito complexo |
| Compatibilidade ProfitDLL | ✅ | ✅ | ✅ | ✅ | ❌ |
| Tampering detection | ✅ | ✅ | ✅ | manual | ✅ |
| Scaleable distribution | ✅ | parcial | ❌ | OK | ✅ |

**Pontos críticos:**
- **Opção E** é incompatível com ctypes + DLL nativa.
- **Opção C** não escala.
- **Opção D** é viável para MVP (audiência técnica), mas não para release público.
- **Opção B** vs **A**: EV é o caminho consensual da indústria; reputation building em OV é incerto.

---

## Decisão

**Opção D para MVP (Epic 1-3); Opção A (EV cert) para release V1 (Epic 4+).** **Status:** deferred.

### Plano

#### MVP (Epic 1-3): sem signing

- Distribuição interna ao squad/usuário.
- README documenta:
  - SHA256 do `.exe` em release page (gerado por ADR-009).
  - Instruções: "Mais informações" → "Executar mesmo assim".
  - Risco aceito documentado em `docs/release/SIGNING.md`.

#### Release V1 (Epic 4+): EV cert + CI signing

##### 1. Aquisição

- Vendor: **DigiCert** ou **Sectigo** EV Code Signing.
- Custo: ~$400/ano (estimativa 2026).
- Lead time: 5-10 dias úteis (validação de organização).
- Owner: Gage executa; usuário aprova despesa.

##### 2. HSM/Token

- Após 2023 mandate: EV cert chave privada **obrigatoriamente** em HSM (hardware token, ex: SafeNet eToken 5110).
- Custo HSM: incluído na maioria dos vendors.
- CI access: opções:
  - **Vendor cloud HSM** (DigiCert KeyLocker) — preferencial; CI assina remotamente via API.
  - **Self-hosted HSM** + GitHub Actions self-hosted runner.

##### 3. Build pipeline (CI)

```yaml
# .github/workflows/release.yml
- name: Build .exe
  run: pwsh ./scripts/build-release.ps1   # ADR-009

- name: Sign .exe
  env:
    SIGNING_CERT_BASE64: ${{ secrets.SIGNING_CERT }}
    SIGNING_KEY_LOCKER_TOKEN: ${{ secrets.KEYLOCKER_TOKEN }}
  run: |
    # Via DigiCert KeyLocker CLI
    smctl sign \
      --keypair-alias data-downloader-key \
      --tool signtool \
      --input dist/data-downloader.exe \
      --tool-flags "/td sha256 /fd sha256 /tr http://timestamp.digicert.com /v"

- name: Verify signature
  run: signtool verify /pa /v dist/data-downloader.exe
```

##### 4. Verificação por usuário

```powershell
# Usuário verifica em PowerShell:
Get-AuthenticodeSignature .\data-downloader.exe
# Status: Valid
# SignerCertificate: ...  Subject: O=<Org>
```

##### 5. SHA256 redundante

Mesmo com signing, manter SHA256 publicado em release (transparência).

##### 6. Renovação

- Aviso 30 dias antes de vencimento (Gage `*release` checklist).
- Renovação anual.
- Re-sign de releases atuais (Microsoft permite re-timestamp).

### Cross-reference ADR-009

Code signing assume **build determinístico** (ADR-009). Sem reprodutibilidade:
- Re-build para investigação não bate o `.exe` assinado.
- Bug forense fica impossível.

ADR-009 é **pré-requisito** para implementar este ADR.

---

## Consequências

### Positivas (após implementação)
- **Zero SmartScreen warning** desde release V1.
- **AV false positives reduzidos** drasticamente.
- **Tampering detection** built-in (signtool verify).
- **Profissionalismo** — assinatura é expectativa de Windows desktop apps em 2026.

### Negativas
- **Custo anual** — ~$400/ano. Approval do usuário.
- **Setup inicial complexo** — HSM, vendor onboarding, CI integration.
- **Lock-in vendor** — re-emissão de cert se trocar vendor.
- **MVP sem signing** — usuário inicial vê warning.

### Neutras
- Status **deferred** até Epic 4 — decisão revisitada quando orçamento de release for discutido.

---

## Validações requeridas (quando ativado)

- [ ] Gage adquire EV cert (Epic 4)
- [ ] Gage configura CI signing pipeline
- [ ] Gage adiciona `signtool verify` em release pipeline
- [ ] Documentação em `docs/release/SIGNING.md`
- [ ] Release V1 `.exe` assinado e validado em VM Windows limpa (sem SmartScreen warning após reputation build, ~24h)
- [ ] Renewal reminder em release calendar
- [ ] CHANGELOG nota "first signed release"
