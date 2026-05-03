# ADR-009 — Build determinístico (PYTHONHASHSEED, SOURCE_DATE_EPOCH, lockfile, container)

**Status:** accepted
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** ⚙️ Gage, ⚡ Pyro
**Related:** ADR-001 (Python+ctypes), ADR-008 (DLL distribution), MANIFEST §R19, PLAN_REVIEW C3

---

## Contexto

**R19 do MANIFEST exige builds reprodutíveis.** Estado atual viola múltiplas vezes:

1. **PyInstaller default não é determinístico:**
   - Gera UUIDs em runtime para PYZ archive.
   - Timestamps embedados em PE headers refletem hora do build.
   - Ordem de bytes em `Analysis.scripts` depende de hash randomization Python.

2. **`pip install` sem lockfile é não-determinístico:**
   - `pyproject.toml` com ranges (`pyarrow>=15`) resolve para versões diferentes em dias diferentes.
   - Subdependências mudam silenciosamente.
   - Wheels podem ser substituídos no PyPI (raro, mas aconteceu — ex: `colorama` rebuild).

3. **Ambiente local difere de CI:**
   - Dev em Win11 com Python 3.12.4 + Visual Studio runtime X.
   - CI em Windows Server 2022 com Python 3.12.6 + runtime Y.
   - Build resultante difere em bytes mesmo com mesmo source.

4. **`ProfitDLL.dll` versão pode mudar entre builds** (resolve via ADR-008 com `.dll-version` + checksum).

**Impacto:** sem determinismo, não conseguimos:
- Reproduzir bugs reportados ("baixei a release v1.0.0, mas no CI o `.exe` é diferente").
- Provar que código não foi adulterado (supply-chain).
- Code-signing meaningful (ADR-016): assinatura cobre build instável.

---

## Opções Consideradas

### Opção A — Lockfile + flags determinísticas + container build oficial

```
1. Adotar uv ou pip-tools para gerar `requirements.lock` versionado.
2. Setar PYTHONHASHSEED=0 e SOURCE_DATE_EPOCH no build script.
3. PyInstaller spec com flags determinísticas (`--noupx`, custom seed).
4. Build oficial (release) só roda em container Windows fixo (Docker Windows ou GitHub Actions windows-2022 versão pinnada).
5. Checksum SHA256 de cada release publicado em GitHub Release notes.
```

### Opção B — Apenas lockfile, sem container

- Resolve parcialmente: dependências fixas, mas runtime ainda varia.
- Build local + CI ainda divergem em PE headers.

### Opção C — Reprodutibilidade "best-effort" sem garantia bit-exata

- Documentar dependências fixas em `pyproject.toml` (versões exatas).
- Aceitar que PyInstaller varia.
- Contornar com checksum funcional (smoke test passa) em vez de checksum byte-exato.

### Opção D — Trocar PyInstaller por Nuitka ou Briefcase

- Nuitka tem mais flags determinísticas mas curva de aprendizado alta.
- Briefcase é Python-puro mas menos maduro para Qt + ctypes.
- Risco: mudança de tooling de packaging atrasa Epic 3.

---

## Análise

| Critério | A (lock+container) | B (só lock) | C (best-effort) | D (Nuitka) |
|---------|--------------------|-------------|-----------------|------------|
| Reprodutibilidade bit-exata | ✅ | parcial | ❌ | parcial |
| Esforço inicial | médio-alto | médio | baixo | alto |
| Compatibilidade Qt+ctypes | ✅ (testado) | ✅ | ✅ | risco |
| CI cost | médio | baixo | baixo | médio |
| Auditável (forense) | ✅ | parcial | ❌ | parcial |
| Code-sign meaningful (ADR-016) | ✅ | parcial | ❌ | parcial |
| Bloqueia bug "no meu PC funciona" | ✅ | parcial | ❌ | parcial |

**Pontos críticos:**

- **Opção C** falha o objetivo central — "best-effort" significa "não garantido", e R19 exige garantia.
- **Opção D** muda toolchain crítica — Felix usa PyInstaller (ADR-003); risco alto demais para Epic 1/3.
- **Opção B** sozinha não resolve PE headers diferentes — bug clássico de "checksum não bate por 4 bytes".
- **Opção A** combina os 3 níveis (deps, runtime, env) que afetam reprodutibilidade. **Escolhida.**

---

## Decisão

**Opção A — Lockfile + flags determinísticas + container/CI fixo para release oficial.**

### Implementação

#### Camada 1: Lockfile

**Tool:** `uv` (preferencial) ou `pip-tools` (fallback).

```
# pyproject.toml mantém ranges semânticos (legibilidade)
[project]
dependencies = [
    "pyarrow>=15,<17",
    "duckdb>=1.0,<2",
    ...
]

# requirements.lock — versionado, gerado por uv pip compile
pyarrow==16.1.0 --hash=sha256:abc...
duckdb==1.1.3 --hash=sha256:def...
# (todas as transitivas + hashes)
```

