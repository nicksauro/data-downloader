# ADR-012 — Configuration: env vars (12-factor) + TOML override + Pydantic Settings

**Status:** accepted
**Aceito em:** 2026-05-03 — Aria
**Data:** 2026-05-03
**Autor:** 🏛️ Aria
**Consultados:** 💻 Dex, ⚙️ Gage, 🎨 Uma
**Related:** ADR-008 (DLL distribution), ADR-010 (logging), ADR-011 (exceptions), MANIFEST §R12 + §R15, PLAN_REVIEW context

---

## Contexto

Squad precisa decidir **como o data-downloader carrega configuração**. Opções e demandas concorrentes:

- **Credenciais ProfitDLL** (`NL_USERNAME`, `NL_PASSWORD`, `NL_KEY`) — devem ser secretas; nunca commitadas.
- **Paths de dados** (`data/history/`, `catalog.db`) — convenção, mas overridable.
- **Tunables** (`DLL_QUEUE_MAXSIZE`, `WRITE_QUEUE_MAXSIZE`) — Pyro pode tunar; default no código.
- **DLL bootstrap** (`DATA_DOWNLOADER_DLL_SOURCE`) — env por ADR-008.
- **Logging** (`LOG_LEVEL`, `LOG_CONSOLE`) — env por ADR-010.
- **CLI flags** podem sobrescrever em runtime.
- **Modo dev vs prod** — diferentes defaults.

Demandas:
1. **12-factor compliance** — env vars são o padrão para deploy/container.
2. **Onboarding amigável** — primeira execução deve guiar (Uma): "configure aqui".
3. **Type-safe** — string `"true"` em env precisa virar `bool` validado.
4. **Defaults documentados** — código não pode esconder magia em strings.
5. **Validation early** — config inválida falha em startup, não na 100ª chamada.
6. **Override hierárquico** — CLI > env > TOML > defaults.

---

## Opções Consideradas

### Opção A — Env vars (12-factor) + TOML override + Pydantic Settings

```python
# pyproject.toml: pydantic-settings>=2.0 (autorizada por este ADR)

# src/data_downloader/config.py
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict, TomlConfigSettingsSource

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix='DATA_DOWNLOADER_',
        env_file='.env',
        env_file_encoding='utf-8',
        toml_file='~/.data_downloader/config.toml',
        extra='ignore',
    )

    # --- Credenciais DLL ---
    nl_username: SecretStr
    nl_password: SecretStr
    nl_key: SecretStr

    # --- Paths ---
    data_dir: Path = Field(default=Path.home() / '.data_downloader' / 'data')

    # --- Logging ---
    log_level: str = 'INFO'
    log_console: bool = False

    # --- Tunables (Pyro) ---
    dll_queue_maxsize: int = 10_000
    write_queue_maxsize: int = 5_000
    chunk_timeout_seconds: int = 1800

    # --- DLL bootstrap ---
    dll_source: str | None = None

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                   env_settings, dotenv_settings,
                                   file_secret_settings):
        return (
            init_settings,             # CLI overrides
            env_settings,              # env vars
            dotenv_settings,           # .env file
            TomlConfigSettingsSource(settings_cls),  # ~/.data_downloader/config.toml
            file_secret_settings,
        )
```

### Opção B — Apenas env vars (12-factor estrito)

- Sem TOML, sem `~/.data_downloader/config.toml`.
- Uma nem dispenseria — UI Epic 3 vai escrever `.env` no first-run.

### Opção C — Apenas TOML

- Mais "amigável" mas viola 12-factor (CI passa via env).
- Secrets em arquivo = fácil de commitar acidentalmente.

### Opção D — argparse/typer custom + dict — sem dep nova

- Type validation manual (verboso).
- Sem composability env+file.
- Pydantic Settings já existe e é leve.

---

## Análise

