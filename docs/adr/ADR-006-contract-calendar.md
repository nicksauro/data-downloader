# ADR-006 — Calendário de contratos vigentes = tabela estática versionada

**Status:** accepted
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💾 Sol, 🗝️ Nelo
**Supersedes:** —
**Related:** Lei R8 (bolsa = uma letra), Lei R9 (não chutar contratos), `docs/storage/CONTRACTS.md`

---

## Contexto

A ProfitDLL aceita tickers como `WDOJ26`, `WINH26`, `PETR4` — mas tem um quirk validado por Nelo (manual silencioso aqui, mas comprovado empiricamente):

> **Quirk:** `GetHistoryTrades` com `"WDOFUT"` ou `"WINFUT"` retorna **0 trades** em algumas janelas históricas, ou `NL_EXCHANGE_UNKNOWN`. Funciona com **contrato vigente específico** (`WDOJ26`, `WINH26`, etc.).

Logo, o downloader precisa, dado um período `[start, end]`, identificar **quais contratos vigentes** baixar. WDO é mensal (contrato roda todo mês — letras F/G/H/J/K/M/N/Q/U/V/X/Z = jan–dez). WIN é trimestral (apenas H/M/U/Z).

**Restrições:**
- Lei R9: não chutar letras de mês — validação contra fonte oficial.
- Foundation projects vão consumir `vigent_contract(root, date)` por anos.
- Mudança de regra de vigência (raro, mas pode acontecer) precisa ser auditável.

---

## Opções Consideradas

### Opção A — Tabela estática versionada em SQLite + `docs/storage/CONTRACTS.md`
- Tabela `contracts(symbol_root, contract_code, vigent_from, vigent_until, validated_at, validation_source)` no catálogo.
- `docs/storage/CONTRACTS.md` é a fonte humana revisável; `aiox-init` (ou script) sincroniza para SQLite.
- Sol mantém. `*contract --validate` faz probe via Nelo `*probe-dll`.

### Opção B — Algoritmo de cálculo em código
- Função `vigent_contract(root, date)` calcula via regra (ex: WDO = penúltimo dia útil do mês X-1 até penúltimo do mês X).
- Sem tabela.

### Opção C — Endpoint Nelogica/B3 em runtime
- Consulta API externa (calendário oficial B3).
- Nada hardcoded.

---

## Análise

| Critério | A (tabela) | B (algoritmo) | C (API runtime) |
|---------|------------|---------------|-----------------|
| Auditável | ✅ (Markdown + SQLite) | médio (lógica em código) | ❌ (depende de remote) |
| Determinístico | ✅ | ✅ | depende uptime |
| Resiliente offline | ✅ | ✅ | ❌ |
| Refletir mudança regulatória | edição manual + validação | refatorar código + ADR | automático (mas sem auditoria) |
| Custo overrides ad-hoc | trivial (linha tabela) | complexo | impossível |
| Single-source-of-truth | ✅ (Markdown) | código | externo |

**Pontos críticos:**

- **Opção C** depende de serviço externo. Quebra promessa de single-machine offline. Quebra reproducibilidade. Rejeitada.

- **Opção B** é elegante, mas regras de vigência B3 têm exceções (feriados, ajustes). Algoritmo "puro" precisa de exceção-list = vira tabela escondida no código. Pior que tabela explícita.

- **Opção A** é Pareto-ótima: humano lê `CONTRACTS.md`, código consulta SQLite, validação contra DLL via probe. Mudança = PR com diff visível.

---

## Decisão

**Opção A — Tabela estática versionada (`docs/storage/CONTRACTS.md` → `catalog.db.contracts`).**

### Estrutura da tabela SQLite

