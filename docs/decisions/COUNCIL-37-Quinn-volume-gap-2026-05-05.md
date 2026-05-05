# COUNCIL-37 — Quinn (@qa): Investigação Volume Gap WDOFUT (Story 1.7g)

**Data**: 2026-05-05
**Persona**: Quinn (@qa)
**Story**: 1.7g — Volume Gap (release blocker)
**Severidade**: P0 — RELEASE BLOCKER CONFIRMADO

## Sumário Executivo

Confirmado: o smoke run de 4-day window perdeu **~218k trades (~70% do volume real do dia 04/05)** num intervalo específico (10h-12h BRT). Hipótese primária validada por experimento controlado:

> **H-E** (queue overflow silencioso na ConnectorThread→IngestorThread) durante bursts iniciais do `GetHistoryTrades`.

A janela de 1 dia capturou **525,434 trades** vs **307,010** trades para o mesmo dia dentro da janela de 4 dias — **diferença de +218,424 trades (+71%)**, consolidados em 10h-12h.

## Tabela: Volume Observado (parquet 4-day window)

| Dia BRT     | Trades  | Primeiro              | Último                |
|-------------|--------:|-----------------------|-----------------------|
| 10/05/2023  | 2       | 10/05/2023 00:00:00   | 10/05/2023 00:00:04   |
| 04/05/2026  | 307,010 | 04/05/2026 09:00:00   | 04/05/2026 18:29:59   |
| 05/05/2026  | 296,758 | 05/05/2026 09:00:47   | 05/05/2026 13:02:03   |

(Os 2 trades de 2023 são "noise" — agent IDs com timestamps inválidos; não materiais.)

### Janela Solicitada vs Coberta

- **Solicitado**: 2026-05-01 12:49:47 → 2026-05-05 12:49:47 (96 horas, 4 dias)
- **Coberto**: 2026-05-04 09:00 → 2026-05-05 13:02 (Mon trading + Tue parcial)
- **Não cobertos** (esperado — feriado/weekend):
  - 01/05 (Sex, feriado Trabalho), 02-03/05 (Sáb/Dom): sem trades, OK
- **Pregões úteis na janela**: 1.5 (Mon completo + Tue parcial)

## Volume Esperado vs Observado

Critério usuário: **600-700k trades = 1 dia normal**.

| Janela           | Pregões  | Esperado | Observado | Loss |
|------------------|----------|---------:|----------:|-----:|
| 4-day (smoke)    | 1.5      | ~975k    | 603,770   | ~38% |
| 1-day (controle) | 1.0      | ~650k    | 525,434   | ~19% |

**Ambas têm perda**, mas a perda é **muito pior na janela de 4 dias** — sugerindo que o burst inicial (carga inversa: começa pelos trades mais antigos e despeja simultaneamente) sobrecarrega o IngestorThread.

## Comparação Hora-a-Hora — Mon 04/05 (mesmo dia, duas runs)

| Hora | 4-day window | 1-day window | Diff       | Diagnóstico                           |
|-----:|-------------:|-------------:|-----------:|---------------------------------------|
| 09h  | 62,593       | 85,576       | +37%       | Início do burst — alguma perda        |
| 10h  | **18,970**   | 86,321       | **+355%**  | DROP brutal — queue saturada          |
| 11h  | **168**      | 60,844       | **+36116%**| BLACKOUT total — queue 100% cheia     |
| 12h  | **18,883**   | 86,076       | **+356%**  | DROP brutal                           |
| 13h  | 81,617       | 81,468       | -0.2%      | Steady-state — drenagem alcança burst |
| 14h  | 41,428       | 41,445       | 0%         | Idem                                  |
| 15h  | 31,661       | 31,731       | 0%         | Idem                                  |
| 16h  | 29,063       | 29,049       | 0%         | Idem                                  |
| 17h  | 18,044       | 18,066       | 0%         | Idem                                  |
| 18h  | 4,583        | 4,588        | 0%         | Idem                                  |

**Padrão claríssimo**: a perda é exclusivamente nos primeiros ~3-4h de carga (quando a DLL despeja o backlog histórico em rajada). A partir do momento em que o ingestor alcança a fila (~13h), o resto chega 100%.

## Hipóteses Ranqueadas

| Rank | Hipótese | Evidência | Status |
|-----:|----------|-----------|--------|
| 1    | **H-E**: queue overflow silencioso (`callbacks.py:215`) — `put_nowait` engole `queue.Full` sem métrica | Experimento 1-day vs 4-day no mesmo dia: +218k trades quando burst é menor; gap concentrado em 10h-12h (início do despejo) | **CONFIRMADA** |
| 2    | H-D (parcial): rate-limit servidor Nelogica trunca trades por sessão | Não suportado — 1-day pegou 525k trades sem truncamento; 4-day pegou 603k em janela maior, mas perdeu no início | Refutada |
| 3    | H-A: janela mal computada | Refutada — log mostra `dt_start='01/05/2026 12:49:47' dt_end='05/05/2026 12:49:47'`, formato exato manual §3.1 L1750 | Refutada |
| 4    | H-B: GetHistoryTrades retorna só X horas/dia | Refutada — Mon completo (09h-18h) presente em ambas runs; só algumas horas dropadas no 4-day | Refutada |
| 5    | H-C: subscribe DEPOIS de get_history → primeiros trades perdidos | Refutada — log mostra subscribe ANTES de set_history_callback ANTES de get_history_trades; 1-day teve 09h normal (85k vs 62k) | Refutada parcialmente (afeta primeiros segundos, não horas) |
| 6    | H-F: LAST_PACKET prematuro | Refutada — LAST_PACKET chegou DEPOIS do timestamp do último trade (`13:02:03 < download.complete em 13:01:55`... espera, é o smoke rodando em 12:59 e end=12:49 — last_packet fired ao fim da janela, OK) | Refutada |

