# COUNCIL-38 — Nelo: Download flow audit (perda 70-80% volume WDOFUT)

- **Persona:** Nelo (profitdll-specialist)
- **Data:** 2026-05-05
- **Story:** 1.7g (smoke real WDOFUT — investigação perda volume)
- **Inputs auditados:**
  - `src/data_downloader/orchestrator/download_primitive.py` (download_chunk)
  - `src/data_downloader/dll/wrapper.py` (subscribe_ticker, set_history_trade_callback_v2, get_history_trades, translate_trade)
  - `src/data_downloader/orchestrator/chunker.py` (chunk_date_range, CHUNK_DAYS)
  - `src/data_downloader/orchestrator/orchestrator.py` (uso real do chunker)
  - `scripts/run_smoke_real_standalone.py` (smoke driver)
  - `profitdll/Exemplo Python/main.py` + `profitdll/Exemplo C++/main.cpp` (canonical Nelogica)
  - `docs/dll/PROFITDLL_KNOWLEDGE.md` + `docs/dll/QUIRKS.md` (Q-DRIFT-31..35)
  - `docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-persisted-20260505T125945Z.log` (UTF-16LE, 16006 lines)

---

## 1. Sumário executivo

**Resultado smoke:** 603,770 trades em 4 dias úteis WDOFUT.
**Esperado pelo usuário:** 600-700k trades **POR DIA** = 2.4M-2.8M em 4 dias.
**Perda observada:** ~75%.

**Hipótese primária ranqueada (H-A):** o smoke driver pede a janela inteira (4 dias) em **uma única chamada** `GetHistoryTrades`. O servidor Nelogica tem cap implícito por request — manual silencioso, mas Q-DRIFT-31 já documentou que >5 dias retorna 0. Suspeita forte: **mesmo dentro de 5 dias, o servidor trunca em ~600-800k trades por request**, encerrando com `TC_LAST_PACKET` prematuro. Solução: split em chamadas **diárias** (1 dia útil/chunk) e somar.

**Hipótese secundária (H-B):** 26,305 translate_failures + 2,600 access violations nativas durante o download — Q-DRIFT-33/34/35 hotfix incompleto. Mesmo com o guard de struct sentinela, a DLL emite repetidos handles inválidos. Pode estar mascarando trades reais como falhas.

---

## 2. Sequência atual vs canonical

### Sequência atual (download_primitive.py L634-693)

```
1. _IngestorThread.start() + _ProgressMonitor.start()
2. dll.subscribe_ticker(symbol, exchange)        # L641
3. dll.set_history_trade_callback_v2(history_cb) # L662
4. dll.set_progress_callback(progress_cb)        # L663 — Q-DRIFT-01: silenciosamente nop
5. dll.get_history_trades(symbol, exchange,
                          dt_start_str, dt_end_str)  # L664
6. while not (monitor.completed or ingestor.last_packet_seen
              or deadline): time.sleep(0.2)      # L678-693
7. finally: stop_event.set(); join; unsubscribe  # L694-724
```

**Análise da ordem:** subscribe → set_callback → get_history. A ordem está **correta** (Q-DRIFT-07 / PROFITDLL_KNOWLEDGE.md §2.7 / Exemplo Python main.py L590-595). O wrapper.set_history_trade_callback_v2 é chamado ANTES de get_history_trades — sem race com callback registration.

### Canonical Nelogica (Exemplo Python + C++)

`profitdll/Exemplo Python/main.py` L740-745: `progressCallBack` é passado como **slot 10 de DLLInitializeMarketLogin**, não via `SetProgressCallback` (Q-DRIFT-01 — função inexistente). `SetTradeCallbackV2` registrado em L753.

`profitdll/Exemplo C++/main.cpp` L877: única chamada `g_GetHistoryTrades` documentada usa janela de **2 dias** (`"12/01/2021"` → `"13/01/2021"`). Esta é a única evidência canônica de janela em código oficial.

`profitdll/Exemplo Python/main.py`: **NÃO há exemplo de download histórico funcional** — é interativo, só subscreve para live. Logo o exemplo Python NÃO mostra split de janela.

### Diferença crítica detectada

**Smoke driver (`run_smoke_real_standalone.py` L72-75)** pede 4 dias diretamente em uma chamada de `download_chunk`, ignorando o `chunker.chunk_date_range`:

```python
_SMOKE_DT_END = datetime.now() - timedelta(minutes=10)
_SMOKE_DT_START = _SMOKE_DT_END - timedelta(days=4)
...
result = download_chunk(dll, _SMOKE_SYMBOL, _SMOKE_EXCHANGE,
                        _SMOKE_DT_START, _SMOKE_DT_END, timeout=600)
```

