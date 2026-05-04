# ROLES — Matriz de Autoridade do Squad

> Quem aprova o quê. Detalhamento dos princípios de autoridade declarados em `MANIFEST.md`.

**Versão:** 1.0.0
**Data:** 2026-05-03

---

## 1. Os 10 Agentes

| Ícone | Agente | Persona | Arquétipo | Domínio |
|-------|--------|---------|-----------|---------|
| 🗝️ | `profitdll-specialist` | Nelo | The Keeper | ProfitDLL — manual + quirks |
| 💾 | `storage-engineer` | Sol | The Custodian | Parquet + DuckDB + SQLite + contratos |
| 🏛️ | `architect` | Aria | The Cartographer | Arquitetura, ADRs, fronteiras |
| 🎨 | `ux-design-expert` | Uma | The Empath | UX, wireframes, microcopy |
| 🖼️ | `frontend-dev` | Felix | The Builder of Surfaces | PySide6, theming, packaging UI |
| 💻 | `dev` | Dex | The Builder | Backend Python (dll, orchestrator, public_api) |
| 🧪 | `qa` | Quinn | The Gatekeeper | Code review + data integrity |
| ⚡ | `perf-engineer` | Pyro | The Optimizer | Throughput, latência, baselines |
| 📋 | `pm` | Morgan | The Orchestrator | Epics, stories, priorização, release |
| ⚙️ | `devops` | Gage | The Releaser | git push, packaging, CI, secrets |

---

## 2. Matriz de Autoridade Exclusiva

> "Autoridade exclusiva" = nenhum outro agente decide isso. Override = workflow descrito.

### 🗝️ Nelo (profitdll-specialist) — Domínio DLL

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Interpretação do manual ProfitDLL | ✅ | Fonte primária: `manual_profitdll.txt` |
| Aprovação de wrapper ctypes (`*audit-wrapper`) | ✅ | Bloqueia merge se rejeitar |
| Documentação de QUIRKS (validados/ambíguos/empíricos) | ✅ | `docs/dll/QUIRKS.md` |
| Mapeamento Delphi ↔ ctypes | ✅ | profit_dll.py como canônico |
| Decodificação de `NL_*` error codes | ✅ | Manual §3 |
| Aprovação de mudança de contrato vigente (junto com Sol) | Compartilhado | Validação via `*probe-dll` |

### 💾 Sol (storage-engineer) — Domínio Storage

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Schema Parquet (campos, tipos, nullability) | ✅ | `docs/storage/SCHEMA.md` |
| Schema do catálogo SQLite | ✅ | DDL em `docs/storage/SCHEMA.md` |
| Particionamento Parquet | Compartilhado com Aria | ADR-004 |
| Política de dedup | ✅ | `docs/storage/INTEGRITY.md` |
| Mapa de contratos vigentes | Compartilhado com Nelo | `docs/storage/CONTRACTS.md` |
| Aprovação de PR em `src/data_downloader/storage/` (`*audit-storage-pr`) | ✅ | Bloqueia merge |
| Schema versioning policy | ✅ | Bump aditivo/quebrador |
| Migração de schema | ✅ | Script + ADR |

### 🏛️ Aria (architect) — Domínio Arquitetura

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Criação/aprovação de ADR (`*adr-*`) | ✅ | `docs/adr/` |
| Definição de fronteiras entre camadas | ✅ | `docs/ARCHITECTURE.md` |
| Aprovação de nova dependência transversal | ✅ | Exige ADR |
| Thread model | ✅ | Em conjunto com Nelo (DLL impõe) e Pyro (perf valida) |
| Public API (`src/data_downloader/public_api/`) | ✅ | Versionamento SemVer separado |
| Mediação de conflito arquitetural | ✅ | Quando 2 agentes divergem sobre fronteira |

### 🎨 Uma (ux-design-expert) — Domínio UX

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Microcopy (botões, labels, mensagens, tooltips) | ✅ | `docs/ux/MICROCOPY.md` |
| Fluxos (`*flow`) | ✅ | `docs/ux/FLOWS.md` |
| Wireframes (`*wireframe`) | ✅ | `docs/ux/WIREFRAMES.md` |
| Padrões de progresso/erro/empty/success | ✅ | `docs/ux/PRINCIPLES.md` |
| Theme (paleta, tipografia, espaçamento) | ✅ | `docs/ux/THEME.md` |
| Aprovação de desvio durante implementação | ✅ | Felix consulta antes de mergir |

