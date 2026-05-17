# data-downloader

[![CI](https://github.com/nicksauro/data-downloader/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/nicksauro/data-downloader/actions/workflows/test.yml)
[![Release](https://github.com/nicksauro/data-downloader/actions/workflows/release.yml/badge.svg)](https://github.com/nicksauro/data-downloader/actions/workflows/release.yml)

> Downloader de histórico de ativos via **ProfitDLL** (Nelogica).
> Fundação para todos os projetos de quant/backtest/research que vierem.

**Versão:** 1.3.0 (UX excepcional + parquet híbrido)
**Plataforma:** Windows x64 (a DLL é Windows-only)
**Squad:** 10 agentes — vide `agents/`

---

## ✨ What's new

**v1.3.0 — UX excepcional + parquet híbrido (BIG COUNCIL round 4):**
- 📦 **Parquet híbrido mensal + diário** — `{ex}/{sym}/{YYYY}/{MM}.parquet` quando o mês está completo, `{ex}/{sym}/{YYYY}/{MM}/{DD}.parquet` durante o mês corrente / downloads parciais / ranges intra-mês. Auto-compact ao fechar um mês (`maybe_compact_month` atômico: tmp + `os.replace` + fsync + SHA256 + recovery na boot via tabela `compactions`). ADR-025. Pichau directive: "rigidamente implementar e testar" → T1-T9 + property test Hypothesis (50 seeds, 3 invariantes: conservação, exclusividade mútua, consistência catálogo↔FS). (Backtest fica feliz: read único do mês fechado, granularidade diária no mês corrente.)
- 🐛 **5 bugs corrigidos:** catálogo vazio após download via UI (data_dir mismatch — `Path.cwd()` em vez de `user_data_dir()`); DLL "desconectada" no statusbar durante download (agora observer 5-state em tempo real); cancelar agora avisa "aguardando dia atual terminar (~60s)"; ícone do projeto no exe/atalho/taskbar; atalho desktop criado pelo Setup (`{commondesktop}`→`{autodesktop}`, era read-only em non-admin).
- ✨ **UX excepcional:** onboarding wizard de 3 telas no 1º run (Welcome / Credenciais / Done); StorageIndicator no statusbar (espaço livre, cores semânticas verde/amarelo/vermelho); ProgressCard polish (hierarquia tipográfica, ícones, cores dinâmicas, segmented progress bar verde/amarelo); CTA "Ver no catálogo" ao concluir.
- ⚡ **Performance:** `_ROW_GROUP_SIZE` 100k→1M (+30% parquet write throughput); `gc.freeze()` entre chunks (7-12% menos tempo total em downloads de 30+ dias); write-once quando partition tem `day` (sem read-merge-rewrite O(N²) — 700ms→50ms por dia de WDOFUT).
- ✅ Suite: ruff 0 / mypy --strict 0 (**90 files**) / **1222 unit + 494 integration + 65 property, 0 fail**.

**v1.2.0 (anterior):** translate_failures≈0 (Q-DRIFT-40), resume funcional, chunk_ledger diário, períodos extensos desde 2018, dead-code removed (~2034 LOC broker).

**v1.1.1 (hotfix anterior):** crash do app GUI ao "Baixar" — DLL singleton (Q08-E) + stdio em frozen windowed (Q-DRIFT-39).
**v1.1.0 (base):** consolidação v1.0.0→v1.0.7 + BIG COUNCIL rounds 1-2; bundle 56% menor; `--healthcheck`; ADR-023 (chunk 1d); ADR-018/021/024.

Detalhes completos: [`CHANGELOG.md`](CHANGELOG.md).

---

## 📥 Install (v1.3.0)

A v1.3.0 é distribuída via **Setup.exe** (InnoSetup, ainda não-assinado — code signing diferido para v1.4.0). Baixe da release page:

```
https://github.com/nicksauro/data-downloader/releases/latest
```

Execute `Setup.exe` e siga o wizard. Caminho default de instalação:

```
%LOCALAPPDATA%\Programs\data-downloader\
```

Após instalação, a `ProfitDLL.dll` companion fica em
`%LOCALAPPDATA%\Programs\data-downloader\profitdll\DLLs\Win64\` e os
secrets de credenciais Nelogica em `~\.data-downloader\.env` (perfil de
usuário, fora da pasta de instalação — preservado em upgrades).

Detalhes (SmartScreen workaround, exclusão Defender, troubleshooting):
[`docs/release/INSTALL.md`](docs/release/INSTALL.md).

---

## 🚀 Quick start (v1.1.0)

```powershell
# 1. Healthcheck — confirma que a instalação está saudável (imports + structlog OK)
data_downloader-cli.exe --healthcheck
# exit 0 = OK; exit 1 = ver mensagem de erro

# 2. Abrir UI
data_downloader.exe

# 3. Smoke download (CLI) — 5 dias úteis WDOFUT, 1-3 minutos
data_downloader-cli.exe download --symbol WDOFUT --start 2026-04-28 --end 2026-05-02

# 4. Verificar versão
data_downloader-cli.exe --version
```

Configure credenciais Nelogica antes do primeiro download — abra a UI e siga o onboarding banner ("Configurar Credenciais"), ou edite `~\.data-downloader\.env` manualmente. O arquivo tem três entradas no formato `NOME=valor` (uma por linha, sem aspas):

- `PROFITDLL_KEY` — sua chave de licença Nelogica
- `PROFITDLL_USER` — seu usuário ProfitChart
- `PROFITDLL_PASS` — sua senha ProfitChart

> **Nunca** commite o `.env` — ele fica fora do repositório por padrão (`.gitignore`).

---

## 🎯 Promessa

**Para o usuário final:**
> Selecionar símbolo + período + clicar 1 botão + aguardar.

**Para projetos downstream (backtest, signals, risk, research):**
> Ler histórico via DuckDB com schema estável, sem duplicatas, sem gaps inesperados, idempotente, versionado.

---

## 📚 Documentação

Toda a governança e arquitetura estão em `docs/`. Ordem sugerida de leitura:

1. **[docs/MANIFEST.md](docs/MANIFEST.md)** — carta do squad, princípios inegociáveis (R1..R20)
2. **[docs/ROLES.md](docs/ROLES.md)** — matriz de autoridade (quem aprova o quê)
3. **[docs/WORKFLOW.md](docs/WORKFLOW.md)** — story lifecycle, gates, padrões cross-agent
4. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — camadas, thread model, invariantes
5. **[docs/adr/](docs/adr/)** — 7 ADRs seed (Python 3.12, Parquet+DuckDB+SQLite, PySide6, particionamento, threads, contratos, public_api)
6. **[docs/epics/EPIC-1-foundation.md](docs/epics/EPIC-1-foundation.md)** — primeiro epic
7. **[docs/stories/](docs/stories/)** — stories detalhadas 1.1..1.7

### Documentação por agente
- 🗝️ **Nelo** (DLL): `docs/dll/PROFITDLL_KNOWLEDGE.md`, `docs/dll/QUIRKS.md` (a popular conforme stories rodam)
- 💾 **Sol** (storage): `docs/storage/SCHEMA.md`, `docs/storage/CONTRACTS.md`, `docs/storage/INTEGRITY.md`
- 🎨 **Uma** (UX): `docs/ux/PRINCIPLES.md`, `docs/ux/FLOWS.md`, `docs/ux/WIREFRAMES.md`, `docs/ux/MICROCOPY.md`, `docs/ux/THEME.md`
- ⚡ **Pyro** (perf): `docs/perf/BASELINES.md`, `docs/perf/REPORTS/`
- 🧪 **Quinn** (QA): `docs/qa/QA_REPORTS/`, `docs/qa/INTEGRITY_REPORTS/`
- ⚙️ **Gage** (release): `docs/release/RELEASES.md`, `docs/release/AUDIT.md`

---

## 🤖 Squad (10 agentes)

| Ícone | Agente | Persona | Domínio |
|-------|--------|---------|---------|
| 🗝️ | `profitdll-specialist` | **Nelo** (The Keeper) | ProfitDLL — manual + quirks |
| 💾 | `storage-engineer` | **Sol** (The Custodian) | Parquet + DuckDB + SQLite + contratos |
| 🏛️ | `architect` | **Aria** (The Cartographer) | Arquitetura, ADRs, fronteiras |
| 🎨 | `ux-design-expert` | **Uma** (The Empath) | UX, wireframes, microcopy |
| 🖼️ | `frontend-dev` | **Felix** (Builder of Surfaces) | PySide6, theming, packaging UI |
| 💻 | `dev` | **Dex** (The Builder) | Backend Python (dll, orchestrator, public_api) |
| 🧪 | `qa` | **Quinn** (The Gatekeeper) | Code review + data integrity |
| ⚡ | `perf-engineer` | **Pyro** (The Optimizer) | Throughput, latência, baselines |
| 📋 | `pm` | **Morgan** (The Orchestrator) | Epics, stories, priorização |
| ⚙️ | `devops` | **Gage** (The Releaser) | git push, packaging, CI, secrets (EXCLUSIVO) |

**Quem aprova o quê:** `docs/ROLES.md`.
**Quem decide arquitetura:** Aria (com consulta a Nelo/Sol/Uma) → ADRs em `docs/adr/`.
**Quem audita DLL:** Nelo (autoridade exclusiva).
**Quem audita storage:** Sol (autoridade exclusiva).
**Quem dá veredito de QA:** Quinn (autoridade exclusiva).
**Quem faz `git push`:** Gage (monopólio — outros agentes commitam local).

---

## 🏗️ Estrutura

```
data-downloader/
├── agents/                       # 10 personas (markdown)
├── profitdll/                    # SDK Nelogica (DLL Win64 + manual + exemplos)
├── docs/                         # governança + arquitetura + stories
│   ├── MANIFEST.md               # leis R1..R20
│   ├── ROLES.md
│   ├── WORKFLOW.md
│   ├── ARCHITECTURE.md
│   ├── adr/                      # ADR-001..007
│   ├── epics/                    # EPIC-1, EPIC-2, ...
│   ├── stories/                  # N.M.story.md
│   ├── dll/                      # Nelo
│   ├── storage/                  # Sol
│   ├── ux/                       # Uma
│   ├── perf/                     # Pyro
│   ├── qa/                       # Quinn
│   ├── release/                  # Gage
│   └── decisions/                # vetos, mediações (Morgan)
├── src/data_downloader/
│   ├── dll/                      # ctypes wrapper (audit Nelo)
│   ├── orchestrator/             # chunking, retry, calendar
│   ├── storage/                  # Parquet + DuckDB + SQLite (audit Sol)
│   ├── public_api/               # SemVer separado (Aria)
│   ├── ui/                       # PySide6 (Felix; UX Uma) — Epic 3+
│   └── cli.py                    # typer
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── property/                 # Hypothesis
│   ├── smoke/                    # E2E contra DLL real (gated por env)
│   └── fixtures/
├── benchmarks/                   # Pyro
├── build/                        # PyInstaller spec (Gage)
├── data/                         # gitignored — gerado pelo download
│   └── history/{exchange}/{symbol}/{year}/{month}.parquet
├── pyproject.toml
└── .env.example
```

---

## ⚙️ Pré-requisitos

- **Windows x64** (a DLL é Win32/Win64; este projeto usa Win64).
- **Python 3.12+** (PEP 604 estendido, performance gains).
- **Chave de licença ProfitDLL** (Nelogica) — não distribuída no repo.
- **Git**.

---

## 🚀 Setup (após Story 1.1 estar `Done`)

```powershell
# Clonar
git clone <repo>
cd data-downloader

# Ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instalar (modo dev)
pip install -e ".[dev,test]"

# Configurar credenciais
cp .env.example .env
# Editar .env com chave ProfitDLL

# Rodar testes
pytest

# Rodar lint
ruff check src/ tests/
mypy src/
```

---

## 🎬 Uso planejado (após Story 1.7 — MVP gate)

```powershell
# Baixar 5 dias úteis de mini-dólar (continuous future, recomendado)
data-downloader download --symbol WDOFUT --start 2026-04-28 --end 2026-05-02

# Resumir job interrompido
data-downloader download --resume <job_id>

# Ver catálogo
data-downloader catalog status

# Resolver contrato vigente
data-downloader contracts vigent WDO 2026-04-15
# → "WDOJ26"

# Validar contrato contra DLL
data-downloader contracts validate WDO WDOJ26
```

Em projetos downstream:

```python
from data_downloader.public_api import read, vigent_contract
from datetime import datetime

contract = vigent_contract('WDO', date(2026, 4, 15))
table = read(contract, datetime(2026, 4, 1), datetime(2026, 4, 15))
# pyarrow.Table com schema versionado, sem duplicatas, ordenado por timestamp_ns
```

---

## 🎯 Roadmap (visão de Morgan)

| Epic | Objetivo | Status |
|------|---------|--------|
| **Epic 1** | Foundation — MVP CLI baixando WDO end-to-end | ⏳ planejamento concluído |
| **Epic 2** | Quality & Performance — validações, baselines, retry inteligente | 📋 planejado |
| **Epic 3** | Desktop UI — PySide6 + UX Uma + packaging .exe | 📋 planejado |
| **Epic 4** | Multi-asset & Library API — WIN, equities, public_api estável | 📋 planejado |

Detalhes: `docs/epics/`.

---

## 📐 Princípios Inegociáveis (resumo R1..R20)

> Lista completa em `docs/MANIFEST.md`.

1. **R1** Foundation primeiro
2. **R2** Manual ProfitDLL é fonte primária
3. **R3** Callback DLL = `queue.put_nowait()` apenas
4. **R4** Schema é contrato perpétuo
5. **R5** Idempotência absoluta
6. **R6** Catálogo SQLite é fonte única
7. **R7** Timestamps em BRT naive (não converter para UTC)
8. **R8** Bolsa = uma letra (`"F"` ou `"B"`)
9. **R9** Não chutar contratos vigentes (validar via probe)
10. **R10** V2 functions only (quando trading entrar)
11. **R11** UI nunca bloqueia MainThread Qt (>16ms)
12. **R12** `git push` = monopólio de Gage
13. **R13** Story → Done exige Quinn PASS
14. **R14** Release exige todos os PASSes (Quinn+Pyro+Sol+Aria+Morgan)
15. **R15** ADR-first para decisões transversais
16. **R16** Performance medida, não palpitada
17. **R17** Microcopy é design (Uma decide)
18. **R18** Zero secret no repo
19. **R19** Build determinístico
20. **R20** Stories pequenas (< 3 dias)

---

## 🤝 Como contribuir

1. Identifique uma story em `docs/stories/` ou peça a Morgan criar uma nova (`*create-story`).
2. Story precisa estar `Ready` (validada por Morgan `*validate-story`).
3. Owner do agente assignado executa o trabalho consultando especialistas (`*consult <agent>`).
4. Quinn `*qa-gate {story-id}` retorna PASS antes de marcar Done.
5. Para push, delegue a Gage com `*commit-and-handoff`.

Workflow completo em `docs/WORKFLOW.md`.

---

## 📜 Licença

A definir.

---

*— Squad data-downloader, 2026-05-03 — fundação para o que vem*

<!-- LATEST-RELEASE --> Latest release: [v1.2.0](https://github.com/nicksauro/data-downloader/releases/tag/v1.2.0) — download robusto + períodos extensos (desde 2018): translate_failures≈0 (Q-DRIFT-40), resume funcional, ProgressCard com ETA/throughput, broker dead-code removido (~2034 LOC). BIG COUNCIL round 3.
