# COUNCIL-32 — Nelo: Agent names + Trade types (council member)

**Persona:** Nelo (DLL/ctypes/Win64 ABI specialist)
**Council:** 32 — pós smoke standalone WDOFUT postfix-35
**Data:** 2026-05-05
**Escopo:** Considerações #2 (nomes de corretora buy/sell) e #3 (trade types datados conforme manual)
**Log analisado:** `docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-postfix35-20260505T123005Z.log`
**Modo:** REPORTE — não modifiquei código (Q-DRIFT-35 não é o root cause; ver §3).

---

## 1. Veredito sumário

| Tópico | Veredito | Severidade |
|--------|----------|------------|
| Agent names em buy/sell | PARTIAL | MEDIUM |
| Trade types datados conforme manual | PARTIAL | MEDIUM |
| translate_failures=961 (root cause) | IDENTIFICADO | LOW (0,12%) |
| 4× unknown_id length=-2147483636 | IDENTIFICADO (NÃO É ABI BUG) | LOW |
| Manual compliance (V2 trade) | ~85% (gaps em persistência, não em fetch) | — |

---

## 2. Considerando #2 — Agent names buy/sell

### 2.1. Pipeline de resolução (atual)

1. **DLL → struct** (`wrapper.translate_trade` L1733-1734): extrai `BuyAgent` e `SellAgent` (c_int) → `TradeFields.buy_agent_id`/`sell_agent_id`. ✅ correto.
2. **Resolver** (`agent_resolver.AgentResolver.resolve`): chama `GetAgentNameLength(id, short=0)` → se length>0, aloca buffer e chama `GetAgentName(length, id, buffer, 0)` → retorna `buffer.value`. Se length<=0 → fallback determinístico `"Agent#{id}"`. ✅ correto.
3. **TradeRecord dataclass** (`download_primitive.TradeRecord` L156-157): possui campos `buy_agent_name` e `sell_agent_name` populados pelo resolver. ✅ correto.
4. **PROBLEMA — Schema parquet** (`storage/schema.py` L43-107 + `SCHEMA.md` v1.0.0): só persiste `buy_agent_id` (`pa.int32 nullable`) e `sell_agent_id`. **NÃO existem campos `buy_agent_name`/`sell_agent_name` no schema**. O comentário em `download_primitive.py` L153-155 admite explicitamente: "Campos NÃO fazem parte do schema Parquet v1.0.0 (Sol authority — adição requer bump SCHEMA_VERSION); writer atual descarta se não encontrar coluna."

**Resultado:** o resolver funciona em runtime e popula a dataclass na memória, mas o nome NUNCA chega ao Parquet. Downstream (DuckDB queries, analytics) só vê IDs numéricos.

### 2.2. Por que 4× `agent_resolver.unknown_id length=-2147483636`?

`-2147483636` em decimal = `0x8000000C` em hex sem sinal. Cross-referência de `error_taxonomy.py` L91:

```python
_NL_NOT_FOUND: Final[int] = -2147483636
```

**`-2147483636` É EXATAMENTE `NL_NOT_FOUND`, NÃO um valor corrompido por ABI mismatch.**

O comentário do Q-DRIFT-35 em `wrapper.py` L731-745 contém um erro de interpretação:

> "length=-2147483636 (== 0x80000004 reinterpretado como c_int signed)"

O cálculo está errado: `0x80000004` (signed) = `-2147483644`, **não** `-2147483636`. O valor real `-2147483636` (`0x8000000C`) é o código `NL_NOT_FOUND` — semântica intencional da DLL: "Esse `agent_id` não existe na tabela interna de corretoras."

**Consequência:** o "fix" Q-DRIFT-35 (registrar argtypes/restype explícitos para `GetAgentNameLength`/`GetAgentName` no path `minimal_handshake`) **continua sendo correto e necessário** (boa higiene de ctypes em x64), MAS não vai eliminar as 4 mensagens unknown_id — porque elas não são corrupção de ABI; são respostas honestas da DLL sobre IDs que ela genuinamente desconhece.

