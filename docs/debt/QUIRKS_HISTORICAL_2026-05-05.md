# QUIRKS_HISTORICAL — Arquivo Histórico de Auditoria (2026-05-05)

**Curador:** Aria 🏛️ (architect) — consolidado do `docs/dll/QUIRKS.md` vivo
**Snapshot:** 2026-05-05 (post Story 1.7g Done, ADR-022 Accepted, Q17-CLOSED)
**Escopo:** quirks **REFUTADAS** (folclore desmentido) + bugs de código com **HOTFIX-APPLIED-VALIDATED** já fechados.

> **Para que serve este arquivo:**
> Este é um **registro de auditoria histórico** das hipóteses que foram propagadas no projeto e depois desmontadas por evidência empírica. Serve para **post-mortems** ("por que perdemos N dias debugando isso?"), **onboarding de novos contribuidores** ("não caia no mesmo folclore"), e **prevenção de regressão de hipótese** (alguém pode re-levantar `WDOFUT retorna 0 trades` daqui a 6 meses — este doc prova que não).
>
> **NÃO seguir as recomendações originais aqui.** Cada entrada tem campo "Status final" com a refutação e o link para a quirk canônica que substitui.
>
> **Quirks vivas (canônicas):** ver `docs/dll/QUIRKS.md`.
> **Quirks abertas P1:** ver `docs/debt/QUIRKS_OPEN_P1_2026-05-05.md`.
> **Índice executivo:** ver `docs/debt/QUIRKS_INDEX.md`.

---

## §1 — Quirks REFUTADAS (folclore desmentido)

Hipóteses que viraram regra de wrapper / story AC / ADR e depois foram REFUTADAS por evidência empírica direta. Mantidas pelo histórico — **NÃO** seguir.

