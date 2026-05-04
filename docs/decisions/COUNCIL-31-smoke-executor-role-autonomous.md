# COUNCIL-31 — Smoke Executor Role for Autonomous Mode

**Topic:** Quem (qual agente) executa smoke real contra ProfitDLL agora que o usuário forneceu credenciais e autorizou modo autônomo
**Date:** 2026-05-04
**Conveners:** Morgan 📋 (PM) + Quinn 🧪 (QA gate authority) + Gage ⚙️ (release authority)
**Status:** RATIFIED (autonomous mode — mini-council tríade)
**Related:** COUNCIL-09 (MVP Gate sem real smoke), `docs/qa/SMOKE_PROTOCOL.md`, `docs/qa/WAIVERS/{1.7b,1.8,4.1,4.2,4.4}-*-deferred-2026-05-04.md`

---

## 1. Contexto

Cinco WAIVERS abertos diferem o smoke real ProfitDLL para "humano executa quando puder":

| WAIVER | Escopo                                                       | Status pré-COUNCIL-31 |
|--------|--------------------------------------------------------------|------------------------|
| 1.7b   | Smoke single-symbol WDOJ26 30 dias (gate Epic 1)             | aguardando humano      |
| 1.8    | Re-baseline performance contra DLL real (depende 1.7b)       | aguardando humano      |
| 4.1    | Smoke multi-symbol 4 paralelos (depende 1.7b + Q17-OPEN)     | aguardando humano      |
| 4.2    | Smoke multi-asset WIN+PETR4 (depende 1.7b + 4.1 + Q18-OPEN)  | aguardando humano      |
| 4.4    | Smoke release V1.0 em VM Windows limpa                        | aguardando humano      |

**Mudança de circunstâncias (2026-05-03):** o usuário humano

1. Forneceu `.env` com `PROFITDLL_KEY`, `PROFIT_USER`, `PROFIT_PASS` válidos.
2. Confirmou ProfitDLL.dll + companions instaladas na máquina Windows do squad.
3. Autorizou explicitamente o squad a executar smoke real em **modo autônomo**.

`SMOKE_PROTOCOL.md` §2 atual diz "apenas o usuário humano roda" — mas essa restrição era **estrutural** (agente não tinha credenciais nem DLL). Com credenciais + DLL agora disponíveis ao squad, a restrição cai. O que falta é decidir formalmente **qual agente** assume o papel de "smoke executor" no modo autônomo, sem violar separation of concerns nem criar conflito de interesse.

---

## 2. Pergunta central

**Quem executa o smoke real agora que o agente passa a ter capacidade técnica?**

---

## 3. Opções consideradas

| Opção | Executor                                       | Pró                                                                           | Contra                                                                         |
|-------|------------------------------------------------|-------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| A     | Quinn (QA)                                     | É autoridade de QA gate; smoke é gate                                          | **Conflito de interesse**: Quinn validaria o próprio output. Viola §5 WAIVERS. |
| B     | Gage (DevOps)                                  | Smoke é pré-release validation; coerente com domínio release                   | Gage é puro infra/release; rodar contra DLL real é fora do seu escopo padrão.  |
| C     | Dex (dev)                                      | Implementou DLL wrapper, orchestrator, storage, public_api, CLI — tem competência | Sozinho seria 1 olho só; precisa de validador independente.                    |
| D     | Novo papel "Smoke Executor" dedicado            | Neutro, não acumula em ninguém                                                 | Cria 11º agente, viola "10 agentes" do MANIFEST. Burocracia sem ganho.         |

---

## 4. Posições da tríade

### 4.1 Quinn 🧪 (QA gate authority)

> Smoke é **gate de QA** — eu sou quem lê evidência e emite verdict PASS/FAIL.
> Se eu também executar, valido meu próprio output: viola separation of concerns
> (mesmo princípio do `WAIVERS/README.md` §5 que me proíbe assinar meus próprios
> WAIVERS). **Eu valido. Não devo executar.**

### 4.2 Gage ⚙️ (release authority)

> Smoke é pré-release validation — historicamente parte do meu domínio. Mas
> meu escopo é git push, packaging, CI, secrets, releases — **não rodar
> orchestrator + DLL contra mercado real**. Isso é territorio de quem
> implementou o backend (Dex). Posso registrar a execução em AUDIT.md depois,
> mas não devo ser o executor primário.

### 4.3 Morgan 📋 (PM, mediator)

> Smoke é teste E2E final do produto. Cabe a quem tem competência simultânea
> de DLL + orchestrator + storage + public_api — perfil exato do Dex. Mas
> Dex sozinho = 1 olho só. **Solução: tríade compartilhada**.
>
> - **Dex** — executa o comando, coleta logs, gera Parquets, calcula hashes.
> - **Quinn** — lê evidência, valida 6 critérios PASS / 8 critérios FAIL do
>   `SMOKE_PROTOCOL.md` §7-8, emite verdict.
> - **Gage** — registra em `docs/qa/AUDIT.md` (ou equivalente) que o smoke
>   foi executado, por quem, com que commit_sha do código, com que SHA dos
>   Parquets, e que o verdict foi PASS/FAIL.
>
> Isso preserva separation of concerns, evita conflito de interesse, e
> habilita o squad a fechar os 5 WAIVERS abertos sem aguardar agendamento humano.

---

## 5. Decisão

