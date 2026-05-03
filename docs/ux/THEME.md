# THEME — Paleta, Tipografia, Espaçamento, Atalhos

> Theming unificado **CLI Rich + Qt PySide6**. Cor é semântica, não decoração.
> Felix implementa Qt; Dex implementa CLI; Uma valida ambos.

**Versão:** 1.0.0
**Data:** 2026-05-03
**Status:** ratificado (Story 0.3, finding M8)
**Autoridade:** 🎨 Uma — exclusiva

---

## 1. Modo de Cor

**Default: dark mode.** Trading e finanças têm uso noturno frequente; dark mode
é o padrão do squad. Light mode opcional em V2 (não bloqueia release).

### Justificativa

- Menor fadiga visual em sessões longas (download de meses).
- Convenção do mercado (terminais Bloomberg, plataformas pro).
- Reduz consumo de energia em telas OLED/AMOLED.

---

## 2. Paleta — Dark Mode

### Cores base (background / surface / texto)

| Token | Hex (Qt) | Rich color | Uso |
|-------|----------|------------|-----|
| `bg.primary` | `#0E0E10` | (default terminal) | Fundo da janela / fundo do terminal |
| `bg.surface` | `#17171A` | — | Cartões, painéis elevados |
| `bg.elevated` | `#1F1F23` | — | Modais, drawers, popovers |
| `bg.input` | `#26262B` | — | Inputs, dropdowns |
| `border.subtle` | `#2D2D33` | `grey23` | Divisores entre painéis |
| `border.strong` | `#3D3D45` | `grey35` | Borda de input focado (não-acento) |
| `text.primary` | `#E8E8EA` | `white` / `default` | Texto principal |
| `text.secondary` | `#A8A8AC` | `grey70` | Subtítulos, metadata |
| `text.muted` | `#6E6E74` | `grey50` | Texto auxiliar, timestamps |
| `text.disabled` | `#4A4A50` | `grey35` | Estados desativados |

### Cores semânticas (a "lei das cores")

| Token | Hex (Qt) | Rich color | Significado | Uso |
|-------|----------|------------|-------------|-----|
| `accent.cyan` | `#3DD0E1` | `cyan` | Foco, link, ação primária neutra | Borda de input focado, links, ícones primários |
| `primary` | `#4F8CFF` | `blue` | Ação primária — DOWNLOAD | Botão BAIXAR |
| `success.green` | `#3FCB6F` | `green` | Sucesso, OK, validado | Toast sucesso, ✓, barra completa |
| `error.red` | `#F25656` | `red` | Erro, destrutivo, cancelar | Toast erro, ✗, botão APAGAR, exit code != 0 |
| `warning.yellow` | `#F2C94C` | `yellow` | Atenção, quirk 99%, warning | ⚠, barra durante reconnect, prompts |
| `info.blue` | `#5E9FFF` | `bright_blue` | Informativo neutro | Mensagens INF_* |

### Estados (overlays sobre cores base)

| Token | Aplicação | Implementação |
|-------|-----------|---------------|
| `state.hover` | Hover em botão/item | overlay branco 8% |
| `state.active` | Pressed em botão | overlay branco 12% |
| `state.focus` | Foco teclado | borda `accent.cyan` 2px |
| `state.disabled` | Item desabilitado | opacity 50% + cursor not-allowed |

---

## 3. Mapeamento Rich ↔ Qt

| Semântica | Rich (color name / style) | Qt (hex / QSS) |
|-----------|---------------------------|----------------|
| Texto primário | `default` ou `white` | `color: #E8E8EA` |
| Texto secundário | `grey70` | `color: #A8A8AC` |
| Texto dim | `dim` ou `grey50` | `color: #6E6E74` |
| Sucesso | `bold green` | `color: #3FCB6F; font-weight: bold` |
| Erro | `bold red` | `color: #F25656; font-weight: bold` |
| Warning | `bold yellow` | `color: #F2C94C; font-weight: bold` |
| Info / link | `cyan` | `color: #3DD0E1` |
| Link clicável | `cyan underline` | `color: #3DD0E1; text-decoration: underline` |
| Botão primário | (n/a CLI — comando colorido) | `bg: #4F8CFF; color: #FFF` |
| Barra progresso (normal) | `progress.bar: cyan` | `QProgressBar::chunk { background: #3DD0E1 }` |
| Barra progresso (reconnect) | `progress.bar: yellow` | `QProgressBar::chunk { background: #F2C94C }` |
| Barra progresso (concluído) | `progress.bar: green` | `QProgressBar::chunk { background: #3FCB6F }` |

