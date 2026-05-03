# ADR-007a — Public API redesign: `DownloadHandle` + `cancel()`

**Status:** accepted
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🖼️ Felix, 🎨 Uma, 💻 Dex
**Supersedes:** ADR-007 (Public API SemVer separado — fronteira preservada; muda apenas o shape de `download()`)
**Related:** ADR-005 (thread model), ADR-011 (exception hierarchy), ARCHITECTURE.md §3, MANIFEST §1, PLAN_REVIEW H9 + H10 + M16

---

## Contexto

A versão original do contrato `download()` em ADR-007 foi:

```python
def download(symbol, start, end, *, exchange='F', stream: bool = False)
    -> DownloadResult | Iterator[DownloadProgress]: ...
```

Três problemas convergentes apareceram na review do squad (PLAN_REVIEW 2026-05-03):

1. **H9 — Liskov violation.** O tipo de retorno depende do valor de um parâmetro (`stream`). Consumidores precisam ramificar (`isinstance`) para tratar o retorno; type-checkers (mypy/pyright) marcam `Union` em todo call site. Streaming e não-streaming compartilham 95% do código mas exigem dois caminhos de teste.

2. **H10 — Cancelamento sem contrato.** Felix (Epic 3) precisa de "Cancel" no botão. Hoje não existe handle no qual chamar `.cancel()`. UI fingia cancelar (matava signal), backend continuava rodando até o próximo checkpoint — a UX **mente** para o usuário.

3. **M16 — `current_contract` ausente em rollover.** `download_continuous()` (Epic 4) muda `symbol` no meio (rollover de WDOH26 → WDOJ26). `DownloadProgress` atual não carrega o contrato vigente — UI mostra label errado.

A fronteira `public_api/` é **fronteira SemVer** (ADR-007). Mudar o shape de `download()` aqui é breaking — exige bump major **antes** do primeiro consumidor existir (custo zero agora, custo proibitivo em 6 meses).

---

## Opções Consideradas

### Opção A — `DownloadHandle` retornado sempre, com `progress()` iterador + `cancel()`

```python
def download(symbol, start, end, *, exchange='F') -> DownloadHandle: ...

class DownloadHandle:
    job_id: str

    def progress(self) -> Iterator[DownloadProgress]: ...
    def wait(self, timeout: float | None = None) -> DownloadResult: ...
    def cancel(self, *, timeout: float = 30.0) -> DownloadResult: ...
    def __enter__(self) -> 'DownloadHandle': ...
    def __exit__(self, exc_type, exc, tb) -> None: ...  # cancel se exc
```

- Retorno único e estável.
- Streaming = `for p in handle.progress(): ...`
- Não-streaming = `result = handle.wait()`
- Cancelamento real, com timeout para drain ordenado (state machine ADR-005 amendment).
- Context manager garante shutdown limpo em exceções.

### Opção B — Manter union, adicionar `cancel()` via callback

```python
def download(symbol, start, end, *, stream=False, on_cancel=None) -> ...: ...
```

- Mantém shape antigo.
- Cancelamento via callback registrado.
- Continua violando Liskov.
- `on_cancel` é arquitetura "callback-hell" — Felix precisaria registrar antes de iniciar, sem handle para inspecionar estado.

### Opção C — Duas funções: `download_sync()` + `download_stream()`

```python
def download_sync(symbol, start, end, *, exchange='F') -> DownloadResult: ...
def download_stream(symbol, start, end, *, exchange='F') -> Iterator[DownloadProgress]: ...
```

- Resolve Liskov.
- Não resolve cancelamento (mesmo problema).
- Duplica superfície da API (más práticas de versionamento — toda mudança em parâmetro precisa ser feita 2x).

### Opção D — `asyncio` (`async def download() -> AsyncIterator[Event]`)

- Resolve cancelamento (`task.cancel()` nativo).
- Força consumidor a ter event loop.
- ADR-005 rejeitou asyncio para V1 (ctypes + ConnectorThread + Qt = friction grande).
- **Inviável sem refator profundo.**

---

## Análise

