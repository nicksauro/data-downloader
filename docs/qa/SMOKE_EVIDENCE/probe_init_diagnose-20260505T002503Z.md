# Probe Init Diagnose — 2026-05-05T00:25:03Z

**Agent:** Dex (Builder) — modo autonomo, probe-only.
**Script:** `scripts/probe_init.py`
**Log bruto:** `docs/qa/SMOKE_EVIDENCE/probe_init_20260505T002503Z.log`

## Resultado executivo

**CENARIO A — probe CONECTA plenamente.**

```
init_return       = 0
bConnectado       = True
bMarketConnected  = True
bAtivo            = True
bBrokerConnected  = False   (nao usamos roteamento, esperado)
tempo_total       = 1.82 s
```

Sequencia de state events observada (ordem real):

```
[STATE] Ativacao: OK            -> nType=3 result=0  bAtivo=True
[STATE] Login: conectado        -> nType=0 result=0  bConnectado=True
[STATE] Market: 1               -> nType=2 result=1
[STATE] Market: 2               -> nType=2 result=2
[STATE] Market: Conectado       -> nType=2 result=4  bMarketConnected=True
[STATE] >>> Servicos Conectados <<<
```

Ou seja, MARKET_DATA passa por `result=1 -> 2 -> 4` em **menos de 2s** quando
o caminho de init eh exatamente o do exemplo Nelogica.

## Veredicto

**Bug NAO eh ambiental.** Servidor responde, conta esta ativa, login funciona.
O problema descrito (`MARKET_DATA fica result=1, nao chega a 4`) reproduz
SOMENTE no nosso `wrapper.py` — o probe oficial conecta em ~2s.

> Consequencia: hipotese "fora do horario de pregao / problema de rede" eh
> descartada por evidencia empirica. O bug esta no nosso codigo de init.

## Diff vs. nosso wrapper (alvos prioritarios para investigacao)

**Importante:** Esta secao apenas LISTA diferencas observaveis. Como Dex em
modo probe, NAO modifico `wrapper.py` — apenas reporto para o agente que
for fazer a correcao.

### 1. cwd no momento do `WinDLL(...)` e do init  (PRIME SUSPECT)

| Aspecto                              | Probe (conecta)                                 | Nosso wrapper (trava)                       |
|--------------------------------------|-------------------------------------------------|---------------------------------------------|
| `os.chdir` antes de `WinDLL`         | SIM — muda para `profitdll/DLLs/Win64/`        | NAO — usa cwd do processo                   |
| Resultado                            | DLL acha `libssl-1_1-x64.dll`, `*.dat`, logs    | DLL pode falhar a achar deps/escrever state |

`profitdll/DLLs/Win64/` contem 19 arquivos auxiliares (libssl/libcrypto,
ServerAddr*.dat, exchangeinfo2.dat, holidays.dat, timezone2.dat, Logs/,
database/, MarketHours2/, strategy/...). Quando rodamos o probe a partir de
qualquer outro cwd a DLL **nao acha esses arquivos**, e o canal MARKET_DATA
fica em estado intermediario sem nunca progredir para `result=4`.

Comprovacao: o exemplo Nelogica (`profitdll/Exemplo Python/main.py`) so
"funciona" porque o usuario manualmente copia a DLL para `Exemplo Python/`
(linha 10: `initializeDll("./ProfitDLL.dll")`) — implicitamente deixando o
cwd igual a `Exemplo Python/`. No probe, conseguimos o mesmo efeito sem
copiar a DLL fazendo `os.chdir(DLL_DIR)` antes de `WinDLL(...)`.

**Acao sugerida (NAO executada por mim):** wrapper deveria fazer `os.chdir`
para `dll_path.parent` antes de `WinDLL(...)`, OU usar `os.add_dll_directory`
+ ajustar working dir para a pasta da DLL durante toda a vida util do
processo (ProfitDLL escreve em `./Logs/`, `./database/` etc).

