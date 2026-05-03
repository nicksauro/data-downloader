# CODERABBIT_DECISION — Story 0.4

**Owner:** Gage (devops) + Quinn (qa)
**Status:** **ADOPTED — Opção B (advisory only)**
**Adoption Date:** 2026-05-03
**Approvers:** Gage (devops, infra) + Quinn (qa, gate authority)
**Story:** 0.4 — CodeRabbit adoption decision
**Finding:** M3 (PLAN_REVIEW_2026-05-03.md) — CodeRabbit referenciado em `agents/dev.md` mas não adaptado nem em stories.

---

## 0. DECISÃO FORMAL (TL;DR)

| Item | Decisão |
|------|---------|
| **Status** | ADOPTED — Opção B (advisory only) |
| **Self-healing automático em `Dex *develop`** | **DESLIGADO** |
| **Trigger inicial** | Quinn invoca manualmente em PR > 500 LOC (NÃO automático em pre-commit, NÃO em `*develop`) |
| **Squad usa especialistas** | Nelo (DLL), Sol (storage), Aria (arquitetura), Quinn (qualidade) — CodeRabbit é input opcional, NUNCA gate |
| **Severity matrix (canônica em `docs/qa/CODE_RABBIT_INTEGRATION.md` §4-5)** | CRITICAL bloqueia QA gate; HIGH/MEDIUM viram dívida em `docs/debt/`; LOW ignorado/informativo |
| **`.coderabbit.yaml` versionado** | NÃO criar |
| **CI workflow CodeRabbit** | NÃO configurar em Epic 1 |
| **Revisitar** | Após Story 1.7b (gate Epic 1) — avaliar se valor entregue justifica overhead |

> **Autoridade:** Quinn é autoridade final sobre QA gate (inclusive sobre severity reclassification). Gage é autoridade sobre infra/instalação WSL. Conflitos de severity → Quinn decide.

---

## 1. Contexto

O AIOX framework integra **CodeRabbit** como ferramenta de code review automatizada (referenciada em `.claude/rules/coderabbit-integration.md` e em `agents/dev.md` no fluxo `*develop`). O squad data-downloader herda essa referência por default — mas:

1. **Não foi adaptado** ao contexto deste squad (zero configuração, sem `.coderabbit.yaml`).
2. **Self-healing automático** (Dex roda CodeRabbit em loop até clean) pode conflitar com a filosofia do squad: **especialistas humanos-virtuais** (Nelo, Sol, Aria, Quinn) são a fonte primária de revisão técnica.
3. **Custo de contexto:** rodar CodeRabbit em cada `*develop` aumenta tokens consumidos sem ganho proporcional.

---

## 2. Opções avaliadas

### Opção A — Adoção total

Configurar CodeRabbit completo, gerar `.coderabbit.yaml`, ativar self-healing automático em `Dex *develop` (max 2 iterações conforme rule do AIOX).

| Pro | Contra |
|-----|--------|
| Catching de bugs rápido (lint, security, style) | Sobreposição com pre-commit (ruff, mypy, detect-secrets) |
| Comentários inline em PR | Conflito com Quinn (qa) — duas vozes |
| Cobertura padrão da indústria | Custo recorrente (API CodeRabbit) |
| | Self-healing pode mascarar bugs reais |

### Opção B — Adaptar minimamente (advisory) — **RECOMENDADO**

Manter referência em `agents/dev.md`, mas:
- **SEM self-healing automático** em `*develop`
- Usar como **ferramenta opcional** que Quinn pode invocar manualmente em `*qa-gate` se quiser segunda opinião sobre PR
- Sem `.coderabbit.yaml` versionado neste squad até decisão revista (Story 0.4 fecha como "advisory only")

| Pro | Contra |
|-----|--------|
| Mantém opção sem se comprometer | Risco: ninguém vai usar |
| Quinn no controle (filosofia squad: especialistas decidem) | |
| Zero conflito com pre-commit/Nelo/Sol/Aria | |
| Custo zero quando não invocado | |

