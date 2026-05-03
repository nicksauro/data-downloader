# ADR-008 — Estratégia de distribuição da ProfitDLL

**Status:** accepted
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🗝️ Nelo, ⚙️ Gage
**Related:** ADR-001 (Python+ctypes), ADR-009 (build determinístico), MANIFEST §R12, PLAN_REVIEW C2

---

## Contexto

A `ProfitDLL.dll` (~16MB Win64, mais companions OpenSSL e arquivos `.dat` de timezone/holidays/exchange) é binária proprietária da **Nelógica**. O squad precisa decidir como o repositório lida com ela.

Restrições inegociáveis:
- **R12** — repo deve ser auto-suficiente: `git clone` + `pip install -e .` + smoke roda sem caça-aos-cliques.
- **Licença EULA Nelógica** — `profitdll/Manual/Termos*.txt` precisa ser auditado por Gage; redistribuição em repositório público pode violar.
- **Tamanho** — DLL+companions+`.dat` somam ~50MB. Versionar binários no Git incha histórico.
- **Atualizações** — Nelógica publica novas versões; squad precisa de mecanismo de bump rastreável.
- **Builds reproduzíveis** (ADR-009) — checksum da DLL precisa ser registrado.

Estado atual:
- `profitdll/` está commitado no repo, mas pasta inclui exemplos, manuais, e binários.
- `.gitignore` não tem regra clara.
- Nenhum agente verificou se EULA permite redistribuição em repo público.

---

## Opções Consideradas

### Opção A — Commitar DLL no repo (estado atual)

```
profitdll/                           # tudo versionado
├── DLLs/Win64/ProfitDLL.dll         # 16MB
├── DLLs/Win64/companions/*.dll      # ~10MB
├── *.dat                            # ~5MB
├── Manual/                          # docs
└── Exemplo Python/                  # samples
```

**Prós:**
- `git clone` é tudo — zero passos extras.
- Versão da DLL versionada com código.
- CI funciona out-of-the-box.

**Contras:**
- Histórico Git incha (cada bump vira blob de 16MB).
- **Risco legal:** redistribuição em repo público sem licença explícita é violação potencial. Nelógica nunca autorizou expressamente.
- Repos privados resolvem o legal, mas inflação Git permanece.
- Bisect lento.

### Opção B — Gitignore + script `bootstrap-dll.ps1` baixa de fonte autorizada

```
.gitignore: profitdll/DLLs/, profitdll/*.dat
scripts/bootstrap-dll.ps1            # baixa de:
  - URL configurada (release Nelógica autorizado)
  - OU storage interno autenticado (S3, Azure Blob, network share)
  - OU pasta local pré-existente (dev local)
docs/release/DLL_VERSIONS.md         # SHA256 esperados, version pinning
```

