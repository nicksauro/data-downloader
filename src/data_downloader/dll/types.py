"""data_downloader.dll.types — Mirror tipado dos tipos da ProfitDLL.

Owner: Dex (impl) | Audit: Nelo. Story 1.2.

Espelha apenas o subconjunto de ``profitdll/Exemplo Python/profitTypes.py``
que o squad usa em V1 (DLLInitializeMarketLogin + state callback). Tipos
adicionais (TConnectorTrade V2, TOfferBookCallback, etc.) entram em
stories subsequentes (1.3 history, 1.5 live trade, etc.) **conforme uso**
— não preencher proativamente (lei "no invention" / Constitution Art. IV).

Definições canônicas:

- ``TStateCallback`` — ``WINFUNCTYPE(None, c_int, c_int)`` (manual §3.2 L2738).
- Constantes ``conn_type``: LOGIN=0, ROTEAMENTO=1, MARKET_DATA=2, MARKET_LOGIN=3.
- Constantes ``result``: CONNECTED=0, MARKET_WAITING=2, MARKET_CONNECTED=4
  (Q-AMB-01 / AC5 — aceitar ambos para conn_type=2).
- Signatures dos demais 10 slots de ``DLLInitializeMarketLogin`` —
  cada uma definida como ``WINFUNCTYPE`` para construir ``NoopCallback``
  via ``callbacks.make_noop_callback`` (Q11-E / AC2 — JAMAIS passar None).

Plataforma: ``WINFUNCTYPE`` é stdcall e só existe em Windows (``ctypes`` em
Linux/Mac não expõe). Em testes mock fora de Windows, importar este módulo é
seguro porque definimos um shim ``WINFUNCTYPE = CFUNCTYPE`` (signature
compatível para mocking — execução real só ocorre em Win64).
"""

from __future__ import annotations

import sys
from ctypes import POINTER, Structure, c_long, c_size_t, c_ubyte, c_ushort
from typing import ClassVar, Final

# ``WINFUNCTYPE`` (stdcall) só existe em Windows. Em outras plataformas
# fazemos shim para ``CFUNCTYPE`` para permitir importação + mocks (testes
# unit em Linux/Mac). A execução REAL do wrapper é gated em
# ``ProfitDLL.initialize_market_only`` que raises UNSUPPORTED_PLATFORM.
if sys.platform == "win32":
    from ctypes import (
        WINFUNCTYPE,
        c_double,
        c_int,
        c_int64,
        c_longlong,
        c_uint,
        c_wchar_p,
    )
else:  # pragma: no cover — shim só ativo em testes não-Windows
    from ctypes import (
        CFUNCTYPE as WINFUNCTYPE,
    )
    from ctypes import (
        c_double,
        c_int,
        c_int64,
        c_longlong,
        c_uint,
        c_wchar_p,
    )

# =====================================================================
# Connection state codes (manual §3.2 linhas 3317-3329)
# =====================================================================

# conn_type — 1º arg do TStateCallback
LOGIN: Final[int] = 0
ROTEAMENTO: Final[int] = 1
MARKET_DATA: Final[int] = 2
MARKET_LOGIN: Final[int] = 3

# result — 2º arg do TStateCallback (semântica varia por conn_type)
CONNECTED: Final[int] = 0  # LOGIN=0/MARKET_LOGIN=0 → conectado
MARKET_WAITING: Final[int] = 2  # MARKET_DATA=2 — aceito (Q-AMB-01)
MARKET_CONNECTED: Final[int] = 4  # MARKET_DATA=4 — manual canônico

# Tipo do conn_type/result — usado por wrapper.wait_market_connected ao
# desempacotar tuplas da fila.
StatePair = tuple[int, int]


# Mapa (conn_type, result) → alias humano para logger structlog (AC8).
# Não cobre todos os pares possíveis — fallback resolvido em
# ``wrapper._resolve_state_alias`` para casos não mapeados.
STATE_CODE_ALIAS: Final[dict[StatePair, str]] = {
    (LOGIN, CONNECTED): "LOGIN_CONNECTED",
    (ROTEAMENTO, MARKET_WAITING): "ROTEAMENTO_CONNECTED",  # result=2 = "estabelecido"
    (MARKET_DATA, MARKET_WAITING): "MARKET_WAITING",
    (MARKET_DATA, MARKET_CONNECTED): "MARKET_CONNECTED",
    (MARKET_LOGIN, CONNECTED): "MARKET_LOGIN_OK",
}