### Opção C — Remoção total

Remover toda referência a CodeRabbit das stories, dos agents, e dos rules locais.

| Pro | Contra |
|-----|--------|
| Limpeza conceitual | Perde opção de revisitar |
| Foco total em especialistas internos | |
| Zero ambiguidade | |

---

## 3. Recomendação Gage + Quinn → **Opção B**

### 3.1 Justificativa

1. **Squad é só de agentes especialistas.** Nelo audita DLL. Sol audita storage. Aria audita arquitetura. Quinn audita qualidade. **Adicionar IA externa como autoridade redundante dilui responsabilidade.**
2. **Pre-commit já cobre o trivial** (ruff, mypy, secrets). CodeRabbit em modo automático seria 90% redundante.
3. **Mas há cenários úteis:** PR grande/complexo onde Quinn quer "olhar fresco" → invocar CodeRabbit on-demand é valioso.
4. **Custo controlado:** apenas roda quando explicitamente invocado.

### 3.2 O que muda na prática

| Item | Antes (default AIOX) | Depois (squad data-downloader) |
|------|----------------------|--------------------------------|
| `Dex *develop` self-heal loop | Ativo (max 2 iter) | **DESATIVADO** |
| `agents/dev.md` referência CodeRabbit | Implícita (via rules) | **Explicitamente: "consultar somente sob solicitação de Quinn"** |
| `.coderabbit.yaml` | Não existe | **Continua não existindo** (decisão revisitada se Story de Epic 4 trouxer back) |
| Quinn `*qa-gate` | Sem CodeRabbit | **Invoca manualmente APENAS em PR > 500 LOC** (trigger formal — ver §0) |
| CI workflow CodeRabbit | Não configurado | **Não configurar** em Epic 1; reavaliar em Epic 4 (release) |

---

## 4. Como rodar manualmente (quando Quinn decide invocar)

### 4.1 Pre-requisito

```powershell
# WSL com Ubuntu, CodeRabbit CLI instalado
wsl -- bash -c '~/.local/bin/coderabbit --version'
```

### 4.2 Invocação

```powershell
# Pre-PR review (compara branch atual vs main)
wsl -- bash -c 'cd /mnt/c/Users/Pichau/Desktop/data-downloader && ~/.local/bin/coderabbit --prompt-only --base main'

# Review apenas uncommitted changes
wsl -- bash -c 'cd /mnt/c/Users/Pichau/Desktop/data-downloader && ~/.local/bin/coderabbit --prompt-only -t uncommitted'
```

### 4.3 Output esperado

CodeRabbit retorna texto estruturado em formato Markdown com:
- **Critical issues** (security, correctness)
- **Major issues** (performance, maintainability)
- **Minor issues** (style, conventions)

### 4.4 Como Quinn deve interpretar

> **CANÔNICO:** A matriz de severity completa vive em `docs/qa/CODE_RABBIT_INTEGRATION.md` §4 (Quinn é autoridade). Resumo abaixo:

| Severidade CodeRabbit (mapeada) | Ação Quinn | Política |
|---------------------------------|------------|----------|
| **CRITICAL** (bug/security/correctness violando INV-*) | Bloqueia PASS | Vai para QA_FIX_REQUEST.md; Dex DEVE corrigir |
| **HIGH** (bug não-hot path, perf hot path) | NÃO bloqueia automaticamente; >= 3 HIGH → CONCERNS | Vira dívida em `docs/debt/` (story-debt criada) |
| **MEDIUM** (maintainability, perf não-hot) | NÃO bloqueia | Vira dívida em `docs/debt/` (catálogo cumulativo) |
| **LOW** (style, naming, nitpick) | Informativo | Ignorado / aplicação oportunística |

> **REGRA:** CodeRabbit é **input para Quinn**, NUNCA gate automático. Verdict final é Quinn. Se CodeRabbit conflita com Nelo/Sol/Aria, especialista do squad tem precedência (Quinn documenta no QA_REPORT).

---

## 5. Em qual gate rodar (resumo)

