# SMOKE PROTOCOL — Download Real contra DLL

> Resolução do **finding C5** (PLAN_REVIEW 2026-05-03):
> "Smoke gated por env nunca roda em CI — gate de Epic 1 vira honor system".
>
> Protocolo único e auditável para smoke test contra ProfitDLL real. Sem este
> documento, smoke é honor system; com este documento, smoke é evidência
> rastreável e verificável.

---

## 1. Objetivo

Garantir que o caminho **CLI → orchestrator → DLL real → write Parquet → catálogo SQLite → re-read DuckDB** funciona end-to-end com a `ProfitDLL.dll` instalada e licença Nelogica ativa, **antes** de marcar o gate de Epic 1 como PASS.

---

## 2. Quem pode rodar

**Apenas o usuário humano**, na máquina Windows que possui:

- `ProfitDLL.dll` + companions DLLs + `.dat` instalados (caminho conhecido).
- Licença Nelogica ativa e credenciais (`PROFIT_USER`, `PROFIT_PASS`, `PROFIT_KEY`) em `.env` local.
- Ambiente Python 3.11+ com `data-downloader` instalado (modo dev: `pip install -e .`).
- Internet estável (banda mínima 1 Mbps; smoke pode baixar ~50-200 MB).

**Agentes (Quinn, Dex, Gage, etc.) NÃO podem rodar este teste** — não têm DLL nem licença. Quinn **valida a evidência produzida** pelo humano.

---

## 3. Quando rodar

| Gatilho                                           | Modo                |
|---------------------------------------------------|---------------------|
| Pré-merge de Story **1.7b** (gate Epic 1)         | `--full` obrigatório |
| Cada release `V*` (V1, V1.1, V2, ...)             | `--full` obrigatório |
| Após mudanças em `dll/`, `orchestrator/`, `storage/writer.py` | `--quick` recomendado |
| Diagnóstico ad-hoc (suspeita de regressão)        | `--quick` ou `--full` |

> **Smoke não roda em CI.** CI roda apenas mocks. O gate de Epic 1 depende
> EXPLICITAMENTE de smoke real produzido pelo humano e arquivado em `docs/qa/smoke_runs/`.

---

## 4. Como rodar

### 4.1 Quick smoke (1 dia, contrato vigente)

```powershell
# A partir da raiz do repo, com .env configurado
data-downloader download `
  --symbol WDO `
  --contract current `
  --start 2026-04-30 `
  --end 2026-04-30 `
  --output ./data/smoke_quick `
  --log-format json `
  --log-file ./logs/smoke_quick_$(Get-Date -Format yyyy-MM-dd_HHmmss).jsonl
```

Duração esperada: ~30-60 segundos.

### 4.2 Full smoke (30 dias, WDOJ26 — gate Epic 1)

```powershell
data-downloader download `
  --symbol WDOJ26 `
  --start 2026-03-01 `
  --end 2026-03-31 `
  --output ./data/smoke_full `
  --log-format json `
  --log-file ./logs/smoke_full_$(Get-Date -Format yyyy-MM-dd_HHmmss).jsonl
