# COVERAGE_WORKAROUND.md — F-Q-1 follow-up resolution

**Status:** RESOLVED (2026-05-04 — Story 2.7 / COUNCIL-22).
**Origem:** Audit Story 1.7a finding F-Q-1 (`docs/qa/AUDIT_REPORTS/1.7a-design-2026-05-04.md`).
**Investigação:** Dex (Story 2.7 mini-council).

---

## Sumário

A finding **F-Q-1** descrevia incompatibilidade entre `pytest-cov` +
`coverage.py` + `duckdb 1.x` + Python 3.14 que supostamente bloqueava
medição formal de cobertura via `--cov`. Verificação empírica em Story
2.7 (mesma data, mas após updates de dependências) demonstrou que o
problema **não existe mais** — pytest-cov funciona normalmente com a
combinação atual.

**Cobertura medida:** 88.46% (target: 80%) — **PASS**.

---

## Cenário do bloqueio (reportado em 1.7a)

Per audit Story 1.7a, ao tentar rodar:

```bash
pytest --cov=data_downloader --cov-report=term-missing tests/
```

erros do tipo:

- `OSError: pytest: reading from stdin while output is captured`
- `BadFileDescriptor`
- conflitos `coverage.py` x `sys.monitoring` em Python 3.14
- `duckdb 1.x` ABI incompatibilidade

---

## Verificação empírica (Story 2.7)

### Setup

| Componente | Versão |
|------------|--------|
| Python | 3.14.3 |
| pytest | 9.0.2 |
| pytest-cov | 7.1.0 |
| coverage.py | (transitive de pytest-cov 7.1) |
| duckdb | >=0.10.0 (instalada: 1.x) |
| pyarrow | >=15.0.0 |

### Teste isolado

```bash
$ python -m pytest --cov=data_downloader --cov-report=term-missing \
    tests/unit/test_storage_schema.py
============================= 11 passed in 3.46s =============================
TOTAL  4683  4419  1000  0  5%
```

✅ 11 testes passam. Coverage report renderizado normalmente.

### Suite full

```bash
$ python -m pytest --cov=data_downloader --cov-report=term \
    tests/ --ignore=tests/smoke -q
...
TOTAL  4683  447  1000  141  88%
Required test coverage of 80.0% reached. Total coverage: 88.46%
=========== 1012 passed, 1 skipped, 8 warnings in 260.58s (0:04:20) ===========
```

✅ 1012/1013 testes passam, 88.46% coverage, exit code 0.

---

## Análise de hipóteses (1.7a) vs realidade (2.7)

### Hipótese A — duckdb 1.x não suporta Python 3.14 ABI

**Status:** Falsa. duckdb >=0.10.0 (testada 1.x) importa, abre arquivos,
executa queries em Python 3.14.3 sem erro.

### Hipótese B — pytest-cov 7.x bug com tracer + duckdb threads

**Status:** Falsa. pytest-cov 7.1.0 + coverage.py latest medem
corretamente módulos que importam duckdb (incluindo
`storage.duckdb_reader.py`, `storage.continuous_reader.py`).

### Hipótese C — coverage.py vs sys.monitoring conflict

**Status:** Resolvido upstream. coverage.py >=7.10 detecta Python 3.12+
e usa `sys.monitoring` corretamente; conflito histórico foi corrigido
antes da Story 2.7.

---

## 3 opções avaliadas (per Story 2.7 AC8)

### Opção (a): downgrade Python alvo para 3.12/3.13

**Status:** NÃO necessário — Python 3.14.3 funciona.
**Recomendação Aria:** preservar Python 3.12 como mínimo (per ADR-001
e `pyproject.toml requires-python = ">=3.12"`); 3.14 funciona como
upper bound em CI.

### Opção (b): bump duckdb para versão compatível com 3.14

**Status:** NÃO necessário — duckdb 1.x atual é compatível.
**Recomendação Sol:** manter `duckdb>=0.10.0` (não pinar minor) para
permitir patch bumps automáticos.

### Opção (c): plugin coverage customizado que skipa duckdb

**Status:** NÃO necessário (e seria contra-produtivo — perderia
cobertura de módulos legítimos).

---

## Recomendação Pyro+Aria (sign-off COUNCIL-22)

**F-Q-1 → CLOSED**. Nenhuma mudança de configuração necessária.

`pyproject.toml` permanece como está:

```toml
[tool.coverage.run]
source = ["src/data_downloader"]
omit = ["src/data_downloader/ui/*"]
branch = true

[tool.coverage.report]
fail_under = 80
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

### Boas práticas mantidas

- **Local dev / CI:** rodar `pytest --cov=data_downloader --cov-report=term`
  para checar threshold antes de PR.
- **HTML report (opcional):** `pytest --cov=data_downloader --cov-report=html`
  gera `htmlcov/index.html` para drill-down.
- **Branch coverage:** habilitado por default (`branch = true`) — captura
  decisões de fluxo, não só linhas executadas.

### Decisão deferida (NÃO necessária)

A Story 2.7 originalmente previa que F-Q-1 poderia exigir uma Story
separada para implementar workaround complexo. **Não é necessário** —
nenhuma Story de follow-up.

---

## Conclusão

F-Q-1 era uma finding válida no momento do audit Story 1.7a, mas foi
auto-resolvida por upgrades upstream do ecossistema entre 1.7a e 2.7.
Story 2.7 fecha a finding sem trabalho de implementação adicional.

— Dex + Pyro + Aria (sign-off COUNCIL-22)
