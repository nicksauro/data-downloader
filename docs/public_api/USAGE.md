# `data_downloader.public_api` — Usage Guide (V1.0)

**Owner:** Aria (architect — fronteira pública SemVer-tracked).
**Status:** stable since `__api_version__ = "1.0.0"` (Story 4.3).
**Audience:** consumidores externos — backtest engine, signal generator,
risk monitor, notebooks Jupyter.

Este documento mostra **3 exemplos completos copy-paste** de consumo da API
pública V1.0, cada um cobrindo uma persona distinta. Todos os exemplos
assumem que `data-downloader` está pinado em `>=1.0,<2.0` no consumer
(ver §"Pinning version" no final).

---

## Visão Geral

A API pública expõe 4 funções, 4 classes e 8 exceções via namespace
único `data_downloader.public_api`:

```python
from data_downloader.public_api import (
    # Funções principais
    download,
    read,
    read_continuous,
    vigent_contract,
    # Async handle + dataclasses
    DownloadHandle,
    DownloadProgress,
    DownloadResult,
    DownloadStatus,
    # Hierarquia de exceções
    DataDownloaderError,
    DLLInitError,
    InvalidContract,
    DiskFull,
    DownloadError,
    IntegrityError,
    OperationCancelled,
    ConnectionLost,
    # Versão da API
    __api_version__,
)
```

**Contract-as-code:** todos os exemplos abaixo só importam de
`data_downloader.public_api` (e dependências fáceis — `pyarrow`, `pandas`,
`Catalog` do storage). Importar de `data_downloader.dll`,
`data_downloader.storage`, `data_downloader.orchestrator` ou `_internal/`
é **violação de fronteira** e quebra a garantia SemVer. Há regression test
(`test_public_api_no_internal_imports.py`) que falha se algum consumer
test atravessar a fronteira.

### Garantias V1.0 (resumo — ver `__init__.py` docstring para detalhes)

| Garantia | Descrição |
|----------|-----------|
| **Idempotência (R5)** | Re-run com mesmo input dedupa via writer canonical key |
| **BRT naive (R7)** | Todos `datetime` são naive (sem `tzinfo`); horário Brasil |
| **Dedup canônico (R5)** | `read`/`read_continuous` nunca retornam duplicatas |
| **Ordem cronológica** | `timestamp_ns` ascendente sempre |
| **Schema estável** | 17 campos canônicos + `schema_version` em metadata |
| **Cancel graceful** | `cancel()` drena chunks; trades committados preservados |
| **Sem leak interno** | Internals lançam `_InternalError`; fronteira traduz |

---

## Exemplo 1 — Backtest Engine Consumer

**Persona:** equipe de quant strategy precisa rodar backtest de uma
estratégia simples (mean-reversion) sobre 6 meses de WDO usando trades
reais. Lê histórico via DuckDB (`pyarrow.Table` → `pandas.DataFrame`)
e roda lógica em Python puro.

**Caso de uso:** download em batch (ETL one-shot) + leitura por dia
durante backtest run.

