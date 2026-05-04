# DLL Full Audit Report — 2026-05-04

**Auditor:** 🗝️ Nelo (ProfitDLL Specialist)
**Escopo:** Auditoria completa do código DLL + orchestrator contra o exemplo oficial Nelogica + manual ProfitDLL
**Trigger:** Usuário (autoridade ProfitDLL real) confirmou que **NÃO HÁ IMPEDITIVO DA DLL — 100% bug nosso**.
**Fontes primárias usadas:**
- `profitdll/Exemplo Python/main.py` (1273 linhas — exemplo CANÔNICO)
- `profitdll/Exemplo Python/profit_dll.py` (102 linhas — argtypes/restype)
- `profitdll/Exemplo Python/profitTypes.py` (455 linhas — structs/enums)
- Manual ProfitDLL pt_br §3.1, §3.2, §4 + p.74-75
- `docs/dll/PROFITDLL_KNOWLEDGE.md` síntese viva
- `docs/dll/QUIRKS.md` Q01..Q-DRIFT-06

> **Modo de uso:** Cada finding tem severity, arquivo:linha, descrição, manual ref, sugestão concreta. Lista numerada para Dex consumir como TODO. NÃO toquei `src/` nem `tests/` — apenas auditoria.

---

## Sumário Executivo

| Severity | Count |
|----------|-------|
| 🔴 **CRITICAL** (root cause de "não baixa") | **3** |
| 🟠 **HIGH** (fail latente / corretude) | **5** |
| 🟡 **MEDIUM** (robustez / hygiene) | **4** |
| 🟢 **LOW** (cosmético / docs) | **2** |
| **TOTAL** | **14** |

**Veredito:** O download SEM `SubscribeTicker(ticker, exchange)` antes de `GetHistoryTrades` é a causa raiz primária. Adicionalmente, **NENHUMA função da DLL tem `argtypes`/`restype` configurados** no nosso wrapper (vs. exemplo oficial em `profit_dll.py` que configura ~30 funções). Isso por si só explica trades chegando mas estado interno corrompendo.

**Prioridade Dex:** Itens 1, 2, 3 desbloqueiam o download. Itens 4..8 evitam regressão futura. 9..14 são qualidade.

---

## 🔴 CRITICAL Findings

### CRIT-1: Falta `SubscribeTicker(ticker, exchange)` ANTES de `GetHistoryTrades`

- **Severity:** CRITICAL — causa direta de "trade callback nunca dispara"
- **Arquivo:** `src/data_downloader/orchestrator/download_primitive.py:564-566`
- **Descrição:** A primitiva `download_chunk` chama na ordem:
  1. `set_history_trade_callback_v2(history_cb)`
  2. `set_progress_callback(progress_cb)`
  3. `get_history_trades(symbol, exchange, dt_start, dt_end)`

  **Falta totalmente** a chamada `SubscribeTicker(ticker, bolsa)` antes do `GetHistoryTrades`. O wrapper nem expõe esse método.
- **Manual ref:** Manual §3.1 — `SubscribeTicker(ticker, bolsa)` é **pré-requisito** de qualquer recepção de dados (live OU histórico) para aquele asset. Confirmado pelo usuário (autoridade real): "para baixar WDOJ26, primeiro `SubscribeTicker('WDOJ26', 'F')`".
- **Exemplo oficial Nelogica:** `profitdll/Exemplo Python/main.py:590-595` define `subscribeTicker()` separadamente; usuário do exemplo executa `subscribe` (input do REPL) ANTES de qualquer outra operação no asset. O fluxo canônico do exemplo é `dllStart → wait_login → subscribeTicker → ... → operations`.
- **Verificação grep:** `grep "SubscribeTicker" src/` → **zero matches**. Confirmado: nunca chamamos.
- **Sugestão concreta para Dex:**
  1. Em `wrapper.py`, adicionar método:
     ```python
     def subscribe_ticker(self, ticker: str, exchange: str) -> int:
         if exchange not in ("F", "B"):
             raise ValueError(...)
         from ctypes import c_wchar_p
         ret = self._dll.SubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
         log.info("dll.subscribe_ticker", ticker=ticker, exchange=exchange, code=ret)
         return ret

     def unsubscribe_ticker(self, ticker: str, exchange: str) -> int:
         from ctypes import c_wchar_p
         return self._dll.UnsubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
     ```
  2. Em `download_primitive.py:download_chunk`, ANTES de `dll.set_history_trade_callback_v2(...)`:
     ```python
     sub_ret = dll.subscribe_ticker(symbol, exchange)
     if sub_ret < 0:
         status = "failed"
         nl_code = sub_ret
         # registrar gap, sair sem chamar GetHistoryTrades
     ```
  3. No `finally` do `download_chunk`, chamar `dll.unsubscribe_ticker(...)` para limpar (símbolo não fica subscrito após o chunk).
  4. Argtypes: `dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; dll.SubscribeTicker.restype = c_int` (configurar uma vez no init).

