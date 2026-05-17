# INSTALL.md — Guia de instalação do Data Downloader

**Versão deste guia:** v1.1.0 (Wave 3 — Pax)
**Público alvo:** Usuários finais do Data Downloader — squad interno + early
adopters do projeto Backtest Engine.
**Owner:** Gage (devops) — mantém este documento alinhado com cada release v1.x.

> **v1.1.0 (single solid release)** consolida 8 hotfixes v1.0.0 → v1.0.7 em
> um único bundle estável. Distribuição agora via **Setup.exe** (InnoSetup) +
> portable `.zip` opcional. Bundle medido em **387.5MB** uncompressed (era
> 886MB na linha v1.0.x — drop de Qt6WebEngineCore + lean spec PySide6, Pyro).
> Zip distribuível `data-downloader-v1.1.0-win64.zip` ~157.6MB compactado.

---

## 1. O que você vai instalar

O Data Downloader é uma **aplicação desktop Windows** que baixa histórico
de ativos B3 (futuros, ações, opções) via ProfitDLL (Nelogica) e armazena em
formato Parquet local. A v1.1.0 expõe:

- **CLI** (`data_downloader-cli.exe download ...`) — uso scriptado, com nova
  flag `--healthcheck` (NEW v1.1.0) para self-test imports + structlog.
- **UI desktop** (`data_downloader.exe`) — interface gráfica para uso humano.
- **Public API Python** (`from data_downloader.public_api import download`) —
  consumo programático em projetos Python.

