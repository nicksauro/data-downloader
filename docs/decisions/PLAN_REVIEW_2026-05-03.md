# Plan Review — Revisão Multi-Agente do Planejamento Inicial

**Data:** 2026-05-03
**Convocada por:** aiox-master (a pedido do usuário)
**Participantes:** Nelo 🗝️, Sol 💾, Aria 🏛️, Quinn 🧪, Pyro ⚡, Uma 🎨, Felix 🖼️, Morgan 📋, Gage ⚙️
**Status:** consolidação de 9 críticas independentes
**Veredicto consolidado:** ⚠️ **NÃO INICIAR Story 1.1 ATÉ ADENDOS APLICADOS**

---

## 1. Sumário executivo

O planejamento inicial proposto pelo aiox-master é **sólido na espinha** (squad, governança, ADRs seed, Epic 1) — mas tem **buracos críticos** que **3 agentes detectaram convergentemente** e **6 agentes detectaram parcialmente**.

**Pontos de convergência forte:**
1. Schema/AC sub-especificados em Stories 1.2/1.3/1.4/1.7 (Nelo + Sol + Quinn).
2. Ferramentas de QA não existem como código mas são exigidas no gate (Quinn CRITICAL + Sol + Aria).
3. ~6 ADRs novos faltando (Aria) + microcopy catalog + perf baselines (Uma + Pyro).
4. Infra básica (git init, DLL distribution, build determinístico) ausente (Gage CRITICAL + Morgan).
5. Story 1.7 sub-estimada e mistura responsabilidades (Morgan + Quinn).

---

## 2. Findings consolidados por severidade

### 🔴 CRITICAL (bloqueiam início do Epic 1)

| # | Finding | Origem | Dono | Resolução |
|---|---------|--------|------|-----------|
| C1 | **Repo não é git** — R12 inoperante até `git init` + branch protection | Gage | Gage | Story **0.1** Environment Bootstrap |
| C2 | **DLL no repo** — sem decisão entre commitar (EULA?) vs gitignorar + bootstrap script | Gage | Aria + Nelo legal | **ADR-008** DLL Distribution Strategy |
| C3 | **Build não-determinístico** (R19) — PyInstaller default viola lei | Gage | Aria | **ADR-009** Build Determinístico |
| C4 | **`Sol *integrity-check` e `Quinn *data-validate` não existem como código** mas são exigidos no gate de 1.7 — circularidade | Quinn | Sol + Quinn | Mover Story 2.1 (validators) para **dentro do Epic 1** OU declarar scripts ad-hoc com protocolo escrito |
| C5 | **Smoke gated por env nunca roda em CI** — gate de Epic 1 vira honor system | Quinn | Quinn + Gage | `docs/qa/SMOKE_PROTOCOL.md` + checklist obrigatório com evidência (hash Parquet + log salvo) |
| C6 | **INV-1 (callback não chama DLL) sem teste explícito** que monitore `mock_calls` durante callback | Quinn | Quinn | AC novo em Story 1.2 |
| C7 | **Story 1.2 AC2/AC4 erradas**: `DLLInitializeMarketLogin` exige **11 callback slots fixos**; passar `None` em slots subsequentes corrompe `SetHistoryTradeCallback` posterior (Quirk Q11-E) | Nelo | Nelo + Dex | Reescrever AC2/AC4 |
| C8 | **Sequência de states incompleta** em Story 1.2 AC5 — falta ROTEAMENTO e ambiguidade `MARKET_WAITING=2 vs MARKET_CONNECTED=4` (Q-AMB-01) | Nelo | Nelo | Reescrever AC5 |
| C9 | **Multi-symbol viola SQLite WAL** — N processos = 1 writer ativo permitido + readers; spec atual gera `SQLITE_BUSY` | Aria | Aria | **ADR-013** Multiprocess Catalog Coordination |
| C10 | **Story 1.7 sub-estimada** (3d / 8 tasks / 30 subtasks) viola R20; decompor em 1.7a + 1.7b + 1.8 | Morgan | Morgan | Decomposição obrigatória |

### 🟠 HIGH (bloqueiam fechamento do Epic 1)