---

### CRIT-2: Argtypes/restype JAMAIS configurados em NENHUMA função

- **Severity:** CRITICAL — causa drift de stack frame stdcall + corrompe valores de retorno
- **Arquivo:** `src/data_downloader/dll/wrapper.py` (todo) — busca `argtypes` em `src/data_downloader/dll/` retorna **zero ocorrências** de configuração real (apenas comentários referenciando o arquivo de exemplo).
- **Descrição:** O exemplo oficial Nelogica configura `argtypes` e `restype` para **30+ funções** em `profit_dll.py:initializeDll()` (linhas 7-101). Nosso wrapper não configura nenhuma. Sem isso:
  - `c_int64` retornos podem chegar truncados em 32 bits;
  - `POINTER(struct)` args podem virar `int` (ctypes default), corrompendo Delphi stdcall;
  - `c_size_t` (handle de `TranslateTrade`) pode ser tratado como `c_int` pelo Python — em x64, isso silenciosamente trunca o handle de 64 bits.
- **Manual ref:** Manual §4 menciona stdcall + types Delphi exatos. `profit_dll.py` é a referência canônica de como configurar via Python ctypes.
- **Caso crítico — `TranslateTrade`:**
  - Oficial (`profit_dll.py:70-71`): `dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]; dll.TranslateTrade.restype = c_int`.
  - Nosso (`wrapper.py:977`): `rc = self._dll.TranslateTrade(p_trade_handle, byref(trade_struct))` — sem argtypes. Em x64 isso pode truncar o handle de 64 bits, fazendo `TranslateTrade` ler memória inválida e retornar lixo (ou crash).
- **Sugestão concreta para Dex:**
  1. Criar método `_configure_argtypes(self)` chamado no `initialize_market_only` LOGO APÓS `WinDLL(...)` e ANTES de `SetEnabledLogToDebug`. Replicar literalmente as ~30 entradas de `profit_dll.py` (porting com nossos tipos em `types.py`):
     ```python
     # Mínimo absolutamente necessário p/ V1 download:
     dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]
     dll.TranslateTrade.restype = c_int
     dll.GetHistoryTrades.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]
     dll.GetHistoryTrades.restype = c_int
     dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
     dll.SubscribeTicker.restype = c_int
     dll.UnsubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
     dll.UnsubscribeTicker.restype = c_int
     dll.GetAgentNameLength.argtypes = [c_int, c_int]
     dll.GetAgentNameLength.restype = c_int
     dll.GetAgentName.argtypes = [c_int, c_int, c_wchar_p, c_int]
     dll.GetAgentName.restype = c_int
     dll.SetEnabledLogToDebug.argtypes = [c_int]
     dll.SetEnabledLogToDebug.restype = c_int
     dll.DLLInitializeMarketLogin.restype = c_int
     dll.DLLFinalize.restype = c_int
     # Set*Callback funcs já são detectadas pelo ctypes (callback objects),
     # mas configurar restype = c_int é boa hygiene.
     ```
  2. Para funcs ainda não usadas (V1 trade, OfferBook, etc.), copiar de `profit_dll.py` ou marcar TODO.

