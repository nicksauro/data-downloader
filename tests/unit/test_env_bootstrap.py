"""tests/unit/test_env_bootstrap.py — Story v1.0.2 fix B3 (Nelo+Aria 2026-05-05).

Cobertura de :func:`data_downloader.cli._bootstrap_env` e
:func:`data_downloader.cli._get_credential`:

- ``_bootstrap_env`` graceful degrade quando python-dotenv não está
  disponível.
- Order de precedência: cwd > exe-dir > user-home.
- ``_get_credential`` retorna canônico quando set.
- ``_get_credential`` fallback para legado emite DeprecationWarning.
- ``_get_credential`` retorna None quando ambos ausentes.

Os testes monkeypatch o dotenv import e Path resolution para evitar
side-effects em FS real.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from data_downloader.cli import _bootstrap_env, _get_credential

# =====================================================================
# _get_credential — backwards-compat naming (B2)
# =====================================================================


def test_get_credential_canonical_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quando canônico está set, retorna direto sem warning."""
    monkeypatch.setenv("PROFITDLL_USER", "alice")
    monkeypatch.delenv("PROFIT_USER", raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _get_credential("PROFITDLL_USER", "PROFIT_USER") == "alice"


def test_get_credential_only_deprecated_set_emits_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quando só legado está set, retorna valor + DeprecationWarning."""
    monkeypatch.delenv("PROFITDLL_USER", raising=False)
    monkeypatch.setenv("PROFIT_USER", "bob")
    with pytest.warns(DeprecationWarning, match="PROFIT_USER is deprecated"):
        result = _get_credential("PROFITDLL_USER", "PROFIT_USER")
    assert result == "bob"


def test_get_credential_canonical_wins_over_deprecated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canônico tem precedência mesmo quando legado também está set."""
    monkeypatch.setenv("PROFITDLL_USER", "canonical")
    monkeypatch.setenv("PROFIT_USER", "legacy")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _get_credential("PROFITDLL_USER", "PROFIT_USER") == "canonical"


def test_get_credential_neither_set_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quando nenhuma das duas está set, retorna None sem warning."""
    monkeypatch.delenv("PROFITDLL_USER", raising=False)
    monkeypatch.delenv("PROFIT_USER", raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _get_credential("PROFITDLL_USER", "PROFIT_USER") is None


def test_get_credential_no_deprecated_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem nome legado, retorna None quando canônico ausente."""
    monkeypatch.delenv("PROFITDLL_KEY", raising=False)
    assert _get_credential("PROFITDLL_KEY") is None
    monkeypatch.setenv("PROFITDLL_KEY", "k123")
    assert _get_credential("PROFITDLL_KEY") == "k123"


# =====================================================================
# _bootstrap_env — dotenv loader
# =====================================================================


def test_bootstrap_env_graceful_degrade_no_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem python-dotenv instalado, _bootstrap_env retorna silenciosamente."""
    import builtins

    real_import = builtins.__import__

    def _no_dotenv(name: str, *args: object, **kwargs: object) -> object:
        if name == "dotenv":
            raise ImportError("simulated missing dotenv")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_dotenv)
    # Não deve levantar.
    _bootstrap_env()


def test_bootstrap_env_loads_first_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``cwd/.env`` tem precedência sobre exe-dir e user-home."""
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
    # Garante que não estamos em frozen mode.
    import sys

    monkeypatch.setattr(sys, "frozen", False, raising=False)

    _bootstrap_env()

    # Apenas o primeiro candidato (cwd) é carregado.
    assert len(calls) == 1
    assert calls[0] == cwd_env / ".env"


def test_bootstrap_env_falls_back_to_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Quando cwd não tem .env, cai para ~/.data-downloader/.env."""
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
    import sys

    monkeypatch.setattr(sys, "frozen", False, raising=False)

    _bootstrap_env()

    assert len(calls) == 1
    assert calls[0] == home_env


def test_bootstrap_env_no_candidates_loads_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quando nenhum candidato existe, load_dotenv não é chamado."""
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
    import sys

    monkeypatch.setattr(sys, "frozen", False, raising=False)

    _bootstrap_env()

    assert calls == []


def test_bootstrap_env_frozen_uses_exe_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Em frozen mode, exe-dir/.env é candidato (entre cwd e home).

    Wave 1 v1.1.0 (Aria — ADR-021): is_frozen() exige BOTH sys.frozen=True
    E sys._MEIPASS setado (espelha PyInstaller real). Test atualizado.
    """
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
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    # ADR-021 contract — both required.
    monkeypatch.setattr(sys, "_MEIPASS", str(exe_dir), raising=False)
    fake_exe = exe_dir / "data_downloader.exe"
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    _bootstrap_env()

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
    import sys

    monkeypatch.setattr(sys, "frozen", False, raising=False)

    _bootstrap_env()
    _bootstrap_env()  # 2ª chamada — não deve levantar
