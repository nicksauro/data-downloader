# WIREFRAMES — Telas Qt Epic 3-Ready

> Wireframes detalhados para Epic 3. Notação ASCII portátil — Felix traduz para
> PySide6. Cada tela tem 5 estados ASCII anotados (normal, loading, error,
> empty, success), atalhos referenciados a `THEME.md §6` e microcopy IDs
> referenciados a `MICROCOPY_CATALOG.md`.

**Versão:** 0.2.0 (Epic 3 prep — COUNCIL-12)
**Data:** 2026-05-03
**Status:** ready (Story 0.3 + COUNCIL-12 expansion)
**Autoridade:** Uma — exclusiva sobre wireframes
**Implementação:** Felix (Epic 3 stories 3.1-3.5)

---

## Convenções de Notação

```
┌─┐ │ └─┘   = bordas de container
[BOTÃO]      = botão clicável (verbo do MICROCOPY_CATALOG)
{Símbolo}    = input editável (label = MICROCOPY)
▾            = dropdown
░░░░░░░      = barra (skeleton ou espaço vazio)
█████░░░ XX% = progress bar (cheia/vazia + %)
✓ ✗ ⚠ ↻      = ícones semânticos (THEME §7)
(text)       = label dim/hint
*texto*      = texto em ênfase
[v]          = ícone download
[CTRL+X]     = atalho de teclado (referência THEME.md §6)
```

Tamanho de referência: janela mínima **960×640** (Qt). Wireframes mostrados
em ~80 cols ASCII.

---

## MainWindow — Frame Geral

Contêiner global. `QMainWindow` com sidebar nav esquerda + `QStackedWidget` central
+ status bar inferior. Implementação: Felix Story 3.1.

### Layout estrutural (estado: tela Download ativa)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  data-downloader                                                       — □ X │ ← title bar OS
├────────────┬─────────────────────────────────────────────────────────────────┤
│            │                                                                  │
│  [⬇]       │                                                                  │
│ Download   │                                                                  │
│ (active)   │                                                                  │
│ Ctrl+D     │                                                                  │
│            │                                                                  │
│  [📁]      │              MAIN AREA                                           │
│ Catálogo   │       (QStackedWidget central)                                   │
│ Ctrl+B     │       — DownloadScreen / CatalogScreen / SettingsScreen —        │
│            │                                                                  │
│  [⚙]       │                                                                  │
│ Settings   │                                                                  │
│ Ctrl+,     │                                                                  │
│            │                                                                  │
│            │                                                                  │
├────────────┴─────────────────────────────────────────────────────────────────┤
│  ✓ DLL: conectada (4.1.0.21)  •  ~/data-downloader/data/  •  app v0.1.0      │ ← status bar
└──────────────────────────────────────────────────────────────────────────────┘
```

### Sidebar — Estados de nav

| Item | Estado normal | Estado active | Estado download em progresso (badge) |
|------|---------------|---------------|--------------------------------------|
| Download | `[⬇] Download` | borda esquerda accent.cyan 3px + bg state.active | `[⬇] Download ↻` (spinner pequeno) |
| Catálogo | `[📁] Catálogo` | idem | — |
| Settings | `[⚙] Settings` | idem | — |

### Status Bar — Composição

| Posição | Conteúdo | Cor / Estado |
|---------|----------|--------------|
| Esquerda | DLL status: `✓ Conectada (v4.1.0.21)` ou `✗ Desconectada` ou `↻ Conectando...` | green / red / yellow |
| Centro | Pasta atual de dados (truncada se > 40 chars) | text.secondary |
| Direita | Versão app + atalho cheat sheet | `v0.1.0  •  Ctrl+/` (text.muted) |

### Atalhos globais (THEME.md §6)

- `Ctrl+D` — Foca/abre DownloadScreen.
- `Ctrl+B` — Foca/abre CatalogScreen.
- `Ctrl+,` — Foca/abre SettingsScreen.
- `Ctrl+R` — Refresh contextual da tela ativa.
- `Ctrl+Q` — Sair do app (com confirm se download em progresso).
- `Ctrl+/` — Abre modal cheat sheet com todos atalhos da tela ativa + globais.
- `F1` — Ajuda contextual (V2).
- `Esc` — Context-aware (ver THEME.md §6).
- `Tab` / `Shift+Tab` — Navegação entre campos com foco visível obrigatório.

---

## Tela 1 — DownloadScreen

Implementação: Felix Story 3.2.

### Estado: **Normal** (golden path, defaults preenchidos)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Baixar Histórico                                                            │ ← title 18px semibold
│  Selecione, configure e clique em baixar                                     │ ← subtitle dim 14px
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  Símbolo                                                                 │ │
│  │  ┌────────────────────────────────────────────────────┐  ┌───────────┐ │ │
│  │  │ WDOJ26  ▾                                          │  │ Listar    │ │ │
│  │  └────────────────────────────────────────────────────┘  │ Vigentes  │ │ │
│  │  (vigente até 28/03/2026)                                └───────────┘ │ │
│  │                                                                          │ │
│  │  Período                                                                 │ │
│  │  ┌────────────────────────────────────────────────────────────────────┐ │ │
│  │  │ Mês corrente  ▾                                                    │ │ │
│  │  └────────────────────────────────────────────────────────────────────┘ │ │
│  │  01/03/2026 → 03/05/2026 (~2 meses)                                     │ │
│  │  Estimativa: 3-7 minutos                                                 │ │
│  │                                                                          │ │
│  │  ▾ Avançado (chunk size, retry, pasta)                                  │ │ ← collapsed drawer
│  │                                                                          │ │
│  │                                                  [⬇ BAIXAR HISTÓRICO]   │ │ ← primário grande
│  │                                                          (Ctrl+D)        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Atalhos: Ctrl+D iniciar  •  Ctrl+C cancelar  •  Ctrl+/ todos                │ ← footer dim
└──────────────────────────────────────────────────────────────────────────────┘
```

