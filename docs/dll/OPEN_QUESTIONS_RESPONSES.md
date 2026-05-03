# OPEN_QUESTIONS_RESPONSES.md — Respostas às Perguntas Abertas sobre a ProfitDLL

**Curador:** Nelo 🗝️ (profitdll-specialist)
**Última atualização:** 2026-05-03

> Este documento responde às perguntas levantadas por outros agentes do squad data-downloader durante o **Plan Review 2026-05-03** sobre comportamento da ProfitDLL. Quando o manual é silencioso e não há evidência empírica suficiente, a resposta é **hipótese + probe proposto** (não invenção).

---

## Q1 — H4 (Pyro): "DLL drop-on-block?"

### Pergunta original (Pyro)

> "`dll_queue=10000` com taxa máxima observada de ~100k trades/s = **100ms de buffer**. Windows Defender scan, GC pause, page fault podem pausar 500ms-3s. Pergunta crítica: quando o consumer Python (engine thread) bloqueia em `put_nowait` (queue cheia), o que a ConnectorThread interna da DLL faz com os eventos pendentes?
>
> - (A) **Drop silencioso** — perda de dados invisível
> - (B) **Bloqueia** a ConnectorThread — toda a fila interna para, dispara `cosTimeout` eventualmente
> - (C) **Erro NL_** \* — entrega `NL_QUEUE_FULL` ou similar via callback de estado
>
> Sem essa resposta, **não posso definir queue policy** (drop-oldest? drop-newest? block? maxsize correto?). Bench de saturação em Story 1.4.5 fica não-determinístico."

### Resposta Nelo

**TL;DR:** Manual é **silencioso**. Hipótese empírica baseada em FFI similares (Bloomberg blpapi, MetaTrader, Sterling): comportamento provavelmente é **(B) — bloqueio com possível `cosTimeout` upstream**, mas isso precisa ser **validado por probe** antes de fixar a queue policy.

#### 1. O que o manual diz

Nada explícito. Manual §4 documenta:

> "Os dados recebidos são armazenados em uma única fila de dados. **O processamento demorado de qualquer callback atrasa a fila interna da DLL.**"

Esta frase indica que **existe back-pressure interno** (a fila interna tem comportamento de fila finita), mas **não diz o que acontece** quando essa fila satura.

Manual §3.1 lista `cosTimeout` como código de status, mas só no contexto de "timeout em conexão" — não está claro se também é disparado por saturação de fila.

#### 2. Inferência por analogia (FFI similares)

Outros FFI nativos com modelo "callback do servidor → cliente":

| FFI | Comportamento de saturação | Documentado? |
|-----|---------------------------|--------------|
| **Bloomberg blpapi** | Bloqueia thread de callback até consumer drenar | sim |
| **MetaTrader 5 (MT5)** | Drop silencioso após N eventos pendentes | parcial |
| **Sterling Trader API** | Bloqueia + dispara warning event | sim |
| **Interactive Brokers TWS** | Bloqueia + disconnect se persistente | sim |

A maioria das implementações **profissionais** opta por **(B)** porque drop silencioso é catastrófico para market data. **Hipótese forte:** ProfitDLL segue essa convenção.

#### 3. Hipótese consolidada

**Hipótese principal (Hb):**
- ConnectorThread tenta enfileirar evento → fila interna cheia → ConnectorThread **bloqueia** no `enqueue` interno.
- Bloqueio prolongado (>= N segundos) **pode** disparar `cosTimeout` via state callback (sinaliza saturação).
- Trades durante o período de bloqueio **chegam atrasados** (não perdidos), mas com timestamp original (BRT do servidor).

**Hipótese secundária (Hc):**
- Em casos extremos, DLL pode reportar `NL_QUEUE_FULL` ou desconectar (cosBroken).

**Hipótese descartada (Ha):**
- Drop silencioso é **improvável** em market data feed profissional.

#### 4. Implicações imediatas

**Independente da hipótese, esta política Python-side é segura:**

```python
# src/data_downloader/orchestrator/queues.py
DLL_QUEUE_MAXSIZE = 10000  # ~100ms a 100k trades/s — minimal back-pressure
WRITE_QUEUE_MAXSIZE = 50000  # ~500ms — absorve write stalls

# Padrão recomendado:
# - dll_queue.put(...) com timeout=N (NÃO put_nowait)  → cria back-pressure deliberado
# - Se put bloquear > N segundos, log "engine.dll_queue_saturated" + métrica
```