| Critério | A (Handle) | B (callback) | C (split) | D (async) |
|----------|-----------|--------------|-----------|-----------|
| Resolve Liskov (H9) | ✅ | ❌ | ✅ | ✅ |
| Cancel real (H10) | ✅ | parcial | ❌ | ✅ |
| `current_contract` em progress (M16) | ✅ (campo) | parcial | parcial | ✅ |
| Type-safety (mypy/pyright clean) | ✅ | ❌ (Union) | ✅ | ✅ |
| Compatível com ADR-005 (sync threads) | ✅ | ✅ | ✅ | ❌ |
| Fácil de testar | ✅ (handle mockável) | difícil (callback chain) | OK | OK (mas exige loop) |
| Custo de migração (zero consumidores hoje) | baixo | nenhum | médio | alto |
| Esforço inicial | médio | baixo | médio | alto |

**Pontos críticos:**

- **Opção D** é a mais elegante em isolamento, mas força async em todo consumidor. Backtest engines e Jupyter notebooks (consumidores prováveis V1) preferem chamada bloqueante simples. **Rejeitada.**
- **Opção C** duplica API e ainda não resolve cancel. **Rejeitada.**
- **Opção B** mantém o problema central. **Rejeitada.**
- **Opção A** unifica retorno, expõe cancel real, segue padrão `concurrent.futures.Future` (familiar para devs Python), e suporta `with` para shutdown automático em exceções. **Escolhida.**

---

## Decisão

**Opção A — `download() → DownloadHandle` único, com `progress()`, `wait()`, `cancel()` e suporte a context manager.**

### Public API V1.0 final

```python
# src/data_downloader/public_api/download.py
from dataclasses import dataclass, field
from collections.abc import Iterator
from datetime import date
from typing import Optional

@dataclass(frozen=True)
class DownloadProgress:
    """Snapshot do progresso. Imutável."""
    job_id: str
    total_chunks: int
    done_chunks: int
    trades_received: int
    bytes_written: int
    current_contract: str          # M16: contrato vigente (rollover-aware)
    current_chunk_range: tuple[date, date]
    message: str                   # microcopy de Uma (catalog em MICROCOPY_CATALOG.md)
    elapsed_seconds: float

@dataclass(frozen=True)
class DownloadResult:
    """Resultado terminal. Imutável."""
    job_id: str
    symbol_root: str               # 'WDO' (raiz, não contrato)
    contracts_used: list[str]      # ['WDOH26', 'WDOJ26'] em rollover
    exchange: str
    actual_start: date
    actual_end: date
    trades_count: int
    partitions_written: list[str]  # paths Parquet
    duration_seconds: float
    cancelled: bool                # True se terminou via cancel()
    bytes_written: int

class DownloadHandle:
    """
    Handle para um download em andamento. Padrão familiar a `Future`.

    Uso típico (bloqueante):
        with download('WDOJ26', d1, d2) as handle:
            result = handle.wait()

    Uso streaming:
        with download('WDOJ26', d1, d2) as handle:
            for p in handle.progress():
                ui.update(p)
            result = handle.wait()  # já terminou; retorna imediatamente

    Cancelamento limpo:
        handle.cancel()  # bloqueia até drain completo (default 30s)
    """

    @property
    def job_id(self) -> str: ...

    @property
    def is_running(self) -> bool: ...

    @property
    def is_done(self) -> bool: ...

    @property
    def is_cancelled(self) -> bool: ...

    def progress(self) -> Iterator[DownloadProgress]:
        """
        Itera snapshots de progresso. Termina quando download conclui ou é cancelado.
        Chamar mais de uma vez é OK — cada chamada cria um cursor independente
        (multi-consumer via fila interna).
        """
        ...

    def wait(self, timeout: Optional[float] = None) -> DownloadResult:
        """
        Bloqueia até término. Levanta TimeoutError se timeout estourar.
        Chamar após término retorna o resultado em cache imediatamente.
        """
        ...

    def cancel(self, *, timeout: float = 30.0) -> DownloadResult:
        """
        Inicia shutdown gracioso (state machine ADR-005 amendment):
        Running → DrainingDLL → DrainingWrite → Committed.
        Bloqueia até timeout. Se timeout estourar, levanta DownloadError
        com cause=TimeoutError. Garante: catálogo SQLite consistente, sem .tmp órfão.
        Chamar em download já terminado é no-op (retorna result em cache).
        """
        ...

    def __enter__(self) -> 'DownloadHandle': ...
    def __exit__(self, exc_type, exc, tb) -> None:
        """
        Em saída normal: aguarda conclusão.
        Em saída por exceção: chama cancel() e propaga.
        """
        ...


def download(
    symbol: str,
    start: date,
    end: date,
    *,
    exchange: str = 'F',
) -> DownloadHandle:
    """
    Inicia download assíncrono (em thread). Retorna handle imediatamente.
    Idempotente: se (symbol, range) já está no catálogo, handle conclui em ~1s
    com `cancelled=False` e `trades_count=0` (no-op semântico).

    Raises (na criação do handle, antes de retornar):
        DLLInitError: DLL não inicializa (chave inválida, companions ausentes).
        InvalidContract: symbol não resolve para contrato vigente.
    """
    ...
```

