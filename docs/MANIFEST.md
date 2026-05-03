# MANIFEST — Squad data-downloader

> Carta fundadora do squad. Princípios inegociáveis. Toda decisão consulta este documento.

**Versão:** 1.0.0
**Data:** 2026-05-03
**Status:** ratificado

---

## 1. Missão

Construir um **downloader de histórico de ativos via ProfitDLL da Nelogica** que seja **a fundação eficiente, íntegra e duradoura para TODOS os projetos futuros** do usuário (backtest, live signals, risk, research).

A promessa de produto para o usuário final:

> **"Selecionar símbolo + período + clicar 1 botão + aguardar."**

A promessa técnica para projetos downstream:

> **"Ler dados via DuckDB com schema estável, sem duplicatas, sem gaps inesperados, idempotente, versionado."**

---

## 2. Escopo

### IN
- Download de histórico de trades via `GetHistoryTrades` (ProfitDLL).
- Persistência em **Parquet (Snappy) + DuckDB (query) + SQLite (catálogo)**.
- Particionamento `data/history/{exchange}/{symbol}/{year}/{month}.parquet`.
- Calendário de **contratos vigentes** (WDO/WIN inicialmente; equities depois).
- **Idempotência** absoluta: re-rodar download é no-op.
- **Resumability**: checkpoint por chunk; falhas retomam de onde pararam.
- **CLI funcional** primeiro (Epic 1 = MVP CLI).
- **Front desktop PySide6** (Epic 3+).
- **Public API** estável (Epic 4) para projetos downstream consumirem.

### OUT (Não-objetivos atuais)
- Trading / envio de ordens (não é downloader).
- Live market data streaming em produção (foco é **histórico**; live só para QA/smoke).
- Backtest engine / signal generator (são **consumidores** dessa fundação, não esse projeto).
- Distribuição multi-tenant / cloud (uso single-user, single-machine, Windows desktop).
- macOS / Linux nativos (a DLL é Windows-only — não tem caminho).

---

## 3. Princípios Inegociáveis (Constitution)

> Numerados R1..Rn. Violação detectada bloqueia merge. Override exige assinatura
> da autoridade indicada.

### **R1 — Foundation primeiro**
O data-downloader é **base de TODOS os projetos futuros**. Schema, dedup, idempotência, versionamento são INVARIANTES. Feature que enfraquece foundation é vetada por **Morgan**, mesmo que pareça atraente.

### **R2 — Manual ProfitDLL é fonte primária para tudo de DLL**
**Nelo** é a única autoridade sobre comportamento da DLL. Toda função/callback/struct/enum citada em código tem referência ao manual. Comportamento empírico vai para `docs/dll/QUIRKS.md` com classificação (validado/ambíguo/empírico).

### **R3 — Callback DLL = `queue.put_nowait()` apenas**
Manual ProfitDLL §4 diz: "as funções de requisições à DLL ou qualquer outra função da interface da DLL NÃO devem ser chamadas dentro de um callback". Implementação que viola = bug crítico. Quinn bloqueia.

### **R4 — Schema é contrato perpétuo**
Cada Parquet escrito carrega metadata `schema_version`. Mudança aditiva = bump minor. Mudança quebradora = bump major + script de migração + ADR. **Sol** tem autoridade exclusiva sobre schema.

### **R5 — Idempotência absoluta**
Re-rodar download de `(symbol, date_range)` é no-op. Implementação: dedup por chave `(symbol, timestamp_ns, trade_id_dll | hash_canonical)` antes de gravar. Quinn valida via property-based test.

### **R6 — Catálogo SQLite é fonte única de "o que está baixado"**
Parquet é o **dado**. Catálogo é o **índice**. Reconciliação periódica catálogo↔arquivos detecta drift. Sem catálogo = sem garantia de consistência.

### **R7 — Timestamps em BRT naive**
Manual ProfitDLL não explicita timezone, mas validação empírica (Nelo) confirma BRT naive (horário local B3, sem offset). Conversão para UTC destrói semântica de fase de pregão (DST, leilões). **Não converter.** Consumidores recebem BRT.