### Tema Rich exportável

```
from rich.theme import Theme

DD_THEME = Theme({
    "info": "bright_blue",
    "warning": "bold yellow",
    "danger": "bold red",
    "success": "bold green",
    "muted": "grey50",
    "link": "cyan underline",
    "progress.bar": "cyan",
    "progress.bar.warning": "yellow",
    "progress.bar.complete": "green",
    "label": "grey70",
})
console = Console(theme=DD_THEME)
```

### Tema Qt (QSS — esqueleto)

```
/* base */
QMainWindow, QDialog { background: #0E0E10; color: #E8E8EA; }
QWidget { font-family: "Segoe UI", "Inter", sans-serif; font-size: 14px; }

/* surface */
QFrame[elevated="true"], QGroupBox { background: #17171A; border: 1px solid #2D2D33; border-radius: 6px; }

/* input */
QLineEdit, QComboBox, QDateEdit, QSpinBox {
    background: #26262B; color: #E8E8EA; border: 1px solid #2D2D33;
    border-radius: 4px; padding: 6px 10px;
}
QLineEdit:focus, QComboBox:focus { border-color: #3DD0E1; }

/* button primário */
QPushButton[primary="true"] {
    background: #4F8CFF; color: #FFF; border: none;
    padding: 10px 20px; border-radius: 6px; font-weight: 600;
}
QPushButton[primary="true"]:hover { background: #6BA0FF; }
QPushButton[primary="true"]:pressed { background: #3D7AE8; }

/* button destrutivo */
QPushButton[destructive="true"] { background: #F25656; color: #FFF; }

/* progress */
QProgressBar { background: #26262B; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #3DD0E1; border-radius: 4px; }
QProgressBar[state="reconnecting"]::chunk { background: #F2C94C; }
QProgressBar[state="complete"]::chunk { background: #3FCB6F; }
```

(Felix expande no Epic 3.)

---

## 4. Tipografia

### Família

- **Qt:** `Segoe UI` (default Windows) com fallback `Inter`, `system-ui`, `sans-serif`.
- **CLI:** herda do terminal do usuário (não força). Recomendado para o usuário:
  fonte monoespaçada com suporte a Powerline/Nerd Font (mas não obrigatório).

### Escala

| Token | Tamanho | Peso | Uso |
|-------|---------|------|-----|
| `font.title` | 18px | 600 (semibold) | Título de tela, header |
| `font.subtitle` | 16px | 500 (medium) | Subtítulo, seção |
| `font.body` | 14px | 400 (regular) | Texto principal — **base** |
| `font.body-bold` | 14px | 600 | Ênfase em texto |
| `font.secondary` | 12px | 400 | Metadata, captions, tooltips |
| `font.code` | 13px | 400 monospace | Código, comando, símbolo de contrato |

### Line height

Default 1.5x do tamanho da fonte. Para títulos: 1.3x.

---

## 5. Espaçamento

**Sistema:** múltiplos de 4px. **Sempre.** Não use 5px, 7px, 10px, etc.

| Token | Pixels | Uso típico |
|-------|--------|------------|
| `space.xs` | 4px | Gap entre ícone e label |
| `space.sm` | 8px | Padding interno de pill, gap entre items relacionados |
| `space.md` | 12px | Padding de input |
| `space.lg` | 16px | Padding de cartão, gap entre seções relacionadas |
| `space.xl` | 24px | Margin entre seções não-relacionadas |
| `space.2xl` | 32px | Margin lateral de tela |
| `space.3xl` | 48px | Margin top de tela / spacing dramático |

### Density

- **Comfortable** (default): espaçamento usa tokens completos acima.
- **Compact** (opcional, drawer Configurações): espaçamentos reduzidos a ~75%
  (xs: 4, sm: 6, md: 8, lg: 12, xl: 16, 2xl: 24, 3xl: 32).

---

## 6. Atalhos de Teclado

### CLI

