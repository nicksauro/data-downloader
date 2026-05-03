# ADR-001 — Python 3.12 + ctypes como runtime

**Status:** accepted
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 🗝️ Nelo, 💻 Dex
**Supersedes:** —
**Related:** ADR-003 (PySide6), ADR-005 (thread model)

---

## Contexto

A ProfitDLL é Win32/Win64 stdcall, com exemplos oficiais Nelogica em **C#, C++, Delphi e Python (ctypes)**. O squad precisa de uma linguagem para o backend (DLL wrapper, orchestrator, storage, public_api) e CLI.

Restrições:
- Win64 obrigatório (DLL).
- Squad inteiro precisa ler/auditar o código (Nelo audita wrapper; Sol audita storage; Quinn audita testes).
- Front desktop entrará em escopo (Epic 3+) → linguagem que tenha framework UI maduro.
- Performance importa (R16) — tick data, throughput >= 100k trades/s na escrita Parquet.

---

## Opções Consideradas

### Opção A — Python 3.12 + ctypes
**Prós:**
- Exemplos oficiais Nelogica em Python (`profit_dll.py`, `profitTypes.py`, `main.py`) — reuso direto.
- ctypes é stdlib, sem dep extra.
- Ecossistema data engineering inigualável (pyarrow, duckdb, pandas, polars).
- PySide6 maduro para UI desktop (mesmo processo do backend).
- Hypothesis para property-based testing.
- Squad inteiro consegue ler.

**Contras:**
- GIL limita paralelismo CPU-bound (mitigado: usar `multiprocessing` para multi-symbol).
- Não nativamente compilado; PyInstaller distribui interpreter junto.
- Type-check posterior (mypy/pyright), não compile-time.

### Opção B — C# (.NET 8)
**Prós:**
- Exemplo oficial Nelogica em C#.
- Performance superior em CPU-bound.
- Tipagem estática estrita.
- WPF/WinUI3 para UI.

**Contras:**
- Ecossistema data engineering inferior (Parquet via Microsoft.Hadoop.Avro/Parquet.Net — menos maduro).
- DuckDB binding via NuGet existe mas menos exercitado.
- Property-based testing menos canônico (FsCheck existe, menos popular).
- Squad teria que migrar conhecimento.

### Opção C — Rust + bindings
**Prós:**
- Performance máxima.
- Memória segura.
- Tauri para UI moderna.

**Contras:**
- ctypes equivalente em Rust (libloading) é correto mas verboso.
- Ecossistema Parquet/DuckDB bom (arrow-rs, duckdb-rs) mas curva alta.
- Time não tem Rust expertise; risco de delay grande.
- Cada change exige recompilação — feedback loop pior em desenvolvimento de pipeline de dados.

---

## Decisão

**Opção A — Python 3.12 + ctypes.**

Versão mínima: **3.12** (não 3.11) para usufruir de:
- `X | None` em vez de `Optional[X]` (PEP 604 estendido).
- Improved error messages.
- `tomllib` na stdlib.
- Performance gains do CPython 3.12.

Razões da escolha:
1. **Reuso imediato** dos exemplos Nelogica (`profit_dll.py` 102 linhas, `profitTypes.py` 455 linhas, `main.py` 1273 linhas).
2. **Ecossistema** Parquet/DuckDB/PyArrow é o melhor disponível em qualquer linguagem.
3. **PySide6** = UI desktop madura, mesmo processo do backend → zero IPC overhead (vide ADR-003).
4. **Property-based testing** (Hypothesis) é state-of-the-art em Python.
5. **GIL não é blocker**: callback DLL é IO-bound; multi-symbol via `multiprocessing` (cada DLL exige processo próprio anyway — limite Nelogica).

---

## Consequências

### Positivas
- Aceleração imediata: time arranca do `main.py` Nelogica.
- Tooling maduro (ruff, mypy, pytest, pyinstaller).
- Onboarding fácil de novos contribuidores.
- Iteração rápida em pipeline de dados.

### Negativas
- Distribuição = bundle PyInstaller (`.exe` ~80-150 MB com PyArrow + DuckDB + PySide6). Aceitável.
- Type errors detectados em CI (mypy), não em compile time. Mitigação: rodar `mypy` em PR (Gage configura CI).
- GIL — trabalhado via multiprocessing onde necessário (Pyro valida).

### Neutras
- Versão Python congelada em 3.12 até decisão consciente de upgrade.

---

## Validações requeridas

- [ ] Smoke test contra DLL real em Windows com Python 3.12 (Story 1.2 — gate)
- [ ] Pyro `*bench_parquet_write` >= 100k trades/s (Story 2.2)
- [ ] PyInstaller produz .exe rodável em Windows limpo (Gage — Epic 3)