**Componentes:**
- **SymbolPicker** (`widgets/symbol_picker.py`): autocomplete consumindo `vigent_contract()` via CatalogAdapter. Mostra contrato vigente em destaque + alternativas. Botão "Listar Vigentes" abre modal com tabela de contratos.
- **PeriodPicker** (`widgets/period_picker.py`): dropdown com presets (`PLH_PERIOD_*`) + opção "Customizado" que expande para 2 DateEdits.
- **Drawer "Avançado"** (collapsible): chunk size, retry policy, pasta destino (delegada para Settings se mudada).
- **Botão primário**: cor `primary` #4F8CFF, padding 10×20, border-radius 6px, semibold. Tooltip `TIP_BTN_DOWNLOAD`.

### Estado: **Loading** (download em andamento)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Baixando WDOJ26                                                             │ ← title (verbo gerúndio)
│  Mês corrente — mar/2026 → mai/2026                                          │ ← subtitle
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  Contrato atual: WDOJ26                                                  │ │ ← current_contract (M16)
│  │                                                                          │ │
│  │  ████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░ 40%                │ │ ← QProgressBar ciano
│  │  Chunk 4 de 12  •  02:14 elapsed  •  ~04:30 restante                    │ │
│  │                                                                          │ │
│  │  ▸ Detalhes (clique para expandir log)                                  │ │ ← expansível
│  │                                                                          │ │
│  │                                                            [CANCELAR]    │ │ ← destrutivo
│  │                                                            (Esc/Ctrl+C)  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  (UI não bloqueia — pode navegar para Catálogo enquanto baixa)              │ ← dim hint
└──────────────────────────────────────────────────────────────────────────────┘
```

**Quando expansível "▸ Detalhes" clicado:**

```
│  │  ▾ Detalhes                                                              │ │
│  │  ┌────────────────────────────────────────────────────────────────────┐ │ │
│  │  │ [15:23:01] Inicializando ProfitDLL...                              │ │ │ ← log streaming
│  │  │ [15:23:03] DLL pronta. Versão: 4.1.0.21                            │ │ │   text.muted
│  │  │ [15:23:04] Login OK (token até 16:23)                              │ │ │   monospace 13px
│  │  │ [15:23:06] Contrato selecionado: WDOJ26 (vigente até 28/03/2026)   │ │ │
│  │  │ [15:23:07] Iniciando download de mar/2026 → mai/2026...            │ │ │
│  │  │ [15:25:21] Chunk 4/12 OK (98.234 trades em 12.3s)                  │ │ │
│  │  └────────────────────────────────────────────────────────────────────┘ │ │
```

### Sub-Estado: **Loading.reconnecting** (quirk 99%)

```
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  Contrato atual: WDOJ26                                                  │ │
│  │                                                                          │ │
│  │  ███████████████████████████████████████████████████░ 99%  ↻            │ │ ← AMARELO + spinner
│  │                                                                          │ │   F2C94C
│  │  ┌────────────────────────────────────────────────────────────────────┐ │ │
│  │  │  ⚠  A corretora está reconectando — é normal, aguarde até 30 minutos.│ │ ← banner amarelo
│  │  │     Não cancele.                                                     │ │ │   WAR_99_RECONNECT literal
│  │  └────────────────────────────────────────────────────────────────────┘ │ │
│  │                                                                          │ │
│  │  ▸ Detalhes                                                             │ │
│  │                                                                          │ │
│  │                                       [CANCELAR] (?)                     │ │ ← tooltip warning extra
│  └────────────────────────────────────────────────────────────────────────┘ │
```

**Tooltip do botão CANCELAR durante reconnect:**

```
┌───────────────────────────────────────────────────────────────────┐
│ Reconnect normal — cancelar agora pode forçar re-baixar tudo.    │
└───────────────────────────────────────────────────────────────────┘
```

### Sub-Estado: **Loading.cancelling** (após confirm cancel)

```
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  Contrato atual: WDOJ26                                                  │ │
│  │                                                                          │ │
│  │  ██████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 35%  ↻            │ │ ← amarelo + spinner
│  │                                                                          │ │
│  │  ↻ Drenando fila + commitando parcial...                                │ │ ← INF_GRACEFUL_SHUTDOWN
│  │                                                                          │ │
│  │  ▸ Detalhes                                                             │ │
│  │                                                                          │ │
│  │                                            [Cancelando...] (disabled)   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