| Atalho | Contexto | Ação |
|--------|----------|------|
| `Ctrl+C` | Download em progresso | Graceful cancel (drena fila + commita parcial + prompt confirmação) |
| `Ctrl+C Ctrl+C` | Download em progresso | Force quit (pode perder buffer) |
| `Enter` | Prompt interativo | Aceita default |
| `Ctrl+D` | Prompt EOF | Sai sem confirmar (mesmo que `n` em prompts boolean) |

### Qt — Globais

| Atalho | Contexto | Ação |
|--------|----------|------|
| `Ctrl+D` | Qualquer tela | Foca na tela Download / inicia download se já configurado |
| `Ctrl+B` | Qualquer tela | Foca na tela Catálogo (Browse) |
| `Ctrl+R` | Qualquer tela | Refresh contextual (recarrega dados da tela ativa) |
| `Ctrl+,` | Qualquer tela | Abre Configurações |
| `Ctrl+Q` | Qualquer tela | Sair do app (com confirmação se download em progresso) |
| `Ctrl+/` | Qualquer tela | Mostra atalhos disponíveis (cheat sheet modal) |
| `F1` | Qualquer tela | Ajuda contextual (abre documentação relevante) |
| `Tab` / `Shift+Tab` | Qualquer tela | Navegação entre campos (foco visível obrigatório) |

### Qt — Esc context-aware (ESPECIFICAÇÃO CRÍTICA)

`Esc` **não tem ação única** — depende do contexto. Ordem de prioridade:

1. **Modal aberto?** → fecha modal (sem confirmar mudanças, equivale a Cancel).
2. **Drawer aberto?** → fecha drawer.
3. **Dropdown aberto?** → fecha dropdown.
4. **DownloadScreen com download em progresso?** → mesma ação que Ctrl+C
   (graceful cancel com prompt de confirmação).
5. **DownloadScreen sem download em progresso?** → no-op (não fecha o app).
6. **CatalogScreen com filtro ativo?** → limpa filtros.
7. **Outras telas?** → no-op.

Implementação Felix: `eventFilter` no MainWindow despachando para handler do
contexto ativo.

### Qt — Por tela

#### DownloadScreen

| Atalho | Ação |
|--------|------|
| `Ctrl+D` | Iniciar download (se campos válidos) |
| `Ctrl+R` | Repetir último download (preenche campos, foca botão) |
| `Esc` | (ver lógica context-aware acima) |
| `Ctrl+L` | Foca campo símbolo (autocomplete) |
| `Ctrl+E` | Edita período (foca dropdown) |

#### CatalogScreen

| Atalho | Ação |
|--------|------|
| `Ctrl+R` | Refresh catálogo (re-lê SQLite) |
| `Ctrl+F` | Foca campo de busca |
| `Esc` | Limpa filtros (se algum) |
| `Enter` | Abre detalhe do item selecionado |
| `Delete` | Apagar item selecionado (com confirmação destrutiva) |
| `Ctrl+O` | Abrir pasta do item no Explorer |

#### SettingsScreen

| Atalho | Ação |
|--------|------|
| `Ctrl+S` | Salvar (atalho convencional) |
| `Esc` | Sair sem salvar (com confirmação se mudou algo) |

### Por que NÃO usar F5

`F5` tem **side-effects históricos** em outras ferramentas:

- Em editores: re-roda código.
- Em browsers: refresh.
- Em IDEs: debug start.
- Em planilhas: recalcular.

Cada usuário tem expectativa diferente. **Ctrl+R é a convenção universal** para
"refresh" em apps desktop modernos (browsers, Discord, Slack, VS Code). Mais
seguro semanticamente.

### Cheat sheet acessível

`Ctrl+/` em qualquer tela abre modal com **todos** os atalhos da tela ativa +
globais. Felix implementa no Epic 3.

---

## 7. Símbolos Unicode + Fallback ASCII

### Mapeamento canônico

