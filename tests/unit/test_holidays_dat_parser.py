"""Unit tests — validation.holidays_dat_parser (Story 2.5).

Cobre:

- Parse de arquivo real ``profitdll/DLLs/Win64/holidays.dat`` (se disponível).
- Parse de fixture sintética (sempre disponível em CI).
- Filtragem de exchanges (apenas B3 entram).
- Skip de pregão parcial (linhas com OPEN preenchido).
- Cache via mtime (re-parse após mtime change).
- Erros: arquivo ausente, linha malformada, data inválida.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pytest

from data_downloader.validation.holidays_dat_parser import (
    B3_EXCHANGE_CODES,
    HolidaysDatNotFoundError,
    HolidaysDatParseError,
    clear_cache,
    parse_holidays_dat,
)

REAL_DAT_PATH = Path("profitdll/DLLs/Win64/holidays.dat")


@pytest.fixture(autouse=True)
def _reset_parser_cache() -> None:
    """Garante cache limpo entre testes."""
    clear_cache()
    yield
    clear_cache()


def _write_dat(path: Path, lines: list[str]) -> None:
    """Helper: escreve fixture .dat com encoding e line endings corretos."""
    content = "\r\n".join(lines) + "\r\n"
    path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))


# =====================================================================
# Erros
# =====================================================================


@pytest.mark.unit
def test_file_not_found_raises(tmp_path: Path) -> None:
    """Arquivo inexistente levanta HolidaysDatNotFoundError."""
    with pytest.raises(HolidaysDatNotFoundError, match="not found"):
        parse_holidays_dat(tmp_path / "nonexistent.dat")


@pytest.mark.unit
def test_malformed_line_raises_with_offset(tmp_path: Path) -> None:
    """Linha malformada levanta HolidaysDatParseError com line_number."""
    p = tmp_path / "bad.dat"
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "66:202501010000000:::Confraternização",
            "this line is junk",  # malformed
        ],
    )
    with pytest.raises(HolidaysDatParseError) as exc_info:
        parse_holidays_dat(p)
    assert exc_info.value.line_number == 3
    assert "junk" in exc_info.value.line_content


@pytest.mark.unit
def test_invalid_date_raises(tmp_path: Path) -> None:
    """Data inválida (mês 13) levanta HolidaysDatParseError."""
    p = tmp_path / "bad_date.dat"
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "66:202513010000000:::Mês inválido",
        ],
    )
    with pytest.raises(HolidaysDatParseError, match="invalid date"):
        parse_holidays_dat(p)


# =====================================================================
# Parsing
# =====================================================================


@pytest.mark.unit
def test_parses_b3_full_holiday(tmp_path: Path) -> None:
    """Linha B3 com OPEN vazio é incluída."""
    p = tmp_path / "ok.dat"
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "66:202501010000000:::Confraternização",
        ],
    )
    holidays = parse_holidays_dat(p)
    assert holidays == frozenset({date(2025, 1, 1)})


@pytest.mark.unit
def test_skips_partial_session(tmp_path: Path) -> None:
    """Linha B3 com OPEN preenchido (pregão parcial) é IGNORADA."""
    p = tmp_path / "partial.dat"
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "66:201403050000000:201403051300000::Quarta-feira de Cinzas",
        ],
    )
    holidays = parse_holidays_dat(p)
    assert holidays == frozenset()


@pytest.mark.unit
def test_skips_foreign_exchanges(tmp_path: Path) -> None:
    """Linhas NYSE (89='Y'), NASDAQ (96='`') etc. são ignoradas."""
    p = tmp_path / "foreign.dat"
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "89:201307040000000:::Independence Day",  # NYSE — ignored
            "96:201312250000000:::NASDAQ Christmas",  # NASDAQ — ignored
            "66:202501010000000:::Confraternização",  # B3 — included
        ],
    )
    holidays = parse_holidays_dat(p)
    assert holidays == frozenset({date(2025, 1, 1)})


@pytest.mark.unit
def test_dedupes_across_exchanges(tmp_path: Path) -> None:
    """Mesma data em 66 (Bovespa) e 70 (BMF) entra UMA vez."""
    p = tmp_path / "dedup.dat"
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "66:202501010000000:::Confraternização",
            "70:202501010000000:::Confraternização",
            "35:202501010000000:::Confraternização",
        ],
    )
    holidays = parse_holidays_dat(p)
    assert holidays == frozenset({date(2025, 1, 1)})


@pytest.mark.unit
def test_skips_comment_and_empty_lines(tmp_path: Path) -> None:
    """Comentários (//) e linhas vazias são ignorados."""
    p = tmp_path / "comments.dat"
    _write_dat(
        p,
        [
            "//29/12/2025 14:16:19.813",
            "",
            "66:202501010000000:::Confraternização",
            "",
        ],
    )
    holidays = parse_holidays_dat(p)
    assert holidays == frozenset({date(2025, 1, 1)})


# =====================================================================
# Cache mtime
# =====================================================================


@pytest.mark.unit
def test_cache_returns_same_object_on_repeat(tmp_path: Path) -> None:
    """Segunda chamada retorna mesmo frozenset (cache hit, sem re-parse)."""
    p = tmp_path / "cache.dat"
    _write_dat(p, ["//01/01/2025 00:00:00.000", "66:202501010000000:::Confra"])
    first = parse_holidays_dat(p)
    second = parse_holidays_dat(p)
    assert first is second  # mesmo objeto = veio do cache


@pytest.mark.unit
def test_cache_invalidates_on_mtime_change(tmp_path: Path) -> None:
    """Alterar mtime do arquivo força re-parse."""
    p = tmp_path / "mtime.dat"
    _write_dat(p, ["//01/01/2025 00:00:00.000", "66:202501010000000:::Confra"])
    first = parse_holidays_dat(p)
    assert first == frozenset({date(2025, 1, 1)})

    # Aguarda mtime granularity (Windows: ~10-15ms; CI safety: 50ms).
    time.sleep(0.1)
    _write_dat(
        p,
        [
            "//01/01/2025 00:00:00.000",
            "66:202501010000000:::Confra",
            "66:202512250000000:::Natal",
        ],
    )
    # Garante que mtime de fato mudou.
    second = parse_holidays_dat(p)
    assert second == frozenset({date(2025, 1, 1), date(2025, 12, 25)})
    assert first is not second  # cache invalidado


# =====================================================================
# Constants
# =====================================================================


@pytest.mark.unit
def test_b3_exchange_codes_is_frozenset() -> None:
    """B3_EXCHANGE_CODES é immutable (frozenset)."""
    assert isinstance(B3_EXCHANGE_CODES, frozenset)
    # Valores ASCII corretos: '#'(35), 'B'(66), 'F'(70), 'X'(88), 'c'(99).
    assert frozenset({"35", "66", "70", "88", "99"}) == B3_EXCHANGE_CODES


# =====================================================================
# Real holidays.dat (skip se ausente — ambiente sem ProfitDLL)
# =====================================================================


@pytest.mark.unit
@pytest.mark.skipif(not REAL_DAT_PATH.is_file(), reason="holidays.dat not available (no ProfitDLL)")
def test_real_holidays_dat_parses_without_error() -> None:
    """Arquivo real distribuído pela Nelogica é parseável sem erro."""
    holidays = parse_holidays_dat(REAL_DAT_PATH)
    # Cobertura mínima: pelo menos 100 feriados (~10 anos x 10 holidays/ano).
    assert len(holidays) >= 100
    # Range: 2013-2035 esperado.
    years = {d.year for d in holidays}
    assert min(years) <= 2014
    assert max(years) >= 2030


@pytest.mark.unit
@pytest.mark.skipif(not REAL_DAT_PATH.is_file(), reason="holidays.dat not available (no ProfitDLL)")
def test_real_holidays_dat_known_dates() -> None:
    """Feriados conhecidos 2025/2026 estão no arquivo real."""
    holidays = parse_holidays_dat(REAL_DAT_PATH)
    # Datas que B3 oficialmente reconhece e que NÃO caem em fim de semana
    # (Nelogica omite weekend holidays — ver HOLIDAYS_DAT_FORMAT.md §4).
    assert date(2025, 1, 1) in holidays  # Confraternização
    assert date(2025, 4, 21) in holidays  # Tiradentes (segunda)
    assert date(2025, 12, 25) in holidays  # Natal (quinta)
    assert date(2026, 4, 21) in holidays  # Tiradentes (terça)
    assert date(2026, 12, 25) in holidays  # Natal (sexta)