| Critério | A (env+TOML+Pydantic) | B (só env) | C (só TOML) | D (manual) |
|---------|----------------------|------------|-------------|-----------|
| 12-factor | ✅ | ✅ | ❌ | parcial |
| Type-safe | ✅ | manual | manual | manual |
| Validation early | ✅ | manual | manual | manual |
| Override hierárquico | ✅ | n/a | n/a | manual |
| Secrets seguros | ✅ (SecretStr) | OK | risco | OK |
| Onboard friendly (UI Epic 3 escreve config.toml) | ✅ | difícil | ✅ | manual |
| Esforço inicial | médio (1 ADR + dep) | baixo | baixo | médio |
| Dep nova transversal | sim (pydantic) | não | não | não |

**Pontos críticos:**

- **Pydantic já é dep semi-autorizada** — ARCHITECTURE.md§7 marca como "pendente — ADR para uso transversal vs apenas em fronteiras". Este ADR autoriza uso transversal (também usado em ADR-007a `DownloadProgress`/`DownloadResult` como dataclasses simples — Pydantic substituiria por mais validação se necessário).
- **`pydantic-settings` é subpacote** — adicionar não infla muito.
- **TOML como override opcional** — combina o melhor de B e C; secrets ficam em env, defaults user-friendly em TOML.

---

## Decisão

**Opção A — Env vars (primário, 12-factor) + `~/.data_downloader/config.toml` (override opcional) + Pydantic Settings (validação).**

### Precedência (alta → baixa)

```
1. CLI flags                      (--log-level=DEBUG)
2. Env vars                       (DATA_DOWNLOADER_LOG_LEVEL=DEBUG)
3. .env file (cwd)                (DATA_DOWNLOADER_LOG_LEVEL=DEBUG)
4. ~/.data_downloader/config.toml ([logging] level = "DEBUG")
5. Defaults no código             (Settings model)
```

Override mais alto vence. Validação Pydantic aplica após merge.

### Estrutura

```python
# src/data_downloader/config.py

from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings, SettingsConfigDict,
    TomlConfigSettingsSource,
    PydanticBaseSettingsSource,
)


class DLLSettings(BaseSettings):
    """ProfitDLL credentials. SecretStr evita log/repr accidental."""
    model_config = SettingsConfigDict(env_prefix='DATA_DOWNLOADER_NL_')

    username: SecretStr
    password: SecretStr
    key: SecretStr
    source_url: str | None = None    # ADR-008 bootstrap
    version: str = Field(default='4.0.0.30', description='Pinned in .dll-version')


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='DATA_DOWNLOADER_STORAGE_')

    data_dir: Path = Field(
        default_factory=lambda: Path.home() / '.data_downloader' / 'data',
    )
    catalog_db_filename: str = 'catalog.db'

    @field_validator('data_dir')
    @classmethod
    def _ensure_absolute(cls, v: Path) -> Path:
        return v.expanduser().resolve()


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='DATA_DOWNLOADER_LOG_')

    level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
    console: bool = False
    file: Path | None = None


class TunableSettings(BaseSettings):
    """Pyro pode override via env. Mudanças aqui = consultar ADR-005."""
    model_config = SettingsConfigDict(env_prefix='DATA_DOWNLOADER_TUNE_')

    dll_queue_maxsize: int = Field(default=10_000, ge=100, le=100_000)
    write_queue_maxsize: int = Field(default=5_000, ge=100, le=100_000)
    ui_progress_queue_maxsize: int = Field(default=100, ge=10, le=1_000)
    chunk_timeout_seconds: int = Field(default=1800, ge=60)
    parquet_compression: Literal['snappy', 'zstd', 'gzip'] = 'snappy'


class Settings(BaseSettings):
    """Root. Importável: `from data_downloader.config import settings`."""
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_nested_delimiter='__',
        toml_file=Path.home() / '.data_downloader' / 'config.toml',
        extra='ignore',
    )

    dll: DLLSettings = Field(default_factory=DLLSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    tunable: TunableSettings = Field(default_factory=TunableSettings)

    debug: bool = False
    profile: Literal['dev', 'prod'] = 'prod'

    @classmethod
    def settings_customise_sources(
        cls, settings_cls,
        init_settings, env_settings, dotenv_settings, file_secret_settings,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


# Instância singleton — importar para uso
settings = Settings()
```

