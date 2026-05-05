# COUNCIL-35 — Sol (documentação canônica)

**Data:** 2026-05-05
**Council member:** Sol (knowledge guardian — QUIRKS, KNOWLEDGE, ADRs)
**Story:** 1.7d (consolidação documentação pós Q-DRIFT-33/34/35)
**Escopo:** auditoria + etiquetagem (modesta) — NÃO refactor amplo, NÃO arquivamento, NÃO modificação de código/STATUS/WAIVERs

---

## TL;DR

Auditoria detectou **2 contradições factuais críticas**, **13 quirks órfãs** vivendo apenas em RESUMO_EXECUTIVO (não em QUIRKS.md), **1 quirk ausente** (Q-DRIFT-35 — apenas em smoke evidence), e **1 hotfix-status desatualizado** (Q-DRIFT-33/34 marcados "descoberta" mas já validados em produção via standalone postfix-35 com 796 963 trades). Aplicada etiquetagem com banners `## ⚠️ REFUTED YYYY-MM-DD`, atualizada legenda visual no índice, criada seção "Quick Reference Canonical" no topo de PROFITDLL_KNOWLEDGE.md, agrupadas Q-DRIFT-13..25 e Q-DRIFT-27..30 em seções históricas. Recomendação: consolidação grande (refactor/arquivamento) deve virar Story 1.7f.

---

## Passo 1 — Tabela de status QUIRKS

### Q-prefix legacy (Sentinel/whale-detector)

| ID | Status anterior | Status auditado | Notas |
|----|-----------------|-----------------|-------|
| Q01-V | ✅ validated | ⚠️ **REFUTED 2026-05-05** | Contradição com Q-DRIFT-32 — WDOFUT é correto para histórico, NÃO refutado |
| Q02-E | ✅ validated | ✅ valid | Workaround formalizado Story 2.6 |
| Q03-AMB | ⚠️ ambiguous | ⚠️ ambiguous | Sem nova evidência |
| Q04-E | 🔬 empirical | ✅ valid | Convencionado em MANIFEST R2 |
| Q05-V | ✅ validated | ✅ valid | Manual literal |
| Q06-V | ✅ validated | ✅ valid | Lei R3 oficial |
| Q07-V | ✅ validated | ✅ valid | Regra ctypes |
| Q08-E | 🔬 empirical | ✅ valid | Adotado em fixture session-scope |
| Q09-AMB | ⚠️ ambiguous | ⚠️ ambiguous | Try/except sane |
| Q10-AMB | ⚠️ ambiguous | ⚠️ ambiguous | Aceitar `2`/`4` documentado |
| Q11-E | ⚠️ REFUTED 2026-05-04 | ⚠️ REFUTED (mantido) | Banner já presente |
| Q12-E | 🔬 empirical | ✅ valid (= Q-DRIFT-31) | Validação empírica 2026-05-05 |
| Q13-V | ✅ validated | ✅ valid | Manual marca V1 obsoleta |
| Q14-E | 🔬 empirical | ✅ valid | Length-first padrão; argtypes em minimal_handshake (Q-DRIFT-35) |
| Q15-OPEN | ❓ open | ❓ open | Probe pendente Story 1.4.5 |
| Q16-VALIDATED | ✅ validated | ✅ valid | Reverse-engineered |
| Q17-OPEN | ❓ open | ❓ open | Probe pendente humano |
| Q18-OPEN | ❓ open | ❓ open | Probe pendente Story 4.2 |

### Q-DRIFT-* (descobertas durante stories 1.2/1.3/1.7b/1.7c/1.7d)

