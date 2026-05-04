"""data_downloader.validation.data_validator — Gap detection (Quinn).

Owner: 🧪 Quinn (qa authority — gap detection contra calendário B3).
Co-reviewer: 💾 Sol (calendário B3 + INTEGRITY.md §6 DST policy).

Refs:

- ``docs/storage/INTEGRITY.md`` §2.6 (gap_detection contra calendário B3)
- :mod:`data_downloader.validation.calendar_b3` (placeholder de feriados)
- Story 2.1 — finding C4 do Plan Review 2026-05-03

Distingue 3 classes de gap:

- ``holiday`` — dia coincide com feriado B3 conhecido. Gap esperado.
- ``no_trades_day`` — dia útil B3 sem trades porque o contrato não
  estava vigente OU não houve negócio (raro para WDO/WIN, possível
  para nomes ilíquidos). Gap "aceitável".
- ``missing_download`` — dia útil B3 sem trades quando esperaríamos
  haver — esta é a única classe que indica problema real.

Política Quinn:

- Para o V1, classificação ``no_trades_day`` vs ``missing_download``
  exige cross-check com tabela ``contracts`` (vigência) que NÃO está
  totalmente populada ainda (Story 1.6). V1 marca como
  ``missing_download`` por default — Story futura cruza com vigência.
- Janela mínima auditada: ``>= 2020-01-01`` (DST B3 — INTEGRITY.md §6).
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal

import duckdb

from data_downloader.storage.catalog import Catalog
from data_downloader.validation.calendar_b3 import (
    b3_business_days_range,
    is_holiday,
)

GapClassification = Literal["holiday", "no_trades_day", "missing_download"]


@dataclass(frozen=True)
class GapReport:
    """Um gap detectado em um dia útil B3.

    Attributes:
        symbol: Código do contrato (ex.: ``"WDOJ26"``).
        gap_start: Início do gap (data, 00:00).
        gap_end: Fim do gap (mesma data, 23:59:59 — granularidade
            diária neste V1).
        business_days_missing: Quantos dias úteis B3 cobrem este gap.
            Para granularidade diária = 1.
        classification: ``holiday`` | ``no_trades_day`` |
            ``missing_download``.
    """

    symbol: str
    gap_start: datetime
    gap_end: datetime
    business_days_missing: int
    classification: GapClassification


@dataclass
class DataValidator:
    """Validador de gaps em datasets contra calendário B3.

    Args:
        data_dir: Raiz dos dados (mesma usada por writer/catalog).
        catalog: Instância de :class:`Catalog` (consultada para
            cross-check de vigência em version futura — Story 1.6+).
    """

    data_dir: Path
    catalog: Catalog

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)

    def _trade_days_in_dataset(
        self, symbol: str, start: date, end: date, *, exchange: str = "F"
    ) -> set[date]:
        """Retorna conjunto de dias (BRT NAIVE) com >=1 trade no Parquet.

        Lê via DuckDB sobre o glob de partições do símbolo. Limita por
        ``timestamp_ns`` derivado de ``[start, end]`` para pruning.
        """
        history_root = self.data_dir / "history"
        if not history_root.exists():
            return set()
        glob_pattern = str(history_root / exchange / symbol / "**" / "*.parquet")
        # Confere se há ao menos um arquivo (DuckDB falha em glob vazio).
        paths = sorted(p for p in glob.glob(glob_pattern, recursive=True) if ".tmp." not in p)
        if not paths:
            return set()

        start_ns = int(datetime.combine(start, time.min).timestamp() * 1_000_000_000)
        # +1 dia para incluir o último dia inteiro.
        end_dt = datetime.combine(end, time.max)
        end_ns = int(end_dt.timestamp() * 1_000_000_000)

        conn = duckdb.connect(":memory:")
        try:
            sql = """
                SELECT DISTINCT date_trunc('day', to_timestamp(timestamp_ns / 1e9))
                       AS trade_day
                FROM read_parquet(?)
                WHERE timestamp_ns BETWEEN ? AND ?
            """
            rows = conn.execute(sql, [paths, start_ns, end_ns]).fetchall()
        finally:
            conn.close()

        days: set[date] = set()
        for r in rows:
            v = r[0]
            if isinstance(v, datetime):
                days.add(v.date())
            elif isinstance(v, date):
                days.add(v)
        return days

    def detect_gaps(
        self,
        symbol: str,
        start: date,
        end: date,
        *,
        exchange: str = "F",
    ) -> list[GapReport]:
        """Detecta dias úteis B3 sem trades em ``[start, end]``.

        Para cada dia útil B3 no range:

        1. Se há ao menos 1 trade no Parquet → não é gap.
        2. Se não há trades, classifica via :meth:`classify_gap`.

        Args:
            symbol: Código do contrato.
            start: Início do range (inclusivo).
            end: Fim do range (inclusivo).
            exchange: ``"F"`` (default) ou ``"B"``.

        Returns:
            Lista de :class:`GapReport`, um por dia útil B3 sem trades.
            Ordenada por ``gap_start``.
        """
        if start > end:
            return []

        business_days = b3_business_days_range(start, end)
        if not business_days:
            return []

        trade_days = self._trade_days_in_dataset(symbol, start, end, exchange=exchange)

        gaps: list[GapReport] = []
        for d in business_days:
            if d in trade_days:
                continue
            classification = self.classify_gap(d)
            gaps.append(
                GapReport(
                    symbol=symbol,
                    gap_start=datetime.combine(d, time.min),
                    gap_end=datetime.combine(d, time.max),
                    business_days_missing=1,
                    classification=classification,
                )
            )
        return gaps

    def classify_gap(self, gap_day: date) -> GapClassification:
        """Classifica um dia sem trades.

        Args:
            gap_day: Dia para classificar.

        Returns:
            ``"holiday"`` se feriado B3; senão ``"missing_download"``
            (V1 — não cruza com vigência de contrato; Story futura
            adiciona ``"no_trades_day"`` via tabela ``contracts``).
        """
        if is_holiday(gap_day):
            return "holiday"
        # TODO Story 1.6+: cross-check com Catalog.contracts para emitir
        # "no_trades_day" quando contrato não estava vigente. V1 marca
        # tudo como missing_download por default — auditor humano
        # decide via WAIVER se aplicável.
        return "missing_download"


def validate_dataset(
    data_dir: Path,
    catalog: Catalog,
    symbols: list[str],
    start: date,
    end: date,
    *,
    exchange: str = "F",
) -> dict[str, list[GapReport]]:
    """Valida múltiplos símbolos em um único call.

    Args:
        data_dir: Raiz dos dados.
        catalog: Catálogo SQLite.
        symbols: Lista de códigos de contrato.
        start: Início do range (inclusivo).
        end: Fim do range (inclusivo).
        exchange: ``"F"`` (default) ou ``"B"``.

    Returns:
        Dict ``{symbol: list[GapReport]}`` — gaps detectados por
        símbolo. Símbolos sem gaps mapeiam para lista vazia.
    """
    validator = DataValidator(data_dir=data_dir, catalog=catalog)
    return {sym: validator.detect_gaps(sym, start, end, exchange=exchange) for sym in symbols}


__all__ = [
    "DataValidator",
    "GapClassification",
    "GapReport",
    "validate_dataset",
]
