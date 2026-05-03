# TEST PYRAMID — Estratégia de Testes do data-downloader

> Estrutura canônica de `tests/` no squad data-downloader. Define propósito,
> exemplos, política mock-vs-real e gatilhos de execução de cada camada.
>
> **Alinhamento com Aria:** ADR-014 (Test Strategy) é a fonte arquitetural;
> este documento é a operacionalização QA. Em conflito, ADR-014 prevalece.

---

## 1. Diretório canônico

```
tests/
├── unit/             # rápido, isolado, mocked
├── integration/      # múltiplas camadas, DLL mockada
├── property/         # Hypothesis para invariantes
├── smoke/            # E2E real (apenas humano roda — ver SMOKE_PROTOCOL.md)
├── fixtures/         # dados sintéticos + mock DLL pattern
└── conftest.py       # configuração compartilhada pytest
```

---

## 2. Pirâmide visual

```
                ╱──────────────────╲
               ╱   smoke E2E real    ╲       1-3 testes (humano roda)
              ╱  CLI→DLL real→Parquet ╲      MUITO LENTOS, MUITO CAROS
             ╱─────────────────────────╲
            ╱   integration (DLL mock)   ╲    ~20 testes
           ╱  orchestrator + storage e2e   ╲  RÁPIDOS-MÉDIOS
          ╱──────────────────────────────────╲
         ╱             unit                    ╲   ~100+ testes
        ╱  dedup, chunking, calendar, schema     ╲  MUITO RÁPIDOS
       ╱─────────────────────────────────────────╲
       ←────  property (Hypothesis, ortogonal)  ──→  ~10 propriedades
              invariantes (idempotência, dedup)     paralelo a unit/integration
```

---

## 3. Camadas em detalhe

### 3.1 `tests/unit/`

| Aspecto                  | Definição                                                   |
|--------------------------|-------------------------------------------------------------|
| **Propósito**            | Testar 1 unidade lógica (1 função / 1 classe) em isolamento |
| **Tempo por teste**      | < 100 ms                                                    |
| **Dependências externas**| Nenhuma — DB / DLL / disco / rede mockados                  |
| **Quando rodar**         | A cada save (watch mode), pre-commit, CI, qa-gate           |
| **Critério de cobertura**| >= 80% nas camadas críticas (`storage/`, `orchestrator/`); >= 70% em `dll/`; >= 60% em `ui/` |
| **Política mock vs real**| 100% mock — qualquer I/O é fake/in-memory                   |
| **Exemplos**             | `test_dedup_basic`, `test_calendar_b3_holiday`, `test_chunking_split`, `test_state_machine_transitions` |

**Comando:**
```bash
pytest tests/unit/ -v --cov=src/data_downloader --cov-report=term-missing
```

### 3.2 `tests/integration/`

| Aspecto                  | Definição                                                   |
|--------------------------|-------------------------------------------------------------|
| **Propósito**            | Testar interação entre 2+ camadas (orchestrator + storage, DLL wrapper + ingestor) |
| **Tempo por teste**      | 100 ms - 5 s                                                |
| **Dependências externas**| DLL: **MOCKADA** via `MockProfitDLL` (ver §6); SQLite real (tmp); Parquet real em `tmp_path` |
| **Quando rodar**         | Pre-commit, CI, qa-gate                                     |
| **Critério de cobertura**| Cobrir todos os "happy paths" de orchestração; testar 2-3 paths de erro críticos |
| **Política mock vs real**| Storage real (SQLite + Parquet em tmp_path); DLL mock; rede mock |
| **Exemplos**             | `test_download_full_pipeline_mocked_dll`, `test_orchestrator_resumes_after_failure`, `test_catalog_atomic_with_writer` |

**Comando:**
```bash
pytest tests/integration/ -v
```

### 3.3 `tests/property/`

| Aspecto                  | Definição                                                   |
|--------------------------|-------------------------------------------------------------|
| **Propósito**            | Verificar **invariantes** (propriedades que devem valer para QUALQUER input válido) via geração aleatória |
| **Framework**            | `hypothesis`                                                |
| **Tempo por teste**      | 100 ms - 30 s (depende de `max_examples` e `deadline`)      |
| **Dependências externas**| Mesmo nível de `unit` (mockado) ou `integration` (storage real) |
| **Quando rodar**         | Pre-commit (com `--hypothesis-profile=ci`), CI (`dev`), qa-gate (`thorough`) |
| **Critério de cobertura**| Toda invariante listada em `docs/qa/INVARIANTS_TESTS.md` deve ter teste property |
| **Política mock vs real**| Conforme nível (unit-style ou integration-style)            |
| **Exemplos**             | `test_dedup_idempotent` (INV-2), `test_download_idempotent_replay` (INV-3), `test_schema_roundtrip_v1` (INV-7) |

