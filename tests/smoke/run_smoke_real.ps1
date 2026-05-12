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

$ErrorActionPreference = "Stop"

# -------------------------------------------------------------------
# Resolução de paths
# -------------------------------------------------------------------
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$bundlePath = Join-Path $repoRoot $BundleDir
$cli = Join-Path $bundlePath "data_downloader-cli.exe"

Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host " Smoke real v1.1.0 — Quinn Wave 2 P0" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "Repo root : $repoRoot"
Write-Host "Bundle    : $bundlePath"
Write-Host "CLI exe   : $cli"
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
& $cli download $Symbol --start $startStr --end $endStr --exchange F
$downloadRc = $LASTEXITCODE
$downloadDuration = (Get-Date) - $downloadStart

Write-Host ""
Write-Host "      duração: $([math]::Round($downloadDuration.TotalSeconds, 1))s, rc=$downloadRc"

# -------------------------------------------------------------------
# Step 4: Validação de output
# -------------------------------------------------------------------
Write-Host ""
Write-Host "[3/4] Validando parquets gerados..." -ForegroundColor Cyan

$dataDir = Join-Path $repoRoot "data\history"
if (-not (Test-Path $dataDir)) {
    Write-Host "AVISO: $dataDir não existe — download pode ter falhado antes do write." -ForegroundColor Yellow
    $parquetCount = 0
} else {
    $parquets = Get-ChildItem -Path $dataDir -Recurse -Filter "*.parquet" -ErrorAction SilentlyContinue
    $parquetCount = ($parquets | Measure-Object).Count
    Write-Host "      Parquet files: $parquetCount"
    if ($parquetCount -gt 0) {
        # Lista os 5 mais recentes — útil para diagnóstico.
        $parquets | Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
            ForEach-Object { Write-Host "        - $($_.FullName)" }
    }
}

# -------------------------------------------------------------------
# G-2 (Quinn round 2 review 2026-05-11) — Validação de chunk count
# Conta n de dias úteis (Mon-Fri, ignorando feriados — aproximação:
# usamos só weekday filter; feriados B3 podem subestimar levemente o
# esperado mas isso é safe — valida >= business_days, não exato pois
# pode haver merge de parquets em runs subsequentes).
# Política V1.1.0+ ADR-023: 1 chunk = 1 dia útil, então parquetCount
# deve refletir >= business_days no range [start, end].
# -------------------------------------------------------------------
Write-Host ""
Write-Host "[3b/4] G-2: Validando chunk count (ADR-023 1d/chunk)..." -ForegroundColor Cyan

$businessDays = 0
$cursor = $start
while ($cursor -le $end) {
    if ($cursor.DayOfWeek -ne [DayOfWeek]::Saturday -and $cursor.DayOfWeek -ne [DayOfWeek]::Sunday) {
        $businessDays++
    }
    $cursor = $cursor.AddDays(1)
}
Write-Host "      Business days esperados (Mon-Fri, sem feriado B3): $businessDays"
Write-Host "      Parquets gerados: $parquetCount"

# Valida que pelo menos 1 parquet por dia útil foi emitido. Não exigimos
# exato porque (a) feriados B3 podem reduzir o esperado e (b) runs
# subsequentes podem mergir partições do mesmo dia.
$chunkCountOk = $true
if ($parquetCount -lt $businessDays) {
    # Subtraímos até 2 feriados de tolerância para janelas curtas — se
    # ainda assim diverge, falha.
    $tolerance = [Math]::Max(0, $businessDays - 2)
    if ($parquetCount -lt $tolerance) {
        $chunkCountOk = $false
        Write-Host "      ERRO G-2: parquetCount=$parquetCount < tolerance=$tolerance" -ForegroundColor Red
        Write-Host "        Esperado >= $businessDays parquets (1 chunk/dia útil — ADR-023)" -ForegroundColor Red
        Write-Host "        Possível regressão: chunker quebrou política 1d/chunk OU" -ForegroundColor Red
        Write-Host "        download falhou em múltiplos chunks silenciosamente." -ForegroundColor Red
    } else {
        Write-Host "      OK (tolerância 2 feriados: $parquetCount >= $tolerance)" -ForegroundColor Green
    }
} else {
    Write-Host "      OK ($parquetCount >= $businessDays)" -ForegroundColor Green
}

# -------------------------------------------------------------------
# Step 5: Catalog list (sanity — confirma que catalog SQLite tem entries)
# -------------------------------------------------------------------
Write-Host ""
Write-Host "[4/4] Catalog contracts list..." -ForegroundColor Cyan
& $cli contracts list 2>&1 | Select-Object -First 20

# -------------------------------------------------------------------
# Verdict
# -------------------------------------------------------------------
Write-Host ""
Write-Host "=================================================" -ForegroundColor Cyan
if ($downloadRc -eq 0 -and $parquetCount -gt 0 -and $chunkCountOk) {
    Write-Host " SMOKE PASS" -ForegroundColor Green
    Write-Host "   download rc=0, parquets=$parquetCount, business_days=$businessDays"
    Write-Host "================================================="
    exit 0
} else {
    Write-Host " SMOKE FAIL" -ForegroundColor Red
    Write-Host "   download rc=$downloadRc, parquets=$parquetCount, business_days=$businessDays, chunkCountOk=$chunkCountOk"
    if ($downloadRc -ne 0) {
        Write-Host "   -> CLI download retornou erro; veja logs acima." -ForegroundColor Red
    }
    if ($parquetCount -eq 0) {
        Write-Host "   -> Nenhum parquet gerado; possível NL_NO_LICENSE ou janela sem trades." -ForegroundColor Red
    }
    if (-not $chunkCountOk) {
        Write-Host "   -> G-2: chunk count divergiu do esperado (ADR-023 1d/chunk)." -ForegroundColor Red
    }
    Write-Host "================================================="
    exit 1
}
