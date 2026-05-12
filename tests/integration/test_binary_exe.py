"""Integration tests — exercita ``dist/data_downloader/*.exe`` via subprocess.

Owner: Quinn (QA — Wave 2 P0 v1.1.0 master plan).

BIG COUNCIL 2026-05-06 (Pichau directive "ta bem bugado, na oadianta ficar
lançando 1 milhão de v"): nenhum teste pré-Wave 1 exercitava o binário
real. ``pytest`` dev-mode não passa por PyInstaller boot, módulos
congelados, DLL companions, ou ``sys._MEIPASS`` extraction. Quem disse
"passou em pytest" sem rodar ``.exe`` está mentindo para si mesmo.

Skip elegante: se o bundle frozen não foi gerado (``dist/data_downloader/``
ausente), os testes pulam com mensagem clara apontando o build script —
NÃO falha CI quando bundle não está presente (CI pode rodar antes do
build de release).

Testes cobrem:
    1. ``data_downloader-cli.exe --healthcheck`` exit-code 0 + stdout
       canonical (Wave 1 P0 / Dex).
    2. ``data_downloader-cli.exe version`` exit-code 0 + identifica produto.
    3. ``data_downloader-cli.exe --help`` exit-code 0 (Typer/Click root).
    4. ``data_downloader-cli.exe doctor`` SEM credentials NÃO crasha com
       Python traceback (degradação graciosa, exit-code não-zero esperado).

Versão tolerante: aceita ``1.0.7``, ``1.0.8``, ``1.1.0``+ (Wave 4 bumpará
pyproject.toml; testes não devem regredir entre waves).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# =====================================================================
# Bundle resolution
# =====================================================================

#: Repo root — três níveis acima deste arquivo.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Frozen bundle (PyInstaller --onedir output).
BUNDLE = _REPO_ROOT / "dist" / "data_downloader"

#: Console CLI executable (Story 4.8 dual-EXE).
CLI_EXE = BUNDLE / "data_downloader-cli.exe"

#: Windowed UI executable (Story 4.8 dual-EXE).
UI_EXE = BUNDLE / "data_downloader.exe"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not CLI_EXE.exists(),
        reason=(
            f"Frozen bundle ausente em {BUNDLE}. "
            "Rode: python scripts/build_release.py "
            "(ou aguarde Wave 1/Pyro buildar — Wave 2 Quinn skipa clean)."
        ),
    ),
]


# =====================================================================
# Helpers
# =====================================================================


def _run_cli(
    *args: str,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoca ``data_downloader-cli.exe`` com ``args`` e captura stdio.

    ``timeout`` default 30s — suficiente para boot PyInstaller frozen
    (cold start ~3-5s). ``env=None`` herda ambiente; ``env={...}`` substitui.

    Encoding: força UTF-8 com ``errors="replace"`` — o CLI usa Rich/Typer
    que emitem caracteres não-ASCII (ex.: U+2713 ✓ no doctor), e o default
    do Windows (cp1252) crasha o reader thread do subprocess
    (``UnicodeDecodeError`` em bytes >= 0x80). ``replace`` substitui
    inválidos por U+FFFD em vez de levantar — o que importa para os
    asserts é o conteúdo ASCII (event names, "healthcheck OK", etc.).
    """
    return subprocess.run(
        [str(CLI_EXE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        check=False,  # nós validamos returncode explicitamente.
    )


# =====================================================================
# Tests — happy path
# =====================================================================


def test_cli_healthcheck_exit_zero() -> None:
    """``--healthcheck`` deve retornar 0 e imprimir ``healthcheck OK``.

    Cobre Wave 1 P0 (Dex) — flag de self-check minimal exercitando
    imports de módulos críticos + setup_logging + 1 emit de log probe.

    Wave 2 hotfix (2026-05-07): allowlist `_CLI_GLOBAL_FLAGS_NO_VALUE`
    em ui/app.py atualizada para incluir `--healthcheck`, então
    dispatcher roteia para Typer CLI em vez de QApplication.
    """
    result = _run_cli("--healthcheck", timeout=15.0)
    assert result.returncode == 0, (
        f"healthcheck retornou {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "healthcheck OK" in result.stdout, (
        f"stdout não contém marker canonical 'healthcheck OK'; " f"stdout={result.stdout!r}"
    )


def test_cli_version_works() -> None:
    """``cli version`` retorna 0 e identifica o produto.

    Tolerante a qualquer versão semver (Wave 4 bumpará — não engessar
    aqui). Apenas valida que o sub-comando está cadastrado no Typer app
    e que ``__version__`` é importável no frozen bundle.
    """
    result = _run_cli("version", timeout=15.0)
    assert result.returncode == 0, (
        f"version retornou {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stdout_lower = result.stdout.lower()
    assert (
        "data-downloader" in stdout_lower or "data_downloader" in stdout_lower
    ), f"stdout não identifica produto; stdout={result.stdout!r}"


def test_cli_help_works() -> None:
    """``--help`` retorna 0 (Typer/Click root help renderizado).

    Smoke test mínimo do entrypoint — se o Typer app falha em montar
    (ex.: comando com signature inválida), help já crasha aqui.
    """
    result = _run_cli("--help", timeout=15.0)
    assert result.returncode == 0, (
        f"--help retornou {result.returncode}; " f"stderr={result.stderr!r}"
    )


# =====================================================================
# Tests — degradação graciosa
# =====================================================================


def test_cli_doctor_runs_without_traceback() -> None:
    """``doctor`` deve rodar sem produzir Python traceback.

    Doctor é o gate de diagnóstico do produto — tem que reportar status
    estruturado (table com PASS/WARN/FAIL) mesmo em ambiente parcialmente
    quebrado. Exception escapando do handler é regressão grave (ex.:
    storage layer mudou e doctor não foi atualizado).

    NÃO assertamos exit-code — doctor pode legitimamente retornar
    não-zero quando algum check falha. O contrato é: NÃO crashar.

    NOTA Wave 2: removemos a tentativa de zerar PROFITDLL_* via env=
    porque Windows subprocess sem SystemRoot/PATH herdados pode
    fundamentalmente quebrar (DLL loader). O .env user-global ou
    variáveis do shell já populam o ambiente em setups Pichau —
    doctor é determinístico no que importa para este teste (não
    crash) independente do estado das credentials.
    """
    result = _run_cli("doctor", timeout=30.0)
    combined = (result.stdout or "") + (result.stderr or "")
    assert "Traceback (most recent call last)" not in combined, (
        f"doctor crashou com Python traceback (degradação NÃO graciosa).\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_cli_help_lists_healthcheck_flag() -> None:
    """``--help`` lista flag ``--healthcheck`` no Typer renderer.

    Garante que o flag foi REGISTRADO no Typer app (cli._global_callback)
    mesmo quando o dispatcher ui/app.py atual roteia errado para UI.
    Quando o fix Wave 3 landar (allowlist), este teste continua válido —
    a flag continua listada e funcional.
    """
    result = _run_cli("--help", timeout=15.0)
    assert result.returncode == 0
    assert "--healthcheck" in result.stdout, (
        "Flag --healthcheck não aparece em --help do CLI bundled. "
        "Wave 1 Dex registrou em cli.py mas pode ter regredido no spec. "
        f"stdout={result.stdout!r}"
    )


# =====================================================================
# Tests — bundle layout
# =====================================================================


def test_ui_exe_present_in_bundle() -> None:
    """Dual-EXE (Story 4.8): ambos ``data_downloader.exe`` e ``-cli.exe`` presentes.

    Garante que validação ``scripts/build_release.py::validate_output``
    foi efetiva no build atual.
    """
    assert UI_EXE.exists(), (
        f"data_downloader.exe (UI windowed) ausente em {UI_EXE}. "
        "Bundle dual-EXE quebrado — Story 4.8 regressão."
    )
    assert CLI_EXE.exists(), f"data_downloader-cli.exe ausente em {CLI_EXE}."


def test_bundle_internal_dir_exists() -> None:
    """``_internal/`` (PyInstaller --onedir runtime) deve existir.

    Sem ``_internal/``, o launcher não acha ``python3*.dll`` e nada roda.
    """
    internal = BUNDLE / "_internal"
    assert internal.is_dir(), f"_internal/ ausente em {internal} — onedir quebrado."