**Seeds canônicos** (reprodutibilidade):

```python
# tests/property/conftest.py
from hypothesis import settings, Verbosity

settings.register_profile(
    "ci",
    max_examples=50,
    deadline=2000,
    derandomize=True,  # seed fixo para CI
)
settings.register_profile(
    "dev",
    max_examples=200,
    deadline=5000,
)
settings.register_profile(
    "thorough",
    max_examples=1000,
    deadline=30000,
    print_blob=True,  # imprime input minimal para reproduzir
)
```

Profiles selecionados via `--hypothesis-profile=ci|dev|thorough`.

### 3.4 `tests/smoke/`

| Aspecto                  | Definição                                                   |
|--------------------------|-------------------------------------------------------------|
| **Propósito**            | E2E **REAL** — CLI → DLL real → Parquet → DuckDB. Validar gate de Epic 1 e cada release |
| **Tempo por teste**      | 30 s - 15 min                                               |
| **Dependências externas**| `ProfitDLL.dll` instalada + licença Nelogica + internet     |
| **Quando rodar**         | Pré-merge Story 1.7b + cada release V*. **Apenas humano roda** (não CI) |
| **Critério de cobertura**| Quick smoke (1 dia WDO) + Full smoke (30 dias WDOJ26)       |
| **Política mock vs real**| 100% REAL — sem nenhum mock                                 |
| **Protocolo completo**   | `docs/qa/SMOKE_PROTOCOL.md`                                 |

**Marcador pytest:**
```python
@pytest.mark.smoke
@pytest.mark.skipif(
    not os.getenv("PROFITDLL_AVAILABLE"),
    reason="Smoke requer DLL real e licença Nelogica"
)
def test_full_smoke_wdoj26_30_days(tmp_path):
    ...
```

CI **NÃO** define `PROFITDLL_AVAILABLE` → smokes são skipped em CI por padrão.
Humano define `PROFITDLL_AVAILABLE=1` localmente para rodar.

### 3.5 `tests/fixtures/`

| Aspecto                  | Definição                                                   |
|--------------------------|-------------------------------------------------------------|
| **Propósito**            | Dados sintéticos canônicos + factories + Mock DLL pattern (§6) |
| **Conteúdo**             | `synthetic_trades.py`, `mock_dll.py`, `b3_calendar_2024_2026.py`, `parquet_samples/` |
| **Política**             | Imutável uma vez aceito — bumpar versão se mudar formato (`v1`, `v2`) |

---

## 4. Quando rodar cada camada

| Gatilho                 | unit | integration | property | smoke | fixtures |
|-------------------------|------|-------------|----------|-------|----------|
| Save (watch mode)       | ✅   | —           | —        | —     | —        |
| Pre-commit              | ✅   | ✅          | ✅ (`ci`) | —     | —        |
| CI push                 | ✅   | ✅          | ✅ (`dev`)| —     | —        |
| qa-gate (Quinn)         | ✅   | ✅          | ✅ (`thorough`) | conditional | — |
| Pré-merge Story 1.7b    | ✅   | ✅          | ✅       | ✅ humano | — |
| Pré-release V*          | ✅   | ✅          | ✅       | ✅ humano | — |

---

## 5. Critérios de cobertura por módulo

| Módulo                       | Threshold | Justificativa |
|------------------------------|-----------|---------------|
| `data_downloader/contracts/` | 90%       | Interfaces (Protocols) — toda assinatura testada |
| `data_downloader/storage/`   | 80%       | Camada crítica — corrupção aqui é catastrófica |
| `data_downloader/orchestrator/` | 80%    | Camada crítica — orquestração de chunks/retry |
| `data_downloader/dll/`       | 70%       | Wrapper inevitavelmente tem caminhos exigindo DLL real |
| `data_downloader/cli/`       | 70%       | Comandos cobertos por integration tests |
| `data_downloader/ui/`        | 60%       | UI requer pytest-qt; cobertura completa fica em Epic 3 |
| **Global**                   | 75%       | Média ponderada                                |

Medido por `pytest --cov=src/data_downloader --cov-report=term-missing --cov-report=xml`.

---

## 6. Mock DLL pattern (delegação a Aria — ADR-014)

> Esta é a operacionalização da decisão arquitetural de Aria em ADR-014 (proposed).
> Em caso de conflito com ADR-014 quando este for accepted, ADR-014 prevalece.

