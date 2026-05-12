"""Integration tests — assets bundled em ``dist/data_downloader/_internal/``.

Owner: Quinn (QA — Wave 2 P0 v1.1.0 master plan).

Valida que o build PyInstaller --onedir empacotou corretamente os assets
não-Python que :func:`data_downloader._internal.bundle_paths.asset_path`
precisa resolver em runtime frozen:

    - ``assets/style.qss``           — Felix-UI tema dark (Story 1.0.4 fix)
    - ``docs/storage/CONTRACTS.md``  — seed de contratos vigentes
    - ``ProfitDLL.dll`` companion    — vendor binary side-by-side

Se algum destes faltar, a UI quebra silenciosamente (QSS) ou o CLI cai
em :class:`FileNotFoundError` na primeira invocação que precisa do
asset (CONTRACTS, DLL).

Approach: probe direto do filesystem — ``Path.exists()`` em candidatos
canônicos do layout ``_internal/``. Não roda subprocess (rápido +
determinístico). Skipa clean se bundle ausente — mesmo gate de
``test_binary_exe.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# =====================================================================
# Bundle resolution — DRY com test_binary_exe.py.
# =====================================================================

_REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE = _REPO_ROOT / "dist" / "data_downloader"
INTERNAL = BUNDLE / "_internal"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not INTERNAL.is_dir(),
        reason=(f"Frozen bundle ausente em {BUNDLE}. " "Rode: python scripts/build_release.py."),
    ),
]


# =====================================================================
# QSS theme (Felix-UI Story 1.0.4)
# =====================================================================


def test_qss_in_bundle() -> None:
    """``assets/style.qss`` deve estar bundled em ``_internal/`` ou variante.

    Story v1.0.4 RCA: o spec antigo apontava para ``data_downloader/ui/assets``
    mas PyInstaller copiava para ``_internal/assets/``. Fix v1.1.0 (Aria
    bundle_paths) tenta múltiplos candidatos. Aqui validamos que AO MENOS
    UM candidato canônico existe — caso contrário a UI carrega sem tema
    (light theme bug v1.0.4).
    """
    candidates = [
        INTERNAL / "assets" / "style.qss",
        INTERNAL / "data_downloader" / "ui" / "assets" / "style.qss",
        BUNDLE / "assets" / "style.qss",
    ]
    found = [c for c in candidates if c.is_file()]
    assert found, "QSS theme não bundled. Candidatos verificados:\n  - " + "\n  - ".join(
        str(c) for c in candidates
    )


def test_qss_non_empty() -> None:
    """QSS bundled deve ter conteúdo (não ser placeholder vazio).

    Defesa contra build que copiou um arquivo zero-byte (acontece quando
    spec referencia path errado e PyInstaller cria stub).
    """
    candidates = [
        INTERNAL / "assets" / "style.qss",
        INTERNAL / "data_downloader" / "ui" / "assets" / "style.qss",
        BUNDLE / "assets" / "style.qss",
    ]
    qss = next((c for c in candidates if c.is_file()), None)
    if qss is None:
        pytest.skip("QSS não bundled — coberto por test_qss_in_bundle.")
    assert qss.stat().st_size > 100, (
        f"QSS suspeitosamente pequeno ({qss.stat().st_size} bytes) — "
        f"path={qss}. Provável placeholder vazio."
    )


# =====================================================================
# CONTRACTS seed (orchestrator first-run)
# =====================================================================


def test_contracts_seed_in_bundle() -> None:
    """``CONTRACTS.md`` (seed de contratos) deve estar bundled.

    Story v1.0.2 fix (first-run auto-populate): ``_open_catalog()`` lê
    este arquivo quando o catalog SQLite está vazio. Sem ele, primeiro
    download falha silencioso (lista vazia de contratos).
    """
    candidates = [
        INTERNAL / "docs" / "storage" / "CONTRACTS.md",
        INTERNAL / "data_downloader" / "orchestrator" / "_data" / "CONTRACTS.md",
        BUNDLE / "docs" / "storage" / "CONTRACTS.md",
    ]
    found = [c for c in candidates if c.is_file()]
    assert found, "CONTRACTS.md seed não bundled. Candidatos verificados:\n  - " + "\n  - ".join(
        str(c) for c in candidates
    )


# =====================================================================
# ProfitDLL companion
# =====================================================================


def test_profitdll_companion_present() -> None:
    """``ProfitDLL.dll`` deve estar side-by-side com o bundle.

    PyInstaller copia DLL companions via ``binaries=`` no spec — Story
    v1.0.5 fix. Pode estar em ``_internal/`` (default PyI 6.x) ou no
    diretório do .exe (PyI 5.x). Sem a DLL, ``ProfitDLL()`` falha no
    boot do CLI/UI antes mesmo do healthcheck.
    """
    candidates = [
        INTERNAL / "ProfitDLL.dll",
        BUNDLE / "ProfitDLL.dll",
        INTERNAL / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll",
    ]
    found = [c for c in candidates if c.is_file()]
    assert found, (
        "ProfitDLL.dll não bundled side-by-side. Candidatos verificados:\n  - "
        + "\n  - ".join(str(c) for c in candidates)
    )


def test_profitdll_companion_size_sane() -> None:
    """ProfitDLL.dll bundled deve ter tamanho compatível com binary real (>1MB).

    Defense em profundidade: build poderia copiar um placeholder/stub
    por engano. ProfitDLL real é >5MB; threshold conservador 1MB pega
    qualquer regression de "esqueci a DLL e o build copiou um README.txt".
    """
    candidates = [
        INTERNAL / "ProfitDLL.dll",
        BUNDLE / "ProfitDLL.dll",
        INTERNAL / "profitdll" / "DLLs" / "Win64" / "ProfitDLL.dll",
    ]
    dll = next((c for c in candidates if c.is_file()), None)
    if dll is None:
        pytest.skip("DLL ausente — coberto por test_profitdll_companion_present.")
    size_mb = dll.stat().st_size / (1024 * 1024)
    assert size_mb > 1.0, (
        f"ProfitDLL.dll suspeitosamente pequeno ({size_mb:.2f}MB) em {dll}. "
        "Provável stub/placeholder — verificar build_release.py spec."
    )


# =====================================================================
# Critical Python runtime files
# =====================================================================


def test_python_runtime_present() -> None:
    """Runtime Python (``python3*.dll``) deve estar em ``_internal/``.

    Sem isso, o launcher PyInstaller não inicia o interpretador. Smoke
    de saneamento — se este teste falha, o bundle está fundamentalmente
    quebrado e nenhum outro teste de subprocess vai passar.
    """
    py_dlls = list(INTERNAL.glob("python3*.dll"))
    assert py_dlls, (
        f"Nenhum python3*.dll em {INTERNAL} — bundle fundamentalmente " "quebrado, nada vai rodar."
    )


def test_base_library_zip_present() -> None:
    """``base_library.zip`` (stdlib bundled) deve estar em ``_internal/``.

    PyInstaller empacota módulos stdlib aqui. Ausência indica spec mal
    formado ou step de bundling pulado.
    """
    assert (
        INTERNAL / "base_library.zip"
    ).is_file(), f"base_library.zip ausente em {INTERNAL} — stdlib não bundled."
