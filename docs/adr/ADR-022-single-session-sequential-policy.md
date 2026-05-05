# ADR-022 — Single-Session Sequential Download Policy

> **Nota de numeração:** este ADR foi originalmente solicitado como "ADR-016" na missão de revogação do ADR-015. Como ID 016 já está ocupado por `ADR-016-code-signing.md` e os IDs 017-021 estão alocados/reservados (ver índice em `docs/adr/README.md` e COUNCIL-39 §I-N10), Aria — autoridade ADR exclusiva (MANIFEST R15) — numerou na sequência correta disponível: **ADR-022**. Escopo e decisão preservados conforme briefing.

- **Status:** Accepted
- **Aceito em:** 2026-05-05 — Aria
- **Data:** 2026-05-05
- **Autor:** 🏛️ Aria (architect)
- **Consultados (mini-council autônomo 2026-05-05):** 🗝️ Nelo (DLL/licensing), 💾 Sol (storage/catalog), ⚡ Pyro (perf), 📋 Pax (PO/stories deprecated em paralelo)
- **Confirmado empiricamente por:** Pichau (dono do produto, autoridade máxima) — 2026-05-05
- **Supersedes:** **ADR-015** (Multiprocess catalog coordination — broker process)
- **Related:** ADR-002 (storage), ADR-005 (thread model), Q17-OPEN→CLOSED em `docs/dll/QUIRKS.md`, COUNCIL-25 (broker impl prep — agora histórico), `scripts/probe_multi_process_license.py`

---

## Contexto

Em 2026-05-05, o dono do produto confirmou (após pergunta direta da arquitetura, ratificada pela mini-council de release readiness COUNCIL-36/39):

> **"A licença Nelogica é single-session — não permite 2 instâncias conectadas simultaneamente com a mesma chave."**

Esta é uma restrição **comercial/contratual** enforced no servidor de licenciamento da Nelogica, não uma característica do binário DLL local. A segunda tentativa de login com a mesma chave recebe erro de licença ocupada e é derrubada — independente de processo, thread, máquina ou ordem temporal de conexão.

Isto **falsifica diretamente a Hipótese A** sobre a qual o ADR-015 (broker process + N workers DLL paralelos) foi construído. A Hipótese A assumia que 1 chave = N conexões simultâneas (1 por processo, com isolamento de DLL). Era plausível com base na restrição técnica documentada "1 DLL = 1 processo" (Q11-E), mas **nunca havia sido validada com o vendor**. EPIC-4 §Risks havia anotado a pendência operacional ("Morgan + Nelo confirmam com Nelogica antes de Story 4.1 começar"), porém Story 4.1 avançou no desenho do broker antes da resposta — gerando código (`src/data_downloader/orchestrator/broker/`) e WAIVER de smoke real (`docs/qa/WAIVERS/4.1-real-smoke-deferred-2026-05-04.md`).

Com a falsificação, a única topologia legalmente operável é **1 processo + 1 DLL conectada por vez**. Toda decisão de multi-symbol em V1.0.0+ deve respeitar esse invariante.

Q17 (Q-DRIFT-17) em `docs/dll/QUIRKS.md`: status muda de **OPEN** para **CLOSED — Hipótese B confirmada**.

---

## Decisão

**Multi-symbol downloads são executados SERIALMENTE em 1 (um) único processo, iterando sobre a lista de símbolos solicitados.**

### Forma canônica

```python
# orchestrator/multi_symbol.py (semântica — não obriga arquivo novo se loop fica em cli.py)
def download_multi(symbols: list[str], window: DateWindow, ...) -> list[ChunkResult]:
    """Download serial multi-symbol — 1 DLL, 1 conexão, N símbolos em sequência."""
    results: list[ChunkResult] = []
    for symbol in symbols:
        # download_chunk já é per-symbol — semântica idempotente preservada
        results.append(download_chunk(symbol=symbol, window=window, ...))
    return results
```

### CLI

- `data-downloader download --symbol WDOJ26 --symbol WINH26 --start ... --end ...`
  itera sequencialmente, **uma flag `--symbol` por símbolo**.