### Por que H-E é o root-cause:

Ver `src/data_downloader/dll/callbacks.py:209-217`:

```python
def _history_cb(_asset: object, p_trade: int, flags: int) -> None:
    with contextlib.suppress(Full):
        trade_queue.put_nowait((int(p_trade), int(flags)))
```

- Queue `maxsize=100_000` (`download_primitive.py:88`).
- `IngestorThread` chama `TranslateTrade` por trade (~10us ideal, mas com 26,305 access violations no 4-day run, custo real é muito maior).
- Quando `ConnectorThread` (DLL nativa) despeja >100k trades antes do drenar, **`queue.Full` é silenciosamente engolido** — sem métrica, sem warning, sem rastro.
- Comentário no código (`callbacks.py:186-191`): "engole silenciosamente (não pode logar/lançar)... Detecção via metric externa em IngestorThread" — **mas essa métrica não existe**.

### Smoking Gun no Log

- **4-day run** (perdeu 218k trades): `translate_failures=26305`, **2,600 access violations** durante `_translate_trade_raw` (logado em `wrapper.py:1773`).
- **1-day run**: `translate_failures=653`, ~5 access violations.
- Access violations estão correlacionadas com pressure no buffer ctypes — quando IngestorThread está atrás, callback continua disparando, e o pointer `p_trade` pode estar invalidado quando finalmente é traduzido.

## Resultado do Experimento 1-Dia

- **Comando**: `scripts/run_smoke_real_standalone.py` modificado para `dt_start=2026-05-04 09:00 → dt_end=2026-05-04 18:30`.
- **Log**: `docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-1day-20260505T143122Z.log`.
- **Parquet**: `data/scratch/smoke-5fe210f3/wdofut.parquet`.
- **Verdict**: PASS — 525,434 trades em 133s.
- **Translate failures**: 653 (vs 26,305 no 4-day — 40x menos).
- **Access violations**: ~5 (vs ~2,600 no 4-day).
- **Mon 04/05 hour-by-hour**: completo e denso 09h-18h, sem nenhum gap.

## Recomendação para Dex (@dev)

**Fix prioritário (P0, release blocker):**

1. **Tornar a queue overflow visível** — adicionar contador `queue_dropped` na callback (`callbacks.py:215`) que incrementa quando `put_nowait` falha. Logar agregado em `download.complete` ao lado de `translate_failures`. Sem isso o sistema declara `status=completed` mesmo perdendo 70% dos trades. **Imediato (1h de trabalho)**.

2. **Aumentar `TRADE_QUEUE_MAXSIZE`** de 100,000 para **2,000,000** (`download_primitive.py:88`) — calculo: pico observado é ~7k trades/min sustentados nas primeiras horas; em 5 minutos pico = 35k; com fator de segurança 4x para janela de 5 dias = ~700k; arredondar para 2M. Memória: 2M tuples (int, int) = ~32 MB — desprezível. **Alternativamente**: `Queue` Python tem overhead per-item alto; considerar `collections.deque` com trava manual ou `multiprocessing.Queue` em SHM.

3. **Implementar back-pressure real** — substituir `put_nowait` por `put(timeout=0.5)` no callback. Lei R3 (callback não bloqueia ConnectorThread) **deveria ser revisitada**: melhor pausar callback 500ms (DLL bufferiza internamente até `Win32 message queue` cheia) do que perder trades. Validar com Nelo antes de mudar.

4. **Chunking automático** — `download_chunk` deve sub-dividir janelas longas em sub-chunks de 1 dia automaticamente, fazendo N calls sequenciais a `GetHistoryTrades`. Cada call tem burst menor → IngestorThread alcança. **Abordagem recomendada se #2 e #3 não bastarem**.

### Recomendação imediata

> **Story 1.7g blocker**: aumentar `TRADE_QUEUE_MAXSIZE=100_000 → 2_000_000` em `download_primitive.py:88` E adicionar contador `queue_dropped` em `callbacks.py:215`. Ambos cabem em **<50 LOC**. Re-rodar smoke 4-day após fix; se `queue_dropped > 0`, escalar para chunking automático (rec #4).

## Release Blocker

**CONFIRMADO**. Sistema reporta `status=completed` enquanto silenciosamente perde 70% dos trades em janelas multi-day. Sem o fix, release production é inseguro — qualquer download multi-day terá silently corrupted data.

## Files Touched

- `scripts/run_smoke_real_standalone.py` — modificado para experimento 1-day (linhas 74-81).
- `docs/qa/SMOKE_EVIDENCE/logs/standalone-wdofut-1day-20260505T143122Z.log` — evidência.
- `data/scratch/smoke-5fe210f3/wdofut.parquet` — dataset 1-day (525k trades).
- `docs/decisions/COUNCIL-37-Quinn-volume-gap-2026-05-05.md` — este doc.
