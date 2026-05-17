# INTEGRITY.md — Checks de Integridade de Dados

**Owner:** 💾 Sol (Storage Engineer)
**Versão:** v1.0.0
**Status:** ACCEPTED (Story 0.0)
**Aplicável a:** todos os Parquet em `data/history/**` e ao catálogo `catalog.db`.

---

## 0. Princípio

Integridade não é evento — é regime. Os checks abaixo são **invariantes que devem ser sempre verdade**. Violação = pegar um avião e pousar (cancelar pipeline em curso, isolar partição suspeita, alarmar).

---

## 1. Invariantes

| ID    | Invariante                                                                                       | Checagem                                  |
|-------|--------------------------------------------------------------------------------------------------|-------------------------------------------|
| INT-1 | Todo Parquet escrito carrega `schema_version` no metadata.                                       | `check_schema_version_present`            |
| INT-2 | `(symbol, timestamp_ns, trade_id)` ou chave canônica longa (ver SCHEMA §2) é única dentro de partição. | `check_no_duplicates`                     |
| INT-3 | `timestamp_ns` é monotonicamente crescente dentro de partição quando ordenado por `(timestamp_ns, sequence_within_ns)`. | `check_monotonic_timestamps`              |
| INT-4 | `price > 0` e `quantity > 0` em todos os trades.                                                 | `check_valid_price_qty`                   |
| INT-5 | `exchange ∈ {"F", "B"}`.                                                                         | `check_exchange_code_valid`               |
| INT-6 | Catálogo `partitions` ↔ arquivos físicos: para cada `partition_path` há arquivo, e vice-versa.   | `check_catalog_filesystem_consistency`    |
| INT-7 | `partitions.checksum_sha256` = SHA256 do arquivo on-disk.                                        | `check_checksums`                         |
| INT-8 | `partitions.first_ts_ns ≤ partitions.last_ts_ns` e ambos batem com min/max do arquivo.           | `check_partition_bounds`                  |
| INT-9 | Sem gaps inesperados em datas de pregão B3 dentro da janela de download declarada.               | `check_gaps_against_b3_calendar`          |
| INT-10| `_pending_commits` está vazio (ou tem entradas com pid ainda vivo).                              | `check_pending_commits_clean` + `Catalog.recover_pending_commits()` (Story 4.22) |
| INT-11| `dll_version` no metadata Parquet está dentro do conjunto de versões aprovadas.                  | `check_dll_version_known`                 |
| INT-12| `ingestion_ts_ns >= timestamp_ns` (não pode ter chegado antes de ocorrer).                       | `check_ingestion_temporal_order`          |

> Nota: INT-12 admite exceção de até 1s para clock skew entre máquina B3 e máquina cliente. Violação > 1s alarma.

---

## 2. Queries DuckDB canônicas (uma por invariante)

Todas as queries operam sobre uma partição via `read_parquet(path)`. Para checks cross-partição, usar glob: `read_parquet('data/history/F/WDOJ26/**/*.parquet')`.

### 2.1 INT-1: schema_version_present

Não é query DuckDB pura — é leitura do metadata Parquet:

```python
import pyarrow.parquet as pq

def check_schema_version_present(path: str) -> bool:
    md = pq.read_metadata(path).metadata or {}
    sv = md.get(b'schema_version')
    if sv is None:
        return False
    # Validar que é semver no conjunto aceito
    return sv.decode().startswith(('1.', '2.'))  # ajustar conforme novas majors
```

### 2.2 INT-2: no_duplicates (chave canônica)

```sql
-- Caso geral: emite linha por chave duplicada
WITH all_keys AS (
    SELECT
        symbol,
        timestamp_ns,
        trade_id,
        price,
        quantity,
        buy_agent_id,
        sell_agent_id,
        sequence_within_ns,
        CASE
            WHEN trade_id IS NOT NULL
                THEN CONCAT(symbol, '|', timestamp_ns, '|TID:', trade_id)
            ELSE CONCAT(
                symbol, '|', timestamp_ns,
                '|', price, '|', quantity,
                '|', COALESCE(CAST(buy_agent_id AS VARCHAR), 'NULL'),
                '|', COALESCE(CAST(sell_agent_id AS VARCHAR), 'NULL'),
                '|SEQ:', sequence_within_ns
            )
        END AS dedup_key
    FROM read_parquet(?)
)
SELECT dedup_key, COUNT(*) AS n
FROM all_keys
GROUP BY dedup_key
HAVING COUNT(*) > 1;
-- Esperado: 0 linhas. Qualquer linha = violação.
```

