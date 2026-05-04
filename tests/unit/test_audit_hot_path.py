"""Tests for ``scripts/audit_hot_path.py`` — Story 2.7 / COUNCIL-22.

Smoke + behavior tests para o auditor R21:

- Fixture sintética com violação → audit detecta + reporta.
- Fixture sintética limpa → audit retorna PASS.
- Registry stale (arquivo inexistente) → reporta como violation própria.
- Custom registry override funciona.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Adicionar scripts/ ao path para importar audit_hot_path.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from audit_hot_path import audit  # noqa: E402  type: ignore[import-not-found]


@pytest.fixture
def synthetic_src(tmp_path: Path) -> Path:
    """Cria árvore sintética de src com 1 arquivo violador + 1 limpo."""
    root = tmp_path / "fake_src" / "fake_pkg"
    root.mkdir(parents=True)

    # Arquivo violador — função marcada @hot_path com print + log.info.
    violator = root / "violator.py"
    violator.write_text(
        '''
"""Module violador."""
import logging
log = logging.getLogger(__name__)


# @hot_path
def emit_trade(trade):
    """Hot path violador."""
    print("trade", trade)  # violation: print
    log.info("trade emitted", trade_id=trade.id)  # violation: log.info
    return trade.value
''',
        encoding="utf-8",
    )

    # Arquivo limpo — função marcada @hot_path mas sem violação.
    clean = root / "clean.py"
    clean.write_text(
        '''
"""Module limpo."""


# @hot_path
def emit_trade_clean(trade, counter):
    """Hot path limpo."""
    counter.inc()  # OK — Counter.inc é lock-free
    return trade.value
''',
        encoding="utf-8",
    )

    return root


def test_audit_detects_violations_in_marked_function(synthetic_src: Path) -> None:
    """Função marcada @hot_path com print + log → 2 violations."""
    violator_path = synthetic_src / "violator.py"
    report = audit(synthetic_src, paths=[violator_path], registry=[])
    assert not report.clean
    assert report.functions_audited == 1
    assert len(report.violations) == 2
    rules = {v.rule for v in report.violations}
    assert "print" in rules
    assert "logger.info" in rules


def test_audit_passes_on_clean_function(synthetic_src: Path) -> None:
    """Função marcada @hot_path sem violations → PASS."""
    clean_path = synthetic_src / "clean.py"
    report = audit(synthetic_src, paths=[clean_path], registry=[])
    assert report.clean
    assert report.functions_audited == 1
    assert report.violations == []


def test_audit_reports_stale_registry(tmp_path: Path) -> None:
    """Registry apontando para arquivo inexistente → reportado como violation."""
    fake_src = tmp_path / "fake_src" / "pkg"
    fake_src.mkdir(parents=True)
    bogus = ("nonexistent_module.py", "fn")
    report = audit(fake_src, registry=[bogus])
    # 1 violation de "stale-registry" type.
    assert len(report.violations) == 1
    assert report.violations[0].rule == "stale-registry"


def test_audit_real_project_runs_without_crashing() -> None:
    """Smoke test — audit no source real do projeto não crasha.

    NÃO assert clean (sabemos que há 3 violations baseline em
    download_primitive.py — Story 2.X-cleanup as fixará).
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "data_downloader"
    if not src_root.exists():
        pytest.skip("src/data_downloader não disponível neste ambiente")
    report = audit(src_root)
    # Funções auditadas > 0 (registry tem entradas válidas).
    assert report.functions_audited >= 1
    # Files scanned > 0.
    assert report.files_scanned >= 1
