# ADR-014 — Test strategy: layers, mock DLL, fake clock, property-based

**Status:** accepted
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🧪 Quinn, 🗝️ Nelo, ⚡ Pyro
**Related:** ADR-005 (thread model), ADR-010 (logging), ADR-011 (exceptions), MANIFEST §R3 + §R5, PLAN_REVIEW C4 + C5 + C6 + M15

---

## Contexto

Sem estratégia clara de testes:
- Tests bagunçados → coverage falsa.
- Smoke contra DLL real misturado com unit → CI lenta + flaky.
- Mock ad-hoc → drift contra contrato real da DLL.
- Time-dependent tests não-determinísticos.
- Invariantes (INV-1 a INV-12) sem auditoria mecânica.

PLAN_REVIEW levantou:
- **C4:** validators (`*integrity-check`, `*data-validate`) não existem como código mas são exigidos no gate.
- **C5:** smoke gated por env nunca roda em CI → "honor system".
- **C6:** INV-1 (callback não chama DLL) não tem teste explícito.
- **M15:** DLL não-idempotente em init→finalize→init na mesma sessão Python.

Restrições:
- **DLL real só em Windows com `.dll-version` correto** (ADR-008 bootstrap).
- **DLL re-init na mesma sessão Python falha (M15)** → fixture session-scoped, único processo.
- **Smoke caro** — minutos por execução; CI deve ter gate explícito (não silencioso).
- **Property-based testing** ideal para invariantes (idempotência, dedup).

---

## Opções Consideradas

### Opção A — Estrutura layered: unit / integration / property / smoke / fixtures + mock DLL + fake clock

```
tests/
├── unit/                 # rápido, sem I/O, sem DLL
├── integration/          # I/O real (Parquet, SQLite), DLL mockada
├── property/             # Hypothesis para invariantes
├── smoke/                # E2E DLL real (gated)
└── fixtures/
    ├── mock_dll.py       # ProfitDLL substituto
    ├── fake_clock.py     # tempo determinístico
    ├── sample_payloads/  # snapshots de TConnectorTradeV1/V2
    └── sample_parquet/   # Parquet de referência
```

### Opção B — Estrutura flat (`tests/` com nomes como prefixo)

- `test_unit_*`, `test_int_*`, `test_smoke_*`.
- Funciona, menos organizado.
- Markers do pytest substituem subdir, mas dev precisa lembrar.

### Opção C — `tox` + envs por layer

- Mais cerimonioso.
- Útil para multi-Python; squad fixou 3.12 (ADR-001).
- Overkill V1.

---

## Análise

| Critério | A (layered) | B (flat) | C (tox) |
|---------|-------------|----------|---------|
| Discovery clara | ✅ | manual | manual |
| CI gate por layer | ✅ | manual | trivial |
| Fixture compartilhada | ✅ | OK | ✅ |
| Esforço inicial | médio | baixo | médio |
| Familiar Python community | ✅ | ✅ | ✅ |

**Decisão:** Opção A — estrutura clara + fixtures bem definidas.

---

## Decisão

**Opção A — Estrutura `tests/{unit,integration,property,smoke,fixtures}/` + mock DLL session-scoped + fake clock + Hypothesis para invariantes + smoke gated por env explícito.**

### Layers

#### `tests/unit/`

- **Sem I/O** (sem disco, sem rede, sem subprocess).
- **Sem DLL** (mockada em fixture).
- **Determinístico** (fake clock).
- **Rápido** — toda suíte <30s.
- **Roda em CI sempre.**

Marker: `pytest.mark.unit` (default).

#### `tests/integration/`

- **I/O real** (escreve Parquet temp, SQLite temp).
- **DLL mockada** (sem chave real).
- **Filesystem isolado** (tmp_path fixture).
- **Determinístico** (fake clock).
- **Roda em CI sempre.**

Marker: `pytest.mark.integration`.

#### `tests/property/`

- **Hypothesis** para invariantes.
- **Sem DLL real.**
- **I/O permitido** (Parquet em tmp).
- **Determinístico** (Hypothesis seed fixo em CI).
- **Roda em CI sempre.**

Marker: `pytest.mark.property`.

#### `tests/smoke/`

- **DLL real** (bootstrap-dll passa).
- **Credenciais reais** (env `DATA_DOWNLOADER_NL_*`).
- **Internet ativa** (DLL conecta servidor Nelógica).
- **Lento** (minutos).
- **Custoso** (consome quota Nelógica).
- **Gated por env** + checklist obrigatório com evidência.

Marker: `pytest.mark.smoke`. **Skipa por padrão**:

```python
# conftest.py
import os
import pytest

def pytest_collection_modifyitems(config, items):
    if not os.getenv('RUN_SMOKE'):
        skip_smoke = pytest.mark.skip(reason='Set RUN_SMOKE=1 to run smoke')
        for item in items:
            if 'smoke' in item.keywords:
                item.add_marker(skip_smoke)
```

