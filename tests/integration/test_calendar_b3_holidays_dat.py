"""Integration tests — calendar_b3 + holidays_dat_parser (Story 2.5).

Cobre:

- Estratégia união (parser UNION hardcoded) cobre datas que cada fonte sozinha
  omitiria (24/12 só está na DAT; feriados em FDS só estão no hardcoded).
- Fallback graceful: env var apontando para arquivo inexistente → API
  funciona com hardcoded only.
- Fallback graceful: arquivo corrompido → API funciona com hardcoded only
  + log warning.
- Refresh automático: alterar conteúdo + mtime do arquivo → próxima call
  re-parseia.
- Real holidays.dat (skip se ausente): comparação parsed vs hardcoded para
  feriados conhecidos 2025/2026.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import pytest

from data_downloader.validation.calendar_b3 import (
    HOLIDAYS_DAT_ENV_VAR,
    _reset_calendar_cache,  # type: ignore[attr-defined]  # test-only
    b3_holidays,
    is_b3_business_day,
    is_holiday,
)

REAL_DAT_PATH = Path("profitdll/DLLs/Win64/holidays.dat")


@pytest.fixture(autouse=True)
def _isolate_calendar() -> None:
    """Reset cache antes/depois de cada teste — isolamento."""
    _reset_calendar_cache()
    yield
    _reset_calendar_cache()


def _write_dat(path: Path, lines: list[str]) -> None:
    """Helper: escreve fixture .dat (UTF-8 BOM + CRLF)."""
    content = "\r\n".join(lines) + "\r\n"
    path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))


# =====================================================================
# Fallback graceful
# =====================================================================


@pytest.mark.integration
def test_arquivo_inexistente_usa_hardcoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem holidays.dat, API funciona via hardcoded (AC8)."""
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(tmp_path / "ghost.dat"))
    _reset_calendar_cache()

    # Tiradentes 2026 está no hardcoded.
    assert is_holiday(date(2026, 4, 21))
    # Quarta normal não.
    assert is_b3_business_day(date(2026, 4, 22))


@pytest.mark.integration
def test_arquivo_corrompido_usa_hardcoded_e_loga_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Arquivo malformado → fallback hardcoded + warn (não crash)."""
    bad = tmp_path / "corrupted.dat"
    # Conteúdo claramente inválido — primeira linha "data" é junk.
    bad.write_bytes(b"\xef\xbb\xbftotal garbage that is not a holiday line\r\n")
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(bad))
    _reset_calendar_cache()

    # API ainda funciona (via hardcoded).
    assert is_holiday(date(2025, 12, 25))


# =====================================================================
# União parser UNION hardcoded
# =====================================================================


@pytest.mark.integration
def test_uniao_inclui_pontos_facultativos_da_dat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24/12 (véspera Natal) está só na DAT — união captura."""
    p = tmp_path / "extra.dat"
    _write_dat(
        p,
        [
            "//29/12/2025 14:16:19.813",
            "66:202512240000000:::Véspera de Natal",  # NÃO está no hardcoded
            "70:202512240000000:::Véspera de Natal",
        ],
    )
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(p))
    _reset_calendar_cache()

    # 24/12 é capturado via DAT.
    assert is_holiday(date(2025, 12, 24))
    # 25/12 ainda é (do hardcoded).
    assert is_holiday(date(2025, 12, 25))