### **R8 — Bolsa é uma letra única**
Manual §3.1 linha 1673: literal `Bovespa="B"`, `BMF="F"`. Não usar `"BMF"` (retorna `NL_EXCHANGE_UNKNOWN`).

### **R9 — Contratos vigentes — não chutar letras de mês**
Mapa de contratos (WDOJ26 etc) validado contra (a) tabela oficial Nelogica/B3 OU (b) probe direto na DLL via Nelo. **Sol** mantém o mapa em `docs/storage/CONTRACTS.md` com `validation_source` e `validated_at`.

### **R10 — Funções V1 são obsoletas, usar V2**
Manual marca como "obsoleta em favor da nova função": `SendBuyOrder, SendSellOrder, SendChangeOrder, SendCancelOrder, SendZeroPosition, GetOrders, GetOrder, GetPosition`. Usar V2 sempre que possível (`SendOrder, SendChangeOrderV2, ...`). Aplicável quando trading entrar em escopo (não no MVP).

### **R11 — UI nunca bloqueia MainThread Qt**
Toda operação > 16ms vai para `QThread`/`QtConcurrent`. Slots no MainThread executam em < 16ms (60 FPS budget). **Felix** mede via `*responsiveness-audit`. **Pyro** valida.

### **R12 — `git push` / `gh pr create` / `gh pr merge` é monopólio de Gage**
Outros agentes commitam local (`git add/commit/status/diff/log/branch/checkout/merge`). **Gage** publica. Sem essa fronteira, não há trilha de auditoria.

### **R13 — Story só vai para `Ready for Review` com Quinn PASS**
PASS de Quinn exige: (a) AC todas demonstradas, (b) testes verdes + cobertura >= 80% em camadas críticas, (c) data-validate clean (se story produziu Parquet), (d) lint+typecheck limpos, (e) auditoria do dono (Sol/Nelo/Aria) se afetou domínio especializado.

### **R14 — Release exige todos os PASSes**
Release exige PASS de **Quinn** (qualidade) + **Pyro** (sem regressão > budget) + **Sol** (integridade dataset) + **Aria** (sem ADR proposed em escopo) + autorização explícita de **Morgan**. Sem todos = sem release.

### **R15 — ADR-first para decisões transversais**
Toda decisão que cruza camadas vira ADR numerado em `docs/adr/`. Adoção de nova dependência transversal exige ADR. **Aria** tem autoridade exclusiva para criar/aprovar ADR.

### **R16 — Performance medida, não palpitada**
Toda otimização tem baseline em `docs/perf/BASELINES.md`. Regressão > 10% bloqueia merge (override por Aria/Morgan). **Pyro** mede; ninguém otimiza sem medir.

### **R17 — Microcopy é design, não enfeite**
Toda mensagem ao usuário responde: (a) o que aconteceu, (b) o que o usuário pode fazer. **Uma** tem autoridade exclusiva sobre microcopy. Sem palavra inventada por Felix/Dex em runtime.

### **R18 — Zero secret no repo**
`.env`, credenciais ProfitDLL, tokens — nunca commitados. **Gage** opera pre-push hook bloqueando padrões conhecidos. `.gitignore` explícito.

### **R19 — Build determinístico**
Mesmo SHA → mesmo `.exe` (modulo metadata reproducible). Build não-determinístico é bug. **Gage** investiga.

### **R20 — Stories pequenas (< 3 dias)**
Story > 3 dias é decomposta. Stories grandes escondem complexidade e bug. Decomposição é trabalho de **Morgan**.

---

## 4. Autoridades (matriz resumida)

> Detalhes em `ROLES.md`.

| Domínio | Autoridade exclusiva |
|---------|---------------------|
| Comportamento da ProfitDLL | 🗝️ **Nelo** |
| Schema Parquet, catálogo, contratos vigentes | 💾 **Sol** |
| Arquitetura, fronteiras, ADRs, public_api | 🏛️ **Aria** |
| Microcopy, fluxos, wireframes, theme | 🎨 **Uma** |
| Implementação UI Qt | 🖼️ **Felix** |
| Implementação backend Python | 💻 **Dex** |
| Verdict de QA gate (PASS/CONCERNS/FAIL/WAIVED) | 🧪 **Quinn** |
| Baselines, regression budgets | ⚡ **Pyro** |
| Escopo de epic/story, validação de story, release readiness | 📋 **Morgan** |
| `git push`, `gh pr create/merge`, packaging, release tag | ⚙️ **Gage** |