### Modal de Confirmação Cancel (sobre Loading)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│         ┌────────────────────────────────────────────────────────┐          │ ← QDialog modal
│         │                                                          │          │   bg.elevated
│         │  ⚠  Cancelar download em progresso?                     │          │
│         │                                                          │          │
│         │  Trades já baixados serão preservados                   │          │
│         │  (cache hit em re-tentativa).                            │          │
│         │                                                          │          │
│         │           [Continuar baixando]  [Sim, cancelar]          │          │
│         │                                                          │          │
│         └────────────────────────────────────────────────────────┘          │
│                                                                              │
│  (resto da tela esmaecido — overlay rgba(0,0,0,0.5))                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Error** (DLL não conectou)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Baixar Histórico                                                            │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  ✗ Não conectei à ProfitDLL                                             │ │ ← vermelho bold
│  │    A chave de licença pode estar inválida ou expirada.                  │ │
│  │    Verifique a chave em Configurações > DLL e clique em Testar.         │ │
│  │                                                                          │ │
│  │    ▸ Mais detalhes                                                      │ │ ← expansível
│  │                                                                          │ │
│  │              [TENTAR NOVAMENTE]    [ABRIR CONFIGURAÇÕES]                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Quando "▸ Mais detalhes" expandido:**

```
│  │    ▾ Mais detalhes                                                      │ │
│  │    ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │    │ Código DLL: NL_NO_LICENSE                                        │ │ │ ← log técnico
│  │    │ Hora: 2026-05-03 15:23:01                                        │ │ │   monospace 13px
│  │    │ Stack:                                                           │ │ │   text.muted
│  │    │   data_downloader.dll.session.connect()                          │ │ │
│  │    │   ProfitDLL.dll DLLInitializeMarket -> -2147483635               │ │ │
│  │    │ Sugestão: renove em https://nelogica.com.br + atualize PROFITDLL_KEY│ │ │
│  │    └──────────────────────────────────────────────────────────────────┘ │ │
```