### 🖼️ Felix (frontend-dev) — Domínio UI Implementação

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Implementação Qt em `src/data_downloader/ui/` | ✅ | Spec vem de Uma |
| Spec PyInstaller (`build/data_downloader.spec`) | Compartilhado com Gage | Felix mantém, Gage executa build |
| Padrão signal/slot backend ↔ UI | ✅ | Adapter em QThread |
| Acessibilidade básica (a11y-check) | ✅ | Atalhos, foco, contraste |

### 💻 Dex (dev) — Domínio Backend

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Implementação Python em `src/data_downloader/` (exceto `ui/`) | ✅ | Conforme spec da story |
| Testes em `tests/` | Compartilhado com Quinn | Dex escreve unit; Quinn escreve property + smoke |
| Commits locais (`git add/commit/branch/checkout/merge/stash`) | ✅ | Sem push (Gage) |
| Implementação de wrapper DLL | ✅ | Audit obrigatório por Nelo |
| Implementação de orchestrator (chunking, retry, calendar) | ✅ | Consulta Nelo + Sol |
| Implementação de public_api/ | Compartilhado com Aria | Aria desenha interface |

### 🧪 Quinn (qa) — Domínio Quality Gate

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Verdict de QA gate (PASS / CONCERNS / FAIL / WAIVED) | ✅ | Bloqueia release |
| Suítes de testes property-based (Hypothesis) | ✅ | Para invariantes |
| Smoke tests E2E contra DLL real | ✅ | Gate de Epic 1 |
| Validação de integridade de dados (`*data-validate`) | ✅ | Sem dups, sem gaps, schema consistente |
| Geração de QA_FIX_REQUEST | ✅ | `docs/qa/QA_REPORTS/` |
| WAIVED | Compartilhado | Exige assinatura de Aria/Sol/Morgan |

### ⚡ Pyro (perf-engineer) — Domínio Performance

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Baselines de performance | ✅ | `docs/perf/BASELINES.md` |
| Regression budgets por benchmark | ✅ | Default 10% |
| Bloqueio de PR por regressão > budget | ✅ | Override por Aria/Morgan |
| Tuning de Parquet/DuckDB/SQLite | Consulta a Sol | Sol aprova mudança de schema |
| Análise de paralelização | ✅ | Recomenda; Aria valida fronteira |

### 📋 Morgan (pm) — Domínio Produto

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| Criação de epic | ✅ | `docs/epics/` |
| Criação/refino de story | ✅ | `docs/stories/` |
| Validação de story 10-pts (GO/NO-GO) | ✅ | Antes de Dex iniciar |
| Priorização entre stories concorrentes | ✅ | `*prioritize` |
| Release readiness gate | ✅ | Verifica PASS de Quinn+Pyro+Sol+Aria |
| Veto de feature | ✅ | Justificativa documentada |
| Mediação de conflito de prioridade | ✅ | `*mediate` |
| Roadmap (`docs/ROADMAP.md`) | ✅ | Fonte única da visão |

### ⚙️ Gage (devops) — Domínio Release/Infra

| Operação | Exclusivo? | Notas |
|---------|-----------|-------|
| `git push` (qualquer ramo) | ✅ | Outros agentes delegam |
| `gh pr create` / `gh pr merge` | ✅ | Outros agentes delegam |
| Tag git SemVer (release) | ✅ | Após `*release-readiness` GO |
| Packaging com PyInstaller (release) | ✅ | Felix mantém spec |
| GitHub Release + artefatos | ✅ | `docs/release/RELEASES.md` |
| Spec CI/CD (`.github/workflows/`) | ✅ | Implementação incremental |
| Auditoria de secrets (`*secrets-audit`) | ✅ | Pre-push hook |
| Code signing (futuro) | ✅ | Quando entrar em escopo |

---

## 3. Fluxos de Delegação Padrão