# Mapa conn_type → nome humano (fallback para STATE_CODE_ALIAS quando o
# par exato não está mapeado).
CONN_TYPE_NAME: Final[dict[int, str]] = {
    LOGIN: "LOGIN",
    ROTEAMENTO: "ROTEAMENTO",
    MARKET_DATA: "MARKET_DATA",
    MARKET_LOGIN: "MARKET_LOGIN",
}


# =====================================================================
# WINFUNCTYPE definitions — 11 slots de DLLInitializeMarketLogin
# =====================================================================
# Manual §3.1 (linha ~4382): ``DLLInitializeMarketLogin`` recebe 11 args:
#   key, user, password, state, trade, daily, priceBook, offerBook,
#   histTrade, progress, tinyBook
#
# Cada callback slot é um ``WINFUNCTYPE`` distinto. Esta story (1.2) usa
# APENAS state ativo; demais 7 viram NoopCallback (Q11-E / AC2 — sem None).
# Stories futuras (1.3 histTrade+progress) substituem slots via
# ``Set*Callback`` posteriores (NÃO durante init).
#
# Signatures derivadas de profitTypes.py (Nelogica) e manual §3.2.
#
# CORREÇÃO Q-DRIFT-05 (Story 1.7b-followup, Nelo): o exemplo oficial
# Nelogica (``profitdll/Exemplo Python/main.py``) passa ``TAssetID``
# (struct de 3 fields) POR VALOR no PRIMEIRO arg dos callbacks V1
# (newDailyCallback L346, tinyBookCallBack L336, progressCallBack L243,
# tradeCallback live L324). EXPANDIR o struct em ``(c_wchar_p, c_wchar_p,
# c_int)`` desalinha o stack frame stdcall e causa silent corruption na
# ConnectorThread (smoke 2026-05-04 root-cause). Por isso ``class TAssetID``
# é declarada AQUI, antes das signatures, para que cada signature use
# exatamente o tipo struct conforme o exemplo.
# =====================================================================


class TAssetID(Structure):
    """V1 asset identifier — mirror de ``profitTypes.py`` L293-296.

    Usado em signatures de callbacks V1 (assetList*, daily, tinyBook,
    progress, trade live, offerBook, etc.). Passado POR VALOR — JAMAIS
    expandir em ``(c_wchar_p, c_wchar_p, c_int)`` no WINFUNCTYPE
    (Q-DRIFT-05).
    """

    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("ticker", c_wchar_p),
        ("bolsa", c_wchar_p),
        ("feed", c_int),
    ]


# State callback — manual §3.2 L2738 — assinatura EXATA (sem TAssetID).
TStateCallback = WINFUNCTYPE(None, c_int, c_int)
"""``(nConnStateType: int, nResult: int) -> None`` — manual §3.2 L2738."""

# Trade callback (V1) — slot 5 do init. Mirror de TNewTradeCallback
# (profitTypes.py L325-335). TAssetID por valor no 1º arg (Q-DRIFT-05).
TTradeCallback = WINFUNCTYPE(
    None,
    TAssetID,  # assetId (passado por valor — NÃO expandir)
    c_wchar_p,  # date
    c_uint,  # tradeNumber
    c_double,  # price
    c_double,  # vol
    c_int,  # qtd
    c_int,  # buyAgent
    c_int,  # sellAgent
    c_int,  # tradeType
    c_int,  # bIsEdit
)

# Daily callback — slot 6 do init. Mirror de @WINFUNCTYPE em main.py L346
# (TAssetID + 18 args primitivos).
TDailyCallback = WINFUNCTYPE(
    None,
    TAssetID,  # assetID (passado por valor)
    c_wchar_p,  # date
    c_double,  # sOpen
    c_double,  # sHigh
    c_double,  # sLow
    c_double,  # sClose
    c_double,  # sVol
    c_double,  # sAjuste
    c_double,  # sMaxLimit
    c_double,  # sMinLimit
    c_double,  # sVolBuyer
    c_double,  # sVolSeller
    c_int,  # nQtd
    c_int,  # nNegocios
    c_int,  # nContratosOpen
    c_int,  # nQtdBuyer
    c_int,  # nQtdSeller
    c_int,  # nNegBuyer
    c_int,  # nNegSeller
)

