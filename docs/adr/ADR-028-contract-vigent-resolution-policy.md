# ADR-028 — Contract resolution policy: root vs vigent-per-chunk + fail-loudly on cross-rollover

- **Status:** Proposed
- **Date:** 2026-05-17
- **Author:** Aria (@architect) + consulta @data-engineer (Sol), @qa (Quinn)
- **Driver:** Revisão consolidada Frente 3 v1.4.0 — P0-D1 (Q-DRIFT-32 derived): `_resolve_contract` em `orchestrator.py:794` resolve contrato vigente **uma única vez** com `config.start.date()`; jobs cuja janela `[start, end]` atravessa rollover baixam todos os chunks com o **mesmo** `contract_code`. Para dias fora da vigência desse contrato a DLL retorna **0 trades silenciosamente** (perda completa de dados nesses dias, sem erro visível).
- **Supersedes:** — (complementa ADR-006 §"Decisão" e Q-DRIFT-32 em `docs/dll/QUIRKS.md`)

---

## 1. Contexto

ADR-006 estabeleceu o calendário de contratos vigentes como tabela estática versionada (`docs/storage/CONTRACTS.md` → `catalog.db.contracts`). A função `vigent_contract(catalog, root, on_date)` retorna o `contract_code` cuja janela `[vigent_from, vigent_until]` cobre `on_date`. Caso ideal — produção opera com `WDOFUT`/`WINFUT` (continuous future, `vigent_from=1900-01-01, vigent_until=9999-12-31` — ver `CONTRACTS.md:100-114`), e cada `vigent_contract("WDOFUT", any_date)` retorna `WDOFUT`. Golden path.

**O bug** mora no caminho não-golden — chamadas com raízes mensais/trimestrais legacy (`WDO`, `WIN`, etc.):

```python
# src/data_downloader/orchestrator/orchestrator.py:785-799
def _resolve_contract(self, config: JobConfig) -> str:
    if not config.resolve_contract:
        return config.symbol
    return vigent_contract(
        self._catalog,
        config.symbol,
        config.start.date(),     # <-- resolvido UMA VEZ com data de início
        exchange=config.exchange,
    )
```

Cenário concreto:

- Usuário invoca `download("WDO", start=2026-01-15, end=2026-06-15)`.
- `vigent_contract(WDO, 2026-01-15)` retorna `WDOG26` (fevereiro/26 — ver `CONTRACTS.md` seção WDO, contratos H/J/K... cobrindo meses sequenciais).
- Orchestrator entra no loop chunked com `contract_code="WDOG26"` para **todos os chunks**.
- Chunk de 2026-01-15..2026-01-31 — DLL aceita `WDOG26` e retorna trades reais.
- Chunk de 2026-03-15..2026-03-31 — `WDOG26` está vencido (vigência expira ~final fev). DLL aceita o ticker (não levanta erro), **retorna 0 trades silenciosamente**. Q-DRIFT-32 documentado.
- Resultado: dia 2026-03-15 fica gravado como `chunk_ledger` status `no_trades` (write-once gap) — semanticamente "este dia não tem trades" — quando na verdade é "este dia tem trades mas pedimos com contrato errado".

A perda é **silenciosa** porque o catálogo registra `no_trades` (válido para fins-de-semana e feriados) e os retries do orchestrator não disparam (DLL retornou ret=0). O usuário só descobre quando faz consulta `read_continuous` e percebe gaps.

### 1.1 Workaround tácito atual

A convenção de fato no squad é **"usar `WDOFUT`/`WINFUT` para downloads"** — esses são tickers continuous-future cadastrados em CONTRACTS.md como `symbol_root == contract_code == "WDOFUT"` com vigência `[1900..9999]`. Calls com `WDOFUT` passam o lookup, recebem `WDOFUT` de volta, e **nunca cruzam rollover** porque a DLL Nelogica trata `XXXFUT` como agregação interna.

A convenção funciona — mas:

1. Não é mecânica. Qualquer chamador legítimo com raiz simples (`WDO`, `WIN`, `IND`, `DOL`, ou futuras como `BGI` boi gordo) cai no buraco.
2. Não é descoberta. Documentação `docs/storage/CONTRACTS.md:135-138` diz "usuário casual deve usar WDOFUT", mas a API pública não enforça.
3. Não cobre uso legítimo de contratos específicos (research/auditoria histórica — ex.: backtester quer reproduzir exatamente o que o trader fez em `WDOJ26`). Esses casos exigem `start..end` dentro da vigência do contrato; cruzar rollover deveria falhar.

