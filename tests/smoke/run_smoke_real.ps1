# =====================================================================
# Smoke real v1.1.0 — Pichau Windows local (Wave 2 Quinn).
#
# Master plan v1.1.0 doc: docs/stories/v1.1.0-master-plan.md
#
# Pré-requisitos:
#   1. Bundle frozen presente em dist\data_downloader\ (Pyro Wave 1).
#   2. Credentials válidas em ~/.data-downloader/.env
#      (PROFITDLL_KEY, PROFITDLL_USER, PROFITDLL_PASS).
#   3. PowerShell 5+ (Windows 10 nativo).
#
# Uso:
#   .\tests\smoke\run_smoke_real.ps1
#   .\tests\smoke\run_smoke_real.ps1 -Symbol WDOFUT -Days 5
#   .\tests\smoke\run_smoke_real.ps1 -Symbol WINFUT -Days 3 -BundleDir "dist\data_downloader"
#
# Saída:
#   - SMOKE PASS  → exit 0 + Parquet count + tabela log do download
#   - SMOKE FAIL  → exit 1 + stderr capturado + diagnóstico
#
# Esta NÃO é replacement para pytest — é o smoke pichau-real que
# exercita .exe + DLL real + B3 servers. Roda fora do CI.
# =====================================================================

[CmdletBinding()]
param(
    [string]$Symbol = "WDOFUT",
    [int]$Days = 5,
    [string]$BundleDir = "dist\data_downloader"
)

# NÃO usar "Stop" aqui: este script chama exes nativos (data_downloader-cli.exe)
# que emitem logs/probes em stderr. Em PS 5.1, native-stderr + ErrorActionPreference=Stop
# vira NativeCommandError terminante e aborta o script antes de checarmos $LASTEXITCODE.
# As checagens de exit code abaixo (rc=0?) são explícitas e suficientes.
$ErrorActionPreference = "Continue"

# -------------------------------------------------------------------
# Resolução de paths
# -------------------------------------------------------------------
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$bundlePath = Join-Path $repoRoot $BundleDir
$cli = Join-Path $bundlePath "data_downloader-cli.exe"

# Task #18 (smoke real v1.1.0): passamos --data-dir EXPLÍCITO para um diretório
# de smoke dedicado. Antes, o download usava o default relativo ./data, mas a
# ProfitDLL faz chdir() para _internal/ ao carregar (Q-DRIFT-10) → o parquet
# writer (que roda com cwd já trocado) escrevia DENTRO do bundle frozen
# (dist\...\_internal\data\). O fix no cli.py resolve --data-dir para absoluto
# logo no início (.resolve() captura o cwd original), mas aqui passamos o path
# explícito para o smoke ser determinístico e não poluir o repo root ./data.
$smokeDataDir = Join-Path $repoRoot "data\smoke-real"

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host " Smoke real v1.1.0 — Quinn Wave 2 P0" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "Repo root : $repoRoot"
Write-Host "Bundle    : $bundlePath"
Write-Host "CLI exe   : $cli"
Write-Host "Data dir  : $smokeDataDir"
Write-Host "Symbol    : $Symbol"
Write-Host "Days      : $Days"
Write-Host ""

# -------------------------------------------------------------------
# Pré-checks
# -------------------------------------------------------------------
if (-not (Test-Path $cli)) {
    Write-Host "ERRO: CLI exe ausente em $cli" -ForegroundColor Red
    Write-Host "Rode primeiro: python scripts\build_release.py" -ForegroundColor Yellow
    exit 1
}

# Verifica .env user-global (~/.data-downloader/.env).
$envFile = Join-Path $env:USERPROFILE ".data-downloader\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "AVISO: $envFile ausente." -ForegroundColor Yellow
    Write-Host "Configure credentials antes do smoke real (UI Settings ou edição manual)." -ForegroundColor Yellow
    Write-Host "Continuando — talvez vars estejam no shell..." -ForegroundColor Yellow
}

# -------------------------------------------------------------------
# Step 1: Healthcheck
# -------------------------------------------------------------------
Write-Host "[1/4] Healthcheck..." -ForegroundColor Cyan
# O probe structlog vai para stderr — em PS 5.1 isso aparece em vermelho mas
# (com ErrorActionPreference=Continue) NÃO aborta. rc=0 é o que validamos.
& $cli --healthcheck
if ($LASTEXITCODE -ne 0) {
    Write-Host "SMOKE FAIL: healthcheck retornou $LASTEXITCODE" -ForegroundColor Red
    exit 1
}
Write-Host "      OK" -ForegroundColor Green

# -------------------------------------------------------------------
# Step 2: Janela temporal (últimos N+2 dias calendário, terminando ontem)
# -------------------------------------------------------------------
$end = (Get-Date).Date.AddDays(-1)
$start = $end.AddDays(-($Days + 2))
$startStr = $start.ToString("yyyy-MM-dd")
$endStr = $end.ToString("yyyy-MM-dd")

Write-Host ""
Write-Host "[2/4] Download $Symbol $startStr -> $endStr ..." -ForegroundColor Cyan

# -------------------------------------------------------------------
# Step 3: Download via CLI
# -------------------------------------------------------------------
$downloadStart = Get-Date
# Sintaxe da CLI: símbolo via --symbol (não posicional). --exchange F = BMF (WDO/WIN/IND).
# --data-dir explícito (Task #18): smoke determinístico, não polui repo root ./data.
& $cli download --symbol $Symbol --start $startStr --end $endStr --exchange F --data-dir $smokeDataDir
$downloadRc = $LASTEXITCODE
$downloadDuration = (Get-Date) - $downloadStart

Write-Host ""
Write-Host "      duração: $([math]::Round($downloadDuration.TotalSeconds, 1))s, rc=$downloadRc"

