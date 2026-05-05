# COUNCIL-39 — Aria · Revisão Crítica de Release (defects schema-drop + volume gap)

> **Member:** Aria (architect) — voto individual em mini-council convocado por aiox-master
> **Data:** 2026-05-05
> **Escopo:** REVISÃO da decisão arquitetural anterior (COUNCIL-34 GO-WITH-TECH-DEBT) à luz de 2 defects P0 trazidos pelo dono do produto.
> **Inputs lidos:** `docs/MANIFEST.md` v1.0.0 (R1..R20), `docs/decisions/COUNCIL-34-Aria-arquitetura-sintoma-A-2026-05-05.md`, `docs/decisions/COUNCIL-36-Pax-release-blockers-2026-05-05.md`, índice de `docs/adr/`, evidência smoke `docs/qa/SMOKE_EVIDENCE/1.7d-*postfix35*MIXED.md`.

---

## 1. Resumo executivo

Em **COUNCIL-34** (este mesmo dia, mais cedo) recomendei **GO-WITH-TECH-DEBT** para V1.0.0. Essa avaliação **NÃO conhecia 2 defects** que o dono do produto trouxe depois:

1. **Defect S** — schema parquet descarta colunas silenciosamente (`buy_agent_name`, `sell_agent_name`, `trade_type_name` capturadas pelo callback V2 mas não persistidas, sem aviso, sem erro).
2. **Defect V** — volume real ~50-70% abaixo do esperado pelo dono (1 dia útil WDOFUT deveria render 600-700k trades; smoke entregou ~307k em dia completo, ~603k em 4 dias calendário).

**Veredito revisado:** **NO-GO** para V1.0.0 estável. Recomendação binária: **GO-after-1.7g** mediante correção integral dos 2 defects + smoke real validando ≥500k trades/dia útil. Como fallback se o gap não puder ser resolvido em janela razoável, **GO-with-major-bump** declarando V0.9.0-rc (não V1.0.0 estável).

Justificativa em uma linha: **schema-drop silencioso e perda de volume não são tech-debt — são violação direta do MANIFEST R1 + R4 + R13**.

---

## 2. Revisão dos 2 defects vs MANIFEST.md

### Defect S — Schema-drop silencioso

| Princípio | Texto literal | Aplicação ao defect | Verdict |
|-----------|---------------|---------------------|---------|
| **R1 — Foundation primeiro** | "Schema, dedup, idempotência, versionamento são INVARIANTES." | Writer descartando colunas viola invariante de schema. Foundation comprometida. | **VIOLADO** |
| **R4 — Schema é contrato perpétuo** | "Mudança aditiva = bump minor. Mudança quebradora = bump major + script de migração + ADR. Sol tem autoridade exclusiva sobre schema." | Adicionar 3 colunas sem bump + sem ADR + sem Sol consultada = duplo erro: (a) callback V2 já entrega os dados; (b) schema v1.0.0 não os carrega. Os 3 campos JÁ SÃO PARTE DO CONTRATO de fato (vendor entrega), só não estão no contrato de jure. | **VIOLADO** (forma) e **PRÉ-VIOLADO** (conteúdo: dados existem, contrato deveria existir) |
| **R13 — Story só vai para Ready for Review com Quinn PASS** | "(c) data-validate clean (se story produziu Parquet)" | Parquet escrito hoje passa data-validate sintaticamente, mas é **incompleto** semanticamente. Quinn não tinha como saber porque Quinn não conhecia a expectativa do dono. | **VIOLADO** (gap de validação que precisa fechar) |

**Dimensão arquitetural do defect:**
- Camada afetada **diretamente:** `storage/parquet_writer.py` (writer aceita dict com keys extras e ignora silenciosamente).
- Camada afetada **transitivamente:**
  - `public_api/` — consumidores downstream (Epic 4) receberão DataFrames sem 3 colunas que existem no vendor stream.
  - `duckdb` queries — analistas downstream **não saberão** que faltam campos; vão concluir microestrutura errada (não saber o agente comprador/vendedor invalida análise de fluxo de mercado).
  - `ui/` (Epic 3) — telas de inspeção mostrarão dataset mutilado.
  - `tests/property/` — properties deveriam testar "todo campo do callback V2 vai parar no parquet"; não testavam.