**Orchestrator real (`orchestrator.py` L607, L640, L729)** usa `chunk_date_range` corretamente — `download_chunk` é chamado N vezes, uma por chunk.

**MAS:** `chunker.CHUNK_DAYS["WDO"] = 5` (5 dias úteis/chunk). Mesmo a produção pede 5 dias por request, e Q-DRIFT-31 mostra que servidor entrega 723k em 4d / 796k em 5d. **Se esses números são caps de servidor (não dados reais), produção também sangra 70%**.

---

## 3. Forensics do smoke log

UTF-16LE; 16,006 linhas. Eventos-chave (timestamps BRT do log):

| Evento | Timestamp | Linha | Notas |
|--------|-----------|-------|-------|
| `download.start` | 12:59:49 | 25 | dt_start=2026-05-01, dt_end=2026-05-05 (4d) |
| `dll.subscribe_ticker` | 12:59:49 | 26 | code=0 (linha 27) |
| `dll.history_trade_callback_v2_registered` | 12:59:49 | 28 | sem race com subscribe |
| `dll.progress_callback_unsupported` | 12:59:49 | 29 | Q-DRIFT-01 (esperado) |
| `dll.get_history_trades_call` | 12:59:49 | 30 | dt_start='01/05/2026 12:49:47', dt_end='05/05/2026 12:49:47' |
| `dll.get_history_trades_return` | 12:59:49 | 31 | code=0 |
| `download.last_packet` | 13:01:54 | 15996 | trades_count=603,770 |
| `dll.unsubscribe_ticker_return` | 13:01:54 | 15998 | code=0 |
| `download.complete` | 13:01:55 | 16000 | duration=124.979s, last_packet_seen=True, trade_edits=0, **translate_failures=26,305** |

**Tempo total entre `subscribe` e primeiro trade (LAST_PACKET final):** 125 segundos. Sem race observável (subscribe e callback registration ocorrem em sub-segundo, antes de get_history_trades).

**Throughput:** 603,770 / 125s = **~4,830 trades/s** sustentado.

**Acess violations nativas:** **2,600 ocorrências de "access violation"** no log (UTF-16 LE), TODAS com stack trace apontando para `wrapper.py:1773 _translate_trade_raw → wrapper.py:1706 translate_trade → download_primitive.py:348 _process_trade`. Cada AV provoca incremento de `translate_failures`.

**Razão translate_failures / total:** 26,305 / (603,770 + 26,305) = **4.17%** dos trades retornados pela DLL são falhas de tradução. NÃO é a explicação principal da perda de 75% — mas é evidência de que o pipeline não está limpo.

---

## 4. Hipóteses ranqueadas (com diff técnico)

### H-A — Server cap por request: ~600-800k trades/chamada (PROBABILIDADE: ALTA)

**Evidência:**
- Probe Q-DRIFT-31: 4 dias = 723.587 trades; 5 dias = 796.963 trades. Mesmo dentro do cap de janela "≤5d", os números são suspeitamente próximos a um cap de servidor.
- Smoke 2026-05-05 12:59 com janela 4d (dynamic now): 603.770 trades — abaixo dos 723k da probe Q-DRIFT-31 com mesma janela. Variável: `now-4d` cruzou final de semana (sex 01/05 + sab/dom + seg 04/05 + ter 05/05 = ~2 dias úteis efetivos → menor volume), mas ainda assim deveria ser >2M para 2 dias úteis se 600-700k/dia for verdade.
- Manual silencioso sobre cap por request.

**Diff conceitual (smoke driver):**

```python
# scripts/run_smoke_real_standalone.py — ATUAL
_SMOKE_DT_END = datetime.now() - timedelta(minutes=10)
_SMOKE_DT_START = _SMOKE_DT_END - timedelta(days=4)
result = download_chunk(dll, _SMOKE_SYMBOL, _SMOKE_EXCHANGE,
                        _SMOKE_DT_START, _SMOKE_DT_END, timeout=600)

# PROPOSTO — split por dia útil B3
from data_downloader.orchestrator.chunker import chunk_date_range
chunks = chunk_date_range("WDOFUT", "F",
                          _SMOKE_DT_START, _SMOKE_DT_END,
                          chunk_days_map={"WDO": 1})  # OVERRIDE: 1 dia/chunk
total_trades = 0
for chunk in chunks:
    r = download_chunk(dll, "WDOFUT", "F", chunk.start, chunk.end, timeout=600)
    total_trades += len(r.trades)
    print(f"chunk {chunk.start.date()}: {len(r.trades)} trades")
```

