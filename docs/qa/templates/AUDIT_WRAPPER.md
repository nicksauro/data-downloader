# Audit Report — Wrapper DLL (Nelo)

> Template para `Nelo *audit-wrapper`. Preencher um arquivo deste por auditoria,
> salvar em `docs/qa/AUDITS/wrapper/{{ story_id }}-{{ date }}.md`.

---

## 1. Header

| Campo                | Valor                                             |
|----------------------|---------------------------------------------------|
| **story_id**         | `{{ story_id }}` (ex: 1.2)                        |
| **agente_auditado**  | `{{ agent_audited }}` (ex: Dex)                   |
| **arquivo_auditado** | `{{ file_path }}` (ex: `src/data_downloader/dll/wrapper.py`) |
| **data**             | `{{ YYYY-MM-DD }}`                                |
| **sha_commit**       | `{{ commit_sha }}` (commit do código auditado)    |
| **auditor**          | Nelo 🗝️ (profitdll-specialist)                    |
| **manual_ref**       | ProfitDLL Manual revisão `{{ manual_revision }}`  |

---

## 2. Escopo

Descrição em prosa do que foi auditado e o que NÃO foi:

- **Em escopo:** `{{ in_scope }}` (ex: callback registration, type bindings, error code handling)
- **Fora de escopo:** `{{ out_of_scope }}` (ex: lógica de orchestrator, persistência)
- **Métodos/funções inspecionados:**
  - `{{ symbol_1 }}` em `{{ file:line }}`
  - `{{ symbol_2 }}` em `{{ file:line }}`

---

## 3. Checklist (wrapper_review)

> Origem: `agents/profitdll-specialist.md` → `checklists.wrapper_review`

- [ ] Tipos ctypes batem com PWideChar (c_wchar_p), Int64 (c_int64), Cardinal (c_uint), Double (c_double), Byte (c_ubyte)?
- [ ] Callbacks usam WINFUNCTYPE (não CFUNCTYPE)? — manual §3.2 linha 2735
- [ ] `_cb_refs` lista global mantida (previne GC)?
- [ ] Callbacks NÃO chamam funções da DLL? — manual §3.2 linha 2730 + §4 linha 4394 (INV-1)
- [ ] Callbacks NÃO fazem I/O (DB, disco)? — manual §4 linha 4391
- [ ] Callbacks usam `queue.put_nowait` (não bloqueiam)?
- [ ] Engine thread separada da ConnectorThread?
- [ ] Agent resolution (GetAgentName) fora do callback?
- [ ] Exchange = "B" ou "F" (letra única)? — manual §3.1 linha 1673
- [ ] Error codes NL_* tratados (NL_OK=0, resto é erro)?
- [ ] Subscribe e Unsubscribe balanceados?
- [ ] DLLFinalize no shutdown (com fallback para Finalize — Q-AMB-03)?
- [ ] Ordens usam V2 (SendOrder, SendChangeOrderV2, SendCancelOrderV2) não V1 obsoletas?
- [ ] Timestamps parseados com tolerância a "." e ":" antes de ms (Q-AMB-02)?
- [ ] GetHistoryTrades usa contrato vigente (WDOJ26) não sintético (WDOFUT) (Q09-E)?
- [ ] Timeout >= 1800s em histórico (Q10-E)?
- [ ] TranslateTrade usado para unpack de V2 trade callback (Q06-V)?
- [ ] **11 callback slots** preenchidos em DLLInitializeMarketLogin (Q11-E) — passar `None` em slots subsequentes corrompe SetHistoryTradeCallback?
- [ ] `SetEnabledLogToDebug(0)` em produção (não vaza handle/console)?

---

## 4. Achados (Findings)

> Cada finding numerado. Severity: CRITICAL | HIGH | MEDIUM | LOW.

### F-{{ N }} — `{{ severity }}` — `{{ title }}`

- **Arquivo:** `{{ file_path }}:{{ line }}`
- **Descrição:** `{{ what_is_wrong }}`
- **Manual ref:** ProfitDLL §`{{ section }}` linha `{{ line_in_manual }}` (ou `Q-XX-Y` para quirk)
- **Sugestão de fix:** `{{ proposed_fix }}`
- **Reprodução mínima (opcional):**
  ```python
  {{ minimal_repro }}
  ```

<!-- Repetir bloco F-N para cada achado. Se 0 findings, escrever "Nenhum finding." -->

---

## 5. Decisão

| Verdict             | Marcar |
|---------------------|--------|
| ✅ APPROVED         | [ ]    |
| 🟡 CHANGES_REQUESTED | [ ]    |
| 🔴 BLOCKED          | [ ]    |

**Justificativa do verdict:** `{{ verdict_rationale }}`

**Próxima ação:**
- APPROVED → Dex pode marcar story Ready for Review e Quinn roda `*qa-gate`
- CHANGES_REQUESTED → Dex aplica fixes nos findings HIGH/CRITICAL e re-submete
- BLOCKED → Escalar para Aria (revisão de design) ou Morgan (replanejamento)

---

## 6. Assinatura digital

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **agente**       | `nelo (profitdll-specialist)`                  |
| **commit_sha**   | `{{ audit_commit_sha }}` (commit deste relatório) |
| **co_authored**  | `Co-Authored-By: Nelo (ProfitDLL Specialist) <agent@data-downloader.local>` |
| **timestamp**    | `{{ ISO8601 }}`                                |

— Nelo 🗝️