### Estado: **Empty** (primeira vez no app — sem `last_symbol` cache)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Baixar Histórico                                                            │
│  Bem-vindo! Selecione um símbolo + período + clique em Baixar.              │ ← welcome subtitle
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  Símbolo                                                                 │ │
│  │  ┌────────────────────────────────────────────────────┐                 │ │
│  │  │ ex: WDOJ26                                          │  ▾              │ │ ← placeholder dim
│  │  └────────────────────────────────────────────────────┘                 │ │
│  │  WDOJ26 sugerido — contrato vigente do WDO                              │ │ ← dim hint
│  │                                                                          │ │
│  │  Período                                                                 │ │
│  │  ┌────────────────────────────────────────────────────┐                 │ │
│  │  │ Mês corrente  ▾                                    │                 │ │
│  │  └────────────────────────────────────────────────────┘                 │ │
│  │                                                                          │ │
│  │                                                  [⬇ BAIXAR HISTÓRICO]   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  📖 Primeira vez? Veja o tour rápido em Ajuda (F1)                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Success** (toast 5s + tela volta ao normal)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                          ┌────────────────────────────────┐ │ ← toast top-right
│                                          │  ✓ WDOJ26                       │ │   verde, 5s, dismissable
│                                          │    1.234.567 trades em 3 arq.   │ │
│                                          │    → Ver no Catálogo            │ │
│                                          └────────────────────────────────┘ │
│  Baixar Histórico                                                            │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Símbolo                                                                 │ │
│  │  ┌────────────────────────────────────────────────────┐                 │ │
│  │  │ WDOJ26  ▾   (campos voltam preenchidos)            │                 │ │
│  │  └────────────────────────────────────────────────────┘                 │ │
│  │  ...                                                                     │ │
│  │                                                  [⬇ BAIXAR HISTÓRICO]   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Atalhos da DownloadScreen (THEME.md §6)

- `Ctrl+D` — Iniciar download (se campos válidos).
- `Ctrl+R` — Repetir último download (preenche campos, foca botão).
- `Esc` — Context-aware: cancela download ativo se houver, senão no-op.
- `Ctrl+L` — Foca campo símbolo (autocomplete).
- `Ctrl+E` — Edita período (foca dropdown).
- `Ctrl+C` — Cancelar download (mesmo que Esc com download ativo).

---

## Tela 2 — CatalogScreen

Implementação: Felix Story 3.3.