| # | Finding | Origem | Dono |
|---|---------|--------|------|
| H1 | **Schema v1.0.0 incompleto**: faltam `side`, `ingestion_ts_ns` (obrigatório), `chunk_id`, `dll_version` | Sol + Gage | Sol |
| H2 | **Dedup quebrado quando `trade_id` NULL** — `hash(price, qty)` insuficiente; precisa `sequence_within_ns` | Sol | Sol |
| H3 | **Targets de performance V1 são palpites** — nenhum bench rodou. Inserir Story 1.4.5 synthetic baselines | Pyro | Pyro |
| H4 | **`dll_queue=10000` = 100ms buffer** — Windows Defender / GC / page fault podem pausar 500ms-3s. Pergunta crítica: DLL drop-on-block? | Pyro | Nelo (responde) + Pyro (mede) |
| H5 | **Snappy escolhido sem matriz** — ZSTD-1 pode ser Pareto-dominante | Pyro | Pyro + Sol |
| H6 | **Append+dedup re-escreve arquivo a cada chunk → O(n²)** | Quinn | Sol |
| H7 | **`fsync(parent_dir)` faltando** em Story 1.4 atomic write | Quinn | Sol + Dex |
| H8 | **Story 1.7 AC6 cache hit ambíguo** — confunde "partição existe" com "range coberto" | Quinn | Dex |
| H9 | **`download(stream=True/False) → DownloadResult \| Iterator` viola Liskov** (ADR-007) — substituir por `DownloadHandle` com `cancel()` | Aria + Felix | Aria → **ADR-007a** |
| H10 | **`cancel()` não existe em public_api** — UI mente para usuário ao cancelar | Felix + Uma | Aria + Dex |
| H11 | **Race no shutdown ADR-005** — progress 100% pode chegar antes do último `HistoryTradeCallback` ser drenado | Aria | Aria |
| H12 | **Story 1.6 dep faltando** — `validate` (AC6) precisa de DLL inicializada (Story 1.2) e primitive (Story 1.3) | Nelo + Morgan | Morgan |
| H13 | **R17 violada** — Dex inventaria microcopy CLI Rich em Story 1.7 sem Uma como reviewer | Uma | Uma |
| H14 | **`MICROCOPY_CATALOG.md` não existe** — mapa exaustivo NL_* → mensagem humana | Uma | Uma |
| H15 | **Ctrl+C cancel sem AC** em Story 1.7 — graceful shutdown não definido | Uma + Quinn | Dex |
| H16 | **Schema migration framework faltando** — sem isso R4 é teatro | Sol | Sol |
| H17 | **Pre-push hook não versionado** — squad inteiro sem proteção R18 | Gage | Gage |
| H18 | **Branch model não definido** — Felix (Epic 3) e Dex (Epic 2) em paralelo sem isolamento | Gage | Gage + Morgan |
| H19 | **`dll_version` no Parquet — quem coleta** via `GetDLLVersion`? Não está em nenhuma story | Gage + Sol | Dex |
| H20 | **Multi-symbol Windows spawn = 2.7-10s overhead/subprocess** — multi-symbol pode não compensar para downloads curtos | Pyro | Aria + Pyro (bench) |
| H21 | **Sem `Protocol` em fronteiras** — refator quebra tudo | Aria | Aria |
| H22 | **`structlog` em hot path = 50-150% de 1 core só logando** | Pyro | Aria → política `HOT_PATH_RULES.md` |
| H23 | **PyInstaller `--onefile` é armadilha** — startup 3-5s, AV flag, paths quebram. Mudar para `--onedir` | Felix | Felix → ADR-003 amendment |

### 🟡 MEDIUM

