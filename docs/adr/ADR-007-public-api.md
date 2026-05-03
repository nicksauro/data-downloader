# ADR-007 — Public API com versionamento SemVer separado do core

**Status:** superseded by ADR-007a (2026-05-03)
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💻 Dex, 💾 Sol
**Supersedes:** —
**Superseded-by:** ADR-007a (shape de `download()` redesenhado para retornar `DownloadHandle` único; o **princípio** de SemVer separado do core permanece válido — apenas o contrato de retorno foi substituído).
**Related:** ADR-002 (storage), ADR-004 (partition), MANIFEST §1 (foundation)

---

## Contexto

O data-downloader é **base de TODOS os projetos futuros do usuário** (R1). Backtest engine, live signal generator, risk monitor, research notebooks vão consumir os dados baixados — todos via uma **interface programática**.

Se essa interface mudar de forma quebradora sem aviso, **todos os consumidores quebram**. Precisamos de:
1. **Fronteira clara** — código consumidor importa só do "público"; nunca toca internals.
2. **Versionamento SemVer** — projetos downstream pinam versão e sabem o que esperar.
3. **Garantias documentadas** — idempotência, ordenação, schema.
4. **Política de deprecação** — funções antigas vivem 2 versões antes de sumir.

---

## Opções Consideradas

### Opção A — Pacote `public_api/` separado, exports controlados, versionamento SemVer próprio
- Diretório `src/data_downloader/public_api/` com `__init__.py` listando exports.
- Versão registrada em `public_api/__init__.py` (`__api_version__ = "1.0.0"`).
- Bump independente da versão do app (`pyproject.toml` é versão "produto", `__api_version__` é versão "interface").

### Opção B — Tudo público, SemVer único do projeto
- Todos os módulos importáveis. SemVer reflete versão do projeto inteiro.

### Opção C — Sem fronteira, deixar consumidores escolherem
- Documentação aponta funções "estáveis", mas tudo é importável.

---

## Análise

| Critério | A (api separada) | B (tudo público) | C (sem fronteira) |
|---------|------------------|------------------|-------------------|
| Refator de internals sem quebrar consumidor | ✅ | ❌ | ❌ |
| Versionamento granular | ✅ | parcial | ❌ |
| Deprecação suave | ✅ | difícil | impossível |
| Auditoria de mudança quebradora | ✅ (Aria revisa public_api/) | ruim | ruim |
| Onboarding de consumidor | claro | confuso | confuso |
| Esforço inicial | médio | baixo | trivial |

**Pontos críticos:**

- **Opção C** é o estado natural de um projeto ad-hoc. Funciona até o primeiro consumidor ficar travado em uma versão velha porque temos medo de mexer em qualquer coisa. **Rejeitada.**

- **Opção B** acopla rigidamente versão de produto a versão de interface. Bug fix interno = bump major (porque algum consumidor pode ter importado o internal). Inflaciona números, não resolve. **Rejeitada.**

- **Opção A** isola fronteira pública. Internals podem refatorar à vontade desde que assinatura pública preserve. Aria tem autoridade exclusiva sobre o diretório `public_api/`. **Escolhida.**

---

## Decisão

**Opção A — Pacote `src/data_downloader/public_api/` com SemVer próprio.**

### Estrutura

```
src/data_downloader/
├── public_api/
│   ├── __init__.py          # __api_version__, exports controlados
│   ├── download.py          # download(), DownloadResult, DownloadProgress
│   ├── history.py           # read(), read_continuous(), vigent_contract()
│   └── exceptions.py        # DLLInitError, InvalidContract, DiskFull, ...
└── (todos os outros módulos = INTERNALS, podem refatorar)
```

### `__init__.py`

```python
"""
Public API of data-downloader.

This module is the STABLE interface for downstream projects.
Only import from here. Do NOT import from data_downloader.dll, .storage,
.orchestrator etc. directly — those are internals and may change without
notice.

API version follows SemVer:
- PATCH: bug fix, no signature change
- MINOR: additive (new function, new optional argument)
- MAJOR: breaking change

See docs/adr/ADR-007-public-api.md for governance.
"""

__api_version__ = "1.0.0"

from .download import download, DownloadResult, DownloadProgress
from .history import read, read_continuous, vigent_contract
from .exceptions import (
    DLLInitError,
    InvalidContract,
    DiskFull,
    DownloadError,
)

__all__ = [
    "__api_version__",
    "download", "DownloadResult", "DownloadProgress",
    "read", "read_continuous", "vigent_contract",
    "DLLInitError", "InvalidContract", "DiskFull", "DownloadError",
]
```

### Garantias documentadas (em docstrings)

| Função | Garantia |
|--------|----------|
| `download(s, a, b)` | Idempotente (R5). Re-rodar é no-op. |
| `read(s, a, b)` | Ordenado por `timestamp_ns` ascendente. Sem duplicatas. |
| `read_continuous(root, a, b)` | Concatena contratos vigentes; rollover transparente. |
| `vigent_contract(root, d)` | Lookup determinístico em `catalog.db.contracts`. |
| Schema retornado | `schema_version` no metadata Parquet (atual: `1.0.0`). |

### Política de deprecação

```python
# Exemplo: função X marcada deprecated em v1.5.0, removida em v3.0.0

@deprecated(since="1.5.0", removed_in="3.0.0",
            replacement="use new_function() instead")
def old_function(...): ...
```

Regra: deprecated em MINOR; removido em MAJOR seguinte (>= 2 versões depois). Aria valida em `*review-design`.

### Versionamento

- `__api_version__` em `public_api/__init__.py` é fonte de verdade.
- `pyproject.toml` versão = versão do **produto** (CLI + UI). Pode incrementar PATCH/MINOR sem mudar `__api_version__`.
- CHANGELOG.md tem duas seções: "App Changes" e "API Changes" (Gage mantém).

### Mudanças exigem ADR

- Toda função nova em `public_api/` exige ADR (ou referência a ADR existente).
- Toda função removida/renomeada exige ADR.
- Aria revisa cada PR que toca `public_api/`.

---

## Consequências

### Positivas
- Internals refatoráveis sem quebrar consumidor.
- Onboarding de novo projeto downstream: "import só do `public_api`".
- Versionamento granular permite consumidor escolher quando upgradar.
- Deprecação suave reduz risco de bug "função sumiu sem aviso".
- Aria tem autoridade clara sobre fronteira (R15).

### Negativas
- Esforço extra: cada feature pública vira função em `public_api/` + delegação para internals.
- Risco de duplicação se consumidor "burlar" e importar internal — mitigação: pre-push hook detecta `from data_downloader.dll/storage/orchestrator import` em projetos consumidores conhecidos (Gage configura quando relevante).

### Neutras
- Inicialmente `public_api/` é fino (poucas funções). Cresce conforme Epic 4 progride.

---

## Validações requeridas

- [ ] Aria revisa cada PR que toca `public_api/` (workflow contínuo)
- [ ] Quinn property-test: `download()` é idempotente (Story 2.1)
- [ ] Quinn smoke test: consumidor protótipo importa só de `public_api` e funciona (Story 4.3)
- [ ] CHANGELOG diferencia "App" e "API" (Gage configura template, Story 4.3)
