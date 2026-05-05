# Architectural Decision Records (ADR) — data-downloader

> Índice canônico de todas as decisões arquiteturais do squad. Mantido por 🏛️ **Aria** (System Architect).
> Toda nova decisão transversal vira ADR numerado em ordem sequencial. ADR não escrito = decisão não tomada.

---

## Status legend

| Marker | Significado |
|--------|-------------|
| `accepted` | Decisão ativa — código deve refletir |
| `accepted (deferred to ...)` | Decisão aprovada como direção; execução agendada para fase futura |
| `superseded by ADR-NNN` | Substituído por ADR mais recente — manter para histórico |
| `proposed` | Em discussão; ainda não tem força normativa |

---

## Índice

| # | Título | Status | Aceito em | Supersedes / Superseded-by |
|---|--------|--------|-----------|----------------------------|
| [001](./ADR-001-python-runtime.md) | Python 3.12 + ctypes como runtime | `accepted` | 2026-05-03 | — |
| [002](./ADR-002-storage-stack.md) | Storage stack: Parquet (Snappy) + DuckDB + SQLite | `accepted` | 2026-05-03 | — |
| [003](./ADR-003-front-pyside6.md) | Front desktop = PySide6 (Qt6) single-process *(+ amendment 2026-05-03: `--onedir` + `DontUseNativeDialog`)* | `accepted` | 2026-05-03 | — |
| [004](./ADR-004-partition-layout.md) | Particionamento `{exchange}/{symbol}/{year}/{month}.parquet` | `accepted` | 2026-05-03 | — |
| [005](./ADR-005-thread-model.md) | Thread model com bounded queues e block back-pressure *(+ amendment 2026-05-03: state machine de shutdown + INV-11 + INV-12)* | `accepted` | 2026-05-03 | — |
| [006](./ADR-006-contract-calendar.md) | Calendário de contratos vigentes = tabela estática versionada | `accepted` | 2026-05-03 | — |
| [007](./ADR-007-public-api.md) | Public API com versionamento SemVer separado do core | `superseded` | 2026-05-03 | superseded by **ADR-007a** |
| [007a](./ADR-007a-public-api-redesign.md) | Public API redesign: `DownloadHandle` + `cancel()` | `accepted` | 2026-05-03 | supersedes **ADR-007** |
| [008](./ADR-008-dll-distribution.md) | Estratégia de distribuição da ProfitDLL (gitignore + bootstrap) | `accepted` | 2026-05-03 | — |
| [009](./ADR-009-build-determinism.md) | Build determinístico (lockfile + `SOURCE_DATE_EPOCH` + container) | `accepted` | 2026-05-03 | — |
| [010](./ADR-010-logging-strategy.md) | Logging strategy: `structlog` + `contextvars` + redaction + R21 hot-path | `accepted` | 2026-05-03 | — |
| [011](./ADR-011-exception-hierarchy.md) | Exception hierarchy & error propagation (pública vs `_InternalError`) | `accepted` | 2026-05-03 | — |
| [012](./ADR-012-configuration.md) | Configuration: env vars (12-factor) + TOML override + Pydantic Settings | `accepted` | 2026-05-03 | — |
| [013](./ADR-013-observability.md) | Runtime observability: counters, gauges, histograms (`prometheus_client`) | `accepted` | 2026-05-03 | — |
| [014](./ADR-014-test-strategy.md) | Test strategy: layers, mock DLL, fake clock, property-based | `accepted` | 2026-05-03 | — |
| [015](./ADR-015-multiprocess-catalog.md) | Multiprocess catalog coordination (broker process) | `REVOKED 2026-05-05` | 2026-05-03 | superseded by **ADR-022** |
| [016](./ADR-016-code-signing.md) | Windows code signing & SmartScreen | `accepted (deferred to V1 release)` | 2026-05-03 | — |
| [017](./ADR-017-auto-updater.md) | Auto-updater strategy (tufup preliminar) | `accepted (deferred to Epic 4)` | 2026-05-03 | — |
| [019](./ADR-019-schema-as-contract.md) | Schema as Contract — Never Drop Columns | `proposed` | 2026-05-05 | — |
| [020](./ADR-020-volume-completeness.md) | Volume Completeness Invariant | `proposed` | 2026-05-05 | — |
| [022](./ADR-022-single-session-sequential-policy.md) | Single-Session Sequential Download Policy | `accepted` | 2026-05-05 | supersedes **ADR-015** |

