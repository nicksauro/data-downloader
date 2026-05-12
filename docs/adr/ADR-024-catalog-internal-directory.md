# ADR-024 — Catalog SQLite em `data/_internal/`

**Status:** ACCEPTED
**Date:** 2026-05-07
**Owner:** @architect (Aria) + @data-engineer (Sol) — directive Pichau live smoke v1.1.0

## Context

Desde Story 1.4, o catalog SQLite reside em `data/history/catalog.db`,
co-habitando o diretório com os arquivos Parquet
(`data/history/{exchange}/{symbol}/{year}/{month}.parquet`).

Live smoke v1.1.0 (Pichau, 2026-05-07) reportou UX confusa: ao abrir
`data/history/` no Windows Explorer, o usuário vê `catalog.db` lado a lado
com os parquets e estranha — esperava ver "apenas os arquivos baixados".
Sintoma capturado nas próprias palavras: "tem algum arquivo chamado catalog
na pasta do hd q eu baixei".

Opções consideradas:

1. **Mover para `~/.data-downloader/catalog.db`** — esconde totalmente, mas
   quebra previsibilidade (usuário não consegue auditar). Rejeitada.
2. **Mover para `data/_internal/catalog.db` + Hidden attribute** — convenção
   universal `_internal/` ("implementation detail, fica fora do meu caminho",
   também usada pelo PyInstaller `--onedir`). Mantém path previsível para
   power users que quiserem inspecionar com `sqlite3 CLI` ou DuckDB. **Aceita**.
3. **Renomear `catalog.db` → `.catalog.db`** — leading-dot é convenção Unix,
   ignorado por Explorer Windows. Rejeitada por não ser cross-platform.

## Decision

Mover `catalog.db` (e os auxiliares WAL/SHM) para `data/_internal/catalog.db`.
Aplicar Windows `FILE_ATTRIBUTE_HIDDEN` em `data/_internal/` para que
Explorer (default settings) oculte o diretório.

**Migration silenciosa**: `Catalog.__post_init__` detecta `data/history/catalog.db`
e move atomicamente via `Path.rename()` antes de abrir conexão. WAL/SHM
auxiliares também migrados. Idempotente; loga `catalog_migrated` quando
aciona.

**Regras de segurança da migration**:

| Estado | Ação |
|--------|------|
| `old` ausente, `new` ausente | no-op (Catalog cria limpo) |
| `old` existe, `new` ausente | rename atômico old → new (+ WAL/SHM); log `catalog_migrated` |
| `old` ausente, `new` existe | no-op (já migrado) |
| `old` existe, `new` existe | preserva NEW; log `catalog_legacy_path_kept`. Admin investiga/exclui legado manualmente. |
| Falha I/O | log `catalog_migration_failed`; não levanta. Catalog tenta abrir new (falha mais limpa downstream). |
| Caller passa path legado explicitamente | no-op (`old.resolve() == new.resolve()`) — defensivo para callers ainda não migrados. |

**Default path canônico** atualizado em `cli.py` (sites: `_DEFAULT_CATALOG_PATH`,
`_open_catalog_for_validation`, multi-symbol broker, `_check_schema`,
`_open_migration_components`).

**Hidden attribute Windows** aplicado via `data_downloader.storage._paths.hide_directory_windows`
(best-effort, no-op em Linux/macOS, no-op em path inexistente, no-op se
`ctypes` falhar). Não interfere com Path operations Python — apenas oculta
no Explorer default.

## Consequences

**Positive:**

- **UX**: `data/history/` no Explorer mostra apenas parquets (data files
  visíveis ao usuário). `data/_internal/` fica oculto por default.
- **Convenção**: `_internal/` indica "implementation detail, not for user" —
  alinhado com PyInstaller `--onedir` layout (familiar a usuários do bundle).
- **Hidden attribute Windows** reforça a separação visual sem quebrar
  inspeção de power users (Mostrar arquivos ocultos ainda revela tudo).
- **Migration silenciosa** preserva continuidade de upgrade v1.0.x → v1.1.0
  sem requerer ação do usuário; log `catalog_migrated` deixa trilha de auditoria.
- **Path previsível**: usuário power continua podendo abrir o `.db` com
  `sqlite3` / DuckDB para queries ad-hoc — não foi parar em `~/.data-downloader/`.

**Negative:**

- **Quebra hardcode** de scripts externos que abrem `data/history/catalog.db`
  diretamente (DuckDB ad-hoc, sqlite3 CLI). Mitigation: este ADR documenta o
  novo path; CLI/UI/public_api permanecem abstratos.
- **Coexistência temporária**: módulos não-CLI (`public_api/download.py`,
  `ui/adapters/catalog_adapter.py`, `ui/screens/settings_screen.py`) ainda
  passam `data/history/catalog.db` explicitamente. Migration helper trata
  esse caso como no-op (defensive: `old.resolve() == new.resolve()` → return).
  Esses sites serão atualizados em hotfix follow-up paralelo (Felix+Uma agente).
- **Hidden attribute** depende do user não ter "Mostrar arquivos ocultos"
  ativado — degrada gracefully se ativado (vê o `_internal/`, mas convenção
  ainda comunica "implementation").

## References

- Story 1.4 — design inicial do catalog SQLite (`data/history/catalog.db`).
- Story 1.5 — Catalog API + integridade.
- Pichau live smoke v1.1.0 (2026-05-07) — directive originária.
- `src/data_downloader/storage/catalog.py::_migrate_legacy_catalog_path`
- `src/data_downloader/storage/_paths.py::hide_directory_windows`
- `tests/unit/test_catalog_legacy_migration.py` (6 testes — semântica completa).
