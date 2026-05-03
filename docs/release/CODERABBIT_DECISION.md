# CODERABBIT_DECISION — Story 0.4

**Owner:** Gage (devops) + Quinn (qa)
**Status:** spec — recomendação registrada, aprovação pendente Morgan
**Story:** 0.4 — CodeRabbit adoption decision
**Finding:** M3 (PLAN_REVIEW_2026-05-03.md) — CodeRabbit referenciado em `agents/dev.md` mas não adaptado nem em stories.

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
| Quinn `*qa-gate` | Sem CodeRabbit | **Pode invocar manualmente** se PR > 500 LOC ou se sentir necessário |
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

| Severidade CodeRabbit | Ação Quinn |
|-----------------------|------------|
| Critical | Considerar como input — ainda decide com base em INV-* e checklists |
| Major | Avaliar se conflita com Nelo/Sol/Aria; se sim, especialista do squad tem precedência |
| Minor | Ignorar se já passou pre-commit/ruff |

> **REGRA:** CodeRabbit é **input para Quinn**, NUNCA gate automático. Verdict final é Quinn.

---

## 5. Em qual gate rodar (resumo)

| Gate | Roda CodeRabbit? | Quem invoca |
|------|------------------|-------------|
| `Dex *develop` (self-heal) | **NÃO** | — |
| `Quinn *qa-gate` em PR pequeno (< 200 LOC) | NÃO (default) | — |
| `Quinn *qa-gate` em PR grande (> 500 LOC) | **OPCIONAL** | Quinn decide |
| `Quinn *qa-gate` em PR de DLL wrapper | **NÃO** (Nelo audita) | — |
| `Quinn *qa-gate` em PR de storage | **NÃO** (Sol audita) | — |
| `Quinn *qa-gate` em PR de arquitetura | **NÃO** (Aria audita) | — |
| `Quinn *qa-gate` em PR de UI/CLI | **OPCIONAL** | Quinn decide |
| Release final (Gage) | NÃO | — |

---

## 6. Re-avaliação programada

Esta decisão é **revisitada em Story de Epic 4 (release V1)**. Triggers para re-avaliar:

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

**Status proposto:** **Opção B — Advisory tool, opt-in, manual invocation por Quinn.**

**Pendência:**
- Morgan ratificar (15 min de leitura)
- Quinn confirmar protocolo de invocação manual (atualizar QA_PROTOCOL futuro)

— Gage, publicando com cuidado ⚙️