**Conclusão arquitetural:** **arquitetura permite o defect** porque writer não tem `validate_columns(record_keys, schema_columns)` no hot path. Solução de Dex (fail-loudly + bump v1.1.0 aditivo) é correta e suficiente para fechar o defect formal. Mas exige reforço de invariante (ver §4 abaixo).

### Defect V — Volume gap ~50-70%

| Princípio | Texto literal | Aplicação ao defect | Verdict |
|-----------|---------------|---------------------|---------|
| **R1 — Foundation primeiro** | "Foundation eficiente, íntegra e duradoura para TODOS os projetos futuros." | Foundation entregando metade dos dados não é foundation, é amostragem enviesada. Backtests downstream produzirão alpha falso. | **VIOLADO** |
| **R5 — Idempotência absoluta** | "Re-rodar download de (symbol, date_range) é no-op." | Idempotência é satisfeita (re-rodar não duplica), mas não há **invariante de completude**: 2 runs idempotentes podem ambos perder os mesmos 50%. Idempotência sem completude = "consistência do incompleto". | **NÃO COBERTO** (gap manifesto no MANIFEST atual) |
| **R13 — Quinn PASS gate** | "(c) data-validate clean" + "Contagem de trades dentro de ordem de magnitude esperada" (§8 Critérios de Sucesso MVP) | Critério §8 é literal: "ordem de magnitude esperada". Esperado = dono diz 600-700k/dia. Observado = 307k/dia. **Não está dentro de ordem de magnitude** (é um fator 2× — o limite "ordem de magnitude" usualmente tolera ±50%, e estamos no fundo da faixa). | **VIOLADO** (limite de tolerância no fio da navalha) |
| **R14 — Release exige todos os PASSes (Sol PASS = integridade dataset)** | "PASS de Sol (integridade dataset)" | Sol não pode dar PASS sabendo que dataset entrega 50%. | **VIOLADO** (preventivo) |

**Dimensão arquitetural do defect:**
- Defect V não é "missing data" — é **silent corruption por incompletude**. O parquet escrito **parece** consistente (dedup ok, schema ok, partition ok) mas é uma **fração não-marcada** do mercado real.
- Causa-raiz arquitetural plausível (das 5 hipóteses de Pax COUNCIL-36):
  - **H1 (race subscribe→get_history):** se `subscribe_ticker` é chamado *após* `GetHistoryTrades` retornar, há janela onde trades reais do passado recente não chegam. Arquitetura atual em `download_chunk` precisa de **ordering invariant** documentado.
  - **H2 (LAST_PACKET prematuro):** se a DLL emite LAST_PACKET sem todos os pacotes do dia, IngestorThread sai cedo. Arquitetura **não tem replay/resume** baseado em count vs janela esperada.
  - **H4 (cap silencioso 5 dias):** Q12-E menciona janela máx 5 dias; pode haver cap por símbolo/contrato não-documentado pelo vendor.
  - **H3 (TranslateTrade descarta legítimos):** sentinel `wYear<=1900` pode estar dropping trades validamente datados (improvável em WDO mas possível em equities históricas).
- **A arquitetura não tem invariante de "volume pós-download = volume esperado por baseline".** Esse é o ponto cego central.

**Conclusão arquitetural:** Defect V exige **3 mudanças arquiteturais**:
1. **Volume baseline registry** (`docs/perf/VOLUME_BASELINES.md` ou similar, ownership Sol + Pyro): para cada (symbol, contract_kind) registrar trades/dia útil esperado, com fonte (dono / ProfitChart desktop / vendor docs).
2. **Volume completeness check** automatizado no smoke: `assert trades_in_window >= baseline * tolerance_low` (default tolerance_low=0.8).
3. **LAST_PACKET cross-check:** ao receber LAST_PACKET, validar que `last_trade_timestamp >= window_end - tolerance` antes de aceitar como "fim do download". Caso contrário, **automatic replay** com nova janela ou flag `incomplete=true` no metadata do parquet.

---

## 3. Decisão de release revisada

### Recomendação binária: **NO-GO para V1.0.0 estável** — refinada como **GO-after-1.7g** (preferida) OU **GO-with-major-bump** (fallback)

#### Opção primária — GO-after-1.7g

