# COUNCIL-18 — Test Strategy ADR-014 Implementation Ratification

**Data:** 2026-05-04
**Convocação:** Mini-council Quinn + Dex + Aria — modo autônomo (Story 2.10)
**Participantes mentais:**
- 🧪 Quinn (QA — gatekeeper, autoridade sobre `tests/`, `docs/qa/`,
  `INVARIANTS_TESTS.md`)
- 💻 Dex (Backend Developer — implementer, dono de
  `src/data_downloader/testing/`)
- 🏛️ Aria (Architect — autora de ADR-014, ratifica conformidade)

**Reviewers (downstream):**
- 🗝️ Nelo (ProfitDLL Specialist — fidelidade do MockProfitDLL ao contrato real)
- 📋 Morgan (PM — origem da Story 2.10, gate Epic 2 G-Quality-Final)

---

## Contexto

Story 2.10 implementa ADR-014 (Test Strategy):
- Mock DLL fixture compartilhada (extração de `tests/conftest.py` + `benchmarks/fixtures/`).
- Fake clock determinístico (substitui ad-hoc `time.sleep` em retry/circuit_breaker).
- Suite Hypothesis core para invariantes críticas (INV-1..12).
- Subpackage opt-in `data_downloader.testing` para consumidores downstream
  (Epic 4 multi-asset + projetos derivados).

Antes desta story:
- Mock vivia em `tests/conftest.py` Story 1.2 (não reusable em benchmarks);
- `benchmarks/fixtures/mock_dll.py` era stub `NotImplementedError`;
- INVs cobertas por property tests dispersos sem agregação canônica.

---

## Decisão Quinn (test strategy)

✅ **Approved.** A consolidação atende AC4 ADR-014:

- 6 INVs core cobertas por Hypothesis property tests em
  `tests/property/test_invariants_core.py` (INV-1, INV-2, INV-3, INV-7,
  INV-9, INV-11).
- Cada property usa >= 100 examples (deadline=None para evitar flakiness
  em CI lento).
- Meta-test (`tests/integration/test_invariants_core.py`) audita
  mapping → impede drift entre `INVARIANTS_TESTS.md` e suite.
- Strategies canônicas (`valid_trade_record_strategy`,
  `valid_partition_key_strategy`, `trade_spec_strategy`) reusáveis em
  novos property tests sem boilerplate.

Quinn ratifica que `INVARIANTS_TESTS.md` agora marca cada INV coberta
com `✓ Hypothesis property test em <path>`.

---

## Decisão Dex (implementação)

✅ **Approved.** O subpackage `data_downloader.testing` foi extraído cleanly:

- `src/data_downloader/testing/__init__.py` (33 linhas, re-exports estáveis)
- `src/data_downloader/testing/mock_dll.py` (~520 linhas, MockProfitDLL +
  Q02-E reconnect quirk + INV-1 violation detection)
- `src/data_downloader/testing/fake_clock.py` (~270 linhas, FakeClock +
  monotonia ns-exact + freeze/thaw + patch_time context manager)
- `src/data_downloader/testing/fixtures.py` (~165 linhas, fixtures
  pytest reutilizáveis: `mock_dll_session`, `fake_clock`, `tmp_catalog`,
  `tmp_data_dir`, `synthetic_trades_factory`)

Backwards compatibility:
- `benchmarks/fixtures/mock_dll.py` agora é stub DEPRECATED que
  re-exporta de `data_downloader.testing.mock_dll` (zero breakage para
  benchmarks legados).
- `tests/conftest.py` re-exporta as 6 fixtures de
  `data_downloader.testing.fixtures` (descoberta automática mantida).

Coverage agregada `data_downloader.testing` = **84.5%** (excede target 80%).

---

## Decisão Aria (ADR-014 conformance)

✅ **Approved.** A implementação está conforme ADR-014 §Layers + §Mock DLL:

- **Layer 1 (atomic):** `mock_dll_session`, `fake_clock`, `tmp_catalog`,
  `tmp_data_dir` — todas implementadas e parametrizáveis.
- **Layer 2 (composto):** `synthetic_trades_factory` (depende de RNG com
  seed) — implementado.
- **Mock fiel ao contrato:** superfície pública da MockProfitDLL espelha
  `ProfitDLL.wrapper.ProfitDLL` (init/wait/history/finalize/dll_version),
  validado por `test_mock_surface_matches_real_wrapper`.
- **M15 / Q08-E:** reinit pós-finalize raises (replicado conforme manual
  Nelógica observação).
- **INV-1 mecânico:** `MockProfitDLL.callback_violations` detecta
  automaticamente quando callback chama de volta a superfície pública —
  Quinn audita via `assert mock.callback_violations == []`.
- **Property-based:** Hypothesis profile padrão (sem freezing CI/dev em
  Story 2.10 — diferimos para Story 2.11/Epic 3 quando ci profile gate
  for fechado por @devops).

---

## Riscos identificados (todos mitigados)

| Risco | Severidade | Mitigação |
|-------|-----------|-----------|
| MockProfitDLL drift contra DLL real | Médio | `test_mock_surface_matches_real_wrapper` falha quando método público é removido; Nelo audita anualmente |
| Fake clock thread-safety | Baixo | Lock interno + meta-test concurrent advances (4 threads × 250 advances) |
| INV-11 (separação threads) testado por proxy | Baixo | Property atual cobre determinismo de dedup+sequence; teste real de threads vivo em Story 1.7a `tests/integration/test_orchestrator.py::test_orchestrator_state_machine_observed_transitions` |
| Coverage de `fixtures.py` baixo (44%) | Informativo | Fixtures são exercitadas via discovery do pytest (não chamadas diretamente em test code); coverage agregada do subpackage = 85% |

---

## Findings cross-agent

Nenhum CRITICAL/HIGH levantado. Findings MEDIUM:

- **F-Q-2 (Quinn):** F-Q-1 (cobertura `--cov` bloqueada por duckdb) **não
  resolvido nesta story** — apenas documentado em
  `INVARIANTS_TESTS.md`. Continua deferred para Story 3.x.
- **F-D-1 (Dex):** Coverage de `testing/fixtures.py` em isolamento é 44%
  (fixtures consumidas via pytest discovery, não chamadas diretas). OK
  conforme padrão da codebase.

---

## Próximos passos

- Story 2.11 (CI hardening): adicionar Hypothesis profile `ci/dev/thorough`
  em `pyproject.toml` + CI matrix por layer (unit/integration/property).
- Story 3.x: resolver F-Q-1 (`--cov` line coverage com duckdb).
- Epic 4: novos property tests para multi-asset reusam strategies
  canônicas sem reinventar (`valid_trade_record_strategy`).

---

— Quinn 🧪 / Dex 💻 / Aria 🏛️ — mini-council COUNCIL-18 ratificado.