# Price book callback (DEPRECIADA pelo manual mas mantida no slot do init).
# Mirror de TPriceBookCallback (profitTypes.py L391-400) com TAssetID por valor.
TPriceBookCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_int,  # nAction
    c_int,  # nPosition
    c_int,  # side
    c_int,  # nQtd
    c_int,  # ncount
    c_double,  # sprice
    POINTER(c_int),  # pArraySell
    POINTER(c_int),  # pArrayBuy
)

# Offer book callback — slot 8 do init. Mirror de TOfferBookCallback
# (profitTypes.py L404-420) com TAssetID por valor.
TOfferBookCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_int,  # nAction
    c_int,  # nPosition
    c_int,  # side
    c_int,  # nQtd
    c_int,  # nAgent
    c_longlong,  # nOfferID
    c_double,  # sPrice
    c_int,  # bHasPrice
    c_int,  # bHasQtd
    c_int,  # bHasDate
    c_int,  # bHasOfferId
    c_int,  # bHasAgent
    c_wchar_p,  # date
    POINTER(c_int),  # pArraySell
    POINTER(c_int),  # pArrayBuy
)

# History trade callback (V1) — slot 9 do init. Mesma signature de
# TNewTradeCallback sem ``bIsEdit`` (TNewHistoryCallback L365-374).
THistoryTradeCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,  # date
    c_uint,  # tradeNumber
    c_double,  # price
    c_double,  # vol
    c_int,  # qtd
    c_int,  # buyAgent
    c_int,  # sellAgent
    c_int,  # tradeType
)

# Progress callback — slot 10 do init. main.py L243
# ``@WINFUNCTYPE(None, TAssetID, c_int)``.
TProgressCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_int,  # nProgress (1..100)
)

# Tiny book callback — slot 11 do init. main.py L336
# ``@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)``.
TTinyBookCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_double,  # price
    c_int,  # qtd
    c_int,  # side
)

# Lista canônica das signatures dos 7 slots NÃO-state (em ordem do
# DLLInitializeMarketLogin). Wrapper itera para construir NoopCallbacks.
NOOP_SLOT_SIGNATURES: Final[tuple[type, ...]] = (
    TTradeCallback,
    TDailyCallback,
    TPriceBookCallback,
    TOfferBookCallback,
    THistoryTradeCallback,
    TProgressCallback,
    TTinyBookCallback,
)
"""7 signatures de callbacks NÃO-state usadas em ``DLLInitializeMarketLogin``.

Total de slots = 1 (state) + 7 (estes) = 8 callback slots, mais 3 args
de credencial (key, user, password) = 11 args totais conforme manual §3.1.

Story 1.2 substitui CADA UM destes slots por NoopCallback (Q11-E / AC2 —
``None`` PROIBIDO). Stories futuras (1.3) usam ``Set*Callback`` posteriores
para registrar handlers reais sem re-init (Q08-E — DLL não-idempotente).

Story 1.7b-followup (Q-DRIFT-05): TODAS as 7 signatures usam ``TAssetID``
por valor no 1º arg, alinhado ao exemplo oficial Nelogica (main.py
L243/L324/L336/L346/L391/L435).
"""


# =====================================================================
# Story 1.3 — V2 history download types
# =====================================================================
# Decisão COUNCIL-03: usar ``SetHistoryTradeCallbackV2`` + ``TranslateTrade``.
# - Callback V2 entrega ``(asset, pTrade_handle, flags)`` na ConnectorThread.
# - ``TranslateTrade(pTrade, byref(TConnectorTrade))`` desempacota o struct
#   FORA do callback (em IngestorThread) — lei R3 / manual §4 L4382.
# - Versões V1 (`THistoryTradeCallback` e `TProgressCallback` acima) ficam
#   mantidas para NoopCallback do init slot.
#
# Fonte canônica:
# - profitdll/Exemplo Python/profitTypes.py L56-66 (SystemTime),
#   L88-94 (TConnectorAssetIdentifier), L280-291 (TConnectorTrade)
# - profitdll/Exemplo Python/profit_dll.py L70-71 (TranslateTrade argtypes)
# - profitdll/Exemplo Python/main.py L324-333 (V2 trade callback pattern)
# =====================================================================