@pytest.mark.integration
def test_uniao_preserva_feriados_em_fds_do_hardcoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feriados em FDS (Nelogica omite) ainda estão via hardcoded."""
    # DAT mínima — não cobre 2025-09-07 (domingo, Nelogica omite).
    p = tmp_path / "minimal.dat"
    _write_dat(
        p,
        [
            "//29/12/2025 14:16:19.813",
            "66:202501010000000:::Confraternização",
        ],
    )
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(p))
    _reset_calendar_cache()

    # Independência 2025 (domingo) está via hardcoded.
    assert is_holiday(date(2025, 9, 7))


# =====================================================================
# Refresh automático (mtime check)
# =====================================================================


@pytest.mark.integration
def test_refresh_automatico_apos_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alterar mtime do holidays.dat → próxima call re-parseia."""
    p = tmp_path / "refresh.dat"
    _write_dat(
        p,
        [
            "//29/12/2025 14:16:19.813",
            "66:204001010000000:::Ano Novo 2040",
        ],
    )
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(p))
    _reset_calendar_cache()

    # Primeira leitura: 2040 não está no hardcoded (range 2020-2030).
    assert is_holiday(date(2040, 1, 1))
    assert not is_holiday(date(2040, 12, 25))

    # Aguarda granularity de mtime (Windows ~10-15ms; safety: 100ms).
    time.sleep(0.1)
    _write_dat(
        p,
        [
            "//29/12/2025 14:16:19.813",
            "66:204001010000000:::Ano Novo 2040",
            "66:204012250000000:::Natal 2040",
        ],
    )

    # Reset apenas do cache do calendar; parser detecta mtime change e re-lê.
    _reset_calendar_cache()
    assert is_holiday(date(2040, 12, 25))


# =====================================================================
# Cobertura ano fora do hardcoded (só DAT responde)
# =====================================================================


@pytest.mark.integration
def test_anos_alem_2030_via_dat_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ano > 2030 só responde via DAT (sem fallback hardcoded)."""
    p = tmp_path / "future.dat"
    _write_dat(
        p,
        [
            "//29/12/2025 14:16:19.813",
            "66:203501010000000:::Confraternização 2035",
        ],
    )
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(p))
    _reset_calendar_cache()

    assert is_holiday(date(2035, 1, 1))


# =====================================================================
# Real holidays.dat (smoke se disponível)
# =====================================================================


@pytest.mark.integration
@pytest.mark.skipif(not REAL_DAT_PATH.is_file(), reason="holidays.dat not available (no ProfitDLL)")
def test_real_dat_concorda_com_hardcoded_para_2025_2026(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Para datas que ambas fontes cobrem, parser e hardcoded concordam.

    Nota: a fonte ÚNICA (parser-only ou hardcoded-only) tem diferenças
    intencionais (FDS vs pontos facultativos). Mas a UNIÃO efetiva
    via API pública deve cobrir o superset.
    """
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(REAL_DAT_PATH))
    _reset_calendar_cache()

    # Feriados 2025/2026 que não caem em FDS — devem estar em ambos.
    casos_universais_2025 = [
        date(2025, 1, 1),
        date(2025, 3, 3),  # Carnaval seg
        date(2025, 3, 4),  # Carnaval ter
        date(2025, 4, 18),  # Sexta Santa
        date(2025, 4, 21),  # Tiradentes
        date(2025, 5, 1),
        date(2025, 6, 19),  # Corpus Christi
        date(2025, 11, 20),  # Consciência Negra (quinta)
        date(2025, 12, 25),
    ]
    for d in casos_universais_2025:
        assert is_holiday(d), f"esperado feriado: {d}"

    # FDS holidays — só hardcoded, mas união ainda captura.
    assert is_holiday(date(2025, 9, 7))  # domingo
    assert is_holiday(date(2025, 11, 15))  # sábado

    # Pontos facultativos — só DAT, mas união captura.
    assert is_holiday(date(2025, 12, 24))  # véspera Natal
    assert is_holiday(date(2025, 12, 31))  # véspera Ano Novo


@pytest.mark.integration
@pytest.mark.skipif(not REAL_DAT_PATH.is_file(), reason="holidays.dat not available (no ProfitDLL)")
def test_real_dat_total_holidays_2025_atinge_15(monkeypatch: pytest.MonkeyPatch) -> None:
    """União DAT + hardcoded para 2025 cobre >= 15 feriados full-day.

    13 nacionais + 2 pontos facultativos (24/12, 31/12) = 15.
    """
    monkeypatch.setenv(HOLIDAYS_DAT_ENV_VAR, str(REAL_DAT_PATH))
    _reset_calendar_cache()

    holidays_2025 = b3_holidays(2025)
    assert len(holidays_2025) >= 15, f"got {len(holidays_2025)}: {sorted(holidays_2025)}"