A v1.1.0 é distribuída como **`Setup.exe`** (InnoSetup) + portable `.zip`
opcional para usuários que preferem extrair manualmente. Code signing
(EV cert) ainda **não aplicado** — ver
[Limitações v1.1.0](#7-limitações-v110).

---

## 2. Pré-requisitos

### 2.1 Sistema operacional

| Item | Requisito |
|------|-----------|
| OS | Windows 10 (build 19045+) ou Windows 11 |
| Arquitetura | x64 (64 bits) |
| RAM | 4 GB mínimo, 8 GB recomendado |
| Disco | **~450 MB** para o app instalado (bundle 387.5MB uncompressed + InnoSetup overhead) + espaço para dados (típico: 5-50 GB para histórico) |
| Conexão | Internet estável (para conectar ao servidor Nelogica) |

> **macOS/Linux não suportados na v1.1.0** — ProfitDLL é uma DLL nativa Windows.

### 2.2 ProfitDLL (Nelogica)

O Data Downloader **não inclui** licença Nelogica. Você precisa:

1. **Conta Nelogica ProfitChart** ativa (Pro ou Ultra) — credenciais
   `usuario` + `senha` que você usa para entrar no ProfitChart.
2. **Chave de licença ProfitDLL** — solicitar à Nelogica via suporte
   (`suporte@nelogica.com.br`) informando que vai usar ProfitDLL para
   automações. Geralmente liberado em 1-2 dias úteis para contas Pro+.

A `ProfitDLL.dll` em si **vem incluída no zip** desta release (pasta
`profitdll/DLLs/Win64/`) — você não precisa baixar separadamente.

### 2.3 Python (apenas se usar como biblioteca)

Para uso como CLI ou UI: **não precisa instalar Python** — o `.exe` é
self-contained.

Para uso como biblioteca Python (importar `data_downloader.public_api`):

- Python **3.12** ou superior (a build PyInstaller é 3.12.x).
- `pip install data-downloader` (quando publicado em PyPI — v1.2.0+) ou
  instalação local via `pip install -e .` no clone do repo.

### 2.4 Pré-requisitos de runtime — apenas credenciais

> **✅ ProfitChart NÃO precisa estar aberto.** Q-DRIFT-02 (hipótese
> "ProfitChart concorrente é pré-requisito") foi **refutado
> empiricamente em 2026-05-05** via probe direto: `MARKET_CONNECTED`
> em 1.6s sem ProfitChart rodando, com WDOFUT/F + janela ≤5d.

Para rodar `data-downloader` basta:

1. `.env` populado com `PROFITDLL_KEY`, `PROFITDLL_USER`, `PROFITDLL_PASS`
   válidos (chave Nelogica licenciada).
2. ProfitDLL.dll instalada em `profitdll/DLLs/Win64/` (vem no bundle do
   `.exe` ou via `pip install`).
3. Conectividade de rede com servidores Nelogica.

**Sem ProfitChart, sem login concorrente, sem dependência externa.**

**Configurar timeout custom (uso avançado):** se preferir um timeout
maior ou menor (ex.: testes de CI), defina a env var
`DATA_DOWNLOADER_DLL_CONNECT_TIMEOUT` em segundos:

```powershell
$env:DATA_DOWNLOADER_DLL_CONNECT_TIMEOUT = "600"
.\data_downloader.exe download --symbol WDOFUT --start 2026-04-28 --end 2026-05-02
```

**Histórico (Q-DRIFT-02 — refutado):** versões pré-2026-05-05 documentavam
ProfitChart concorrente como pré-requisito devido a 3 falhas de smoke
(`153cf43`, `4412d48`, `8d59254`) onde o handshake travava em
`MARKET_DATA(2,1)` por >5min. Investigação Story 1.7d/g identificou a
causa real: **WDOJ26/WDOK26 (contrato vencido)** + janela 30d. Com
**WDOFUT (continuous future)** + janela ≤5d (Q-DRIFT-31), handshake
completa em 1-2s. Ver `docs/stories/1.7c.story.md` (Deprecated) e
`docs/stories/1.7g.story.md` (Done) para histórico completo.

---

## 3. Download e verificação

### 3.1 Onde baixar

A release oficial está em **GitHub Releases**:

```
https://github.com/nicksauro/data-downloader/releases/latest
```

Baixe os arquivos abaixo (use **Setup.exe** se possível — fluxo
recomendado):

| Arquivo | Descrição |
|---------|-----------|
| `data-downloader-Setup-v1.1.0.exe` | **Instalador InnoSetup** (105.7 MB; SHA256 `774850493E4A0FC80808FED8CFB86EF910C0BDAFD3917E99556AEE7899345DD5`) |
| `data-downloader-v1.1.0-win64.zip` | App portable completo (157.6 MB compactado, ~387.6 MB extraído; SHA256 `D9654208493029BD227D0134D83A26A1052832C9F76C2A16781124F104ED43AF`) — alternativa ao Setup |
| `build-manifest-v1.1.0.json` | Audit trail com SHA256 de cada arquivo do bundle (git_sha=`3a9fd83`, build_timestamp=`2026-05-12T04:26:38Z`) |

### 3.2 Verificar SHA256 (recomendado)

Antes de extrair o zip, confirme que o arquivo não foi adulterado:

**PowerShell:**

```powershell
Get-FileHash -Algorithm SHA256 .\data-downloader-Setup-v1.1.0.exe
Get-FileHash -Algorithm SHA256 .\data-downloader-v1.1.0-win64.zip
```

Compare o `Hash` impresso com o campo `setup.sha256` /
`zip.sha256` do `build-manifest-v1.1.0.json` (também aparece nas notas
da Release). Devem ser **idênticos**. Se diferirem: re-baixe ou abra
issue.

### 3.3 Code signing — pendente v1.2.0

v1.1.0 distribui o `Setup.exe` **não-assinado**: SmartScreen vai
exibir warning na primeira execução (ver §5). Code signing com EV cert
está agendado para v1.2.0 — ver
[`docs/adr/ADR-016-code-signing.md`](../adr/ADR-016-code-signing.md).

---

## 4. Instalação passo-a-passo

### 4.1 Executar o Setup.exe (recomendado)

1. Duplo-clique em `data-downloader-Setup-v1.1.0.exe`.
2. SmartScreen warning aparecerá (não-assinado) — ver [§5](#5-smartscreen-workaround-v110).
3. Wizard InnoSetup pergunta caminho de instalação. Default:
   `%LOCALAPPDATA%\Programs\data-downloader\`
   (recomendado — não exige privilégio admin).
4. Marque **"Criar atalho na Área de trabalho"** se desejar.
5. **Concluir** — o instalador deixa:

   ```
   %LOCALAPPDATA%\Programs\data-downloader\
       data_downloader.exe                     # UI (PySide6)
       data_downloader-cli.exe                 # CLI
       _internal\                              # PyInstaller payload
       profitdll\DLLs\Win64\ProfitDLL.dll      # companion DLL
       profitdll\DLLs\Win64\<companions>       # libssl, timezone2.dat, etc
   ```

> **Não copie** o `.exe` para outra pasta sem trazer junto `_internal/`,
> `profitdll/` e companions — ProfitDLL espera os arquivos `.dat` e as
> pastas `MarketHours2/`, `database/` lado a lado com a DLL.

### 4.1-alt Alternativa portable (zip)

Se preferir não usar o instalador:

1. Crie a pasta de destino, ex.: `C:\Apps\data-downloader\`.
2. Botão direito em `data-downloader-v1.1.0-win64.zip` → **Extrair tudo...**
   → escolha a pasta criada.
3. O conteúdo extraído inclui uma subpasta `data_downloader/` — todo o
   conteúdo (`.exe` + DLLs + `_internal/` + assets) deve ficar **junto**.

### 4.2 Configurar credenciais ProfitDLL

O Data Downloader lê credenciais Nelogica de **variáveis de ambiente**
ou de um arquivo `.env`. Na v1.1.0 o caminho **canônico** do `.env`
de usuário é:

```
%USERPROFILE%\.data-downloader\.env
```

(equivalente a `~/.data-downloader/.env` em PowerShell). Esse caminho
é resolvido por `bundle_paths.user_env_path()` (ADR-018/021) e é
**preservado em upgrades** — fica fora da pasta de instalação.

Crie o arquivo com as chaves canônicas (substitua os placeholders pelos
seus valores reais):

| Chave              | Obrigatória? | Valor                                                    |
|--------------------|--------------|----------------------------------------------------------|
| `PROFITDLL_KEY`    | sim          | sua chave de licença ProfitDLL                           |
| `PROFITDLL_USER`   | sim          | seu usuário do ProfitChart                               |
| `PROFITDLL_PASS`   | sim          | sua senha do ProfitChart                                 |
| `PROFITDLL_PATH`   | opcional     | caminho absoluto p/ `ProfitDLL.dll` (default: ao lado do .exe) |

Cada linha do arquivo segue a forma `CHAVE=valor`, sem aspas.
Exemplo de template canônico em `.env.example` (incluído no zip).

> **Depreciação (v1.0.0+):** versões antes de v1.0.0 usavam
> `PROFIT_USER` e `PROFIT_PASS`. Esses nomes ainda são aceitos com
> warning de depreciação, mas serão removidos em v2.0. **Recomendado
> migrar** para `PROFITDLL_USER` / `PROFITDLL_PASS`.

> **Segurança:** este arquivo contém **secrets** — não compartilhe e não
> commite em git. O Data Downloader não logga esses valores (R12 — secret
> redaction).

Alternativa: setar como variáveis de ambiente Windows
(**Sistema → Variáveis de ambiente**).

### 4.3 Adicionar exclusão Defender (recomendado para performance)

Defender escaneia cada arquivo Parquet à medida que é gravado, o que pode
**dobrar** o tempo de download. Para evitar:

1. **Configurações** → **Privacidade e segurança** → **Segurança do Windows**
   → **Proteção contra vírus e ameaças**.
2. **Gerenciar configurações** → role até **Exclusões** → **Adicionar ou
   remover exclusões**.
3. Adicione **2 pastas**:
   - A pasta de instalação (default v1.1.0:
     `%LOCALAPPDATA%\Programs\data-downloader\`).
   - A pasta de dados onde o histórico será armazenado
     (ex.: `C:\Users\<seu-user>\Documents\data-downloader\data\`).

Detalhes adicionais (Avast, Norton, etc.):
[`build/WINDOWS_DEFENDER_NOTES.md`](../../build/WINDOWS_DEFENDER_NOTES.md).

### 4.4 Healthcheck — primeiro comando após instalar (NEW v1.1.0)

A v1.1.0 adiciona uma flag `--healthcheck` no CLI que valida imports +
structlog probe sem tocar na DLL/credenciais. Rode antes do primeiro
download para confirmar que o bundle está saudável:

```powershell
cd "$env:LOCALAPPDATA\Programs\data-downloader"
.\data_downloader-cli.exe --healthcheck
```

- **Exit 0** → bundle OK, prossiga para 4.5.
- **Exit 1** → mensagem de erro identifica o problema (ex.: companion
  faltante, structlog quebrado). Abra issue com a saída.

### 4.5 Primeira execução da UI

1. Dê duplo clique em `data_downloader.exe` (atalho da Área de trabalho
   ou em `%LOCALAPPDATA%\Programs\data-downloader\`).
2. **SmartScreen warning**: ver [§5](#5-smartscreen-workaround-v110).
3. Após passar o SmartScreen, a tela inicial abre. Se não houver `.env`
   válido, o **onboarding banner** (NEW v1.1.0) exibe CTA "Configurar
   Credenciais" — clique e siga.
4. Em **Configurações → ProfitDLL** → clique em **TESTAR CONEXÃO**.
5. Status esperado: `✓ Conectado (versão X.Y.Z)`.
6. Atalho **Ctrl+/** abre o **Cheat Sheet** (NEW v1.1.0) com a lista
   completa de atalhos de teclado e ações rápidas.

### 4.6 Smoke download

Para validar que tudo funciona:

```powershell
.\data_downloader.exe download `
    --symbol WDOFUT `
    --start 2026-04-28 `
    --end 2026-05-02
```

Resultado esperado: partições Parquet criadas em
`<data-dir>/history/<symbol>/<year>/<month>.parquet`. Tempo: ~30-90s
por dia de minidolar.

> Use **`WDOFUT`** (continuous future) — NÃO contratos específicos
> vencidos como `WDOJ26`/`WDOK26` que retornam 0 trades (Q-DRIFT-32).
> Janela máxima por chamada `GetHistoryTrades`: **5 dias úteis** (Q-DRIFT-31,
> server-side Nelogica). O orchestrator internamente fragmenta a janela em
> **chunks de 1 dia útil** (uniform policy ADR-023, hotfix v1.1.0 2026-05-07)
> para feedback granular na UI.

---

## 5. SmartScreen workaround (v1.1.0)

### 5.1 O que você vai ver

Na **primeira vez** que o Windows abre o `Setup.exe` ou o
`data_downloader.exe`, aparece:

> **O Windows protegeu seu computador**
> O Microsoft Defender SmartScreen impediu o início de um aplicativo
> não reconhecido. Executar este aplicativo pode colocar seu computador
> em risco.

### 5.2 Por que aparece

Os artefatos da v1.1.0 (`Setup.exe` + `.exe`) **não são assinados** com
certificado de organização reconhecida. Code signing com EV cert
(~$300/ano) está agendado para v1.2.0 (ver
[`docs/adr/ADR-016-code-signing.md`](../adr/ADR-016-code-signing.md)).

**Não significa que o app é malicioso** — significa apenas que ainda não
existe assinatura digital. Você pode (e deve) verificar o SHA256 do zip
[§3.2](#32-verificar-sha256-recomendado) para confirmar integridade.

### 5.3 Como executar mesmo assim

1. Na tela do SmartScreen, clique em **Mais informações** (link pequeno
   abaixo do título).
2. Clique no botão **Executar assim mesmo**.
3. O app abre normalmente. SmartScreen **não pergunta de novo** para esta
   versão do `.exe` — só nas releases futuras (cada release nova começa
   com reputação zero).

---

## 6. Auto-updater (v1.1.0 — manual)

A v1.1.0 inclui **notificação de updates**, não auto-aplicação:

1. **Configurações** → seção **Atualizações** → **Verificar atualizações**.
2. Se houver versão mais nova, o app mostra:
   - Versão atual (ex.: `v1.1.0`).
   - Versão disponível.
   - Link para a release page.
3. **Para atualizar**: baixe o novo `Setup.exe` da release page e execute.
   InnoSetup detecta a instalação anterior e faz upgrade in-place.
4. Suas configurações em `~/.data-downloader/.env` e seus dados em
   `<data-dir>/` são preservados (ficam fora da pasta de instalação).

A v1.2.0 introduz **auto-update com TUF** (verificação criptográfica de
integridade + apply automático com restart) — ver
[`docs/adr/ADR-017-auto-updater.md`](../adr/ADR-017-auto-updater.md).

### 6.1 Opt-out (v1.2.0+)

A check para updates é manual na v1.1.0 (você sempre clica). Em v1.2.0,
será periódico (uma vez por dia) com opção de opt-out em
**Configurações → Atualizações → ☑ Verificar automaticamente**.

---

## 7. Limitações v1.1.0

| Limitação | Razão | Resolvido em |
|-----------|-------|--------------|
| Sem code signing (SmartScreen warning) | EV cert não adquirido | v1.2.0 (ADR-016) |
| Auto-update manual | TUF setup requer key ceremony | v1.2.0 (ADR-017) |
| Apenas Windows x64 | ProfitDLL é DLL nativa Windows | macOS/Linux: nunca |
| Broker dead-code 2013 LOC ainda no bundle | Cleanup adiado | v1.2.0 (Dex code-quality #4) |
| Coverage tool incompatibility Python 3.14 | Workaround: pin Python 3.13 OR coverage 7.6 | v1.2.0 (Dex #3) |

---

## 8. Troubleshooting

### 8.0 Healthcheck antes de qualquer outro diagnóstico (NEW v1.1.0)

Sempre rode `data_downloader-cli.exe --healthcheck` primeiro — exit 0
descarta problemas de empacotamento e indica que o erro está em DLL,
credenciais ou conectividade.

### 8.1 "Could not load Qt platform plugin 'windows'"

Causa: pasta `_internal/PySide6/plugins/platforms/qwindows.dll` faltando ou
foi quarentenada pelo Defender.

Solução: re-rodar Setup.exe (ou re-extrair zip se portable). A pasta de
instalação deve ter **~450 MB** na v1.1.0. Verifique se Defender
bloqueou algum arquivo.

### 8.2 "DLL load failed" / "ProfitDLL not found"

Causa: `ProfitDLL.dll` ou um companion (`libssl-1_1-x64.dll`,
`timezone2.dat`, etc.) ausente.

Solução: confirme que **todos** os arquivos do zip estão na pasta de
instalação. Não copie só o `.exe` — DLLs e `.dat` precisam estar lado a lado.

### 8.3 "NL_NOT_LOGGED" / "NL_NO_LICENSE"

Causa: credenciais Nelogica inválidas ou licença DLL não autorizada.

Solução:

1. Confirme `PROFITDLL_USER` + `PROFITDLL_PASS` entrando no ProfitChart manualmente.
2. Confirme `PROFITDLL_KEY` com a Nelogica (ela pode estar expirada ou
   não habilitada para sua máquina).

### 8.3b Licença em uso (MaxHID) — banner "Licença Nelogica em uso"

Causa: o servidor Nelogica recusou o login porque **todos os HIDs**
(computadores/sessões) da licença já estão em uso. O bug Pichau
2026-05-17 expôs este caso — antes do v1.4.0, o app ficava ~990s em
spinner sem mensagem clara; Story 4.29 detecta MaxHID em <3s e mostra
banner dedicado.

Sintoma: ao iniciar download, em ~3s aparece o card vermelho **"Licença
Nelogica em uso"** com 3 remedies + botões "Abrir portal Nelogica" /
"Tentar de novo" + link **"Ver logs"**.

Solução (3 passos prescritos pelo banner — Q-DRIFT-41):

1. **Feche todas as instâncias do data-downloader e do ProfitChart** —
   inclusive em outros computadores. O HID é por máquina/sessão;
   licença Nelogica básica permite poucos HIDs simultâneos.
2. **Acesse o portal Nelogica** (botão "Abrir portal Nelogica" ou
   navegue direto para `https://www.nelogica.com.br/area-cliente`) e
   **desconecte os HIDs ativos** na sua conta.
3. **Aguarde 5–30 minutos** e clique em "Tentar de novo". O servidor
   pode levar alguns minutos para liberar o slot após o disconnect.

Se persistir após 30 min com tudo fechado:

- Clique em **"Ver logs"** (no banner) ou **"Abrir pasta de logs"**
  (em Configurações → ProfitDLL) e anexe o arquivo
  `LogDesktop_YYYY_MM_DD.log` mais recente.
- Abra ticket em **suporte@nelogica.com.br** com assunto "licença
  travada em MaxHID" e a evidência do log (linha
  `TInfoClientProcessor.ProcessLoginResult: ActivationResult=MaxHID`).

### 8.4 Logs

Logs estruturados (JSON) em:

```
%APPDATA%\data_downloader\logs\app.log
```

Para diagnóstico rápido:

```powershell
.\data_downloader.exe doctor
```

Comando `doctor` checa: DLL presente, credenciais setadas, conexão
servidor, espaço em disco, schema do catálogo.

### 8.5 Bug reports

Abrir issue em:

```
https://github.com/nicksauro/data-downloader/issues
```

Inclua:

- Versão do app (`data_downloader.exe --version`).
- SHA256 do zip baixado (para confirmar build).
- Logs sanitizados (`%APPDATA%\data_downloader\logs\app.log`).
- Reprodução mínima.

---

## 9. Próximas releases

| Versão | ETA | Highlights |
|--------|-----|------------|
| v1.1.0 | **Esta release** | Single solid ship (consolida v1.0.0→v1.0.7), bundle 387.5MB, `--healthcheck`, Setup.exe InnoSetup, lean PySide6, ADR-018/021/023/024, Q-DRIFT-37+38 mitigated |
| v1.2.0 | TBD (3-4 semanas) | Code signing EV cert, auto-updater tufup full, broker dead-code cleanup, Python 3.14 coverage |
| v1.3.0 | TBD | Container Docker Windows para build determinístico bit-exato |

---

## 10. Referências

- [`docs/public_api/USAGE.md`](../public_api/USAGE.md) — uso programático
- [`docs/release/RELEASES.md`](RELEASES.md) — histórico de releases
- [`build/BUILD_PROTOCOL.md`](../../build/BUILD_PROTOCOL.md) — como
  reproduzir o build localmente (audiência avançada)
- [`build/WINDOWS_DEFENDER_NOTES.md`](../../build/WINDOWS_DEFENDER_NOTES.md)
  — detalhes Defender + outros AVs
- [`CHANGELOG.md`](../../CHANGELOG.md) — changelog (package + Public API)
- [`docs/release-notes/v1.1.0-draft.md`](../release-notes/v1.1.0-draft.md)
  — release notes para GitHub Release v1.1.0

---

— ⚙️ Gage (DevOps) mantém este guia. Dúvidas / sugestões: PR em
`docs/release/INSTALL.md`.
