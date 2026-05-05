# QUIRKS_OPEN_P1 — Quirks Abertas Bloqueantes (2026-05-05)

**Curador:** Aria 🏛️ (architect)
**Snapshot:** 2026-05-05 (post Story 1.7g Done)
**Escopo:** quirks **OPEN** classificadas P0/P1 que **bloqueiam próximas features** ou exigem probe humano para destravar story específica.

> **Critério de inclusão neste arquivo:**
> - Status ≠ ✅ valid (não fechada).
> - Bloqueia release-candidate **OU** bloqueia AC de story planejada **OU** representa risco operacional sem mitigação determinística.
> - Tem **próximo experimento** definido (não é "TBD eternamente").
>
> **Quirks vivas (todas):** ver `docs/dll/QUIRKS.md`.
> **Quirks históricas (refutadas/arquivadas):** ver `docs/debt/QUIRKS_HISTORICAL_2026-05-05.md`.
> **Índice executivo:** ver `docs/debt/QUIRKS_INDEX.md`.

---

## §1 — P0 ABERTAS (release-blocker ativo)

**Status atualizado 2026-05-05 (Orion @aiox-master):** Q-DRIFT-37 foi
**RESOLVIDO** em Story 1.7g AC7 (commit `974fb97`). Mantido aqui apenas
como cross-ref histórico — não é mais blocker. Ver §1.1 abaixo.

### Q-DRIFT-37 — Volume completeness gap — ✅ RESOLVED (1.7g AC7)

