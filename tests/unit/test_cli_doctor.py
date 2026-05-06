"""tests/unit/test_cli_doctor.py — Story 4.9 (v1.0.3 hotfix).

Cobertura do comando ``data-downloader doctor`` adicionado em
``src/data_downloader/cli.py``. Verifica que cada um dos 5 checks
estáticos (+ 1 opcional via ``--with-handshake``) reporta corretamente
PASS / FAIL / WARN e que o exit code agrega corretamente.

Owner: Dex (dev). Story 4.9 (Owners Council B5 mini-council).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _seed_catalog(db_path: Path, version: str = "1.1.0") -> None:
    """Seed minimal catalog with ``catalog_version`` em ``_schema_meta``."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO _schema_meta(key, value) VALUES('catalog_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (version,),
        )
        conn.commit()


def _patch_static_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patcheia os 4 checks que dependem do mundo real para PASS.

    Mantém apenas ``_check_credentials`` (env vars) e ``_check_disk``
    (tmp_path) reais — que controlamos via fixtures.
    """
    from data_downloader import cli as cli_module

    monkeypatch.setattr(cli_module, "_check_dll_companions", lambda: ("PASS", "mocked OK"))
    monkeypatch.setattr(cli_module, "_check_connectivity", lambda: ("PASS", "mocked OK"))


# =====================================================================
# All checks pass → exit 0
# =====================================================================


def test_doctor_all_checks_pass(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Com env vars + DLL companions OK + catalog 1.1.0 → exit 0."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stdout
    assert "PASS" in result.stdout
    assert "FAIL" not in result.stdout or "0 fail(s)" in result.stdout


# =====================================================================
# Credentials missing → exit 1
# =====================================================================


def test_doctor_credentials_missing(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sem PROFITDLL_KEY/USER/PASS → check Credenciais FAIL + exit 1."""
    for var in ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS"):
        monkeypatch.delenv(var, raising=False)
    for var in ("PROFIT_USER", "PROFIT_PASS"):
        monkeypatch.delenv(var, raising=False)
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1, result.stdout
    assert "Credenciais" in result.stdout
    assert "FAIL" in result.stdout
    # Mensagem cita as 3 vars ausentes.
    assert "PROFITDLL_KEY" in result.stdout


# =====================================================================
# DLL companions missing → exit 1
# =====================================================================


def test_doctor_dll_companions_missing(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``PROFITDLL_PATH`` apontando p/ path inválido → companions FAIL."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")

    from data_downloader import cli as cli_module

    # Patch ``DEFAULT_DLL_PATH`` para diretório vazio (sem companions).
    empty_dir = tmp_path / "empty_dll_dir"
    empty_dir.mkdir()
    fake_dll_path = empty_dir / "ProfitDLL.dll"  # not exists
    monkeypatch.setattr("data_downloader.dll.wrapper.DEFAULT_DLL_PATH", fake_dll_path)
    monkeypatch.setattr(cli_module, "_check_connectivity", lambda: ("PASS", "mocked"))

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1, result.stdout
    assert "DLL companions" in result.stdout
    assert "FAIL" in result.stdout


# =====================================================================
# Disk read-only → exit 1
# =====================================================================


def test_doctor_disk_unwritable(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``data_dir`` que não pode ser criado/escrito → Disk FAIL."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    # Patcheia _check_disk para simular falha de write — mais
    # determinístico que tentar criar dir read-only no Windows.
    monkeypatch.setattr(
        cli_module,
        "_check_disk",
        lambda data_dir: ("FAIL", f"Não writável: {data_dir}"),
    )

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 1, result.stdout
    assert "Disk" in result.stdout
    assert "FAIL" in result.stdout


# =====================================================================
# Schema outdated (1.0.0) → WARN, mas não FAIL
# =====================================================================


def test_doctor_schema_outdated_warns_but_not_fail(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """schema_version=1.0.0 → check Schema WARN (não FAIL); exit 0."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.0.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    # WARN não deveria gerar exit 1.
    assert result.exit_code == 0, result.stdout
    assert "WARN" in result.stdout
    assert "1.0.0" in result.stdout


# =====================================================================
# Schema missing (catalog inexistente) → WARN
# =====================================================================


def test_doctor_schema_missing_catalog_warns(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """catalog.db inexistente → Schema WARN (first-run válido)."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    # Sem _seed_catalog — catalog não existe.
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stdout
    assert "WARN" in result.stdout


# =====================================================================
# Legacy credentials (PROFIT_USER/PASS sem prefixo) → WARN
# =====================================================================


def test_doctor_legacy_credentials_warn(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Apenas ``PROFIT_USER``/``PROFIT_PASS`` (sem PROFITDLL_*) → WARN."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.delenv("PROFITDLL_USER", raising=False)
    monkeypatch.delenv("PROFITDLL_PASS", raising=False)
    monkeypatch.setenv("PROFIT_USER", "legacy_u")
    monkeypatch.setenv("PROFIT_PASS", "legacy_p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    # WARN não vira FAIL.
    assert result.exit_code == 0, result.stdout
    assert "WARN" in result.stdout
    assert "legado" in result.stdout.lower() or "legacy" in result.stdout.lower()


# =====================================================================
# --with-handshake flag (mocked DLL OK)
# =====================================================================


def test_doctor_with_handshake_flag_invokes_check(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--with-handshake`` adiciona check 'DLL handshake' à tabela."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    # Mock handshake direto.
    monkeypatch.setattr(cli_module, "_check_dll_handshake", lambda: ("PASS", "mocked OK"))

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path), "--with-handshake"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stdout
    assert "DLL handshake" in result.stdout


def test_doctor_without_handshake_omits_check(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sem ``--with-handshake`` → 'DLL handshake' NÃO aparece na tabela."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        ["doctor", "--data-dir", str(tmp_path)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stdout
    assert "DLL handshake" not in result.stdout


# =====================================================================
# run_doctor_checks pure function (testable API)
# =====================================================================


def test_run_doctor_checks_returns_exit_code_and_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """API pure ``run_doctor_checks`` retorna ``(exit_code, results)``."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader.cli import run_doctor_checks

    exit_code, results = run_doctor_checks(data_dir=tmp_path)

    assert exit_code == 0
    # 5 checks default (sem handshake).
    assert len(results) == 5
    names = [r[0] for r in results]
    assert "DLL companions" in names
    assert "Credenciais" in names
    assert "Disk" in names
    assert "Schema" in names
    assert "Connectivity" in names
    # Cada item é tupla (name, status, msg).
    for name, status, msg in results:
        assert isinstance(name, str) and name
        assert status in ("PASS", "FAIL", "WARN")
        assert isinstance(msg, str)


def test_run_doctor_checks_with_handshake_adds_6th_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``with_handshake=True`` produz 6 checks (5 default + handshake)."""
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")
    _seed_catalog(tmp_path / "history" / "catalog.db", version="1.1.0")
    _patch_static_checks_pass(monkeypatch)

    from data_downloader import cli as cli_module
    from data_downloader.cli import run_doctor_checks

    monkeypatch.setattr(cli_module, "_check_dll_handshake", lambda: ("PASS", "mocked"))

    exit_code, results = run_doctor_checks(data_dir=tmp_path, with_handshake=True)

    assert len(results) == 6
    names = [r[0] for r in results]
    assert "DLL handshake" in names