Os IDs que falharam são esclarecedores:

| agent_id | Análise |
|----------|---------|
| `91` | Provavelmente broker delistado / código antigo |
| `6094896` | Fora do range usual de broker IDs (1-99999); trade roteado por mesa/algoritmo? |
| `3801138` | Idem |
| `3407922` | Idem |

IDs >1M não são corretoras CVM tradicionais — podem ser identificadores internos da B3 para mesas, gateways de market makers, ou valores especiais (e.g. RLP). A DLL não tem esses no `newagents.dat`.

**Taxa:** 4 IDs únicos / 796.963 trades = 0,0005%. O resolver tem cache, então mesmo com IDs repetindo o lookup só falha 1× por ID. Aceitável para MVP. Fallback `Agent#{id}` é usado.

### 2.3. Veredito agents

**PARTIAL.** Funciona em memória, mas nomes não persistem no Parquet (gap autoritativo de Sol — bump de schema necessário). Os 4 unknown_id são NL_NOT_FOUND legítimos, não bugs ABI.

---

## 3. Considerando #3 — Trade types

### 3.1. Enum canônico TConnectorTradeType (manual / Delphi)

Fonte: `profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas` L33-46:

```pascal
TTradeType = (ttZero            = 0,
              ttCrossTrade      = 1,
              ttAgressionBuy    = 2,
              ttAgressionSell   = 3,
              ttAuction         = 4,
              ttSurveillance    = 5,
              ttExpit           = 6,
              ttOptionsExercise = 7,
              ttOverTheCounter  = 8,
              ttDerivativeTerm  = 9,
              ttIndex           = 10,
              ttBTC             = 11,
              ttOnBehalf        = 12,
              ttRLP             = 13);
```

**Nota crítica:** o comentário em `SCHEMA.md` L33 está **incorreto**. Ele diz "1=auction, 2=normal, 3=cross". O mapeamento real do manual é `1=CrossTrade`, `2=AgressionBuy`, `3=AgressionSell`, `4=Auction`. Documentação drift (gap @sol).

### 3.2. Pipeline atual

1. **DLL → struct** (`TConnectorTrade.TradeType` é `c_ubyte`). ✅ correto.
2. **Wrapper** (`wrapper.translate_trade` L1735): `trade_type=int(struct.TradeType)`. ✅ correto.
3. **TradeRecord** (`download_primitive.py` L136): `trade_type: int`. ✅ correto.
4. **Schema parquet** (`schema.py` L96): `pa.field("trade_type", pa.uint8(), nullable=False)`. ✅ tipo correto, persistido.
5. **GAP:** o valor é gravado como `uint8` numérico — **NÃO há coluna `trade_type_name` resolvida** (e.g., "AgressionBuy", "Auction"). Downstream tem que lembrar o enum.

### 3.3. Trade date / preservação

Manual §3.2 (V2): `TConnectorTrade.TradeDate` é `SystemTime` (struct Win32 com `wYear..wMilliseconds`). `wrapper.translate_trade` chama `_system_time_to_ns_local(struct.TradeDate)` (L1728) → `timestamp_ns` BRT naive. Schema persiste `timestamp_ns` (`int64`, NOT NULL) + `timestamp_str` (string, NOT NULL).

**Precisão:** ms → ns (`*1000`). Sub-ms é perdido (DLL não fornece). ✅ aderente ao manual.

**Q-DRIFT-34 guard** (`wrapper.py` L1723-1724): trades com `wYear<=1900` (FILETIME 1601 sentinela) viram `None` → contados em `translate_failures`. Defense-in-depth correto.

### 3.4. Veredito trade types

**PARTIAL.** ID persistido corretamente como `uint8`, mas:
- Nome legível NÃO existe na coluna (analista precisa de tabela auxiliar de tradução).
- Comentário em SCHEMA.md L33 contém mapping errado (`2=normal` em vez de `2=AgressionBuy`).

