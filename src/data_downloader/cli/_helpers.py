"""data_downloader.cli._helpers — shared helpers for the cli/ package.

Owner: Sol (Story 4.28 P0-A1 refactor — pacotificação do monolito ``cli.py``).

Centraliza utilitários compartilhados entre os submódulos do pacote
``data_downloader.cli/``. Sem este módulo, helpers ``_make_console``,
``_format_microcopy``, last_symbol cache, e sentinels frozen-mode
seriam duplicados em ``download.py``, ``doctor.py``, ``migrate.py``,
etc.

Convenção (Story 4.28 AC4):

- Cada submódulo importa via path absoluto:
  ``from data_downloader.cli._helpers import _make_console, ...``.
- Submódulos NÃO importam uns dos outros — única dependência cruzada
  permitida é este módulo (`_helpers`).
- Backward-compat: nomes ``_bootstrap_env`` / ``_get_credential`` /
  ``_open_catalog`` etc. são re-exportados via ``cli/__init__.py``
  para preservar callsites de tests (e.g.
  ``from data_downloader.cli import _bootstrap_env``).
"""

from __future__ import annotations

import contextlib
import logging
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from data_downloader.storage.catalog import Catalog
    from data_downloader.ui.microcopy_loader import MicrocopyEntry as _MicrocopyEntryT
else:
    # Placeholder runtime — type alias só é resolvido lazy em
    # ``_build_known_sentinels``. Evita ciclo cli→ui em import time.
    _MicrocopyEntryT = object


__all__ = [
    "DEFAULT_CATALOG_PATH",
    "MicrocopyEntryT",
    "_approx_size_mb",
    "_bootstrap_env",
    "_build_known_sentinels",
    "_default_period",
    "_format_duration",
    "_format_microcopy",
    "_get_credential",
    "_get_known_sentinels",
    "_last_symbol_cache_path",
    "_load_last_symbol",
    "_make_console",
    "_migrate_legacy_last_symbol_cache",
    "_open_catalog",
    "_open_catalog_for_validation",
    "_save_last_symbol",
]

# Tipo público para uso pelos submódulos (re-export do alias interno).
MicrocopyEntryT = _MicrocopyEntryT


# =====================================================================
# Bootstrap env (dotenv) + credentials precedence — preserves v1.0.2 fix
# =====================================================================
#
# Carrega ``.env`` de candidatos em ordem de precedência ANTES de qualquer
# leitura ``os.getenv``. Delegado a ``_env_loader`` para que UI mode
# (``ui/app.py::main``) carregue o mesmo .env user-global (Pichau live
# test 2026-05-06 / Story v1.0.5).
#
# Ordem (primeiro arquivo encontrado vence):
#   1. ``cwd / .env``                              — projeto local (dev)
#   2. ``<exe-dir> / .env``                        — distribuição PyInstaller
#   3. ``~/.data-downloader/.env``                 — config user-global


def _bootstrap_env() -> None:
    """Carrega ``.env`` do primeiro candidato existente.

    Delega a :func:`data_downloader._env_loader.bootstrap_env` — single
    source of truth compartilhado com ``ui/app.py::main()``.
    Idempotent — chamada múltipla é segura. Best-effort: qualquer erro é
    silenciado (CLI ainda funciona sem .env quando vars já estão no ambiente).
    """
    from data_downloader._env_loader import bootstrap_env

    bootstrap_env()


def _get_credential(canonical: str, deprecated: str | None = None) -> str | None:
    """Lê env var canônica com fallback warning para nome deprecated.

    Story v1.0.2 fix B2 (Nelo+Aria 2026-05-05): backwards-compat para os
    naming antigos ``PROFIT_USER`` / ``PROFIT_PASS`` (sem prefixo). Naming
    canônico é ``PROFITDLL_*``. Quando só o deprecated está set, emitimos
    ``DeprecationWarning`` e retornamos o valor.

    Args:
        canonical: Nome canônico (``PROFITDLL_USER``).
        deprecated: Nome legado opcional (``PROFIT_USER``).

    Returns:
        Valor da var ou ``None`` quando nenhuma das duas está set.
    """
    val = os.getenv(canonical)
    if val:
        return val
    if deprecated is not None:
        legacy = os.getenv(deprecated)
        if legacy:
            warnings.warn(
                f"{deprecated} is deprecated; use {canonical} (Story v1.0.2 B2).",
                DeprecationWarning,
                stacklevel=2,
            )
            return legacy
    return None


