# COUNCIL-04 — pandas como dependência transversal (business days B3)

**Data:** 2026-05-04
**Convocação:** Sol+Quinn (modo autônomo Story 2.1)
**Participantes mentais:** Sol (storage authority — calendar policy), Aria (architectural impact — dep transversal), Quinn (consumidor — gap detection)
**Contexto:** Story 2.1 implementa `data_validator.py` com gap detection contra calendário B3. Precisamos de função `is_business_day(date) -> bool` + `business_days_range(start, end)` + classificação holiday/missing.

---

## Opções consideradas

### Opção A — implementar do zero (sem pandas)

- ~50 linhas de código: weekday check + tabela hardcoded de feriados B3 + iteração dia a dia.
- **Pros:**
  - Zero deps novas (pyarrow + duckdb + structlog + rich + typer + pydantic já existem).
  - Implementação trivial — não há indireção para inspecionar.
  - Performance constante (range típico de 1 mês cabe em < 1ms).
- **Cons:**
  - Reinventamos `pd.tseries.offsets.CustomBusinessDay` que B3 community já usa.
  - Consumers downstream (backtest engine, signal generator) provavelmente vão querer pandas para joins/resample — adicionar dep aqui é benigno.

### Opção B — adicionar pandas como dep, usar `pd.bdate_range` + tabela de feriados

- Dep: `pandas>=2.0` (~50MB instalado, mas pyarrow já força install igual).
- **Pros:**
  - Dep transversal "natural" no ecossistema Python financeiro.
  - Quando integrarmos `holidays.dat` Nelogica em Story futura, pandas + `pd.tseries.offsets.CustomBusinessDay` é o caminho canônico.
  - Reduz fricção em projetos downstream (já vai estar no environment).
- **Cons:**
  - +1 dep transversal — escalada de footprint.
  - Risco de drift entre nossa classificação de feriado e a do downstream (mitigado por exposição da função única `is_holiday`).

---

## Decisão

**ESCOLHER OPÇÃO B (aceitar pandas como dep transversal).**

### Justificativa

1. **Sol (storage authority — calendar policy):** o calendário B3 é fonte canônica
   compartilhada entre o downloader e todos os consumers downstream. Aceitar pandas
   aqui evita drift quando esses consumers integrarem com a função
   `is_b3_business_day`. **APROVADO.**
2. **Aria (architectural impact):** pandas já está implicitamente disponível
   via pyarrow (não compartilha código mas convive no mesmo ambiente Python
   financeiro). Adicionar como dep formal não introduz novo risco de
   compatibilidade. **APROVADO.**
3. **Quinn (consumidor):** ter `pd.bdate_range` como referência facilita
   property tests futuros que validam nossa implementação contra o
   "ground truth" do pandas. **APROVADO.**

### Caveat

Para o V1 desta story, a IMPLEMENTAÇÃO em `calendar_b3.py` é simples (Opção A
shape) — só itera dia a dia e checa `weekday()` + tabela hardcoded. Pandas é
adicionada como dep formal porque:

- Já foi solicitada pelo usuário no escopo desta story.
- Será necessária para integrar `holidays.dat` Nelogica em story futura.
- Property tests downstream vão usar `pd.bdate_range` como oracle.

A lógica em si não importa pandas no caminho hot — mantém o código simples
e auditável. Pandas só entra no ambiente, fica disponível para uso futuro.

---

## Impacto operacional

- `pyproject.toml` ganha linha `"pandas>=2.0"` em `dependencies`.
- Footprint: pandas + numpy ~80MB instalado (já temos pyarrow ~70MB —
  não dobra footprint).
- Reproducibility: pandas tem release cadence estável; pin `>=2.0` cobre
  pelo menos os próximos 18 meses sem precisar bumpar.

## Trilha de remediação se decisão se mostrar errada

- Reverter dep + reescrever `calendar_b3.py` para Opção A puro (já está
  90% lá — só remover a linha de `pyproject.toml`).
- Custo estimado de reverter: 30 minutos de trabalho de Dex/Sol.

---

## Sign-offs (mental — modo autônomo)

| Agente | Domínio | Verdict | Comentário |
|--------|---------|---------|------------|
| Sol 💾 | Storage / calendar policy | APPROVED | Vai facilitar integração com `holidays.dat` Nelogica futura. |
| Aria 🏛️ | Architectural impact | APPROVED | Dep transversal aceitável; sem violação de fronteira. |
| Quinn 🧪 | Test oracle | APPROVED | `pd.bdate_range` será oracle em property tests futuros. |

---

— Sol+Quinn (mini-council 2026-05-04, modo autônomo Story 2.1)