### 2.3 INT-3: monotonic_timestamps

```sql
WITH ordered AS (
    SELECT
        timestamp_ns,
        sequence_within_ns,
        LAG(timestamp_ns) OVER (
            ORDER BY timestamp_ns, sequence_within_ns
        ) AS prev_ts
    FROM read_parquet(?)
)
SELECT COUNT(*) AS regression_count
FROM ordered
WHERE prev_ts IS NOT NULL AND timestamp_ns < prev_ts;
-- Esperado: 0.
```

### 2.4 INT-4: valid_price_qty

```sql
SELECT COUNT(*) AS bad_rows
FROM read_parquet(?)
WHERE price <= 0 OR quantity <= 0 OR price IS NULL OR quantity IS NULL;
-- Esperado: 0.
```

### 2.5 INT-5: exchange_code_valid

```sql
SELECT DISTINCT exchange
FROM read_parquet(?)
WHERE exchange NOT IN ('F', 'B');
-- Esperado: 0 linhas.
```

### 2.6 INT-9: gap_detection contra calendário B3

Pré-requisito: tabela auxiliar `b3_trading_days` (carregada no boot — fonte: pacote `bizdays` ou CSV B3 oficial).

```sql
WITH partitions_ymd AS (
    SELECT
        date_trunc('day', to_timestamp(timestamp_ns / 1e9)) AS trade_day
    FROM read_parquet(?)
    GROUP BY 1
),
expected AS (
    SELECT trading_day
    FROM b3_trading_days
    WHERE trading_day BETWEEN
          (SELECT MIN(trade_day) FROM partitions_ymd)
      AND (SELECT MAX(trade_day) FROM partitions_ymd)
)
SELECT trading_day AS missing_day
FROM expected
LEFT JOIN partitions_ymd ON expected.trading_day = partitions_ymd.trade_day
WHERE partitions_ymd.trade_day IS NULL;
-- Esperado: 0 linhas. Cada linha = dia útil B3 sem nenhum trade no Parquet.
-- Se contrato não estava vigente nesse dia → ignorar (cross-check com `contracts`).
```

### 2.7 INT-7: checksums

```python
def check_checksums(catalog: sqlite3.Connection, root: Path) -> list[dict]:
    """Compara checksum no catálogo vs SHA256 recalculado on-disk."""
    rows = catalog.execute(
        "SELECT partition_path, checksum_sha256 FROM partitions"
    ).fetchall()
    violations = []
    for path, expected in rows:
        full = root / path
        if not full.exists():
            violations.append({"path": path, "error": "MISSING_FILE"})
            continue
        actual = sha256_file(full)
        if actual != expected:
            violations.append({
                "path": path,
                "expected": expected,
                "actual": actual,
                "error": "CHECKSUM_MISMATCH",
            })
    return violations
```

> Otimização (escala): consultar `_checksum_cache` primeiro; rehash apenas se `(file_size_bytes, mtime_ns)` mudou.

---

## 3. Política de checksum

### 3.1 Algoritmo

- **SHA256** dos bytes do arquivo Parquet final (após footer, sem buffer pendente).
- Calculado **antes** do `os.replace(tmp, final)` (sobre o `.tmp`).
- Armazenado em **dois lugares** (redundância — finding M4):
  1. Metadata Parquet do próprio arquivo: chave `sha256_self`.
  2. Catálogo SQLite: `partitions.checksum_sha256`.

### 3.2 Cache (`_checksum_cache`)

Tabela `_checksum_cache(partition_path, file_size_bytes, mtime_ns, checksum_sha256, cached_at)`.

```python
def get_or_compute_checksum(catalog, path: Path) -> str:
    stat = path.stat()
    cached = catalog.execute(
        "SELECT checksum_sha256 FROM _checksum_cache "
        "WHERE partition_path = ? AND file_size_bytes = ? AND mtime_ns = ?",
        (relative_path, stat.st_size, stat.st_mtime_ns),
    ).fetchone()
    if cached:
        return cached[0]
    digest = sha256_file(path)
    catalog.execute(
        "INSERT OR REPLACE INTO _checksum_cache VALUES (?, ?, ?, ?, datetime('now'))",
        (relative_path, stat.st_size, stat.st_mtime_ns, digest),
    )
    catalog.commit()
    return digest
```

