# Resumo Executivo — Modo Autônomo 2026-05-04 a 2026-05-05

**Ler ao acordar.** Status do bloqueio do release Story 1.7d.

**Estado atual:** **Release BLOQUEADO**. Smoke real não passou em nenhum dos 11 attempts.

**Decisão pendente do usuário:** ler seção *Próxima ação recomendada* abaixo e escolher caminho.

---

## TL;DR (60s)

1. Após 11 attempts e 2 sub-runs hoje, identificamos que o problema **NÃO É APENAS** o harness pytest trava o handshake. **Existe um segundo problema independente:** mesmo standalone (sem pytest), o `download_chunk` recebe **zero trades em 600s** — apesar do handshake conectar em 1.43s e `GetHistoryTrades` retornar `code=0`.
2. **Diagnóstico:** dois sintomas distintos foram isolados:
   - **Sintoma A:** pytest harness trava `wait_market_connected`. Refutadas todas as hipóteses sobre conftest, plugins, capture, buffering.
   - **Sintoma B (NOVO em attempt 11):** `download_chunk` standalone com data fixa 2026-04-15 (WDOJ26) não recebe trades.
3. **Próxima ação que recomendo (ver detalhes abaixo):** rodar smoke standalone com data ATUAL durante pregão B3 aberto para diferenciar "data inválida" vs "fluxo download quebrado".

---

## Cronologia dos attempts (resumida)

| Attempt | Data | Hipótese principal testada | Verdict |
|---------|------|----------------------------|---------|
| 7 | 04/05 21:51 | Smoke flakey; baseline pré-bissection | FAIL-flakey |
| 8 | 04/05 22:44 | Story 1.7c espelho probe ESTRITO | FAIL-still-stuck |
| 9 | 05/05 09:25 | Pytest "nu" (sem `--timeout`) | FAIL-still-stuck |
| 10 | 05/05 10:00 | Plugin autoload OFF + `-s` + unbuffered | FAIL-still-stuck |
| 11 sub-1 | 05/05 10:07 | `--confcutdir=tests/smoke` (Q-DRIFT-22) | **FAIL-still-stuck** |
| 11 sub-2 | 05/05 10:15 | Standalone fast-path (sem pytest) | **FAIL-download-zero-trades** ← **NOVO!** |

Probes lab anteriores (não-smoke, contexto):
- `probe_init.py` (ctypes puro, sem ProfitDLL class): conecta 1.62-2.43s
- `probe_wrapper_minimal.py` (wrapper class standalone, sem `download_chunk`): conecta 2.21s

---

## Hipóteses testadas e refutadas (Q-DRIFT-11 a 22)