---

### CRIT-3: `TranslateTrade` incompleta — campos `BuyAgent`/`SellAgent` lidos mas SEM resolução de nome

- **Severity:** CRITICAL (parcial — leitura ID OK; nome de corretora ausente)
- **Arquivos:**
  - `src/data_downloader/dll/wrapper.py:977` (TranslateTrade call)
  - `src/data_downloader/orchestrator/download_primitive.py:343-344` (lê IDs)
- **Descrição:** Confirmando o feedback do usuário ("TranslateTrade precisa estar 100% desenvolvida"):
  - **Atualmente fazemos:** `trade_struct.Version = 0` → `TranslateTrade(handle, byref(struct))` → lemos `Price, Quantity, TradeNumber, TradeDate, TradeType, BuyAgent (ID), SellAgent (ID)`. ✅ Esses campos estão sendo lidos.
  - **Falta:** `Volume` do struct (campo `c_double` em `profitTypes.py:287`) — não copiamos. Schema Sol requer apenas `price * quantity` derivado, mas a DLL já calcula em `Volume`.
  - **Falta principal:** **Nome dos agentes**. Temos `BuyAgent=123` e `SellAgent=456` (IDs), mas o usuário espera saber que `123 = "BTG Pactual"`. Resolução requer:
    - `GetAgentNameLength(id, shortFlag)` → `length`
    - `GetAgentName(length, id, buffer, shortFlag)` → preenche `buffer`
    - **Cache local obrigatório** (Q14-E + manual §3.1 L1707-1729)
    - **JAMAIS** chamar de dentro do callback (R3 / Q06-V).
- **Verificação:** `grep GetAgentName src/` → **zero matches** (apenas docstring referenciando como "fora do escopo").
- **Schema impact:** `TradeRecord` em `download_primitive.py:114-148` tem `buy_agent_id`/`sell_agent_id` (int IDs). Não tem `buy_agent_name`/`sell_agent_name`. Sol precisa decidir se o schema cresce.
- **Sugestão concreta para Dex (via mini-council com Sol):**
  1. Adicionar em `wrapper.py` um `AgentNameResolver` com cache thread-safe:
     ```python
     class AgentNameResolver:
         def __init__(self, dll):
             self._dll = dll
             self._cache: dict[tuple[int, bool], str] = {}
             self._lock = threading.Lock()

         def resolve(self, agent_id: int, *, short: bool = False) -> str:
             from ctypes import c_int, c_wchar_p, create_unicode_buffer
             flag = 1 if short else 0
             key = (agent_id, short)
             with self._lock:
                 cached = self._cache.get(key)
                 if cached is not None:
                     return cached
             length = self._dll.GetAgentNameLength(c_int(agent_id), c_int(flag))
             if length <= 0:
                 result = f"Agent#{agent_id}"
             else:
                 buf = create_unicode_buffer(length + 1)  # +1 NUL
                 rc = self._dll.GetAgentName(c_int(length), c_int(agent_id), buf, c_int(flag))
                 result = buf.value if rc == 0 else f"Agent#{agent_id}"
             with self._lock:
                 self._cache[key] = result
             return result
     ```
  2. Resolver **em IngestorThread** (cool path), **NUNCA** em callback (R3).
  3. Estender `TradeRecord`/schema com `buy_agent_name`/`sell_agent_name` (Sol owner).
  4. Fallback explícito `"Agent#{id}"` quando `length<=0` ou `rc != NL_OK`.
  5. **Não usar** `GetAgentNameByID` / `GetAgentShortNameByID` (DEPRECIADOS desde 4.0.0.24 — Q14-E).

---

## 🟠 HIGH Findings

### HIGH-1: Não chamamos `SetStateCallback` separadamente — só state via slot 4 do init

