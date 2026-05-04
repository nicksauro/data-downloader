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
    MARKET_CONNECTED,
    MARKET_DATA,
    MARKET_WAITING,
    NOOP_SLOT_SIGNATURES,
    STATE_CODE_ALIAS,
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
        """Exit do context manager — finaliza DLL se foi inicializada."""
        if self._dll is not None:
            self.finalize()

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
    # Initialization (AC2, AC7, AC11, AC12)
    # =================================================================

    def initialize_market_only(
        self,
        key: str,
        user: str,
        password: str,
    ) -> None:
        """Inicializa a DLL em modo market-only (sem trading).

        Sequência (ordem importa — AC11/AC12):
            1. ``_verify_companions`` (AC12) — falha cedo se companions
               ausentes.
            2. Verifica plataforma — Windows obrigatório.
            3. ``WinDLL(path)`` — carrega DLL (AC9 path já resolvido em
               ``__init__``).
            4. ``SetEnabledLogToDebug(0)`` (AC11) — silencia log nativo
               ANTES do init.
            5. Constrói 8 callbacks (1 state ativo + 7 NoopCallback) — AC2,
               todos via factories que appendam em ``_cb_refs`` (Q07-V/AC4).
            6. ``DLLInitializeMarketLogin(key, user, password, state, ...7
               noop)`` — 11 args totais (manual §3.1).
            7. Verifica retorno; se < 0, raises ``DLLInitError`` (AC7).

        Args:
            key: Chave de licença ProfitDLL (Nelogica).
            user: Usuário Profit (B3 broker login).
            password: Senha Profit.

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

        # Carrega DLL principal. Erros aqui (DLL ausente, dependência
        # quebrada não capturada por verify_dll_companions) viram OSError
        # do Windows loader; deixamos propagar com contexto via log.
        log.info("dll.loading", path=str(self._dll_path))
        # Lazy import: ctypes.WinDLL só existe em Windows. Importar inline
        # após checagem de plataforma evita ImportError no module load
        # em Linux/Mac (testes mockados).
        from ctypes import WinDLL

        try:
            self._dll = WinDLL(str(self._dll_path))
        except OSError as exc:
            log.error("dll.load_failed", path=str(self._dll_path), error=str(exc))
            raise DLLInitError(
                -1,
                "WINDLL_LOAD_FAILED",
                f"WinDLL falhou ao carregar {self._dll_path}: {exc}",
                cause=exc,
                details={"path": str(self._dll_path)},
            ) from exc

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

        # AC2 — construir 8 callbacks (1 state ativo + 7 NoopCallback).
        # JAMAIS passar ``None`` (Q11-E / Sentinel §12 — slots ``None``
        # corrompem registro interno e Set*Callback posteriores ficam
        # silenciosamente quebrados).
        state_cb = make_state_callback(self._state_queue)
        noop_cbs: list[Any] = [make_noop_callback(sig) for sig in NOOP_SLOT_SIGNATURES]

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
            slots_noop=len(noop_cbs),
            total_callback_slots=1 + len(noop_cbs),
        )

        # AC2 — chamada com 11 args: 3 credenciais + 1 state + 7 noop.
        # Manual §3.1: DLLInitializeMarketLogin(key, user, password, state,
        # trade, daily, priceBook, offerBook, histTrade, progress, tinyBook).
        # ``c_wchar_p`` import inline para coerência com WinDLL lazy import
        # acima — ambos só usados após checagem de plataforma.
        from ctypes import c_wchar_p

        ret: int = self._dll.DLLInitializeMarketLogin(
            c_wchar_p(key),
            c_wchar_p(user),
            c_wchar_p(password),
            state_cb,
            *noop_cbs,
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
            raise DLLInitError(err.code, err.name, err.message)

        log.info("dll.initialized", code=ret)

    # =================================================================
    # Wait for connected (AC5)
    # =================================================================

    def wait_market_connected(self, timeout: int = 60) -> bool:
        """Aguarda sequência canônica de connection states até MARKET_DATA conectado.

        Drena ``self._state_queue`` em loop (na thread do caller — NÃO no
        callback, R3) e retorna ``True`` quando recebe ``(MARKET_DATA, 2)``
        OU ``(MARKET_DATA, 4)`` — Q-AMB-01 / AC5: aceita ambos
        ``MARKET_WAITING=2`` e ``MARKET_CONNECTED=4`` como "market data
        conectado". Loga cada estado recebido com alias resolvido.

        Sequência típica (manual §3.2 L3317-3329):
            (0, 0) → LOGIN connected
            (1, 2) → ROTEAMENTO connected
            (2, X) → MARKET_DATA conectado (X ∈ {2, 4})
            (3, 0) → MARKET_LOGIN OK

        Args:
            timeout: Timeout total em segundos (default 60).

        Returns:
            ``True`` se MARKET_DATA conectou dentro do timeout; ``False``
            em timeout (sem raise — caller decide se aborta ou re-tenta).
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("dll.connected_timeout", timeout=timeout)
                return False
            try:
                conn_type, result = self._state_queue.get(timeout=remaining)
            except Empty:
                # Timeout dentro do get — segunda checagem de safety.
                log.warning("dll.connected_timeout", timeout=timeout)
                return False

            alias = self._resolve_state_alias(conn_type, result)
            log.info(
                "dll.market_state",
                conn_type=conn_type,
                result=result,
                alias=alias,
            )

            # AC5 / Q-AMB-01: aceita result ∈ {2, 4} para conn_type=2.
            if conn_type == MARKET_DATA and result in (
                MARKET_WAITING,
                MARKET_CONNECTED,
            ):
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

        IMPORTANTE (AC4): NÃO chamar ``_cb_refs.clear()`` aqui. ConnectorThread
        interna da DLL pode ainda referenciar callbacks pendentes; remover
        a referência Python-side liberaria o trampoline ctypes e crashar
        o processo (Q07-V). Apenas anular ``self._dll = None``.
        """
        if self._dll is None:
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
        self._dll.SetHistoryTradeCallbackV2(callback)
        log.info("dll.history_trade_callback_v2_registered")

    def set_progress_callback(self, callback: Any) -> None:
        """Registra callback de progresso de download histórico (Story 1.3).

        Wraps ``self._dll.SetProgressCallback(callback)``. ``callback`` DEVE
        vir de :func:`data_downloader.dll.callbacks.make_progress_callback` —
        já em ``_cb_refs``, faz APENAS ``put_nowait(int)`` (R3).

        Args:
            callback: Objeto ``WINFUNCTYPE``-wrapped (signature
                ``TProgressCallback``).

        Raises:
            DLLInitError: Se DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de set_progress_callback.",
            )
        self._cb_refs.append(callback)
        self._dll.SetProgressCallback(callback)
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

    def translate_trade(self, p_trade_handle: int, trade_struct: Any) -> int:
        """Desempacota handle V2 em ``TConnectorTrade`` struct (Story 1.3).

        Wraps ``self._dll.TranslateTrade(handle, byref(struct))``. **DEVE ser
        chamado em IngestorThread (FORA do callback)** — chamar a DLL de
        dentro do callback viola lei R3 / manual §4 L4382 / Q06-V.

        Caller é responsável por:

        1. Setar ``trade_struct.Version = 0`` antes da primeira chamada
           (main.py L328 demonstra).
        2. Copiar campos relevantes do struct ANTES da próxima chamada (a DLL
           reusa o buffer apontado pela próxima invocação).

        Args:
            p_trade_handle: Handle opaco recebido pelo callback V2 (1º item
                da tuple enfileirada).
            trade_struct: Instância de ``TConnectorTrade`` reutilizável (caller
                aloca uma vez e reusa entre chamadas — barato).

        Returns:
            Código retornado por ``TranslateTrade`` (``0 = NL_OK`` em sucesso,
            NL_* negativo em erro). Caller decide se descarta ou loga.

        Raises:
            DLLInitError: DLL não inicializada.
        """
        if self._dll is None:
            raise DLLInitError(
                -2147483646,
                "NL_NOT_INITIALIZED",
                "Chame initialize_market_only antes de translate_trade.",
            )
        from ctypes import byref

        rc: int = self._dll.TranslateTrade(p_trade_handle, byref(trade_struct))
        return rc


# =====================================================================
# Story 1.3 — Helpers de validação (módulo-level, reusáveis em testes)
# =====================================================================


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
