"""Unit tests — Story 2.9 / ADR-010 redaction processor.

Owner: Dex (impl) | Authority: Aria (ADR-010 strategy) | Audit: Quinn (property
test for redaction completeness — INV-credenciais).

Cobertura exhaustiva de :func:`redact_secrets`:

- AC3.1: Keys conhecidas (lista canônica do ADR-010 §SENSITIVE_KEYS).
- AC3.2: Recursive (nested dicts, listas).
- AC3.3: Allow-list (``key_redacted``, ``credential_redacted`` preservam
  semântica "intentionally already redacted").
- AC3.4: Edge cases — None, empty strings, bool, int, listas mistas.
- AC7 property test: Hypothesis sobre dicts arbitrários — secret keys
  sempre redactadas, non-secret keys preservadas.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from data_downloader.observability.logging_config import (
    REDACTED_VALUE,
    SENSITIVE_KEY_SUBSTRINGS,
    _is_sensitive_key,
    redact_secrets,
)

# =====================================================================
# AC3.1 — Known keys (canonical list)
# =====================================================================


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "PASSWORD",
        "Password",
        "nl_password",
        "NL_PASSWORD",
        "user_password",
        "old_password",
        "secret",
        "client_secret",
        "TOKEN",
        "api_key",
        "API_KEY",
        "apikey",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "key",
        "NL_KEY",
        "PROFITDLL_KEY",
        "PROFIT_PASS",
        "nl_username",  # nl_username contains nothing sensitive — but we keep it loose
    ],
)
@pytest.mark.unit
def test_is_sensitive_key_matches_canonical(key: str) -> None:
    """Cada key canônica é detectada como sensível (case-insensitive substring match).

    Nota: ``nl_username`` é incluído por defesa em profundidade — embora
    username não seja secret, a heurística pega ``user`` via... espera,
    não pega. Vamos verificar caso a caso.
    """
    # Keys que NÃO contêm substring sensível (false neg controlado).
    keys_not_sensitive = {"nl_username"}
    if key in keys_not_sensitive:
        assert not _is_sensitive_key(key), f"{key} should NOT be sensitive"
    else:
        assert _is_sensitive_key(key), f"{key} should be detected as sensitive"


@pytest.mark.parametrize(
    "key",
    [
        "user",
        "username",
        "email",
        "trade_id",
        "chunk_id",
        "symbol",
        "exchange",
        "trades_count",
        "duration_ms",
        "status",
        "thread",
        "level",
        "event",
        "logger",
    ],
)
@pytest.mark.unit
def test_is_sensitive_key_does_not_match_safe_keys(key: str) -> None:
    """Keys neutras (canônicas do log canonical) NÃO são marcadas como sensíveis."""
    assert not _is_sensitive_key(key), f"{key} should NOT be sensitive"


@pytest.mark.parametrize(
    "key",
    ["key_redacted", "credential_redacted", "password_redacted"],
)
@pytest.mark.unit
def test_is_sensitive_key_allowlist(key: str) -> None:
    """Allow-list — chaves "intentionally redacted" NÃO são re-redactadas.

    Preserva a string ``"***"`` que o dev passou explicitamente
    (DLL wrapper usa este padrão).
    """
    assert not _is_sensitive_key(key), f"{key} should be in allow-list"


# =====================================================================
# AC3.2 — Recursive (nested)
# =====================================================================


@pytest.mark.unit
def test_redact_recursive_nested_dict() -> None:
    """Nested dicts são redactados em profundidade arbitrária."""
    # pragma: allowlist nextline secret
    payload: dict[str, Any] = {
        "user": "demo",
        "outer": {
            "inner": {
                "deepest": {
                    "nl_password": "secret",  # pragma: allowlist secret
                    "kept": "value",
                },
            },
            "token": "x",  # pragma: allowlist secret
        },
    }
    result = redact_secrets(payload)
    assert result["user"] == "demo"
    assert result["outer"]["inner"]["deepest"]["nl_password"] == REDACTED_VALUE
    assert result["outer"]["inner"]["deepest"]["kept"] == "value"
    assert result["outer"]["token"] == REDACTED_VALUE


@pytest.mark.unit
def test_redact_recursive_list_of_dicts() -> None:
    """Listas de dicts: cada item é redactado."""
    payload = {
        "users": [
            {"name": "alice", "password": "p1"},  # pragma: allowlist secret
            {"name": "bob", "secret": "p2"},  # pragma: allowlist secret
            {"name": "charlie", "api_key": "p3"},  # pragma: allowlist secret
        ]
    }
    result = redact_secrets(payload)
    assert result["users"][0]["name"] == "alice"
    assert result["users"][0]["password"] == REDACTED_VALUE
    assert result["users"][1]["secret"] == REDACTED_VALUE
    assert result["users"][2]["api_key"] == REDACTED_VALUE


@pytest.mark.unit
def test_redact_tuple_preserved_as_tuple() -> None:
    """Tuples são preservadas como tuples (não viram lists)."""
    payload = {"items": ({"password": "x"}, {"k": "v"})}  # pragma: allowlist secret
    result = redact_secrets(payload)
    assert isinstance(result["items"], tuple)
    assert result["items"][0]["password"] == REDACTED_VALUE
    assert result["items"][1]["k"] == "v"


# =====================================================================
# AC3.4 — Edge cases
# =====================================================================


@pytest.mark.unit
def test_redact_none_value() -> None:
    """Value None: chave sensível ainda é redactada (defesa em profundidade)."""
    result = redact_secrets({"password": None, "user": None})
    assert result["password"] == REDACTED_VALUE
    assert result["user"] is None


@pytest.mark.unit
def test_redact_empty_string_value() -> None:
    """Value '' (empty string) em chave sensível: também redactada."""
    result = redact_secrets({"password": "", "secret": ""})
    assert result["password"] == REDACTED_VALUE
    assert result["secret"] == REDACTED_VALUE


@pytest.mark.unit
def test_redact_int_bool_values() -> None:
    """Ints, bools em chave sensível: também redactados."""
    result = redact_secrets({"password": 12345, "auth": True, "token": 0})
    assert result["password"] == REDACTED_VALUE
    assert result["auth"] == REDACTED_VALUE
    assert result["token"] == REDACTED_VALUE


@pytest.mark.unit
def test_redact_empty_dict() -> None:
    """Empty dict: retorna empty dict sem erro."""
    assert redact_secrets({}) == {}


@pytest.mark.unit
def test_redact_empty_list() -> None:
    """Empty list: retorna empty list sem erro."""
    assert redact_secrets([]) == []


@pytest.mark.unit
def test_redact_leaf_value_passthrough() -> None:
    """Valores leaf (str, int, etc) passam direto (no-op)."""
    assert redact_secrets("hello") == "hello"
    assert redact_secrets(42) == 42
    assert redact_secrets(None) is None
    assert redact_secrets(True) is True


@pytest.mark.unit
def test_redact_list_of_strings_no_dict_inside() -> None:
    """Lista de strings sem chave parent → no-op (não há key context)."""
    payload = {"tags": ["alice", "bob", "secret-value-but-no-key-context"]}
    result = redact_secrets(payload)
    # 'tags' não é sensitive key, valor preservado integralmente.
    assert result["tags"] == ["alice", "bob", "secret-value-but-no-key-context"]


@pytest.mark.unit
def test_redact_preserves_allowlist_keys() -> None:
    """Allow-list keys (já-redactados pelo dev) são preservados sem alteração."""
    payload = {"key_redacted": "***", "credential_redacted": "***"}
    result = redact_secrets(payload)
    assert result["key_redacted"] == "***"
    assert result["credential_redacted"] == "***"


@pytest.mark.unit
def test_redact_mutates_in_place_for_dict() -> None:
    """Optimização: dict é mutado in-place (perf — log dicts são ephemerais)."""
    payload: dict[str, Any] = {"password": "x", "ok": "y"}
    result = redact_secrets(payload)
    assert result is payload  # mesma identidade


# =====================================================================
# AC7 — Property test (Hypothesis)
# =====================================================================


# Strategy: dicts com chaves arbitrárias (mix de sensíveis e não-sensíveis).
_SENSITIVE_KEY_NAMES = sorted(set(SENSITIVE_KEY_SUBSTRINGS))
_SAFE_KEY_NAMES = ["user", "trade_id", "symbol", "exchange", "thread", "event"]


@st.composite
def _mixed_dict_strategy(draw: st.DrawFn) -> dict[str, Any]:
    n_keys = draw(st.integers(min_value=1, max_value=8))
    keys = draw(
        st.lists(
            st.sampled_from(_SENSITIVE_KEY_NAMES + _SAFE_KEY_NAMES),
            min_size=n_keys,
            max_size=n_keys,
            unique=True,
        )
    )
    payload: dict[str, Any] = {}
    for k in keys:
        # Valor arbitrário (pequeno).
        v = draw(
            st.one_of(
                st.text(min_size=1, max_size=20),
                st.integers(min_value=0, max_value=10**9),
                st.booleans(),
                st.none(),
            )
        )
        payload[k] = v
    return payload


@pytest.mark.unit
@pytest.mark.property
@given(payload=_mixed_dict_strategy())
@settings(max_examples=100, deadline=None)
def test_property_redaction_complete_for_sensitive_keys(payload: dict[str, Any]) -> None:
    """Property: para qualquer dict, secret keys são SEMPRE redactadas.

    Quinn — INV-credenciais: 100 examples; falsifica se UMA secret key
    escapar sem redaction.
    """
    # Snapshot de quais keys são sensíveis ANTES (porque _is_sensitive_key
    # é reflexão pura — sem state).
    sensitive_keys = {k for k in payload if _is_sensitive_key(k)}
    safe_values_before = {k: v for k, v in payload.items() if k not in sensitive_keys}

    result = redact_secrets(dict(payload))  # cópia para preservar payload

    # Toda chave sensível foi mascarada.
    for k in sensitive_keys:
        assert result[k] == REDACTED_VALUE, f"sensitive key {k!r} not redacted"

    # Toda chave segura foi preservada.
    for k, v in safe_values_before.items():
        assert result[k] == v, f"safe key {k!r} value changed: {v!r} → {result[k]!r}"


@pytest.mark.unit
@pytest.mark.property
@given(
    sensitive_key=st.sampled_from(_SENSITIVE_KEY_NAMES),
    nested_value=st.text(min_size=1, max_size=30),
)
@settings(max_examples=50, deadline=None)
def test_property_redaction_recursive_nesting(
    sensitive_key: str,
    nested_value: str,
) -> None:
    """Property: sensitive key em qualquer profundidade de aninhamento é
    redactada.
    """
    payload: dict[str, Any] = {
        "level1": {
            "level2": {
                "level3": {
                    sensitive_key: nested_value,
                    "safe": "ok",
                },
            },
        },
    }
    result = redact_secrets(payload)
    assert result["level1"]["level2"]["level3"][sensitive_key] == REDACTED_VALUE
    assert result["level1"]["level2"]["level3"]["safe"] == "ok"
