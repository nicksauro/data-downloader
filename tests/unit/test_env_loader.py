"""tests/unit/test_env_loader.py — Story v1.0.5 (Pichau live test 2026-05-06).

Cobertura de :mod:`data_downloader._env_loader`:

- ``user_env_path`` retorna path canônico com hífen (NÃO underscore).
- ``bootstrap_env`` carrega ``cwd/.env`` com precedência sobre user-home.
- ``bootstrap_env`` cai para ``~/.data-downloader/.env`` quando cwd vazio.
- ``bootstrap_env`` retorna ``False`` quando nenhum candidato existe.
- ``bootstrap_env`` retorna ``False`` (graceful) sem ``python-dotenv``.
- ``bootstrap_env`` em frozen mode adiciona ``<exe-dir>/.env`` como candidato.
- Idempotência (chamada múltipla é segura).

Os testes monkeypatch o ``dotenv.load_dotenv`` e Path resolution para
evitar side-effects em FS real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data_downloader._env_loader import bootstrap_env, user_env_path

# =====================================================================
# user_env_path — canonical path
# =====================================================================


def test_user_env_path_uses_hyphen_not_underscore() -> None:
    """``user_env_path()`` deve usar hífen (``.data-downloader``)."""
    p = user_env_path()
    parts = p.parts
    # Diretório pai = '.data-downloader' (com hífen).
    assert (
        ".data-downloader" in parts
    ), f"user_env_path() deve usar hífen ('.data-downloader'); got {p}"
    # NUNCA underscore — divergência foi consertada na Story v1.0.5.
    assert (
        ".data_downloader" not in parts
    ), f"user_env_path() NÃO pode usar underscore ('.data_downloader'); got {p}"
    # Filename é ``.env``.
    assert p.name == ".env"


def test_user_env_path_is_under_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``user_env_path()`` é construído a partir de ``Path.home()``."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = user_env_path()
    # Deve ser tmp_path/.data-downloader/.env
    assert p == tmp_path / ".data-downloader" / ".env"


# =====================================================================
# bootstrap_env — candidate ordering
# =====================================================================


def test_bootstrap_env_loads_cwd_env_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``cwd/.env`` tem precedência sobre user-home (Story v1.0.5)."""
    cwd_env = tmp_path / "cwd_env"
    cwd_env.mkdir()
    (cwd_env / ".env").write_text("PROFITDLL_KEY" + "=from_cwd\n", encoding="utf-8")

    home_dir = tmp_path / "home"
    (home_dir / ".data-downloader").mkdir(parents=True)
    (home_dir / ".data-downloader" / ".env").write_text(
        "PROFITDLL_KEY" + "=from_home\n", encoding="utf-8"
    )

    calls: list[Path] = []

    def fake_load_dotenv(p: Path) -> bool:
        calls.append(Path(p))
        return True

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd_env))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    result = bootstrap_env()

    assert result is True
    # Apenas o primeiro candidato (cwd) é carregado.
    assert len(calls) == 1
    assert calls[0] == cwd_env / ".env"


def test_bootstrap_env_loads_user_home_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quando cwd não tem ``.env``, cai para ``~/.data-downloader/.env``."""
    cwd_dir = tmp_path / "cwd_no_env"
    cwd_dir.mkdir()  # vazio — sem .env

    home_dir = tmp_path / "home"
    (home_dir / ".data-downloader").mkdir(parents=True)
    home_env = home_dir / ".data-downloader" / ".env"
    home_env.write_text("PROFITDLL_KEY" + "=from_home\n", encoding="utf-8")

    calls: list[Path] = []

    def fake_load_dotenv(p: Path) -> bool:
        calls.append(Path(p))
        return True

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd_dir))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    result = bootstrap_env()

    assert result is True
    assert len(calls) == 1
    assert calls[0] == home_env


def test_bootstrap_env_returns_false_when_no_env_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quando nenhum candidato existe, retorna ``False`` e load_dotenv não é chamado."""
    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()

    calls: list[Path] = []

    def fake_load_dotenv(p: Path) -> bool:  # pragma: no cover  defensive
        calls.append(Path(p))
        return True

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: empty_cwd))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: empty_home))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    result = bootstrap_env()

    assert result is False
    assert calls == []


def test_bootstrap_env_graceful_degrade_no_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem ``python-dotenv`` instalado, retorna ``False`` silenciosamente."""
    import builtins

    real_import = builtins.__import__

    def _no_dotenv(name: str, *args: object, **kwargs: object) -> object:
        if name == "dotenv":
            raise ImportError("simulated missing dotenv")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_dotenv)
    # Não deve levantar; retorno False indica "nada carregado".
    result = bootstrap_env()
    assert result is False


def test_bootstrap_env_frozen_uses_exe_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Em frozen mode, ``<exe-dir>/.env`` é candidato (entre cwd e home)."""
    cwd_dir = tmp_path / "cwd_no_env"
    cwd_dir.mkdir()
    exe_dir = tmp_path / "exe_dir"
    exe_dir.mkdir()
    exe_env = exe_dir / ".env"
    exe_env.write_text("PROFITDLL_KEY" + "=from_exe\n", encoding="utf-8")
    home_dir = tmp_path / "home_unused"
    home_dir.mkdir()

    calls: list[Path] = []

    def fake_load_dotenv(p: Path) -> bool:
        calls.append(Path(p))
        return True

    monkeypatch.setattr("dotenv.load_dotenv", fake_load_dotenv)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd_dir))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    fake_exe = exe_dir / "data_downloader.exe"
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    result = bootstrap_env()

    assert result is True
    assert len(calls) == 1
    assert calls[0] == exe_env


def test_bootstrap_env_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Chamadas múltiplas não causam erro."""
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    (cwd_dir / ".env").write_text("X=1\n", encoding="utf-8")

    monkeypatch.setattr("dotenv.load_dotenv", lambda p: True)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd_dir))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "no_home"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    # Idempotente — segunda chamada não pode levantar.
    assert bootstrap_env() is True
    assert bootstrap_env() is True
