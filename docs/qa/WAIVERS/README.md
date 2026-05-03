# WAIVERS — Mecânica Operacional

> Resolução do **finding M2** (PLAN_REVIEW 2026-05-03):
> "WAIVED não tem mecânica operacional".
>
> Este documento define o protocolo único para emitir, assinar, armazenar e
> auditar WAIVERS no squad data-downloader.

---

## 1. O que é um WAIVER

Um **WAIVER** é uma exceção formal e documentada em que Quinn aceita marcar
o gate de QA como `WAIVED` (em vez de `FAIL`) para permitir que uma story
prossiga apesar de um finding aberto.

**WAIVED não significa "ignorado".** Significa:

1. O finding é **conhecido**, **documentado** e **com prazo de remediação**.
2. Existe **autoridade explícita** (1 assinatura de Aria, Sol ou Morgan) aceitando o risco.
3. Existe **story-debt criada** que rastreia a remediação até o fechamento.

WAIVED é a válvula de escape **rara**. Default = corrigir o finding, não pular.

---

## 2. Quando usar WAIVED

✅ **Cenários aceitáveis:**

- Bug em dependência externa (DLL Nelogica, biblioteca terceira) sem workaround viável até release X.
- Optimização de performance fora do orçamento da story atual, com benchmark mostrando impacto aceitável e deadline acordado.
- Schema temporariamente incompleto enquanto Sol finaliza migration framework, com prazo bem definido.
- Smoke test infraestruturalmente impossível na janela atual (ex: licença Nelogica não renovada), com substituição por evidência alternativa documentada.

❌ **Cenários NÃO aceitáveis (Quinn rejeita o WAIVER):**

- "Não quero refatorar agora" — sem prazo, sem story-debt → FAIL.
- "Cobertura está baixa porque deu preguiça" → FAIL.
- "Smoke test pulou porque não rodei" → FAIL.
- Violação de invariante de integridade de dados (INV-1..INV-12) → **NUNCA WAIVED**.
- Violação constitucional (princípios de MANIFEST.md) → **NUNCA WAIVED**.

---

## 3. Localização e nomenclatura

```
docs/qa/WAIVERS/
├── README.md              # este arquivo
├── 1.4-2026-05-15.md      # waiver da story 1.4 emitido em 15/05/2026
├── 1.7b-2026-06-02.md     # waiver da story 1.7b emitido em 02/06/2026
└── ...
```

**Formato do nome:** `{story-id}-{YYYY-MM-DD}.md`

Se a mesma story precisar de mais de um waiver na mesma data, adicionar sufixo:
`1.4-2026-05-15-a.md`, `1.4-2026-05-15-b.md`.

---

## 4. Template obrigatório do arquivo de WAIVER

> Copiar este template inteiro ao criar `WAIVERS/{story-id}-{date}.md`.

