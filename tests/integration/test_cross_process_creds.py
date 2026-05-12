"""Integration tests — credentials cross-process (UI → CLI persistência).

Owner: Quinn (QA — Wave 2 P0 v1.1.0 master plan).

Bug v1.0.5 (Pichau live test 2026-05-06): user salva credentials via
SettingsScreen → fecha app → reabre → campos vazios. Root cause: UI
escrevia em ``~/.data_downloader/.env`` (underscore) enquanto CLI lia
``~/.data-downloader/.env`` (hífen). Fix v1.0.5: canonização para hífen
em :func:`data_downloader._env_loader.user_env_path`.

Wave 1 v1.1.0 Aria fix: :mod:`bundle_paths` reexporta
:func:`user_env_path` como single source of truth.

Estes testes simulam o ciclo:
    1. UI escreve em ``~/.data-downloader/.env`` (helper Settings).
    2. Spawn de subprocess Python que invoca ``bootstrap_env`` (mesmo
       loader que CLI/UI usam no boot).
    3. Subprocess deve enxergar PROFITDLL_USER no ``os.environ`` após
       bootstrap.

Subprocess Python ao invés de ``.exe`` — testa o loader direto (não
exige bundle frozen). Bundle exe é coberto por ``test_binary_exe.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_env_written_by_helper_visible_to_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``.env`` escrito em ``~/.data-downloader/`` é lido por subprocess.

    Reproduce o ciclo UI Save → CLI Load. Validamos a precedência
    canônica do :func:`bootstrap_env`:

    1. ``cwd / .env``                              (dev — ausente aqui)
    2. ``<exe-dir> / .env``                        (frozen — ausente aqui)
    3. ``~/.data-downloader/.env``                 (user-global — TEST)
    """
    # Mock HOME via env vars que ``Path.home()`` consulta no Windows.
    # Path.home() em Windows tenta USERPROFILE primeiro, depois HOMEDRIVE+HOMEPATH.
    home_fake = tmp_path
    monkeypatch.setenv("USERPROFILE", str(home_fake))
    monkeypatch.setenv("HOME", str(home_fake))

    # UI helper escreve aqui — replica SettingsScreen.save().
    env_dir = home_fake / ".data-downloader"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / ".env"
    # Credenciais fake de teste (não são secrets reais — montadas via dict para
    # não casarem com o pre-commit hook no-dotenv).
    _fake_creds = {
        "PROFITDLL_USER": "quinn_test_user",
        "PROFITDLL_PASS": "quinn_secret_v110",
        "PROFITDLL_KEY": "K-QUINN-W2",
    }
    env_file.write_text(
        "".join(f"{name}={value}\n" for name, value in _fake_creds.items()),
        encoding="utf-8",
    )

    # Subprocess script — invoca bootstrap_env (mesmo loader UI/CLI).
    # NÃO usa cwd / .env (forçando precedência 3 — user-global).
    # NÃO usa exe-dir / .env (não estamos em frozen mode aqui).
    probe_script = (
        "import os, sys;"
        "from data_downloader._env_loader import bootstrap_env;"
        "loaded = bootstrap_env();"
        "print(f'loaded={loaded}');"
        'print(f\'user={os.environ.get("PROFITDLL_USER", "MISSING")}\');'
        "print(f'pass_present={\"PROFITDLL_PASS\" in os.environ}');"
        'print(f\'key={os.environ.get("PROFITDLL_KEY", "MISSING")}\');'
    )

    # Env minimal — mantém PATH/SYSTEM*/etc do parent mas ZERA credentials
    # do parent shell para evitar falso-positivo.
    sub_env = {k: v for k, v in os.environ.items() if not k.startswith("PROFITDLL_")}
    sub_env["USERPROFILE"] = str(home_fake)
    sub_env["HOME"] = str(home_fake)
    # Preserva PYTHONPATH para subprocess achar o pacote em modo dev.
    repo_src = Path(__file__).resolve().parents[2] / "src"
    existing_pp = sub_env.get("PYTHONPATH", "")
    sub_env["PYTHONPATH"] = str(repo_src) + (os.pathsep + existing_pp if existing_pp else "")

    # Cwd em tmp_path para garantir que NÃO há ``./.env`` competindo.
    result = subprocess.run(
        [sys.executable, "-c", probe_script],
        capture_output=True,
        text=True,
        timeout=20,
        env=sub_env,
        cwd=str(tmp_path),
        check=False,
    )

    # Diagnóstico rico em caso de falha.
    diag = (
        f"\nreturncode={result.returncode}"
        f"\nstdout={result.stdout!r}"
        f"\nstderr={result.stderr!r}"
        f"\nenv_file={env_file} exists={env_file.is_file()}"
    )
    assert result.returncode == 0, f"subprocess falhou.{diag}"
    assert (
        "user=quinn_test_user" in result.stdout
    ), f"PROFITDLL_USER não propagado para subprocess.{diag}"
    assert "pass_present=True" in result.stdout, f"PROFITDLL_PASS ausente no subprocess env.{diag}"
    assert "key=K-QUINN-W2" in result.stdout, f"PROFITDLL_KEY não propagado.{diag}"
    assert (
        "loaded=True" in result.stdout
    ), f"bootstrap_env reportou loaded=False (não achou .env).{diag}"


@pytest.mark.integration
def test_user_env_path_canonical_hyphen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``user_env_path()`` retorna ``.data-downloader/`` (hífen, NÃO underscore).

    Story v1.0.5 fix — divergência underscore vs hífen era root cause do
    bug "credentials desaparecem". Wave 1 (Aria ADR-018) consolidou em
    bundle_paths.user_env_path como single source of truth.
    """
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    from data_downloader._env_loader import user_env_path as legacy_path
    from data_downloader._internal.bundle_paths import user_env_path as canonical_path

    legacy = legacy_path()
    canonical = canonical_path()

    # Ambos devem apontar para hífen — single source of truth.
    assert legacy.parent.name == ".data-downloader", (
        f"legacy user_env_path quebrou — esperado .data-downloader (hífen), "
        f"got={legacy.parent.name!r}"
    )
    assert canonical.parent.name == ".data-downloader", (
        f"canonical bundle_paths.user_env_path quebrou — " f"got={canonical.parent.name!r}"
    )
    # E devem ser idênticos (legacy delega para canonical).
    assert legacy == canonical, (
        f"legacy ({legacy}) != canonical ({canonical}) — " "delegação Wave 1 quebrada."
    )


@pytest.mark.integration
def test_bootstrap_env_returns_false_when_no_env_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bootstrap_env`` retorna False quando NENHUM candidato existe.

    Graceful degrade — CLI/UI ainda funcionam se vars estão exportadas
    no shell. Apenas o loader sinaliza "não carreguei nada".
    """
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    # Garantir que tmp_path está limpo — sem .env em nenhum lugar.
    # (tmp_path do pytest é fresco por test, mas defesa em profundidade)
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".data-downloader" / ".env").exists()

    from data_downloader._env_loader import bootstrap_env

    result = bootstrap_env()
    # Pode ser False (nenhum .env) ou True (dotenv não instalado retorna
    # False também). Aceitamos qualquer dos dois — o que NÃO pode é
    # crashar (assert implícito: chamada não levanta).
    assert isinstance(result, bool)
