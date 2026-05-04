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
from ctypes import Structure, c_size_t, c_ubyte, c_ushort
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
# =====================================================================

# State callback — manual §3.2 L2738 — assinatura EXATA.
TStateCallback = WINFUNCTYPE(None, c_int, c_int)
"""``(nConnStateType: int, nResult: int) -> None`` — manual §3.2 L2738."""

# Trade callback (V1) — TNewTradeCallback fields desempacotados.
# Manual §3.2 L2740, L3331. Assinatura compatível com slot 5 do init.
TTradeCallback = WINFUNCTYPE(
    None,
    c_wchar_p,  # ticker (TAssetID.ticker)
    c_wchar_p,  # bolsa (TAssetID.bolsa)
    c_int,  # feed (TAssetID.feed)
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

# Daily callback — TNewDailyCallback (19 fields). Assinatura defensiva
# usando varargs-like (ctypes não tem; expandimos os campos básicos).
# Para Noop, signature exata não importa (no-op consome qualquer args via
# *args), mas WINFUNCTYPE precisa de tipo concreto.
TDailyCallback = WINFUNCTYPE(
    None,
    c_wchar_p,
    c_wchar_p,
    c_int,
    c_wchar_p,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_double,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
)

# Price book callback (DEPRECIADA pelo manual mas mantida no slot do init).
TPriceBookCallback = WINFUNCTYPE(
    None,
    c_wchar_p,
    c_wchar_p,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_double,
)

# Offer book callback — TOfferBookCallback (16 fields). Slot do init.
TOfferBookCallback = WINFUNCTYPE(
    None,
    c_wchar_p,
    c_wchar_p,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int64,
    c_double,
    c_int,
    c_int,
    c_int,
    c_int,
    c_int,
    c_wchar_p,
)

# History trade callback (V1) — mesma signature do TNewTradeCallback sem
# ``bIsEdit`` (manual §3.2 L3002, L3730).
THistoryTradeCallback = WINFUNCTYPE(
    None,
    c_wchar_p,
    c_wchar_p,
    c_int,
    c_wchar_p,
    c_uint,
    c_double,
    c_double,
    c_int,
    c_int,
    c_int,
    c_int,
)

# Progress callback — manual §3.2 L2739, L3750.
TProgressCallback = WINFUNCTYPE(
    None,
    c_wchar_p,  # ticker
    c_wchar_p,  # bolsa
    c_int,  # feed
    c_int,  # nProgress (1..100)
)

# Tiny book callback — TNewTinyBookCallBack (manual §3.2 L3022, L3759).
TTinyBookCallback = WINFUNCTYPE(
    None,
    c_wchar_p,
    c_wchar_p,
    c_int,
    c_double,
    c_int,
    c_int,
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
