# WIREFRAMES — Esqueletos ASCII das Telas Qt Principais

> Wireframes preliminares para Epic 3. Notação ASCII portátil — Felix traduz
> para PySide6. Cada tela tem 5 estados anotados (normal, loading, error,
> empty, success).

**Versão:** 0.1.0 (seed)
**Data:** 2026-05-03
**Status:** seed (Story 0.3) — refinamento no Epic 3
**Autoridade:** 🎨 Uma — exclusiva sobre wireframes

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
```

Tamanho de referência: janela mínima **960×640** (Qt). Wireframes mostrados
em ~80 cols ASCII.

---

## Tela 1 — DownloadScreen

### Estado: **Normal** (golden path, defaults preenchidos)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  data-downloader                              [Download] Catálogo  ⚙   │ ← header (nav)
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Baixar Histórico                                                        │ ← title 18px
│  (1 botão + aguardar)                                                    │ ← subtitle dim
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Símbolo                                                            │ │
│  │  ┌────────────────────────────────────────────────────────┐         │ │
│  │  │ WDOJ26  ▾                                              │ Listar  │ │
│  │  └────────────────────────────────────────────────────────┘         │ │
│  │  (vigente até 28/03/2026)                                           │ │
│  │                                                                      │ │
│  │  Período                                                             │ │
│  │  ┌────────────────────────────────────────────────────────┐         │ │
│  │  │ Mês corrente  ▾                                        │         │ │
│  │  └────────────────────────────────────────────────────────┘         │ │
│  │  01/03/2026 → 03/05/2026 (~2 meses, ~3-7 min estimados)             │ │
│  │                                                                      │ │
│  │  ▾ Avançado (chunk size, retry, pasta)                              │ │ ← collapsed drawer
│  │                                                                      │ │
│  │                                                  [⬇ BAIXAR HISTÓRICO]│ │ ← primário
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Atalhos: Ctrl+D iniciar • Ctrl+R repetir último • Ctrl+/ todos          │ ← dim footer
└──────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Loading** (download em andamento)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  data-downloader                              [Download] Catálogo  ⚙   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Baixando WDOJ26                                                         │
│  Mês corrente (mar/2026 → mai/2026)                                      │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  ████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░ 40%            │ │
│  │  Chunk 4 de 12 • 02:14 elapsed • ~04:30 restante                    │ │
│  │                                                                      │ │
│  │  ▸ Detalhes (clique para expandir log)                              │ │
│  │                                                                      │ │
│  │                                                          [CANCELAR]  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  (UI não bloqueia: navegue para Catálogo enquanto baixa)                │
└──────────────────────────────────────────────────────────────────────────┘
```

### Sub-Estado: **Loading.reconnecting** (quirk 99%)

```
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  ███████████████████████████████████████████████████░ 99%  ↻        │ │ ← amarelo
│  │  ⚠ A corretora está reconectando — é normal, aguarde até 30 minutos.│ │
│  │     Não cancele.                                                     │ │
│  │                                                                      │ │
│  │  ▸ Detalhes                                                         │ │
│  │                                                                      │ │
│  │                                                          [CANCELAR]  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Error** (DLL não conectou)

```
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  ✗ Não conectei à ProfitDLL                                         │ │ ← vermelho bold
│  │    A chave de licença pode estar inválida ou expirada.              │ │
│  │    Verifique a chave em Configurações > DLL e tente de novo.        │ │
│  │                                                                      │ │
│  │    ▸ Mais detalhes                                                  │ │
│  │                                                                      │ │
│  │                  [TENTAR NOVAMENTE]    [ABRIR CONFIGURAÇÕES]        │ │
│  └────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Empty** (primeira vez no app — sem `last_symbol` cache)

