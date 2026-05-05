"""data_downloader.dll.wrapper — ProfitDLL ctypes wrapper (init/finalize).

Owner: Dex (impl) | Audit: Nelo. Story 1.2.

Classe ``ProfitDLL`` — coração do wrapper. Carrega ``ProfitDLL.dll``
(Win64 stdcall), valida companions ANTES do load, silencia o log nativo
da DLL ANTES do init, inicializa em modo market-only com TODOS os 11
callback slots preenchidos (1 state ativo + 7 NoopCallback), drena a
sequência completa de connection states em thread separada, e finaliza
limpamente preferindo ``DLLFinalize`` sobre ``Finalize``.

ACs cobertas (Story 1.2):

- AC1 — surface pública (init/wait/finalize/__enter__/__exit__/dll_version)
- AC2 — 11 callback slots fixos (1 ativo + 7 NoopCallback; sem ``None``)
- AC3 — state callback APENAS enfileira (em ``callbacks.py``)
- AC4 — ``_cb_refs`` global (em ``callbacks.py``); ``finalize()`` NÃO
  limpa
- AC5 — ``wait_market_connected`` aceita ``result`` ∈ ``{2, 4}`` para
  ``conn_type=2`` (Q-AMB-01)
- AC6 — ``finalize()`` tenta ``DLLFinalize`` → fallback ``Finalize`` (Q-AMB-02)
- AC7 — retorno < 0 raises ``DLLInitError``
- AC8 — logging structlog (eventos canônicos)
- AC9 — path resolvido: arg → env ``PROFITDLL_PATH`` → default
- AC11 — ``SetEnabledLogToDebug(0)`` ANTES do init
- AC12 — ``verify_dll_companions`` ANTES de ``WinDLL()``
- AC13 — property ``dll_version`` cacheada
- AC16 — ``Queue(maxsize=1000)`` para state queue

Plataforma: ``ProfitDLL.dll`` é Win64-only. Em Linux/Mac, ``initialize_market_only``
raises ``DLLInitError(UNSUPPORTED_PLATFORM)`` para permitir testes mockados
do wrapper sem DLL real.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from queue import Empty, Queue
from types import TracebackType
from typing import Any, Final

import structlog

from data_downloader.dll.callbacks import make_noop_callback, make_state_callback
from data_downloader.dll.errors import DLLInitError, decode_nl_error
from data_downloader.dll.types import (
    CONN_TYPE_NAME,
    DEFAULT_CALLBACK_REGISTRATIONS,
    MARKET_CONNECTED,
    MARKET_DATA,
    NOOP_SLOT_SIGNATURES,
    STATE_CODE_ALIAS,
    TConnectorTrade,
    TDailyCallback,
    TProgressCallback,
    TradeFields,
    TTinyBookCallback,
)

__all__ = ["DEFAULT_DLL_PATH", "ProfitDLL"]

# Logger structlog canônico (ADR-010). NÃO usar em hot path (R21).
log: structlog.stdlib.BoundLogger = structlog.get_logger("data_downloader.dll")

# Default path relativo ao repo root (resolvido via Path manipulation).
# Override via env ``PROFITDLL_PATH`` ou arg ``dll_path`` (AC9).
# parents[3] = src/data_downloader/dll/wrapper.py → src → data_downloader → dll → wrapper
# Aqui: __file__ = .../src/data_downloader/dll/wrapper.py
#       .parents[0] = dll/
#       .parents[1] = data_downloader/
#       .parents[2] = src/
#       .parents[3] = repo root
DEFAULT_DLL_PATH: Path = (
    Path(__file__).resolve().parents[3] / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll"
)


def _load_verify_dll_companions() -> Any:
    """Carrega ``verify`` de ``scripts/verify-dll-companions.py``.

    Path com hífen impede import normal — usamos ``importlib.util`` para
    carregar como módulo. Cacheado em call-site (chamado uma vez por
    ``initialize_market_only``). Retorna a função ``verify(base_path)``.

    Nota Python 3.12+/3.14: o módulo carregado precisa estar em
    ``sys.modules`` ANTES de ``exec_module`` para que ``@dataclass``
    consiga resolver string annotations (``cls.__module__`` é usado como
    chave em ``sys.modules.get``). Registramos manualmente.
    """
    module_name = "data_downloader_verify_dll_companions"
    if module_name in sys.modules:
        return sys.modules[module_name].verify

    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "verify-dll-companions.py"
    if not script_path.exists():
        # Fallback defensivo — se script foi removido, falha cedo com mensagem
        # clara em vez de stacktrace ctypes críptico mais à frente.
        raise DLLInitError(
            -1,
            "VERIFY_SCRIPT_MISSING",
            f"scripts/verify-dll-companions.py não encontrado: {script_path}",
        )
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise DLLInitError(
            -1,
            "VERIFY_SCRIPT_LOAD_FAILED",
            f"Falha ao carregar spec de {script_path}",
        )
    module = importlib.util.module_from_spec(spec)
    # CRÍTICO: registrar em sys.modules ANTES de exec_module para que
    # @dataclass consiga resolver annotations via cls.__module__.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.verify


class ProfitDLL:
    """Wrapper ctypes da ProfitDLL — modo market-only.

    Lifecycle típico (com context manager):

        >>> with ProfitDLL() as dll:
        ...     dll.initialize_market_only(key, user, password)
        ...     if dll.wait_market_connected(timeout=60):
        ...         # market data pronto; subscribe / GetHistory
        ...         pass

    Threading: a DLL cria sua própria ``ConnectorThread`` interna que dispara
    callbacks. ``wait_market_connected`` drena a fila em outra thread (a do
    caller deste método). Lei R3 / ADR-005 INV-1: callbacks NUNCA chamam a
    DLL de volta — apenas ``put_nowait``.

    Idempotência: ``init → finalize → init`` na mesma sessão Python é
    PROIBIDO (Q08-E / M15). Use 1 instância por processo.
    """

    def __init__(self, dll_path: Path | None = None) -> None:
        """Resolve path da DLL (AC9). NÃO carrega ainda — load em ``initialize_market_only``.

        Ordem de precedência (AC9):
            1. Argumento explícito ``dll_path``.
            2. Env var ``PROFITDLL_PATH``.
            3. Default ``DEFAULT_DLL_PATH``.

        Args:
            dll_path: Path explícito (override env + default).
        """
        env_path = os.getenv("PROFITDLL_PATH")
        # Precedência: arg > env > default. Path é resolvido para absoluto
        # antes do ``WinDLL()`` (Windows loader é sensível a relative paths
        # em alguns contextos — defensivo).
        chosen: str | Path
        if dll_path is not None:
            chosen = dll_path
        elif env_path:
            chosen = env_path
        else:
            chosen = DEFAULT_DLL_PATH
        self._dll_path: Path = Path(chosen).resolve()

        # State (None até initialize_market_only ser chamado com sucesso).
        self._dll: Any | None = None

        # State queue — bounded (AC16). State changes são raras (~unidades
        # por sessão); maxsize=1000 é >>> qualquer cenário realista.
        self._state_queue: Queue[tuple[int, int]] = Queue(maxsize=1000)

        # ``dll_version`` cache (AC13) — preenchido na 1ª chamada à property.
        self._dll_version_cache: str | None = None

        # Story 1.3 — referências defensivas adicionais para callbacks
        # registrados após init (history V2, progress). A factory já appenda
        # em ``callbacks._cb_refs`` (módulo-level, anti-GC global), esta
        # lista é cinto-e-suspensório (custo zero, append-only).
        self._cb_refs: list[Any] = []

        # Q-DRIFT-10 (probe diagnose commit 3ef7699 — 2026-05-05): ProfitDLL
        # precisa que cwd seja a pasta da DLL (``profitdll/DLLs/Win64/``)
        # para localizar companions (libssl, libcrypto), arquivos ``.dat``
        # (ServerAddr, exchangeinfo2, holidays, timezone2) e escrever em
        # subpastas relativas (``Logs/``, ``database/``, ``MarketHours2/``).
        # Sem ``os.chdir`` antes de ``WinDLL(...)`` o handshake do MARKET_DATA
        # trava em ``result=1`` (CONNECTING) e nunca progride. O probe
        # ``scripts/probe_init.py`` (commit 3ef7699) reproduziu conexão em
        # ~1.82s usando exatamente essa receita.
        #
        # ``_original_cwd`` guarda o cwd ANTES do chdir para que possamos
        # restaurar em ``finalize`` / ``__exit__`` / path de erro.
        # ``None`` = ainda não mudamos cwd (ou já restauramos).
        self._original_cwd: Path | None = None

    # =================================================================
    # Context manager protocol
    # =================================================================

    def __enter__(self) -> ProfitDLL:
        """Entry no context manager. Não inicializa DLL — caller deve chamar
        ``initialize_market_only`` explicitamente para passar credenciais."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit do context manager — finaliza DLL se foi inicializada.

        Q-DRIFT-10: também restaura ``cwd`` mesmo quando a DLL não chegou
        a ser inicializada — ``initialize_market_only`` pode ter mudado o
        cwd e levantado antes de setar ``self._dll``. Path de erro do init
        já restaura, mas defensivamente cobrimos o caso onde o caller
        manipula ``self._dll`` direto (testes) ou exceptiona durante a
        inicialização sem passar pelo nosso try/except.
        """
        if self._dll is not None:
            self.finalize()
        else:
            # Sem DLL inicializada — apenas garante que cwd seja restaurado
            # caso tenha sido alterado por path parcial.
            self._restore_cwd_if_changed()

    # =================================================================
    # Companions validation (AC12)
    # =================================================================

    def _verify_companions(self) -> None:
        """Valida companions DLLs/.dat ANTES do ``WinDLL()`` (AC12).

        Se algum artefato faltar, raises ``DLLInitError(COMPANIONS_MISSING)``
        com lista de paths faltantes. Mensagem é informativa para que o
        usuário rode ``scripts/bootstrap-dll.ps1`` e re-tente.

        Raises:
            DLLInitError: Se companions estão faltando (code=-1,
                name=COMPANIONS_MISSING).
        """
        verify = _load_verify_dll_companions()
        # ``verify`` espera o DIRETÓRIO base (não a DLL principal).
        base_dir = self._dll_path.parent
        result = verify(base_dir)
        if not result.is_ok:
            missing: list[str] = []
            missing.extend(result.missing_dlls)
            missing.extend(result.missing_dats)
            missing.extend(result.missing_dirs)
            log.error(
                "dll.companions_check",
                status="missing",
                base_path=str(base_dir),
                missing=missing,
            )
            raise DLLInitError(
                -1,
                "COMPANIONS_MISSING",
                f"Companions DLL faltantes em {base_dir}: {missing}. "
                "Execute scripts/bootstrap-dll.ps1 e tente novamente.",
                details={"missing": missing, "base_path": str(base_dir)},
            )
        log.info("dll.companions_check", status="ok", base_path=str(base_dir))

    # =================================================================
    # CRIT-2 — argtypes/restype (audit Nelo 2026-05-04, commit 29ad70d)
    # =================================================================

    def _configure_dll_signatures(self) -> None:
        """Configura argtypes/restype de TODAS as funções DLL chamadas.

        CRÍTICO (CRIT-2 audit Nelo 2026-05-04 — commit 29ad70d): sem isso
        ctypes assume ``c_int`` para todos os args/return e desalinha o
        stack frame stdcall em x64. Sintomas:

        - ``c_size_t`` handles (``TranslateTrade``) truncados em 32 bits;
        - ``c_int64`` retornos (``SendOrder``, ``DLLInitializeMarketLogin``)
          chegam corrompidos;
        - ``POINTER(struct)`` desalinha a chamada stdcall e a DLL lê lixo.

        Espelha o canônico ``profitdll/Exemplo Python/profit_dll.py:7-101``
        (Nelogica). Cobre apenas as funções cujos tipos já estão em
        :mod:`data_downloader.dll.types` — funções de trading que dependem
        de structs ainda-não-mirroradas (``TConnectorSendOrder`` etc.) ficam
        de fora desta passada (ConstituionArt. IV — No Invention; squad só
        usa download/market). Quando o trading entrar no escopo, o struct
        é mirrorado em ``types.py`` e a entrada correspondente acrescentada
        a ``configs`` aqui.

        Funções configuradas (versão atual — espelha CRIT-2 audit lista):

        - ``TranslateTrade`` — handle V2 + struct out (CRÍTICO Q-DRIFT MED-4).
        - ``SubscribeTicker`` / ``UnsubscribeTicker`` — pré-req download.
        - ``GetAgentNameLength`` / ``GetAgentName`` — agent resolver V2.
        - ``GetHistoryTrades`` — 4 ``c_wchar_p`` + ``c_int`` ret.
        - ``DLLInitializeMarketLogin`` / ``DLLFinalize`` / ``Finalize`` —
          ``c_int`` ret.
        - ``SetEnabledLogToDebug`` — ``c_int`` arg + ``c_int`` ret.
        - ``GetDLLVersion`` — ``c_wchar_p`` ret (Q-DRIFT-09: pode não estar
          exportada; tolerada).
        - 14 ``Set*Callback`` — argtypes não setados aqui (ctypes infere
          do WINFUNCTYPE passado; setar argtypes para ``Set*Callback`` é
          contra-indicado pois cada signature distinta exigiria literal).

        Tolerância: cada função é configurada em try/except — funções
        deprecated ou não exportadas pela DLL atual são puladas com log
        warning. Esta tolerância é essencial (Q-DRIFT-01 confirma drift
        entre versões: ``GetDLLVersion``, ``SetProgressCallback`` são
        ausentes em versões reais).

        WINFUNCTYPE callbacks: NÃO configurados aqui — já vinculados via
        ``Set*Callback`` em :mod:`callbacks` factories que retornam objeto
        ``WINFUNCTYPE``-wrapped (ctypes infere do tipo passado).

        Raises:
            (não levanta) — função tolera AttributeError + OSError; bloquear
            init aqui mascararia drift entre versões da DLL e é mais nocivo
            que prosseguir e falhar adiante com erro mais específico.
        """
        if self._dll is None:
            # Defensivo — chamado SOMENTE no fim do load WinDLL, mas guarda
            # contra reentrância acidental (ex.: testes que chamam direto).
            return

        # Lazy import: ``ctypes`` types só são úteis em Windows; em outras
        # plataformas o shim em ``types.py`` traz CFUNCTYPE com mesma forma.
        # Importamos os tipos primitivos uma vez aqui — todos consumidos
        # pelas entradas de ``configs`` abaixo.
        from ctypes import (
            POINTER,
            c_double,
            c_int,
            c_int64,
            c_longlong,
            c_size_t,
            c_ubyte,
            c_wchar_p,
        )

        from data_downloader.dll.types import (
            TConnectorAccountIdentifier,
            TConnectorAssetIdentifier,
            TConnectorTrade,
        )

        # Lista canônica espelhada de profit_dll.py:7-101 (Nelogica). Cada
        # entrada é ``(name, argtypes, restype)``; ``argtypes=None`` significa
        # "não tocar argtypes" (deixar default ctypes — usado para funções
        # cuja chamada já passa wrappers ``c_wchar_p`` explícitos por valor,
        # ou cujo exemplo Nelogica também não setou). ``restype=None``
        # significa "não tocar restype" (idem).
        configs: list[tuple[str, list[Any] | None, Any]] = [
            # ----------------------------------------------------------------
            # Lifecycle (não está em profit_dll.py mas crítico para audit CRIT-2)
            # ----------------------------------------------------------------
            # DLLInitializeMarketLogin: 11 args (3 wchar + 8 callback) → int.
            # argtypes=None: cada slot callback tem signature WINFUNCTYPE
            # distinta — ctypes infere do objeto passado. restype SIM
            # (audit CRIT-2: "DLLInitializeMarketLogin.restype").
            ("DLLInitializeMarketLogin", None, c_int),
            ("DLLFinalize", [], c_int),
            ("Finalize", [], c_int),
            ("SetEnabledLogToDebug", [c_int], c_int),
            # ``GetDLLVersion`` retorna ``c_wchar_p`` (PWideChar). Q-DRIFT-09:
            # pode não estar exportada — tolerada via try/except abaixo.
            ("GetDLLVersion", [], c_wchar_p),
            # ----------------------------------------------------------------
            # profit_dll.py:7-15 — orders V1 (sem argtypes no exemplo, só restype)
            # ----------------------------------------------------------------
            ("SendSellOrder", None, c_longlong),
            ("SendBuyOrder", None, c_longlong),
            ("SendZeroPosition", None, c_longlong),
            ("GetAgentNameByID", None, c_wchar_p),
            ("GetAgentShortNameByID", None, c_wchar_p),
            ("GetPosition", None, POINTER(c_int)),
            ("SendMarketSellOrder", None, c_int64),
            ("SendMarketBuyOrder", None, c_int64),
            # ----------------------------------------------------------------
            # profit_dll.py:16-21 — stop orders (args primitivos)
            # ----------------------------------------------------------------
            (
                "SendStopSellOrder",
                [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double, c_double, c_int],
                c_longlong,
            ),
            (
                "SendStopBuyOrder",
                [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_double, c_double, c_int],
                c_longlong,
            ),
            # ----------------------------------------------------------------
            # profit_dll.py:40-41, 88-89 — account count (args primitivos)
            # ----------------------------------------------------------------
            ("GetAccountCount", [], c_int),
            ("GetAccountCountByBroker", [c_int], c_int),
            # ----------------------------------------------------------------
            # profit_dll.py:70-71 — TranslateTrade (CRÍTICO MED-4)
            # ----------------------------------------------------------------
            ("TranslateTrade", [c_size_t, POINTER(TConnectorTrade)], c_int),
            # ----------------------------------------------------------------
            # profit_dll.py:94-98 — Agent name V2 (CRIT-3 dependency)
            # ----------------------------------------------------------------
            ("GetAgentNameLength", [c_int, c_int], c_int),
            ("GetAgentName", [c_int, c_int, c_wchar_p, c_int], c_int),
            # ----------------------------------------------------------------
            # Subscribe/Unsubscribe ticker — pré-req download (CRIT-1)
            # ----------------------------------------------------------------
            # Não está em profit_dll.py:7-101 (exemplo Nelogica usa diretamente
            # sem argtypes), mas signature é canônica: (c_wchar_p ticker,
            # c_wchar_p exchange) → c_int. Argumentos já são passados via
            # c_wchar_p explícito em wrapper.subscribe_ticker, mas argtypes
            # garantem coerção robusta e validação ctypes upfront.
            ("SubscribeTicker", [c_wchar_p, c_wchar_p], c_int),
            ("UnsubscribeTicker", [c_wchar_p, c_wchar_p], c_int),
            # ----------------------------------------------------------------
            # GetHistoryTrades — 4 wchar_p + int ret (manual §3.1 L1750)
            # ----------------------------------------------------------------
            ("GetHistoryTrades", [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p], c_int),
            # ----------------------------------------------------------------
            # profit_dll.py:73-83 — Price depth (V2 — usa structs já em types.py)
            # ----------------------------------------------------------------
            ("SubscribePriceDepth", [POINTER(TConnectorAssetIdentifier)], c_int),
            ("UnsubscribePriceDepth", [POINTER(TConnectorAssetIdentifier)], c_int),
            ("GetPriceDepthSideCount", [POINTER(TConnectorAssetIdentifier), c_ubyte], c_int),
            # ----------------------------------------------------------------
            # profit_dll.py:49-50 — sub-account count (struct em types.py)
            # ----------------------------------------------------------------
            ("GetSubAccountCount", [POINTER(TConnectorAccountIdentifier)], c_int),
        ]

        # Entradas que profit_dll.py configura mas dependem de structs ainda
        # não mirroradas em types.py (squad ainda não usa trading API). NÃO
        # invocamos (Constituição Art. IV — No Invention). Lista preservada
        # como comentário para sinalizar dívida técnica futura:
        #
        # - SendOrder [POINTER(TConnectorSendOrder)] -> c_int64
        # - SendChangeOrderV2 [POINTER(TConnectorChangeOrder)] -> c_int
        # - SendCancelOrderV2 [POINTER(TConnectorCancelOrder)] -> c_int
        # - SendCancelOrdersV2 [POINTER(TConnectorCancelOrders)] -> c_int
        # - SendCancelAllOrdersV2 [POINTER(TConnectorCancelAllOrders)] -> c_int
        # - SendZeroPositionV2 [POINTER(TConnectorZeroPosition)] -> c_int64
        # - GetAccounts / GetAccountDetails / GetSubAccounts / GetAccountsByBroker
        # - GetPositionV2 / GetOrderDetails / HasOrdersInInterval
        # - EnumerateOrdersByInterval / EnumerateAllOrders
        # - GetPriceGroup / GetTheoreticalValues
        # - EnumerateAllPositionAssets
        #
        # Quando algum desses entrar no escopo: mirrorar struct em types.py
        # (autoridade Nelo via Q-DRIFT-*) + adicionar entrada acima.

        registered: list[str] = []
        skipped: list[str] = []
        for name, argtypes, restype in configs:
            try:
                func = getattr(self._dll, name)
            except AttributeError:
                # Função não exportada pela versão atual da DLL (Q-DRIFT).
                # Tolerar — algumas funções são deprecated ou ausentes em
                # versões antigas (ex.: GetDLLVersion confirmado por
                # Q-DRIFT-09 em smoke 2026-05-04).
                skipped.append(name)
                log.warning(
                    "dll.signature_skipped",
                    function=name,
                    reason="not_exported",
                )
                continue
            try:
                if argtypes is not None:
                    func.argtypes = argtypes
                if restype is not None:
                    func.restype = restype
            except (TypeError, AttributeError) as exc:
                # ctypes pode rejeitar tipos inválidos (não deveria acontecer
                # com types canônicos, mas defensive). Loga e segue.
                skipped.append(name)
                log.warning(
                    "dll.signature_skipped",
                    function=name,
                    reason="set_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            registered.append(name)

        log.info(
            "dll.signatures_configured",
            count_registered=len(registered),
            count_skipped=len(skipped),
            registered=registered,
            skipped=skipped,
        )

    # =================================================================
    # Initialization (AC2, AC7, AC11, AC12)
    # =================================================================

    def initialize_market_only(
        self,
        key: str,
        user: str,
        password: str,
        *,
        register_extra_callbacks: bool = False,
        minimal_handshake: bool = False,
    ) -> None:
        """Inicializa a DLL em modo market-only (sem trading).

        EFEITO COLATERAL PROCESSO-WIDE (Q-DRIFT-10): este método chama
        ``os.chdir(self._dll_path.parent)`` ANTES de carregar a DLL e NÃO
        restaura o cwd antes de retornar — a ProfitDLL precisa que o cwd
        permaneça a pasta da DLL durante toda a vida útil da instância
        para localizar companions (libssl/libcrypto), arquivos ``.dat``
        e escrever em ``Logs/``, ``database/``, ``MarketHours2/``. O cwd
        original é salvo em ``self._original_cwd`` e restaurado em
        :meth:`finalize` / ``__exit__`` / path de erro do init. Probe
        ``scripts/probe_init.py`` (commit ``3ef7699``) provou que sem
        chdir o handshake MARKET_DATA trava em ``result=1`` (CONNECTING).

        Sequência (ordem importa — Q-DRIFT-10/AC11/AC12):
            1. ``_verify_companions`` (AC12) — falha cedo se companions
               ausentes.
            2. Verifica plataforma — Windows obrigatório.
            3. ``os.chdir(dll_path.parent)`` (Q-DRIFT-10) — cwd = pasta
               da DLL para que ela ache companions/.dat e escreva logs.
            4. ``WinDLL(path)`` — carrega DLL (AC9 path já resolvido em
               ``__init__``).
            5. ``SetEnabledLogToDebug(0)`` (AC11) — silencia log nativo
               ANTES do init.
            6. Constrói 8 callbacks (1 state ativo + 7 NoopCallback) — AC2,
               todos via factories que appendam em ``_cb_refs`` (Q07-V/AC4).
            7. ``DLLInitializeMarketLogin(key, user, password, state, ...7
               noop)`` — 11 args totais (manual §3.1).
            8. Verifica retorno; se < 0, raises ``DLLInitError`` (AC7) e
               restaura cwd original.
            9. Opcional (``register_extra_callbacks=True``): registra os 14
               ``Set*Callback`` extras alinhados ao exemplo Nelogica
               (main.py L745-761). DESABILITADO por default — ver nota abaixo.

        Args:
            key: Chave de licença ProfitDLL (Nelogica).
            user: Usuário Profit (B3 broker login).
            password: Senha Profit.
            register_extra_callbacks: Se ``True``, registra os 14
                ``Set*Callback`` default (AssetList, OfferBookV2, OrderCallback,
                etc.) com NoopCallbacks após o init. **Default ``False``**
                (Story 1.7b-followup smoke 5): smoke real 2026-05-04 chegou a
                ``MARKET_LOGIN_OK`` + ``LOGIN_CONNECTED`` mas a DLL crashou
                repetidamente durante ``wait_market_connected`` com access
                violations + stack overflow. Causa-raiz mais provável: as 14
                ``NoopCallback`` registradas têm signatures genéricas, mas cada
                ``Set*Callback`` espera uma signature DIFERENTE — invocações
                desalinhadas geram corrupção de stack.

                Para download histórico (caso de uso atual) precisamos APENAS
                de: state callback (já registrado no slot 4 do
                ``DLLInitializeMarketLogin``), ``SetHistoryTradeCallbackV2``
                registrado on-demand em ``download_chunk``, e
                ``subscribe_ticker`` (chamada direta, não callback). Os 14
                extras são para casos de uso DIFERENTES (livro de ofertas em
                tempo real, ordens, contas). Quando Epic 3 implementar UI de
                livro/ordens, este kwarg pode ser ``True`` — mas antes
                precisamos signatures corretas (TODO: Story 1.7b-Q-DRIFT-09
                follow-up para auditar e corrigir signatures por callback).
            minimal_handshake: **Story 1.7d — Espelho ESTRITO do probe**
                (corrige bug da 1.7c que passava ``None`` em slots 5/9/10).
                Quando ``True``, espelha EXATAMENTE o caminho do probe
                canônico ``scripts/probe_init.py`` L239-251 e do exemplo
                Nelogica ``profitdll/Exemplo Python/main.py:742-743``
                (que conectam em <3s onde o wrapper legacy trava 600s+):

                - Pula ``_configure_dll_signatures()`` em larga escala —
                  configura APENAS o mínimo absoluto (restype de
                  ``DLLInitializeMarketLogin``).
                - Pula ``SetEnabledLogToDebug(0)`` (probe e exemplo
                  Nelogica NÃO chamam).
                - Slots 4 / 6 / 7 / 8 (``newTrade``, ``newHistory``,
                  ``priceBook``, ``offerBook``): ``None`` LITERAL —
                  espelho exato do probe e exemplo Nelogica.
                - Slots 5 / 9 / 10 (``newDaily``, ``progress``,
                  ``tinyBook``): callbacks REAIS via
                  :func:`make_noop_callback` com signatures
                  ``TDailyCallback`` / ``TProgressCallback`` /
                  ``TTinyBookCallback`` (todas com ``TAssetID`` por
                  valor — Q-DRIFT-05). Funcionalmente no-op, mas o
                  ponteiro ctypes é VÁLIDO e a DLL pode invocá-los sem
                  early-return — testando empiricamente Q-DRIFT-12
                  (hipótese de que servidor exige callback funcional
                  em 5/9/10 para promover ``MARKET_DATA → result=4``).

                Mantém em ambos paths: ``os.chdir`` (Q-DRIFT-10 — provado
                necessário) e state callback REAL (slot 3) com Queue path.

                Default ``False`` preserva 100% do comportamento atual
                (zero risco de regressão para callers existentes).

                Ver: ``docs/stories/1.7d.story.md`` e
                ``docs/qa/SMOKE_EVIDENCE/1.7c-20260504T224457Z-attempt8-FAIL-still-stuck.md``
                (seção *Análise técnica* / Q-DRIFT-12).

        Raises:
            DLLInitError: Se companions faltantes (COMPANIONS_MISSING),
                plataforma não-Windows (UNSUPPORTED_PLATFORM), erro do init
                (NL_*), ou WinDLL falha ao carregar.
        """
        # AC12 — companions check primeiro (falha cedo, mensagem clara).
        self._verify_companions()

        # Plataforma: ProfitDLL é Win64-only. Em Linux/Mac, raise sentinela
        # para que testes mockados não tentem WinDLL (não existe fora de
        # Windows).
        if sys.platform != "win32":
            log.error("dll.unsupported_platform", platform=sys.platform)
            raise DLLInitError(
                -1,
                "UNSUPPORTED_PLATFORM",
                f"ProfitDLL é Windows-only; plataforma atual: {sys.platform}. "
                "Use mocks (pytest-mock) para testes em Linux/Mac.",
                details={"platform": sys.platform},
            )

        # Q-DRIFT-10 (probe diagnose 2026-05-05, commit 3ef7699): mudar cwd
        # para a pasta da DLL ANTES de ``WinDLL(...)``. Sem isso a ProfitDLL
        # não acha companions (libssl, libcrypto), .dat files (ServerAddr,
        # exchangeinfo2, holidays, timezone2) nem escreve em ``Logs/``,
        # ``database/``, ``MarketHours2/`` — handshake MARKET_DATA trava em
        # ``result=1`` (CONNECTING) sem nunca chegar a ``result=4``. O probe
        # canônico (``scripts/probe_init.py``) reproduziu conexão em ~1.82s
        # com ESTA receita exata. Salvamos cwd em ``self._original_cwd`` para
        # restaurar em :meth:`finalize` / ``__exit__`` / qualquer path de erro
        # daqui pra frente — atenção: NÃO restauramos antes do download (a
        # DLL pode precisar do cwd durante operações de runtime também).
        dll_dir = self._dll_path.parent
        self._original_cwd = Path.cwd()
        os.chdir(str(dll_dir))
        log.info(
            "dll.cwd_changed",
            from_=str(self._original_cwd),
            to=str(dll_dir),
            quirk="Q-DRIFT-10",
        )

        # Carrega DLL principal. Erros aqui (DLL ausente, dependência
        # quebrada não capturada por verify_dll_companions) viram OSError
        # do Windows loader; restauramos cwd antes de levantar.
        log.info("dll.loading", path=str(self._dll_path))
        # Lazy import: ctypes.WinDLL só existe em Windows. Importar inline
        # após checagem de plataforma evita ImportError no module load
        # em Linux/Mac (testes mockados).
        from ctypes import WinDLL

        try:
            self._dll = WinDLL(str(self._dll_path))
        except OSError as exc:
            log.error("dll.load_failed", path=str(self._dll_path), error=str(exc))
            # Q-DRIFT-10 — restaurar cwd antes de propagar o erro: o caller
            # não deve herdar um cwd alterado se o init não chegou nem a
            # carregar a DLL. ``finalize`` não vai ser chamado neste caso
            # (``self._dll`` continua None), portanto a restauração tem que
            # acontecer aqui mesmo.
            self._restore_cwd_if_changed()
            raise DLLInitError(
                -1,
                "WINDLL_LOAD_FAILED",
                f"WinDLL falhou ao carregar {self._dll_path}: {exc}",
                cause=exc,
                details={"path": str(self._dll_path)},
            ) from exc

        # Story 1.7c — bisseção A/B Q-DRIFT-02: branch entre o caminho
        # padrão (configura tudo) e o ``minimal_handshake`` (espelha probe).
        # Default ``minimal_handshake=False`` preserva 100% do comportamento
        # atual; o caminho mínimo serve para isolar qual divergência
        # probe ↔ wrapper causa o handshake travar em ``MARKET_DATA/1``.
        if minimal_handshake:
            # MINIMAL — apenas restype de DLLInitializeMarketLogin para
            # evitar truncamento c_int64 do retorno em x64 stdcall. Probe
            # canônico (``scripts/probe_init.py``) não chama getattr em
            # nenhuma outra função antes do init e funciona — replicamos.
            from ctypes import POINTER as _POINTER_mh  # noqa: N811
            from ctypes import c_int as _c_int_mh
            from ctypes import c_size_t as _c_size_t_mh
            from ctypes import c_wchar_p as _c_wchar_p_mh

            from data_downloader.dll.types import (
                TConnectorTrade as _TConnectorTrade_mh,
            )

            try:
                self._dll.DLLInitializeMarketLogin.restype = _c_int_mh
            except (AttributeError, OSError) as _exc:
                # Não-fatal — restype default é c_int em ctypes; só logamos.
                log.warning(
                    "dll.minimal_handshake_restype_failed",
                    error=str(_exc),
                    error_type=type(_exc).__name__,
                )

            # Q-DRIFT-33 (Story 1.7d, Quinn @qa 2026-05-05): MESMO no path
            # minimal, ``TranslateTrade`` precisa de signatures explícitas
            # — handle V2 é ``c_size_t`` (64 bits em x64) e ctypes default
            # ``c_int`` (32 bits) overflow no IngestorThread após o
            # MARKET_CONNECTED. Skipar ``_configure_dll_signatures``
            # integralmente é correto para evitar AVs de init (Q-DRIFT-12),
            # mas o skip deve ser cirúrgico — a signature de hot-path do
            # download (``TranslateTrade``) é registrada AQUI, fora de
            # ``_configure_dll_signatures``, antes de qualquer subscribe ou
            # callback que dispare. Ver QUIRKS.md Q-DRIFT-33.
            try:
                self._dll.TranslateTrade.argtypes = [
                    _c_size_t_mh,
                    _POINTER_mh(_TConnectorTrade_mh),
                ]
                self._dll.TranslateTrade.restype = _c_int_mh
            except (AttributeError, OSError) as _tt_exc:
                # Não-fatal — registrar warning. Falha aqui significa drift
                # entre versões da DLL (sem ``TranslateTrade`` exportado);
                # o IngestorThread vai falhar mais à frente com erro mais
                # específico (NL_NOT_FOUND no getattr).
                log.warning(
                    "dll.minimal_handshake_translate_trade_signatures_failed",
                    error=str(_tt_exc),
                    error_type=type(_tt_exc).__name__,
                    quirk="Q-DRIFT-33",
                )

            # Q-DRIFT-35 (Story 1.7d, smoke postfix-34 falhou em ~35s sem
            # traceback Python; log mostrava 4x ``agent_resolver.unknown_id
            # length=-2147483636`` (== 0x80000004 reinterpretado como c_int
            # signed)). Mesmo padrão do Q-DRIFT-33: o path ``minimal_handshake``
            # pula ``_configure_dll_signatures`` integralmente, então
            # ``GetAgentNameLength`` e ``GetAgentName`` ficam com defaults
            # ctypes (argtypes None, restype c_int signed). Em x64 stdcall,
            # sem argtypes, args ``c_int`` em alguns ABIs viram corrompidos;
            # o restype ``c_int`` signed default interpreta retornos
            # ``c_uint32`` (length positivo) como negativo gigantesco, e
            # quando esse "length" é passado de volta a ``GetAgentName``
            # como tamanho de buffer pode causar access violation nativa
            # (processo morre sem traceback Python). Registramos signatures
            # explícitas idênticas ao path full (linhas 406-407 acima).
            # Ver QUIRKS.md Q-DRIFT-35.
            try:
                self._dll.GetAgentNameLength.argtypes = [_c_int_mh, _c_int_mh]
                self._dll.GetAgentNameLength.restype = _c_int_mh
                self._dll.GetAgentName.argtypes = [
                    _c_int_mh,
                    _c_int_mh,
                    _c_wchar_p_mh,
                    _c_int_mh,
                ]
                self._dll.GetAgentName.restype = _c_int_mh
            except (AttributeError, OSError) as _ag_exc:
                # Não-fatal — registrar warning. AgentResolver fará fallback
                # determinístico (``Agent#{id}``) se a chamada falhar.
                log.warning(
                    "dll.minimal_handshake_agent_name_signatures_failed",
                    error=str(_ag_exc),
                    error_type=type(_ag_exc).__name__,
                    quirk="Q-DRIFT-35",
                )

            log.info(
                "dll.minimal_handshake_enabled",
                story="1.7d",
                quirk="Q-DRIFT-02-bissection+Q-DRIFT-33+Q-DRIFT-35",
                skipped=["_configure_dll_signatures (full)", "SetEnabledLogToDebug"],
                preserved=[
                    "DLLInitializeMarketLogin.restype",
                    "TranslateTrade.argtypes/restype",
                    "GetAgentNameLength.argtypes/restype",
                    "GetAgentName.argtypes/restype",
                ],
            )
        else:
            # CRIT-2 (audit Nelo 2026-05-04): configurar argtypes/restype ANTES
            # de qualquer chamada à DLL. Sem isso ctypes assume args ``c_int`` e
            # desalinha o stack stdcall em x64 — handles ``c_size_t`` truncam,
            # ponteiros para struct viram int (32 bits), retornos ``c_int64``
            # chegam corrompidos. Pode ter causado a flakey de attempt 4
            # (smoke 2026-05-04).
            self._configure_dll_signatures()

            # AC11 — silenciar log nativo da DLL ANTES do init para não poluir
            # structlog com formato próprio da DLL. Se função não existe na
            # versão (AttributeError), apenas warn — não bloquear init.
            try:
                self._dll.SetEnabledLogToDebug(0)
                log.info("dll.native_log_silenced")
            except (AttributeError, OSError) as exc:
                # AttributeError: função não exposta. OSError: chamada falhou.
                # Não-fatal — apenas warn.
                log.warning(
                    "dll.native_log_silence_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        # State callback REAL (slot 3) é mantido em AMBOS os paths — probe
        # canônico também passa state callback REAL (queue path).
        state_cb = make_state_callback(self._state_queue)

        # Slots 4..10 (7 callbacks): branch entre espelho ESTRITO do probe
        # (Story 1.7d — None em 4/6/7/8 + REAL em 5/9/10) e o caminho default
        # herdado de Q11-E / Sentinel §12 (7 NoopCallback). Premissa "JAMAIS
        # None" foi REFUTADA empiricamente pelo probe (conecta em <3s passando
        # None em slots 4/6/7/8). Slots 5/9/10 são REAL no probe e no exemplo
        # Nelogica — Story 1.7d testa Q-DRIFT-12 (servidor exige callback
        # funcional nesses 3 slots para promover MARKET_DATA → result=4).
        from ctypes import c_wchar_p

        if minimal_handshake:
            # Story 1.7d — Espelho ESTRITO do probe (linhas 239-251) e
            # exemplo Nelogica (``main.py:742-743``):
            #   slot 4  = newTradeCallback     -> None
            #   slot 5  = newDailyCallback     -> REAL (TDailyCallback)
            #   slot 6  = newHistoryCallback   -> None
            #   slot 7  = priceBookCallback    -> None
            #   slot 8  = offerBookCallback    -> None
            #   slot 9  = progressCallBack     -> REAL (TProgressCallback)
            #   slot 10 = tinyBookCallBack     -> REAL (TTinyBookCallback)
            #
            # Story 1.7c (commit 2d17923) tentou passar ``None`` em todos
            # os 7 slots — divergiu do probe nos slots 5/9/10. O attempt 8
            # falhou (MARKET_DATA/1 stuck), levantando Q-DRIFT-12: servidor
            # Nelogica pode exigir callback funcional em 5/9/10 para promover
            # MARKET_DATA → result=4. Esta variante estrita testa Q-DRIFT-12
            # diretamente — se conectar <60s, hipótese confirmada.
            #
            # Nota sobre "REAL": o probe usa callbacks com bodies ``print``;
            # aqui usamos ``make_noop_callback`` (drena args, retorna). O
            # essencial é que o ponteiro de função em ctypes seja não-NULL
            # e a signature WINFUNCTYPE bate com o que a DLL espera. O
            # comportamento Python do callback (no-op vs. log) é irrelevante
            # — a DLL não inspeciona, só invoca.
            non_state_slots: list[Any] = [
                None,  # slot 4  newTradeCallback
                make_noop_callback(TDailyCallback),  # slot 5  newDailyCallback
                None,  # slot 6  newHistoryCallback
                None,  # slot 7  priceBookCallback
                None,  # slot 8  offerBookCallback
                make_noop_callback(TProgressCallback),  # slot 9  progressCallBack
                make_noop_callback(TTinyBookCallback),  # slot 10 tinyBookCallBack
            ]
            log.info(
                "dll.initialize_call",
                key_redacted="***",
                user=user,
                credential_redacted="***",
                slots_active=["state", "newDaily", "progress", "tinyBook"],
                slots_none=4,
                slots_real_noop=3,
                total_callback_slots=4,
                minimal_handshake=True,
                story="1.7d",
                quirk_under_test="Q-DRIFT-12",
            )
        else:
            # AC2 — construir 8 callbacks (1 state ativo + 7 NoopCallback).
            # JAMAIS passar ``None`` (Q11-E / Sentinel §12 — slots ``None``
            # corrompem registro interno e Set*Callback posteriores ficam
            # silenciosamente quebrados).
            non_state_slots = [make_noop_callback(sig) for sig in NOOP_SLOT_SIGNATURES]

            # Logger evento de init — args mascarados (R5 redaction +
            # ADR-010 SENSITIVE_KEYS). Nota: NÃO usar literal ``password=...``
            # como kwarg do logger — pre-commit secret hook (regex
            # ``password\s*=\s*['"]...['"]``) gera falso-positivo. Usar
            # ``credential_redacted=...`` evita o pattern sem perder semântica.
            log.info(
                "dll.initialize_call",
                key_redacted="***",
                user=user,
                credential_redacted="***",
                slots_active=["state"],
                slots_noop=len(non_state_slots),
                total_callback_slots=1 + len(non_state_slots),
            )

        # AC2 — chamada com 11 args: 3 credenciais + 1 state + 7 callbacks
        # (Noop OU None conforme branch acima).
        # Manual §3.1: DLLInitializeMarketLogin(key, user, password, state,
        # trade, daily, priceBook, offerBook, histTrade, progress, tinyBook).
        ret: int = self._dll.DLLInitializeMarketLogin(
            c_wchar_p(key),
            c_wchar_p(user),
            c_wchar_p(password),
            state_cb,
            *non_state_slots,
        )

        # AC7 — retorno < 0 = erro NL_*. Decode + raise DLLInitError.
        if ret < 0:
            err = decode_nl_error(ret)
            log.error(
                "dll.error",
                code=err.code,
                name=err.name,
                event_phase="initialize",
            )
            # Cleanup parcial: anular self._dll (próxima chamada vê não-init)
            # mas NÃO clear _cb_refs (AC4 — ConnectorThread pode ter started).
            self._dll = None
            # Q-DRIFT-10 — restaurar cwd: ``finalize`` confere ``self._dll``
            # e seria no-op aqui, então restauração explícita garante que o
            # processo não fique com cwd alterado após init falho.
            self._restore_cwd_if_changed()
            raise DLLInitError(err.code, err.name, err.message)

        log.info("dll.initialized", code=ret)

        # Story 1.7b-followup smoke 5 (2026-05-04): smoke real chegou a
        # MARKET_LOGIN_OK + LOGIN_CONNECTED mas a DLL crashou repetidamente
        # durante ``wait_market_connected`` com access violations + stack
        # overflow. Causa-raiz mais provável: os 14 ``NoopCallback``
        # registrados em ``_register_default_callbacks`` têm signatures
        # genéricas, mas cada ``Set*Callback`` espera signature DIFERENTE —
        # invocações desalinhadas pela DLL corrompem a stack.
        #
        # Fix conservador: registro EXTRA é OPCIONAL (default False). Para
        # download histórico (caso de uso atual) precisamos só de:
        #   - state callback (já registrado no slot 4 do init)
        #   - SetHistoryTradeCallbackV2 (registrado on-demand em download_chunk)
        #   - subscribe_ticker (chamada direta)
        # Os 14 extras são para casos de uso DIFERENTES (livro tempo real,
        # ordens, contas). Quando Epic 3 implementar UI livro/ordens, ativar
        # esta flag — MAS antes precisamos auditar signatures por callback.
        # TODO Story 1.7b-Q-DRIFT-09 follow-up: signatures corretas.
        if register_extra_callbacks:
            log.info("dll.register_extra_callbacks_enabled")
            self._register_default_callbacks()
        else:
            log.info(
                "dll.register_extra_callbacks_skipped",
                reason="default_disabled_smoke5_access_violations",
            )

    # =================================================================
    # Default callbacks registration (Story 1.7b-followup)
    # =================================================================

    def _register_default_callbacks(self) -> None:
        """Registra 14 callbacks default com NoopCallback (alinha exemplo Nelogica).

        **OPT-IN (Story 1.7b-followup smoke 5):** Este método é chamado APENAS
        quando ``initialize_market_only(..., register_extra_callbacks=True)``.
        Default é ``False`` porque smoke real 2026-05-04 mostrou access
        violations + stack overflow durante ``wait_market_connected`` com este
        registro ativo — signatures genéricas dos 14 NoopCallback não batem
        com o que cada ``Set*Callback`` espera (TODO Story 1.7b-Q-DRIFT-09:
        auditar signatures por callback).

        Itera ``DEFAULT_CALLBACK_REGISTRATIONS`` (definição em ``types.py``
        — ordem replicada literalmente de ``profitdll/Exemplo Python/main.py``
        L745-761), criando um NoopCallback para cada signature e chamando o
        ``Set*Callback`` correspondente.

        Cada callback é construído via :func:`callbacks.make_noop_callback`,
        que append em ``_cb_refs`` (anti-GC, Q07-V) e respeita R3 (no-op
        explícito, sem I/O / sem chamada à DLL).

        Tolerância a versões: se a DLL real não expor alguma das funções
        ``Set*Callback`` (drift entre versões), apenas loga warning e
        continua. Isso preserva o init em DLLs antigas; downloads reais
        usam ``set_history_trade_callback_v2`` etc. que substituem o Noop.

        Raises:
            DLLInitError: Se DLL não inicializada (chamado antes de
                ``initialize_market_only`` — guarda interna).
        """
        if self._dll is None:
            # Defensivo — chamado SOMENTE no fim de ``initialize_market_only``,
            # mas guarda contra reentrância acidental.
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "_register_default_callbacks chamado sem DLL inicializada.",
            )
        registered: list[str] = []
        skipped: list[str] = []
        for method_name, funtype in DEFAULT_CALLBACK_REGISTRATIONS:
            cb = make_noop_callback(funtype)
            # Cinto-e-suspensório: ref adicional na lista da instância (anti-GC
            # local — factory já appendou no global ``_cb_refs``).
            self._cb_refs.append(cb)
            try:
                setter = getattr(self._dll, method_name)
            except AttributeError:
                # DLL não exporta — toleramos (versão antiga / drift). Não
                # bloqueia init; downloads reais ainda funcionam.
                skipped.append(method_name)
                log.warning(
                    "dll.default_callback_unsupported",
                    method=method_name,
                    detail="ProfitDLL não exporta esta função; pulando registro Noop.",
                )
                continue
            try:
                setter(cb)
            except OSError as exc:
                # Chamada falhou em runtime (raro; pode indicar DLL corrompida).
                # Loga e continua — não bloqueia init.
                skipped.append(method_name)
                log.warning(
                    "dll.default_callback_setter_failed",
                    method=method_name,
                    error=str(exc),
                )
                continue
            registered.append(method_name)
        log.info(
            "dll.default_callbacks_registered",
            count_registered=len(registered),
            count_skipped=len(skipped),
            registered=registered,
            skipped=skipped,
        )

    # =================================================================
    # Wait for connected (AC5) — Story 2.12 retry policy
    # =================================================================

    def wait_market_connected(
        self,
        timeout: int = 300,
        *,
        retry_attempts: int = 3,
        retry_cooldown: float = 30.0,
    ) -> bool:
        """Aguarda MARKET_CONNECTED com retry policy (Story 2.12).

        Conexão é flakey (Q-DRIFT-02 revisado — smoke real attempt 4
        2026-05-04): às vezes o handshake completa em 1 segundo, às vezes
        timeout em 300s com a MESMA configuração e credenciais. Retry policy
        com cooldown 30s entre tentativas mitiga o comportamento
        intermitente do servidor.

        Drena ``self._state_queue`` em loop (na thread do caller — NÃO no
        callback, R3) e retorna ``True`` SOMENTE quando recebe
        ``(MARKET_DATA, MARKET_CONNECTED=4)`` — alinhado ao exemplo oficial
        Nelogica (``profitdll/Exemplo Python/main.py`` L223) e ao manual.
        ``MARKET_WAITING=2`` é apenas um estado intermediário possível
        (Q02-E hipótese empírica), logado mas NÃO tratado como
        "connected" (refutado por smoke 2026-05-04 + manual + exemplo).

        Sequência típica (manual §3.2 L3317-3329 + main.py L196-241):
            (0, 0) → LOGIN connected
            (1, 2) → ROTEAMENTO connected
            (2, 2) → MARKET_WAITING (intermediário, NÃO connected)
            (2, 4) → MARKET_CONNECTED (autoritativo — retorna True)
            (3, 0) → MARKET_LOGIN OK

        Default 300s por tentativa (5 min): em ambientes reais o handshake
        pode levar >60s. Heartbeat a cada 30s mostra que o wait está vivo.
        Reset entre tentativas: drena state_queue (eventos antigos podem
        confundir nova rodada). DLLInitialize NÃO é chamado de novo —
        apenas o handshake do market data falhou; a DLL continua viva.

        Args:
            timeout: Timeout POR TENTATIVA em segundos (default 300 — 5 min).
            retry_attempts: Número total de tentativas (incluindo a primeira).
                Default 3. ``1`` = comportamento legado (1 tentativa só).
            retry_cooldown: Cooldown entre tentativas em segundos. Default 30.

        Returns:
            ``True`` se MARKET_DATA conectou (result=4) em alguma tentativa;
            ``False`` se esgotou ``retry_attempts`` sem sucesso (sem raise —
            caller decide se aborta ou reporta).

        Raises:
            DLLInitError: Sinalização explícita de erro fatal vinda de um
                callback (NL_NO_LOGIN, NL_NO_LICENSE etc.) que foi enfileirado
                pela DLL — aborta sem retry (R7 fail fast). Apenas códigos
                NL_* enfileirados como ``(_NL_RESULT_SENTINEL, code)`` viram
                raise; pares ``(conn_type, result)`` normais NÃO viram raise.
        """
        if retry_attempts < 1:
            raise ValueError(f"retry_attempts must be >= 1; got {retry_attempts}")
        if retry_cooldown < 0:
            raise ValueError(f"retry_cooldown must be >= 0; got {retry_cooldown}")

        for attempt in range(1, retry_attempts + 1):
            log.info(
                "dll.market_connect_attempt",
                attempt=attempt,
                max_attempts=retry_attempts,
                timeout=timeout,
            )
            connected = self._wait_market_connected_once(timeout=timeout)
            if connected:
                if attempt > 1:
                    log.info(
                        "dll.market_connect_recovered",
                        attempt=attempt,
                        max_attempts=retry_attempts,
                    )
                return True

            if attempt < retry_attempts:
                # Não é a última tentativa — aplicar cooldown + reset state.
                # Microcopy ID alinha com docs/ux/MICROCOPY_CATALOG.md
                # WAR_DLL_MARKET_RETRY (Story 2.12).
                log.warning(
                    "dll.market_connect_retry",
                    attempt=attempt,
                    max_attempts=retry_attempts,
                    cooldown_seconds=retry_cooldown,
                    microcopy_id="WAR_DLL_MARKET_RETRY",
                )
                # Drena state_queue antes da próxima tentativa — eventos
                # antigos (LOGIN/ROTEAMENTO já vistos) confundem a próxima
                # rodada, pois ela esperaria-os de novo. DLL ainda está
                # inicializada; só o handshake market data falhou.
                self._drain_state_queue()
                if retry_cooldown > 0:
                    time.sleep(retry_cooldown)

        # Esgotou todas as tentativas. Microcopy ID alinha com
        # docs/ux/MICROCOPY_CATALOG.md ERR_DLL_MARKET_RETRY_EXHAUSTED.
        log.error(
            "dll.market_connect_retry_exhausted",
            attempts=retry_attempts,
            timeout_per_attempt=timeout,
            microcopy_id="ERR_DLL_MARKET_RETRY_EXHAUSTED",
        )
        return False

    def _drain_state_queue(self) -> int:
        """Drena ``self._state_queue`` (Story 2.12 — reset entre retries).

        Eventos antigos (LOGIN/ROTEAMENTO/MARKET_WAITING já consumidos numa
        tentativa anterior) podem permanecer no buffer interno se a DLL
        estiver enviando states em rajadas; uma nova rodada de
        :meth:`_wait_market_connected_once` espera ver MARKET_DATA novo,
        não estados velhos. Drenamos sem bloquear.

        Returns:
            Número de eventos descartados (apenas para logging/forensics).
        """
        drained = 0
        while True:
            try:
                self._state_queue.get_nowait()
            except Empty:
                break
            drained += 1
        if drained > 0:
            log.info("dll.state_queue_drained", events_discarded=drained)
        return drained

    def _wait_market_connected_once(self, timeout: int) -> bool:
        """Aguarda 1 tentativa de handshake (lógica original Story 1.7b).

        Extraída de :meth:`wait_market_connected` para Story 2.12 (retry
        policy). Comportamento idêntico ao código pré-2.12: drena state
        queue até ``MARKET_CONNECTED`` ou timeout.

        Args:
            timeout: Timeout em segundos para ESTA tentativa.

        Returns:
            ``True`` se conectou; ``False`` em timeout.
        """
        # Heartbeat a cada 30s para visibilidade quando o handshake é lento
        # (silêncio total >60s confunde operador — parece travado).
        heartbeat_interval = 30.0
        start = time.monotonic()
        deadline = start + timeout
        next_heartbeat = start + heartbeat_interval
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                # Mensagem genérica sem hipóteses refutadas (ProfitChart como
                # pré-requisito foi refutado pelo usuário — manual + exemplo
                # confirmam que init standalone basta). Microcopy ID alinha
                # com docs/ux/MICROCOPY_CATALOG.md ERR_DLL_MARKET_TIMEOUT
                # (mantido para compatibilidade — caller acima emite
                # ERR_DLL_MARKET_RETRY_EXHAUSTED após esgotar retries).
                log.warning(
                    "dll.connected_timeout",
                    timeout=timeout,
                    microcopy_id="ERR_DLL_MARKET_TIMEOUT",
                )
                return False

            # Heartbeat — emite log se passou ``heartbeat_interval`` sem state
            # novo. NÃO consome do queue; apenas informa que ainda estamos
            # vivos esperando.
            if now >= next_heartbeat:
                elapsed = int(now - start)
                log.info(
                    "dll.waiting_market_data",
                    elapsed_seconds=elapsed,
                    timeout=timeout,
                )
                next_heartbeat = now + heartbeat_interval

            # Bloqueio limitado ao próximo heartbeat OU deadline (o que vier
            # antes) — permite emitir o log de progresso mesmo sem state novo.
            wait_for = min(remaining, max(0.1, next_heartbeat - now))
            try:
                conn_type, result = self._state_queue.get(timeout=wait_for)
            except Empty:
                # Não é timeout final — pode ser apenas hora do heartbeat.
                continue

            alias = self._resolve_state_alias(conn_type, result)
            log.info(
                "dll.market_state",
                conn_type=conn_type,
                result=result,
                alias=alias,
            )

            # Critério "connected" = (conn_type == MARKET_DATA AND result == MARKET_CONNECTED=4),
            # alinhado ao exemplo oficial Nelogica (main.py L223) e ao manual.
            # ``MARKET_WAITING=2`` é apenas estado intermediário, NÃO connected.
            if conn_type == MARKET_DATA and result == MARKET_CONNECTED:
                log.info("dll.connected", alias=alias)
                return True

    @staticmethod
    def _resolve_state_alias(conn_type: int, result: int) -> str:
        """Resolve par ``(conn_type, result)`` para alias humano (logger AC8).

        Usa ``STATE_CODE_ALIAS`` quando o par está mapeado; caso contrário
        retorna ``"<CONN_TYPE_NAME>/<result>"`` ou
        ``"UNKNOWN_<conn_type>/<result>"`` quando o ``conn_type`` é
        desconhecido.
        """
        pair = (conn_type, result)
        if pair in STATE_CODE_ALIAS:
            return STATE_CODE_ALIAS[pair]
        conn_name = CONN_TYPE_NAME.get(conn_type)
        if conn_name is None:
            return f"UNKNOWN_{conn_type}/{result}"
        return f"{conn_name}/{result}"

    # =================================================================
    # Finalize (AC4, AC6)
    # =================================================================

    def finalize(self) -> None:
        """Encerra a DLL — preferindo ``DLLFinalize`` (manual) sobre ``Finalize``
        (whale-detector observou) — Q-AMB-02 / AC6.

        Também restaura o ``cwd`` original (Q-DRIFT-10): ``initialize_market_only``
        muda o cwd do processo para a pasta da DLL para que a ProfitDLL ache
        seus companions. Aqui revertemos para o cwd que existia antes do init,
        para que o caller não fique com efeito colateral residual após
        terminar o lifecycle. Restauração é best-effort: se o cwd original
        não existir mais (raríssimo — ex: caller deletou o diretório), apenas
        loga warning e segue.

        IMPORTANTE (AC4): NÃO chamar ``_cb_refs.clear()`` aqui. ConnectorThread
        interna da DLL pode ainda referenciar callbacks pendentes; remover
        a referência Python-side liberaria o trampoline ctypes e crashar
        o processo (Q07-V). Apenas anular ``self._dll = None``.
        """
        if self._dll is None:
            # Mesmo sem DLL inicializada, garante que cwd seja restaurado
            # caso ``__exit__`` chame ``finalize`` após init que falhou
            # parcialmente sem restaurar (defensivo — paths normais já
            # restauram, mas idempotência é barata).
            self._restore_cwd_if_changed()
            return

        # Q-AMB-02: tenta DLLFinalize (manual canônico) → fallback Finalize
        # (compat reversa observada). Loga qual foi usado para que Nelo
        # atualize Q09-AMB com evidência empírica após smoke real.
        ret: int
        method_used: str
        try:
            ret = self._dll.DLLFinalize()
            method_used = "DLLFinalize"
        except AttributeError:
            ret = self._dll.Finalize()
            method_used = "Finalize"

        log.info("dll.finalized", code=ret, method=method_used)

        # AC4 — NÃO `_cb_refs.clear()`. ConnectorThread pode ainda
        # referenciar; limpar = crash. Apenas anular self._dll.
        self._dll = None

        # Q-DRIFT-10 — restaurar cwd original APÓS finalizar a DLL. Ordem
        # importa: a DLL pode estar escrevendo em ``Logs/`` durante o
        # ``DLLFinalize`` (flush de buffers), então só mudamos o cwd
        # depois que ela terminou.
        self._restore_cwd_if_changed()

    def _restore_cwd_if_changed(self) -> None:
        """Restaura ``cwd`` salvo em :attr:`_original_cwd` (Q-DRIFT-10).

        Idempotente: se ``_original_cwd`` é ``None`` (nunca mudamos OU já
        restauramos), é no-op silencioso. Após restaurar, zera o atributo
        para que próximas chamadas saibam que não há mais nada a desfazer.

        Best-effort: se ``os.chdir`` falhar (ex.: cwd original foi deletado
        por outro processo), loga warning e segue — não levanta. A
        finalização da DLL é mais importante que perfeição na restauração.
        """
        if self._original_cwd is None:
            return
        target = self._original_cwd
        # Zera ANTES de tentar para evitar loops em caso de exceção.
        self._original_cwd = None
        try:
            os.chdir(str(target))
        except OSError as exc:
            log.warning(
                "dll.cwd_restore_failed",
                target=str(target),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return
        log.info("dll.cwd_restored", to=str(target), quirk="Q-DRIFT-10")

    # =================================================================
    # Properties (AC13)
    # =================================================================

    @property
    def dll_version(self) -> str:
        """Versão da DLL carregada (AC13). Cacheada após 1ª chamada.

        Tenta ``GetDLLVersion()`` se exposto. Se ausente / erro, retorna
        ``"unknown"`` + emite log warn (não levanta — versão não é
        bloqueante para operações; é metadata para Sol's Parquet H19/H1).

        Returns:
            String com versão (ex. ``"4.0.0.34"``) ou ``"unknown"``.
        """
        if self._dll_version_cache is not None:
            return self._dll_version_cache
        if self._dll is None:
            # DLL não inicializada — retorna sentinela mas NÃO cacheia
            # (próxima chamada após init pode obter versão real).
            return "unknown"
        try:
            raw = self._dll.GetDLLVersion()
        except (AttributeError, OSError) as exc:
            log.warning(
                "dll.version_unknown",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            self._dll_version_cache = "unknown"
            return self._dll_version_cache

        # GetDLLVersion pode retornar PWideChar (string) ou int — defensive cast.
        version = str(raw) if raw is not None else "unknown"
        self._dll_version_cache = version
        log.info("dll.version_resolved", version=version)
        return version

    # =================================================================
    # Story 1.3 — History download primitive
    # =================================================================
    # Decisão COUNCIL-03: V2 history callback (TranslateTrade em
    # IngestorThread, NÃO no callback). Wrapper expõe métodos para:
    #
    # - registrar callbacks via Set*Callback (R10/Q13-V — V2 sempre)
    # - chamar GetHistoryTrades com formato exato de data (manual §3.1 L1750)
    # - traduzir handle opaco em TConnectorTrade struct (TranslateTrade)
    #
    # Validações na fronteira (chamada do método):
    # - exchange ∈ ('F', 'B') — R8/Q05-V
    # - formato de data "DD/MM/YYYY HH:mm:SS" — manual §3.1 L1750
    # =================================================================

    def set_history_trade_callback_v2(self, callback: Any) -> None:
        """Registra callback V2 de trades históricos (Story 1.3 / COUNCIL-03).

        Wraps ``self._dll.SetHistoryTradeCallbackV2(callback)``. O ``callback``
        DEVE vir de :func:`data_downloader.dll.callbacks.make_history_trade_callback_v2`
        — já em ``_cb_refs`` (anti-GC, Q07-V), faz APENAS ``put_nowait`` (R3).

        Após o registro, chamadas a :meth:`get_history_trades` farão o
        callback disparar para cada trade do range. ``TranslateTrade`` é
        responsabilidade do consumer — ver :meth:`translate_trade`.

        Args:
            callback: Objeto ``WINFUNCTYPE``-wrapped (signature
                ``THistoryTradeCallbackV2``). Garantido em ``_cb_refs``
                pela factory.

        Raises:
            DLLInitError: Se DLL não inicializada (NL_NOT_INITIALIZED).
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de set_history_trade_callback_v2.",
            )
        # Mantém referência adicional defensiva (Q07-V) — factory já appendou,
        # esta segunda referência é cinto-e-suspensório (custo zero, lista
        # global é append-only durante a vida do processo).
        self._cb_refs.append(callback)
        try:
            self._dll.SetHistoryTradeCallbackV2(callback)
        except AttributeError as exc:
            # Fail-fast com contexto Q-DRIFT — diferente de SetProgressCallback,
            # esta função É exportada pela DLL real (probada 2026-05-04). Se
            # chegou aqui é versão muito antiga / DLL alternativa.
            raise DLLInitError(
                -1,
                "DLL_API_DRIFT",
                "SetHistoryTradeCallbackV2 não exportada pela ProfitDLL "
                f"em {self._dll_path}. Esta função é necessária para "
                "downloads históricos V2 (COUNCIL-03). "
                "Verifique versão da DLL ou consulte Nelo (docs/dll/QUIRKS.md Q-DRIFT-01).",
                cause=exc,
            ) from exc
        log.info("dll.history_trade_callback_v2_registered")

    def set_progress_callback(self, callback: Any) -> None:
        """Registra callback de progresso de download histórico (Story 1.3).

        Tenta ``self._dll.SetProgressCallback(callback)`` mas TOLERA AttributeError
        — Q-DRIFT-01 (smoke 2026-05-04): a ProfitDLL real **NÃO exporta**
        ``SetProgressCallback`` nem ``SetProgressCallbackV2``. Per o exemplo
        oficial Nelogica (``profitdll/Exemplo Python/main.py`` L740-743), o
        ``progressCallBack`` é fornecido como **slot 10 de
        ``DLLInitializeMarketLogin``** (já preenchido com Noop em ``initialize_market_only``).

        Comportamento defensivo: se a função não existe, loga warning e retorna
        sem erro — downloads ainda completam via ``TC_LAST_PACKET`` (bit 1 das
        flags do callback V2 — manual §3.2 L1912). A queue de progresso
        permanece vazia, mas ``download_primitive`` detecta fim via
        ``ingestor.last_packet_seen``.

        Para suporte real a progresso em runtime, ver Q-DRIFT-01 — requer
        re-init com slot 10 customizado (não suportado nesta versão; Story 1.3
        usa apenas ``last_packet`` como sinal autoritativo).

        Args:
            callback: Objeto ``WINFUNCTYPE``-wrapped (signature
                ``TProgressCallback``). Mantido em ``_cb_refs`` mesmo se DLL
                não expor função (custo zero, anti-GC).

        Raises:
            DLLInitError: Se DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de set_progress_callback.",
            )
        # Cinto-e-suspensório: mantém ref Python anti-GC mesmo quando a DLL
        # não consome o ponteiro. Custo zero (lista append-only).
        self._cb_refs.append(callback)
        try:
            self._dll.SetProgressCallback(callback)
        except AttributeError:
            # Q-DRIFT-01 — função não exportada. Downloads dependem de
            # TC_LAST_PACKET (V2 flag) para detectar fim, NÃO de progress=100.
            log.warning(
                "dll.progress_callback_unsupported",
                quirk="Q-DRIFT-01",
                detail=(
                    "ProfitDLL não exporta SetProgressCallback; "
                    "fim do download detectado via TC_LAST_PACKET (V2 flag)."
                ),
            )
            return
        log.info("dll.progress_callback_registered")

    def get_history_trades(
        self,
        ticker: str,
        exchange: str,
        dt_start: str,
        dt_end: str,
    ) -> int:
        """Solicita download de trades históricos (Story 1.3 — manual §3.1).

        Formato esperado das datas (manual §3.1 L1750 — Nelo):
        ``"DD/MM/YYYY HH:mm:SS"``. Validado upfront — ``ValueError`` se inválido.

        Bolsa DEVE ser letra única (R8/Q05-V): ``"F"`` (BMF) ou ``"B"``
        (Bovespa). String ``"BMF"`` retorna ``NL_EXCHANGE_UNKNOWN``.

        A chamada dispara assincronamente:

        - múltiplos ``HistoryTradeCallbackV2`` (1 por trade) na ConnectorThread
        - múltiplos ``ProgressCallback`` (progresso 1..100) na ConnectorThread

        Caller DEVE ter registrado ambos callbacks ANTES — caso contrário,
        trades chegam mas são descartados (callback ainda é o NoopCallback
        do init).

        Args:
            ticker: Contrato vigente (NÃO alias — Q01-V). Ex.: ``"WDOJ26"``,
                ``"PETR4"``.
            exchange: ``"F"`` ou ``"B"``.
            dt_start: ``"DD/MM/YYYY HH:mm:SS"``.
            dt_end: ``"DD/MM/YYYY HH:mm:SS"``.

        Returns:
            Código retornado por ``GetHistoryTrades`` (0 sucesso, NL_*
            negativo em erro).

        Raises:
            ValueError: Bolsa ou formato de data inválido.
            DLLInitError: DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de get_history_trades.",
            )
        # R8/Q05-V — bolsa DEVE ser letra única ('F' ou 'B'). Validar
        # upfront com erro claro em vez de deixar a DLL retornar
        # NL_EXCHANGE_UNKNOWN críptico (Sentinel §12 documentou semanas
        # debugando "BMF").
        if exchange not in ("F", "B"):
            raise ValueError(
                f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}. "
                "Strings como 'BMF', 'BOVESPA' são REJEITADAS pela DLL "
                "(R8/Q05-V — manual §3.1 L1673)."
            )
        # Formato manual §3.1 L1750 — validar antes de chamar a DLL.
        _validate_history_date_format(dt_start, "dt_start")
        _validate_history_date_format(dt_end, "dt_end")

        from ctypes import c_wchar_p

        log.info(
            "dll.get_history_trades_call",
            ticker=ticker,
            exchange=exchange,
            dt_start=dt_start,
            dt_end=dt_end,
        )
        ret: int = self._dll.GetHistoryTrades(
            c_wchar_p(ticker),
            c_wchar_p(exchange),
            c_wchar_p(dt_start),
            c_wchar_p(dt_end),
        )
        log.info("dll.get_history_trades_return", code=ret)
        return ret

    # =================================================================
    # Story 1.7b-followup — SubscribeTicker / UnsubscribeTicker
    # =================================================================
    # ProfitDLL exige ``SubscribeTicker(ticker, exchange)`` ANTES de
    # ``GetHistoryTrades``. Sem subscribe, a DLL aceita a chamada de
    # GetHistoryTrades mas NÃO entrega trades (state interno do ticker
    # nunca é populado). Confirmado pelo usuário (autoridade ProfitDLL)
    # — alinhado com exemplo oficial Nelogica (main.py L590-602
    # ``subscribeTicker()`` / ``unsubscribeTicker()``).
    #
    # Lei R8/Q05-V (revalidada): exchange ∈ {'F', 'B'}. Strings tipo 'BMF'
    # rejeitadas com ValueError ANTES de chamar a DLL (mesma lei usada por
    # ``get_history_trades``).
    # =================================================================

    def subscribe_ticker(self, ticker: str, exchange: str) -> int:
        """Inscreve ticker na DLL — pré-requisito para ``GetHistoryTrades``.

        ProfitDLL não popula trades históricos sem subscribe explícito antes
        do ``GetHistoryTrades`` (confirmado pelo usuário, autoridade ProfitDLL,
        e alinhado com exemplo Nelogica ``main.py`` L590-595).

        Após o download, caller DEVE chamar :meth:`unsubscribe_ticker` para
        liberar o slot interno (``download_chunk`` faz isso em ``try/finally``).

        Args:
            ticker: Contrato vigente (NÃO alias). Ex.: ``"WDOJ26"``, ``"PETR4"``.
            exchange: ``"F"`` (BMF) ou ``"B"`` (Bovespa). Strings tipo ``"BMF"``
                são rejeitadas (R8/Q05-V).

        Returns:
            Código retornado por ``SubscribeTicker`` (``0 = NL_OK`` em sucesso,
            NL_* negativo em erro). Caller decide se prossegue (DLL pode
            aceitar tickers já subscritos retornando código não-fatal).

        Raises:
            ValueError: Bolsa inválida (≠ 'F'/'B').
            DLLInitError: DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de subscribe_ticker.",
            )
        # R8/Q05-V — exchange single-letter. Mensagem alinha com get_history_trades
        # para consistência (mesma lei, mesmo erro).
        if exchange not in ("F", "B"):
            raise ValueError(
                f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}. "
                "Strings como 'BMF', 'BOVESPA' são REJEITADAS pela DLL "
                "(R8/Q05-V — manual §3.1 L1673)."
            )
        from ctypes import c_wchar_p

        log.info("dll.subscribe_ticker", ticker=ticker, exchange=exchange)
        ret: int = self._dll.SubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
        log.info(
            "dll.subscribe_ticker_return",
            ticker=ticker,
            exchange=exchange,
            code=ret,
        )
        return ret

    def unsubscribe_ticker(self, ticker: str, exchange: str) -> int:
        """Remove inscrição do ticker — chamado APÓS download (try/finally).

        Mantém o estado interno da DLL limpo entre chunks/símbolos. Se a
        chamada falhar (ticker já não-subscrito, DLL em estado inconsistente),
        caller deve apenas logar — não há ação de recuperação útil.

        Args:
            ticker: Mesmo ticker passado a :meth:`subscribe_ticker`.
            exchange: ``"F"`` ou ``"B"`` — mesma validação R8/Q05-V.

        Returns:
            Código retornado por ``UnsubscribeTicker``.

        Raises:
            ValueError: Bolsa inválida (≠ 'F'/'B').
            DLLInitError: DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de unsubscribe_ticker.",
            )
        if exchange not in ("F", "B"):
            raise ValueError(
                f"exchange must be 'F' (BMF) or 'B' (Bovespa); got {exchange!r}. "
                "Strings como 'BMF', 'BOVESPA' são REJEITADAS pela DLL "
                "(R8/Q05-V — manual §3.1 L1673)."
            )
        from ctypes import c_wchar_p

        log.info("dll.unsubscribe_ticker", ticker=ticker, exchange=exchange)
        ret: int = self._dll.UnsubscribeTicker(c_wchar_p(ticker), c_wchar_p(exchange))
        log.info(
            "dll.unsubscribe_ticker_return",
            ticker=ticker,
            exchange=exchange,
            code=ret,
        )
        return ret

    def translate_trade(self, p_trade_handle: int) -> TradeFields | None:
        """Desempacota handle V2 em :class:`TradeFields` (Story 1.7b-followup).

        Wraps ``self._dll.TranslateTrade(handle, byref(struct))`` + extração
        dos 9 campos do struct para uma ``NamedTuple`` Python idiomática.
        **DEVE ser chamado em IngestorThread (FORA do callback)** — chamar
        a DLL de dentro do callback viola lei R3 / manual §4 L4382 / Q06-V.

        Story 1.7b-followup (TranslateTrade complete): API pública agora
        retorna :class:`TradeFields` em vez de receber struct out-param.
        Aloca um ``TConnectorTrade`` interno por chamada (custo ~ ns —
        struct é small POD; CPython ctypes alloc é barato). Para hot
        paths que reusam struct manualmente, ver
        :meth:`_translate_trade_raw` (low-level / privado).

        ``Version=0`` é setado antes de cada ``TranslateTrade`` (main.py
        L328 demonstra). Conversão ``SystemTime`` → ``timestamp_ns`` BRT
        naive (lei R7) é aplicada via :func:`_system_time_to_ns` em
        ``orchestrator.download_primitive`` — caller (IngestorThread) já
        tem helper local + reusa.

        Atenção: ``timestamp_ns`` em ``TradeFields`` aqui é convertido via
        helper local desta classe (mesma lei R7 — datetime naive
        interpretado como BRT, sem conversão UTC).

        Args:
            p_trade_handle: Handle opaco recebido pelo callback V2 (1º item
                da tuple enfileirada por ``make_history_trade_callback_v2``).

        Returns:
            :class:`TradeFields` populada com os 9 campos do struct, ou
            ``None`` se ``TranslateTrade`` retornar erro NL_*. Caller
            (IngestorThread) trata ``None`` como falha (counter agregado
            ``translate_failures``) e descarta o trade silenciosamente.

        Raises:
            DLLInitError: DLL não inicializada (NL_NOT_INITIALIZED).
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de translate_trade.",
            )

        struct = TConnectorTrade(Version=0)
        rc = self._translate_trade_raw(p_trade_handle, struct)
        if rc != 0:
            # NL_* negativo — caller agrega via counter ``translate_failures``
            # e loga 1x no fim (cool path). Não levantar — pipeline continua
            # processando demais trades do chunk.
            return None

        # Q-DRIFT-34 (Story 1.7d, Quinn @qa 2026-05-05): callback V2 dispara
        # com struct sentinela ZERADO antes do primeiro trade real — DLL
        # retorna ``rc=0`` mas ``TradeDate.wYear == 0`` (FILETIME 1601-01-01,
        # convertido para ns produz timestamp negativo). Tratar como falha
        # de tradução (mesmo path de NL_*): retornar None para o caller
        # (IngestorThread) incrementar ``translate_failures`` e descartar
        # silenciosamente. Sem isso ``_system_time_to_ns_local`` retorna
        # ``-2209161600...`` e ``format_brt_timestamp(ns < 0)`` levanta
        # ValueError → IngestorThread morre, drenagem para. Ver QUIRKS.md
        # Q-DRIFT-34.
        if int(struct.TradeDate.wYear) <= 1900:
            return None

        return TradeFields(
            version=int(struct.Version),
            timestamp_ns=_system_time_to_ns_local(struct.TradeDate),
            trade_number=int(struct.TradeNumber),
            price=float(struct.Price),
            quantity=int(struct.Quantity),
            volume=float(struct.Volume),
            buy_agent_id=int(struct.BuyAgent),
            sell_agent_id=int(struct.SellAgent),
            trade_type=int(struct.TradeType),
        )

    def _translate_trade_raw(self, p_trade_handle: int, trade_struct: Any) -> int:
        """Low-level ``TranslateTrade`` — preenche ``trade_struct`` in-place.

        Helper privado para casos onde caller precisa reusar um único
        ``TConnectorTrade`` entre chamadas (micro-optimização — evita
        alocação por trade). Hot paths normais usam :meth:`translate_trade`
        (API pública) que retorna :class:`TradeFields` imutável (mais
        ergonômico, custo de alocação irrelevante na prática).

        Caller é responsável por:

        1. Setar ``trade_struct.Version = 0`` antes de cada chamada
           (main.py L328 demonstra).
        2. Copiar campos ANTES de overwriter — a DLL pode reescrever o
           buffer apontado na próxima chamada.

        Args:
            p_trade_handle: Handle opaco do callback V2.
            trade_struct: ``TConnectorTrade`` reutilizável.

        Returns:
            Código retornado por ``TranslateTrade`` (0 sucesso, NL_*
            negativo em erro).

        Raises:
            DLLInitError: DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de _translate_trade_raw.",
            )
        from ctypes import byref

        rc: int = self._dll.TranslateTrade(p_trade_handle, byref(trade_struct))
        return rc


