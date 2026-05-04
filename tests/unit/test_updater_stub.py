"""Unit tests para ``data_downloader._updater.tufup_stub`` (Story 4.4).

Owner: Quinn (QA) | Implementer: Felix (Frontend-Dev).

Cobertura:

    - Parse SemVer + comparação (newer / equal / pre-release vs final).
    - check_for_updates: GitHub API mock retorna newer release →
      UpdateInfo populada + status OUTDATED.
    - check_for_updates: API retorna mesma versão → status UP_TO_DATE.
    - check_for_updates: rede falha (URLError) → status ERROR.
    - check_for_updates: payload malformado → status ERROR.
    - download_update / apply_update: V1.0 raises NotImplementedError.

Não invoca rede real — todos os calls externos são mockados via
``urllib.request.urlopen`` patch.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from data_downloader._updater.tufup_stub import (
    UpdateInfo,
    UpdaterStub,
    UpdateStatus,
    _is_newer,
    _parse_semver,
)

# =====================================================================
# Helpers
# =====================================================================


def _mock_github_response(payload: dict[str, Any]) -> Any:
    """Simula response do urllib.request.urlopen (context manager)."""
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


# =====================================================================
# SemVer parsing
# =====================================================================


class TestParseSemver:
    def test_basic_semver(self) -> None:
        major, minor, patch_n, pre = _parse_semver("v1.2.3")
        assert (major, minor, patch_n, pre) == (1, 2, 3, None)

    def test_prerelease(self) -> None:
        major, minor, patch_n, pre = _parse_semver("v1.0.0-rc.1")
        assert (major, minor, patch_n, pre) == (1, 0, 0, "rc.1")

    def test_invalid_no_v_prefix(self) -> None:
        with pytest.raises(ValueError):
            _parse_semver("1.2.3")

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            _parse_semver("v1.2")

    def test_invalid_garbage(self) -> None:
        with pytest.raises(ValueError):
            _parse_semver("not-a-version")


class TestIsNewer:
    def test_strictly_newer_patch(self) -> None:
        assert _is_newer("v1.0.1", "1.0.0") is True

    def test_strictly_newer_minor(self) -> None:
        assert _is_newer("v1.1.0", "1.0.5") is True

    def test_strictly_newer_major(self) -> None:
        assert _is_newer("v2.0.0", "1.99.99") is True

    def test_equal_versions(self) -> None:
        assert _is_newer("v1.0.0", "1.0.0") is False

    def test_older_release(self) -> None:
        assert _is_newer("v0.9.0", "1.0.0") is False

    def test_final_beats_prerelease(self) -> None:
        # current is rc, latest is final → latest wins.
        assert _is_newer("v1.0.0", "1.0.0-rc.1") is True

    def test_invalid_tag_returns_false(self) -> None:
        # Tag malformada não confunde — retorna False.
        assert _is_newer("garbage", "1.0.0") is False


# =====================================================================
# check_for_updates
# =====================================================================


class TestCheckForUpdates:
    def test_outdated_returns_update_info(self) -> None:
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/x/y/releases/tag/v2.0.0",
            "published_at": "2026-06-01T12:00:00Z",
            "body": "## Changelog\n- New feature",
            "assets": [
                {
                    "name": "data-downloader-v2.0.0-win64.zip",
                    "browser_download_url": "https://github.com/x/y/releases/download/v2.0.0/data-downloader-v2.0.0-win64.zip",
                }
            ],
        }
        with patch("urllib.request.urlopen", return_value=_mock_github_response(payload)):
            updater = UpdaterStub(current_version="1.0.0")
            info = updater.check_for_updates()

        assert info is not None
        assert isinstance(info, UpdateInfo)
        assert info.latest_version == "2.0.0"
        assert info.current_version == "1.0.0"
        assert info.release_url == "https://github.com/x/y/releases/tag/v2.0.0"
        assert info.download_url is not None
        assert info.download_url.endswith(".zip")
        assert updater.last_status == UpdateStatus.OUTDATED
        assert updater.last_error is None

    def test_up_to_date_returns_none(self) -> None:
        payload = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/x/y/releases/tag/v1.0.0",
            "published_at": "2026-05-01T12:00:00Z",
            "body": "Release",
            "assets": [],
        }
        with patch("urllib.request.urlopen", return_value=_mock_github_response(payload)):
            updater = UpdaterStub(current_version="1.0.0")
            info = updater.check_for_updates()

        assert info is None
        assert updater.last_status == UpdateStatus.UP_TO_DATE
        assert updater.last_error is None

    def test_network_error_returns_none_with_error_status(self) -> None:
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            updater = UpdaterStub(current_version="1.0.0")
            info = updater.check_for_updates()

        assert info is None
        assert updater.last_status == UpdateStatus.ERROR
        assert updater.last_error is not None
        assert "Falha ao verificar updates" in updater.last_error

    def test_invalid_json_returns_error(self) -> None:
        bad_response = MagicMock()
        bad_response.read.return_value = b"not-valid-json{"
        bad_response.__enter__ = MagicMock(return_value=bad_response)
        bad_response.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=bad_response):
            updater = UpdaterStub(current_version="1.0.0")
            info = updater.check_for_updates()

        assert info is None
        assert updater.last_status == UpdateStatus.ERROR

    def test_missing_tag_name_returns_error(self) -> None:
        payload = {"published_at": "2026-05-01T12:00:00Z", "body": "no tag"}
        with patch("urllib.request.urlopen", return_value=_mock_github_response(payload)):
            updater = UpdaterStub(current_version="1.0.0")
            info = updater.check_for_updates()

        assert info is None
        assert updater.last_status == UpdateStatus.ERROR
        assert updater.last_error is not None

    def test_no_zip_asset_still_returns_info_without_download_url(self) -> None:
        payload = {
            "tag_name": "v1.5.0",
            "html_url": "https://github.com/x/y/releases/tag/v1.5.0",
            "published_at": "2026-05-15T12:00:00Z",
            "body": "Release",
            "assets": [
                {"name": "checksums.txt", "browser_download_url": "https://x.y/checksums.txt"}
            ],
        }
        with patch("urllib.request.urlopen", return_value=_mock_github_response(payload)):
            updater = UpdaterStub(current_version="1.0.0")
            info = updater.check_for_updates()

        assert info is not None
        assert info.latest_version == "1.5.0"
        assert info.download_url is None  # nenhum asset .zip


# =====================================================================
# download_update / apply_update — V1.0 raise NotImplementedError
# =====================================================================


class TestUpdateActions:
    def test_download_update_raises(self) -> None:
        info = UpdateInfo(
            latest_version="2.0.0",
            current_version="1.0.0",
            release_url="https://example.com/r",
            download_url=None,
            published_at="",
            body="",
        )
        updater = UpdaterStub(current_version="1.0.0")
        with pytest.raises(NotImplementedError) as exc_info:
            updater.download_update(info)
        assert "tufup" in str(exc_info.value).lower()
        assert "https://example.com/r" in str(exc_info.value)

    def test_apply_update_raises(self, tmp_path: Any) -> None:
        zip_path = tmp_path / "fake.zip"
        zip_path.write_bytes(b"PK\x03\x04")
        updater = UpdaterStub(current_version="1.0.0")
        with pytest.raises(NotImplementedError) as exc_info:
            updater.apply_update(zip_path)
        assert "INSTALL.md" in str(exc_info.value)


# =====================================================================
# Defaults
# =====================================================================


class TestDefaults:
    def test_default_current_version_resolves_from_public_api(self) -> None:
        # Sem patch — usa __api_version__ real (deve ser "1.0.0" pós Story 4.3).
        updater = UpdaterStub()
        # Tolerante: aceita qualquer SemVer não-vazio.
        assert updater.current_version
        assert updater.current_version != "0.0.0"

    def test_unchecked_status_initial(self) -> None:
        updater = UpdaterStub(current_version="1.0.0")
        assert updater.last_status == UpdateStatus.UNCHECKED
        assert updater.last_error is None
