# ADR-011 — Exception hierarchy & error propagation

**Status:** accepted
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💻 Dex, 🖼️ Felix, 🎨 Uma
**Related:** ADR-007a (public API), ADR-010 (logging), MANIFEST §R5 (idempotência), PLAN_REVIEW H10

---

## Contexto

Erros atravessam 4 camadas:
1. **DLL** (ProfitDLL) — códigos numéricos (`NL_OK=0`, `NL_INTERNAL_ERROR=80`, ...) + estados assíncronos via `ProgressCallback`.
2. **dll/** wrapper Python — converte códigos em exceptions ou retornos.
3. **storage/** — `IOError`, `OSError`, `sqlite3.Error`, integrity errors.
4. **orchestrator/** — chunking errors, timeouts, retry exhaustion.
5. **public_api/** — fronteira que UI/CLI/notebooks consomem.
6. **UI** (Epic 3+) — apresenta para humano.

Sem hierarquia clara:
- Caller pega `Exception` genérica → trata mal ou ignora.
- `try: download(...) except Exception:` esconde bugs reais (e.g., AttributeError).
- Logs não distinguem "erro esperado de domínio" (símbolo inválido) de "bug" (None inesperado).
- Felix (UI) precisa ramificar comportamento por tipo de erro (ex: "Sem conexão" vs "Disco cheio" vs "Bug — relatar").
- Uma precisa de mapa estável de erro → microcopy.

Ainda: **internals devem poder usar exceptions livremente sem vazar detalhes** para fora da fronteira `public_api/`. Internal stack traces são valiosos para debug, mas tipos internals (e.g., `_ChunkRetryExhausted`) não pertencem ao contrato público.

---

## Opções Consideradas

### Opção A — Hierarquia pública + `_InternalError` privado, traduzido na fronteira

```
DataDownloaderError (base pública)
├── DLLInitError
├── InvalidContract
├── DiskFull
├── DownloadError              # genérico de download (cause= preservado)
├── IntegrityError             # dado inconsistente (gap, dup, schema)
└── ConfigurationError

# Internals:
_InternalError (base privada)
├── _ChunkRetryExhausted
├── _CallbackTimeout
├── _CatalogLockBusy
└── ...
```

- Internals lançam `_InternalError` (ou subclasses).
- `public_api/` captura `_InternalError`, traduz para `DownloadError(cause=internal)`.
- UI/consumer só vê tipos públicos, mas pode inspecionar `.cause` para detalhe.
- Internals podem evoluir sem breaking change na API pública.

### Opção B — Hierarquia única, tudo público

- Toda exception é da hierarquia pública.
- Sem distinção interno/externo.
- Refatorar internal exception = breaking change na API pública.

### Opção C — Sem hierarquia — usar `Exception` direto

- Trivial.
- Inviável: caller não consegue tratar diferenciado.

### Opção D — Result type (tipo `Result<T, Error>`)

- Funcional puro, sem exceptions.
- Não-pythônico; consumidores Jupyter esperam exceptions.
- Force every call to unwrap — verbose.
- **Rejeitado por mismatch com idiom Python.**

---

## Análise

| Critério | A (pub+priv) | B (tudo público) | C (sem) | D (Result) |
|---------|--------------|------------------|---------|-----------|
| Caller trata diferenciado | ✅ | ✅ | ❌ | ✅ |
| Internals refatoráveis sem breaking | ✅ | ❌ | n/a | parcial |
| Uma mapeia erro → microcopy estável | ✅ | parcial | ❌ | ✅ |
| Mantém `.cause` para debug | ✅ | parcial | ❌ | ✅ |
| Idiomático Python | ✅ | ✅ | ✅ | ❌ |
| Esforço inicial | médio | baixo | trivial | alto |

**Decisão:** Opção A — separa contrato público (estável) de internals (livres).

---

## Decisão

**Opção A — Hierarquia pública (`DataDownloaderError`) + base interna privada (`_InternalError`) + tradução na fronteira `public_api/`.**

### Hierarquia pública

```python
# src/data_downloader/public_api/exceptions.py
"""
Hierarquia pública de exceções. Caller pega DataDownloaderError para
tratar genericamente, ou subclasses para tratamento específico.
"""

class DataDownloaderError(Exception):
    """Base de todas as exceções públicas do data-downloader."""

    def __init__(self, message: str, *, cause: Exception | None = None,
                 details: dict | None = None):
        super().__init__(message)
        self.cause = cause                  # Exception interna (detalhe forense)
        self.details = details or {}        # info estruturada para UI/log


class DLLInitError(DataDownloaderError):
    """
    DLL não pôde ser inicializada.

    Causas comuns:
    - Chave/credenciais inválidas (NL_INVALID_PASS, NL_INVALID_USER)
    - Companions ausentes (libssl, libcrypto, ssleay32, libeay32)
    - Arquivos .dat ausentes (timezone2.dat, holidays.dat, ...)
    - DLL versão incompatível (.dll-version mismatch)

    UI: tela de erro fatal, sugere checar credenciais e bootstrap.
    """


class InvalidContract(DataDownloaderError):
    """
    Símbolo não resolve para contrato vigente na data informada.

    Ex: download('WDO', 2026-03-15) — 'WDO' é raiz, não contrato.
    Sugestão de corretor: usar vigent_contract('WDO', date).
    """


class DiskFull(DataDownloaderError):
    """
    Disco cheio durante escrita Parquet ou SQLite.
    UI: tela de erro fatal, sugere liberar espaço; preserva work-so-far.
    """


class DownloadError(DataDownloaderError):
    """
    Erro genérico durante download. Inspecionar .cause para detalhe.

    Causas típicas:
    - Retry exhausted (cause=_ChunkRetryExhausted)
    - Cancelado por timeout (cause=TimeoutError)
    - DLL desconectou e não reconectou (cause=_DLLDisconnected)
    """


class IntegrityError(DataDownloaderError):
    """
    Dado inconsistente detectado.

    Causas:
    - Schema do Parquet existente não bate com schema_version atual
    - Catálogo SQLite e Parquet em desacordo (chunk no catálogo sem arquivo)
    - Hash mismatch em re-leitura

    Crítica: caller deve parar e investigar; não corrigir silenciosamente.
    """


class ConfigurationError(DataDownloaderError):
    """
    Configuração inválida (env var faltando, TOML mal-formado).
    Detectada em startup ou na primeira chamada.
    """


# (futuro: TimeoutError, AuthenticationError, etc. — adicionar conforme necessário)


__all__ = [
    'DataDownloaderError',
    'DLLInitError',
    'InvalidContract',
    'DiskFull',
    'DownloadError',
    'IntegrityError',
    'ConfigurationError',
]
```

### Hierarquia interna (privada)

```python
# src/data_downloader/_internal/errors.py
"""
Hierarquia interna. NUNCA propagar fora de public_api/ sem tradução.
"""

class _InternalError(Exception):
    """Base interna. Não importável por consumidores externos."""


class _ChunkRetryExhausted(_InternalError):
    def __init__(self, chunk_id: str, attempts: int, last_cause: Exception):
        super().__init__(f'Chunk {chunk_id} failed after {attempts} retries')
        self.chunk_id = chunk_id
        self.attempts = attempts
        self.last_cause = last_cause


class _DLLDisconnected(_InternalError):
    """DLL desconectou (state MARKET_DISCONNECTED) sem reconexão."""


class _CallbackTimeout(_InternalError):
    """ProgressCallback não chegou em janela esperada."""


class _CatalogLockBusy(_InternalError):
    """SQLITE_BUSY após retries."""


class _SchemaDriftDetected(_InternalError):
    """Schema do Parquet existente difere do esperado."""


class _PartialWriteDetected(_InternalError):
    """`.tmp.{uuid}` órfão encontrado em startup."""
```

### Política de propagação cross-camada

```
┌──────────────────────────────────────────────────────────────┐
│ public_api/  (FRONTEIRA)                                     │
│  - Captura _InternalError                                    │
│  - Traduz para DataDownloaderError ou subclasse              │
│  - cause= preserva detalhe forense                           │
│  - re-raise NUNCA propaga _InternalError fora                │
└──────────────────────────────────────────────────────────────┘
       ▲                              ▲
       │ DataDownloaderError          │ DataDownloaderError
       │                              │
┌──────┴──────┐  ┌──────┴──────┐  ┌──┴──────┐
│ orchestrator│  │ storage/    │  │ dll/    │
│  raise      │  │  raise      │  │  raise  │
│ _Internal*  │  │ _Internal*  │  │ _Init*  │
│ ou std lib  │  │ ou std lib  │  │         │
└─────────────┘  └─────────────┘  └─────────┘
```

#### Padrão de tradução

```python
# src/data_downloader/public_api/download.py

def download(symbol, start, end, *, exchange='F') -> DownloadHandle:
    try:
        handle = _start_download_internal(symbol, start, end, exchange)
        return handle
    except _InternalError as e:
        # Tradução
        if isinstance(e, _ChunkRetryExhausted):
            raise DownloadError(
                f'Failed to download chunk after {e.attempts} attempts',
                cause=e,
                details={'chunk_id': e.chunk_id, 'attempts': e.attempts},
            ) from e
        # Fallback genérico
        raise DownloadError(str(e), cause=e) from e
    except DLLInitError:
        raise  # já é pública
    except OSError as e:
        if e.errno in (errno.ENOSPC, errno.EDQUOT):
            raise DiskFull(str(e), cause=e) from e
        raise DownloadError(str(e), cause=e) from e
```

#### Logging de erro

```python
log = get_logger(__name__)

try:
    ...
except _InternalError as e:
    log.error('chunk.failed',
              chunk_id=e.chunk_id if hasattr(e, 'chunk_id') else None,
              error_type=type(e).__name__,
              cause_type=type(e.last_cause).__name__ if hasattr(e, 'last_cause') else None)
    raise
```

ADR-010 garante que stacktrace vai para log via `dict_tracebacks`. Em hot path: NÃO logar exception cada chamada — counter `errors_total{type=...}` em ADR-013.

### Mapeamento erro → UI (Felix + Uma)

Uma mantém `MICROCOPY_CATALOG.md` (Story 0.3) com:

| Tipo público | Microcopy título | Microcopy detalhe | Ação UI |
|--------------|------------------|-------------------|---------|
| `DLLInitError` | "Não foi possível conectar" | "Verifique as credenciais e a conexão." | Botão "Configurações" |
| `InvalidContract` | "Símbolo não disponível em {date}" | "Sugestão: {vigent_contract}" | Botão "Usar sugestão" |
| `DiskFull` | "Disco cheio" | "Libere espaço e tente novamente." | Botão "Abrir pasta" |
| `DownloadError` | "Falha no download" | "{cause.message}" | Botão "Tentar novamente" |
| `IntegrityError` | "Dado inconsistente detectado" | "Não tente corrigir manualmente — relate." | Botão "Relatar bug" |

### Regras

1. **Internals NUNCA fazem `import` de `public_api/`.** Fronteira unidirecional.
2. **`public_api/` captura toda subclasse de `_InternalError`** e traduz.
3. **`raise X from y`** sempre — preserva chain para debug.
4. **`.cause` é detalhe interno** — UI mostra mensagem amigável, não `repr(cause)`.
5. **Quinn property test:** chamar `download()` com input inválido lança apenas tipos de `DataDownloaderError`. Falha se `_InternalError` vaza.

---

## Consequências

### Positivas
- **API estável:** internals refatoráveis sem breaking change.
- **UI determinística:** Felix sabe exatamente quais tipos esperar.
- **Microcopy estável:** Uma mapeia tipo → mensagem 1:1.
- **Forense preservado:** `.cause` mantém detalhe interno.
- **Logging consistente:** `error_type` e `cause_type` padronizados.

### Negativas
- **Tradução verbosa em `public_api/`** — boilerplate inevitável; mitigação: helper `translate_internal()` em `_internal/errors.py`.
- **Disciplina:** dev tem que lembrar de lançar `_InternalError`, não `Exception`. Quinn audita.

### Neutras
- Adicionar tipos públicos no futuro = MINOR bump (aditivo).
- Renomear/remover tipo público = MAJOR bump.

---

## Validações requeridas

- [ ] Quinn property test: `download(invalid_input)` só lança `DataDownloaderError` ou subclasses (Story 1.7b)
- [ ] Quinn property test: `_InternalError` nunca aparece em `__cause__` chain externa exposta — só em `.cause` field (Story 2.1)
- [ ] Aria revisa cada PR em `public_api/exceptions.py` (workflow contínuo)
- [ ] Uma valida `MICROCOPY_CATALOG.md` cobre todos os tipos públicos (Story 0.3)
- [ ] Felix UI test: cada tipo público renderiza em tela com microcopy correto (Epic 3)
- [ ] Quinn checklist `*qa-gate`: nenhum `raise Exception(...)` genérico em `public_api/`
