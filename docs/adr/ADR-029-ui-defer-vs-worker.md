# ADR-029 — UI Threading Pattern: Defer-vs-Worker (R11 enforcement)

**Status:** proposed
**Data:** 2026-05-17
**Autor:** Aria (architect)
**Consultados:** Uma (UX), Felix (frontend-dev), Pyro (perf)
**Supersedes:** —
**Related:** ADR-005 (thread model — backend), ADR-003 (PySide6), PRINCIPLES.md §3 (P3/R11),
docs/ux/QT_PATTERNS.md (UI cookbook), Story 4.27 (UI MainThread enforcement)

---

## Contexto

A revisão consolidada da Frente 4 (v1.4.0, 2026-05-16) identificou 4 violações
P0 de R11 ("MainThread Qt < 16ms"). O P0-U1 (`installEventFilter` faltando)
já foi resolvido em Story 4.31 AC3. Os 3 restantes (P0-U2/U3/U4) compartilham
o mesmo anti-padrão arquitetural: **I/O síncrono dentro de `__init__` ou de
slots que correm no MainThread**.

### Casos detectados

| ID    | Local                                                                                   | Operação MainThread                                  | Custo medido / esperado |
|-------|------------------------------------------------------------------------------------------|------------------------------------------------------|--------------------------|
| U2    | `download_screen.py:222-223, 528-534` (`DownloadScreen.__init__` → `_check_for_interrupted_download`) | `Catalog(...)` open + `list_jobs` + `resume_job`     | 5-200 ms (catalog grande) |
| U3    | `settings_screen.py:858, 895-902` (`SettingsScreen.__init__` → `_refresh_storage_status`)              | `shutil.disk_usage` + `sqlite3.connect` + `COUNT(*)` | 5-300 ms (boot path)      |
| U4    | `storage_indicator.py:156` (`_parquets_used_gb` chamado em timer 30s + `partition_registered`)         | `data_dir.rglob("*.parquet")` + `stat` por arquivo   | 500 ms - 2 s (50k+ files) |

O squad já possui dois padrões em uso, hoje aplicados sem critério explícito:

- **Padrão A — Defer (`QTimer.singleShot(0, slot)`):** adia a chamada para a
  próxima iteração do event loop. A operação **continua rodando no MainThread**,
  mas só após o widget ter sido pintado uma vez. Resolve apenas "freeze
  durante `__init__`" — não cria thread, não escala se a operação cresce.
- **Padrão B — Worker (QObject + QThread + signals via `QueuedConnection`):**
  empurra a operação para fora do MainThread inteiramente. Exemplos
  existentes: `CatalogAdapter`, `DownloadAdapter`, `MetricsAdapter`,
  `_TestConnectionWorker`/`_IntegrityWorker`/`_ReconcileWorker` em
  `settings_screen.py`. R11 cumprido de forma robusta independente do
  custo real da operação.

Sem critério explícito, futuras telas escolherão arbitrariamente — e o
custo das operações cresce com o uso real (catalog grande, data_dir 7 anos).
Defer hoje pode virar freeze amanhã.

### Restrições

- **R11 (inegociável):** MainThread Qt < 16 ms por slot/init.
- **R3/ADR-005:** UI nunca chama DLL diretamente — fronteira é `dll/session`.
- **Determinismo:** o padrão escolhido tem que ser auditável (Quinn precisa
  rodar `responsiveness-audit` e enumerar threads).
- **Sem regressão de UX:** banners/labels que hoje aparecem no `__init__`
  precisam continuar aparecendo (apenas posso atrasar 1 frame).

---

## Opções consideradas

### Opção A — Defer (`QTimer.singleShot(0, slot)`) em todos os casos

Adia a operação para depois do primeiro paint. Mantém código simples
(uma linha trocada).

- **Prós:** sem nova thread, sem signals, sem teardown extra; ideal para
  operações garantidamente baratas (~1 ms).
- **Contras:** a operação **continua rodando no MainThread**. Se o custo
  for >16 ms o usuário verá freeze 1 frame depois — mesmo bug, momento
  diferente. Não escala com o crescimento natural do dado (catalog grande,
  data_dir 50k+ parquets).