### 1.2 Sintoma em prod

Sintoma é diagnosticável post-hoc via `catalog.gaps`/`chunk_ledger` mas **invisível durante o download**: ProgressCard mostra "100% completo" mesmo com 80% dos dias retornando `no_trades` falsos. Pichau identificou um caso onde 6 meses de WDO chamado por raiz pura entregaram apenas o primeiro mês completo + 5 meses de `no_trades` — investigação consumiu ~3h até atribuir a Q-DRIFT-32.

## 2. Decisão

**Híbrido — fail-loudly default + opt-in para per-chunk re-resolution.**

A política respeita os 3 perfis de chamador:

| Perfil | Como passa o symbol | Resultado |
|--------|---------------------|-----------|
| **Continuous-future (golden path)** | `WDOFUT`, `WINFUT`, `INDFUT`, `DOLFUT`, equities | Funciona como hoje. Lookup retorna ticker = root. Zero código novo. |
| **Specific contract** | `WDOJ26`, `WINH26`, etc. (resolve_contract=False OU symbol já é code) | Funciona como hoje SE `[start, end]` dentro da vigência. Se cruza rollover → erro claro. |
| **Root simples** | `WDO`, `WIN`, `IND`, `DOL`, `BGI`, etc. | **Default (v1.4.0):** falha cedo se `[start, end]` cruza rollover. Mensagem instrui usar `WDOFUT` (golden path) ou contrato específico. **Opt-in:** se `JobConfig.resolve_contract_per_chunk=True`, re-resolve por chunk e baixa cada dia com o vigente correto. |

### 2.1 Componente 1 — `_validate_config` ganha rollover-spanning check

```python
# src/data_downloader/orchestrator/orchestrator.py:749 (expandido)

def _validate_config(self, config: JobConfig) -> None:
    """Valida invariantes antes do run."""
    if config.exchange not in ("F", "B"):
        raise ValueError(...)
    if config.end < config.start:
        raise ValueError(...)
    if config.max_retry_attempts < 1:
        raise ValueError(...)

    # Story 4.26 — defesa contra rollover-spanning silencioso (Q-DRIFT-32).
    if config.resolve_contract and not config.resolve_contract_per_chunk:
        self._validate_no_rollover_in_window(config)


def _validate_no_rollover_in_window(self, config: JobConfig) -> None:
    """Valida que o range [start, end] não cruza rollover sob a raiz config.symbol.

    Conta quantos contracts vigentes da raiz cobrem o range. Se > 1 → rollover-spanning.
    Levanta AmbiguousRolloverError com mensagem prescritiva.
    """
    contracts_in_range = self._catalog.list_contracts_in_range(
        root=config.symbol,
        start=config.start.date(),
        end=config.end.date(),
    )
    if len(contracts_in_range) > 1:
        codes = sorted(c.contract_code for c in contracts_in_range)
        raise AmbiguousRolloverError(
            symbol_root=config.symbol,
            start=config.start.date(),
            end=config.end.date(),
            contracts_in_range=codes,
        )
```

`AmbiguousRolloverError` (subclasse de `InvalidContract` em `public_api/exceptions.py`) traz mensagem prescritiva:

```
Symbol root 'WDO' cobre 4 contratos vigentes no range [2026-01-15, 2026-06-15]:
  WDOG26 (vigent 2025-12-30..2026-01-29)
  WDOH26 (vigent 2026-01-29..2026-02-26)
  WDOJ26 (vigent 2026-02-26..2026-03-30)
  WDOK26 (vigent 2026-03-30..2026-04-29)

Cross-rollover downloads com raiz são bloqueados por padrão (Q-DRIFT-32).
Escolha UMA opção:

  1. Use o continuous-future (recomendado para histórico longo):
       download('WDOFUT', start=..., end=...)

  2. Use o contrato específico (sub-range deve caber dentro da vigência):
       download('WDOJ26', start=2026-02-26, end=2026-03-30)

  3. Habilite re-resolução por chunk explicitamente (opt-in avançado):
       download('WDO', start=..., end=..., resolve_contract_per_chunk=True)
       (cada dia baixa com o vigente correto; cross-FS-friendly mas requer
        contracts table populada cobrindo todo o range).
```

### 2.2 Componente 2 — `JobConfig.resolve_contract_per_chunk: bool = False`

```python
# orchestrator.py JobConfig (Story 4.26)
@dataclass(frozen=True)
class JobConfig:
    ...
    resolve_contract: bool = True
    resolve_contract_per_chunk: bool = False  # NEW — Story 4.26 opt-in
```