| # | Finding | Origem | Dono |
|---|---------|--------|------|
| M1 | Templates de output `*audit-wrapper`, `*audit-storage-pr`, `*review-design` não existem | Quinn | Quinn |
| M2 | WAIVED não tem mecânica operacional (`docs/qa/WAIVERS/{story}.md`) | Quinn | Quinn |
| M3 | CodeRabbit referenciado em `agents/dev.md` mas não adaptado nem em stories | Gage + Quinn | Gage decide adoption (Story 0.4) |
| M4 | `_meta/checksum.json` separado pode dessincronizar; mover para metadata Parquet + redundância no catálogo | Sol | Sol |
| M5 | `os.replace` em Windows falha com handle aberto (DuckDB reader) | Sol | Sol + Aria |
| M6 | SQLite PRAGMAs `mmap=256MB + cache=200MB` estouram RAM em laptop modesto | Pyro | Sol → reduzir defaults |
| M7 | `parse_brt_timestamp` aceita 2 formatos sem normalização canônica documentada — risco silencioso de dedup quebrar | Quinn + Nelo | Nelo + Dex |
| M8 | CLI sem suporte a `NO_COLOR`, fallback ASCII, paleta dark mode estendida | Uma | Uma |
| M9 | QSS + QFileDialog nativo Windows = inconsistência visual; flag `DontUseNativeDialog` precisa documentação | Felix | Felix + Uma |
| M10 | Atalhos Esc/F5 problemáticos — context-aware ou Ctrl+R | Felix + Uma | Uma decide |
| M11 | `ui_progress_queue` drop-oldest sem métrica `ui_progress_dropped_count` exposta | Felix | Pyro |
| M12 | EPIC-2/3/4 sem doc IN/OUT — risco de scope creep contínuo | Morgan | Morgan |
| M13 | Stories 1.2-1.5 estimate sem buffer de auditoria (Nelo/Sol/Aria audit pode somar 0.5d) | Morgan | Morgan |
| M14 | DoD do Epic 1 ponto 8 ("reproduzível por outro contribuidor") vago — squad é de agentes | Morgan | Morgan |
| M15 | DLL não é idempotente em `init→finalize→init` na mesma sessão Python — testes smoke em sequência vão falhar misteriosamente | Nelo | Quinn (fixture session-scoped) |
| M16 | `download_continuous` (rollover) muda `symbol` no meio — UI mostra contrato errado. Adicionar `current_contract` em `DownloadProgress` | Felix | Aria |
| M17 | DST: B3 não observa desde 2019; histórico anterior tem ambiguidade no fuso. Limitar smoke a >= 2020 | Nelo | Sol |

### 🟢 LOW

| # | Finding | Origem | Dono |
|---|---------|--------|------|
| L1 | Story 1.1 — adicionar `pytest --collect-only` retorna 0 erros (garante imports) | Quinn | Dex |
| L2 | Padrão de logger: keys obrigatórias (correlation_id = job_id) | Quinn | Aria |
| L3 | `bench_boot_cleanup` para 10k+ partições — cleanup escopado a job ativo | Pyro | Sol |
| L4 | Auto-updater Epic 4 — escolher tech (tufup vs alternativas) | Felix | Aria → **ADR-011** |
| L5 | Code signing Windows ($300/ano EV cert) | Gage | Aria → **ADR-010** |
| L6 | Reservar slot em Epic 3 para `pytest-qt` setup | Felix | Morgan |
| L7 | Story 0.4 — CodeRabbit adoption decision (manter/adaptar/remover) | Gage | Gage |

---

## 3. Stories adicionais a criar

| ID | Título | Owner | Estimativa | Bloqueia |
|----|--------|-------|------------|----------|
| **0.0** | Sol cria SCHEMA.md + CONTRACTS.md + INTEGRITY.md (docs canônicos) | Sol | 1d | 1.3, 1.4, 1.6 |
| **0.1** | Environment Bootstrap (git init, .gitignore, branch protection, primeiro commit) | Gage | 0.5d | 1.1 |
| **0.2** | Pre-commit Framework (`.pre-commit-config.yaml` versionado) | Gage | 0.5d | 1.1 |
| **0.3** | UX Foundation (Uma cria `CLI_PATTERNS.md` + `MICROCOPY_CATALOG.md`) | Uma | 1d | 1.7 |
| **0.4** | CodeRabbit adoption decision | Gage + Quinn | 0.5d | (não bloqueia, mas remove ambiguidade) |
| **1.4.5** | Synthetic perf baselines (bench_parquet_write, bench_dedup, bench_callback_to_disk com mock DLL) | Pyro | 1d | 1.7 (gate honesto) |
| **1.5b** | `read_continuous` + queries canônicas DuckDB + property tests rollover | Sol + Dex | 1d | gate Epic 1 |
| **1.7a** | chunker + retry + orchestrator core (era 1.7 Tasks 1-3) | Dex | 2d | 1.7b |
| **1.7b** | CLI typer + public_api mínima + smoke MVP gate (era 1.7 Tasks 4-6, 8) | Dex | 2d | 1.8 |
| **1.8** | Pyro baselines reais + regression budgets (registra após smoke verde) | Pyro | 1d | gate Epic 1 |
| **2.1 (movida de Epic 2)** | Data integrity validator como código (`Sol *integrity-check`, `Quinn *data-validate`) | Sol + Quinn | 2d | 1.7b smoke gate |

**Novo total Epic 1:** 13d → **20d** estimados (15% buffer honesto > 30% surpresa garantida).