### 2. Slots de callback no init (`DLLInitializeMarketLogin`)

| Slot | Wrapper                      | Probe (= main.py L742)        |
|------|------------------------------|-------------------------------|
| 4 state         | `make_state_callback(queue)`        | `stateCallback` (mesma signature) |
| 5 trade         | `NoopCallback(TTradeCallback)`      | `None`                        |
| 6 daily         | `NoopCallback(TDailyCallback)`      | `newDailyCallback` (REAL)     |
| 7 priceBook     | `NoopCallback(TPriceBookCallback)`  | `None`                        |
| 8 offerBook     | `NoopCallback(TOfferBookCallback)`  | `None`                        |
| 9 historyTrade  | `NoopCallback(THistoryTradeCallback)`| `None`                       |
| 10 progress     | `NoopCallback(TProgressCallback)`   | `progressCallBack` (REAL)     |
| 11 tinyBook     | `NoopCallback(TTinyBookCallback)`   | `tinyBookCallBack` (REAL)     |

O wrapper segue a regra "JAMAIS passar None" (Q11-E / Sentinel §12),
preenchendo todos os 7 slots com NoopCallback. **O exemplo Nelogica passa
None em 5 dos 7 slots e mesmo assim conecta.** Nossa regra "no None" pode
ser mais conservadora do que necessaria, mas em si nao bloqueia conexao —
o probe demonstra apenas que None tambem conecta. Se a regra esta correta
ou nao precisa ser revalidada por @architect; nao eh a causa-raiz observada
neste probe (probe usa None e conecta, wrapper usa Noop e nao conecta).

Possivel hipotese complementar: o `NoopCallback(TPriceBookCallback)` ou
`NoopCallback(TOfferBookCallback)` (signatures pesadas com `POINTER(c_int)`)
pode estar sendo invocado pela DLL durante o handshake e desalinhando a
stack stdcall — mesmo um no-op precisa que a signature WINFUNCTYPE bata
EXATAMENTE com o que a DLL chama. Se a hipotese principal (#1) nao
resolver, este eh o segundo lugar para olhar.

### 3. Ordem das `Set*Callback` extras

Nosso wrapper, com `register_extra_callbacks=False` (default), **NAO** chama
nenhuma das 14 `Set*Callback`. O probe tambem nao chama — paridade.
Diferenca neutra.

### 4. `SetEnabledLogToDebug(0)` ANTES do init

Wrapper chama; probe nao chama (puramente cosmetico — silencia log).
Diferenca neutra para conectividade.

### 5. Threading

Probe roda single-thread: a propria thread principal (de onde fazemos
`DLLInitializeMarketLogin`) eh a que fica em `time.sleep` esperando a flag.
Wrapper usa ConnectorThread / state queue. O probe DEMONSTROU que a propria
thread Python que chama o init recebe os callbacks state (eles disparam la
mesmo via apartment COM/STA do Windows). Diferenca de design pode ser
relevante mas o probe nao isolou esse vetor.

## Sugestao de proximo passo (para @architect / @dev em outra sessao)

1. PRIMEIRO experimento: adicionar `os.chdir(dll_path.parent)` no wrapper
   logo antes do `WinDLL(...)` e rodar smoke. Custo: 1 linha. Probabilidade
   alta de resolver baseado neste probe.
2. Se nao resolver: substituir TEMPORARIAMENTE os 7 NoopCallbacks por `None`
   (replicando exatamente o probe) para isolar se e o conjunto Noop que
   esta corrompendo handshake.
3. Se ainda nao resolver: comparar threading model — probe usa mesma thread
   para init+wait; wrapper usa ConnectorThread separada.

## Arquivos

- `scripts/probe_init.py` (criado)
- `docs/qa/SMOKE_EVIDENCE/probe_init_20260505T002503Z.log` (criado)
- `docs/qa/SMOKE_EVIDENCE/probe_init_diagnose-20260505T002503Z.md` (este arquivo)
