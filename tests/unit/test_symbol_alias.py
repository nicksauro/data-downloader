"""tests/unit/test_symbol_alias.py — Story 4.6 / v1.0.2 fix UX (Q-DRIFT-32).

Cobertura de :func:`data_downloader.orchestrator.symbol_alias.resolve_alias`:

- Aliases de raiz (``WDO`` → ``WDOFUT``, etc.) → 4 raízes cobertas.
- Continuous futures passam direto (``WDOFUT`` → ``WDOFUT``).
- Contratos com vencimento (``WDOJ26``) emitem ``UserWarning``.
- Equities (PETR4, BBAS3, ABEV3) passam direto sem warning.
- Normalização de case e whitespace (``  wdo  `` → ``WDOFUT``).
- Símbolo vazio é tolerado (caller valida).

Story 4.6 ACs 1-2 (UX simplification — Pichau directive 2026-05-05).
"""

from __future__ import annotations

import warnings

import pytest

from data_downloader.orchestrator.symbol_alias import resolve_alias


@pytest.mark.parametrize(
    ("input_symbol", "expected"),
    [
        # Raízes → continuous future (Q-DRIFT-32 — recomendado).
        ("WDO", "WDOFUT"),
        ("WIN", "WINFUT"),
        ("IND", "INDFUT"),
        ("DOL", "DOLFUT"),
    ],
)
def test_resolve_alias_root_to_continuous(input_symbol: str, expected: str) -> None:
    """Raízes WDO/WIN/IND/DOL → ROOTFUT, sem warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # qualquer warning vira erro
        assert resolve_alias(input_symbol) == expected


def test_resolve_alias_continuous_passthrough() -> None:
    """Continuous future já canônico passa direto sem warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_alias("WDOFUT") == "WDOFUT"
        assert resolve_alias("WINFUT") == "WINFUT"


@pytest.mark.parametrize(
    "equity",
    [
        "PETR4",
        "BBAS3",
        "ABEV3",
        "VALE3",
        "ITUB4",
        "WEGE3",
    ],
)
def test_resolve_alias_equity_passthrough(equity: str) -> None:
    """Equities passam direto sem warning (symbology já estável)."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_alias(equity) == equity


def test_resolve_alias_vencimento_emits_warning() -> None:
    """Contratos com vencimento (WDOJ26) emitem UserWarning Q-DRIFT-32."""
    with pytest.warns(UserWarning, match="Q-DRIFT-32"):
        result = resolve_alias("WDOJ26")
    # Warning é emitido mas o input é respeitado (não rewriting).
    assert result == "WDOJ26"


@pytest.mark.parametrize(
    "vencimento",
    ["WDOJ26", "WINH26", "INDM25", "DOLZ27", "WDOG26"],
)
def test_resolve_alias_all_vencimento_letters(vencimento: str) -> None:
    """Todas as letras CME válidas (F G H J K M N Q U V X Z) disparam warning."""
    with pytest.warns(UserWarning):
        result = resolve_alias(vencimento)
    assert result == vencimento


def test_resolve_alias_lowercase_normalization() -> None:
    """Input lowercase é normalizado para uppercase."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_alias("wdo") == "WDOFUT"
        assert resolve_alias("petr4") == "PETR4"
        assert resolve_alias("wdofut") == "WDOFUT"


def test_resolve_alias_whitespace_strip() -> None:
    """Whitespace ao redor é removido."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_alias("  WDO  ") == "WDOFUT"
        assert resolve_alias("\tPETR4\n") == "PETR4"


def test_resolve_alias_empty_string() -> None:
    """Empty string é tolerada — caller (CLI) valida no schema typer."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_alias("") == ""
        assert resolve_alias("   ") == ""


def test_resolve_alias_unknown_root_passthrough() -> None:
    """Raízes não cobertas (futuro V1.x) passam direto sem warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # ISP, BGI, etc. ainda não estão no _FUT_ROOTS — não devem emitir warning.
        assert resolve_alias("ISPFUT") == "ISPFUT"
        assert resolve_alias("BGI") == "BGI"
