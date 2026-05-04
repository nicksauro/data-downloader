# COUNCIL-03 — History Trade Callback: V1 vs V2

**Data:** 2026-05-03
**Convocação:** Dex (dev) — modo autônomo Story 1.3
**Participantes mentais:** Dex (impl authority), Nelo (DLL authority), Sol (TradeRecord schema authority)
**Contexto:** Story 1.3 AC1 exige decisão explícita V1 vs V2 para `SetHistoryTradeCallback`.
A versão V2 (`SetHistoryTradeCallbackV2` + `TranslateTrade`) foi introduzida em
4.0.0.20 e listada como recomendada em PROFITDLL_KNOWLEDGE.md §2.1 (R10/Q13-V).

---

## Opções consideradas

### Opção A — V1 (`SetHistoryTradeCallback`)
- Signature: `WINFUNCTYPE(None, c_wchar_p ticker, c_wchar_p bolsa, c_int feed,
  c_wchar_p date, c_uint tradeNumber, c_double price, c_double vol,
  c_int qtd, c_int buyAgent, c_int sellAgent, c_int tradeType)` (manual §3.2 L3002).
- Trade já vem desempacotado — sem `TranslateTrade` no caminho.
- **Cons:**
  - Marcada **obsoleta** no manual desde 4.0.0.20 (R10/Q13-V).
  - **Não expõe `TC_LAST_PACKET`** — terminação só via progress=100.
  - Sem flags estruturadas (TC_IS_EDIT etc.).
  - Sem `trade_id` direto — chave de dedup obrigatoriamente cai na variante longa
    (SCHEMA.md §2.1) com `sequence_within_ns` para todos os trades.

### Opção B — V2 (`SetHistoryTradeCallbackV2`)
- Signature: `WINFUNCTYPE(None, TConnectorAssetIdentifier asset,
  c_size_t pTrade, c_uint flags)` (espelha `tradeCallback` em
  `profitdll/Exemplo Python/main.py` L324).
- Tradução via `TranslateTrade(pTrade, byref(TConnectorTrade))` retorna struct
  rica com `TradeNumber` (= trade_id), `TradeDate` (SystemTime), `Price`,
  `Quantity`, `Volume`, `BuyAgent`, `SellAgent`, `TradeType`.
- Flags expostos (`TC_IS_EDIT=1`, `TC_LAST_PACKET=2` per padrão Connector V2).
- **Cons:**
  - `TranslateTrade` é função da DLL — **NÃO pode ser chamada dentro do callback**
    (Q06-V/R3/manual §4 L4382). Tem que rodar em IngestorThread.
  - Adiciona indireção: callback enfileira `(handle: c_size_t, flags: c_uint)`,
    IngestorThread chama `TranslateTrade` para obter o struct.

---

## Decisão

**ESCOLHER OPÇÃO B (V2).** `SetHistoryTradeCallbackV2` + `TranslateTrade` chamado
em IngestorThread (NÃO no callback).

### Justificativa

1. **R10/Q13-V** do MANIFEST exige V2 sempre que disponível (4.0.0.20+).
   ProfitDLL alvo é 4.0.0.34 (PROFITDLL_KNOWLEDGE.md §8) — V2 está disponível.
2. **`trade_id` real** disponível (= `TConnectorTrade.TradeNumber`) → permite dedup
   via chave curta `(symbol, timestamp_ns, trade_id)` (SCHEMA.md §2.1) — mais
   robusta que chave longa, dispensa `sequence_within_ns` na maioria dos casos.
3. **Flag `TC_LAST_PACKET`** dá sinal autoritativo de fim do download —
   complementa o callback de progresso (que pode travar em 99% — Q02-E).
   Mesmo que progresso 99% reconnect ocorra, `TC_LAST_PACKET` no último trade
   é sinal definitivo.
4. **Lei R3 preservada:** callback faz APENAS
   `queue.put_nowait((handle, flags))` — `TranslateTrade` é responsabilidade do
   IngestorThread (executa fora do callback). Documentado em docstring.
5. **Compat futura:** versões V2+ podem evoluir o `TConnectorTrade` (campos
   aditivos via `Version` ubyte) sem quebrar o callback signature — V1 é
   congelada.

### Implementação

