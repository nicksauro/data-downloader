# CodeRabbit Integration — QA Advisory

> Operacionalização da decisão de Gage em `docs/release/CODERABBIT_DECISION.md`
> (resolução do **finding M3** do PLAN_REVIEW 2026-05-03).
>
> Este documento define **como** Quinn consome a saída do CodeRabbit dentro do
> `*qa-gate`, **qual** o severity mapping para o `QA_REPORT.md`, e **qual** a
> política de bloqueio vs dívida.

---

## 1. Status & escopo

| Aspecto              | Decisão                                                                |
|----------------------|------------------------------------------------------------------------|
| **Status**           | **ADOPTED — Opção B (advisory; CRITICAL bloqueia QA gate)**             |
| **Decisão formal**   | `docs/release/CODERABBIT_DECISION.md` §0 (Story 0.4, ADOPTED 2026-05-03) |
| **Trigger único**    | **Quinn invoca manualmente em PR > 500 LOC** (NÃO pre-commit, NÃO `*develop`) |
| **Self-healing automático** | **DESLIGADO** — squad usa especialistas (Nelo/Sol/Aria/Quinn) |
| **Quem audita output**| Quinn — incorpora ao QA_REPORT seção 6                                |
| **Ambiente**         | WSL (Windows Subsystem for Linux) — ferramenta CLI Linux               |
| **Instalação CodeRabbit CLI no WSL** | **Responsabilidade do usuário** (ver Apêndice A) — não bloqueia Story 0.4 |

> Adoção formalizada em `docs/release/CODERABBIT_DECISION.md` §0 + §8 (Gage + Quinn aprovaram em 2026-05-03). Re-avaliação obrigatória após Story 1.7b.

---

## 2. Comando WSL

### 2.1 Manual sobre uncommitted changes (uso ad-hoc por Quinn — NÃO automático)

> **Não é hook de pre-commit.** Trigger automático foi DESLIGADO em §0/CODERABBIT_DECISION §0.
> Comando preservado abaixo apenas para invocação manual de Quinn quando útil.

```bash
wsl bash -c 'cd /mnt/c/Users/Pichau/Desktop/data-downloader \
  && ~/.local/bin/coderabbit --prompt-only -t uncommitted'
```

### 2.2 Pre-PR vs base branch (uso manual por Quinn em PR > 500 LOC)

```bash
wsl bash -c 'cd /mnt/c/Users/Pichau/Desktop/data-downloader \
  && ~/.local/bin/coderabbit --prompt-only --base main'
```

### 2.3 Em `*qa-gate {story-id}` (Quinn)

Quinn roda em cima do branch da story:

```bash
wsl bash -c 'cd /mnt/c/Users/Pichau/Desktop/data-downloader \
  && git checkout {{ story_branch }} \
  && ~/.local/bin/coderabbit --prompt-only --base main \
     > /mnt/c/Users/Pichau/Desktop/data-downloader/docs/qa/.coderabbit_runs/{{ story_id }}-{{ date }}.txt'
```

Output salvo em `docs/qa/.coderabbit_runs/` (gitignored — só artefato local).

---

## 3. Parsing do output

CodeRabbit retorna findings em texto livre estruturado. Quinn faz extração manual
(ou semi-automática via `*qa-gate`) capturando para cada finding:

| Campo            | Exemplo                                          |
|------------------|--------------------------------------------------|
| `file:line`      | `src/data_downloader/storage/writer.py:142`      |
| `category`       | `bug | performance | maintainability | security | style` |
| `description`    | "Possible race condition between writer and catalog update" |
| `suggested_fix`  | "Wrap write_partition + catalog.register in single transaction" |

---

## 4. Severity mapping para QA_REPORT

CodeRabbit usa categorias amplas. Quinn aplica o seguinte mapping para encaixar
na matriz de severity do `QA_REPORT.md`:

| CodeRabbit category                              | Severity QA      |
|--------------------------------------------------|------------------|
| `bug` (lógica errada, race, null deref)          | **CRITICAL**     |
| `security` (vazamento, injeção, credencial)      | **CRITICAL**     |
| `correctness` envolvendo invariantes (INV-1..12) | **CRITICAL**     |
| `performance` em hot path (callbacks, write loop)| **HIGH**         |
| `bug` em path não-hot                            | **HIGH**         |
| `maintainability` (complexidade, duplicação significativa) | **MEDIUM** |
| `performance` fora de hot path                   | **MEDIUM**       |
| `style`, `naming`, `comment`                     | **LOW**          |
| `nitpick`                                        | **LOW**          |

> **Quinn override:** se Quinn julgar que a categoria está mal mapeada (ex:
> CodeRabbit marcou como `style` mas é violação de invariante), Quinn reclassifica
> e documenta a decisão na seção 6 do `QA_REPORT.md`.

---

## 5. Política

### 5.1 CRITICAL findings

- **Bloqueia PASS** no `*qa-gate`.
- Vão para `QA_FIX_REQUEST.md` na seção CRITICAL.
- Dex DEVE corrigir antes de re-submeter para Quinn.
- Não podem virar dívida sem WAIVER assinado (raríssimo — Aria/Sol/Morgan).

### 5.2 HIGH findings

- **NÃO bloqueia PASS** automaticamente, mas:
  - >= 3 HIGH em uma story → verdict CONCERNS (não PASS).
  - Cada HIGH vira **dívida documentada** com story-debt criada (Morgan aloca em sprint subsequente).
- Quinn lista no `QA_REPORT.md` seção 6.

### 5.3 MEDIUM findings

- Não bloqueia.
- Vira dívida em `docs/qa/COVERAGE_DEBT.md` (catálogo cumulativo de débitos técnicos).
- Morgan revisa mensalmente para promoção a story.

### 5.4 LOW findings

- Informativo.
- Quinn lista contagem agregada no QA_REPORT (sem detalhar cada um).
- Dex pode aplicar oportunisticamente, sem rigor.

---

## 6. Workflow no `*qa-gate`

1. Quinn executa CodeRabbit conforme §2.3.
2. Quinn parseia output conforme §3.
3. Quinn aplica severity mapping conforme §4.
4. Quinn preenche seção 6 do `QA_REPORT.md`:
   ```markdown
   | Severity | Count | Política |
   |----------|-------|----------|
   | CRITICAL | 0     | — (PASS permitido) |
   | HIGH     | 2     | Vira dívida (story-debt criada) |
   | MEDIUM   | 5     | Catálogo COVERAGE_DEBT atualizado |
   | LOW      | 12    | Informativo |
   ```
5. Se `CRITICAL > 0`: Quinn move o finding para `QA_FIX_REQUEST.md` e seta verdict FAIL.
6. Se `HIGH >= 3`: Quinn rebaixa verdict para CONCERNS (não PASS).
7. Quinn arquiva texto bruto em `docs/qa/.coderabbit_runs/` (gitignored — referência local).

---

## 7. Falsos positivos

CodeRabbit pode flag-ar idiomas ou padrões intencionais (ex: `# noqa` em hot path
para pular logging por design — R21). Quinn faz triagem:

| Cenário                                          | Ação                                  |
|--------------------------------------------------|---------------------------------------|
| Padrão intencional documentado (ADR/MANIFEST)    | Marcar "false positive" no QA_REPORT, citar referência |
| Limitação conhecida do CodeRabbit                | Documentar em `docs/qa/CODE_RABBIT_INTEGRATION.md` §9 (lista vivente) |
| Disputa entre Quinn e CodeRabbit sobre severidade| Quinn é autoridade final; documenta decisão em QA_REPORT |

---

## 8. Quando NÃO rodar CodeRabbit

- Story 0.x (foundation) — diff irrelevante para review automatizado.
- Hotfix urgente em produção — Quinn pode pular CodeRabbit no `*qa-gate` mas DEVE rodar pos-merge e abrir issues retroativas.
- Refatoração mecânica massiva (ex: rename global) — output será ruidoso; rodar manualmente após e triar.

Em todos os casos de skip, Quinn anota `CodeRabbit: skipped — rationale: {{ X }}` na seção 6 do QA_REPORT.