### 3.3 Limitações

- Cache assume que `(size, mtime_ns)` muda quando arquivo muda. Filesystems exóticos (ZFS dedup, edição com mtime-preserve) podem violar. Em ambiente Windows + NTFS isso é seguro.
- Para auditoria forense (suspeita de corrupção sem mudança de metadata), CLI oferece `data-downloader integrity-check --force-rehash`.

### 3.4 Workflow no boot

1. Para cada `partition_path` em `partitions`:
   - Se arquivo não existe → registra em `_drift_report` (drift A — ver §5.1).
   - Se arquivo existe mas size difere → drift B.
   - Se size bate mas checksum (cache ou recomputado) difere → drift C (corrupção).

---

## 4. Two-phase commit emulado (atomicidade — finding M5/H7)

### 4.1 Problema

`os.replace(tmp, final)` é atômico no Linux/Windows desde que mesmo filesystem. Mas se processo crash entre `replace` e `INSERT INTO partitions`, o catálogo fica desatualizado: arquivo existe, catálogo não sabe. Re-execução escreveria de novo (perde idempotência) ou pular (perde dado se for write reentrante diferente).

### 4.2 Protocolo

**Fase 1 — pending commit:**

```sql
BEGIN IMMEDIATE;
INSERT INTO _pending_commits(partition_path, started_at, expected_sha256, expected_size, job_id, pid)
VALUES (?, datetime('now'), ?, ?, ?, ?);
COMMIT;
```

**Fase 2 — atomic file replace:**

```python
# tmp já escrito e fsync'd
os.replace(tmp_path, final_path)
# fsync do diretório pai (Linux semantics — Windows é no-op mas seguro chamar)
if hasattr(os, 'O_DIRECTORY'):
    fd = os.open(str(final_path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
```

**Fase 3 — register partition + clear pending:**

```sql
BEGIN IMMEDIATE;
INSERT INTO partitions(...)
VALUES (...);
DELETE FROM _pending_commits WHERE partition_path = ?;
COMMIT;
```

### 4.3 Recovery no boot

```python
def recover_pending_commits(catalog, root: Path) -> RecoveryReport:
    rows = catalog.execute(
        "SELECT partition_path, expected_sha256, expected_size, pid, started_at "
        "FROM _pending_commits"
    ).fetchall()
    report = RecoveryReport()
    for path, expected_sha, expected_size, pid, started in rows:
        if pid_alive(pid):
            # Outro processo ainda escrevendo — não tocar
            report.skipped.append((path, "pid_alive"))
            continue
        full = root / path
        if not full.exists():
            # Crash antes do replace → nada para recuperar
            catalog.execute("DELETE FROM _pending_commits WHERE partition_path = ?", (path,))
            report.cleaned.append((path, "no_file"))
            continue
        actual_size = full.stat().st_size
        if actual_size != expected_size:
            report.corrupted.append((path, f"size {actual_size} != {expected_size}"))
            continue
        actual_sha = sha256_file(full)
        if actual_sha != expected_sha:
            report.corrupted.append((path, "checksum mismatch"))
            continue
        # Arquivo OK mas catálogo não tem entry → re-registrar
        register_partition_from_file(catalog, full, expected_sha)
        catalog.execute("DELETE FROM _pending_commits WHERE partition_path = ?", (path,))
        report.recovered.append(path)
    catalog.commit()
    return report
```

### 4.4 Limitação Windows (finding M5)

`os.replace` em Windows falha com `PermissionError` se o destino estiver aberto por outro processo (ex: leitor DuckDB ativo). Mitigações:

1. Writer faz retry com backoff (max 3 tentativas, 100ms→500ms→2s).
2. Se falhar definitivamente, deixa `_pending_commits` populado e arquivo `.tmp` no disco, alarmando. Próxima execução tenta de novo.
3. Política para projetos downstream: ler via `pq.ParquetFile(path).read()` (que abre+lê+fecha) em vez de manter file handle aberto.

### 4.5 Recovery on boot — protocolo (Story 4.22 / ADR-026 §2.2)

**Implementação:** `Catalog.recover_pending_commits()` em `src/data_downloader/storage/catalog.py` (substitui o pseudo-código documental §4.3 anterior — agora é executável e coberto por unit + integration tests).