### Estado: **Normal** (com items)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Catálogo                                              [↻ Atualizar Ctrl+R] │ ← title + action
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  🔍 Buscar por símbolo...                              [Filtros ▾]    │ │ ← search + filters
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌──────────┬──────────────┬──────────┬─────────┬──────┬─────────────────┐ │
│  │ Símbolo  │ Período      │ Trades   │ Arquivos│ MB   │ Atualizado      │ │ ← QHeaderView
│  ├──────────┼──────────────┼──────────┼─────────┼──────┼─────────────────┤ │
│  │ WDOJ26   │ mar/2026     │ 1.234.567│ 3       │ 45.2 │ há 2 minutos    │ │ ← row selecionada (azul)
│  │ WDOH26   │ fev/2026     │ 1.876.432│ 4       │ 62.8 │ há 1 dia        │ │
│  │ WINJ26   │ mar/2026     │   876.543│ 2       │ 28.4 │ há 3 dias       │ │
│  │ WDOG26 ⚠│ jan/2026     │   234.567│ 1       │  8.2 │ há 1 semana     │ │ ← drift warning
│  │ ...      │              │          │         │      │                 │ │
│  └──────────┴──────────────┴──────────┴─────────┴──────┴─────────────────┘ │
│                                                                              │
│  ┌── Detalhes: WDOJ26 (selecionado) ───────────────────────────────────┐   │ ← detail panel
│  │  Pasta:    ~/data-downloader/data/B/WDOJ26/2026/03/                  │   │   QSplitter divider
│  │  Schema:   v1.0.0   •   DLL: 4.1.0.21                                │   │
│  │  Checksum: ✓ válido (sha256: a3f7...)                                │   │
│  │  Row count: 1.234.567   •   Tamanho: 45.2 MB                         │   │
│  │                                                                        │   │
│  │  [VALIDAR] [ABRIR PASTA] [REPETIR DOWNLOAD] [APAGAR]                 │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  4 partições  •  144.6 MB total                            ⚠ 1 com drift   │ ← footer summary
└──────────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Loading** (carregando catálogo)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Catálogo                                              [↻ Atualizar Ctrl+R] │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  🔍 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  [Filtros ▾]    │ │ ← skeleton dim
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │ ← skeleton rows
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │   animado
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│                                                                              │
│  Carregando catálogo...                                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Error** (catálogo dessincronizado)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Catálogo                                                                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │  ⚠ Catálogo desincronizado                                              │ │ ← amarelo bold
│  │    Detectei diferença entre o catálogo SQLite e os arquivos no disco.   │ │
│  │    Rode reconciliação para corrigir.                                    │ │
│  │                                                                          │ │
│  │                          [RECONCILIAR]    [ABRIR PASTA]                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Empty** (primeira vez ou tudo apagado)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Catálogo                                                                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │                                                                          │ │
│  │                              📁                                         │ │ ← ícone xl 32px
│  │                                                                          │ │
│  │                  Nenhum histórico baixado ainda.                        │ │ ← title
│  │                  Comece baixando um símbolo.                            │ │ ← subtitle
│  │                                                                          │ │
│  │                       [⬇ BAIXAR HISTÓRICO]                              │ │ ← CTA primário
│  │                                                                          │ │
│  │                                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Empty filtrado** (busca sem resultado)

