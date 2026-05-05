# Probe Wrapper Class Standalone — CENARIO_A (CONECTOU)

**Story**: 1.7d — experimento decisivo: isolar pytest harness vs wrapper class
**Data**: 2026-05-05T09:53:24Z
**Executor**: @dev (Dex) — modo autonomo
**Script**: `scripts/probe_wrapper_minimal.py`
**Log**: `docs/qa/SMOKE_EVIDENCE/logs/probe-wrapper-class-20260505T095324Z.log`

## Verdict

**CENARIO_A — CONECTOU em 2.21s (init 0.67s + wait 1.54s)**

```
[OK] >>> MARKET_CONNECTED em 1.54s (total init+wait: 2.21s) <<<
CENARIO_A => CONECTOU. Bug NAO esta no wrapper class — esta no pytest harness.
[VERDICT] CENARIO_A
```

A classe `ProfitDLL` da nossa codebase, com `minimal_handshake=True` e
`register_extra_callbacks=False`, conecta em ~2s **fora de pytest**. A mesma
classe, com os mesmos kwargs, dentro do smoke pytest, **trava 600s** em
`result=1` (MARKET_DATA never promoted to result=4).

## Sequencia de eventos do handshake (cenario sucesso)

```
09:53:27 LOGIN_CONNECTED        (conn_type=0, result=0)
09:53:27 MARKET_LOGIN_OK        (conn_type=3, result=0)
09:53:27 MARKET_DATA/1          (conn_type=2, result=1)  <-- aqui o smoke pytest trava
09:53:27 MARKET_WAITING         (conn_type=2, result=2)
09:53:28 MARKET_CONNECTED       (conn_type=2, result=4)  <-- promocao que nunca chega no pytest
```

No smoke pytest com `minimal_handshake=True` (Aria observou): callback
recebe **150x `(2, 1)`** sem progressao a `(2, 2)` ou `(2, 4)`.

## Evidencia diagnostica (Q-DRIFT-15 / Q-DRIFT-17)

### Q-DRIFT-15: argtypes/restype de DLLInitializeMarketLogin
- **argtypes pos-init**: `None` (default ctypes — nenhuma coercao explicita)
- **restype pos-init**: `<class 'ctypes.c_long'>`

Isso confirma que `minimal_handshake=True` **pula `_configure_dll_signatures`
em larga escala** (apenas restype eh definido). Hipotese Q-DRIFT-15
(divergencia de signature entre probe e wrapper) **NAO se aplica neste cenario**:
o wrapper rodou exatamente assim e conectou. Logo a divergencia hipotetica
nao existe ou nao e a causa-raiz.

### Q-DRIFT-17: identidade da DLL
- **DLL hash sha256[:16]**: `af8aa3e45872735f`
- **DLL path absoluto**: `C:\Users\Pichau\Desktop\data-downloader\profitdll\DLLs\Win64\ProfitDLL.dll`
- **DLL existe**: True

A DLL carregada eh exatamente a mesma usada pelo probe canonico e pelo
smoke pytest. Q-DRIFT-17 (binario diferente carregado) **REFUTADA** por
evidencia direta: hash identico ao baseline.

### Outras condicoes ambiente
- **Thread**: `MainThread`
- **Python**: 3.14.3 (win32)
- **CWD inicial**: `C:\Users\Pichau\Desktop\data-downloader`
- **CWD pos-init**: `C:\Users\Pichau\Desktop\data-downloader\profitdll\DLLs\Win64` (Q-DRIFT-10 ok)
- **Credenciais**: carregadas do `.env` via `dotenv` (user=04***, key_len=20, pass_len=15)

## Implicacao

**Bug isolado na camada de teste (pytest harness), nao no wrapper class
ProfitDLL.** Os 4 atributos do wrapper (initialize_market_only,
wait_market_connected, lifecycle, signatures) estao corretos. Algo no
ambiente do pytest interfere com o servidor Nelogica para que ele NAO
promova MARKET_DATA de `result=1` -> `result=4`.

### Diferenciais possiveis pytest vs script standalone (a investigar)

1. **Plugins pytest carregados** (capsys, capfd, etc.) — podem interferir
   com stdin/stdout/stderr da DLL nativa.
2. **structlog reconfig** — `tests/conftest.py` provavelmente reconfigura
   structlog; o probe usa a config default do wrapper.
3. **Hooks pytest** (autouse fixtures, session hooks) — podem mexer com
   threads, sinais, ou cwd antes do init.
4. **`os.chdir` em fixture** — alguma fixture pode mudar cwd durante o init.
5. **`sys.path` / import order** — pytest manipula sys.path; modulo
   `data_downloader.dll.wrapper` pode ser importado em ordem diferente.
6. **Buffering de I/O** — pytest captura stdout por default (`-s` desabilita);
   isso interage com prints da DLL via stderr/stdout.
7. **Thread pool / event loop** — alguma fixture pode criar event loop
   que ocupa MainThread quando a DLL espera responder no MainThread.
8. **Variaveis de ambiente extras** — pytest pode setar/limpar env vars
   (PYTEST_CURRENT_TEST, etc.) que o servidor Nelogica le.

### Q-DRIFT atualizadas

| Q-DRIFT | Status | Evidencia |
|---------|--------|-----------|
| Q-DRIFT-13 | REFUTADA (anterior) | — |
| Q-DRIFT-14 | REFUTADA (anterior) | — |
| Q-DRIFT-15 | REFUTADA (este probe) | argtypes=None / restype=c_long iguais ao probe |
| Q-DRIFT-16 | REFUTADA (anterior) | — |
| Q-DRIFT-17 | REFUTADA (este probe) | DLL hash `af8aa3e45872735f` igual ao baseline |

Todas as Q-DRIFTs sobre **wrapper class / DLL identity / signatures**
refutadas. Proxima rodada de investigacao deve focar em **harness pytest**.

## Proxima acao para @aiox-master

Despachar **mini-council 2 paralelos** (1 agente por persona):

1. **@qa (Quinn)**: auditar `tests/conftest.py` e `tests/smoke/` para
   listar todas as fixtures que rodam antes do init (autouse, session,
   module). Identificar fixtures que: mudam cwd, manipulam env vars,
   reconfigurate structlog, criam event loops, ou interagem com
   stdout/stderr.

2. **@architect (Aria)**: comparar invocacao Python no script standalone
   (`python scripts/probe_wrapper_minimal.py`) versus no smoke
   (`pytest tests/smoke/...`) — diferenca de sys.argv, sys.path,
   stdin/stdout fds, signal handlers, threading state. Levantar
   hipoteses Q-DRIFT-18/19/20 sobre o **harness pytest**.

Apos consolidacao, **bisseccionar**: rodar smoke pytest com
`-s -p no:cacheprovider --tb=no` (desabilitando capture e cache) para
testar hipotese de I/O capture.

## Commit (pendente)

```bash
git add scripts/probe_wrapper_minimal.py docs/qa/SMOKE_EVIDENCE/probe-wrapper-class-20260505T095324Z-CENARIO_A.md
git commit -m "diag: probe wrapper class standalone CONECTOU em 2.21s — bug no harness pytest [Story 1.7d]"
```

NAO `git push`. @devops (Gage) eh exclusivo.