- **ID:** [Q-DRIFT-37](../dll/QUIRKS.md#q-drift-37)
- **Status:** 🐛 **HOTFIX-APPLIED-VALIDATED 2026-05-05** (Story 1.7g AC7)
- **Severidade:** ~~P0 RELEASE BLOCKER~~ → **RESOLVED**
- **Categoria:** history / volume completeness / silent-data-loss

**Resolução (COUNCIL-37 Quinn / hipótese H-E queue overflow):**
Diagnóstico precisamente **NÃO** foi LAST_PACKET prematuro nem cap
server-side, mas sim **trade_queue saturação silenciosa** em
`dll/callbacks.py::_history_cb` (`put_nowait` engolindo `queue.Full`
sem métrica). Burst histórico Nelogica >100k trades em ~10s saturava
o buffer 100k. Fix Story 1.7g AC7:

- `TRADE_QUEUE_MAXSIZE`: 100_000 → **2_000_000** (~32MB par-int64).
- `make_history_trade_callback_v2(stats={"queue_dropped": 0})` —
  contador GIL-atômico não-bloqueante.
- `ChunkResult.queue_dropped: int = 0` campo novo.
- `download.complete` log inclui `queue_dropped` agregado.

**Validação empírica (smoke 5-dia 28/04→02/05):**
- 1.574.806 trades capturados em 174.4s download.
- `queue_dropped == 0` (zero drops silenciosos).
- 29/04=552k ✅, 30/04=533k ✅ (≥500k threshold).
- 28/04=488k (97.6% threshold) PASS-CONCERNS — volume real legítimo,
  dia atípico pós-Páscoa pré-feriado, sem perda silenciosa confirmada.

**Histórico das hipóteses (referência):**
- ~~H37-A LAST_PACKET prematuro~~ — REFUTADA (callback recebe LAST_PACKET correto)
- ~~H37-B window cap server-side~~ — REFUTADA (5-dia entregou 1.5M trades)
- ~~H37-C subscribe race~~ — REFUTADA (subscribe_ticker confirmado pré-GetHistoryTrades)
- ✅ **H37-E queue overflow silencioso** — CONFIRMADA + FIXADA

**Stories desbloqueadas:**
- **1.7g** Done (AC1..AC8 satisfeitos; AC4 PASS-CONCERNS aceito).
- **Release v1.0.0** desbloqueada (aguarda apenas smoke real 1.7b-followup humano).

**Referências:**
- `docs/qa/SMOKE_EVIDENCE/1.7g-20260505T181037Z-5day-AC7-PASS-AC4-conferir.md` (evidência conclusiva)
- `docs/decisions/COUNCIL-37-Quinn-volume-gap-2026-05-05.md` (diagnóstico)
- `docs/decisions/COUNCIL-38-Nelo-download-flow-audit-2026-05-05.md`
- `docs/INVARIANTS.md` I2 (Volume Completeness)
- `docs/adr/ADR-020-volume-completeness-invariant.md` Nível 4 detection ativa
- Commit `974fb97` (AC7 implementation)
- Commit `aec39e9` (1.7b flakey evidence + gitignore cleanup)

**Migração agendada:** Q-DRIFT-37 será movido para `QUIRKS_HISTORICAL` na
próxima sweep (lifecycle 30d pós-validação — ~2026-06-04).
- `docs/adr/ADR-020-volume-completeness.md`

---

## §2 — P1 ABERTAS (bloqueia próxima story / feature)

### Q-DRIFT-09 — SetXxxCallback signatures (potencial regressão Q-DRIFT-05)

- **ID:** [Q-DRIFT-09](../dll/QUIRKS.md#q-drift-09)
- **Status:** 🧪 HYPOTHESIS (não validada definitivamente; Opção C funcionou de fato em 1.7d/g — registrar APENAS necessários)
- **Severidade:** **P1 — affecta extensão futura**
- **Categoria:** callback / signatures (mesma classe Q-DRIFT-05)

**Contexto:**
Smoke 5 crashou com 14 access violations + 1 stack overflow após `MARKET_LOGIN_OK`. Hipótese: signatures dos 14 `SetXxx` Noop divergiam — alta superfície de bug porque 9 dos 14 usam structs por valor (TAssetID, TConnectorAssetIdentifier, TConnectorAccountIdentifier).

**Estado atual:** Story 1.7d adotou Opção C (Nelo) — registrar APENAS `SetHistoryTradeCallbackV2` (+ `SetTradeCallbackV2` quando V1.live precisar). Os outros 12 NÃO são chamados. Isso **passou** em smoke postfix-35 → Opção C funciona empiricamente.

**Próximo experimento:**
- Quando Story 4.x (live broadcasting Sol, book ladder) precisar de qualquer dos 12 outros callbacks, validar signature **uma de cada vez** com smoke isolado.
- Documentar signatures canônicas em `PROFITDLL_KNOWLEDGE.md` §3.3 (já existe — confirmar accuracy contra `profitTypes.py`).

**Stories bloqueadas (futuro):**
- **5.x — live broadcasting / Sol** (assim que precisarmos de `SetTinyBookCallback` real, `SetOfferBookCallbackV2`, etc.).
- **Epic 6 — order flow** (todos os `SetOrderXxx` callbacks).

**Referências:**
- `PROFITDLL_KNOWLEDGE.md §3.3` (tabela canônica das 14 signatures)
- `profitdll/Exemplo Python/main.py` L745-L761 (modelo de registro)

---

### Q15-OPEN — DLL queue saturation behavior

- **ID:** [Q15-OPEN](../dll/QUIRKS.md#q15-open) (finding H4 Pyro)
- **Status:** ❓ open
- **Severidade:** **P1 — risco operacional sem mitigação determinística**
- **Categoria:** threading / queue

**Contexto:**
Quando consumidor Python (engine thread) é mais lento que produtor (ConnectorThread) e a fila interna de callbacks da DLL enche, **não sabemos** o que a DLL faz. Três hipóteses possíveis:
- **H-A** drop silencioso (perda de dados sem erro)
- **H-B** bloqueia ConnectorThread (back-pressure)
- **H-C** levanta `cosTimeout` ou `NL_QUEUE_FULL`

Manual silencioso. Se for H-A, **podemos perder trades em produção sob load** sem detecção.

**Próximo experimento (Pyro / Dex):**
1. Mock writer que sleeps 5s (simula GC pause / disk freeze).
2. Live trade subscription.
3. Contar trades antes/depois da pausa.
4. Verificar se algum NL_* error ou `cosTimeout` chega via state callback.
5. Comparar com taxa esperada (snapshot pré-pausa × duração).

**Stories bloqueadas:**
- **1.4.5** (probe formal Pyro — pendente).
- **1.7a** (queue policy final — atualmente assume H-A pessimista com `maxsize=10000`).
- **5.x — live broadcasting** (sob load real, hipótese desconhecida = risco silent data loss).

**Workaround atual:** `dll_queue` Python-side com `maxsize=10000` + política `block` em `put`. Logger de saturação quando `qsize() > 0.8 * maxsize`.

**Referências:**
- `docs/dll/OPEN_QUESTIONS_RESPONSES.md` Q1
- `src/data_downloader/orchestrator/download_primitive.py` (queue policy)

---

### Q18-OPEN — Vigência exata WIN trimestrais (calendário B3)

- **ID:** [Q18-OPEN](../dll/QUIRKS.md#q18-open)
- **Status:** ❓ open
- **Severidade:** **P1 — bloqueia validação seed Story 4.2**
- **Categoria:** history / contract calendar

**Contexto:**
Pergunta: vigência exata dos contratos WIN trimestrais (H/M/U/Z) segue regra B3 documentada (5º dia útil mês X-3 → quarta mais próxima do dia 15 mês X) em todas as instâncias, ou há exceções por feriado / pregão estendido / decisão B3?

Seed `CONTRACTS.md §3` (Story 4.2) tem 8 entradas WIN com `validation_source=hypothesized`. **Nenhuma confirmada por probe.**

**Próximo experimento (humano + Nelo):**
1. Para cada vencimento WIN (H/M/U/Z 26/27): rodar `data-downloader contracts validate --root WIN --year 2026` (Story 4.2 AC3).
2. Cross-check com calendário B3 oficial PDF (humano + Nova).
3. Atualizar `validation_source=dll_probe` ou `b3_calendar` quando confirmado.

**Stories bloqueadas:**
- **4.2** (multi-asset seed — depende de validação WIN entries).
- **4.2-followup** (smoke real WIN+equity humano — gating por probe).

**Workaround atual:** seed `hypothesized` + WAIVER `docs/qa/WAIVERS/4.2-real-smoke-deferred-2026-05-04.md`.

**Referências:**
- `docs/storage/CONTRACTS.md §2.2 + §3`
- `docs/decisions/COUNCIL-29-multi-asset-impl.md`
- `docs/qa/WAIVERS/4.2-real-smoke-deferred-2026-05-04.md`

---

## §3 — Hipóteses não-validadas residuais (P2 — não bloqueia release atual)

Listadas para visibilidade. Não bloqueiam release MVP (1.7g + ADR-022 + Q17-CLOSED).

| ID | Categoria | Status | Próximo passo |
|----|-----------|--------|---------------|
| [Q-DRIFT-23](../dll/QUIRKS.md#q-drift-13--25-bissection-history) | bisseção pytest | 🧪 hypothesis (não validada) | pytest core `signal.signal(SIGINT, ...)` interage mal com ConnectorThread — virar Story 1.7e separada |
| [Q-DRIFT-24](../dll/QUIRKS.md#q-drift-13--25-bissection-history) | bisseção pytest | 🧪 hypothesis (não validada) | assertion rewriter via `sys.settrace`/`sys.setprofile` residual — Story 1.7e |
| [Q-DRIFT-25](../dll/QUIRKS.md#q-drift-13--25-bissection-history) | bisseção pytest | 🧪 hypothesis (não validada) | pytest core `atexit` handlers — Story 1.7e |

**Recomendação:** Sintoma A (pytest harness trava) deve virar **Story 1.7e** separada com WAIVER se Q-DRIFT-23/24/25 não confirmarem em probe direcionado. Smoke real para release passa via `scripts/run_smoke_real_standalone.py` (PASS confirmado postfix-35).

---

## §4 — Ambíguas com workaround estável (não-bloqueiam mas não-fechadas)

Listadas para tracking. Têm workaround estável; não exigem ação imediata.

| ID | Categoria | Status | Workaround atual |
|----|-----------|--------|------------------|
| [Q03-AMB](../dll/QUIRKS.md#q03-amb) | timestamp | ⚠️ ambiguous | parser canônico aceita `:ZZZ` e `.ZZZ`; normaliza para `.ZZZ` (story 1.3 + property test 2.1) |
| [Q09-AMB](../dll/QUIRKS.md#q09-amb) | lifecycle | ⚠️ ambiguous | try/except `DLLFinalize`/`Finalize` (story 1.2 AC6) |
| [Q10-AMB](../dll/QUIRKS.md#q10-amb) | state | ⚠️ ambiguous | aceitar `2` e `4` para `conn_type=2` (story 1.2 AC5) |

---

## §5 — Resumo executivo

**Total OPEN P0:** 1 (Q-DRIFT-37 volume gap — release blocker)
**Total OPEN P1:** 3 (Q-DRIFT-09 SetXxx signatures, Q15-OPEN queue saturation, Q18-OPEN WIN calendar)
**Total HYPOTHESIS P2:** 3 (Q-DRIFT-23/24/25 pytest harness)
**Total AMBIGUOUS estável:** 3 (Q03-AMB, Q09-AMB, Q10-AMB)

**Top 3 prioridades para destravar release:**
1. **Q-DRIFT-37** (P0) — Quinn + Nelo councils 37/38 entregar diagnóstico de volume gap. Bloqueia toda release pública.
2. **Q15-OPEN** (P1) — Pyro Story 1.4.5 probe queue saturation. Bloqueia 5.x live broadcasting com confiança.
3. **Q18-OPEN** (P1) — humano + Nelo Story 4.2-followup probe vigência WIN. Bloqueia 4.2 close.

— Aria 🏛️