- **Veredito:** insuficiente para U2/U3/U4 — o custo real já está acima
  do orçamento R11 hoje (300 ms - 2 s).

### Opção B — Worker QObject+QThread em todos os casos

Cria um worker dedicado por operação, com signals `Qt.QueuedConnection`.

- **Prós:** R11 cumprido categoricamente (operação NUNCA toca MainThread);
  escala com o dado; padrão já consolidado no projeto (4 adapters vivem).
- **Contras:** boilerplate (QObject + thread + lifecycle + connect_to);
  teardown precisa rodar no `closeEvent` (já há padrão); um worker novo
  é ~80 linhas Python.
- **Veredito:** correto, mas pesado para operações sabidamente <1 ms.

### Opção C — Híbrido com regra de decisão (escolhida)

Defer para operações **provadamente baratas e bounded** (puramente
CPU/memória, sem I/O); Worker para qualquer operação que toque I/O
(disco, rede, SQLite) ou cujo custo cresce com o uso (catalog,
filesystem scan).

- **Prós:** balanceia custo de manutenção (sem boilerplate desnecessário)
  com correção (R11 categórica em I/O); decisão é determinística (tabela
  de critérios), audita-se via grep.
- **Contras:** exige discriminador claro — definido abaixo.

### Opção D — `QtConcurrent.run` / `QThreadPool`

Pool reutilizável. Reduz boilerplate.

- **Prós:** menos código que worker dedicado.
- **Contras:** PySide6 6.x tem suporte limitado a `QtConcurrent`;
  signals do `QRunnable` exigem ponte custom (`QObject` auxiliar);
  pool de threads não dá identidade nomeada (Quinn não consegue auditar
  via `threading.enumerate()`); thread-affinity de timers e callbacks
  vira armadilha sutil (Wave 2B catalog_adapter L143-149 documenta o
  caso). **Rejeitada** — ganho marginal, risco real.

---

## Decisão

**Opção C — Híbrido com regra de decisão determinística.**

### Regra de decisão (auditável)

| Critério                                                                            | Veredito        |
|--------------------------------------------------------------------------------------|------------------|
| Operação toca disco (`open`, `read`, `stat`, `rglob`)?                              | **Worker**       |
| Operação toca SQLite (`sqlite3.connect`, `Catalog(...)`, `cursor.execute`)?         | **Worker**       |
| Operação toca DLL (ctypes call)?                                                    | **Worker**       |
| Operação faz `subprocess.run` / chamada a `shutil` que sai do volume corrente?      | **Worker**       |
| Operação é I/O de rede (HTTP, gRPC, socket)?                                        | **Worker**       |
| Custo cresce com tamanho do dado do usuário (catalog, filesystem, log)?             | **Worker**       |
| Operação é puramente em memória, custo bounded (<1 ms para input válido)?           | **Defer** OK     |
| Operação é apenas update de propriedade Qt (setText, setVisible, setStyleSheet)?    | **Inline** OK    |

**Tie-breaker:** em dúvida, escolher **Worker**. R11 é inegociável; o custo
de marcar "muitos workers" é apenas verbosidade — o custo de marcar "1
defer onde devia ser worker" é freeze percebido pelo usuário.

### Padrão Defer (referência)

```python
class FooScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # ... construção UI inline (set widgets, layouts) ...
        # Operação leve, mas que requer paint antes (ex.: ler atributo
        # de widget que só vira válido pós-show):
        QTimer.singleShot(0, self._post_init_setup)

    @Slot()
    def _post_init_setup(self) -> None:
        # bounded, em memória — OK no MainThread após 1 frame
        ...
```

**NUNCA usar Defer para I/O.** Defer só atrasa o problema: se a operação
custa 300 ms, o usuário vê 1 frame de UI vazia e depois 300 ms de freeze —
pior que freeze no init (que ao menos é durante splash). Defer existe para
"preciso do widget já pintado para ler size/geometry", não para "esconder
I/O caro".