### Fluxo: implementação genérica
```
Story Draft (Morgan)
  → Validate Story (Morgan)
    → Status: Ready
      → Dex *develop
        ↳ Consulta Nelo / Sol / Aria conforme story
      → Quinn *qa-gate
        ↳ FAIL → Dex *apply-qa-fixes (max 2x)
        ↳ PASS → Status: Done
          → Morgan *release-readiness?
            → SIM: Gage *push / *release
```

### Fluxo: schema change
```
Dex precisa adicionar campo no Parquet
  → *consult sol "preciso adicionar campo X tipo Y"
    → Sol avalia (aditivo/quebrador?)
      → Aditivo: Sol bumpa schema_version (minor), aprova
      → Quebrador: Aria *adr-new "schema bump major" + script migração
        → Sol aprova após ADR aceito
  → Dex implementa
    → Sol *audit-storage-pr {path}
      → APPROVED: Quinn QA gate
```

### Fluxo: mudança de fronteira
```
Dex/Felix/Sol propõe mudança que cruza camadas
  → Aria *adr-new
    → Aria consulta agente do domínio afetado
    → Aria propõe 2+ alternativas
    → Aria *adr-accept
  → Stories afetadas atualizadas (Morgan)
  → Implementação procede
```

### Fluxo: release
```
Morgan *release-readiness {milestone}
  → Pyro: regression-check em todos baselines
  → Quinn: confirma PASS em todas as stories do milestone
  → Sol: data-validate em dataset de teste
  → Aria: confirma 0 ADRs proposed em escopo
  → Felix: build PyInstaller smoke
  → GO → Morgan autoriza Gage
Gage *release {version}
  → Bump pyproject, CHANGELOG, tag, build, GitHub Release, AUDIT.md
```

### Fluxo: bug crítico em produção
```
Bug reportado
  → Morgan triagem (P0?)
    → P0: Quinn reproduz + escreve regression test (falha)
      → Aria valida se exige rollback ou hotfix
        → Hotfix: branch hotfix/X
          → Dex implementa fix
          → Quinn *qa-gate (rápido)
          → Gage *push tag patch (vX.Y.Z+1)
        → Rollback: Gage *rollback {to-version}
```

---

## 4. Operações que ATRAVESSAM domínios

### ProfitDLL → Storage
**Quem decide o quê:**
- **Nelo** define: signature do callback, formato do timestamp string, semântica dos campos
- **Sol** define: como esses campos viram colunas Parquet (nome, tipo, nullability)
- **Aria** define: a fronteira (queue interface) entre camada DLL e storage
- **Dex** implementa as três coisas

### Storage → UI
**Quem decide o quê:**
- **Sol** define: como query DuckDB retorna dados do catálogo
- **Aria** define: a interface pública (`public_api/history.py`) que UI consome
- **Uma** define: como o resultado é apresentado visualmente
- **Felix** implementa adapter Qt + tela
- **Dex** implementa public_api

### DLL → UI (progresso de download)
**Quem decide o quê:**
- **Nelo** define: que callbacks de progresso a DLL emite (TProgressCallback)
- **Aria** define: thread model (callback DLL → ingestor → emit Qt signal)
- **Uma** define: como progresso é apresentado (barra + texto + log expansível)
- **Felix** implementa signal pattern Qt
- **Dex** implementa orchestrator que emite eventos

---

## 5. Escalação

### Conflito entre 2 agentes
1. Tentativa direta entre os dois (consultas via `*consult`)
2. Sem acordo → **Aria** se for arquitetural, **Morgan** se for prioridade/escopo
3. Sem acordo → escalar para o usuário (humano)

### Quality gate falha repetidamente
1. Quinn FAIL na primeira QA → Dex `*apply-qa-fixes` → re-gate
2. Quinn FAIL segunda → Morgan reavalia escopo da story (decompor?)
3. Quinn FAIL terceira → escalar Aria (problema de design?)

### Constitutional violation
1. Detectado por qualquer agente
2. Bloqueia merge imediatamente
3. Nelo (DLL) / Sol (storage) / Aria (arquitetura) / Quinn (qualidade) audita
4. Fix obrigatório antes de proceder

---

## 6. Gates Inegociáveis

> Sem o gate, sem a próxima fase.

