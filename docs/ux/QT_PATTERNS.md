# QT_PATTERNS.md — Padrões Qt/PySide6 para Felix

**Owner:** Felix (frontend-dev)
**Audiência:** implementação de qualquer tela, widget ou adapter PySide6 do data-downloader.
**Status:** living document — atualizar quando novo padrão emergir do código.

> **Escopo:** este documento cobre **padrões técnicos Qt/PySide6** (signal/slot, threading, layout, QSS, atalhos no nível do framework). Ele NÃO duplica:
> - `docs/ux/CLI_PATTERNS.md` (Uma) — padrões de CLI Rich.
> - `docs/ux/THEME.md` (Uma) — paleta canônica, tipografia, atalhos UX canônicos.
>
> Quando houver atalho UX (ex.: "Esc cancela download"), QT_PATTERNS descreve **como** implementar em Qt; THEME.md define **o quê** e **quando**. Em conflito, **Uma é autoridade** (R17 — microcopy + atalhos UX).

---

## 1. File Dialogs — `DontUseNativeDialog` (finding M9)

**Regra:** todos os `QFileDialog` do app DEVEM usar `DontUseNativeDialog`.

```python
from PySide6.QtWidgets import QFileDialog

dialog = QFileDialog(self)
dialog.setOption(QFileDialog.DontUseNativeDialog, True)
dialog.setFileMode(QFileDialog.Directory)
dialog.setWindowTitle('Selecionar pasta de destino')
if dialog.exec():
    paths = dialog.selectedFiles()
```

Ou na forma estática:

```python
path, _ = QFileDialog.getOpenFileName(
    self,
    caption='Abrir Parquet',
    dir=str(self._last_dir),
    filter='Parquet (*.parquet)',
    options=QFileDialog.DontUseNativeDialog,   # OBRIGATÓRIO
)
```

**Por quê?**
- Dialog nativo do Windows ignora QSS — quebra o tema escuro do app, gera flash branco e fontes diferentes.
- O dialog Qt obedece o stylesheet, garantindo paleta consistente em qualquer tela.

**Trade-off documentado:**
- O dialog Qt é **menos polido** que o nativo (sem painel "Acesso Rápido", sem preview, sem integração com OneDrive/SharePoint).
- Aceitamos a perda de polimento em troca de **consistência visual** — princípio "fiel ao desenho de Uma" prevalece sobre conveniência do SO.
- Se Uma decidir reverter no futuro, basta remover o flag em um único helper.

**Implementação centralizada (recomendada):** criar `src/data_downloader/ui/widgets/file_dialog.py` com wrappers que já aplicam o flag — ninguém esquece, ninguém customiza errado.

---

## 2. Padrão Signal/Slot Canônico

Referência completa: `agents/frontend-dev.md` → `expertise.signal_slot_pattern_v1`.

### 2.1 Signals carregando objetos tipados — NÃO `dict` (finding Felix §2)

**ERRADO:**
```python
class DownloadAdapter(QObject):
    finished = Signal(dict)   # tipo opaco; UI quebra silenciosamente quando schema muda
```

**CERTO:**
```python
from data_downloader.public_api import DownloadResult

class DownloadAdapter(QObject):
    finished = Signal(object)   # carrega DownloadResult — tipado, IDE-friendly, refatorável
```

**Por quê?**
- `Signal(dict)` aceita qualquer dict — quando Sol muda schema, UI continua compilando e quebra em produção.
- `Signal(object)` carregando uma `@dataclass` (ou `Pydantic`) força a UI a importar o tipo, gera erro de import quando o contrato some, e dá autocomplete no slot.
- Idem para `progress` — usar `Signal(object)` carregando `DownloadProgress` (ver §2.4 sobre `current_contract`).

### 2.2 QueuedConnection é a única conexão cross-thread aceitável

```python
adapter.progress.connect(self._on_progress, Qt.QueuedConnection)
adapter.error.connect(self._on_error, Qt.QueuedConnection)
adapter.finished.connect(self._on_finished, Qt.QueuedConnection)
```

**Nunca** use `Qt.DirectConnection` (default em mesma thread, mas armadilha em cross-thread — chama o slot na thread emissora, violando MainThread-only para widgets).

`Qt.AutoConnection` (default) **resolve para Direct** se emissor e receptor estiverem na mesma thread; em cross-thread funciona como Queued. Em adapters de backend (sempre cross-thread), **declare explicitamente Queued** — defesa contra refator que mova adapter para MainThread por engano.

### 2.3 Padrão Adapter QThread