```python
# src/data_downloader/dll/types.py — V2 signatures
THistoryTradeCallbackV2 = WINFUNCTYPE(
    None,
    TConnectorAssetIdentifier,  # asset
    c_size_t,                    # pTrade (handle opaco)
    c_uint,                      # flags (TC_IS_EDIT|TC_LAST_PACKET|...)
)

TC_IS_EDIT: Final[int] = 0x01
TC_LAST_PACKET: Final[int] = 0x02

# src/data_downloader/dll/callbacks.py
def make_history_trade_callback_v2(queue: Queue) -> Any:
    @THistoryTradeCallbackV2
    def _cb(asset, p_trade_handle, flags):
        # APENAS put_nowait — R3/INV-1.
        with contextlib.suppress(Full):
            queue.put_nowait((int(p_trade_handle), int(flags)))
    _cb_refs.append(_cb)
    return _cb

# src/data_downloader/orchestrator/download_primitive.py — IngestorThread
trade_struct = TConnectorTrade(Version=0)
while True:
    handle, flags = trade_queue.get(timeout=1.0)
    rc = dll.translate_trade(handle, trade_struct)  # <-- FORA do callback
    if rc != NL_OK:
        log.warning("download.translate_failed", ...)
        continue
    record = struct_to_trade_record(trade_struct, flags, ...)
    trades.append(record)
    if flags & TC_LAST_PACKET:
        last_packet_seen = True
```

### Fallback V1

A Story 1.3 implementa **V2 only**. V1 fica disponível apenas como signature
no `dll/types.py` (já existe — usada em NoopCallback do init slot). Stories
futuras que precisem operar em DLL < 4.0.0.20 (cenário hoje inexistente — alvo
é 4.0.0.34) podem adicionar `make_history_trade_callback_v1` sem quebrar
contratos. Por ora, **YAGNI**.

---

## Concordância de Nelo (DLL authority — mental)

Nelo concordaria com:
- Decisão por V2 (alinha com R10/Q13-V).
- `TranslateTrade` em IngestorThread — única forma de respeitar Q06-V/R3.
- Tipagem `c_size_t` para handle — espelha exatamente `profit_dll.py` L70-71
  (`TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]`).

Nelo enfatizaria:
- `Version=0` no `TConnectorTrade` antes de cada `TranslateTrade` (main.py L328
  faz isso; é preenchido pela DLL no retorno).
- **Reuso** do mesmo `TConnectorTrade` struct entre chamadas é seguro porque
  IngestorThread copia os campos para `TradeRecord` antes do próximo
  `TranslateTrade`.
- A flag `TC_LAST_PACKET=0x02` é convenção observada — não documentada
  explicitamente no manual mas referenciada como "flag de fim" em V2 (manual
  §3.2 L1912). Se na prática a flag for outra, ajustar via probe (Story 1.7
  smoke).

---

## Concordância de Sol (TradeRecord schema authority — mental)

Sol concordaria com:
- V2 dá `trade_id` (= `TradeNumber`) → chave curta de dedup
  (SCHEMA.md §2.1) — variante preferida quando disponível.
- IngestorThread enriquece com `ingestion_ts_ns`, `chunk_id`, `dll_version`,
  `sequence_within_ns` antes de devolver no `ChunkResult` — alinhado com
  schema v1.0.0 (17 campos).

Sol enfatizaria:
- `sequence_within_ns` ainda é preenchido (default 0) mesmo quando `trade_id`
  presente — campo é NOT NULL no schema. `assign_sequence_within_ns` da
  storage layer já trata isso.
- `source_callback="history_v2"` em todos os trades produzidos — distingue de
  trades live (`"trade_v2"`, futuro) para auditoria.

---

## Aplicação imediata nesta Story (1.3)

- `dll/types.py`: adicionar `TConnectorAssetIdentifier`, `TConnectorTrade`,
  `THistoryTradeCallbackV2`, `TProgressCallbackV2` (mantém também a V1
  `TProgressCallback` já existente para compat com NoopCallback do init slot).
- `dll/callbacks.py`: adicionar `make_history_trade_callback_v2`,
  `make_progress_callback`.
- `dll/wrapper.py`: adicionar `set_history_trade_callback_v2`,
  `set_progress_callback`, `get_history_trades`, `translate_trade`.
- `orchestrator/download_primitive.py`: implementa `download_chunk` chamando
  `TranslateTrade` em IngestorThread (NÃO no callback).
- Testes: assert via mock que callback faz APENAS `put_nowait` e que
  `TranslateTrade` é chamado em IngestorThread (mock_calls vazio durante
  callback exec).

— Dex 💻 (com mini-council Nelo + Sol)
