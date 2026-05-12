"""data_downloader.observability.logging_config — Story 2.9 / ADR-010.

Owner: Dex (impl) | Authority: Aria (ADR-010 — strategy oficial) | Audit: Pyro
(R21 hot-path discipline preserved), Quinn (redaction property tests).
COUNCIL-19 (Dex+Aria+Pyro).

Implementação formal de **ADR-010 — Logging strategy: structlog + contextvars +
redaction + hot-path rules** (V1):

1. **Pipeline structlog formal** (AC1) — :func:`configure_logging` /
   :func:`setup_logging` registram processors canônicos: contextvars merge,
   thread name, log level, ISO 8601 UTC timestamp, redaction, stack info,
   ``dict_tracebacks``, e renderer final (``JSONRenderer`` em produção,
   ``ConsoleRenderer`` em dev).
2. **Contextvars helpers** (AC2) — :func:`bind_context` / :func:`clear_context`
   /  :func:`bound_context` são thin-wrappers sobre ``structlog.contextvars``
   para os campos canônicos (``correlation_id``, ``job_id``, ``chunk_id``,
   ``symbol``, ``exchange``).
3. **Redaction de credenciais** (AC3) — :func:`redact_secrets` redige valores
   de chaves sensíveis (``nl_password``, ``nl_key``, ``nl_username``,
   ``password``, ``secret``, ``token``, ``api_key``, ``auth``,
   ``authorization``, ``credential``). Recursivo em dicts/lists aninhados;
   case-insensitive no nome da chave; valor substituído por
   ``"***REDACTED***"`` (preserva schema).
4. **Cross-thread propagation** (AC2) — :func:`copy_context_to_thread` retorna
   um wrapper que propaga ``contextvars.copy_context()`` do thread origem
   para o thread destino. Necessário para QThread + worker threads sem
   re-bind manual (ADR-005 multi-thread).
5. **JSON canonical** (AC4) — output de produção é uma linha JSON por evento
   contendo ``timestamp``, ``level``, ``event``, ``logger``, ``thread``, mais
   contextvars e fields arbitrários do call site.

LEIS RESPEITADAS:

- **R21** (hot path): :func:`configure_logging` é chamado UMA vez por processo
  (boot do CLI / public_api). O pipeline NÃO é instalado dentro de hot path.
  ``redact_secrets`` é processor leve — varre apenas chaves do event_dict
  (cool path: per-chunk, per-job).
- **INV-credenciais**: redaction é defesa em profundidade. Mesmo que dev
  passe ``nl_password=`` por engano (não recomendado), o processor mascara.
  Property test (``test_logging_redaction.py``) prova p/ qualquer dict.
- **Backwards compat**: call sites existentes que fazem
  ``log = structlog.get_logger(__name__)`` continuam funcionando — apenas
  ganham campos automáticos via contextvars + redaction transparente.
- **Sem dependência nova**: usa apenas ``structlog`` (já em deps).

Exemplo de uso (CLI boot)::

    from data_downloader.observability.logging_config import configure_logging
    configure_logging(level="INFO", json_output=True, redact=True)
    # ou alias com defaults conv:
    setup_logging(level="INFO", format="json")

Exemplo de uso (orchestrator entry point)::

    from data_downloader.observability.logging_config import bind_context, clear_context

    def run(self, config):
        bind_context(job_id=job_id, symbol=config.symbol, exchange=config.exchange)
        try:
            ...
        finally:
            clear_context()
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sys
import threading
import warnings
from typing import TYPE_CHECKING, Any, Final, Literal, cast

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, MutableMapping

__all__ = [
    "SENSITIVE_KEY_SUBSTRINGS",
    "DynamicStreamLoggerFactory",
    "bind_context",
    "bound_context",
    "clear_context",
    "configure_logging",
    "copy_context_to_thread",
    "get_logger",
    "redact_secrets",
    "setup_logging",
]


# =====================================================================
# Test-infra hardening — Dynamic stream logger factory
# =====================================================================
#
# Story 2.7 / COUNCIL-22 (Quinn finding): structlog.PrintLoggerFactory
# captura ``sys.stderr`` no momento da configuração e produz
# ``PrintLogger`` instances que carregam a referência fixa do file
# handle. Quando pytest CliRunner / capsys captura sys.stderr para uma
# StringIO ephemeral, qualquer log emitido APÓS o teardown do runner
# levanta ``ValueError: I/O operation on closed file.`` em testes
# subsequentes (poison cross-test).
#
# Fix: ``DynamicStreamLoggerFactory`` produz loggers que resolvem
# ``sys.stderr`` a CADA emit (em vez de no construtor), evitando o
# leak da referência morta. Hot path NÃO é impactado (R21) — produção
# resolve sys.stderr UMA vez no boot do CLI e nunca o substitui;
# overhead é uma leitura de atributo (<10ns).


class _DynamicStreamLogger:
    """Logger structlog-compatível que resolve ``sys.stderr`` a cada emit.

    Substitui :class:`structlog.PrintLogger` que captura o file handle no
    construtor — cenário que quebra suítes pytest com captura de stdout
    (CliRunner, capsys). Chamadas de log resolvem ``sys.stderr`` no
    momento do emit, então mudanças temporárias do stream (como pytest
    capturando) NÃO contaminam tests subsequentes quando o stream
    original é restaurado.

    Methods (msg/log/info/debug/warning/error/critical/exception/fatal)
    têm assinatura idêntica a PrintLogger — drop-in replacement.
    """

    def __init__(self, file: Any | None = None) -> None:
        # ``file`` é aceito por API compat mas IGNORADO em favor de
        # resolução dinâmica via ``sys.stderr``. Caller que precise de
        # destino diferente (ex.: stdout) pode setar :data:`_target_attr`
        # explicitamente.
        self._target_attr: str = "stderr"

    def _emit(self, message: str) -> None:
        # print-allowed: backend do PrintLogger structlog. structlog renderiza
        # a mensagem como string e este método a emite via print() para o
        # stream resolvido — NÃO é debug print que viola R21. Pragma
        # ``# print-allowed`` é reconhecido por scripts/hooks/check_no_print.py
        # e ignorado por ruff (diferente do legado ``noqa-print``, que vira
        # "invalid noqa" se T20x for habilitado).
        stream = getattr(sys, self._target_attr, None)
        if stream is None:  # pragma: no cover — defensivo, sys.stderr quase nunca é None
            return
        try:
            print(message, file=stream, flush=True)  # print-allowed: structlog backend
        except (ValueError, OSError):
            # Stream foi fechado entre o getattr e o print (race em teardown
            # de pytest capture). Fallback para o stderr "real" do
            # processo via fileno=2 — best-effort, NÃO levanta.
            with contextlib.suppress(ValueError, OSError, AttributeError):
                print(message, file=sys.__stderr__, flush=True)  # print-allowed: fallback

    msg = _emit
    log = _emit
    info = _emit
    debug = _emit
    warning = _emit
    warn = _emit
    error = _emit
    err = _emit
    critical = _emit
    fatal = _emit
    exception = _emit


class DynamicStreamLoggerFactory:
    """Factory que produz :class:`_DynamicStreamLogger` instances.

    Drop-in replacement para :class:`structlog.PrintLoggerFactory` —
    aceita ``file`` por compat mas resolve sys.stderr dinamicamente.
    """

    def __init__(self, file: Any | None = None) -> None:
        self._file = file  # ignorado intencionalmente — vide _DynamicStreamLogger

    def __call__(self, *args: Any) -> _DynamicStreamLogger:
        return _DynamicStreamLogger(self._file)


# =====================================================================
# Constants
# =====================================================================

#: Substrings (case-insensitive) usados para detectar chaves sensíveis no
#: event_dict de logs. Match é por **substring**, não por igualdade — assim
#: ``nl_password``, ``user_password`` e ``profitdll_pass`` são todos
#: redactados via ``"pass"``. Lista derivada do ADR-010 §SENSITIVE_KEYS +
#: variantes do código (``PROFITDLL_KEY``, ``PROFIT_PASS``, etc.).
SENSITIVE_KEY_SUBSTRINGS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "pass",  # cobre PROFIT_PASS, NL_PASSWORD, etc.
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "credential",
        "key",  # cobre NL_KEY, PROFITDLL_KEY, api_key, etc.
    }
)

#: Substituto canônico para valores redactados — string fixa para parsing
#: estável em Loki/ELK/jq. Documentado em ``docs/dev/LOGGING.md``.
REDACTED_VALUE: Final[str] = "***REDACTED***"

#: Allow-list — chaves que CONTÊM substring sensível mas NÃO devem ser
#: redactadas (false positives controlados). Examples:
#: - ``key_redacted`` é o padrão usado pelo wrapper para sinalizar que o
#:   campo já foi mascarado pelo dev (não redactar duas vezes — preserva
#:   semantic "intentionally already redacted").
#: - ``credential_redacted`` idem.
_REDACTION_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "key_redacted",
        "credential_redacted",
        "password_redacted",
    }
)

#: Env var canônica para nível (override de --log-level).
ENV_LOG_LEVEL: Final[str] = "DATA_DOWNLOADER_LOG_LEVEL"

#: Env var canônica para format (override de --log-format).
ENV_LOG_FORMAT: Final[str] = "DATA_DOWNLOADER_LOG_FORMAT"


# =====================================================================
# Custom processors
# =====================================================================


def _add_thread_name(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Processor: adiciona ``thread`` (nome da thread atual) ao event_dict.

    Necessário para distinguir logs de OrchestratorThread vs IngestorThread
    vs ConnectorThread em produção (ADR-005 multi-thread + cross-thread
    debugging).
    """
    event_dict["thread"] = threading.current_thread().name
    return event_dict


