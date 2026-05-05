# ADR-019 — Schema as Contract — Never Drop Columns

> **Nota de numeração:** este ADR foi solicitado como "ADR-006" em mini-council COUNCIL-39, mas o ID 006 já está ocupado por `ADR-006-contract-calendar.md`. Como autoridade ADR exclusiva (MANIFEST R15), Aria numerou na sequência correta disponível: **ADR-019**. Título mantido conforme pedido.

- **Status:** Proposed
- **Data:** 2026-05-05
- **Autor:** Aria (architect)
- **Stakeholders consultados (mini-council COUNCIL-39):** Pax (Product Owner), Dex (implementação concorrente), Sol (storage authority — owner formal de schema)
- **Bloqueia release:** SIM — deve ser ACCEPTED antes de tag V1.0.0 (ou V0.9.0-rc1 se fallback)
- **Relacionado:** COUNCIL-32 (Nelo, agents/trade-types), COUNCIL-36 (Pax, release-blockers), COUNCIL-39 (Aria, revisão crítica), Story 1.7g (P0 release-blockers)

---

## Contexto

Em 2026-05-05, durante mini-council de release readiness pós-COUNCIL-34, o dono do produto identificou que o schema parquet v1.0.0 **descarta silenciosamente** três campos entregues pelo callback V2 da ProfitDLL:

- `buy_agent_name`
- `sell_agent_name`
- `trade_type_name`

Esses campos são produzidos pelo callback (Nelo COUNCIL-32 confirmou: callback V2 entrega TradeID, agent IDs, trade_type) mas o `storage/parquet_writer.py` aceita um dict com keys extras e os ignora **sem aviso, sem warn, sem erro**. O parquet escrito passa data-validate sintaticamente (R5/R13 forma-only), mas é **incompleto semanticamente**.

Isso viola o MANIFEST de duas formas:

1. **R4 (Schema é contrato perpétuo)** — o vendor já entrega o dado; o "contrato de fato" inclui esses 3 campos; o "contrato de jure" (schema parquet v1.0.0) não os reconhece. Bump v1.1.0 aditivo é mandatório.
2. **R1 (Foundation primeiro)** — qualquer projeto downstream (backtest, signals, microestrutura) que precise de fluxo de agentes ou de classificação de trade-type vai consumir dataset mutilado **sem saber**. Foundation comprometida.

Mais perigoso: o defeito **arquitetural** que permite isso — writer não valida `record.keys() ⊆ schema.columns()` antes de gravar — é **estrutural**, não pontual. Se amanhã Nelo introduzir mais um campo no callback V3 e Dex esquecer de bumpar schema, o problema repete.

## Decisão

**Adotamos schema-as-contract com fail-loudly em três níveis:**

### Nível 1 — Validação no hot path (runtime)

```python
# storage/parquet_writer.py (proposta)
def write_records(records: list[TradeRecord], schema: ParquetSchema) -> None:
    schema_cols = set(schema.column_names())
    for record in records:
        record_keys = set(record.as_dict().keys())
        unknown = record_keys - schema_cols
        if unknown:
            raise SchemaContractViolation(
                f"TradeRecord contém campos não mapeados no schema "
                f"v{schema.version}: {sorted(unknown)}. "
                f"Bump aditivo obrigatório (vN→vN+1) com ADR. "
                f"Veja ADR-019. NUNCA descartar silenciosamente."
            )
        missing_required = (schema_cols - record_keys) & schema.required_columns()
        if missing_required:
            raise SchemaContractViolation(
                f"TradeRecord faltando campos obrigatórios do schema "
                f"v{schema.version}: {sorted(missing_required)}."
            )
    # ... continua escrita
```

`SchemaContractViolation` é exceção dedicada (não genérica `ValueError`) para que CI logs e Quinn QA gate reconheçam o defeito imediatamente.

### Nível 2 — Validação em build (estática)

CI script `tools/check_traderecord_schema_sync.py`:
- Introspecta `dll/types.py::TradeRecord` (dataclass).
- Carrega `storage/schema.py::CURRENT_SCHEMA`.
- Falha build se `set(TradeRecord.fields) != set(schema.columns())`.
- Mensagem orienta para bump + ADR.

Esse check é o que I-N6 (COUNCIL-39) define.

### Nível 3 — Bump aditivo obrigatório com ADR

