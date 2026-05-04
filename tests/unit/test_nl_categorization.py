"""Unit tests — dll.error_taxonomy (Story 2.6 AC1 / AC7).

Cobertura:
- Cada NL_* canônico é categorizado corretamente (table-driven).
- Códigos legacy (dll/errors.py) batem com os canônicos.
- ``NL_OK`` é PERMANENT (não-retryable, sucesso).
- ``categorize_nl(unknown)`` → UNKNOWN (R7 conservadora) sem raise.
- ``is_retryable`` somente True em TRANSIENT.
- 30+ casos table-driven (cobre todos os 39 entries do NL_CATEGORY_MAP).
"""

from __future__ import annotations

import pytest

from data_downloader.dll.error_taxonomy import (
    NL_CATEGORY_MAP,
    ErrorCategory,
    NLErrorCategory,
    categorize_nl,
    is_retryable,
)

# =====================================================================
# Suite table-driven — Story 2.6 AC1: cobre TODOS os codes do mapa
# =====================================================================


# (code, expected_name, expected_category)
_CANONICAL_CASES: list[tuple[int, str, ErrorCategory]] = [
    # Sucesso
    (0, "NL_OK", ErrorCategory.PERMANENT),
    # Internos
    (-2147483647, "NL_INTERNAL_ERROR", ErrorCategory.TRANSIENT),
    (-2147483646, "NL_NOT_INITIALIZED", ErrorCategory.PERMANENT),
    (-2147483645, "NL_INVALID_ARGS", ErrorCategory.PERMANENT),
    (-2147483644, "NL_WAITING_SERVER", ErrorCategory.TRANSIENT),
    # Auth / licença
    (-2147483643, "NL_NO_LOGIN", ErrorCategory.PERMANENT),
    (-2147483642, "NL_NO_LICENSE", ErrorCategory.PERMANENT),
    (-2147483630, "NL_LICENSE_NOT_ALLOWED", ErrorCategory.PERMANENT),
    (-2147483641, "NL_PASSWORD_HASH_SHA1", ErrorCategory.PERMANENT),
    (-2147483640, "NL_PASSWORD_HASH_MD5", ErrorCategory.PERMANENT),
    (-2147483620, "NL_NO_PASSWORD", ErrorCategory.PERMANENT),
    (-2147483619, "NL_NO_USER", ErrorCategory.PERMANENT),
    # Subscriptions / tickers
    (-2147483617, "NL_INVALID_TICKER", ErrorCategory.PERMANENT),
    (-2147483633, "NL_EXCHANGE_UNKNOWN", ErrorCategory.PERMANENT),
    # History
    (-2147483628, "NL_SERIE_NO_HISTORY", ErrorCategory.PERMANENT),
    (-2147483626, "NL_SERIE_NO_DATA", ErrorCategory.PERMANENT),
    (-2147483624, "NL_SERIE_NO_MORE_HISTORY", ErrorCategory.PERMANENT),
    (-2147483623, "NL_SERIE_MAX_COUNT", ErrorCategory.PERMANENT),
    (-2147483627, "NL_ASSET_NO_DATA", ErrorCategory.AMBIGUOUS),
    # State / lifecycle
    (-2147483638, "NL_MARKET_ONLY", ErrorCategory.PERMANENT),
    (-2147483637, "NL_NO_POSITION", ErrorCategory.PERMANENT),
    (-2147483629, "NL_NOT_HARD_LOGOUT", ErrorCategory.PERMANENT),
    (-2147483625, "NL_HAS_STRATEGY_RUNNING", ErrorCategory.PERMANENT),
    # Resource / generic
    (-2147483636, "NL_NOT_FOUND", ErrorCategory.AMBIGUOUS),
    (-2147483639, "NL_OUT_OF_RANGE", ErrorCategory.PERMANENT),
    (-2147483635, "NL_VERSION_NOT_SUPPORTED", ErrorCategory.PERMANENT),
    (-2147483634, "NL_OCO_NO_RULES", ErrorCategory.PERMANENT),
    (-2147483632, "NL_NO_OCO_DEFINED", ErrorCategory.PERMANENT),
    (-2147483631, "NL_INVALID_SERIE", ErrorCategory.PERMANENT),
    (-2147483622, "NL_DUPLICATE_RESOURCE", ErrorCategory.PERMANENT),
    (-2147483621, "NL_UNSIGNED_CONTRACT", ErrorCategory.PERMANENT),
    (-2147483618, "NL_FILE_ALREADY_EXISTS", ErrorCategory.PERMANENT),
    (-2147483616, "NL_NOT_MASTER_ACCOUNT", ErrorCategory.PERMANENT),
    # Sentinela interna
    (-1, "DLL_SENTINEL", ErrorCategory.PERMANENT),
    # Códigos legacy (dll/errors.py)
    (-2147483393, "NL_INVALID_ARGS", ErrorCategory.PERMANENT),
    (-2147483392, "NL_NO_LICENSE", ErrorCategory.PERMANENT),
    (-2147483391, "NL_NO_LOGIN", ErrorCategory.PERMANENT),
    (-2147483390, "NL_INVALID_TICKER", ErrorCategory.PERMANENT),
    (-2147483389, "NL_EXCHANGE_UNKNOWN", ErrorCategory.PERMANENT),
]