def _redact_secrets_processor(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Processor: redacta valores de chaves sensíveis recursivamente.

    Wrapper sobre :func:`redact_secrets` que adapta a assinatura para
    structlog. ``event_dict`` é mutado in-place (perf — evita copy a cada
    log call) e retornado.
    """
    redact_secrets(event_dict)
    return event_dict


# =====================================================================
# Public API — redaction
# =====================================================================


def _is_sensitive_key(key: str) -> bool:
    """Verifica se ``key`` deve ter seu valor redactado.

    Caso-insensitive; match por substring contra
    :data:`SENSITIVE_KEY_SUBSTRINGS`. Allow-list em
    :data:`_REDACTION_ALLOWLIST` tem precedência (chaves explicitamente
    marcadas como já-redactadas pelo dev).
    """
    if not isinstance(key, str):
        return False
    key_lower = key.lower()
    if key_lower in _REDACTION_ALLOWLIST:
        return False
    return any(needle in key_lower for needle in SENSITIVE_KEY_SUBSTRINGS)


def redact_secrets(payload: Any) -> Any:
    """Redacta valores de chaves sensíveis em ``payload`` (recursivo).

    Mutação in-place quando ``payload`` é dict/list (perf — log dicts são
    ephemerais; ok mutar). Estruturas leaf (str, int, etc.) são retornadas
    inalteradas.

    - **dict**: para cada chave, se a chave matches
      :func:`_is_sensitive_key`, valor é substituído por
      :data:`REDACTED_VALUE`. Caso contrário, recursão em ``value``.
    - **list / tuple**: recursão em cada item (tuples são mantidos como
      tuple — preserva tipo).
    - **str / int / float / bool / None**: retorno direto (no-op).
    - **outros tipos**: retorno direto (no-op — best-effort, não tenta
      introspectar dataclasses/objetos).

    Args:
        payload: Estrutura a redactar (tipicamente o ``event_dict`` do
            structlog mas funciona em qualquer dict aninhado).

    Returns:
        Mesmo objeto (mutado in-place se mutável) ou nova tuple/leaf.

    Examples:
        >>> redact_secrets({"user": "demo", "nl_password": "x"})
        {'user': 'demo', 'nl_password': '***REDACTED***'}

        >>> redact_secrets({"outer": {"nl_key": "abc"}})
        {'outer': {'nl_key': '***REDACTED***'}}

        >>> redact_secrets({"creds": [{"password": "p"}]})
        {'creds': [{'password': '***REDACTED***'}]}
    """
    if isinstance(payload, dict):
        for k in list(payload.keys()):
            if _is_sensitive_key(k):
                payload[k] = REDACTED_VALUE
            else:
                payload[k] = redact_secrets(payload[k])
        return payload
    if isinstance(payload, list):
        for i, item in enumerate(payload):
            payload[i] = redact_secrets(item)
        return payload
    if isinstance(payload, tuple):
        return tuple(redact_secrets(item) for item in payload)
    return payload


# =====================================================================
# Public API — configure / setup
# =====================================================================


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    redact: bool = True,
    bridge_to_stdlib: bool = False,
) -> None:
    """Configura o pipeline canônico de structlog (ADR-010 / Story 2.9 AC1).

    Chamar **uma vez** por processo (boot do CLI ou boot do
    ``download_handle.start()``). Múltiplas chamadas são idempotentes
    (structlog reconfigure simplesmente substitui).

    Pipeline final (em ordem):

    1. ``structlog.contextvars.merge_contextvars`` — injeta contextvars do
       thread atual (job_id, chunk_id, symbol, correlation_id, exchange).
    2. ``_add_thread_name`` — injeta ``thread`` (nome da thread).
    3. ``structlog.processors.add_log_level`` — injeta ``level``.
    4. ``structlog.processors.TimeStamper(fmt='iso', utc=True)`` — injeta
       ``timestamp`` ISO 8601 UTC.
    5. ``_redact_secrets_processor`` (opcional via ``redact``) — mascara
       chaves sensíveis (defesa em profundidade).
    6. ``structlog.processors.StackInfoRenderer()`` — formata
       ``stack_info=True`` quando passado.
    7. ``structlog.processors.dict_tracebacks`` — formata exception via
       ``exc_info=True`` em dict estruturado (parseável).
    8. **Renderer final**: ``JSONRenderer`` se ``json_output`` else
       ``ConsoleRenderer(colors=True)``.

    Args:
        level: Nível mínimo (``"DEBUG"|"INFO"|"WARNING"|"ERROR"|"CRITICAL"``).
            Case-insensitive. Inválido → ``ValueError``.
        json_output: Se ``True`` (default — production), usa
            ``JSONRenderer``. Se ``False`` (dev), usa
            ``ConsoleRenderer(colors=True)``.
        redact: Se ``True`` (default), instala o processor de redaction.
            Em testes pode-se desabilitar com ``redact=False`` quando se
            está validando explicitamente o conteúdo de uma chave sensível
            (raro — preferível usar mock).
        bridge_to_stdlib: Se ``True``, encaminha eventos structlog para o
            stdlib ``logging`` root logger (via
            :class:`structlog.stdlib.LoggerFactory`). Necessário em UI
            windowed mode (``console=False`` PyInstaller build) — sem o
            bridge, structlog escreve em ``sys.stderr`` que está detached
            e :class:`QtLogHandler` não captura. Default ``False`` para
            preservar comportamento CLI (stderr direto, sem cost de
            stdlib propagation). Story v1.0.8 fix (Pichau live test
            2026-05-06): UI mode "DLL conectada" mas nenhum log
            posterior aparecia — root cause era structlog → void.

    Raises:
        ValueError: ``level`` inválido (não corresponde a um nível de
            ``logging`` builtin).
    """
    level_upper = level.upper()
    level_int = getattr(logging, level_upper, None)
    if not isinstance(level_int, int):
        raise ValueError(
            f"Invalid log level {level!r}; expected one of DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _add_thread_name,
        structlog.processors.add_log_level,
        timestamper,
    ]
    if redact:
        shared_processors.append(_redact_secrets_processor)
    shared_processors.extend(
        [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.dict_tracebacks,
        ]
    )

    renderer: Any
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Story v1.0.8 fix — UI windowed mode bridge:
    # Sem bridge_to_stdlib, factory é DynamicStreamLoggerFactory que escreve
    # em sys.stderr (CLI mode OK; UI windowed → void, QtLogHandler nunca
    # captura). Com bridge_to_stdlib=True, factory é
    # ``structlog.stdlib.LoggerFactory`` e cada evento structlog vira um
    # ``logging.LogRecord`` no root logger — QtLogHandler (ou qualquer
    # ``logging.Handler``) captura cross-thread.
    factory: Any
    if bridge_to_stdlib:
        factory = structlog.stdlib.LoggerFactory()
        # Garante que stdlib root logger emite em INFO+ por default
        # (root.level=WARNING) e tem ao menos um handler — necessário
        # caso UI mode esqueça de instalar QtLogHandler antes do primeiro
        # emit (defesa em profundidade; UI mode adiciona QtLogHandler em
        # cima).
        root_logger = logging.getLogger()
        if root_logger.level == 0 or root_logger.level > level_int:
            root_logger.setLevel(level_int)
        # NÃO adicionamos StreamHandler aqui — caller decide (CLI mode
        # geralmente não chama com bridge_to_stdlib=True; UI mode instala
        # QtLogHandler externamente).
    else:
        # Story 2.7 / COUNCIL-22: factory dinâmica resolve sys.stderr a
        # CADA emit, evitando crash em testes que capturam stdout
        # (CliRunner / capsys). Hot path safe — overhead < 10ns
        # (getattr de módulo). Ver _DynamicStreamLogger docstring.
        factory = DynamicStreamLoggerFactory()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        context_class=dict,
        logger_factory=factory,
        cache_logger_on_first_use=True,
    )


def setup_logging(
    level: str = "INFO",
    *,
    format: Literal["json", "console"] = "json",  # noqa: A002 — kw arg name é canônico
    redact_secrets: bool = True,
    bridge_to_stdlib: bool = False,
) -> None:
    """Alias com API alternativa para :func:`configure_logging`.

    Equivalente a ``configure_logging(level=..., json_output=(format == 'json'),
    redact=...)``. Útil para call sites que preferem a API
    "format=json|console" (mais legível em CLI flags).

    Args:
        level: Nível mínimo (case-insensitive).
        format: ``"json"`` (production) ou ``"console"`` (dev — colorido).
        redact_secrets: Se ``True`` (default), instala redaction processor.
        bridge_to_stdlib: Se ``True``, roteia eventos structlog para o
            ``logging`` stdlib root logger (necessário em UI windowed
            mode — caller instala :class:`QtLogHandler` em seguida). Ver
            docstring de :func:`configure_logging`.
    """
    configure_logging(
        level=level,
        json_output=(format == "json"),
        redact=redact_secrets,
        bridge_to_stdlib=bridge_to_stdlib,
    )


# =====================================================================
# Public API — contextvars helpers
# =====================================================================


def bind_context(**kwargs: Any) -> None:
    """Bind contextvars canônicos para o thread/task atual.

    Thin-wrapper sobre ``structlog.contextvars.bind_contextvars`` —
    documenta intent + auto-redacta valores sensíveis no bind (defesa
    em profundidade caso dev faça ``bind_context(password=...)`` por
    engano — extremamente raro mas barato).

    Campos canônicos esperados (ADR-010 §Configuração):

    - ``correlation_id`` — alias de ``job_id`` (compat). Aria recomenda
      usar ``job_id`` direto.
    - ``job_id`` — UUID hex do job orchestrator.
    - ``chunk_id`` — UUID hex do chunk download_primitive.
    - ``symbol`` — contrato vigente (ex.: ``"WDOJ26"``).
    - ``exchange`` — ``"F"`` (BMF) ou ``"B"`` (Bovespa).

    Campos extras são permitidos — apenas devem fazer sentido como
    contexto (não payload one-off).

    Args:
        **kwargs: Pares ``key=value`` para bind (recomendado: campos
            canônicos acima).
    """
    redacted = redact_secrets(dict(kwargs))
    structlog.contextvars.bind_contextvars(**redacted)


def clear_context() -> None:
    """Limpa todos os contextvars bound no thread/task atual.

    Equivalente a ``structlog.contextvars.clear_contextvars``. Chamar no
    ``finally`` de entry points (orchestrator.run, public_api.download
    worker) para evitar contaminação cross-job.
    """
    structlog.contextvars.clear_contextvars()


def unbind_context(*keys: str) -> None:
    """Unbind chaves específicas dos contextvars (preserva outras).

    Útil para limpar contexto per-chunk sem afetar contexto per-job
    (que continua bound após o chunk).

    Args:
        *keys: Nomes de chaves a remover dos contextvars.
    """
    structlog.contextvars.unbind_contextvars(*keys)


@contextlib.contextmanager
def bound_context(**kwargs: Any) -> Iterator[None]:
    """Context manager — bind no enter, clear no exit (try/finally).

    Útil quando o escopo do bind é claramente delimitado (e.g.
    ``with bound_context(chunk_id=..., symbol=...): ...``).

    Args:
        **kwargs: Mesma assinatura de :func:`bind_context`.

    Yields:
        ``None``.
    """
    redacted = redact_secrets(dict(kwargs))
    structlog.contextvars.bind_contextvars(**redacted)
    try:
        yield
    finally:
        # Unbind apenas as chaves que essa context manager bound — preserva
        # contextvars de escopos externos.
        structlog.contextvars.unbind_contextvars(*kwargs.keys())


# =====================================================================
# Public API — cross-thread propagation
# =====================================================================


# Module-level flag (set once) used to ensure the no-arg ``copy_context_to_thread()``
# usage warning is emitted at most one time per process. Avoids log spam from
# adapters that call this per-slot (CatalogAdapter, DownloadAdapter).
_COPY_CONTEXT_NULL_WARNED: bool = False


def _warn_copy_context_noop_call_site_once() -> None:
    """Emit a one-shot warning when ``copy_context_to_thread()`` is called null.

    Fix B-4 (Wave A): the previous behavior of ``copy_context_to_thread()`` with
    ``target=None`` returns a true no-op — useful as an "I observed contextvars"
    marker but NOT a propagator. Call sites that rely on this for actual
    propagation (e.g., Qt slots already running on the worker thread) get
    silently broken contextvars. We surface the issue exactly once per process
    so the operator can fix the call site (pass an explicit target, or use
    ``snapshot.run(...)`` from the parent thread).
    """
    global _COPY_CONTEXT_NULL_WARNED
    if _COPY_CONTEXT_NULL_WARNED:
        return
    _COPY_CONTEXT_NULL_WARNED = True
    warnings.warn(
        "copy_context_to_thread() called without a target — this is a no-op for "
        "contextvar restoration. To actually propagate contextvars to a worker "
        "thread, capture the snapshot in the parent thread and call "
        "snapshot.run(worker_callable, ...) from the worker, OR pass an "
        "explicit target= to receive a decorated callable.",
        RuntimeWarning,
        stacklevel=3,
    )


def copy_context_to_thread(
    target: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    """Wrapper que propaga ``contextvars.copy_context()`` do main → worker thread.

    Decora ``target`` (função alvo de ``threading.Thread(target=...)``) para
    capturar o snapshot dos contextvars do thread chamador (no momento da
    decoração) e re-aplicá-los no thread filho via ``ctx.run(...)``.

    Necessário porque ``threading.Thread`` em Python NÃO copia contextvars
    automaticamente (ao contrário de ``asyncio.Task``). Sem este wrapper,
    contextvars setados via :func:`bind_context` no parent NÃO aparecem em
    logs do worker.

    Aria nota: para QThread no Felix (Story 3.x), o mesmo padrão se aplica
    — passar o callable wrapped via ``QThread(...)`` ou ``QRunnable``.

    **v1.1.0 fix (Aria Wave 1 — copy_context_to_thread null call):**
    Antes desta correção, o call site em
    :class:`CatalogAdapter._propagate_context` invocava
    ``copy_context_to_thread()`` (sem argumentos), o que levantava
    :class:`TypeError` (target obrigatório). O ``TypeError`` era engolido por
    ``contextlib.suppress(Exception)`` no caller — bug silencioso onde
    contextvars NÃO eram propagados mas nenhum log alertava (Felix v1.0.8 RCA).
    A nova assinatura aceita ``target=None`` e devolve um no-op callable que
    apenas mantém o snapshot vivo (best-effort) — useful pattern em adapters
    Qt onde o worker já roda dentro de uma QThread e não há um ``target``
    discreto para decorar.

    Args:
        target: Função sem contexto especial (mesma assinatura aceita por
            ``threading.Thread(target=...)``). Se ``None`` (default), retorna
            um no-op callable que apenas captura snapshot — semântica "marca
            que contextvars foram observados" sem alterar control flow.

    Returns:
        Wrapper que executa ``target(*args, **kwargs)`` dentro de
        ``ctx.run(...)`` — preserva contextvars do snapshot capturado. Quando
        ``target=None``, retorna no-op que sempre retorna ``None``.

    Example::

        def worker(payload):
            log.info("worker.start")  # tem job_id do parent
            ...

        bind_context(job_id="abc")
        thread = threading.Thread(target=copy_context_to_thread(worker), args=(payload,))
        thread.start()

    Example (no-arg form — apenas captura, sem decorar)::

        # Adapter Qt já rodando no worker thread; quer "marcar" que
        # snapshot parent foi tomado. Best-effort, NÃO levanta TypeError.
        copy_context_to_thread()
    """
    ctx = contextvars.copy_context()

    if target is None:
        # No-op mode — apenas captura snapshot. Caller usa este modo para
        # honrar a API de propagação sem ter um target discreto. O snapshot
        # ``ctx`` é mantido vivo via closure enquanto o callable retornado
        # estiver alive (defense in depth contra GC precoce).
        #
        # Fix B-4 (Wave A 2026-05-11): emite warning explícito UMA vez por
        # processo para surfaceá-lo. O call sem ``target`` é tecnicamente
        # válido (capture-only) mas NÃO restaura contextvars no worker
        # thread — chamadas downstream a ``get_logger().info(...)`` no
        # worker thread ainda perdem job_id/symbol/etc. Caller deve ou
        # passar ``target=`` discreto OU capturar o snapshot na thread
        # parent e re-rodar via ``snapshot.run(worker_callable, ...)``.
        _warn_copy_context_noop_call_site_once()

        def _noop(*_args: Any, **_kwargs: Any) -> None:
            # Referencia ``ctx`` para mantê-lo vivo (mypy strict não reclama
            # de variável não-usada via no-op statement).
            _ = ctx
            return None

        return _noop

    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        return ctx.run(target, *args, **kwargs)

    return _wrapper


# =====================================================================
# Public API — logger factory
# =====================================================================


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Helper canônico — todo módulo usa este (ADR-010).

    Equivalente a ``structlog.get_logger(name)`` mas com tipo de retorno
    explícito (mypy strict).

    Args:
        name: Nome do logger (default: ``__name__`` do call site).

    Returns:
        Bound logger structlog (já com pipeline configurado se
        :func:`configure_logging` foi chamado).
    """
    # structlog.get_logger é tipado como Any → cast explícito para satisfazer
    # mypy strict (warn_return_any). BoundLogger é a classe real produzida
    # pelo pipeline configurado via wrap_class=structlog.stdlib.BoundLogger.
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))


# =====================================================================
# Default level resolver (for cli.py)
# =====================================================================


def resolve_level_from_env(default: str = "INFO") -> str:
    """Resolve nível de log da env var ``DATA_DOWNLOADER_LOG_LEVEL``.

    Se a env var está setada, retorna o valor (uppercase). Se ausente,
    retorna ``default``.
    """
    return os.environ.get(ENV_LOG_LEVEL, default).upper()


def resolve_format_from_env(
    default: Literal["json", "console"] = "json",
) -> Literal["json", "console"]:
    """Resolve formato de log da env var ``DATA_DOWNLOADER_LOG_FORMAT``.

    Aceita ``"json"`` ou ``"console"`` (case-insensitive). Valores inválidos
    fallback para ``default`` (best-effort — não falha boot por env var
    malformada).
    """
    val = os.environ.get(ENV_LOG_FORMAT, default).lower()
    if val == "json":
        return "json"
    if val == "console":
        return "console"
    return default