```

Duração esperada: 5-15 minutos (depende de banda e tamanho do contrato).

### 4.3 Idempotência (re-run obrigatório)

Logo após o full smoke completar, **re-rodar o mesmo comando**:

```powershell
# Mesmo comando exato
data-downloader download --symbol WDOJ26 --start 2026-03-01 --end 2026-03-31 ...
```

Esperado: log estruturado mostra `cache_hit=true` para todas as partições; nenhum trade novo escrito; catálogo inalterado.

---

## 5. Evidência obrigatória

Para **cada execução** do smoke (quick ou full), produzir as seguintes evidências:

### 5.1 Screenshot do terminal

PNG salvo em `docs/qa/smoke_runs/_screenshots/{date}-{story_id}-{quick|full}.png` mostrando:

- Comando executado (cabeçalho).
- Status final (`Download completed: N partitions, M trades`).
- Sem stack trace / sem ERRO.

### 5.2 Hashes SHA256 dos Parquets gerados

Comando para coletar (PowerShell):

```powershell
Get-ChildItem -Recurse ./data/smoke_full/*.parquet | `
  ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.FullName }
```

Salvar saída em `docs/qa/smoke_runs/_hashes/{date}-{story_id}.sha256.txt`.

### 5.3 Log estruturado completo

O `--log-file ./logs/smoke_*.jsonl` produzido pelo run (uma linha JSON por evento). Não comitar logs no repo (estão no `.gitignore`); copiar para o documento de evidência apenas as linhas-chave (start, cada chunk completo, final, stats agregadas).

### 5.4 Documento de evidência

Salvar em `docs/qa/smoke_runs/{YYYY-MM-DD}-{story_id}.md` com o template abaixo.

---

## 6. Template de evidência (`docs/qa/smoke_runs/{date}-{story_id}.md`)

```markdown
# Smoke Run — `{{ story_id }}` — `{{ YYYY-MM-DD }}`

## Ambiente (sanitizado)

| Campo               | Valor                                          |
|---------------------|------------------------------------------------|
| **modo**            | quick / full                                   |
| **data_execucao**   | `{{ YYYY-MM-DD HH:MM:SS-03:00 }}`              |
| **maquina_classe**  | `Windows 10/11 Pro` (NÃO incluir hostname)     |
| **cpu**             | `{{ vendor + model_class }}` (ex: AMD Ryzen 9 7950X3D) |
| **ram_gb**          | `{{ N }}`                                      |
| **python_version**  | `{{ 3.11.x }}`                                 |
| **dll_version**     | `{{ via GetDLLVersion }}`                      |
| **data_downloader_version** | `{{ pip show data-downloader | grep Version }}` |
| **commit_sha_codigo**| `{{ git rev-parse HEAD }}`                    |

> **Não incluir:** hostname, IP, username, conteúdo de `.env`, credenciais, paths absolutos com nome de usuário.

## Comando executado

```
{{ comando_completo_sanitizado }}
```

## Output relevante (recortes do log estruturado)

```jsonl
{{ linha de start }}
{{ linha de chunk completo (1+ exemplos) }}
{{ linha de final com stats }}
```

## Hashes SHA256 dos Parquets

(arquivo completo em `_hashes/{date}-{story_id}.sha256.txt`)

```
{{ sha256 }}  data/smoke_full/symbol=WDOJ26/year=2026/month=03/day=03/part-0001.parquet
{{ sha256 }}  data/smoke_full/symbol=WDOJ26/year=2026/month=03/day=04/part-0001.parquet
... (até 5 exemplos no documento; lista completa no .txt)
```

## Catálogo SQLite snapshot

```sql
SELECT COUNT(*) AS partitions FROM partitions WHERE symbol = 'WDOJ26';
-- esperado: M (ver critérios PASS abaixo)

SELECT SUM(row_count) AS total_trades FROM partitions WHERE symbol = 'WDOJ26';
-- esperado: N (ver critérios PASS abaixo)

SELECT DISTINCT schema_version FROM partitions WHERE symbol = 'WDOJ26';
-- esperado: ['v1.0.0'] (ou versão atual)
```

## Verificação DuckDB (re-read)

```sql
SELECT COUNT(*) FROM read_parquet('data/smoke_full/**/*.parquet');
-- esperado: bate com SUM(row_count) acima

SELECT MIN(timestamp_ns), MAX(timestamp_ns) FROM read_parquet('data/smoke_full/**/*.parquet');
-- esperado: range coerente com 2026-03-01..2026-03-31
```

## Idempotência (re-run)

```
{{ output do segundo run mostrando cache_hit=true em todas as partições }}
```

## Critérios PASS aplicados (ver §7)

- [ ] PASS-1: M partições criadas (M esperado: ver §7 abaixo)
- [ ] PASS-2: N rows totais > limite inferior; N < limite superior
- [ ] PASS-3: catálogo tem M entries com `schema_version` válido
- [ ] PASS-4: re-run = no-op (cache_hit=true em todos os logs do segundo run)
- [ ] PASS-5: DuckDB lê 100% dos arquivos sem exception
- [ ] PASS-6: invariantes de integridade (data_validate) verdes

## Verdict

| Verdict | Marcar |
|---------|--------|
| ✅ PASS  | [ ]    |
| ❌ FAIL  | [ ]    |

**Rationale:** `{{ texto curto }}`

## Assinatura

| Campo            | Valor                              |
|------------------|------------------------------------|
| **executor**     | usuário (humano)                   |
| **validador**    | Quinn 🧪 (lê esta evidência)       |
| **commit_sha_evidencia** | `{{ commit do .md }}`        |
```

---

## 7. Critérios objetivos PASS

> **Objetivos** = mensuráveis. **Sem subjetividade**. Quinn lê a evidência e checa
> cada item contra o esperado.

### 7.1 Quick smoke (1 dia, WDO contrato vigente)

| ID      | Critério                                                                  |
|---------|---------------------------------------------------------------------------|
| PASS-1  | >= 1 arquivo Parquet criado em `data/smoke_quick/symbol=WDO*/year=.../day=...` |
| PASS-2  | Total de trades em `[1.000 ; 5.000.000]` (ordem de magnitude WDO 1 dia)   |
| PASS-3  | Catálogo SQLite tem >= 1 entry com `schema_version` em `['v1.0.0']` (ou versão vigente) |
| PASS-4  | Re-run produz log com `cache_hit=true` em **todas** as partições; 0 trades novos escritos |
| PASS-5  | `SELECT COUNT(*) FROM read_parquet(...)` retorna sem exception            |
| PASS-6  | `Quinn *data-validate --symbol WDOJ26 --date-range ...` retorna 0 violations |