**Validação proposta:** rodar com `CHUNK_DAYS["WDO"]=1` e medir total. Se total > 2M, hipótese confirmada.

### H-B — translate_failures + 2,600 AVs durante TranslateTrade (PROBABILIDADE: MÉDIA)

**Evidência:**
- 26,305 translate_failures no log final.
- 2,600 ocorrências de "Windows fatal exception: access violation" no traceback faulthandler, todas em `_translate_trade_raw` → `dll.TranslateTrade(handle, byref(struct))`.
- Pico em ingestor após Q-DRIFT-34 hotfix — guard `wYear > 1900` evita kill thread, mas a AV nativa NÃO é evitada; só o fallout em Python é.

**Causa raiz suspeita (Nelo):** depois do TC_LAST_PACKET o callback V2 pode emitir handles "stale" cujo backing memory já foi liberado pela DLL. Cada AV é um `byref(struct)` lendo memória descomissionada. O guard atual só vê lixo zerado quando o ponteiro casualmente cai em zona zerada; quando cai em zona random, AV.

**Diff conceitual (defensivo no callback):**

```python
# src/data_downloader/dll/callbacks.py — make_history_trade_callback_v2
# ATUAL: callback enfileira (handle, flags) sem distinguir LAST_PACKET
def cb(asset_id, p_trade, flags):
    queue.put_nowait((p_trade, flags))

# PROPOSTO — drop handles após LAST_PACKET (TC_LAST_PACKET = 0x2)
_seen_last_packet = [False]
def cb(asset_id, p_trade, flags):
    if _seen_last_packet[0]:
        return  # ignora handles stale pós-fim
    queue.put_nowait((p_trade, flags))
    if flags & 0x2:  # TC_LAST_PACKET
        _seen_last_packet[0] = True
```

> **Risco:** R3 (callback APENAS put_nowait). Esta proposta adiciona check + flag — Aria valida se aceitável; alternativa é filtrar no IngestorThread por timestamp de chegada vs LAST_PACKET seen time.

### H-C — Race subscribe vs server propagation (PROBABILIDADE: BAIXA)

**Evidência contra:** subscribe retorna code=0 (estado interno DLL OK). GetHistoryTrades também retorna code=0 imediatamente. Servidor começa a despachar trades em <2s (já chegam aos milhares antes do timestamp 12:59:50).

**Veredito:** improvável. Pulamos.

### H-D — Janela > 1 dia gera truncamento (PROBABILIDADE: ALTA — cobre H-A)

**Evidência:**
- Probe Q-DRIFT-31 4d→723k, 5d→796k. Diferença marginal entre 4d e 5d (~10%) é suspeita: se cada dia tem 600-700k trades (afirmação do usuário), 5d deveria ter ~3.5M, NÃO 796k.
- Hipótese refinada: **servidor entrega no máximo ~800k trades por chamada, indiferente da janela**. Então 30d retorna 0 (Q-DRIFT-31 — interpretado como "janela inválida", mas pode ser "cap excedido cedo demais → 0 entregues").

**Veredito:** mesma classe de H-A; fix recomendado é split por dia.

### H-E — LAST_PACKET prematuro (PROBABILIDADE: MÉDIA, sub-hipótese de H-A/H-D)

**Evidência:**
- `last_packet_seen=True` em download.complete.
- Mas `actual_end` do ChunkResult não é logado no `download.complete` — não sabemos se o último trade está em 13:01:54 (= chegou ao fim da janela) ou em algum ponto interno (= servidor cortou).

**Diff conceitual (forensics):** adicionar log `actual_start` / `actual_end` em download.complete.

```python
# download_primitive.py:757-769 — adicionar:
log.info(
    "download.complete",
    ...,
    actual_start=actual_start.isoformat() if actual_start else None,
    actual_end=actual_end.isoformat() if actual_end else None,
    requested_start=dt_start.isoformat(),
    requested_end=dt_end.isoformat(),
)
```

Se `actual_end` < `requested_end - 1h`, LAST_PACKET foi prematuro — confirma cap servidor.

---

## 5. Fix recomendado priorizado

### P0 — Confirmar H-A com probe diário (Dex, blocker investigation)

Rodar smoke modificado com chunker `WDO=1d`:

```python
# scripts/probe_history_per_day.py (NOVO)
from datetime import date, datetime, time, timedelta
from data_downloader.dll.wrapper import ProfitDLL
from data_downloader.orchestrator.download_primitive import download_chunk
from data_downloader.validation.calendar_b3 import b3_business_days_range

dt_end = (datetime.now() - timedelta(minutes=10))
dt_start = dt_end - timedelta(days=10)
business_days = b3_business_days_range(dt_start.date(), dt_end.date())

with ProfitDLL() as dll:
    dll.initialize_market_only(KEY, USER, PWD, minimal_handshake=False)
    assert dll.wait_market_connected(timeout=300)
    for d in business_days:
        s = datetime.combine(d, time(0, 0, 0))
        e = datetime.combine(d, time(23, 59, 59, 999_999))
        r = download_chunk(dll, "WDOFUT", "F", s, e, timeout=600)
        print(f"{d}: {len(r.trades):>8d} trades / "
              f"failures={r.trades and 'N/A'} / "
              f"actual_end={r.actual_end}")
```

**Critério de sucesso:** se cada dia útil entregar 400k-700k trades (consistente com afirmação do usuário), H-A confirmada → fix é split diário.

### P1 — Reduzir CHUNK_DAYS["WDO"] = 1 (após confirmação H-A)

```python
# src/data_downloader/orchestrator/chunker.py:56-63
CHUNK_DAYS: Final[Mapping[str, int]] = {
    "WDO": 1,  # Q-DRIFT-31 + COUNCIL-38 (Nelo): server cap ~800k/request,
    "WIN": 1,  # split diário evita truncamento silencioso (H-A)
    "IND": 1,
    "DOL": 1,
}
```

Custo: 5× mais chamadas GetHistoryTrades, mas cada uma <30s pelo throughput observado (4,830 trades/s × 600k = 124s — bate com smoke). Total: ~10min/símbolo/dia para WDO ativo.

### P2 — Adicionar `actual_start`/`actual_end` ao download.complete (forensics)

Já mostrado em H-E; trivial. Permite detectar truncamento futuro automático.

### P3 — Investigar 2,600 access violations (Nelo + Aria)

Hipótese mais refinada: handles V2 stale pós-LAST_PACKET. Aria valida proposta H-B (filtro no callback ou no ingestor). Não é P0 porque mesmo com 4% de translate_failures, ainda recuperaríamos 96% dos trades — H-A é a causa primária da perda 75%.

---

## 6. Citações exatas (verificáveis)

- `profitdll/Exemplo C++/main.cpp:877`:
  > `if (g_GetHistoryTrades(asset, bolsa, (wchar_t*)L"12/01/2021", (wchar_t*)L"13/01/2021") != NL_OK)`
  Janela 1 dia (12 → 13 inclusive end) — único exemplo canônico operacional.

- `profitdll/Exemplo Python/main.py:740-743`:
  > `result = profit_dll.DLLInitializeMarketLogin(c_wchar_p(key), c_wchar_p(user), c_wchar_p(password), stateCallback, None, None, accountCallback, None, newDailyCallback, None, None, None, progressCallBack, tinyBookCallBack)`
  Confirma que `progressCallback` é slot, NÃO via `SetProgressCallback`.

- `profitdll/Exemplo Python/main.py:590-595`:
  > `def subscribeTicker(): ... result = profit_dll.SubscribeTicker(c_wchar_p(asset), c_wchar_p(bolsa))`
  Confirma `SubscribeTicker` antes de qualquer trade callback.

- `profitdll/Exemplo Python/main.py`: **NÃO contém GetHistoryTrades** — exemplo é interativo (live subscribe), não há exemplo de download histórico em Python oficial.

- Manual ProfitDLL (PDF, não acessível neste audit; referenciado via `docs/dll/PROFITDLL_KNOWLEDGE.md`): silencioso sobre cap de trades por request. Apenas indica formato de data §3.1 L1750 e janela ≤5d (Q12-E / Q-DRIFT-31).

---

## 7. Decisões finais Nelo

1. **NÃO modifiquei código** (escopo audit).
2. **Hipótese H-A** é a causa primária mais provável da perda 75% — recomendo Dex aplicar P0 (probe diário) + P1 (chunker=1d) prioritários.
3. **Hipótese H-B** (translate_failures + AVs) é secundária mas merece investigação follow-up (P3).
4. **Sequência subscribe → set_callback → get_history_trades está CORRETA** — não há fix necessário aqui. PROFITDLL_KNOWLEDGE.md §7 já documenta a ordem canonical e o código respeita.
5. **Recomendo NÃO impersonar Dex/Aria** — escalei a aplicação dos fixes a eles via mini-council (autoridade Constitution).

— Nelo, guardião da DLL 🗝️