---

## Resumo por categoria

### Runtime & linguagem
- ADR-001 (Python 3.12 + ctypes)

### Storage & dados
- ADR-002 (Parquet + DuckDB + SQLite)
- ADR-004 (Particionamento mensal)
- ADR-006 (Calendário de contratos)
- ~~ADR-015 (Multiprocess catalog broker)~~ — **REVOKED 2026-05-05** (ver ADR-022)
- ADR-019 (Schema as Contract — proposed)
- ADR-020 (Volume Completeness — proposed)

### Multi-symbol & licensing
- ADR-022 (Single-Session Sequential Download Policy — supersedes ADR-015)

### UI & packaging
- ADR-003 (PySide6 single-process + `--onedir`)

### Concorrência
- ADR-005 (Thread model + state machine de shutdown)

### Public API & contratos
- ADR-007 (princípio SemVer separado — superseded)
- ADR-007a (`DownloadHandle` + `cancel()`)
- ADR-011 (Exception hierarchy)

### Operacional / DevOps
- ADR-008 (DLL distribution)
- ADR-009 (Build determinism)
- ADR-012 (Configuration)
- ADR-016 (Code signing) *(deferred)*
- ADR-017 (Auto-updater) *(deferred)*

### Observabilidade & qualidade
- ADR-010 (Logging strategy + R21)
- ADR-013 (Runtime observability)
- ADR-014 (Test strategy)

---

## Cross-references com outros agentes

| ADR | Documento agente | Nota |
|-----|------------------|------|
| ADR-002, ADR-004, ADR-006 | `docs/storage/SCHEMA.md`, `CONTRACTS.md`, `INTEGRITY.md`, `MIGRATIONS.md`, `QUERIES.md` (💾 Sol) | Schema interno e particionamento operacionalizados por Sol |
| ADR-005 amendment (INV-11/12) | `docs/dll/QUIRKS.md` Q11-E (🗝️ Nelo) | Restrições de callback DLL alinhadas |
| ADR-008 | `docs/release/BOOTSTRAP_PROTOCOL.md` (⚙️ Gage) | Bootstrap script + .dll-version |
| ADR-009 | `build/BUILD_PROTOCOL.md` (🏗️ Felix + ⚙️ Gage) | Determinismo de build operacionalizado |
| ADR-003 amendment (--onedir) | `build/BUILD_PROTOCOL.md`, `build/data_downloader.spec.template` (🏗️ Felix) | Packaging --onedir |
| ADR-010 (R21) | `docs/perf/HOT_PATH_RULES.md` (⚡ Pyro) | Hot-path rules ratificadas |
| ADR-014 | `docs/qa/TEST_PYRAMID.md`, `INVARIANTS_TESTS.md`, `SMOKE_PROTOCOL.md` (🧪 Quinn) | Test strategy operacionalizada |
| ~~ADR-015~~ | `docs/ARCHITECTURE.md` §2.4, §6 (🏛️ Aria) | **REVOKED 2026-05-05** — multi-symbol broker process; ver ADR-022 |
| ADR-022 | `docs/ARCHITECTURE.md` §2.4 (amendment 1.1.2 pendente), `docs/dll/QUIRKS.md` Q17 (🗝️ Nelo, CLOSED Hipótese B) | Single-session sequential — supersedes ADR-015 |

---

## Governança

**Autoridade exclusiva:** 🏛️ Aria (System Architect)

- Criação: `*adr-new {título-curto}`
- Promoção `proposed → accepted`: `*adr-accept {NNN}` (após validação cross-ADR)
- Supersedência: `*adr-supersede {NNN-antigo} {NNN-novo}`
- Listagem: `*adr-list [--status proposed|accepted|superseded]`

**Regras (vide `agents/architect.md`):**

1. Toda decisão transversal vira ADR. Sem ADR = decisão não existe.
2. Mínimo 2 alternativas consideradas com prós/contras explícitos.
3. Decisões que tocam DLL exigem consulta a 🗝️ Nelo.
4. Decisões que tocam schema/storage exigem consulta a 💾 Sol.
5. Decisões que tocam UI/UX exigem consulta a 🎨 Uma.
6. Decisões de packaging/release exigem consulta a ⚙️ Gage.
7. Mudanças em `public_api/` exigem ADR (lei R15 — fronteira SemVer).

---

*— maintainer 🏛️ Aria, mapeando o território — 2026-05-03*