```python
# ui/adapters/download_adapter.py
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt

class DownloadAdapter(QObject):
    progress = Signal(object)   # DownloadProgress (inclui current_contract)
    error    = Signal(str)      # mensagem humanizada (Uma)
    finished = Signal(object)   # DownloadResult

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.start()
        self._handle = None      # DownloadHandle vindo do public_api (ADR-007a)

    @Slot(str, str, str)
    def start(self, symbol: str, start: str, end: str):
        from data_downloader.public_api import download
        try:
            self._handle = download(symbol, start, end)
            for progress in self._handle.stream():
                self.progress.emit(progress)
            self.finished.emit(self._handle.result())
        except Exception as e:
            self.error.emit(str(e))

    @Slot()
    def cancel(self):
        # Depende de ADR-007a (Aria) — ver §8 abaixo
        if self._handle is not None:
            self._handle.cancel()

    def stop(self):
        self._thread.quit()
        self._thread.wait()
```

Mesmo padrão para `CatalogAdapter`, `MetadataAdapter`, etc. — cada fronteira backend↔UI tem seu adapter.

### 2.4 `current_contract` em `DownloadProgress` (finding M16)

`download_continuous` faz rollover entre contratos no meio da execução (ex.: WDOK26 → WDOX26). Sem `current_contract`, a UI mostra o símbolo inicial mesmo após o rollover — usuário pensa que falhou.

A `DownloadProgress` (definida pela Aria no public_api) DEVE incluir `current_contract: str`. A UI atualiza o label do contrato a cada `progress` recebido:

```python
def _on_progress(self, progress):  # progress: DownloadProgress
    self.contract_label.setText(progress.current_contract)
    self.progress_bar.setValue(int(progress.done / progress.total * 100))
```

---

## 3. High-DPI

```python
# app.py — antes de criar QApplication
from PySide6.QtCore import Qt, QCoreApplication
QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

app = QApplication(sys.argv)
```

**Windows tem 100/125/150/200% DPI.** Ignorar HiDPI = fonte borrada em laptops modernos.

**Assets:**
- Preferir **SVG** sempre que possível (escala perfeita, 1 arquivo).
- Para PNG, fornecer densidades `icon.png`, `icon@2x.png`, `icon@3x.png` em `assets/icons/`.
- Carregar via `QIcon` (que escolhe a densidade certa automaticamente).

---

## 4. Layout — NUNCA `setGeometry`

**Proibido:**
```python
self.button.setGeometry(10, 20, 100, 30)   # quebra em qualquer DPI != 100%
```

**Obrigatório:**
```python
layout = QVBoxLayout(self)
layout.addWidget(self.header)
layout.addWidget(self.progress_bar)
layout.addStretch()
layout.addLayout(self._build_button_row())
```

**Layouts disponíveis:** `QVBoxLayout`, `QHBoxLayout`, `QGridLayout`, `QFormLayout`, `QStackedLayout`. Qualquer combinação cobre 99% dos casos. Se precisar de algo mais avançado, consulte Uma antes (provavelmente o wireframe pode ser ajustado para um layout-padrão).

---

## 5. QSS Theming

**Fonte única:** `src/data_downloader/ui/assets/style.qss`. Carregado uma vez em `app.py`:

```python
from pathlib import Path

qss_path = Path(__file__).parent / 'assets' / 'style.qss'
app.setStyleSheet(qss_path.read_text(encoding='utf-8'))
```

**Regras:**
- **Sem styling inline** em widget (`widget.setStyleSheet(...)` apenas em casos extremos, com comentário justificando).
- Cores, fontes, espaçamentos vêm de `THEME.md` (Uma); QSS é a tradução técnica.
- Ao adicionar uma classe nova, dê-lhe `objectName` para o seletor QSS (`#downloadButton`) ou use property dinâmica (`[role="primary"]`).

---

## 6. Atalhos Qt (referência para THEME.md)

> **Autoridade canônica de atalhos:** `docs/ux/THEME.md` (Uma). Esta seção descreve **como** implementar; **quais** atalhos existem está lá.

### 6.1 Esc — context-aware

`Esc` tem dois comportamentos:
1. Se houver `QDialog` modal aberto → fecha o dialog (comportamento default do Qt — não fazer nada).
2. Se estiver na `DownloadScreen` e houver download ativo → cancela o download.
3. Em qualquer outra tela → não faz nada (não fechar a janela principal).

**Implementação:**