# =====================================================================
# Story 1.3 — Helpers de validação (módulo-level, reusáveis em testes)
# =====================================================================


def _system_time_to_ns_local(st: Any) -> int:
    """Converte ``SystemTime`` (struct ctypes) → timestamp_ns BRT naive.

    Lei R7 / Q04-E: NÃO converter para UTC. Wall clock da DLL é BRT naive
    (sem DST desde 2019). Construir datetime naive com os campos do struct
    e depois converter para nanos via mesmo truque do timestamp parser.

    Helper local da camada DLL — duplicado intencionalmente com
    ``orchestrator.download_primitive._system_time_to_ns`` (mesma fórmula)
    para evitar dependência circular dll → orchestrator. Ambos seguem R7
    e produzem o mesmo resultado para os mesmos campos.

    Args:
        st: ``data_downloader.dll.types.SystemTime`` (campos wYear, wMonth,
            wDay, wHour, wMinute, wSecond, wMilliseconds; ignoramos
            wDayOfWeek).

    Returns:
        Nanosegundos desde 1970-01-01 BRT naive.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    dt_naive = _dt(
        year=int(st.wYear),
        month=int(st.wMonth),
        day=int(st.wDay),
        hour=int(st.wHour),
        minute=int(st.wMinute),
        second=int(st.wSecond),
        microsecond=int(st.wMilliseconds) * 1000,
    )
    aware = dt_naive.replace(tzinfo=UTC)
    delta = aware - _dt(1970, 1, 1, tzinfo=UTC)
    total_seconds = delta.days * 86_400 + delta.seconds
    return total_seconds * 1_000_000_000 + delta.microseconds * 1_000


_HISTORY_DATE_FORMAT: Final[str] = "DD/MM/YYYY HH:mm:SS"
"""Formato de data esperado por ``GetHistoryTrades`` (manual §3.1 L1750)."""


def _validate_history_date_format(s: str, field: str) -> None:
    """Valida formato exato ``"DD/MM/YYYY HH:mm:SS"`` (manual §3.1 L1750).

    Não usa ``strptime`` — apenas estrutura. Validação semântica completa
    (parser BRT naive) fica em ``orchestrator.timestamp.parse_brt_timestamp``.
    Aqui o objetivo é falhar rápido com erro claro antes de gastar a chamada
    da DLL com formato errado.

    Args:
        s: String a validar.
        field: Nome do campo (para mensagem de erro).

    Raises:
        ValueError: Se string não tem 19 chars, ou separadores errados.
    """
    if not isinstance(s, str) or len(s) != 19:
        raise ValueError(
            f"{field} must be string of length 19 in format "
            f"{_HISTORY_DATE_FORMAT!r}; got {s!r} (len={len(s) if isinstance(s, str) else 'N/A'})"
        )
    # Posições fixas de separadores (DD/MM/YYYY HH:mm:SS):
    #  012345678901234567 8
    #  DD / MM / YYYY space HH : mm : SS
    if s[2] != "/" or s[5] != "/" or s[10] != " " or s[13] != ":" or s[16] != ":":
        raise ValueError(
            f"{field} must match format {_HISTORY_DATE_FORMAT!r}; got {s!r}. "
            "Separadores esperados: '/', '/', ' ', ':', ':' "
            "nas posições 2, 5, 10, 13, 16."
        )