Quando `True`:

- Bypass do `_validate_no_rollover_in_window` (caller assume risco/responsabilidade).
- `_resolve_contract` se torna no-op (retorna `config.symbol` como placeholder; loop chunks NÃO usa o retorno).
- Loop `for chunk in chunks` no `Orchestrator.run` chama `vigent_contract(self._catalog, config.symbol, chunk.start.date())` **por chunk** ANTES de `_process_chunk`. Esse `contract_code` por-chunk passa para `_process_chunk` em vez do `contract_code` global.

Refator do `Orchestrator.run` (apenas o caminho per-chunk):

```python
# Pseudo-código — substitui o trecho atual ~orchestrator.py:482, 555-...
contract_code_global = self._resolve_contract(config)   # Hoje
# Vira:
if config.resolve_contract_per_chunk:
    contract_code_global = config.symbol  # placeholder semantico
else:
    contract_code_global = self._resolve_contract(config)

for chunk_index, chunk in enumerate(chunks):
    if config.resolve_contract_per_chunk:
        try:
            chunk_contract_code = vigent_contract(
                self._catalog, config.symbol, chunk.start.date(),
                exchange=config.exchange,
            )
        except InvalidContract:
            # Re-raise — sem vigência para esse dia, falha loud
            raise
    else:
        chunk_contract_code = contract_code_global

    result = self._process_chunk(
        job_id=job_id,
        config=config,
        contract_code=chunk_contract_code,
        chunk=chunk,
        metrics=metrics,
    )
    ...
```

**Compat:** `_process_chunk` já aceita `contract_code: str` como parâmetro (`orchestrator.py:913`). Per-chunk mode apenas varia o valor passado. Zero mudança na assinatura.

### 2.3 Componente 3 — `Catalog.list_contracts_in_range`

Método novo em `storage/catalog.py` (delega para `contracts` module):

```python
def list_contracts_in_range(
    self,
    *,
    root: str,
    start: date,
    end: date,
) -> list[Contract]:
    """Lista contratos vigentes para root que se sobrepõem ao range [start, end]."""
    conn = self._conn_or_raise()
    rows = conn.execute(
        """
        SELECT * FROM contracts
         WHERE symbol_root = ?
           AND vigent_from <= ?
           AND vigent_until >= ?
         ORDER BY vigent_from ASC
        """,
        (root, end.isoformat(), start.isoformat()),  # overlap: cf.from <= end AND cf.until >= start
    ).fetchall()
    return [_row_to_contract(r) for r in rows]
```

Retorna lista vazia se a raiz não tem vigência alguma cobrindo o range → `_validate_no_rollover_in_window` deixa passar (fail-late no `vigent_contract` que vai levantar `InvalidContract` normal — mensagem útil).

Retorna lista de 1 → range cabe inteiro em um contrato → safe, prossegue.

Retorna lista > 1 → rollover-spanning detectado → `AmbiguousRolloverError`.

### 2.4 Componente 4 — `AmbiguousRolloverError` (exception nova)

```python
# src/data_downloader/public_api/exceptions.py (adiciona)

class AmbiguousRolloverError(InvalidContract):
    """Raised when [start, end] window spans multiple contracts under a root.

    Default-blocked behavior (Q-DRIFT-32 defense): user must choose
    continuous-future OR specific contract OR opt-in per-chunk resolution.
    """
    def __init__(
        self,
        symbol_root: str,
        start: date,
        end: date,
        contracts_in_range: list[str],
    ) -> None:
        self.symbol_root = symbol_root
        self.start = start
        self.end = end
        self.contracts_in_range = contracts_in_range
        # Mensagem multi-linha prescritiva — ver §2.1 acima
        super().__init__(symbol_root, start, exchange=None)
```

Subclasse de `InvalidContract` para que código existente que já captura `InvalidContract` continue funcionando (compat). Quem quiser distinguir captura por tipo.

### 2.5 Telemetria e logs

- Log estruturado no orchestrator quando rollover detected:
  ```python
  log.warning(
      "orchestrator.rollover_spanning_blocked",
      symbol_root=config.symbol,
      start=config.start.date().isoformat(),
      end=config.end.date().isoformat(),
      contracts_in_range=codes,
      remedy="use_continuous_future_or_split_or_opt_in_per_chunk",
  )
  ```
- Quando `resolve_contract_per_chunk=True` ativa:
  ```python
  log.info(
      "orchestrator.per_chunk_contract_resolved",
      job_id=job_id,
      chunk_start=chunk.start.date().isoformat(),
      contract_code=chunk_contract_code,
      symbol_root=config.symbol,
  )
  ```