```markdown
# WAIVER — `{{ story_id }}` — `{{ YYYY-MM-DD }}`

## Justificativa

`{{ Por que este finding pode prosseguir como WAIVED em vez de FAIL.
   Mínimo 3 frases, com contexto concreto. }}`

## Finding original

| Campo            | Valor                                          |
|------------------|------------------------------------------------|
| **finding_id**   | `{{ F-C-N | F-H-N | F-M-N }}`                  |
| **severity**     | CRITICAL / HIGH / MEDIUM                       |
| **arquivo:linha**| `{{ file:line }}`                              |
| **qa_report_ref**| `docs/qa/QA_REPORTS/{{ story_id }}.md` §`{{ section }}` |
| **descrição**    | `{{ original_finding_description }}`           |

## Risco aceito

`{{ O que pode dar errado em produção / dataset por aceitar este WAIVER.
   Quantificar quando possível: "delay de 50ms por callback" /
   "perda de 1 trade a cada 10k em situação X" / etc. }}`

## Plano de remediação

| Campo                    | Valor                                |
|--------------------------|--------------------------------------|
| **prazo_remediacao**     | `{{ YYYY-MM-DD }}` (data limite)     |
| **story_debt_criada**    | `{{ debt_story_id }}` (link p/ story de remediação) |
| **bloqueia_release**     | `{{ V1 | V1.1 | V2 | none }}`        |

## Aprovador (1 assinatura suficiente)

| Aprovador  | Domínio                       | Marcar | Assinatura                          |
|------------|-------------------------------|--------|-------------------------------------|
| Aria 🏛️    | arquitetural                  | [ ]    | `Co-Authored-By: Aria (Architect) <agent@data-downloader.local>` |
| Sol 💾     | storage / schema / catálogo   | [ ]    | `Co-Authored-By: Sol (Storage Engineer) <agent@data-downloader.local>` |
| Morgan 📋  | produto / escopo / prioridade | [ ]    | `Co-Authored-By: Morgan (PM) <agent@data-downloader.local>` |

> **Regra de jurisdição:** o aprovador deve corresponder ao domínio do finding.
> Finding de schema → Sol. Finding de fronteira/thread/ADR → Aria. Finding de
> escopo/prazo/prioridade → Morgan. Em ambiguidade, escalar para Aria.

## Assinatura digital

| Campo                    | Valor                                  |
|--------------------------|----------------------------------------|
| **commit_sha_waiver**    | `{{ commit_sha_do_arquivo_waiver }}`   |
| **commit_author**        | `{{ approver_email }}`                 |
| **co_authored_by**       | (linha conforme tabela acima)          |
| **timestamp**            | `{{ ISO8601 }}`                        |

## Referência cruzada no PR

Ao mergir o PR da story, o autor DEVE incluir no body do PR:

> WAIVED finding `{{ finding_id }}` — ver `docs/qa/WAIVERS/{{ filename }}` (commit `{{ sha }}`)

## Status (atualizado por Morgan no `*plan` semanal)

- [ ] Aberto (default ao criar)
- [ ] Remediado (linkar PR/commit que fechou)
- [ ] Vencido (passou do `prazo_remediacao` sem remediação — escalar)
```

---

## 5. Quem aprova

| Domínio do finding              | Aprovador padrão | Backup       |
|---------------------------------|------------------|--------------|
| Arquitetura, fronteira, thread, ADR | Aria 🏛️       | Morgan 📋    |
| Storage, schema, catálogo, dedup    | Sol 💾         | Aria 🏛️     |
| Escopo, prazo, prioridade, release  | Morgan 📋      | Aria 🏛️     |
| DLL/wrapper                         | Nelo 🗝️ + Aria 🏛️ (precisa de **ambos**) | — |

**Regra de assinatura:** **1 assinatura suficiente** (exceto DLL, que exige Nelo + Aria).

> ⚠️ Quinn **não** assina WAIVERS próprios — Quinn é o emissor; assinar seria conflito de interesse.

---

## 6. Mecânica de "assinatura digital"

A assinatura é validada por três artefatos convergentes:

1. **Commit author do arquivo `WAIVERS/*.md`** — deve ser o aprovador (ou Quinn, se Quinn é quem digitou em nome do aprovador, com `Co-Authored-By` apontando para o aprovador real).
2. **Linha `Co-Authored-By:`** no commit message (Aria / Sol / Morgan).
3. **SHA do commit do WAIVER referenciado no body do PR** que mergir a story.

A combinação dos três fecha a cadeia auditável: PR → commit do WAIVER → arquivo do WAIVER → finding original no QA_REPORT.

---

## 7. Auditoria periódica

Morgan revisa todos os WAIVERS abertos no `*plan` semanal:

| Cadência | Atividade                                                                 |
|----------|---------------------------------------------------------------------------|
| Semanal  | Listar WAIVERS abertos. Para cada: status, prazo, story-debt progresso.   |
| Mensal   | Relatório agregado em `docs/qa/WAIVERS/_REPORT-{{ YYYY-MM }}.md`           |
| Pré-release | **Bloqueio:** nenhum WAIVER que tenha `bloqueia_release = V1` pode estar aberto na release V1. Gage não publica. |

**Vencidos:** WAIVERS que passaram do `prazo_remediacao` sem remediação são marcados `Vencido` e escalados para Aria + Morgan em sessão de replanning.

---

## 8. Histórico (para auditoria longitudinal)

WAIVERS nunca são deletados — apenas marcados como `Remediado` ou `Vencido`.
O histórico permanece em `docs/qa/WAIVERS/` para auditoria futura.

---

— Quinn, no portão 🧪 (autoria do template; aprovação assinada por Aria/Sol/Morgan)