| ID | Categoria | Sintoma original (refutado) | Resolução / superseded por | Refutação |
|----|-----------|------------------------------|----------------------------|-----------|
| **Q01-V** | history | "WDOFUT/WINFUT retornam 0 trades; usar contrato vigente" | superseded por [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) | Probe 2026-05-05 — WDOFUT entrega 723k trades em 4d; contratos específicos vencidos é que retornam 0. Folclore Sentinel/whale-detector v2 sem evidência reprodutível. |
| **Q11-E** | init | "JAMAIS passar None nos slots de DLLInitializeMarketLogin — corrompe registro interno" | superseded por [Q-DRIFT-06](../dll/QUIRKS.md#q-drift-06) + [Q-DRIFT-11](../dll/QUIRKS.md#q-drift-11) | Probe 2026-05-04 22:10 BRT — `None` literal nos slots 4/6/7/8 conecta em 2.43s. Exemplo oficial Nelogica `main.py` L742-743 passa `None` em 4 dos 8 slots. Folclore Sentinel §12 (~2025) custou Story 1.2 implementando `make_noop_callback` factory desnecessária. |
| **Q-DRIFT-13** | bisseção pytest | "Race condition `_set_state_callback` antes init" | refutada — Nelo audit | bissection RESUMO_EXECUTIVO_AUTONOMOUS_2026-05-04 |
| **Q-DRIFT-14** | bisseção pytest | "Lifetime de callback CFUNCTYPE" | refutada — wrapper retém refs em `_cb_refs` | wrapper grep |
| **Q-DRIFT-15** | bisseção pytest | "argtypes/restype mutados pós-init" | refutada — match exato pré/pós | wrapper inspect |
| **Q-DRIFT-16** | bisseção pytest | "Threading model MTA vs STA" | refutada — sem pytest funciona | standalone PASS |
| **Q-DRIFT-17** | bisseção pytest | "DLL hash diferente / múltiplo carregamento" | refutada — sha256 idêntico | hash check |
| **Q-DRIFT-18** | bisseção pytest | "pytest-qt autoload `CoInitializeEx(MTA)`" | refutada — `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` mantém trava | plugin disable test |
| **Q-DRIFT-19** | bisseção pytest | "pytest fd-capture → ConnectorThread bloqueia em write" | refutada — callback dispara 2s/2s durante "trava" | log timestamps |
| **Q-DRIFT-20** | bisseção pytest | "pytest-cov instala `sys.settrace` global" | refutada — sem cov, trava igual | cov disable test |
| **Q-DRIFT-21** | bisseção pytest | (gap de numeração no resumo executivo) | n/a | n/a |
| **Q-DRIFT-22** | bisseção pytest | "`tests/conftest.py` raiz importa MockProfitDLL → ctypes pré-poluído" | refutada — `--confcutdir=tests/smoke` mantém trava | confcutdir test |
| **Q-DRIFT-26** | download / data validity | "GetHistoryTrades exige data dentro de janela de pregão recente" | superseded por [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) | Standalone-pregao 2026-05-05 10:35 BRT — data dinâmica em pregão B3 aberto também trava (zero trades). Bug real era contrato vencido WDOJ26 vs continuous WDOFUT. |
| **Q-DRIFT-27** | download / wrapper | "Exchange code `'F'` errado para WDOJ26" | superseded por [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) | PETR4/B PASS + WDOFUT/F PASS — exchange code estava correto |
| **Q-DRIFT-28** | download / wrapper | "`set_history_trade_callback_v2` race / ordem" | superseded por [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) | Probe ctypes puro espelhando exemplo Nelogica reproduz mesmo zero-trades com WDOJ26 |
| **Q-DRIFT-29** | download / wrapper | "TConnectorTrade struct mismatch" | superseded por [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) | `translate_failures=0` indicou callback v2 nunca chamado, não falhou no translate |
| **Q-DRIFT-30** | download / wrapper | "make_history_trade_callback_v2 factory ref-lifetime" | superseded por [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) | Probe ctypes puro com factory inline reproduz mesmo zero-trades |

**Lição arquitetural canônica (Aria 2026-05-04):**

> **NÃO inventar quirks sem evidência empírica direta.** Q11-E veio de folclore (Sentinel §12, ~2025) sem reprodutor isolado. A regra "JAMAIS None" foi propagada por 12+ meses e provavelmente foi a causa-raiz dos timeouts Q-DRIFT-02/Q-DRIFT-10. **Toda nova quirk DEVE ter probe minimalista reprodutor antes de virar regra de wrapper.**

---

## §2 — Bugs de código com HOTFIX-APPLIED-VALIDATED

Bugs reais (não folclore) já corrigidos e validados em smoke real. Mantidos aqui após **30 dias** da validação para reduzir ruído visual em `QUIRKS.md`.

| ID | Categoria | Sintoma | Hotfix aplicado | Validado em |
|----|-----------|---------|-----------------|-------------|
| **Q-DRIFT-33** | wrapper / signatures | `minimal_handshake=True` skipava `TranslateTrade.argtypes` → `OverflowError: int too long to convert` no IngestorThread | `wrapper.py` modo minimal preserva `TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]` cirurgicamente | 2026-05-05 (postfix-35 standalone PASS, 796 963 trades) |
| **Q-DRIFT-34** | orchestrator / ingestor | `_process_trade` morria silenciosamente em `format_brt_timestamp(ns<0)` (struct sentinel TradeDate=0 da DLL); IngestorThread parava drenagem | (1) `wrapper.translate_trade` valida `TradeDate.wYear > 1900`; (2) `_process_trade` envolve body em try/except + `translate_failures += 1` | 2026-05-05 (postfix-35 standalone PASS) |
| **Q-DRIFT-35** | wrapper / signatures | `minimal_handshake=True` skipava `GetAgentNameLength`/`GetAgentName.argtypes` → length lido como `0x80000004` reinterpretado como `c_int signed = -2147483636`; risco de access violation nativa | `wrapper.py` modo minimal preserva também `GetAgentNameLength` + `GetAgentName.argtypes/restype`; `faulthandler.enable()` em smoke scripts | 2026-05-05 12:44 BRT (postfix-35 PASS) |
| **Q-DRIFT-36** | storage / schema / silent-data-loss | Writer parquet v1.0.0 silenciosamente descartava `buy_agent_name`/`sell_agent_name`/`trade_type_name` por não mapearem no schema (pyarrow descarta chaves não-mapeadas sem warning); pipeline DLL+IngestorThread populava corretamente | (1) Schema v1.1.0 aditivo: campos string nullable; (2) Writer fail-loudly: `SchemaContractViolation` se row tem chave não-mapeada; (3) Política §6.2 — schema v1.1.0 NEVER drops; (4) ADR-019 invariante I1 | 2026-05-05 (Story 1.7g Done, commit `756a61d`) |

**Política de arquivamento de bugs validados (Aria 2026-05-05):**

Bug-código com `HOTFIX-APPLIED-VALIDATED` permanece em `QUIRKS.md` por **30 dias** após validação, então migra para este arquivo (`QUIRKS_HISTORICAL`). Justificativa: 30d cobrem janela típica de regressão pós-deploy + onboarding de novo squad. Após 30d, o conhecimento canônico vive em **ADR + INVARIANTS.md + test reprodutor** — `QUIRKS.md` deve refletir apenas quirks **vivas da DLL** (a DLL é uma caixa-preta externa que pode regredir; nosso código não regride com mesmo bug se test cobre).

**Próxima migração programada:**
- 2026-06-04: Q-DRIFT-33, Q-DRIFT-34, Q-DRIFT-35 completam 30d (validados em 2026-05-05).
- 2026-06-04: Q-DRIFT-36 completa 30d (validado 2026-05-05 com Story 1.7g Done).

---

## §3 — Cross-refs canônicas (vivas)

Para cada quirk arquivada aqui, a fonte canônica viva é:

| Refutada | Canônica viva |
|----------|---------------|
| Q01-V | [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) — sempre WDOFUT para histórico |
| Q11-E | [Q-DRIFT-06](../dll/QUIRKS.md#q-drift-06) (refuta por leitura) + [Q-DRIFT-11](../dll/QUIRKS.md#q-drift-11) (refuta por probe) |
| Q-DRIFT-13..22 | RESUMO_EXECUTIVO_AUTONOMOUS_2026-05-04 + Story 1.7e (proposta para Sintoma A pytest harness) |
| Q-DRIFT-26 | [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) |
| Q-DRIFT-27..30 | [Q-DRIFT-32](../dll/QUIRKS.md#q-drift-32) |
| Q-DRIFT-33 | ADR-019 (schema-as-contract) + tests `test_writer_raises_on_missing_schema_field` |
| Q-DRIFT-34 | `INVARIANTS.md` I3 (IngestorThread sentinel resilience) + `tests/unit/test_ingestor_thread_sentinel.py` |
| Q-DRIFT-35 | ADR-019 + `wrapper.py` `_configure_dll_signatures` cirúrgico em modo minimal |
| Q-DRIFT-36 | ADR-019 + `INVARIANTS.md` I1 (schema-as-contract) + Story 1.7g closure |

---

## §4 — Auditoria de consolidação

Esta consolidação foi gerada **2026-05-05** por @architect (Aria) após:
- Story 1.7g Done (Q-DRIFT-36 fechado, schema v1.1.0).
- Q17-CLOSED confirmado (license single-session).
- ADR-022 Accepted (Single-Session Sequential Download Policy).
- Council Sol consolidação documentação (COUNCIL-35).

**Total movido para histórico:** 19 quirks (16 refutadas + 4 bug-código já validados; intersection 1 = Q11-E que tem dimensão folclore + bug fix).

**Total mantido em QUIRKS.md vivo:** ~22 quirks (validated + ambiguous + open + hypothesis ainda em investigação).

— Aria 🏛️