**Chamada no boot:** `__post_init__` invoca `self.recover_pending_commits()` ANTES de `cleanup_orphans` e `reconcile`. Try/except `(OSError, sqlite3.Error)` garante que falha de recovery NÃO derruba o boot — apenas loga `catalog.recover_pending.failed` e segue. Próximo boot tenta de novo (idempotente).

**Resolution table** (por row em `_pending_commits`):

| Condição | Ação | Categoria |
|----------|------|-----------|
| `_pid_alive(pid, started_at)` retorna `True` | nada | `skipped` (motivo: `pid_alive`) |
| PID morto + arquivo ausente em `data_dir/history/{rel_path}` | `DELETE` da pending row | `cleaned` (motivo: `no_file`) |
| PID morto + arquivo presente + `size + sha256` match | UPSERT em `partitions` via `_register_recovered_partition` + `DELETE` pending | `recovered` |
| PID morto + arquivo presente + `size` mismatch | `_quarantine_partition` + `DELETE` pending | `quarantined` (motivo: `size_mismatch`) |
| PID morto + arquivo presente + `sha256` mismatch | `_quarantine_partition` + `DELETE` pending | `quarantined` (motivo: `sha_mismatch`) |
| Falha de I/O em `stat` | `_quarantine_partition` + `DELETE` pending | `quarantined` (motivo: `stat_failed`) |

Se `_quarantine_partition` falhar (disco cheio, FS read-only), a row pending é **preservada** para retry no próximo boot — quarantine é idempotente.

**PID liveness algorithm** (`_pid_alive(pid, started_at)`):

1. `pid is None` → `False`.
2. Se `psutil` indisponível (`ImportError`) → fallback timestamp: `True` apenas se `started_at > now - 1h`.
3. `psutil.pid_exists(pid)` → se `False` → morto.
4. `psutil.Process(pid).create_time()` (epoch UTC) comparado com `started_at`. Se `create_time > started_at` → PID reciclado pelo OS (processo diferente) → morto.
5. Caso contrário → vivo (skip recovery).

**Defesa contra PID recycling:** a comparação `create_time vs started_at` é essencial. Sem ela, `psutil.pid_exists` pode dar falso positivo se outro processo nascer com o mesmo PID após o crash do writer original.

**Quarantine convention:** `data/_quarantine/{YYYYMMDDTHHMMSSZ}/{partition_path_relativo}`. Cada evento cria um diretório raiz timestamped (UTC compact) e preserva a hierarquia interna a partir de `data_dir/history/`. Move via `os.replace` (atômico, mesmo FS); fallback `shutil.move` para cross-drive Windows.

**Defense-in-depth:** `cleanup_orphans` (Story 1.5 AC7) ganhou `DELETE FROM _pending_commits WHERE pid IS NOT NULL AND started_at < datetime('now', '-1 day')` ao final — garante eventual limpeza mesmo se recovery deu falso-positivo de `pid_alive` em alguma janela patológica.

**CLI manual:**

```bash
# Read-only — classifica e mostra counts sem mutar nada
data-downloader catalog recover-pending --dry-run

# Aplica o protocolo (DELETE/UPSERT/quarantine conforme tabela acima)
data-downloader catalog recover-pending
```

Exit codes:

- `0` — report limpo OU mutações aplicadas sem quarantine.
- `2` — uma ou mais partições foram quarentenadas (alerta operacional; inspecionar `data/_quarantine/`).
- `3` — erro de operação (catálogo inacessível, `OSError`, `sqlite3.Error`).

**Logs estruturados** (úteis para grep em ambiente prod):

- `catalog.recover_pending.startup` — sumário após boot (apenas se houve trabalho).
- `catalog.recover_pending.failed` — exception durante recovery (degrade, não levanta).
- `catalog.recovery.recovered` — partição re-registrada com sucesso.
- `catalog.recovery.quarantined` — arquivo movido para quarantine.
- `catalog.recovery.quarantine_failed` — quarantine não conseguiu mover (pending preservada).
- `catalog.recovery.invalid_layout` / `.metadata_read_failed` / `.no_metadata` / `.metadata_parse_failed` / `.upsert_failed` — falhas durante `_register_recovered_partition` (pending preservada).
- `catalog.cleanup_orphans.pending_purged` — defense-in-depth purgou rows >1 dia.