```python
"""Backtest mean-reversion WDO últimos 6 meses.

Consumer code — depende APENAS de data_downloader.public_api.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from data_downloader.public_api import (
    DataDownloaderError,
    DownloadHandle,
    InvalidContract,
    download,
    read_continuous,
    vigent_contract,
)
from data_downloader.storage.catalog import Catalog  # storage exposto p/ catalog handle

DATA_DIR = Path("./market-data")


def ensure_history(symbol_root: str, start: date, end: date) -> None:
    """ETL — garante que partições estão presentes para o range.

    Idempotente: re-run não duplica trades (R5 — writer dedup canonical).
    """
    catalog = Catalog(db_path=DATA_DIR / "history" / "catalog.db", data_dir=DATA_DIR)
    try:
        # Resolve contrato vigente em cada início de mês — WDO faz rollover mensal
        cursor = start
        while cursor <= end:
            try:
                code = vigent_contract(symbol_root, on_date=cursor, catalog=catalog)
            except InvalidContract:
                # Pula gap no calendário de contratos (raro, mas possível)
                cursor += timedelta(days=30)
                continue

            month_end = min(cursor + timedelta(days=30), end)
            print(f"Downloading {code} {cursor} → {month_end}")
            handle: DownloadHandle = download(
                code,
                start=cursor,
                end=month_end,
                data_dir=DATA_DIR,
            )
            try:
                result = handle.result(timeout=3600.0)  # max 1h por chunk de 30d
            except DataDownloaderError as exc:
                print(f"  FAIL: {exc}")
                cursor += timedelta(days=30)
                continue

            print(f"  OK: {result.trades_count} trades in {result.duration_seconds:.1f}s")
            cursor += timedelta(days=30)
    finally:
        catalog.close()


def backtest_mean_reversion(symbol_root: str, start: date, end: date) -> dict[str, float]:
    """Estratégia simples: short se preço > MA10 + 1σ, long se < MA10 - 1σ."""
    catalog = Catalog(db_path=DATA_DIR / "history" / "catalog.db", data_dir=DATA_DIR)
    try:
        # read_continuous concatena rollovers WDOH26 → WDOJ26 → WDOK26... sem duplicatas
        table = read_continuous(
            symbol_root,
            start=datetime.combine(start, datetime.min.time()),
            end=datetime.combine(end, datetime.max.time()),
            catalog=catalog,
        )
    finally:
        catalog.close()

    df: pd.DataFrame = table.to_pandas()
    df["ts"] = pd.to_datetime(df["timestamp_ns"], unit="ns")
    df = df.set_index("ts").sort_index()

    # Resample para minutos (backtest tick-to-bar)
    bars = df["price"].resample("1min").last().ffill()
    ma10 = bars.rolling(window=10).mean()
    std = bars.rolling(window=10).std()

    long_signal = bars < (ma10 - std)
    short_signal = bars > (ma10 + std)

    pnl = (bars.diff().shift(-1) * (long_signal.astype(int) - short_signal.astype(int))).sum()
    return {"pnl": float(pnl), "trades": int(long_signal.sum() + short_signal.sum())}


if __name__ == "__main__":
    end = date(2026, 4, 30)
    start = end - timedelta(days=180)

    ensure_history("WDO", start, end)
    metrics = backtest_mean_reversion("WDO", start, end)
    print(f"Backtest PnL: {metrics['pnl']:+.2f} R$ over {metrics['trades']} signals")
```

**Notas sobre garantias acionadas:**

- `vigent_contract` é determinístico — mesma `(WDO, 2026-04-15)` retorna
  sempre `"WDOJ26"`. Backtest reproducible.
- `read_continuous` aplica cut-off `+1ns` em rollovers — coluna
  `_rollover_event=True` marca boundary se você precisa ignorar o
  primeiro tick pós-rollover.
- Re-rodar `ensure_history` após crash no meio do download é seguro:
  trades já committados não são reescritos (atomic + dedup).

---

## Exemplo 2 — Live Signal Generator Consumer

**Persona:** sistema de signal generator que precisa de leitura
incremental durante o dia para alimentar indicadores em tempo real
(EMAs, VWAP, etc.). Leitura é via `pyarrow` direto (zero-copy para
NumPy quando possível) com computação vetorizada.

**Caso de uso:** download incremental no fim do dia + leitura intraday
para warm-start de indicadores.

