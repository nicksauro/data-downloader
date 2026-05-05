# QUIRKS.md — Catálogo Vivo de Quirks da ProfitDLL

**Curador:** Nelo 🗝️ (profitdll-specialist)
**Última atualização:** 2026-05-04 (Q-DRIFT-10 NOVO — smoke 6 commit `7badeea` confirma `MARKET_DATA` trava em `(2,1)` MARKET_CONNECTING após Q-DRIFT-05 fix; audit linha-por-linha vs `dllStart()` (main.py L729-764) revela 3 divergências do exemplo oficial; hipótese primária: substituir Noop por `None` nos slots 5/7/8/9 onde exemplo passa `None` literal — alavanca Q-DRIFT-06 já validado em fonte primária)

> **O que é quirk:** comportamento da DLL **surpreendente** comparado ao que o manual diz (ou silencia). Aqui registramos cada um com sintoma, causa raiz (se conhecida), evidência, workaround, comparação com manual, data e status.
>
> **Status:**
> - `validated` ✅ — confirmado em manual + prática (não é surpresa, mas é trap pra quem não leu)
> - `ambiguous` ⚠️ — manual diz X, prática observou Y. Documentar ambos, decisão registrada.
> - `empirical` 🔬 — manual silencioso, prática ensinou. Pode virar `validated` se manual atualizar.
> - `open` ❓ — pergunta sem resposta. Aguarda probe.

---

## Índice

