# CLI_PATTERNS — Padrões de UI da CLI Rich

> Padrões obrigatórios da CLI (`data-downloader`). Toda UI textual passa por
> Uma antes de implementação. Story 1.7 implementa estes padrões.

**Versão:** 1.0.0
**Data:** 2026-05-03
**Status:** ratificado (Story 0.3, finding H13)
**Stack:** Typer (parsing) + Rich (rendering) + sys.stdin (stdin)
**Autoridade:** 🎨 Uma — exclusiva sobre microcopy e layout textual.

---

## 1. Princípios da CLI

1. **CLI é UI** — não é "saída de texto", é interface. Sujeita aos princípios de PRINCIPLES.md.
2. **Honestidade visual** — barra de progresso reflete trabalho real, nunca "estética".
3. **Cor é semântica, não decoração** — verde=ok, vermelho=erro, amarelo=warning, ciano=info/link.
4. **Fallback gracioso** — `NO_COLOR` ou terminal sem UTF-8 → degrada para ASCII puro.
5. **Output curto por padrão** — `--verbose` desbloqueia detalhe; modo padrão é minimalista.
6. **Comandos são verbos** — `download`, `list`, `validate`, `repeat`. Substantivos viram subgrupos.
7. **Help formatado** — todo `--help` tem sumário, exemplos e link para docs.

---

## 2. Layout de Progresso (Rich Progress)

### Componentes obrigatórios

```
┌──────────────────────────────────────────────────────────────────┐
│ [⬇] Baixando WDOJ26 (mar/2026) — 4 de 12 chunks                  │ ← título
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │ ← barra principal
│  33% • 4/12 • 02:14 elapsed • ~04:30 restante                     │ ← stats
│                                                                    │
│ ▸ Detalhes (clique para expandir, ou --verbose)                   │ ← log expansível
└──────────────────────────────────────────────────────────────────┘
[Ctrl+C] cancelar
```

### Especificação de campos

| Campo | Conteúdo | Cor | Atualização |
|-------|----------|-----|-------------|
| Título | `[ícone] Verbo + Símbolo (Período) — N de M chunks` | branco | a cada chunk |
| Barra | Progresso visual contínuo | ciano sobre cinza | a cada `progress_event` |
| Stats | `XX% • N/M • elapsed • ETA` | cinza claro | a cada 500ms |
| Subtitle | Estado contextual (ver §3) | varia | quando estado muda |
| Log expansível | Eventos por chunk com timestamp | cinza | streaming |

### Implementação Rich (referência para Felix/Dex)

```
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn, SpinnerColumn

progress = Progress(
    TextColumn("[bold cyan]{task.description}"),
    BarColumn(complete_style="cyan", finished_style="green"),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TextColumn("• {task.completed}/{task.total}"),
    TimeElapsedColumn(),
    TextColumn("•"),
    TimeRemainingColumn(),
    console=console,
    transient=False,  # mantém após conclusão
)
```

---

## 3. Padrão Especial: Quirk 99% Reconnect

**Contexto:** quando download chega em ~99%, a corretora frequentemente fica
reconectando por 1-30 minutos. Isso é validado por Nelo como **comportamento
normal**, não erro.

### Comportamento da UI

1. Barra **mantém posição em 99%** (não regride, não vai pra 100%).
2. Subtitle muda para texto explícito amarelo:

```
⚠ A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele.
```

3. Cor da barra muda de ciano para amarelo (warning, não erro).
4. Spinner ativo ao lado para indicar atividade.
5. Após reconectar, subtitle desaparece, cor volta para ciano, barra completa
   e vai pra success state.

### Microcopy exato (do MICROCOPY_CATALOG.md, ID `99_reconnect`)

> "A corretora está reconectando — é normal, aguarde até 30 minutos. Não cancele."

Variação curta (terminal estreito, < 80 cols):

> "Reconectando... (normal, aguarde)"

### O que NÃO fazer

- Mostrar barra travada em 99% sem explicação.
- Mostrar erro vermelho.
- Resetar para 0% e recomeçar.
- Mostrar "Recuperando conexão... [40s]" sem dizer que pode demorar 30min.