**RATIFIED — Opção C com twist: Smoke Executor é uma autoridade compartilhada (tríade Dex + Quinn + Gage), aplicável EXCLUSIVAMENTE em modo autônomo após autorização explícita do usuário.**

### 5.1 Distribuição de responsabilidades

| Papel             | Agente | Responsabilidade                                                                                              |
|-------------------|--------|--------------------------------------------------------------------------------------------------------------|
| **Executor**      | Dex 💻 | Roda comando `data-downloader download ...` per `SMOKE_PROTOCOL.md` §4. Coleta logs, Parquets, hashes.        |
| **Validador**     | Quinn 🧪 | Lê evidência (logs, hashes, snapshot catálogo), aplica 6 critérios PASS / 8 critérios FAIL §7-8. Verdict.    |
| **Auditor**       | Gage ⚙️ | Registra entry em `docs/qa/AUDIT.md` (ou equivalente release-readiness) com: timestamp, commit_sha, smoke_id, verdict, evidência path. |

### 5.2 Política operacional

1. **Pré-condição obrigatória:** `.env` presente E credenciais válidas E DLL instalada E autorização explícita do usuário registrada (em conversa ou em comentário no PR/story).
2. **Sanitização obrigatória:** evidência arquivada em `docs/qa/SMOKE_EVIDENCE/{story_id}-{ts}.md` ou `docs/qa/smoke_runs/` segue §11 do `SMOKE_PROTOCOL.md` (sem hostname, IP, username em path, conteúdo de `.env`, credenciais).
3. **Falha de execução:** se smoke falhar, Dex produz relatório de falha mesmo assim com hashes parciais sanitizados, Quinn lê e gera `QA_FIX_REQUEST` per §10 do protocolo.
4. **Conflito de interesse preservado:** Quinn **NUNCA** executa o que vai validar. Dex **NUNCA** valida o que executou. Gage **NUNCA** assina como executor nem como validador — apenas audita.
5. **Modo autônomo é opt-in:** `SMOKE_PROTOCOL.md` §2 default permanece "humano executa". Tríade autônoma só aplica quando usuário autoriza explicitamente.

### 5.3 Critérios PASS/FAIL inalterados

Os 6 critérios PASS (`SMOKE_PROTOCOL.md` §7) e 8 critérios FAIL (§8) são **objetivos** e independentes de quem executa. Tríade autônoma usa exatamente os mesmos critérios — a única mudança é o executor humano → tríade.

### 5.4 Rastreabilidade

- Cada smoke autônomo gera evidência commit-rastreável (commit_sha do `.md` evidência + commit_sha do código rodado).
- Gage adiciona linha em audit log com triple (executor=Dex, validator=Quinn, auditor=Gage).
- Cadeia auditável: PR → commit do código → smoke run → evidência md → audit entry → verdict Quinn.

---

## 6. Implicações para os 5 WAIVERS abertos

| WAIVER  | Pré-COUNCIL-31              | Pós-COUNCIL-31                                                                |
|---------|-----------------------------|--------------------------------------------------------------------------------|
| 1.7b    | aguardando humano           | tríade pode executar; remediation desbloqueada                                 |
| 1.8     | aguardando humano           | desbloqueia após 1.7b; Pyro re-baseline pós smoke real PASS                    |
| 4.1     | aguardando humano + Q17-OPEN | tríade pode executar pós 1.7b PASS; Q17-OPEN ainda exige confirmação Nelogica  |
| 4.2     | aguardando humano + Q18-OPEN | tríade pode executar pós 1.7b + 4.1 PASS; Q18-OPEN exige probe                 |
| 4.4     | aguardando VM humana         | **fica como WAIVER humano** — VM limpa + SmartScreen click-through não automatizáveis pela tríade |

WAIVER 4.4 **continua sendo de humano** porque exige VM Windows limpa fora do ambiente do squad — escopo de release real, fora do alcance da tríade autônoma.

---

## 7. Sign-off

**RATIFIED** — Smoke Executor (modo autônomo) = Dex executa + Quinn valida + Gage audita.

| Aprovador | Domínio                               | Sign-off                                                              |
|-----------|---------------------------------------|-----------------------------------------------------------------------|
| Morgan 📋 | escopo / política autônomo            | `Co-Authored-By: Morgan (PM) <agent@data-downloader.local>`           |
| Quinn 🧪  | gate authority / separation concerns  | `Co-Authored-By: Quinn (Gatekeeper) <agent@data-downloader.local>`    |
| Gage ⚙️   | release / audit authority             | `Co-Authored-By: Gage (DevOps) <agent@data-downloader.local>`         |

**Timestamp:** `2026-05-04T00:00:00-03:00`

---

## 8. Próximos passos

1. **Imediato:** Atualizar `docs/ROLES.md` (nova autoridade compartilhada — escopo desta entrega).
2. **Imediato:** Atualizar `docs/qa/SMOKE_PROTOCOL.md` §2 (modo padrão humano vs modo autônomo tríade — escopo desta entrega).
3. **Próxima ação Dex:** iniciar execução smoke single-symbol WDOJ26 30 dias (Story 1.7b-followup) per `SMOKE_PROTOCOL.md` §4.2.
4. **Após 1.7b PASS:** desbloqueia 1.8 (re-baseline Pyro), depois 4.1, depois 4.2.
5. **WAIVER 4.4:** permanece humano (VM limpa fora do escopo tríade).

---

— Morgan 📋 + Quinn 🧪 + Gage ⚙️ (mini-council COUNCIL-31)