| ID | Status | Categoria | Sumário |
|----|--------|-----------|---------|
| [Q01-V](#q01-v) | ✅ validated | history | `WDOFUT`/`WINFUT` retornam 0 trades; usar contrato vigente |
| [Q02-E](#q02-e) | ✅ validated | history | Progresso 99% reconectando — não é trava (workaround formalizado em Story 2.6) |
| [Q03-AMB](#q03-amb) | ⚠️ ambiguous | timestamp | Formato `.ZZZ` (manual) vs `:ZZZ` (whale-detector v2) |
| [Q04-E](#q04-e) | 🔬 empirical | timestamp | Timestamps em BRT naive (manual silencioso) |
| [Q05-V](#q05-v) | ✅ validated | subscription | Bolsa = uma letra (`B`, `F`); `BMF` retorna NL_EXCHANGE_UNKNOWN |
| [Q06-V](#q06-v) | ✅ validated | callback / threading | Callback NÃO pode chamar funções da DLL |
| [Q07-V](#q07-v) | ✅ validated | ctypes | `_cb_refs` global previne GC dos callbacks |
| [Q08-E](#q08-e) | 🔬 empirical | lifecycle | DLL não-idempotente em init→finalize→init na mesma sessão Python |
| [Q09-AMB](#q09-amb) | ⚠️ ambiguous | lifecycle | `DLLFinalize` (manual) vs `Finalize` (whale-detector) |
| [Q10-AMB](#q10-amb) | ⚠️ ambiguous | state | `MARKET_CONNECTED=4` (manual) vs `MARKET_WAITING=2` (prática) |
| [Q11-E](#q11-e) | 🔬 empirical | init | Slots `None` no DLLInitialize corrompem `SetHistoryTradeCallback` posterior |
| [Q12-E](#q12-e) | 🔬 empirical | history | Chunk size adaptativo: WDO=5d, WIN=1d funciona |
| [Q13-V](#q13-v) | ✅ validated | api | Funções V1 obsoletas — usar V2 sempre que existir |
| [Q14-E](#q14-e) | 🔬 empirical | metadata | `GetAgentName` requer `GetAgentNameLength` PRIMEIRO |
| [Q15-OPEN](#q15-open) | ❓ open | threading | Comportamento ConnectorThread quando `put_nowait` bloqueia (drop ou wait?) |
| [Q16-VALIDATED](#q16-validated) | ✅ validated | auxiliary file / calendar | `holidays.dat` Nelogica omite feriados oficiais que caem em fim de semana |
| [Q17-OPEN](#q17-open) | ❓ open | licença / multi-process | Múltiplas instâncias da mesma chave Nelogica em processos diferentes na mesma máquina é OK? (Story 4.1 broker pré-requisito) |
| [Q18-OPEN](#q18-open) | ❓ open | history / contract calendar | Vigência exata WIN H/M/U/Z conforme regra B3 oficial (5º dia útil mês X-3 → quarta mais próxima 15/X)? |
| [Q-DRIFT-01](#q-drift-01) | 🔬 empirical | api drift | `SetProgressCallback` e `GetDLLVersion` **NÃO exportadas** pela DLL real |
| [Q-DRIFT-02](#q-drift-02) | ⚠️ ambiguous → 🔬 ROOT CAUSE: signatures NoopCallback erradas | lifecycle | `wait_market_connected` trava em (2,1) MARKET_CONNECTING; hipótese ProfitChart REFUTADA |
| [Q-DRIFT-03](#q-drift-03) | ✅ validated | config | Env vars do código divergiam de `.env.example` — padronizado em `PROFITDLL_*` |
| [Q-DRIFT-04](#q-drift-04) | 🔬 empirical | tooling / encoding | Rich Panel emoji crash em Windows cp1252 — CLI força `PYTHONIOENCODING=utf-8` |
| [Q-DRIFT-05](#q-drift-05) | 🔬 empirical | init / signatures | NoopCallback signatures expandem TAssetID em 3 args primitivos (errado) — exemplo Nelogica usa TAssetID struct por valor |
| [Q-DRIFT-06](#q-drift-06) | ⚠️ corrected | init | Q11-E "JAMAIS passar None" REFUTADO pelo exemplo oficial — Nelogica passa `None` em 4 dos 8 slots em `DLLInitializeMarketLogin` |
| [Q-DRIFT-07](#q-drift-07) | ✅ validated | history / subscription | `SubscribeTicker(ticker, exchange)` é PRÉ-REQUISITO de `GetHistoryTrades` — sem subscribe, callback V2 nunca dispara |
| [Q-DRIFT-08](#q-drift-08) | 🔬 empirical | ctypes / argtypes | argtypes/restype JAMAIS configurados no wrapper; exemplo oficial configura ~30 funções em `profit_dll.py` — sem isso, x64 stdcall pode truncar handles e desalinhar stack |
| [Q-DRIFT-09](#q-drift-09) | 🔬 empirical → hipótese | callback / signatures | Smoke 5: 14 SetXxxCallback NoopCallback signatures suspeitas → access violations + stack overflow após MARKET_LOGIN_OK; Q11-E refutado parcialmente (passar `None` pode ser MAIS SEGURO que NoopCallback errado) |
| [Q-DRIFT-10](#q-drift-10) | 🔬 empirical → hipótese forte | init / divergência exemplo | Smoke 6 (commit `7badeea`): `MARKET_DATA` trava em `(2,1)` MARKET_CONNECTING. Audit linha-por-linha vs `dllStart()` (main.py L729-764) revela 3 divergências do exemplo oficial: (a) wrapper passa **7 NoopCallbacks** onde exemplo passa **`None` em 4 slots**; (b) wrapper chama `SetEnabledLogToDebug(0)` ANTES do init (exemplo NÃO chama); (c) wrapper SKIPA os 14 `SetXxxCallback` que exemplo chama ANTES de `wait_login`. Hipótese primária: NoopCallback nos slots 5/7/8/9 onde exemplo usa `None` — DLL pode validar callback no handshake (não só no fire) e signatures Noop divergentes corrompem state machine antes do `result=4`. |

---

## Q01-V

- **ID:** Q01-V
- **Status:** ✅ validated
- **Categoria:** history
- **Sintoma:** `GetHistoryTrades(ticker="WDOFUT", ...)` ou `GetHistoryTrades(ticker="WINFUT", ...)` retorna **0 trades** mesmo em janelas históricas com pregão ativo.
- **Causa raiz:** `WDOFUT` / `WINFUT` são apenas **aliases live** que apontam para o contrato vigente em tempo real. O servidor de histórico só conhece **contratos específicos por mês** (`WDOJ26` = abril 2026, `WINH26` = março 2026, etc.).
- **Evidência:** validado em whale-detector v2 (2026-03-09) e Sentinel §12. Manual §3.1 linha 1747 só mostra exemplo com `"PETR4"` (ação cash, não tem alias).
- **Workaround:** Resolver alias → contrato vigente via tabela de rollover (responsabilidade da Nova, não da DLL).
- **Manual diz:** silencioso sobre aliases.
- **Data descoberta:** ~2026-03 (whale-detector v2).
- **Aplica a stories:** 1.6 (probe), 1.7a/b (orchestrator), 2.1 (validator).

---

## Q02-E

- **ID:** Q02-E
- **Status:** ✅ validated (workaround formalizado em Story 2.6)
- **Categoria:** history
- **Sintoma:** `ProgressCallback` reporta `99` repetidamente por dezenas de minutos antes de chegar a `100` ou disparar último `HistoryTradeCallback`. Aparenta travamento.
- **Causa raiz:** A DLL cicla a conexão com o servidor de histórico antes de entregar o último pacote (especulação — manual silencioso). Pode estar relacionado a checkpoint/handshake interno.
- **Evidência:** validado em whale-detector v2 e Sentinel §12. Reproduzível em dias com volume alto de trades.
- **Workaround (Story 1.3 + Story 2.6):**
  - **Timeout duro:** 1800s sem progresso real (não confundir com 99% repetido) — `download_chunk` timeout default.
  - **Progress-aware policy:** progress=99% NÃO é error code NL_*, é estado de fluxo. `download_primitive` (Story 1.3) detecta e ignora; orchestrator + circuit breaker (Story 2.6) NÃO contam como falha porque `download_chunk` retorna `status='completed'` se `TC_LAST_PACKET` chegou (mesmo após N callbacks de 99%).
  - **Apenas falhas reais contam:** circuit breaker recebe `record_failure` apenas quando `status='timeout'` (deadline duro) OU `status='failed'` (NL_* error code). Q02-E permanece transparente — N reconnects 99% durante 1 chunk = 0 falhas no breaker = CLOSED preservado.
  - **NÃO** abortar em 99% — esperar `100` OU `TC_LAST_PACKET` (V2) OU timeout duro.
- **Test reprodutor:** `tests/integration/test_orchestrator_with_retry.py::test_circuit_breaker_does_not_count_q02e_progress_99_as_failure`.
- **Manual diz:** §3.1 linha 1750 — "progresso de Download (1 até 100)" sem detalhar.
- **Data descoberta:** ~2025 (Sentinel).
- **Data validated:** 2026-05-03 (Story 2.6 / COUNCIL-20).
- **Aplica a stories:** 1.3 (history primitive), 1.7a/b, 2.6 (circuit breaker policy).

---

## Q03-AMB

- **ID:** Q03-AMB
- **Status:** ⚠️ ambiguous
- **Categoria:** timestamp
- **Sintoma:** Timestamp recebido em `TNewTradeCallback`/`THistoryTradeCallback` chega como string. Manual documenta formato `"DD/MM/YYYY HH:mm:SS.ZZZ"` (PONTO antes de ms). Whale-detector v2 observou empiricamente `"DD/MM/YYYY HH:mm:SS:ZZZ"` (DOIS-PONTOS) em algumas versões.
- **Causa raiz:** desconhecida — possível bug por versão da DLL OU divergência por contrato/exchange.
- **Evidência:** manual §3.2 (callbacks de trade) literal `.ZZZ`. Whale-detector v2 logs (2026-03) mostram `:ZZZ` em produção live.
- **Workaround:** parser canônico aceita **ambos**; normaliza para `.ZZZ` antes de armazenar:
  ```python
  def parse_brt_timestamp(s: str) -> datetime:
      # Aceita ":ZZZ" ou ".ZZZ"
      s = s.replace(":", ".", 3)  # cuidado: substitui só os 3 primeiros ":" (data/hora)
      # ... parse com strptime
  ```
  Validar canonização em property test (Quinn, story 2.1).
- **Manual diz:** `.ZZZ`.
- **Data descoberta:** ~2026-02 (whale-detector v2).
- **Aplica a stories:** 1.3 (parse), 1.4 (write).

---

## Q04-E

- **ID:** Q04-E
- **Status:** 🔬 empirical
- **Categoria:** timestamp / timezone
- **Sintoma:** Timestamps de trades, book, ordens chegam **sem timezone explícito**. Manual não diz se é UTC ou local.
- **Causa raiz:** DLL emite em **BRT naive** (horário local B3). Confirmado validando contra fuso de pregão (abertura 09:00, fechamento 17:00).
- **Evidência:** whale-detector v2 + Sentinel + reconciliação com timestamps de pregão B3. Manual silencioso.
- **Workaround:** **MANIFEST R2** — armazenar BRT naive, **NÃO** converter para UTC. Conversão destrói semântica de fase de pregão / DST / leilões.
- **Manual diz:** silencioso.
- **Data descoberta:** ~2025.
- **Aplica a stories:** 1.4 (write Parquet), todo consumer downstream.
- **Nota DST:** B3 não observa DST desde 2019; histórico anterior tem ambiguidade (M17). Limitar smoke a >= 2020.

---

## Q05-V

- **ID:** Q05-V
- **Status:** ✅ validated
- **Categoria:** subscription
- **Sintoma:** Passar `bolsa="BMF"` ou `bolsa="BOVESPA"` em `SubscribeTicker` retorna `NL_EXCHANGE_UNKNOWN`.
- **Causa raiz:** Manual define exchange como **uma letra única**.
- **Evidência:** Manual §3.1 linha 1673 literal: `"Ticker: PETR4, Bolsa: B"` e `"Ticker: WINFUT, Bolsa: F"`. Validado empiricamente.
- **Workaround:** sempre passar:
  - `B` para Bovespa (ações cash)
  - `F` para BMF (futuros, opções sobre futuros)
- **Manual diz:** literal `B` e `F`.
- **Data descoberta:** documentada no manual desde sempre, mas é trap clássico.
- **Aplica a stories:** todas que façam Subscribe ou GetHistory.

---

## Q06-V

- **ID:** Q06-V
- **Status:** ✅ validated
- **Categoria:** callback / threading
- **Sintoma:** Chamar qualquer função da DLL de dentro de um callback causa "exceções inesperadas e comportamento indefinido" (manual literal).
- **Causa raiz:** ConnectorThread interna da DLL não é reentrante. Chamar a DLL de dentro do callback causa deadlock ou corrupção da fila interna.
- **Evidência:** Manual §4 linha 4382 — regra OFICIAL.
- **Workaround:** padrão **callback → queue → engine thread**. Callback faz APENAS `queue.put_nowait(...)`.
- **Manual diz:** literal — esta é regra oficial, não quirk. Listada aqui para visibilidade.
- **Data descoberta:** sempre.
- **Aplica a stories:** 1.2 (state callback), 1.3 (history callback), todas que envolvam callback.

---

## Q07-V

- **ID:** Q07-V
- **Status:** ✅ validated
- **Categoria:** ctypes (não específico DLL — regra geral)
- **Sintoma:** Após init, callback nunca dispara OU dispara algumas vezes e depois Python crasha com access violation.
- **Causa raiz:** GC do Python coletou o objeto `WINFUNCTYPE`-wrapped porque nenhuma referência ativa existe no Python-side. A DLL ainda tem o ponteiro mas o trampoline desapareceu.
- **Evidência:** regra documentada na própria documentação do `ctypes` Python e confirmada em produção whale-detector v2.
- **Workaround:** lista global `_cb_refs: list = []` em `dll/callbacks.py`. **Append** todo callback criado, **never clear** durante a vida do processo.
- **Manual diz:** silencioso (não é responsabilidade do manual da DLL — é regra do ctypes Python).
- **Data descoberta:** sempre.
- **Aplica a stories:** 1.2, 1.3 e qualquer uso de WINFUNCTYPE.

---

## Q08-E

- **ID:** Q08-E
- **Status:** 🔬 empirical
- **Categoria:** lifecycle
- **Sintoma:** Sequência `init → finalize → init` na **mesma** sessão Python:
  - 2º init pode crashar com access violation, OU
  - 2º init retorna sucesso mas callbacks nunca disparam, OU
  - 2º init retorna NL_INTERNAL_ERROR.
- **Causa raiz:** ConnectorThread provavelmente não é re-inicializável; estado interno da DLL não é zerado por `Finalize`.
- **Evidência:** observado em testes whale-detector durante desenvolvimento. Não documentado em manual.
- **Workaround:**
  - **Em testes:** fixture `pytest` **session-scoped** (init exatamente UMA vez por invocation). Story 1.2 AC14.
  - **Em produção:** 1 init por processo Python (R3 expandida). Para re-init, **respawn do processo** (multi-symbol via subprocess).
- **Manual diz:** silencioso.
- **Data descoberta:** ~2026-02.
- **Aplica a stories:** 1.2 (fixture), 1.7a (orchestrator decisão por subprocess), MANIFEST R3.

---

## Q09-AMB

- **ID:** Q09-AMB
- **Status:** ⚠️ ambiguous
- **Categoria:** lifecycle
- **Sintoma:** Manual documenta função `DLLFinalize` (sem args) para encerrar. Whale-detector usa `Finalize()` (sem o prefixo `DLL`). Ambos parecem funcionar em algumas versões.
- **Causa raiz:** possível dual-export pela Nelogica para compat reversa (especulação).
- **Evidência:**
  - Manual §4 documenta `DLLFinalize`.
  - Whale-detector v2 código-fonte usa `Finalize()`.
  - Não testado lado-a-lado em mesma versão.
- **Workaround (decisão Story 1.2 AC6):**
  ```python
  try:
      ret = self._dll.DLLFinalize()
      method_used = "DLLFinalize"
  except AttributeError:
      ret = self._dll.Finalize()
      method_used = "Finalize"
  ```
  Logar qual foi usado. Atualizar este quirk para `validated` quando smoke real (Story 1.2) confirmar qual existe na versão 4.0.0.34.
- **Manual diz:** `DLLFinalize` (oficial).
- **Data descoberta:** 2026-03 (whale-detector code review).
- **Aplica a stories:** 1.2 (AC6).

---

## Q10-AMB

- **ID:** Q10-AMB (= Q-AMB-01 no PLAN_REVIEW)
- **Status:** ⚠️ ambiguous
- **Categoria:** state
- **Sintoma:** Manual §3.2 documenta `MARKET_CONNECTED` como `result=4` para `conn_type=2 (MARKET_DATA)`. Em produção (whale-detector v2), o que chega frequentemente é `result=2` (`MARKET_WAITING`), e ainda assim subscriptions e history funcionam imediatamente após.
- **Causa raiz:** desconhecida — possível diferença por horário (pré-pregão vs intraday) ou versão da DLL.
- **Evidência:**
  - Manual §3.2 linha 3317-3329: `MARKET_CONNECTED=4`
  - Whale-detector v2: aceita `2` ou `4` em `wait_market_connected`.
  - Sentinel §12: documenta divergência.
- **Workaround (decisão Story 1.2 AC5):** aceitar **ambos** `2` e `4` para `conn_type=2` como market data conectado. Logar qual veio:
  ```python
  log.info("dll.market_state", conn_type=2, result=result,
           alias="MARKET_WAITING" if result == 2 else "MARKET_CONNECTED")
  ```
- **Manual diz:** `MARKET_CONNECTED=4`.
- **Data descoberta:** 2026-02.
- **Aplica a stories:** 1.2 (AC5).

---

## Q11-E

- **ID:** Q11-E (Sentinel §12) ⚠️ **SUPERSEDED por [Q-DRIFT-06](#q-drift-06) (2026-05-04)**
- **Status:** 🔬 empirical → ⚠️ REFUTADO em 2026-05-04. Mantido aqui pelo histórico, mas o exemplo oficial Nelogica (`main.py` L742) passa `None` em 4 dos 8 slots tranquilamente. Provável causa do bug Sentinel §12 era signatures incorretas (Q-DRIFT-05), não `None`.
- **Categoria:** init
- **Sintoma:** `DLLInitializeMarketLogin` é chamado com `None` em alguns dos 11 callback slots opcionais (ex: passar `None` em `histTrade` porque a story atual não usa histórico). Init **retorna sucesso**. Story posterior chama `SetHistoryTradeCallback(real_callback)` — **callback nunca dispara**, sem erro reportado.
- **Causa raiz:** DLL provavelmente armazena os ponteiros do init internamente em uma estrutura/array; passar `None` (NULL ptr) corrompe um índice e o `Set*Callback` posterior escreve no slot errado OU é silenciosamente ignorado.
- **Evidência:** Sentinel §12 — documentado após semanas debugando "histórico não chega". Solução foi sempre passar callback (mesmo no-op) em todos os 11 slots.
- **Workaround:** definir `NoopCallback` por signature em `dll/callbacks.py`:
  ```python
  def make_noop_callback(funtype):
      cb = funtype(lambda *args: None)  # signature compatível, no-op
      _cb_refs.append(cb)
      return cb
  ```
  Sempre passar `NoopCallback` em slots não usados. **JAMAIS** `None`. Story 1.2 AC2.
- **Manual diz:** silencioso (lista os args como obrigatórios mas não diz que `None` corrompe).
- **Data descoberta:** ~2025 (Sentinel).
- **Aplica a stories:** 1.2 (AC2 + Task 4 NoopCallback factory), 1.3 (precisa que 1.2 não tenha passado None).

---

## Q12-E

- **ID:** Q12-E
- **Status:** 🔬 empirical
- **Categoria:** history
- **Sintoma:** `GetHistoryTrades` com chunk grande (10+ dias para WDO, 5+ dias para WIN) frequentemente:
  - Causa timeout interno DLL (NL_HISTORY_TIMEOUT)
  - Trava em 99% (Q02-E exacerbado)
  - Entrega histórico incompleto sem error
- **Causa raiz:** servidor de histórico tem limite implícito por request (não documentado).
- **Evidência:** validado por trial-and-error em Sentinel + whale-detector.
- **Workaround:** chunk size adaptativo por symbol:
  - **WDO:** 5 dias úteis
  - **WIN:** 1 dia útil
  - **Ações cash (PETR4, etc.):** 5-10 dias úteis (não testado exaustivamente)
- **Manual diz:** silencioso sobre limites.
- **Data descoberta:** ~2025.
- **Aplica a stories:** 1.3 (chunker), 1.7a (chunk strategy).

---

## Q13-V

- **ID:** Q13-V (= R10 do MANIFEST)
- **Status:** ✅ validated
- **Categoria:** api / versionamento
- **Sintoma:** Funções V1 (`SendBuyOrder`, `GetOrders`, `SetTradeCallback`, etc.) ainda funcionam mas estão marcadas como obsoletas no manual e podem ser removidas em versões futuras.
- **Causa raiz:** Nelogica modernizou API com structs (V2) a partir de 4.0.0.18.
- **Evidência:** Manual marca cada V1 com "obsoleta em favor da nova função {V2}".
- **Workaround:** **sempre usar V2 quando existir**. Lista completa em `PROFITDLL_KNOWLEDGE.md` §2.1.
- **Manual diz:** explícito.
- **Aplica a stories:** todas que toquem trade ou callbacks de trade.

---

## Q14-E

- **ID:** Q14-E
- **Status:** 🔬 empirical
- **Categoria:** metadata
- **Sintoma:** Chamar `GetAgentName(buffer, ...)` sem alocar buffer correto causa buffer overrun.
- **Causa raiz:** desde 4.0.0.24, manual exige fluxo "length first":
  1. Chamar `GetAgentNameLength(id, shortFlag)` → retorna `length`
  2. Alocar buffer `length`
  3. Chamar `GetAgentName(length, id, buffer, shortFlag)` → preenche
- **Evidência:** Manual §3.1 linhas 1707-1729 documenta o pattern. Versões anteriores usavam `GetAgentNameByID` (DEPRECIADA) que retornava PWideChar direto.
- **Workaround:** sempre seguir length-first. **JAMAIS** chamar de dentro do callback (Q06-V).
- **Manual diz:** documenta o fluxo correto.
- **Data descoberta:** 4.0.0.24 release notes.
- **Aplica a stories:** futura (Epic 2 metadata enrichment), não Epic 1.

---

## Q15-OPEN

- **ID:** Q15-OPEN (finding **H4** de Pyro no Plan Review)
- **Status:** ❓ open
- **Categoria:** threading / queue
- **Sintoma:** Pergunta: quando o consumidor Python (engine thread) é mais lento que o produtor (ConnectorThread) e a fila interna de callbacks da DLL enche, **o que a DLL faz?**
  - Hipótese A: **drop silencioso** dos eventos novos (perda de dados sem error)
  - Hipótese B: **bloqueia** a ConnectorThread (back-pressure → toda a fila para)
  - Hipótese C: levanta `cosTimeout` ou `NL_QUEUE_FULL` em algum callback (estado de erro)
- **Causa raiz:** desconhecida. Manual silencioso sobre o comportamento de saturação da fila interna.
- **Evidência:** nenhuma — apenas inferência. Outros FFI similares (Bloomberg, MetaTrader) tendem a Hipótese B.
- **Workaround proposto (até probe):**
  - `dll_queue` (Python-side) com `maxsize=10000` + política `block` em `put`. Se DLL adota A, perdemos dados; se B, contém dano.
  - Logger de saturação em `engine` thread quando `dll_queue.qsize() > 0.8 * maxsize`.
- **Manual diz:** silencioso.
- **Probe proposto (Pyro Story 1.4.5 OU Dex Story 1.7a):**
  1. Mock writer que sleeps 5s (simula GC pause / disk freeze)
  2. Live trade subscription
  3. Contar trades antes/depois da pausa
  4. Verificar se algum NL_* error ou `cosTimeout` chega via state callback
  5. Comparar com taxa esperada (snapshot pré-pausa × duração)
- **Resposta detalhada:** ver [`OPEN_QUESTIONS_RESPONSES.md`](./OPEN_QUESTIONS_RESPONSES.md) Q1.
- **Data descoberta:** 2026-05-03 (Pyro plan review).
- **Aplica a stories:** 1.4.5 (probe), 1.7a (queue policy final).

---

## Q16-VALIDATED

- **ID:** Q16-VALIDATED
- **Status:** ✅ validated (com sub-status `reverse_engineered` — manual silente sobre auxiliary file)
- **Categoria:** auxiliary file / calendar
- **Sintoma:** Arquivo auxiliar `profitdll/DLLs/Win64/holidays.dat` distribuído com a DLL **omite feriados oficiais que caem em fim de semana** (sábado/domingo). Exemplos observados em 2025: `2025-09-07` Independência (domingo), `2025-10-12` Aparecida (domingo), `2025-11-02` Finados (domingo), `2025-11-15` Proclamação (sábado) — todos AUSENTES do DAT.
- **Causa raiz:** Provavelmente otimização Nelogica — já não há pregão nesses dias, então o arquivo (~34 KB, 843 linhas dados) lista apenas datas que afetariam pregão se fossem em dia útil. Especulação — manual silencioso sobre o critério.
- **Evidência:** Inspeção byte-a-byte do DAT distribuído em `2025-12-29 14:16:19.813` UTC (33 976 bytes, 843 linhas dados, cobertura 2013-2035). 100% das linhas com `OPEN` vazio que caem em FDS estão **ausentes**. Validado por ground truth comparison vs tabela B3 oficial publicada (`docs/dll/HOLIDAYS_DAT_FORMAT.md` §7).
- **Workaround:** Manter tabela hardcoded estendida (2020-2030) em `src/data_downloader/validation/calendar_b3.py` que **inclui** feriados FDS para completude semântica. Estratégia de **união parser ∪ hardcoded** captura superset semântico (caller pode querer saber "é feriado?" mesmo num fim de semana — gap detection conservadora).
- **Manual diz:** silencioso sobre `holidays.dat` (auxiliary file não documentado em `PROFITDLL_KNOWLEDGE.md` §1-8).
- **Data descoberta:** 2026-05-03 (Story 2.5 mini-council Sol+Nelo+Dex — COUNCIL-16).
- **Data validated:** 2026-05-04 (gate Quinn `*qa-gate 2.5` + Nelo `*audit` formato).
- **Validation source:** `reverse_engineered` (parser funcional via reverse engineering; **Q16-OPEN** mantido aberto para confirmação oficial Nelogica futura via `Nelo *probe-manual`).
- **Aplica a stories:** 2.5 (calendar B3 holidays.dat — esta story); futuro 4.X (multi-asset gap detection que dependa de calendar B3 estendido).
- **Refs:**
  - `src/data_downloader/validation/holidays_dat_parser.py` — parser
  - `src/data_downloader/validation/calendar_b3.py` — consumer + fallback
  - `docs/dll/HOLIDAYS_DAT_FORMAT.md` — formato byte-a-byte (Nelo authority)
  - `docs/decisions/COUNCIL-16-holidays-dat-integration.md` — sign-offs
  - `docs/qa/AUDIT_REPORTS/2.5-dll-2026-05-04.md` — esta validação

---

## Q17-OPEN

- **ID:** Q17-OPEN
- **Status:** ❓ open
- **Categoria:** licença / multi-process
- **Sintoma:** Pergunta: ao iniciar **N processos Python independentes** na **mesma máquina** com **mesma chave de licença Nelogica**, todos conseguem
  conectar (`MARKET_CONNECTED`) e baixar histórico simultaneamente?
  - Hipótese A: **OK** — licença é per-machine; N processos = N usos legítimos da mesma chave.
  - Hipótese B: **NL_LICENSE_BUSY** ou similar — licença é single-session; segundo init falha.
  - Hipótese C: **Funciona, mas com rate limit** — DLL conecta mas servidor degrada throughput por chave.
- **Causa raiz:** desconhecida. Manual silencioso. Política comercial Nelogica + comportamento DLL não documentados oficialmente.
- **Evidência:** nenhuma — apenas inferência. Q06-V regula thread model dentro de 1 processo, mas é silencioso sobre N processos.
- **Workaround proposto (até probe):**
  - Story 4.1 (broker process) **assume Hipótese A** (R20 conservador: 1 conexão por processo, N processos = N usos).
  - Implementação completa via mock (sem licença real); smoke real bloqueado por Story 4.1-followup pending humano.
  - Se probe revelar Hipótese B: Story 4.1 fica deprecated; novo ADR substitui (ex: 1 instância OS-wide com queue compartilhada).
- **Probe proposto (humano + Nelo):**
  1. Humano abre 2 terminais simultâneos.
  2. Em cada um, roda `data-downloader contracts validate WDO WDOJ26 --sample-date 2026-04-15` com mesmas credenciais.
  3. Observar se ambos conectam (state callback `MARKET_CONNECTED`) ou se segundo falha NL_LICENSE_BUSY.
  4. Bonus: rodar `data-downloader download --symbol WDOJ26 --symbol WINH26 --parallel 2 --start ... --end ...` (Story 4.1 multi-symbol) com ProfitDLL real para validar end-to-end.
- **Manual diz:** silencioso sobre licença multi-instance na mesma máquina.
- **Data descoberta:** 2026-05-04 (Story 4.1 implementação — mini-council COUNCIL-25).
- **Aplica a stories:** 4.1 (broker — hoje mock + WAIVER), 4.1-followup (smoke real — gating).
- **Refs:**
  - `docs/decisions/COUNCIL-25-multi-symbol-broker-impl.md` D5 (decisão de assumir Hipótese A pessimista)
  - `docs/stories/4.1-followup.story.md` (probe humano em AC1.2)
  - `docs/qa/WAIVERS/4.1-real-smoke-deferred-2026-05-04.md` (WAIVER que cobre esta open question)

---

## Q18-OPEN

- **ID:** Q18-OPEN
- **Status:** ❓ open
- **Categoria:** history / contract calendar
- **Sintoma:** Pergunta: a vigência exata dos contratos WIN trimestrais
  (H/M/U/Z) segue a regra B3 documentada — **vigente do 5º dia útil do
  mês X-3 até a quarta-feira mais próxima do dia 15 do mês X** — em
  todas as instâncias, ou há exceções por feriado / pregão estendido /
  decisão B3?
  - Hipótese A: Regra é determinística, todas as 8 entradas WIN no seed
    `CONTRACTS.md` §3 (WINH26..WINZ27) estão corretas dentro de ±1 dia.
  - Hipótese B: B3 muda calendário por feriado regional (Carnaval cai
    em fev/mar — afeta WINH); regra documentada é aproximação.
  - Hipótese C: Vigência efetiva é menor (último dia útil antes do
    vencimento, não o vencimento — diferença ~3 dias úteis).
- **Causa raiz:** desconhecida — Nelogica não documenta calendário de
  vencimento WIN; B3 publica calendário oficial mas formato não-machine-readable.
- **Evidência:** seed `CONTRACTS.md` §3 (Story 4.2) tem 8 entradas WIN
  com `validation_source=hypothesized`. Nenhuma confirmada por probe.
- **Workaround proposto (até probe):**
  - Story 4.2 — manter seed com `hypothesized`; AC3 prevê probe humano
    contra `WINH26 + 5 dias úteis` para validar primeira entrada.
  - Operadores que precisam de WIN antes do probe: usar `vigent_contract`
    com data dentro da janela hipotetizada; cross-check via DLL probe se
    `NL_INVALID_TICKER` aparece.
- **Probe proposto (humano + Nelo):**
  1. Para cada vencimento WIN (H/M/U/Z 26/27): rodar
     `data-downloader contracts validate --root WIN --year 2026` (Story 4.2 AC3).
  2. Cross-check com calendário B3 oficial PDF (humano + Nova).
  3. Atualizar `validation_source=dll_probe` ou `b3_calendar` quando
     confirmado.
- **Manual diz:** silencioso sobre calendário de vencimentos.
- **Data descoberta:** 2026-05-04 (Story 4.2 mini-council COUNCIL-29).
- **Aplica a stories:** 4.2 (multi-asset seed), 4.2-followup (smoke real
  WIN+equity humano).
- **Refs:**
  - `docs/storage/CONTRACTS.md` §2.2 + §3 (regra hipotetizada + entries seed)
  - `docs/decisions/COUNCIL-29-multi-asset-impl.md` (decisão de assumir
    Hipótese A com `hypothesized` source até probe humano)
  - `docs/qa/WAIVERS/4.2-real-smoke-deferred-2026-05-04.md` (WAIVER que
    cobre esta open question)

---

## Q-DRIFT-01

- **ID:** Q-DRIFT-01
- **Status:** 🔬 empirical
- **Categoria:** api drift (manual vs DLL real)
- **Sintoma:** Wrapper crashava com `AttributeError: function 'SetProgressCallback' not found` ao
  registrar callback de progresso. `GetDLLVersion` também não existe — wrapper já tinha try/except
  para retornar `"unknown"`.
- **Causa raiz:** o documento `PROFITDLL_KNOWLEDGE.md` foi populado a partir de leitura do manual
  + memória do agente Nelo, mas a DLL Win64 real (`profitdll/DLLs/Win64/ProfitDLL.dll`,
  inicializada com sucesso usando credenciais reais) NÃO exporta:
  - `SetProgressCallback` / `SetProgressCallbackV2` / `SetHistoryProgressCallback`
  - `GetDLLVersion` / `GetVersion`
- **Evidência:** probe ctypes via `getattr` (smoke 2026-05-04, após init+autenticação OK):
  ```python
  dll = ctypes.WinDLL('profitdll/DLLs/Win64/ProfitDLL.dll')
  for name in ['SetProgressCallback', 'SetProgressCallbackV2', 'GetDLLVersion', 'GetVersion']:
      try: getattr(dll, name); print(f'{name}: OK')
      except AttributeError: print(f'{name}: MISSING')
  # → todos MISSING
  # Funções OK: SetHistoryTradeCallbackV2, TranslateTrade, GetHistoryTrades,
  #            DLLInitializeMarketLogin, DLLFinalize, SetStateCallback, SetEnabledLogToDebug,
  #            SetTradeCallback, SetTradeCallbackV2, SetTinyBookCallback, GetServerClock, etc.
  ```
- **Cross-check Nelogica example** (`profitdll/Exemplo Python/main.py` L740-743): o
  `progressCallBack` é passado como **slot 10** de `DLLInitializeMarketLogin` no init —
  NÃO via função standalone:
  ```python
  result = profit_dll.DLLInitializeMarketLogin(
      key, user, password, stateCallback, None, newDailyCallback, None,
      None, None, progressCallBack, tinyBookCallBack
  )
  ```
- **Manual diz:** lista `SetProgressCallback` e `GetDLLVersion` (ou seja, ambíguo — manual e DLL
  real divergem). Possíveis causas: (a) versão do manual mais nova que a DLL fornecida;
  (b) função descontinuada entre releases; (c) erro de transcrição no manual.
- **Workaround:**
  - **`set_progress_callback`** (wrapper): try/except `AttributeError`. Se a função não existe,
    log warning + retorna sem erro. Downloads ainda completam — `download_primitive` detecta fim
    via **`TC_LAST_PACKET`** (bit 1 das flags V2, manual §3.2 L1912), independente de `progress=100`.
  - **`dll_version`** (wrapper): já gracioso desde Story 1.2 — retorna `"unknown"` em
    `AttributeError`/`OSError`. Metadata Parquet (Sol H19/H1) consome string `"unknown"` sem crash.
  - **`SetHistoryTradeCallbackV2`** (mantida): É exportada → mantém raise se sumir em release
    futura (signal de DLL incompatível, não graceful — fail-fast com mensagem Q-DRIFT).
- **Test reprodutor:** smoke executor (commit `153cf43`) com credenciais reais — bug B1.
- **Data descoberta:** 2026-05-04 (smoke executor, hotfix B1).
- **Próximo passo:** se progresso real for necessário em futuras stories, custom slot 10
  no `DLLInitializeMarketLogin` (em vez de Noop) — requer mudança em
  `wrapper.initialize_market_only` aceitar `progress_callback` opcional.
- **Aplica a stories:** 1.2 (init), 1.3 (history primitive), 1.7b (smoke MVP gate).
- **Refs:** `src/data_downloader/dll/wrapper.py:set_progress_callback`,
  `profitdll/Exemplo Python/main.py` L740-743, `docs/dll/PROFITDLL_KNOWLEDGE.md` §2.2.

---

## Q-DRIFT-02

- **ID:** Q-DRIFT-02
- **Status:** ⚠️ **CORRIGIDO** — hipótese ProfitChart REFUTADA pelo usuário; causa raiz real é signatures incorretas (ver Q-DRIFT-05). Mantido aqui pelo histórico do sintoma e ID estável.
- **Categoria:** lifecycle / handshake
- **Sintoma:** `wait_market_connected` retornava `False` (timeout) — DLL inicializa e
  autentica OK (recebe `(0,0)` LOGIN_CONNECTED, `(3,0)` MARKET_LOGIN_OK), mas o canal
  `MARKET_DATA` **fica em `(2, 1)` por minutos** sem evoluir para `(2, 4)`.
- **Hipótese descartada (V1.0 manhã 2026-05-04):** ⚠️ ProfitChart concorrente como pré-requisito.
  - **Refutada pelo usuário em 2026-05-04 tarde:** "não é tão difícil, o manual não está
    errado, muito menos o exemplo, basta segui-los."
  - Manual ProfitDLL pt_br pp.74-75 (seção "Uso do Produto / Inicializando com Market
    Data") **NÃO menciona ProfitChart** como pré-requisito.
  - Exemplo oficial `profitdll/Exemplo Python/main.py` linhas 729-764 (`dllStart`) **não
    abre ProfitChart**; apenas chama `DLLInitializeMarketLogin` + `SetXxxCallback`s e
    aguarda em `wait_login` (linha 568) por `bMarketConnected = True` que vem de
    `(conn_type=2, result=4)` (linhas 222-225 do `stateCallback`).
- **Causa raiz REAL (descoberta 2026-05-04 noite, investigação Nelo manual-first):**
  - Manual pp.13/55: `MARKET_CONNECTING = 1` significa **literalmente "Conectando ao
    servidor de market data"** — é estado de progresso normal. **NÃO é estado terminal.**
  - O handshake fica preso em `(2,1)` porque a **ConnectorThread interna da DLL provavelmente
    falha ao chamar UM dos NoopCallback que registramos** durante a sincronização inicial
    de market data, devido a **signatures ctypes incorretas**.
  - Detalhes técnicos completos em [Q-DRIFT-05](#q-drift-05).
  - Adicionalmente, [Q-DRIFT-06](#q-drift-06) refuta Q11-E ("JAMAIS passar None") — o exemplo
    oficial passa `None` em 4 dos 8 slots tranquilamente.
- **Evidência:**
  - Smoke #1 e #2 (commits `153cf43` e `4412d48`, 2026-05-04): travam em `(2,1)`.
  - Smoke #3 (log `docs/qa/SMOKE_EVIDENCE/logs/smoke1-attempt3-20260504T163934Z.log`):
    sequência observada `LOGIN_CONNECTED (0,0) → MARKET_LOGIN_OK (3,0) → MARKET_DATA/1
    (2,1) repetido 300s`. Manual diz `result=1` é `MARKET_CONNECTING`, ou seja: DLL
    **está tentando conectar** mas algo a impede de evoluir.
  - Comparação `src/data_downloader/dll/types.py` (NOSSO wrapper) vs
    `profitdll/Exemplo Python/main.py` (exemplo oficial Nelogica):
    - **NOSSO:** `TProgressCallback = WINFUNCTYPE(None, c_wchar_p, c_wchar_p, c_int, c_int)` (4 args primitivos)
    - **OFICIAL** (main.py L243): `@WINFUNCTYPE(None, TAssetID, c_int)` (TAssetID struct + 1 c_int)
  - Mesmo erro em `TTradeCallback`, `TDailyCallback`, `TPriceBookCallback`,
    `TOfferBookCallback`, `THistoryTradeCallback`, `TTinyBookCallback` — todos expandem
    `TAssetID` em 3 args primitivos quando deveriam ser **um único arg struct por valor**.
- **Mitigação correta (REVERTER):**
  - **Remover** documentação ProfitChart pré-requisito de `docs/release/INSTALL.md` §2.4.
  - **Remover** hint sobre ProfitChart de `docs/ux/MICROCOPY_CATALOG.md` §5
    `ERR_DLL_MARKET_TIMEOUT` (mensagem deve apenas dizer "MARKET_DATA não conectou — ver
    log para state codes").
  - **Corrigir signatures dos NoopCallback** (escopo Dex — ver Q-DRIFT-05 "Recomendação Dex").
- **Status code mapping (manual pp.13/55 confirma):**
  - `(2, 0)` = MARKET_DISCONNECTED — desconectado.
  - `(2, 1)` = **MARKET_CONNECTING — conectando ao servidor (estado de transição)**.
  - `(2, 2)` = MARKET_WAITING — esperando conexão (Q10-AMB; aceito empiricamente).
  - `(2, 3)` = MARKET_NOT_LOGGED — não logado.
  - `(2, 4)` = MARKET_CONNECTED — conectado ao market data **(único valor correto, manual p.55)**.
- **Data descoberta:** 2026-05-04 (smoke #1, hotfix B3 originalmente diagnosticado errado).
- **Data CORRIGIDO:** 2026-05-04 (investigação Nelo manual-first após smoke #3 + feedback usuário).
- **Aplica a stories:** 1.2 (wait_market_connected, NoopCallback signatures), 1.6 (probe),
  1.7b (CLI download), 4.4 (INSTALL.md — REMOVER §2.4 ProfitChart), todas smoke tests.
- **Refs:**
  - `src/data_downloader/dll/types.py` (signatures NOOP_SLOT_SIGNATURES — INCORRETAS, ver Q-DRIFT-05)
  - `src/data_downloader/dll/wrapper.py:wait_market_connected`
  - `profitdll/Exemplo Python/main.py` L195, L243, L324, L336, L346, L391, L440, L445 (signatures corretas)
  - `profitdll/Exemplo Python/profitTypes.py` L293-296 (TAssetID struct), L325-335 (TNewTradeCallback)
  - `docs/qa/SMOKE_EVIDENCE/logs/smoke1-attempt3-20260504T163934Z.log` (evidência de (2,1) por 300s)
  - Manual pp.13, 55, 74-75 (state codes + Uso do Produto — NÃO menciona ProfitChart).

---

## Q-DRIFT-03

- **ID:** Q-DRIFT-03
- **Status:** ✅ validated (corrigido)
- **Categoria:** config / env vars
- **Sintoma:** Smoke real falhava com "Credenciais ausentes" mesmo após preencher `.env`
  corretamente. `.env.example` define `PROFITDLL_KEY` / `PROFITDLL_USER` / `PROFITDLL_PASS`
  mas o código (cli.py, public_api/download.py, ui/) lia `PROFIT_USER` / `PROFIT_PASS`
  (sem prefixo). Tests adicionais usavam `PROFITDLL_PASSWORD` (terceira variante).
- **Causa raiz:** drift de naming durante implementação — agentes diferentes (Felix/UI,
  Dex/CLI, Quinn/smoke) usaram convenções distintas; nenhum ficou alinhado com
  `.env.example` original (Story 0.1).
- **Evidência:** `grep PROFIT_USER\|PROFITDLL_USER` em src/ tests/ mostrava 3 convenções
  coexistindo. `.env` real do usuário usa `PROFITDLL_PASS` (alinhado com example).
- **Decisão (mini-council Dex+Aria, 2026-05-04 hotfix):** padrão canônico é
  `PROFITDLL_KEY` / `PROFITDLL_USER` / `PROFITDLL_PASS` (alinhado com `.env.example`).
- **Workaround / fix:**
  - `cli.py` (escopo Dex hotfix): `PROFIT_USER` → `PROFITDLL_USER`,
    `PROFIT_PASS` → `PROFITDLL_PASS`.
  - `tests/smoke/*.py`: idem; `PROFITDLL_PASSWORD` → `PROFITDLL_PASS`.
  - `public_api/download.py` e `ui/*` (FORA do escopo deste hotfix): permanecem com
    `PROFIT_USER`/`PROFIT_PASS` — Aria deve abrir story de follow-up para padronizar
    sem violar fronteira `public_api` SemVer (deprecação ou alias env).
- **Manual diz:** N/A (config local do projeto).
- **Data descoberta:** 2026-05-04 (smoke executor, hotfix B2).
- **Aplica a stories:** 0.1 (env template), 1.7b (CLI), 4.0 (UI settings).
- **Refs:** `.env.example`, `src/data_downloader/cli.py:contracts_validate`,
  `tests/smoke/test_download_primitive_real.py`, `tests/smoke/test_probe.py`,
  `tests/smoke/test_mvp_gate.py`.

---

## Q-DRIFT-04

- **ID:** Q-DRIFT-04
- **Status:** 🔬 empirical
- **Categoria:** tooling / encoding
- **Sintoma:** `UnicodeEncodeError: 'charmap' codec can't encode character '✨'` ao
  emitir Rich Panel com emoji em terminal Windows default cp1252.
- **Causa raiz:** Windows cmd/PowerShell default encoding é cp1252; Rich emite caracteres
  unicode (emojis, box-drawing) que não cabem nessa code page. Python 3.7+ tem
  `sys.stdout.reconfigure(encoding=...)` que força UTF-8 sem reabrir os streams.
- **Evidência:** smoke executor (commit `153cf43`) — `UnicodeEncodeError cp1252 vs Rich emoji`.
- **Workaround (CLI startup):** em `data_downloader/cli.py`, ANTES de importar Rich:
  - `os.environ.setdefault("PYTHONIOENCODING", "utf-8")`
  - `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` (e `stderr`)
  - `errors="replace"` garante que mesmo se reconfigure falhar (subprocess pipe sem TTY),
    caracteres não-encodáveis viram `?` em vez de crash.
- **Alternativa não escolhida:** substituir emojis por ASCII art — perde fidelity da UX
  proposta por Uma (microcopy). Encoding fix é menos invasivo.
- **Manual diz:** N/A (problema de tooling Python/Windows).
- **Data descoberta:** 2026-05-04 (smoke executor, hotfix B4).
- **Aplica a stories:** todas com CLI Rich (1.6, 1.7b, 2.1, 2.9).
- **Refs:** `src/data_downloader/cli.py` topo do módulo.

---

## Q-DRIFT-05

- **ID:** Q-DRIFT-05
- **Status:** 🔬 **empirical** — root cause de Q-DRIFT-02. Aguarda fix no wrapper + smoke confirmação.
- **Categoria:** init / signatures ctypes / NoopCallback
- **Sintoma:** `wait_market_connected` trava em `(conn_type=2, result=1)` MARKET_CONNECTING
  por minutos, sem evoluir para `(2,4)` MARKET_CONNECTED. DLL inicializa OK, autentica OK,
  mas o canal de market data nunca conclui o handshake.
- **Causa raiz:** As 7 signatures `WINFUNCTYPE` em `src/data_downloader/dll/types.py`
  (`TTradeCallback`, `TDailyCallback`, `TPriceBookCallback`, `TOfferBookCallback`,
  `THistoryTradeCallback`, `TProgressCallback`, `TTinyBookCallback`) **EXPANDEM** o struct
  `TAssetID` em 3 args primitivos (`c_wchar_p, c_wchar_p, c_int` — ticker, bolsa, feed)
  quando o exemplo oficial Nelogica passa **`TAssetID` como struct por valor** (1 arg).
  - **Stdcall convention:** quando os args do callback Python diferem do que a DLL Delphi
    espera no stack frame, o stack pointer fica desalinhado após retorno do callback.
    Em 64-bit isso normalmente apenas corrompe valores; em alguns casos pode causar
    exception silenciosa interna na ConnectorThread, abortando o handshake de market data.
  - Provavelmente, durante a sincronização de market data, a DLL chama internamente um
    desses callbacks (ex.: TinyBook para ativo de teste, ou Daily snapshot) e o
    desalinhamento do stack causa erro silencioso, deixando o handshake preso em
    `MARKET_CONNECTING` (não progride para `MARKET_CONNECTED`).
- **Evidência (citações exatas):**
  - **Manual `Manual - ProfitDLL pt_br.pdf` p.55** (TStateCallback values): `MARKET_CONNECTING = 1`
    é literalmente "Conectando ao servidor de market data" — estado de progresso, não terminal.
  - **Exemplo oficial `profitdll/Exemplo Python/main.py`:**
    - L243: `@WINFUNCTYPE(None, TAssetID, c_int)` — `progressCallBack` recebe `TAssetID` STRUCT.
    - L336: `@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)` — `tinyBookCallBack` recebe TAssetID STRUCT + 3 args.
    - L346-347: `@WINFUNCTYPE(None, TAssetID, c_wchar_p, c_double × 12, c_int × 7)` — `newDailyCallback` recebe TAssetID STRUCT + 18 fields.
    - L391-392: `@WINFUNCTYPE(None, TAssetID, c_int, c_int, c_int, c_int, c_int, c_longlong, c_double, c_int × 5, c_wchar_p, POINTER(c_ubyte) × 2)` — `offerBookCallbackV2` recebe TAssetID STRUCT.
  - **Struct `TAssetID` (`profitTypes.py` L293-296):**
    ```python
    class TAssetID(Structure):
        _fields_ = [("ticker", c_wchar_p),
                    ("bolsa", c_wchar_p),
                    ("feed", c_int)]
    ```
    Quando passado por valor em stdcall, ocupa 1 slot lógico (struct), não 3 slots primitivos.
  - **NOSSO `src/data_downloader/dll/types.py` L122-237** (INCORRETO — expande TAssetID):
    - L122-136 `TTradeCallback`: `WINFUNCTYPE(None, c_wchar_p, c_wchar_p, c_int, c_wchar_p, c_uint, c_double, c_double, c_int, c_int, c_int, c_int, c_int)` — expande TAssetID em 3 primitivos + 9 demais.
    - L220-226 `TProgressCallback`: `WINFUNCTYPE(None, c_wchar_p, c_wchar_p, c_int, c_int)` — expande em 3 primitivos + nProgress (vs oficial: TAssetID + c_int = 2 args).
    - Mesmo erro em `TDailyCallback`, `TPriceBookCallback`, `TOfferBookCallback`, `THistoryTradeCallback`, `TTinyBookCallback`.
- **Workaround (recomendação para Dex):**
  1. Adicionar `TAssetID` Structure em `src/data_downloader/dll/types.py` (mirror exato de `profitTypes.py` L293-296).
  2. Reescrever as 7 signatures NOOP_SLOT_SIGNATURES espelhando EXATAMENTE o `@WINFUNCTYPE` do exemplo oficial:
     - Slot 5 trade (V1): `WINFUNCTYPE(None, TAssetID, c_wchar_p, c_uint, c_double, c_double, c_int, c_int, c_int, c_int, c_int)` (TAssetID + 10 args; ver `profitTypes.py` L325-335 TNewTradeCallback).
     - Slot 6 daily: `WINFUNCTYPE(None, TAssetID, c_wchar_p, c_double × 11, c_int × 7)` (main.py L346-347).
     - Slot 7 priceBook (DEPRECIADO, mas signature precisa estar ok): TAssetID + (vários — ver `profitTypes.py` L391+ se necessário).
     - Slot 8 offerBook V1: TAssetID + (vários — ver `profitTypes.py` L404+).
     - Slot 9 histTrade (V1): `WINFUNCTYPE(None, TAssetID, c_wchar_p, c_uint, c_double, c_double, c_int, c_int, c_int, c_int)` (sem `bIsEdit` — `profitTypes.py` L365-374 TNewHistoryCallback).
     - Slot 10 progress: `WINFUNCTYPE(None, TAssetID, c_int)` (main.py L243).
     - Slot 11 tinyBook: `WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)` (main.py L336).
  3. Considerar **opção alternativa segura**: passar `None` literal nos slots não-usados (como o exemplo oficial faz em main.py L742) — refuta Q11-E (ver Q-DRIFT-06). Isso elimina a necessidade de Noop e por consequência elimina risco de signatures erradas.
  4. **Smoke test:** após fix, rerun `tests/smoke/test_mvp_gate.py`. Esperar transição
     `(2,1) → (2,4)` em < 60s sem necessidade de ProfitChart concorrente.
- **Manual diz:** as **signatures dos callbacks** são tipos Delphi com `TAssetIDRec`
  (= `TAssetID` em ctypes Python) como primeiro arg de quase todos os callbacks de market
  data (manual §3.2 pp.55-71). Manual NÃO ensina a expandir struct em primitivos — isso
  foi assunção incorreta nossa.
- **Data descoberta:** 2026-05-04 (investigação Nelo manual-first após Q-DRIFT-02 ProfitChart REFUTADA).
- **Aplica a stories:** 1.2 (NoopCallback signatures), 1.7b (CLI smoke), 1.6 (probe).
- **Refs:**
  - `src/data_downloader/dll/types.py` (signatures NOOP_SLOT_SIGNATURES — corrigir).
  - `profitdll/Exemplo Python/main.py` L195, L243, L324, L336, L346-347, L391-392.
  - `profitdll/Exemplo Python/profitTypes.py` L293-296 (TAssetID), L325-335 (TNewTrade), L342-361 (TNewDaily), L378-381 (TProgress), L383-389 (TTinyBook).
  - `docs/qa/SMOKE_EVIDENCE/logs/smoke1-attempt3-20260504T163934Z.log` (evidência (2,1) por 300s).

---

## Q-DRIFT-06

- **ID:** Q-DRIFT-06
- **Status:** ⚠️ **CORRECTED** — refuta Q11-E (Sentinel §12 / Story 1.2 AC2).
- **Categoria:** init / NoopCallback policy
- **Sintoma:** Story 1.2 implementou `NoopCallback` em todos os 7 slots não-state de
  `DLLInitializeMarketLogin` baseando-se em Q11-E ("JAMAIS passar None — corrompe
  registro interno e Set*Callback posterior nunca dispara").
- **Causa raiz da regra incorreta:** Q11-E é uma observação empírica do Sentinel (~2025)
  que provavelmente combinava signatures incorretas + `None` em slots — atribuiu a culpa
  ao `None` quando provavelmente era o desalinhamento de stdcall (ver Q-DRIFT-05).
- **Refutação direta com fonte primária:**
  - **`profitdll/Exemplo Python/main.py` L742-743** (chamada oficial Nelogica):
    ```python
    result = profit_dll.DLLInitializeMarketLogin(
        c_wchar_p(key), c_wchar_p(user), c_wchar_p(password),
        stateCallback, None, newDailyCallback, None,
        None, None, progressCallBack, tinyBookCallBack
    )
    ```
  - O exemplo passa `None` em **4 dos 8 slots de callback** (slot 5 trade, slot 7
    priceBook, slot 8 offerBook, slot 9 histTrade) e ainda assim a DLL conecta + funciona.
  - Em main.py L745-761, callbacks adicionais são registrados via `SetXxxCallback` AFTER
    init (`SetTradeCallbackV2`, `SetOfferBookCallbackV2`, `SetHistoryTradeCallbackV2`,
    etc.) — isso PROVA que os slots passados como `None` no init NÃO impedem o registro
    posterior via `SetXxxCallback`.
- **Workaround (decisão):** Aceitar `None` como valor válido para slots não-usados.
  Eliminar `make_noop_callback` factory ou mantê-la apenas como opcional (não default).
- **Decisão para Dex:** o caminho mais simples e fiel ao exemplo oficial é:
  1. Para slot 4 (state): SEMPRE callback real (estado de conexão é obrigatório).
  2. Para slots 5-11: passar `None` literal por padrão; usar callback real APENAS quando a
     story precisa daquele dado (ex.: Story 1.3 usa slot 9 histTrade ou registra via
     `SetHistoryTradeCallbackV2` AFTER init).
  3. Atualizar `Q11-E` em QUIRKS.md como ⚠️ REFUTADO / superseded por Q-DRIFT-06.
- **Atenção (NÃO ALTERAR sem nova evidência):** Story 1.2 AC2 e o Sentinel §12 falam em
  semanas de debugging por causa de None. Pode haver edge case que o exemplo oficial não
  cobre. **Implementação recomendada conservadora:** começar passando `None` (como exemplo
  oficial), e se algum callback "set posteriormente" não disparar, voltar atrás caso-a-caso.
- **Manual diz:** Manual pp.22-23 lista os callbacks de `DLLInitializeMarketLogin` SEM
  marcar quais são opcionais — descrição diz "callbacks obrigatórios" (p.74), mas o
  exemplo oficial contradiz claramente passando `None`. Esta é uma divergência real
  manual ↔ exemplo, mas o **exemplo é a fonte canônica de uso** (manual descreve a API
  Delphi; exemplo demonstra a API Python).
- **Data descoberta:** 2026-05-04 (investigação Nelo durante root-cause de Q-DRIFT-02).
- **Aplica a stories:** 1.2 (AC2 — relaxar regra "JAMAIS None"), 1.7b, 1.3.
- **Refs:**
  - `profitdll/Exemplo Python/main.py` L738-743 (`DLLInitializeLogin` e `DLLInitializeMarketLogin` com `None` em 4-7 slots).
  - `profitdll/Exemplo Python/main.py` L745-761 (callbacks registrados via `SetXxxCallback` AFTER init).
  - Q11-E (Sentinel §12) — SUPERSEDED.

---

## Q-DRIFT-07

- **ID:** Q-DRIFT-07
- **Status:** ✅ validated (autoridade Nelogica direta — usuário confirmou em 2026-05-04)
- **Categoria:** history / subscription
- **Sintoma:** `GetHistoryTrades(ticker, exchange, dt_start, dt_end)` retorna `NL_OK` mas `HistoryTradeCallbackV2` **nunca dispara** — IngestorThread fica esperando, deadline atinge timeout, chunk falha em `status='timeout'` sem trades.
- **Causa raiz:** `SubscribeTicker(ticker, exchange)` é **pré-requisito** para qualquer recepção de dados (live OU histórico). Sem o subscribe, a DLL aceita o `GetHistoryTrades` (não retorna erro) mas o feed do asset nunca é estabelecido na sessão, então o callback V2 nunca é chamado.
- **Evidência:**
  - Confirmação do usuário (autoridade ProfitDLL real, 2026-05-04): "para baixar WDOJ26, primeiro `SubscribeTicker('WDOJ26', 'F')`".
  - Exemplo oficial Nelogica `profitdll/Exemplo Python/main.py:590-595` define `subscribeTicker()` separadamente; usuário do REPL invoca `subscribe` ANTES de `GetHistoryTrades`.
  - Manual §3.1 lista `SubscribeTicker` como obrigatório para receber callbacks de trade do asset.
- **Workaround:**
  ```python
  # ANTES de GetHistoryTrades:
  ret = dll.SubscribeTicker(c_wchar_p(symbol), c_wchar_p(exchange))
  if ret < 0:
      raise DLLError(...)

  # ... configurar callbacks, chamar GetHistoryTrades, drenar ...

  # APÓS o chunk:
  dll.UnsubscribeTicker(c_wchar_p(symbol), c_wchar_p(exchange))
  ```
  Argtypes: `dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; dll.SubscribeTicker.restype = c_int`.
- **Manual diz:** §3.1 documenta `SubscribeTicker` como função pública. Exemplo oficial usa.
- **Data descoberta:** 2026-05-04 (auditoria Nelo após feedback usuário sobre falha de download MVP).
- **Aplica a stories:** 1.3 (download_primitive — adicionar subscribe), 1.7b (smoke), todas que envolvam `GetHistoryTrades` ou trade live.
- **Refs:**
  - `profitdll/Exemplo Python/main.py` L590-595 (`subscribeTicker`), L753 (`SetTradeCallbackV2` registrado APÓS init).
  - `docs/qa/AUDIT_REPORTS/dll-full-audit-2026-05-04.md` CRIT-1 + HIGH-5.

---

## Q-DRIFT-08

- **ID:** Q-DRIFT-08
- **Status:** 🔬 empirical
- **Categoria:** ctypes / argtypes drift
- **Sintoma:** `TranslateTrade(handle, struct)` pode retornar lixo OU acessar memória inválida em x64; valores de retorno `c_int64` (e.g. `SendOrder` LocalOrderID) podem chegar truncados; `c_size_t` handles passados a `TranslateTrade` podem ser truncados em 32 bits.
- **Causa raiz:** Nosso wrapper (`src/data_downloader/dll/wrapper.py`) NUNCA configura `dll.foo.argtypes = [...]` nem `dll.foo.restype = ...` em **nenhuma** função. O exemplo oficial Nelogica em `profitdll/Exemplo Python/profit_dll.py` configura argtypes/restype para ~30 funções. Sem isso, ctypes default usa `c_int` para args/restype, o que:
  - Trunca `c_int64` (e.g. handles `c_size_t` em x64).
  - Desalinha o stack frame stdcall em chamadas com `POINTER(struct)` (ctypes vê `int`, Delphi espera `Pointer`).
- **Evidência:**
  - `grep -rn "argtypes\|restype" src/data_downloader/dll/` retorna zero ocorrências reais (apenas comentários).
  - `profitdll/Exemplo Python/profit_dll.py` L7-101 configura 30+ funções incluindo `TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]; .restype = c_int`.
- **Workaround:** criar método `_configure_argtypes(self)` em `ProfitDLL` chamado logo após `WinDLL(path)` e antes de qualquer outra chamada. Replicar literalmente as entradas de `profit_dll.py` (port para nossos tipos em `dll/types.py`). Mínimo absoluto (V1 download):
  ```python
  dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]; dll.TranslateTrade.restype = c_int
  dll.GetHistoryTrades.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]; dll.GetHistoryTrades.restype = c_int
  dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; dll.SubscribeTicker.restype = c_int
  dll.UnsubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]; dll.UnsubscribeTicker.restype = c_int
  dll.GetAgentNameLength.argtypes = [c_int, c_int]; dll.GetAgentNameLength.restype = c_int
  dll.GetAgentName.argtypes = [c_int, c_int, c_wchar_p, c_int]; dll.GetAgentName.restype = c_int
  dll.SetEnabledLogToDebug.argtypes = [c_int]; dll.SetEnabledLogToDebug.restype = c_int
  dll.DLLInitializeMarketLogin.restype = c_int
  dll.DLLFinalize.restype = c_int
  ```
- **Manual diz:** Manual §4 fala de stdcall + tipos Delphi exatos; `profit_dll.py` é a referência canônica concreta.
- **Data descoberta:** 2026-05-04 (auditoria Nelo manual-first).
- **Aplica a stories:** 1.2 (init), 1.3 (download), todas que chamem funções da DLL.
- **Refs:**
  - `profitdll/Exemplo Python/profit_dll.py` L7-101.
  - `docs/qa/AUDIT_REPORTS/dll-full-audit-2026-05-04.md` CRIT-2 + MED-4.

---

## Q-DRIFT-09

- **ID:** Q-DRIFT-09
- **Status:** 🔬 **empirical → hipótese forte aguardando fix-and-rerun**
- **Categoria:** callback / signatures (mesma classe de Q-DRIFT-05, agora nos 14 `SetXxx`)
- **Sintoma:** Smoke 5 (`tests/smoke/test_smoke5_*`) progride normalmente:
  - DLL carrega OK
  - `DLLInitializeMarketLogin` retorna `NL_OK`
  - State callback recebe `(0,0) LOGIN_OK`, `(3,0) MARKET_LOGIN_OK`, `LOGIN_CONNECTED`
  - Em seguida, durante `wait_market_connected`, processo crasha com **múltiplas Access Violations + 1 Stack Overflow**.
  - **Importante:** crash NÃO ocorre em `result=4` (`MARKET_CONNECTED`) — ocorre antes, durante o handshake interno onde a DLL começa a invocar callbacks de market data (asset list, daily, etc.).
- **Causa raiz hipotética:** o squad registra 14 callbacks via `SetXxx` (ver `dllStart()` em `main.py` L745-761) usando `NoopCallback` placeholders. Se a signature de QUALQUER um desses 14 NoopCallbacks divergir da signature canônica esperada pela DLL (extraída do exemplo Nelogica e tabulada em `PROFITDLL_KNOWLEDGE.md` §3.3), quando a DLL invocar o callback ela passa argumentos no stack que ctypes interpreta errado → leitura de memória inválida → Access Violation. Stack Overflow específico sugere recursão acidental por callback que devolve controle errado (talvez `restype` errado faz a DLL re-invocar). **Mesma classe do Q-DRIFT-05 (que afetou os Noop slots de `DLLInitializeMarketLogin`); agora suspeito-se em todos os 14 `SetXxx`.**
- **Evidência:**
  - Smoke 5 logs (sessão 2026-05-04): 14 access violations seguidas de 1 stack overflow durante boot.
  - LOGIN/MARKET_LOGIN succeeded — DLL conseguiu autenticar e estabelecer canal. Crash veio na fase pós-login, exatamente quando DLL começa a empurrar dados para callbacks (asset list é tipicamente o primeiro `SetAssetListCallback`).
  - Tabela §3.3 de `PROFITDLL_KNOWLEDGE.md` confirma que 5 callbacks usam `TAssetID` por valor (struct legado, mesmo bug class de Q-DRIFT-05), 3 usam `TConnectorAssetIdentifier` por valor, 3 usam `TConnectorAccountIdentifier` por valor — **9 dos 14 são structs por valor**, alta superfície de erro.
  - Exemplo oficial Nelogica passa `None` em 4 dos 8 slots de `DLLInitializeMarketLogin` sem crash (Q-DRIFT-06), o que sugere que `None` é aceitável como "no-op" pela DLL nos casos onde o exemplo o usa. **Não é confirmado** que `SetXxx(None)` é válido — o exemplo SEMPRE passa um callback real nos 14 `SetXxx`. Validar empiricamente.
- **Refuta parcialmente Q11-E:** Q11-E (Sentinel §12) dizia "JAMAIS passar None — corrompe SetHistoryTradeCallback". Q-DRIFT-06 já refutou para `DLLInitializeMarketLogin`. Q-DRIFT-09 sugere agora que **passar `None` em `SetXxx` não-críticos pode ser MAIS SEGURO que NoopCallback errado** (porque NoopCallback errado garantidamente crasha quando DLL invoca, enquanto `None` no pior caso é rejeitado com erro retornável OU silenciosamente ignorado). **Validar empiricamente** — não promover ainda a "validated".
- **Workaround proposto (3 opções, ver §"Recomendação para Dex"):** A) implementar 14 signatures corretas; B) passar `None` em vez de NoopCallback; C) **não registrar `SetXxx` que não usamos** (preferida — exemplo registra todos porque a UI exemplifica todos; data-downloader V1 só precisa de download histórico, então só `SetTradeCallbackV2` + `SetHistoryTradeCallbackV2` + `SetStateCallback` são necessários).
- **Manual diz:** §3.2 documenta cada `SetXxx` como função pública. Manual NÃO obriga registrar todos — registrar só os que se usa é prática válida (deduzido do silêncio do manual + Q-DRIFT-06 que provou ser permissivo com slots não-usados em `DLLInitializeMarketLogin`).
- **Data descoberta:** 2026-05-04 (smoke 5 pós Q-DRIFT-05 fix; investigação Nelo).
- **Aplica a stories:** 1.2 (init / Sentinel §12 violations), 1.7b (smoke), todas que tocam `SetXxxCallback`.

### Recomendação para Dex (paralelo agent)

Três opções para resolver Q-DRIFT-09 — Nelo recomenda **C** com fallback **B**.

#### Opção A — Implementar todas 14 signatures corretas

- **O que fazer:** copiar literalmente as 14 entradas de `PROFITDLL_KNOWLEDGE.md §3.3` para `src/data_downloader/dll/types.py` e registrar cada NoopCallback com a signature exata.
- **Prós:**
  - Determinístico — se signatures estão certas, DLL nunca crasha por isso.
  - Espelha 100% o exemplo oficial.
  - Permite reaproveitar callbacks reais no futuro (live mode, Sol, etc.) sem mudar lifecycle.
- **Contras:**
  - Escala alta — 14 signatures, várias com 9-16 args. Cada erro pequeno (`c_int` vs `c_long`, `c_ubyte` vs `c_int`) pode reintroduzir Q-DRIFT-09.
  - 5 callbacks com `TAssetID` por valor — alta probabilidade de erro de iniciante (Q-DRIFT-05 já mostrou).
  - Demora para validar (cada commit = smoke run completo).
  - **YAGNI** — V1 só precisa de download histórico; 12 dos 14 callbacks são para features (book, ordens, broker accounts) que V1 não usa.

#### Opção B — Passar `None` em vez de NoopCallback

- **O que fazer:** `dll.SetAssetListCallback(None)` para cada um dos 14. Não criar Noop nenhum.
- **Prós:**
  - Zero superfície de bug por signature errada.
  - Simples — uma linha por callback.
  - Refuta empiricamente Q11-E para `SetXxx` (alavanca Q-DRIFT-06 que já refutou para `DLLInitializeMarketLogin`).
- **Contras:**
  - **Não confirmado** que `SetXxx(None)` é aceitável — o exemplo Nelogica SEMPRE passa callback real. Pode ser que `SetXxx` valide `LPVOID != NULL` antes de aceitar, ou pior, aceite `None`, salve `NULL` internamente e crashe quando for invocar.
  - Mistura de tipo — ctypes pode reclamar (`SetXxx` espera `WINFUNCTYPE(...)`, não `None`); mitigação: `argtypes = [WINFUNCTYPE(...)]` aceita `None` como `NULL` em ctypes (verificado).
  - Risco médio — vale tentar SE C não for viável.

#### Opção C — Não registrar SetXxxCallback que não usamos (RECOMENDADA pela Nelo)

- **O que fazer:** dos 14 `SetXxx`, **chamar APENAS os necessários para download histórico**:
  - `SetStateCallback` (já registrado via `DLLInitializeMarketLogin` — não conta como "SetXxx").
  - `SetHistoryTradeCallbackV2` (CORE — recebe os trades históricos).
  - `SetTradeCallbackV2` (necessário se a DLL exigir registrar live trade callback antes de `SubscribeTicker`; **Nelo: validar com probe** — exemplo oficial registra; segurança extra).
  - **Os outros 12 não chamar** — não chamar `SetAssetListCallback`, `SetOfferBookCallbackV2`, `SetOrderCallback`, etc.
- **Prós:**
  - **Mínimo de superfície** — só 1-2 NoopCallbacks para revisar (ou nenhum, se `SetTradeCallbackV2` for o callback real).
  - Alinha com **YAGNI**: V1 = download histórico apenas. Book, ordens, broker accounts, position list = V2+.
  - Exemplo oficial registra todos porque o REPL `main.py` expõe TODAS as features ao usuário interativo. Nosso CLI download não precisa.
  - Eliminação completa de Q-DRIFT-09 com mudança mínima de código.
- **Contras:**
  - Suposição implícita: DLL não exige `SetXxx` para callbacks não-usados (nunca convida o callback porque a feature não foi acionada). **Manual silencioso aqui** — confirma com smoke run.
  - Quando V2 (live mode, Sol broadcasting) chegar, adicionar `SetXxx` reais um a um, com signature exata copiada de §3.3.

### Recomendação Nelo (síntese)

> **Implementar Opção C imediatamente** (remover 12 dos 14 `SetXxx`; manter só `SetHistoryTradeCallbackV2` + `SetTradeCallbackV2` se este último for necessário). Smoke 6 deve passar `wait_market_connected` sem access violations.
>
> Se Smoke 6 ainda crashar nos 1-2 callbacks restantes, Opção A para esses 1-2 (signature exata de §3.3 — `SetTradeCallbackV2`: `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)`).
>
> Opção B (passar `None`) só como **probe diagnóstico** caso A+C não resolvam — comparar comportamento `None` vs Noop-com-signature-correta para esclarecer Q11-E definitivamente.
>
> **NÃO** começar pela Opção A para os 14 — desperdício de esforço (12 callbacks são YAGNI) e alta superfície de re-bug.

- **Refs:**
  - `PROFITDLL_KNOWLEDGE.md` §3.3 — tabela canônica das 14 signatures.
  - `profitdll/Exemplo Python/main.py` L745-L761 — bloco que registra os 14 (modelo).
  - Q-DRIFT-05 — bug class "TAssetID expandido em primitivos" (precedente nos Noop slots).
  - Q-DRIFT-06 — refuta Q11-E para `DLLInitializeMarketLogin`; alavanca para Opção B.
  - Q11-E — agora **duplamente questionado** (refutado para init em Q-DRIFT-06; refuta parcial para `SetXxx` aqui).
  - `tests/smoke/` — pasta dos smokes.
  - `src/data_downloader/dll/wrapper.py` (escopo Dex — bloco `SetXxx` a auditar/reduzir).

---

## Q-DRIFT-10

- **ID:** Q-DRIFT-10
- **Status:** 🔬 **empirical → hipótese forte aguardando fix-and-rerun**
- **Categoria:** init / divergência audit linha-por-linha vs exemplo oficial
- **Sintoma (smoke 6, commit `7badeea` — 2026-05-04 noite):**
  - DLL carrega ✅
  - argtypes/restype configurados (25 funcs) ✅
  - `DLLInitializeMarketLogin` retorna `code=0` (NL_OK) ✅
  - State callback recebe `MARKET_LOGIN_OK (3,0)` ✅
  - State callback recebe `LOGIN_CONNECTED (0,0)` ✅
  - **`MARKET_DATA` fica em `(conn_type=2, result=1)` MARKET_CONNECTING — NUNCA evolui para `(2,4)` MARKET_CONNECTED** ❌
  - Manual p.55 confirma: `MARKET_CONNECTED=4` é o ÚNICO valor terminal correto.
  - Autoridade ProfitDLL real (usuário): "se MARKET_DATA não está conectando, é erro na função de inicialização". NÃO é horário pós-pregão, NÃO é flakiness.

### Audit linha-por-linha — `initialize_market_only` vs `dllStart()` (main.py L729-764)

| Item | Exemplo Nelogica (main.py) | Nosso wrapper (`wrapper.py`) | Diverge? |
|------|---------------------------|------------------------------|----------|
| **A1. Slot 4 (state)** | `stateCallback` REAL (`@WINFUNCTYPE(None, c_int32, c_int32)` L195) | `make_state_callback(queue)` REAL (`TStateCallback`) | ✅ EQUAL |
| **A2. Slot 5 (NewTradeCallback)** | **`None`** (L742) | `make_noop_callback(TTradeCallback)` (10 args c/ TAssetID) | ❌ DIVERGE |
| **A3. Slot 6 (NewDailyCallback)** | `newDailyCallback` REAL (L348, 19 args) | `make_noop_callback(TDailyCallback)` (Noop) | ⚠️ DIVERGE (real vs noop) |
| **A4. Slot 7 (PriceBookCallback)** | **`None`** (L742) | `make_noop_callback(TPriceBookCallback)` | ❌ DIVERGE |
| **A5. Slot 8 (OfferBookCallback)** | **`None`** (L743) | `make_noop_callback(TOfferBookCallback)` | ❌ DIVERGE |
| **A6. Slot 9 (HistoryTradeCallback)** | **`None`** (L743) | `make_noop_callback(THistoryTradeCallback)` | ❌ DIVERGE |
| **A7. Slot 10 (ProgressCallback)** | `progressCallBack` REAL (L243-246, `@WINFUNCTYPE(None, TAssetID, c_int)`) | `make_noop_callback(TProgressCallback)` (Noop, mesma sig) | ⚠️ DIVERGE (real vs noop) |
| **A8. Slot 11 (TinyBookCallback)** | `tinyBookCallBack` REAL (L336-343, `@WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)`) | `make_noop_callback(TTinyBookCallback)` (Noop, mesma sig) | ⚠️ DIVERGE (real vs noop) |
| **B1. SetEnabledLogToDebug** | **NÃO chamado** (grep: 0 matches em main.py) | Chamado com `0` ANTES do init (`wrapper.py:579`) | ❌ DIVERGE |
| **B2. argtypes/restype** | Setados em `profit_dll.initializeDll(path)` ANTES de qualquer chamada (`profit_dll.py:7-101`) | Setados em `_configure_dll_signatures()` após `WinDLL()`, antes do init | ✅ EQUAL (semântico) |
| **C1. Ordem do init** | `WinDLL → initializeDll(argtypes) → DLLInitializeMarketLogin → SetXxx(14) → wait_login` | `verify_companions → WinDLL → _configure_dll_signatures → SetEnabledLogToDebug(0) → DLLInitializeMarketLogin → wait_market_connected` | ❌ DIVERGE (sem 14 `SetXxx` antes do wait) |
| **D1. Cast c_wchar_p** | `c_wchar_p(key), c_wchar_p(user), c_wchar_p(password)` (L742) | `c_wchar_p(key), c_wchar_p(user), c_wchar_p(password)` (`wrapper.py:619-622`) | ✅ EQUAL |
| **D2. Argtypes do init** | Não setados explicitamente (ctypes infere por valor passado) | `argtypes=None, restype=c_int` (`wrapper.py:333`) | ✅ EQUAL (semântico) |
| **E1. Total de args** | 11 args (3 wchar + 8 callback slots) | 11 args (3 wchar + state + 7 noop) | ✅ EQUAL (count) |
| **E2. _cb_refs anti-GC** | Funções globais com `@WINFUNCTYPE` (escopo módulo permanente) | `callbacks._cb_refs` lista global + `self._cb_refs` instância (cinto-suspensório) | ✅ EQUAL (semântico — anti-GC garantido) |
| **F1. SetXxxCallback antes do wait** | **14 chamados** (L745-761): `SetAssetListCallback`, `SetAdjustHistoryCallbackV2`, `SetAssetListInfoCallback`, `SetAssetListInfoCallbackV2`, `SetOfferBookCallbackV2`, `SetOrderCallback`, `SetOrderHistoryCallback`, `SetInvalidTickerCallback`, `SetTradeCallbackV2`, `SetAssetPositionListCallback`, `SetBrokerAccountListChangedCallback`, `SetBrokerSubAccountListChangedCallback`, `SetPriceDepthCallback`, `SetTradingMessageResultCallback` | **0 chamados** (default `register_extra_callbacks=False` desde smoke 5 / Q-DRIFT-09) | ❌ DIVERGE |
| **F2. Modo do init** | Por default usa `DLLInitializeLogin` (com roteamento, `bRoteamento=True`, L735); `DLLInitializeMarketLogin` é o branch `else` (L742) | `DLLInitializeMarketLogin` (market-only) | ⚠️ DIVERGE intencional (nosso caso de uso é market-only — não é candidato à causa raiz, mas registrado) |

### 3 candidatos por confiança (Nelo)

#### 🥇 #1 (60% confiança) — `None` literal nos slots 5/7/8/9 (alavanca Q-DRIFT-06)

- **Hipótese:** A DLL **valida o ponteiro do callback durante o handshake interno do MARKET_DATA** (não só na hora de invocar). Quando recebe um trampoline ctypes com signature divergente da esperada (mesmo Noop, mesmo nunca-disparado), o validador interno da Nelogica detecta mismatch via algum heurístico (tabela de hash de signatures? leitura prévia de stack frame size?) e **bloqueia a transição `(2,1) → (2,4)` silenciosamente** sem nunca crashar nem retornar erro.
- **Evidência:**
  - Q-DRIFT-06 (refutação Q11-E): exemplo oficial passa `None` em 4 slots **e a DLL conecta**.
  - Q-DRIFT-05 fixou as signatures dos Noop (TAssetID por valor), mas o smoke 6 ainda trava — **se o problema fosse só signature errada, smoke 6 passaria**. O fato de não passar sugere que a presença do Noop em si (mesmo signature certa) é o problema.
  - Manual p.74 diz callbacks são "obrigatórios" mas exemplo contradiz — **exemplo é a fonte canônica de uso Python**.
- **Por que NÃO 100%:** ainda não temos evidência empírica direta de que substituir Noop por `None` resolve. É a divergência mais óbvia, mas não é prova.

#### 🥈 #2 (25% confiança) — Faltam `SetTradeCallbackV2` + `SetAssetListCallback` antes do wait

- **Hipótese:** A DLL precisa que **pelo menos 1-2 `SetXxxCallback` reais estejam registrados** antes de evoluir o handshake do market data. Sem nenhum `SetXxxCallback` o servidor pode não enviar o pacote de "first asset list" / "first trade" que destrava `(2,4)`.
- **Evidência indireta:** exemplo SEMPRE registra os 14 antes do `wait_login`. Pode ser ritualismo, mas pode ser requisito não documentado.
- **Por que NÃO #1:** Q-DRIFT-09 mostrou que registrar os 14 com Noop signatures crasha. Se fosse só "registre algo", então Noop bastaria — mas Noop crashou. Isso sugere que o requisito (se existe) é **callback real com signature correta**, não qualquer Noop. Custo de validar: alto (precisa implementar 1-2 callbacks reais primeiro).

#### 🥉 #3 (10% confiança) — `SetEnabledLogToDebug(0)` antes do init confunde a DLL

- **Hipótese:** Chamar `SetEnabledLogToDebug(0)` ANTES de `DLLInitializeMarketLogin` toca estado interno da DLL antes que esteja pronta — talvez a DLL inicialize variáveis de log no `Initialize` e nossa chamada prévia as zere. Exemplo NÃO chama esta função (zero matches em main.py).
- **Por que NÃO #1:** smoke logs de 1.7b mostram que `dll.native_log_silenced` aparece e `DLLInitializeMarketLogin` retorna `code=0` — se houvesse corrupção, o init provavelmente já falharia. Custo de validar: trivial (comentar 1 linha).

#### Outros candidatos descartados

- **(d) Cast `c_wchar_p` errado** — ✅ EQUAL ao exemplo, descartado.
- **(e) NoopCallback signature errada (Q-DRIFT-05 não fixou)** — improvável: `TProgressCallback`, `TTinyBookCallback`, `TDailyCallback` em `types.py` L242/L250/L165 batem literalmente com `@WINFUNCTYPE` de main.py L243/L336/L346 (TAssetID por valor). Q-DRIFT-05 já corrigiu.
- **(f) DLLInitializeLogin (14 args) vs DLLInitializeMarketLogin (11 args)** — exemplo usa o de 14 args por default (`bRoteamento=True`), mas o de 11 args TAMBÉM existe (branch `else` L742) — não é candidato à causa raiz.

### Recomendação para Dex (linha exata a mudar)

**Implementar #1 PRIMEIRO** (mudança mínima, alavanca Q-DRIFT-06 já validado em fonte primária):

**Arquivo:** `src/data_downloader/dll/wrapper.py`
**Linhas:** 590-625 (bloco "AC2 — construir 8 callbacks" + chamada `DLLInitializeMarketLogin`)

**Mudança proposta (espelhar literalmente main.py L742-743):**

```python
# AC2 — REVISADO Q-DRIFT-10: espelhar exemplo oficial (main.py L742-743).
# Exemplo passa None em 4 dos 7 slots não-state. Q-DRIFT-06 já refutou
# Q11-E ("JAMAIS None"). Hipótese primária Q-DRIFT-10: DLL valida
# signature do callback no handshake (não só no fire), e Noop com
# signature divergente impede MARKET_DATA → (2,4).
state_cb = make_state_callback(self._state_queue)
# Slot 5 (trade), 7 (priceBook), 8 (offerBook), 9 (histTrade) = None
# (alinhado main.py L742-743). Slots 6 (daily), 10 (progress), 11
# (tinyBook) = Noop com signature correta (Q-DRIFT-05 fixou).
daily_cb = make_noop_callback(TDailyCallback)
progress_cb = make_noop_callback(TProgressCallback)
tinybook_cb = make_noop_callback(TTinyBookCallback)

ret: int = self._dll.DLLInitializeMarketLogin(
    c_wchar_p(key),
    c_wchar_p(user),
    c_wchar_p(password),
    state_cb,        # slot 4 — REAL (state)
    None,            # slot 5 — trade (None, exemplo L742)
    daily_cb,        # slot 6 — daily (exemplo passa REAL; aqui Noop com sig certa)
    None,            # slot 7 — priceBook (None, exemplo L742)
    None,            # slot 8 — offerBook (None, exemplo L743)
    None,            # slot 9 — histTrade (None, exemplo L743)
    progress_cb,     # slot 10 — progress (Noop, sig OK)
    tinybook_cb,     # slot 11 — tinyBook (Noop, sig OK)
)
```

**Pré-requisito ctypes:** verificar que `argtypes=None` (já é o caso em `wrapper.py:333`) permite `None` literal — ctypes aceita `None` como `NULL` para `WINFUNCTYPE` quando `argtypes` não força tipo. Confirmar com `mypy`/smoke run.

**Plano de fallback se #1 não resolver smoke 7:**

1. Tentar **#3 (trivial)**: comentar `SetEnabledLogToDebug(0)` em `wrapper.py:579` e re-rodar.
2. Tentar **#2 (custoso)**: implementar `SetTradeCallbackV2` real (signature `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)`, mesma de `THistoryTradeCallbackV2` em `types.py:419`) e `SetAssetListCallback` real (Noop com signature exata de `types.py` `TAssetListCallback`) ANTES de `wait_market_connected`. Aplicar Q-DRIFT-09 Opção C (subset mínimo, não os 14).

**NÃO mexer em:**
- `_cb_refs` (Q07-V) — anti-GC continua obrigatório.
- `_configure_dll_signatures()` (Q-DRIFT-08) — argtypes/restype continuam corretos.
- `wait_market_connected` (já aceita só `result=4` — alinhado manual + exemplo).

- **Manual diz:**
  - p.22-23: lista 11 args de `DLLInitializeMarketLogin` (3 wchar + 8 callback). NÃO marca quais são opcionais.
  - p.55: confirma `MARKET_CONNECTED=4` é o ÚNICO valor terminal.
  - p.74: diz "callbacks obrigatórios" — **mas exemplo oficial L742-743 passa `None` em 4 slots e funciona**. Divergência manual ↔ exemplo já catalogada em Q-DRIFT-06; **exemplo prevalece como fonte canônica de uso Python**.
- **Data descoberta:** 2026-05-04 (audit init Nelo, smoke 6 commit `7badeea`).
- **Aplica a stories:** 1.2 (init wrapper), 1.7b (smoke MVP gate), todas que dependem de MARKET_DATA conectado.
- **Refs:**
  - `profitdll/Exemplo Python/main.py` L729-764 (`dllStart` canônico).
  - `profitdll/Exemplo Python/main.py` L194-241 (`stateCallback` referência `result=4`).
  - `src/data_downloader/dll/wrapper.py:472-667` (`initialize_market_only`).
  - `src/data_downloader/dll/callbacks.py:make_noop_callback` (factory a manter — uso reduzido a 3 slots).
  - Q-DRIFT-02 (sintoma original `(2,1)`), Q-DRIFT-05 (signatures Noop fixadas), Q-DRIFT-06 (refuta Q11-E — alavanca para `None`), Q-DRIFT-08 (argtypes), Q-DRIFT-09 (não registrar 14 SetXxx).

---

## Manutenção

- **Adicionar quirk:** comando Nelo `*add-quirk {description}` OU edit manual aqui.
- **Atualizar status:** quando `ambiguous` ou `open` resolver via probe → mover para `validated`/`empirical` e adicionar evidência.
- **Cross-ref:** quirks referenciados em stories (AC) e em `PROFITDLL_KNOWLEDGE.md`. Ao mudar ID, atualizar refs.
- **Comando consulta:** Nelo `*quirks --status ambiguous` filtra esta lista.

— Nelo, guardião da DLL 🗝️