---

## 5. Reconcile catálogo ↔ arquivos (drift report)

Comando: `data-downloader catalog reconcile [--fix]`.

### 5.1 Tipos de drift

| Tipo | Sintoma                                   | Default ação                                                                |
|------|-------------------------------------------|-----------------------------------------------------------------------------|
| A    | Catálogo lista, arquivo não existe        | Reportar; com `--fix`: remove entry de `partitions` (após confirmar gap em `gaps`). |
| B    | Arquivo existe, catálogo não lista        | Reportar; com `--fix`: lê metadata Parquet do arquivo, registra em `partitions`. Se metadata ausente/inválida → quarantine em `data/_quarantine/`. |
| C    | Catálogo lista + arquivo existe + checksum diverge | Reportar como CORRUPÇÃO. Nunca auto-fix. Exige investigação humana. |

### 5.2 Output esperado (`--dry-run`)

```
Reconcile report — 2026-05-03T14:32:11Z
Root: data/history/
Total partitions in catalog: 47
Total parquet files on disk: 49

Drift A (orphan catalog entries): 1
  - F/WINH26/2026/02.parquet  (file missing since 2026-04-12)

Drift B (untracked files): 3
  - F/WDOJ26/2026/04.parquet  (size: 12.3 MB, schema_version: 1.0.0, recoverable: YES)
  - F/WDOJ26/2026/05.parquet  (size: 11.8 MB, schema_version: 1.0.0, recoverable: YES)
  - F/WDOJ26/2026/06.tmp.parquet  (orphan tmp from crashed write — quarantine)

Drift C (corruption): 0

Suggested actions:
  - Run with --fix to apply A and B (B will quarantine 1 file).
  - No action will be taken for C.
```

---

## 6. DST e ambiguidade pré-2020 (finding M17)

- B3 não observa DST desde 2019.
- Para histórico < 2020, o `timestamp_ns` BRT NAIVE pode mapear ambiguamente a 2 instantes UTC nos dias de transição.
- Política Sol: **smoke tests e benchmarks limitados a >= 2020-01-01**.
- Para histórico anterior, usuário deve invocar com `--allow-dst-ambiguity`. Sem flag, downloads pré-2020 são rejeitados pelo orchestrator.
- Schema **não** carrega informação de fuso (R2). Quem quiser converter para UTC com tratamento de DST faz no leitor downstream.

---

## 7. Resposta a Pyro (finding H4 — `dll_queue` size tunável)

**Decisão:** `dll_queue maxsize` deixa de ser hardcoded `10000` e vira parâmetro tuável:

- **Variável de ambiente:** `DATA_DOWNLOADER_DLL_QUEUE_SIZE`.
- **Default:** `10000` (mantido para compatibilidade com plano atual).
- **Range válido:** `[1000, 1_000_000]`.
- **Validação no boot:** valor fora do range → erro fatal com mensagem clara.

**Pergunta aberta para Pyro:** o default `10000` precisa ser validado pelo benchmark `bench_callback_to_disk` com pausa simulada de writer em **0ms / 100ms / 500ms / 2000ms** (story 1.4.5). Sem esse bench, o default é provisório. Ver finding H4 do plan review.

> Sol não decide o default ótimo — Pyro decide com dados. Sol garante que o knob existe.

---

## 8. CLI

```
data-downloader integrity-check [--symbol X] [--date-range A B] [--checks all|catalog|files|schema|gaps]
data-downloader integrity-check --force-rehash       # ignora _checksum_cache
data-downloader catalog reconcile [--dry-run | --fix]
data-downloader catalog recover-pending             # corre §4.3 manualmente
```

Exit codes:
- `0` — sem violações.
- `2` — violações detectadas (relatório no stdout).
- `3` — erro de operação (catálogo inacessível, etc.).

---

## 9. Referências

- `docs/storage/SCHEMA.md` §2 (dedup), §5 (catálogo), §5.7 (`_pending_commits`).
- ADR-002, ADR-004.
- Story 1.4.5 (Pyro — bench_callback_to_disk).
- Story 1.6 (probe DLL).
- Story 2.1 (Quinn — data validators como código — cross-references INT-* com ferramentas executáveis).
- `docs/decisions/PLAN_REVIEW_2026-05-03.md` findings: H4, H6, H7, M4, M5, M6, M17.

— Sol, custodiando o histórico 💾
