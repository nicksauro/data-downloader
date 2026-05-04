# `data_downloader.public_api` — Deprecation Policy (V1.0+)

**Owner:** Aria (architect — fronteira pública).
**Status:** active since `__api_version__ = "1.0.0"` (Story 4.3).
**Aplica-se a:** todos os símbolos exportados em
`src/data_downloader/public_api/__init__.py:__all__`.

---

## SemVer Estrito

A API pública `data_downloader.public_api` segue **Semantic Versioning 2.0**
(https://semver.org), interpretado **estritamente** pelo squad:

| Bump | Trigger | Exemplo |
|------|---------|---------|
| **PATCH** (`1.0.0 → 1.0.1`) | Bug fix sem mudança de assinatura. Mesma semântica observável (corrige bug). | Correção de off-by-one em paginação interna. |
| **MINOR** (`1.0.0 → 1.1.0`) | Adição compatível: nova função, novo argumento opcional com default, novo símbolo em `__all__`. Código consumer existente continua funcionando sem mudança. | Adicionar `download_batch(symbols=[...], ...)`; adicionar param opcional `compression="zstd"` em `read`. |
| **MAJOR** (`1.0.0 → 2.0.0`) | Breaking change: remoção, rename, mudança de tipo, mudança semântica observável. Consumer pode precisar editar código. | Remover símbolo deprecado; renomear `read` → `read_trades`; mudar tipo de retorno. |

**Garantia operacional:** entre minor versions consecutivas, o squad
**não** quebra nenhum import que constava em `__all__` da versão
anterior. Se quebrar acidentalmente, é bug — abrir issue + patch.

### Símbolos NÃO cobertos por SemVer

Mudanças nestes alvos podem ocorrer em **qualquer** versão (incluindo
patch) sem aviso prévio:

- Módulos privados: `data_downloader._internal`, `data_downloader.dll`,
  `data_downloader.storage`, `data_downloader.orchestrator`,
  `data_downloader.ui`.
- Símbolos com prefixo `_` (ex.: `_deprecation`, helpers).
- Mensagens humanas (microcopy) — IDs são estáveis, texto resolvido
  pode mudar via `MICROCOPY_CATALOG.md`.
- Performance / latência (governada por `benchmarks/BASELINES.md`).
- Logs estruturados (campos podem ser adicionados aditivamente).

---

## Lifecycle de Deprecação

```
Released (V1.0)
    │
    │ <decisão: deprecar símbolo X>
    ▼
Deprecated in V1.N  (decorator @deprecated emitido em runtime)
    │
    │ ≥ N+1 minor releases (≥ 6 meses calendário)
    ▼
Removed in V(N+major).0  (Major bump explícito + entry CHANGELOG)
```

### Regra dura: ≥ 2 versões + ≥ 6 meses entre anúncio e remoção

Um símbolo deprecado em `1.2.0` é removido **no mais cedo** em `2.0.0`,
**e** somente se passaram pelo menos **6 meses calendário** entre o
release de `1.2.0` e o release de `2.0.0`. Se 2.0 sair em < 6 meses,
o símbolo permanece (com warning) até 3.0.

**Razão:** consumers downstream (backtest engine, signal generator) podem
ter ciclos de release próprios. 6 meses garante 1+ ciclo de release para
absorção da mensagem `DeprecationWarning`.

### Rationale para deprecar (não apenas remover)

Remover símbolo direto = quebra silenciosa para consumers que ainda usam.
Deprecar = sinal explícito via warning antes da quebra. Squad **deve**
deprecar antes de remover; remover sem deprecação prévia é violação
constitucional (Article IV — No Invention).

---

## Decorator `@deprecated`

Implementação em `src/data_downloader/public_api/_deprecation.py`. Uso:

```python
from data_downloader.public_api._deprecation import deprecated

@deprecated(
    since="1.2.0",
    removed_in="2.0.0",
    replacement="data_downloader.public_api.download_batch",
)
def download_many(symbols, start, end):
    """Legacy batch download — use download_batch instead."""
    ...
```

### Comportamento

1. **Runtime warning:** primeira chamada emite
   ```
   DeprecationWarning: download_many is deprecated since v1.2.0 and will
   be removed in v2.0.0. Use data_downloader.public_api.download_batch instead.
   ```
2. **Docstring mutation:** `help(download_many)` mostra prefix
   `[DEPRECATED since v1.2.0, removed in v2.0.0]`.
3. **Marker introspectivo:** `download_many.__deprecated__` retorna
   `{"since": "1.2.0", "removed_in": "2.0.0", "replacement": "..."}`.
4. **Stacklevel correto:** warning aponta para o **caller**, não para o
   decorator (debug-friendly).

### Quando aplicar

- **Função inteira:** decorator no `def`.
- **Método de classe:** decorator no método.
- **Classe inteira:** decorator no `__init__` (warning na construção).
- **Argumento de função:** NÃO usar este decorator. Em vez disso,
  detectar o uso do arg e emitir `warnings.warn(...)` manual com
  ``DeprecationWarning`` no corpo da função (decorator não tem
  granularidade de arg).

### Workflow ao deprecar

1. **Decisão arquitetural:** Aria valida via `*review-design`. Cada novo
   `@deprecated` é uma decisão pública — entra em ADR ou council.
2. **Aplicar decorator:** `@deprecated(since=..., removed_in=..., replacement=...)`.
3. **Documentar substituto:** se `replacement=None`, justificar no
   CHANGELOG (ex.: "comportamento removido sem substituto — caller deve
   reimplementar").
4. **CHANGELOG entry:** seção "Deprecated" da versão `since` lista o
   símbolo. Tracker em DEPRECATION_POLICY.md (este arquivo) também.
5. **Test:** garantir que `pytest --filterwarnings 'error::DeprecationWarning'`
   ainda passa nos testes que NÃO chamam o símbolo deprecado, e captura
   warnings nos que chamam.
6. **Remoção (em release MAJOR):** delete + entry "Removed" no CHANGELOG
   + ADR-XXX se a remoção tem rationale arquitetural.

---

## Tracker de Deprecações Ativas

Esta tabela é a **single source of truth** sobre o que está deprecado
HOJE. Updates obrigatórios em cada release que adiciona/remove
deprecação.

| Símbolo | Deprecated since | Will be removed in | Replacement | Rationale |
|---------|------------------|--------------------|-------------|-----------|
| _(nenhum em V1.0.0)_ | — | — | — | V1.0.0 é baseline; primeira deprecação será anunciada em V1.x se/quando necessário. |

---

## Backwards-Compat Tests Obrigatórios

Cada release V1.x **deve** rodar a suite de regression tests SemVer:

- `tests/integration/test_public_api_semver_regression.py` — verifica
  que TODOS os símbolos da V1.0 continuam importáveis e mantêm assinatura.
- `tests/integration/test_public_api_no_internal_imports.py` — AST scan
  garante que tests consumer não importam de internals (guardrail
  anti-leak).
- (Futuro) `tests/integration/test_public_api_deprecation_decorator.py` —
  smoke test do decorator `@deprecated` (warning emitido,
  attrs preservados).

CI bloqueia merge se algum desses falhar — não negociável.

---

## Workflow do Consumer

### Captura proativa de DeprecationWarning

Em `pyproject.toml` do consumer:

```toml
[tool.pytest.ini_options]
filterwarnings = [
    "error::DeprecationWarning:data_downloader.*",
]
```

Isto faz o consumer test suite **falhar** se algum código chamar símbolo
deprecado da `data_downloader.public_api`. Você descobre cedo.

### Decisão de upgrade

| Bump observado em changelog | Ação recomendada |
|-----------------------------|-------------------|
| Patch (`1.0.0 → 1.0.1`) | Re-instalar; rodar testes; commit. |
| Minor (`1.0.0 → 1.1.0`) | Re-instalar; ler "Added" no CHANGELOG (pode adotar novos símbolos opcionalmente); commit. |
| Major (`1.x → 2.0.0`) | Branch dedicada de upgrade. Ler "Breaking changes" e "Removed" no CHANGELOG. Aplicar edits. Rodar test suite + smoke. |

### Exemplo: migrar um símbolo deprecado

Cenário hipotético: `download_many` deprecado em `1.2.0`, removido em `2.0.0`.

1. Em `1.2.0` (consumer ainda usa `download_many`):
   ```
   DeprecationWarning: download_many is deprecated since v1.2.0 ...
   ```
2. Editar consumer para usar `download_batch` (replacement):
   ```python
   # antes:
   results = download_many(["WDOJ26", "WINH26"], start, end)
   # depois:
   results = download_batch(symbols=["WDOJ26", "WINH26"], start=start, end=end)
   ```
3. Rodar testes — `DeprecationWarning` desaparece.
4. Em `2.0.0`, `download_many` não existe mais. Consumer já migrou
   antes — zero impacto.

---

## Referências

- `docs/public_api/USAGE.md` — exemplos copy-paste para 3 personas.
- `docs/adr/ADR-007a-public-api-redesign.md` — design rationale fronteira.
- `CHANGELOG.md` — histórico + seções "Added" / "Deprecated" / "Removed".
- `src/data_downloader/public_api/_deprecation.py` — decorator implementation.
- https://semver.org — Semantic Versioning 2.0.