- `--parallel N` / `--workers N` / qualquer flag que prometa concorrência inter-symbol **NÃO existe** e **NÃO deve ser aceita**. Se já existir no código (legado da Story 4.1), deve ser removida ou mapeada a `1` com warning de depreciação. (Owner: @dev na limpeza pós-revogação.)

### Public API (Epic 4)

- `DownloadHandle` permanece per-symbol. Multi-symbol é orquestração na camada cliente (loop do consumidor) ou utilitário fino do public_api que internaliza o `for`.
- Não introduzir abstrações de "WorkerPool" / "BrokerHandle" / "MultiSymbolHandle" que sugiram paralelismo. Nomes devem refletir a serialidade real (ex.: `download_symbols_sequential`, ou simplesmente um for explícito documentado).

### Catalog & storage

- Catálogo SQLite permanece **single-writer** (1 processo, 1 conn write). Sem broker, sem `multiprocessing.Queue`, sem ACK protocol. WAL mode mantido apenas para reads concorrentes locais (DuckDB UI lendo enquanto download roda) — concorrência intra-processo, não inter-processo.
- INV-6 (catálogo é única fonte de verdade) preservada **trivialmente**: só existe um writer.

### Thread model

- ADR-005 (5 threads + 3 filas bounded) **não muda**. As threads são intra-processo (DLL callback ↔ Translator ↔ Ingestor ↔ Writer ↔ Coordinator). Multi-symbol não altera essa topologia — apenas re-executa o pipeline N vezes em sequência.

---

## Alternativas Consideradas

| # | Alternativa | Status | Por que rejeitada |
|---|-------------|--------|-------------------|
| **A** | **Multi-process broker (ADR-015 original)** — N processos, 1 DLL cada, mp.Queue + ACK serializando catalog writes | **REJECTED por restrição comercial** | Hipótese A falsificada empiricamente em 2026-05-05: licença Nelogica é single-session. N conexões simultâneas com a mesma chave é violação contratual e tecnicamente bloqueado pelo servidor de licenciamento. |
| **B** | **1 processo + DLL única + subscribe múltiplo + IngestorThread routing por símbolo** — em vez de loop sequencial, manter 1 conexão e subscrever a vários tickers em paralelo, demuxando trades por `symbol` no callback | **REJECTED como over-engineering** | (1) DLL throughput total é fixo (single-session é o gargalo real, não o loop Python); paralelismo intra-conexão é marginal. (2) Refator significativo: dispatch table por símbolo, particionamento de buffers, complexidade de error-handling (1 símbolo falha → derruba os outros?). (3) GetHistoryTrades é per-symbol e per-window com limite de 5 dias (Q12-E); subscrever N tickers em paralelo não acelera a query histórica, que é a parte cara. (4) Loop sequencial é trivial, idempotente, fácil de debugar e cobre 100% do caso de uso V1. |
| **C** | **N processos com OS-wide lock (mutex global)** garantindo serialidade entre processos | **REJECTED como equivalente pior** | Funcionalmente equivalente ao loop serial, mas com overhead de spawn (Pyro H20: 2.7-10s no Windows), debugging multi-process, e cleanup de lock órfão em crash. Pior em todas as dimensões. |
| **D** | **Romper a licença via socket proxy / hook DLL / virtualização de chave** | **REJECTED — fora do escopo legal/comercial** | Violação contratual com vendor, risco jurídico, e expectativa razoável de detecção/banimento de chave. Não considerado. |
| **E** | **Postgres ou DB cliente-servidor** (resolveria contention de catalog em multi-process) | **N/A — premissa morta** | Resolveria o problema de SQLITE_BUSY que ADR-015 atacava, mas o problema não existe mais com 1 processo. Adicionalmente: 12-factor desktop app não tolera servidor extra. |

---

## Consequências

### Positivas