### 6.1 Princípios

- **Mock fiel**: assinaturas exatas, comportamento ressalvas-aware (Q-AMB-01..03, Q11-E, etc).
- **Mock determinístico**: dada a mesma sequência de inputs, gera a mesma sequência de callbacks.
- **Mock auditável**: monitora violações como "callback chamou DLL" (INV-1) e expõe em `mock_calls`.
- **Mock separado de teste**: `tests/fixtures/mock_dll.py` é a única fonte; testes não criam mocks ad-hoc.

### 6.2 API mínima esperada

```python
class MockProfitDLL:
    """Mock fiel da ProfitDLL. Usado em tests/unit e tests/integration.

    Princípios:
    - WINFUNCTYPE-compatible: callbacks têm assinatura idêntica à DLL real.
    - Determinístico: mesmo seed → mesma sequência.
    - Auditável: rastreia callback_call_stack para verificar INV-1.
    """

    def __init__(self, scenario: Scenario, seed: int = 42): ...

    def DLLInitializeMarketLogin(self, *cb_slots): ...   # 11 slots — Q11-E
    def SetHistoryTradeCallback(self, cb): ...
    def GetHistoryTrades(self, symbol, start, end): ...  # dispara callbacks no thread fake
    def GetDLLVersion(self) -> str: ...                  # H19 — coletado p/ Parquet metadata
    def Finalize(self) -> int: ...
    def DLLFinalize(self) -> int: ...                    # Q-AMB-03

    # Auditoria de invariantes
    @property
    def callback_violations(self) -> list[str]:
        """Retorna lista de violações INV-1 detectadas (callback chamou DLL)."""
        return self._violations

    @property
    def mock_calls(self) -> list[tuple]:
        """Histórico ordenado de chamadas — útil para assertions."""
        return self._calls
```

### 6.3 Cenários canônicos (`Scenario`)

| Cenário              | Descrição                                              |
|----------------------|--------------------------------------------------------|
| `HappyPath`          | 1k-1M trades sem erros, sem reconnects                 |
| `ReconnectMid`       | Reconnect 99% no meio do download (Q-99-recover)       |
| `RolloverContract`   | `download_continuous` cruza vencimento (M16)           |
| `EmptyHistory`       | Símbolo sem trades no range (gap legítimo)             |
| `MarketWaitingQuirk` | State `MARKET_WAITING=2` antes de `MARKET_CONNECTED=4` (Q-AMB-01) |
| `TimestampWithDot`   | Timestamps com "." e ":" misturados (Q-AMB-02)         |
| `LateCallback`       | HistoryTradeCallback chega 100ms após Finalize (race H11) |
| `CallbackViolation`  | (negativo) cenário em que mock detecta DLL chamada de dentro de callback — usado para verificar que asserção INV-1 funciona |

---

## 7. Política de execução

| Cenário                             | Ação                                              |
|-------------------------------------|---------------------------------------------------|
| Teste flaky (passa intermitente)    | Quinn investiga causa raiz — **NUNCA** silenciar com `@pytest.flaky` |
| Teste lento (> 5s) em unit          | Mover para `integration/` ou refatorar            |
| Teste depende de DLL real           | Mover para `smoke/` com `@pytest.mark.smoke`      |
| Teste depende de internet           | Marcar `@pytest.mark.requires_network` e skip em CI sem flag |
| Property test demora > 30s no CI    | Usar profile `ci` (max_examples=50)               |

---

## 8. Comandos de referência

```bash
# Watch mode (durante desenvolvimento)
ptw tests/unit/

# Pre-commit local
pytest tests/unit/ tests/integration/ tests/property/ \
  --hypothesis-profile=ci -x

# CI (config padrão — sem smoke)
pytest --cov=src/data_downloader --cov-report=xml \
  --hypothesis-profile=dev

# qa-gate completo (sem smoke)
pytest --cov=src/data_downloader --cov-report=term-missing \
  --hypothesis-profile=thorough -v

# Smoke (humano apenas, com DLL)
PROFITDLL_AVAILABLE=1 pytest tests/smoke/ -v
```

---

## 9. Pendência aberta

- **ADR-014 (Test Strategy)** ainda em status `proposed` — Aria precisa fechar antes do gate Epic 1.
- Assim que ADR-014 for `accepted`, este documento será revisado e qualquer divergência reconciliada (ADR-014 vence).
- Pergunta aberta para Aria: a partição entre property tests "estilo unit" (mock total) e "estilo integration" (storage real) está correta?

---

— Quinn, no portão 🧪
