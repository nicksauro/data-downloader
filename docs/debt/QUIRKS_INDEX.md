# QUIRKS_INDEX — Índice Executivo de Quirks DLL (2026-05-05)

**Curador:** Aria 🏛️ (architect)
**Última atualização:** 2026-05-05 (post Story 1.7g Done, ADR-022 Accepted, Q17-CLOSED)

---

## §1 — Resumo executivo (números)

| Categoria | Total | Localização |
|-----------|-------|-------------|
| ✅ **Validated** (canônico vivo) | 24 | [`docs/dll/QUIRKS.md`](../dll/QUIRKS.md) |
| ⚠️ **Ambiguous** (workaround estável) | 3 | [`docs/dll/QUIRKS.md`](../dll/QUIRKS.md) |
| ❓ **Open P0** (release blocker) | 1 | [`QUIRKS_OPEN_P1_2026-05-05.md`](./QUIRKS_OPEN_P1_2026-05-05.md) §1 |
| ❓ **Open P1** (bloqueia próxima feature) | 3 | [`QUIRKS_OPEN_P1_2026-05-05.md`](./QUIRKS_OPEN_P1_2026-05-05.md) §2 |
| 🧪 **Hypothesis P2** (não-bloqueia release) | 3 | [`QUIRKS_OPEN_P1_2026-05-05.md`](./QUIRKS_OPEN_P1_2026-05-05.md) §3 |
| ⚠️ **Refuted** (folclore desmentido) | 16 | [`QUIRKS_HISTORICAL_2026-05-05.md`](./QUIRKS_HISTORICAL_2026-05-05.md) §1 |
| 🐛 **Bug-código HOTFIX-VALIDATED** (já fechados) | 4 | [`QUIRKS_HISTORICAL_2026-05-05.md`](./QUIRKS_HISTORICAL_2026-05-05.md) §2 |
| **TOTAL universo Q-DRIFT + Q-NN** | ~54 entradas | — |

**Distribuição vivos vs históricos:**
- **Vivos em `QUIRKS.md`:** ~31 entradas (validated + ambiguous + open + hypothesis ainda relevantes)
- **Históricos arquivados:** ~20 entradas (refuted folclore + bug-código já fechados — referência post-mortem)

---

## §2 — Estrutura de arquivos

```
docs/
├── dll/
│   └── QUIRKS.md                        ← VIVO — quirks canônicas (validated/ambiguous/open/hypothesis)
└── debt/
    ├── QUIRKS_INDEX.md                  ← ESTE arquivo (sumário executivo + política)
    ├── QUIRKS_HISTORICAL_2026-05-05.md  ← ARQUIVO — refuted + bug-código já fechados
    └── QUIRKS_OPEN_P1_2026-05-05.md     ← FOCO — P0/P1 abertas que bloqueiam features
```

**Por que separar?**
`QUIRKS.md` cresceu para ~1486 linhas e ~37 entradas Q-DRIFT — ruído visual alto. Refutadas e bug-código já fechados não são consultados em runtime de implementação, mas são valiosos para post-mortem e onboarding. Separação reduz superfície cognitiva de quem está implementando uma story (lê QUIRKS.md vivo) vs quem está auditando (lê HISTORICAL).

---

## §3 — Política de governança (Aria 2026-05-05)

### §3.1 — Quando criar nova quirk

Toda nova quirk **DEVE**:
- Ter probe minimalista reprodutor antes de virar regra de wrapper (lição Q11-E).
- Ser registrada inicialmente em `docs/dll/QUIRKS.md` (vivo) com status apropriado.
- Listar **evidência empírica direta** (log, smoke, probe) — não pode ser inferência teórica.

### §3.2 — Lifecycle de status

```
🧪 hypothesis  →  ✅ validated  ─┐
                                 │
                  ⚠️ refuted  ───┼───→  (após 30d) ARQUIVAR em QUIRKS_HISTORICAL
                                 │
                  🐛 bug-código  ┘
                  HOTFIX-APPLIED-VALIDATED
```

