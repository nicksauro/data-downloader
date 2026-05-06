"""Integration tests para dual-EXE validation em ``scripts/build_release.py``.

Owner: Felix (frontend-dev) | Story 4.8 hotfix v1.0.3.

Cobre o fix do bug v1.0.2 onde `console=True` causava janela preta a cada
double-click no .exe. Solução (Pichau directive 2026-05-06, council Aria
Opção A): emitir DOIS executáveis no mesmo onedir bundle:

    - ``data_downloader.exe``      — windowed (console=False), default UI
    - ``data_downloader-cli.exe``  — console (console=True), CLI explícita

Os testes aqui validam que ``build_release.validate_output()`` exige AMBOS
os .exes presentes no onedir produzido pelo PyInstaller (não apenas o
single-exe legado v1.0.2).

Estes testes simulam o output do PyInstaller criando arquivos stub no
diretório onedir (não rodam PyInstaller real — isso é coberto pelo smoke
manual descrito na Story 4.8).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Adiciona scripts/ ao path para importar build_release.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import build_release  # noqa: E402  isort: skip


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def fake_onedir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cria um onedir stub que simula o output do PyInstaller.

    Inclui ambos os .exes do dual-EXE bundle + DLL companions + um arquivo
    grande o bastante para passar o sanity range (>= 50 MB).
    """
    dist = tmp_path / "dist"
    onedir = dist / "data_downloader"
    onedir.mkdir(parents=True)

    # Dual EXE (Story 4.8): ambos presentes.
    (onedir / "data_downloader.exe").write_bytes(b"MZ\x00\x00windowed-stub")
    (onedir / "data_downloader-cli.exe").write_bytes(b"MZ\x00\x00console-stub")

    # DLL companions requeridos.
    for dll in build_release.REQUIRED_DLL_COMPANIONS:
        (onedir / dll).write_bytes(b"DLL\x00stub")

    # Filler para passar o size sanity range (50-1000 MB).
    filler = onedir / "filler.bin"
    filler.write_bytes(b"\x00" * (60 * 1024 * 1024))  # 60 MB

    monkeypatch.setattr(build_release, "DIST_DIR", dist)
    return onedir


# =====================================================================
# Tests — happy path
# =====================================================================


class TestDualExeHappyPath:
    def test_validate_output_passes_with_both_exes(self, fake_onedir: Path) -> None:
        """``validate_output`` retorna onedir quando AMBOS os .exes existem."""
        result = build_release.validate_output()
        assert result == fake_onedir

    def test_required_executables_constant_lists_both(self) -> None:
        """O constante exporta ambos os executáveis do dual-EXE bundle."""
        assert "data_downloader.exe" in build_release.REQUIRED_EXECUTABLES
        assert "data_downloader-cli.exe" in build_release.REQUIRED_EXECUTABLES
        assert len(build_release.REQUIRED_EXECUTABLES) == 2


# =====================================================================
# Tests — failure modes
# =====================================================================


class TestDualExeMissingFails:
    def test_missing_ui_exe_raises(self, fake_onedir: Path) -> None:
        """Falta ``data_downloader.exe`` (UI windowed) → FileNotFoundError."""
        (fake_onedir / "data_downloader.exe").unlink()
        with pytest.raises(FileNotFoundError, match=r"data_downloader\.exe"):
            build_release.validate_output()

    def test_missing_cli_exe_raises(self, fake_onedir: Path) -> None:
        """Falta ``data_downloader-cli.exe`` (CLI console) → FileNotFoundError.

        Este é exatamente o regression-guard contra v1.0.2: se alguém
        reverter o spec template para single-exe (apenas
        ``data_downloader.exe``), build_release falha aqui.
        """
        (fake_onedir / "data_downloader-cli.exe").unlink()
        with pytest.raises(FileNotFoundError, match=r"data_downloader-cli\.exe"):
            build_release.validate_output()

    def test_missing_both_exes_raises(self, fake_onedir: Path) -> None:
        """Falta ambos → FileNotFoundError no primeiro check."""
        (fake_onedir / "data_downloader.exe").unlink()
        (fake_onedir / "data_downloader-cli.exe").unlink()
        with pytest.raises(FileNotFoundError):
            build_release.validate_output()

    def test_error_message_references_story_4_8(self, fake_onedir: Path) -> None:
        """Mensagem de erro cita 'dual EXE' para devs que reintroduzirem o bug."""
        (fake_onedir / "data_downloader-cli.exe").unlink()
        with pytest.raises(FileNotFoundError) as excinfo:
            build_release.validate_output()
        assert "dual EXE" in str(excinfo.value)