UI consume o `AmbiguousRolloverError` no adapter (`ui/adapters/download_adapter.py`) e exibe um dialog com as 3 opções clicáveis (CTA "Usar WDOFUT" / "Dividir range" / "Avançado: per-chunk"). Story 4.26 AC8.

### 2.6 Backward-compat

- Chamadas com `WDOFUT`/`WINFUT`/`INDFUT`/`DOLFUT`/equities (`PETR4` etc): **zero impacto**. `list_contracts_in_range` retorna 1 contrato → validation passa.
- Chamadas com `WDO`/`WIN`/etc onde range cabe em 1 contrato: **zero impacto**. Validation passa.
- Chamadas com `WDO`/`WIN`/etc onde range cruza rollover: **breaking change**. Antes silenciosamente baixava dados parciais; agora falha cedo com mensagem prescritiva. **Justificado** — o comportamento anterior era bug, não feature.
- Tests existentes que dependem do bug (se houver — Quinn audita em Story 4.26 AC4): atualizar para usar `WDOFUT` OU `resolve_contract_per_chunk=True` explícito.
- `resolve_contract=False` (configs antigas): caller responsável; nada muda. Validation rollover-check só dispara se `resolve_contract=True`.

### 2.7 Migração & rollout

- Sem mudança de DDL (catálogo existente serve).
- Sem mudança em `CONTRACTS.md` seed (mas docs §1.1 deve ganhar nota sobre nova policy).
- Estratégia release: incluir em v1.4.0 minor bump. Documentar prominentemente em `docs/release-notes/v1.4.0.md` e `CHANGELOG.md`.

## 3. Cenários verificados

| Cenário | Resultado esperado |
|---------|--------------------|
| `download('WDOFUT', 2025-01-01, 2026-12-31)` | Funciona (continuous future, sem rollover) |
| `download('WDOJ26', 2026-02-26, 2026-03-30)` | Funciona (specific contract, range dentro da vigência) |
| `download('WDOJ26', 2026-02-26, 2026-04-15)` | `resolve_contract=False` por inferência (symbol é code) → orchestrator usa `WDOJ26` direto → DLL retorna 0 trades pós-vigência. **Não detectado por esta ADR** (assumimos caller é avançado quando passa contract code). |
| `download('WDO', 2026-01-15, 2026-01-28)` (cabe em WDOG26) | Funciona (1 contrato cobrindo, validation passa) |
| `download('WDO', 2026-01-15, 2026-06-15)` (cruza rollover) | **`AmbiguousRolloverError`** com mensagem prescritiva listando WDOG26..WDOK26 e 3 opções. |
| `download('WDO', 2026-01-15, 2026-06-15, resolve_contract_per_chunk=True)` | Funciona: cada chunk diário baixa com vigente correto. Catálogo registra partitions sob `contract_code` heterogêneo. |
| `download('WDO', 2030-01-01, 2030-06-15, resolve_contract_per_chunk=True)` | `InvalidContract` no primeiro chunk fora-de-vigência (seed CONTRACTS.md não tem 2030). Mensagem instrui popular contratos. |
| Cancel mid-run em modo per-chunk | Graceful — `cancel_event` ainda checa entre chunks (ADR-022 single-session sequential). |
| Resume de job iniciado em per-chunk mode | Funciona — `chunk_ledger` armazena `contract_code` por dia, resume lê de lá. |
| Cache hit em range completo | Funciona — `_compute_chunks` filtra ledger por contract_code; em per-chunk mode, filtra por root via `list_contracts_in_range`. (Story 4.26 AC6 — `_compute_chunks` ganha awareness de per-chunk.) |

## 4. Consequências

### Positivas

- **Q-DRIFT-32 silent loss eliminado.** Cross-rollover com raiz falha cedo OU baixa correto (com flag explícita).
- **Continuous future torna-se documentado/enforced golden path.** Mensagem da exception é onboarding implícito.
- **Compat preservada para 99% dos casos.** Apenas o cenário bug-prone fica bloqueado por padrão.
- **Opt-in escape hatch.** Caso de uso legítimo (research multi-mês com seguimento de rollover) ainda atende, com flag explícita.
- **Telemetria diagnosticável.** Logs estruturados informam exatamente o que aconteceu.
- **Sem mudança de DDL.** Catálogo intacto. Migração trivial.

### Negativas / trade-offs