```python
"""Live signal generator — ingestão incremental + warm-start de EMAs."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from data_downloader.public_api import (
    DownloadHandle,
    OperationCancelled,
    download,
    read,
)
from data_downloader.storage.catalog import Catalog

DATA_DIR = Path("./market-data")


def end_of_day_ingest(contract: str, day: date, *, cancel_after: float | None = None) -> int:
    """Ingere trades do dia D entre 9h e 18h.

    Args:
        contract: Código exato do contrato (ex.: "WINH26").
        day: Data BRT.
        cancel_after: Se setado, cancela após N segundos (útil em
            ambiente com SLA — protege contra DLL travada).

    Returns:
        Número de trades persistidos.
    """
    handle: DownloadHandle = download(
        contract,
        start=datetime.combine(day, time(9, 0)),
        end=datetime.combine(day, time(18, 0)),
        data_dir=DATA_DIR,
    )

    if cancel_after is not None:
        # cancel non-blocking — checa após cancel_after segundos
        # (timeout=0 = só seta o flag e retorna)
        import threading

        threading.Timer(cancel_after, lambda: handle.cancel(timeout=0)).start()

    try:
        result = handle.result(timeout=3700.0)
        return result.trades_count
    except OperationCancelled as exc:
        preserved = int(exc.details["trades_preserved"])
        print(f"Cancelled gracefully — {preserved} trades preserved")
        return preserved


def warm_start_ema(contract: str, day: date, *, period: int = 20) -> float:
    """Warm-start EMA com trades do dia D para uso em D+1.

    Usa pyarrow.compute para vetorização — zero-copy para NumPy.
    """
    catalog = Catalog(db_path=DATA_DIR / "history" / "catalog.db", data_dir=DATA_DIR)
    try:
        table: pa.Table = read(
            contract,
            start=datetime.combine(day, time(9, 0)),
            end=datetime.combine(day, time(18, 0)),
            data_dir=DATA_DIR,
        )
    finally:
        catalog.close()

    if table.num_rows == 0:
        raise ValueError(f"No trades for {contract} on {day}")

    # Zero-copy slice — pyarrow → numpy sem realocação
    prices: np.ndarray = table["price"].to_numpy(zero_copy_only=False)

    # EMA recursiva — alpha = 2/(period+1)
    alpha = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1 - alpha) * ema
    return float(ema)


def vwap_intraday(contract: str, day: date) -> float:
    """VWAP do dia usando pyarrow.compute (vetorizado)."""
    table: pa.Table = read(
        contract,
        start=datetime.combine(day, time(9, 0)),
        end=datetime.combine(day, time(18, 0)),
        data_dir=DATA_DIR,
    )
    if table.num_rows == 0:
        return float("nan")

    price = table["price"]
    qty = table["quantity"]
    notional = pc.multiply(price, qty)
    total_notional = pc.sum(notional).as_py()
    total_qty = pc.sum(qty).as_py()
    return float(total_notional) / float(total_qty) if total_qty else float("nan")


if __name__ == "__main__":
    today = date.today()
    yesterday = today - timedelta(days=1)

    # 1. Ingere D-1 ao final do dia (CRON 18h05)
    n = end_of_day_ingest("WINH26", yesterday, cancel_after=3600.0)
    print(f"Ingested {n} trades for D-1")

    # 2. Warm-start indicadores para D
    ema = warm_start_ema("WINH26", yesterday, period=20)
    vwap = vwap_intraday("WINH26", yesterday)
    print(f"D-1 close-EMA20={ema:.2f}, D-1 VWAP={vwap:.2f}")
```

**Notas sobre garantias acionadas:**

- `OperationCancelled` é o sinal **canônico** de cancel cooperativo —
  consumer trata como sucesso parcial, não como falha. `details` carrega
  `trades_preserved` para logging/telemetria.
- `read` retorna `pa.Table` ordenado — `to_numpy(zero_copy_only=False)`
  evita realocação quando o buffer Arrow está contíguo.
- `read` com range vazio retorna table vazia (não levanta) — checar
  `table.num_rows == 0` antes de processar.

---

## Exemplo 3 — Risk Monitor Consumer

**Persona:** sistema de risk monitor que agrega exposure cross-symbol
(WDO + WIN) em janela móvel para alertar quando concentração ultrapassa
limites. Lê continuamente trades de múltiplos contratos via
`read_continuous` (rollover automático).

**Caso de uso:** leitura cross-symbol agregada com schedule periódico
(a cada 15 min durante pregão).