- Toda mudança em `TradeRecord` exige bump de versão de schema.
- Aditivo (campo novo) = bump minor (v1.0.0 → v1.1.0).
- Quebrador (rename, type change, drop) = bump major + script de migração + ADR dedicado.
- Sol é owner formal (MANIFEST R4); Aria audita ADR.
- Schema v1.1.0 (motivado por este ADR + Story 1.7g) adiciona:
  - `buy_agent_name` (string, NOT NULL, fallback `Agent#{id}` se `NL_NOT_FOUND`).
  - `sell_agent_name` (string, NOT NULL, fallback `Agent#{id}`).
  - `trade_type_name` (string, NOT NULL, valores enumerados em `docs/storage/SCHEMA.md` tabela TTradeType de 14 valores conforme Nelo COUNCIL-32 §3.1).

### Nunca downgrade silencioso

Reader carregando parquet v1.1.0 com código que conhece apenas v1.0.0 deve **falhar loudly** ou pelo menos **logar warn nivel ERROR**, jamais silenciosamente ignorar campos. Política simétrica à escrita.

## Alternativas consideradas

| Alternativa | Por que rejeitada |
|------------|-------------------|
| **Aceitar schema-drop como permissivo** ("writer flexível") | Viola R1 + R4 diretamente. Não é trade-off, é defeito. |
| **Validação opt-in (flag `strict=True`)** | Defaults importam. Em produção, alguém esqueceria de ativar. Defeito retorna. |
| **Warn em vez de raise** | Warns são ignorados em logs ruidosos. R13 exige PASS verdadeiro, não PASS-com-warns. |
| **Bump major v2.0.0 em vez de v1.1.0 aditivo** | Aditivo é compat backward (readers v1.0.0 podem ler v1.1.0 ignorando colunas extras explicitamente, com warn — não silenciosamente). Major seria exagero. |

## Consequências

### Positivas
- Foundation íntegra (R1 cumprido).
- Schema contrato real (R4 cumprido).
- Quinn PASS pode auditar sintática **e** semanticamente (R13 reforçado).
- Sol PASS pode dar release readiness (R14 cumprido).
- Defeito não pode reaparecer (CI gate I-N6).
- Próximos campos do callback V3/V4 entram com governança formal.

### Negativas
- Exige migration helper para readers v1.0.0 existentes do squad.
- Property tests precisam atualizar fixtures (mocks que omitem campos vão quebrar — desejado).
- Custo de bump em PRs futuros: +1 ADR por campo novo (mas é o ponto: governança formal).

### Neutras
- Não afeta performance hot path (validation é O(N campos) ~constante).
- Não afeta thread model nem storage layout.

## Implementação

Owner: Dex (em paralelo a este council, conforme COUNCIL-36 AC1+AC2).
Validação: Sol (auditoria storage), Quinn (QA gate), Aria (review final ADR).

Tasks:
1. `storage/schema.py` — adicionar enum `SchemaVersion` + função `validate_columns()`.
2. `storage/parquet_writer.py` — chamar `validate_columns()` no hot path.
3. `tests/property/test_schema_contract.py` — propriedade "todo TradeRecord gravado tem todos os campos do schema".
4. `tools/check_traderecord_schema_sync.py` — CI build check.
5. `dll/types.py::TradeRecord` — campos `buy_agent_name`, `sell_agent_name`, `trade_type_name`.
6. `dll/agent_resolver.py` — fallback `Agent#{id}` para `NL_NOT_FOUND`.
7. Migration helper para readers v1.0.0.
8. `docs/storage/SCHEMA.md` — bump v1.1.0 + tabela TTradeType.

Aceitação: Story 1.7g AC1+AC2 PASS via Quinn QA gate.

## Promoção para ACCEPTED

Este ADR muda de **Proposed** → **Accepted** quando:
- (a) Story 1.7g implementação concluída.
- (b) `tests/property/test_schema_contract.py` verde.
- (c) `tools/check_traderecord_schema_sync.py` integrado no CI.
- (d) Sol audit-storage-pr PASS.
- (e) Aria review final neste ADR (assina mudança de Status).

## Referências

- MANIFEST R1 (Foundation), R4 (Schema), R13 (PASS gate), R14 (Release readiness), R15 (ADR-first).
- COUNCIL-32 (Nelo) — agents + trade-types reais entregues pelo callback V2.
- COUNCIL-36 (Pax) — release-blockers P0 B1+B2.
- COUNCIL-39 (Aria) — revisão crítica + invariantes I-N1, I-N4, I-N5, I-N6.
- Story 1.7g — execução técnica.
- ADR-014 (test strategy) — property tests como mecanismo de enforcement.
- `docs/storage/SCHEMA.md` — schema canônico (a ser bumpado v1.1.0).

---

*— Aria, autoridade ADR-first, 2026-05-05*
