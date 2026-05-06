"""tests/unit/test_cli_error_mapping_extended.py — Story v1.0.2 fix B-Frozen #3.

Cobertura da extensão do mapping de erros em :func:`data_downloader.cli.download_cmd`:

Antes (v1.0.0/v1.0.1) só humanizávamos prefix ``NL_*``. Sentinelas internas
do wrapper frozen (``COMPANIONS_MISSING``, ``VERIFY_SCRIPT_MISSING``,
``WINDLL_LOAD_FAILED``, ``UNSUPPORTED_PLATFORM``, ``InvalidContract``)
caíam em "Código ?: UNKNOWN" — confuso. Agora cada sentinela tem microcopy
específica + exit code 3 (mapeado).

Testamos via :class:`typer.testing.CliRunner` com factories mockados que
forçam ``DownloadResult(status="failed", error_message="<sentinel>: ...")``.

Story v1.0.2 fix B-Frozen #3 (Nelo+Aria mini-council 2026-05-05).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner


def _make_failed_handle(error_message: str) -> Any:
    """Cria fake handle que retorna DownloadResult(status='failed', error_message=...)."""
    from data_downloader.public_api.handle import DownloadResult

    handle = MagicMock()
    handle.events.return_value = iter([])  # nenhum progress event
    fake_result = DownloadResult(
        job_id="test-job",
        symbol="WDOFUT",
        exchange="F",
        actual_start=None,
        actual_end=None,
        trades_count=0,
        partitions=(),
        duration_seconds=0.1,
        status="failed",
        error_message=error_message,
    )
    handle.result.return_value = fake_result
    return handle


@pytest.fixture
def cli_runner() -> CliRunner:
    # Click 8.2+ removeu o kwarg ``mix_stderr`` (default agora mistura).
    # Mantemos default p/ compat e capturamos via ``result.stdout``.
    return CliRunner()


@pytest.fixture
def patch_download_failed(monkeypatch: pytest.MonkeyPatch):
    """Patch ``api_download`` para retornar handle com status='failed'."""

    def _install(error_message: str) -> None:
        fake_handle = _make_failed_handle(error_message)
        # cli.py importa lazy: ``from data_downloader.public_api.download import download``
        # então monkeypatch o atributo ``download`` no módulo
        # ``data_downloader.public_api.download`` (nome do módulo == nome
        # do callable, usamos importlib para desambiguar).
        import importlib

        dl_mod = importlib.import_module("data_downloader.public_api.download")
        monkeypatch.setattr(dl_mod, "download", lambda **kwargs: fake_handle)

    return _install


# =====================================================================
# Sentinel mapping coverage
# =====================================================================


@pytest.mark.parametrize(
    ("error_message", "expected_title_fragment", "expected_exit"),
    [
        (
            "VERIFY_SCRIPT_MISSING: scripts/verify-dll-companions.py não encontrado",
            "Script de verificação ausente",
            3,
        ),
        (
            "COMPANIONS_MISSING: timezone2.dat ausente em /path",
            "DLL companions ausentes",
            3,
        ),
        (
            "WINDLL_LOAD_FAILED: ProfitDLL.dll could not load (winerror 126)",
            "Falha ao carregar ProfitDLL.dll",
            3,
        ),
        (
            "UNSUPPORTED_PLATFORM: linux not supported",
            "Plataforma não suportada",
            3,
        ),
        (
            "InvalidContract: WDOJ99 não é vigente",
            "Contrato inválido",
            3,
        ),
        (
            "NL_NO_LICENSE: licença expirada",
            "Licença ausente",
            3,
        ),
    ],
)
def test_sentinel_mapping_humanized(
    cli_runner: CliRunner,
    patch_download_failed: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_message: str,
    expected_title_fragment: str,
    expected_exit: int,
) -> None:
    """Cada sentinela mapeada produz microcopy específica + exit 3."""
    patch_download_failed(error_message)
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        [
            "download",
            "--symbol",
            "WDOFUT",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-04",
            "--data-dir",
            str(tmp_path),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == expected_exit, result.stdout
    assert expected_title_fragment in result.stdout


def test_unknown_error_falls_back_generic(
    cli_runner: CliRunner,
    patch_download_failed: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Erro não mapeado (nem NL_ nem sentinela) cai em ERR_DLL_GENERIC, exit 1."""
    patch_download_failed("RandomFooBar: algo deu errado")
    monkeypatch.setenv("PROFITDLL_KEY", "k")
    monkeypatch.setenv("PROFITDLL_USER", "u")
    monkeypatch.setenv("PROFITDLL_PASS", "p")

    from data_downloader import cli as cli_module

    result = cli_runner.invoke(
        cli_module.app,
        [
            "download",
            "--symbol",
            "WDOFUT",
            "--start",
            "2026-05-01",
            "--end",
            "2026-05-04",
            "--data-dir",
            str(tmp_path),
        ],
        catch_exceptions=False,
    )

    # Não mapeado → exit 1 (vs 3 para mapeados).
    assert result.exit_code == 1, result.stdout
    # Microcopy genérica usa "Erro não documentado"
    assert "não documentado" in result.stdout or "UNKNOWN" in result.stdout