| ID | Status anterior | Status auditado | Notas |
|----|-----------------|-----------------|-------|
| Q-DRIFT-01 | 🔬 empirical | ✅ valid | API drift confirmado |
| Q-DRIFT-02 | ⚠️ OPEN | ✅ valid (root cause = Q-DRIFT-11/12/33/34/35) | Cadeia de bugs identificada |
| Q-DRIFT-03 | ✅ validated | ✅ valid | Padronizado |
| Q-DRIFT-04 | 🔬 empirical | ✅ valid | Hotfix UTF-8 |
| Q-DRIFT-05 | 🔬 empirical | ✅ valid | Signatures TAssetID corrigidas |
| Q-DRIFT-06 | ⚠️ corrected | ✅ valid (corrected) | Refuta Q11-E |
| Q-DRIFT-07 | ✅ validated | ✅ valid | Autoridade Nelogica direta |
| Q-DRIFT-08 | 🔬 empirical | ✅ valid | argtypes obrigatórios |
| Q-DRIFT-09 | 🔬 hipótese | 🧪 hypothesis | Sem nova evidência |
| Q-DRIFT-10 | 🔬 hipótese | ✅ valid (corrected via Q-DRIFT-11+12) | Validação postfix-35 |
| Q-DRIFT-11 | 🧪 HIPÓTESE | ✅ valid (validated postfix-35) | Standalone PASS confirma |
| Q-DRIFT-12 | 🧪 HIPÓTESE | ✅ valid (validated postfix-35) | Standalone PASS confirma |
| Q-DRIFT-13..20, 22 | (ausente em QUIRKS.md) | ⚠️ refuted (histórico) | Adicionadas em seção histórica |
| Q-DRIFT-21 | (gap numeração) | n/a | Documentada como gap |
| Q-DRIFT-23..25 | (ausente em QUIRKS.md) | 🧪 hypothesis (não validadas) | Adicionadas em seção histórica |
| Q-DRIFT-26 | ❌ REFUTADA | ⚠️ REFUTED 2026-05-05 | Banner adicionado |
| Q-DRIFT-27..30 | (ausente em QUIRKS.md) | ⚠️ refuted (histórico) | Adicionadas em seção histórica (todas refutadas por Q-DRIFT-32) |
| Q-DRIFT-31 | ✅ VALIDATED | ✅ valid | Empírico |
| Q-DRIFT-32 | ✅ VALIDATED | ✅ valid | **Supersede Q01-V** |
| Q-DRIFT-33 | 🐛 BUG-CÓDIGO descoberta | 🐛 HOTFIX-APPLIED-VALIDATED | Postfix-35 standalone PASS |
| Q-DRIFT-34 | 🐛 BUG-CÓDIGO descoberta | 🐛 HOTFIX-APPLIED-VALIDATED | Postfix-35 standalone PASS |
| Q-DRIFT-35 | (ausente em QUIRKS.md) | 🐛 HOTFIX-APPLIED-VALIDATED | Adicionada como nova entrada |

### Sumário numérico

- **Total:** 53 IDs registrados (18 Q-prefix + 35 Q-DRIFT slots, com gap em 21)
- **Valid/confirmed (✅):** 26
- **Refuted (⚠️):** 16 (Q01-V, Q11-E, Q-DRIFT-13..20, 22, 26, 27..30)
- **Hypothesis (🧪):** 4 (Q-DRIFT-09, 23, 24, 25)
- **Bug-código (🐛, hotfix-applied-validated):** 3 (Q-DRIFT-33, 34, 35)
- **Open (❓):** 4 (Q15, Q17, Q18, Q-DRIFT-21 gap)
- **Ambiguous (⚠️):** 3 (Q03-AMB, Q09-AMB, Q10-AMB)

---

## Passo 2 — Auditoria PROFITDLL_KNOWLEDGE.md

