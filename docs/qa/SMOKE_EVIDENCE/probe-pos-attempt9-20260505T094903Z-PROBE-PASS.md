# Probe Discriminante — Pós-Attempt 9

**Timestamp:** 2026-05-05T09:49:03Z
**Executor:** @qa (Quinn) — modo autônomo
**Story:** 1.7d
**Verdict:** **PROBE-PASS** (CENARIO_A — wrapper-specific bug confirmado)

---

## Resumo executivo

Após o falho attempt 9 (smoke ESTRITO via `minimal_handshake_strict`, espelho do probe), foi
rerodado `scripts/probe_init.py` para discriminar entre hipóteses:

- **PROBE-PASS** => Q-DRIFT-16 (sessão server-side travada por probes anteriores) **REFUTADA**.
  Bug é wrapper-specific mesmo após espelhamento estrito.
- **PROBE-FAIL** => indicaria mudança ambiental/sessão entre probes.

**Resultado:** **PROBE-PASS**. Probe conectou em **1.62s** com `bMarketConnected=True`,
`init_return=0`, `bAtivo=True`.

---

## Evidência (probe-pos-attempt9-20260505T094903Z.log)

```
[INIT] DLLInitializeMarketLogin retornou: 0 (em 0.25s)
[WAIT] >>> bMarketConnected em 1.62s <<<

VEREDICTO PROBE:
  init_return       = 0
  bConnectado       = True
  bMarketConnected  = True
  bAtivo            = True
  bBrokerConnected  = False
  tempo_total       = 1.62s
  CENARIO_A => CONECTOU. Bug esta no NOSSO wrapper.
```

**Log path:** `docs/qa/SMOKE_EVIDENCE/logs/probe-pos-attempt9-20260505T094903Z.log`

---

## Comparação temporal entre probes

| Probe | bMarketConnected (s) | Verdict |
|---|---|---|
| Probe inicial (Dex) | 1.82s | CENARIO_A |
| Probe pós-attempt 7 | 2.43s | CENARIO_A |
| **Probe pós-attempt 9 (este)** | **1.62s** | **CENARIO_A** |

Tempo de conexão **estável** (1.6-2.4s), inclusive **mais rápido** que probes anteriores.
Servidor está saudável. Credenciais não estão travadas server-side.

---

## Implicação para hipóteses ativas

| Hipótese | Status pós-probe |
|---|---|
| **Q-DRIFT-15 (Nelo)** — argtypes `DLLInitializeMarketLogin` cacheados | **VIVA**. Probe sempre configura argtypes corretamente; minimal_handshake_strict pode ter ordem diferente ou estar usando DLL singleton com state divergente. |
| **Q-DRIFT-16 (Aria)** — credenciais consumidas/sessão travada | **REFUTADA**. Probe imediatamente após attempt 9 conectou em 1.62s. Servidor não está travando sessão. |
| **Q-DRIFT-17 (Nelo)** — versão de ProfitDLL.dll difere entre probe e wrapper | **VIVA mas IMPLAUSÍVEL**. Mesmo path absoluto da DLL é referenciado. Suspeita reduzida, mas não eliminada — pode haver caching no `ctypes.CDLL` ou outra DLL na env path. |

---

## Diretriz "é bug, NÃO É DLL" — status

**MANTIDA E REFORÇADA.** Probe usa a mesma DLL, mesmas credenciais, mesma máquina,
mesmo momento — e conecta em 1.62s. O delta entre probe (passa) e
`minimal_handshake_strict` + smoke (falha após 150× MARKET_DATA/1) está **100% no nosso código**.

---

## Evidência adicional do attempt 9 (de Aria)

> 150× MARKET_DATA/1 chegam ao callback do wrapper, mas wrapper não promove
> `result=4` para `bMarketConnected=True`.

Combinado com PROBE-PASS, isso aponta para:

1. **Tradução incorreta de result code** no callback do wrapper
   (probe trata `result==4` como "Market: Conectado" e seta flag; wrapper pode estar
   filtrando/ignorando).
2. **Race condition na atribuição da flag** (callback recebe mas variável compartilhada
   não é promovida ao escopo correto).
3. **State machine divergente** entre `minimal_handshake_strict` e probe — strict é
   espelho da chamada DLL, mas o **handler de eventos** ainda é o do wrapper.

---

## Próxima ação recomendada (para aiox-master)

Despachar **@dev (Dex)** para diff cirúrgico entre o callback do `probe_init.py` e o
callback usado por `minimal_handshake_strict` / wrapper, focando em:

1. Como `result==4` é tratado em ambos.
2. Como `bMarketConnected` flag é promovida (escopo, lock, atribuição).
3. Se `_configure_dll_signatures` (argtypes) está realmente sendo aplicado em
   strict (Q-DRIFT-15 ainda viva).

NÃO escalar ao usuário ainda — discriminação interna foi conclusiva, ainda há trabalho
de investigação interna a fazer.