CI install usa **somente** `requirements.lock`:
```bash
uv pip sync requirements.lock
```

Bump de dep:
1. Edita `pyproject.toml`.
2. Roda `uv pip compile pyproject.toml -o requirements.lock`.
3. Commit lockfile junto.
4. PR review inclui diff do lockfile.

#### Camada 2: Variáveis determinísticas

Build script (`scripts/build-release.ps1`):
```powershell
$env:PYTHONHASHSEED = "0"
$env:SOURCE_DATE_EPOCH = "1700000000"   # epoch fixo do "release time" — pinado por release tag
$env:PYTHONDONTWRITEBYTECODE = "1"

# PyInstaller
pyinstaller `
    --noconfirm `
    --noupx `                        # UPX comprime não-deterministicamente
    --clean `
    build/data_downloader.spec
```

`SOURCE_DATE_EPOCH` é pinado pela tag git do release (ex: `git log -1 --format=%ct v1.0.0` → epoch). CI usa esse valor.

#### Camada 3: PyInstaller spec determinístico

```python
# build/data_downloader.spec (Felix mantém)
import os
os.environ['PYTHONHASHSEED'] = '0'

a = Analysis(
    ['src/data_downloader/cli.py'],
    pathex=[],
    binaries=collect_dlls(),
    datas=collect_dat_files(),
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# Sort scripts/binaries para ordem determinística
a.scripts = sorted(a.scripts, key=lambda x: x[0])
a.binaries = sorted(a.binaries, key=lambda x: x[0])
a.datas = sorted(a.datas, key=lambda x: x[0])

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    name='data-downloader',
    debug=False,
    upx=False,         # CRÍTICO: UPX não-determinístico
    console=True,
    icon='build/icon.ico',
)
```

#### Camada 4: Container build oficial

Releases (Story 4.x via Gage) só rodam em **GitHub Actions** com:
```yaml
runs-on: windows-2022   # imagem versionada, não 'windows-latest'
strategy:
  matrix:
    python-version: ['3.12.6']   # versão exata
```

Para reprodutibilidade local:
- Documenta passo "rodar smoke build em container Docker Windows" (opcional, dev avançado).
- Default: dev confia que `requirements.lock` + `SOURCE_DATE_EPOCH=<release tag epoch>` reproduz aceitavelmente.
- Garantia bit-exata: apenas em CI windows-2022 + python-3.12.6.

#### Camada 5: Verificação

Script `scripts/verify-build.ps1`:
```powershell
# Compara dois builds
$Sha1 = (Get-FileHash dist/data-downloader.exe).Hash
$Sha2 = (Get-FileHash dist/data-downloader-rebuild.exe).Hash
if ($Sha1 -ne $Sha2) {
    throw "Build não-determinístico: $Sha1 != $Sha2"
}
```

CI roda `verify-build` rebuilding 2x — falha se diferentes.

---

## Consequências

### Positivas
- **Reprodutibilidade bit-exata** em ambiente CI controlado.
- **Bug forense** — "baixou da release v1.0.0; SHA256 confere; é nosso código".
- **Code-sign meaningful** (ADR-016 quando vier).
- **Supply-chain protection** — wheel substituído no PyPI = lockfile detecta.
- **CI cache eficiente** — lockfile permite cache de wheels.

### Negativas
- **Esforço inicial** — Gage configura uv + lockfile + spec ajustado.
- **Bump de dep mais cerimonioso** — atualizar `pyproject.toml` + recompilar lock + commit.
- **Local ≠ CI** garantido apenas via container Docker Windows (não trivial em laptop sem Docker Desktop). Aceitável: smoke local não exige bit-exact.
- **`SOURCE_DATE_EPOCH` epoch fixo** desalinha PE timestamp do "agora" — alguns AVs usam timestamp como heuristic; mitigação: documentar em release notes.

### Neutras
- Decisão entre `uv` vs `pip-tools` é detalhe de implementação (Gage decide em Story 0.1; preferência: `uv` por velocidade).

---

## Validações requeridas

- [ ] Gage adiciona `requirements.lock` versionado (Story 0.1)
- [ ] Gage cria `scripts/build-release.ps1` com env vars determinísticas
- [ ] Felix ajusta `build/data_downloader.spec` com sorts + `upx=False`
- [ ] CI roda `verify-build.ps1` (2 builds, mesmo SHA256) — gate Epic 3
- [ ] Quinn property test: build em VM limpa + cold cache produz mesmo SHA256 que CI release (gate release V1)
- [ ] Documentação em `docs/release/BUILD.md` de como reproduzir (Gage)
- [ ] Pre-push hook checa que `requirements.lock` foi atualizado se `pyproject.toml` mudou (Gage)
