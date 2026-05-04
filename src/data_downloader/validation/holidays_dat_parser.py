"""data_downloader.validation.holidays_dat_parser — Parser de ``holidays.dat`` Nelogica.

Owner: 🗝️ Nelo (DLL authority — formato proprietário Nelogica) +
💾 Sol (custodian — consume em :mod:`calendar_b3`).

Story 2.5 — substitui tabela hardcoded de feriados B3 (2025-2026) por leitura
do arquivo ``profitdll/DLLs/Win64/holidays.dat`` distribuído pela Nelogica.

Formato descoberto (validation_source: ``reverse_engineered`` — manual
ProfitDLL não documenta o arquivo, mas formato é texto plano e deterministicamente
parseável). Detalhes completos em ``docs/dll/HOLIDAYS_DAT_FORMAT.md``.

**Layout resumido:**

- Encoding: UTF-8 com BOM (``\\xef\\xbb\\xbf``).
- Line endings: CRLF (``\\r\\n``).
- Primeira linha: comentário ``//DD/MM/YYYY HH:MM:SS.fff`` com timestamp de geração.
- Linhas de dados: ``EE:YYYYMMDDHHMMSSF:OPEN:CLOSE:DESCRICAO``
  - ``EE``: 2 dígitos = código ASCII do exchange (66='B' Bovespa, 70='F' BMF,
    35='#' B3 unified, 88='X', 99='c' — todos B3-related para feriados BR).
  - ``YYYYMMDDHHMMSSF``: 15 dígitos. Os primeiros 8 (``YYYYMMDD``) são a data;
    o restante é hora padronizada para ``000000000`` em feriados full-day.
  - ``OPEN`` / ``CLOSE``: opcionais. Vazios = feriado de dia inteiro. Preenchidos
    (formato ``YYYYMMDDHHMMSSF``) = pregão parcial (ex: meio-pregão Cinzas).
  - ``DESCRICAO``: texto livre (Carnaval, Tiradentes, etc.).

**Política Sol+Nelo (mini-council COUNCIL-16):**

- Apenas linhas com ``OPEN`` vazio são tratadas como feriado full-day.
- Pregão parcial (Cinzas, vésperas) NÃO entra como feriado em V1 — é dia útil
  com sessão reduzida. Story futura pode adicionar suporte.
- Filtramos apenas exchanges B3-related; ignora NYSE (89='Y'), NASDAQ (96='`'),
  outros mercados estrangeiros.
- Cobertura observada: 2013-2035 (23 anos). Cobre amplamente o range mínimo
  Sol policy ``>= 2020`` (M17 DST boundary).

**Fallback graceful:**

- Arquivo ausente → :class:`HolidaysDatNotFoundError` (consumer deve fallback).
- Arquivo malformado → :class:`HolidaysDatParseError` com offset.
- Cache via mtime: parser cacheia resultado por path; re-parse se mtime mudar.
"""

from __future__ import annotations

import re
import threading
from datetime import date
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


# Códigos de exchange B3-related no holidays.dat. Validados empiricamente
# contra o arquivo distribuído pela Nelogica em 2025-12-29 (33976 bytes,
# 843 linhas de dados, cobertura 2013-2035).
#
# - '66' = ASCII 'B' = Bovespa (legado pré-merger)
# - '70' = ASCII 'F' = BMF (legado pré-merger)
# - '35' = ASCII '#' = B3 unified (post-merger)
# - '88' = ASCII 'X' = código observado para alguns feriados B3 raros
# - '99' = ASCII 'c' = código observado pós-2017
#
# Exchanges estrangeiros (89='Y' NYSE, 96='`' NASDAQ, 80='P', etc.) são
# IGNORADOS — não afetam pregão B3.
B3_EXCHANGE_CODES: frozenset[str] = frozenset({"35", "66", "70", "88", "99"})

# Regex para parsear linha de dado (5 campos separados por ':').
_LINE_PATTERN = re.compile(
    r"^(?P<exchange>\d+):"
    r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})\d+:"
    r"(?P<open>\d*):"
    r"(?P<close>\d*):"
    r"(?P<desc>.*)$"
)


class HolidaysDatError(Exception):
    """Erro base ao processar ``holidays.dat``."""


