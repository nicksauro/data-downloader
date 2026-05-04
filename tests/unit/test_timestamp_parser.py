"""tests/unit/test_timestamp_parser.py — Story 1.3.

Cobertura crítica de ``data_downloader.orchestrator.timestamp``:

- AC9: aceita AMBOS formatos (manual ``.ZZZ`` + quirk ``:ZZZ`` Q03-AMB).
- AC9: timestamp em BRT NAIVE (R7 — não converte UTC).
- Property test (Hypothesis): parse(format(d)) ≈ d (precisão ms).
- Erros: formato inválido → ValueError.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from data_downloader.orchestrator.timestamp import (
    format_brt_timestamp,
    parse_brt_timestamp,
)

# =====================================================================
# Aceita ambos os formatos (Q03-AMB)
# =====================================================================


@pytest.mark.unit
def test_parse_accepts_manual_dot_format() -> None:
    """Manual canônico ``.ZZZ`` (ponto antes de ms) é aceito."""
    ns = parse_brt_timestamp("15/04/2026 09:00:00.000")
    # 15/04/2026 09:00:00 BRT naive — interpretação como wall clock.
    # Cálculo: dias desde epoch * 86400 * 1e9 + horas/minutos/segundos.
    expected_dt_naive = datetime(2026, 4, 15, 9, 0, 0)
    expected_seconds = (expected_dt_naive - datetime(1970, 1, 1)).total_seconds()
    assert ns == int(expected_seconds * 1_000_000_000)


@pytest.mark.unit
def test_parse_accepts_quirk_colon_format() -> None:
    """Quirk ``:ZZZ`` (dois-pontos antes de ms — Q03-AMB) é aceito."""
    ns_dot = parse_brt_timestamp("15/04/2026 09:00:00.000")
    ns_colon = parse_brt_timestamp("15/04/2026 09:00:00:000")
    # Devem produzir EXATAMENTE o mesmo timestamp_ns.
    assert ns_dot == ns_colon


@pytest.mark.unit
def test_parse_with_milliseconds() -> None:
    """Milissegundos são preservados (precisão ms)."""
    ns = parse_brt_timestamp("15/04/2026 09:00:00.123")
    # 123ms = 123_000_000 ns adicionais ao base de 09:00:00.000.
    base_ns = parse_brt_timestamp("15/04/2026 09:00:00.000")
    assert ns - base_ns == 123_000_000


@pytest.mark.unit
def test_parse_quirk_format_with_milliseconds() -> None:
    """Quirk ``:ZZZ`` com ms != 0 também funciona."""
    ns = parse_brt_timestamp("15/04/2026 09:00:00:456")
    base_ns = parse_brt_timestamp("15/04/2026 09:00:00:000")
    assert ns - base_ns == 456_000_000


# =====================================================================
# BRT naive — R7 (não converter UTC)
# =====================================================================


@pytest.mark.unit
def test_parse_does_not_apply_local_timezone_offset() -> None:
    """R7/Q04-E — wall clock é tratado como BRT naive, NÃO local time.

    Verificação: timestamp_ns deve ser sempre o MESMO valor independente
    da timezone do sistema rodando o teste. Construímos via cálculo
    explícito (sem strptime) e comparamos.
    """
    # 1970-01-01 00:00:00.000 BRT naive → 0 ns.
    ns = parse_brt_timestamp("01/01/1970 00:00:00.000")
    assert ns == 0


@pytest.mark.unit
def test_parse_epoch_plus_one_second() -> None:
    """1s após epoch BRT naive = 1e9 ns."""
    ns = parse_brt_timestamp("01/01/1970 00:00:01.000")
    assert ns == 1_000_000_000


@pytest.mark.unit
def test_parse_one_full_day_after_epoch() -> None:
    """1 dia após epoch BRT naive = 86400 * 1e9 ns."""
    ns = parse_brt_timestamp("02/01/1970 00:00:00.000")
    assert ns == 86_400 * 1_000_000_000


# =====================================================================
# Formato inválido → ValueError
# =====================================================================


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "invalid",
        "2026-04-15 09:00:00.000",  # ISO format (não suportado)
        "15/04/2026",  # sem horário
        "15/04/2026 09:00:00",  # sem ms
        "32/04/2026 09:00:00.000",  # dia inválido
        "15/13/2026 09:00:00.000",  # mês inválido
        "15/04/2026 25:00:00.000",  # hora inválida
    ],
)
def test_parse_raises_value_error_on_invalid_format(bad_input: str) -> None:
    """Formato inválido levanta ValueError com mensagem informativa."""
    with pytest.raises(ValueError) as exc:
        parse_brt_timestamp(bad_input)
    msg = str(exc.value).lower()
    # Mensagem deve mencionar pelo menos um formato aceito (debug-friendly).
    assert "format" in msg or "timestamp" in msg


@pytest.mark.unit
def test_parse_raises_on_non_string_input() -> None:
    """Tipo errado também levanta ValueError (não TypeError silencioso)."""
    with pytest.raises(ValueError):
        parse_brt_timestamp(None)  # type: ignore[arg-type]


# =====================================================================
# Format
# =====================================================================


@pytest.mark.unit
def test_format_emits_canonical_dot_format() -> None:
    """``format_brt_timestamp`` sempre emite ``.ZZZ`` (manual canônico)."""
    ns = parse_brt_timestamp("15/04/2026 09:00:00.123")
    s = format_brt_timestamp(ns)
    assert s == "15/04/2026 09:00:00.123"
    # Garantir que NÃO usa o formato quirk ``:ZZZ`` na saída.
    assert ":000" not in s.replace("09:00:00", "")  # só os : do hh:mm:ss


@pytest.mark.unit
def test_format_zero_ns_yields_epoch() -> None:
    """0 ns → 01/01/1970 00:00:00.000."""
    assert format_brt_timestamp(0) == "01/01/1970 00:00:00.000"


@pytest.mark.unit
def test_format_raises_on_negative_ns() -> None:
    """Timestamp negativo é inválido (timestamp_ns NOT NULL && > 0 no schema)."""
    with pytest.raises(ValueError):
        format_brt_timestamp(-1)


# =====================================================================
# Roundtrip — parse(format(parse(s))) == parse(s)
# =====================================================================


@pytest.mark.unit
def test_roundtrip_manual_format_preserved_exactly() -> None:
    """parse(format(parse(s))) == parse(s) para o formato manual."""
    inputs = [
        "01/01/1970 00:00:00.000",
        "15/04/2026 09:00:00.123",
        "31/12/2026 23:59:59.999",
        "29/02/2024 12:30:45.500",  # ano bissexto
    ]
    for s in inputs:
        ns = parse_brt_timestamp(s)
        formatted = format_brt_timestamp(ns)
        ns_again = parse_brt_timestamp(formatted)
        assert ns == ns_again, f"roundtrip falhou para {s!r}"


@pytest.mark.unit
def test_roundtrip_quirk_format_normalized_to_dot() -> None:
    """Q03-AMB — input com `:ZZZ` é normalizado para `.ZZZ` no roundtrip."""
    quirk_input = "15/04/2026 09:00:00:789"
    ns = parse_brt_timestamp(quirk_input)
    formatted = format_brt_timestamp(ns)
    # Normalizado: ponto, não dois-pontos.
    assert formatted == "15/04/2026 09:00:00.789"


# =====================================================================
# Property-based — Hypothesis
# =====================================================================


# Restringimos Hypothesis a faixa válida (>= 1970, sem DST risk pre-2020).
# Q04-E nota: B3 não observa DST desde 2019 — limitar smoke a >= 2020 é
# a recomendação, mas o parser puro funciona em qualquer ano >= 1970.
_STRATEGY_DATETIME = st.datetimes(
    min_value=datetime(1970, 1, 1, 0, 0, 0),
    max_value=datetime(2100, 12, 31, 23, 59, 59, 999_000),
).map(lambda d: d.replace(microsecond=(d.microsecond // 1000) * 1000))  # truncate ms


@pytest.mark.property
@given(dt=_STRATEGY_DATETIME)
def test_property_format_then_parse_roundtrip_ms_precision(dt: datetime) -> None:
    """Property: ``parse(format(d_as_ns)) == d_as_ns`` (precisão ms).

    Constrói ns a partir de dt naive (interpretação BRT), formata, parseia,
    compara ns. Precisão da DLL é milissegundos — Hypothesis gera datetimes
    com microssegundos truncados para múltiplos de 1000.
    """
    # Converte dt naive → ns (mesmo método do parser).
    from datetime import UTC

    aware = dt.replace(tzinfo=UTC)
    delta = aware - datetime(1970, 1, 1, tzinfo=UTC)
    total_seconds = delta.days * 86_400 + delta.seconds
    ns_in = total_seconds * 1_000_000_000 + delta.microseconds * 1_000

    formatted = format_brt_timestamp(ns_in)
    ns_out = parse_brt_timestamp(formatted)

    assert ns_in == ns_out


@pytest.mark.property
@given(dt=_STRATEGY_DATETIME)
def test_property_quirk_colon_yields_same_ns_as_dot(dt: datetime) -> None:
    """Property: para qualquer datetime, `.ZZZ` e `:ZZZ` produzem MESMO ns."""
    # Formata como manual (`.ZZZ`).
    s_dot = dt.strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]  # truncate to ms
    # Formata quirk (`:ZZZ`) — substitui ÚLTIMO ponto por dois-pontos.
    s_colon = s_dot[:-4] + ":" + s_dot[-3:]

    ns_dot = parse_brt_timestamp(s_dot)
    ns_colon = parse_brt_timestamp(s_colon)
    assert ns_dot == ns_colon
