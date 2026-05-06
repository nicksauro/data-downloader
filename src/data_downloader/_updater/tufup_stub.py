"""data_downloader._updater.tufup_stub — UpdaterStub V1.0 (Story 4.4).

Owner: Felix | Reviewer: Aria (ADR-017 trajectory).

V1.0 stub para auto-updater. Implementa APENAS check + notify (não
aplica updates). Full tufup integration deferred V1.1 — ver
``docs/stories/4.4-followup.story.md``.

Fluxo V1.0:

    1. ``UpdaterStub().check_for_updates()``
       → fetch ``GET https://api.github.com/repos/{owner}/{repo}/releases/latest``
       → parse ``tag_name`` (formato ``v{MAJOR}.{MINOR}.{PATCH}``)
       → compara com ``__api_version__`` do pacote local
       → retorna ``UpdateInfo`` se outdated, ``None`` se up-to-date
    2. UI chama ``download_update(info)`` para abrir página de release
       no browser (V1.0 — usuário baixa manualmente).
    3. ``apply_update(path)`` em V1.0 retorna ``NotImplementedError`` com
       mensagem amigável apontando para INSTALL.md.

Política R17 (microcopy): mensagens visíveis ao usuário em runtime são
strings curtas em pt-BR — quando integradas via `SettingsScreen`,
passam por ``microcopy_loader.format_msg(...)``. Aqui mantemos rótulos
internos (``UpdateStatus`` enum) que são mapeados para microcopy IDs
no consumidor (UI / CLI).

Threading: ``check_for_updates`` faz I/O HTTP síncrono. UI deve invocar
em ``QThread`` ou ``QTimer.singleShot`` para evitar blocking
MainThread > 16ms (R11).

Segurança V1.0: GitHub API HTTPS apenas (TLS verifica server cert).
Ataque MITM possível mas baixo risco para audiência inicial (squad +
early adopters). V1.1 adiciona TUF signature verification via tufup.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

# =====================================================================
# Constantes
# =====================================================================

# Repo GitHub do data-downloader. Configurável via env em deploy futuro
# (V1.1 com tufup, esse vai virar config TUF root).
DEFAULT_GITHUB_OWNER: Final[str] = "nicksauro"
DEFAULT_GITHUB_REPO: Final[str] = "data-downloader"

# Endpoint GitHub Releases API.
GITHUB_API_BASE: Final[str] = "https://api.github.com"

# Timeout HTTP para check (UI responsiveness — fail fast).
CHECK_TIMEOUT_SECONDS: Final[float] = 5.0

# User-Agent obrigatório para GitHub API (rate-limit policies).
USER_AGENT: Final[str] = "data-downloader-updater-stub/1.0"

# Regex de parse de tag SemVer ``v1.2.3`` ou ``v1.2.3-rc.4``.
_TAG_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:-(?P<prerelease>[A-Za-z0-9.-]+))?$"
)

# =====================================================================
# Tipos públicos do módulo (internal — re-exportados via __init__)
# =====================================================================


class UpdateStatus(Enum):
    """Status do check de updates.

    Mapeado para microcopy IDs em ``SettingsScreen`` (R17 — Uma):

    - ``UP_TO_DATE`` → ``LBL_UPDATE_STATUS_UP_TO_DATE``
    - ``OUTDATED`` → ``LBL_UPDATE_STATUS_OUTDATED``
    - ``ERROR`` → ``LBL_UPDATE_STATUS_ERROR``
    - ``UNCHECKED`` → ``LBL_UPDATE_STATUS_UNCHECKED``
    """

    UNCHECKED = "unchecked"
    UP_TO_DATE = "up_to_date"
    OUTDATED = "outdated"
    ERROR = "error"


@dataclass(frozen=True)
class UpdateInfo:
    """Metadados de um update disponível.

    Campos espelham o JSON do GitHub Releases API (subset relevante).

    Attributes:
        latest_version: Versão SemVer (ex.: ``"1.2.3"`` — sem prefixo ``v``).
        current_version: Versão atualmente instalada.
        release_url: URL HTML da release page (humano-friendly download).
        download_url: URL direto do asset .zip (best-effort — None se
            asset não encontrado no payload).
        published_at: ISO-8601 timestamp da publicação.
        body: Markdown body da release (changelog excerpt).
    """

    latest_version: str
    current_version: str
    release_url: str
    download_url: str | None
    published_at: str
    body: str


# =====================================================================
# Helpers de versionamento
# =====================================================================


def _parse_semver(tag: str) -> tuple[int, int, int, str | None]:
    """Parse ``v1.2.3[-prerelease]`` → tupla ordenável.

    Returns:
        ``(major, minor, patch, prerelease_or_None)``.

    Raises:
        ValueError: se ``tag`` não for SemVer válido com prefixo ``v``.
    """
    match = _TAG_REGEX.match(tag)
    if match is None:
        raise ValueError(f"Tag não é SemVer válido: {tag!r}")
    return (
        int(match["major"]),
        int(match["minor"]),
        int(match["patch"]),
        match["prerelease"],
    )


def _is_newer(latest_tag: str, current_version: str) -> bool:
    """Compara ``latest_tag`` (``v1.2.3``) com ``current_version`` (``1.2.3``).

    Pre-releases (``v1.2.3-rc.1``) são considerados MENORES que o
    final correspondente (``v1.2.3``) — semântica SemVer 2.0 §11.

    Returns:
        ``True`` se ``latest_tag`` > ``current_version``.
    """
    try:
        latest = _parse_semver(latest_tag)
    except ValueError:
        return False

    # current_version vem sem ``v`` prefix — adicionar.
    try:
        current = _parse_semver(f"v{current_version}")
    except ValueError:
        return False

    # Compare core (major, minor, patch).
    if latest[:3] != current[:3]:
        return latest[:3] > current[:3]
    # Iguais no core — pre-release perde para release final.
    latest_pre = latest[3]
    current_pre = current[3]
    if latest_pre is None and current_pre is None:
        return False
    if latest_pre is None and current_pre is not None:
        return True  # latest é final, current é pre-release → latest é newer
    if latest_pre is not None and current_pre is None:
        return False  # latest é pre-release de versão já lançada
    # Ambos pre-release — comparação lexicográfica simplificada (suficiente V1.0).
    return (latest_pre or "") > (current_pre or "")


# =====================================================================
# UpdaterStub — API principal
# =====================================================================


class UpdaterStub:
    """Stub do auto-updater para V1.0.

    V1.0 = check + notify only. Full TUF integration via tufup deferred
    para V1.1 (Story 4.4-followup).

    Args:
        github_owner: Owner do repo GitHub (default: ``nicksauro``).
        github_repo: Nome do repo (default: ``data-downloader``).
        current_version: Versão atualmente instalada. Se ``None``, lê de
            ``data_downloader.public_api.__api_version__``.

    Example:
        >>> updater = UpdaterStub()
        >>> info = updater.check_for_updates()
        >>> if info is not None:
        ...     # UI consumer mostra notificação via SettingsScreen
        ...     # (consumidor decide microcopy via R17 / microcopy_loader).
        ...     pass
    """

    def __init__(
        self,
        *,
        github_owner: str = DEFAULT_GITHUB_OWNER,
        github_repo: str = DEFAULT_GITHUB_REPO,
        current_version: str | None = None,
    ) -> None:
        self._owner = github_owner
        self._repo = github_repo
        self._current_version = current_version or self._resolve_current_version()
        self._last_status: UpdateStatus = UpdateStatus.UNCHECKED
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Public API (used by SettingsScreen + future CLI)
    # ------------------------------------------------------------------

    @property
    def current_version(self) -> str:
        """Versão atualmente instalada (string SemVer sem prefixo ``v``)."""
        return self._current_version

    @property
    def last_status(self) -> UpdateStatus:
        """Resultado do último ``check_for_updates`` (default: UNCHECKED)."""
        return self._last_status

    @property
    def last_error(self) -> str | None:
        """Mensagem de erro do último check (None se OK)."""
        return self._last_error

    def check_for_updates(self) -> UpdateInfo | None:
        """Verifica se há update disponível via GitHub Releases API.

        Returns:
            ``UpdateInfo`` se update disponível, ``None`` se up-to-date.
            Em caso de erro de rede/parse, retorna ``None`` e seta
            ``last_status = ERROR`` + ``last_error`` com mensagem.
        """
        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/releases/latest"
        try:
            payload = self._fetch_json(url)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            self._last_status = UpdateStatus.ERROR
            self._last_error = f"Falha ao verificar updates: {exc}"
            return None
        except ValueError as exc:
            # JSON inválido.
            self._last_status = UpdateStatus.ERROR
            self._last_error = f"Resposta inválida do GitHub: {exc}"
            return None

        return self._parse_release_payload(payload)

    def download_update(self, info: UpdateInfo) -> Path:
        """V1.0: NÃO baixa automaticamente — abre release page no browser.

        V1.1 com tufup: baixa .zip + verifica TUF signature + retorna
        path local.

        Args:
            info: ``UpdateInfo`` retornado por ``check_for_updates``.

        Raises:
            NotImplementedError: sempre — V1.0 redireciona ao browser.
                Mensagem inclui URL para o consumidor (UI) abrir.
        """
        raise NotImplementedError(
            "Auto-download deferred V1.1 (tufup). " f"V1.0: baixe manualmente em {info.release_url}"
        )

    def apply_update(self, downloaded_zip: Path) -> None:
        """V1.0: NÃO aplica updates — instrui usuário a re-extrair zip.

        V1.1 com tufup: extrai zip + atomic replace files via
        ``os.replace`` (.tmp → final) + restart hint.

        Args:
            downloaded_zip: Path para zip baixado.

        Raises:
            NotImplementedError: sempre — V1.0 instrui ação manual.
        """
        raise NotImplementedError(
            "Auto-apply deferred V1.1 (tufup). "
            f"V1.0: extraia {downloaded_zip} e substitua a pasta de instalação. "
            "Veja docs/release/INSTALL.md."
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_current_version(self) -> str:
        """Resolve versão atual via ``__api_version__`` (fallback ``0.0.0``)."""
        try:
            from data_downloader.public_api import __api_version__

            return str(__api_version__)
        except (ImportError, AttributeError):
            return "0.0.0"

    def _fetch_json(self, url: str) -> dict[str, object]:
        """GET URL + parse JSON. Raises on network/parse error."""
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        # urllib.request.urlopen valida HTTPS server cert por default.
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_SECONDS) as response:
            data = response.read()
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Payload GitHub Releases não é objeto JSON")
        return parsed

    def _parse_release_payload(self, payload: dict[str, object]) -> UpdateInfo | None:
        """Parse payload GitHub Releases. Retorna UpdateInfo ou None."""
        tag_name = payload.get("tag_name")
        if not isinstance(tag_name, str):
            self._last_status = UpdateStatus.ERROR
            self._last_error = "Campo tag_name ausente/inválido na release"
            return None

        if not _is_newer(tag_name, self._current_version):
            self._last_status = UpdateStatus.UP_TO_DATE
            self._last_error = None
            return None

        # Strip 'v' prefix para latest_version (consistente com __api_version__).
        latest = tag_name[1:] if tag_name.startswith("v") else tag_name

        html_url_raw = payload.get("html_url")
        html_url = html_url_raw if isinstance(html_url_raw, str) else ""

        published_raw = payload.get("published_at")
        published = published_raw if isinstance(published_raw, str) else ""

        body_raw = payload.get("body")
        body = body_raw if isinstance(body_raw, str) else ""

        # Tenta extrair URL do .zip do primeiro asset (best-effort).
        download_url: str | None = None
        assets = payload.get("assets")
        if isinstance(assets, list):
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                name = asset.get("name")
                url = asset.get("browser_download_url")
                if isinstance(name, str) and isinstance(url, str) and name.endswith(".zip"):
                    download_url = url
                    break

        info = UpdateInfo(
            latest_version=latest,
            current_version=self._current_version,
            release_url=html_url,
            download_url=download_url,
            published_at=published,
            body=body,
        )
        self._last_status = UpdateStatus.OUTDATED
        self._last_error = None
        return info
