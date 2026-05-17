# ADR-026 — Storage atomicity & recovery (two-phase commit invertido, recovery on boot, single-flight compact)

- **Status:** Proposed
- **Date:** 2026-05-16
- **Author:** Aria (@architect) + consulta @data-engineer (Sol)
- **Driver:** Revisão consolidada Frente 1 v1.4.0 — 4 P0s identificados (S1/S2/S3/S4) entre `_pending_commits`, ordem do two-phase commit, writer race em partições diárias e compactação concorrente cross-process.
- **Supersedes:** — (complementa ADR-025 §2.4 e INTEGRITY.md §4)

---

## 1. Contexto

A v1.3.0 (ADR-025) introduziu layout híbrido diário/mensal com auto-compactação. A revisão técnica 2026-05-16 do squad mapeou quatro defeitos de atomicidade no caminho `ParquetWriter.write → Catalog.register_partition → maybe_compact_month`:

| ID | Defeito | Sintoma | Referência |
|----|---------|---------|------------|
| **P0-S1** | `_pending_commits` populado mas nunca lido após crash | tabela acumula órfãos indefinidamente; INT-10 (`check_pending_commits_clean`) sempre verde mas falso | `catalog.py:863-987` (write path), `INTEGRITY.md §4.3` (doc-only) |
| **P0-S2** | Two-phase commit invertido | ordem real: `os.replace → INSERT pending → UPSERT partitions + DELETE pending`. INTEGRITY.md §4 prescreve `Fase 1 → replace → Fase 3`. Janela atômica vazia entre `os.replace` e Fase 1 | `parquet_writer.py:419`, `catalog.py:913-980` |
| **P0-S3** | Writers concorrentes em mesma partição diária | ADR-025 §2.2 declara write-once; sem advisory lock; last-writer-wins via `os.replace`. Trades do primeiro somem silenciosamente | `parquet_writer.py:347` |
| **P0-S4** | `maybe_compact_month` race cross-process | `INSERT ... ON CONFLICT DO UPDATE SET started_at = excluded.started_at` sobrescreve in-flight; ambos processos compactam, segundo `os.replace` sobrescreve | `catalog.py:1228-1242` |

A janela de exposição cresce com (a) deploys multi-processo (UI + CLI concorrentes), (b) crashes durante write (Windows BSOD, processo killado), (c) compactação automática disparada após cada `register_partition`. Em produção (Pichau, 7 anos × N símbolos), o número absoluto de eventos é alto mesmo com probabilidade individual baixa.

A solução exige decisões transversais (writer + catalog + recovery + CLI) que não cabem em correções pontuais.

## 2. Decisão

### 2.1 Two-phase commit — invertido para a ordem prescrita

**Ordem nova (Fase 1 → Replace → Fase 3):**

```
ParquetWriter.write():
  1. escreve tmp.{uuid}
  2. fsync(file)
  3. SHA256 + file_size do tmp
  4. fsync(parent_dir)
  ──── Fase 1 (catalog) ────
  5. catalog.pending_commit_start(rel_path, expected_sha256, expected_size, pid, job_id)
     → INSERT em _pending_commits (claim com advisory lock implícito — ver §2.3)
  ──── Fase 2 (filesystem) ────
  6. os.replace(tmp, final)
  7. fsync(parent_dir)
  ──── Fase 3 (catalog) ────
  8. catalog.pending_commit_finish(write_result, partition, job_id)
     → UPSERT em partitions + DELETE de _pending_commits (mesma transação)
```

**API nova:** `Catalog.pending_commit(rel_path, partition, *, expected_sha256, expected_size, job_id) → ContextManager[PendingCommitHandle]`.

```python
with catalog.pending_commit(rel_path, partition,
                            expected_sha256=sha,
                            expected_size=size,
                            job_id=job_id) as handle:
    os.replace(tmp_path, final_path)
    _fsync_directory(final_path.parent)
    handle.complete(write_result)  # Fase 3 dentro do __exit__
```

