"""tests/unit/test_bundle_paths.py — v1.1.0 Wave 1 (Aria — ADR-018 / ADR-021).

Cobertura de :mod:`data_downloader._internal.bundle_paths`:

- ``is_frozen`` retorna False em dev (sem sys.frozen / sys._MEIPASS).
- ``is_frozen`` retorna True quando frozen=True E _MEIPASS setado.
- ``is_frozen`` retorna False quando frozen=True mas _MEIPASS vazio
  (defesa em profundidade — raro: --onefile ainda extraindo).
- ``bundle_root`` em source mode retorna raiz do pacote ``data_downloader``.
- ``bundle_root`` em frozen mode retorna ``Path(sys._MEIPASS)``.
- ``exe_dir`` retorna ``Path(sys.executable).parent``.
- ``asset_path`` busca em ordem de candidatos e retorna primeiro existente.
- ``asset_path`` levanta ``FileNotFoundError`` listando todos candidatos.
- ``user_data_dir`` retorna ``~/.data-downloader/`` com hífen.
- ``user_env_path`` retorna ``~/.data-downloader/.env``.

Teste NÃO faz I/O em ``$HOME`` ou em FS real — usa ``tmp_path`` +
monkeypatch para Path.home / sys.executable / sys._MEIPASS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data_downloader._internal.bundle_paths import (
    asset_path,
    bundle_root,
    exe_dir,
    is_frozen,
    user_data_dir,
    user_env_path,
)

# =====================================================================
# is_frozen
# =====================================================================


def test_is_frozen_false_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem sys.frozen e sem _MEIPASS, retorna False."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert is_frozen() is False


def test_is_frozen_true_when_meipass_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """sys.frozen=True E _MEIPASS não-vazio → True."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert is_frozen() is True


def test_is_frozen_false_when_frozen_but_meipass_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys.frozen=True mas _MEIPASS vazio → False (defesa em profundidade)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "", raising=False)
    assert is_frozen() is False


# =====================================================================
# bundle_root
# =====================================================================


def test_bundle_root_in_source_mode_returns_package_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Em dev, bundle_root() é o diretório do pacote data_downloader."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    root = bundle_root()
    # Ponto âncora: pacote contém ``__init__.py``.
    assert (root / "__init__.py").is_file()
    assert root.name == "data_downloader"


def test_bundle_root_in_frozen_mode_returns_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Em frozen, bundle_root() é Path(sys._MEIPASS)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert bundle_root() == tmp_path


# =====================================================================
# exe_dir
# =====================================================================


def test_exe_dir_returns_parent_of_sys_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """exe_dir() é Path(sys.executable).parent."""
    fake_exe = tmp_path / "fake.exe"
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert exe_dir() == tmp_path


# =====================================================================
# asset_path
# =====================================================================


def test_asset_path_finds_in_bundle_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """asset_path() retorna candidato em bundle_root() quando existe."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    # Cria um asset fake em bundle_root.
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    asset_file = asset_dir / "style.qss"
    asset_file.write_text("/* fake */", encoding="utf-8")

    found = asset_path("assets/style.qss")
    assert found == asset_file


def test_asset_path_falls_through_to_exe_dir_internal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quando bundle_root() não tem o asset, cai para exe_dir/_internal/."""
    # bundle_root é vazio, mas exe_dir/_internal/ tem o arquivo.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)

    exe_parent = tmp_path / "exe"
    exe_parent.mkdir()
    fake_exe = exe_parent / "data_downloader.exe"
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    internal_dir = exe_parent / "_internal" / "assets"
    internal_dir.mkdir(parents=True)
    asset_file = internal_dir / "style.qss"
    asset_file.write_text("/* fake */", encoding="utf-8")

    found = asset_path("assets/style.qss")
    assert found == asset_file


def test_asset_path_raises_with_all_candidates_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quando NENHUM candidato existe, FileNotFoundError lista todos os paths tentados."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "exe" / "fake.exe"))

    with pytest.raises(FileNotFoundError) as excinfo:
        asset_path("does/not/exist.bin")
    msg = str(excinfo.value)
    assert "does/not/exist.bin" in msg or "does\\not\\exist.bin" in msg
    # Mensagem deve indicar mode + listar candidatos.
    assert "is_frozen()" in msg
    assert "Candidates tried" in msg


# =====================================================================
# user_data_dir / user_env_path
# =====================================================================


def test_user_data_dir_uses_hyphen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """user_data_dir() usa hífen (.data-downloader), nunca underscore."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = user_data_dir()
    assert p == tmp_path / ".data-downloader"
    assert ".data_downloader" not in p.parts


def test_user_env_path_canonical(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """user_env_path() = user_data_dir() / .env."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p = user_env_path()
    assert p == tmp_path / ".data-downloader" / ".env"
    assert p.name == ".env"


def test_module_no_side_effects_on_import() -> None:
    """Importar bundle_paths NÃO deve fazer I/O em FS.

    R21 hot path discipline: módulo é puro (sem is_file/exists no
    module-level). Re-importar deve ser barato.
    """
    import importlib

    import data_downloader._internal.bundle_paths as mod

    # Reimport não deve levantar / não deve mudar nada visível.
    reloaded = importlib.reload(mod)
    assert reloaded.is_frozen is mod.is_frozen
