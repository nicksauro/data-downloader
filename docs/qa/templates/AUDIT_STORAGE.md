# Audit Report — Storage / Schema (Sol)

> Template para `Sol *audit-storage-pr`. Preencher um arquivo deste por auditoria,
> salvar em `docs/qa/AUDITS/storage/{{ story_id }}-{{ date }}.md`.

---

## 1. Header

| Campo                | Valor                                             |
|----------------------|---------------------------------------------------|
| **story_id**         | `{{ story_id }}` (ex: 1.4)                        |
| **agente_auditado**  | `{{ agent_audited }}` (ex: Dex)                   |
| **arquivo_auditado** | `{{ file_paths }}` (ex: `src/data_downloader/storage/writer.py`, `src/data_downloader/storage/catalog.py`) |
| **data**             | `{{ YYYY-MM-DD }}`                                |
| **sha_commit**       | `{{ commit_sha }}`                                |
| **auditor**          | Sol 💾 (storage-engineer)                          |
| **schema_ref**       | `docs/storage/SCHEMA.md` v`{{ schema_version }}`  |

---

## 2. Escopo

- **Em escopo:** `{{ in_scope }}` (ex: write path, dedup, atomic write, catálogo SQLite)
- **Fora de escopo:** `{{ out_of_scope }}` (ex: orchestrator, CLI)
- **Tabelas/arquivos tocados:**
  - `{{ table_or_file_1 }}`
  - `{{ table_or_file_2 }}`
- **Mudou schema?** `{{ yes/no }}` — se sim, `schema_version` antigo `{{ old }}` → novo `{{ new }}`

---

## 3. Checklists

### 3.1 schema_change_review (apenas se mudou schema)

> Origem: `agents/storage-engineer.md` → `checklists.schema_change_review`

- [ ] É aditivo (campo novo nullable) ou quebrador?
- [ ] `schema_version` foi bumpado?
- [ ] Script de migração existe (se quebrador)?
- [ ] ADR atualizado?
- [ ] Aria foi consultada (se afeta interface pública)?
- [ ] Projetos downstream foram comunicados?

### 3.2 storage_pr_review

> Origem: `agents/storage-engineer.md` → `checklists.storage_pr_review`

- [ ] Idempotência preservada (re-rodar não duplica)?
- [ ] Append-only respeitado (sem overwrite silencioso)?
- [ ] Catálogo atualizado na mesma transação lógica?
- [ ] `schema_version` escrito no metadata Parquet?
- [ ] Checksum calculado e armazenado?
- [ ] Testes cobrem dedup, gap detection, schema versioning?
- [ ] `fsync(parent_dir)` pós-replace (durabilidade Linux/Windows)?
- [ ] Threshold de rewrite vs new file aplicado (evita O(n²) append)?

### 3.3 contract_validation (apenas se story toca contratos/calendário)

> Origem: `agents/storage-engineer.md` → `checklists.contract_validation`

- [ ] Letra de mês confere com tabela CME/B3?
- [ ] `vigent_from` / `vigent_until` validados contra calendário B3?
- [ ] Probe na DLL retornou trades reais (não NL_EXCHANGE_UNKNOWN)?
- [ ] `validation_source` preenchido corretamente?

---

## 4. Achados (Findings)

### F-{{ N }} — `{{ severity }}` — `{{ title }}`

- **Arquivo:** `{{ file_path }}:{{ line }}`
- **Descrição:** `{{ what_is_wrong }}`
- **Manual ref:** `docs/storage/SCHEMA.md` §`{{ section }}` ou `INTEGRITY.md` §`{{ section }}`
- **Sugestão de fix:** `{{ proposed_fix }}`
- **Regression test sugerido:** `{{ test_path::test_name }}`

<!-- Repetir bloco F-N para cada achado. Se 0 findings, escrever "Nenhum finding." -->

---

## 5. Decisão

| Verdict             | Marcar |
|---------------------|--------|
| ✅ APPROVED         | [ ]    |
| 🟡 CHANGES_REQUESTED | [ ]    |
| 🔴 BLOCKED          | [ ]    |

**Justificativa:** `{{ verdict_rationale }}`

**Próxima ação:**
- APPROVED → Dex segue; Quinn pode rodar `*qa-gate`
- CHANGES_REQUESTED → Dex aplica fixes; re-auditoria
- BLOCKED → Escalar Aria (decisão arquitetural) ou Morgan (replanejamento)

---

## 6. Assinatura digital

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **agente**       | `sol (storage-engineer)`                       |
| **commit_sha**   | `{{ audit_commit_sha }}`                       |
| **co_authored**  | `Co-Authored-By: Sol (Storage Engineer) <agent@data-downloader.local>` |
| **timestamp**    | `{{ ISO8601 }}`                                |

— Sol 💾
