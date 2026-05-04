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
from typing import Final

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
