# 📊 STATUS — data-downloader

> Resumo executivo do estado do projeto. Atualizado: 2026-05-04

## 🎯 Estado consolidado

| Epic | Stories | Status |
|------|---------|--------|
| **1 — Foundation** | 17/17 | ✅ Done* (smoke real bloqueado por Q-DRIFT-02) |
| **2 — Quality & Performance** | 11/11 | ✅ Done (todas) |
| **3 — Desktop UI** | 3/N | ✅ Done (3.1 + 3.2 + 3.3) — funcional |
| **4 — Multi-asset & V1.0** | 4/4 | ✅ Done* (4.3 limpo; 4.1/4.2/4.4 com WAIVERs) |

**Asterisco (\*)** = stories Done com WAIVER esperando smoke real (1 ação humana = abrir ProfitChart).

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

**1 ação humana necessária:**

> **Abrir o ProfitChart, fazer login com a chave Nelogica configurada em `.env`, deixar rodando.**

**Quando isso acontecer (smoke desbloqueia em cadeia):**

1. **Smoke 1.7b-followup** — download 30 dias WDOJ26 real → PASS esperado em ~5-15 min
2. **Smoke 1.8-followup** — Pyro re-mede baselines com DLL real → ~5 min
3. **Smoke 4.1-followup** — multi-symbol paralelo → ~10 min
4. **Smoke 4.2-followup** — WIN+PETR4 multi-asset → ~10 min
5. **Build PyInstaller** local (Gage) → ~5 min
6. **GitHub Release** v1.0.0 (Gage) → ~2 min

**Total: ~30-50 min** depois de você abrir ProfitChart.

---

## 🗝️ Q-DRIFT-02 (HIPÓTESE LIKELY)

3 attempts de smoke autônomo confirmaram empiricamente:
- DLL **autentica** com sucesso (credenciais OK!)
- DLL **fica travada em `MARKET_DATA/(2,1)`** por > 5 min
- Em todos os 3 attempts, ProfitChart **NÃO estava rodando**

**Hipótese:** ProfitDLL exige ProfitChart aberto concorrentemente para handshake `MARKET_DATA` completar. Documentado em `docs/dll/QUIRKS.md` e `docs/release/INSTALL.md`.

**Validação final:** depende de você abrir ProfitChart e confirmar.

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