`bootstrap-dll.ps1` flow:
1. Checa `.dll-version` (versionado) → versão alvo (ex: `4.0.0.30`).
2. Checa cache local (`%LOCALAPPDATA%\data-downloader\dll-cache\<version>\`).
3. Se ausente, baixa de URL (config via env `DATA_DOWNLOADER_DLL_SOURCE`).
4. Verifica SHA256 contra `docs/release/DLL_VERSIONS.md`.
5. Copia para `profitdll/DLLs/Win64/` (ignored).

**Prós:**
- Zero risco legal — repo só tem código + docs.
- Histórico Git limpo.
- Versão da DLL pinnada via `.dll-version` + checksum.
- Suporta dev local (já tem DLL na máquina) sem download.
- CI usa secret/token para acessar fonte autorizada.

**Contras:**
- Onboard exige variável de ambiente ou prompt no primeiro `bootstrap-dll`.
- Requer infra de hosting (release Nelógica autorizado, S3, ou network share corporativo).
- CI precisa de credencial.

### Opção C — Git LFS

```
.gitattributes:
profitdll/DLLs/**/*.dll filter=lfs diff=lfs merge=lfs
profitdll/*.dat filter=lfs
```

**Prós:**
- Histórico Git fica leve (LFS armazena blobs separados).
- `git clone` ainda traz tudo (LFS faz pull automático).
- Versão da DLL versionada como qualquer arquivo.

**Contras:**
- **Mesmo risco legal de Opção A** — repo continua redistribuindo a DLL.
- LFS storage tem custo (GitHub: 1GB free, depois pago).
- Onboard exige `git lfs install` (passo extra que Quinn esquecerá em smoke checklist).
- LFS bandwidth limitado em GitHub Free.
- Bisect/diff de binário não ajuda em nada.

### Opção D — Híbrido: companions OpenSSL e `.dat` commit; ProfitDLL via bootstrap

- Companions OpenSSL são open-source com licença que permite redist.
- `.dat` files são "data" — Nelógica historicamente trata como livre (validar com Gage).
- Apenas `ProfitDLL.dll` (proprietário) via bootstrap.

**Prós:** reduz fricção do bootstrap (só 1 arquivo para baixar).
**Contras:** risco legal não desaparece; auditoria de licença fica granular e cara.

---

## Análise

| Critério | A (commit tudo) | B (gitignore+bootstrap) | C (LFS) | D (híbrido) |
|---------|-----------------|-------------------------|---------|-------------|
| Risco legal | 🔴 alto | 🟢 zero | 🔴 alto | 🟡 médio |
| Histórico Git limpo | ❌ | ✅ | ✅ | parcial |
| Onboarding (passos) | 1 | 2 | 2 | 2 |
| Versionamento da DLL | trivial | explícito (`.dll-version`) | trivial | misto |
| Custo infra | nenhum | hosting + credencial | LFS storage | hosting parcial |
| Reprodutibilidade build | trivial | requer cache | trivial | misto |
| Bisect | lento | rápido | rápido | rápido |
| Funciona offline (após bootstrap inicial) | ✅ | ✅ (cache local) | ✅ | ✅ |

**Pontos críticos:**

- **Risco legal é o critério decisivo.** O usuário pode tornar repo público em qualquer momento. Opção A e C deixam essa decisão dependente de auditoria EULA que ninguém fez. **Eliminar risco é mais barato que mitigá-lo depois.**
- **Opção D** mistura categorias e força auditoria granular — Gage vetou (conversa via Morgan).
- **Opção B** é a única que separa "código do squad" de "binário proprietário de terceiros" — separação que combina com R12 (auto-suficiência via `bootstrap-dll`) sem violar licença.

---

## Decisão

**Opção B — `.gitignore` + script `scripts/bootstrap-dll.ps1` + cache local + checksum versionado.**

### Implementação

#### `.gitignore` (adições)

```gitignore
# ProfitDLL artefatos (binários proprietários — distribuídos via bootstrap)
profitdll/DLLs/
profitdll/*.dat
profitdll/MarketHours2/
profitdll/database/
profitdll/PopupManagerV2/
profitdll/strategy/
profitdll/bin/

# Cache de bootstrap
.dll-cache/
```

#### Estrutura mantida no Git

```
profitdll/
├── README.md                  # bootstrap instructions
├── Manual/                    # docs (texto, livre)
├── Exemplo Python/            # samples Nelógica (texto, livre)
└── (DLLs/, *.dat: gitignored)

scripts/
├── bootstrap-dll.ps1          # download + checksum + copy
└── bootstrap-dll.sh           # variante WSL/CI (mesmo flow)

docs/release/
└── DLL_VERSIONS.md            # SHA256 + version pinning + URL fonte autorizada

.dll-version                   # arquivo de 1 linha: versão alvo (ex: 4.0.0.30)
```

#### `scripts/bootstrap-dll.ps1` (esqueleto)

```powershell
# bootstrap-dll.ps1 — baixa ProfitDLL conforme .dll-version
# Uso: .\scripts\bootstrap-dll.ps1 [-Source URL] [-CacheDir PATH]

param(
    [string]$Source = $env:DATA_DOWNLOADER_DLL_SOURCE,
    [string]$CacheDir = "$env:LOCALAPPDATA\data-downloader\dll-cache"
)

$ErrorActionPreference = "Stop"

# 1. Lê versão alvo
$Version = (Get-Content .dll-version -Raw).Trim()

# 2. Lê SHA256 esperado (parseado de docs/release/DLL_VERSIONS.md)
$ExpectedSha = Get-ExpectedSha -Version $Version

# 3. Cache hit?
$CachedZip = Join-Path $CacheDir "$Version\profitdll-$Version.zip"
if (Test-Path $CachedZip) {
    $ActualSha = (Get-FileHash $CachedZip -Algorithm SHA256).Hash
    if ($ActualSha -eq $ExpectedSha) {
        Write-Host "Cache hit: $Version"
    } else {
        Write-Warning "Cache corrupt — re-downloading"
        Remove-Item $CachedZip
    }
}

# 4. Download (se necessário)
if (-not (Test-Path $CachedZip)) {
    if (-not $Source) {
        throw "DATA_DOWNLOADER_DLL_SOURCE not set. See docs/release/DLL_VERSIONS.md"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $CachedZip) | Out-Null
    Invoke-WebRequest -Uri "$Source/profitdll-$Version.zip" -OutFile $CachedZip
}

# 5. Verifica checksum
$ActualSha = (Get-FileHash $CachedZip -Algorithm SHA256).Hash
if ($ActualSha -ne $ExpectedSha) {
    throw "SHA256 mismatch: expected $ExpectedSha, got $ActualSha"
}

# 6. Extrai para profitdll/
Expand-Archive -Path $CachedZip -DestinationPath profitdll/ -Force

Write-Host "Bootstrap completo — DLL versão $Version"
```

#### `docs/release/DLL_VERSIONS.md`

```markdown
# ProfitDLL Version Registry

| Version | SHA256 (zip) | Released | Notes |
|---------|--------------|----------|-------|
| 4.0.0.30 | ab12...ef89 | 2025-12-15 | First version pinned by squad |

## Distribution source

Set env var:
```
$env:DATA_DOWNLOADER_DLL_SOURCE = "https://internal-storage.example.com/profitdll"
```

Or place pre-downloaded zip in cache: `%LOCALAPPDATA%\data-downloader\dll-cache\<version>\profitdll-<version>.zip`

## Bumping version

1. Atualizar `.dll-version` para nova versão.
2. Calcular SHA256 do novo zip.
3. Adicionar linha nesta tabela.
4. Rodar `bootstrap-dll.ps1` para validar.
5. Smoke test (Quinn).
6. Aria + Nelo aprovam ADR de bump (se quirks novos detectados).
```

#### CI (Story 0.1 / Gage)

```yaml
# .github/workflows/test.yml
- name: Bootstrap ProfitDLL
  env:
    DATA_DOWNLOADER_DLL_SOURCE: ${{ secrets.DLL_DISTRIBUTION_URL }}
  run: pwsh ./scripts/bootstrap-dll.ps1
```

#### `pyproject.toml` ou `Makefile` integrate

```toml
[tool.poe.tasks]
bootstrap-dll = "pwsh ./scripts/bootstrap-dll.ps1"
```

`README.md` de quickstart manda `poe bootstrap-dll` (ou `make bootstrap-dll`).

---

## Consequências

### Positivas
- **Risco legal: zero.** Repo pode ser público sem auditoria EULA.
- **Histórico Git limpo** — bisect rápido, clone leve.
- **Versionamento explícito** — `.dll-version` + SHA256 = checksum reprodutível em ADR-009.
- **Cache local** — dev não baixa em todo `git pull`.
- **CI funciona** com secret bem configurado (Gage gerencia em Story 0.1).

### Negativas
- **Onboard exige 2 passos:** `git clone` + `bootstrap-dll`. Mitigação: `README.md` super claro + integração ao quickstart.
- **Requer hosting da DLL** — Nelógica autorizado preferencial; alternativa: storage corporativo. Decisão final: Gage + usuário (em Story 0.1).
- **CI precisa de credencial** — secret no GitHub Actions.

### Neutras
- Manual + samples Nelógica continuam no repo (texto livre).

---

## Validações requeridas

- [ ] Gage cria `bootstrap-dll.ps1` + `bootstrap-dll.sh` (Story 0.1)
- [ ] Gage configura `.dll-version` com SHA256 inicial (Story 0.1)
- [ ] Gage decide e configura source autorizado (consulta usuário)
- [ ] Gage adiciona secret no CI (Story 0.1)
- [ ] Quinn smoke: `git clone` em VM limpa + `bootstrap-dll` + smoke roda (gate Epic 1)
- [ ] Aria valida que docs/release/DLL_VERSIONS.md existe e é atualizada em bump
- [ ] README.md tem quickstart com bootstrap explícito (Uma colabora microcopy)