**Pré-condição:** Story 1.7g (Pax) executada integralmente, com:
- AC1 — schema v1.1.0 aditivo persistindo `buy_agent_name`, `sell_agent_name`, `trade_type_name`.
- AC2 — writer fail-loudly em colunas não mapeadas.
- AC3 — smoke real WDOFUT 1 dia útil retornando **≥ 500k trades** (limite mínimo aceito; ideal: ≥600k aproximando a expectativa do dono).
- AC4 — `trades_per_day` ≥ 500k para cada dia útil dentro da janela.
- AC5/AC6 — docs corrigidos (SCHEMA.md TTradeType, Q-DRIFT-35 NL_NOT_FOUND).

**Se AC3+AC4 PASSAR:** GO para V1.0.0 estável — defects fechados, R1/R4/R5/R13/R14 satisfeitos.

**Se AC3+AC4 FALHAR após 1 dia de investigação:** escalar para mini-council Aria+Nelo+Pax (já previsto por Pax COUNCIL-36 §4 cascata).

#### Opção fallback — GO-with-major-bump (V0.9.0-rc1, NÃO V1.0.0)

**Quando aplicar:** se o gap de volume não puder ser totalmente fechado em janela razoável (≤ 3 dias), mas o **schema fix (Defect S) for resolvido**.

**Implicações:**
- Tag `v0.9.0-rc1` em vez de `v1.0.0`.
- README + STATUS.md anunciam "release candidate, não declarado V1 estável".
- ADR-019 (Schema as Contract) = ACCEPTED imediato.
- ADR-020 (Volume Completeness) = ACCEPTED com `enforcement: warn-only` durante rc.
- Story 1.7h aberta como blocker de V1.0.0 estável: investigar e fechar gap volume.
- Public API marcada como `unstable` (evita downstream baseando-se em dataset incompleto sem aviso).

#### Por que NÃO mantenho GO-WITH-TECH-DEBT (revisão de COUNCIL-34)

COUNCIL-34 §1 disse "Nenhum princípio R1..R20 está sendo violado em produção". Essa frase estava **factualmente errada** porque eu não tinha conhecimento de:
- O writer descartar colunas silenciosamente (R4 violação de fato).
- O volume estar 50-70% abaixo do esperado pelo dono (R1 + §8 violação de fato).

Constitution Article V (Quality First): "smoke real precisa PASS com volumetria correta". Smoke com 50-70% loss não é PASS — é **PASS-aparente** mascarando FAIL semântico. Não posso assinar Aria PASS para R14 sabendo disso.

#### Critérios de release final exigidos por R14 — atualizados

- ⚠️ **Quinn PASS** (qualidade) — pendente AC3+AC4 da Story 1.7g.
- ⚠️ **Pyro PASS** — Story 1.8 baselines pendente (já era pendente antes).
- ❌ **Sol PASS** (integridade dataset) — atual schema v1.0.0 NÃO tem integridade. Pós-1.7g pode ter.
- ❌ **Aria PASS** (sem ADR proposed em escopo) — ADR-019 (schema-as-contract) e ADR-020 (volume-completeness) **devem ser ACCEPTED antes** do release. Não podem ficar Proposed.
- ⚠️ **Morgan autoriza** — depende dos PASSes acima.

---

## 4. Invariantes arquiteturais propostas (CI/CD enforcement, próximas fases)

> Lista nova e/ou reforçada em cima das 12 invariantes existentes em `ARCHITECTURE.md`. Cada invariante exige check automatizável; severidade indica se BLOCK MERGE ou WARN.