```python
# Apenas na DownloadScreen (escopo restrito)
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtCore import Qt

self._cancel_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
self._cancel_shortcut.setContext(Qt.WidgetWithChildrenShortcut)  # NÃO ApplicationShortcut
self._cancel_shortcut.activated.connect(self._on_cancel_requested)

def _on_cancel_requested(self):
    if not self._download_active:
        return   # no-op se não há download
    self.adapter.cancel()
```

Uso de `Qt.WidgetWithChildrenShortcut` (não `ApplicationShortcut`) garante que o atalho só dispara quando a `DownloadScreen` (ou seus filhos) tem foco — evita cancelar ao apertar Esc em outra tela.

### 6.2 Refresh — Ctrl+R, NÃO F5 (finding M10 / Felix §7)

**Por quê não F5?**
- F5 conflita com debugger no IDE de quem desenvolve (Visual Studio, PyCharm).
- `Ctrl+R` é o padrão de "reload" em Chrome/Firefox/VS Code/Slack — mais reconhecível.

```python
self._refresh_shortcut = QShortcut(QKeySequence('Ctrl+R'), self)
self._refresh_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
self._refresh_shortcut.activated.connect(self._on_refresh)
```

### 6.3 Outros atalhos (canônico em THEME.md)

`Ctrl+D` (download), `Ctrl+B` (browse catálogo), `Ctrl+,` (settings) — implementação idêntica via `QShortcut`. Consulte `THEME.md` para a lista completa e tooltips.

### 6.4 Documentação no help dialog

Toda mudança em atalho exige update simultâneo:
1. THEME.md (Uma aprova).
2. Implementação (`shortcuts.py`).
3. Help dialog (`F1` ou menu Ajuda → "Atalhos").

---

## 7. Async UI — chamando adapter da MainThread

Slots normalmente são invocados via signal connect, mas quando a UI precisa **disparar** algo no adapter (ex.: clique de botão dispara `start()`), use `QMetaObject.invokeMethod` para garantir que o slot rode na thread do adapter:

```python
from PySide6.QtCore import QMetaObject, Qt, Q_ARG

def on_download_clicked(self):
    symbol = self.symbol_picker.value()
    start, end = self.period_picker.range()
    QMetaObject.invokeMethod(
        self.adapter, 'start',
        Qt.QueuedConnection,
        Q_ARG(str, symbol),
        Q_ARG(str, start),
        Q_ARG(str, end),
    )
```

**Alternativa pythonica:** chamar `self.adapter.start(...)` diretamente — se `start` está marcado `@Slot` e a conexão foi feita com `QueuedConnection`, Qt faz o marshalling. Mas `invokeMethod` é mais explícito e à prova de refator (e necessário quando o método não é um Slot puro).

---

## 8. Cancel pattern — depende de ADR-007a (Aria)

A cadeia completa de cancel:

```
User aperta Esc na DownloadScreen
  → QShortcut → DownloadScreen._on_cancel_requested()
  → QMetaObject.invokeMethod(adapter, 'cancel', QueuedConnection)
  → DownloadAdapter.cancel() (executa na thread do adapter)
  → handle.cancel()  ← API estável vinda de ADR-007a
  → orchestrator interrompe chunks pendentes, drena dll_queue,
    commita parcial no Parquet, fecha sessão DLL
  → adapter recebe progress final + finished com status='cancelled'
  → UI atualiza para estado "Cancelado"
```

**Pendência:** ADR-007a (`DownloadHandle` com `cancel()`) precisa estar `accepted` antes de Felix começar Epic 3. Sem ele, `adapter.cancel()` é vapor — UI mente para o usuário ao mostrar "Cancelando...".

Felix coordena com Aria via `*architect-consult`.

---

## 9. Checklist de revisão (auto-aplicar antes de PR)

- [ ] Slot na MainThread mede < 16ms (rodar `*responsiveness-audit`).
- [ ] Toda chamada de backend passa por adapter em `QThread` separada.
- [ ] Conexões cross-thread declaram `Qt.QueuedConnection` explicitamente.
- [ ] Signals carregam objetos tipados (não `dict`).
- [ ] `QFileDialog` usa `DontUseNativeDialog`.
- [ ] Layout via `QVBoxLayout`/`QHBoxLayout`/`QGridLayout` — zero `setGeometry`.
- [ ] Sem `widget.setStyleSheet(...)` inline (a menos que justificado).
- [ ] Atalhos novos consultados com Uma (autoridade THEME.md).
- [ ] HiDPI: assets em SVG ou múltiplas densidades.
- [ ] Help dialog atualizado se atalho mudou.

---

— Felix, construindo superfícies 🖼️
