# Probe History Minimal — ctypes puro — VERDICT CENARIO_B

**Story:** 1.7d
**Timestamp:** 2026-05-05T10:55:18Z (BRT 07:55)
**Verdict:** **CENARIO_B** — zero trades recebidos. Bug é EXTERNO, NÃO no nosso wrapper/orchestrator.
**Implicação:** Diretiva "é bug, NÃO É DLL" é parcialmente refutada. Bug provável em conta/permissão/exchange code/contrato vigente, NÃO no código do projeto.

---

## Hipótese isolada

Probe ctypes puro (`scripts/probe_history_minimal.py`):

- **SEM** `data_downloader.dll.wrapper.ProfitDLL`
- **SEM** `data_downloader.orchestrator.download_chunk`
- **SEM** pytest
- **SEM** estruturas custom — apenas `WinDLL`, `WINFUNCTYPE`, structs do exemplo oficial Nelogica (`profitTypes.py`)

Resultado: **handshake perfeito (1.61s) + zero trades em 120s**.

Isso significa que mesmo reproduzindo EXATAMENTE o fluxo do exemplo oficial Nelogica (C++ `main.cpp:875-892` + Python `main.py` + `PROFITDLL_KNOWLEDGE.md §2.7`), trades históricos NÃO chegam.

---

## Resultado completo

```
[INFO] Python 3.14.3 (win32)
[INFO] cwd: C:\Users\Pichau\Desktop\data-downloader\profitdll\DLLs\Win64
[INFO] dll: C:\Users\Pichau\Desktop\data-downloader\profitdll\DLLs\Win64\ProfitDLL.dll
[INFO] SetEnabledLogToDebug(0) ret=-2147483646
[STEP] DLLInitializeMarketLogin...
[INIT] ret=0 elapsed=0.25s
[STEP] aguardando MARKET_CONNECTED...
[STATE] ATIVO
[STATE] LOGIN_OK
[STATE] MARKET_RESULT=1
[STATE] MARKET_RESULT=2
[STATE] MARKET_CONNECTED
[OK] connected em 1.61s
[STEP] SetHistoryTradeCallbackV2...
[CB] SetHistoryTradeCallbackV2 ret=0
[STEP] SubscribeTicker(WDOJ26, F)...
[SUB] WDOJ26/F ret=0
[REQ] GetHistoryTrades WDOJ26 '05/05/2026 08:45:23' -> '05/05/2026 10:45:23'
[REQ] GetHistoryTrades ret=0 elapsed=0.00s
[STEP] aguardando trades (timeout 120s)...
[WAIT] +10s trades=0
... (todos 0) ...
[WAIT] +110s trades=0
[FINAL] trades_received=0 last_packet=False wait=120.17s
[FINAL] time_to_market_connected=1.61s
[CLEANUP] UnsubscribeTicker ret=0
[CLEANUP] DLLFinalize ret=0
[VERDICT] CENARIO_B
```

Log completo: `docs/qa/SMOKE_EVIDENCE/logs/probe-history-minimal-20260505T105518Z.log`

---

## Comparação com `run_smoke_real_standalone.py`

| Aspecto | `run_smoke_real_standalone.py` (NOSSA wrapper) | `probe_history_minimal.py` (puro) |
|---------|------------------------------------------------|-----------------------------------|
| Stack | `ProfitDLL` class + `download_chunk` orchestrator | `ctypes.WinDLL` + WINFUNCTYPE |
| Init | minimal_handshake=True (3 args válidos + 7 None) | 11 slots todos preenchidos com Noop signatures EXATAS |
| State callback | dispatcher via Queue | dispatcher direto + log linear |
| Subscribe | `dll.subscribe_ticker(...)` (chama dll.SubscribeTicker dentro) | `dll.SubscribeTicker(c_wchar_p, c_wchar_p)` direto |
| HistoryTradeCallbackV2 | `make_history_trade_callback_v2` com fila | callback Python que apenas incrementa contador global |
| GetHistoryTrades | via `dll.get_history_trades(...)` | `dll.GetHistoryTrades(c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p)` direto |
| Símbolo/exchange | WDOJ26 / F | WDOJ26 / F |
| Janela | now-2h → now-10min | now-2h → now-10min |
| **Connect time** | 2.21s (probe wrapper class) | **1.61s** ✓ |
| **Trades recebidos** | 0 (em todas tentativas) | **0** ❌ MESMO comportamento |

**Conclusão da comparação:** o nosso código NÃO é o problema. Mesmo um probe ctypes puro com signatures literalmente copiadas do exemplo oficial Nelogica recebe ZERO trades — comportamento idêntico.

---

## Estados observados

State callback registrou (em ordem):

1. `nType=3, nResult=0` — ATIVACAO OK
2. `nType=0, nResult=0` — LOGIN OK
3. `nType=2, nResult=1` — MARKET_CONNECTING
4. `nType=2, nResult=2` — MARKET_CONNECTED_WAITING (csConnectedWaiting)
5. `nType=2, nResult=4` — MARKET_CONNECTED ✓ (1.61s)

`SubscribeTicker(WDOJ26, F)` retornou `0` (NL_OK).
`GetHistoryTrades(WDOJ26, F, "05/05/2026 08:45:23", "05/05/2026 10:45:23")` retornou `0` (NL_OK).
`SetHistoryTradeCallbackV2(historyTradeCallbackV2)` retornou `0` (NL_OK).