### 7.2 Full smoke (30 dias, WDOJ26 — gate Epic 1)

| ID      | Critério                                                                  |
|---------|---------------------------------------------------------------------------|
| PASS-1  | >= 18 arquivos Parquet criados (~21 dias úteis em mar/2026 menos feriados; mínimo 18 para tolerância) |
| PASS-2  | Total de trades em `[100.000 ; 50.000.000]`                               |
| PASS-3  | Catálogo SQLite tem >= 18 entries com `schema_version` válido em todas    |
| PASS-4  | Re-run completo = no-op observável (todas partições `cache_hit=true`)     |
| PASS-5  | DuckDB lê 100% dos arquivos sem exception; `MIN(timestamp_ns)` em 2026-03-01..03 e `MAX` em 2026-03-29..31 |
| PASS-6  | `*data-validate --all` retorna 0 violations em todas as 8 regras (ver `agents/qa.md` data_integrity_full) |

---

## 8. Critérios objetivos FAIL

> Qualquer **um** destes basta para FAIL.

| ID     | Critério (qualquer ocorrência => FAIL)                                    |
|--------|---------------------------------------------------------------------------|
| FAIL-1 | Stack trace não tratado em qualquer ponto da execução                     |
| FAIL-2 | Catálogo SQLite dessincronizado dos arquivos físicos (entry sem arquivo OU arquivo sem entry) |
| FAIL-3 | Re-run escreve >= 1 trade novo (idempotência quebrada — viola INV-3)      |
| FAIL-4 | DuckDB falha ao ler qualquer arquivo gerado                                |
| FAIL-5 | Total de trades fora do range esperado (ordem de magnitude muito divergente — investigar) |
| FAIL-6 | Qualquer regra de `data_validate` falha (dup, gap inesperado, schema ausente, price/qty <= 0, exchange code inválido) |
| FAIL-7 | `dll_version` ausente no metadata Parquet (campo obrigatório por H19)     |
| FAIL-8 | Smoke ficou >= 30 minutos sem progresso visível (provável deadlock)       |

---

## 9. Workflow PASS

1. Usuário roda smoke conforme §4.
2. Usuário coleta evidências conforme §5.
3. Usuário cria `docs/qa/smoke_runs/{date}-{story_id}.md` conforme §6 e comita.
4. Usuário comenta no PR da story:
   > ✅ Smoke `{{ quick|full }}` PASS — evidência: `docs/qa/smoke_runs/{date}-{story_id}.md` (commit `{sha}`)
5. Usuário marca AC10 da Story 1.7b (`smoke real validado`) na story file.
6. Quinn revisa a evidência e os 6 critérios PASS.
7. Se Quinn confirma: `*qa-gate` pode emitir verdict PASS na story.

---

## 10. Workflow FAIL

1. Usuário roda smoke; observa FAIL.
2. Usuário cria evidência mesmo assim em `docs/qa/smoke_runs/{date}-{story_id}.md` marcando ❌ FAIL e detalhando qual critério falhou.
3. Usuário comenta no PR:
   > ❌ Smoke `{{ quick|full }}` FAIL — critério `FAIL-N` violado. Evidência: `{path}`
4. Quinn lê a evidência e gera `docs/qa/QA_FIX_REQUESTS/{story_id}.md` com:
   - Finding CRITICAL referenciando o critério `FAIL-N`.
   - Snippet do log estruturado como evidência.
   - Causa raiz suspeita (Quinn pode consultar Nelo/Sol).
   - Sugestão de fix.
   - Regression test sugerido (ex: novo unit test que reproduza a falha em mock).
5. Quinn devolve a story para Dex via `*apply-qa-fixes`.
6. Após fix, Dex pede ao usuário re-rodar o smoke. Loop até PASS ou WAIVED documentado.

---

## 11. Sanitização de evidência (privacidade)

**Antes de comitar** qualquer evidência em `docs/qa/smoke_runs/`, remover:

- Hostname (`COMPUTERNAME`, `HOSTNAME`).
- Username em paths absolutos (substituir `C:\Users\Pichau\` por `C:\Users\<user>\` ou usar paths relativos).
- IP local / MAC / serial.
- Conteúdo de `.env` ou qualquer credencial Nelogica.
- Tokens, chaves, senhas em qualquer forma.

Se houver dúvida, perguntar a Gage (devops) antes de comitar.

---

— Quinn, no portão 🧪 (autoria do protocolo; smoke executado pelo humano, validado por Quinn)