---

## 5. Workflow Resumido

> Detalhes em `WORKFLOW.md`.

```
@morgan create-epic
  → @morgan create-story → @morgan validate-story (10 pts)
    → @dex develop (consulta @nelo / @sol / @aria conforme story)
      → @quinn qa-gate → PASS / FAIL
        ↳ FAIL: @dex apply-qa-fixes (max 2 ciclos) → re-gate
        ↳ PASS: @morgan release-readiness?
          → @gage push / package / release
```

Para stories de UI:

```
@morgan create-story (UI)
  → @uma flow + wireframe + microcopy
    → @felix implement-screen (consultando @uma para desvios)
      → @quinn qa-gate (visual + responsiveness)
        → @gage build / package
```

---

## 6. Fluxos Cross-Agent Padrão

### Implementação que toca DLL
```
@dex *consult nelo {pergunta}
  → Nelo responde com (a) snippet executável, (b) referência manual §X linha Y
  → Dex implementa
  → Nelo audita PR via *audit-wrapper
  → Quinn QA gate
```

### Implementação que toca storage
```
@dex *consult sol {pergunta}
  → Sol responde com schema + chave dedup + query DuckDB
  → Dex implementa
  → Sol audita PR via *audit-storage-pr
  → Quinn QA gate (com data-validate)
```

### Decisão arquitetural transversal
```
@aria *adr-new {título}
  → Consulta @nelo (se DLL) / @sol (se storage) / @uma (se UX)
  → Propõe 2+ alternativas
  → Aceita → @aria *adr-accept {NNN}
  → Stories ajustadas conforme ADR
```

### Release
```
@morgan *release-readiness {milestone}
  → Verifica PASS Quinn + Pyro + Sol + Aria
  → GO → autoriza @gage
@gage *release {version}
  → Bump version, changelog, tag, build, GitHub release
```

---

## 7. Não-Objetivos Explícitos

- **Não somos um trading system.** Trading entra como projeto downstream, não aqui.
- **Não somos uma plataforma multi-usuário.** Single-user desktop Windows.
- **Não somos uma data lake genérica.** Especializados em market data B3 via ProfitDLL.
- **Não buscamos cross-platform.** A DLL é Windows. Outros OS = projeto separado (não há).
- **Não somos um substituto do ProfitChart.** Somos um pipeline de coleta + persistência + leitura programática.

---

## 8. Critérios de Sucesso

### MVP (Epic 1, Story 1.7 gate)
- ✅ CLI baixa **30 dias de WDO contrato vigente** sem intervenção manual.
- ✅ Re-rodar mesmo comando = no-op (idempotência).
- ✅ DuckDB lê 100% dos trades baixados.
- ✅ Catálogo SQLite reflete o que está em disco.
- ✅ Contagem de trades dentro de ordem de magnitude esperada.
- ✅ Quinn PASS no gate.

### V1 Release
- ✅ Front PySide6 cumprindo promessa "1 botão + aguardar" (Epic 3).
- ✅ Public API estável documentada (Epic 4).
- ✅ Multi-symbol (WDO + WIN + 1 equity) (Epic 4).
- ✅ `data_downloader.exe` empacotado e rodável em Windows limpo (Gage).

---

## 9. Versionamento deste documento

Mudanças neste MANIFEST exigem:
- Discussão entre todos os agentes do squad.
- Aprovação de **Morgan** + **Aria**.
- Bump de versão.
- Entrada em changelog deste arquivo.

### Changelog
- **1.0.0** (2026-05-03) — Versão inicial. Squad ratificado: Aria, Sol, Nelo, Uma, Felix, Dex, Quinn, Pyro, Morgan, Gage. 20 princípios (R1..R20).

---

*— Squad data-downloader, ratificado em 2026-05-03*