@pytest.mark.unit
@pytest.mark.parametrize(("code", "expected_name", "expected_category"), _CANONICAL_CASES)
def test_categorize_nl_canonical(
    code: int,
    expected_name: str,
    expected_category: ErrorCategory,
) -> None:
    """Cada NL_* canônico é categorizado conforme tabela Nelo."""
    info = categorize_nl(code)
    assert isinstance(info, NLErrorCategory)
    assert info.code == code
    assert info.name == expected_name
    assert info.category is expected_category
    assert info.justification, "justification não pode ser vazia"


@pytest.mark.unit
def test_table_size_matches_cases() -> None:
    """Garante que TODOS os entries do NL_CATEGORY_MAP estão nos casos canônicos
    (anti-bitrot: novo NL_* sem teste é bug).
    """
    table_codes = set(NL_CATEGORY_MAP.keys())
    test_codes = {code for code, _, _ in _CANONICAL_CASES}
    missing = table_codes - test_codes
    assert not missing, f"NL_* sem teste em test_nl_categorization.py: {missing}"


@pytest.mark.unit
def test_minimum_30_cases() -> None:
    """Story 2.6 AC requer 30+ NL_* codes corretamente categorizados."""
    assert len(_CANONICAL_CASES) >= 30


@pytest.mark.unit
def test_categorize_nl_unknown_code_returns_unknown() -> None:
    """Códigos não-mapeados retornam UNKNOWN (R7 conservadora) sem raise."""
    info = categorize_nl(99999)
    assert info.code == 99999
    assert info.name == "NL_UNKNOWN_99999"
    assert info.category is ErrorCategory.UNKNOWN
    assert "desconhecido" in info.justification.lower()


@pytest.mark.unit
def test_categorize_nl_negative_unknown_code() -> None:
    """Códigos negativos não-mapeados também → UNKNOWN."""
    info = categorize_nl(-12345)
    assert info.category is ErrorCategory.UNKNOWN
    assert info.name == "NL_UNKNOWN_-12345"


@pytest.mark.unit
def test_is_retryable_only_true_for_transient() -> None:
    """is_retryable só retorna True para TRANSIENT (R7 — AMBIGUOUS NÃO entra)."""
    # TRANSIENT
    assert is_retryable(-2147483647) is True  # NL_INTERNAL_ERROR
    assert is_retryable(-2147483644) is True  # NL_WAITING_SERVER
    # PERMANENT
    assert is_retryable(0) is False  # NL_OK
    assert is_retryable(-2147483646) is False  # NL_NOT_INITIALIZED
    assert is_retryable(-2147483617) is False  # NL_INVALID_TICKER
    # AMBIGUOUS — não-retryable via is_retryable (caller decide via categorize_nl)
    assert is_retryable(-2147483636) is False  # NL_NOT_FOUND
    assert is_retryable(-2147483627) is False  # NL_ASSET_NO_DATA
    # UNKNOWN
    assert is_retryable(99999) is False


@pytest.mark.unit
def test_categorize_nl_never_raises_on_extreme_values() -> None:
    """Defesa: códigos extremos (overflow, zero, max int) não devem raise."""
    for code in (0, -(2**31), 2**31 - 1, -1, 1):
        info = categorize_nl(code)
        assert info.code == code
        assert info.category in ErrorCategory


@pytest.mark.unit
def test_error_category_enum_has_4_members() -> None:
    """Sanidade — só TRANSIENT/PERMANENT/AMBIGUOUS/UNKNOWN existem."""
    members = {e.value for e in ErrorCategory}
    assert members == {"transient", "permanent", "ambiguous", "unknown"}


@pytest.mark.unit
def test_nl_category_map_immutable_signature() -> None:
    """Cada entry tem (name: str, category: ErrorCategory, justification: str)."""
    for code, entry in NL_CATEGORY_MAP.items():
        assert isinstance(code, int)
        name, category, justification = entry
        assert isinstance(name, str) and name.startswith(("NL_", "DLL_"))
        assert isinstance(category, ErrorCategory)
        assert isinstance(justification, str) and justification