---

## 4. ADRs a criar/modificar (Aria)

| ADR | Título | Status proposto | Bloqueia |
|-----|--------|-----------------|----------|
| ADR-007a | Public API redesign — `DownloadHandle` com `cancel()` (supersede ADR-007) | proposed → accept | Felix Epic 3 |
| ADR-008 | DLL Distribution Strategy (commit vs gitignore + bootstrap script vs LFS) | proposed | Story 0.1 |
| ADR-009 | Build Determinístico (PYTHONHASHSEED, SOURCE_DATE_EPOCH, lockfile, container) | proposed | release V1 |
| ADR-010 | Logging strategy (structlog format, contextvars, redaction, hot-path rules) | proposed | Story 1.2 |
| ADR-011 | Exception hierarchy & error propagation (internals → public_api → UI) | proposed | Story 1.7b |
| ADR-012 | Configuration system (env vs TOML, precedência, schema Pydantic) | proposed | Story 1.1 amendment |
| ADR-013 | Runtime observability (counters, gauges, histograms, métricas exportadas) | proposed | Epic 2 |
| ADR-014 | Test strategy (mock DLL, fake clock, fixtures, layers) | proposed | Story 1.2 |
| ADR-015 | Multiprocess catalog coordination (broker vs sharded vs retry) | proposed | Epic 4 |
| ADR-016 | Code signing & SmartScreen (Windows EV cert) | proposed | release V1 |
| ADR-017 | Auto-updater (tufup vs alternativas) | proposed | Epic 4 |
| Amendment ADR-003 | Packaging: trocar `--onefile` por `--onedir`; flag `DontUseNativeDialog` | accepted | Felix Epic 3 |
| Amendment ADR-005 | State machine de shutdown (`Running→DrainingDLL→DrainingWrite→Committed`) + INV-11 | accepted | Story 1.7a |
| Amendment ROLES.md | Ownership de `cli.py`: Dex (engine) + Uma (microcopy/layout) | accepted | Story 0.3 |

---

## 5. Modificações em arquivos existentes

### MANIFEST.md
- Adicionar **R21**: hot-path logging — eventos per-trade NÃO logados; per-chunk OK.
- Adicionar nota em R3: "1 init de DLL por processo Python (não-idempotente em init→finalize→init)".

### ARCHITECTURE.md
- Adicionar invariantes:
  - **INV-11**: OrchestratorThread ≠ IngestorThread ≠ ConnectorThread (separação física obrigatória).
  - **INV-12**: "fim de chunk" só declarado quando `dll_queue` vazia AND `write_queue` vazia AND último write commitou no SQLite.
- Atualizar §2.4 multi-symbol com referência a ADR-015 (em vez de mão-baixa).
- Adicionar §6 — `data_downloader/contracts/` com Protocols por fronteira.

### Story 1.1
- AC11: validar `pytest --collect-only` retorna 0 erros.
- AC12: capturar `dll_version` via `GetDLLVersion` em build E runtime (coordenar com Sol).

### Story 1.2
- Reescrever AC2 (11 callback slots).
- Reescrever AC5 (sequência completa de states + decisão Q-AMB-01).
- Adicionar AC novos: `SetEnabledLogToDebug(0)`, validação companions DLLs/.dat, fallback `Finalize()` para Q-AMB-02, fixture session-scoped para evitar re-init issue, teste explícito `mock_calls == []` durante callback.

### Story 1.3
- AC1: decidir explicitamente V1 vs V2; se V2, dizer que `TranslateTrade` é chamado **fora** do callback (memcpy do payload bruto na fila).
- AC6+1.7 AC7: unificar política do quirk 99% reconnect.

### Story 1.4
- Bumpa schema com campos novos (`side`, `ingestion_ts_ns`, `chunk_id`, `dll_version`).
- Reformular dedup key (Sol `sequence_within_ns`).
- AC novo: `fsync(parent_dir_fd)` pós-replace.
- AC novo: threshold de rewrite vs new file (evitar O(n²) append).
- Remover AC10 (round-trip property) → vai para Story 2.1.

### Story 1.5
- AC11: reconcile automático no startup do orchestrator.
- AC12: WAL checkpoint após cada `register_partition`.
- AC13: two-phase commit emulado (catalog `pending_commit` → replace → catalog `committed`).

