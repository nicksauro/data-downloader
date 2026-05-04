"""data_downloader.orchestrator.contracts_probe — Validação de contrato via probe DLL.

Owner: Dex (impl) | Consult: Nelo (probe semantics) + Sol (validation_source).
Story 1.6 — AC6, AC7, AC10 (smoke gated).

Probe = chamada de :func:`download_chunk` em janela curta (1 dia útil) sobre
o ``contract_code``. Sucesso = ao menos 1 trade retornado; falha = log
estruturado + ``ProbeResult(success=False, reason=...)``. Em sucesso, o
catálogo é atualizado: ``validated_at = now()``,
``validation_source = 'dll_probe'``.

Não objetivos:
- Calcular vigência (responsabilidade da seed em CONTRACTS.md).
- Re-tentar probe automaticamente (caller decide; CLI tem flag explícita).
- Probe paralelo de N contratos (Story 1.7+, com chunker).

LEIS RESPEITADAS:
- R3: probe NÃO toca callbacks diretamente — reusa primitive
  ``download_chunk`` (Story 1.3) que já obedece R3.
- R9: probe valida hipótese existente; não cria nova entrada.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import structlog

from data_downloader.orchestrator.download_primitive import download_chunk

if TYPE_CHECKING:
    from data_downloader.dll.wrapper import ProfitDLL
    from data_downloader.storage.catalog import Catalog

__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "ProbeResult",
    "probe_contract",
]


log: structlog.stdlib.BoundLogger = structlog.get_logger(
    "data_downloader.orchestrator.contracts_probe"
)


PROBE_TIMEOUT_SECONDS: Final[int] = 300
"""Timeout reduzido para probe (5 min) — janela é só 1 dia útil; não
faz sentido herdar o default de 30 min do ``download_chunk``."""


@dataclass(frozen=True)
class ProbeResult:
    """Resultado da validação de um contrato via probe DLL.

    Atributos:
        success: ``True`` sse ao menos 1 trade foi retornado.
        contract_code: Código testado (ex.: ``"WDOJ26"``).
        sample_date: Data efetivamente usada no probe (BRT naive).
        trades_count: Total de trades recebidos no chunk.
        reason: ``None`` em sucesso; mensagem curta de diagnóstico em
            falha (ex.: ``"no_trades"``, ``"timeout"``,
            ``"nl_error: -7"``).
    """

    success: bool
    contract_code: str
    sample_date: date
    trades_count: int
    reason: str | None = None


def probe_contract(
    dll: ProfitDLL,
    catalog: Catalog,
    symbol_root: str,
    contract_code: str,
    sample_date: date | None = None,
    *,
    exchange: str = "F",
) -> ProbeResult:
    """Valida ``contract_code`` chamando ``GetHistoryTrades`` em 1 dia.

    Sequência:

    1. Resolve ``sample_date``: se ``None``, usa ``vigent_from + 1 dia``
       da linha em ``contracts`` (caller deve ter populado seed primeiro).
       Se ainda assim não houver linha, usa ``date.today() - 7 days``
       como fallback defensivo (probe ad-hoc fora de seed).
    2. Chama :func:`download_chunk` para a janela ``[sample_date 09:00,
       sample_date 18:00]`` com ``timeout=PROBE_TIMEOUT_SECONDS``.
    3. ``trades > 0`` → atualiza ``contracts.validated_at`` e
       ``validation_source = 'dll_probe'``.
    4. Falha (``trades == 0`` ou ``status != 'completed'``) → log
       structured warn + ``ProbeResult(success=False, reason=...)``.
       Não atualiza o catálogo.

    Args:
        dll: ProfitDLL já inicializada e conectada (ver Story 1.2).
        catalog: Catálogo SQLite (Story 1.5).
        symbol_root: Raiz do contrato (ex.: ``"WDO"``). Reservada para
            log estruturado e escalation a Sol/Nelo em probes recorrentes
            (não usada na lógica atual).
        contract_code: Código testado (ex.: ``"WDOJ26"``).
        sample_date: Data do probe. Se ``None``, deriva de
            ``contracts.vigent_from + 1 dia``. Caller pode forçar uma
            data específica (útil para mid-window probe).
        exchange: ``"F"`` (BMF, default — WDO/WIN) ou ``"B"`` (Bovespa).

    Returns:
        :class:`ProbeResult` — caller decide UI/escalation.
    """
    resolved_date = (
        sample_date if sample_date is not None else _resolve_sample_date(catalog, contract_code)
    )

    # Janela 09:00..18:00 — cobre pregão regular B3 sem precisar de
    # calendário/feriado (caso seja feriado, simplesmente retorna 0
    # trades e probe falha — operador escolhe outra data).
    dt_start = datetime(resolved_date.year, resolved_date.month, resolved_date.day, 9, 0, 0)
    dt_end = datetime(resolved_date.year, resolved_date.month, resolved_date.day, 18, 0, 0)

    log.info(
        "probe.start",
        contract_code=contract_code,
        sample_date=resolved_date.isoformat(),
        timeout=PROBE_TIMEOUT_SECONDS,
    )

    chunk = download_chunk(
        dll=dll,
        symbol=contract_code,
        exchange=exchange,
        dt_start=dt_start,
        dt_end=dt_end,
        timeout=PROBE_TIMEOUT_SECONDS,
    )

    trades_count = len(chunk.trades)

    if chunk.status != "completed":
        reason = f"status={chunk.status}" + (
            f" nl_error={chunk.nl_error_code}" if chunk.nl_error_code else ""
        )
        log.warning(
            "probe.failed",
            contract_code=contract_code,
            sample_date=resolved_date.isoformat(),
            reason=reason,
            trades_count=trades_count,
        )
        return ProbeResult(
            success=False,
            contract_code=contract_code,
            sample_date=resolved_date,
            trades_count=trades_count,
            reason=reason,
        )

    if trades_count == 0:
        log.warning(
            "probe.no_trades",
            contract_code=contract_code,
            sample_date=resolved_date.isoformat(),
        )
        return ProbeResult(
            success=False,
            contract_code=contract_code,
            sample_date=resolved_date,
            trades_count=0,
            reason="no_trades",
        )

    # Sucesso — atualiza catálogo (AC7).
    _mark_validated(catalog, contract_code, source="dll_probe")
    log.info(
        "probe.success",
        contract_code=contract_code,
        sample_date=resolved_date.isoformat(),
        trades_count=trades_count,
    )
    return ProbeResult(
        success=True,
        contract_code=contract_code,
        sample_date=resolved_date,
        trades_count=trades_count,
        reason=None,
    )


# =====================================================================
# Helpers internos
# =====================================================================


def _resolve_sample_date(catalog: Catalog, contract_code: str) -> date:
    """Resolve ``sample_date`` default = ``vigent_from + 1 dia``.

    Story 4.2 (COUNCIL-29) — equity tickers (``vigent_from=1900-01-01``)
    são detectados via :func:`is_equity_ticker` e usam ``today() - 7d``
    como sample (vigência infinita não tem ponto canônico de probe).

    Se nenhuma linha em ``contracts`` para ``contract_code``, fallback
    para ``date.today() - 7 dias``. Não levanta — probe ad-hoc é caso
    válido durante onboarding de novo contrato.
    """
    from data_downloader.orchestrator.chunker import is_equity_ticker

    # Equity: vigência infinita não dá ponto canônico — usa today-7d.
    if is_equity_ticker(contract_code):
        return date.today() - timedelta(days=7)

    conn = catalog._conn_or_raise()
    row = conn.execute(
        "SELECT vigent_from FROM contracts WHERE contract_code = ? LIMIT 1",
        (contract_code,),
    ).fetchone()
    if row is None:
        return date.today() - timedelta(days=7)
    raw = row["vigent_from"]
    # Reaproveita o parser do módulo contracts (formato canônico SQLite).
    from data_downloader.orchestrator.contracts import _coerce_to_datetime

    base = _coerce_to_datetime(raw).date()
    return base + timedelta(days=1)


def _mark_validated(catalog: Catalog, contract_code: str, *, source: str) -> None:
    """Atualiza ``validated_at`` (now UTC) e ``validation_source``.

    UPDATE direto — não falha se 0 linhas afetadas (probe ad-hoc pode
    ter sido feito antes de ``populate_contracts_from_seed``; logamos
    e retornamos).
    """
    conn = catalog._conn_or_raise()
    now_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    with catalog._transaction():
        cur = conn.execute(
            "UPDATE contracts SET validated_at = ?, validation_source = ? "
            "WHERE contract_code = ?",
            (now_iso, source, contract_code),
        )
        if cur.rowcount == 0:
            log.warning(
                "probe.mark_validated_no_row",
                contract_code=contract_code,
                hint="run 'contracts add' or 'populate_contracts_from_seed' first",
            )
        else:
            log.info(
                "probe.mark_validated",
                contract_code=contract_code,
                source=source,
                validated_at=now_iso,
            )


def _is_sqlite_error(exc: BaseException) -> bool:
    """Helper de type-guard para excepts em testes (não usado em runtime)."""
    return isinstance(exc, sqlite3.Error)