**Por quê `put` com timeout em vez de `put_nowait`:**
- `put_nowait` + drop = perda de dados (catastrófico para audit trail)
- `put` blocking = propaga back-pressure ao consumer da DLL (ConnectorThread bloqueia → trades atrasam mas não somem)
- Se ConnectorThread também bloqueia, eventualmente DLL pode disparar `cosTimeout` — captamos no state callback (Story 1.2 AC5 já drena state queue independentemente)

#### 5. Probe proposto (entra em Story 1.4.5 ou Story 1.7a)

**Owner sugerido:** Pyro mede + Nelo audita resultado.
**Onde:** Story 1.4.5 (synthetic baselines com mock DLL) é a fit ideal — não envolve DLL real, só caracteriza comportamento esperado. Probe **REAL** (com DLL) entra em Story 1.7a smoke.

**Setup do probe:**

```python
# benchmarks/bench_dll_saturation.py (esqueleto Pyro)

import time
from queue import Queue
from data_downloader.dll import ProfitDLL

dll = ProfitDLL()
dll.initialize_market_only(...)
dll.wait_market_connected()

trade_queue = Queue(maxsize=10000)
trade_count = {"received": 0, "processed": 0}

# Substitui callback de trade por put_nowait counting
def trade_cb(*args):
    trade_count["received"] += 1
    try:
        trade_queue.put_nowait(args)
    except queue.Full:
        pass  # NÃO faça isso em prod — só para isolar comportamento

dll.set_trade_callback(trade_cb)
dll.subscribe_ticker("WDOJ26", "F")  # contrato vigente líquido

# Fase 1: baseline 60s
time.sleep(60)
baseline_rate = trade_count["received"] / 60

# Fase 2: PAUSA do consumer (não drena queue) por 5s
print(f"PAUSING consumer for 5s. Queue size: {trade_queue.qsize()}")
time.sleep(5)
mid_count = trade_count["received"]
print(f"Received during pause: {mid_count - 60*baseline_rate}")

# Fase 3: drenar queue rapidamente, ver se DLL recupera
while not trade_queue.empty():
    trade_queue.get_nowait()
    trade_count["processed"] += 1

# Fase 4: 60s post-pause
time.sleep(60)
post_rate = (trade_count["received"] - mid_count) / 60

# Análise:
# - Se post_rate ≈ baseline_rate → DLL aguenta back-pressure (bloqueou e recuperou) → Hb confirmado
# - Se post_rate <<  baseline_rate → DLL desconectou ou degradou → Hc parcial
# - Se mid_count - 60*baseline == 5*baseline_rate → DLL não dropou (entregou todos) → Hb forte
# - Se mid_count - 60*baseline << 5*baseline_rate → DLL DROPOU → Ha confirmado (assustador)
# - Verificar state callback log: cosTimeout? cosBroken?
```

**Critério de sucesso do probe:**
1. Quantos trades entregues durante a pausa de 5s?
2. Algum NL_* error ou state change anormal?
3. DLL recuperou após pausa (post_rate vs baseline_rate)?

**Resultado esperado (hipótese Hb):**
- Trades durante pausa: ~`5 * baseline_rate` (DLL bufferizou tudo)
- Sem NL_* error (a menos que pausa > timeout interno DLL ~10-30s)
- post_rate ≈ baseline_rate (recuperação total)

#### 6. Onde esta resposta entra

- **Q15-OPEN** em [`QUIRKS.md`](./QUIRKS.md) referencia esta resposta.
- **Story 1.4.5** (Pyro synthetic baselines) inclui probe contra mock DLL.
- **Story 1.7a** (Dex orchestrator) inclui probe contra DLL real (smoke gated).
- **Decisão final de queue policy** será tomada por Aria (orchestrator design) com input do probe — provavelmente:
  - `dll_queue`: `Queue(maxsize=10000)`, `put(timeout=5.0)`. Timeout dispara métrica + log.
  - `write_queue`: `Queue(maxsize=50000)`, `put(timeout=30.0)`. Timeout = halt + alert.
- **Atualizar Q15-OPEN** para `validated` ou `empirical` após probe rodar e registrar evidência.

---

## Notas para próximas perguntas abertas

Quando outros agentes levantarem perguntas sobre comportamento da DLL durante o Epic 1:

1. **Buscar manual primeiro** — se cobre, citar seção/linha.
2. **Buscar evidência empírica** — whale-detector v2 / Sentinel §12 / código existente.
3. **Se nenhum dos dois cobre** → propor **probe** (`*probe-dll`) e registrar pergunta aqui como `Qn — open`.
4. **Nunca inventar** — se não tenho evidência, digo "não sei, vou testar".

— Nelo, guardião da DLL 🗝️