```
│  Baixar Histórico                                                        │
│  Bem-vindo! Selecione um símbolo + período + clique em Baixar.          │ ← welcome subtitle
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Símbolo                                                            │ │
│  │  ┌────────────────────────────────────────────────────────┐         │ │
│  │  │ WDOJ26  ▾   (sugerido — contrato vigente do WDO)       │         │ │
│  │  └────────────────────────────────────────────────────────┘         │ │
│  │  ...                                                                 │ │
│  │                                                  [⬇ BAIXAR HISTÓRICO]│ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  📖 Primeira vez? Veja o tour rápido em Ajuda (F1)                      │
```

### Estado: **Success** (toast 5s + tela volta ao normal)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│         ┌──────────────────────────────────────────────────┐            │ ← toast (overlay)
│         │  ✓ WDOJ26: 1.234.567 trades em 3 arquivos.       │            │   verde, top-right
│         │  → Ver no Catálogo                                │            │
│         └──────────────────────────────────────────────────┘            │
│                                                                          │
│  Baixar Histórico                          (campos voltam preenchidos    │
│  ...                                        para próximo download)       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Tela 2 — CatalogScreen

### Estado: **Normal** (com items)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  data-downloader                              Download [Catálogo]  ⚙   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Catálogo                                            ↻ Atualizar (Ctrl+R)│
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  🔍 Buscar por símbolo...                              [Filtros ▾] │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌──────────┬──────────────┬──────────┬─────────┬──────┬──────────────┐│
│  │ Símbolo  │ Período      │ Trades   │ Arquivos│ MB   │ Atualizado    ││ ← header table
│  ├──────────┼──────────────┼──────────┼─────────┼──────┼──────────────┤│
│  │ WDOJ26   │ mar/2026     │ 1.234.567│ 3       │ 45.2 │ há 2 minutos  ││
│  │ WDOH26   │ fev/2026     │ 1.876.432│ 4       │ 62.8 │ há 1 dia      ││
│  │ WINJ26   │ mar/2026     │   876.543│ 2       │ 28.4 │ há 3 dias     ││
│  │ WDOG26 ⚠│ jan/2026     │   234.567│ 1       │  8.2 │ há 1 semana   ││ ← drift detected
│  │ ...      │              │          │         │      │               ││
│  └──────────┴──────────────┴──────────┴─────────┴──────┴──────────────┘│
│                                                                          │
│  ┌── Detalhes: WDOJ26 (selecionado) ─────────────────────────────────┐ │
│  │  Pasta: ~/data-downloader/data/B/WDOJ26/2026/03/                   │ │
│  │  Schema: v1.0.0  •  DLL: 4.1.0.21                                  │ │
│  │  [VALIDAR] [ABRIR PASTA] [REPETIR DOWNLOAD] [APAGAR]               │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  4 partições  •  144.6 MB total                                         │ ← footer summary
└──────────────────────────────────────────────────────────────────────────┘
```

### Estado: **Loading** (carregando catálogo)

```
│  Catálogo                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  🔍 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  [Filtros ▾] │ │ ← skeleton
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │ ← skeleton rows
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│                                                                          │
│  Carregando catálogo...                                                  │
```

### Estado: **Error** (catálogo dessincronizado)

```
│  Catálogo                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  ⚠ Catálogo desincronizado                                          │ │
│  │    Detectei diferença entre o catálogo SQLite e os arquivos no disco.│ │
│  │    Rode reconciliação para corrigir.                                 │ │
│  │                                                                      │ │
│  │                              [RECONCILIAR]   [ABRIR PASTA]           │ │
│  └────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Empty** (primeira vez ou tudo apagado)

```
│  Catálogo                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │                                                                      │ │
│  │                          📁                                         │ │ ← ícone xl
│  │                                                                      │ │
│  │              Nenhum histórico baixado ainda.                        │ │
│  │              Comece baixando um símbolo.                            │ │
│  │                                                                      │ │
│  │                    [⬇ BAIXAR HISTÓRICO]                             │ │
│  │                                                                      │ │
│  │                                                                      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
```

### Estado: **Success** (após reconciliar — toast 4s)