| Gate | Roda CodeRabbit? | Quem invoca |
|------|------------------|-------------|
| `Dex *develop` (self-heal) | **NÃO** (DESLIGADO formalmente em §0) | — |
| Pre-commit / pre-push automático | **NÃO** (decisão revisada — não é trigger automático) | — |
| `Quinn *qa-gate` em PR <= 500 LOC | NÃO | — |
| `Quinn *qa-gate` em PR > 500 LOC | **SIM (manual)** — trigger formal | Quinn decide |
| `Quinn *qa-gate` em PR de DLL wrapper | **NÃO** (Nelo audita, mesmo se > 500 LOC) | — |
| `Quinn *qa-gate` em PR de storage | **NÃO** (Sol audita, mesmo se > 500 LOC) | — |
| `Quinn *qa-gate` em PR de arquitetura | **NÃO** (Aria audita, mesmo se > 500 LOC) | — |
| `Quinn *qa-gate` em PR de UI/CLI > 500 LOC | **OPCIONAL** | Quinn decide |
| Release final (Gage) | NÃO | — |

---

## 6. Re-avaliação programada

**Re-avaliação obrigatória após Story 1.7b (gate Epic 1)** — avaliar se valor entregue justifica overhead operacional. Decisão pode ser mantida (Opção B), promovida (Opção A), ou removida (Opção C).

Esta decisão é **também revisitada em Story de Epic 4 (release V1)**. Triggers para re-avaliar:

- Squad cresce com agente humano externo → CodeRabbit vira útil para alinhar
- Especialistas internos atrasarem reviews → CodeRabbit vira gap-filler
- Pyro detectar regressão de qualidade no codebase → considerar adoção mais profunda
- Custo CodeRabbit virar gratuito/zero → barreira removida

Até lá: **modo advisory, opcional, invocação manual por Quinn**.

---

## 7. Atualização em arquivos relacionados

| Arquivo | Mudança |
|---------|---------|
| `agents/dev.md` | Adicionar nota: "CodeRabbit self-heal NÃO ativo neste squad. Consultar Quinn antes de invocar." |
| `.claude/rules/coderabbit-integration.md` (global) | Não modificar (regra global do AIOX). Squad documenta override aqui. |
| `docs/qa/QA_PROTOCOL.md` (futuro, Quinn) | Documentar quando Quinn invoca CodeRabbit (ver §5 desta página) |
| `.coderabbit.yaml` | **NÃO criar** |

---

## 8. Decisão final

**Status:** **ADOPTED — Opção B — Advisory tool, opt-in, manual invocation por Quinn em PR > 500 LOC.**

**Aprovadores:**
- ⚙️ **Gage (devops):** assina autoridade sobre infra (instalação WSL, ausência de `.coderabbit.yaml`, ausência de CI workflow)
- 🧪 **Quinn (qa):** assina autoridade sobre QA gate (severity matrix canônica em `docs/qa/CODE_RABBIT_INTEGRATION.md` §4-5; trigger; bloqueio CRITICAL)

**Data:** 2026-05-03

**Pendências (não-bloqueantes):**
- Morgan ratificar formalmente em próximo `*release-readiness` (informativo — adoção já válida)
- Re-avaliar após Story 1.7b (gate Epic 1)

— Gage, publicando com cuidado ⚙️ + Quinn, no portão 🧪

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-05-03 | Gage (Fase A) | Documento criado — recomendação Opção B registrada (status spec) |
| 2026-05-03 | Gage + Quinn (Fase B) | **Status ADOPTED.** Adicionada §0 (decisão TL;DR formal). Harmonizada §3.2 (trigger restringido a PR > 500 LOC). Harmonizada §4.4 (severity matrix delegada à autoridade canônica de Quinn em CODE_RABBIT_INTEGRATION.md §4-5). Harmonizada §5 (tabela de gates clarificada: pre-commit/automatic NÃO é trigger). Adicionada §6 trigger de re-avaliação após Story 1.7b. §8 atualizada com aprovadores formais + data. |
