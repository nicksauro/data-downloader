# QA Gate Report — `{{ story_id }}`

> Template para `Quinn *qa-gate {{ story-id }}`. Salvar em
> `docs/qa/QA_REPORTS/{{ story_id }}.md`. Verdict é **inegociável** — Dex não merge sem PASS/CONCERNS.

---

## 1. Header

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **story_id**     | `{{ story_id }}` (ex: 1.4)                     |
| **story_path**   | `docs/stories/{{ story_id }}.story.md`         |
| **branch**       | `{{ branch_name }}`                            |
| **sha_commit**   | `{{ commit_sha }}` (HEAD do branch auditado)   |
| **data**         | `{{ YYYY-MM-DD }}`                             |
| **gatekeeper**   | Quinn 🧪 (qa)                                   |
| **dev**          | `{{ implementer }}` (ex: Dex)                  |

---

## 2. Acceptance Criteria checklist

> Cada AC da story marcada Pass / Fail / N/A. Citar evidência (test name, file, log).

| AC   | Descrição (resumo)            | Resultado | Evidência                                  |
|------|-------------------------------|-----------|--------------------------------------------|
| AC1  | `{{ ac1_summary }}`           | Pass / Fail / N/A | `{{ test_path::test_name }}` ou `log:line` |
| AC2  | `{{ ac2_summary }}`           | Pass / Fail / N/A | ...                                        |
| AC3  | ...                           | ...       | ...                                        |
| ...  | ...                           | ...       | ...                                        |

**ACs Fail count:** `{{ N }}` — bloqueia PASS se > 0.

---

## 3. Test results

### 3.1 pytest summary

```
{{ pytest_oneline_output }}
```

| Métrica           | Valor              |
|-------------------|--------------------|
| Total tests       | `{{ N }}`          |
| Passed            | `{{ N }}`          |
| Failed            | `{{ N }}`          |
| Skipped           | `{{ N }}`          |
| xfail / xpassed   | `{{ N }} / {{ N }}` |
| Duração           | `{{ S }}s`         |

**Falhas detalhadas (se houver):**

```
{{ failure_details }}
```

### 3.2 Coverage report

| Módulo                       | Cobertura | Threshold | Status |
|------------------------------|-----------|-----------|--------|
| `data_downloader/storage/`   | `{{ X }}%` | >= 80%   | ✅/❌ |
| `data_downloader/orchestrator/` | `{{ X }}%` | >= 80% | ✅/❌ |
| `data_downloader/dll/`       | `{{ X }}%` | >= 70%   | ✅/❌ |
| `data_downloader/ui/`        | `{{ X }}%` | >= 60%   | ✅/❌ |
| `data_downloader/contracts/` | `{{ X }}%` | >= 90%   | ✅/❌ |
| **Global**                   | `{{ X }}%` | >= 75%   | ✅/❌ |

Comando reproduzível:
```
pytest --cov=src/data_downloader --cov-report=term-missing --cov-report=xml
```

### 3.3 Lint / Typecheck

| Tool          | Resultado                        |
|---------------|----------------------------------|
| `ruff check`  | ✅ clean / ❌ `{{ N }}` issues    |
| `mypy` ou `pyright` | ✅ clean / ❌ `{{ N }}` errors |

---

## 4. Smoke test (se story afeta path de download)

| Campo                  | Valor                                    |
|------------------------|------------------------------------------|
| Aplicável?             | `{{ yes/no }}` (se `no`, justificar)     |
| Resultado              | PASS / FAIL / N/A                        |
| Evidência              | `docs/qa/smoke_runs/{{ date }}-{{ story_id }}.md` |
| Hashes Parquet         | `{{ sha256_list }}`                      |
| Re-run idempotente?    | `{{ yes/no }}` (cache_hit observado em log)|

> Protocolo completo: `docs/qa/SMOKE_PROTOCOL.md`

---

## 5. Data validation (se story produziu Parquet)

| Check                                    | Resultado |
|------------------------------------------|-----------|
| Sem duplicatas em `(symbol, ts_ns, trade_id)` | ✅/❌ |
| Timestamps monotônicos por partição      | ✅/❌ |
| `schema_version` presente em todo Parquet | ✅/❌ |
| Catálogo SQLite reconciliado             | ✅/❌ |
| Sem gaps em dias úteis (exceto holidays) | ✅/❌ |
| `price > 0 AND quantity > 0` em 100%     | ✅/❌ |
| `exchange` em `('F', 'B')`               | ✅/❌ |
| Contagem em ordem de magnitude esperada  | ✅/❌ |

