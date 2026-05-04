# QUIRKS.md — Catálogo Vivo de Quirks da ProfitDLL

**Curador:** Nelo 🗝️ (profitdll-specialist)
**Última atualização:** 2026-05-04

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
| [Q02-E](#q02-e) | 🔬 empirical | history | Progresso 99% reconectando — não é trava |
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
- **Status:** 🔬 empirical
- **Categoria:** history
- **Sintoma:** `ProgressCallback` reporta `99` repetidamente por dezenas de minutos antes de chegar a `100` ou disparar último `HistoryTradeCallback`. Aparenta travamento.
- **Causa raiz:** A DLL cicla a conexão com o servidor de histórico antes de entregar o último pacote (especulação — manual silencioso). Pode estar relacionado a checkpoint/handshake interno.
- **Evidência:** validado em whale-detector v2 e Sentinel §12. Reproduzível em dias com volume alto de trades.
- **Workaround:**
  - Timeout mínimo: **1800s** sem progresso real (não confundir com 99% repetido).
  - "Progresso real" = mudança no número de `HistoryTradeCallback` recebidos OU mudança no progress reportado.
  - **NÃO** abortar em 99% — esperar `100` OU `TC_LAST_PACKET` (V2) OU timeout duro.
- **Manual diz:** §3.1 linha 1750 — "progresso de Download (1 até 100)" sem detalhar.
- **Data descoberta:** ~2025 (Sentinel).
- **Aplica a stories:** 1.3 (history primitive), 1.7a/b.

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

- **ID:** Q11-E (Sentinel §12)
- **Status:** 🔬 empirical
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

## Manutenção

- **Adicionar quirk:** comando Nelo `*add-quirk {description}` OU edit manual aqui.
- **Atualizar status:** quando `ambiguous` ou `open` resolver via probe → mover para `validated`/`empirical` e adicionar evidência.
- **Cross-ref:** quirks referenciados em stories (AC) e em `PROFITDLL_KNOWLEDGE.md`. Ao mudar ID, atualizar refs.
- **Comando consulta:** Nelo `*quirks --status ambiguous` filtra esta lista.

— Nelo, guardião da DLL 🗝️