`ParquetWriter.write(...)` ganha kwarg opcional `catalog: Catalog | None`. Quando passado, usa o context manager. Quando `None` (callers legacy), preserva comportamento atual mas emite `DeprecationWarning` (remoção planejada para v1.5.0).

`Catalog.register_partition` é reescrito como wrapper de compatibilidade: faz o ciclo completo (Fase 1 + simula Fase 2 detectando que `os.replace` já aconteceu + Fase 3). Marcado como `deprecated` — caller correto é o context manager.

**Justificativa do acoplamento writer ↔ catalog:** o protocolo two-phase commit é por definição cross-module. Alternativa de "Orchestrator chama Fase 1 manualmente" exige vazar SHA256/size pre-replace para fora do writer, quebrando encapsulamento. Injeção opcional é o trade-off mínimo.

### 2.2 Recovery on boot — `recover_pending_commits()`

Método público novo na classe `Catalog`. Chamado em `__post_init__` ANTES de `cleanup_orphans` e `reconcile` (cleanup poderia deletar `.tmp` que recovery ainda quer validar; reconcile depende do FS estar consistente).

```python
def recover_pending_commits(self) -> PendingRecoveryReport:
    """Resolve entries órfãs de _pending_commits após crash.

    Para cada row:
    - PID vivo (psutil.pid_exists + started_at < 1h) → skip ('pid_alive').
    - PID morto + arquivo ausente em final_path → DELETE pending ('no_file').
    - PID morto + arquivo presente + sha/size match → re-registra em partitions, DELETE pending ('recovered').
    - PID morto + arquivo presente + sha/size mismatch → move para data/_quarantine/, DELETE pending ('corrupted').
    """
```

**PID liveness algorithm:**
1. `psutil.pid_exists(pid)` — se False → morto.
2. Se True, comparar `psutil.Process(pid).create_time()` com `started_at` da row. Se `create_time > started_at` → PID reciclado (processo diferente do que originou a pending) → morto.
3. Se True e `create_time <= started_at` → vivo (skip).
4. Fallback (psutil indisponível): `started_at < now - 1h` → morto.

**Quarantine convention:** `data/_quarantine/{YYYY-MM-DDTHHMMSS}/{original_relative_path}` (mesma estrutura interna; UTC ISO no diretório raiz para auditoria).

**CLI:** `data-downloader catalog recover-pending [--dry-run]` invoca o método manualmente. Exit codes alinhados com `integrity-check`.

### 2.3 Writer race — `_pending_commits` como advisory lock

Após a inversão (§2.1), a Fase 1 ocorre ANTES do `os.replace`. Como `_pending_commits.partition_path` é PRIMARY KEY, dois writers concorrentes para a mesma partição diária colidem no INSERT.

**Política de claim refinada:**

```sql
INSERT INTO _pending_commits(partition_path, started_at, expected_sha256, expected_size, job_id, pid)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(partition_path) DO UPDATE SET
  started_at = excluded.started_at,
  expected_sha256 = excluded.expected_sha256,
  expected_size = excluded.expected_size,
  job_id = excluded.job_id,
  pid = excluded.pid
WHERE _pending_commits.started_at < datetime('now', '-1 hour')
   OR _pending_commits.pid = excluded.pid  -- mesmo processo, retry idempotente
```

Após o INSERT, re-`SELECT` da row e comparar `pid` com `os.getpid()`. Se diferente → outro writer ativo → levanta `ConcurrentWriterError` (subclasse de `IntegrityError`).

**Retry policy no writer:**
- `ConcurrentWriterError` → backoff exponencial 100ms → 500ms → 2s (max 3 attempts).
- Se persiste após 3 attempts → propaga erro ao orchestrator. Orchestrator marca o chunk como `failed` no `chunk_ledger` para retry futuro.

**Trade-off:** alternativa de arquivo `.lock` no FS adiciona complexidade Windows (`msvcrt.locking`) sem ganho vs advisory lock SQLite (que já é WAL-coordenado entre processos via `BEGIN IMMEDIATE`).