- **Breaking change parcial.** Chamadas com `WDO`/`WIN` cruzando rollover param de funcionar (silenciosamente entregando lixo). Quem dependia disso precisa ajustar. Mitigado: mensagem da exception é prescritiva; CHANGELOG destaca; release notes V1.4.0 explica.
- **Per-chunk mode tem overhead.** Cada chunk executa 1 lookup SQLite adicional. Cool path (1 por chunk, ADR-022 1 dia/chunk), custo desprezível (~1ms).
- **`_compute_chunks` precisa de awareness.** Em per-chunk mode, filtro `done_days` precisa considerar contract_code heterogêneo. Story 4.26 AC6 endereça. Risco: lógica fica mais complexa nesse hot-path (ainda assim cool — 1 query por run).
- **Testes precisam novos cenários.** ~4-6 testes novos (validation rollover-block / per-chunk happy path / per-chunk com gap / cache hit per-chunk). Story 4.26 AC7.
- **UI dialog adicional.** download_adapter precisa traduzir AmbiguousRolloverError para diálogo com 3 botões. Story 4.26 AC8. Pequeno trabalho UX.
- **Documentação.** ADR-006 ganha amendment apontando para esta ADR como complemento. `docs/storage/CONTRACTS.md` ganha seção "Resolution policy" referenciando ADR-028. Q-DRIFT-32 em QUIRKS.md ganha update status (de "workaround=use WDOFUT" para "v1.4.0 fail-loudly + opt-in").

## 5. Alternativas consideradas

| Opção | Por que rejeitada |
|-------|-------------------|
| **A pura — re-resolve por chunk default** | Quebra suposição de "1 download = 1 contract_code" amplamente usada em catálogo + UI + storage layout. Risco de drift de schema em partitions (cada dia sob contract_code diferente). Per-chunk como opt-in mantém invariante para 99% dos casos. |
| **B pura — sempre falha em raiz multi-rollover** | Remove capacidade legítima de "download 7 anos de WDO seguindo rollover" sem alternativa. Por isso adicionamos opt-in. |
| **C — auto-fallback silencioso para WDOFUT quando raiz é WDO** | Magic. Esconde decisão do caller. Quebra reprodutibilidade ("eu pedi WDO mas veio WDOFUT?"). |
| **D — exception genérica `InvalidContract` sem subclass** | Caller não consegue distinguir "vigência ausente" de "rollover detected"; mensagem fica genérica. |
| **E — validar rollover em `vigent_contract` (não em `_validate_config`)** | `vigent_contract` é chamado em múltiplos callsites (orchestrator, UI preview, scripts). Centralizar em `_validate_config` mantém escopo do check no boundary correto (job submission). |
| **F — adicionar nova função `download_continuous` que sempre re-resolve** | Duplicação da API pública; aumenta surface. `resolve_contract_per_chunk` flag é menos invasivo. |
| **G — runtime warning + prosseguir** | Não corrige o bug — usuário ignora warnings. Fail-loudly força resolução. |

## 6. Referências

- `src/data_downloader/orchestrator/orchestrator.py:785-799` (`_resolve_contract` — callsite com 1-resolve bug)
- `src/data_downloader/orchestrator/orchestrator.py:482` (uso em `Orchestrator.run`)
- `src/data_downloader/orchestrator/orchestrator.py:749-758` (`_validate_config` — extension point)
- `src/data_downloader/orchestrator/contracts.py:155-219` (`vigent_contract` — lookup canônico)
- `src/data_downloader/storage/catalog.py` (alvo de `list_contracts_in_range`)
- `src/data_downloader/public_api/exceptions.py:146` (`InvalidContract` — base para `AmbiguousRolloverError`)
- `docs/storage/CONTRACTS.md:100-114` (continuous futures `WDOFUT`/`WINFUT`/etc)
- `docs/storage/CONTRACTS.md:140-162` (WDO mensal — legacy contracts)
- `docs/storage/CONTRACTS.md:135-138` (nota tácita "usuário casual deve usar WDOFUT")
- `docs/dll/QUIRKS.md` Q-DRIFT-32 (`docs/dll/QUIRKS.md:1331-1346` — silent 0-trades quando contrato vencido)
- ADR-006 (calendário de contratos vigentes — base da tabela `contracts`)
- ADR-022 (single-session sequential policy — relevante para per-chunk overhead)
- ADR-023 (uniform chunk policy 1d — torna per-chunk re-resolution custeável)
- Revisão consolidada 2026-05-16 (Frente 3: Rollover Safety)

— Aria 🏛️, mapeando o calendário sob movimento