- **Severity:** HIGH — funciona, mas é frágil
- **Arquivo:** `wrapper.py:328, 353-359`
- **Descrição:** Passamos `state_cb` no slot 4 do `DLLInitializeMarketLogin`. O exemplo oficial Nelogica também faz isso (main.py L738), então **OK em essência**. Mas o exemplo NÃO substitui state callback depois — não há `SetStateCallback` no main.py. Por outro lado, manual lista `SetStateCallback` como função existente (probe via `getattr` em smoke pode confirmar). Se a DLL real expõe `SetStateCallback` e em alguma sessão o slot 4 do init for ignorado, ficaríamos sem state. Este risco é baixo, mas é um single point of failure.
- **Sugestão:** após o init, opcionalmente chamar `dll.SetStateCallback(state_cb)` adicional. Custo zero (re-registra mesmo callback). Tolerar `AttributeError` (Q-DRIFT-01 style). Documentar como "cinto-e-suspensório" em comentário.

---

### HIGH-2: Versionamento V1 vs V2 — slot 5 do init é V1 trade callback

- **Severity:** HIGH — não bloqueia download HISTÓRICO mas mostra confusão de tipo
- **Arquivo:** `types.py:149-161` (TTradeCallback) e `types.py:524` (`TTradeCallbackV2 = THistoryTradeCallbackV2`)
- **Descrição:** `DEFAULT_CALLBACK_REGISTRATIONS` registra `("SetTradeCallbackV2", TTradeCallbackV2)` (linha 573). Mas o **slot 5 do `DLLInitializeMarketLogin` é V1** (signature `TTradeCallback` em types.py L149). O exemplo oficial Nelogica passa o slot 5 V1 como `None` (main.py L742) e DEPOIS registra V2 via `SetTradeCallbackV2(tradeCallback)` (main.py L753). Nosso wrapper:
  - Slot 5 do init = NoopCallback com signature V1 (`TTradeCallback`).
  - Depois registra `SetTradeCallbackV2` com signature V2 (NoopCallback).

  Isto está OK em comportamento, mas **adicionamos um Noop V1 que o exemplo oficial nem usa**. Em si não bloqueia. Mas se a DLL trata "slot 5 = NULL" diferente de "slot 5 = noop V1 com signature errada", pode ser ruído.
- **Sugestão:** considerar passar `None` (refutado Q11-E em Q-DRIFT-06) no slot 5 do init para alinhar EXATAMENTE com main.py L742. Se Dex preferir manter Noop pela consistência R-CALLBACK, deixar comentário explicando que é cinto-e-suspensório.

---

### HIGH-3: Trade live (`SetTradeCallbackV2`) registrado com Noop sem necessidade

- **Severity:** HIGH — desperdício de slot + ruído no debug
- **Arquivo:** `types.py:573` + `wrapper.py:_register_default_callbacks`
- **Descrição:** Registramos `SetTradeCallbackV2(noop)` mesmo quando o uso é APENAS download histórico. Live trade não é o use case. O exemplo oficial registra `SetTradeCallbackV2(tradeCallback)` (main.py L753) porque o exemplo TEM trade live. Para nosso uso histórico-only, podemos pular ou deixar Noop. Não bloqueia, mas ofusca o que é realmente necessário.
- **Sugestão:** documentar em comentário no `DEFAULT_CALLBACK_REGISTRATIONS` quais callbacks são "ESSENCIAIS para histórico" vs. "OPCIONAIS para alinhamento com exemplo". Reduzir set futuro se algum smoke real provar que menos é mais.

---

### HIGH-4: `SetEnabledLogToDebug(0)` chamado SEM argtypes — silenciamento pode falhar silenciosamente

- **Severity:** HIGH — não-bloqueante mas mascara root causes em debug
- **Arquivo:** `wrapper.py:313` + ausência de argtypes (CRIT-2)
- **Descrição:** Sem argtypes, `dll.SetEnabledLogToDebug(0)` passa `0` como `c_int` por default Python — provavelmente OK em x64 mas em x86 (não usado, mas ilustrativo) falharia. O try/except `(AttributeError, OSError)` pode mascarar bugs reais.
- **Sugestão:** após CRIT-2, configurar `dll.SetEnabledLogToDebug.argtypes = [c_int]; dll.SetEnabledLogToDebug.restype = c_int`. Se retorno != NL_OK, log warning estruturado.