# -------------------------------------------------------------------
# Step 4: Validação de output
# -------------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Validando parquets gerados..." -ForegroundColor Cyan

$dataDir = Join-Path $smokeDataDir "history"
if (-not (Test-Path $dataDir)) {
    Write-Host "AVISO: $dataDir não existe — download pode ter falhado antes do write." -ForegroundColor Yellow
    $parquetFileCount = 0
} else {
    $parquets = Get-ChildItem -Path $dataDir -Recurse -Filter "*.parquet" -ErrorAction SilentlyContinue
    $parquetFileCount = ($parquets | Measure-Object).Count
    Write-Host "      Parquet files: $parquetFileCount (particionados por ano/mês — N dias do mesmo mês = 1 arquivo)"
    if ($parquetFileCount -gt 0) {
        $parquets | Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
            ForEach-Object { Write-Host "        - $($_.FullName)" }
    }
}

# -------------------------------------------------------------------
# G-2 (Quinn round 2 review 2026-05-11; revisto Task #18 2026-05-12) —
# Validação de chunk count via CONTEÚDO dos parquets, não nº de arquivos.
# O schema particiona por ano/mês (history/F/SYM/YYYY/MM.parquet), então
# N dias úteis do mesmo mês viram 1 arquivo. A política ADR-023 (1 chunk =
# 1 dia útil) é validada por: (a) nº de chunk_id distintos = nº de chunks
# emitidos pelo orchestrator; (b) nº de dias-calendário distintos nos
# timestamps. Ambos devem ser >= business_days (com tolerância p/ feriados B3).
# -------------------------------------------------------------------
Write-Host ""
Write-Host "[3b/4] G-2: Validando ADR-023 (1 chunk = 1 dia útil) via conteúdo dos parquets..." -ForegroundColor Cyan

# Conta dias úteis (Mon-Fri) no range. Feriados B3 podem reduzir o real;
# por isso validamos >= (businessDays - tolerância), não exato.
$businessDays = 0
$cursor = $start
while ($cursor -le $end) {
    if ($cursor.DayOfWeek -ne [DayOfWeek]::Saturday -and $cursor.DayOfWeek -ne [DayOfWeek]::Sunday) {
        $businessDays++
    }
    $cursor = $cursor.AddDays(1)
}
$tolerance = [Math]::Max(1, $businessDays - 2)
Write-Host "      Business days esperados (Mon-Fri, sem feriado B3): $businessDays (tolerância feriados: >= $tolerance)"

# Helper python: lê os parquets via duckdb e printa "rows=N chunks=C days=D files=F range=...".
$counterScript = Join-Path $PSScriptRoot "_count_chunks.py"
$counterOut = & python $counterScript $smokeDataDir $Symbol 2>&1 | Out-String
$counterOut = $counterOut.Trim()
Write-Host "      $counterOut"

$rowCount = 0; $chunkIdCount = 0; $distinctDays = 0
if ($counterOut -match 'rows=(\d+)')   { $rowCount = [int]$matches[1] }
if ($counterOut -match 'chunks=(\d+)') { $chunkIdCount = [int]$matches[1] }
if ($counterOut -match 'days=(\d+)')   { $distinctDays = [int]$matches[1] }

$chunkCountOk = ($chunkIdCount -ge $tolerance) -and ($distinctDays -ge $tolerance)
if ($chunkCountOk) {
    Write-Host "      OK (chunk_id distintos=$chunkIdCount, dias distintos=$distinctDays, ambos >= $tolerance)" -ForegroundColor Green
} else {
    Write-Host "      ERRO G-2: chunk_id distintos=$chunkIdCount, dias distintos=$distinctDays — esperado ambos >= $tolerance" -ForegroundColor Red
    Write-Host "        Possível regressão: chunker quebrou política 1d/chunk (ADR-023) OU" -ForegroundColor Red
    Write-Host "        download falhou em múltiplos chunks silenciosamente OU parquet vazio." -ForegroundColor Red
}

# -------------------------------------------------------------------
# Step 5: Catalog contracts list (sanity — confirma que catalog SQLite responde)
# -------------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Catalog contracts list..." -ForegroundColor Cyan
# Nota: `contracts list` não aceita --data-dir (lê o catálogo padrão / seed bundled).
# É só um sanity-check de que a CLI responde; o dado do smoke já foi validado em [3b/4].
& $cli contracts list 2>&1 | Select-Object -First 12

# -------------------------------------------------------------------
# Verdict
# -------------------------------------------------------------------
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
if ($downloadRc -eq 0 -and $rowCount -gt 0 -and $chunkCountOk) {
    Write-Host " SMOKE PASS" -ForegroundColor Green
    Write-Host "   download rc=0, rows=$rowCount, chunks=$chunkIdCount, dias=$distinctDays, business_days=$businessDays, files=$parquetFileCount"
    Write-Host "================================================="
    exit 0
} else {
    Write-Host " SMOKE FAIL" -ForegroundColor Red
    Write-Host "   download rc=$downloadRc, rows=$rowCount, chunks=$chunkIdCount, dias=$distinctDays, business_days=$businessDays, chunkCountOk=$chunkCountOk"
    if ($downloadRc -ne 0) {
        Write-Host "   -> CLI download retornou erro; veja logs acima." -ForegroundColor Red
    }
    if ($rowCount -eq 0) {
        Write-Host "   -> Nenhum trade gravado; possível NL_NO_LICENSE, janela sem trades, ou parquet vazio." -ForegroundColor Red
    }
    if (-not $chunkCountOk) {
        Write-Host "   -> G-2: chunk/dias distintos divergiram do esperado (ADR-023 1d/chunk)." -ForegroundColor Red
    }
    Write-Host "================================================="
    exit 1
}