### 2.4 Compact single-flight — claim atômico

`maybe_compact_month` ganha proteção idêntica ao writer race:

```sql
INSERT INTO compactions(symbol, exchange, year, month, started_at, completed_at, error)
VALUES (?, ?, ?, ?, ?, NULL, NULL)
ON CONFLICT(symbol, exchange, year, month) DO UPDATE SET
  started_at = excluded.started_at,
  completed_at = NULL,
  error = NULL
WHERE compactions.completed_at IS NOT NULL
   OR compactions.started_at < datetime('now', '-1 hour')
```

Pós-INSERT, `SELECT started_at FROM compactions WHERE ...` e comparar com o `now` original passado. Se != → claim falhou (outro processo está compactando há <1h) → no-op, retorna `False`.

**Deadlock recovery:** se `started_at < now - 1h` E `completed_at IS NULL`, considera-se processo morto. O claim sobrescreve. `_recover_inflight_compactions` (já existente em `catalog.py:1641`) processa o estado consistente no próximo boot.

**Trade-off:** alternativa `BEGIN EXCLUSIVE TRANSACTION` foi rejeitada — bloquearia o catálogo inteiro pelo tempo da compactação (segundos a minutos), causando back-pressure no writer e no UI auto-refresh. O claim atômico é localizado.

### 2.5 INTEGRITY.md update

A ordem nova (§2.1) torna `INTEGRITY.md §4` correto na descrição mas a implementação atual estava invertida. O texto fica intacto; muda a implementação. Adiciona-se §4.5 documentando:

- O claim atômico em `_pending_commits` como advisory lock cross-process.
- A política de PID liveness com `psutil` + `create_time` (defesa contra PID recycling).
- A política de quarantine para corrupted entries.

### 2.6 Schema do catálogo

**Sem mudança de DDL.** A tabela `_pending_commits` (`catalog.py:166-175`) já tem as colunas necessárias (`partition_path` PK, `started_at`, `expected_sha256`, `expected_size`, `pid`, `job_id`). A tabela `compactions` (criada pela migration v1.2→v1.3) já tem `started_at`/`completed_at` para o claim atômico.

**Migration v1.3→v1.4 (catalog_version bump):**
- Bump `catalog_version='1.4.0'` em `_meta`.
- Sem ALTER TABLE — apenas semantic upgrade do protocolo de write/recovery.

## 3. Cenários verificados

| Cenário | Resultado esperado |
|---------|--------------------|
| Crash entre Fase 1 e os.replace (sem arquivo final) | Boot: recovery vê pending sem arquivo → DELETE pending (`no_file`). FS limpo. |
| Crash entre os.replace e Fase 3 (arquivo presente, partition row ausente) | Boot: recovery vê pending com arquivo + sha match → re-registra em `partitions` + DELETE pending (`recovered`). |
| Crash entre os.replace e Fase 3 + tmp corrompido (mas houve replace OK antes de outro write) | sha mismatch → quarantine + DELETE pending. Reconcile flagra `partition_path` ausente posteriormente, sem perda real (era write parcial). |
| 2 processos escrevem 2026/03/15.parquet simultaneamente | Writer #2 vê pending row do Writer #1 (pid vivo) → backoff 3x → falha com `ConcurrentWriterError`. Orchestrator marca chunk como `failed` para retry. Writer #1 completa normalmente. |
| 2 processos chamam maybe_compact_month("WDOJ26", 2026, 3) simultaneamente | Processo #2 vê started_at do Processo #1 (<1h) → claim falha → retorna False. Processo #1 compacta. Apenas 1 `os.replace` no `MM.parquet`. |
| Processo morto durante compact (`started_at` há 2h, `completed_at` NULL) | Boot: `_recover_inflight_compactions` (já existente) detecta in-flight e resolve (completa OU reverte). Próxima `maybe_compact_month` consegue claim porque `started_at < now-1h`. |
| PID reciclado (pending criado por PID 1234 morto; outro processo agora é PID 1234) | psutil.create_time(1234) > pending.started_at → recovery considera morto → resolve normalmente. |
| Recovery falha (DB locked) | log warning + skip; próximo boot tenta de novo. Idempotente. |