### Padrão Worker (referência)

Worker mínimo (QObject + thread + sinal único de saída). Modelo canônico
existente: `_TestConnectionWorker` (`settings_screen.py:190-254`).

```python
class _FooWorker(QObject):
    """Worker que executa <operação custosa> em QThread separada.

    Caller cria, move para thread, conecta finished, dá start().
    """
    finished = Signal(object, str)  # result_payload, error_msg

    def __init__(self, *args) -> None:
        super().__init__()  # NUNCA passar parent — moveToThread requirement
        self._args = args

    @Slot()
    def run(self) -> None:
        try:
            result = _heavy_operation(*self._args)
            self.finished.emit(result, "")
        except Exception as exc:
            self.finished.emit(None, f"{type(exc).__name__}: {exc}")


# Caller:
class FooScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # ... UI inline ...
        # Defer kick-off do worker para depois do paint inicial (UX:
        # widget aparece imediatamente, dados chegam logo depois).
        QTimer.singleShot(0, self._kick_off_load)

    def _kick_off_load(self) -> None:
        self._thread = QThread(self)
        self._thread.setObjectName("foo-load")
        self._worker = _FooWorker(...)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(
            self._on_load_finished, Qt.ConnectionType.QueuedConnection
        )
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(object, str)
    def _on_load_finished(self, result: object, error_msg: str) -> None:
        # MainThread — seguro tocar UI aqui
        ...
```

### Reuso vs Worker dedicado

- **Reusar `CatalogAdapter` existente** quando a operação é uma query do
  catalog que já está modelada como slot do adapter (`list_partitions`,
  `delete_partition`, etc.). Ganho: 0 boilerplate, 1 thread a menos por
  screen.
- **Criar Worker dedicado** quando a operação não pertence ao adapter
  (ex.: scan de filesystem para `StorageIndicator`, que é statusbar e não
  tem dono natural no `CatalogAdapter`).

### Cardinalidade de threads

R11 + R3 não impõem limite explícito, mas o squad mantém disciplina:

- 1 thread por **conceito de dado** (catalog, download, métricas, DLL session, storage usage).
- Workers **one-shot** (test connection, integrity, reconcile) criam thread
  curta, descartada no `finished`.
- Em qualquer momento de runtime, `threading.enumerate()` deve listar no
  máximo ~10 threads Python nomeadas (excluindo `ConnectorThread` da DLL).
  Inflação além disso requer review de @architect.

---

## Aplicação à Frente 4 (Story 4.27)

| Caso | Padrão escolhido                                  | Justificativa                                                                                                        |
|------|---------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| U2   | **Worker — reusar `CatalogAdapter`**              | `list_jobs` + `resume_job` são queries do catalog → pertencem ao adapter. Adicionar slot `check_interrupted_jobs(data_dir)` + signal `interrupted_job_found(JobInfo | None)`. Zero boilerplate novo. |
| U3   | **Worker dedicado `_StorageStatusWorker`**        | `_refresh_storage_status` toca `shutil.disk_usage` + SQLite `COUNT(*)`. Já existe convenção workers em `settings_screen.py` (`_TestConnectionWorker`/`_IntegrityWorker`/`_ReconcileWorker`); este é o 4º — encaixa naturalmente. |
| U4   | **Worker dedicado `StorageIndicatorWorker`** + estratégia mais barata | `rglob` em 50k+ arquivos custa segundos. **Solução 1 (curto prazo):** worker em QThread, refresh assíncrono, UI consome último valor cached. **Solução 2 (escalável):** trocar `_parquets_used_gb` por `SELECT SUM(file_size_bytes) FROM partitions` — O(1) no SQLite, ordens de magnitude mais barato que `rglob`+stat. Story 4.27 implementa AMBOS: worker (defesa) + query SQLite (otimização). |

### Por que não Defer puro em U2/U3?

- U2: `_check_for_interrupted_download` faz **2 round-trips SQLite** (`list_jobs`
  + `resume_job`) numa DB que pode ter centenas de jobs. Defer atrasa 1 frame
  mas continua bloqueando 100-200 ms no MainThread.
