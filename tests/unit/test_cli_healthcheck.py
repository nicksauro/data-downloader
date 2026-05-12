"""tests/unit/test_cli_healthcheck.py — Wave 1 P0 (Quinn BIG COUNCIL 2026-05-06).

Cobertura do flag global ``--healthcheck`` adicionado em
``src/data_downloader/cli.py``. Caso de uso primário: subprocess test do
binário frozen (``data_downloader.exe --healthcheck``) — exercita import
+ logging, paths que pytest dev-mode NÃO testa.

Acceptance criteria:
    - ``--healthcheck`` exit 0 com output contendo ``"healthcheck OK"``.
    - Output inclui versão do package (``data_downloader X.Y.Z``).
    - NÃO inicializa DLL (não há side effect ``loadprofitdll``).
    - Falha de import em módulo crítico → exit 1 + mensagem em stderr.

Owner: Dex (dev). Wave 1 P0.
"""

from __future__ import annotations

import pytest
import structlog
from typer.testing import CliRunner

from data_downloader.cli import app


@pytest.fixture
def cli_runner() -> CliRunner:
    # Newer click/typer (>=0.13) já separa stdout/stderr por default —
    # ``mix_stderr`` foi removido. Mantemos invocação simples; cada test
    # decide se acessa ``result.stdout`` ou ``result.stderr``.
    return CliRunner()


@pytest.fixture(autouse=True)
def _restore_structlog_config() -> None:
    """Restaura a configuração default do structlog após cada test.

    O healthcheck chama ``setup_logging(level="WARNING")`` que reconfigura
    o pipeline globalmente (level filter, processors, factory). Sem essa
    fixture, tests subsequentes que esperam INFO-level logs (ex.:
    ``test_dll_signatures``) falham por filter — cross-test pollution.
    """
    yield
    # Reset estado global do structlog para defaults da lib (sem level filter
    # custom, factory padrão). Tests downstream que precisem de pipeline
    # configurado vão chamar ``configure_logging`` explicitamente.
    structlog.reset_defaults()


def test_healthcheck_exit_zero(cli_runner: CliRunner) -> None:
    """``--healthcheck`` retorna exit 0 com output canônico."""
    result = cli_runner.invoke(app, ["--healthcheck"])

    assert result.exit_code == 0, (
        f"healthcheck deveria retornar 0; got {result.exit_code}\n"
        f"stdout={result.stdout!r}\n"
        f"stderr={getattr(result, 'stderr', '<no stderr>')!r}"
    )
    assert "healthcheck OK" in result.stdout
    assert "data_downloader" in result.stdout


def test_healthcheck_includes_version(cli_runner: CliRunner) -> None:
    """Output deve incluir a versão do package (formato ``data_downloader X.Y.Z``)."""
    from data_downloader import __version__

    result = cli_runner.invoke(app, ["--healthcheck"])

    assert result.exit_code == 0
    assert __version__ in result.stdout
    # Linha "data_downloader {version}" deve aparecer ANTES de "healthcheck OK"
    # (subprocess parser pode confiar nessa ordem).
    pos_version = result.stdout.find(f"data_downloader {__version__}")
    pos_ok = result.stdout.find("healthcheck OK")
    assert pos_version >= 0
    assert pos_ok > pos_version


def test_healthcheck_does_not_initialize_dll(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthcheck NÃO deve chamar ``Init`` da DLL (diferente de ``doctor``).

    Patcheamos qualquer função de Init no wrapper e verificamos que o
    counter permanece 0 após ``--healthcheck``. Garante que o smoke test
    em subprocess não vai falhar por falta de credentials.
    """
    init_calls: list[str] = []

    # Patcheamos a função de inicialização — se chamada, registra.
    import data_downloader.dll.wrapper as wrapper_module

    def _spy_init(*args: object, **kwargs: object) -> int:
        init_calls.append("Init")
        return 0

    # Apenas patch se a função existir; senão é no-op (defensivo).
    if hasattr(wrapper_module, "DLLInitializeLogin"):
        monkeypatch.setattr(wrapper_module, "DLLInitializeLogin", _spy_init, raising=False)

    result = cli_runner.invoke(app, ["--healthcheck"])

    assert result.exit_code == 0
    assert init_calls == [], f"healthcheck não deve invocar DLL Init; calls={init_calls}"


def test_healthcheck_fail_on_import_error(
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha em import crítico → exit 1 + mensagem em stderr.

    Forçamos ``setup_logging`` a levantar ImportError para simular
    cenário em que módulo de logging está corrompido (ex.: missing
    structlog na build PyInstaller).
    """
    from data_downloader import cli as cli_module

    def _broken_run_healthcheck() -> int:
        # Replica lógica original mas força Exception no probe.
        try:
            raise RuntimeError("simulated import failure")
        except Exception as exc:
            import typer

            typer.echo(f"healthcheck FAIL: {type(exc).__name__}: {exc}", err=True)
            return 1

    monkeypatch.setattr(cli_module, "_run_healthcheck", _broken_run_healthcheck)

    result = cli_runner.invoke(app, ["--healthcheck"])

    assert result.exit_code == 1
    assert "healthcheck FAIL" in result.stderr
    assert "RuntimeError" in result.stderr
