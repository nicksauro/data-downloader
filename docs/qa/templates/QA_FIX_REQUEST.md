# QA Fix Request — `{{ story_id }}`

> Gerado por Quinn quando `*qa-gate` retorna **FAIL**. Consumido por Dex via
> `*apply-qa-fixes`. Salvar em `docs/qa/QA_FIX_REQUESTS/{{ story_id }}.md`.

---

## 1. Header

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **story_id**     | `{{ story_id }}`                               |
| **gate_report**  | `docs/qa/QA_REPORTS/{{ story_id }}.md`         |
| **branch**       | `{{ branch_name }}`                            |
| **sha_commit_failing** | `{{ commit_sha }}`                       |
| **data**         | `{{ YYYY-MM-DD }}`                             |
| **gerado_por**   | Quinn 🧪                                        |
| **destinatário** | Dex (dev)                                      |
| **prazo sugerido** | `{{ N }} dias úteis` (CRITICAL = imediato)   |

---

## 2. Resumo executivo

| Severity  | Count | Status                                  |
|-----------|-------|-----------------------------------------|
| CRITICAL  | `{{ N }}` | Bloqueia merge — fix imediato obrigatório |
| HIGH      | `{{ N }}` | Bloqueia release — fix antes de marcar Done |
| MEDIUM    | `{{ N }}` | Pode virar dívida explícita (story spinoff) com aprovação Morgan |
| LOW       | `{{ N }}` | Nice-to-have                            |

**Sequência recomendada para Dex:** atacar CRITICAL → HIGH → MEDIUM → LOW (top-down nas seções abaixo).

---

## 3. Findings priorizados

### 🔴 CRITICAL

#### F-C-{{ N }} — `{{ short_title }}`

| Campo                    | Valor                                          |
|--------------------------|------------------------------------------------|
| **arquivo:linha**        | `{{ file_path }}:{{ line_number }}`            |
| **descrição**            | `{{ what_is_wrong_in_one_sentence }}`          |
| **causa raiz suspeita**  | `{{ root_cause_hypothesis }}`                  |
| **sugestão de fix**      | `{{ proposed_change_in_prose }}`               |
| **regression test**      | `{{ tests/path/test_file.py::test_name }}` (criar se não existir) |

**Evidência (snippet de log/teste):**

```
{{ failing_log_or_test_output }}
```

**Reprodução mínima:**

```python
{{ minimal_repro_code_or_command }}
```

**Manual/ADR ref (se aplicável):** `{{ ProfitDLL §X | ADR-Y | INV-Z | docs/storage/SCHEMA.md §K }}`

<!-- Repetir bloco F-C-N para cada CRITICAL. -->

---

### 🟠 HIGH

#### F-H-{{ N }} — `{{ short_title }}`

| Campo                    | Valor                                          |
|--------------------------|------------------------------------------------|
| **arquivo:linha**        | `{{ file_path }}:{{ line_number }}`            |
| **descrição**            | `{{ what }}`                                   |
| **causa raiz suspeita**  | `{{ root_cause }}`                             |
| **sugestão de fix**      | `{{ proposed_change }}`                        |
| **regression test**      | `{{ test_target }}`                            |

**Evidência:**

```
{{ evidence }}
```

<!-- Repetir bloco F-H-N para cada HIGH. -->

---

### 🟡 MEDIUM

#### F-M-{{ N }} — `{{ short_title }}`

| Campo                    | Valor                                |
|--------------------------|--------------------------------------|
| **arquivo:linha**        | `{{ file:line }}`                    |
| **descrição**            | `{{ what }}`                         |
| **causa raiz suspeita**  | `{{ root_cause }}`                   |
| **sugestão de fix**      | `{{ proposed_change }}`              |
| **regression test**      | `{{ test_target }}`                  |
| **alternativa: virar dívida** | `{{ debt_story_id_proposed }}` (se Morgan aprovar) |

<!-- Repetir bloco F-M-N para cada MEDIUM. -->

---

### 🟢 LOW

#### F-L-{{ N }} — `{{ short_title }}`

| Campo            | Valor                  |
|------------------|------------------------|
| **arquivo:linha** | `{{ file:line }}`     |
| **descrição**    | `{{ what }}`           |
| **sugestão**     | `{{ proposed_change }}`|

<!-- Repetir bloco F-L-N para cada LOW. -->

---

## 4. Workflow de aplicação (Dex)

1. Dex lê este arquivo via `*apply-qa-fixes {{ story_id }}`.
2. Dex aplica fixes em ordem: CRITICAL → HIGH → MEDIUM → LOW.
3. Para cada finding fixado, marcar checkbox abaixo e referenciar commit:
   - [ ] F-C-1 → fix em `{{ commit_sha }}`
   - [ ] F-H-1 → fix em `{{ commit_sha }}`
   - [ ] ...
4. Para cada finding com regression test sugerido, escrever teste antes ou junto com o fix.
5. Dex re-submete a story para `Quinn *qa-gate {{ story_id }}` (re-execução do gate).
6. Quinn re-emite QA_REPORT — só verifica os findings listados aqui (não re-roda checklist do zero, exceto se Quinn julgar que o escopo do fix exige).

> **Limite de iterações:** Quinn aceita até 5 ciclos `qa-gate → fix-request → fix → qa-gate`. No 6º, escala para Aria/Morgan.

---

## 5. Findings que NÃO viram fix (justificar aqui)

> Se Quinn entendeu que algum item observado durante a auditoria deve ser dispensado
> (ex: falso positivo, fora de escopo da story), documentar aqui para rastro.

- `{{ observed_item }}` → `{{ rationale_for_skip }}`

---

## 6. Assinatura

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **agente**       | `quinn (qa)`                                   |
| **commit_sha**   | `{{ fix_request_commit_sha }}`                 |
| **timestamp**    | `{{ ISO8601 }}`                                |

— Quinn 🧪 (devolvendo a Dex)