| ID | Invariante | Camada | Enforcement | Severidade |
|----|-----------|--------|-------------|-----------|
| **I-N1** | Parquet writer NUNCA descarta colunas silenciosamente | `storage/parquet_writer.py` | Test unit `test_writer_fails_on_unknown_column` + asserção runtime `validate_columns(record_keys, schema_columns)` | **BLOCK** |
| **I-N2** | Smoke real volume ≥ 80% de baseline esperado por (symbol, contract_kind, day_type) | smoke + `docs/perf/VOLUME_BASELINES.md` | `pytest tests/smoke/test_volume_completeness.py` (precisa criar pós-1.7g) | **BLOCK** |
| **I-N3** | LAST_PACKET cross-checked: `last_trade_ts >= window_end_ts - tolerance` (default tolerance=60s para WDOFUT) | `dll/wrapper.py` IngestorThread + `orchestrator/download_chunk` | Test unit com mock LAST_PACKET prematuro → espera-se replay automático ou `incomplete=true` no metadata | **BLOCK** |
| **I-N4** | Schema versioning é monotônico aditivo (vN → vN+1 só adiciona campos NOT NULL com fallback ou OPTIONAL) | `storage/schema.py` + `docs/storage/SCHEMA.md` + ADR | CI script `tools/check_schema_compat.py` que carrega vN parquet com vN+1 reader e valida backward | **BLOCK** |
| **I-N5** | `agent_resolver` fallback é graceful (`NL_NOT_FOUND` legítimo → string `Agent#{id}`) mas **NUNCA NULL silencioso** em parquet — colunas `buy_agent_name`/`sell_agent_name`/`trade_type_name` são NOT NULL no schema v1.1.0 | `dll/agent_resolver.py` + `storage/parquet_writer.py` | Test property: para todo trade gravado, 3 campos NOT NULL e bytes>0; CI check `pyarrow.Table.validate()` | **BLOCK** |
| **I-N6** | Toda mudança em record dict (TradeRecord) que **adiciona campo** dispara erro de build se schema não foi bumpado simultaneamente | `dll/types.py` + `storage/schema.py` | CI `tools/check_traderecord_schema_sync.py` (introspect TradeRecord dataclass vs schema.parquet_columns()) | **BLOCK** |
| **I-N7** | Volume baselines auditados: `docs/perf/VOLUME_BASELINES.md` revisado por Sol+Pyro a cada bump de schema **e** a cada novo símbolo adicionado (Epic 4.1/4.2) | docs + Pyro | CI check `tools/check_baselines_freshness.py` (warn se >90 dias sem revisão) | WARN |
| **I-N8** | Smoke real persiste **count vs baseline ratio** no SMOKE_EVIDENCE: `volume_completeness_ratio = trades_observed / baseline_expected` | `docs/qa/SMOKE_EVIDENCE/*.md` | Template SMOKE_EVIDENCE.md com seção obrigatória "Volume completeness ratio: X%" | WARN |
| **I-N9** | Public API v1 (Epic 4) expõe metadata `incomplete=true` no DataFrame se parquet foi gravado com flag de incompletude (caso fallback V0.9.0-rc1) | `public_api/` | Test downstream lendo parquet `incomplete=true` recebe attribute set | **BLOCK** se rc; WARN se v1 final |
| **I-N10** | Subscribe→GetHistoryTrades ordering documentado e enforced: `orchestrator.download_chunk` chama `subscribe_ticker` ANTES de `get_history_trades`, com sleep configurável de estabilização (default 0 — só ativa se evidência empírica exigir) | `orchestrator/download_chunk.py` | Test unit + ADR-021 (proposed pós-1.7g se H1 confirmada) | **BLOCK** |

**Mapeamento solicitado pela missão:**
- I1 = I-N1 (parquet writer fail-loudly).
- I2 = I-N2 (volume ≥ 80% baseline).
- I3 = I-N3 (LAST_PACKET cross-check).
- I4 = I-N4 (schema versioning aditivo + backward).
- I5 = I-N5 (agent_resolver graceful, mas NOT NULL).
- I6 = I-N6 (TradeRecord ↔ schema sync forçado em build) **+** I-N7..I-N10 como invariantes adicionais propostas.

---

## 5. ADRs propostos

> Decisão de numeração: usuário pediu literalmente "ADR-006" e "ADR-007", mas esses IDs já existem no repo (`ADR-006-contract-calendar.md`, `ADR-007-public-api.md` + supersede 007a). Como autoridade ADR exclusiva (R15), **numerei na sequência correta disponível: ADR-019 e ADR-020**, mantendo os títulos exatos pedidos. Documentado abaixo.

### ADR-019 — Schema as Contract — Never Drop Columns
**Path:** `docs/adr/ADR-019-schema-as-contract.md`
**Status:** Proposed (ACCEPTED após Story 1.7g implementação validada por Sol+Quinn)
**Sumário:** writer falha loudly se TradeRecord tem campos não mapeados; bump aditivo obrigatório; jamais downgrade silencioso.

### ADR-020 — Volume Completeness Invariant
**Path:** `docs/adr/ADR-020-volume-completeness.md`
**Status:** Proposed (ACCEPTED após Story 1.7g + baselines registrados)
**Sumário:** smoke valida volume contra baseline; LAST_PACKET cross-checked; replay automático em gap; flag `incomplete=true` no metadata se gap não-resolvível.

