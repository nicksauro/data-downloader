"""Integration tests para installer InnoSetup (Story 4.17).

Owner: Felix (frontend-dev) | Reviewer: Quinn (QA), Aria (architect).

Pichau directive 2026-05-06: integrar Setup.exe na v1.0.5 (override v1.1.0).

Cobertura (AC1, AC2 do Story 4.17):

    - ``installer/data_downloader.iss`` existe + tem token ``AppVersion``
      compilável.
    - ``_resolve_iscc_path()`` detecta ISCC.exe em paths típicos (skipif
      InnoSetup não instalado em dev local).
    - ``compile_installer()`` produz ``data-downloader-Setup-vX.Y.Z.exe``
      end-to-end (skipif ISCC + onedir indisponíveis).
    - ``write_build_manifest()`` aceita ``installer_path`` e popula section
      ``installer`` no JSON.
    - ``--with-installer`` é parseável + warning correto em dry-run.

Os testes que requerem ISCC.exe real são marcados com
``pytest.mark.skipif`` para CI/dev sem InnoSetup instalado. Test seco
(dry-run, schema, .iss script existence) sempre roda.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Adiciona scripts/ ao path para importar build_release.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import build_release  # noqa: E402  isort: skip


# =====================================================================
# Helpers
# =====================================================================


def _iscc_available() -> bool:
    """True se ISCC.exe é resolvível (env, PATH, ou typical install)."""
    try:
        build_release._resolve_iscc_path()
        return True
    except FileNotFoundError:
        return False


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ISS_PATH = _REPO_ROOT / "installer" / "data_downloader.iss"


# =====================================================================
# AC1 — Script .iss versionado em repo
# =====================================================================


class TestIssScriptExists:
    def test_iss_script_present_in_repo(self) -> None:
        assert _ISS_PATH.is_file(), f"InnoSetup script ausente: {_ISS_PATH}"

    def test_iss_script_has_app_version_token(self) -> None:
        content = _ISS_PATH.read_text(encoding="utf-8")
        # Token AppVersion deve ser sobreescrevível via /D flag.
        assert "#define AppVersion" in content
        assert "{#AppVersion}" in content

    def test_iss_script_has_required_sections(self) -> None:
        """AC1: sections obrigatórias presentes."""
        content = _ISS_PATH.read_text(encoding="utf-8")
        for section in ("[Setup]", "[Files]", "[Icons]", "[Tasks]", "[Code]"):
            assert section in content, f"Section ausente: {section}"

    def test_iss_script_default_dir_is_localappdata(self) -> None:
        """AC3: install path = %LOCALAPPDATA%\\Programs\\data-downloader."""
        content = _ISS_PATH.read_text(encoding="utf-8")
        assert "DefaultDirName={localappdata}" in content
        assert "PrivilegesRequired=lowest" in content

    def test_iss_script_creates_start_menu_and_desktop_icons(self) -> None:
        """AC4: Start Menu sempre + Desktop opt-in via [Tasks] desktopicon."""
        content = _ISS_PATH.read_text(encoding="utf-8")
        assert 'Name: "desktopicon"' in content
        assert "{commondesktop}" in content
        assert "{group}\\" in content

    def test_iss_script_does_not_touch_userprofile_data(self) -> None:
        """AC6: ~/.data-downloader/ NÃO é incluído em [UninstallDelete]."""
        content = _ISS_PATH.read_text(encoding="utf-8")
        # Deve mencionar preservação de userprofile no [Code] msg.
        assert ".data-downloader" in content
        # Mas não deve ter Type: filesandordirs apontando para userprofile.
        bad_pattern = "{userprofile}\\.data-downloader"
        assert (
            bad_pattern not in content
        ), "AC6 violation: uninstaller estaria removendo user data preservada"


# =====================================================================
# AC2 — _resolve_iscc_path detecção
# =====================================================================


class TestIsccPathResolution:
    def test_iscc_env_var_overrides_path_search(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ISCC_PATH env var tem precedência sobre busca no PATH."""
        fake_iscc = tmp_path / "ISCC.exe"
        fake_iscc.write_bytes(b"stub")
        monkeypatch.setenv("ISCC_PATH", str(fake_iscc))
        resolved = build_release._resolve_iscc_path()
        assert resolved == fake_iscc

    def test_iscc_missing_raises_friendly_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem ISCC instalado, erro tem instrução actionable."""
        monkeypatch.delenv("ISCC_PATH", raising=False)
        # Simula PROGRAMFILES vazios apontando para tmp.
        monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "pf"))
        monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "pfx86"))
        # Hide PATH entries que possam ter ISCC real.
        monkeypatch.setenv("PATH", str(tmp_path))
        with pytest.raises(FileNotFoundError, match="winget install"):
            build_release._resolve_iscc_path()

    @pytest.mark.skipif(not _iscc_available(), reason="InnoSetup não instalado")
    def test_iscc_detected_in_typical_path(self) -> None:
        """ISCC resolvível em ambiente com InnoSetup instalado."""
        path = build_release._resolve_iscc_path()
        assert path.is_file()
        assert path.name.lower() == "iscc.exe"


# =====================================================================
# CLI flag --with-installer
# =====================================================================


class TestWithInstallerFlag:
    def test_with_installer_flag_parseable(self) -> None:
        args = build_release.parse_args(["--dry-run", "--with-installer"])
        assert args.with_installer is True

    def test_default_no_installer(self) -> None:
        args = build_release.parse_args(["--dry-run"])
        assert args.with_installer is False


# =====================================================================
# Manifest schema com installer section
# =====================================================================


@pytest.fixture
def isolated_repo_with_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repo isolado com pyproject + spec template + installer/ stub."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n" 'name = "data_downloader"\n' 'version = "1.0.5"\n',
        encoding="utf-8",
    )

    build_dir = tmp_path / "build"
    build_dir.mkdir()
    spec_template = build_dir / "data_downloader.spec.template"
    spec_template.write_text(
        'APP_VERSION = "{{VERSION}}"\nBUILD_TIMESTAMP = "{{BUILD_TIMESTAMP}}"\n'
        'ICON_PATH = "{{ICON_PATH}}"\n',
        encoding="utf-8",
    )

    installer_dir = tmp_path / "installer"
    installer_dir.mkdir()
    (installer_dir / "data_downloader.iss").write_text(
        '#define AppName "data-downloader"\n[Setup]\nAppName={#AppName}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(build_release, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(build_release, "BUILD_DIR", build_dir)
    monkeypatch.setattr(build_release, "SPEC_TEMPLATE", spec_template)
    monkeypatch.setattr(build_release, "SPEC_FINAL", build_dir / "data_downloader.spec")
    monkeypatch.setattr(build_release, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(build_release, "PYPROJECT_TOML", pyproject)
    monkeypatch.setattr(build_release, "INSTALLER_ISS", installer_dir / "data_downloader.iss")
    monkeypatch.setattr(build_release, "INSTALLER_DIR", installer_dir)
    return tmp_path


class TestManifestInstallerSection:
    def test_dry_run_with_installer_emits_warning(self, isolated_repo_with_installer: Path) -> None:
        """Dry-run + --with-installer: warning informativo, rc=0."""
        rc = build_release.main(["--dry-run", "--with-installer"])
        assert rc == 0
        manifest_path = isolated_repo_with_installer / "dist" / "build-manifest-v1.0.5.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["installer"] is None
        assert any("installer" in w.lower() for w in payload["warnings"])

    def test_dry_run_without_installer_has_null_section(
        self, isolated_repo_with_installer: Path
    ) -> None:
        """Sem flag, manifest installer=None mantido (backward compat)."""
        rc = build_release.main(["--dry-run"])
        assert rc == 0
        manifest_path = isolated_repo_with_installer / "dist" / "build-manifest-v1.0.5.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "installer" in payload
        assert payload["installer"] is None

    def test_manifest_installer_field_populated_when_path_provided(
        self, isolated_repo_with_installer: Path, tmp_path: Path
    ) -> None:
        """write_build_manifest popula section installer com sha256 + size."""
        # Cria fake Setup.exe.
        dist = isolated_repo_with_installer / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        fake_setup = dist / "data-downloader-Setup-v1.0.5.exe"
        fake_setup.write_bytes(b"FAKE_SETUP_EXE_PAYLOAD" * 1000)

        ctx = build_release.BuildContext(
            version="1.0.5",
            git_sha="0" * 40,
            git_short_sha="0" * 7,
            source_date_epoch=1700000000,
            build_timestamp_iso="2023-11-14T22:13:20Z",
            dry_run=False,
        )
        manifest_path = build_release.write_build_manifest(
            ctx,
            file_manifest={},
            zip_path=None,
            spec_template_sha256="abc123",
            warnings=[],
            installer_path=fake_setup,
        )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(payload["installer"], dict)
        assert payload["installer"]["path"] == fake_setup.name
        assert payload["installer"]["size_bytes"] == len(b"FAKE_SETUP_EXE_PAYLOAD") * 1000
        assert len(payload["installer"]["sha256"]) == 64  # SHA256 hex


# =====================================================================
# End-to-end compile (skipif sem ISCC + sem onedir)
# =====================================================================


@pytest.mark.skipif(
    not _iscc_available(),
    reason="InnoSetup (ISCC.exe) não instalado — skipping E2E compile",
)
@pytest.mark.skipif(
    not (_REPO_ROOT / "dist" / "data_downloader" / "data_downloader.exe").is_file(),
    reason="dist/data_downloader/ ausente — rode build_release.py primeiro",
)
class TestCompileInstallerE2E:
    def test_compile_installer_produces_setup_exe(self, tmp_path: Path) -> None:
        """E2E: ISCC + onedir reais → Setup.exe gerado em dist/."""
        version = "0.0.0-test"
        setup_exe = build_release.compile_installer(version, _REPO_ROOT)
        try:
            assert setup_exe.is_file()
            assert setup_exe.name == f"data-downloader-Setup-v{version}.exe"
            # Sanity: Setup.exe > 50 MB (bundle PyInstaller ~350 MB + LZMA2).
            size_mb = setup_exe.stat().st_size / (1024 * 1024)
            assert size_mb > 50, f"Setup.exe muito pequeno: {size_mb:.1f} MB"
        finally:
            # Cleanup.
            if setup_exe.is_file():
                setup_exe.unlink()