```sql
CREATE TABLE contracts (
  symbol_root        TEXT NOT NULL,    -- 'WDO', 'WIN', 'PETR', ...
  contract_code      TEXT NOT NULL,    -- 'WDOJ26'
  vigent_from        TIMESTAMP NOT NULL,
  vigent_until       TIMESTAMP NOT NULL,
  validated_at       TIMESTAMP NOT NULL,
  validation_source  TEXT NOT NULL,    -- 'nelogica_official' | 'dll_probe' | 'b3_calendar'
  PRIMARY KEY (symbol_root, contract_code)
);
```

### Mapa de letras de mês (CME/B3 convention)

| Letra | Mês |
|-------|-----|
| F | Janeiro |
| G | Fevereiro |
| H | Março |
| J | Abril |
| K | Maio |
| M | Junho |
| N | Julho |
| Q | Agosto |
| U | Setembro |
| V | Outubro |
| X | Novembro |
| Z | Dezembro |

WDO usa todas as 12 letras (mensal).
WIN usa H, M, U, Z (trimestral).

### Função pública

```python
# src/data_downloader/public_api/history.py

def vigent_contract(symbol_root: str, on_date: date, *, exchange: str = 'F') -> str:
    """
    Retorna o contract_code vigente em on_date.
    Lookup em catalog.db.contracts.
    Levanta InvalidContract se não houver contrato vigente nesta data.
    """
```

### Workflow de manutenção (Sol)

1. Sol edita `docs/storage/CONTRACTS.md` adicionando contrato (ex: WDOJ26 → vigent_from / vigent_until).
2. Sol roda `*contract-add WDO J 26`.
3. Comando dispara `*probe-dll` via Nelo: faz `GetHistoryTrades` no primeiro dia vigente para confirmar que retorna trades > 0.
4. Se probe OK → insert em `catalog.db.contracts` com `validation_source = 'dll_probe'` + timestamp.
5. PR aberto: humano revisa Markdown + diff SQLite + log do probe.
6. Sol audita. Quinn QA gate.

### Regras V1 (a validar via probe + tabela oficial Nelogica/B3)

> ⚠️ **Validar antes de hardcodar.** Estas são hipóteses iniciais; Sol valida em Story 1.6.

- **WDO** (mini-dólar futuro): mensal. Hipótese — vigente do **penúltimo dia útil do mês X-1** até o **penúltimo dia útil do mês X**. Nelo valida via probe.
- **WIN** (mini-Ibovespa futuro): trimestral H/M/U/Z. Hipótese — vigente do **5º dia útil do mês de vencimento - 3 meses** até o **5º dia útil do mês de vencimento**. Nelo valida via probe.
- **Equities** (PETR4, VALE3): não há vigência — ticker é estável. Tabela `contracts` tem entrada com `vigent_from = '1900-01-01', vigent_until = '9999-12-31'`.

---

## Consequências

### Positivas
- Auditável: qualquer agente lê `CONTRACTS.md`.
- Determinístico: mesma data → mesmo contrato (assumindo tabela atualizada).
- Resiliente: funciona offline, sem dep de API.
- Override trivial para casos especiais (ex: contrato com vencimento atípico em feriado).
- Validação obrigatória contra DLL via probe.

### Negativas
- Manutenção manual: novo contrato exige PR. Mitigação: Sol pode automatizar geração da próxima janela (script `*contract-next-cycle`).
- Risco de tabela ficar desatualizada se Sol não acompanhar — mitigação: alerta automático em catálogo se data atual sai do `vigent_until` mais distante (delegado a Pyro via métrica).

### Neutras
- Não tentamos reverse-engineer regra B3 — confiamos no probe + tabela oficial. Se B3 muda regra, Sol atualiza.

---

## Validações requeridas

- [ ] Sol implementa `*contract-add` com probe (Story 1.6)
- [ ] Quinn property-test: para todo `vigent_contract(r, d)` retornado, vigent_from <= d <= vigent_until (Story 1.6)
- [ ] Sol popula tabela inicial: WDO 2025-2026 + WIN 2025-2026 (Story 1.6)
- [ ] Smoke test (Story 1.7): `download('WDOJ26', ..., '2026-03-01', '2026-03-31')` retorna trades > 0
