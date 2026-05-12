# Invariantes do Sistema — data-downloader

**Owner:** Sol (Storage / Knowledge guardian)
**Versão:** v1.0.0
**Status:** ACCEPTED (Story 1.7g — 2026-05-05, council Sol)
**Origem:** consolidação de bugs P0 descobertos em smoke real postfix-35 + auditoria Nelo Council-32 (2026-05-05)

---

## 0. Propósito

Este documento define os **princípios INVIOLÁVEIS** do sistema data-downloader. Cada invariante (I1..I6) descreve uma propriedade que **nunca** pode ser violada em produção, sob risco de perda silenciosa de dados, regressão de qualidade ou quebra de contrato com consumidores downstream.

**Tooling DEVE checar essas invariantes em CI/CD.** Se o tooling não consegue checar uma invariante, ela ainda é lei — mas é considerada uma **fragilidade do projeto** e deve receber Story de remediação.

> Os invariantes derivam diretamente de **Constitution Article V (Quality First)** + **Article IV (No Invention)**. Violação = falha constitucional bloqueante.

---

## I1: Schema-as-Contract

**Categoria:** storage / parquet writer
**Origem do bug:** [Q-DRIFT-36](./dll/QUIRKS.md#q-drift-36) (writer parquet v1.0.0 silenciosamente descartava `buy_agent_name`/`sell_agent_name`/`trade_type_name`)
**ADR formal:** ADR-019 (Aria)

### Princípio

> Writer parquet **NUNCA** descarta colunas silenciosamente. Se `TradeRecord` (ou qualquer dict do pipeline) contém campos não mapeados no schema declarado, o writer **DEVE FALHAR LOUDLY** com `SchemaContractViolation` antes da escrita.

### Regras concretas

1. **Schema imutável por release** — bump aditivo (campo novo nullable + default seguro) = bump **minor** (`v1.0.0 → v1.1.0`). Quebrador (rename/drop/type/null change) = bump **major** (`v1.0.0 → v2.0.0`) + ADR + script de migração.
2. **Validação prévia obrigatória** — antes de `pa.Table.from_pylist(rows, schema=...)`, validar para cada row: `set(row.keys()) <= set(schema.names)` → se sobrar chave não mapeada, levantar `SchemaContractViolation`.
3. **Fail-loudly > tolerar** — pyarrow descarta silenciosamente por design (Q-DRIFT-36). NÃO confie. NÃO trate writer como caixa preta.
4. **Schema bumpa antes de writer** — adicionar campo novo no schema **antes** de o pipeline começar a populá-lo. Caso contrário, dados ficam no dict mas evaporam silenciosamente no parquet.

### Test obrigatório (CI)

```python
# tests/unit/test_storage_schema.py
def test_writer_raises_on_missing_schema_field():
    rows = [{"symbol": "X", "field_not_in_schema": 42, ...}]
    with pytest.raises(SchemaContractViolation):
        write_parquet(rows, schema=SCHEMA_TRADES_V1_0_0, path=tmp)
```

### CI lint check (recomendado)

`storage/lint_schema_field_count.py`: garante que `len(SCHEMA_TRADES_V*.names) >= len(SCHEMA_TRADES_V*_PREVIOUS.names)` — bumpou minor mas removeu campo? bloquear merge.

### Refs

- `docs/storage/SCHEMA.md` §0 (princípios não-negociáveis)
- `docs/storage/SCHEMA.md` §6 (política de migração)
- `docs/dll/QUIRKS.md` Q-DRIFT-36

---

## I2: Volume Completeness

**Categoria:** history / download flow
**Origem do bug:** [Q-DRIFT-37](./dll/QUIRKS.md#q-drift-37) (smoke real WDOFUT entregou 603k trades em ~4d quando baseline 1d ≈ 600-700k → perda de 70-80% silenciosa)
**ADR formal:** ADR-020 (Aria)

### Princípio

> Smoke real **DEVE** validar volume entregue contra baseline empírico antes de declarar download "completo". `TC_LAST_PACKET` é sinalização **necessária mas não suficiente** de fim de janela — DEVE ser cross-checada vs timestamp do último trade vs janela solicitada.

### Regras concretas

1. **Baseline empírico mínimo (validado smoke 2026-05-05):**
   - `WDOFUT` 1 dia útil → trades >= **500 000** (baseline real ≈ 600-700k; 500k é piso conservador).
   - `WINFUT` 1 dia útil → baseline TBD (Quinn Council-37 medirá).
   - Outros símbolos: medir antes de release.
2. **LAST_PACKET cross-check obrigatório** — após receber `TC_LAST_PACKET`, comparar `last_trade_timestamp_ns` vs `dt_end_str`. Se gap > threshold (TBD, sugestão inicial: > 1 hora útil), considerar **truncado**.
3. **Replay automático em gap detectado** — se gap detectado em I2.2, agendar replay da janela faltante (`gap_start = last_trade_ts + 1ns`, `gap_end = dt_end`). Marcar `downloads.status = 'partial'` até replay completar.
4. **Telemetria visível** — counter `volume_gap_detected_total` exposto em Prometheus (Story 2.x). Alarme se > 0 em produção.

### Test obrigatório (CI)

```python
# tests/integration/test_volume_baseline.py
def test_volume_baseline_per_day_minimum():
    """Smoke real WDOFUT 1d entrega trades >= 500k."""
    result = run_smoke_real(symbol="WDOFUT", exchange="F", days=1)
    assert result.trades_count >= 500_000, (
        f"VOLUME GAP detected: {result.trades_count} trades < 500k baseline. "
        f"Possível LAST_PACKET prematuro ou window cap server-side."
    )
```

### Refs

- `docs/dll/QUIRKS.md` Q-DRIFT-37
- `docs/dll/QUIRKS.md` Q-DRIFT-31 (janela máx ~5d) — relação direta
- COUNCIL-37 (Quinn — volume gap analysis)
- COUNCIL-38 (Nelo — download flow audit)

---

## I3: Agent Name Resolution Graceful

**Categoria:** metadata / DLL agent ID resolution
**Origem do bug:** [Q-DRIFT-34](./dll/QUIRKS.md#q-drift-34) (sentinel `0x8000000C = -2147483636` retornado por `GetAgentName` para IDs >1M)

### Princípio

> Agent ID `NL_NOT_FOUND` (`0x8000000C`, decimal `-2147483636`) é resposta **SEMÂNTICA LEGÍTIMA** da DLL para IDs >1M (mesas/gateways/RLP B3). Pipeline **DEVE** preencher `buy_agent_name`/`sell_agent_name` com fallback string (ex.: `"UNKNOWN_<id>"`) — **JAMAIS NULL silencioso** no parquet.

### Regras concretas

1. **Sentinel é dado, não erro** — não logar como `ERROR` / não bloquear pipeline / não kill thread. Counter dedicado: `agent_resolver.sentinel_skips_total`.
2. **Fallback obrigatório** — quando `GetAgentName` retorna `NL_NOT_FOUND`, popular `buy_agent_name` / `sell_agent_name` com `f"UNKNOWN_{agent_id}"`. Preserva rastreabilidade do ID original.
3. **Cache local de fallbacks** — uma vez classificado um ID como `NL_NOT_FOUND`, cachear o nome fallback para evitar query repetida.
4. **Telemetria separada** (ver I5) — sentinel skips ≠ exceções ≠ nl_errors reais.

### Test obrigatório (CI)

```python
def test_agent_resolver_unknown_id_returns_fallback():
    result = resolve_agent_name(agent_id=2_000_000)
    assert result == "UNKNOWN_2000000"
    assert result is not None  # JAMAIS None
```

### Refs

- `docs/dll/QUIRKS.md` Q-DRIFT-34
- `src/data_downloader/dll/agent_resolver.py`

---

## I4: Trade Type Resolution

**Categoria:** metadata / trade type enum
**Origem:** Nelo Council-32 (`docs/decisions/COUNCIL-32-Nelo-agents-trade-types-2026-05-05.md`)

### Princípio

> Mapping `trade_type_id → trade_type_name` usa enum `TConnectorTradeType` (14 valores em `profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas`). IDs desconhecidos viram `f"UNKNOWN_{id}"`, **JAMAIS NULL**.

### Regras concretas

1. **Enum canônico** — fonte única de verdade é `LegacyProfitDataTypesU.pas`. Mapeamento Python em `src/data_downloader/dll/trade_types.py` espelha literalmente os 14 valores.
2. **Fallback `UNKNOWN_<id>` para IDs novos** — DLL nova pode introduzir trade_type_id 15+ sem aviso. Pipeline NÃO quebra: aceita silenciosamente e popula `trade_type_name = "UNKNOWN_<id>"`.
3. **Telemetria** — counter `trade_type_unknown_total` exposto. Se > 0 em release, abrir story para atualizar enum.
4. **`trade_type_id` SEMPRE preservado** no parquet (uint8, NOT NULL) ao lado de `trade_type_name` (string, nullable após bump v1.1.0). Consumidor downstream pode escolher qual usar.

### Test obrigatório (CI)

```python
def test_trade_type_unknown_id_returns_fallback():
    assert resolve_trade_type_name(99) == "UNKNOWN_99"
    assert resolve_trade_type_name(99) is not None
```

### Refs

- `profitdll/Exemplo Delphi/Types/LegacyProfitDataTypesU.pas` (TConnectorTradeType — 14 valores)
- `src/data_downloader/dll/trade_types.py` (mapeamento Python)
- COUNCIL-32 (Nelo)

---

## I5: Translate Failures Telemetria

**Categoria:** observability / pipeline health
**Origem:** [Q-DRIFT-34](./dll/QUIRKS.md#q-drift-34) — sentinela vs nl_errors vs exceções confundiam telemetria

### Princípio

> Counters de falha do pipeline **DEVEM** ser separados por categoria semântica. Misturar sentinela (esperada) com exceção (bug crítico) mascara incidentes.

### Regras concretas

Counters separados em `metrics/`:

| Counter | Esperado em produção | Sintoma se elevado |
|---------|----------------------|---------------------|
| `translate.sentinel_skips_total` | ~0.1% dos trades | Nada — comportamento documentado (Q-DRIFT-34) |
| `translate.nl_errors_total` | ~0% (tolerância < 1%) | DLL devolvendo NL_* inesperado — abrir story |
| `translate.exceptions_total` | **0** | Bug em código de produção — bloquear release |
| `agent_resolver.sentinel_skips_total` | ~5% (IDs >1M) | Normal — Q-DRIFT-34 |
| `agent_resolver.exceptions_total` | **0** | Bug — bloquear release |
| `trade_type_unknown_total` | 0 | DLL nova introduziu trade_type_id — atualizar enum (I4) |
| `volume_gap_detected_total` | 0 | I2 violado — replay automático ativado |

### Test obrigatório (CI)

```python
def test_metrics_separate_sentinel_from_exceptions():
    metrics = run_smoke_real(symbol="WDOFUT", days=1).metrics
    assert metrics["translate.exceptions_total"] == 0
    assert metrics["agent_resolver.exceptions_total"] == 0
    # Sentinel é esperado, não falha:
    assert metrics["agent_resolver.sentinel_skips_total"] >= 0
```

### Refs

- `docs/dll/QUIRKS.md` Q-DRIFT-34
- `src/data_downloader/metrics/counters.py` (a auditar pós Story 1.7g)

---

## I6: GetHistoryTrades Window Split

**Categoria:** download flow / history window
**Origem:** [Q-DRIFT-37](./dll/QUIRKS.md#q-drift-37) (volume gap) + [Q-DRIFT-31](./dll/QUIRKS.md#q-drift-31) (limite ~5d WDO)
**Status:** PROVISÓRIA — confirmar com Nelo Council-38 (download flow audit)

### Princípio

> Janela `GetHistoryTrades` **DEVE** ser splitted em chamadas diárias se o servidor Nelogica não garantir entrega completa de janela longa. Ou seja: **NÃO assumir** que "5 dias que cabem" entregam 5 dias completos.

### Regras concretas (provisórias até Nelo Council-38)

1. **Default conservador:** janela > 1 dia útil splittada em chamadas de 1 dia útil + agregação cliente-side. Aceita custo de N chamadas seriais em troca de garantia de volume.
2. **Override explícito:** flag CLI `--max-window-days N` permite janela maior se operador validou empiricamente para o símbolo específico.
3. **Cross-check sempre** — independentemente do tamanho da janela, I2 (Volume Completeness) é checada após cada chamada.
4. **Logs por chunk** — cada chunk diário registra: `dt_start`, `dt_end`, `trades_count`, `last_trade_ts`, `last_packet_received`. Permite reconstrução pos-mortem.

### Decisão pendente

Nelo Council-38 vai medir empiricamente:
- Janela 1d vs 2d vs 3d vs 4d vs 5d para WDOFUT/WINFUT.
- Identificar onde curva trades-count quebra.
- Decidir definitivamente entre "split obrigatório" vs "limite ajustado".

Após Nelo Council-38, esta seção será atualizada de **PROVISÓRIA** para **ACCEPTED**.

### Refs

- `docs/dll/QUIRKS.md` Q-DRIFT-37, Q-DRIFT-31
- COUNCIL-38 (Nelo — download flow audit, em redação)

---

## CI checks recomendados (resumo)

Tooling DEVE rodar os seguintes checks em CI/CD para enforçar invariantes:

| Check | Invariante | Tool | Quebra build? |
|-------|-----------|------|---------------|
| `tests/unit/test_storage_schema.py::test_writer_raises_on_missing_schema_field` | I1 | pytest | YES |
| `tests/integration/test_volume_baseline.py::test_volume_baseline_per_day_minimum` | I2 | pytest (smoke real) | YES |
| `tests/unit/test_agent_resolver.py::test_agent_resolver_unknown_id_returns_fallback` | I3 | pytest | YES |
| `tests/unit/test_trade_types.py::test_trade_type_unknown_id_returns_fallback` | I4 | pytest | YES |
| `tests/integration/test_metrics_separation.py::test_metrics_separate_sentinel_from_exceptions` | I5 | pytest (smoke real) | YES |
| `storage/lint_schema_field_count.py` | I1 (regression) | custom lint | YES |
| Counter alarming (Prometheus): `volume_gap_detected_total > 0` | I2 (runtime) | alertmanager | NO (alerta, não bloqueia) |
| Counter alarming: `translate.exceptions_total > 0` | I5 (runtime) | alertmanager | NO (alerta) |

---

## Tables — Catálogo SQLite (clarificação Sol Wave 2)

**Origem da confusão:** v1.1.0 master plan (`docs/stories/v1.1.0-master-plan.md` L25/L53) cita "tabela `dll_companions` purpose vs `dll_session_log`" como concern Sol. Auditoria 2026-05-06 confirmou: **NENHUMA das duas é tabela SQLite.** Esta seção encerra a ambiguidade.

### Tabelas reais (catálogo SQLite — `data/_internal/catalog.db`)

> v1.0.x usava `data/history/catalog.db` — migração silenciosa em `Catalog.__post_init__` (ver ADR-024 e `_migrate_legacy_catalog_path` em `storage/catalog.py:288`).

Fonte canônica: `src/data_downloader/storage/catalog.py` (DDL `_DDL_V1_0_0` + `_DDL_V1_1_0_DELTAS`). Se você editou o DDL, atualize esta seção.

| Tabela | Purpose | Lifecycle | CHECK / UNIQUE |
|--------|---------|-----------|----------------|
| `_schema_meta` | KV store de metadata (`catalog_version`, `parquet_schema_min_supported`, `created_at`) | UPSERT por `key` | PK `key` |
| `downloads` | Job tracking — uma linha por requisição de download | INSERT no register, UPDATE per progress | CHECK `status IN (pending, in_progress, completed, failed, partial, cancelled)` |
| `partitions` | Catálogo de Parquet files mensais | UPSERT por `partition_path` | CHECK `month BETWEEN 1 AND 12`, `row_count >= 0`, `file_size_bytes > 0`; FK `job_id → downloads` |
| `gaps` | Janelas sem trades (replay candidates) | UPSERT por triple-key | PK `(symbol, gap_start, gap_end)`; CHECK `reason IN (no_trades, holiday, weekend, failed_chunk, unknown, outside_vigency)` |
| `contracts` | Vigência de contratos (root + code) | UPSERT por `(symbol_root, contract_code)` | PK + CHECK `validation_source IN (hypothesized, nelogica_official, dll_probe, b3_calendar, manual)` |
| `_checksum_cache` | Cache de SHA256 indexado por `(size, mtime_ns)` (INTEGRITY.md §3) | UPSERT, CASCADE delete via `partitions` FK | PK `partition_path`; FK CASCADE |
| `_pending_commits` | Two-phase commit emulation (AC13) — pending writes | INSERT na fase 1, DELETE na fase 3 | PK `partition_path`; FK `job_id → downloads` |
| `_migration_log` | Checkpoint resumível do framework de migration v1.1.0 | INSERT per run/partition pair | PK `(run_id, partition_path)`; CHECK `status IN (pending, migrated, rolled_back, failed)` |

### `dll_companions` — NÃO é tabela

`dll_companions` é o **nome do verificador runtime de companion files do .dll** (DLLs/recursos siblings que `ProfitDLL.dll` requer no diretório):

- Implementado em `scripts/verify-dll-companions.py` (carregado dinamicamente em `src/data_downloader/dll/wrapper.py::_load_verify_dll_companions`).
- Função: `verify_dll_companions(dll_path) -> list[str]` — retorna lista de filenames esperados que estão **ausentes** no diretório do .dll.
- Chamado **ANTES** de `WinDLL(path)` (Story 1.2 AC12) e por `aiox doctor` / `cli.py::_check_dll_companions` (`src/data_downloader/cli.py` L1704).
- Sem persistência. Nenhum SQLite envolvido. Resultado é log/exit-code, não estado.

Ref: `docs/stories/1.2.story.md` L116, `docs/dll/PROFITDLL_KNOWLEDGE.md` L374, `docs/adr/ADR-018-frozen-mode-boundary.md` L24.

### `dll_session_log` — NÃO existe

Exaustivamente buscado em todo o repositório (2026-05-06) — **`dll_session_log` não existe**: nem como tabela SQLite, nem como módulo Python, nem como spec em ADR/story. A única menção é o próprio brief Wave 2 que motivou esta clarificação (master plan L53). Provavelmente sintetizado por engano de "dll_companions" + alguma noção genérica de "session log".

Telemetria de sessão DLL (Q-AMB-02, license_status, dll_version per init) hoje é serviço de logs estruturado (`src/data_downloader/observability/logging_config.py` + `metrics/counters.py`), não tabela SQLite.

### Decisão

**Não há refactor pendente** — o concern Sol Wave 2 era de documentação, não de código. Esta seção é o entregável.

Se no futuro precisar persistir telemetria DLL em SQLite (Story 2.x), criar `dll_sessions` (plural, append-only) com:
- `session_id` (PK), `started_at`, `ended_at`, `dll_version`, `license_status`, `init_args_hash`.
- WORM (NEVER UPDATE) — append-only.
- ADR formal + bump `CATALOG_VERSION` (atualmente 1.1.0).

Não faça isso para v1.1.0.

---

## Manutenção

- **Adicionar invariante:** edit aqui + ADR formal Aria + atualizar CI checks recomendados.
- **Mudar invariante existente:** EXIGE bump major + ADR + comunicação a Morgan/Aria + janela de manutenção. Invariantes são contrato perpétuo (Constitution Art. V).
- **Refutar invariante:** EXIGE evidência empírica reproduzível + council Sol + Aria + Quinn.

---

## Refs cruzadas

- `docs/dll/QUIRKS.md` — catálogo de quirks (Q-DRIFT-36/37 são origem direta de I1/I2).
- `docs/dll/PROFITDLL_KNOWLEDGE.md` Quick Reference — regras 6/7/8 derivam destas invariantes.
- `docs/storage/SCHEMA.md` — schema canônico parquet.
- `docs/decisions/COUNCIL-40-Sol-invariantes-2026-05-05.md` — relatório council de criação deste doc.
- ADR-019 (Aria) — Schema-as-Contract formal.
- ADR-020 (Aria) — Volume Completeness formal.

— Sol, custodiando os princípios 💾