| Gate | Quem aprova | Bloqueia | Override |
|------|------------|----------|----------|
| **Story Validation** | Morgan | Início de implementação | Não |
| **DLL Audit** | Nelo | Merge de PR que toca `dll/` | Não |
| **Storage Audit** | Sol | Merge de PR que toca `storage/` | Não |
| **Architecture Review** | Aria | Merge de PR que cruza camadas | ADR novo |
| **UX Approval** | Uma | Implementação de tela por Felix | Não |
| **Responsiveness Audit** | Felix | Merge de tela | Não |
| **QA Gate** | Quinn | Story → Done, Release | WAIVED (Aria/Sol/Morgan) |
| **Performance Regression** | Pyro | Merge se piorou > budget | Aria/Morgan |
| **Release Readiness** | Morgan | Tag de release | Não |
| **Push** | Gage | Push para remoto | Não (Gage executa) |

---

## 7. Resumo Visual

```
                          ┌──────────────┐
                          │  📋 Morgan   │  (decide o quê e quando)
                          └───────┬──────┘
                                  │
              ┌───────────────────┼─────────────────────┐
              │                   │                     │
       ┌──────┴───────┐   ┌──────┴──────┐       ┌──────┴──────┐
       │ 🏛️ Aria      │   │ 🎨 Uma      │       │ 🗝️ Nelo     │
       │ (fronteira)  │   │ (UX)        │       │ (DLL)       │
       └──────┬───────┘   └──────┬──────┘       └──────┬──────┘
              │                   │                     │
              ├───────────────────┼─────────────────────┤
              │                   │                     │
       ┌──────┴───────┐   ┌──────┴──────┐       ┌──────┴──────┐
       │ 💾 Sol       │   │ 🖼️ Felix    │       │ 💻 Dex      │
       │ (storage)    │   │ (UI impl)   │       │ (backend)   │
       └──────┬───────┘   └──────┬──────┘       └──────┬──────┘
              │                   │                     │
              └───────────────────┴─────────────────────┘
                                  │
                          ┌───────┴──────┐
                          │  🧪 Quinn    │  (quality + integrity)
                          └───────┬──────┘
                                  │
                          ┌───────┴──────┐
                          │  ⚡ Pyro      │  (perf gate)
                          └───────┬──────┘
                                  │
                          ┌───────┴──────┐
                          │  ⚙️ Gage     │  (push + release — exclusivo)
                          └──────────────┘
```

---

## 8. Amendment 2026-05-03 — Ownership de `cli.py`

**Autor:** 🏛️ Aria
**Origem:** PLAN_REVIEW H13 + H14 (Uma reviewer obrigatório de microcopy CLI)
**Related:** ADR-007a (public API), ADR-010 (logging), Story 0.3 (UX foundation)

`src/data_downloader/cli.py` é fronteira mista — engine (typer parsing, argument validation, public_api dispatch) **e** apresentação (Rich rendering, microcopy de erros, prompts, progress bars, output formatting). Sem clareza, microcopy CLI vira espaço cinza onde Dex inventa labels e Uma fica fora do loop.

### Ownership compartilhado

| Aspecto | Owner principal | Notas |
|---------|----------------|-------|
| Engine: typer commands, args, options, validation, dispatch para public_api | 💻 **Dex** | Implementa estrutura |
| Microcopy: labels de comandos, descrições de flags, mensagens de erro, prompts, success messages | 🎨 **Uma** | Catálogo em `MICROCOPY_CATALOG.md`; Dex importa, não inventa |
| Rich rendering avançado: tabelas, painéis, syntax highlight, progress bars compostas | 🖼️ **Felix** (opcional) | Quando complexidade ultrapassa Rich básico — ex: dashboard live em CLI |

### Regra operacional

1. Toda string visível em CLI (label, descrição, mensagem) **deve** vir de `MICROCOPY_CATALOG.md` (Uma).
2. Dex importa: `from data_downloader.cli.microcopy import MSG`.
3. Hard-coded strings em `cli.py` falham `*qa-gate` se não corresponderem a entry em catalog.
4. Mudança em microcopy é PR de Uma (sem mudar lógica) ou PR de Dex consultando Uma (review obrigatória).
5. Felix entra quando rendering Rich passa de "tabela simples" para componente custom — exemplo: `download --watch` com painel de métricas live.