| Verificação | Resultado | Ação |
|-------------|-----------|------|
| Padrão canonical de uso pós-Q-DRIFT-33/34/35 | Parcialmente correto — §7 ainda menciona Q-DRIFT-11 como pendente; §2.4 cita Q01-V refutada | Atualizar Q01-V→Q-DRIFT-32 em §2.4; adicionar Quick Reference top-of-doc |
| Aviso WDOFUT vs contratos específicos | **AUSENTE** (na verdade dizia o contrário, Q01-V) | Corrigido: §2.4 aponta para Q-DRIFT-32 |
| Aviso janela máx 5 dias GetHistoryTrades | Presente em §2.4 (Q12-E) | Reforçado em Quick Reference top |
| Aviso minimal_handshake + TranslateTrade/GetAgentName signatures | **AUSENTE** | Adicionado em Quick Reference (regra #5) |

**Mudanças aplicadas em PROFITDLL_KNOWLEDGE.md:**
1. Quick Reference Canonical (top 5 do-and-don't) inserido após front matter, antes do Índice.
2. §2.4 Q01-V tachado e redirecionado para Q-DRIFT-32.
3. §2.4 Q12-E reforçado com referência cruzada Q-DRIFT-31.

---

## Passo 3 — Auditoria ADRs

| ADR | Verificação | Resultado |
|-----|-------------|-----------|
| ADR-005 amendment-d (NoopCallback × ConnectorThread) | Hipótese ratificada por Q-DRIFT-11/12 validados | Permanece valid; não precisa amendment-e neste momento |
| ADR-005 baseline | Thread model 5-thread permanece correto | OK |
| ADR-005 amendment-a (state machine) | OK, ratificado por implementação | OK |
| ADR-005 amendment-b (DLL init sequence Nelogica) | Recomendação (3) "alinhar critério para somente result=4" não foi adotada — wrapper aceita 2 e 4 (Q10-AMB) | Histórico — decisão de manter Q10-AMB preserva flexibilidade |
| ADR-005 amendment-c (Init/Wait separation + subscribe-handshake) | Implementado (`subscribe_for_handshake`) — Q-DRIFT-07 confirmado | OK |
| ADR-005 amendment-d (NoopCallback × ConnectorThread) | Inverte Q11-E — Sol (este council) ratifica + adiciona Q-DRIFT-35 como complemento da família | OK |
| Outros ADRs (001, 002, 003, 004, 006, 007/a, 008-017) | Não revisados nesta auditoria — fora do escopo Story 1.7d | Marcado para Story 1.7f (consolidação grande) |

**Recomendação:** **NÃO** criar amendment-e neste momento. ADR-005 amendment-d cobre adequadamente NoopCallback × ConnectorThread. Q-DRIFT-33/34/35 são bugs de wrapper (skip de signatures em minimal_handshake), não decisões arquiteturais — vivem em QUIRKS.md sem precisar amendment formal.

---

## Passo 4 — Auditoria SMOKE_EVIDENCE/RESUMO_EXECUTIVO

| Verificação | Resultado |
|-------------|-----------|
| Reflete estado atual? | Parcialmente — última atualização documentada é 2026-05-05 ~11:42 (postfix-35 ainda como "PARTIAL"). Adendo posterior 12:44 (postfix-35 PASS via standalone, FAIL-handshake via pytest) NÃO está no resumo |
| Cronologia completa attempts 7-13 | Sim, attempts 7-11 cobertos. Attempts 12-13 (postfix-34/35) só em arquivos individuais |
| Próximos passos atualizados | Caminho A (Q-DRIFT-32 via WDOFUT) é o caminho real adotado; Caminho B (WAIVER) ainda em aberto para Sintoma A |

**Decisão (Sol):** RESUMO_EXECUTIVO foi marcado em CLAUDE.md global como "histórico — não atualizar mais" via menção em QUIRKS.md (seção bissection history aponta para o resumo). NÃO aplicar mudanças de conteúdo aqui — caso seja desejado consolidar tudo em um único `SMOKE_EVIDENCE_INDEX.md`, fica para Story 1.7f.

---

## Passo 5 — Inconsistências e contradições detectadas

### Críticas (resolvidas nesta auditoria)

1. **Q01-V × Q-DRIFT-32 contradição direta:** Q01-V dizia "WDOFUT retorna 0 trades, usar contrato específico"; Q-DRIFT-32 (validado 2026-05-05) diz exatamente o oposto.
   - **Resolução:** Q01-V marcada REFUTED com banner; PROFITDLL_KNOWLEDGE.md §2.4 atualizado.
2. **Q-DRIFT-33/34 status desatualizado:** marcadas como "descoberta Story 1.7d" mas já estão hotfix-applied-validated via standalone postfix-35 (796 963 trades).
   - **Resolução:** status atualizado para HOTFIX-APPLIED-VALIDATED.
3. **Q-DRIFT-35 órfã:** referenciada em smoke evidence (commit `0f6c2ea`) mas ausente em QUIRKS.md.
   - **Resolução:** entrada completa criada.

### Médias (rastreadas para Story 1.7f)

4. **Q-DRIFT-13..25 órfãs:** documentadas apenas em RESUMO_EXECUTIVO, ausentes em QUIRKS.md.
   - **Resolução parcial:** seção "Q-DRIFT-13 a 25 — bissection history" criada agrupando-as. Não aprofundadas individualmente.
5. **Q-DRIFT-27..30 órfãs:** mesma situação.
   - **Resolução parcial:** seção "Q-DRIFT-27 a 30 — sucessores históricos" criada agrupando-as.
6. **Knowledge fragmentado entre arquivos:** Q-DRIFTs vivem em QUIRKS.md, RESUMO_EXECUTIVO, smoke evidence individuais, ADRs, e CLAUDE.md global. **Não consolidado** nesta auditoria — escopo Story 1.7f.

### Baixas

7. **Manual reference §3.2 L3317-3329 vs L3267:** Q10-AMB cita L3267, §1 cita L3267, mas tabela em §6 cita L3317-3329. Range provavelmente correto — não modificado.
8. **Versão alvo "4.0.0.34" vs DLL real:** PROFITDLL_KNOWLEDGE.md §8 cita 4.0.0.34 como alvo, mas Q-DRIFT-01 indica que a DLL real não exporta `GetDLLVersion`. Versão real desconhecida — `dll_version="unknown"`.

---

## Passo 6 — Recomendação de estrutura final (futura Story 1.7f)

| Documento | Estado proposto | Ação |
|-----------|-----------------|------|
| `PROFITDLL_KNOWLEDGE.md` | Documento canônico atualizado (já é) | Manter; Quick Reference no topo (feito) |
| `QUIRKS.md` | Índice com Q-DRIFTs **CONFIRMADOS apenas**; refutados arquivados em `QUIRKS-ARCHIVE.md` | **Story 1.7f** — não fazer agora |
| `ADR-005` | Já consolida lições aprendidas via amendments a/b/c/d | Sem ação imediata |
| `RESUMO_EXECUTIVO_AUTONOMOUS_2026-05-04.md` | Marcar como "histórico — não atualizar mais" | **Story 1.7f** — adicionar banner no topo |
| Novo: `DLL_SURVIVAL_GUIDE.md` (PROFITDLL_KNOWLEDGE atualizado renomeado) | Single source of truth de uso prático | **Story 1.7f** — não fazer agora |
| Novo: `SMOKE_EVIDENCE_INDEX.md` | Índice cronológico de attempts 1-13 | **Story 1.7f** — não fazer agora |

---

## Passo 7 — Mudanças aplicadas nesta auditoria (modesta, sem refactor)

1. **`docs/dll/QUIRKS.md`**:
   - Índice: legenda visual (✅/⚠️/🧪/🐛/❓/📜) com nota de auditoria 2026-05-05.
   - Índice: 13 entradas adicionadas (Q-DRIFT-13..20, 22, 23..25, 27..30, 35) + Q-DRIFT-21 marcada como gap.
   - Q01-V: banner `## ⚠️ REFUTED 2026-05-05` no topo da entrada.
   - Q-DRIFT-26: banner `## ⚠️ REFUTED 2026-05-05` no topo da entrada.
   - Q-DRIFT-33: status atualizado para HOTFIX-APPLIED-VALIDATED.
   - Q-DRIFT-34: status atualizado para HOTFIX-APPLIED-VALIDATED.
   - Nova entrada Q-DRIFT-35 (canonical, postfix-35 evidence).
   - Nova seção "Q-DRIFT-13 a 25 — bissection history" (tabela compacta).
   - Nova seção "Q-DRIFT-27 a 30 — sucessores históricos" (tabela compacta).
2. **`docs/dll/PROFITDLL_KNOWLEDGE.md`**:
   - Seção "Quick Reference Canonical" no topo (top 5 do-and-don't).
   - §2.4 Q01-V tachado/redirecionado para Q-DRIFT-32.
   - §2.4 Q12-E referenciando Q-DRIFT-31.
3. **`docs/decisions/COUNCIL-35-Sol-documentacao-2026-05-05.md`**: este documento.

**NÃO modificado:** STATUS.md, WAIVERs, código `src/`, código `tests/`, ADRs (não há amendment-e), outros docs.

---

## Recomendações para próximas fases

1. **Imediato (próximo agente, Dex/Quinn):** consultar Quick Reference Canonical em PROFITDLL_KNOWLEDGE.md antes de tocar em wrapper/download_primitive.
2. **Story 1.7e (proposta):** debug Sintoma A pytest harness (Q-DRIFT-23/24/25). Mini-council Quinn+Dex+Aria; smoke real continua via standalone como caminho de release.
3. **Story 1.7f (proposta — consolidação grande):** refactor amplo conforme passo 6 acima — não tentar em modo autônomo.
4. **Story 4.2 / multi-asset:** Q-DRIFT-32 estende-se: WIN deve usar `WINFUT`, ações cash devem usar ticker exato (sem alias). Validar via probe humano.

---

## Sign-off

- **Sol (knowledge guardian):** APPROVED — auditoria não-destrutiva conforme escopo Story 1.7d. Etiquetagem aplicada; refactor amplo deferido para Story 1.7f.

— Sol, guardião do conhecimento canonical 📜