Detalhes completos nos próprios ADRs.

---

## 6. Riscos residuais e bloqueios de cascata

| # | Risco | Severidade | Mitigation |
|---|-------|-----------|-----------|
| RR1 | Story 1.7g identifica que o gap de volume é **estrutural na DLL Nelogica** (vendor não emite mais que ~300k/dia para WDOFUT via GetHistoryTrades) | ALTA | Plano B: aceitar V0.9.0-rc com flag `incomplete=true` + abrir story de discovery via subscribe_ticker em tempo real (live capture) como fonte complementar |
| RR2 | Bump schema v1.0.0→v1.1.0 quebra readers downstream existentes (público interno do squad) | MÉDIA | Migration helper em `storage/schema.py` (já previsto Pax COUNCIL-36); manter readers v1.0.0 capazes de ignorar 3 colunas extras (forward-compat por padding NULL na leitura, não na escrita) |
| RR3 | `validate_columns` fail-loudly causa regressão em testes existentes que mockam TradeRecord parcial | MÉDIA | Atualizar fixtures + property tests; exigir mocks completos (alinha com R5 idempotência) |
| RR4 | I-N3 (LAST_PACKET cross-check) + replay automático introduz risco de loop infinito se DLL Nelogica nunca completa janela | MÉDIA | Cap em N=3 replays por chunk; após 3, falha loudly com `incomplete=true` flag + log estruturado |
| RR5 | Volume baselines não registrados para WIN/equities (Epic 4.1/4.2) bloqueia próximas stories | BAIXA-MÉDIA | Story de baselines paralela ao 1.7g — cada novo símbolo entra com baseline registrado por Sol+dono |
| RR6 | Sintoma A pytest (COUNCIL-34 §2) ainda tech-debt; agora I-N2 e I-N5 exigem CI gates que rodam via pytest | MÉDIA | Manter padrão: smoke real via `scripts/run_smoke_real_standalone.py`; CI gates de schema/baseline rodam unit-test (não smoke), pytest está OK para essa camada |

---

## 7. Diff face a COUNCIL-34

| Aspecto | COUNCIL-34 (anterior) | COUNCIL-39 (revisado) |
|---------|----------------------|----------------------|
| Recomendação binária | GO-WITH-TECH-DEBT | NO-GO/GO-after-1.7g (preferida) ou GO-with-major-bump V0.9.0-rc1 (fallback) |
| Violação R1..R20 | "Nenhum princípio violado em produção" | **R1, R4, R13, R14 violados** pelos 2 defects |
| ADRs proposed em escopo | ADR-018 (DLL signatures) — deferred OK | **ADR-019 e ADR-020 ACCEPTED ANTES do release** — não podem ficar proposed |
| Sol PASS | Implícito ✅ | ❌ até schema v1.1.0 + baseline registry |
| Aria PASS | ✅ "ADR-018 deferred não bloqueia" | ❌ até ADR-019/020 ACCEPTED |
| Smoke real evidência | "796k trades validados" (anterior) | **Reinterpretado:** 796k em 4 dias = ~200k/dia, abaixo do baseline 600-700k/dia → smoke é evidência de FAIL semântico, não PASS |

---

## 8. Sumário executivo (1 parágrafo)

A arquitetura está **estruturalmente sólida** (thread model, storage stack, modularidade) — minha avaliação em COUNCIL-34 quanto a esses pontos permanece. Mas dois defects de **integridade de dados** (schema-drop silencioso + volume gap 50-70%) **violam diretamente R1, R4, R13, R14** do MANIFEST e invalidam minha recomendação anterior de GO-WITH-TECH-DEBT. **Veredito revisado: NO-GO para V1.0.0 estável**, refinado para **GO-after-1.7g** (preferido) com **GO-with-major-bump V0.9.0-rc1** como fallback caso o gap de volume não seja totalmente fechado. Proponho **10 invariantes arquiteturais (I-N1..I-N10)** novas/reforçadas para CI/CD enforcement, e **ADR-019 (Schema as Contract) + ADR-020 (Volume Completeness Invariant)** como Proposed, com requisito de promoção para ACCEPTED antes do release. **A foundation precisa estar íntegra antes de carregar o resto do produto.**

---

*— Aria, council member voto, 2026-05-05 (revisão crítica de COUNCIL-34)*