---

### HIGH-5: Sequência de boot não inclui `SubscribeTicker` — wait_market_connected retorna mas downloads falham

- **Severity:** HIGH (acoplado a CRIT-1 mas merece destaque arquitetural)
- **Arquivos:** `wrapper.py:initialize_market_only` + `wait_market_connected` + `download_primitive.py`
- **Descrição:** Sequência atual:
  1. `DLLInitializeMarketLogin` ← OK
  2. `_register_default_callbacks` (14 setters) ← OK alinhado a Story 1.7b-followup
  3. `wait_market_connected` ← retorna `True` quando recebe `(2, 4)`
  4. **`GetHistoryTrades` direto** ← MISSING `SubscribeTicker`

  Sequência canônica do exemplo (main.py): após `wait_login` retornar com `bMarketConnected = True`, o usuário do REPL precisa rodar `subscribeTicker` para CADA ativo antes de receber trades. Mesmo histórico precisa subscribe (confirmado pelo usuário).
- **Sugestão:** documentar a sequência canônica em comentário de topo de `download_primitive.py`:
  ```
  Sequência canônica para 1 chunk de download histórico:
    1. dll já initialized + wait_market_connected OK (Story 1.2).
    2. dll.subscribe_ticker(symbol, exchange).  ← NOVO (CRIT-1)
    3. dll.set_history_trade_callback_v2(history_cb).
    4. dll.set_progress_callback(progress_cb).
    5. dll.get_history_trades(symbol, exchange, dt_start, dt_end).
    6. Aguardar TC_LAST_PACKET ou progress=100 ou timeout.
    7. dll.unsubscribe_ticker(symbol, exchange).  ← NOVO (CRIT-1)
  ```

---

## 🟡 MEDIUM Findings

### MED-1: `TranslateTrade` não copia `Volume` (já calculado pela DLL)

- **Severity:** MEDIUM — schema completeness
- **Arquivo:** `download_primitive.py:329-347`
- **Descrição:** `TConnectorTrade` (profitTypes.py:287) tem campo `Volume: c_double` (preço × qty pré-computado pela DLL). Não copiamos para `TradeRecord`. Pode ser por design (schema Sol = 17 campos sem volume) — mas a info está disponível "de graça".
- **Sugestão:** confirmar com Sol se `volume` deve entrar no schema. Se não, comentar explicitamente que ignoramos por design (não esquecimento).

---

### MED-2: `bIsEdit` flag em `TradeRecord` mas live trade não suportada

- **Severity:** MEDIUM — design dead code
- **Arquivo:** `download_primitive.py:354-360`
- **Descrição:** Tratamos `flags & TC_IS_EDIT` em IngestorThread incrementando `trade_edits`. Para histórico V2, o manual e exemplo NÃO mencionam que histórico emite `TC_IS_EDIT`. O bit faz sentido para live trades (`SetTradeCallbackV2` em produção). Histórico raramente tem edição. O counter em si é OK, mas comentário em download_primitive.py:354 diz "Trade V2 com flag de edição" — sem contextualizar que isso é raro em histórico.
- **Sugestão:** documentar que esse counter é defensivo; observação deveria sempre ser zero em chunks históricos. Se valor > 0 em smoke real, escalar.

---

### MED-3: 14 `SetXxxCallback` registrados mesmo quando o uso é só histórico