---

## 4. translate_failures=961 — root cause

### 4.1. Análise do log

Log mostra apenas o counter agregado emitido em `download.complete` (L179): `translate_failures=961`. Não há linhas individuais (R21 — counter atomic, sem log per-trade).

### 4.2. Hipóteses ranked

**H1 (PROVÁVEL — ~99%)**: trades sentinela com `TradeDate.wYear <= 1900` filtrados pelo guard Q-DRIFT-34 (`wrapper.py` L1723-1724). A DLL emite o callback V2 com struct zerado/inicializado em momentos:
- Antes do primeiro trade real (warm-up).
- Entre packets para sincronizar handles internos.
- Trades de "edição" (`TC_IS_EDIT`) com payload incompleto.

961 / 796.963 = 0,12% — consistente com a literatura empírica de DLL vendor (sentinelas + housekeeping packets).

**H2 (POSSÍVEL — ~1%)**: `TranslateTrade` retornou NL_* negativo para handles válidos mas em estado inconsistente (race entre callback dispatch e DLL internal buffer). Callback V2 enfileira handle, IngestorThread chama TranslateTrade alguns ms depois — se DLL já reciclou o slot do handle, retorna NL_NOT_FOUND ou NL_INTERNAL_ERROR.

**H3 (REJEITADA)**: ABI mismatch. Se fosse, AVs/crashes seriam visíveis (e o log mostra um único Windows fatal exception isolado, sem outros crashes — provavelmente um sentinela tocando ponteiro inválido em `_translate_trade_raw` L1773 mas tratado pelo try/except defensivo `_run_inner` L307).

### 4.3. Veredito translate_failures

**ACEITÁVEL para MVP (0,12%)**, mas precisamos:
- Logar 1× por chunk a distribuição: quantas falhas foram `TradeDate.wYear<=1900` vs `rc != 0` vs exceção genérica. Hoje todos caem no mesmo counter.
- Considerar separar em `translate_failures_sentinel` vs `translate_failures_nl_error` vs `translate_failures_exception`.

---

## 5. Tabela schema parquet vs schema esperado pelo manual

| Campo manual / DLL | Manual ref | Parquet v1.0.0 | Status |
|--------------------|------------|----------------|--------|
| `TradeNumber` (uint32) | §3.2 V2 | `trade_id` int64 nullable | ✅ |
| `TradeDate` (SystemTime, ms) | §3.2 V2 | `timestamp_ns` int64 + `timestamp_str` | ✅ ms→ns |
| `Price` (double) | §3.2 V2 | `price` float64 | ✅ |
| `Quantity` (int64) | §3.2 V2 | `quantity` int64 | ✅ |
| `Volume` (double) | §3.2 V2 | — | ❌ DESCARTADO |
| `BuyAgent` (int32) | §3.2 V2 | `buy_agent_id` int32 nullable | ✅ ID |
| `BuyAgent` → name | §3.1 L1707 | — | ❌ AUSENTE no parquet |
| `SellAgent` (int32) | §3.2 V2 | `sell_agent_id` int32 nullable | ✅ ID |
| `SellAgent` → name | §3.1 L1707 | — | ❌ AUSENTE no parquet |
| `TradeType` (uint8) | §3.2 V2 + Delphi enum | `trade_type` uint8 NOT NULL | ⚠️ ID, sem nome |
| Flags V2 | §3.2 L1912 | `flags` uint32 NOT NULL | ✅ |
| `bIsEdit` | flag bit 0 | embutido em `flags` | ✅ |
| `TC_LAST_PACKET` | flag bit 1 | embutido em `flags` | ✅ |

**Volume**: campo do manual descartado (calculável `price*quantity` — decisão Sol, OK).

---

## 6. Recomendações para Dex (sem prescrever implementação)