- **Simplicidade radical.** Multi-symbol é `for` loop. Zero IPC, zero broker, zero ACK protocol, zero serialização inter-processo.
- **Zero código novo necessário.** `download_chunk(symbol=..., window=..., ...)` já é per-symbol e idempotente. O loop pode viver em `cli.py` ou em `orchestrator/multi_symbol.py` (decisão de @dev na limpeza), com ≤ 30 linhas Python.
- **INV-6 trivialmente preservada.** Single writer = não há contention possível.
- **Crash isolation natural.** 1 símbolo falha → próximo segue ou aborta conforme política, sem zumbis multi-process. Recovery é R5/R12 idempotente.
- **Debug simples.** Stack trace linear, logs em ordem, sem "qual worker travou" — só existe um.
- **Conformidade contratual com vendor.** Eliminamos risco de banimento de chave por uso indevido.
- **Bench / smoke real simples.** Mede `Σ(tempo_por_símbolo)` — sem ruído de spawn, fila, IPC.

### Negativas

- **Sem ganho de paralelismo entre símbolos.** Tempo total = soma dos tempos individuais. **Mitigation:** o gargalo real é a DLL (single-session enforce), não a CPU/IO Python — paralelismo seria ilusório de qualquer forma. Para usuário final, o impacto é "esperar mais", não "perder ordem de magnitude".
- **Stories 4.1 + 4.1-followup + 4.2-followup ficam deprecated.** Trabalho de design do broker (~38 testes, 5 módulos `orchestrator/broker/`, WAIVER smoke) vira código órfão. **Mitigation:** Pax cancela/reescreve as stories em paralelo a esta ADR; @dev agenda Story de limpeza para remover ou marcar dead-code do package broker.
- **EPIC-4 perde a "feature arquitetural multi-symbol".** Multi-symbol vira commodity, não diferencial. **Mitigation:** Epic 4 reposicionado pelo @pm — foco em *quais* símbolos/asset-classes (multi-asset = WIN, equities) e em *qualidade* (volume completeness ADR-020), não em *paralelismo*.
- **Expectativa de "speedup linear com N símbolos"** (se algum stakeholder mantinha) é falsa. **Mitigation:** documentar explicitamente em README + UI tooltip que multi-symbol é serial e por quê (link para ADR-022).

### Neutras

- ADR-005 (thread model intra-processo) intocado.
- ADR-002, ADR-004 (storage/partition) intocados.
- ADR-015 marcado REVOKED, preservado como histórico (governance MANIFEST R15).

---

## Implementação

Owner imediato: @dev (Dex), em coordenação com @po (Pax) para deprecation de stories.

Tasks:
1. Confirmar/criar `orchestrator/multi_symbol.py` (loop fino) ou inline em `cli.py` — decisão de @dev conforme padrão do código atual.
2. Remover ou stubar flags de paralelismo no CLI/public_api (se existem como herança de Story 4.1 incompleta).
3. Marcar `src/data_downloader/orchestrator/broker/*` como dead-code pendente de limpeza (Story 4.X-cleanup) — não importar no caminho ativo.
4. Atualizar `docs/ARCHITECTURE.md` §2.4 e Change Log para amendment 1.1.2: broker → sequential.
5. Atualizar `docs/epics/EPIC-4-multi-asset-api.md` (ownership @pm) — escopo redefinido.
6. Q17 em `docs/dll/QUIRKS.md`: status OPEN → CLOSED com referência a este ADR.
7. CLI tooltip / `--help` deixa explícito: "Símbolos são processados em sequência (single-session licensing)."

---

## Referências

- **Pichau (dono do produto), 2026-05-05** — confirmação verbal da restrição single-session da licença Nelogica.
- `docs/dll/QUIRKS.md` Q17-OPEN → CLOSED (Hipótese B confirmada).
- `docs/adr/ADR-015-multiprocess-catalog.md` — REVOKED (this supersedes).
- `scripts/probe_multi_process_license.py` — probe que validou empiricamente Hipótese B (CLOSED).
- `docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md` — preserved como histórico (decisão de implementação do broker, agora obsoleta).
- `docs/decisions/COUNCIL-36-Pax-release-blockers-2026-05-05.md` — release-blockers V1.0.0 (multi-symbol não é P0 nesse contexto pós-revogação).
- MANIFEST R15 (ADR-first), R1 (Foundation), R5 (Idempotência), R14 (Release readiness).
- ADR-005 (thread model — intra-process, intocado).
- ADR-002 (storage stack — single-writer, intocado).

---

*— Aria, autoridade ADR-first, mini-council autônomo 2026-05-05*
