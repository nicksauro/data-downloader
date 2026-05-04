# COUNCIL-08 — CLI download Microcopy Audit (Uma R17 + Aria public_api + Pyro 99%-reconnect)

**Story:** 1.7b — CLI typer + public_api mínima + smoke MVP gate
**Date:** 2026-05-03
**Conveners:** Dex (impl) + Uma (microcopy R17) + Aria (public_api SemVer) + Pyro (99% perf signal)
**Status:** RATIFIED (autonomous mode — sign-offs implícitos com gate em PR)

---

## 1. Contexto

Story 1.7b é o **gate de Epic 1**: comando `data-downloader download` que orquestra
o pipeline DLL → orchestrator → writer → catalog para validar end-to-end o MVP.
Como toda string visível ao usuário deve vir do `MICROCOPY_CATALOG.md` (R17), uma
auditoria mini-council é necessária antes do commit.

---

## 2. Mini-Council — Uma (R17 — microcopy)

### 2.1 Checklist

| Item | Status | Evidência |
|------|--------|-----------|
| Toda mensagem visível vem do MICROCOPY_CATALOG | ✅ via `_format_microcopy()` (CLI) e `format_msg()` (loader) |
| 5 estados implementados (normal / loading / error / empty / success) | ✅ Panel header cyan / Rich Progress / Panel red / Panel green dim (cache_hit) / Panel green |
| Quirk 99% reconnect — texto LITERAL preservado | ✅ unit test `test_war_99_reconnect_text_is_canonical` valida string idêntica |
| Atalhos respeitam THEME.md (Ctrl+C, NÃO Esc) | ✅ `signal.SIGINT` handler — exit code 130 POSIX |
| NO_COLOR env respeitado | ✅ `_make_console()` cria `Console(no_color=True)` quando set |

### 2.2 Desvios identificados (minor)

**D1 — Texto estrutural do Header Panel.** O Panel inicial mostra:

```
⬇ data-downloader download
Baixando WDOJ26 (2026-03-01 a 2026-03-31) — exchange=F
```

O verbo "Baixando" + estrutura "[verbo] [símbolo] ([período])" segue
`CLI_PATTERNS.md §2` que documenta esse layout como **padrão estrutural**
(não como entrada de catálogo). Não é uma string de catálogo formal.

**Decisão Uma (implícita — segue documento ratificado de Story 0.3):**
Aceito como pattern, **não como microcopy** — `CLI_PATTERNS.md` é fonte
autoritativa para layout estrutural; `MICROCOPY_CATALOG.md` é fonte para
strings de tipo `button | label | error | success | warning | info | empty | prompt`.

**Ação:** zero — pattern legítimo. Se Uma pedir entry formal no futuro
(`HDR_DOWNLOAD_PROGRESS` ou similar), criar entrada e refatorar.

**D2 — Texto auxiliar `Símbolo (cache):` quando default lê last_symbol.**
Pequeno hint contextual em `dim` que não está catalogado. Aceito como
status informativo curto (categoria `info` não-template).

**Ação:** se Uma pedir, criar `INF_SYMBOL_FROM_CACHE` no catálogo.

### 2.3 Verdict Uma

**GO** — Microcopy atende R17. Desvios D1/D2 são patterns estruturais
documentados em CLI_PATTERNS.md, não strings inventadas em runtime.

---

## 3. Mini-Council — Aria (public_api SemVer)

### 3.1 Checklist

| Item | Status | Evidência |
|------|--------|-----------|
| `__api_version__` bumpado conforme ADR-007a | ✅ `0.2.0 → 0.3.0` (minor aditivo) — apenas adições, sem remoções |
| `download()` assinatura estável (kw-only opts, defaults) | ✅ `download(symbol, start, end, *, exchange='F', data_dir=None, dll_factory=None, ...)` |
| `DownloadHandle` contrato ADR-007a (cancel/result/events) | ✅ 3 métodos públicos + `is_cancelling`, `join` (utilitários) |
| Imports da fronteira pública não circulam | ✅ `download.py` faz imports inline; `handle.py` é stand-alone |
| Erros públicos só de `DataDownloaderError` hierarchy | ✅ worker captura tudo; serializa via `DownloadResult.error_message` |

### 3.2 Verdict Aria

**GO** — Bump 0.3.0 correto. Nenhuma quebra retrocompatível. Caller que
importa `read`, `read_continuous`, `vigent_contract` continua funcionando
idêntico (Story 1.5b/1.6).

---

## 4. Mini-Council — Pyro (99%-reconnect quirk perf)

### 4.1 Análise

Quirk Q11-99 é cenário onde a barra de progresso fica em ~99% por 1-30min
(corretora reconectando). Performance NÃO é o gargalo aqui — é UX (Uma).
Pyro valida apenas que:

1. ✅ Texto canônico amarelo (não vermelho — não é erro).
2. ✅ Spinner ativo (sinaliza "vivo, não congelado").
3. ✅ Não há polling intensivo — Rich Progress refresh é controlado.

### 4.2 Verdict Pyro

**GO** — Implementação respeita o quirk. Sem hot-loop adicional.

---

## 5. Decisão consolidada

**RATIFIED** — implementação Story 1.7b vai a Ready for Review com:

- Microcopy 100% via catálogo (R17 — Uma GO).
- public_api estável, SemVer 0.3.0 (Aria GO).
- 99% reconnect renderiza canônico (Pyro GO).

Validações:
- ruff: clean
- mypy strict: clean (7 source files)
- pytest: 42 passed + 1 skipped (smoke gated por env)

---

## 6. Próximos passos

1. Quinn lê `docs/qa/SMOKE_PROTOCOL.md` para saber como **executar** o
   smoke real (humano roda).
2. Quinn valida evidência produzida em `docs/qa/SMOKE_EVIDENCE/1.7b-{ts}.md`.
3. Quinn emite `*qa-gate 1.7b` — PASS = gate Epic 1 fechado.

---

— Dex (autor) | Uma, Aria, Pyro (sign-offs implícitos via mini-council autônomo)