# =====================================================================
# Frozen-mode sentinels → microcopy (Story v1.0.2 fix B-Frozen #3)
# =====================================================================
#
# Mapa de sentinelas internas (não-``NL_*``) que podem aparecer em
# ``DownloadResult.error_message`` quando algo falha no frozen mode
# (PyInstaller bundle).


def _build_known_sentinels() -> dict[str, _MicrocopyEntryT]:
    """Lazy builder do mapa de sentinelas — evita import circular cli↔microcopy."""
    from data_downloader.ui.microcopy_loader import MicrocopyEntry

    return {
        "VERIFY_SCRIPT_MISSING": MicrocopyEntry(
            msg_type="error",
            title="Script de verificação ausente",
            detail=(
                "O script ``verify-dll-companions.py`` não foi encontrado "
                "no bundle PyInstaller. Provável corrupção do build."
            ),
            action=("Reinstale o data-downloader (ou rode `data-downloader doctor`)."),
        ),
        "VERIFY_SCRIPT_LOAD_FAILED": MicrocopyEntry(
            msg_type="error",
            title="Falha ao carregar verify-dll-companions",
            detail="Importlib não conseguiu carregar o script de verificação.",
            action="Reinstale o data-downloader.",
        ),
        "COMPANIONS_MISSING": MicrocopyEntry(
            msg_type="error",
            title="DLL companions ausentes",
            detail="Arquivos companions da ProfitDLL não foram encontrados ({tail}).",
            action=(
                "Rode `bootstrap-dll.ps1` ou reinstale o data-downloader "
                "para restaurar os companions."
            ),
        ),
        "WINDLL_LOAD_FAILED": MicrocopyEntry(
            msg_type="error",
            title="Falha ao carregar ProfitDLL.dll",
            detail="Não consegui carregar a ProfitDLL ({tail}).",
            action="Verifique que o Windows é x64 e que a DLL não está bloqueada.",
        ),
        "UNSUPPORTED_PLATFORM": MicrocopyEntry(
            msg_type="error",
            title="Plataforma não suportada",
            detail="data-downloader requer Windows x64 (ProfitDLL é Win64-only).",
            action="Use uma máquina Windows 10/11 x64.",
        ),
        "InvalidContract": MicrocopyEntry(
            msg_type="error",
            title="Contrato inválido",
            detail="O símbolo ``{tail}`` não é um contrato vigente.",
            action="Liste vigentes: `data-downloader contracts list`.",
        ),
    }


# Cache module-level — populado lazy na 1ª chamada de ``_get_known_sentinels``.
_KNOWN_SENTINELS: dict[str, _MicrocopyEntryT] | None = None


def _get_known_sentinels() -> dict[str, _MicrocopyEntryT]:
    """Retorna o mapa cacheado de sentinelas (lazy build na 1ª chamada)."""
    global _KNOWN_SENTINELS
    if _KNOWN_SENTINELS is None:
        _KNOWN_SENTINELS = _build_known_sentinels()
    return _KNOWN_SENTINELS


# =====================================================================
# Rich Console + microcopy formatter (CLI_PATTERNS §9 + R17)
# =====================================================================


def _make_console() -> Console:
    """Console Rich respeitando NO_COLOR env (CLI_PATTERNS §9)."""
    if os.environ.get("NO_COLOR") is not None:
        return Console(no_color=True, force_terminal=False, highlight=False)
    return Console()


def _format_microcopy(msg_id: str, field: str = "title", **kwargs: object) -> str:
    """Wrapper local — ensura R17 sem expor o loader em todo lugar."""
    from data_downloader.ui.microcopy_loader import format_msg

    return format_msg(msg_id, field=field, **kwargs)


# =====================================================================
# last_symbol cache (CLI_PATTERNS §10)
# =====================================================================
#
# Canonical path uses HYPHEN (``~/.data-downloader/``) — alinhado a
# :func:`data_downloader._internal.bundle_paths.user_data_dir`. Pré-fix
# usava UNDERSCORE (``~/.data_downloader/``), criando diretório fantasma.
# Migração silenciosa best-effort.


def _last_symbol_cache_path() -> Path:
    from data_downloader._internal.bundle_paths import user_data_dir

    return user_data_dir() / "cache" / "last_symbol.txt"


