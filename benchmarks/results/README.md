# benchmarks/results/ — Output de benchmarks

Este diretório armazena resultados JSON de cada execução de benchmark.

## Convenção de nomes

```
{benchmark_name}-{YYYY-MM-DD}-{git_sha_short}.json
```

Exemplos:
- `bench_parquet_write-2026-05-03-a1b2c3d.json`
- `bench_callback_to_disk-2026-05-15-f9e8d7c.json`

`git_sha_short` = primeiros 7 chars do commit em que o benchmark rodou (HEAD se workdir limpo, `HEAD-dirty` se uncommitted changes).

## Schema canônico

Todo JSON deve seguir esse schema base (campos `[bench_specific]` variam por benchmark):

```json
{
  "benchmark": "bench_parquet_write",
  "version": "1.0.0",
  "git_sha": "a1b2c3d",
  "git_dirty": false,
  "date": "2026-05-03T18:42:00-03:00",
  "hardware": {
    "cpu_model": "Intel Core i7-12700H",
    "cpu_cores_physical": 14,
    "cpu_cores_logical": 20,
    "ram_gb": 32,
    "disk_type": "NVMe SSD",
    "disk_model": "Samsung 980 Pro 1TB",
    "os": "Windows 10 Pro 22H2 build 19045"
  },
  "python": {
    "version": "3.13.0",
    "implementation": "CPython"
  },
  "dependencies": {
    "pyarrow": "20.0.0",
    "duckdb": "1.5.0",
    "structlog": "24.4.0"
  },
  "dll_version": "4.0.0.30",
  "config": {
    "n_runs_per_scenario": 5,
    "warmup_runs": 1
  },
  "scenarios": [
    {
      "...bench_specific...": "..."
    }
  ],
  "summary": {
    "winner": {"...": "..."},
    "verdict": "PASS|FAIL",
    "vs_target": {
      "target_metric": "trades_per_sec",
      "target_value": 100000,
      "measured_value": 145000,
      "delta_pct": 45.0
    }
  },
  "notes": "Run em laptop dev; resultados de produção podem variar."
}
```

## Como ler

### CLI (TODO — script `compare.py`):
```powershell
python -m benchmarks.compare \
    benchmarks/results/bench_parquet_write-2026-05-03-a1b2c3d.json \
    benchmarks/results/bench_parquet_write-2026-05-15-f9e8d7c.json
```

Output:
```
bench_parquet_write — comparação
================================
config: row_group=100000, compression=snappy

trades_per_sec: 145,000 → 132,000  (-9.0%)  WARN
mb_per_sec:        320 →    295    (-7.8%)  WARN
peak_rss_mb:       510 →    528    (+3.5%)  OK
p99_ms:            145 →    162    (+11.7%) REGRESSION (budget=10%)

Verdict: REGRESSION (1/4 metrics)
```

### Programático:
```python
import json
from pathlib import Path

results_dir = Path("benchmarks/results")
latest = max(results_dir.glob("bench_parquet_write-*.json"),
             key=lambda p: p.stat().st_mtime)
data = json.loads(latest.read_text())
print(data["summary"]["vs_target"])
```

## Política de versionamento

- **NÃO commitamos resultados normais** ao git (`.gitignore` deve cobrir `*.json` aqui).
- **Commitamos baselines canônicos** sob `benchmarks/results/baselines/` (TODO: criar quando 1ª baseline existir).
- **Atualização de baseline** exige commit explícito + assinatura de Pyro.

## Retenção

Resultados locais podem ser limpos a qualquer momento. Apenas `benchmarks/results/baselines/` é canônico.

— Pyro ⚡