---

## 9. Falsos positivos conhecidos (lista vivente)

> Atualizar conforme observados. Cada entrada com referência à decisão.

| Padrão flag-ado | Por quê é intencional | Referência |
|-----------------|------------------------|------------|
| `# type: ignore` em ctypes WINFUNCTYPE | Tipos `WINFUNCTYPE` são incompatíveis com mypy strict | `agents/profitdll-specialist.md` |
| `pass` silencioso em callback de logging shutdown | Evita re-raise dentro de logger durante drain | ADR-005 amendment |
| Loop sem early-exit em chunk validator | Validar todos os chunks (não fail-fast) | `docs/qa/INVARIANTS_TESTS.md` INV-8 |

---

## 10. Pendências

- ~~**Story 0.4** (Gage): decisão final de adoção.~~ **RESOLVED 2026-05-03** — ADOPTED Opção B (advisory).
- Mapping para severity ainda é manual; futuro: script `tools/coderabbit_to_qa_report.py` (issue tracker).
- Considerar custo de runs em PRs grandes (timeout WSL — Gage avalia).
- **Instalação CodeRabbit CLI no WSL** — pendente (responsabilidade do usuário; ver Apêndice A). Não bloqueia Story 0.4.
- **Re-avaliação obrigatória após Story 1.7b** (gate Epic 1) — Quinn + Gage avaliam se valor entregue justifica overhead.

---

## Apêndice A — Probe de disponibilidade do CodeRabbit no WSL (2026-05-03)

**Executado por:** Gage durante fechamento da Story 0.4.

| Check | Resultado | Detalhe |
|-------|-----------|---------|
| WSL disponível | **YES** | Distros: `Ubuntu (Padrão)`, `docker-desktop` |
| Comando: `wsl bash -c 'which coderabbit \|\| ls -la ~/.local/bin/coderabbit 2>/dev/null \|\| echo NOT_INSTALLED'` | **NOT_INSTALLED** | CodeRabbit CLI não está instalado em `$PATH` nem em `~/.local/bin/coderabbit` |

### Implicação

CodeRabbit não é executável neste host **agora**. Como adoção é **advisory + on-demand** (Opção B), isso **NÃO bloqueia** o fechamento da Story 0.4 nem qualquer story subsequente até a primeira ocasião em que Quinn precise invocar (PR > 500 LOC).

### Instalação (responsabilidade do usuário, quando necessário)

Documentação oficial: https://docs.coderabbit.ai/cli (verificar URL atual). Comando típico (sujeito a mudança):

```bash
wsl bash -c 'curl -fsSL https://cli.coderabbit.ai/install.sh | sh'
```

Após instalar, validar:

```bash
wsl bash -c '~/.local/bin/coderabbit --version'
```

### Quando instalar

- Quando Quinn identificar primeiro PR > 500 LOC fora do escopo de especialista (Nelo/Sol/Aria) e quiser segunda opinião.
- Antes da Story 1.7b (gate Epic 1) é recomendado para que Quinn possa invocar se decidir.
- Custo: ~5-10 min de install + autenticação CodeRabbit (chave API ou OAuth, conforme produto).

> **Decisão:** Sem instalação automatizada via squad. Gage não prescreve infra que não vai usar imediatamente. Usuário instala quando Quinn pedir.

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-05-03 | Quinn (Fase A) | Documento criado — operacionalização da decisão de Gage (status pendente) |
| 2026-05-03 | Gage + Quinn (Fase B) | Status atualizado para **ADOPTED**. §1 harmonizada (trigger único = Quinn manual em PR > 500 LOC; pre-commit removido como auto-trigger). §2.1/§2.2 reclassificadas como invocação manual (não hook). §10 pendência Story 0.4 marcada como RESOLVED. **Apêndice A adicionado** (probe WSL: CodeRabbit NOT_INSTALLED — instalação delegada ao usuário, não bloqueante). |

---

— Quinn, no portão 🧪 (consumidora); Gage ⚙️ (owner de adoção e infra)