### Exemplo TOML (`~/.data_downloader/config.toml`)

```toml
[storage]
data_dir = "D:/market-data"

[logging]
level = "INFO"
console = false

[tunable]
parquet_compression = "zstd"
dll_queue_maxsize = 20000
```

### Exemplo `.env` (root do projeto, gitignored)

```bash
DATA_DOWNLOADER_NL_USERNAME=user@example.com
DATA_DOWNLOADER_NL_PASSWORD=hunter2
DATA_DOWNLOADER_NL_KEY=ABCD-EFGH-IJKL-MNOP
DATA_DOWNLOADER_LOG_LEVEL=DEBUG
DATA_DOWNLOADER_LOG_CONSOLE=1
DATA_DOWNLOADER_DLL_SOURCE=https://internal.example.com/profitdll
```

### CLI override

```python
# typer flag
@app.command()
def download(
    symbol: str,
    log_level: str = typer.Option(None, '--log-level'),
    ...
):
    if log_level:
        settings.logging.level = log_level    # runtime override
    ...
```

### First-run UX (Uma)

CLI primeira execução:
```
$ data-downloader download WDOJ26
ERROR: ProfitDLL credentials missing.

Set environment variables OR create config file:

Option 1: Environment
  $env:DATA_DOWNLOADER_NL_USERNAME = "..."
  $env:DATA_DOWNLOADER_NL_PASSWORD = "..."
  $env:DATA_DOWNLOADER_NL_KEY = "..."

Option 2: Config file
  Edit: C:\Users\<you>\.data_downloader\config.toml

Run `data-downloader init` to generate template.
```

`data-downloader init` (Story 1.7b ou Epic 3):
- Cria `~/.data_downloader/config.toml` com template comentado.
- Não escreve credenciais (manda usar env).

### Validação em startup

Toda CLI command e UI startup chama:

```python
from data_downloader.config import settings, Settings

try:
    _ = Settings()      # força revalidação
except ValidationError as e:
    raise ConfigurationError(
        f'Invalid configuration: {e}',
        details={'missing': [str(err['loc']) for err in e.errors()]},
    )
```

`ConfigurationError` (ADR-011) é a tradução pública.

### Secrets nunca em log

`SecretStr` faz `repr()` retornar `'**********'`. Combinado com `redact_credentials` processor de ADR-010, secrets nunca vazam mesmo em traceback.

---

## Consequências

### Positivas
- **12-factor:** containers, CI, deploy todos via env.
- **Type-safe:** Pydantic valida em startup; bug "string em vez de int" pego cedo.
- **Hierárquico:** CLI > env > TOML > defaults — flexível.
- **Secrets seguros:** `SecretStr` + redaction.
- **Onboarding:** TOML user-friendly + `init` command (Uma microcopy).
- **Tunables documentados:** Pyro acha em `TunableSettings` com bounds.

### Negativas
- **Dep nova transversal:** `pydantic` + `pydantic-settings`. **Autorizada via este ADR** (R15 satisfeito).
- **2 places para checar:** dev precisa lembrar env > TOML. Mitigação: `data-downloader config show` lista config efetiva e fonte (Story 0.3 ou 1.7b).
- **TOML support precisa Python 3.11+** (`tomllib`) — OK, ADR-001 já fixou 3.12.

### Neutras
- TOML opcional — em CI, só env.
- Defaults no código são auto-documentação.

---

## Validações requeridas

- [ ] Aria valida lista de campos em `Settings` (Story 1.1)
- [ ] Quinn property test: env > TOML > default precedence (Story 1.7b)
- [ ] Quinn test: SecretStr nunca aparece em `repr(settings)` ou logs (Story 1.7b)
- [ ] Uma valida microcopy de erros de config + `init` command (Story 0.3)
- [ ] Gage adiciona `pydantic` + `pydantic-settings` ao `pyproject.toml` + `requirements.lock` (Story 0.1)
- [ ] Documentação em `docs/dev/CONFIG.md` (Dex)
- [ ] CLI: `data-downloader config show` exibe origem de cada valor (Story 1.7b)
