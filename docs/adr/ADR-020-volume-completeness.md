# ADR-020 — Volume Completeness Invariant

> **Nota de numeração:** este ADR foi solicitado como "ADR-007" em mini-council COUNCIL-39, mas o ID 007 já está ocupado por `ADR-007-public-api.md` (com supersede em 007a). Como autoridade ADR exclusiva (MANIFEST R15), Aria numerou na sequência correta disponível: **ADR-020**. Título mantido conforme pedido.

- **Status:** Proposed
- **Data:** 2026-05-05
- **Autor:** Aria (architect)
- **Stakeholders consultados (mini-council COUNCIL-39):** Pax (Product Owner — fonte da expectativa), Quinn (QA — owner de smoke), Pyro (perf — owner de baselines), Sol (storage — owner de integridade dataset), Nelo (DLL — owner de comportamento vendor)
- **Bloqueia release:** SIM — deve ser ACCEPTED antes de tag V1.0.0; em fallback V0.9.0-rc1 pode estar ACCEPTED com `enforcement: warn-only`
- **Relacionado:** COUNCIL-36 (Pax, gap volume ~50%), COUNCIL-39 (Aria, revisão crítica), Story 1.7g AC3+AC4

---

## Contexto

Em 2026-05-05, durante mini-council de release readiness, o dono do produto trouxe expectativa de volumetria empírica:

> "1 dia útil completo de WDOFUT em pregão B3 = 600.000 a 700.000 trades."

O smoke real `1.7d-postfix35` capturou:
- **603.770 trades em 4 dias calendário** (01/05–05/05).
- **307.010 trades no único dia útil completo** (04/05, 9h25 de pregão).
- **296.758 trades no dia parcial** (05/05, ~4h até `now-10min`).

Análise (COUNCIL-36 §1, Pax):
- Pro-rated 04/05 para 10h pregão completo: ~326k esperado se taxa atual está correta.
- Expectativa do dono: 600-700k/dia → **fator 2× a 2.3× maior** que observado.
- **Gap absoluto:** ~324k trades/dia perdidos.
- **Gap percentual:** ~50% data loss.

A arquitetura **não tem invariante de completude**. R5 (idempotência) é satisfeita (re-rodar não duplica), mas dois runs idempotentes podem ambos perder os mesmos 50% — "consistência do incompleto". MANIFEST §8 critério MVP exige "contagem de trades dentro de ordem de magnitude esperada"; estamos no fundo da faixa de tolerância (fator 2×).

Mais grave: parquet escrito **parece correto** (dedup ok, schema ok, particionamento ok). Análise downstream produzirá conclusões **falsas** sobre microestrutura (volume horário, distribuição de tamanho de trade, agressor ratio). Backtests calibrarão alpha falso. **Defeito é silent corruption por incompletude.**

5 hipóteses de root-cause (Pax COUNCIL-36 §1, ranked):

| # | Hipótese | Prob. |
|---|----------|-------|
| H1 | Race `subscribe_ticker` ↔ `GetHistoryTrades` (ordering) | 30% |
| H2 | LAST_PACKET emitido prematuramente pela DLL — IngestorThread sai cedo | 30% |
| H3 | TranslateTrade descarta sentinelas legítimas | 20% |
| H4 | Janela 5 dias é cap silencioso da DLL | 15% |
| H5 | Callback V2 buffer overflow em alta liquidez | 5% |

Independente de **qual** hipótese se confirme, a **arquitetura precisa de um invariante** que detecte e/ou corrija o defeito automaticamente. Esse é o objeto deste ADR.

## Decisão

**Adotamos volume completeness como invariante arquitetural enforceada em 4 níveis.**

### Nível 1 — Volume baseline registry (canônico)

Novo documento: `docs/perf/VOLUME_BASELINES.md`.

Para cada `(symbol, contract_kind, day_type)`:
- Valor esperado em trades/dia.
- Fonte (dono do produto / ProfitChart desktop screenshot / vendor docs).
- Data de validação.
- Tolerance band (default `low=0.8, high=1.5`).

Exemplo:
```yaml
WDOFUT:
  full_day:
    expected_trades: 650000
    tolerance_low: 0.8   # 520k
    tolerance_high: 1.5  # 975k
    source: dono-do-produto (2026-05-05) + ProfitChart (a validar)
    validated_at: 2026-05-05
    validated_by: Pax
```

Owners: Sol (estrutura) + Pyro (manutenção) + dono do produto (fonte de verdade).

### Nível 2 — LAST_PACKET cross-check

`dll/wrapper.py` IngestorThread, ao receber LAST_PACKET, deve validar:

```python
# pseudocódigo
if last_packet_received:
    last_trade_ts = max(t.timestamp for t in trades_received)
    expected_end_ts = window_end - LAST_PACKET_TOLERANCE  # default 60s WDO, configurable
    if last_trade_ts < expected_end_ts:
        log.warning(
            f"LAST_PACKET prematuro: last_trade_ts={last_trade_ts} < "
            f"expected_end_ts={expected_end_ts}. Iniciando replay."
        )
        return State.NEEDS_REPLAY
    return State.COMPLETE
```

Se replay falhar 3 vezes seguidas (cap), chunk é gravado com metadata `incomplete=true` e log nível ERROR.

### Nível 3 — Replay automático

`orchestrator/download_chunk.py` aceita estado `NEEDS_REPLAY` retornado por IngestorThread:
- Re-emite `GetHistoryTrades` com janela `[last_trade_ts, original_window_end]`.
- Junta resultados ao buffer existente (dedup absorve overlap por chave canonical).
- Cap 3 replays por chunk; após cap, propaga `incomplete=true` ao writer.

