# Changelog

Todas as mudanças notáveis no `data_downloader.public_api` (a fronteira
SemVer-tracked) são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
e a versão da API segue [Semantic Versioning 2.0](https://semver.org).

A versão da API (`__api_version__`) é independente de
`data_downloader.__version__` (que rastreia o pacote inteiro). Política
de SemVer estrito documentada em
[`docs/public_api/DEPRECATION_POLICY.md`](docs/public_api/DEPRECATION_POLICY.md).

---

## [API v1.0.0] — 2026-05-04

### Stable Public API release

Primeiro release **estável** da fronteira pública `data_downloader.public_api`.
A partir desta versão, garantias semânticas, assinaturas e hierarquia de
exceções são governadas por **SemVer estrito** (Story 4.3, COUNCIL-27).

- `__api_version__`: **0.4.0 → 1.0.0**.
- Política de deprecação formal em
  `docs/public_api/DEPRECATION_POLICY.md`.
- Exemplos de consumo (backtest, signal generator, risk monitor) em
  `docs/public_api/USAGE.md`.
- Decorator `@deprecated` (lifecycle `since`/`removed_in`/`replacement`)
  disponível em `data_downloader.public_api._deprecation` (uso interno).
- Regression test suite SemVer (`test_public_api_semver_regression.py`)
  garante que TODOS os símbolos da V1.0 mantêm assinatura cross-version.
- Guardrail anti-leak: `test_public_api_no_internal_imports.py` impede
  que tests consumer importem de internals (`dll`, `storage`,
  `orchestrator`, `_internal`).

### Exports estáveis (`__all__`)

**Funções:**

- `download(symbol, start, end, *, exchange="F", data_dir=None, ...) -> DownloadHandle`
- `read(symbol, start, end, *, exchange="F", data_dir=None, columns=None) -> pa.Table`
- `read_continuous(symbol_root, start, end, *, exchange="F", data_dir=None, catalog) -> pa.Table`
- `vigent_contract(symbol_root, on_date, *, exchange="F", catalog) -> str`

**Classes:**

- `DownloadHandle` (`cancel`, `result`, `events`, `cancelled`, `is_cancelled`,
  `is_cancelling`, `peek_result`, `join`)
- `DownloadProgress` (frozen dataclass — `total`, `done`, `message`,
  `trades_received`, `current_contract`, `is_99_reconnect`)
- `DownloadResult` (frozen dataclass — `job_id`, `symbol`, `exchange`,
  `actual_start`, `actual_end`, `trades_count`, `partitions`,
  `duration_seconds`, `status`, `error_message`)
- `DownloadStatus` (`Literal["completed", "partial", "failed", "cache_hit", "cancelled"]`)

**Exceções:**

- `DataDownloaderError` (base)
- `DLLInitError`
- `InvalidContract`
- `DiskFull`
- `DownloadError`
- `IntegrityError`
- `OperationCancelled` (Story 2.11)
- `ConnectionLost` (Story 2.11)

### Garantias V1.0 (contratuais — quebrar exige bump major)

1. **Idempotência (R5)** — re-run com mesmo `(symbol, start, end, exchange)` é
   seguro; trades duplicados são deduplicados pelo writer.
2. **BRT naive (R7)** — todos `datetime` são naive (sem `tzinfo`),
   horário Brasil (UTC-3).
3. **Dedup canônico (R5)** — `read`/`read_continuous` nunca retornam
   duplicatas (cut-off `+1ns` em rollovers).
4. **Ordem cronológica** — `timestamp_ns` ascendente.
5. **Schema estável** — 17 campos canônicos + `schema_version` em
   metadata Parquet.
6. **Cancel graceful** — `cancel()` drena chunks; trades committados
   preservados; status final `"cancelled"` levanta `OperationCancelled`
   em `result()`.
7. **Sem leak de exceções internas** — internals lançam
   `_InternalError`; fronteira traduz para `DataDownloaderError` family.

### Mudanças desde v0.x (cumulativo)

Todas as mudanças listadas abaixo já existiam em código (V0.x); este
release **formaliza** a fronteira como estável — não introduz novas
funções nem altera comportamento.

- **Docstrings completos** em todas funções/classes públicas (formato
  Google style com `Args`, `Returns`, `Raises`, `Examples`, `Notes`).
- Module docstring em `public_api/__init__.py` com:
  - Visão geral da API.
  - Garantias semânticas detalhadas.
  - Política SemVer.
  - Cobertura SemVer (o que está / o que NÃO está).
  - Histórico de bumps.
- Type annotations completas (mypy `--strict` clean em `public_api/`).

### Deprecated

_Nenhum em V1.0.0 — baseline._ Primeira deprecação será anunciada em
V1.x se/quando necessário, conforme política em
`docs/public_api/DEPRECATION_POLICY.md`.

### Removed

_Nenhum em V1.0.0 — baseline._

### Não coberto por SemVer (sujeito a mudança sem bump)

- Módulos `_internal/`, `dll/`, `storage/`, `orchestrator/`, `ui/`.
- Comportamento de exceções internas (`_InternalError` family).
- Performance / latência (governada por `benchmarks/BASELINES.md`).
- Mensagens humanas (microcopy ID estável; texto pode mudar via
  `MICROCOPY_CATALOG.md` — Uma authority).

### Roadmap

- **V1.x (minor):** possíveis adições aditivas — `download_batch(symbols=[...])`
  se backtest engine demandar; `read(columns=...)` push-down quando
  `DuckDBReader` expor.
- **V2.0 (major):** **nada planejado**. Declarado intencionalmente —
  V1.0 é projetado como contrato estável de longo prazo.

---

## [API v0.4.0] — 2026-05-03

### Added (Story 2.11 — H10 closure + Q02-E)

- `OperationCancelled` exception — sinaliza cancel cooperativo concluído
  (não é falha; trades parciais preservados em `details`).
- `ConnectionLost` exception — reconexão DLL ultrapassou janela
  esperada (Q02-E hard timeout).
- `DownloadHandle.cancelled()` — non-blocking probe se cancel
  concluído.
- `DownloadHandle.is_cancelled` (property alias).
- `DownloadHandle.is_cancelling()` — `True` se cancel pedido (ainda
  pode estar drenando).
- `DownloadHandle.peek_result()` — non-blocking, no-raise inspection do
  `DownloadResult` (não levanta `OperationCancelled` para
  `status='cancelled'` como `result()` faz).

### Changed (soft-break)

- `DownloadHandle.result()` agora **levanta** `OperationCancelled` quando
  `status == "cancelled"` (anteriormente retornava o `DownloadResult`
  com status). Soft-break porque consumers que tratavam `result.status
  == "cancelled"` continuam funcionando se trocarem o pattern para
  `try/except OperationCancelled`. Justificado em COUNCIL-17 (exception
  hierarchy H10 cancel) — sinal explícito é UX correto.

---

## [API v0.3.0] — 2026-05-03

### Added (Story 1.7b — ADR-007a)

- `download(symbol, start, end, *, exchange='F', ...) -> DownloadHandle`
  — função primária da API; retorna handle assíncrono.
- `DownloadHandle` class com `cancel`, `result`, `events`.
- `DownloadProgress` frozen dataclass.
- `DownloadResult` frozen dataclass.
- `DownloadStatus` Literal type alias.
- `DownloadError` exception (placeholder pré-existente, agora ativo).

### Design rationale

ADR-007a: handle pattern (vs. union return) elimina violação Liskov +
viabiliza cancel real (H10) + carrega `current_contract` em rollover
(M16).

---

## [API v0.2.0] — 2026-05-03

### Added (Story 1.6)

- `vigent_contract(symbol_root, on_date, *, exchange='F', catalog) -> str`
  — resolve raiz + data → `contract_code` vigente.
- `InvalidContract` exception — símbolo não resolve em contrato vigente.

---

## [API v0.1.0] — 2026-05-03

### Added (Story 1.5b)

- `read(symbol, start, end, *, exchange='F', data_dir=None, columns=None) -> pa.Table`
- `read_continuous(symbol_root, start, end, *, exchange='F', data_dir=None, catalog) -> pa.Table`
- `DataDownloaderError` (base exception).
- `DLLInitError`, `DiskFull`, `IntegrityError` (placeholders).

### Design rationale

ADR-007: fronteira `public_api/` separada das internals. SemVer-tracked
desde v0.1.0 mas **não-estável** até v1.0 (esperado quebrar entre
minor versions durante alpha).
