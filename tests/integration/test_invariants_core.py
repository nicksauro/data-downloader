"""tests/integration/test_invariants_core.py — Meta-test cobertura INV.

Story 2.10 / Quinn authority. Audita que o consolidated property suite
(``tests/property/test_invariants_core.py``) **realmente** contém property
tests Hypothesis para cada invariante crítica documentada em
``docs/qa/INVARIANTS_TESTS.md``.

Não é teste funcional — é guard-rail meta. Quinn requer que toda nova INV
adicionada ao mapa tenha entry correspondente aqui (test fail = força
refresh do mapping). Isso reduz drift entre documentação e suite.

Verificações:

1. Cada INV-N abaixo tem test correspondente carregado do property suite.
2. Cada test usa decorator ``@given`` (Hypothesis-based).
3. Cobertura agregada >= 6 INVs (gate ADR-014 / Story 2.10 AC4).
"""

from __future__ import annotations

import importlib
import inspect

import pytest

# Lista canônica de INVs cobertas pelo property suite (Story 2.10).
# Cada entry: (inv_id, nome_função_hypothesis, descrição_curta)
EXPECTED_INV_COVERAGE: list[tuple[str, str, str]] = [
    (
        "INV-1",
        "test_inv1_well_behaved_callback_never_violates_for_any_input",
        "callback NÃO chama DLL",
    ),
    ("INV-2", "test_inv2_dedup_idempotent_under_concat", "dedup(L ++ L) == dedup(L)"),
    ("INV-2", "test_inv2_dedup_idempotent_under_self_apply", "dedup(dedup(L)) == dedup(L)"),
    (
        "INV-3",
        "test_inv3_write_atomicity_no_tmp_files_after_success",
        "write atômico — sem tmp órfão",
    ),
    ("INV-7", "test_inv7_read_returns_sorted_by_timestamp_ns", "read sorted by timestamp_ns ASC"),
    (
        "INV-9",
        "test_inv9_migration_v100_to_v110_preserves_common_fields",
        "migration aditiva preserva campos comuns",
    ),
    (
        "INV-11",
        "test_inv11_assign_sequence_then_dedup_is_stable",
        "thread-safe equivalente: dedup determinístico",
    ),
]


@pytest.mark.integration
def test_property_suite_module_imports_cleanly() -> None:
    """O módulo do suite consolidado importa sem erro."""
    mod = importlib.import_module("tests.property.test_invariants_core")
    assert mod is not None


@pytest.mark.integration
@pytest.mark.parametrize(
    "inv_id, fn_name, description",
    EXPECTED_INV_COVERAGE,
    ids=[f"{i}-{n}" for i, n, _ in EXPECTED_INV_COVERAGE],
)
def test_invariant_has_hypothesis_property_test(
    inv_id: str, fn_name: str, description: str
) -> None:
    """Cada INV listada DEVE ter test correspondente decorado com @given."""
    mod = importlib.import_module("tests.property.test_invariants_core")
    fn = getattr(mod, fn_name, None)
    assert fn is not None, (
        f"{inv_id}: function {fn_name!r} ausente em test_invariants_core. "
        f"Esperado: property test para '{description}'."
    )
    # Heurística: Hypothesis envolve a função em um wrapper; checar
    # presença de atributo 'hypothesis' (settings/strategy attached).
    assert hasattr(fn, "hypothesis") or hasattr(fn, "_hypothesis_internal_use_settings"), (
        f"{inv_id}: function {fn_name!r} encontrada mas SEM @given decorator. "
        f"Esperado: Hypothesis property test."
    )


@pytest.mark.integration
def test_aggregate_coverage_meets_minimum_6_inv() -> None:
    """Quinn AC4 / ADR-014: >= 6 INVs cobertas por property tests."""
    distinct_invs = {inv for inv, _, _ in EXPECTED_INV_COVERAGE}
    assert len(distinct_invs) >= 6, (
        f"Cobertura agregada de {len(distinct_invs)} INVs é insuficiente "
        f"(mínimo 6 — ADR-014 / Story 2.10 AC4). Cobertas: {sorted(distinct_invs)}"
    )


@pytest.mark.integration
def test_strategies_module_exports_canonical_strategies() -> None:
    """Strategies canônicas exportadas pelo módulo property suite."""
    mod = importlib.import_module("tests.property.test_invariants_core")
    expected_strategies = [
        "valid_trade_record_strategy",
        "valid_partition_key_strategy",
        "trade_spec_strategy",
    ]
    for name in expected_strategies:
        assert hasattr(mod, name), f"strategy canônica {name!r} ausente"
        fn = getattr(mod, name)
        assert callable(fn), f"{name!r} deve ser callable (factory de strategy)"
        assert inspect.isfunction(fn) or inspect.isbuiltin(
            fn
        ), f"{name!r} deve ser função (não classe)"