### Nível 4 — Smoke completeness check (CI gate)

`tests/smoke/test_volume_completeness.py` (novo, criado em Story 1.7g AC3):

```python
def test_smoke_volume_against_baseline():
    baseline = load_baseline("WDOFUT", "full_day")
    smoke_result = run_smoke(window=1_business_day_complete)
    ratio = smoke_result.trades_count / baseline.expected_trades
    assert ratio >= baseline.tolerance_low, (
        f"Volume completeness FAILED: ratio={ratio:.2%} < "
        f"tolerance_low={baseline.tolerance_low:.0%}. "
        f"Veja ADR-020 + docs/perf/VOLUME_BASELINES.md."
    )
```

E template `docs/qa/SMOKE_EVIDENCE/*.md` ganha seção obrigatória:
```markdown
### Volume completeness
- Trades observados: 612.450
- Baseline esperado: 650.000
- Ratio: 94,2%
- Tolerance band: [80%, 150%]
- Verdict: PASS
```

### Flag `incomplete=true` no parquet metadata

Caso replay esgote retries OU smoke detecte ratio < tolerance_low durante release rc:
- Parquet escrito com metadata key `incomplete=true`.
- Public API (Epic 4) lê metadata e expõe DataFrame com attribute `df.attrs["incomplete"] = True`.
- Downstream consumers podem decidir filtrar/avisar.
- Em V1.0.0 final: `incomplete=true` deve ser **ZERO casos**. Em V0.9.0-rc1 (fallback): aceitar com warning visível.

## Alternativas consideradas

| Alternativa | Por que rejeitada |
|------------|-------------------|
| **Confiar em LAST_PACKET sem cross-check** | É exatamente o estado atual que produziu 50% loss silencioso. |
| **Bater apenas ratio sem replay** | Detecta defeito mas não corrige. Usuário re-rodaria manualmente N vezes — viola promessa "1 botão + aguardar" do MANIFEST §1. |
| **Replay infinito sem cap** | Risco de loop se DLL nunca completa janela; cap=3 + flag `incomplete` é compromisso. |
| **Baseline hardcoded em código** | Impede atualização sem deploy; baseline em `docs/perf/VOLUME_BASELINES.md` é versionado git mas editável. |
| **Tolerance fixo 100%** | Volumetria de mercado oscila legitimamente (dia tranquilo vs vol-day); banda 80-150% absorve oscilação real sem mascarar gap estrutural. |

## Consequências

### Positivas
- R1 (Foundation) cumprido: dataset entregue tem invariante de completude.
- R5 (Idempotência) reforçada: agora "consistente E completo".
- R13/R14 PASS gates ganham critério mensurável (não mais "ordem de magnitude" subjetivo).
- Defeito silencioso vira erro loudly (replay + flag + assert).
- Próximos símbolos (Epic 4.1 WIN, 4.2 equities) entram com baseline obrigatório → governança escala.

### Negativas
- Smoke real fica mais lento (replay + cross-check adicionam latência).
- Exige manutenção de baselines a cada novo símbolo / mudança estrutural de mercado.
- Tolerance band larga (80-150%) pode esconder gap menor (ex.: 20% loss). Mitigation: review periódico do tolerance por Sol+Pyro.

### Neutras
- Não afeta thread model nem storage layout (mudanças em wrapper + orchestrator + writer metadata, todas localizadas).
- Não afeta dedup, idempotência, particionamento.

## Implementação

Fases:
1. **Fase A (bloqueia release):** níveis 1+4 (baseline registry + smoke completeness check). Owner: Sol+Pyro+Quinn. Story 1.7g AC3+AC4.
2. **Fase B (release-blocker se H1/H2 confirmados):** níveis 2+3 (LAST_PACKET cross-check + replay). Owner: Nelo+Dex. Pode entrar como Story 1.7h se H1/H2 confirmadas em Story 1.7g.
3. **Fase C (continuous):** revisão de baselines a cada bump de schema, novo símbolo, vol-day extremo detectado.

## Promoção para ACCEPTED

Este ADR muda de **Proposed** → **Accepted** quando:
- (a) `docs/perf/VOLUME_BASELINES.md` criado e validado por dono+Pyro+Sol.
- (b) `tests/smoke/test_volume_completeness.py` verde com ratio ≥ 0.8 em smoke real WDOFUT 1 dia útil.
- (c) Story 1.7g AC3+AC4 PASS via Quinn QA gate.
- (d) Decisão sobre Fase B (replay automático) tomada — implementada se H1/H2 confirmados, agendada como Story 1.7h se outras hipóteses confirmadas.
- (e) Aria review final neste ADR (assina mudança de Status).

Fallback para V0.9.0-rc1 (se gap não fechar): Status muda para Accepted com `enforcement: warn-only` e Story 1.7h aberta como blocker explícito de V1.0.0 estável.

## Referências

- MANIFEST R1 (Foundation), R5 (Idempotência), R13 (PASS gate), R14 (Release readiness), R16 (Performance medida), §8 (Critérios de Sucesso).
- COUNCIL-36 (Pax) — gap ~50% identificado, 5 hipóteses de root-cause.
- COUNCIL-39 (Aria) — revisão crítica + invariantes I-N2, I-N3, I-N7, I-N8, I-N9.
- Story 1.7g — AC3 (smoke ≥500k trades) + AC4 (trades_per_day ≥500k).
- Q12-E (QUIRKS) — janela 5 dias GetHistoryTrades.
- Q-DRIFT-34 — sentinel filter (relacionado a H3).
- ADR-013 (observability) — logs estruturados para auditar replay events.
- ADR-014 (test strategy) — smoke real como evidência canônica.

---

*— Aria, autoridade ADR-first, 2026-05-05*