### Sinais Qt (Felix usa via adapter)

ADR original previa `Signal(dict)` em adapters. **Mudança:** sinais carregam dataclasses tipados:

```python
class DownloadAdapter(QObject):
    progress = Signal(object)   # carrega DownloadProgress (dataclass)
    finished = Signal(object)   # carrega DownloadResult
    failed = Signal(object)     # carrega DownloadError (com .cause)
```

Por que `Signal(object)` e não `Signal(DownloadProgress)`: PySide6 trata classes Python via `object` em `pyqtSignal` para evitar marshalling custoso. Type-safety vem do hint do slot Python, não do meta-system Qt.

### Garantias documentadas

| Garantia | Detalhe |
|---------|---------|
| Idempotência (R5) | `download(s, a, b)` re-rodado é no-op — handle conclui rápido com `trades_count=0` |
| Ordenação | `DownloadProgress.done_chunks` é monotônico crescente |
| Cancel atômico | Após `cancel()`, catálogo + Parquet refletem **somente** chunks já committados; nenhum `.tmp` órfão |
| Multi-consumer | `handle.progress()` chamado N vezes cria N cursores; fila interna é fan-out |
| Thread-safety | Métodos do handle são thread-safe — UI thread pode chamar `.is_done` enquanto worker executa |

### Impacto em ADR-005 (cross-reference)

`cancel()` aciona a state machine de shutdown documentada no **Amendment 2026-05-03 de ADR-005**:

```
Running → DrainingDLL → DrainingWrite → Committed → Idle
```

Cada transição tem timeout e atualiza catálogo SQLite. INV-12 (fim de chunk = filas vazias + último write commitou) é a invariante que torna `cancel()` corretamente atômico.

---

## Consequências

### Positivas
- **Type-safe:** mypy/pyright sem warnings de Union.
- **UX honesta:** Felix entrega botão "Cancelar" que cancela de verdade.
- **Padrão familiar:** `DownloadHandle` espelha `concurrent.futures.Future`.
- **Multi-consumer:** UI + log file + métricas todas leem `progress()` em paralelo sem race.
- **`current_contract`:** rollover transparente em UI (M16 fechado).
- **Context manager:** garante cleanup em exceções — Quinn não precisa caçar `.tmp` órfão em smoke.

### Negativas
- **Esforço de implementação:** Dex precisa estruturar fila fan-out + cursor independente. Story 1.7b absorve.
- **Documentação:** docstrings precisam ser exemplares — handle é mais "novo" para devs que esperam call bloqueante simples.
- **Mudança em `DownloadProgress`:** adiciona 4 campos (`job_id`, `current_contract`, `current_chunk_range`, `bytes_written`). Felix e Uma alinham labels.

### Neutras
- ADR-007 fica registrado como "principle ainda válido" (SemVer separado). Apenas o **shape** das funções muda. `__api_version__` não bumpa porque ainda estamos pré-1.0 (v0.x — breaking changes toleradas, doc em CHANGELOG).

---

## Validações requeridas

- [ ] Aria revisa PR que introduz `DownloadHandle` (Story 1.7b)
- [ ] Quinn property test: `download(s, [a,b])` é idempotente para qualquer (s, a, b) válido (Story 2.1)
- [ ] Quinn property test: `cancel()` deixa catálogo consistente — nenhum chunk parcial (Story 2.1)
- [ ] Quinn smoke test: `cancel()` durante download real termina em <30s (Story 1.7b)
- [ ] Felix UI test: clicar "Cancelar" reflete estado real em <1s na barra de progresso (Epic 3)
- [ ] Mypy strict passa sem warnings de Union em `public_api/` (Story 1.7b)
- [ ] Uma valida microcopy para estados Cancelling/Cancelled (MICROCOPY_CATALOG.md)