### Story 1.6
- Atualizar `depends_on` para `[1.2, 1.3, 1.5]`.
- OU dividir em **1.6a** (seed sem probe, dep 1.5) + **1.6b** (probe via DLL, dep 1.2 + 1.3 + 1.5).

### Story 1.7 (será decomposta em 1.7a + 1.7b + 1.8)
- Refinar AC6 cache hit (range coverage real).
- AC novo: Ctrl+C graceful shutdown (Uma microcopy + Dex impl).
- AC novo: AC11/12/13 da Uma (microcopy 99% reconnect, catálogo de erros).
- Remover AC10 baseline → vai para Story 1.8.
- Adicionar Uma como reviewer obrigatório.

### Epic 1 (epic doc)
- Reformular DoD ponto 8: "smoke rodável apenas com README + .env + ProfitDLL.dll, validado em VM Windows limpa OU container".
- Adicionar 3 riscos: schema drift entre 1.4↔1.7, MARKET_WAITING quirk, data sample em feriado/fim-semana.
- Atualizar lista de stories (12 stories agora, não 7).
- Atualizar gate: depende de Story 0.0+0.1+0.2+0.3+1.0..1.6+1.7a+1.7b+1.8+2.1.

---

## 6. Plano de ação proposto

### Fase A — Adendos pré-implementação (~5 dias estimados)

| Sequência | Owner | Entrega |
|-----------|-------|---------|
| 1 | Aria | ADR-007a, ADR-008..017 (esqueletos pelo menos), amendments ADR-003/005, ROLES |
| 2 (paralelo) | Sol | Story 0.0 — SCHEMA.md, CONTRACTS.md, INTEGRITY.md |
| 3 (paralelo) | Uma | Story 0.3 — CLI_PATTERNS.md, MICROCOPY_CATALOG.md |
| 4 (paralelo) | Gage | Story 0.1 (git init, branch protection), Story 0.2 (pre-commit), Story 0.4 (CodeRabbit decision) |
| 5 | Quinn | Templates de output `AUDIT_*.md`, `WAIVERS/` mecânica, `SMOKE_PROTOCOL.md` |
| 6 | Morgan | Decompor 1.7→1.7a+1.7b+1.8; criar Story 1.4.5, 1.5b, 2.1; corrigir deps; criar EPIC-2/3/4 docs IN/OUT mínimos |
| 7 | Pyro | Especificar 9 benchmarks em `benchmarks/` (esqueletos); definir regression budgets |
| 8 | Nelo | Atualizar Story 1.2 (AC corretos), responder pergunta de Pyro (drop-on-block?) |
| 9 | Felix | Validar PyInstaller spec com Gage; documentar `DontUseNativeDialog`; revisar atalhos com Uma |

### Fase B — Re-validação plano por Morgan
- Morgan `*validate-story` 10pts em **todas** as 12 stories (incluindo as novas 0.x e 1.4.5/1.5b/1.7a/1.7b/1.8/2.1).
- Cada story precisa GO antes de Dex iniciar.

### Fase C — Implementação
- Apenas após Morgan dar GO em todas.
- Sequência de execução otimizada (Aria pode propor wave analysis com `*waves` se quiser).

---

## 7. Decisão a confirmar com o usuário

O squad recomenda **NÃO INICIAR Story 1.1 imediatamente**. Há 3 caminhos:

### Opção A — Aplicar TODOS os adendos (recomendação consolidada)
- Investimento: ~5 dias só de adendos antes de qualquer código.
- Resultado: foundation realmente sólida; Quinn não bloqueia gates por falta de ferramenta.
- Custo: atraso de 1 semana em "primeira linha de código".

### Opção B — Aplicar SÓ os CRITICAL (C1..C10)
- Investimento: ~2-3 dias.
- Resultado: bloqueadores eliminados; HIGH viram débito tracked.
- Custo: alguns débitos vão amadurecer durante implementação.

### Opção C — Implementar 1.1 com plano atual e aplicar adendos em paralelo
- Investimento: 0 dias adicionais (paralelismo).
- Resultado: começa logo, mas Story 1.1 pode precisar refazer (ex: AC11 dll_version exige Sol schema antes).
- Custo: retrabalho garantido em pelo menos 2 stories.

**Recomendação do squad consolidada:** **Opção A** (Morgan veta Opção C; Quinn bloqueia Opção C; Gage bloqueia início sem Story 0.1).

---

## 8. Pergunta pendente para o usuário

Qual opção (A/B/C) você autoriza?

— Squad data-downloader, debate concluído em 2026-05-03