| ID | Hipótese | Status | Refutada por |
|----|----------|--------|-------------|
| Q-DRIFT-11 | Race condition `_set_state_callback` antes init | REFUTADA | probe sem set_state_callback ainda conecta |
| Q-DRIFT-12 | Slots 4/6/7/8 do init devem ser `None` literal | REFUTADA | espelho ESTRITO em smoke trava igual |
| Q-DRIFT-13 | Signature `c_int` vs `wintypes.HRESULT` | REFUTADA | Nelo audit |
| Q-DRIFT-14 | Lifetime de callback CFUNCTYPE | REFUTADA | wrapper retem refs corretamente |
| Q-DRIFT-15 | argtypes/restype mutados pós-init | REFUTADA | match exato pré/pós |
| Q-DRIFT-16 | Threading model MTA vs STA | REFUTADA | sem pytest funciona |
| Q-DRIFT-17 | DLL hash diferente / múltiplo carregamento | REFUTADA | sha256 idêntico |
| Q-DRIFT-18 | pytest-qt autoload `CoInitializeEx(MTA)` | REFUTADA | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` mantém trava |
| Q-DRIFT-19 | pytest fd-capture → ConnectorThread bloqueia em write | REFUTADA | callback dispara 2s/2s durante a "trava" — thread C viva |
| Q-DRIFT-20 | pytest-cov instala `sys.settrace` global | REFUTADA | sem cov, trava igual |
| Q-DRIFT-22 | `tests/conftest.py` raiz importa MockProfitDLL → ctypes pré-poluído | **REFUTADA** (attempt 11 sub-1) | `--confcutdir=tests/smoke` mantém trava |

**Em aberto (especulativas, não validadas):**
- Q-DRIFT-23: pytest core `signal.signal(SIGINT, ...)` interage mal com DLL ConnectorThread
- Q-DRIFT-24: assertion rewriter via `sys.settrace`/`sys.setprofile` residual
- Q-DRIFT-25: pytest core `atexit` handlers
- **Q-DRIFT-26 (NOVO, attempt 11 sub-2):** servidor Nelogica não despacha histórico para data fixa 2026-04-15 / WDOJ26
- **Q-DRIFT-27 (NOVO):** `subscribe_ticker + GetHistoryTrades` é caminho errado; histórico tem path próprio
- **Q-DRIFT-28 (NOVO):** signature do `HistoryTradeCallbackV2` não bate com o que servidor envia para esse contrato/data

---

## Estado do release

**BLOQUEADO.** Story 1.7d depende de smoke real PASS (AC10: `len(trades) > 0`). Nenhum attempt produziu PASS.

Workaround possível (não aplicado): WAIVER formal para Story 1.7 com checklist do constitutional gate. Não fiz isso porque restrições da missão proibiam editar STATUS.md/WAIVERs.

---

## Próxima ação recomendada (escolha 1 dos 3 caminhos)

### Caminho A: continuar bisection — recomendado se ainda há orçamento autônomo

1. Rodar `python scripts/run_smoke_real_standalone.py` com data ATUAL (modificar script para `datetime.now() - timedelta(hours=1)`) durante **pregão B3 aberto** (qualquer dia útil, 09:00-18:30 BRT). Resultado discrimina:
   - **Trades chegam:** sintoma B é específico da data fixa 2026-04-15 (Q-DRIFT-26 confirmada). Solução: alterar test para usar data dinâmica.
   - **Trades não chegam mesmo com data atual:** sintoma B é do fluxo de download em si. Aprofundar Q-DRIFT-27/28 (comparar com manual ProfitDLL §History).

### Caminho B: WAIVER formal — recomendado se você quer desbloquear release rapidamente

1. Convocar mini-council Pax (PO) + Quinn (QA) + River (SM) + Aria (Architect) para deliberar WAIVER da AC10.
2. Documento de WAIVER explicaria que:
   - Smoke real é flakey por bug não-determinado entre pytest harness + download flow.
   - Fluxo end-to-end funciona em probes ctypes puros (handshake + market state).
   - Fluxo `download_chunk` standalone conecta mas não recebe trades — fora de pytest.
3. Riscos: shipping sem validação real ponta-a-ponta.

### Caminho C: pivot para data atual + script standalone — solução técnica simples

1. Editar `tests/smoke/test_download_primitive_real.py` para:
   - Usar `datetime.now() - timedelta(minutes=30)` em vez de data fixa.
   - Marcar test como `@pytest.mark.skipif(not os.getenv("DATA_DOWNLOADER_RUN_SMOKE"))` para desabilitar em CI.
   - Documentar que smoke roda via `python scripts/run_smoke_real_standalone.py` (workaround do harness pytest).
2. Adicionar `scripts/run_smoke_real_standalone.py` ao README como caminho oficial.
3. Riscos: deixa sintoma A (pytest harness trava handshake) como tech debt sem resolução.

---

## Arquivos produzidos nesta sessão autônoma

### Novos
- `scripts/run_smoke_real_standalone.py` — fast-path do test, sem pytest.
- `docs/qa/SMOKE_EVIDENCE/1.7d-20260505T100753Z-attempt11-confcutdir-FAIL.md` — evidência sub-run 1.
- `docs/qa/SMOKE_EVIDENCE/1.7d-20260505T101516Z-attempt11-fastpath-FAIL-download.md` — evidência sub-run 2.
- `docs/qa/SMOKE_EVIDENCE/RESUMO_EXECUTIVO_AUTONOMOUS_2026-05-04.md` — este arquivo.

### Logs
- `docs/qa/SMOKE_EVIDENCE/logs/smoke1-attempt11-confcutdir-20260505T100753Z.log` (45 KB)
- `docs/qa/SMOKE_EVIDENCE/logs/smoke1-attempt11-fastpath-20260505T101516Z.log` (9.8 KB)

### NÃO modificados (restrições da missão)
- `src/` (todos)
- `tests/` (todos)
- `STATUS.md`
- WAIVERs
- `pyproject.toml`

---

## Constitutional integrity

- **Article I (CLI First):** todas as ações via CLI Python/PowerShell, nada via UI.
- **Article II (Agent Authority):** apenas Dex (@dev), sem impersonar outras personas.
- **Article III (Story-Driven):** trabalho atrelado a Story 1.7d.
- **Article IV (No Invention):** hipóteses Q-DRIFT-23-28 explicitamente etiquetadas como especulativas.
- **Article V (Quality First):** smoke não passou; refutações claras e documentadas.
- **Sem `git push`** (modo autônomo, restrição explícita).

---

**Última atualização:** 2026-05-05 10:35 BRT (attempt 11 completo).

---

## Adendo 2026-05-05 ~10:46 BRT — sub-run 3 (PREGÃO ABERTO + DATA DINÂMICA)

**Verdict:** `FAIL-zero-trades-novamente` (idêntico ao sub-2 com data fixa).

**Setup:** Mesmo `scripts/run_smoke_real_standalone.py`, terça 05/05 10:35 BRT
(pregão B3 ABERTO), com **única alteração** vs sub-2: data dinâmica
`datetime.now() - timedelta(hours=2)` → `datetime.now() - timedelta(minutes=10)`.

**Resultado:** connect=1.40s, download=600.21s timeout, trades=0,
last_packet_seen=False, progress_history_len=0, translate_failures=0,
trade_edits=0, get_history_trades **code=0** (success).

**Q-DRIFT-26 REFUTADA.** Bug NÃO é a data — é o fluxo de download
(`subscribe_ticker → set_history_trade_callback_v2 → get_history_trades`)
em si. DLL aceita todas as chamadas (`code=0`) mas callback v2 NUNCA dispara.

**Hipóteses sucessoras (Q-DRIFT-27/28/29/30):** Q-DRIFT-26 documentada como
REFUTADA em `docs/dll/QUIRKS.md`. Hipóteses 27-30 listadas como "a investigar"
— próximo turno: probe `ctypes` puro reproduzindo `profitdll/Exemplo Python/main.py`
linha-a-linha para isolar wrapper vs semântica DLL.

**Refs:**
- `docs/qa/SMOKE_EVIDENCE/1.7d-20260505T103538Z-standalone-pregao-FAIL-zero-trades-novamente.md`
- `docs/qa/SMOKE_EVIDENCE/logs/standalone-pregao-20260505T103538Z.log`

**Caminhos atualizados:**
- ❌ Caminho C (data dinâmica) **REFUTADO** como solução técnica simples.
- Caminho A (continuar bisection) **agora é Q-DRIFT-27/28/29/30** — não mais Q-DRIFT-26.
- Caminho B (WAIVER) **prioridade aumentada** — Sintoma B é mais fundo do que
  apenas "data inválida"; pode levar dias para discriminar wrapper vs DLL.

---

## Adendo 2026-05-05 ~10:55 BRT — probe ctypes puro (EXPERIMENTO DECISIVO)

**Verdict:** **CENARIO_B** — zero trades em probe ctypes puro **sem** wrapper, **sem** orchestrator, **sem** pytest.

**Setup:** `scripts/probe_history_minimal.py` — reproduz fluxo de download histórico
do exemplo oficial Nelogica linha-a-linha:
- `WinDLL` direto, sem `data_downloader.dll.wrapper.ProfitDLL`.
- `WINFUNCTYPE` callbacks com signatures EXATAS dos exemplos C++ (`main.cpp`) e
  Python (`main.py`) Nelogica + `profitTypes.py` structs.
- 11 slots do `DLLInitializeMarketLogin` todos preenchidos com Noop signatures
  CORRETAS (sem `None`).
- `SetHistoryTradeCallbackV2` registrado após `MARKET_CONNECTED`.
- `SubscribeTicker(WDOJ26, F)` + `GetHistoryTrades(WDOJ26, F, ...)`.

**Resultado:**
- `MARKET_CONNECTED` em **1.61s** (handshake perfeito, sequência ATIVO → LOGIN_OK
  → MARKET_CONNECTING → csConnectedWaiting → MARKET_CONNECTED).
- `SubscribeTicker` ret=0 (NL_OK).
- `SetHistoryTradeCallbackV2` ret=0 (NL_OK).
- `GetHistoryTrades` ret=0 (NL_OK) — janela `now-2h → now-10min` durante pregão B3 ABERTO.
- **Zero trades em 120s. Zero progress callbacks. Zero LAST_PACKET.**

**Implicação CRÍTICA — REFUTAÇÃO PARCIAL DA DIRETIVA "é bug, NÃO É DLL":**
Como o probe puro tem comportamento IDÊNTICO ao smoke via wrapper, o bug
**NÃO está no nosso código**. Está em uma das três áreas externas:
1. **H1 (mais provável):** conta `nicolascarasaibaptista@gmail.com` sem permissão de
   histórico de trades (apenas real-time).
2. **H4:** contrato `WDOJ26` (abril/2026) vencido — vigente seria `WDOK26` ou `WDON26`.
3. **H5 (refuta a diretiva):** bug ou regressão na DLL para essa conta/contrato.

**Refs:**
- `scripts/probe_history_minimal.py` (criado nesta sessão)
- `docs/qa/SMOKE_EVIDENCE/probe-history-minimal-20260505T105518Z-CENARIO_B.md`
- `docs/qa/SMOKE_EVIDENCE/logs/probe-history-minimal-20260505T105518Z.log`

---

## Próxima ação recomendada (ATUALIZADA — pós CENARIO_B)

**Caminho A.1 (sanity check rápido — 5min, recomendado PRIMEIRO):**
Rodar `scripts/probe_history_minimal.py` modificando símbolo para
`PETR4` + exchange `B`. Esse contrato é 100% disponível e usado no exemplo Nelogica.
- Se PETR4 traz trades → problema é específico WDO/F (provável H4 contrato vencido
  ou licença BMF distinta).
- Se PETR4 também zero → confirma H1 (conta sem permissão histórica em geral).

**Caminho A.2 (se A.1 mostrar problema com WDO):**
Rodar mesmo probe com `WDOK26` (maio/2026 — vigente) ou `WDON26` (julho/2026).

**Caminho A.3 (definitivo — escalar Nelogica):**
Após A.1 e A.2, contatar suporte Nelogica com TODOS os logs deste sub-run
+ probe history minimal. Pedir confirmação se a conta tem permissão de
**histórico de trades** (não só real-time) e qual contrato WDO/WIN é vigente
para chamada `GetHistoryTrades`.

**Caminho B (WAIVER) — prioridade ainda alta:**
Se A.3 demorar dias, formalizar WAIVER de AC10 conforme já planejado
(Pax + Quinn + River + Aria mini-council). Argumento adicional:
**diagnóstico interno está completo e o bloqueio é externo ao projeto**.