class HolidaysDatNotFoundError(HolidaysDatError, FileNotFoundError):
    """Arquivo ``holidays.dat`` não encontrado no path especificado."""


class HolidaysDatParseError(HolidaysDatError, ValueError):
    """Linha malformada em ``holidays.dat``.

    Attributes:
        line_number: Número da linha (1-indexed) onde o erro ocorreu.
        line_content: Conteúdo bruto da linha problemática.
    """

    def __init__(self, line_number: int, line_content: str, reason: str) -> None:
        self.line_number = line_number
        self.line_content = line_content
        super().__init__(
            f"holidays.dat parse error at line {line_number}: {reason} "
            f"| content={line_content!r}"
        )


# Cache módulo: path → (mtime_ns, parsed_holidays).
# Lock garante thread-safety em primeiro uso simultâneo.
_cache: dict[Path, tuple[int, frozenset[date]]] = {}
_cache_lock = threading.Lock()


def parse_holidays_dat(path: Path) -> frozenset[date]:
    """Lê arquivo ``holidays.dat`` Nelogica e retorna feriados B3 full-day.

    Filtra apenas exchanges B3-related (:data:`B3_EXCHANGE_CODES`) e ignora
    pregão parcial (linhas com ``opening_time`` preenchido). Cache via mtime
    do arquivo: invocações sucessivas para o mesmo path com mtime inalterado
    retornam resultado cacheado.

    Args:
        path: Caminho absoluto para ``holidays.dat`` (tipicamente
            ``profitdll/DLLs/Win64/holidays.dat``).

    Returns:
        ``frozenset`` de :class:`datetime.date` com feriados B3 cobertos pelo
        arquivo (deduplicados — uma data aparece em múltiplas linhas para
        cada exchange code, mas retornamos cada data uma vez).

    Raises:
        HolidaysDatNotFoundError: Se ``path`` não existe.
        HolidaysDatParseError: Se alguma linha de dados está malformada
            (não respeita o pattern ``EE:DATE:OPEN:CLOSE:DESC``).

    Example:
        >>> from pathlib import Path
        >>> holidays = parse_holidays_dat(Path("profitdll/DLLs/Win64/holidays.dat"))
        >>> from datetime import date
        >>> date(2025, 12, 25) in holidays  # Natal
        True
    """
    path = path.resolve()
    if not path.is_file():
        raise HolidaysDatNotFoundError(f"holidays.dat not found at {path}")

    # mtime check (cache invalidation).
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError as exc:  # pragma: no cover — defensivo
        raise HolidaysDatError(f"cannot stat {path}: {exc}") from exc

    with _cache_lock:
        cached = _cache.get(path)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]

    # Read + parse fora do lock (evita serializar I/O entre threads).
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        raw = fh.read()

    holidays: set[date] = set()
    for idx, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        match = _LINE_PATTERN.match(line)
        if match is None:
            raise HolidaysDatParseError(
                line_number=idx,
                line_content=raw_line,
                reason="line does not match expected format EE:DATE:OPEN:CLOSE:DESC",
            )

        exchange = match.group("exchange")
        if exchange not in B3_EXCHANGE_CODES:
            # Exchange estrangeiro (NYSE, NASDAQ, etc.). Skip silenciosamente.
            continue

        opening = match.group("open")
        if opening:
            # Pregão parcial — em V1 NÃO é feriado (é dia útil com sessão reduzida).
            continue

        try:
            day = date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError as exc:
            raise HolidaysDatParseError(
                line_number=idx,
                line_content=raw_line,
                reason=f"invalid date: {exc}",
            ) from exc

        holidays.add(day)

    result = frozenset(holidays)

    with _cache_lock:
        _cache[path] = (mtime_ns, result)

    logger.info(
        "holidays_dat.parsed",
        path=str(path),
        holiday_count=len(result),
        years_covered=sorted({d.year for d in result}),
    )
    return result


def clear_cache() -> None:
    """Limpa cache interno de parses. Útil em testes que mockam o filesystem."""
    with _cache_lock:
        _cache.clear()


__all__ = [
    "B3_EXCHANGE_CODES",
    "HolidaysDatError",
    "HolidaysDatNotFoundError",
    "HolidaysDatParseError",
    "clear_cache",
    "parse_holidays_dat",
]