```
│         ┌──────────────────────────────────────────────────┐            │
│         │  ✓ Catálogo reconciliado                          │            │ ← toast verde
│         │    3 entradas adicionadas, 0 removidas.           │            │
│         └──────────────────────────────────────────────────┘            │
│                                                                          │
│  Catálogo (atualizado)                                                  │
│  ...
```

---

## Tela 3 — SettingsScreen

### Estado: **Normal**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  data-downloader                              Download Catálogo  [⚙]   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Configurações                                                           │
│                                                                          │
│  ┌── DLL ─────────────────────────────────────────────────────────────┐ │
│  │  Status: ✓ Conectada (versão 4.1.0.21)                              │ │
│  │  Chave de licença: ●●●●●●●●●●●●1234   [Mostrar] [Renovar]           │ │
│  │  Usuário: trader@example.com                                         │ │
│  │  [TESTAR CONEXÃO]                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌── Pasta de Destino ────────────────────────────────────────────────┐ │
│  │  Atual: ~/data-downloader/data/                                     │ │
│  │  Espaço: 245.3 GB livres de 500 GB total                            │ │
│  │  [MUDAR PASTA] [ABRIR NO EXPLORER]                                   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌── Aparência ───────────────────────────────────────────────────────┐ │
│  │  Tema:        ● Dark   ○ Light (V2)                                 │ │
│  │  Densidade:   ● Confortável   ○ Compacta                            │ │
│  │  Atalhos:     [VER LISTA COMPLETA]                                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌── Avançado ────────────────────────────────────────────────────────┐ │
│  │  Chunk size: [30] dias   (default; menor = retry mais rápido)       │ │
│  │  Max retries: [3]        (por chunk antes de falhar)                │ │
│  │  Validação automática:   ☑ após cada download                        │ │
│  │  Logs verbose:           ☐ ativar (escreve em ~/.data-downloader/)  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Versão app: 0.1.0  •  DLL: 4.1.0.21  •  Schema: v1.0.0                │
│                                                                          │
│  [DIAGNÓSTICO COMPLETO (doctor)]                          [SALVAR]      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Outros estados de Settings

- **Loading**: ao testar conexão DLL — botão vira "Testando..." spinner.
- **Error**: ao falhar teste — banner vermelho com microcopy ERR_DLL_*.
- **Empty**: (n/a — settings sempre têm conteúdo; só primeira vez tem
  defaults pré-preenchidos).
- **Success**: ao salvar — toast verde "Configurações salvas." 3s.

---

## Notas de Implementação para Felix (Epic 3)

1. **Janela principal**: `QMainWindow` com `QStackedWidget` central, navegação
   por nav top-bar (Download/Catálogo/Configurações).
2. **DownloadScreen**: `QWidget` com `QFormLayout` para inputs + `QProgressBar`
   custom (cor amarela em estado reconnecting).
3. **CatalogScreen**: `QTableView` + `QSortFilterProxyModel` para tabela;
   detail panel embaixo via splitter.
4. **SettingsScreen**: `QScrollArea` com `QGroupBox` por seção.
5. **Toasts**: widget custom flutuante top-right (overlay), auto-dismiss
   por timer.
6. **Atalhos globais**: registrar via `QShortcut(QKeySequence(...), self)` no
   MainWindow + `eventFilter` para Esc context-aware.
7. **5 estados por tela**: implementar como `QStackedWidget` interno OU
   `setVisible()` em groups, com transições fade 200ms.
8. **Theming**: QSS carregado em startup de `assets/theme/dark.qss`. Tokens
   referenciam paleta de THEME.md.
9. **`DontUseNativeDialog`** em QFileDialog (consistência visual — finding M9).
10. **Não bloquear MainThread** — todo I/O em `QThread` (R11).

---

## Referências

- THEME.md (paleta + atalhos)
- MICROCOPY_CATALOG.md (textos exatos)
- FLOWS.md (fluxos detalhados)
- PRINCIPLES.md (5 estados, density, hierarquia)

---

— Uma, desenhando empatia 🎨