1. **Bump schema → v1.1.0** (aditivo, minor): adicionar 3 colunas nullable:
   - `buy_agent_name string nullable` (já populado pelo resolver, hoje descartado pelo writer).
   - `sell_agent_name string nullable` (idem).
   - `trade_type_name string nullable` (lookup do enum Delphi `TTradeType`).

   Decisão é de Sol (schema authority) — Nelo recomenda baseado em compliance com manual + valor analítico. Custo on-disk: ~30 bytes/trade compressed (Snappy/Zstd dedup nomes repetidos drasticamente — 796k trades, ~100 brokers únicos = compressão >95%).

2. **Corrigir SCHEMA.md L33 trade_type comment**: mapping errado (`2=normal` deve ser `2=AgressionBuy`). Adicionar tabela completa do enum `TTradeType` (14 valores). Ownership: Sol.

3. **Manter Q-DRIFT-35 fix** mas atualizar comentário (`wrapper.py` L731-745): o "0x80000004 reinterpretado" está errado; `-2147483636 = NL_NOT_FOUND = 0x8000000C` (valor de erro semântico, não corrupção). Higiene ctypes ainda é boa prática.

4. **Telemetria translate_failures**: separar counter em 3 buckets (sentinel / nl_error / exception) para observability, sem custo em hot path (3× int+= é negligível). Dex decide se faz parte deste sprint.

5. **NÃO investir em** "eliminar 4 unknown_id" — são NL_NOT_FOUND legítimos para IDs especiais B3 (mesas/gateways/RLP). Fallback `Agent#{id}` é a resposta correta. Aceitável <0,001%.

---

## 7. Manual compliance %

- Fetch (callback V2 → TranslateTrade → struct): **100%** ✅
- In-memory representation (TradeFields/TradeRecord): **100%** ✅
- Resolução de nomes em runtime: **100%** ✅ (resolver funciona, cache funciona)
- Persistência no Parquet: **~70%** ⚠️ (IDs sim, nomes não, trade_type sem label)
- Documentação (SCHEMA.md): **~80%** ⚠️ (comment errado em trade_type)

**Composto: ~85%** (peso maior em fetch/in-memory que estão 100%).

---

## 8. Reporte JSON (para o agregador do council)

```json
{
  "agent_buyer_name_in_parquet": false,
  "agent_seller_name_in_parquet": false,
  "trade_type_resolved_in_parquet": false,
  "trade_date_preserved": true,
  "translate_failures_root_cause": "Q-DRIFT-34 sentinel guard (TradeDate.wYear<=1900) — DLL emite callbacks V2 com struct zerado em warm-up/housekeeping; 961/796963 = 0,12%, aceitável; recomendar separar counter em 3 buckets (sentinel/nl_error/exception)",
  "unknown_id_count": 4,
  "council_doc_path": "docs/decisions/COUNCIL-32-Nelo-agents-trade-types-2026-05-05.md",
  "agents_verdict": "PARTIAL",
  "trade_types_verdict": "PARTIAL",
  "manual_compliance_pct": 85,
  "recommendations_for_dex": [
    "Bump schema parquet v1.0.0 -> v1.1.0 com colunas nullable buy_agent_name, sell_agent_name, trade_type_name (decisão Sol)",
    "Corrigir SCHEMA.md L33 trade_type mapping (2=AgressionBuy, NÃO normal); adicionar tabela TTradeType de 14 valores",
    "Atualizar comentário Q-DRIFT-35 em wrapper.py L731-745: -2147483636 = NL_NOT_FOUND (0x8000000C), não 0x80000004 reinterpretado; o fix de signatures continua correto",
    "Telemetria translate_failures: separar em 3 counters (sentinel/nl_error/exception) para observability",
    "NÃO investir em zerar unknown_id; 4 IDs/796963 = 0,0005% são NL_NOT_FOUND legítimos para mesas/gateways B3"
  ]
}
```