class SystemTime(Structure):
    """Mirror Win32 ``SYSTEMTIME`` — campo ``TradeDate`` em ``TConnectorTrade``.

    Campos canônicos (profitTypes.py L56-66). ``wDayOfWeek`` é preenchido
    pela DLL mas IGNORADO no parser de timestamp do squad (R7 — usamos
    apenas ``wYear..wMilliseconds``, BRT naive).
    """

    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("wYear", c_ushort),
        ("wMonth", c_ushort),
        ("wDayOfWeek", c_ushort),
        ("wDay", c_ushort),
        ("wHour", c_ushort),
        ("wMinute", c_ushort),
        ("wSecond", c_ushort),
        ("wMilliseconds", c_ushort),
    ]


class TConnectorAssetIdentifier(Structure):
    """Asset identifier V2 — usado em callbacks V2 (manual §3.2).

    Mirror de ``profitTypes.py`` L88-94. Passado por valor (não pointer)
    no callback V2 — ConnectorThread monta o struct na stack do callback.
    """

    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("Version", c_ubyte),
        ("Ticker", c_wchar_p),
        ("Exchange", c_wchar_p),
        ("FeedType", c_ubyte),
    ]


class TConnectorTrade(Structure):
    """Struct desempacotada por ``TranslateTrade`` (V2 trade — manual §3.2).

    Mirror de ``profitTypes.py`` L280-291. Antes de cada chamada a
    ``TranslateTrade``, ``Version`` deve ser setada para ``0`` pelo caller
    (main.py L328 demonstra). Os demais campos são preenchidos pela DLL.

    - ``TradeDate``: timestamp BRT naive (R7) via ``SystemTime``.
    - ``TradeNumber``: trade_id estável (chave de dedup curta — SCHEMA.md §2.1).
    - ``Price``: preço do trade.
    - ``Quantity``: quantidade negociada (``c_longlong``).
    - ``Volume``: ``Price * Quantity`` (calculado pela DLL).
    - ``BuyAgent`` / ``SellAgent``: IDs de corretora (resolvíveis via
      ``GetAgentName`` — Q14-E, fora do escopo Story 1.3).
    - ``TradeType``: tipo do trade (auction, regular, cross, etc.).
    """

    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("Version", c_ubyte),
        ("TradeDate", SystemTime),
        ("TradeNumber", c_uint),
        ("Price", c_double),
        ("Quantity", c_longlong),
        ("Volume", c_double),
        ("BuyAgent", c_int),
        ("SellAgent", c_int),
        ("TradeType", c_ubyte),
    ]


# Flags do callback V2 (3º arg). Convenção observada (PROFITDLL_KNOWLEDGE.md §3
# + manual §3.2 L1912 cita ``TC_LAST_PACKET``). Bit-fields:
TC_IS_EDIT: Final[int] = 0x01
"""Bit 0: trade é edição (correção) de trade prévio (não inserção nova)."""

TC_LAST_PACKET: Final[int] = 0x02
"""Bit 1: este é o último pacote do download histórico — sinal autoritativo
de fim, complementar ao progress=100 (Q02-E mitigation)."""


# History trade callback V2 — manual §3.2 L1912 + main.py L324 (mesmo padrão
# que tradeCallback live; SetHistoryTradeCallbackV2 reusa a signature).
THistoryTradeCallbackV2 = WINFUNCTYPE(
    None,
    TConnectorAssetIdentifier,  # asset (passado por valor)
    c_size_t,  # pTrade — handle opaco (passar a TranslateTrade)
    c_uint,  # flags (TC_IS_EDIT | TC_LAST_PACKET | ...)
)
"""V2 history trade callback (Story 1.3 / COUNCIL-03).

Callback recebe handle opaco (``c_size_t``) que DEVE ser passado a
``TranslateTrade`` em IngestorThread (FORA do callback — R3). Callback faz
APENAS ``queue.put_nowait((handle, flags))`` — ver
``callbacks.make_history_trade_callback_v2``.
"""