> Relatório completo: `docs/qa/INTEGRITY_REPORTS/{{ date }}.md`

---

## 6. CodeRabbit (advisory, se habilitado)

> Ver `docs/qa/CODE_RABBIT_INTEGRATION.md` para política exata.

| Severity   | Count | Política                              |
|------------|-------|---------------------------------------|
| CRITICAL   | `{{ N }}` | Exige fix antes de PASS (bloqueante) |
| HIGH       | `{{ N }}` | Vira dívida documentada              |
| MEDIUM     | `{{ N }}` | Vira dívida documentada              |
| LOW        | `{{ N }}` | Informativo                          |

**CRITICAL findings (se houver):**
- F-CR-1: `{{ file:line }}` — `{{ description }}` — fix em `{{ commit }}` ou pendente

---

## 7. Audits dependentes

| Auditoria                      | Necessária? | Verdict        | Path                                                |
|--------------------------------|-------------|----------------|-----------------------------------------------------|
| Nelo `*audit-wrapper`          | `{{ y/n }}` | APPROVED / CR / BLOCKED | `docs/qa/AUDITS/wrapper/{{ story_id }}-{{ date }}.md` |
| Sol `*audit-storage-pr`        | `{{ y/n }}` | APPROVED / CR / BLOCKED | `docs/qa/AUDITS/storage/{{ story_id }}-{{ date }}.md` |
| Aria `*review-design`          | `{{ y/n }}` | APPROVED / CR / BLOCKED | `docs/qa/AUDITS/design/{{ story_id }}-{{ date }}.md`  |

> Regra: qualquer auditoria dependente com verdict ≠ APPROVED bloqueia PASS, exceto via WAIVED documentado (ver `docs/qa/WAIVERS/README.md`).

---

## 8. Findings (severity matrix)

> Findings desta gate. Se >= 1 CRITICAL ou >= 3 HIGH, verdict não pode ser PASS.

### CRITICAL
- F-C-1: `{{ file:line }}` — `{{ description }}`

### HIGH
- F-H-1: ...

### MEDIUM
- F-M-1: ...

### LOW
- F-L-1: ...

---

## 9. Verdict final

| Verdict     | Marcar |
|-------------|--------|
| ✅ PASS      | [ ]    |
| 🟡 CONCERNS  | [ ]    |
| 🔴 FAIL      | [ ]    |
| ⚪ WAIVED    | [ ]    |

### Critérios objetivos

| Verdict   | Quando aplicar                                                                 |
|-----------|--------------------------------------------------------------------------------|
| PASS      | Todas ACs Pass + suíte verde + cobertura nos thresholds + audits APPROVED + 0 CRITICAL |
| CONCERNS  | Todas ACs Pass + suíte verde + cobertura ok + 0 CRITICAL + <= 2 HIGH com dívida registrada |
| FAIL      | Qualquer AC Fail OU >= 1 CRITICAL OU >= 3 HIGH OU audit BLOCKED                |
| WAIVED    | FAIL com WAIVER assinado (Aria/Sol/Morgan) em `docs/qa/WAIVERS/{{ story_id }}-{{ date }}.md` |

**Justificativa:** `{{ verdict_rationale }}`

**Se CONCERNS, dívidas tracked:**
- `{{ debt_story_id }}` — `{{ summary }}`

**Se FAIL, próximo passo:** Quinn gera `docs/qa/QA_FIX_REQUESTS/{{ story_id }}.md` para Dex aplicar via `*apply-qa-fixes`.

**Se WAIVED, referenciar:** `docs/qa/WAIVERS/{{ story_id }}-{{ date }}.md`

---

## 10. Assinatura digital

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **agente**       | `quinn (qa)`                                   |
| **commit_sha**   | `{{ report_commit_sha }}`                      |
| **co_authored**  | `Co-Authored-By: Quinn (Gatekeeper) <agent@data-downloader.local>` |
| **timestamp**    | `{{ ISO8601 }}`                                |

— Quinn, no portão 🧪
