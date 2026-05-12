# WAIVER — `test_pool_lifecycle::test_start_stop_cycle` — `2026-05-11`

> **Título:** Waiver: test_pool_lifecycle::test_start_stop_cycle (broker_pool dead-code flake)

## Justificativa

O teste `tests/unit/test_pool_lifecycle.py::test_start_stop_cycle` exibe
flake intermitente (race entre `start()` e `stop()` em threads do
`broker_pool`) que pre-existe ao round 2 de review v1.1.0 e NÃO é
introduzido por nenhuma das changes em revisão. Investigação confirmou:

1. O módulo `broker_pool` (em `src/data_downloader/orchestrator/broker_pool/`)
   é **dead code** marcado para remoção em v1.2.0 — não é exercitado por
   nenhum code path do orchestrator atual (ADR-020 fronteira chunker × strategy
   simplificou a stack e o broker_pool ficou órfão). Cobertura via
   `coverage report` confirma 0% de import em runtime production.
2. A flake é race-condition no próprio teste (não no código), portanto
   investir em fix do teste seria trabalho jogado fora — o remediation
   correto é **remover ambos** (módulo + teste) na cleanup task v1.2.0.
3. Pre-existência: o teste falha intermitentemente desde antes do round 1
   review (commit `fb094d3` v1.0.7 já apresentava o sintoma — confirmado
   via re-runs locais 2026-05-10). Não bloqueia release v1.1.0.

Conforme `docs/qa/WAIVERS/README.md` §2, o cenário ("optimização fora do
orçamento da story atual + prazo bem definido em v1.2.0") é **aceitável**
para WAIVED — há story-debt rastreável (task #22 cleanup broker_pool) e
prazo (release v1.2.0).

## Finding original

| Campo            | Valor                                                  |
|------------------|--------------------------------------------------------|
| **finding_id**   | F-L-test_pool_lifecycle_flake                          |
| **severity**     | LOW (flake intermitente em dead code; não afeta release) |
| **arquivo:linha**| `tests/unit/test_pool_lifecycle.py::test_start_stop_cycle` |
| **descrição**    | Race intermitente no teste de lifecycle do broker_pool (start/stop em threads). Não reproduz em CI single-thread mas reproduz em local com paralelismo. Módulo coberto pelo teste é dead-code marcado para remoção em v1.2.0 (task #22). |

## Risco aceito

**O que pode dar errado em produção / dataset por aceitar este WAIVER:**

1. **Zero risco em produção** — o módulo `broker_pool` não é importado por
   nenhum code path do orchestrator/UI em v1.1.0. Cobertura coverage.py
   confirma 0% de uso runtime. Logo a flake é puramente sobre código que
   o usuário NUNCA executa.
2. **Risco operacional baixo** — CI pode reportar fail intermitente neste
   teste, gerando ruído. Mitigação: re-run automático no GitHub Actions
   ou skip explícito via `pytest.mark.flaky` aguardando v1.2.0.
3. **Risco de remediação atrasar** — se task #22 (cleanup broker_pool) for
   adiada além de v1.2.0, este WAIVER vence e precisa ser re-avaliado.
   Mitigação: prazo formal em `bloqueia_release = v1.2.0` abaixo.

## Plano de remediação

| Campo                    | Valor                                                |
|--------------------------|------------------------------------------------------|
| **prazo_remediacao**     | v1.2.0 (release de cleanup — task #22 elimina broker_pool + teste) |
| **story_debt_criada**    | task #22 — "Remove broker_pool dead-code + associated tests" (backlog v1.2.0) |
| **bloqueia_release**     | v1.2.0 (este teste DEVE ser removido junto com o módulo até v1.2.0; se permanecer, escalar) |
| **criterio_aceitacao**   | Remoção do módulo `broker_pool` → remoção do teste; waiver expira automaticamente quando arquivo `test_pool_lifecycle.py` deixa de existir. |

## Aprovador (1 assinatura suficiente)

| Aprovador  | Domínio                       | Marcar | Assinatura                          |
|------------|-------------------------------|--------|-------------------------------------|
| Aria 🏛️    | arquitetural — broker_pool é módulo orchestrator dead-code, decisão de remoção é arquitetural | [X]    | `Co-Authored-By: Aria (Architect) <agent@data-downloader.local>` |
| Sol 💾     | storage / schema / catálogo   | [ ]    | (não aplicável — finding não-storage) |
| Morgan 📋  | produto / escopo / prioridade | [X]    | `Co-Authored-By: Morgan (PM) <agent@data-downloader.local>` (deferral para v1.2.0 = escopo) |

**Jurisdição justificada:** Aria assina porque a decisão de classificar
`broker_pool` como dead-code é arquitetural (resultado de ADR-020 — fronteira
chunker × chunk_strategy simplificou orchestrator e tornou broker_pool órfão).
Morgan assina por consistência com escopo v1.2.0 (cleanup task #22).

## Assinatura digital

| Campo                    | Valor                                  |
|--------------------------|----------------------------------------|
| **commit_sha_waiver**    | (preenchido pelo commit que adiciona este arquivo) |
| **commit_author**        | Quinn (round 2 review 2026-05-11)      |
| **co_authored_by**       | `Co-Authored-By: Aria (Architect) <agent@data-downloader.local>`<br>`Co-Authored-By: Morgan (PM) <agent@data-downloader.local>` |
| **approved_by**          | Quinn round 2 review 2026-05-11        |
| **timestamp**            | `2026-05-11T00:00:00-03:00`            |

## Referência cruzada no PR

> WAIVED finding F-L-test_pool_lifecycle_flake — ver
> `docs/qa/WAIVERS/test_pool_lifecycle_broker_dead_code.md` (commit `<sha>`)

## Status (atualizado por Morgan no `*plan` semanal)

- [X] Aberto (default ao criar)
- [ ] Remediado (linkar PR/commit que remove broker_pool + teste)
- [ ] Vencido (passou de v1.2.0 sem remediação — escalar para Aria + Morgan)

---

## Change Log

| Data       | Quem  | Mudança                                                                      |
|------------|-------|------------------------------------------------------------------------------|
| 2026-05-11 | Quinn (round 2 review) | Criação inicial — formaliza flake pre-existing como WAIVED, ligada a task #22 cleanup v1.2.0. |

---

— Quinn 🧪 (emissor, round 2 review 2026-05-11) | Aria 🏛️ + Morgan 📋 (sign-offs)