# =====================================================================
# Story 1.7b-followup — 14 default callback signatures (alinhamento Nelogica)
# =====================================================================
# Exemplo oficial (``profitdll/Exemplo Python/main.py`` L745-761) chama 14
# ``Set*Callback`` ANTES de aguardar conexão. Inicialização sem esses
# registros pode deixar slots NULL e impedir o handshake (smoke 2026-05-04
# refutou hipóteses ProfitChart e MARKET_WAITING — restou alinhamento ao
# exemplo como caminho seguro). Cada signature é derivada literalmente do
# decorator ``@WINFUNCTYPE(...)`` da função correspondente em main.py.
#
# Todos os tipos são WINFUNCTYPE — em Linux/Mac shim para CFUNCTYPE
# (definido no topo deste módulo).
# =====================================================================


class TConnectorOrderIdentifier(Structure):
    """Order identifier — mirror de ``profitTypes.py`` L115-120.

    Usado em ``orderCallback`` (main.py L465-467). Passado por valor.
    """

    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("Version", c_ubyte),
        ("LocalOrderID", c_int64),
        ("ClOrderID", c_wchar_p),
    ]


class TConnectorAccountIdentifier(Structure):
    """Account identifier — mirror de ``profitTypes.py`` L68-75.

    Usado em ``orderHistoryCallback``, ``BrokerSubAccountListChangedCallback``
    e ``getAssetsPositionCallback`` (main.py L487, L538, L507). Passado por
    valor.
    """

    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("Version", c_ubyte),
        ("BrokerID", c_int),
        ("AccountID", c_wchar_p),
        ("SubAccountID", c_wchar_p),
        ("Reserved", c_int64),
    ]


# main.py L440 — assetListCallback signature.
TAssetListCallback = WINFUNCTYPE(None, TAssetID, c_wchar_p)

# main.py L445 — adjustHistoryCallbackV2 signature (9 args após TAssetID).
TAdjustHistoryCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_double,  # value
    c_wchar_p,  # strType
    c_wchar_p,  # strObserv
    c_wchar_p,  # dtAjuste
    c_wchar_p,  # dtDelib
    c_wchar_p,  # dtPagamento
    c_uint,  # nFlags
    c_double,  # dMult
)

# main.py L450 — assetListInfoCallback signature (12 args).
TAssetListInfoCallback = WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,  # strName
    c_wchar_p,  # strDescription
    c_int,  # iMinOrdQtd
    c_int,  # iMaxOrdQtd
    c_int,  # iLote
    c_int,  # iSecurityType
    c_int,  # iSecuritySubType
    c_double,  # dMinPriceInc
    c_double,  # dContractMult
    c_wchar_p,  # strValidDate
    c_wchar_p,  # strISIN
)

# main.py L457 — assetListInfoCallbackV2 signature (15 args; +setor/subSetor/segmento).
TAssetListInfoCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_wchar_p,  # strName
    c_wchar_p,  # strDescription
    c_int,  # iMinOrdQtd
    c_int,  # iMaxOrdQtd
    c_int,  # iLote
    c_int,  # iSecurityType
    c_int,  # iSecuritySubType
    c_double,  # dMinPriceInc
    c_double,  # dContractMult
    c_wchar_p,  # strValidDate
    c_wchar_p,  # strISIN
    c_wchar_p,  # strSetor
    c_wchar_p,  # strSubSetor
    c_wchar_p,  # strSegmento
)

# main.py L391 — offerBookCallbackV2 signature (16 args; pArraySell/Buy = POINTER(c_ubyte)).
TOfferBookCallbackV2 = WINFUNCTYPE(
    None,
    TAssetID,
    c_int,  # nAction
    c_int,  # nPosition
    c_int,  # Side
    c_int,  # nQtd
    c_int,  # nAgent
    c_longlong,  # nOfferID
    c_double,  # sPrice
    c_int,  # bHasPrice
    c_int,  # bHasQtd
    c_int,  # bHasDate
    c_int,  # bHasOfferID
    c_int,  # bHasAgent
    c_wchar_p,  # date
    POINTER(c_ubyte),  # pArraySell
    POINTER(c_ubyte),  # pArrayBuy
)

# main.py L465 — orderCallback signature.
TOrderCallback = WINFUNCTYPE(None, TConnectorOrderIdentifier)