- **Severity:** MEDIUM — robustez vs. simplicidade
- **Arquivo:** `wrapper.py:389-456` + `types.py:564-579`
- **Descrição:** Story 1.7b-followup adicionou `_register_default_callbacks` que itera sobre 14 setters. Justificativa: alinhar exatamente com o exemplo oficial (main.py L745-761). É correto se hipótese for "DLL precisa de TODOS os slots Set*Callback registrados para handshake completar". Mas Q-DRIFT-06 mostrou que o exemplo passa `None` em metade dos slots do init e funciona. Pode ser que o set posterior também tolere `None` ou ausência. Manter os 14 não machuca, mas adiciona superfície de erro (signatures, types).
- **Sugestão:** após CRIT-1 + CRIT-2 corrigirem o download real, fazer A/B de smoke:
  - A) Atual: 14 SetXxxCallback registrados.
  - B) Apenas `SetHistoryTradeCallbackV2` + (opcional) `SetTradeCallbackV2`.
  Manter A se B falhar. Se B funcionar, simplificar (menos código = menos bug).

---

### MED-4: `c_size_t` truncado em x64 sem argtypes

- **Severity:** MEDIUM (sub-caso de CRIT-2 mas merece destaque)
- **Arquivo:** `wrapper.py:977` + `callbacks.py:209-216`
- **Descrição:** O callback V2 (`make_history_trade_callback_v2`) recebe `p_trade: int` da signature `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)`. Faz `int(p_trade)` antes de enfileirar. OK no callback. **Mas** ao chegar em `wrapper.translate_trade(p_trade_handle, struct)`, sem `argtypes=[c_size_t, POINTER(TConnectorTrade)]`, ctypes pode passar como `c_int` (32 bits). Em Python 3 `int` é arbitrary precision, mas ctypes default é `c_int`. Isso TRUNCA handles de 64 bits.
- **Sugestão:** corrige automaticamente após CRIT-2. Para garantir, adicionar teste unit que passa um handle > 2**31 em mock e verifica que chega íntegro até `TranslateTrade.argtypes[0]`.

---

## 🟢 LOW Findings

### LOW-1: Documentação de R3 inconsistente — "manual §4 L4382"

- **Severity:** LOW (cosmético — referência de manual)
- **Arquivos:** múltiplos (`callbacks.py`, `download_primitive.py`, `wrapper.py`)
- **Descrição:** Várias docstrings citam "manual §4 L4382". Isto referencia o `manual_profitdll.txt` extraído do PDF. O manual real (PDF) tem a regra na p.74-75 / §"Uso do Produto". Linha citada (`L4382`) é do TXT extraído, não do PDF. Potencialmente confuso para quem só tem o PDF.
- **Sugestão:** complementar referências com `(p.74-75)` quando aplicável.

---

### LOW-2: `bolsa` (P-letter validation) duplicada em wrapper E em download_primitive

- **Severity:** LOW
- **Arquivos:** `wrapper.py:914-919` + `download_primitive.py:494-498` + `orchestrator.py:510-513`
- **Descrição:** Validação `exchange in ('F', 'B')` aparece 3× no codepath. DRY violation menor.
- **Sugestão:** centralizar em `dll/types.py` como `VALID_EXCHANGES: frozenset[str] = frozenset({"F", "B"})` + função `validate_exchange(s) -> None`.

---

## Lista numerada de TODOs para Dex (ordem de prioridade)