```
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  🔍 WIN                                                [Filtros ▾]    │ │ ← filter active
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                          │ │
│  │                  Nenhum histórico encontrado para "WIN".                │ │
│  │                  Tente outros filtros ou liste tudo.                    │ │
│  │                                                                          │ │
│  │                          [Limpar filtros]                                │ │
│  │                                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Success** (após reconciliar — toast 4s)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                          ┌────────────────────────────────┐ │
│                                          │  ✓ Catálogo reconciliado        │ │ ← toast verde
│                                          │    3 entradas adicionadas, 0   │ │   4s
│                                          │    removidas.                   │ │
│                                          └────────────────────────────────┘ │
│  Catálogo                                              [↻ Atualizar Ctrl+R] │
│  ...                                                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Confirmação destrutiva — Apagar partição

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│         ┌────────────────────────────────────────────────────────┐          │ ← QDialog modal
│         │                                                          │          │   bg.elevated
│         │  ⚠  Apagar PERMANENTEMENTE histórico de WDOJ26?         │          │
│         │                                                          │          │
│         │  Esta operação é irreversível.                           │          │
│         │  Trades serão removidos do disco e do catálogo.         │          │
│         │                                                          │          │
│         │  Digite APAGAR para confirmar:                           │          │
│         │  ┌──────────────────────────────────────────────────┐   │          │
│         │  │                                                    │   │          │ ← input vazio
│         │  └──────────────────────────────────────────────────┘   │          │
│         │                                                          │          │
│         │                  [Cancelar]   [Apagar permanentemente]  │          │ ← red destructive
│         │                                  (disabled até "APAGAR") │          │
│         └────────────────────────────────────────────────────────┘          │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Atalhos da CatalogScreen (THEME.md §6)

- `Ctrl+R` — Refresh catálogo (re-lê SQLite). **NÃO F5** (finding M10).
- `Ctrl+F` — Foca campo de busca.
- `Esc` — Limpa filtros (se algum ativo); senão no-op.
- `Enter` — Abre detalhe do item selecionado (já visível no detail panel).
- `Delete` — Apagar item selecionado (com confirmação destrutiva).
- `Ctrl+O` — Abrir pasta do item no Explorer.

---

## Tela 3 — SettingsScreen

Implementação: Felix Story 3.4.

### Estado: **Normal**

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Configurações                                                               │ ← title 18px
│                                                                              │
│  ┌── ProfitDLL ────────────────────────────────────────────────────────────┐ │
│  │  Status:    ✓ Conectada (versão 4.1.0.21)                                │ │ ← green
│  │  DLL path:  C:\ProfitDLL\ProfitDLL.dll                                  │ │
│  │  Variáveis .env:                                                         │ │
│  │    PROFITDLL_KEY:    ●●●●●●●●●●●●1234   [Mostrar]                       │ │
│  │    PROFIT_USER:      trader@example.com                                  │ │
│  │    PROFIT_PASS:      ●●●●●●●●●●           [Mostrar]                      │ │
│  │                                                                          │ │
│  │  [TESTAR CONEXÃO]   [ABRIR PASTA DLL]                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌── Storage ─────────────────────────────────────────────────────────────┐ │
│  │  Pasta data: ~/data-downloader/data/                                    │ │
│  │  Espaço:     245.3 GB livres de 500 GB total                            │ │
│  │  Catálogo:   ✓ íntegro (47 partições registradas)                        │ │
│  │                                                                          │ │
│  │  [MUDAR PASTA]   [ABRIR NO EXPLORER]   [VERIFICAR INTEGRIDADE]          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌── Performance (read-only) ─────────────────────────────────────────────┐ │
│  │  DLL queue size:       8192 (default)                                   │ │
│  │  Storage queue size:   2048 (default)                                   │ │
│  │  Chunk size:           30 dias (default)                                │ │
│  │  Max retries:          3 (default)                                      │ │
│  │  (Mudanças requerem advanced flags — consulte docs/perf/)               │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌── About ────────────────────────────────────────────────────────────────┐ │
│  │  data-downloader v0.1.0                                                  │ │
│  │  ProfitDLL: 4.1.0.21                                                     │ │
│  │  Schema:    v1.0.0                                                       │ │
│  │                                                                          │ │
│  │  📖 Documentação:  https://github.com/.../docs                          │ │
│  │  🐛 Reportar bug:  https://github.com/.../issues                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  [DIAGNÓSTICO COMPLETO (doctor)]                                  [SALVAR]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Layout:** `QScrollArea` contendo `QVBoxLayout` com `QGroupBox` por seção. Densidade: comfortable default.

### Estado: **Loading** (testando conexão DLL)

```
│  ┌── ProfitDLL ────────────────────────────────────────────────────────────┐ │
│  │  Status:    ↻ Testando conexão...                                       │ │ ← amarelo + spinner
│  │  DLL path:  C:\ProfitDLL\ProfitDLL.dll                                  │ │
│  │  ...                                                                     │ │
│  │                                                                          │ │
│  │  [Testando...] (disabled)   [ABRIR PASTA DLL]                           │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Error** (teste de conexão falhou)

```
│  ┌── ProfitDLL ────────────────────────────────────────────────────────────┐ │
│  │  Status:    ✗ Não conectou                                              │ │ ← red bold
│  │                                                                          │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐ │ │
│  │  │ ✗ Não conectei à ProfitDLL                                       │ │ │
│  │  │   A chave de licença pode estar inválida ou expirada.            │ │ │
│  │  │   Renove em https://nelogica.com.br e atualize PROFITDLL_KEY.    │ │ │
│  │  │   ▸ Mais detalhes                                                │ │ │
│  │  └──────────────────────────────────────────────────────────────────┘ │ │
│  │                                                                          │ │
│  │  [TENTAR NOVAMENTE]   [EDITAR .env]                                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Empty** (primeira execução — .env não configurado)

```
│  ┌── ProfitDLL ────────────────────────────────────────────────────────────┐ │
│  │  Status:    ⚠ Não configurado                                           │ │ ← yellow
│  │                                                                          │ │
│  │  Para começar, configure suas credenciais ProfitDLL:                    │ │
│  │                                                                          │ │
│  │    1. Obtenha sua chave em https://nelogica.com.br                      │ │
│  │    2. Crie/edite ~/.data-downloader/.env com as variáveis               │ │
│  │       PROFITDLL_KEY, PROFIT_USER, PROFIT_PASS                            │ │
│  │       (formato chave = valor, uma por linha)                             │ │
│  │    3. Clique em Testar Conexão                                          │ │
│  │                                                                          │ │
│  │  [ABRIR PASTA .env]   [TESTAR CONEXÃO]                                  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Success** (após salvar)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                          ┌────────────────────────────────┐ │
│                                          │  ✓ Configurações salvas.       │ │ ← toast verde 3s
│                                          └────────────────────────────────┘ │
│  Configurações                                                               │
│  ...                                                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Atalhos da SettingsScreen (THEME.md §6)