---

## 4. Padrão de Erro

### Estrutura

```
✗ [TÍTULO HUMANO em vermelho bold]
  [O QUE ACONTECEU em 1 frase, branco]
  [O QUE FAZER em 1 frase imperativa, branco]
  [opcional: dica em itálico cinza]
  [opcional: --verbose mostra stack trace]
```

### Exemplo

```
✗ Não conectei à ProfitDLL
  A chave de licença pode estar inválida ou expirada.
  Verifique a chave em ~/.data-downloader/.env e tente de novo.
  (Use --verbose para ver detalhes técnicos)
```

### Cores

- Ícone `✗` (ou `[X]` em ASCII): **red bold**
- Título: **red bold**
- Corpo: **white** (não red — vermelho é só para sinalizar gravidade)
- Dicas: **dim italic**

### Exit code

Erro sempre sai com código != 0. Códigos canônicos:

| Código | Categoria |
|--------|-----------|
| 0 | Sucesso |
| 1 | Erro genérico (catch-all) |
| 2 | Erro de input do usuário (símbolo inválido, período inválido) |
| 3 | Erro de DLL (não conectou, sessão caiu) |
| 4 | Erro de storage (disco cheio, permissão) |
| 130 | Cancelado (Ctrl+C) — convenção POSIX (128 + SIGINT=2) |

---

## 5. Padrão de Sucesso

### Estrutura

```
✓ [VERBO_NO_PASSADO + RESUMO em verde]
  [SUMMARY linha única branco]
  [LINK / ATALHO em ciano sublinhado]
```

### Exemplo

```
✓ Download concluído: WDOJ26
  1.234.567 trades em 3 arquivos (45 MB) — 4min 12s
  → Ver no catálogo: data-downloader list --symbol WDOJ26
```

### Cores

- Ícone `✓`: **green bold**
- Verbo + resumo: **green bold**
- Summary: **white**
- Link / próximo passo: **cyan underline** (representa "comando que você pode rodar")

### Sem alarme

Sucesso é silencioso e celebrado. Não pisca, não toca som, não bloqueia. Só
informa e termina o programa (exit 0).

---

## 6. Padrão de Empty State (Catálogo Vazio)

### Comando: `data-downloader list` sem dados

```
[catálogo vazio] Nenhum histórico baixado ainda.

   Comece com:
     data-downloader download --symbol WDOJ26 --period current-month

   Ou veja contratos vigentes:
     data-downloader contracts list

📖 Documentação: docs/ux/FLOWS.md
```

### Variação: filtro sem resultado

```
[sem resultados] Nenhum histórico encontrado para WIN com filtro 2024.

   Sugestões:
     • Listar todos: data-downloader list
     • Tentar outro símbolo: data-downloader list --symbol WDO
```

### Cores

- "[catálogo vazio]" / "[sem resultados]": **dim**
- Mensagem principal: **white**
- Comando sugerido: **cyan** (executável, copiável)
- Sufixo `📖`: **dim**

---

## 7. Padrão de Cancelamento (Ctrl+C)

### Fluxo

1. Usuário pressiona Ctrl+C durante download.
2. SIGINT capturado pelo handler graceful (NÃO termina abrupto).
3. Confirmação inline:

```
^C
⚠ Cancelar download em progresso?
  Trades já baixados serão preservados (cache hit em re-tentativa).
  [s/N]:
```

4. Se `n` (default): retoma. Se `s`:

```
↻ Cancelando... (drenando fila + commitando parcial)
✓ Download cancelado.
  Parcial salvo: 234.567 trades (chunks 1-4 de 12).
  Retomar com: data-downloader download --symbol WDOJ26 --resume
```

5. Exit code 130.

### Pressionar Ctrl+C 2x rapidamente

Force quit (KeyboardInterrupt sem cleanup). Mensagem:

```
✗ Forçando saída — dados em buffer podem ser perdidos.
```

Exit code 130. Atomic write ainda protege Parquet já comitado.

### Cores