```python
"""Risk monitor — exposure WDO + WIN em janela móvel."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from data_downloader.public_api import (
    DataDownloaderError,
    InvalidContract,
    read_continuous,
)
from data_downloader.storage.catalog import Catalog

DATA_DIR = Path("./market-data")
WINDOW = timedelta(hours=4)
LIMIT_R = 5_000_000.0  # R$ exposure limit por símbolo


@dataclass(frozen=True)
class ExposureSnapshot:
    """Snapshot de exposure agregada no instante `as_of`."""

    as_of: datetime
    by_symbol: dict[str, float]  # symbol_root → exposure em R$
    breaches: list[str]  # symbol_roots que estão acima de LIMIT_R


def _load_window(symbol_root: str, as_of: datetime) -> pd.DataFrame:
    """Lê janela móvel para um symbol_root via read_continuous (rollover-safe)."""
    start = as_of - WINDOW
    catalog = Catalog(db_path=DATA_DIR / "history" / "catalog.db", data_dir=DATA_DIR)
    try:
        table = read_continuous(
            symbol_root,
            start=start,
            end=as_of,
            catalog=catalog,
        )
    finally:
        catalog.close()
    return table.to_pandas()


def compute_exposure(roots: list[str], as_of: datetime) -> ExposureSnapshot:
    """Agrega exposure cross-symbol no instante `as_of`."""
    by_symbol: dict[str, float] = {}
    breaches: list[str] = []

    for root in roots:
        try:
            df = _load_window(root, as_of)
        except InvalidContract:
            # Fim de calendário — sem contrato vigente; assume zero
            by_symbol[root] = 0.0
            continue
        except DataDownloaderError as exc:
            # Erro qualquer da lib — log e segue (risk monitor não pode parar)
            print(f"  WARN {root}: {exc}")
            by_symbol[root] = 0.0
            continue

        if df.empty:
            by_symbol[root] = 0.0
            continue

        # Notional bruto = sum(price * qty) na janela — proxy de turnover
        notional = float((df["price"] * df["quantity"]).sum())
        by_symbol[root] = notional

        if notional > LIMIT_R:
            breaches.append(root)

    return ExposureSnapshot(as_of=as_of, by_symbol=by_symbol, breaches=breaches)


def risk_monitor_loop() -> None:
    """Loop principal — chamado por scheduler externo (cron / APScheduler)."""
    snapshot = compute_exposure(["WDO", "WIN"], as_of=datetime.now())

    print(f"[{snapshot.as_of.isoformat()}] Exposure snapshot:")
    for root, notional in snapshot.by_symbol.items():
        flag = " BREACH!" if root in snapshot.breaches else ""
        print(f"  {root}: R$ {notional:,.0f}{flag}")

    if snapshot.breaches:
        # Caller integra com PagerDuty / Slack / email aqui
        print(f"  ALERT: {len(snapshot.breaches)} breach(es) — escalate to risk desk")


if __name__ == "__main__":
    risk_monitor_loop()
```

**Notas sobre garantias acionadas:**

- `read_continuous` para WDO + WIN concorrentemente é seguro:
  `Catalog` é re-criado por chamada (sem state shared cross-thread). Em
  produção, prefira pool de catálogos read-only.
- `InvalidContract` é levantado só na `read_continuous` quando *nenhum*
  contrato cobre porção do range — risk monitor assume `0.0` (fail-safe
  = sem exposure conhecida) e segue.
- Janela móvel de 4h × dois símbolos = ~10s de read em SSD — a 15 min
  cadence o monitor não acumula latência.

---

## Pinning version

No `pyproject.toml` do consumer, **sempre** pinar com major-bound:

```toml
[project]
dependencies = [
    "data-downloader>=1.0,<2.0",
    # outras deps...
]
```

Em runtime, **inspecionar** a versão para sanity check em startup do
consumer:

```python
from data_downloader.public_api import __api_version__

assert __api_version__.startswith("1."), (
    f"Incompatible data-downloader API: {__api_version__}; "
    "consumer requires >=1.0,<2.0"
)
```

### Migração entre versões

- **Patch** (`1.0.0 → 1.0.1`): sempre seguro. Re-instalar e seguir.
- **Minor** (`1.0.0 → 1.1.0`): sempre seguro (aditivo). Pode usar
  símbolos novos opcionalmente; código antigo continua funcionando.
- **Major** (`1.x → 2.0`): pode quebrar. **Ler o CHANGELOG** seção
  "Breaking changes" e a seção "Deprecated → Removed" antes de bumpar.
  Símbolos removidos foram anunciados como `@deprecated` em release(s)
  prévia — `DeprecationWarning` no log do consumer é seu aviso prévio.

### Workflow recomendado de upgrade

1. Capturar `DeprecationWarning` em CI (filterwarnings: ``error::DeprecationWarning``).
2. Antes de cada release de consumer, bumpar `data-downloader` patch ou minor.
3. Quando chegar nova major (`2.0`), criar branch de upgrade, ler
   CHANGELOG seção breaking, fazer os edits, rodar test suite.

Ver `docs/public_api/DEPRECATION_POLICY.md` para política completa.

---

## Referências

- `docs/public_api/DEPRECATION_POLICY.md` — política formal de deprecação.
- `docs/adr/ADR-007a-public-api-redesign.md` — design rationale `DownloadHandle`.
- `docs/adr/ADR-011-exception-hierarchy.md` — hierarquia de exceções.
- `CHANGELOG.md` — histórico de bumps + seção "Deprecated".
- Source: `src/data_downloader/public_api/` — docstrings completos por
  função/classe.