- `Ctrl+S` — Salvar (atalho convencional).
- `Esc` — Sair sem salvar (com confirmação se mudou algo).

---

## Notas de Implementação para Felix (Epic 3)

1. **MainWindow** (Story 3.1): `QMainWindow` com sidebar `QListWidget` ou custom `QFrame` esquerda + `QStackedWidget` central + `QStatusBar` inferior. Atalhos globais via `QShortcut(Qt.ApplicationShortcut)` + `eventFilter` para Esc context-aware.

2. **DownloadScreen** (Story 3.2): `QWidget` com `QFormLayout` para inputs + `QStackedLayout` interno para 5 estados; `QProgressBar` com property dinâmica `state` (qss switch ciano/amarelo/verde) — finding M9 reforço.

3. **CatalogScreen** (Story 3.3): `QSplitter` vertical: top = `QTableView` + `QSortFilterProxyModel`; bottom = detail panel (`QFrame`). Empty state via `QStackedWidget` interno com 3 páginas (table, empty-first-run, empty-filtered).

4. **SettingsScreen** (Story 3.4): `QScrollArea` + `QGroupBox` por seção; cada seção tem própria stack para 5 estados.

5. **Toasts**: widget custom `widgets/toast.py` (não existe ainda; Felix cria) — `QFrame` flutuante top-right com `QPropertyAnimation` para fade in/out; auto-dismiss via `QTimer.singleShot`.

6. **Atalhos globais vs locais**: globais via `QShortcut(QKeySequence(...), self.main_window, context=Qt.ApplicationShortcut)`; locais (Esc na DownloadScreen) via `Qt.WidgetWithChildrenShortcut` — finding QT_PATTERNS §6.1.

7. **5 estados por tela**: implementar como `QStackedWidget` interno com índices nomeados (ENUM `ScreenState.NORMAL/LOADING/ERROR/EMPTY/SUCCESS`). Transições fade 200ms via `QPropertyAnimation`.

8. **Theming**: `assets/style.qss` carregado uma vez em `app.py` via `app.setStyleSheet()`. Nunca styling inline — finding QT_PATTERNS §5.

9. **`DontUseNativeDialog`** em todos `QFileDialog` — finding M9. Wrapper em `widgets/file_dialog.py` para enforce.

10. **HiDPI**: `QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)` antes de `QApplication()`. Assets em SVG.

11. **Não bloquear MainThread**: todo I/O via Adapter em `QThread`. Slots conectados com `Qt.QueuedConnection` explícito — finding QT_PATTERNS §2.2.

12. **`current_contract` em DownloadProgress**: label dedicado atualiza a cada progress (M16) — finding QT_PATTERNS §2.4.

13. **Métrica `ui_progress_dropped_count`**: M11 — Pyro instrumenta; UI registra mas não expõe diretamente (apenas no log expansível se > 0).

---

## Referências

- THEME.md (paleta + atalhos + tipografia + iconografia)
- MICROCOPY_CATALOG.md (textos exatos + IDs novos Epic 3 prep)
- FLOWS.md (fluxos detalhados Epic 3-ready)
- PRINCIPLES.md (5 estados, density, hierarquia, P4 quirk 99%)
- QT_PATTERNS.md (Felix — implementação técnica Qt)
- ADR-003 + amendment (PySide6 single-process, --onedir, DontUseNativeDialog)
- COUNCIL-12 (Epic 3 prep sign-off)

---

— Uma, desenhando empatia 🎨
