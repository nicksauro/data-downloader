# COUNCIL-06 — Política de rollover em `read_continuous` (vigent_until + 1ns)

**Data:** 2026-05-03
**Convocação:** Dex+Sol mini-council (modo autônomo Story 1.5b)
**Participantes mentais:** Dex (impl — public_api fronteira), Sol (storage authority — query canônica QUERIES.md), Aria (consult — public_api estabilidade SemVer)
**Contexto:** Story 1.5b implementa `read_continuous(symbol_root, start, end)`
que concatena trades de múltiplos contratos vigentes (ex.: WDOH26 → WDOJ26 no
fim de março). A pergunta crítica é: COMO escolher o ponto de costura entre
contratos? A política precisa garantir zero duplicata, zero gap silencioso, e
manter ordering monotônico de `timestamp_ns` cross-contract.

---

## Opções consideradas

### Opção A — `vigent_until` (cut-off determinístico)

- Trades do contrato seguinte só entram a partir de
  `vigent_until_anterior + 1 nanossegundo`.
- Source de verdade: tabela `contracts` (catálogo SQLite, Sol é dono).
- **Pros:**
  - Determinístico — mesmo resultado para qualquer chamada com mesmo seed.
  - Zero overlap garantido por construção (cut-off exclusive).
  - Property test trivial: `(timestamp_ns, _contract_code)` é único.
  - Alinhado a Sol QUERIES.md §2.2 (implementação canônica documentada).
- **Cons:**
  - Pode introduzir descontinuidade artificial nos primeiros minutos do
    contrato novo se o seed não bater exatamente com a data real de
    transição (Sol §2.4 documenta o caveat).
  - Depende da qualidade do seed `contracts` (Story 1.6 valida via probe DLL).

### Opção B — `first_trade` (rollover quando novo contrato tem 1º trade)

- Olha cada arquivo Parquet do novo contrato; quando achar um trade real
  no range `[vigent_from, vigent_until]`, troca para o novo a partir desse
  `timestamp_ns`.
- **Pros:**
  - Reflete o que aconteceu na prática — sem buracos artificiais.
  - Útil para análises de liquidez (saber QUANDO o mercado realmente
    rolou).
- **Cons:**
  - Não-determinístico se dois contratos têm trades sobrepostos no mesmo
    range (caso real durante janela de transição).
  - Custa I/O extra (precisa abrir Parquets do novo contrato antes de
    decidir o cut-off).
  - Implementação mais complexa — fica para Story 4.X quando tivermos
    casos reais para calibrar.

### Opção C — `liquidity_crossover` (rollover quando volume novo > corrente)

- Critério de mercado real — institutional rollers olham volume.
- **Pros:**
  - Captura a "data real" de transição na visão de quem opera.
- **Cons:**
  - Requer agregação cross-contract por bucket temporal — caro em I/O.
  - Implementação altamente paramétrica (qual janela? qual threshold?).
  - Política de mercado, não de storage — fica para Epic futuro de
    backtesting (Epic 4+).

---

## Decisão

**ESCOLHER OPÇÃO A (`vigent_until` cut-off com +1ns) como DEFAULT em V1.**

Opções B e C ficam documentadas como TODOs explícitos no código
(`continuous_reader.py` docstring) para Story 4.X.

### Justificativa

1. **Sol (storage authority — QUERIES.md):** a query canônica em
   QUERIES.md §2.2 já assume `vigent_until` policy. Manter consistência
   entre documentação e implementação reduz fricção para projetos
   downstream que vão consumir `read_continuous`. **APROVADO.**

2. **Dex (impl — public_api fronteira):** determinismo é requisito SemVer
   (ADR-007a) — a mesma chamada deve retornar a mesma tabela em qualquer
   ambiente. Opções B/C dependem de I/O ad-hoc e dados do filesystem,
   o que viola determinismo se o seed de contratos for diferente. **APROVADO.**

3. **Aria (consult — public_api):** introduzir parâmetro
   `rollover_policy=...` aditivamente no futuro é minor bump (compatível
   com SemVer); cravar `vigent_until` como default em V1 não nos
   compromete. Mudança de default seria major bump. **APROVADO COM
   RESSALVA**: documentar em docstring que `policy="vigent_until"` é o
   único valor suportado em V1, e que adições futuras serão aditivas.

### Implementação

Em `continuous_reader.py::read_continuous_with_rollover_metadata`:

```python
prev_vigent_until_ns: int | None = None
for contract in contracts:
    slice_start = max(start, contract.vigent_from)
    if prev_vigent_until_ns is not None:
        slice_start_ns = max(_to_ns(slice_start), prev_vigent_until_ns + 1)
    # ... lê chunk, anexa _contract_code, atualiza prev_vigent_until_ns
```

Notação `+1`: nanossegundo seguinte ao último ns coberto pelo
`vigent_until` do contrato anterior. Garante exclusive boundary.

### Property tests obrigatórios (Story 1.5b AC6)

- `test_no_duplicates_at_rollover` — `(timestamp_ns, _contract_code)` único.
- `test_chunking_invariance` — chunked == direct read.
- `test_ordering_monotonic_cross_contract` — `ts[i] >= ts[i-1]` cross-contract.
- `test_contract_code_never_reverts` — uma vez transicionado, não volta.

### Mini-council bumps API version

Adição de `read`, `read_continuous`, `vigent_contract` em `public_api/` é
**aditiva** (ADR-007a). Bump: `0.1.0` → `0.2.0` (minor). Smoke test
`test_public_api_exposes_api_version` atualizado.

---

## Referências

- `docs/storage/QUERIES.md` §2 (read_continuous canônico)
- `docs/storage/CONTRACTS.md` §6.1 (rollover semantics)
- ADR-007a (SemVer da public_api)
- ADR-002 (DuckDB como engine de leitura)
- Story 1.5b (this story)
- Story 1.6 (probe DLL — valida seed contracts)
- Story 4.X (futuro — `first_trade` / `liquidity_crossover` policies)

— Dex + Sol, mini-council 2026-05-03