1. **[CRIT-1]** Adicionar `subscribe_ticker`/`unsubscribe_ticker` no wrapper. Chamar em `download_chunk` antes de `set_history_trade_callback_v2` e em `finally` para unsubscribe. **(desbloqueia download.)**
2. **[CRIT-2]** Configurar `argtypes`/`restype` em método `_configure_argtypes` chamado logo após `WinDLL(...)`. Mínimo absoluto: `TranslateTrade`, `GetHistoryTrades`, `SubscribeTicker`, `UnsubscribeTicker`, `GetAgentNameLength`, `GetAgentName`, `SetEnabledLogToDebug`, `DLLInitializeMarketLogin.restype`, `DLLFinalize.restype`.
3. **[CRIT-3]** Implementar `AgentNameResolver` com cache thread-safe. Chamar em IngestorThread (NÃO no callback). Estender schema `TradeRecord` com `buy_agent_name`/`sell_agent_name` (mini-council com Sol).
4. **[HIGH-5]** Documentar sequência canônica em comentário de topo de `download_primitive.py` incluindo subscribe/unsubscribe.
5. **[HIGH-1]** Adicionar `dll.SetStateCallback(state_cb)` redundante após init (cinto-e-suspensório, tolerar AttributeError).
6. **[HIGH-2]** Decidir: passar `None` no slot 5 do init (alinhado main.py L742) OU manter Noop V1 com comentário explicando.
7. **[HIGH-3]** Comentar quais callbacks de `DEFAULT_CALLBACK_REGISTRATIONS` são essenciais vs. apenas alinhamento com exemplo.
8. **[HIGH-4]** `SetEnabledLogToDebug` argtypes + log warning se retorno != NL_OK.
9. **[MED-1]** Mini-council com Sol: copiar `Volume` para `TradeRecord` ou marcar ignore explícito.
10. **[MED-2]** Comentar que `TC_IS_EDIT` em histórico deve sempre ser zero (defensive only).
11. **[MED-3]** Após CRIT-1+2 funcionarem, A/B smoke com 14 vs. minimal `SetXxxCallback`.
12. **[MED-4]** Teste unit cobrindo handle > 2**31 (regression guard para argtypes).
13. **[LOW-1]** Adicionar `(p.74-75)` em docstrings que citam "manual §4 L4382".
14. **[LOW-2]** Centralizar `VALID_EXCHANGES` em `dll/types.py`.

---

## Manual references cheat-sheet (para Dex consultar rapidamente)

- **§3.1 SubscribeTicker/UnsubscribeTicker:** prerequisitos para receber trades (live OU histórico).
- **§3.1 L1673:** bolsa = letra única. Nunca "BMF".
- **§3.1 L1707-1729:** `GetAgentNameLength` + `GetAgentName` (length-first pattern).
- **§3.1 L1750:** `GetHistoryTrades` formato `"DD/MM/YYYY HH:mm:SS"`.
- **§3.2 p.13/55:** state codes `MARKET_CONNECTING=1`, `MARKET_CONNECTED=4`.
- **§3.2 L1912:** `TC_LAST_PACKET` flag bit 1 do callback V2.
- **§4 p.74-75:** threading model — callbacks NÃO podem chamar funções da DLL.
- **`profit_dll.py` L7-101:** argtypes/restype canônicos para 30+ funções.
- **`main.py` L729-764 (`dllStart`):** sequência canônica de init + 14 SetXxxCallback.
- **`main.py` L590-595 (`subscribeTicker`):** chamada canônica `SubscribeTicker(c_wchar_p(asset), c_wchar_p(bolsa))`.
- **`main.py` L1185-1193 (`GetAgentName`):** length-first com `create_unicode_buffer`.

---

## Observações finais

**O que confirmamos manual-first:**
1. ✅ Manual + exemplo: `SubscribeTicker` é pré-requisito de qualquer recepção de dados (CRIT-1).
2. ✅ Exemplo `profit_dll.py` configura argtypes em todas as funções usadas (CRIT-2).
3. ✅ `TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]` é canônico (CRIT-2/MED-4).
4. ✅ `GetAgentName` length-first é a forma moderna (CRIT-3 / Q14-E).
5. ✅ Exemplo passa `None` em 4 dos 8 slots do init (Q-DRIFT-06 confirmado por main.py L742).

**O que NÃO está testado nesta auditoria (escopo de Dex/Quinn):**
- Smoke real após fixes — provar que o download volta a funcionar.
- Estender `TradeRecord` com `agent_name` (decisão Sol + schema).
- Comportamento de `GetAgentName` se ID for desconhecido (provavelmente `length=0` ou `NL_NOT_FOUND`).

**Atualização QUIRKS.md:** adicionei nota de `SubscribeTicker` mandatório como Q-DRIFT-07 (ver QUIRKS.md edit).

— Nelo, guardião da DLL 🗝️