- `^C` literal: **dim** (apenas eco)
- Pergunta amarela: **yellow**
- Spinner cancelando: **yellow**
- Resumo final: **green** (sucesso do cancelamento)

---

## 8. Padrão de Comando Help (`--help`)

### Estrutura

```
data-downloader download — Baixar histórico de um símbolo.

USO
  data-downloader download --symbol SÍMBOLO [opções]

DESCRIÇÃO
  Baixa histórico de trades para o símbolo e período especificados.
  Defaults inteligentes: símbolo = última usada; período = mês corrente
  do contrato vigente.

EXEMPLOS
  # Caso comum (defaults inteligentes):
  $ data-downloader download

  # Símbolo específico, mês corrente:
  $ data-downloader download --symbol WDOJ26

  # Período customizado:
  $ data-downloader download --symbol WDOJ26 --start 2026-01-01 --end 2026-01-31

  # Sem cor (CI ou pipe):
  $ NO_COLOR=1 data-downloader download

OPÇÕES
  --symbol TEXT          Símbolo do contrato. [default: última usada]
  --start DATE           Data inicial (YYYY-MM-DD). [default: mês corrente]
  --end DATE             Data final (YYYY-MM-DD). [default: hoje]
  --output-dir PATH      Pasta de destino. [default: ~/data-downloader/data/]
  --resume               Continuar download interrompido.
  --verbose              Mostrar detalhes técnicos.
  --ascii-only           Forçar saída ASCII (sem Unicode).
  --no-color             Desativar cores (mesmo sem NO_COLOR env).
  --help                 Mostrar esta ajuda.

VARIÁVEIS DE AMBIENTE
  NO_COLOR               Desativa cores (qualquer valor).
  PROFITDLL_KEY          Chave de licença ProfitDLL.

ERROS COMUNS
  ✗ Não conectei à ProfitDLL
    → Verifique PROFITDLL_KEY em ~/.data-downloader/.env

  ✗ {SÍMBOLO} não é contrato vigente
    → Liste vigentes: data-downloader contracts list

📖 Documentação completa: docs/ux/FLOWS.md
🐛 Reportar bug: https://github.com/.../issues
```

### Convenções

- **Sumário curto** no topo (1 linha após o nome).
- **Exemplos antes de opções** (usuário comum quer ver exemplo rápido).
- **Erros comuns no fim** (cobre 80% dos primeiros tropeços).
- Link para docs completa sempre no rodapé.

---

## 9. Política `NO_COLOR` e Fallback ASCII

### NO_COLOR

```
if os.environ.get('NO_COLOR') is not None:
    console = Console(no_color=True, force_terminal=False)
else:
    console = Console()
```

Quando ativado:
- Sem cores (todo texto branco/default do terminal).
- Símbolos Unicode mantidos (é só cor que sai, não estrutura).
- Barra de progresso usa caracteres `=` ou `-` em vez de blocos `█`.

### Detecção de terminal sem Unicode

Detectar via `sys.stdout.encoding` ou tentar escrever um caractere de teste.
Se falhar (cmd.exe legado), aplicar fallback ASCII automaticamente:

| Unicode | ASCII fallback |
|---------|----------------|
| ✓ | [OK] |
| ✗ | [X] |
| ⚠ | [!] |
| ↻ | [~] |
| ⬇ | [v] |
| ▸ | > |
| → | -> |
| 📖 | (omitido) |
| █ | # |

Flag manual `--ascii-only` força este modo independente da detecção.

### Encoding

CLI sempre tenta ler/escrever em **UTF-8**. Em Windows com `cmd.exe` legado,
chamar `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` no startup.
Se reconfigure falhar, log warning silencioso e segue com ASCII fallback.

---

## 10. Defaults Inteligentes

### `--symbol` default

1. Se cache local `~/.data-downloader/last_symbol` existe → usa.
2. Senão, sugere contrato vigente do **WDO** (mais comum nos testes do squad).
3. Em modo interativo (TTY), prompt com sugestão pré-preenchida:

```
Símbolo [WDOJ26]:
```

(usuário aperta Enter → aceita; ou digita outro).

4. Em modo não-interativo (pipe, CI), erro claro:

```
✗ Símbolo não especificado.
  Forneça --symbol ou rode em terminal interativo.
```

### `--start` / `--end` default

- `--start` ausente → primeiro dia útil do mês corrente do contrato vigente.
- `--end` ausente → hoje (último dia útil disponível).
- Ambos ausentes → mês corrente completo (definição operacional: dia 1 do mês
  até hoje).

Validação: se `--start` é dia não-útil, ajusta para próximo dia útil + warning
inline ("Ajustado para 2026-03-02 — 01/03 é sábado").

### `--output-dir` default

- `~/data-downloader/data/` (criada automaticamente, sem perguntar).
- Em Windows: `%USERPROFILE%\data-downloader\data\`.
- Persistido no `~/.data-downloader/config.toml` para próximas execuções.

### `--chunk-size` default

- 30 dias (escondido — só aparece em `--verbose --help` ou drawer "Avançado" na UI Qt).
- Validado por Pyro; baseline em `docs/perf/BASELINES.md`.

---

## 11. Padrão de Warning (não-bloqueante)

```
⚠ [TÍTULO em amarelo]
  [contexto em branco]
```

Exemplo:

```
⚠ Período > 30 dias detectado
  Será dividido em 4 chunks (~12 minutos estimados).
  Continuar? [S/n]:
```

Diferente de erro: warning **pergunta**, erro **informa+sai**.

---

## 12. Padrão Informativo (Status)

Para eventos durante operação longa que não precisam de barra mas o usuário
deveria saber:

```
[15:23:01] Inicializando ProfitDLL...
[15:23:03] Conectado ao Roteador.
[15:23:04] Login OK (token válido até 16:23).
[15:23:05] Buscando contratos vigentes para WDO...
[15:23:06] Contrato selecionado: WDOJ26 (vigente até 28/03/2026).
[15:23:07] Iniciando download de mar/2026...
```

Cor: **dim** (cinza claro), timestamp **dim italic**. Esse log é suprimido por
default; aparece com `--verbose` ou no log expansível da barra de progresso.

---

## 13. Comandos da CLI (sumário canônico)

| Comando | Descrição | Atalho |
|---------|-----------|--------|
| `data-downloader download` | Baixar histórico | `dd dl` (alias) |
| `data-downloader list` | Listar histórico baixado (catálogo) | `dd ls` |
| `data-downloader contracts list` | Listar contratos vigentes | `dd cl` |
| `data-downloader validate` | Validar integridade de contrato baixado | `dd val` |
| `data-downloader repeat` | Repetir último download | `dd rp` |
| `data-downloader version` | Mostrar versão + dll_version | `dd v` |
| `data-downloader doctor` | Diagnóstico (DLL conectada? disco?) | `dd dr` |

---

## 14. Anti-Patterns Proibidos

1. **Spinner sem progresso** — usuário não sabe se travou.
2. **Mensagem `Loading...` por > 3s sem update** — adicionar progresso ou status.
3. **Erro com stack trace por padrão** — esconder atrás de `--verbose`.
4. **Cores fora da paleta** (THEME.md) — manter consistência semântica.
5. **`print()` direto** — sempre passar por `console.print()` (Rich) para
   respeitar `NO_COLOR` e detect de terminal.
6. **Verbo em inglês quando há equivalente comum em pt-BR** — "Baixar" não
   "Download" no texto visível ao usuário (o **comando CLI** continua em inglês:
   `data-downloader download`).
7. **Modal "OK" para sucesso** — sucesso é silencioso (toast verde, exit 0).
8. **Bloqueio de UI por > 16ms** — toda operação longa em thread (R11).

---

## 15. Referências

- Rich docs — https://rich.readthedocs.io/
- Typer docs — https://typer.tiangolo.com/
- NO_COLOR — https://no-color.org/
- POSIX exit codes — https://tldp.org/LDP/abs/html/exitcodes.html
- PRINCIPLES.md (princípios gerais)
- MICROCOPY_CATALOG.md (textos exatos)
- THEME.md (paleta + tipografia + atalhos)

---

— Uma, desenhando empatia 🎨