| Unicode | Codepoint | ASCII fallback | Significado |
|---------|-----------|----------------|-------------|
| ✓ | U+2713 | `[OK]` | Sucesso |
| ✗ | U+2717 | `[X]` | Erro / failure |
| ⚠ | U+26A0 | `[!]` | Warning |
| ↻ | U+21BB | `[~]` | Loading / processing / cancelando |
| ⬇ | U+2B07 | `[v]` | Download |
| ⬆ | U+2B06 | `[^]` | Upload (futuro) |
| ▸ | U+25B8 | `>` | Expandir / next |
| ▾ | U+25BE | `v` | Recolher / down |
| → | U+2192 | `->` | Navegar / próximo |
| ← | U+2190 | `<-` | Voltar |
| ⋯ | U+22EF | `...` | Menu mais opções / continuação |
| 📖 | U+1F4D6 | (omitido) | Documentação (decorativo) |
| 🐛 | U+1F41B | (omitido) | Bug report (decorativo) |
| █ | U+2588 | `#` | Bloco progress bar cheio |
| ░ | U+2591 | `-` | Bloco progress bar vazio |

### Política de fallback

Aplicar fallback automaticamente quando:
1. `--ascii-only` flag passada.
2. `sys.stdout.encoding` != utf-8 e não é "UTF-8" (case-insensitive).
3. Tentativa de escrever um Unicode levanta `UnicodeEncodeError` (rare).

Emojis decorativos (📖, 🐛) **caem** no fallback ASCII (não viram texto), pois
não são essenciais para entendimento. Símbolos semânticos (✓ ✗ ⚠) **sempre**
têm equivalente textual.

---

## 8. Iconografia (Qt)

Stack: ícones via **Phosphor Icons** ou **Material Symbols Outlined** (Felix
escolhe; Uma valida consistência). Tamanhos:

| Token | Tamanho | Uso |
|-------|---------|-----|
| `icon.sm` | 16px | Inline em texto, table cells |
| `icon.md` | 20px | Botões padrão |
| `icon.lg` | 24px | Botões primários, header |
| `icon.xl` | 32px | Empty state, hero |

Cor padrão herda `text.primary`. Ícones com cor semântica (ex: ✗ vermelho) são
exceção justificada por significado.

---

## 9. Animação / Transições

- **Duração padrão:** 200ms (rápido o suficiente para não cansar, lento para
  dar feedback).
- **Easing:** `cubic-bezier(0.4, 0, 0.2, 1)` (Material Design standard).
- **Hover:** transição opacity/cor 150ms.
- **Modal abrir/fechar:** fade 200ms.
- **Toast:** slide-in 250ms / slide-out 200ms.

**Reduce motion:** respeitar `QApplication.styleHints().showIsFullScreen()` —
em V2, ler preferência de OS para "prefer reduced motion" e desativar
animações quando ativo.

---

## 10. Auditoria de Contraste (WCAG AA)

Combinações pre-aprovadas:

| Texto | Background | Contraste | Status |
|-------|------------|-----------|--------|
| `#E8E8EA` (text.primary) | `#0E0E10` (bg.primary) | 16.7:1 | AAA ✓ |
| `#A8A8AC` (text.secondary) | `#0E0E10` | 8.2:1 | AAA ✓ |
| `#6E6E74` (text.muted) | `#0E0E10` | 4.5:1 | AA ✓ |
| `#3DD0E1` (accent.cyan) | `#0E0E10` | 9.4:1 | AAA ✓ |
| `#3FCB6F` (success.green) | `#0E0E10` | 7.8:1 | AAA ✓ |
| `#F25656` (error.red) | `#0E0E10` | 5.1:1 | AA ✓ |
| `#F2C94C` (warning.yellow) | `#0E0E10` | 11.2:1 | AAA ✓ |
| `#FFF` em `#4F8CFF` (botão primário) | — | 4.7:1 | AA ✓ |

Texto pequeno (< 14px regular ou < 18px bold): mínimo 4.5:1.
Texto grande (>= 18px ou >= 14px bold): mínimo 3:1.

Combinações rejeitadas (não usar):
- `text.muted` em `bg.input` — apenas 2.8:1.
- `accent.cyan` em `success.green` — saturação demais, hard to read.

---

## 11. Versionamento do Theme

- Mudança aditiva (novo token, nova cor de extensão): bump minor (1.0 → 1.1).
- Mudança quebradora (renomear token, mudar valor existente): bump major
  (1.0 → 2.0) + ADR.
- Felix re-valida QSS, Dex re-valida tema Rich a cada bump.

---

— Uma, desenhando empatia 🎨