- U3: `_refresh_storage_status` é chamado também via `_load_initial_values`
  no `__init__`. Cresce com tamanho do catalog. Defer não escala.

### Por que NÃO migrar tudo para QThreadPool

- Threads nomeadas (`setObjectName`) são auditáveis por Quinn — pool oculta
  identidade.
- Lifecycle determinístico (`shutdown()` + `wait(2000)` no closeEvent) é
  trivial com QObject+QThread; com pool, exige tracking manual de
  `QRunnable` ainda em voo.
- Adapter padrão já consolidado — pool seria inconsistência.

---

## Consequências

### Positivas

- R11 cumprido categoricamente para U2/U3/U4 (operações nunca tocam
  MainThread).
- Padrão auditável — Quinn pode validar via responsiveness-audit + grep
  `sqlite3.connect|rglob|Catalog\(` em `ui/screens/`.
- Solução para U4 (query SQLite ao invés de rglob) reduz custo de ~2 s para
  <10 ms em data_dirs grandes — ganho independente de threading.
- Padrão Worker existente é reaproveitado — 0 ruído arquitetural.

### Negativas

- 1 worker novo (`_StorageStatusWorker` em settings_screen) + 1 worker novo
  (`StorageIndicatorWorker`) + 1 slot adicional no `CatalogAdapter`. ~150
  linhas líquidas de código adicional.
- Banner de "Retomar download interrompido" (U2) aparece com latência de
  ~50-150 ms depois do paint — UX trade-off explícito. Mitigação: skeleton
  do banner hidden até worker responder (já é o comportamento atual).

### Neutras

- Padrão Defer continua existindo para casos legítimos (ex.: `QTimer.singleShot(0,
  self._post_init_focus)` quando precisa de widget visível para `setFocus()`).
- A regra "em dúvida, Worker" pode levar a workers ocasionalmente
  redundantes (~1 ms operações). Custo aceitável: verbosidade > freeze.

---

## Invariantes derivadas

- **INV-UI-1:** Nenhum `__init__` ou slot que rode no MainThread Qt pode
  chamar `sqlite3.connect`, `Catalog(...)`, `rglob`, `read_text`,
  `write_text`, `shutil.disk_usage` síncronos. Operações com I/O vão para
  worker (QObject + QThread + signal Queued).
- **INV-UI-2:** Adapter (QObject em QThread) NUNCA recebe parent Qt no
  `__init__` (`super().__init__(None)`) — moveToThread requirement.
- **INV-UI-3:** Signals cross-thread DEVEM declarar
  `Qt.ConnectionType.QueuedConnection` explícito — auto-detect do PySide6
  6.11+ tem race silenciosa em alguns hosts (já documentado em
  metrics_panel.py:L389-397).

---

## Validações requeridas

- [ ] Quinn — `responsiveness-audit` por screen: `DownloadScreen.__init__`,
  `SettingsScreen.__init__`, `StorageIndicator.refresh` cada um <16 ms em
  100% das amostras (50 iterações).
- [ ] Quinn — grep no path `ui/screens/` e `ui/widgets/` por padrões
  proibidos (`sqlite3\.connect`, `rglob\(`, `Catalog\(`) fora de bodies de
  Worker QObject.
- [ ] Felix — smoke real: abrir UI com catalog 10k jobs + data_dir 50k
  parquets, medir TTFI (time to first interaction). Alvo: <500 ms total.
- [ ] Pyro — confirmar que `SELECT SUM(file_size_bytes) FROM partitions` é
  O(1) ou O(log N) com `idx_partitions_job` (provavelmente full scan da
  tabela; partitions tem N=número de meses × símbolos, tipicamente <1000).

---

## Sign-off

- **Aria (architect):** APPROVED como **proposed** — sujeito a validação
  via Story 4.27 (smoke + responsiveness-audit). Após PASS, transição
  para `accepted`.
- **Uma (UX), Felix (frontend-dev), Pyro (perf):** revisão pendente
  durante implementação de Story 4.27.
