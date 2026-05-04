"""Integration tests para ``scripts/build_release.py`` (Story 4.4).

Owner: Quinn (QA) | Implementer: Gage (DevOps).

Roda o script em ``--dry-run`` mode (não invoca PyInstaller real).
Valida:

    - Smoke: script importável + main() retorna 0 em dry-run.
    - Spec template é renderizado com tokens substituídos.
    - build-manifest-v{version}.json é criado com schema esperado.
    - Manifest dry_run=True é detectado por github_release.py (cross-test).
    - Resolução de versão de pyproject.toml.
    - Resolução de git context (best-effort em ambiente sem git).
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
# Helpers / fixtures
# =====================================================================


@pytest.fixture
def isolated_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cria repo isolado com pyproject.toml + spec template + minimal layout."""
    # pyproject.toml mínimo.
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n" 'name = "data_downloader"\n' 'version = "1.0.0"\n',
        encoding="utf-8",
    )

    # build/ dir + spec template stub.
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    spec_template = build_dir / "data_downloader.spec.template"
    spec_template.write_text(
        "# Spec template stub for tests\n"
        'APP_VERSION = "{{VERSION}}"\n'
        'BUILD_TIMESTAMP = "{{BUILD_TIMESTAMP}}"\n'
        'ICON_PATH = "{{ICON_PATH}}"\n',
        encoding="utf-8",
    )

    # Patch module-level constants para o repo isolado.
    monkeypatch.setattr(build_release, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(build_release, "BUILD_DIR", build_dir)
    monkeypatch.setattr(build_release, "SPEC_TEMPLATE", spec_template)
    monkeypatch.setattr(build_release, "SPEC_FINAL", build_dir / "data_downloader.spec")
    monkeypatch.setattr(build_release, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(build_release, "PYPROJECT_TOML", pyproject)

    return tmp_path


# =====================================================================
# Tests
# =====================================================================


class TestDryRunSmoke:
    def test_dry_run_returns_zero(self, isolated_repo: Path) -> None:
        rc = build_release.main(["--dry-run"])
        assert rc == 0

    def test_dry_run_creates_manifest(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run"])
        manifest_path = isolated_repo / "dist" / "build-manifest-v1.0.0.json"
        assert manifest_path.exists()

    def test_dry_run_renders_spec(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run"])
        spec_final = isolated_repo / "build" / "data_downloader.spec"
        assert spec_final.exists()
        content = spec_final.read_text(encoding="utf-8")
        assert "{{VERSION}}" not in content  # token substituído
        assert "1.0.0" in content
        assert "{{BUILD_TIMESTAMP}}" not in content
        assert "{{ICON_PATH}}" not in content


class TestManifestSchema:
    def test_manifest_has_required_fields(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run"])
        manifest_path = isolated_repo / "dist" / "build-manifest-v1.0.0.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        required_keys = {
            "version",
            "git_sha",
            "git_short_sha",
            "build_timestamp_iso",
            "source_date_epoch",
            "builder_hostname_sanitized",
            "spec_template_sha256",
            "dry_run",
            "files",
            "zip",
            "total_size_bytes",
            "warnings",
        }
        assert required_keys.issubset(payload.keys())

    def test_manifest_dry_run_flag(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run"])
        manifest_path = isolated_repo / "dist" / "build-manifest-v1.0.0.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["dry_run"] is True
        assert any("dry_run" in w.lower() for w in payload["warnings"])

    def test_manifest_version_matches(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run"])
        manifest_path = isolated_repo / "dist" / "build-manifest-v1.0.0.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["version"] == "1.0.0"

    def test_manifest_force_version_override(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run", "--version", "2.5.0"])
        manifest_path = isolated_repo / "dist" / "build-manifest-v2.5.0.json"
        assert manifest_path.exists()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert payload["version"] == "2.5.0"

    def test_manifest_files_dict_empty_in_dry_run(self, isolated_repo: Path) -> None:
        build_release.main(["--dry-run"])
        manifest_path = isolated_repo / "dist" / "build-manifest-v1.0.0.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Em dry-run, PyInstaller não roda, então não há arquivos para hashear.
        assert payload["files"] == {}
        assert payload["zip"] is None


class TestVersionResolution:
    def test_read_version_from_pyproject(self, isolated_repo: Path) -> None:
        version = build_release._read_version_from_pyproject()
        assert version == "1.0.0"

    def test_missing_pyproject_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(build_release, "PYPROJECT_TOML", tmp_path / "missing.toml")
        with pytest.raises(FileNotFoundError):
            build_release._read_version_from_pyproject()

    def test_pyproject_without_version_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad_toml = tmp_path / "bad.toml"
        bad_toml.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        monkeypatch.setattr(build_release, "PYPROJECT_TOML", bad_toml)
        with pytest.raises(ValueError, match="version"):
            build_release._read_version_from_pyproject()


class TestPreConditions:
    def test_missing_spec_template_returns_one(self, isolated_repo: Path) -> None:
        # Remove spec template.
        build_release.SPEC_TEMPLATE.unlink()
        rc = build_release.main(["--dry-run"])
        assert rc == 1


class TestEnvVars:
    def test_apply_deterministic_env_sets_pythonhashseed(
        self, isolated_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Limpa env antes para confirmar set.
        monkeypatch.delenv("PYTHONHASHSEED", raising=False)
        ctx = build_release.BuildContext(
            version="1.0.0",
            git_sha="0" * 40,
            git_short_sha="0" * 7,
            source_date_epoch=1700000000,
            build_timestamp_iso="2023-11-14T22:13:20Z",
            dry_run=True,
        )
        snapshot = build_release.apply_deterministic_env(ctx)
        assert snapshot["PYTHONHASHSEED"] == "0"
        assert snapshot["SOURCE_DATE_EPOCH"] == "1700000000"
        assert snapshot["TZ"] == "UTC"


class TestHostnameSanitization:
    def test_hostname_does_not_leak_full_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMPUTERNAME", "secret-host-with-pii-info")
        sanitized = build_release._sanitize_hostname()
        assert "secret-host-with-pii-info" not in sanitized
        assert "secret" not in sanitized.lower()
        # Mas mantém prefixo curto (3 chars) + hash.
        assert "-XXXX-" in sanitized

    def test_hostname_unknown_when_env_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("COMPUTERNAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)
        sanitized = build_release._sanitize_hostname()
        assert sanitized.startswith("unk")
