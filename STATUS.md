# 📊 STATUS — data-downloader

> Resumo executivo do estado do projeto. Atualizado: 2026-05-05 (Quinn @qa — Story 1.7d consolidação WDOFUT)

## 🎯 Estado consolidado

| Epic | Stories | Status |
|------|---------|--------|
| **1 — Foundation** | 17/17 | ⚠️ Done* (smoke real bloqueado por Q-DRIFT-33 + Q-DRIFT-34 — bugs no orchestrator/wrapper) |
| **2 — Quality & Performance** | 11/11 | ✅ Done (todas) |
| **3 — Desktop UI** | 3/N | ✅ Done (3.1 + 3.2 + 3.3) — funcional |
| **4 — Multi-asset & V1.0** | 4/4 | ⚠️ Done* (4.3 limpo; 4.1/4.2/4.4 com WAIVERs — bloqueio mudou para bugs código) |

**Asterisco (\*)** = stories Done com WAIVER. **Bloqueio mudou (2026-05-05):** Q-DRIFT-02 (handshake 5min) é provavelmente FALSO; o bug real é dois bugs novos no nosso código:
- **Q-DRIFT-33:** `minimal_handshake=True` quebra `TranslateTrade.argtypes` (overflow).
- **Q-DRIFT-34:** `IngestorThread._process_trade` morre em `format_brt_timestamp(<0)` na primeira invocação sentinela do callback V2.

Probe minimalista (`scripts/probe_history_minimal.py`) confirmou em 2026-05-05 que a conta TEM permissão BMF, MARKET_CONNECTED em 1.6s, e WDOFUT/F + 4 dias = **723.587 trades reais**. O bug é nosso, não da DLL/conta/contrato.

---

## 🔢 Números

- **70 commits** autônomos no `main`
- **~1201 testes** passando, 1 skipped, 0 failed
- **Cobertura ~88%** em camadas críticas (storage, orchestrator, dll)
- **~30 documentos de decisão (COUNCILs)** registrados
- **17 ADRs** + 5 amendments
- **~75 microcopy IDs** em catálogo Uma
- **5 WAIVERs abertos** — todos relacionados a Q-DRIFT-02

---

## 🚦 O que falta para publicar V1.0.0 oficial

**Trabalho de código pendente (Dex):**

1. **Q-DRIFT-33 hotfix** — em modo `minimal_handshake=True`, ainda registrar `TranslateTrade.argtypes`. Skipar APENAS as signatures de inicialização que comprovadamente trazem o crash de smoke 5.
2. **Q-DRIFT-34 hotfix** — `IngestorThread._process_trade` deve guardar `try/except` ou `wrapper.translate_trade` deve retornar `None` quando `TradeDate.wYear <= 1900` (sentinel zero).
3. Re-rodar `scripts/run_smoke_real_standalone.py` com WDOFUT — esperado: trades > 0, status=ok.
4. Re-rodar pytest smoke 1.7d com WDOFUT + 5 dias — esperado: PASS.
5. **Smoke 1.8-followup** — Pyro re-mede baselines → ~5 min.
6. **Smoke 4.1/4.2** — multi-symbol → ~20 min.
7. **Build PyInstaller** (Gage) → ~5 min.
8. **GitHub Release** v1.0.0 (Gage) → ~2 min.

**Total estimado:** Q-DRIFT-33+34 fix em ~30 min de Dex + smoke chain ~50 min.

---

## 🗝️ Q-DRIFT-02 — REAVALIAÇÃO (2026-05-05)

3 attempts anteriores de smoke autônomo confirmaram empiricamente:
- DLL **autentica** com sucesso (credenciais OK!)
- DLL **fica travada em `MARKET_DATA/(2,1)`** por > 5 min
- Em todos os 3 attempts, ProfitChart **NÃO estava rodando**

**Hipótese original (LIKELY-FALSE):** ProfitDLL exige ProfitChart aberto. Em 2026-05-05, ProfitChart NÃO estava rodando e MARKET_CONNECTED chegou em 1.6s (probe minimalista) e 1.7s (standalone). Logo, **a hipótese "ProfitChart simultâneo é pré-requisito" foi REFUTADA empiricamente**.

**Hipótese revisada:** o travamento histórico em `MARKET_DATA/(2,1)` provavelmente foi causado por (a) WDOJ26/WDOK26 (contrato vencido) + (b) janela 30 dias (servidor rejeita silenciosamente — Q-DRIFT-31). Com WDOFUT + 5 dias, handshake completa rapidamente.

**Q-DRIFT-02 será arquivado em próxima sweep** (rebaixar status para REFUTED ou downgrade severity).

---

## 📁 Como usar agora (sem release oficial)

```powershell
# 1. Abrir ProfitChart e fazer login com sua chave
# 2. Verificar .env existe com credenciais
# 3. Rodar:
python -m data_downloader.cli download --symbol WDOJ26 --start 2026-03-01 --end 2026-03-30

# 4. Em projetos downstream:
from data_downloader.public_api import download, read, vigent_contract
contract = vigent_contract('WDO', date(2026, 3, 15))
table = read(contract, datetime(2026, 3, 1), datetime(2026, 3, 30))
```

API V1.0 **estável** — pinar como `data_downloader>=1.0.0,<2.0.0`.

---

## 🛑 Modo autônomo encerrado (após esta atualização)

Esgotei trabalho útil sem dependência de DLL real. Não vou mais agendar wakeups cegos.

**Quando você voltar:**
1. Abra ProfitChart
2. Diga no chat: *"ProfitChart aberto"* ou similar
3. O squad re-roda smoke + finaliza release V1.0.0

---

## 📚 Onde ler mais

- **Visão geral**: `README.md`
- **Princípios**: `docs/MANIFEST.md` (R1..R21)
- **Quem decide**: `docs/ROLES.md`
- **Arquitetura**: `docs/ARCHITECTURE.md`
- **ADRs**: `docs/adr/` (17 ADRs + amendments)
- **Stories**: `docs/stories/` (~30 stories)
- **Decisões**: `docs/decisions/` (~30 COUNCILs)
- **WAIVERs abertos**: `docs/qa/WAIVERS/`
- **Uso público**: `docs/public_api/USAGE.md`
- **Instalação**: `docs/release/INSTALL.md`