def _migrate_legacy_last_symbol_cache() -> None:
    """Migra ``~/.data_downloader/cache/last_symbol.txt`` → path canônico (hífen).

    Best-effort: qualquer ``OSError`` é apenas logado em ``warning`` e
    suprimido — UX cache é opcional, nunca pode quebrar a CLI.
    """
    legacy = Path.home() / ".data_downloader" / "cache" / "last_symbol.txt"
    canonical = _last_symbol_cache_path()
    try:
        if legacy.exists() and not canonical.exists():
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_bytes(legacy.read_bytes())
    except OSError as exc:
        logging.getLogger("data_downloader.cli").warning(
            "last_symbol cache legacy migration skipped: %s", exc
        )


def _load_last_symbol() -> str | None:
    """Lê último símbolo usado do cache (CLI_PATTERNS §10)."""
    _migrate_legacy_last_symbol_cache()
    p = _last_symbol_cache_path()
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def _save_last_symbol(symbol: str) -> None:
    """Persiste símbolo no cache (best-effort; falha silenciosa)."""
    p = _last_symbol_cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(symbol, encoding="utf-8")
    except OSError:
        pass


# =====================================================================
# Default period (CLI_PATTERNS §10)
# =====================================================================


def _default_period() -> tuple[object, object]:
    """Mês corrente — 1º até hoje (CLI_PATTERNS §10).

    Returns:
        Tupla ``(first_of_month, today)`` ambos ``datetime.date``. Typed
        como ``object`` para evitar import datetime no helpers (já
        importado on-demand pelos submódulos).
    """
    from datetime import date

    today = date.today()
    first = date(today.year, today.month, 1)
    return first, today


# =====================================================================
# Catalog helpers (open + auto-populate seed YAML — v1.0.2 fix Pichau smoke)
# =====================================================================

DEFAULT_CATALOG_PATH: Path = Path("data") / "_internal" / "catalog.db"


def _open_catalog(db_path: Path | None = None) -> Catalog:
    """Abre o catálogo no path canônico (data/_internal/catalog.db — ADR-024).

    Story v1.0.2 fix (Pichau smoke 2026-05-06): catalog vazio (first-run
    do .exe distribuído) auto-populava do seed YAML embutido em
    ``CONTRACTS.md``.
    """
    from data_downloader.orchestrator.contracts import (
        list_contracts,
        populate_contracts_from_seed,
    )
    from data_downloader.storage.catalog import Catalog

    path = db_path if db_path is not None else DEFAULT_CATALOG_PATH
    catalog = Catalog(db_path=path)
    try:
        existing = list_contracts(catalog)
        if not existing:
            populate_contracts_from_seed(catalog)
    except Exception as exc:
        from data_downloader.observability.logging_config import get_logger

        get_logger(__name__).warning(
            "seed_populate_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            location="_open_catalog",
            db_path=str(path),
        )
    return catalog


def _open_catalog_for_validation(data_dir: Path) -> Catalog:
    """Variante de :func:`_open_catalog` que respeita ``data_dir`` arbitrário.

    Usado pelos comandos ``integrity check`` e ``integrity validate-data``
    (Story 2.1) — sem reconcile automático (ADR-024).
    """
    from data_downloader.orchestrator.contracts import (
        list_contracts,
        populate_contracts_from_seed,
    )
    from data_downloader.storage.catalog import Catalog

    db_path = data_dir / "_internal" / "catalog.db"
    catalog = Catalog(db_path=db_path, data_dir=data_dir, auto_reconcile=False)
    try:
        existing = list_contracts(catalog)
        if not existing:
            populate_contracts_from_seed(catalog)
    except Exception as exc:
        from data_downloader.observability.logging_config import get_logger

        get_logger(__name__).warning(
            "seed_populate_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            location="_open_catalog_for_validation",
            db_path=str(db_path),
        )
    return catalog


# =====================================================================
# Misc download UI helpers
# =====================================================================


def _approx_size_mb(partitions: tuple[Path, ...]) -> float:
    """Soma file size em MB. Best-effort; ignora arquivos ausentes."""
    total = 0
    for p in partitions:
        with contextlib.suppress(OSError):
            total += Path(p).stat().st_size
    return total / (1024 * 1024)


def _format_duration(seconds: float) -> str:
    """Formata duração humana (ex.: '4min 12s', '34s')."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = int(seconds % 60)
    return f"{minutes}min {rem:02d}s"