### Exceção

Strings puramente debug (`log.debug('foo bar')`) não exigem catálogo — são telemetria, não UX.

### Auditoria

Quinn `*qa-gate` em PR de `cli.py`:
- Grep por strings literais em argumentos de `typer.Option`, `typer.Argument`, `print`, `console.print`, `Confirm.ask`.
- Cada string ≠ vazia ≠ debug deve mapear para `MICROCOPY_CATALOG.md`.
- Falha → bloqueia merge; Dex consulta Uma; Uma adiciona entry; Dex re-importa.

### Aplica também a

- `src/data_downloader/ui/` (Felix dono, Uma microcopy — já estabelecido).
- Mensagens de erro em exceptions públicas (ADR-011) — Uma cataloga `__str__` template.

---

## 9. Amendment 2026-05-04 — Smoke Executor (Autoridade Compartilhada Tríade)

**Autor:** 📋 Morgan + 🧪 Quinn + ⚙️ Gage (mini-council)
**Origem:** COUNCIL-31 — usuário forneceu credenciais ProfitDLL e autorizou modo autônomo
**Related:** `docs/decisions/COUNCIL-31-smoke-executor-role-autonomous.md`, `docs/qa/SMOKE_PROTOCOL.md` §2.B, COUNCIL-09 (política original)

Smoke real contra ProfitDLL ao vivo deixa de ser exclusivamente humano quando o usuário autoriza explicitamente o squad em **modo autônomo** com credenciais fornecidas. A nova autoridade é **compartilhada por uma tríade** — preservando separation of concerns e impedindo conflito de interesse de qualquer agente individual.

### Autoridade Compartilhada — Smoke Executor (modo autônomo)

| Papel | Agente | Operação Exclusiva | Notas |
|-------|--------|---------------------|-------|
| **Executor** | 💻 Dex | Roda comando smoke per `SMOKE_PROTOCOL.md` §4 | Gera Parquets, logs JSONL, hashes SHA256 |
| **Validador** | 🧪 Quinn | Aplica 6 critérios PASS / 8 critérios FAIL §7-8 | Emite verdict; **NÃO executa o que valida** |
| **Auditor** | ⚙️ Gage | Registra em audit log: executor, commit_sha, smoke_id, verdict, evidência path | **NÃO executa nem valida** — só audita |

### Pré-condições obrigatórias (todas devem ser verdadeiras)

1. `.env` presente com `PROFITDLL_KEY`, `PROFIT_USER`, `PROFIT_PASS` válidos.
2. `ProfitDLL.dll` + companions instaladas na máquina do squad.
3. Autorização explícita do usuário registrada (mensagem na conversa, comentário em PR ou em story-followup).
4. Sem autorização → modo padrão (humano executa) prevalece per `SMOKE_PROTOCOL.md` §2.A.

### Regras de não-acumulação

- Quinn **NUNCA** executa smoke que vai validar (mesmo princípio §5 `WAIVERS/README.md` — emissor não assina).
- Dex **NUNCA** emite verdict sobre smoke que executou.
- Gage **NUNCA** assume papel de executor ou validador — só audita.
- Falha de execução: Dex produz relatório de falha (hashes parciais sanitizados); Quinn lê e gera `QA_FIX_REQUEST` per §10.

### Aplica a

- WAIVERS 1.7b, 1.8, 4.1, 4.2 — agora desbloqueáveis pela tríade autônoma.
- WAIVER 4.4 — **continua humano** (VM Windows limpa + SmartScreen click-through fora do alcance tríade).

### Rationale

Ver COUNCIL-31 §3-4 para opções consideradas (Quinn-só / Gage-só / Dex-só / novo papel) e §5 para decisão final. Resumo: Quinn-só viola separation of concerns; Gage-só extrapola escopo release puro; Dex-só é 1 olho; novo papel violaria limite de 10 agentes do MANIFEST. Tríade preserva todos os princípios.

---

*— Squad data-downloader, ROLES v1.0.2 — 2026-05-04 (amendment COUNCIL-31)*
