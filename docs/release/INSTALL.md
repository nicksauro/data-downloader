# INSTALL.md — Guia de instalação do Data Downloader

**Versão deste guia:** V1.0 (Story 4.4)
**Público alvo:** Usuários finais do Data Downloader — squad interno + early
adopters do projeto Backtest Engine.
**Owner:** Gage (devops) — mantém este documento alinhado com cada release V1.x.

---

## 1. O que você vai instalar

O Data Downloader é uma **aplicação desktop Windows** que baixa histórico
de ativos B3 (futuros, ações, opções) via ProfitDLL (Nelogica) e armazena em
formato Parquet local. A V1.0 expõe:

- **CLI** (`data_downloader.exe download ...`) — uso scriptado.
- **UI desktop** (`data_downloader.exe`) — interface gráfica para uso humano.
- **Public API Python** (`from data_downloader.public_api import download`) —
  consumo programático em projetos Python.

A V1.0 é distribuída como **pasta zipada** (não há instalador `.msi` ainda —
ver [Limitações V1.0](#7-limitações-v10)).

---

## 2. Pré-requisitos

### 2.1 Sistema operacional

| Item | Requisito |
|------|-----------|
| OS | Windows 10 (build 19045+) ou Windows 11 |
| Arquitetura | x64 (64 bits) |
| RAM | 4 GB mínimo, 8 GB recomendado |
| Disco | 200 MB para o app + espaço para dados (típico: 5-50 GB para histórico) |
| Conexão | Internet estável (para conectar ao servidor Nelogica) |

> **macOS/Linux não suportados na V1.0** — ProfitDLL é uma DLL nativa Windows.

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
- `pip install data-downloader` (quando publicado em PyPI — V1.1+) ou
  instalação local via `pip install -e .` no clone do repo.

---

## 3. Download e verificação

### 3.1 Onde baixar

A release oficial está em **GitHub Releases**:

```
https://github.com/synkra-aiox/data-downloader/releases/latest
```

Baixe os dois arquivos:

| Arquivo | Descrição |
|---------|-----------|
| `data-downloader-v1.0.0-win64.zip` | App completo (~80-150 MB) |
| `build-manifest-v1.0.0.json` | Audit trail com SHA256 de cada arquivo |

### 3.2 Verificar SHA256 (recomendado)

Antes de extrair o zip, confirme que o arquivo não foi adulterado:

**PowerShell:**

```powershell
Get-FileHash -Algorithm SHA256 .\data-downloader-v1.0.0-win64.zip
```

Compare o `Hash` impresso com o campo `zip.sha256` do
`build-manifest-v1.0.0.json` (também aparece nas notas da Release).
Devem ser **idênticos**. Se diferirem: re-baixe ou abra issue.

### 3.3 Por que não há instalador `.msi` na V1.0

V1.0 distribui via **zip + extração manual** porque:

1. Sem cert EV (code signing) ainda — instalador `.msi` não-assinado tem
   UX pior que zip (warning duplo).
2. Reduz superfície de complexidade enquanto squad+adopters validam a
   release.

V1.1+ introduz instalador `.msi` assinado — ver
[`docs/adr/ADR-016-code-signing.md`](../adr/ADR-016-code-signing.md).

---

## 4. Instalação passo-a-passo

### 4.1 Extrair o zip

1. Crie a pasta de destino, ex.: `C:\Apps\data-downloader\`.
2. Botão direito no `data-downloader-v1.0.0-win64.zip` → **Extrair tudo...**
   → escolha a pasta criada.
3. O conteúdo extraído inclui uma subpasta `data_downloader/` — todo o
   conteúdo (`.exe` + DLLs + `_internal/` + assets) deve ficar **junto**.

> **Não separe** o `.exe` das DLLs/companions. ProfitDLL espera os arquivos
> `.dat` e as pastas `MarketHours2/`, `database/` etc. lado a lado com a DLL.

### 4.2 Configurar credenciais ProfitDLL

O Data Downloader lê credenciais Nelogica de **variáveis de ambiente** (ou de
um arquivo `.env` na pasta de instalação).

Crie um arquivo `.env` na pasta `data_downloader/` com 3 chaves
(substitua os placeholders pelos seus valores reais):

| Chave              | Valor                                |
|--------------------|--------------------------------------|
| `PROFITDLL` `_KEY` | sua chave de licenca ProfitDLL       |
| `PROFIT_USER`      | seu usuario do ProfitChart           |
| `PROFIT_PASS`      | sua senha do ProfitChart             |

Cada linha do arquivo segue a forma `CHAVE` igual `valor`, sem aspas.
Exemplo de template canônico em `.env.example` (incluído no zip).

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
   - A pasta de instalação (ex.: `C:\Apps\data-downloader\data_downloader\`).
   - A pasta de dados onde o histórico será armazenado
     (ex.: `C:\Users\<seu-user>\Documents\data-downloader\data\`).

Detalhes adicionais (Avast, Norton, etc.):
[`build/WINDOWS_DEFENDER_NOTES.md`](../../build/WINDOWS_DEFENDER_NOTES.md).

### 4.4 Primeira execução

1. Dê duplo clique em `data_downloader.exe` (ou execute via terminal:
   `data_downloader.exe --help`).
2. **SmartScreen warning**: ver [§5](#5-smartscreen-workaround-v10).
3. Após passar o SmartScreen, a tela inicial abre. Vá em
   **Configurações** → **ProfitDLL** → clique em **TESTAR CONEXÃO**.
4. Status esperado: `✓ Conectado (versão X.Y.Z)`.

### 4.5 Smoke download

Para validar que tudo funciona:

```powershell
.\data_downloader.exe download `
    --symbol WDOJ26 `
    --start 2026-04-15 `
    --end 2026-04-15
```

Resultado esperado: 1 partição Parquet criada em
`<data-dir>/history/<symbol>/<date>.parquet`. Tempo: ~30-90s para 1 dia
de minidolar.

---

## 5. SmartScreen workaround (V1.0)

### 5.1 O que você vai ver

Na **primeira vez** que o Windows abre o `data_downloader.exe`, aparece:

> **O Windows protegeu seu computador**
> O Microsoft Defender SmartScreen impediu o início de um aplicativo
> não reconhecido. Executar este aplicativo pode colocar seu computador
> em risco.

### 5.2 Por que aparece

O `.exe` da V1.0 **não é assinado** com certificado de organização
reconhecida. Code signing com EV cert (~$300/ano) está agendado para
V1.1 (ver [`docs/adr/ADR-016-code-signing.md`](../adr/ADR-016-code-signing.md)).

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

## 6. Auto-updater (V1.0 — manual)

A V1.0 inclui **notificação de updates**, não auto-aplicação:

1. **Configurações** → seção **Atualizações** → **Verificar atualizações**.
2. Se houver versão mais nova, o app mostra:
   - Versão atual (ex.: `v1.0.0`).
   - Versão disponível (ex.: `v1.0.1`).
   - Link para a release page.
3. **Para atualizar**: baixe o novo zip da release page, extraia em uma
   pasta nova (ou substitua a pasta antiga após fechar o app), reabra.
4. Suas configurações em `~/.data_downloader/config.toml` e seus dados em
   `<data-dir>/` são preservados (ficam fora da pasta de instalação).

A V1.1 introduz **auto-update com TUF** (verificação criptográfica de
integridade + apply automático com restart) — ver
[`docs/adr/ADR-017-auto-updater.md`](../adr/ADR-017-auto-updater.md).

### 6.1 Opt-out (V1.1+)

A check para updates é manual na V1.0 (você sempre clica). Em V1.1, será
periódico (uma vez por dia) com opção de opt-out em
**Configurações → Atualizações → ☑ Verificar automaticamente**.

---

## 7. Limitações V1.0

| Limitação | Razão | Resolvido em |
|-----------|-------|--------------|
| Sem code signing (SmartScreen warning) | EV cert não adquirido | V1.1 (ADR-016) |
| Sem instalador `.msi` | Depende de signing | V1.1 |
| Auto-update manual | TUF setup requer key ceremony | V1.1 (ADR-017) |
| Apenas Windows x64 | ProfitDLL é DLL nativa Windows | macOS/Linux: nunca |
| Distribuição via zip | UX simplificada para audiência inicial | V1.1 |

---

## 8. Troubleshooting

### 8.1 "Could not load Qt platform plugin 'windows'"

Causa: pasta `_internal/PySide6/plugins/platforms/qwindows.dll` faltando ou
foi quarentenada pelo Defender.

Solução: re-extrair zip (verifique se Defender bloqueou algum arquivo —
a pasta deve ter ~80-150 MB total).

### 8.2 "DLL load failed" / "ProfitDLL not found"

Causa: `ProfitDLL.dll` ou um companion (`libssl-1_1-x64.dll`,
`timezone2.dat`, etc.) ausente.

Solução: confirme que **todos** os arquivos do zip estão na pasta de
instalação. Não copie só o `.exe` — DLLs e `.dat` precisam estar lado a lado.

### 8.3 "NL_NOT_LOGGED" / "NL_NO_LICENSE"

Causa: credenciais Nelogica inválidas ou licença DLL não autorizada.

Solução:

1. Confirme `PROFIT_USER` + `PROFIT_PASS` entrando no ProfitChart manualmente.
2. Confirme `PROFITDLL_KEY` com a Nelogica (ela pode estar expirada ou
   não habilitada para sua máquina).

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
https://github.com/synkra-aiox/data-downloader/issues
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
| V1.0.0 | Esta release | Public API estável, packaging --onedir, updater notify-only |
| V1.1.0 | TBD (3-4 semanas) | Code signing EV cert, auto-updater tufup full, instalador .msi |
| V1.2.0 | TBD | Container Docker Windows para build determinístico bit-exato |

---

## 10. Referências

- [`docs/public_api/USAGE.md`](../public_api/USAGE.md) — uso programático
- [`docs/release/RELEASES.md`](RELEASES.md) — histórico de releases
- [`build/BUILD_PROTOCOL.md`](../../build/BUILD_PROTOCOL.md) — como
  reproduzir o build localmente (audiência avançada)
- [`build/WINDOWS_DEFENDER_NOTES.md`](../../build/WINDOWS_DEFENDER_NOTES.md)
  — detalhes Defender + outros AVs
- [`CHANGELOG.md`](../../CHANGELOG.md) — changelog da Public API

---

— ⚙️ Gage (DevOps) mantém este guia. Dúvidas / sugestões: PR em
`docs/release/INSTALL.md`.
