"""Microcopy completeness audit (Story v1.1.0 Wave 3 P1 — Felix-UI).

Felix-UI BIG COUNCIL identificou drift entre o catálogo de microcopy
estatico (:data:`data_downloader.ui.microcopy_loader.MSG`) e o que o
loader exibe em runtime — algumas keys eram referenciadas no código UI
sem entry correspondente, resultando em ``<microcopy id not found: XYZ>``
visível ao usuário.

Este teste itera sobre TODOS os arquivos ``src/data_downloader/ui/**.py``
e extrai chamadas ``format_msg("KEY", ...)``. Para cada key encontrada,
valida que existe entry em ``MSG``. Falha lista a key + arquivo onde foi
referenciada — facilita o fix.

Padrão regex: ``format_msg("KEY"...)`` com aspas simples ou duplas,
tolerando whitespace ao redor da key. Keys são UPPER_SNAKE_CASE ou
dot.notation (ambos legítimos no catálogo — Story 2.11 introduziu IDs
em dot-notation para erros).

Não checamos o caminho contrário (entries em MSG sem uso) — entries
extras são aceitáveis (compatibilidade reversa, IDs futuros).
"""

from __future__ import annotations

import re
from pathlib import Path

from data_downloader.ui.microcopy_loader import MSG, format_msg

# Path para o pacote UI src/.
_UI_SRC = Path(__file__).resolve().parents[3] / "src" / "data_downloader" / "ui"

# Regex que captura ``format_msg("KEY"...)`` ou ``format_msg('KEY'...)``.
# Suporta keys UPPER_SNAKE e dot.notation (ambos legítimos no catálogo).
_MSG_KEY_PATTERN = re.compile(r"""format_msg\(\s*["']([A-Za-z][A-Za-z0-9_.]*)["']""")


def _collect_referenced_keys() -> dict[str, list[str]]:
    """Varre src/ e retorna {key: [arquivo1, arquivo2, ...]}."""
    found: dict[str, list[str]] = {}
    for py_file in _UI_SRC.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _MSG_KEY_PATTERN.finditer(text):
            key = match.group(1)
            found.setdefault(key, []).append(str(py_file.relative_to(_UI_SRC.parents[2])))
    return found


def test_all_microcopy_keys_present_in_catalog() -> None:
    """TODA key referenciada via ``format_msg("KEY")`` em src/ui/ existe em MSG.

    Falha lista keys + arquivos para guiar fix:

        AssertionError: Microcopy keys missing in catalog:
            BTN_FOO_BAR -> ['src/data_downloader/ui/screens/foo.py']
    """
    referenced = _collect_referenced_keys()
    missing: dict[str, list[str]] = {
        key: files for key, files in referenced.items() if key not in MSG
    }
    assert not missing, (
        "Microcopy keys missing in catalog "
        "(adicione entries em data_downloader.ui.microcopy_loader.MSG):\n"
        + "\n".join(f"  {k} -> {sorted(set(v))}" for k, v in sorted(missing.items()))
    )


def test_referenced_keys_collection_is_non_empty() -> None:
    """Sanidade — se o regex parou de pegar nada, este teste falha cedo
    (não silencia regressões disfarçadas em "0 missing keys")."""
    referenced = _collect_referenced_keys()
    assert len(referenced) >= 50, (
        f"Microcopy reference collection regrediu: only {len(referenced)} keys found "
        "in src/data_downloader/ui — esperado >= 50. Regex pode ter quebrado."
    )


# =====================================================================
# G-1 — UI ↔ source-of-truth (chunk policy) guard (Quinn round 2 review
# 2026-05-11). Garante que microcopy exibida ao usuário em TIP_PERIOD
# reflete o valor real de DEFAULT_CHUNK_DAYS na chunk_strategy, e que o
# prefix-map histórico do chunker (CHUNK_DAYS) também é consistente.
# Drift entre microcopy e source-of-truth = mentira ao usuário.
# =====================================================================


def test_microcopy_reflects_chunk_policy() -> None:
    """TIP_PERIOD deve mencionar o valor real de DEFAULT_CHUNK_DAYS.

    Se Pichau (ou qualquer caller) bumpar a política de 1d/chunk para
    N dias, este teste obriga atualizar a microcopy de TIP_PERIOD para
    refletir o novo N — caso contrário, o tooltip do usuário mente.
    """
    from data_downloader.orchestrator.chunk_strategy import DEFAULT_CHUNK_DAYS

    tip = format_msg("TIP_PERIOD")
    # TIP_PERIOD deve mencionar o valor real de DEFAULT_CHUNK_DAYS
    assert (
        f"{DEFAULT_CHUNK_DAYS}" in tip or f"{DEFAULT_CHUNK_DAYS} dia" in tip
    ), f"TIP_PERIOD ({tip!r}) não reflete DEFAULT_CHUNK_DAYS={DEFAULT_CHUNK_DAYS}"


def test_chunker_chunk_days_consistent_with_strategy() -> None:
    """Garante que ``chunker.CHUNK_DAYS`` valores == ``DEFAULT_CHUNK_DAYS``.

    ADR-023 (Pichau directive 2026-05-07): política unificada — TODOS os
    ativos baixam em ``DEFAULT_CHUNK_DAYS`` dias úteis/chunk. O override
    map ``_CHUNK_OVERRIDES`` em chunk_strategy é vazio em v1.1.0+; o
    prefix-map ``chunker.CHUNK_DAYS`` (legacy compat Story 1.7a) DEVE
    apresentar os mesmos valores para evitar drift entre o orchestrator
    (que consome chunker) e a UI (que consome chunk_strategy).
    """
    from data_downloader.orchestrator.chunk_strategy import DEFAULT_CHUNK_DAYS
    from data_downloader.orchestrator.chunker import CHUNK_DAYS, DEFAULT_EQUITY_CHUNK_DAYS

    # Todos os valores do prefix-map devem ser == DEFAULT_CHUNK_DAYS.
    drift = {prefix: n for prefix, n in CHUNK_DAYS.items() if n != DEFAULT_CHUNK_DAYS}
    assert not drift, (
        f"chunker.CHUNK_DAYS drift contra DEFAULT_CHUNK_DAYS={DEFAULT_CHUNK_DAYS}: "
        f"{drift!r}. ADR-023 exige política unificada — atualize ambos."
    )

    # Default equity fallback também deve bater (mesma política unificada).
    assert DEFAULT_EQUITY_CHUNK_DAYS == DEFAULT_CHUNK_DAYS, (
        f"chunker.DEFAULT_EQUITY_CHUNK_DAYS ({DEFAULT_EQUITY_CHUNK_DAYS}) != "
        f"chunk_strategy.DEFAULT_CHUNK_DAYS ({DEFAULT_CHUNK_DAYS}). ADR-023 exige unificação."
    )