- **🧪 hypothesis → ✅ validated**: probe ou smoke confirma. Mantém em `QUIRKS.md` permanentemente.
- **🧪 hypothesis → ⚠️ refuted**: probe ou smoke refuta. Status muda em `QUIRKS.md`; **após 30 dias** migra para `QUIRKS_HISTORICAL`.
- **🐛 bug-código → HOTFIX-APPLIED-VALIDATED**: hotfix aplicado + smoke confirma. **Após 30 dias** migra para `QUIRKS_HISTORICAL` (conhecimento canônico vive em ADR + INVARIANTS + test reprodutor).

**Por que 30 dias?** Cobre janela típica de regressão pós-deploy + ciclo de onboarding de novo squad. Após 30d, se test reprodutor cobre, o bug não regride no nosso código.

### §3.3 — Quando arquivar em DEBT vs deletar

**NUNCA deletar** quirk refutada ou bug fechado. Sempre arquivar. Razões:
- **Prevenção de regressão de hipótese**: alguém pode re-levantar `WDOFUT retorna 0 trades` daqui a 6 meses; HISTORICAL prova que não.
- **Post-mortems**: "por que perdemos N dias debugando isso?" exige histórico.
- **Onboarding**: "não caia no mesmo folclore Sentinel §12".
- **Compliance / auditoria**: rastreabilidade de decisões técnicas.

### §3.4 — Quando promover de OPEN_P1 para QUIRKS.md vivo (resolved)

Quando OPEN P0/P1 é resolvida (probe confirmou hipótese OU bug foi corrigido):
1. Atualizar `docs/dll/QUIRKS.md` com status final + evidência.
2. Remover entrada de `QUIRKS_OPEN_P1_2026-05-05.md` (ou marcar como `RESOLVED YYYY-MM-DD` mantendo histórico no arquivo).
3. Atualizar contagem em `QUIRKS_INDEX.md` §1.

### §3.5 — Cadência de revisão

- **Por story Done**: @qa verifica se alguma quirk OPEN foi destravada e atualiza status.
- **Por sprint (15d)**: @architect revisa OPEN P1 — se >15d sem progresso, escalar a council.
- **Por release-candidate**: @architect roda audit completo — todas P0 devem ser ✅ validated ou ter ADR + WAIVER explícito.

---

## §4 — Top 3 OPEN P1 ABERTAS (atualizado 2026-05-05)

Para detalhes, ver [`QUIRKS_OPEN_P1_2026-05-05.md`](./QUIRKS_OPEN_P1_2026-05-05.md).

| # | ID | Severidade | Story bloqueada | Próximo passo |
|---|----|------------|-----------------|---------------|
| 1 | [Q-DRIFT-37](../dll/QUIRKS.md#q-drift-37) | **P0** release blocker | Toda release pública (1.7g + futuras) | Quinn Council-37 + Nelo Council-38 — diagnóstico volume gap |
| 2 | [Q15-OPEN](../dll/QUIRKS.md#q15-open) | **P1** | 5.x live broadcasting | Pyro Story 1.4.5 probe queue saturation |
| 3 | [Q18-OPEN](../dll/QUIRKS.md#q18-open) | **P1** | 4.2-followup multi-asset | Humano + Nelo probe vigência WIN |

---

## §5 — Comandos úteis (Nelo)

```bash
# Listar quirks por status
@nelo *quirks --status open
@nelo *quirks --status validated
@nelo *quirks --status refuted

# Adicionar nova quirk (Nelo)
@nelo *add-quirk "{description}"

# Audit completo (Aria pré-release)
@architect *audit-quirks --release-candidate
```

---

## §6 — Histórico de consolidações

| Data | Curador | Ação |
|------|---------|------|
| 2026-05-05 | Aria 🏛️ | **Consolidação inicial** — separação QUIRKS.md (vivo) vs HISTORICAL (refuted/bug fechado) vs OPEN_P1 (P0/P1 ativas). Triggered por: Story 1.7g Done, Q17-CLOSED, ADR-022 Accepted, Council Sol COUNCIL-35. |
| 2026-06-04 (programado) | Aria 🏛️ | **Migração 30d** — Q-DRIFT-33/34/35/36 completam ciclo HOTFIX-VALIDATED → arquivar de QUIRKS.md para HISTORICAL §2. |

---

— Aria 🏛️, guardiã da arquitetura