# main.py L487 — orderHistoryCallback signature.
TOrderHistoryCallback = WINFUNCTYPE(None, TConnectorAccountIdentifier)

# main.py L491 — invalidAssetCallback signature.
TInvalidTickerCallback = WINFUNCTYPE(None, TConnectorAssetIdentifier)

# main.py L324 — tradeCallback live (V2) signature — mesma de THistoryTradeCallbackV2.
TTradeCallbackV2 = THistoryTradeCallbackV2

# main.py L507 — getAssetsPositionCallback signature.
TAssetPositionListCallback = WINFUNCTYPE(
    None,
    TConnectorAccountIdentifier,
    TConnectorAssetIdentifier,
    c_long,  # LastEvent
)

# main.py L523 — BrokerAccountListChangedCallback signature.
TBrokerAccountListChangedCallback = WINFUNCTYPE(None, c_int, c_int)

# main.py L538 — BrokerSubAccountListChangedCallback signature.
TBrokerSubAccountListChangedCallback = WINFUNCTYPE(None, TConnectorAccountIdentifier)

# main.py L253 — priceDepthCallback signature.
TPriceDepthCallback = WINFUNCTYPE(
    None,
    TConnectorAssetIdentifier,
    c_ubyte,  # side
    c_int,  # position
    c_ubyte,  # updateType
)

# main.py L316 — tradingMessageResultCallback signature
# (POINTER(TConnectorTradingMessageResult)). Para evitar definir struct nova
# (não usada além deste registro), usamos POINTER(c_ubyte) — ctypes aceita
# qualquer ponteiro como POINTER(c_ubyte) para callback que apenas ignora
# o conteúdo (Noop). Nota: alinhamento de chamada (stdcall) depende
# apenas da quantidade/tamanho de args — POINTER é POINTER, conteúdo
# não-importa. TODO se algum dia formos consumir esse callback de verdade:
# definir TConnectorTradingMessageResult Structure (profitTypes.py L312-323).
TTradingMessageResultCallback = WINFUNCTYPE(None, POINTER(c_ubyte))


# Lista canônica das 14 funções `Set*Callback` chamadas pelo exemplo oficial
# ANTES de wait_login (main.py L745-761). Cada entrada é
# ``(method_name, funtype)`` — wrapper itera para registrar Noop em todos.
# Ordem replicada literalmente do exemplo.
DEFAULT_CALLBACK_REGISTRATIONS: Final[tuple[tuple[str, type], ...]] = (
    ("SetAssetListCallback", TAssetListCallback),
    ("SetAdjustHistoryCallbackV2", TAdjustHistoryCallbackV2),
    ("SetAssetListInfoCallback", TAssetListInfoCallback),
    ("SetAssetListInfoCallbackV2", TAssetListInfoCallbackV2),
    ("SetOfferBookCallbackV2", TOfferBookCallbackV2),
    ("SetOrderCallback", TOrderCallback),
    ("SetOrderHistoryCallback", TOrderHistoryCallback),
    ("SetInvalidTickerCallback", TInvalidTickerCallback),
    ("SetTradeCallbackV2", TTradeCallbackV2),
    ("SetAssetPositionListCallback", TAssetPositionListCallback),
    ("SetBrokerAccountListChangedCallback", TBrokerAccountListChangedCallback),
    ("SetBrokerSubAccountListChangedCallback", TBrokerSubAccountListChangedCallback),
    ("SetPriceDepthCallback", TPriceDepthCallback),
    ("SetTradingMessageResultCallback", TTradingMessageResultCallback),
)
"""14 ``Set*Callback`` registrations alinhadas ao exemplo oficial Nelogica.

Fonte canônica: ``profitdll/Exemplo Python/main.py`` L745-761 (chamados
ANTES de ``wait_login``). Cada signature derivada literalmente do
``@WINFUNCTYPE(...)`` da função correspondente em main.py.

Wrapper itera esta lista em ``ProfitDLL._register_default_callbacks``,
registrando NoopCallback em cada slot — todos respeitam R3 (callback faz
no-op explícito). Para registrar handler real depois, caller chama o
método ``Set*`` próprio (ex.: ``set_history_trade_callback_v2``) que
substitui o Noop.
"""
