"""data_downloader._updater — Auto-updater stub (Story 4.4 / V1.0).

Owner: Felix (frontend-dev) UI integration | Architect: Aria (ADR-017
trajectory) | Release: Gage.

Pacote stub do auto-updater do data_downloader.

V1.0 entrega APENAS notificação manual (check + propose download). Full
TUF-based updater (`tufup` Client wrapper conforme ADR-017 §"Plano para
Epic 4") está deferred para V1.1 — pré-requisitos:

1. ADR-016 Caminho A ativado (cert EV adquirido) — sem signing, TUF
   verification client é teatro.
2. Key ceremony executada (humano + cold storage root key) — fora do
   escopo agente.
3. `release.yml` integra signing TUF metadata (targets/snapshot/
   timestamp) no pipeline.

Story-debt formal: ``docs/stories/4.4-followup.story.md``.

Convenção de privacidade (ADR-011 / ``_internal/``):

- Prefixo ``_`` no nome do pacote sinaliza "internal — não importável
  por consumidores externos".
- Tudo aqui é wired pela UI (`SettingsScreen`) ou CLI futura
  (`data-downloader self-update --check-only` em V1.1).
- `__all__` limitado a `UpdateInfo`, `UpdateStatus`, `UpdaterStub`
  para discovery interna.

Pública (re-export controlado em V1.1 via ``data_downloader.public_api``):
nenhum símbolo público em V1.0 — usuários interagem via UI Settings
screen apenas.
"""

from __future__ import annotations

from data_downloader._updater.tufup_stub import (
    UpdateInfo,
    UpdaterStub,
    UpdateStatus,
)

__all__ = [
    "UpdateInfo",
    "UpdateStatus",
    "UpdaterStub",
]
