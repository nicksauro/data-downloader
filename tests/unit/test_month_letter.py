"""Unit tests — orchestrator.contracts month letter helpers (Story 1.6 Subtasks 2.3/2.4 + 6.1).

Cobertura:

- ``month_letter`` exato para os 12 meses do calendário CME/B3.
- ``month_from_letter`` aceita case-insensitive.
- Round-trip (Hypothesis): para todo m in [1, 12],
  ``month_from_letter(month_letter(m)) == m``.
- Erros: mês fora de range, letra inválida (incluindo I/L pulados pela CME).
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from data_downloader.orchestrator.contracts import (
    LETTER_TO_MONTH,
    MONTH_LETTERS,
    month_from_letter,
    month_letter,
)


@pytest.mark.unit
def test_month_letter_table_exact() -> None:
    """Tabela canônica CME/B3 — fixar contra regression."""
    expected = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"]
    for month, letter in enumerate(expected, start=1):
        assert month_letter(month) == letter
    # Garante que MONTH_LETTERS bate com expected.
    assert list(MONTH_LETTERS) == expected


@pytest.mark.unit
def test_month_from_letter_case_insensitive() -> None:
    """Aceita lowercase — convenção de DLLs Win API."""
    assert month_from_letter("j") == 4
    assert month_from_letter("J") == 4
    assert month_from_letter("z") == 12
    assert month_from_letter("Z") == 12


@pytest.mark.unit
@pytest.mark.parametrize("invalid", ["I", "L", "i", "l", "A", "0", "1", "Y"])
def test_month_from_letter_rejects_invalid(invalid: str) -> None:
    """Letras puladas pela CME (I, L) e fora do alfabeto canônico — falham."""
    with pytest.raises(ValueError, match="not a valid"):
        month_from_letter(invalid)


@pytest.mark.unit
@pytest.mark.parametrize("invalid", [0, 13, -1, 100])
def test_month_letter_rejects_out_of_range(invalid: int) -> None:
    with pytest.raises(ValueError, match=r"\[1, 12\]"):
        month_letter(invalid)


@pytest.mark.unit
def test_month_from_letter_rejects_non_single_char() -> None:
    with pytest.raises(ValueError, match="single char"):
        month_from_letter("JJ")
    with pytest.raises(ValueError, match="single char"):
        month_from_letter("")


@pytest.mark.unit
def test_letter_to_month_dict_consistency() -> None:
    """LETTER_TO_MONTH é fielmente derivado de MONTH_LETTERS."""
    for month, letter in enumerate(MONTH_LETTERS, start=1):
        assert LETTER_TO_MONTH[letter] == month
    assert len(LETTER_TO_MONTH) == 12


@pytest.mark.property
@given(st.integers(min_value=1, max_value=12))
def test_round_trip_month_letter(month: int) -> None:
    """Property: para todo m in [1, 12], inverso é fiel."""
    assert month_from_letter(month_letter(month)) == month


@pytest.mark.property
@given(st.sampled_from(MONTH_LETTERS))
def test_round_trip_letter_month(letter: str) -> None:
    """Property: para toda letra CME/B3, ida-volta preserva."""
    assert month_letter(month_from_letter(letter)) == letter