CI gate (Quinn responsável — Story 1.4.5):
- `RUN_SMOKE=1 pytest tests/smoke/ --strict-markers` em job manual.
- Output salvo em `docs/qa/smoke-runs/<date>-<commit>.log`.
- Hash SHA256 do Parquet gerado salvo em `docs/qa/smoke-runs/<date>-parquet-hashes.json`.
- Evidência exigida em PR de release (gate Epic 1).

#### `tests/fixtures/`

##### `mock_dll.py`

```python
"""ProfitDLL substituto. Reproduz contrato de callbacks sem chamar DLL real."""

from typing import Callable
from datetime import datetime, timedelta
import threading
import queue


class MockProfitDLL:
    """
    Substitui ctypes wrapper. Roda callbacks em thread separada para
    simular ConnectorThread real.

    Uso:
        mock = MockProfitDLL()
        mock.register_history_trade_callback(my_cb)
        mock.simulate_state(MARKET_CONNECTED)
        mock.simulate_trades([trade1, trade2, ...])
        mock.simulate_progress(100)
    """

    def __init__(self):
        self._callbacks: dict[str, Callable] = {}
        self._connector_thread = None
        self._event_queue = queue.Queue()
        self._stopping = threading.Event()

    def DLLInitializeMarketLogin(self, *, key, user, password, **callbacks_11):
        # Valida que recebeu 11 slots fixos (Q11-E)
        assert len(callbacks_11) == 11, 'DLL exige 11 callback slots'
        self._callbacks.update(callbacks_11)
        self._start_connector_thread()
        return 0  # NL_OK

    def SetHistoryTradeCallback(self, cb):
        self._callbacks['history_trade'] = cb
        return 0

    def SetEnabledLogToDebug(self, enabled):
        return 0

    def Finalize(self):
        self._stopping.set()
        self._connector_thread.join(timeout=5)
        return 0

    # === Test helpers ===

    def simulate_state(self, state_code: int):
        """Dispara state callback no ConnectorThread."""
        self._event_queue.put(('state', state_code))

    def simulate_trades(self, trades: list):
        """Dispara N history_trade callbacks."""
        for t in trades:
            self._event_queue.put(('trade', t))

    def simulate_progress(self, percent: int):
        self._event_queue.put(('progress', percent))

    def assert_no_dll_call_during_callback(self):
        """INV-1: nenhuma chamada à DLL deve ter ocorrido durante callback."""
        # Implementado via wrapper que checa stack frame
        ...

    def _start_connector_thread(self):
        def loop():
            while not self._stopping.is_set():
                try:
                    kind, payload = self._event_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                cb = self._callbacks.get(kind)
                if cb:
                    cb(payload)
        self._connector_thread = threading.Thread(target=loop, name='MockConnectorThread', daemon=True)
        self._connector_thread.start()
```

##### `fake_clock.py`

```python
"""Clock determinístico para testes time-dependent."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch


class FakeClock:
    def __init__(self, start: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)):
        self.now_dt = start

    def now(self) -> datetime:
        return self.now_dt

    def time(self) -> float:
        return self.now_dt.timestamp()

    def time_ns(self) -> int:
        return int(self.now_dt.timestamp() * 1e9)

    def advance(self, seconds: float):
        self.now_dt += timedelta(seconds=seconds)


@contextmanager
def freeze_time(at: datetime):
    clock = FakeClock(at)
    with (
        patch('time.time', clock.time),
        patch('time.time_ns', clock.time_ns),
        patch('datetime.datetime.now', staticmethod(clock.now)),
    ):
        yield clock
```

##### Fixtures session-scoped (M15)

```python
# tests/conftest.py

@pytest.fixture(scope='session')
def real_dll():
    """
    DLL real, init+finalize uma única vez por sessão pytest.
    Workaround para M15 (DLL não-idempotente em init→finalize→init).

    Para usar: marker `pytest.mark.smoke` no teste; fixture é injetada.
    """
    if not os.getenv('RUN_SMOKE'):
        pytest.skip('smoke disabled')

    from data_downloader.dll.wrapper import ProfitDLLWrapper
    dll = ProfitDLLWrapper()
    dll.initialize(...)
    yield dll
    dll.finalize()
```

### Property-based tests para invariantes

`tests/property/test_invariants.py`:

```python
from hypothesis import given, strategies as st, settings

# INV-2: dedup(L ++ L) == dedup(L)
@given(trades=st.lists(trade_strategy(), min_size=0, max_size=1000))
@settings(max_examples=200, deadline=2000)
def test_inv2_dedup_idempotent(trades):
    assert dedup(trades + trades) == dedup(trades)

# INV-3: download é idempotente — re-rodar não duplica
@given(symbol=symbol_strategy(), date_range=date_range_strategy())
def test_inv3_download_idempotent(symbol, date_range, mock_dll):
    download(symbol, *date_range).wait()
    snapshot1 = read_all(symbol, *date_range)
    download(symbol, *date_range).wait()  # re-rodar
    snapshot2 = read_all(symbol, *date_range)
    assert snapshot1.equals(snapshot2)

# INV-7: read() ordena por timestamp_ns ASC
@given(symbol=symbol_strategy(), date_range=date_range_strategy())
def test_inv7_read_ordered(symbol, date_range, prepopulated_storage):
    table = read(symbol, *date_range)
    timestamps = table['timestamp_ns'].to_pylist()
    assert timestamps == sorted(timestamps)
```

### INV-1: callback não chama DLL (C6 + Quinn)

```python
# tests/unit/test_inv1_callback_purity.py

def test_inv1_history_trade_callback_does_not_call_dll(mock_dll, capture_dll_calls):
    """
    INV-1: durante execução de callback, ZERO chamadas à DLL.

    Estratégia: wrap métodos da DLL para registrar call sites; após
    callback, asserta que nenhum call site veio do callback frame.
    """
    capture_dll_calls.start_recording_in_callback()

    mock_dll.simulate_trades([sample_trade()])

    # Espera callback drenar
    time.sleep(0.5)

    assert capture_dll_calls.recorded_in_callback == [], (
        f'INV-1 violated: DLL called from callback: '
        f'{capture_dll_calls.recorded_in_callback}'
    )
```

### Markers e CI gates

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "unit: fast, no I/O, no DLL (default)",
    "integration: real I/O, mocked DLL",
    "property: Hypothesis-based",
    "smoke: real DLL (gated by RUN_SMOKE=1)",
    "slow: takes >5s (excluded by -m 'not slow')",
]
```

CI matrix:
- Job `test-unit`: `pytest -m unit -m 'not slow'`
- Job `test-integration`: `pytest -m integration -m 'not slow'`
- Job `test-property`: `pytest -m property` (Hypothesis seed fixo via CI env)
- Job `test-smoke`: manual trigger; `RUN_SMOKE=1 pytest -m smoke`

### Validators (resolve C4)

`Quinn *data-validate` e `Sol *integrity-check` são CLI subcommands implementados em **Story 2.1** (movida para dentro do Epic 1 conforme PLAN_REVIEW):

```bash
data-downloader validate-data <parquet-glob>
data-downloader integrity-check <data-dir>
```

Estes invocam código em `src/data_downloader/validators/` que cobre:
- Schema match (`schema_version`).
- Sem duplicatas (dedup key).
- Sem gaps temporais inesperados (vs calendário).
- Catálogo SQLite ↔ Parquet em sync.

**Antes de Story 2.1 existir**, gate de Epic 1 usa scripts ad-hoc documentados em `docs/qa/SMOKE_PROTOCOL.md` (Quinn cria em Phase A).

---

## Consequências

### Positivas
- **Estrutura clara** — dev sabe onde colocar teste novo.
- **CI rápida** — unit+integration+property em <5min.
- **Smoke gated** — não rouba budget de CI; gate explícito de release.
- **Mock DLL canônica** — drift detectado por contract test (Nelo audita).
- **Fake clock** — testes time-dependent determinísticos.
- **INV-1 mecânico** — Quinn audita em CI, não confia em "review humano".
- **Property-based** — invariantes auditadas em milhares de inputs.

### Negativas
- **Esforço inicial alto** — `mock_dll.py` precisa ser fiel ao contrato real (Nelo audita).
- **Hypothesis aprendizado** — Quinn lidera; Dex aprende em Story 1.7b.
- **Smoke evidence** — checklist manual; risco de não rodar antes de release. Mitigação: gate Morgan `*release-readiness` exige.

### Neutras
- Smoke roda em VM Windows ou laptop dev — não em GitHub Actions free (DLL secret + Win64).

---

## Validações requeridas

- [ ] Quinn cria estrutura `tests/{unit,integration,property,smoke,fixtures}/` (Story 1.1)
- [ ] Quinn implementa `mock_dll.py` (Story 1.2 — Nelo audita fidelidade ao contrato)
- [ ] Quinn implementa `fake_clock.py` (Story 1.1)
- [ ] Quinn fixture `real_dll` session-scoped (Story 1.2 — workaround M15)
- [ ] Quinn property test INV-1 (Story 1.2)
- [ ] Quinn property tests INV-2, INV-3, INV-7 (Story 2.1)
- [ ] Quinn `SMOKE_PROTOCOL.md` com checklist de evidência (Story 0.4)
- [ ] CI: 3 jobs unit/integration/property obrigatórios; smoke manual (Gage Story 0.1)
- [ ] Hypothesis seed fixo em CI env (`HYPOTHESIS_DATABASE=cache+ci`)