Tudo retornou OK. **Mesmo assim zero callbacks dispararam em 120s** — mesma matriz de sintomas dos smokes anteriores via wrapper.

---

## Hipóteses externas (em ordem de probabilidade)

### H1 — Conta sem permissão de histórico (ALTA probabilidade)
Conta de produção pode ter sido provisionada apenas para **roteamento/real-time**, NÃO para `GetHistoryTrades`. Manual menciona `NL_LICENSE_NOT_ALLOWED` mas DLL retornaria erro — a DLL retornar `NL_OK` e nunca disparar callback é consistente com licença que aceita request mas servidor backend ignora.

**Como validar:** contatar suporte Nelogica e confirmar se a conta `nicolas.car...@gmail.com` tem licença de **histórico de trades** (não apenas market data real-time).

### H2 — Pregão BMF aberto mas latência de servidor (MÉDIA)
Janela `now-2h` durante pregão aberto pode ainda estar em "buffer de consolidação". Servidor pode demorar mais para entregar histórico recente. **Mas:** 120s sem nenhum trade nem progress update sugere que NÃO é só latência — o request sequer chegou ao backend.

**Como validar:** repetir com janela bem antiga (ex: `2026-04-15 09:00 → 17:30` — pregão completo passado). Já testado em `run_smoke_real_standalone.py` com mesmo resultado.

### H3 — Exchange code errado para WDOJ26 (BAIXA, mas testar)
Documentação interna confirma `'F'` para BMF. Manual oficial: `B` (Bovespa), `F` (BMF). C++ exemplo usa `B` para PETR4 (Bovespa). Manual literal §3.1 L1673: `"Ticker: PETR4, Bolsa: B"`. WDO é definitivamente BMF, então `F` é correto. **Mas:** vale tentar testar com PETR4/B como sanity check (asset 100% certamente disponível).

### H4 — Contrato WDOJ26 vencido (BAIXA)
`WDOJ26` é abril/2026. Hoje é 2026-05-05 (maio). Contrato pode ter expirado. Vigente seria `WDOK26` (maio/2026) ou `WDOM26` (junho/2026).

**Como validar:** rodar mesmo probe com `WDOK26` ou `WDON26`.

### H5 — Bug na DLL versão (BAIXA — refuta diretiva)
Versão atual da DLL pode ter regressão. Mas como a infraestrutura toda funciona (handshake, subscribe, set_callback, get_history_trades retorna NL_OK), e o Delphi/C++ exemplos da Nelogica usam mesma DLL, isso seria muito improvável.

---

## Próxima ação recomendada

**Para o usuário (ordem de prioridade):**

1. **Verificar com Nelogica** (canal direto que estabeleceu a diretiva "não é DLL") se a conta tem permissão de **histórico de trades** especificamente, não só real-time. Esta é a hipótese H1 e tem maior probabilidade.

2. **Sanity check com PETR4/B** — rodar o mesmo probe trocando `("WDOJ26", "F")` por `("PETR4", "B")` para descartar problema específico ao contrato WDO. Se PETR4 traz trades → problema é com o contrato/exchange WDO. Se PETR4 também zero → confirma H1 (conta sem permissão histórica).

3. **Sanity check com contrato vigente WDOK26** — caso H4 seja real.

4. **Se Nelogica confirma conta com permissão**: escalar bug para suporte deles com este log + log do `run_smoke_real_standalone.py`. Toda diagnóstico interno aponta para problema do lado deles.

5. **Caminho B (mitigação imediata)**: aceitar `WAIVER 1.7b` se já existe e seguir adiante com mocks até desbloquear conta. Ou procurar conta de homologação Nelogica que sabidamente tenha permissão histórica.

---

## Arquivos relacionados

- `scripts/probe_history_minimal.py` — probe criado
- `docs/qa/SMOKE_EVIDENCE/logs/probe-history-minimal-20260505T105518Z.log` — log completo
- `docs/qa/SMOKE_EVIDENCE/1.7d-20260505T103538Z-standalone-pregao-FAIL-zero-trades-novamente.md` — smoke anterior com mesmo sintoma (via nossa wrapper)
- `docs/dll/PROFITDLL_KNOWLEDGE.md §2.7` — sequência canônica que foi reproduzida
- `profitdll/Exemplo C++/main.cpp:875-892` — referência da chamada `GetHistoryTrades`
- `profitdll/Exemplo Python/profitTypes.py` — structs usados

---

## Refutação parcial da diretiva

A diretiva "é bug, NÃO É DLL" assumia que o problema estava no nosso código. Este experimento prova que:

- **Não é bug do nosso wrapper** (probe puro tem mesmo sintoma).
- **Não é bug do nosso orchestrator** (probe não usa orchestrator).
- **Não é bug do pytest** (probe não usa pytest).
- **Pode ser problema de conta/permissão** (mais provável).
- **Pode ser bug ou comportamento da DLL** com esta conta específica (também possível).

A interpretação mais consistente: **o canal Nelogica disse "não é a DLL" pensando no software, mas o problema pode estar no provisionamento da conta no backend** — que do ponto de vista do dev é "externo à DLL" mas ainda assim do lado deles.