## 4. Consequências

### Positivas

- **Atomicidade real:** crash em qualquer ponto da pipeline write deixa estado recuperável. INT-10 (`check_pending_commits_clean`) passa a refletir realidade.
- **Writer race resolvido sem novo lock primitive:** `_pending_commits` PK serve como advisory lock natural — zero novas tabelas, zero código de lock FS.
- **Compact race resolvido com `WHERE` claim — sem BEGIN EXCLUSIVE.** Catálogo permanece responsivo durante compactação.
- **PID recycling defendido** (psutil.create_time check) — corrige bug latente em qualquer recovery baseado só em `os.kill(pid, 0)`.
- **Backward-compatible:** `register_partition` segue funcional como wrapper deprecated. Callers de v1.3.x não quebram.

### Negativas / trade-offs

- **Acoplamento `ParquetWriter ↔ Catalog`:** writer agora aceita injeção opcional de catalog. Antes era completamente desacoplado (writer produzia `WriteResult`, caller decidia se/como registrar). Trade-off justificado: protocolo two-phase é por definição cross-module.
- **Dependência nova: `psutil`:** já estava em `requirements.txt`? Validar; se não, adicionar. Se inviável, fallback timestamp-based degrada para 1h timeout.
- **Latência adicional na fase de write:** +1 INSERT em `_pending_commits` ANTES do `os.replace` (era depois). Custo: ~5-10ms por write. Em downloads densos (~1 write/s), absorvido na perda visual zero.
- **Boot mais lento:** recovery percorre todas as rows de `_pending_commits` + valida cada uma (SHA256 de arquivos restantes). Se há centenas de pending órfãs (cenário patológico — múltiplos crashes em sequência), boot pode levar segundos. Mitigação: log INFO com count + tempo total.
- **Test surface grande:** três protocolos novos a testar (recovery, writer race, compact race) — esforço de QA significativo. Mitigado pela estrutura modular (cada um testável em isolation).

## 5. Alternativas consideradas

| Opção | Por que rejeitada |
|-------|-------------------|
| Manter ordem invertida + chamar `register_partition` ANTES de `os.replace` | Não resolve writer race (sem advisory lock pre-replace); resolve apenas P0-S2 parcialmente. |
| Arquivo `.lock` no FS (msvcrt em Windows, fcntl em Linux) | Complexidade cross-platform + risco de orphan locks após crash. SQLite advisory já é WAL-coordenado. |
| `BEGIN EXCLUSIVE TRANSACTION` durante compactação | Bloqueia catálogo inteiro por minutos. Quebra UI auto-refresh, quebra writer concorrente. |
| Separar `_pending_writes` (P0-S3) de `_pending_commits` (P0-S1/S2) | Duas tabelas com semântica idêntica — overhead conceptual sem ganho. |
| Implementar lock distribuído via SQLite WAL com `BEGIN IMMEDIATE` e retry loop sem `_pending_commits` | Funciona como mutex mas não cobre crash recovery — perde a propriedade de "claim que sobrevive a crash". |

## 6. Referências

- `src/data_downloader/storage/parquet_writer.py` (write, compact_month)
- `src/data_downloader/storage/catalog.py` (`_pending_commits` DDL :166-175; `register_partition` :863-987; `maybe_compact_month` :1178-1338; `_recover_inflight_compactions` :1641-1792)
- `docs/storage/INTEGRITY.md` §4 (two-phase commit), §4.3 (recovery), INT-10
- ADR-025 §2.4 (compactação atomicity)
- ADR-002 (storage stack, fsync semantics)
- ADR-004 (partition layout — referenced)
- Revisão consolidada 2026-05-16 (Frente 1: Storage Atomicity)
- Stories 4.22, 4.23, 4.24 (implementação)

— Aria 🏛️, cartografando atomicidade
