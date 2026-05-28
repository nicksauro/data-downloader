# PROFITDLL_KNOWLEDGE.md — Síntese Viva do Manual ProfitDLL (pt_br)

**Curador:** Nelo 🗝️ (profitdll-specialist)
**Fonte primária:** `Manual - ProfitDLL pt_br.pdf` (extraído em `manual_profitdll.txt`, 4452 linhas)
**Fontes secundárias:** `profitdll/Exemplo Python/main.py` (1274L) · `profit_dll.py` (signatures) · `profitTypes.py` (structs/enums)
**Validação empírica:** whale-detector v2 (live mode 2026-03-09) · Sentinel §12
**Última atualização:** 2026-05-05 (council Sol Story 1.7g — Quick Reference expandida 5→8 regras: #6 (janela vs volume real), #7 (NUNCA confiar em LAST_PACKET cego), #8 (NL_NOT_FOUND em GetAgentName é semântico). Cross-ref a `docs/INVARIANTS.md` I1-I6. Trigger: Q-DRIFT-36 (writer descarta colunas) + Q-DRIFT-37 (volume gap 70-80%) — ambos P0 release blockers.)

> **Regra de uso:** Este documento é a referência canônica do squad data-downloader. Toda afirmação aqui referencia seção/linha do manual OU está marcada como `[empírico]` / `[ambíguo]` com link ao quirk em `QUIRKS.md`. Quando manual e prática divergem, divergência é registrada — nunca escondida.

---

## ⚡ Quick Reference Canonical (top 8 do-and-don't)

Auditoria 2026-05-05 (council Sol — `docs/decisions/COUNCIL-35-Sol-documentacao-2026-05-05.md` + `docs/decisions/COUNCIL-40-Sol-invariantes-2026-05-05.md`) consolidou as seguintes regras de ouro a partir da cadeia Q-DRIFT-31..37:

| # | DO ✅ | DON'T ❌ | Ref |
|---|-------|----------|-----|
| 1 | **Histórico:** usar `WDOFUT`/`WINFUT` (continuous future) — entrega 723k–796k trades em 4–5d | NÃO usar contrato específico vencido (`WDOJ26` abril/2026) — retorna 0 trades silenciosamente | [Q-DRIFT-32](./QUIRKS.md#q-drift-32) (supersede Q01-V refutada) |
| 2 | **Janela:** `GetHistoryTrades` máximo ~5 dias úteis para WDO (1d para WIN). Exemplo C++ usa 2d. | NÃO pedir 30d em uma chamada — servidor Nelogica retorna code=0 silenciosamente sem despachar trades | [Q-DRIFT-31](./QUIRKS.md#q-drift-31), [Q12-E](./QUIRKS.md#q12-e) |
| 3 | **Subscribe sempre antes de GetHistory:** `SubscribeTicker(symbol, exchange)` → `SetHistoryTradeCallbackV2` → `GetHistoryTrades` → `UnsubscribeTicker` | NÃO chamar `GetHistoryTrades` sem `SubscribeTicker` prévio (autoridade Nelogica direta) — callback V2 nunca dispara mesmo com `NL_OK` | [Q-DRIFT-07](./QUIRKS.md#q-drift-07), §2.7 |
| 4 | **Init slots:** passar `None` literal nos 4 slots não usados de `DLLInitializeMarketLogin` (4=trade, 6=histTrade, 7=priceBook, 8=offerBook); `None` nos 4 + REAL nos 3 (5=daily, 9=progress, 10=tinyBook). Espelha `main.py` L742-743 | NÃO usar `NoopCallback` em slots não usados — bloqueia ConnectorThread durante handshake. NÃO passar `None` em slots 5/9/10 — DLL espera ack do snapshot inicial e trava em `(2,1)` | [Q11-E REFUTED](./QUIRKS.md#q11-e), [Q-DRIFT-06](./QUIRKS.md#q-drift-06), [Q-DRIFT-11](./QUIRKS.md#q-drift-11), [Q-DRIFT-12](./QUIRKS.md#q-drift-12) |
| 5 | **Argtypes/restype canônicos:** mesmo em `minimal_handshake=True`, registrar argtypes para `TranslateTrade`, `GetAgentNameLength`, `GetAgentName`, `SubscribeTicker`, `UnsubscribeTicker`, `GetHistoryTrades` ANTES de qualquer download | NÃO confiar em defaults ctypes (`c_int 32-bit signed`) em x64 stdcall — handles `c_size_t` truncam, length retorna `0x80000004 = -2147483636` | [Q-DRIFT-08](./QUIRKS.md#q-drift-08), [Q-DRIFT-33](./QUIRKS.md#q-drift-33), [Q-DRIFT-35](./QUIRKS.md#q-drift-35), §2.8 |
| 6 | **Janela GetHistoryTrades:** confirmar limite empírico real **por dia** vs **5d agregado** — investigação em curso (Nelo Council-38). Até validar, **considere split forçado por dia útil** quando volume esperado > 600k trades | NÃO assumir que 5d "que cabem" no manual entregam 5d completos — smoke real WDOFUT entregou 603k trades em 4d quando baseline de 1d ≈ 600-700k (perda silenciosa de 70-80%) | [Q-DRIFT-37](./QUIRKS.md#q-drift-37), [Q-DRIFT-31](./QUIRKS.md#q-drift-31) |
| 7 | **NUNCA confiar em `TC_LAST_PACKET` cego:** cross-checar `last_trade_timestamp` vs `dt_end_str` solicitado; se gap > threshold, agendar replay automático da janela faltante | NÃO declarar download "completo" só porque a flag `TC_LAST_PACKET` (ou retorno 0) foi recebida — server pode truncar volume sem sinalizar erro | [Q-DRIFT-37](./QUIRKS.md#q-drift-37), `INVARIANTS.md` I2 |
| 8 | **NL_NOT_FOUND em `GetAgentName` é semântico, não bug:** agent IDs >1M (mesas/gateways/RLP B3) frequentemente retornam `0x8000000C` (`-2147483636`) — preencher com fallback string (ex.: `"UNKNOWN_<id>"`); JAMAIS NULL silencioso no parquet | NÃO logar como erro / NÃO bloquear pipeline / NÃO deixar campo NULL silencioso (consumidor downstream perde rastreabilidade) | [Q-DRIFT-34](./QUIRKS.md#q-drift-34), [Q-DRIFT-36](./QUIRKS.md#q-drift-36), `INVARIANTS.md` I3 |

> **Regra absoluta de callback (R3 / [Q06-V](./QUIRKS.md#q06-v)):** todo callback registrado faz APENAS `queue.put_nowait(...)` e retorna em <100µs. NUNCA chamar funções da DLL de dentro do callback. NUNCA fazer log/print/I/O/sleep dentro do callback.

> **Regra absoluta de ctypes ([Q07-V](./QUIRKS.md#q07-v)):** lista global `_cb_refs: list = []` retém todos `WINFUNCTYPE`-wrapped objects. Append todo callback criado, never clear durante a vida do processo.

> **Invariantes do projeto:** ver [`docs/INVARIANTS.md`](../INVARIANTS.md) — princípios I1-I6 são **inegociáveis** e devem ser checados em CI/CD. Schema-as-Contract (I1), Volume Completeness (I2), Agent Name Resolution Graceful (I3), Trade Type Resolution (I4), Translate Failures Telemetria (I5), Window Split (I6).

---

## Índice

1. [Visão geral da DLL (manual §2)](#1-visão-geral)
2. [Funções expostas (manual §3.1)](#2-funções-expostas)
3. [Callbacks (manual §3.2)](#3-callbacks) — inclui §3.3 SetXxxCallback signatures canônicas (Q-DRIFT-09)
4. [Uso, threading, linkagem (manual §4)](#4-uso--threading)
5. [Códigos de erro NL_* (manual §5)](#5-códigos-de-erro)
6. [Sequência canônica de inicialização](#6-sequência-canônica-de-inicialização)
7. [Padrão canônico callback → queue](#7-padrão-canônico-de-uso)
8. [Versões da DLL documentadas](#8-versões-da-dll)

---

## 1. Visão geral

A ProfitDLL é uma DLL Windows (Win32 + Win64) escrita em Delphi pela Nelogica que expõe market data e roteamento (envio de ordens) para a plataforma B3. Carregada em Python via `ctypes.WinDLL` (stdcall convention).

**Áreas funcionais (manual §2):**
1. **Lifecycle / Sessão** — autenticar, conectar, encerrar
2. **Market Data** — subscribe/unsubscribe + callbacks de trade/livro/diário
3. **Trading** — envio/cancelamento/alteração de ordens, posições
4. **Metadata / Agentes** — resolução de nomes de corretoras, tradução de trades V2

**Modelos de inicialização:**
- `DLLInitializeMarketLogin` — **11 args** — só market data (esta é a função usada pelo data-downloader)
- `DLLInitializeLogin` — **13 args** — market data + roteamento (trading habilitado)

**Threading model (manual §3.2 linha 2732, §4 linha 4382):**
> "Os callbacks são chamados a partir de uma thread chamada ConnectorThread. Os dados recebidos são armazenados em uma única fila de dados. As funções de requisições à DLL ou qualquer outra função da interface da DLL **NÃO devem** ser chamadas dentro de um callback, pois isso pode causar exceções inesperadas e comportamento indefinido."

Esta regra (R3 do MANIFEST do squad) é **oficial**, não quirk.

---

## 2. Funções expostas

### 2.1 V1 vs V2 (R10)

A Nelogica modernizou a API ao longo das versões 4.0.0.18+ adicionando funções V2 que aceitam **structs** ao invés de listas longas de argumentos primitivos. **Funções V1 estão marcadas como obsoletas no manual** mas mantidas por compat.

| Área | V1 (obsoleta) | V2 (recomendada) | Versão de introdução |
|------|---------------|------------------|---------------------|
| Envio de ordem (compra) | `SendBuyOrder` | `SendOrder(TConnectorSendOrder*)` | 4.0.0.18 |
| Envio de ordem (venda) | `SendSellOrder` | `SendOrder` (mesmo, side=cosSell) | 4.0.0.18 |
| Envio market | `SendMarketBuyOrder`/`SendMarketSellOrder` | `SendOrder(OrderType=cotMarket=1)` | 4.0.0.18 |
| Envio stop | `SendStopBuyOrder`/`SendStopSellOrder` | `SendOrder(OrderType=cotStopLimit=4)` | 4.0.0.18 |
| Alterar ordem | `SendChangeOrder` | `SendChangeOrderV2(TConnectorChangeOrder*)` | 4.0.0.18 |
| Cancelar ordem | `SendCancelOrder` | `SendCancelOrderV2(TConnectorCancelOrder*)` | 4.0.0.18 |
| Cancelar várias | `SendCancelOrders` | `SendCancelOrdersV2(TConnectorCancelOrders*)` | 4.0.0.18 |
| Cancelar todas | `SendCancelAllOrders` | `SendCancelAllOrdersV2(TConnectorCancelAllOrders*)` | 4.0.0.18 |
| Zerar posição | `SendZeroPosition` | `SendZeroPositionV2(TConnectorZeroPosition*)` | 4.0.0.18 |
| Listar ordens | `GetOrders` / `GetOrder` / `GetOrderProfitID` | `GetOrderDetails(TConnectorOrderOut*)` + `EnumerateOrdersByInterval` / `EnumerateAllOrders` | 4.0.0.20 |
| Posição | `GetPosition` | `GetPositionV2(TConnectorTradingAccountPosition*)` | 4.0.0.20 |
| Conta | `GetAccount` | `GetAccountDetails(TConnectorTradingAccountOut*)` + `GetAccountCount`/`GetAccounts` | — |
| Nome agente | `GetAgentNameByID` / `GetAgentShortNameByID` | `GetAgentNameLength(id, shortFlag)` + `GetAgentName(length, id, buf, shortFlag)` | 4.0.0.24 |
| Trade callback | `SetTradeCallback` (TNewTradeCallback) | `SetTradeCallbackV2` (TConnectorTradeCallback + `TranslateTrade`) | 4.0.0.20 |
| History trade callback | `SetHistoryTradeCallback` (THistoryTradeCallback) | `SetHistoryTradeCallbackV2` (TConnectorTradeCallback + `TranslateTrade`) | 4.0.0.20 |
| Order change callback | `SetOrderChangeCallback` | `SetOrderChangeCallbackV2` (+ ValidityType, LastUpdate, etc.) | — |
| History callback | `SetHistoryCallback` | `SetHistoryCallbackV2` | — |
| Adjust history callback | `SetAdjustHistoryCallback` | `SetAdjustHistoryCallbackV2` | — |
| Asset list info | `SetAssetListInfoCallback` | `SetAssetListInfoCallbackV2` (+ setor, subSetor, segmento) | — |
| Offer book callback | `SetOfferBookCallback` | `SetOfferBookCallbackV2` (Int64 nQtd) | — |
| Price book callback | `SetPriceBookCallback` (DEPRECIADA) | `SetPriceBookCallbackV2` (DEPRECIADA → use **PriceDepth**) | — |
| Livro de preços | `SubscribePriceBook` (DEPRECIADA) | `SubscribePriceDepth` + `SetPriceDepthCallback` + `GetPriceDepthSideCount` + `GetPriceGroup(TConnectorPriceGroup*)` | 4.0.0.31 |

### 2.2 Lifecycle (manual §3.1, §4)

| Função | Args | Retorno | Uso |
|--------|------|---------|-----|
| `DLLInitializeLogin` | 13 (key, user, pass, state, history, orderChange, account, trade, daily, priceBook, offerBook, histTrade, progress, tinyBook) | `int` | Market + trading |
| `DLLInitializeMarketLogin` | 11 (key, user, pass, **state**, **trade**, **daily**, **priceBook**, **offerBook**, **histTrade**, **progress**, **tinyBook**) | `int` | Só market data |
| `DLLFinalize` | 0 | `int` | Encerrar — **OFICIAL no manual** [Q09-AMB: whale-detector observou `Finalize()`] |
| `SetServerAndPort` | 2 (server, port) | `int` | Antes de init, com orientação Nelogica |
| `GetServerClock` | 8 (out dtDate, y, m, d, h, min, s, ms) | `int` | Relógio servidor |
| `SetDayTrade` | 1 (useDayTrade: int) | `int` | 1=True, 0=False |
| `SetEnabledLogToDebug` | 1 (enabled: int) | `int` | 0=silencia log nativo da DLL (recomendado em produção) |
| `SetEnabledHistOrder` | 1 (enabled: int) | `int` | Habilita histórico de ordens (chamar após init) |
| ~~`GetDLLVersion`~~ | — | — | **Q-DRIFT-01 (2026-05-04)**: NÃO exportada pela DLL real (probe via `getattr` em `profitdll/DLLs/Win64/ProfitDLL.dll`). Wrapper retorna `"unknown"` graciosamente; metadata Parquet usa esta string. |
| ~~`SetProgressCallback`~~ | — | — | **Q-DRIFT-01 (2026-05-04)**: NÃO exportada como função standalone. Per `Exemplo Python/main.py` L740-743, o `progressCallBack` é o **slot 10 de `DLLInitializeMarketLogin`** (já preenchido com Noop pelo wrapper). Para ativar, precisa custom-noop no slot — fora do escopo Story 1.3. Detecção de fim via **`TC_LAST_PACKET`** (V2 flag). |

### 2.3 Market Data — Subscriptions

| Subscribe | Unsubscribe | Callback disparado |
|-----------|-------------|-------------------|
| `SubscribeTicker(ticker, bolsa)` | `UnsubscribeTicker(ticker, bolsa)` | `TNewTradeCallback` (V1) ou `TConnectorTradeCallback` (V2) |
| `SubscribeOfferBook(ticker, bolsa)` | `UnsubscribeOfferBook` | `TOfferBookCallback`/V2 |
| `SubscribePriceBook` (**DEPRECIADA**) | `UnsubscribePriceBook` | — (use Depth) |
| `SubscribePriceDepth(assetId*)` | `UnsubscribePriceDepth` | `TConnectorPriceDepthCallback` |
| `SubscribeAdjustHistory(ticker, bolsa)` | `UnsubscribeAdjustHistory` | `TAdjustHistoryCallback`/V2 |
| `RequestTickerInfo(ticker, bolsa)` | — | `TAssetListInfoCallback`/V2 |

**Bolsa = uma letra única** (Q05-V): `B` (Bovespa), `F` (BMF). Manual §3.1 linha 1673 é literal: `"Ticker: PETR4, Bolsa: B"`. Usar string `"BMF"` retorna `NL_EXCHANGE_UNKNOWN`.

### 2.4 Market Data — Queries

| Função | Retorna |
|--------|---------|
| `GetPriceDepthSideCount(assetId*, side)` | tamanho do lado do livro |
| `GetPriceGroup(assetId*, side, position, priceGroup*)` | entrada do livro |
| `GetTheoreticalValues(assetId*, out price, out qty)` | preço teórico (leilão) |
| `GetLastDailyClose(ticker, bolsa, out close, adjusted)` | fechamento D-1 |
| `GetHistoryTrades(ticker, bolsa, dtStart, dtEnd)` | dispara `HistoryTradeCallback` + `ProgressCallback` |

**`GetHistoryTrades` quirks:**
- ~~**Q01-V**: `WDOFUT`/`WINFUT` (genéricos) retornam **0 trades** em janelas históricas. Usar **contrato vigente** (`WDOJ26`, `WINH26`).~~ **REFUTADA 2026-05-05** — ver [Q-DRIFT-32](./QUIRKS.md#q-drift-32). Realidade: **SEMPRE usar `WDOFUT`/`WINFUT` (continuous future)** para histórico. Contratos específicos vencidos é que retornam 0 trades.
- **Q02-E**: progresso 99% NÃO é trava — DLL cicla conexão antes de entregar histórico. Aguardar até **1800s** sem progresso real.
- **Q-DRIFT-31 / Q12-E**: chunk size **adaptativo** — WDO 5d, WIN 1d funciona. Maior pode timeout. Validado empiricamente 2026-05-05 (probe entrega 723k trades em 4d com WDOFUT).

### 2.5 Trading — Ordens (V2)

| Função V2 | Struct param | Retorno |
|-----------|--------------|---------|
| `SendOrder` | `TConnectorSendOrder*` | `int64` (LocalOrderID ou NL_*) |
| `SendChangeOrderV2` | `TConnectorChangeOrder*` | `int` |
| `SendCancelOrderV2` | `TConnectorCancelOrder*` | `int` |
| `SendCancelOrdersV2` | `TConnectorCancelOrders*` | `int` |
| `SendCancelAllOrdersV2` | `TConnectorCancelAllOrders*` | `int` |
| `SendZeroPositionV2` | `TConnectorZeroPosition*` | `int64` |

Rastreamento: `ClOrderID` (permanente) + `MessageID` (sessão).

### 2.6 Metadata / Agentes (manual §3.1)

- `GetAgentNameLength(id, shortFlag)` → `int` — **OBRIGATÓRIO chamar PRIMEIRO** (Q14-E)
- `GetAgentName(length, id, buffer, shortFlag)` → `int` — preenche buffer
- `GetAgentNameByID` / `GetAgentShortNameByID` → **DEPRECIADAS** desde 4.0.0.24
- `TranslateTrade(pTrade, TConnectorTrade*)` → destrincha trade V2

**Cache local obrigatório.** **JAMAIS** chamar de dentro do callback (manual §4).

### 2.7 SubscribeTicker — PRÉ-REQUISITO de QUALQUER trade callback (Q-DRIFT-07)

**Confirmado pelo usuário (autoridade Nelogica direta) em 2026-05-04:**
> "para baixar WDOJ26, primeiro `SubscribeTicker('WDOJ26', 'F')`. Sem subscribe, callback nunca dispara, mesmo que `GetHistoryTrades` retorne `NL_OK`."

**Sequência canônica para download histórico de 1 chunk:**
```python
# 1. Subscribe ANTES de qualquer set_callback ou GetHistory
ret = dll.SubscribeTicker(c_wchar_p(symbol), c_wchar_p(exchange))  # exchange = 'F' ou 'B'
if ret < 0: raise DLLError(...)

# 2. Registrar callbacks V2
dll.SetHistoryTradeCallbackV2(history_cb)  # callback faz APENAS put_nowait((handle, flags))

# 3. Disparar download
dll.GetHistoryTrades(symbol, exchange, dt_start_str, dt_end_str)

# 4. Drenar fila em IngestorThread; aguardar TC_LAST_PACKET ou progress=100 ou timeout

# 5. Unsubscribe quando chunk completar (limpa estado da sessão para próximo chunk)
dll.UnsubscribeTicker(c_wchar_p(symbol), c_wchar_p(exchange))
```

Argtypes obrigatórios (ver §2.8):
- `dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; .restype = c_int`
- `dll.UnsubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; .restype = c_int`

Para live trade subscriber (Story futura): mesma `SubscribeTicker` + `SetTradeCallbackV2`.

### 2.8 Argtypes/Restype canônicos (Q-DRIFT-08)

A DLL é Delphi stdcall. Sem `argtypes` configurados, ctypes usa `c_int` por default — quebra com handles `c_size_t` (truncado para 32 bits em x64), com `c_int64` retornos (LocalOrderID), e com `POINTER(struct)` args (Delphi espera Pointer, ctypes manda int).

**Configurar UMA vez no init**, replicar literalmente de `profitdll/Exemplo Python/profit_dll.py:7-101`. Mínimo absoluto para download histórico V1:

```python
from ctypes import POINTER, c_double, c_int, c_int64, c_size_t, c_wchar_p

# Histórico
dll.GetHistoryTrades.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]
dll.GetHistoryTrades.restype = c_int
dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]
dll.TranslateTrade.restype = c_int

# Subscribe
dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
dll.SubscribeTicker.restype = c_int
dll.UnsubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
dll.UnsubscribeTicker.restype = c_int

# Agentes (Q14-E)
dll.GetAgentNameLength.argtypes = [c_int, c_int]
dll.GetAgentNameLength.restype = c_int
dll.GetAgentName.argtypes = [c_int, c_int, c_wchar_p, c_int]
dll.GetAgentName.restype = c_int

# Lifecycle
dll.SetEnabledLogToDebug.argtypes = [c_int]
dll.SetEnabledLogToDebug.restype = c_int
dll.DLLInitializeMarketLogin.restype = c_int
dll.DLLFinalize.restype = c_int
```

Lista completa para todas as funções da DLL (incluindo trading): `profitdll/Exemplo Python/profit_dll.py`.

---

## 3. Callbacks

### 3.1 Tabela completa

Todos com convenção **stdcall** (`WINFUNCTYPE` em Python ctypes). Todos disparados na **ConnectorThread** interna da DLL.

> ⚠️ **NOTA CRÍTICA — TAssetID por valor (Q-DRIFT-05, descoberto 2026-05-04):**
> A maioria dos callbacks legados V1 (todos os listados na coluna "Signature" abaixo que começam com `rAssetID`) recebem o struct **`TAssetID` POR VALOR como UM ÚNICO ARG**, não 3 args primitivos expandidos.
>
> **Definição canônica (`profitdll/Exemplo Python/profitTypes.py` L293-296):**
> ```python
> class TAssetID(Structure):
>     _fields_ = [("ticker", c_wchar_p),
>                 ("bolsa", c_wchar_p),
>                 ("feed", c_int)]
> ```
>
> **Exemplos `WINFUNCTYPE` corretos (`profitdll/Exemplo Python/main.py`):**
> - L243 progress: `WINFUNCTYPE(None, TAssetID, c_int)` — 2 args
> - L336 tinyBook: `WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)` — 4 args
> - L346 daily: `WINFUNCTYPE(None, TAssetID, c_wchar_p, c_double × 11, c_int × 7)` — 20 args
> - L391 offerBook V2: `WINFUNCTYPE(None, TAssetID, c_int × 5, c_longlong, c_double, c_int × 5, c_wchar_p, POINTER(c_ubyte) × 2)` — 16 args
>
> **NUNCA expandir TAssetID em `(c_wchar_p, c_wchar_p, c_int)`** — desalinha o stack frame de stdcall e causa silent corruption na ConnectorThread (root cause de Q-DRIFT-02, manifest do bug "MARKET_CONNECTING preso em (2,1)").
>
> Callbacks **V2** novos (TConnectorTradeCallback, TConnectorPriceDepthCallback, etc.) usam `TConnectorAssetIdentifier` (também struct por valor — `profitTypes.py` L88-94).

| Callback | Signature (resumo) | Manual ref | Notas |
|----------|-------------------|------------|-------|
| `TStateCallback` | `(nConnStateType: int, nResult: int)` | §3.2 L2738, L3267 | Estados de conexão; sequência canônica seção 6 |
| `TProgressCallback` | `(rAssetID: TAssetIDRec, nProgress: int)` | §3.2 L2739, L3750 | 1..100; 99 + reconnect = quirk Q02-E |
| `TNewTradeCallback` (V1) | `(rAssetID, pwcDate, nTradeNumber, dPrice, dVol, nQtd, nBuyAgent, nSellAgent, nTradeType, bEdit)` | §3.2 L2740, L3331 | Trade real-time |
| `TConnectorTradeCallback` (V2) | `(a_Asset, a_pTrade: Pointer, a_nFlags: Cardinal)` | §3.2 L3243 | Use `TranslateTrade` para desempacotar |
| `TNewDailyCallback` | 19 args (open/high/low/close/vol/etc.) | §3.2 L2762, L3376 | Diário |
| `TPriceBookCallback`/V2 | (vários) — **DEPRECIADO** → use PriceDepth | §3.2 L2802, L2822 | — |
| `TOfferBookCallback`/V2 | 16 args (V2 com Int64 nQtd) | §3.2 L2841, L2875 | Livro de ofertas |
| `TConnectorPriceDepthCallback` | `(a_AssetID, a_Side: Byte, a_nPosition, a_UpdateType: Byte)` | §3.2 L3250 | Livro de preços novo |
| `TTinyBookCallback` | `(rAssetID, dPrice, nQtd, nSide)` | §3.2 L3022, L3759 | Top of book |
| `THistoryTradeCallback` (V1) | mesma de TNewTradeCallback | §3.2 L3002, L3730 | Trades históricos |
| `THistoryTradeCallbackV2` | usa TConnectorTradeCallback; flag `TC_LAST_PACKET` indica fim | §3.2 L1912 | V2 |
| `TInvalidTickerCallback` | `(AssetID)` | §3.2 L3098, L4095 | Ticker inválido |
| `TChangeStateTicker` | `(rAssetID, pwcDate, nState)` | §3.2 L3093, L4224 | Mudança fase pregão |
| `TChangeCotation` | `(rAssetID, pwcDate, nTradeNumber, dPrice)` | §3.2 L3144, L4208 | — |
| `TAdjustHistoryCallback`/V2 | 8/9 args | §3.2 L3103, L3121 | V2 inclui flags + dMult |
| `TTheoreticalPriceCallback` | `(rAssetID, dPrice, nQtd: Int64)` | §3.2 L3136, L4102 | Leilão |
| `TAccountCallback` | (legado) | §3.2 L2914 | Use só com DLLInitializeLogin |
| `TAssetListCallback` | `(rAssetID, pwcName)` | §3.2 L3032, L3871 | — |
| `TAssetListInfoCallback`/V2 | 12/15 args | §3.2 L3035, L3061 | V2 inclui setor/subSetor/segmento |
| `TOrderChangeCallback`/V2 | 17/22 args | §3.2 L2933, L3194 | V2 inclui Validity, dates |
| `THistoryCallback`/V2 | 16/20 args | §3.2 L2968, L3154 | Hist de ordens |
| `TConnectorOrderCallback` | `(a_OrderID: TConnectorOrderIdentifier)` | §3.2 L3233 | — |
| `TConnectorAccountCallback` | `(a_AccountID: TConnectorAccountIdentifier)` | §3.2 L3238 | — |
| `TConnectorAssetPositionListCallback` | `(AccountID, AssetID, EventID: Int64)` | §3.2 L2909 | — |
| `TConnectorBrokerAccountListCallback` | `(BrokerID, Changed: Cardinal)` | §3.2 L2924, L4352 | — |
| `TConnectorBrokerSubAccountListCallback` | `(a_AccountID)` | §3.2 L2928, L4361 | — |
| `TConnectorTradingMessageResultCallback` | `(a_pResult: PConnectorTradingMessageResult)` | §3.2 L3262 | Resultado de envio ordem |
| `TConnectorEnumerateOrdersProc` | `(a_Order, a_Param: LPARAM): BOOL` | §3 L794 | Enumerator |

### 3.2 Ordem de chegada / thread

- **Todos** os callbacks chegam na **mesma** thread (`ConnectorThread`), serializados em uma **fila única interna** (manual §4 L4382).
- Processamento demorado em qualquer callback **bloqueia toda a fila** (logs, livros, trades, states param de chegar).
- **Padrão obrigatório:** callback faz APENAS `queue.put_nowait(...)` e retorna em <100µs.

---

### 3.3 SetXxxCallback signatures canônicas (14 callbacks registrados via `Set*`)

**Contexto (Q-DRIFT-09, 2026-05-04):** após Q-DRIFT-05 corrigir os Noop slots de `DLLInitializeMarketLogin`, smoke 5 ainda falhou com **múltiplas Access Violations + 1 Stack Overflow** durante `wait_market_connected`. Estado chega `LOGIN_OK` + `MARKET_LOGIN`, mas **DLL crasha** ao invocar algum dos 14 NoopCallback registrados via `SetXxx`. Hipótese forte: **signatures dos 14 NoopCallbacks divergem da forma esperada pela DLL** (mesmo bug-class de Q-DRIFT-05, agora nos Set callbacks).

Esta seção é a **referência canônica auditada** das signatures que `profitdll/Exemplo Python/main.py` registra nas linhas L745–L761. **Toda signature foi extraída literalmente do exemplo oficial Nelogica.**

#### Tabela canônica — 14 callbacks `SetXxx`

| # | Função `Set*` registrada | Signature `WINFUNCTYPE` (literal do exemplo) | Args (nomes) | Origem `main.py` | Manual ref |
|---|--------------------------|-----------------------------------------------|--------------|------------------|------------|
| 1 | `SetAssetListCallback` | `WINFUNCTYPE(None, TAssetID, c_wchar_p)` | `(assetId, strName)` | L440-443 | §3.2 L3032, L3871 |
| 2 | `SetAdjustHistoryCallbackV2` | `WINFUNCTYPE(None, TAssetID, c_double, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_uint, c_double)` | `(assetId, value, strType, strObserv, dtAjuste, dtDelib, dtPagamento, nFlags, dMult)` | L445-448 | §3.2 L3121 |
| 3 | `SetAssetListInfoCallback` | `WINFUNCTYPE(None, TAssetID, c_wchar_p, c_wchar_p, c_int, c_int, c_int, c_int, c_int, c_double, c_double, c_wchar_p, c_wchar_p)` | `(assetId, strName, strDescription, iMinOrdQtd, iMaxOrdQtd, iLote, iSecurityType, iSecuritySubType, dMinPriceInc, dContractMult, strValidDate, strISIN)` | L450-455 | §3.2 L3035 |
| 4 | `SetAssetListInfoCallbackV2` | `WINFUNCTYPE(None, TAssetID, c_wchar_p, c_wchar_p, c_int, c_int, c_int, c_int, c_int, c_double, c_double, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p)` | `(assetId, strName, strDescription, iMinOrdQtd, iMaxOrdQtd, iLote, iSecurityType, iSecuritySubType, dMinPriceInc, dContractMult, strValidDate, strISIN, strSetor, strSubSetor, strSegmento)` | L457-463 | §3.2 L3061 |
| 5 | `SetOfferBookCallbackV2` | `WINFUNCTYPE(None, TAssetID, c_int, c_int, c_int, c_int, c_int, c_longlong, c_double, c_int, c_int, c_int, c_int, c_int, c_wchar_p, POINTER(c_ubyte), POINTER(c_ubyte))` | `(assetId, nAction, nPosition, Side, nQtd, nAgent, nOfferID, sPrice, bHasPrice, bHasQtd, bHasDate, bHasOfferID, bHasAgent, date, pArraySell, pArrayBuy)` — **16 args** | L391-432 | §3.2 L2875 |
| 6 | `SetOrderCallback` | `WINFUNCTYPE(None, TConnectorOrderIdentifier)` | `(orderId)` | L465-467 | §3.2 L3233 |
| 7 | `SetOrderHistoryCallback` | `WINFUNCTYPE(None, TConnectorAccountIdentifier)` | `(accountId)` | L487-489 | §3.2 L3194 (V2 history) |
| 8 | `SetInvalidTickerCallback` | `WINFUNCTYPE(None, TConnectorAssetIdentifier)` | `(assetID)` | L491-493 | §3.2 L3098, L4095 |
| 9 | `SetTradeCallbackV2` | `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)` | `(assetId, pTrade, flags)` — `pTrade` é handle p/ `TranslateTrade` | L324-333 | §3.2 L3243 |
| 10 | `SetAssetPositionListCallback` | `WINFUNCTYPE(None, TConnectorAccountIdentifier, TConnectorAssetIdentifier, c_long)` | `(accountId, asset, LastEvent)` | L507-521 | §3.2 L2909 |
| 11 | `SetBrokerAccountListChangedCallback` | `WINFUNCTYPE(None, c_int, c_int)` | `(BrokerID, HasChange)` | L523-536 | §3.2 L2924, L4352 |
| 12 | `SetBrokerSubAccountListChangedCallback` | `WINFUNCTYPE(None, TConnectorAccountIdentifier)` | `(accountId)` | L538-553 | §3.2 L2928, L4361 |
| 13 | `SetPriceDepthCallback` | `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_ubyte, c_int, c_ubyte)` | `(assetId, side, position, updateType)` | L253-314 | §3.2 L3250 |
| 14 | `SetTradingMessageResultCallback` | `WINFUNCTYPE(None, POINTER(TConnectorTradingMessageResult))` | `(a_Result)` — pointer, NÃO struct por valor | L316-321 | §3.2 L3262 |

> **Confiança:** todas as 14 signatures são **EXATAS** (extraídas literalmente do exemplo oficial). **Zero `OPEN`** nesta tabela.

#### Estatística de tipos no primeiro arg

| Família do primeiro arg | Callbacks | Implicação ctypes |
|--------------------------|-----------|-------------------|
| `TAssetID` por valor (struct legado, `profitTypes.py` L293-296) | 1, 2, 3, 4, 5 | 5 callbacks. **NUNCA** expandir em `(c_wchar_p, c_wchar_p, c_int)` (mesmo bug Q-DRIFT-05). |
| `TConnectorAssetIdentifier` por valor (struct V2, `profitTypes.py` L88-94) | 8, 9, 13 | 3 callbacks. Idem regra struct-by-value. |
| `TConnectorAccountIdentifier` por valor (`profitTypes.py` L68-75) | 7, 10, 12 | 3 callbacks (10 também tem TConnectorAssetIdentifier no 2º arg). |
| `TConnectorOrderIdentifier` por valor | 6 | 1 callback. |
| `POINTER(TConnectorTradingMessageResult)` | 14 | 1 callback. **Pointer**, não struct por valor. |
| Primitivos (`c_int, c_int`) | 11 | 1 callback. Sem struct. |

#### Pegadinhas observadas (auditoria 2026-05-04)

1. **Callback #5 `OfferBookCallbackV2` tem 16 args.** Erro mais provável: declarar com 13 ou 14 args (esquecer pArraySell/pArrayBuy). Ambos são `POINTER(c_ubyte)` — não `POINTER(c_int)` apesar do nome do campo na struct `TOfferBookCallback` ser `pArraySell: POINTER(c_int)`. **A signature do callback usa `POINTER(c_ubyte)`** (`main.py` L392).
2. **Callback #2 `AdjustHistoryCallbackV2` tem 9 args** com 5 `c_wchar_p` consecutivos no meio (strType, strObserv, dtAjuste, dtDelib, dtPagamento). Confundir um por `c_int` desalinha o stack.
3. **Callback #9 `TradeCallbackV2`:** o pointer `pTrade` é declarado como `c_size_t` no exemplo (não `POINTER(TConnectorTrade)` direto). Isso permite passar para `TranslateTrade(handle, byref(struct))` — handle é opaco até traduzir. **NÃO confundir com `TConnectorTrade` por valor.**
4. **Callback #14 `TradingMessageResultCallback`:** único caso de **POINTER(struct)** entre os 14 (versus struct por valor). Já registrado corretamente via `TConnectorTradingMessageResultCallback = WINFUNCTYPE(None, POINTER(TConnectorTradingMessageResult))` em `profitTypes.py` L453-456.
5. **Callback #11 `BrokerAccountListChangedCallback`:** dois `c_int` puros, sem struct. Mais simples de todos.
6. **Tipos `c_long` vs `c_int`:** em Win64 ambos são 32-bit, mas o exemplo distingue: callbacks #7, #10 e o enumerator usam `c_long`; outros usam `c_int`. **Manter literal o exemplo.**

#### Argtypes/restype das funções `SetXxx`

O exemplo oficial **NÃO configura argtypes/restype** para as funções `SetXxx` em `profit_dll.py` — elas usam o default do ctypes (que aceita o callback `WINFUNCTYPE` como argumento). Isso funciona porque ctypes detecta a signature do callback no momento da chamada `dll.SetXxxCallback(my_cb)`. **Não é necessário** configurar `dll.SetTradeCallbackV2.argtypes = [...]`.

> ⚠️ **Q-DRIFT-08 ainda se aplica** às funções de query (`TranslateTrade`, `GetHistoryTrades`, etc.) — apenas `SetXxx` é exceção segura.

#### Refs cruzadas

- Q-DRIFT-05 — bug class "TAssetID expandido em primitivos" nos Noop slots de `DLLInitializeMarketLogin`. Mesma classe agora suspeita nos `SetXxx` (Q-DRIFT-09).
- Q-DRIFT-06 — refuta Q11-E ("JAMAIS passar None"). Implica que **passar `None` em `SetXxx` não-críticos pode ser MAIS SEGURO que NoopCallback errado**. Validar empiricamente.
- Q-DRIFT-09 (NEW) — registra hipótese atual sobre access violations no smoke 5.

---

## 4. Uso & Threading

**Manual §4 linha 4382 — regras oficiais:**
1. Callbacks executam em ConnectorThread (única thread DLL → cliente).
2. Fila interna única — processamento lento atrasa tudo.
3. **Funções da DLL NÃO devem ser chamadas dentro de callback** (Q06-V).
4. Convenção stdcall (`WINFUNCTYPE`).

**Regra ctypes (não no manual mas obrigatória):**
- `_cb_refs: list = []` global retém os `WINFUNCTYPE`-wrapped objects para impedir GC. Sem isso, GC libera o objeto e a DLL crasha ao chamar callback (Q07-V).

**Linkagem (manual §4):**
- DLL principal: `ProfitDLL.dll` (Win64 ou Win32 conforme arquitetura)
- Companions: várias `.dll` na mesma pasta + arquivos `.dat` (lista canônica em `profitdll/DLLs/Win64/`).
- **Ausência de companion** causa erro críptico do Windows loader. Validar antes de `WinDLL()` via `verify_dll_companions()` (Story 1.2 AC12).

---

## 5. Códigos de erro

Códigos `NL_*` são `int` retornados por funções (negativos = erro, 0 ou positivo = sucesso/ID). Lista canônica em `profitTypes.py`. Categorias principais (manual §3 "Códigos de erro"):

| Faixa | Categoria | Exemplos |
|-------|-----------|----------|
| `NL_OK` (0) | sucesso | — |
| `NL_INTERNAL_ERROR` | interno DLL | `NL_INVALID_ARGS`, `NL_NOT_INITIALIZED`, `NL_INVALID_HANDLE` |
| `NL_LICENSE_*` | autenticação/licença | `NL_LICENSE_NOT_FOUND`, `NL_LICENSE_BLOCKED`, `NL_LICENSE_EXPIRED` |
| `NL_SUBSCRIBE_*` | subscriptions | `NL_SUBSCRIBE_INVALID_TICKER`, `NL_EXCHANGE_UNKNOWN` (Q05-V) |
| `NL_HISTORY_*` | histórico | `NL_HISTORY_TIMEOUT`, `NL_HISTORY_NO_DATA` |
| `NL_ORDER_*` | trading | `NL_ORDER_REJECTED`, `NL_ORDER_INVALID_QTY` |
| `NL_QUEUE_FULL` | fila interna DLL cheia | sintoma de consumer lento (Q15-OPEN) |
| `cosTimeout` | timeout em conexão | manual §3.1 |

> **Decode obrigatório** via `dll/errors.py decode_nl_error(code) -> NLError(name, message)`. Mapa completo gerado a partir de `profitTypes.py`.

---

## 6. Sequência canônica de inicialização

**Manual §3.2 linha 3317-3329** documenta os 4 conn_types e seus result codes esperados durante o boot:

| conn_type | Nome | result esperado | Significado |
|-----------|------|----------------|-------------|
| `0` | `LOGIN` | `0` (CONNECTED) | login OK |
| `1` | `ROTEAMENTO` | `2` (variável) | roteamento estabelecido |
| `2` | `MARKET_DATA` | `4` (`MARKET_CONNECTED`) **OU** `2` (`MARKET_WAITING`) [Q10-AMB / Q-AMB-01] | market data conectado |
| `3` | `MARKET_LOGIN` | `0` | login market OK |

**Tabela completa de results para `conn_type=2 MARKET_DATA` (manual p.13/55):**

| result | Constante | Significado |
|--------|-----------|-------------|
| `0` | `MARKET_DISCONNECTED` | Desconectado do servidor de market data |
| `1` | `MARKET_CONNECTING` | **Conectando ao servidor** (estado de transição — DLL ainda em handshake) |
| `2` | `MARKET_WAITING` | Esperando conexão (Q10-AMB; aceito empiricamente como "pronto") |
| `3` | `MARKET_NOT_LOGGED` | Não logado ao servidor de market data |
| `4` | `MARKET_CONNECTED` | **Conectado ao market data** (único valor "correto" pelo manual p.55) |

> ⚠️ **Q-DRIFT-02 (corrigido 2026-05-04):** se sua DLL fica preso em `(2, 1)` MARKET_CONNECTING por minutos sem evoluir para `(2, 4)`, **NÃO é pré-requisito de ProfitChart concorrente** (hipótese refutada pelo usuário). Causa raiz real é signatures incorretas dos NoopCallback no wrapper — ver Q-DRIFT-05 + nota crítica TAssetID em §3.1.

**Decisão Story 1.2 AC5:** aceitar **ambos** `2` e `4` para `conn_type=2` como market data conectado. Logar qual veio com alias resolvido (`MARKET_WAITING` vs `MARKET_CONNECTED`).

**Sequência típica observada (whale-detector v2):**
```
(0, 0)  →  LOGIN connected
(1, 2)  →  ROTEAMENTO connected
(2, 4)  →  MARKET_DATA → MARKET_CONNECTED  [ou (2, 2) → MARKET_WAITING]
(3, 0)  →  MARKET_LOGIN OK
```

Após `(2, 4)` ou `(2, 2)`, market data está pronto para `SubscribeTicker` / `GetHistoryTrades`.

---

## 7. Padrão canônico de uso

```python
# 1. Verificar companions
missing = verify_dll_companions(dll_path)
if missing:
    raise DLLInitError(-1, "COMPANIONS_MISSING", str(missing))

# 2. Carregar DLL
dll = WinDLL(str(dll_path))

# 3. Configurar argtypes/restype (reuse de profit_dll.py)
configure_argtypes(dll)

# 4. SILENCIAR log nativo ANTES do init
dll.SetEnabledLogToDebug(0)

# 5. Construir SOMENTE callbacks reais necessários — exemplo oficial Nelogica
#    `profitdll/Exemplo Python/main.py` L742-743 passa `None` em 4 dos 8 slots
#    de DLLInitializeMarketLogin tranquilamente. (Q-DRIFT-06 refuta Q11-E por
#    leitura do exemplo; Q-DRIFT-11 confirma empiricamente via probe — wrapper
#    com NoopCallback nestes mesmos slots trava em result=1 por 600s+, probe
#    com None conecta em 1.82–2.43s.)
state_cb = register_state_callback(state_queue)  # appended to _cb_refs

# 6. Init seguindo EXEMPLO OFICIAL — None nos slots não-usados
#    Verified by probe 2026-05-04 (`scripts/probe_init.py` L222-256 — conecta
#    em 1.82s + 2.43s passando None nos slots 4/6/7/8 abaixo).
ret = dll.DLLInitializeMarketLogin(
    c_wchar_p(key), c_wchar_p(user), c_wchar_p(pwd),
    state_cb,
    None,  # slot 5 — trade V1 (use SetTradeCallbackV2 depois se necessário)
    None,  # slot 6 — daily
    None,  # slot 7 — priceBook (DEPRECIADO; use SetPriceDepthCallback)
    None,  # slot 8 — offerBook V1
    None,  # slot 9 — histTrade V1 (use SetHistoryTradeCallbackV2 depois)
    None,  # slot 10 — progress
    None,  # slot 11 — tinyBook
)
# IMPORTANTE: NÃO usar Noop nestes slots (Q-DRIFT-11 — bloqueia ConnectorThread
# durante o handshake do MARKET_DATA, impede transição (2,1) → (2,4)).
# Se mesmo assim quiser Noop em algum slot, signatures DEVEM espelhar EXATAMENTE
# `Exemplo Python/main.py` (TAssetID por valor, NÃO expandir em c_wchar_p × 2 + c_int).
# Ver Q-DRIFT-05 + Q-DRIFT-11 para detalhes.
if ret < 0:
    raise DLLInitError(ret, *decode_nl_error(ret))

# 7. Drenar state queue em thread separada (NÃO no callback)
while True:
    conn_type, result = state_queue.get(timeout=remaining)
    if conn_type == MARKET_DATA and result in (MARKET_WAITING, MARKET_CONNECTED):
        break  # connected!

# 8. Para CADA chunk de download histórico (Q-DRIFT-07 — SubscribeTicker é PRÉ-REQUISITO):
ret = dll.SubscribeTicker(c_wchar_p(symbol), c_wchar_p(exchange))  # exchange = 'F' ou 'B'
assert ret >= 0
dll.SetHistoryTradeCallbackV2(history_cb)
dll.GetHistoryTrades(symbol, exchange, dt_start_str, dt_end_str)
# ... drenar callbacks em IngestorThread, chamar TranslateTrade FORA do callback ...
dll.UnsubscribeTicker(c_wchar_p(symbol), c_wchar_p(exchange))

# 9. Finalize: tenta DLLFinalize (manual §4) → fallback Finalize (Q09-AMB)
try:
    dll.DLLFinalize()
except AttributeError:
    dll.Finalize()
# NÃO _cb_refs.clear() — ConnectorThread ainda pode referenciar
```

**Regra absoluta no callback:**
```python
def state_callback(conn_type, result):
    state_queue.put_nowait((conn_type, result))  # SÓ ISSO
    # PROIBIDO: log, print, dll.foo(), self.bar(), file I/O, sleep, etc.
```

---

## 8. Versões da DLL

Mudanças notáveis (ordem reversa cronológica) — `agents/profitdll-specialist.md` `expertise.manual_changelog_summary`:

| Versão | Mudanças |
|--------|----------|
| **4.0.0.34** | Bug fixes: timeout em send order, revalidação de ativos, livro de preços compra |
| **4.0.0.31** | Modernização do livro de preços: `TConnectorPriceGroup`, `SubscribePriceDepth`, `SetPriceDepthCallback`, `GetPriceGroup`, `GetPriceDepthSideCount`. `SubscribePriceBook` agora **DEPRECIADA**. |
| **4.0.0.30** | `AccountType` adicionado em `TConnectorTradingAccountOut` |
| **4.0.0.28** | Iteração sobre ativos (`EnumerateAllPositionAssets`); listas de contas/subcontas por broker (`GetAccountCountByBroker`, `GetAccountsByBroker`); `EventID` em `TConnectorTradingAccountPosition`, `TConnectorOrder`, `TConnectorOrderOut` |
| **4.0.0.24** | Resolução de nomes de agentes: `GetAgentNameLength` + `GetAgentName` (substituem `GetAgentNameByID` que vira **DEPRECIADA**). Q14-E: length first. |
| **4.0.0.20** | Callbacks **V2** de trade: `SetTradeCallbackV2`, `SetHistoryTradeCallbackV2`, `TranslateTrade`. Histórico de ordens aprimorado: `SetOrderHistoryCallback`, `HasOrdersInInterval`, `EnumerateOrdersByInterval`, `EnumerateAllOrders` |
| **4.0.0.18** | Introdução de `SendOrder` V1 com enums novos: `cotMarket=1`, `cotLimit=2`, `cotStopLimit=4`; `cosBuy=1`, `cosSell=2` (anteriores: `cosBuy=0`, `cosSell=1` — quebra de compat documentada no manual L875/L882) |

**Versão alvo do data-downloader V1:** **4.0.0.34** (mais recente documentada). Versão real exposta em runtime via `ProfitDLL.dll_version` (Story 1.2 AC13) e gravada em metadata Parquet por Sol (H19).

---

## WDO historical data range

**Descoberto:** 2026-05-26 (Story 4.32 — backfill WDOFUT 2013-2017)

| Range observado | Estado em 2026-05-26 |
|---|---|
| **2013-01-02 → 2017-01-30** | ✅ acessível (iter 4/5 da Story 4.32, ~988 chunks baixados) |
| **2017-01-31 → 2017-12-31** | ❌ inacessível (~225 dias úteis — Q-DRIFT-41-NELO) |
| **2018-01-02 → 2026-05-25** | ✅ acessível (Story 4.20 + Run 1 — 2083 dias) |

**Earliest empirical date (probe Story 4.32 T4):** `2013-01-02` retornou trades válidos (1,894 trades em ~10s). ProfitDLL aceita queries para essa data e mais antigas — não foi probado abaixo de 2013-01-02. **Manual silencioso sobre data mínima absoluta.**

**Cutoff observado mid-run (Q-DRIFT-41-NELO):** 2017-01-31 parou de retornar dados ~9h após o começo do backfill. Comportamento: `NL_OK` + zero trades + zero progress + zero `TC_LAST_PACKET`. Mesmo padrão para 2017-06-01 após 1h cooldown. **Refutada** hipótese rolling-window contínua (cutoff saltou 4 anos em 9h, não 1 dia em 25h).

**Hipótese (Nelo, 2026-05-26):** backend Nelogica rotaciona snapshots históricos em **steps discretos por símbolo** (provavelmente fronteiras trimestrais/semestrais). Não é janela rolante por wall-clock. Próxima rotação pode reabrir 2017-Fev-Dec — ou pode empurrar 2018 para fora. Comportamento opaco; canal comercial (corretora → Nelogica) é única fonte autoritativa.

**Latências observadas (típicas, conta atual em 2026-05-25/26):**

| Cenário | Latência | Trades típicos |
|---|---|---|
| Dia recente (2026-05-25) | ~30-50s | 300k+ |
| Dia 2018-2022 (volume médio-alto) | ~30-90s | 200k-700k |
| Dia 2014-2016 (volume médio) | ~10-30s | 50k-200k |
| Dia 2013 (volume baixo) | ~5-15s | 1k-10k |
| Dia inacessível (Q-DRIFT-41) | 30min silent timeout | 0 |

**Mitigação:** ver [Q-DRIFT-41-NELO em QUIRKS.md](./QUIRKS.md#q-drift-41-nelo) — workaround tactical (fail-fast 120s) + operational (contatar corretora).

---

## Manutenção

- **Atualizar este arquivo** quando: (a) novo quirk descoberto, (b) nova versão da DLL liberada, (c) divergência manual-vs-prática resolvida.
- **Comandos Nelo:** `*knowledge-doc` (regenera/atualiza este arquivo); `*manual --section X` (consulta seção crua).
- **Quirks separados** em [`QUIRKS.md`](./QUIRKS.md). Aqui só ficam referências `[Qxx-S]`.
- **Perguntas abertas** em [`OPEN_QUESTIONS_RESPONSES.md`](./OPEN_QUESTIONS_RESPONSES.md).

— Nelo, guardião da DLL 🗝️
